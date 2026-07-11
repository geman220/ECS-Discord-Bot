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

from flask import (
    current_app, flash, g, jsonify, redirect, render_template,
    request, session, url_for
)
from flask_login import current_user, login_required

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
from .services import (
    PubLeagueOrderService, PlayerActivationService,
    RoleSyncService, ProfileConflictService, UserSearchService
)

logger = logging.getLogger(__name__)

# Whitelists derived once from the canonical form option lists so the
# profile-confirmation endpoint only ever persists known-good values.
_ALLOWED_POSITIONS = {value for value, _ in soccer_positions}
_ALLOWED_GOAL_FREQUENCY = {value for value, _ in goal_frequency_choices}
_ALLOWED_AVAILABILITY = {value for value, _ in availability_choices}
_ALLOWED_PRONOUNS = {value for value, _ in pronoun_choices}
_ALLOWED_REFEREE = {value for value, _ in willing_to_referee_choices}


def _parse_pg_array(value):
    """Parse a Postgres-style '{a,b}' text column into a clean list."""
    if not value:
        return []
    return [v for v in value.strip('{}').split(',') if v]


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

    # Store in session for post-login redirect
    session['pub_league_order_id'] = order_id
    session['pub_league_token'] = token

    # Try to verify and fetch order
    try:
        # First check if order already exists in our system
        existing_order = PubLeagueOrder.find_by_woo_order_id(order_id)

        if existing_order:
            order = existing_order
            order_data = existing_order.woo_order_data
            # Transition from NOT_STARTED to PENDING if this is first link click
            if order.status == PubLeagueOrderStatus.NOT_STARTED.value:
                order.mark_link_clicked()
                db.session.commit()
                logger.info(f"Order {order_id} transitioned from NOT_STARTED to PENDING")
        else:
            # Verify token
            if not PubLeagueOrderService.verify_order_token(order_id, token):
                flash('Invalid or expired order verification. Please contact support.', 'error')
                return redirect(url_for('main.index'))

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
        'favorite_position': player.favorite_position if player else '',
        'other_positions': _parse_pg_array(player.other_positions) if player else [],
        'positions_not_to_play': _parse_pg_array(player.positions_not_to_play) if player else [],
        'frequency_play_goal': player.frequency_play_goal if player else '',
        'expected_weeks_available': player.expected_weeks_available if player else '',
        'willing_to_referee': player.willing_to_referee if player else '',
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
        # Check for existing order
        existing_order = PubLeagueOrder.find_by_woo_order_id(order_id)
        if existing_order:
            # Transition from NOT_STARTED to PENDING if this is first link click
            if existing_order.status == PubLeagueOrderStatus.NOT_STARTED.value:
                existing_order.mark_link_clicked()
                db.session.commit()
            return jsonify({
                'success': True,
                'order': existing_order.to_dict(),
                'already_exists': True
            })

        # Verify token
        if not PubLeagueOrderService.verify_order_token(order_id, token):
            return jsonify({'success': False, 'message': 'Invalid verification token'}), 403

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

        line_item = session.query(PubLeagueOrderLineItem).get(line_item_id)
        if not line_item or line_item.order_id != order_id:
            return jsonify({'success': False, 'message': 'Line item not found'}), 404

        if line_item.is_assigned():
            return jsonify({'success': False, 'message': 'This pass has already been assigned'}), 400

        # Get the actual, session-bound User model.
        user = session.query(User).get(safe_current_user.id)
        if not user:
            return jsonify({'success': False, 'message': 'Account not found'}), 400

        # Never dead-end a first-timer: create a minimal Player if they don't
        # have one yet, then continue straight into assignment.
        player = PlayerActivationService.ensure_player_for_user(user, order.woo_order_data)

        # Link the pass
        PubLeagueOrderService.link_pass_to_player(line_item, player, user)

        # Activate player for the division (set is_current_player, sync roles)
        PlayerActivationService.activate_player_for_league(
            player=player,
            user=user,
            division=line_item.division,
            jersey_size=line_item.jersey_size
        )

        # Set primary user if not set
        if not order.primary_user_id:
            order.primary_user_id = safe_current_user.id
            session.commit()

        return jsonify({
            'success': True,
            'message': 'Pass linked successfully',
            'line_item': line_item.to_dict(),
            'order': order.to_dict(),
            # Membership (is_approved) is separate from payment; surface both
            # so the final screen can reflect the real state.
            'is_approved': bool(getattr(user, 'is_approved', False)),
            'is_current_player': bool(player.is_current_player),
        })

    except Exception as e:
        logger.error(f"Error linking pass: {e}")
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

    try:
        session = get_db_session()

        player = safe_current_user.player
        if not player:
            return jsonify({'success': False, 'message': 'No player profile found'}), 400

        # Get division from line item
        division = None
        if line_item_id:
            line_item = session.query(PubLeagueOrderLineItem).get(line_item_id)
            if line_item:
                division = line_item.division

        if not division:
            # Try to get from order
            order = session.query(PubLeagueOrder).get(order_id)
            if order:
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

        # --- Identity & Contact ---
        name = (data.get('name') or '').strip()
        if name:
            player.name = name[:100]

        pronouns = (data.get('pronouns') or '').strip()
        if pronouns in _ALLOWED_PRONOUNS:
            player.pronouns = pronouns

        # Phone uses the encrypting setter; only write when a value is given so
        # we don't wipe an existing number on an accidental blank.
        phone = (data.get('phone') or '').strip()
        if phone:
            player.phone = phone[:20]

        # Jersey size mirrors the profile form, which accepts any distinct size
        # in use (not a fixed list). Guard only on column length (String(10)).
        jersey_size = (data.get('jersey_size') or '').strip()
        if jersey_size and len(jersey_size) <= 10:
            player.jersey_size = jersey_size

        jersey_number_raw = data.get('jersey_number')
        if jersey_number_raw not in (None, ''):
            try:
                _jn = int(jersey_number_raw)
                # Range-guard: the column is a 4-byte int; an out-of-range value
                # only fails at commit() and would then lose the WHOLE profile
                # update. Jersey numbers are 0-99.
                if 0 <= _jn <= 99:
                    player.jersey_number = _jn
            except (TypeError, ValueError):
                pass  # ignore non-numeric jersey numbers

        # --- Playing ---
        favorite_position = (data.get('favorite_position') or '').strip()
        if favorite_position in _ALLOWED_POSITIONS:
            player.favorite_position = favorite_position

        other_positions = data.get('other_positions')
        if isinstance(other_positions, list):
            cleaned = [p for p in other_positions if p in _ALLOWED_POSITIONS]
            player.other_positions = ('{' + ','.join(cleaned) + '}') if cleaned else None

        positions_not_to_play = data.get('positions_not_to_play')
        if isinstance(positions_not_to_play, list):
            cleaned = [p for p in positions_not_to_play if p in _ALLOWED_POSITIONS]
            player.positions_not_to_play = ('{' + ','.join(cleaned) + '}') if cleaned else None

        frequency_play_goal = (data.get('frequency_play_goal') or '').strip()
        if frequency_play_goal in _ALLOWED_GOAL_FREQUENCY:
            player.frequency_play_goal = frequency_play_goal

        # --- Availability ---
        expected_weeks_available = (data.get('expected_weeks_available') or '').strip()
        if expected_weeks_available in _ALLOWED_AVAILABILITY:
            player.expected_weeks_available = expected_weeks_available

        willing_to_referee = (data.get('willing_to_referee') or '').strip()
        if willing_to_referee in _ALLOWED_REFEREE:
            player.willing_to_referee = willing_to_referee

        # Stamp the review so the 5-month "please update" alert resets.
        player.profile_last_updated = datetime.utcnow()

        session.commit()

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

    Returns:
        Order status and line item states
    """
    order = PubLeagueOrder.find_by_woo_order_id(order_id)
    if not order:
        return jsonify({'success': False, 'message': 'Order not found'}), 404

    return jsonify({
        'success': True,
        'order': order.to_dict()
    })
