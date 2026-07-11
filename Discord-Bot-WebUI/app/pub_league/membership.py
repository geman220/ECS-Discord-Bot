# app/pub_league/membership.py

"""
ECS Membership Detection

An ECS supporters-group membership gets $10 off a Pub League season pass. That
discount is applied by the **WooCommerce Memberships plugin**, keyed off the
customer being logged in to weareecs.com — the product simply shows $100 instead
of $110. We cannot apply it, replicate it, or work around it, and we deliberately
don't try: WooCommerce owns all pricing and all money.

What we CAN do is stop members silently overpaying. Nobody stays logged in to a
WordPress store they use twice a year, so without a nudge a member lands on the
product logged out and is charged the full $110. This module answers one
question — "does this person look like a member?" — so the buy screen can tell
them to sign in first.

Detection mirrors the bot's `/verify` command (`interactions.py`): an ECS
membership is a WooCommerce **product purchase** whose name looks like
"ECS Membership 2026" / "ECS Member 2026" / "ECSmember 2025", on a paid order
placed within the current membership period.

IMPORTANT — this is advisory only.
  * A "yes" makes the sign-in prompt loud and personal.
  * A "no" or an "unknown" NEVER hides the prompt entirely, only softens it.
    The portal email and the weareecs.com email can easily differ (they're
    separate accounts with separate logins), so a false negative is expected and
    must not cost a real member $10.
  * On API failure we return UNKNOWN, not False — no fake "not a member" answer.
"""

import logging
import re
from datetime import datetime

from flask import current_app

logger = logging.getLogger(__name__)


# "ECS Membership 2026", "ECS Member 2026", "ECSmember 2025" — the store's naming
# has drifted over the years, so match loosely but still require a plausible year.
_MEMBERSHIP_PATTERN = re.compile(r'ecs\s*member(?:ship)?\s*20\d{2}', re.IGNORECASE)

_PAID_STATUSES = ('processing', 'completed')

# Cache for an hour. The answer only changes when someone buys a membership, and
# a stale "not a member" just means they see the softer prompt — which still
# tells them to sign in.
_CACHE_TTL = 3600
_CACHE_PREFIX = 'ecs_membership:'

# Separate short back-off after a Woo failure. The membership call runs
# synchronously during buy-page render with a network timeout, so if Woo is down
# and members refresh, every request would block for the full timeout (no answer
# is ever cached, because it errored). This marker is NOT a cached answer — while
# it's set we skip the API and return UNKNOWN immediately, so the page stays fast
# and the sign-in prompt still shows. It expires quickly so detection resumes as
# soon as Woo recovers.
_FAIL_BACKOFF_TTL = 45
_FAIL_PREFIX = 'ecs_membership_fail:'
# Deliberately short so a flaky-Woo window can't stall the buy page for 10s/hit.
_WOO_TIMEOUT = 4

# Tri-state, so "we couldn't reach WooCommerce" is never confused with "no".
MEMBER = 'member'
NOT_MEMBER = 'not_member'
UNKNOWN = 'unknown'


def _membership_period_start() -> datetime:
    """Memberships run from Dec 1 of the previous year (same rule as the bot)."""
    return datetime(datetime.now().year - 1, 12, 1)


def _looks_like_membership_item(name: str) -> bool:
    return bool(name and _MEMBERSHIP_PATTERN.search(name))


def _woo_api():
    from woocommerce import API
    return API(
        url=current_app.config['WOO_API_URL'],
        consumer_key=current_app.config['WOO_CONSUMER_KEY'],
        consumer_secret=current_app.config['WOO_CONSUMER_SECRET'],
        version='wc/v3',
        timeout=_WOO_TIMEOUT,
    )


def _in_fail_backoff() -> bool:
    """True if a recent Woo call failed and we're briefly skipping the API."""
    try:
        from app.utils.redis_manager import get_redis_connection
        return bool(get_redis_connection().get(_FAIL_PREFIX))
    except Exception:
        return False


