# app/services/pub_league_order_admin.py

"""
Pub League Order Admin Service — the one copy of every order-desk mutation.

The order desk (link a pass to the right person, unassign a mis-linked one,
resend a claim email, clear the limbo a paid-but-unapproved buyer sits in) lived
entirely as route bodies inside ``app/admin/pub_league_orders_routes.py``,
reachable only by a session-cookie POST. An admin standing at the door on a
Thursday night had to open the website.

So the bodies moved here and both surfaces call the SAME function:

    web    app/admin/pub_league_orders_routes.py   (@login_required + @role_required)
    mobile app/mobile_api/admin_orders.py          (@jwt_required + @jwt_role_required)

Each function returns ``(payload_dict, http_status)``; the caller only jsonifies.
That matters more here than almost anywhere else in the app, because these
mutations carry accounting that is easy to get subtly wrong on a second copy:
the reassignment path must NOT double-count ``order.linked_passes``, and the
previous holder has to be deactivated only when they hold no OTHER pass this
season.

⚠️ SESSION — these functions are NOT uniform, and that is deliberate, copied
verbatim from the routes they replace:

* ``manual_link`` works on ``g.db_session``, because
  ``link_pass_to_player`` / ``activate_player_for_league`` commit that session.
  Loading the line item on ``db.session`` was a real bug: the admin saw
  "linked", and a refresh showed the pass still unassigned.
* ``resolve_limbo`` works on ``db.session`` and commits it, because
  ``apply_approval`` mutates ``db.session`` throughout.

Mixing the two is the silently-discarded-write bug (see
reference_two_sessions_lost_writes). Callers must therefore NOT wrap these in
``@transactional`` expecting it to be the commit — each function commits what it
owns.

⚠️ ERRORS: these return ``{'success': False, 'error': …}`` — the shape the web
JS already reads. Every 404 carries that key, because the mobile client treats a
BODYLESS 404 as "this endpoint isn't deployed" and hides the entire screen; a
404 with a body is shown to the admin as a real error.
"""

import logging
from datetime import datetime

from sqlalchemy import or_, func
from sqlalchemy.orm import joinedload

from app.core import db
from app.models import (
    PubLeagueOrder, PubLeagueOrderLineItem, PubLeagueOrderClaim,
    PubLeagueLineItemStatus, PubLeagueClaimStatus,
    Player, Season,
)

logger = logging.getLogger(__name__)


# Server-side ceiling, stated in every list response. A silent cap reads as
# "that's every order", which is exactly the wrong thing to believe at a gate.
ORDERS_PER_PAGE_DEFAULT = 25
ORDERS_PER_PAGE_CAP = 100


def _ok(**extra):
    payload = {'success': True}
    payload.update(extra)
    return payload, 200


def _err(message, status=400, **extra):
    payload = {'success': False, 'error': message}
    payload.update(extra)
    return payload, status


def _request_session():
    """The per-request session, falling back to db.session outside a request."""
    from flask import g
    return getattr(g, 'db_session', db.session)


# ---------------------------------------------------------------------------
# serialization
# ---------------------------------------------------------------------------

def _money_str(amount, currency=None):
    """Numeric -> '$85.00', or None when there is no amount to state.

    Returns None rather than '$0.00' for a missing value: the revenue columns
    are added by a hand-run migration (sql_pub_league_order_revenue.sql), so
    "we don't know" is a real state and must not be rendered as "free".
    """
    if amount is None:
        return None
    from app.admin.pub_league_orders_routes import _CURRENCY_SYMBOLS
    symbol = _CURRENCY_SYMBOLS.get((currency or 'USD').upper(), '')
    try:
        return f'{symbol}{amount:,.2f}'
    except (TypeError, ValueError):
        return None


def _serialize_line_item(li, claim=None):
    """One line item, in the shape the app renders.

    ⚠️ ``quantity`` is ALWAYS 1. Line items are quantity-EXPANDED at import —
    ordering two Premier passes creates two rows — so a quantity here would be a
    second, disagreeing count. It is emitted as a constant purely because the
    client's contract has the field.

    ``claim_id`` is what the app keys its Resend / Cancel buttons on (those two
    endpoints take a claim_id, everything else takes a line_item_id), so it is
    included whenever the line item carries one — without it the buttons never
    render at all.
    """
    player = li.assigned_player
    return {
        'id': li.id,
        'name': li.product_name,
        'division': li.division,
        'quantity': 1,
        'jersey_size': li.jersey_size,
        'status': li.status,
        'player_id': li.assigned_player_id,
        'player_name': player.name if player else None,
        'link_method': li.link_method,
        'link_confirmed_at': (li.link_confirmed_at.isoformat()
                              if li.link_confirmed_at else None),
        'wallet_pass_id': li.wallet_pass_id,
        'claim_id': li.claim_id,
        'claim_email': claim.recipient_email if claim else None,
        'claim_status': claim.status if claim else None,
    }


