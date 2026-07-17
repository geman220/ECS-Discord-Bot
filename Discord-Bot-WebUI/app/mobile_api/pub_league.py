# app/mobile_api/pub_league.py

"""
Pub League Season Pass API (mobile)

The app-side equivalent of the web order-linking wizard
(``app/pub_league/routes.py``), reached by deep-linking the same URLs the
WooCommerce plugin and the claim emails already send:

    https://portal.ecsfc.com/pub-league/link-order?order_id=<woo_id>&token=<hmac>
    https://portal.ecsfc.com/pub-league/claim?token=<claim_token>

Those are registered as Universal Links / App Links in ``app/routes/app_links.py``,
so an install intercepts them and lands here; everyone else gets the web wizard
unchanged. The app forwards the query params it parsed off the URL verbatim.

Scope is deliberately "claim the pass that's mine":

* link-self, confirm-profile and generate-pass — the renewal path, which is the
  overwhelming majority of traffic (a returning, already-approved player buying
  next season's pass).
* Assigning a pass to someone else, searching users, and gifting via claim email
  are NOT here. An order with leftover unassigned passes returns
  ``manage_remaining_url`` and the app sends the buyer to the web wizard for
  that, rather than duplicating a multi-recipient UI that already works.

Everything routes through the same services the web wizard uses
(``PubLeagueOrderService`` / ``PlayerActivationService`` / ``ProfileUpdateService``),
so the two front-ends cannot drift on what "linked" or "active" means.

Auth: JWT, and reachable by PENDING users — ``/api/v1/pub-league/`` is on the
allowlist in ``approval_gate.py``, exactly as ``/pub-league/`` is on the web
gate's allowlist. A brand-new buyer must be able to claim the pass they paid for
before an admin has approved them; they just stay boxed in behind the hold screen
until then.
"""

import logging

from flask import jsonify, request, url_for
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.mobile_api import mobile_api_v2
from app.core.session_manager import managed_session
from app.models import (
    User, PubLeagueOrder, PubLeagueOrderLineItem, PubLeagueOrderClaim,
    PubLeagueOrderStatus,
)
from app.pub_league.membership import MEMBER, UNKNOWN, membership_status
from app.pub_league.services import (
    PubLeagueOrderService, PlayerActivationService,
    ProfileConflictService, ProfileUpdateService, ProductUrlService,
)

logger = logging.getLogger(__name__)


def _forbidden():
    """Uniform refusal for a missing/incorrect order token."""
    return jsonify({
        'success': False,
        'code': 'INVALID_ORDER_TOKEN',
        'msg': 'This link is no longer valid. Please reopen the link from your order confirmation.',
    }), 403


def _resolve_order(session, woo_order_id, token):
    """
    Verify the HMAC token, then load (or create) the order it names.

    Returns (order, error_response). Exactly one is non-None.

    The token is the authorization — it's what the WooCommerce plugin hands the
    buyer, and it's checked BEFORE the order is touched, so a guessed order id
    never reaches the database.
    """
    if not woo_order_id or not token:
        return None, (jsonify({
            'success': False,
            'msg': 'Missing order_id or token',
        }), 400)

    if not PubLeagueOrderService.verify_order_token(woo_order_id, token):
        return None, _forbidden()

    # Query through the session we commit on. Model.query binds to
    # Flask-SQLAlchemy's db.session, which is a DIFFERENT session from
    # g.db_session in this app — loading there and committing here would drop
    # the write silently.
    order = session.query(PubLeagueOrder).filter_by(woo_order_id=woo_order_id).first()

    if not order:
        # The webhook normally pre-creates the order, so this is the cold path:
        # the app opened the link before the webhook landed. Fetch and create,
        # same as the web wizard does.
        order_data = PubLeagueOrderService.fetch_order_from_woocommerce(woo_order_id)
        if not order_data:
            return None, (jsonify({
                'success': False,
                'code': 'ORDER_NOT_AVAILABLE',
                'msg': 'We could not find that order. It may not have completed, or it may have been refunded.',
            }), 404)
        order = PubLeagueOrderService.create_or_get_order(woo_order_id, order_data)

    if order.status == PubLeagueOrderStatus.NOT_STARTED.value:
        order.mark_link_clicked()
        session.commit()

    return order, None