def _mark_fail_backoff() -> None:
    try:
        from app.utils.redis_manager import get_redis_connection
        get_redis_connection().setex(_FAIL_PREFIX, _FAIL_BACKOFF_TTL, '1')
    except Exception:
        pass


def _cache_get(email: str):
    try:
        from app.utils.redis_manager import get_redis_connection
        value = get_redis_connection().get(f"{_CACHE_PREFIX}{email.lower()}")
        if isinstance(value, bytes):
            value = value.decode('utf-8')
        return value or None
    except Exception:
        return None  # cache is an optimization, never a dependency


def _cache_set(email: str, status: str) -> None:
    # Never cache UNKNOWN — that's a transient failure, not an answer.
    if status == UNKNOWN:
        return
    try:
        from app.utils.redis_manager import get_redis_connection
        get_redis_connection().setex(f"{_CACHE_PREFIX}{email.lower()}", _CACHE_TTL, status)
    except Exception:
        pass


def membership_status(email: str) -> str:
    """
    MEMBER / NOT_MEMBER / UNKNOWN for a given email address.

    Scans that customer's recent WooCommerce orders for a membership product in
    the current period. Returns UNKNOWN (never NOT_MEMBER) if WooCommerce can't
    be reached, so a store outage can't quietly tell a member they aren't one.
    """
    if not email:
        return UNKNOWN

    cached = _cache_get(email)
    if cached in (MEMBER, NOT_MEMBER):
        return cached

    # Woo recently failed — skip the blocking call and stay fast. UNKNOWN still
    # shows the sign-in prompt, so a member isn't harmed by the back-off.
    if _in_fail_backoff():
        return UNKNOWN

    try:
        wcapi = _woo_api()

        # `search` matches billing email among other fields; we re-check the email
        # on each hit below so a fuzzy match can't grant someone else's discount.
        response = wcapi.get('orders', params={
            'search': email,
            'per_page': 50,
            'after': _membership_period_start().isoformat(),
        })
        response.raise_for_status()
        orders = response.json()

    except Exception as exc:
        # No mock answer. UNKNOWN keeps the neutral prompt on screen, which still
        # tells them to sign in — the safe failure direction. Set the short
        # back-off so a Woo outage doesn't block every subsequent buy-page render.
        logger.warning(f"Could not check ECS membership for {email}: {exc}")
        _mark_fail_backoff()
        return UNKNOWN

    target = email.strip().lower()
    for order in orders or []:
        if order.get('status') not in _PAID_STATUSES:
            continue

        billing_email = ((order.get('billing') or {}).get('email') or '').strip().lower()
        if billing_email != target:
            continue  # `search` is fuzzy; require an exact billing-email match

        for item in order.get('line_items') or []:
            if _looks_like_membership_item(item.get('name', '')):
                logger.info(f"ECS membership found for {email} (order {order.get('id')})")
                _cache_set(email, MEMBER)
                return MEMBER

    _cache_set(email, NOT_MEMBER)
    return NOT_MEMBER


def member_login_url(redirect_to: str) -> str:
    """
    Where to send someone to sign in to weareecs.com so member pricing applies.

    WordPress core honours ?redirect_to= on wp-login.php and (via wp_safe_redirect)
    will only follow a same-host target — which the product URL is — so the buyer
    lands back on the product with the member price already applied.

    Overridable via the `ecs_member_login_url` AdminConfig key, because security
    plugins sometimes rename or block wp-login.php. `{redirect}` in the template
    is replaced with the URL-encoded product URL.
    """
    from urllib.parse import quote
    from app.models import AdminConfig

    shop_url = AdminConfig.get_setting('woocommerce_shop_url', 'https://weareecs.com').rstrip('/')
    template = AdminConfig.get_setting(
        'ecs_member_login_url', '{shop}/wp-login.php?redirect_to={redirect}'
    )

    return template.replace('{shop}', shop_url).replace('{redirect}', quote(redirect_to, safe=''))