def _serialize_order(order, line_items=None, claims_by_id=None):
    """One order. ``order_number`` is the WooCommerce id — the number a buyer
    quotes at the door, which is NOT this row's primary key."""
    if line_items is None:
        line_items = order.line_items.all()
    claims_by_id = claims_by_id or {}
    return {
        'id': order.id,
        'order_number': str(order.woo_order_id) if order.woo_order_id else None,
        'customer_name': order.customer_name,
        'customer_email': order.customer_email,
        'status': order.status,
        'season_name': order.season_name,
        'total_passes': order.total_passes,
        'linked_passes': order.linked_passes,
        'created_at': order.created_at.isoformat() if order.created_at else None,
        'total': _money_str(getattr(order, 'order_total', None),
                            getattr(order, 'currency', None)),
        'line_items': [_serialize_line_item(li, claims_by_id.get(li.claim_id))
                       for li in line_items],
    }


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------

def list_orders(session, page=1, per_page=ORDERS_PER_PAGE_DEFAULT):
    """The orders list as JSON, on the SAME filter semantics as the web page.

    Filters (status, search, season, division, sort) are parsed by
    ``_parse_order_filters`` — the web module's own reader — rather than
    re-derived, so the phone and the screen can never scope to a different set
    of orders. That includes the default season scope, which spans every
    pub-league-like program's current season plus genuine orphans; a
    ``filter_by(league_type='Pub League')`` here would silently drop every
    Summer Sprint order (see project_summer_sprint_orders_invisible).

    ⚠️ Requires a request context — ``_parse_order_filters`` reads
    ``request.args`` directly, which is exactly why no ``args`` mapping is taken
    here: a second source for the same query string is how filters drift.
    """
    from app.admin.pub_league_orders_routes import (
        _parse_order_filters, ORDER_SORTS)
    from sqlalchemy import desc

    filters = _parse_order_filters()

    try:
        page = max(1, int(page or 1))
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = int(per_page or ORDERS_PER_PAGE_DEFAULT)
    except (TypeError, ValueError):
        per_page = ORDERS_PER_PAGE_DEFAULT
    per_page = max(1, min(per_page, ORDERS_PER_PAGE_CAP))

    q = session.query(PubLeagueOrder).options(
        joinedload(PubLeagueOrder.primary_user))

    # Read status/search off the SAME parsed dict as everything else rather than
    # re-reading request.args here — two readers of one query string is how the
    # list and its own filter chips drift apart.
    status_filter = filters['status_filter'] or 'all'
    if status_filter and status_filter != 'all':
        q = q.filter(PubLeagueOrder.status == status_filter)

    search = filters['search']
    if search:
        like = f'%{search}%'
        q = q.filter(or_(
            PubLeagueOrder.customer_name.ilike(like),
            PubLeagueOrder.customer_email.ilike(like),
            PubLeagueOrder.woo_order_id.cast(db.String).ilike(like),
        ))

    if filters['season_condition'] is not None:
        q = q.filter(filters['season_condition'])
    if filters['division_condition'] is not None:
        q = q.filter(filters['division_condition'])

    q = q.order_by(ORDER_SORTS[filters['sort']](), desc(PubLeagueOrder.id))

    total = q.count()
    rows = q.limit(per_page).offset((page - 1) * per_page).all()

    # One query for every line item on the page rather than N lazy loads:
    # `line_items` is lazy='dynamic', so serializing 25 orders one at a time
    # fires 25 SELECTs inside the open transaction, and transaction HOLD TIME is
    # the scarce resource here (22 PgBouncer slots, 1 vCPU).
    order_ids = [o.id for o in rows]
    items_by_order, claims_by_id = {}, {}
    if order_ids:
        li_rows = (session.query(PubLeagueOrderLineItem)
                   .options(joinedload(PubLeagueOrderLineItem.assigned_player))
                   .filter(PubLeagueOrderLineItem.order_id.in_(order_ids))
                   .order_by(PubLeagueOrderLineItem.id).all())
        for li in li_rows:
            items_by_order.setdefault(li.order_id, []).append(li)
        claim_ids = [li.claim_id for li in li_rows if li.claim_id]
        if claim_ids:
            claims_by_id = {c.id: c for c in session.query(PubLeagueOrderClaim)
                            .filter(PubLeagueOrderClaim.id.in_(claim_ids)).all()}

    pages = (total + per_page - 1) // per_page if per_page else 0

    return {
        'success': True,
        'items': [_serialize_order(o, items_by_order.get(o.id, []), claims_by_id)
                  for o in rows],
        'total': total,
        'page': page,
        'per_page': per_page,
        # Stated, never silent.
        'per_page_cap': ORDERS_PER_PAGE_CAP,
        'pages': pages,
        'filters': {
            'status': status_filter,
            'search': search,
            'season': filters['season_filter'],
            'division': filters['division_filter'],
            'sort': filters['sort'],
        },
    }, 200