def _line_item_payload(line_item, player, user):
    """One pass, plus whether it belongs to the caller."""
    data = line_item.to_dict()
    data['is_assigned'] = line_item.is_assigned()
    data['is_mine'] = bool(
        line_item.assigned_user_id == user.id
        or (player and line_item.assigned_player_id == player.id)
    )
    return data


@mobile_api_v2.route('/pub-league/buy-options', methods=['GET'])
@jwt_required()
def pub_league_buy_options():
    """
    What the app shows after the buy QR is scanned: season + division picker.

    Resolved live from the current Pub League season, so the SAME printed QR
    works every season — the app never hardcodes a product or a season.

    Returns:
        {
          "season_name": "2026 Fall",
          "options": [
            {"division": "classic", "name": "Classic", "available": true,
             "checkout_url": "https://portal.ecsfc.com/pub-league/buy?division=classic&src=app"},
            {"division": "premier", "name": "Premier", "available": true, "checkout_url": "..."}
          ],
          "any_available": true
        }

    The app opens `checkout_url` in a SYSTEM BROWSER SHEET (SFSafariViewController
    / Chrome Custom Tabs — NOT a WebView). That URL redirects to WooCommerce,
    which owns the presale password gate, the cart and the card form. We never
    see a card. `src=app` is what makes the post-payment redirect bounce the
    buyer back into the app rather than leaving them in the browser.
    """
    user_id = int(get_jwt_identity())
    season_name = ProductUrlService.get_current_season_name()

    with managed_session() as session:
        user = session.query(User).get(user_id)
        email = getattr(user, 'email', None) if user else None

    # The $10 ECS-membership discount is applied by WooCommerce Memberships and
    # ONLY shows for a customer signed in to weareecs.com — a separate account
    # from the portal, which nobody stays logged in to. A member who taps straight
    # through pays the full $110. 'member' | 'not_member' | 'unknown'.
    member_status = membership_status(email) if email else UNKNOWN

    options = []
    for option in ProductUrlService.get_buy_options(season_name):
        options.append({
            'division': option['division'],
            'name': option['name'],
            # available == "we could resolve a real product URL for it". It does
            # NOT mean in stock — Woo owns stock, and a sold-out product says so
            # on its own page.
            'available': bool(option['product_url']),
            'checkout_url': url_for(
                'pub_league.buy', division=option['division'], src='app', _external=True
            ),
            # Same checkout, but via the shop's sign-in first so member pricing
            # applies on arrival. Open THIS one when the buyer says they're a member.
            'checkout_url_member': url_for(
                'pub_league.buy', division=option['division'], src='app', login=1, _external=True
            ),
        })

    return jsonify({
        'success': True,
        'season_name': season_name,
        'options': options,
        'any_available': any(o['available'] for o in options),
        'membership': {
            'status': member_status,
            'is_member': member_status == MEMBER,
            # NEVER hide the member prompt on 'not_member'/'unknown'. The portal
            # email and the weareecs.com email are different accounts and often
            # differ, so a false negative is expected — and one that hid the
            # prompt would silently cost a real member $10. Show a loud banner on
            # 'member', a quiet "I have a membership" opt-in otherwise.
            'prompt': (
                "You have an ECS membership — that's $10 off, but only if you sign in "
                "to the ECS shop first."
                if member_status == MEMBER else
                "Have an ECS membership? Sign in to the ECS shop first to get $10 off."
            ),
        },
    }), 200


