# app/mobile_api/admin_orders.py

"""
Mobile Admin — Pub League Order Desk

The order desk on a phone: find the order someone is quoting at the door, link
their pass to the right person, unassign a mis-link, chase a claim email, and
clear the limbo a paid-but-unapproved buyer sits in.

Every handler is a thin shell: parse the body, resolve the JWT actor, call
``app/services/pub_league_order_admin.py``, jsonify. That service holds the ONLY
copy of each mutation — the web handlers in ``app/admin/pub_league_orders_routes.py``
call the same functions — so the two surfaces cannot drift. That matters more
here than most places: the reassignment path carries counter accounting
(``order.linked_passes``) and a conditional deactivation of the previous holder
that a second copy would get subtly wrong.

Gate: ``@jwt_required()`` + ``@jwt_role_required(ADMIN_ROLES)``, exactly the
web's ``['Global Admin', 'Pub League Admin']``.

⚠️ NO ``@transactional`` here. Unlike ``admin_members.py``, these service
functions own their own commits (and ``manual_link`` deliberately runs on
``g.db_session`` while ``resolve_limbo`` runs on ``db.session``) — wrapping them
would add a second, competing commit boundary. See the service docstring.

⚠️ ROUTING SPLIT: resend/cancel key on ``claim_id``; everything else keys on
``line_item_id``. That is not an inconsistency to tidy up — it is what the web
handlers take, and a claim outlives the line item it was minted for.
"""

import logging

from flask import jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.mobile_api import mobile_api_v2
from app.core import db
from app.core.session_manager import managed_session
from app.decorators import jwt_role_required
from app.services import pub_league_order_admin as order_admin

logger = logging.getLogger(__name__)

# Same pair the web order pages enforce, and the same pair the app gates its own
# UI on (canManageMemberLifecycleProvider). A narrower server gate would show
# actions that 403.
ADMIN_ROLES = ['Global Admin', 'Pub League Admin']


def _body():
    """Request body as a dict, JSON or form.

    ``get_json()`` without ``silent=True`` raises 400/415 in Flask 3 BEFORE the
    ``or {}`` can run, which turns a bodyless confirm-button POST (``refresh``
    takes ``{}``) into an unexplained error.
    """
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    if request.form:
        return request.form.to_dict()
    return {}


def _actor_id():
    return int(get_jwt_identity())


def _fail(where, exc):
    """Uniform 500 that still carries a message.

    A bodyless 404/500 is read by the client's feature-availability helper as
    "this endpoint isn't deployed", which hides the whole screen instead of
    showing the admin what went wrong.
    """
    logger.error(f"[MOBILE_API] {where} failed: {exc}", exc_info=True)
    return jsonify({'success': False, 'error': 'Something went wrong on our end.'}), 500


# ==================== reads ====================