def get_order(session, order_id):
    """One order with its line items and claim state."""
    order = (session.query(PubLeagueOrder)
             .options(joinedload(PubLeagueOrder.primary_user))
             .filter_by(id=order_id).first())
    if not order:
        return _err('Order not found', 404)

    line_items = order.line_items.options(
        joinedload(PubLeagueOrderLineItem.assigned_player),
        joinedload(PubLeagueOrderLineItem.assigned_user),
    ).order_by(PubLeagueOrderLineItem.id).all()

    claims = (session.query(PubLeagueOrderClaim)
              .filter_by(order_id=order_id).all())
    claims_by_id = {c.id: c for c in claims}

    payload = _serialize_order(order, line_items, claims_by_id)
    payload['claims'] = [c.to_dict() for c in claims]
    return {'success': True, 'order': payload}, 200


def _current_season_types():
    """Season types that count as "this season" across every pub-league program.

    ⚠️ NOT just 'Pub League' — Summer Sprint's seasons are 'PL Third', and
    scoping to the one literal is how its orders went invisible on the web page
    (see project_summer_sprint_orders_invisible).
    """
    try:
        from app.services import program_registry
        return program_registry.pub_league_like_season_types() or ['Pub League']
    except Exception:
        return ['Pub League']


def search_players(session, query='', suggest_for='', limit=10):
    """Players an admin can link a pass to.

    ``already_has_pass`` drives a "link anyway?" confirm in the app — a WARNING,
    never a block. Two passes for one person is a legitimate, if unusual, state
    (someone buying for a partner who then never claims), and the desk has to be
    able to do it.
    """
    from app.admin.pub_league_orders_routes import _mask_email

    query = (query or '').strip()
    suggest_for = (suggest_for or '').strip()

    if suggest_for and len(query) < 2:
        parts = [p for p in suggest_for.split() if len(p) >= 2]
        if not parts:
            return {'success': True, 'players': [], 'is_suggestion': True}, 200
        players = (session.query(Player).options(joinedload(Player.user))
                   .filter(or_(*[Player.name.ilike(f'%{p}%') for p in parts]))
                   .limit(limit).all())
        # Rank by how many of the buyer's name parts a player matches, so the
        # obvious "same human" candidate leads.
        scored = sorted(
            ((p, sum(1 for part in parts if part.lower() in (p.name or '').lower()))
             for p in players),
            key=lambda pair: pair[1], reverse=True)
        players = [p for p, _ in scored[:5]]
        is_suggestion = True
    else:
        if len(query) < 2:
            return {'success': True, 'players': []}, 200
        like = f'%{query}%'
        players = (session.query(Player).options(joinedload(Player.user))
                   .filter(or_(Player.name.ilike(like),
                               Player.discord_username.ilike(like)))
                   .limit(limit).all())
        is_suggestion = False

    pass_holders = set()
    pids = [p.id for p in players]
    if pids:
        # ONE query, joined straight through to Season rather than fetching the
        # current season ids first. This runs on the WEB order page's
        # debounced-per-keystroke search too, and query count on lookup paths is
        # a known sensitivity here — a second round-trip for something this
        # small is not worth it.
        #
        # Orders with a NULL season_id (unmatched orphans) are deliberately NOT
        # counted: they are the queue of orders nobody has placed in a season
        # yet, so "already has a pass" would be asserting more than we know.
        q = (session.query(PubLeagueOrderLineItem.assigned_player_id)
             .join(PubLeagueOrder,
                   PubLeagueOrderLineItem.order_id == PubLeagueOrder.id)
             .join(Season, Season.id == PubLeagueOrder.season_id)
             .filter(PubLeagueOrderLineItem.assigned_player_id.in_(pids),
                     Season.is_current.is_(True),
                     Season.league_type.in_(_current_season_types())))
        pass_holders = {pid for (pid,) in q.all() if pid}

    out = []
    for p in players:
        user = p.user
        picture = p.profile_picture_url
        if picture and picture.startswith('/'):
            # Absolute, like every other image URL the mobile API returns — the
            # app has no base URL to resolve a bare path against.
            try:
                from flask import request, has_request_context
                if has_request_context():
                    picture = f"{request.host_url.rstrip('/')}{picture}"
            except Exception:
                pass
        out.append({
            'id': p.id,
            'player_id': p.id,
            'user_id': user.id if user else None,
            'name': p.name,
            'discord_username': p.discord_username,
            'team_name': (p.primary_team.name if getattr(p, 'primary_team', None)
                          else None),
            'profile_picture_url': picture,
            'email_hint': (_mask_email(user.email)
                           if user and getattr(user, 'email', None) else None),
            'is_current_player': bool(p.is_current_player),
            'already_has_pass': p.id in pass_holders,
        })

    payload = {'success': True, 'players': out}
    if is_suggestion:
        payload['is_suggestion'] = True
        payload['suggested_for'] = suggest_for
    return payload, 200