@mobile_api_v2.route('/pub-league/order', methods=['GET'])
@jwt_required()
def pub_league_order():
    """
    Everything the app needs to render the season-pass flow in one call.

    Query params:
        order_id: WooCommerce order id (from the deep link)
        token:    HMAC token (from the deep link)

    Returns the order and its passes, which of them are the caller's, whether the
    caller must complete a full profile or just confirm an existing one, the
    option lists to render that form with, and the caller's membership state.
    """
    woo_order_id = request.args.get('order_id', type=int)
    token = request.args.get('token', '')
    user_id = int(get_jwt_identity())

    with managed_session() as session:
        user = session.query(User).get(user_id)
        if not user:
            return jsonify({'success': False, 'msg': 'User not found'}), 404

        order, error = _resolve_order(session, woo_order_id, token)
        if error:
            return error

        player = user.player
        order_data = order.woo_order_data or {}
        line_items = list(order.line_items.all())

        # The size on the WooCommerce variation, so the profile form can prefill
        # it even if it's a size no existing player has.
        order_jersey_size = next(
            (li.jersey_size for li in line_items if li.jersey_size), ''
        )

        billing = order_data.get('billing', {}) or {}
        fallback_name = f"{(billing.get('first_name') or '').strip()} {(billing.get('last_name') or '').strip()}".strip()

        items = [_line_item_payload(li, player, user) for li in line_items]
        unassigned = [i for i in items if not i['is_assigned']]

        return jsonify({
            'success': True,
            'order': order.to_dict(),
            'line_items': items,
            'unassigned_count': len(unassigned),
            # Multi-pass orders (bought for a friend too) are handled on the web,
            # which already has search / gift-by-email. The app links the caller's
            # own pass and hands the rest off rather than half-reimplementing it.
            'manage_remaining_url': (
                url_for('pub_league.link_order', order_id=order.woo_order_id,
                        token=token, _external=True)
                if len(unassigned) > 1 else None
            ),

            # 'full' = brand-new or incomplete or stale -> force the whole profile.
            # 'compact' = complete and fresh -> one-tap confirm. Same call the web
            # wizard makes, so a renewing player sees the same thing in both.
            'profile_review_mode': (
                'full' if PlayerActivationService.profile_needs_full_review(player) else 'compact'
            ),
            'profile_prefill': ProfileUpdateService.prefill(
                player,
                fallback_name=fallback_name,
                fallback_jersey_size=order_jersey_size,
            ),
            'form_options': ProfileUpdateService.form_options(
                session, extra_jersey_sizes=[order_jersey_size]
            ),
            'conflicts': ProfileConflictService.detect_conflicts(player, order_data) if player else [],

            # Payment and membership are separate axes. A returning player is
            # approved already and goes straight to active; a new buyer ends up
            # PAID + PENDING APPROVAL and the app holds them on the wait screen.
            'is_approved': bool(user.is_approved),
            'is_current_player': bool(player and player.is_current_player),
        }), 200


