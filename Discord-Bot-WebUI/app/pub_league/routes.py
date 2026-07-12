# app/pub_league/routes.py

"""
Pub League Order Linking Routes

This module provides routes for the Pub League order linking wizard:
- /link-order: Main wizard page
- /link-order/* API endpoints: AJAX handlers for wizard steps
- /claim: Claim link processing
"""

import logging
from datetime import datetime, timedelta
from functools import wraps
from urllib.parse import quote

from flask import (
    current_app, flash, g, jsonify, make_response, redirect, render_template,
    request, session, url_for
)
from flask_login import current_user, login_required
from markupsafe import escape

from app.core import db
from app.utils.user_helpers import safe_current_user
from app.models import (
    Player, Season, User,
    PubLeagueOrder, PubLeagueOrderLineItem, PubLeagueOrderClaim,
    PubLeagueOrderStatus, PubLeagueLineItemStatus, PubLeagueClaimStatus
)
from app.forms import (
    soccer_positions, goal_frequency_choices, availability_choices,
    pronoun_choices, willing_to_referee_choices
)
from . import pub_league_bp
from .membership import MEMBER, UNKNOWN, member_login_url, membership_status
from .services import (
    PubLeagueOrderService, PlayerActivationService,
    RoleSyncService, ProfileConflictService, ProfileUpdateService,
    ProductUrlService, UserSearchService
)

logger = logging.getLogger(__name__)

# Marks a checkout that was started from inside the app. Set on /pub-league/buy,
# read on /pub-league/link-order to bounce the buyer back into the app after
# WooCommerce redirects them here.
#
# Why a cookie and not a query param: WooCommerce owns the checkout and the
# thank-you redirect, and its plugin builds that redirect URL itself — we can't
# thread a param through it without changing the plugin. But the whole round trip
# starts and ends on portal.ecsfc.com, so a first-party cookie survives the hop
# out to weareecs.com and back. SameSite=Lax is required and sufficient: Lax
# cookies ARE sent on a top-level GET navigation from another site, which is
# exactly what Woo's redirect is.
_APP_CHECKOUT_COOKIE = 'pl_buy_src'
_APP_CHECKOUT_MAX_AGE = 4 * 60 * 60  # a purchase + payment, generously


# Position parsing/normalization lives in the single source of truth.
from app.constants.positions import normalize_position, parse_positions


def _get_jersey_size_choices(session):
    """Distinct jersey sizes actually in use.

    Mirrors the player profile form (app/players.py) which builds its size
    dropdown from ``distinct(Player.jersey_size)`` rather than a hardcoded list.
    Building the link-order step the same way keeps the two option sets in sync
    so a size that shows on /players/profile also shows here.
    """
    rows = session.query(Player.jersey_size).distinct().all()
    return sorted({r[0] for r in rows if r[0]})


def get_db_session():
    """Get the current database session."""
    return getattr(g, 'db_session', db.session)


def _order_token_ok(order: PubLeagueOrder, supplied_token: str = None) -> bool:
    """
    Authorize a mutating action against a specific order.

    Possession of the order's HMAC token IS the authorization here — it's what
    the WooCommerce plugin hands the buyer and the only thing that ties a
    caller to an order they paid for. Without this check, `order_id` is just a
    small integer: any logged-in user could POST a guessed id and link an
    unassigned pass to themselves for free.

    The token is verified against the *target* order's woo_order_id, so a
    session token stashed for one order can't be replayed against another.
    Web callers fall back to the session copy stashed by `link_order()`;
    the app (which has no cookie session) sends it explicitly in the body.
    """
    token = supplied_token or session.get('pub_league_token')
    if not token:
        return False
    return PubLeagueOrderService.verify_order_token(order.woo_order_id, token)


def _forbidden():
    """Uniform refusal for a missing/incorrect order token."""
    return jsonify({
        'success': False,
        'message': 'This link is no longer valid. Please reopen the link from your order confirmation.'
    }), 403


def _app_deep_link(order_id: int, token: str) -> str:
    """Custom-scheme URL that hands an order off to the native app."""
    return (
        f"ecs-fc-scheme://link-order?order_id={quote(str(order_id))}"
        f"&token={quote(token)}"
    )