# ---------------------------------------------------------------------------
# mutations
# ---------------------------------------------------------------------------

def _load_line_item(session, line_item_id, order_id=None):
    """(line_item, error) — enforcing that it really belongs to ``order_id``.

    The mobile routes carry the order in the URL and the line item in the body,
    so the two can disagree. Checking is cheap and turns "linked the wrong
    order's pass" into a 404 instead of a silent cross-order write.
    """
    li = (session.query(PubLeagueOrderLineItem)
          .options(joinedload(PubLeagueOrderLineItem.order),
                   joinedload(PubLeagueOrderLineItem.assigned_player))
          .filter_by(id=line_item_id).first())
    if not li:
        return None, _err('Line item not found', 404)
    if order_id is not None and li.order_id != order_id:
        return None, _err('Line item does not belong to this order', 404)
    return li, None


def manual_link(line_item_id, player_id, actor_id, order_id=None):
    """Link (or RE-link) a pass to a player.

    ⚠️ Runs on ``g.db_session``: ``link_pass_to_player`` and
    ``activate_player_for_league`` commit that session, and objects loaded on
    ``db.session`` belong to a different one — their changes were never
    committed, so the admin saw "linked" and a refresh showed it unassigned.

    ⚠️ Reassignment does NOT go through the unassign path's counter decrement +
    re-increment as two independent facts: ``assign_to_player`` re-increments
    ``order.linked_passes``, so the old assignment is cleared WITHOUT touching
    the counter. Getting this wrong inflates the order's linked count forever.
    """
    from app.pub_league.services import PubLeagueOrderService, PlayerActivationService

    if not line_item_id or not player_id:
        return _err('Missing line_item_id or player_id')

    session = _request_session()
    line_item, err = _load_line_item(session, line_item_id, order_id)
    if err:
        return err

    player = (session.query(Player).options(joinedload(Player.user))
              .filter_by(id=player_id).first())
    if not player:
        return _err('Player not found', 404)

    was_assigned = line_item.status != PubLeagueLineItemStatus.UNASSIGNED.value
    previous_name = line_item.assigned_player.name if line_item.assigned_player else None
    previous_player_id = line_item.assigned_player_id

    if was_assigned and line_item.assigned_player_id == player.id:
        return _err('Pass is already assigned to this player')

    if was_assigned:
        # Back to unassigned without touching linked_passes (assign
        # re-increments), and drop the wallet pass so the new holder gets a
        # fresh one rather than the previous holder's.
        line_item.assigned_player_id = None
        line_item.assigned_user_id = None
        line_item.assigned_at = None
        line_item.wallet_pass_id = None
        line_item.pass_created_at = None
        line_item.link_method = None
        line_item.link_confirmed_at = None
        line_item.status = PubLeagueLineItemStatus.UNASSIGNED.value
        if line_item.order:
            line_item.order.linked_passes = max(0, line_item.order.linked_passes - 1)
        session.flush()

        # The previous holder loses this pass — deactivate them unless they
        # still hold another for this season.
        PlayerActivationService.deactivate_player_if_no_current_pass(
            previous_player_id, line_item.order, exclude_line_item_id=line_item.id)

    user = player.user if player.user_id else None
    player_name = player.name
    # Read before the link/activation run, and before the rollback path below.
    # Safe either way today (both sessions are expire_on_commit=False), but this
    # answers "did they have Discord when we linked them?" — reading it after a
    # commit/rollback would be relying on session config for a correct answer.
    has_discord = bool(getattr(player, 'discord_id', None))

    # Stamped 'admin' so the orders page shows staff linked it (via the
    # name-match suggestion, which CAN pick the wrong same-named player) rather
    # than the buyer confirming it themselves.
    PubLeagueOrderService.link_pass_to_player(line_item, player, user, method='admin')

    verb = 'reassigned' if was_assigned else 'linked'
    msg = (f'Pass reassigned from {previous_name} to {player_name}'
           if was_assigned and previous_name else f'Pass linked to {player_name}')
    payload = {'success': True, 'message': msg, 'line_item': line_item.to_dict()}

    if user:
        try:
            PlayerActivationService.activate_player_for_league(
                player=player, user=user, division=line_item.division,
                jersey_size=line_item.jersey_size)
        except Exception as exc:
            logger.error(
                f"Activation failed for player {player_id} after admin link of "
                f"line item {line_item_id} (the pass IS linked): {exc}", exc_info=True)
            session.rollback()
            payload['message'] = (
                f'{msg}, but activating them for the season failed — '
                'their pass is linked; re-run the link to activate.')

    # Activation moves league/team roles, so tell the client to show its
    # "Discord role updating…" hint rather than looking frozen.
    payload['discord_sync_queued'] = bool(user and has_discord)

    logger.info(f"Admin {actor_id} {verb} line item {line_item_id} to player {player_id}"
                + (f" (was {previous_name})" if previous_name else ""))
    return payload, 200