@mobile_api_v2.route('/pub-league/link-self', methods=['POST'])
@jwt_required()
def pub_league_link_self():
    """
    Link one pass from the order to the caller and activate them for the season.

    Body:
        order_id:     WooCommerce order id
        token:        HMAC token
        line_item_id: which pass (from /pub-league/order)

    This is the step that sets is_current_player — payment, not approval.
    """
    data = request.get_json(silent=True) or {}
    woo_order_id = data.get('order_id')
    token = data.get('token', '')
    line_item_id = data.get('line_item_id')
    user_id = int(get_jwt_identity())

    if not line_item_id:
        return jsonify({'success': False, 'msg': 'Missing line_item_id'}), 400

    with managed_session() as session:
        user = session.query(User).get(user_id)
        if not user:
            return jsonify({'success': False, 'msg': 'User not found'}), 404

        order, error = _resolve_order(session, woo_order_id, token)
        if error:
            return error

        line_item = session.query(PubLeagueOrderLineItem).get(line_item_id)
        if not line_item or line_item.order_id != order.id:
            return jsonify({'success': False, 'msg': 'Pass not found on this order'}), 404

        player = PlayerActivationService.ensure_player_for_user(user, order.woo_order_data)

        # Capture what the response and the log lines need BEFORE any commit
        # expires these instances. Touching them afterwards re-queries the DB,
        # and on the error path that re-query raises — which would turn a
        # successfully linked pass back into a 500.
        is_approved = bool(user.is_approved)
        was_current = bool(player.is_current_player)
        li_id, p_id, u_id = line_item.id, player.id, user.id
        division, li_jersey_size = line_item.division, line_item.jersey_size

        # IDEMPOTENT. A slow first request can leave the app unsure it succeeded, so
        # it retries — and this endpoint must make that retry a clean success, not
        # an error. If the pass is ALREADY this user's, fall through to activation
        # (which is idempotent) so a first attempt that linked the pass but died
        # before activating still ends with the player active. Only refuse (409)
        # when the pass belongs to someone ELSE.
        already_mine = False
        if line_item.is_assigned():
            already_mine = (
                line_item.assigned_user_id == user.id
                or (player and line_item.assigned_player_id == player.id)
            )
            if not already_mine:
                return jsonify({
                    'success': False,
                    'code': 'ALREADY_ASSIGNED',
                    'msg': 'This pass has already been claimed by someone else.',
                }), 409
        else:
            # Claim the pass and stamp the primary user in ONE transaction.
            # Explicit in-app "link my pass" tap = a confirmed, human decision.
            if not order.primary_user_id:
                order.primary_user_id = user.id
            PubLeagueOrderService.link_pass_to_player(line_item, player, user, method='user_confirmed')

        # Snapshot the response while the link is fresh — re-reading these after
        # the (slower) activation step would re-query the DB, and a dropped
        # connection there would 500 a request whose pass is already linked.
        payload = {
            'success': True,
            'msg': 'Pass already linked to you' if already_mine else 'Pass linked',
            'line_item': line_item.to_dict(),
            'order': order.to_dict(),
        }
        if already_mine:
            payload['already_linked'] = True

        # Best-effort: the pass is committed, so an activation failure must not
        # report the claim as failed.
        #
        # jersey_size is only applied on a FRESH link — on a retry the player may
        # already have confirmed their profile with a different size, and
        # re-applying the WooCommerce size would silently revert that.
        activated = True
        try:
            PlayerActivationService.activate_player_for_league(
                player=player,
                user=user,
                division=division,
                jersey_size=None if already_mine else li_jersey_size,
            )
        except Exception as e:
            activated = False
            logger.error(
                f"Mobile: activation failed for line item {li_id} / player "
                f"{p_id} (the pass IS linked): {e}", exc_info=True
            )
            try:
                session.rollback()
            except Exception:
                pass

        logger.info(f"Mobile: linked line item {li_id} to player {p_id} (user {u_id})")

        payload['is_approved'] = is_approved
        payload['is_current_player'] = was_current or activated
        return jsonify(payload), 200


@mobile_api_v2.route('/pub-league/confirm-profile', methods=['POST'])
@jwt_required()
def pub_league_confirm_profile():
    """
    Persist the confirmed profile from the season-pass flow.

    Body: any of name, pronouns, phone, jersey_size, jersey_number,
    favorite_position, other_positions[], positions_not_to_play[],
    frequency_play_goal, expected_weeks_available, willing_to_referee,
    player_notes.

    Writes through ProfileUpdateService — identical whitelisting, position
    normalization and profile_last_updated stamp as the web wizard's
    update-profile step.
    """
    data = request.get_json(silent=True) or {}
    user_id = int(get_jwt_identity())

    with managed_session() as session:
        user = session.query(User).get(user_id)
        if not user:
            return jsonify({'success': False, 'msg': 'User not found'}), 404

        player = PlayerActivationService.ensure_player_for_user(user)
        ProfileUpdateService.apply(player, data)

        return jsonify({
            'success': True,
            'msg': 'Profile confirmed',
            'profile': ProfileUpdateService.prefill(player),
        }), 200


