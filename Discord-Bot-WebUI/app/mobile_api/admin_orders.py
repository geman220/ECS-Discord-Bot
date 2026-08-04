# app/mobile_api/admin_orders.py

"""
Mobile Admin — Pub League Order Desk

The order desk on a phone: find the order someone is quoting at the door, link
their pass to the right person, unassign a mis-link, chase a claim email, and
clear the limbo a paid-but-unapproved buyer sits in.

Also the Player Hub's Orders section: ``GET /admin/players/<id>/orders`` answers
"what did this person buy, and which pass do they hold?" by ID — the desk's
free-text search matches customer_name, so it returns same-named strangers, and
presenting THAT as an order history is how a pass gets linked to the wrong
person.

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


@mobile_api_v2.route('/admin/players/<int:player_id>/orders', methods=['GET'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def admin_player_orders(player_id: int):
    """Every order this person is on, as BUYER or as pass HOLDER.

    Resolved by id, NOT by the desk's free-text search. That search matches
    customer_name / customer_email / woo_order_id, so it will happily return a
    different human with the same name — presenting that as "their orders" is
    how a pass gets linked to the wrong person.

    Each order carries ``relationship``: 'buyer' | 'holder' | 'buyer_and_holder'.
    "She paid for her partner" and "she holds this pass" lead to opposite actions
    at the desk, so the client must be able to tell them apart.

    ⚠️ NOT season-scoped, unlike the desk list. On one person, last season's
    order is exactly what an admin is asking about.

    A person with no orders is 200 with ``orders: []`` — never a 404, which the
    client would read as "this endpoint isn't deployed" and hide the section.
    """
    try:
        with managed_session() as session:
            payload, status = order_admin.player_orders(session, player_id)
        return jsonify(payload), status
    except Exception as exc:
        return _fail(f'player orders {player_id}', exc)


@mobile_api_v2.route('/admin/pub-league/orders/import', methods=['POST'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def admin_order_import():
    """Pull one WooCommerce order in by its number. Body: {"woo_order_id": "10421"}.

    The recovery path for a sale the webhook never ingested at all. Idempotent —
    ``imported`` says whether a row was actually created, so a re-run is not
    reported as an import.

    Declared BEFORE the ``<int:order_id>`` routes so the literal path wins.

    ⚠️ Calls out to WooCommerce over HTTP inside the request.
    """
    data = _body()
    try:
        payload, status = order_admin.import_order(
            woo_order_id=data.get('woo_order_id'), actor_id=_actor_id())
        return jsonify(payload), status
    except Exception as exc:
        try:
            from flask import g
            getattr(g, 'db_session', db.session).rollback()
        except Exception:
            pass
        return _fail('import order', exc)


@mobile_api_v2.route('/admin/pub-league/orders/scan-missing', methods=['POST'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def admin_orders_scan_missing():
    """Paid Woo orders with league passes that are NOT here. Body: {"days": 180}.

    READ-ONLY. It writes nothing and imports nothing — the admin recognises the
    names and imports deliberately, because a scan that silently bulk-created
    orders would be very hard to undo if the parser were ever wrong.

    ``days`` is clamped to 1-730. ``truncated`` means the page ceiling was hit
    and there may be more further back; the client MUST show it, or "nothing
    missing" reads as all-clear when we simply stopped looking.

    ⚠️ Several WooCommerce round trips inside one request — the slowest endpoint
    in this module. Explicit action, never a poll.
    """
    data = _body()
    try:
        payload, status = order_admin.scan_missing_orders(
            days=data.get('days'), actor_id=_actor_id())
        return jsonify(payload), status
    except Exception as exc:
        logger.error(f"[MOBILE_API] scan missing orders failed: {exc}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Could not reach WooCommerce or read its response.',
        }), 502


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


@mobile_api_v2.route('/admin/pub-league/orders/<int:order_id>/line-item',
                     methods=['POST'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def admin_order_update_line_item(order_id: int):
    """Change a line item's division / jersey size.

    Body: {"line_item_id": 901, "division": "Classic", "jersey_size": "M"}

    Both fields are OPTIONAL and the two empty values mean different things:
    omitting a key leaves that field alone, sending ``""`` clears it. A client
    that sends ``""`` for "unchanged" will wipe the value.

    ``division`` is validated against the program REGISTRY, not a hardcoded
    Classic/Premier pair — a 400 lists the valid names in ``valid_divisions``.

    A no-op is ``200 {"success": true, "changed": false, "message": "No changes
    made"}``. The app must not report that as a change.
    """
    data = _body()
    try:
        payload, status = order_admin.update_line_item(
            line_item_id=data.get('line_item_id'),
            # Passed through untouched: `None` (absent) and `''` (clear) are
            # different instructions and the service depends on telling them apart.
            division=data.get('division'),
            jersey_size=data.get('jersey_size'),
            actor_id=_actor_id(),
            order_id=order_id,
        )
        return jsonify(payload), status
    except Exception as exc:
        db.session.rollback()
        return _fail(f'update line item on order {order_id}', exc)


@mobile_api_v2.route('/admin/pub-league/orders/<int:order_id>', methods=['DELETE'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def admin_order_delete(order_id: int):
    """Delete an order and ALL its line items and claims. NO UNDO.

    Body: {"confirm_order_number": "10421"} — REQUIRED, and it must match this
    order's WooCommerce number. A mistap on a phone must not be able to destroy
    an order, so the number is typed back rather than merely tapped through.

    Refuses with 409 while any line item still holds a live wallet pass:
    deleting the row behind a pass leaves it sitting in someone's Apple Wallet
    with nothing backing it. Unassign first.

    On success ``deleted`` states what actually went, so an admin who expected
    one pass and destroyed three finds out now.
    """
    data = _body()
    try:
        payload, status = order_admin.delete_order(
            order_id=order_id,
            actor_id=_actor_id(),
            confirm_order_number=data.get('confirm_order_number'),
            # The web page runs a two-step Swal confirm; a phone gets the typed
            # echo instead.
            require_confirm=True,
        )
        return jsonify(payload), status
    except Exception as exc:
        db.session.rollback()
        return _fail(f'delete order {order_id}', exc)


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