def unassign_pass(line_item_id, actor_id, order_id=None):
    """Return a pass to the pool and deactivate its holder if it was their only one."""
    from app.pub_league.services import PlayerActivationService

    if not line_item_id:
        return _err('Missing line_item_id')

    line_item, err = _load_line_item(db.session, line_item_id, order_id)
    if err:
        return err

    if line_item.status == PubLeagueLineItemStatus.UNASSIGNED.value:
        return _err('Pass is already unassigned')

    old_player_name = line_item.assigned_player.name if line_item.assigned_player else 'Unknown'
    old_player_id = line_item.assigned_player_id
    order = line_item.order

    # Clearing wallet_pass_id matters: generate-pass short-circuits on a
    # non-null wallet_pass_id and hands back the OLD pass, so without this a
    # re-linked line item would give the new holder the previous holder's pass.
    line_item.assigned_player_id = None
    line_item.assigned_user_id = None
    line_item.assigned_at = None
    line_item.wallet_pass_id = None
    line_item.pass_created_at = None
    line_item.link_method = None
    line_item.link_confirmed_at = None
    line_item.status = PubLeagueLineItemStatus.UNASSIGNED.value

    if order:
        order.linked_passes = max(0, order.linked_passes - 1)
        order.update_status()

    db.session.commit()

    deactivated = PlayerActivationService.deactivate_player_if_no_current_pass(
        old_player_id, order, exclude_line_item_id=line_item.id)

    logger.info(f"Admin {actor_id} unassigned line item {line_item_id} "
                f"(was {old_player_name}); player deactivated={deactivated}")

    msg = f'Pass unassigned from {old_player_name}'
    if deactivated:
        msg += ' (no longer active for the season)'
    return {'success': True, 'message': msg, 'deactivated': bool(deactivated)}, 200


def _load_claim(claim_id, order_id=None, with_order=False):
    """(claim, error), scoped to ``order_id`` when the caller supplies one."""
    opts = [joinedload(PubLeagueOrderClaim.line_item)]
    if with_order:
        opts.append(joinedload(PubLeagueOrderClaim.order))
    claim = (db.session.query(PubLeagueOrderClaim).options(*opts)
             .filter_by(id=claim_id).first())
    if not claim:
        return None, _err('Claim not found', 404)
    if order_id is not None and claim.order_id != order_id:
        return None, _err('Claim does not belong to this order', 404)
    return claim, None