def _bounce_to_app(deep_link: str, web_fallback_url: str):
    """
    Hand off to the app, with a visible way back to the web flow.

    Used when WooCommerce lands the buyer back on us and we know (from the
    checkout cookie) that they started in the app. A meta-refresh to the custom
    scheme is what gets us out of the in-app browser sheet — an https Universal
    Link will NOT fire here, because iOS never triggers one on a redirect.

    Always renders the escape hatch: if the scheme doesn't resolve (app was
    uninstalled mid-purchase, or the sheet blocks it) the buyer must not be
    stranded on a blank page holding a pass they just paid for.
    """
    safe_deep_link = escape(deep_link)
    safe_web = escape(web_fallback_url)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta http-equiv="refresh" content="0; url={safe_deep_link}">
    <title>Returning to the ECS FC app...</title>
    <style>
        body {{ font-family: system-ui, -apple-system, sans-serif; padding: 2rem;
                text-align: center; color: #1f2937; }}
        a {{ display: inline-block; margin-top: 1rem; color: #213e96; }}
    </style>
</head>
<body>
    <p>Payment received. Returning to the ECS FC app to set up your pass...</p>
    <p><a href="{safe_deep_link}">Tap here if the app doesn't open.</a></p>
    <p><a href="{safe_web}">Or finish in your browser instead.</a></p>
</body>
</html>"""

    response = make_response(html, 200)
    response.headers['Content-Type'] = 'text/html; charset=utf-8'
    response.headers['Cache-Control'] = 'no-store'
    # One-shot: consume the marker so a later visit to this same URL (e.g. the
    # buyer reopening the link from their email) doesn't bounce them again.
    response.delete_cookie(_APP_CHECKOUT_COOKIE, path='/')
    return response


def _set_app_checkout_cookie(response):
    """Mark this checkout as app-originated so we can bounce them home after Woo."""
    response.set_cookie(
        _APP_CHECKOUT_COOKIE, 'app',
        max_age=_APP_CHECKOUT_MAX_AGE,
        secure=True,
        httponly=True,
        samesite='Lax',  # MUST be Lax, not Strict — Woo's redirect back to us is a
                         # cross-site top-level GET, and Strict would drop the cookie.
        path='/',
    )
    return response


@pub_league_bp.route('/buy')
def buy():
    """
    Entry point for buying a season pass. Send people HERE, not to WooCommerce.

    Query params:
        division: 'classic' | 'premier'. OMIT IT to show the division picker —
                  that's what the single printed QR does.
        src:      'app' when the native app opened this.

    ONE QR, forever. The URL carries no season and no product id: the division
    picker and the product URL are both resolved at scan time from whichever Pub
    League season is currently is_current. Scan it this season and it lands on
    the 2026-fall product; scan the SAME code next season and it lands on
    2027-spring. Nothing to reprint at rollover.

    As a Universal Link this opens the app when installed and the browser when
    not. Either way we hand off to the real WooCommerce product page — Woo owns
    the cart, the presale password gate, the card form and the money. We never
    see a card and never take a payment; we are a launcher and a return handler.
    """
    division = (request.args.get('division') or '').strip().lower()
    from_app = request.args.get('src') == 'app'

    # No division -> show the picker. This is the single-QR path.
    if division not in ('classic', 'premier'):
        options = ProductUrlService.get_buy_options()

        # The $10 ECS-membership discount is applied by WooCommerce Memberships
        # and ONLY shows for a customer logged in to weareecs.com. Nobody stays
        # logged in to a store they use twice a year, so a member who just taps
        # through gets charged the full $110. Warn them here, before Woo.
        member_status = UNKNOWN
        if current_user.is_authenticated and getattr(current_user, 'email', None):
            member_status = membership_status(current_user.email)

        # Route the division links through the shop sign-in when we KNOW they're a
        # member, or when they self-declared via ?member=1. The self-declare path
        # is a plain link reload (see the template), so it works with NO JavaScript
        # — the group we couldn't auto-detect is exactly the group that most needs
        # the discount, so it must not depend on JS running.
        self_declared_member = request.args.get('member') == '1'
        route_via_login = (member_status == MEMBER) or self_declared_member

        response = make_response(render_template(
            'pub_league/buy_flowbite.html',
            options=options,
            season_name=ProductUrlService.get_current_season_name(),
            from_app=from_app,
            # Nothing on sale at all -> say so rather than showing dead buttons.
            any_available=any(o['product_url'] for o in options),
            member_status=member_status,
            is_member=(member_status == MEMBER),
            route_via_login=route_via_login,
            self_declared_member=self_declared_member,
        ))
        # Set the marker HERE too: the buyer will click through to
        # /buy?division=X from this page, but if they instead deep-link straight
        # to a division we still want the return hop to find the cookie.
        return _set_app_checkout_cookie(response) if from_app else response

    product_url = ProductUrlService.get_product_url(division.capitalize())
    if not product_url:
        # No configured slug AND no current season to derive one from. Don't dump
        # the buyer on a 404 at the shop.
        logger.error(f"No WooCommerce product URL resolved for division '{division}'")
        flash('Passes are not on sale yet. Check the Discord for the on-sale time.', 'info')
        return redirect(url_for('main.index'))

    # ?login=1 -> sign in to weareecs.com FIRST, then land on the product with
    # member pricing already applied. WordPress honours redirect_to on wp-login.
    destination = product_url
    if request.args.get('login') == '1':
        destination = member_login_url(product_url)

    logger.info(
        f"Pub League buy: division={division} src={'app' if from_app else 'web'} "
        f"login_first={request.args.get('login') == '1'}"
    )

    response = redirect(destination)
    return _set_app_checkout_cookie(response) if from_app else response


# ============================================================================
# Main Wizard Route
# ============================================================================

@pub_league_bp.route('/link-order')
def link_order():
    """
    Main order linking wizard page.

    Query params:
        order_id: WooCommerce order ID (required)
        token: Verification token (required)

    The wizard handles:
    1. Order verification
    2. Discord login (if not authenticated)
    3. Pass assignment (self/search/claim)
    4. Conflict resolution
    5. Profile update (if stale)
    6. Wallet pass download
    """
    order_id = request.args.get('order_id', type=int)
    token = request.args.get('token', '')

    if not order_id or not token:
        flash('Invalid order link. Please use the link from your WooCommerce order.', 'error')
        return redirect(url_for('main.index'))

    # Verify the token BEFORE anything else — including before stashing it in
    # the session. The webhook pre-creates every paid order, so "order already
    # exists" is the normal path; verifying only in the not-found branch meant
    # the token was effectively never checked, and this page would render another
    # customer's name, email and passes to anyone who guessed an order id.
    if not PubLeagueOrderService.verify_order_token(order_id, token):
        flash('Invalid or expired order verification. Please contact support.', 'error')
        return redirect(url_for('main.index'))

    # Store in session so the post-login redirect and the wizard's XHR calls
    # (which don't re-send it) can re-present it.
    session['pub_league_order_id'] = order_id
    session['pub_league_token'] = token

    # If this purchase started in the app, hand the buyer straight back to it.
    # WooCommerce 302s them here after payment, and a redirect can never trigger
    # a Universal Link — so without this the app-initiated buyer would silently
    # finish in a browser sheet instead of the app they started in.
    # ?stay=1 forces the web wizard (the "finish in your browser" escape hatch).
    if request.cookies.get(_APP_CHECKOUT_COOKIE) == 'app' and request.args.get('stay') != '1':
        web_fallback = url_for(
            'pub_league.link_order', order_id=order_id, token=token, stay=1, _external=True
        )
        return _bounce_to_app(_app_deep_link(order_id, token), web_fallback)

    # Try to fetch order
    try:
        # First check if order already exists in our system
        existing_order = PubLeagueOrder.find_by_woo_order_id(order_id)

        if existing_order:
            order = existing_order
            order_data = existing_order.woo_order_data
            # Transition from NOT_STARTED to PENDING if this is first link click
            if order.status == PubLeagueOrderStatus.NOT_STARTED.value:
                order.mark_link_clicked()
                # Commit the session the order actually lives on. This was
                # db.session.commit(), which commits a DIFFERENT session that knows
                # nothing about this change — the classic silently-discarded write.
                get_db_session().commit()
                logger.info(f"Order {order_id} transitioned from NOT_STARTED to PENDING")
        else:
            # Fetch from WooCommerce
            order_data = PubLeagueOrderService.fetch_order_from_woocommerce(order_id)
            if not order_data:
                flash('Could not fetch order details. The order may not be complete or may have been refunded.', 'error')
                return redirect(url_for('main.index'))

            # Create order in our system
            order = PubLeagueOrderService.create_or_get_order(order_id, order_data)

    except Exception as e:
        logger.error(f"Error processing order {order_id}: {e}")
        flash('An error occurred processing your order. Please try again or contact support.', 'error')
        return redirect(url_for('main.index'))

    # Determine initial step
    if not current_user.is_authenticated:
        initial_step = 2  # Login step
    elif order.is_fully_linked():
        initial_step = 6  # Download step (all passes already linked)
    else:
        initial_step = 3  # Assignment step

    # Get line items for display
    line_items = list(order.line_items.all())
    unassigned_items = [item for item in line_items if not item.is_assigned()]

    # Logged-in user context -------------------------------------------------
    player = safe_current_user.player if current_user.is_authenticated else None

    # Membership (is_approved) is admin-granted and separate from payment.
    # A brand-new buyer ends up PAID (is_current_player) but PENDING APPROVAL.
    is_approved = bool(current_user.is_authenticated and getattr(current_user, 'is_approved', False))
    is_current_player = bool(player and player.is_current_player)

    # Check for profile conflicts if logged in
    conflicts = []
    if player:
        conflicts = ProfileConflictService.detect_conflicts(player, order_data or {})

    # The confirm-your-profile step is ALWAYS part of the authenticated path
    # now. If the profile is complete AND fresh we show a compact one-tap
    # confirm; otherwise we force the full multi-section review.
    profile_needs_update = current_user.is_authenticated
    profile_review_mode = 'full'
    if player:
        profile_review_mode = 'full' if PlayerActivationService.profile_needs_full_review(player) else 'compact'

    # Prefill values for the profile-confirmation step. Fall back to the
    # order billing name for a first-timer who has no Player yet.
    fallback_name = ''
    if order_data:
        billing = order_data.get('billing', {}) or {}
        fallback_name = f"{(billing.get('first_name') or '').strip()} {(billing.get('last_name') or '').strip()}".strip()

    # Jersey sizes: same source as the player profile form, plus whatever size
    # this order carries (from the WooCommerce variation) so it can prefill even
    # if no existing player has that size yet.
    jersey_size_choices = _get_jersey_size_choices(get_db_session())
    order_jersey_size = next(
        (li.jersey_size for li in line_items if getattr(li, 'jersey_size', None)), ''
    )
    if order_jersey_size and order_jersey_size not in jersey_size_choices:
        jersey_size_choices = sorted(set(jersey_size_choices) | {order_jersey_size})

    profile_prefill = {
        'name': (player.name if player else '') or fallback_name,
        'pronouns': player.pronouns if player else '',
        'phone': (player.phone if player else '') or '',
        # Prefer the saved profile size; fall back to the size on the order.
        'jersey_size': (player.jersey_size if player else '') or order_jersey_size,
        'jersey_number': player.jersey_number if player else '',
        'favorite_position': normalize_position(player.favorite_position) if player else '',
        'other_positions': parse_positions(player.other_positions) if player else [],
        'positions_not_to_play': parse_positions(player.positions_not_to_play) if player else [],
        'frequency_play_goal': player.frequency_play_goal if player else '',
        'expected_weeks_available': player.expected_weeks_available if player else '',
        'willing_to_referee': player.willing_to_referee if player else '',
        'player_notes': (player.player_notes if player else '') or '',
    }

    # Line items that belong to THIS user. The final step needs this so it can
    # offer the user's own pass download on a fresh page load (an already-linked
    # order renders no in-page assignment cards, so the client-side "assigned"
    # list is empty and would otherwise show the gift/"recipients" message).
    my_line_item_ids = []
    if current_user.is_authenticated:
        uid = safe_current_user.id
        pid = player.id if player else None
        my_line_item_ids = [
            li.id for li in line_items
            if li.assigned_user_id == uid or (pid and li.assigned_player_id == pid)
        ]

    return render_template(
        'pub_league/link_order_flowbite.html',
        order=order,
        order_data=order_data,
        line_items=line_items,
        unassigned_items=unassigned_items,
        my_line_item_ids=my_line_item_ids,
        initial_step=initial_step,
        conflicts=conflicts,
        profile_needs_update=profile_needs_update,
        profile_review_mode=profile_review_mode,
        profile_prefill=profile_prefill,
        is_approved=is_approved,
        is_current_player=is_current_player,
        # Option lists for the profile-confirmation selects
        jersey_size_choices=jersey_size_choices,
        soccer_positions=soccer_positions,
        goal_frequency_choices=goal_frequency_choices,
        availability_choices=availability_choices,
        pronoun_choices=pronoun_choices,
        willing_to_referee_choices=willing_to_referee_choices,
    )


# ============================================================================
# Wizard API Endpoints
# ============================================================================

@pub_league_bp.route('/link-order/verify', methods=['POST'])
def verify_order():
    """
    Verify order token and fetch order details.

    Request JSON:
        order_id: WooCommerce order ID
        token: Verification token

    Returns:
        Order data and line items
    """
    data = request.get_json() or {}
    order_id = data.get('order_id')
    token = data.get('token')

    if not order_id or not token:
        return jsonify({'success': False, 'message': 'Missing order_id or token'}), 400

    try:
        # Verify the token FIRST, always. The webhook pre-creates every paid
        # order, so the "order already exists" branch is the normal path — only
        # checking the token when the order is missing meant it was effectively
        # never checked, and this endpoint would hand out order contents
        # (customer name, email, line items) to anyone with an order id.
        if not PubLeagueOrderService.verify_order_token(order_id, token):
            return jsonify({'success': False, 'message': 'Invalid verification token'}), 403

        # Check for existing order
        existing_order = PubLeagueOrder.find_by_woo_order_id(order_id)
        if existing_order:
            # Transition from NOT_STARTED to PENDING if this is first link click
            if existing_order.status == PubLeagueOrderStatus.NOT_STARTED.value:
                existing_order.mark_link_clicked()
                # See the note in the sibling route: commit the order's own session.
                get_db_session().commit()
            return jsonify({
                'success': True,
                'order': existing_order.to_dict(),
                'already_exists': True
            })

        # Fetch from WooCommerce
        order_data = PubLeagueOrderService.fetch_order_from_woocommerce(order_id)
        if not order_data:
            return jsonify({'success': False, 'message': 'Could not fetch order from WooCommerce'}), 404

        # Create order
        order = PubLeagueOrderService.create_or_get_order(order_id, order_data)

        return jsonify({
            'success': True,
            'order': order.to_dict(),
            'already_exists': False
        })

    except Exception as e:
        logger.error(f"Error verifying order {order_id}: {e}")
        return jsonify({'success': False, 'message': 'An error occurred'}), 500


@pub_league_bp.route('/link-order/link-self', methods=['POST'])
@login_required
def link_self():
    """
    Link a pass to the current logged-in user.

    Request JSON:
        order_id: PubLeagueOrder ID
        line_item_id: PubLeagueOrderLineItem ID to assign

    Returns:
        Updated line item data
    """
    data = request.get_json() or {}
    order_id = data.get('order_id')
    line_item_id = data.get('line_item_id')

    if not order_id or not line_item_id:
        return jsonify({'success': False, 'message': 'Missing order_id or line_item_id'}), 400

    try:
        session = get_db_session()

        # Get order and line item
        order = session.query(PubLeagueOrder).get(order_id)
        if not order:
            return jsonify({'success': False, 'message': 'Order not found'}), 404

        if not _order_token_ok(order, data.get('token')):
            return _forbidden()

        line_item = session.query(PubLeagueOrderLineItem).get(line_item_id)
        if not line_item or line_item.order_id != order_id:
            return jsonify({'success': False, 'message': 'Line item not found'}), 404

        # Get the actual, session-bound User model.
        user = session.query(User).get(safe_current_user.id)
        if not user:
            return jsonify({'success': False, 'message': 'Account not found'}), 400

        # Never dead-end a first-timer: create a minimal Player if they don't
        # have one yet, then continue straight into assignment.
        player = PlayerActivationService.ensure_player_for_user(user, order.woo_order_data)

        # Capture everything we need for the response and for logging BEFORE any
        # commit below. A commit expires these instances, so touching them
        # afterwards re-queries the DB — and on the error path that re-query
        # would itself raise, turning a linked pass back into a 500.
        is_approved = bool(getattr(user, 'is_approved', False))
        was_current = bool(player.is_current_player)
        li_id, p_id, division = line_item.id, player.id, line_item.division
        li_jersey_size = line_item.jersey_size

        # IDEMPOTENT, like the mobile endpoint. The link commits before the
        # slower activation step, so a request that dies in activation leaves the
        # pass linked to this very user — and the retry must land on success, not
        # "already assigned". Only refuse when the pass belongs to someone ELSE.
        already_mine = False
        if line_item.is_assigned():
            already_mine = (
                line_item.assigned_user_id == user.id
                or line_item.assigned_player_id == player.id
            )
            if not already_mine:
                return jsonify({
                    'success': False,
                    'message': 'This pass has already been claimed by someone else.',
                }), 409
        else:
            # Claim the pass and stamp the primary user in ONE transaction, so a
            # failure downstream can't leave the order half-linked.
            if not order.primary_user_id:
                order.primary_user_id = user.id
            PubLeagueOrderService.link_pass_to_player(line_item, player, user)

        # Snapshot the response now, while the link is fresh. Everything below is
        # best-effort and re-reading these afterwards would re-query the DB — a
        # slow or dropped connection at that point used to 500 a request whose
        # pass was already linked, which is what produced "Error" on the first
        # attempt and "already assigned" on the retry.
        payload = {
            'success': True,
            'message': 'Pass linked successfully',
            'line_item': line_item.to_dict(),
            'order': order.to_dict(),
        }

        # Activate player for the division (set is_current_player, sync roles).
        # The pass is already committed; a failure here must not tell the user
        # their claim failed. It is idempotent, so the retry path re-runs it.
        #
        # jersey_size is only applied on a FRESH link. On the retry path the
        # player may since have confirmed their profile and changed size, and
        # re-applying the size off the WooCommerce line item would silently
        # revert that edit.
        activated = True
        try:
            PlayerActivationService.activate_player_for_league(
                player=player,
                user=user,
                division=division,
                jersey_size=None if already_mine else li_jersey_size
            )
        except Exception as e:
            activated = False
            logger.error(
                f"Activation failed for line item {li_id} / player {p_id} "
                f"(the pass IS linked; player stays non-current until retried): {e}",
                exc_info=True
            )
            try:
                session.rollback()
            except Exception:
                pass

        # Membership (is_approved) is separate from payment; surface both
        # so the final screen can reflect the real state.
        payload['is_approved'] = is_approved
        payload['is_current_player'] = was_current or activated
        if already_mine:
            payload['already_linked'] = True
        return jsonify(payload)

    except Exception as e:
        logger.error(f"Error linking pass: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'An error occurred'}), 500


@pub_league_bp.route('/link-order/search-users')
@login_required
def search_users():
    """
    Search for users to assign passes to.

    Query params:
        q: Search query (name, email, or Discord username)

    Returns:
        List of matching users
    """
    query = request.args.get('q', '').strip()

    if len(query) < 2:
        return jsonify({'success': True, 'users': []})

    try:
        results = UserSearchService.search_users(query, limit=10)
        return jsonify({'success': True, 'users': results})

    except Exception as e:
        logger.error(f"Error searching users: {e}")
        return jsonify({'success': False, 'message': 'Search failed'}), 500


@pub_league_bp.route('/link-order/assign', methods=['POST'])
@login_required
def assign_to_user():
    """
    Assign a pass to an existing user.

    Request JSON:
        order_id: PubLeagueOrder ID
        line_item_id: PubLeagueOrderLineItem ID
        player_id: Player ID to assign to

    Returns:
        Updated line item data
    """
    data = request.get_json() or {}
    order_id = data.get('order_id')
    line_item_id = data.get('line_item_id')
    player_id = data.get('player_id')

    if not all([order_id, line_item_id, player_id]):
        return jsonify({'success': False, 'message': 'Missing required fields'}), 400

    try:
        session = get_db_session()

        # Get entities
        order = session.query(PubLeagueOrder).get(order_id)
        line_item = session.query(PubLeagueOrderLineItem).get(line_item_id)
        player = session.query(Player).get(player_id)

        if not order or not line_item or not player:
            return jsonify({'success': False, 'message': 'Not found'}), 404

        if not _order_token_ok(order, data.get('token')):
            return _forbidden()

        if line_item.order_id != order_id:
            return jsonify({'success': False, 'message': 'Line item does not belong to order'}), 400

        if line_item.is_assigned():
            return jsonify({'success': False, 'message': 'This pass has already been assigned'}), 400

        # Get user associated with player
        user = player.user if player.user_id else None

        # Link the pass
        PubLeagueOrderService.link_pass_to_player(line_item, player, user)

        # Activate player for the division (set is_current_player, sync roles)
        # Only activates roles if user exists and is approved
        if user:
            PlayerActivationService.activate_player_for_league(
                player=player,
                user=user,
                division=line_item.division,
                jersey_size=line_item.jersey_size
            )

        return jsonify({
            'success': True,
            'message': f'Pass assigned to {player.name}',
            'line_item': line_item.to_dict(),
            'order': order.to_dict()
        })

    except Exception as e:
        logger.error(f"Error assigning pass: {e}")
        return jsonify({'success': False, 'message': 'An error occurred'}), 500


@pub_league_bp.route('/link-order/send-claim', methods=['POST'])
@login_required
def send_claim():
    """
    Create a claim link for an unassigned pass.

    Request JSON:
        order_id: PubLeagueOrder ID
        line_item_id: PubLeagueOrderLineItem ID
        recipient_email: Optional email to send claim to
        recipient_name: Optional name of recipient

    Returns:
        Claim link data
    """
    data = request.get_json() or {}
    order_id = data.get('order_id')
    line_item_id = data.get('line_item_id')
    recipient_email = data.get('recipient_email', '').strip() or None
    recipient_name = data.get('recipient_name', '').strip() or None

    if not order_id or not line_item_id:
        return jsonify({'success': False, 'message': 'Missing required fields'}), 400

    try:
        session = get_db_session()

        order = session.query(PubLeagueOrder).get(order_id)
        line_item = session.query(PubLeagueOrderLineItem).get(line_item_id)

        if not order or not line_item:
            return jsonify({'success': False, 'message': 'Not found'}), 404

        if not _order_token_ok(order, data.get('token')):
            return _forbidden()

        if line_item.order_id != order.id:
            return jsonify({'success': False, 'message': 'Line item does not belong to order'}), 400

        if line_item.is_assigned():
            return jsonify({'success': False, 'message': 'This pass has already been assigned'}), 400

        # Create claim link
        claim = PubLeagueOrderService.create_claim_link(
            order=order,
            line_item=line_item,
            created_by_user=current_user,
            recipient_email=recipient_email,
            recipient_name=recipient_name
        )

        # Build claim URL
        claim_url = url_for('pub_league.claim', token=claim.claim_token, _external=True)

        # Send email if recipient_email provided
        email_sent = False
        if recipient_email:
            from .email_helpers import send_claim_link_email
            sender_name = safe_current_user.player.name if safe_current_user.player else safe_current_user.username
            email_sent = send_claim_link_email(
                recipient_email=recipient_email,
                recipient_name=recipient_name,
                claim_token=claim.claim_token,
                division=line_item.division or 'Pub League',
                sender_name=sender_name,
                expires_at=claim.expires_at
            )
            if email_sent:
                claim.email_sent_at = datetime.utcnow()
                session.commit()

        return jsonify({
            'success': True,
            'message': 'Claim link created' + (' and email sent' if email_sent else ''),
            'claim': claim.to_dict(),
            'claim_url': claim_url,
            'email_sent': email_sent,
            'order': order.to_dict()
        })

    except Exception as e:
        logger.error(f"Error creating claim link: {e}")
        return jsonify({'success': False, 'message': 'An error occurred'}), 500


@pub_league_bp.route('/link-order/resolve-conflicts', methods=['POST'])
@login_required
def resolve_conflicts():
    """
    Resolve profile conflicts between order and portal data.

    Request JSON:
        resolutions: List of resolution decisions
            - field: Field name
            - use_order_value: Boolean (true to update from order)
            - order_value: Value to use if use_order_value is true

    Returns:
        Success status
    """
    data = request.get_json() or {}
    resolutions = data.get('resolutions', [])

    if not resolutions:
        return jsonify({'success': True, 'message': 'No resolutions to apply'})

    try:
        player = safe_current_user.player
        if not player:
            return jsonify({'success': False, 'message': 'No player profile found'}), 400

        ProfileConflictService.apply_resolutions(player, resolutions)

        return jsonify({
            'success': True,
            'message': 'Profile updated successfully'
        })

    except Exception as e:
        logger.error(f"Error resolving conflicts: {e}")
        return jsonify({'success': False, 'message': 'An error occurred'}), 500


@pub_league_bp.route('/link-order/activate', methods=['POST'])
@login_required
def activate_player():
    """
    Activate player for the Pub League division.

    Request JSON:
        order_id: PubLeagueOrder ID
        line_item_id: PubLeagueOrderLineItem ID (for division info)
        jersey_size: Optional jersey size to update

    Returns:
        Success status
    """
    data = request.get_json() or {}
    order_id = data.get('order_id')
    line_item_id = data.get('line_item_id')
    jersey_size = data.get('jersey_size')

    if not order_id:
        return jsonify({'success': False, 'message': 'Missing order_id'}), 400

    try:
        session = get_db_session()

        # Activation is what grants a paid season (is_current_player), so it
        # carries the same token gate as linking — an order_id alone is not
        # authorization to activate yourself.
        order = session.query(PubLeagueOrder).get(order_id)
        if not order:
            return jsonify({'success': False, 'message': 'Order not found'}), 404

        if not _order_token_ok(order, data.get('token')):
            return _forbidden()

        player = safe_current_user.player
        if not player:
            return jsonify({'success': False, 'message': 'No player profile found'}), 400

        # Get division from line item (must belong to this order)
        division = None
        if line_item_id:
            line_item = session.query(PubLeagueOrderLineItem).get(line_item_id)
            if line_item and line_item.order_id == order.id:
                division = line_item.division

        if not division:
            first_item = order.line_items.first()
            if first_item:
                division = first_item.division

        if not division:
            return jsonify({'success': False, 'message': 'Could not determine division'}), 400

        # Get the actual User model (not the proxy)
        user = player.user

        # Activate player
        PlayerActivationService.activate_player_for_league(
            player=player,
            user=user,
            division=division,
            jersey_size=jersey_size
        )

        return jsonify({
            'success': True,
            'message': f'Activated for {division} division',
            'division': division,
            'is_approved': bool(user and getattr(user, 'is_approved', False)),
            'is_current_player': bool(player.is_current_player),
        })

    except Exception as e:
        logger.error(f"Error activating player: {e}")
        return jsonify({'success': False, 'message': 'An error occurred'}), 500


@pub_league_bp.route('/link-order/update-profile', methods=['POST'])
@login_required
def update_profile():
    """
    Persist the player's confirmed profile from the multi-section review step.

    Accepts (all optional): name, pronouns, phone, jersey_size, jersey_number,
    favorite_position, other_positions[], positions_not_to_play[],
    frequency_play_goal, expected_weeks_available, willing_to_referee.

    All select values are whitelisted against the canonical form option lists.
    Stamps profile_last_updated so the review-due logic resets.

    Returns:
        {success: bool}
    """
    data = request.get_json() or {}

    try:
        session = get_db_session()

        # Never dead-end: create a Player if this user somehow has none.
        user = session.query(User).get(safe_current_user.id)
        if not user:
            return jsonify({'success': False, 'message': 'Account not found'}), 400
        player = PlayerActivationService.ensure_player_for_user(user)

        # Whitelisting, position normalization and the profile_last_updated
        # stamp all live in the service so the app's confirm-profile endpoint
        # writes byte-identical data.
        ProfileUpdateService.apply(player, data)

        return jsonify({
            'success': True,
            'message': 'Profile updated successfully'
        })

    except Exception as e:
        logger.error(f"Error updating profile: {e}")
        return jsonify({'success': False, 'message': 'An error occurred'}), 500


@pub_league_bp.route('/link-order/generate-pass', methods=['POST'])
@login_required
def generate_pass():
    """
    Generate wallet pass for an assigned line item.

    Request JSON:
        line_item_id: PubLeagueOrderLineItem ID

    Returns:
        Wallet pass data with download links
    """
    data = request.get_json() or {}
    line_item_id = data.get('line_item_id')

    if not line_item_id:
        return jsonify({'success': False, 'message': 'Missing line_item_id'}), 400

    try:
        session = get_db_session()

        line_item = session.query(PubLeagueOrderLineItem).get(line_item_id)
        if not line_item:
            return jsonify({'success': False, 'message': 'Line item not found'}), 404

        # A wallet pass is a bearer credential (its download URL is public), so
        # minting one needs the order token — otherwise any logged-in user could
        # walk line_item ids and mint passes for other people's orders.
        if not _order_token_ok(line_item.order, data.get('token')):
            return _forbidden()

        # Check if pass already created
        if line_item.wallet_pass_id:
            wallet_pass = line_item.wallet_pass
            return jsonify({
                'success': True,
                'wallet_pass': {
                    'id': wallet_pass.id,
                    'download_token': wallet_pass.download_token,
                    'download_url': url_for('public_wallet.download_pass_by_token', token=wallet_pass.download_token, _external=True)
                }
            })

        # Generate pass
        wallet_pass = PubLeagueOrderService.generate_wallet_pass_for_line_item(line_item)

        return jsonify({
            'success': True,
            'wallet_pass': {
                'id': wallet_pass.id,
                'download_token': wallet_pass.download_token,
                'download_url': url_for('public_wallet.download_pass_by_token', token=wallet_pass.download_token, _external=True)
            }
        })

    except ValueError as e:
        return jsonify({'success': False, 'message': 'Internal Server Error'}), 400
    except Exception as e:
        logger.error(f"Error generating pass: {e}")
        return jsonify({'success': False, 'message': 'An error occurred'}), 500


# ============================================================================
# Claim Link Routes
# ============================================================================

@pub_league_bp.route('/claim')
def claim():
    """
    Claim link landing page.

    Query params:
        token: Claim token

    Handles:
    1. Token validation
    2. Discord login (if not authenticated)
    3. Claim processing
    4. Pass generation
    """
    token = request.args.get('token', '')

    if not token:
        flash('Invalid claim link.', 'error')
        return redirect(url_for('main.index'))

    # Store token in session for post-login
    session['pub_league_claim_token'] = token

    # Find claim
    claim = PubLeagueOrderClaim.find_by_token(token)
    if not claim:
        flash('This claim link is invalid or has already been used.', 'error')
        return redirect(url_for('main.index'))

    if not claim.is_valid():
        if claim.status == PubLeagueClaimStatus.EXPIRED.value:
            flash('This claim link has expired. Please contact the person who purchased your pass.', 'error')
        elif claim.status == PubLeagueClaimStatus.CLAIMED.value:
            flash('This pass has already been claimed.', 'info')
        else:
            flash('This claim link is no longer valid.', 'error')
        return redirect(url_for('main.index'))

    # Get line item and order info
    line_item = claim.line_item
    order = claim.order

    return render_template(
        'pub_league/claim_flowbite.html',
        claim=claim,
        line_item=line_item,
        order=order,
        is_authenticated=current_user.is_authenticated
    )


@pub_league_bp.route('/claim/process', methods=['POST'])
@login_required
def process_claim():
    """
    Process a claim after user is logged in.

    Request JSON:
        claim_token: The claim token

    Returns:
        Claim result and pass data
    """
    data = request.get_json() or {}
    claim_token = data.get('claim_token') or session.get('pub_league_claim_token')

    if not claim_token:
        return jsonify({'success': False, 'message': 'Missing claim token'}), 400

    try:
        db_session = get_db_session()

        # Never dead-end a first-time claimer: create a minimal Player if
        # they don't have one, then proceed.
        user = db_session.query(User).get(safe_current_user.id)
        if not user:
            return jsonify({'success': False, 'message': 'Account not found'}), 400
        player = PlayerActivationService.ensure_player_for_user(user)

        # Process the claim
        line_item = PubLeagueOrderService.process_claim(claim_token, player, user)

        # Activate player for the division
        PlayerActivationService.activate_player_for_league(
            player=player,
            user=user,
            division=line_item.division,
            jersey_size=line_item.jersey_size
        )

        # Generate wallet pass
        wallet_pass = PubLeagueOrderService.generate_wallet_pass_for_line_item(line_item)

        # Clear session
        session.pop('pub_league_claim_token', None)

        return jsonify({
            'success': True,
            'message': 'Pass claimed successfully!',
            'line_item': line_item.to_dict(),
            'is_approved': bool(getattr(user, 'is_approved', False)),
            'is_current_player': bool(player.is_current_player),
            'wallet_pass': {
                'id': wallet_pass.id,
                'download_token': wallet_pass.download_token,
                'download_url': url_for('public_wallet.download_pass_by_token', token=wallet_pass.download_token, _external=True)
            }
        })

    except ValueError as e:
        return jsonify({'success': False, 'message': 'Internal Server Error'}), 400
    except Exception as e:
        logger.error(f"Error processing claim: {e}")
        return jsonify({'success': False, 'message': 'An error occurred'}), 500


# ============================================================================
# Status/Info Routes
# ============================================================================

@pub_league_bp.route('/order/<int:order_id>/status')
def order_status(order_id):
    """
    Get order linking status.

    Used for polling/checking status.

    Query params:
        token: The order's HMAC token (required)

    Returns:
        Order status and line item states
    """
    order = PubLeagueOrder.find_by_woo_order_id(order_id)
    if not order:
        return jsonify({'success': False, 'message': 'Order not found'}), 404

    # This is an unauthenticated endpoint that returns customer name/email and
    # every pass on the order, so it needs the token — an order id alone is a
    # guessable integer.
    if not _order_token_ok(order, request.args.get('token')):
        return _forbidden()

    return jsonify({
        'success': True,
        'order': order.to_dict()
    })
