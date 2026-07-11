# app/mobile_api/approval_gate.py

"""
Mobile Approval Gate

The mobile counterpart to the web's ``app/init/access_gating.py``.

A not-yet-approved user CAN sign in on mobile — they have to, or a brand-new
buyer who happens to have the app installed would be dead-ended with a pass they
paid for and no way to link it. Instead they get a real JWT carrying
``approved: false``, and this gate confines them to the same small surface the
web gate allows: sign in, claim/link the pass they bought, fill in their profile,
see their wallet pass, and sit on a "pending approval" hold screen.

Everything else returns 403 ``ACCOUNT_NOT_APPROVED``.

Why a single before_request instead of a decorator on each route: the web gate's
allowlist (``access_gating.py``) exempts ``/api`` wholesale — the JSON/mobile API
is trusted to enforce its own state. So the moment we start issuing tokens to
unapproved users, EVERY ``/api`` endpoint is reachable by them unless something
stops it centrally. A per-route decorator would mean remembering to add it to
~250 endpoints and every future one. This is the choke point.

Two deliberate details:

* **Legacy tokens.** Tokens minted before this change carry no ``approved``
  claim. They were only ever issued to approved users (the old code hard-403'd
  everyone else), so a missing claim is treated as approved. No forced re-login.

* **Stale-deny recheck.** A token minted while pending still says
  ``approved: false`` after an admin approves the user, and access tokens live
  30 days. Rather than stranding a freshly-approved member behind their own
  cached token, a false claim triggers a cheap DB read of ``users.is_approved``
  — so approval takes effect on the next request, not the next token refresh.
  Only pending users pay for that query, and they are a tiny population.
"""

import logging

from flask import request, jsonify
from flask_jwt_extended import verify_jwt_in_request, get_jwt, get_jwt_identity

logger = logging.getLogger(__name__)


# Paths an unapproved user may still reach. Matched with a SEGMENT BOUNDARY
# (`path == p` or `path startswith p + '/'`), never a bare string prefix — a bare
# prefix would exempt any sibling route sharing the string, e.g. '/api/v1/feedback'
# would also open a future '/api/v1/feedback-export', and '/api/v1/app_config'
# already covers '/api/v1/app_config/build'. That would be a silent authz bypass.
#
# Keep this in step with _ALLOW_PREFIXES / _ALLOW_ENDPOINTS in
# app/init/access_gating.py — the two gates should confine the same surface.
_PENDING_ALLOWED_PATHS = (
    # --- auth: they must be able to sign in, refresh and sign out ---
    '/api/v1/login',
    '/api/v1/verify_2fa',
    '/api/v1/refresh_token',
    '/api/v1/logout',
    '/api/v1/get_discord_auth_url',
    '/api/v1/discord_callback',
    # --- the hold screen needs to know who they are and what state they're in ---
    '/api/v1/user_profile',
    # --- the whole point: buy -> link/claim the pass -> confirm profile.
    #     (trailing slash => matches the whole /pub-league/* subtree) ---
    '/api/v1/pub-league',
    # --- profile completion (a brand-new buyer onboards rather than confirms) ---
    '/api/v1/onboarding',
    '/api/v1/player/update',
    # --- their wallet pass (they paid for it; they get it before approval) ---
    '/api/v1/membership',
    # --- account settings, incl. password / delete / data export.
    #     Bare /account too, so the DELETE-account route is reachable. ---
    '/api/v1/account',
    # --- reference data the onboarding / profile-confirm screens read ---
    '/api/v1/positions',
    '/api/v1/leagues',
    '/api/v1/seasons',
    # --- push registration, so the "you've been approved" notification lands ---
    '/api/v1/notifications',
    # --- let a stuck user shout for help ---
    '/api/v1/feedback',
    # --- unauthenticated infra endpoints (force-update checks, health) ---
    '/api/v1/app_config',
    '/api/v1/version',
    '/api/v1/health',
)


def _is_allowed_path(path: str) -> bool:
    """Segment-boundary allowlist match — never a bare string prefix."""
    for p in _PENDING_ALLOWED_PATHS:
        if path == p or path.startswith(p + '/'):
            return True
    return False


def _is_approved_in_db(user_id: int) -> bool:
    """Authoritative re-read, so approval isn't held hostage by a stale token."""
    from app.core.session_manager import managed_session
    from app.models import User

    try:
        with managed_session() as session:
            user = session.query(User).get(user_id)
            return bool(user and user.is_approved)
    except Exception as exc:
        # Fail OPEN, exactly like the web gate: a DB hiccup must never lock out
        # the entire member base. The pending population is small; the blast
        # radius of failing closed here is everyone.
        logger.warning(f"Approval gate could not verify user {user_id}, allowing: {exc}")
        return True


def register_approval_gate(app):
    """Install the mobile approval gate for all /api/ traffic on ``app``."""

    @app.before_request
    def _mobile_approval_gate():
        path = request.path or ''
        if not path.startswith('/api/'):
            return None  # web routes are handled by app/init/access_gating.py

        if _is_allowed_path(path):
            return None

        # Read the JWT if there is one. No token (or an expired/garbage one) is
        # not our problem — the route's own @jwt_required will answer 401.
        try:
            verify_jwt_in_request(optional=True)
            claims = get_jwt()
        except Exception:
            return None

        if not claims:
            return None

        # Missing claim == legacy token == approved (see module docstring).
        if claims.get('approved', True):
            return None

        try:
            user_id = int(get_jwt_identity())
        except (TypeError, ValueError):
            return None

        if _is_approved_in_db(user_id):
            return None

        logger.info(f"Approval gate blocked pending user {user_id} from {path}")
        return jsonify({
            'msg': "Your account is pending admin approval. You'll get access once an admin approves your membership.",
            'code': 'ACCOUNT_NOT_APPROVED',
        }), 403

    logger.info("Mobile approval gate registered for /api/ routes")