def resend_claim(claim_id, actor_id, order_id=None):
    """Resend the claim email for a still-PENDING claim."""
    from app.pub_league.email_helpers import send_claim_link_email

    if not claim_id:
        return _err('Missing claim_id')

    claim, err = _load_claim(claim_id, order_id, with_order=True)
    if err:
        return err
    if not claim.recipient_email:
        return _err('No recipient email on claim')
    if claim.status != PubLeagueClaimStatus.PENDING.value:
        return _err('Claim is not pending')

    line_item = claim.line_item
    order = claim.order
    sent = send_claim_link_email(
        recipient_email=claim.recipient_email,
        recipient_name=claim.recipient_name,
        claim_token=claim.claim_token,
        division=line_item.division if line_item else 'Pub League',
        sender_name=order.customer_name if order else 'ECS Pub League',
        expires_at=claim.expires_at,
    )
    if not sent:
        return _err('Failed to send email', 500)

    claim.email_sent_at = datetime.utcnow()
    db.session.commit()
    logger.info(f"Admin {actor_id} resent claim email for claim {claim_id}")
    return {'success': True, 'message': 'Claim email sent'}, 200


def cancel_claim(claim_id, actor_id, order_id=None):
    """Cancel a pending claim and release its line item."""
    if not claim_id:
        return _err('Missing claim_id')

    claim, err = _load_claim(claim_id, order_id)
    if err:
        return err
    if claim.status != PubLeagueClaimStatus.PENDING.value:
        return _err('Claim is not pending')

    claim.status = PubLeagueClaimStatus.CANCELLED.value
    if claim.line_item:
        claim.line_item.claim_id = None

    db.session.commit()
    logger.info(f"Admin {actor_id} cancelled claim {claim_id}")
    return {'success': True, 'message': 'Claim cancelled'}, 200


def refresh_order(order_id, actor_id):
    """Re-fetch an order from WooCommerce and re-derive its money columns.

    This is the ONLY path that picks up a refund issued after purchase — the
    webhook copy is frozen at the moment of sale.
    """
    from app.pub_league.services import PubLeagueOrderService

    if not order_id:
        return _err('Missing order_id')

    order = db.session.query(PubLeagueOrder).filter_by(id=order_id).first()
    if not order:
        return _err('Order not found', 404)

    order_data = PubLeagueOrderService.fetch_order_from_woocommerce(order.woo_order_id)
    if not order_data:
        return _err('Could not fetch order from WooCommerce', 502)

    order.woo_order_data = order_data

    billing = order_data.get('billing', {}) or {}
    new_name = f"{billing.get('first_name', '')} {billing.get('last_name', '')}".strip()
    new_email = billing.get('email', '')
    if new_name:
        order.customer_name = new_name
    if new_email:
        order.customer_email = new_email

    try:
        from app.pub_league.revenue import apply_order_revenue
        apply_order_revenue(order)
    except Exception as exc:
        # The revenue columns come from a hand-run migration; a missing column
        # must not fail a refresh that otherwise worked.
        logger.warning(f"Could not refresh revenue for order {order_id}: {exc}",
                       exc_info=True)

    order.updated_at = datetime.utcnow()
    db.session.commit()

    logger.info(f"Admin {actor_id} refreshed order {order_id} from WooCommerce")
    return {'success': True,
            'message': 'Order data refreshed from WooCommerce',
            'order': order.to_dict()}, 200


# ---------------------------------------------------------------------------
# limbo
# ---------------------------------------------------------------------------