@mobile_api_v2.route('/admin/pub-league/orders', methods=['GET'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def admin_orders_list():
    """The orders list. Query: search, status, season, division, sort, page, per_page.

    Season/division scoping is parsed by the web module's own filter reader, so
    the phone and the page can never scope to a different set of orders — which
    is how Summer Sprint orders went invisible on the web page for a fortnight
    (a hardcoded ``league_type='Pub League'``).

    ``per_page`` is capped server-side and the cap is stated in every response.
    """
    try:
        with managed_session() as session:
            payload, status = order_admin.list_orders(
                session,
                page=request.args.get('page', 1, type=int),
                per_page=request.args.get(
                    'per_page', order_admin.ORDERS_PER_PAGE_DEFAULT, type=int),
            )
        return jsonify(payload), status
    except Exception as exc:
        return _fail('orders list', exc)


@mobile_api_v2.route('/admin/pub-league/orders/search-players', methods=['GET'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def admin_orders_search_players():
    """Players a pass can be linked to. Query: q, suggest_for.

    ``already_has_pass`` on each result drives a "link anyway?" confirm in the
    app — a WARNING, not a block. Someone legitimately holding two passes (they
    bought for a partner who never claimed) still has to be linkable.

    Declared BEFORE the ``<int:order_id>`` routes so the literal path wins; the
    int converter would not match 'search-players' anyway, but the ordering
    makes that independent of luck.
    """
    try:
        with managed_session() as session:
            payload, status = order_admin.search_players(
                session,
                query=request.args.get('q', ''),
                suggest_for=request.args.get('suggest_for', ''),
            )
        return jsonify(payload), status
    except Exception as exc:
        return _fail('order player search', exc)


@mobile_api_v2.route('/admin/pub-league/orders/<int:order_id>', methods=['GET'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def admin_order_detail(order_id: int):
    """One order with its line items and claims.

    Each line item carries ``claim_id`` when it has one — the app only renders
    its Resend / Cancel buttons for line items that do.
    """
    try:
        with managed_session() as session:
            payload, status = order_admin.get_order(session, order_id)
        return jsonify(payload), status
    except Exception as exc:
        return _fail(f'order detail {order_id}', exc)


# ==================== line-item mutations (keyed on line_item_id) ====================

@mobile_api_v2.route('/admin/pub-league/orders/<int:order_id>/manual-link',
                     methods=['POST'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def admin_order_manual_link(order_id: int):
    """Link (or re-link) a pass. Body: {"line_item_id": 9, "player_id": 908}.

    The order in the URL is checked against the line item's own order, so a
    client that pairs the wrong two ids gets a 404 rather than a silent
    cross-order write.
    """
    data = _body()
    try:
        payload, status = order_admin.manual_link(
            line_item_id=data.get('line_item_id'),
            player_id=data.get('player_id'),
            actor_id=_actor_id(),
            order_id=order_id,
        )
        return jsonify(payload), status
    except Exception as exc:
        try:
            from flask import g
            getattr(g, 'db_session', db.session).rollback()
        except Exception:
            pass
        return _fail(f'manual link on order {order_id}', exc)


@mobile_api_v2.route('/admin/pub-league/orders/<int:order_id>/unassign',
                     methods=['POST'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def admin_order_unassign(order_id: int):
    """Return a pass to the pool. Body: {"line_item_id": 9}.

    Deactivates the previous holder for the season UNLESS they still hold
    another pass — the response says which happened.
    """
    data = _body()
    try:
        payload, status = order_admin.unassign_pass(
            line_item_id=data.get('line_item_id'),
            actor_id=_actor_id(), order_id=order_id)
        return jsonify(payload), status
    except Exception as exc:
        db.session.rollback()
        return _fail(f'unassign on order {order_id}', exc)


# ==================== claim mutations (keyed on claim_id) ====================

@mobile_api_v2.route('/admin/pub-league/orders/<int:order_id>/resend-claim',
                     methods=['POST'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def admin_order_resend_claim(order_id: int):
    """Resend a pending claim email. Body: {"claim_id": 55} — NOT line_item_id."""
    data = _body()
    try:
        payload, status = order_admin.resend_claim(
            claim_id=data.get('claim_id'), actor_id=_actor_id(), order_id=order_id)
        return jsonify(payload), status
    except Exception as exc:
        return _fail(f'resend claim on order {order_id}', exc)


@mobile_api_v2.route('/admin/pub-league/orders/<int:order_id>/cancel-claim',
                     methods=['POST'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def admin_order_cancel_claim(order_id: int):
    """Cancel a pending claim. Body: {"claim_id": 55} — NOT line_item_id."""
    data = _body()
    try:
        payload, status = order_admin.cancel_claim(
            claim_id=data.get('claim_id'), actor_id=_actor_id(), order_id=order_id)
        return jsonify(payload), status
    except Exception as exc:
        db.session.rollback()
        return _fail(f'cancel claim on order {order_id}', exc)


# ==================== order-level ====================

@mobile_api_v2.route('/admin/pub-league/orders/<int:order_id>/refresh',
                     methods=['POST'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def admin_order_refresh(order_id: int):
    """Re-fetch from WooCommerce. Body: {} (bodyless is fine).

    ⚠️ This calls out to WooCommerce over HTTP inside the request. It is the
    only way to see a refund issued after purchase, but it is also the slowest
    endpoint here — the client should treat it as a deliberate, explicit action,
    not something to poll.
    """
    try:
        payload, status = order_admin.refresh_order(
            order_id=order_id, actor_id=_actor_id())
        return jsonify(payload), status
    except Exception as exc:
        db.session.rollback()
        return _fail(f'refresh order {order_id}', exc)


# ==================== limbo ====================

@mobile_api_v2.route('/admin/pub-league/limbo', methods=['POST'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def admin_pub_league_limbo():
    """What's inconsistent about this person now that they hold a pass.

    Body: {"player_id": 908, "line_item_id": 9} — line_item_id optional (it is
    what resolves the division, and therefore whether an approve action can be
    offered at all).

    WRITES NOTHING. It reports the misalignment and never prescribes an outcome
    — buying a pass and being cleared to play are separate axes on purpose.
    """
    data = _body()
    try:
        payload, status = order_admin.player_limbo(
            player_id=data.get('player_id'),
            line_item_id=data.get('line_item_id'))
        return jsonify(payload), status
    except Exception as exc:
        return _fail('player limbo', exc)


@mobile_api_v2.route('/admin/pub-league/limbo/resolve', methods=['POST'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def admin_pub_league_limbo_resolve():
    """Apply ONLY the ticked limbo fixes.

    Body: {"player_id": 908, "actions": ["approve"], "approve_value": "premier"}

    ``actions`` is honoured exactly — nothing more is applied, and an empty list
    is a successful no-op ("none" must not be harder than the other choices).
    ``approve_value`` comes from the matching action's ``value`` in the limbo
    response; it is re-validated server-side against the approvals vocabulary,
    never trusted as round-tripped.

    Returns ``discord_sync_queued`` when an approval moved Discord roles.
    """
    data = _body()
    try:
        payload, status = order_admin.resolve_limbo(
            player_id=data.get('player_id'),
            actions=data.get('actions'),
            approve_value=data.get('approve_value'),
            actor_id=_actor_id(),
        )
        return jsonify(payload), status
    except Exception as exc:
        db.session.rollback()
        return _fail('resolve limbo', exc)