@mobile_api_v2.route('/pub-league/generate-pass', methods=['POST'])
@jwt_required()
def pub_league_generate_pass():
    """
    Mint the wallet pass for a linked line item and return its download URL.

    Body:
        order_id:     WooCommerce order id
        token:        HMAC token
        line_item_id: the pass to generate

    Idempotent: an already-generated pass returns the existing download URL.
    """
    data = request.get_json(silent=True) or {}
    woo_order_id = data.get('order_id')
    token = data.get('token', '')
    line_item_id = data.get('line_item_id')
    user_id = int(get_jwt_identity())

    if not line_item_id:
        return jsonify({'success': False, 'msg': 'Missing line_item_id'}), 400

    with managed_session() as session:
        order, error = _resolve_order(session, woo_order_id, token)
        if error:
            return error

        line_item = session.query(PubLeagueOrderLineItem).get(line_item_id)
        if not line_item or line_item.order_id != order.id:
            return jsonify({'success': False, 'msg': 'Pass not found on this order'}), 404

        if not line_item.assigned_player_id:
            return jsonify({
                'success': False,
                'code': 'NOT_LINKED',
                'msg': 'Link this pass to a player before generating it.',
            }), 400

        if line_item.wallet_pass_id:
            wallet_pass = line_item.wallet_pass
        else:
            try:
                wallet_pass = PubLeagueOrderService.generate_wallet_pass_for_line_item(line_item)
            except ValueError as exc:
                # Almost always "could not determine season" — the order's season
                # name doesn't match a Season row. Surface it; don't fake a pass.
                logger.error(f"Mobile pass generation failed for line item {line_item.id}: {exc}")
                return jsonify({
                    'success': False,
                    'code': 'PASS_UNAVAILABLE',
                    'msg': 'We could not build your pass yet. Please contact an admin.',
                }), 400

        logger.info(f"Mobile: wallet pass {wallet_pass.id} served for line item {line_item.id} (user {user_id})")

        return jsonify({
            'success': True,
            'wallet_pass': {
                'id': wallet_pass.id,
                'download_token': wallet_pass.download_token,
                'download_url': url_for(
                    'public_wallet.download_pass_by_token',
                    token=wallet_pass.download_token, _external=True
                ),
            },
        }), 200


@mobile_api_v2.route('/pub-league/claim/<claim_token>', methods=['GET'])
@jwt_required()
def pub_league_claim_preview(claim_token):
    """
    Preview a gifted pass before claiming it (deep link target for /pub-league/claim).

    Read-only: shows what's on offer and whether it's still valid, so the app can
    render a confirm screen rather than silently consuming a single-use token.
    """
    user_id = int(get_jwt_identity())

    with managed_session() as session:
        user = session.query(User).get(user_id)
        if not user:
            return jsonify({'success': False, 'msg': 'User not found'}), 404

        # Same session we commit on — see _resolve_order.
        claim = session.query(PubLeagueOrderClaim).filter_by(claim_token=claim_token).first()
        if not claim:
            return jsonify({
                'success': False,
                'code': 'CLAIM_INVALID',
                'msg': 'This claim link is invalid or has already been used.',
            }), 404

        if not claim.is_valid():
            session.commit()  # is_valid() flips PENDING -> EXPIRED past the deadline
            return jsonify({
                'success': False,
                'code': 'CLAIM_EXPIRED' if claim.status == 'expired' else 'CLAIM_UNAVAILABLE',
                'msg': 'This claim link has expired or the pass has already been claimed.',
                'status': claim.status,
            }), 409

        line_item = claim.line_item
        player = user.player

        return jsonify({
            'success': True,
            'claim': claim.to_dict(),
            'division': line_item.division if line_item else None,
            'jersey_size': line_item.jersey_size if line_item else None,
            'season_name': claim.order.season_name if claim.order else None,
            'sent_by': claim.created_by.username if claim.created_by else None,
            'profile_review_mode': (
                'full' if PlayerActivationService.profile_needs_full_review(player) else 'compact'
            ),
            'profile_prefill': ProfileUpdateService.prefill(player),
            'form_options': ProfileUpdateService.form_options(
                session,
                extra_jersey_sizes=[line_item.jersey_size] if line_item else None,
            ),
            'is_approved': bool(user.is_approved),
            'is_current_player': bool(player and player.is_current_player),
        }), 200