def player_limbo(player_id, line_item_id=None):
    """What is inconsistent about this person now that they hold a pass.

    Buying a pass and being CLEARED TO PLAY are deliberately separate axes — we
    refund people who turn out not to be a good fit — so this WRITES NOTHING. It
    only lets the admin doing a manual assignment fix things in the same breath
    instead of leaving someone pending/waitlisted forever with a paid pass.

    Reports the misalignment; it never prescribes an outcome (no "refund owed",
    no "deny them"). ``resolve_limbo`` applies only what gets ticked.
    """
    from app.admin.pub_league_orders_routes import _division_form_value
    from app.models.substitutes import SubstitutePool

    if not player_id:
        return _err('Missing player_id')

    session = _request_session()
    player = (session.query(Player).options(joinedload(Player.user))
              .filter_by(id=player_id).first())
    if not player:
        return _err('Player not found', 404)

    line_item = None
    if line_item_id:
        line_item = (session.query(PubLeagueOrderLineItem)
                     .options(joinedload(PubLeagueOrderLineItem.order))
                     .filter_by(id=line_item_id).first())

    division = line_item.division if line_item else None
    form_value, division_label = _division_form_value(division)

    user = player.user if player.user_id else None
    actions, notes = [], []

    if user is None:
        notes.append("This player has no linked user account, so they cannot "
                     "be approved or taken off a waitlist here.")
    else:
        role_names = {r.name for r in user.roles}
        approved = bool(getattr(user, 'is_approved', False))
        status = (getattr(user, 'approval_status', None) or '').lower()

        if not approved or status == 'pending':
            if not form_value:
                notes.append(
                    f"They are still awaiting approval, but this pass's division "
                    f"({division or 'unknown'}) doesn't match a known program, so "
                    f"approval can't be offered here. Approve them from their "
                    f"member page instead.")
            else:
                label = f"Approve them for {division_label}"
                if status == 'denied':
                    # Surfaced, never hidden: silently re-approving someone an
                    # admin deliberately denied is exactly the decision this
                    # feature must not make on its own.
                    label += " — heads up, they were previously DENIED"
                actions.append({
                    'key': 'approve',
                    'label': label,
                    'detail': f"Grants the {division_label} role, creates their "
                              f"membership row, and syncs Discord.",
                    'value': form_value,
                })

        if 'pl-waitlist' in role_names or getattr(user, 'waitlist_league', None):
            lane = (getattr(user, 'waitlist_league', None) or '').replace('-', ' ').title()
            actions.append({
                'key': 'remove_waitlist',
                'label': f"Take them off the {lane or 'league'} waitlist",
                'detail': "They hold a paid pass, so a waitlist spot is contradictory. "
                          "(Approving above already does this.)",
            })

    pools = session.query(SubstitutePool).filter_by(player_id=player.id).all()
    if pools:
        pool_names = ', '.join(sorted({p.league_type for p in pools if p.league_type}))
        actions.append({
            'key': 'remove_sub_pools',
            'label': f"Remove them from the {pool_names} substitute pool"
                     f"{'s' if len(pools) > 1 else ''}",
            'detail': "Only if they should no longer be offered as a sub. Plenty of "
                      "rostered players stay in a pool on purpose — leave this "
                      "unticked to keep them.",
        })

    # Informational only: a pending quick profile can't be claimed BY an admin —
    # the person claims it themselves — so this is a note, not an action.
    try:
        from app.models.quick_profile import QuickProfile, QuickProfileStatus
        email = (line_item.order.customer_email if (line_item and line_item.order) else None)
        if email:
            qp = session.query(QuickProfile).filter(
                QuickProfile.status == QuickProfileStatus.PENDING.value,
                func.lower(QuickProfile.email) == email.strip().lower(),
            ).first()
            if qp:
                notes.append(
                    f"There's an unclaimed quick profile for {email} "
                    f"(code {qp.claim_code}). They have to claim it themselves — "
                    f"resend the code if they never got it.")
    except Exception:
        logger.debug("quick-profile limbo check skipped", exc_info=True)

    return {
        'success': True,
        'player_name': player.name,
        'division': division,
        'actions': actions,
        'notes': notes,
    }, 200


def resolve_limbo(player_id, actions, approve_value, actor_id):
    """Apply ONLY the limbo fixes that were explicitly ticked.

    An empty ``actions`` list is a valid, successful no-op — "none" is one of
    the choices and must not be harder than the others.

    ⚠️ SESSION: ``apply_approval`` mutates and expects ``db.session``
    throughout, so everything here stays on ``db.session`` and commits it. The
    rest of the orders blueprint works on ``g.db_session``, which is a DIFFERENT
    session — mixing them is the silently-discarded-write bug.
    """
    from app.models import Role
    from app.models.admin_config import AdminAuditLog
    from app.models.substitutes import SubstitutePool

    if not player_id:
        return _err('Missing player_id')
    actions = actions or []
    if not isinstance(actions, list):
        return _err('actions must be a list')
    if not actions:
        return {'success': True, 'applied': [], 'message': 'Nothing changed.'}, 200

    _ALLOWED = {'approve', 'remove_waitlist', 'remove_sub_pools'}
    unknown = [a for a in actions if a not in _ALLOWED]
    if unknown:
        return _err(f"Unknown action(s): {', '.join(map(str, unknown))}")

    player = (db.session.query(Player).options(joinedload(Player.user))
              .filter_by(id=player_id).first())
    if not player:
        return _err('Player not found', 404)
    user = player.user if player.user_id else None
    # Read before the commits below, for the same reason as manual_link.
    has_discord = bool(getattr(player, 'discord_id', None))

    applied, failed = [], []
    approved_here = False

    if 'approve' in actions:
        from app.admin_panel.routes.user_management.approvals import apply_approval
        # ⚠️ approve_league_types lives in integrity_service, NOT approvals —
        # approvals only imports it inside a function body, so importing it from
        # there raises ImportError at request time.
        from app.services.integrity_service import approve_league_types
        if user is None:
            failed.append('Approve — no user account linked to this player.')
        elif not approve_value:
            failed.append('Approve — no league was resolved for this pass.')
        elif approve_value not in approve_league_types():
            # Never trust a value round-tripped through a client.
            failed.append(f"Approve — '{approve_value}' is not an approvable league.")
        else:
            prior = (user.approval_status or 'pending')
            try:
                apply_approval(user, approve_value, approver_id=actor_id,
                               notes='Approved from the order page after a pass was assigned.')
                _audit_approval(AdminAuditLog, actor_id, user.id, prior, approve_value)
                applied.append(f'Approved for {approve_value}')
                approved_here = True
            except ValueError as ve:
                failed.append(f'Approve — {ve}')

    # Skipped when approve ran: apply_approval already clears the waitlist, and
    # re-running it would report a change that did not happen.
    if 'remove_waitlist' in actions and not approved_here:
        if user is None:
            failed.append('Waitlist — no user account linked to this player.')
        else:
            wl_role = db.session.query(Role).filter_by(name='pl-waitlist').first()
            if wl_role and wl_role in user.roles:
                user.roles.remove(wl_role)
            user.waitlist_joined_at = None
            user.waitlist_league = None
            applied.append('Removed from the waitlist')

    if 'remove_sub_pools' in actions:
        pools = db.session.query(SubstitutePool).filter_by(player_id=player.id).all()
        removed = []
        for pool in pools:
            removed.append(pool.league_type)
            # ⚠️ substitute_pool_history.pool_id is NOT NULL with no ON DELETE,
            # so history rows must go first or the delete raises.
            try:
                from app.models.substitutes import SubstitutePoolHistory
                db.session.query(SubstitutePoolHistory).filter_by(
                    pool_id=pool.id).delete(synchronize_session=False)
            except Exception:
                logger.exception("could not clear sub pool history for pool %s", pool.id)
            db.session.delete(pool)
        if removed:
            applied.append(f"Removed from sub pool(s): {', '.join(sorted(set(removed)))}")

    db.session.commit()

    # The spine recomputes from the source facts just changed, so it has to run
    # AFTER the commit above or it recomputes from stale state.
    try:
        from app.services.league_membership_sync import resync_player_memberships
        resync_player_memberships(db.session, player.id)
        db.session.commit()
    except Exception:
        logger.exception("membership resync after limbo resolve failed for player %s",
                         player.id)

    logger.info("Admin %s resolved limbo for player %s: applied=%s failed=%s",
                actor_id, player_id, applied, failed)

    return {
        'success': True,
        'applied': applied,
        'failed': failed,
        'message': ('; '.join(applied) if applied else 'Nothing changed.'),
        # Approval moves Discord roles; the app shows "Discord role updating…".
        'discord_sync_queued': bool(approved_here and has_discord),
    }, 200


def _audit_approval(AdminAuditLog, actor_id, user_id, prior, approve_value):
    """Audit the approval without letting a logging failure undo the approval."""
    try:
        from flask import request, has_request_context
        ip = request.remote_addr if has_request_context() else None
        ua = request.headers.get('User-Agent') if has_request_context() else None
        AdminAuditLog.log_action(
            user_id=actor_id, action='approve_user',
            resource_type='user_approval', resource_id=str(user_id),
            old_value=prior, new_value=f'approved:{approve_value}',
            ip_address=ip, user_agent=ua)
    except Exception as exc:
        logger.warning(f"audit log skipped for limbo approval of user {user_id}: {exc}")