@mobile_api_v2.route('/pub-league/claim/<claim_token>', methods=['POST'])
@jwt_required()
def pub_league_claim_process(claim_token):
    """
    Claim a gifted pass: assign it to the caller, activate them, mint the pass.

    Mirrors the web POST /pub-league/claim/process. The claim token is a
    single-use, 7-day DB token — consuming it here marks it CLAIMED.
    """
    user_id = int(get_jwt_identity())

    with managed_session() as session:
        user = session.query(User).get(user_id)
        if not user:
            return jsonify({'success': False, 'msg': 'User not found'}), 404

        player = PlayerActivationService.ensure_player_for_user(user)

        # IDEMPOTENT: a slow first claim can leave the app retrying. If THIS user
        # already claimed this token, return success with the existing pass rather
        # than a 409 — the claim is single-use and the retry must not look like a
        # failure. Only a claim used by someone else (or expired) is a real error.
        existing_claim = session.query(PubLeagueOrderClaim).filter_by(claim_token=claim_token).first()
        if existing_claim and existing_claim.claimed_by_user_id == user.id and existing_claim.line_item:
            li = existing_claim.line_item
            wp = li.wallet_pass
            return jsonify({
                'success': True,
                'msg': 'Pass already claimed by you',
                'already_claimed': True,
                'line_item': li.to_dict(),
                'wallet_pass': ({
                    'id': wp.id,
                    'download_token': wp.download_token,
                    'download_url': url_for('public_wallet.download_pass_by_token',
                                            token=wp.download_token, _external=True),
                } if wp else None),
                'is_approved': bool(user.is_approved),
                'is_current_player': bool(player.is_current_player),
            }), 200

        try:
            line_item = PubLeagueOrderService.process_claim(claim_token, player, user)
        except ValueError as exc:
            return jsonify({
                'success': False,
                'code': 'CLAIM_UNAVAILABLE',
                'msg': str(exc),
            }), 409

        PlayerActivationService.activate_player_for_league(
            player=player,
            user=user,
            division=line_item.division,
            jersey_size=line_item.jersey_size,
        )

        try:
            wallet_pass = PubLeagueOrderService.generate_wallet_pass_for_line_item(line_item)
        except ValueError as exc:
            # The claim itself succeeded and the player IS active — don't fail the
            # whole call over a pass we can rebuild later from the wallet screen.
            logger.error(f"Mobile claim {claim_token[:8]}...: pass generation failed: {exc}")
            return jsonify({
                'success': True,
                'msg': 'Pass claimed. Your wallet pass will be ready shortly.',
                'line_item': line_item.to_dict(),
                'wallet_pass': None,
                'is_approved': bool(user.is_approved),
                'is_current_player': bool(player.is_current_player),
            }), 200

        logger.info(f"Mobile: claim {claim_token[:8]}... processed for player {player.id}")

        return jsonify({
            'success': True,
            'msg': 'Pass claimed',
            'line_item': line_item.to_dict(),
            'wallet_pass': {
                'id': wallet_pass.id,
                'download_token': wallet_pass.download_token,
                'download_url': url_for(
                    'public_wallet.download_pass_by_token',
                    token=wallet_pass.download_token, _external=True
                ),
            },
            'is_approved': bool(user.is_approved),
            'is_current_player': bool(player.is_current_player),
        }), 200
