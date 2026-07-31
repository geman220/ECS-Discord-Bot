"""
Pub League Order Admin Routes

Admin routes for managing Pub League WooCommerce orders, including:
- Viewing all orders and their linking status
- Viewing order details with line items and claims
- Resending claim emails
- Manually linking passes
- Cancelling claims
"""

import io
import logging
import re
from datetime import datetime, timedelta
from decimal import Decimal

from flask import (
    Blueprint, render_template, request, jsonify, url_for, send_file, abort, redirect, g,
    current_app,
)
from flask_login import login_required, current_user
from sqlalchemy import desc, asc, or_, and_, func, distinct, exists, nullslast, select
from sqlalchemy.orm import joinedload

from app.core import db
from app.models import (
    PubLeagueOrder, PubLeagueOrderLineItem, PubLeagueOrderClaim,
    PubLeagueOrderStatus, PubLeagueLineItemStatus, PubLeagueClaimStatus,
    Player, User, Season
)
from app.decorators import role_required
from app.utils.user_helpers import safe_current_user

logger = logging.getLogger(__name__)

pub_league_orders_admin_bp = Blueprint('pub_league_orders_admin', __name__, url_prefix='/admin-panel')


# Sort options shared by the list view and the email export. The key is the
# `sort` query param; the value is the ORDER BY clause. customer_name uses
# nullslast so unnamed orders never lead an alphabetical list.
ORDER_SORTS = {
    'created_desc': lambda: desc(PubLeagueOrder.created_at),
    'created_asc': lambda: asc(PubLeagueOrder.created_at),
    'name_asc': lambda: nullslast(asc(PubLeagueOrder.customer_name)),
    'name_desc': lambda: nullslast(desc(PubLeagueOrder.customer_name)),
    'woo_asc': lambda: asc(PubLeagueOrder.woo_order_id),
    'woo_desc': lambda: desc(PubLeagueOrder.woo_order_id),
}
DEFAULT_SORT = 'created_desc'


def division_filter_options():
    """[(value, label)] for the Division filter -- one entry per program.

    Registry-driven. This was a hardcoded ('premier', 'classic', 'mixed') tuple,
    so a newer program's orders had no filter entry at all: they still appeared
    under "All divisions" (the default), but there was no way to filter TO them.

    `value` is the program's own league_name lowercased, which is what
    PubLeagueOrderLineItem.division stores (see extract_pub_league_items --
    it writes `program.league_name`).
    """
    opts = [('all', 'All divisions')]
    try:
        from app.services import program_registry
        for pr in program_registry.all_programs():
            if pr.is_pub_league_like and pr.league_name:
                opts.append((pr.league_name.lower(), pr.league_name))
    except Exception as exc:
        logger.warning(f"division filter options fell back to literals: {exc}")
        opts.extend([('premier', 'Premier'), ('classic', 'Classic')])
    opts.append(('mixed', 'Mixed (one order, several divisions)'))
    return opts


def _division_names():
    """Every division value that can appear on a line item."""
    try:
        from app.services import program_registry
        names = [pr.league_name for pr in program_registry.all_programs()
                 if pr.is_pub_league_like and pr.league_name]
        if names:
            return names
    except Exception:
        pass
    return ['Premier', 'Classic']


def _division_condition(division_filter):
    """
    WHERE condition matching the Division badge shown in the list.

      '<division>' = this order contains ONLY that division
      'mixed'      = this ORDER contains more than one distinct division

    ⚠️ "Mixed" is deliberately PER ORDER, not per person. Buying a Premier pass
    in one order and a Summer Sprint pass in another creates two separate
    orders, and each shows its own division -- that person is not "mixed", they
    simply belong to two independent programs. Mixed means one order that
    covers several divisions (buying for yourself and a friend in different
    divisions), which is the only case where the badge is genuinely ambiguous.

    The old version hardcoded mixed as "has Premier AND has Classic", so an
    order spanning any newer program was invisible to that filter.

    Uses correlated EXISTS so it composes with the plain PubLeagueOrder query
    (no join needed) and reuses across list/stats/export. None for 'all'.

    ⚠️ `.correlate(PubLeagueOrder)` is load-bearing, not decoration. Left to
    auto-correlation, SQLAlchemy correlates EVERY table the subquery shares with
    the enclosing query -- so the moment this is used on a query that also
    selects from `pub_league_order_line_item` (the auto-unconfirmed stat, the
    jersey-size export aggregate), the line-item table is correlated away too
    and the subquery is left with NO FROM clause at all. That raises
    InvalidRequestError and drops the whole orders page into its error state:
    picking any division but "All divisions" blanked the page. Naming the one
    table we mean to correlate keeps the line-item table in the subquery's FROM.
    """
    if not division_filter or division_filter == 'all':
        return None

    li = PubLeagueOrderLineItem
    names = _division_names()

    def _has(name):
        return (exists().where(and_(li.order_id == PubLeagueOrder.id,
                                    func.lower(li.division) == name.lower()))
                .correlate(PubLeagueOrder))

    if division_filter == 'mixed':
        # More than one distinct division on the same order.
        return (select(func.count(func.distinct(li.division)))
                .where(li.order_id == PubLeagueOrder.id)
                .correlate(PubLeagueOrder)
                .scalar_subquery()) > 1

    match = next((n for n in names if n.lower() == division_filter.lower()), None)
    if match is None:
        return None

    # ONLY this division: has it, and has nothing else.
    others = [~_has(n) for n in names if n.lower() != match.lower()]
    return and_(_has(match), *others) if others else _has(match)


def _parse_order_filters():
    """
    Parse the status/search/season/division/sort filter params shared by the
    orders list and the email export, and build the season scope condition.

    Season scope defaults to the current season of EVERY pub-league-like
    program so the list is not clogged with last season's orders. This "ties to
    rollover": whichever seasons are is_current become the default view
    automatically, no config. 'all' shows every season; a numeric id shows one
    specific season.

    Returns a dict with: status_filter, search, season_filter,
    selected_season_id, is_current_view, current_season, current_seasons,
    current_season_ids, current_season_label, season_condition.
    """
    status_filter = request.args.get('status', 'all')
    search = request.args.get('search', '').strip()

    sort = request.args.get('sort', DEFAULT_SORT)
    if sort not in ORDER_SORTS:
        sort = DEFAULT_SORT

    division_filter = request.args.get('division', 'all')
    _valid_divisions = {v for v, _label in division_filter_options()}
    if division_filter not in _valid_divisions:
        division_filter = 'all'
    division_condition = _division_condition(division_filter)

    # "Current" spans EVERY pub-league-like program, not just Pub League.
    #
    # ⚠️ This was `filter_by(league_type='Pub League', is_current=True).first()`.
    # Each program carries its OWN `Season.league_type` precisely so it can have
    # its own `is_current` row -- Summer Sprint's seasons are 'PL Third'. So a
    # Summer Sprint order, correctly bound to the current 'PL Third' season, did
    # not match `season_id == <Pub League current>` and did not match the orphan
    # branch either (its `season_name` is set and is not the Pub League season's
    # name). It was invisible on the default view with no error and no empty
    # state -- the page simply looked like nobody had bought one.
    #
    # `pub_league_like_season_types()` is exactly the "I genuinely want all
    # pub-league-like seasons at once" case its docstring sanctions; the bug it
    # warns about is feeding that list to `.in_()` and then `.first()`, which is
    # not what happens here -- every current season is kept.
    try:
        from app.services import program_registry
        _season_types = program_registry.pub_league_like_season_types() or ['Pub League']
    except Exception as exc:
        logger.warning(f"orders: season types fell back to Pub League: {exc}")
        _season_types = ['Pub League']

    current_seasons = db.session.query(Season).filter(
        Season.league_type.in_(_season_types), Season.is_current.is_(True)
    ).order_by(Season.id.desc()).all()
    current_season_ids = [s.id for s in current_seasons]
    # Kept for the template's "is this option already the current one" check and
    # for callers that want a single representative season.
    current_season = current_seasons[0] if current_seasons else None
    current_season_label = ', '.join(s.name for s in current_seasons if s.name)

    season_filter = request.args.get('season', 'current')
    is_current_view = False
    if season_filter == 'all':
        selected_season_id = None
    elif season_filter == 'current':
        selected_season_id = current_season.id if current_season else None
        is_current_view = True
    else:
        try:
            selected_season_id = int(season_filter)
            is_current_view = False
        except (TypeError, ValueError):
            selected_season_id = current_season.id if current_season else None
            season_filter = 'current'
            is_current_view = True

    # Season scope condition, reused for the list, the stat counts, and the
    # email export. The current view also surfaces orphan/unmatched orders
    # (season_id IS NULL) that need admin attention; a specific past season
    # shows only that season.
    season_condition = None
    if season_filter != 'all' and selected_season_id is not None:
        if is_current_view:
            # Current view = orders in ANY program's current season, PLUS
            # genuine orphans that need attention. An orphan is a NULL season_id
            # with no season_name (truly unmatched) or a name that IS one of the
            # current seasons. We must NOT sweep in legacy orders that carry
            # a PAST season_name (e.g. "2024 Spring") but never had their
            # season_id backfilled — those were flooding the current view.
            orphan_names = [PubLeagueOrder.season_name.is_(None), PubLeagueOrder.season_name == '']
            for _cs in current_seasons:
                if _cs.name:
                    orphan_names.append(PubLeagueOrder.season_name == _cs.name)
            season_condition = or_(
                PubLeagueOrder.season_id.in_(current_season_ids),
                and_(
                    PubLeagueOrder.season_id.is_(None),
                    or_(*orphan_names)
                )
            )
        else:
            # An explicitly chosen season means THAT season only — including
            # when it happens to be a current one. Orphans stay on the
            # "Current Season" view, which is the queue for them.
            season_condition = PubLeagueOrder.season_id == selected_season_id

    return {
        'status_filter': status_filter,
        'search': search,
        'season_filter': season_filter,
        'selected_season_id': selected_season_id,
        'is_current_view': is_current_view,
        'current_season': current_season,
        'current_seasons': current_seasons,
        'current_season_ids': current_season_ids,
        'current_season_label': current_season_label,
        'season_condition': season_condition,
        'sort': sort,
        'division_filter': division_filter,
        'division_condition': division_condition,
    }


@pub_league_orders_admin_bp.route('/pub-league-orders')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def orders_list():
    """Display list of all Pub League orders with filtering and pagination."""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = 25

        filters = _parse_order_filters()
        status_filter = filters['status_filter']
        search = filters['search']
        season_filter = filters['season_filter']
        selected_season_id = filters['selected_season_id']
        season_condition = filters['season_condition']
        current_season = filters['current_season']
        current_season_ids = filters['current_season_ids']
        current_season_label = filters['current_season_label']
        sort = filters['sort']
        division_filter = filters['division_filter']
        division_condition = filters['division_condition']

        # Subquery for divisions - aggregates distinct divisions per order
        # Use string_agg for PostgreSQL (group_concat is MySQL)
        division_subq = (
            db.session.query(
                PubLeagueOrderLineItem.order_id,
                func.string_agg(distinct(PubLeagueOrderLineItem.division), ',').label('divisions')
            )
            .group_by(PubLeagueOrderLineItem.order_id)
            .subquery()
        )

        # Base query with eager loading and division subquery
        # Note: line_items uses lazy='dynamic' so we can't use joinedload on it
        query = db.session.query(
            PubLeagueOrder,
            division_subq.c.divisions
        ).options(
            joinedload(PubLeagueOrder.primary_user)
        ).outerjoin(
            division_subq,
            PubLeagueOrder.id == division_subq.c.order_id
        )

        # Apply status filter
        if status_filter != 'all':
            query = query.filter(PubLeagueOrder.status == status_filter)

        # Apply search filter
        if search:
            search_term = f'%{search}%'
            query = query.filter(
                or_(
                    PubLeagueOrder.customer_name.ilike(search_term),
                    PubLeagueOrder.customer_email.ilike(search_term),
                    PubLeagueOrder.woo_order_id.cast(db.String).ilike(search_term)
                )
            )

        # Apply season scope
        if season_condition is not None:
            query = query.filter(season_condition)

        # Apply division (Premier/Classic/Mixed) scope
        if division_condition is not None:
            query = query.filter(division_condition)

        # Apply sort (name alphabetical, created, or woo order id), with a
        # stable id tie-breaker so equal keys page consistently.
        query = query.order_by(ORDER_SORTS[sort](), desc(PubLeagueOrder.id))

        # Paginate - need to handle the tuple results
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)

        # Convert tuples to objects with divisions attribute
        class OrderWithDivisions:
            def __init__(self, order, divisions):
                self._order = order
                self.divisions = divisions

            def __getattr__(self, name):
                return getattr(self._order, name)

        orders_with_divisions = [OrderWithDivisions(order, divisions) for order, divisions in pagination.items]

        # Create a custom pagination-like object
        class PaginationWrapper:
            def __init__(self, items, pagination):
                self.items = items
                self.page = pagination.page
                self.pages = pagination.pages
                self.has_prev = pagination.has_prev
                self.has_next = pagination.has_next
                self.prev_num = pagination.prev_num
                self.next_num = pagination.next_num
                self.total = pagination.total

            def iter_pages(self, **kwargs):
                return pagination.iter_pages(**kwargs)

        orders = PaginationWrapper(orders_with_divisions, pagination)

        # Statistics — scoped to the SELECTED season so the counts match the list.
        def _order_count(status=None):
            q = db.session.query(func.count(PubLeagueOrder.id))
            if season_condition is not None:
                q = q.filter(season_condition)
            if division_condition is not None:
                q = q.filter(division_condition)
            if status is not None:
                q = q.filter(PubLeagueOrder.status == status)
            return q.scalar() or 0

        stats = {
            'total': _order_count(),
            'not_started': _order_count(PubLeagueOrderStatus.NOT_STARTED.value),
            'pending': _order_count(PubLeagueOrderStatus.PENDING.value),
            'partial': _order_count(PubLeagueOrderStatus.PARTIALLY_LINKED.value),
            'fully_linked': _order_count(PubLeagueOrderStatus.FULLY_LINKED.value),
            'cancelled': _order_count(PubLeagueOrderStatus.CANCELLED.value),
        }

        # Passes auto-linked to the buyer but never confirmed by them. These are
        # almost always fine (the buyer is Discord-authenticated), but this is the
        # one place an auto-link could theoretically catch the wrong person, so
        # surface a count for a quick eyeball.
        auto_unconfirmed_q = (
            db.session.query(func.count(PubLeagueOrderLineItem.id))
            .join(PubLeagueOrder, PubLeagueOrderLineItem.order_id == PubLeagueOrder.id)
            .filter(
                PubLeagueOrderLineItem.link_method == 'auto',
                PubLeagueOrderLineItem.link_confirmed_at.is_(None),
                PubLeagueOrderLineItem.assigned_player_id.isnot(None),
            )
        )
        if season_condition is not None:
            auto_unconfirmed_q = auto_unconfirmed_q.filter(season_condition)
        if division_condition is not None:
            auto_unconfirmed_q = auto_unconfirmed_q.filter(division_condition)
        stats['auto_unconfirmed'] = auto_unconfirmed_q.scalar() or 0

        # Money in for the same filtered scope. Isolated in its own try: the
        # columns it reads are added by sql_pub_league_order_revenue.sql, which
        # is run by hand in pgAdmin, so the code can land before the table has
        # them. A missing column must degrade to "no revenue section" rather
        # than blanking a page admins use to link passes.
        try:
            revenue = _revenue_stats(filters)
        except Exception as rev_err:
            logger.warning(f"revenue stats unavailable: {rev_err}")
            revenue = None

        # Season options for the filter dropdown — only seasons that actually
        # have orders, newest first.
        season_options = [
            {'id': sid, 'name': sname or f'Season {sid}'}
            for sid, sname in db.session.query(
                PubLeagueOrder.season_id, PubLeagueOrder.season_name
            ).filter(PubLeagueOrder.season_id.isnot(None)).distinct().all()
        ]
        season_options.sort(key=lambda s: s['id'], reverse=True)

        # Get user roles for template
        user_roles = [role.name for role in safe_current_user.roles] if safe_current_user.is_authenticated else []

        # Get product URL settings
        from app.models.admin_config import AdminConfig
        premier_product_slug = AdminConfig.get_setting('pub_league_premier_product_slug', '')
        classic_product_slug = AdminConfig.get_setting('pub_league_classic_product_slug', '')

        return render_template(
            'admin/pub_league_orders_flowbite.html',
            title='Pub League Orders',
            orders=orders,
            stats=stats,
            revenue=revenue,
            status_filter=status_filter,
            search=search,
            season_filter=season_filter,
            selected_season_id=selected_season_id,
            season_options=season_options,
            current_season=current_season,
            current_season_ids=current_season_ids,
            current_season_label=current_season_label,
            sort=sort,
            division_filter=division_filter,
            division_options=division_filter_options(),
            user_roles=user_roles,
            PubLeagueOrderStatus=PubLeagueOrderStatus,
            premier_product_slug=premier_product_slug,
            classic_product_slug=classic_product_slug,
            now=datetime.utcnow()
        )

    except Exception as e:
        logger.error(f"Error loading pub league orders: {e}", exc_info=True)
        return render_template(
            'admin/pub_league_orders_flowbite.html',
            title='Pub League Orders',
            orders=None,
            stats={},
            revenue=None,
            error=str(e),
            season_filter='current',
            selected_season_id=None,
            season_options=[],
            current_season=None,
            current_season_ids=[],
            current_season_label='',
            sort=DEFAULT_SORT,
            division_filter='all',
            user_roles=[],
            now=datetime.utcnow()
        )


def _apply_order_export_filters(query, filters):
    """Apply the shared status/search/season/division scope to an export query.

    Shared by the order rows and the per-order jersey-size aggregate so the two
    can never disagree about which orders are in scope. The division/season
    conditions are correlated on PubLeagueOrder, so any query that selects from
    (or joins to) PubLeagueOrder can use this.
    """
    if filters['status_filter'] != 'all':
        query = query.filter(PubLeagueOrder.status == filters['status_filter'])
    else:
        query = query.filter(PubLeagueOrder.status != PubLeagueOrderStatus.CANCELLED.value)
    if filters['search']:
        search_term = f"%{filters['search']}%"
        query = query.filter(
            or_(
                PubLeagueOrder.customer_name.ilike(search_term),
                PubLeagueOrder.customer_email.ilike(search_term),
                PubLeagueOrder.woo_order_id.cast(db.String).ilike(search_term)
            )
        )
    if filters['season_condition'] is not None:
        query = query.filter(filters['season_condition'])
    if filters['division_condition'] is not None:
        query = query.filter(filters['division_condition'])
    return query


def _money(value):
    """Format a Decimal/None as a plain grouped amount: 1234.5 -> '1,234.50'."""
    return f'{(value or 0):,.2f}'


_CURRENCY_SYMBOLS = {'USD': '$', 'CAD': 'CA$', 'EUR': '€', 'GBP': '£'}


def _revenue_stats(filters):
    """Money in for the CURRENTLY FILTERED orders, overall and per division.

    Reads the denormalised `amount_paid` / `amount_list` columns rather than
    re-parsing `woo_order_data`, so a season total is one grouped aggregate
    instead of a few hundred JSON blobs loaded into the web process.

    Scoped through `_apply_order_export_filters`, the SAME helper the list and
    the CSV exports use, so the revenue cards can never describe a different set
    of orders than the rows underneath them. That helper also drops cancelled
    orders unless they are explicitly filtered for, which is what keeps a
    cancelled sale out of the revenue figure.

    `paid` is Woo's line `total` (AFTER coupons), so an ECS member's $35 Summer
    Sprint pass counts as $35, not $40 -- that is the "actual money in" number.
    `list_` is the pre-coupon `subtotal`, and the gap between them is reported
    as `discount`.

    ⚠️ `unpriced` is load-bearing, not a curiosity. A pass whose amount is NULL
    contributes $0 to the sum, so a partly-backfilled table would quietly
    under-report revenue and look like a bad sales season. The template shows a
    warning whenever it is non-zero.
    """
    li = PubLeagueOrderLineItem

    def _scoped(*columns):
        return _apply_order_export_filters(
            db.session.query(*columns).join(
                PubLeagueOrder, li.order_id == PubLeagueOrder.id),
            filters,
        )

    rows = _scoped(
        li.division,
        func.coalesce(func.sum(li.amount_paid), 0),
        func.coalesce(func.sum(li.amount_list), 0),
        func.count(li.id),
        func.count(li.amount_paid),  # counts NON-NULL only -> priced passes
    ).group_by(li.division).all()

    divisions, paid_total, list_total, passes_total, priced_total = [], Decimal('0'), Decimal('0'), 0, 0
    for division, paid, listed, passes, priced in rows:
        paid, listed = Decimal(paid or 0), Decimal(listed or 0)
        divisions.append({
            'division': division or 'Unknown',
            'paid': paid,
            'paid_display': _money(paid),
            'list': listed,
            'discount': listed - paid,
            'discount_display': _money(listed - paid),
            'passes': passes,
            'priced': priced,
            'unpriced': passes - priced,
            # Blank rather than a divide-by-zero guard that reads as $0.00.
            'avg_display': _money(paid / priced) if priced else '',
        })
        paid_total += paid
        list_total += listed
        passes_total += passes
        priced_total += priced

    divisions.sort(key=lambda d: d['paid'], reverse=True)

    # Refunds live on the ORDER, so they are summed over orders. Summing them
    # through the line-item join above would multiply each refund by that
    # order's pass count.
    refunds = _apply_order_export_filters(
        db.session.query(func.coalesce(func.sum(PubLeagueOrder.refund_total), 0)),
        filters,
    ).scalar() or Decimal('0')

    # One currency in practice; if a stray order disagrees, fall back to a bare
    # symbol rather than asserting a wrong one.
    currencies = [c for (c,) in _apply_order_export_filters(
        db.session.query(PubLeagueOrder.currency).distinct(), filters
    ).all() if c]
    currency = currencies[0] if len(currencies) == 1 else None

    return {
        'symbol': _CURRENCY_SYMBOLS.get(currency, '$'),
        'currency': currency,
        'paid': paid_total,
        'paid_display': _money(paid_total),
        'list': list_total,
        'list_display': _money(list_total),
        'discount': list_total - paid_total,
        'discount_display': _money(list_total - paid_total),
        'refunds': refunds,
        'refunds_display': _money(refunds),
        'net_display': _money(paid_total - Decimal(refunds or 0)),
        'passes': passes_total,
        'priced': priced_total,
        'unpriced': passes_total - priced_total,
        'avg_display': _money(paid_total / priced_total) if priced_total else '',
        'divisions': divisions,
    }


# Smallest-to-largest so the jersey column reads like a size run rather than
# alphabetically ("AL, AM, AS"). Mirrors the size vocabulary the registration
# form offers (W* women's, A* adult); bare S/M/L cover legacy rows. Sizes
# outside this list (a new Woo variation) sort to the end alphabetically
# instead of being dropped.
_JERSEY_SIZE_ORDER = [
    'WXS', 'WS', 'WM', 'WL', 'WXL', 'WXXL',
    'AXS', 'AS', 'AM', 'AL', 'AXL', 'AXXL', 'A3XL', 'A4XL',
    'XS', 'S', 'M', 'L', 'XL', 'XXL', '2XL', 'XXXL', '3XL',
]


def _format_jersey_sizes(size_counts):
    """Render [(size, count), ...] as "S, M x2, XL".

    Count is only shown when an order has more than one pass in that size.
    Passes whose Woo product name carried no parseable size land as NULL and
    render as "Unknown" rather than vanishing, so the listed sizes always
    account for every pass on the order.
    """
    def _key(item):
        size = (item[0] or '').upper()
        try:
            return (_JERSEY_SIZE_ORDER.index(size), '')
        except ValueError:
            return (len(_JERSEY_SIZE_ORDER), size)

    parts = []
    for size, count in sorted(size_counts, key=_key):
        label = size or 'Unknown'
        parts.append(f'{label} x{count}' if count > 1 else label)
    return ', '.join(parts)


@pub_league_orders_admin_bp.route('/pub-league-orders/export-emails')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def export_order_emails():
    """
    Export customer emails for the currently filtered order list as CSV.

    Honors the same status/search/season query params as the list view, so
    e.g. ?status=not_started exports exactly the orders shown on that tab.
    Cancelled orders are excluded unless explicitly filtered to cancelled.
    Emails are deduped (one row per address).

    The jersey_sizes column comes from the ORDER's own line items (the size
    extracted from the WooCommerce variation the customer bought), NOT from
    Player.jersey_size — profile sizes drift, and an unlinked pass has no
    player attached at all.
    """
    import csv

    filters = _parse_order_filters()

    query = _apply_order_export_filters(db.session.query(PubLeagueOrder), filters)

    # Always dedup by NEWEST order per email (created_at desc), independent of
    # the list's display sort. The CSV is for mail-merge, so row order doesn't
    # matter — but which order supplies a duplicate-email customer's status/pass
    # counts must be deterministic, not a side effect of the active sort.
    orders = query.order_by(desc(PubLeagueOrder.created_at), desc(PubLeagueOrder.id)).all()

    # One grouped pass over the in-scope line items instead of touching the
    # lazy='dynamic' line_items relationship per order (that would be a query
    # per row). Filtered by the same scope so it stays a bounded aggregate.
    size_rows = _apply_order_export_filters(
        db.session.query(
            PubLeagueOrderLineItem.order_id,
            PubLeagueOrderLineItem.jersey_size,
            func.count(PubLeagueOrderLineItem.id),
        ).join(PubLeagueOrder, PubLeagueOrderLineItem.order_id == PubLeagueOrder.id),
        filters,
    ).group_by(
        PubLeagueOrderLineItem.order_id, PubLeagueOrderLineItem.jersey_size
    ).all()

    sizes_by_order = {}
    for order_id, jersey_size, count in size_rows:
        sizes_by_order.setdefault(order_id, []).append((jersey_size, count))

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        'name', 'email', 'woo_order_id', 'status', 'season',
        'linked_passes', 'total_passes', 'jersey_sizes',
    ])
    seen = set()
    for o in orders:
        email = (o.customer_email or '').strip()
        if not email or email.lower() in seen:
            continue
        seen.add(email.lower())
        writer.writerow([
            o.customer_name or '', email, o.woo_order_id, o.status,
            o.season_name or '', o.linked_passes, o.total_passes,
            _format_jersey_sizes(sizes_by_order.get(o.id, [])),
        ])

    status_slug = filters['status_filter']
    season_slug = filters['season_filter']
    filename = f'pub-league-order-emails-{season_slug}-{status_slug}.csv'
    # utf-8-sig so Excel detects the encoding
    return send_file(
        io.BytesIO(buf.getvalue().encode('utf-8-sig')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=filename,
    )


@pub_league_orders_admin_bp.route('/pub-league-orders/export-revenue')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def export_order_revenue():
    """Export money-in for the currently filtered orders as CSV.

    Two sections in one file, because the two questions ("what did we take in
    per league" and "which order was that") are always asked together and a
    single download beats reconciling two:

      1. A per-division summary, plus a TOTAL row.
      2. One row per ORDER with its own paid/list/discount figures.

    Honors the same status/search/season/division params as the list, so the
    Summer Sprint view exports Summer Sprint money.

    Amounts are per-PASS sums (`amount_paid`, from Woo's post-coupon line
    total), NOT `order_total` -- an order that also contained merch would
    otherwise report the scarf as league revenue. `order_total` is included as
    its own column precisely so the difference is visible rather than guessed
    at.

    Unlike the email export, rows are NOT deduped by customer: this is a money
    report, and dropping a repeat buyer's second order would drop its revenue.
    """
    import csv

    filters = _parse_order_filters()
    revenue = _revenue_stats(filters)
    li = PubLeagueOrderLineItem

    # Per-order money, aggregated in SQL so this stays one query rather than
    # touching each order's lazy='dynamic' line_items relationship.
    order_rows = _apply_order_export_filters(
        db.session.query(
            PubLeagueOrder,
            func.coalesce(func.sum(li.amount_paid), 0),
            func.coalesce(func.sum(li.amount_list), 0),
            func.count(li.id),
            func.count(li.amount_paid),
            func.string_agg(distinct(li.division), ', '),
        ).outerjoin(li, li.order_id == PubLeagueOrder.id),
        filters,
    ).group_by(PubLeagueOrder.id).order_by(
        desc(PubLeagueOrder.created_at), desc(PubLeagueOrder.id)
    ).all()

    buf = io.StringIO()
    writer = csv.writer(buf)

    writer.writerow(['REVENUE BY LEAGUE'])
    writer.writerow(['league', 'passes', 'money_in', 'at_list_price',
                     'discounts', 'avg_per_pass', 'unpriced_passes'])
    for d in revenue['divisions']:
        writer.writerow([
            d['division'], d['passes'], _money(d['paid']), _money(d['list']),
            _money(d['discount']), d['avg_display'], d['unpriced'],
        ])
    writer.writerow([
        'TOTAL', revenue['passes'], revenue['paid_display'],
        _money(revenue['list']), revenue['discount_display'],
        revenue['avg_display'], revenue['unpriced'],
    ])
    writer.writerow(['REFUNDED', '', revenue['refunds_display']])
    writer.writerow(['NET OF REFUNDS', '', revenue['net_display']])
    writer.writerow([])

    writer.writerow(['ORDERS'])
    writer.writerow([
        'woo_order_id', 'date', 'name', 'email', 'status', 'season', 'leagues',
        'passes', 'money_in', 'at_list_price', 'discount', 'refunded',
        'woo_order_total', 'currency', 'unpriced_passes',
    ])
    for order, paid, listed, passes, priced, divisions in order_rows:
        writer.writerow([
            order.woo_order_id,
            order.created_at.strftime('%Y-%m-%d') if order.created_at else '',
            order.customer_name or '',
            order.customer_email or '',
            order.status,
            order.season_name or '',
            divisions or '',
            passes,
            _money(paid),
            _money(listed),
            _money(Decimal(listed or 0) - Decimal(paid or 0)),
            _money(order.refund_total) if order.refund_total else '',
            _money(order.order_total) if order.order_total is not None else '',
            order.currency or '',
            passes - priced,
        ])

    filename = (f'pub-league-revenue-{filters["season_filter"]}'
                f'-{filters["division_filter"]}-{filters["status_filter"]}.csv')
    return send_file(
        io.BytesIO(buf.getvalue().encode('utf-8-sig')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=filename,
    )


@pub_league_orders_admin_bp.route('/pub-league-orders/<int:order_id>')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def order_detail(order_id):
    """Display detailed view of a specific Pub League order."""
    try:
        # Note: line_items uses lazy='dynamic' so we query it separately
        order = db.session.query(PubLeagueOrder).options(
            joinedload(PubLeagueOrder.primary_user)
        ).filter_by(id=order_id).first_or_404()

        # Eager load line items with their relationships
        # Since line_items is dynamic, we need to query them separately
        line_items = order.line_items.options(
            joinedload(PubLeagueOrderLineItem.assigned_player),
            joinedload(PubLeagueOrderLineItem.assigned_user),
            joinedload(PubLeagueOrderLineItem.wallet_pass)
        ).all()

        # Get all claims for this order
        claims = db.session.query(PubLeagueOrderClaim).options(
            joinedload(PubLeagueOrderClaim.line_item),
            joinedload(PubLeagueOrderClaim.created_by),
            joinedload(PubLeagueOrderClaim.claimed_by_player),
            joinedload(PubLeagueOrderClaim.claimed_by_user)
        ).filter_by(order_id=order_id).order_by(desc(PubLeagueOrderClaim.created_at)).all()

        # Get user roles for template
        user_roles = [role.name for role in safe_current_user.roles] if safe_current_user.is_authenticated else []

        # Real jersey sizes actually in use — same source as the player profile
        # form and the link-order wizard, so the edit dropdown here can't drift
        # from a hardcoded XS/SM/… list that doesn't match reality. Fold in any
        # size already on this order's line items so it stays selectable even if
        # no existing player currently uses it.
        jersey_size_choices = sorted({
            r[0] for r in db.session.query(Player.jersey_size).distinct().all() if r[0]
        } | {li.jersey_size for li in line_items if li.jersey_size})

        return render_template(
            'admin/pub_league_order_detail_flowbite.html',
            title=f'Order #{order.woo_order_id}',
            order=order,
            line_items=line_items,
            claims=claims,
            user_roles=user_roles,
            jersey_size_choices=jersey_size_choices,
            PubLeagueOrderStatus=PubLeagueOrderStatus,
            PubLeagueLineItemStatus=PubLeagueLineItemStatus,
            PubLeagueClaimStatus=PubLeagueClaimStatus
        )

    except Exception as e:
        logger.error(f"Error loading pub league order {order_id}: {e}", exc_info=True)
        from flask import redirect, flash
        flash('Failed to load order details.', 'error')
        return redirect(url_for('pub_league_orders_admin.orders_list'))


@pub_league_orders_admin_bp.route('/pub-league-orders/api/search-players')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def api_search_players():
    """Search for players to manually assign passes to."""
    query = request.args.get('q', '').strip()
    suggest_for = request.args.get('suggest_for', '').strip()

    def _format_player(player):
        """Format a player for JSON response."""
        user = player.user
        return {
            'player_id': player.id,
            'user_id': user.id if user else None,
            'name': player.name,
            'discord_username': player.discord_username,
            'email_hint': _mask_email(user.email) if user and hasattr(user, 'email') and user.email else None,
            'is_current_player': player.is_current_player,
        }

    # Suggestion mode: search by customer name parts
    if suggest_for and len(query) < 2:
        try:
            name_parts = suggest_for.split()
            conditions = []
            for part in name_parts:
                if len(part) >= 2:
                    conditions.append(Player.name.ilike(f'%{part}%'))

            if conditions:
                players = db.session.query(Player).options(
                    joinedload(Player.user)
                ).filter(or_(*conditions)).limit(10).all()

                # Score by name part matches
                results = []
                for player in players:
                    player_lower = player.name.lower()
                    match_count = sum(1 for part in name_parts if part.lower() in player_lower)
                    results.append((player, match_count))
                results.sort(key=lambda x: x[1], reverse=True)

                return jsonify({
                    'success': True,
                    'players': [_format_player(p) for p, _ in results[:5]],
                    'is_suggestion': True,
                    'suggested_for': suggest_for
                })

            return jsonify({'success': True, 'players': [], 'is_suggestion': True})

        except Exception as e:
            logger.error(f"Error in suggestion search: {e}", exc_info=True)
            return jsonify({'success': False, 'error': 'Internal Server Error'}), 500

    # Normal search mode
    if len(query) < 2:
        return jsonify({'success': True, 'players': []})

    try:
        search_term = f'%{query}%'
        players = db.session.query(Player).options(
            joinedload(Player.user)
        ).filter(
            or_(
                Player.name.ilike(search_term),
                Player.discord_username.ilike(search_term)
            )
        ).limit(10).all()

        results = [_format_player(player) for player in players]

        return jsonify({'success': True, 'players': results})

    except Exception as e:
        logger.error(f"Error searching players: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Internal Server Error'}), 500


@pub_league_orders_admin_bp.route('/pub-league-orders/api/manual-link', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def api_manual_link():
    """Manually link a pass to a player."""
    data = request.get_json(silent=True) or {}
    line_item_id = data.get('line_item_id')
    player_id = data.get('player_id')

    if not line_item_id or not player_id:
        return jsonify({'success': False, 'error': 'Missing line_item_id or player_id'}), 400

    try:
        # Load on the REQUEST session (g.db_session), not db.session. The
        # services below (link_pass_to_player / activate_player_for_league)
        # commit g.db_session; objects loaded on db.session are a different
        # session's objects, so their changes were never committed — the admin
        # saw "linked", and a refresh showed the pass still unassigned.
        session = getattr(g, 'db_session', db.session)

        line_item = session.query(PubLeagueOrderLineItem).options(
            joinedload(PubLeagueOrderLineItem.order)
        ).filter_by(id=line_item_id).first()

        if not line_item:
            return jsonify({'success': False, 'error': 'Line item not found'}), 404

        player = session.query(Player).options(
            joinedload(Player.user)
        ).filter_by(id=player_id).first()

        if not player:
            return jsonify({'success': False, 'error': 'Player not found'}), 404

        # Reassignment: if this pass is already assigned to someone else, clear
        # the previous holder first. assign_to_player() below increments the
        # order's linked_passes and flips status to assigned, so we mustn't let
        # it double-count — an already-assigned pass keeps the same slot.
        was_assigned = line_item.status != PubLeagueLineItemStatus.UNASSIGNED.value
        previous_name = line_item.assigned_player.name if line_item.assigned_player else None
        previous_player_id = line_item.assigned_player_id
        if was_assigned and line_item.assigned_player_id == player.id:
            return jsonify({'success': False, 'error': 'Pass is already assigned to this player'}), 400
        if was_assigned:
            # Return it to unassigned WITHOUT touching linked_passes (assign
            # re-increments), and drop the old wallet pass so the new holder gets
            # a fresh one rather than the previous holder's.
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
            # still hold another pass for this season. (The new holder is
            # activated below via activate_player_for_league.)
            from app.pub_league.services import PlayerActivationService as _PAS
            _PAS.deactivate_player_if_no_current_pass(
                previous_player_id, line_item.order, exclude_line_item_id=line_item.id
            )

        # Import services
        from app.pub_league.services import PubLeagueOrderService, PlayerActivationService

        # Link the pass. Stamped 'admin' so the orders page shows it was linked
        # by staff (via the name-match suggestion, which can pick the wrong
        # same-named player) rather than confirmed by the buyer themselves.
        user = player.user if player.user_id else None
        player_name = player.name
        PubLeagueOrderService.link_pass_to_player(line_item, player, user, method='admin')

        # Snapshot the response while the link is fresh — activation below is
        # best-effort, and the assignment is already committed either way.
        verb = 'reassigned' if was_assigned else 'linked'
        msg = (f'Pass reassigned from {previous_name} to {player_name}'
               if was_assigned and previous_name else f'Pass linked to {player_name}')
        payload = {
            'success': True,
            'message': msg,
            'line_item': line_item.to_dict()
        }

        # Activate player for the division
        if user:
            try:
                PlayerActivationService.activate_player_for_league(
                    player=player,
                    user=user,
                    division=line_item.division,
                    jersey_size=line_item.jersey_size
                )
            except Exception as e:
                logger.error(
                    f"Activation failed for player {player_id} after admin link of "
                    f"line item {line_item_id} (the pass IS linked): {e}", exc_info=True
                )
                session.rollback()
                payload['message'] = (
                    f'{msg}, but activating them for the season failed — '
                    'their pass is linked; re-run the link to activate.'
                )

        logger.info(
            f"Admin {current_user.id} {verb} line item {line_item_id} to player {player_id}"
            + (f" (was {previous_name})" if previous_name else "")
        )

        return jsonify(payload)

    except Exception as e:
        logger.error(f"Error manually linking pass: {e}", exc_info=True)
        try:
            getattr(g, 'db_session', db.session).rollback()
        except Exception:
            pass
        return jsonify({'success': False, 'error': 'Internal Server Error'}), 500


def _division_form_value(division):
    """`League.name` on a line item -> the approval form value for that program.

    'Summer Sprint' -> 'pl_third'. Returns (form_value, label) or (None, None)
    when the division resolves to no program — in which case we must NOT guess,
    because approving into the wrong league is silent data corruption that
    nothing downstream flags.
    """
    if not division:
        return None, None
    try:
        from app.services import program_registry
        pr = program_registry.by_league_name(division)
        if pr is None:
            return None, None
        return (pr.form_value or pr.membership_lane), (pr.display_name or pr.league_name)
    except Exception:
        logger.warning("could not resolve division %r to a program", division, exc_info=True)
        return None, None


@pub_league_orders_admin_bp.route('/pub-league-orders/api/player-limbo', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def api_player_limbo():
    """Report the "limbo" states of the player a pass was just assigned to.

    Buying a pass and being CLEARED TO PLAY are deliberately separate axes — we
    refund people who turn out not to be a good fit — so nothing here is applied
    automatically and this endpoint writes nothing at all. It only answers "what
    is inconsistent about this person now that they hold a pass?", so the admin
    doing a manual assignment can fix it in the same breath instead of leaving
    them pending/waitlisted forever with a paid pass.

    Read-only by design: the companion `api_resolve_limbo` does the writing, and
    only for the boxes the admin actually ticked.
    """
    data = request.get_json(silent=True) or {}
    player_id = data.get('player_id')
    line_item_id = data.get('line_item_id')

    if not player_id:
        return jsonify({'success': False, 'error': 'Missing player_id'}), 400

    try:
        from app.models import Role
        from app.models.substitutes import SubstitutePool

        session = getattr(g, 'db_session', db.session)

        player = session.query(Player).options(
            joinedload(Player.user)
        ).filter_by(id=player_id).first()
        if not player:
            return jsonify({'success': False, 'error': 'Player not found'}), 404

        line_item = None
        if line_item_id:
            line_item = session.query(PubLeagueOrderLineItem).options(
                joinedload(PubLeagueOrderLineItem.order)
            ).filter_by(id=line_item_id).first()

        division = line_item.division if line_item else None
        form_value, division_label = _division_form_value(division)

        user = player.user if player.user_id else None
        actions, notes = [], []

        if user is None:
            # Nothing here is actionable without an account: approval, roles and
            # the waitlist all hang off User, not Player.
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

        # Informational only. A pending quick profile can't be claimed BY an
        # admin — the person claims it themselves — so this is a note, not an action.
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

        return jsonify({
            'success': True,
            'player_name': player.name,
            'division': division,
            'actions': actions,
            'notes': notes,
        })

    except Exception as e:
        logger.error(f"Error checking player limbo: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Internal Server Error'}), 500


@pub_league_orders_admin_bp.route('/pub-league-orders/api/resolve-limbo', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def api_resolve_limbo():
    """Apply ONLY the limbo fixes the admin explicitly ticked.

    An empty `actions` list is a valid, successful no-op — "none" is one of the
    choices, and it must not be harder than the others.

    ⚠️ SESSION: `apply_approval` mutates and expects `db.session` throughout.
    The rest of this blueprint works on `g.db_session`, which is a DIFFERENT
    session in this app. Everything here therefore stays on `db.session` and
    commits it — mixing the two is the silently-discarded-write bug.
    """
    data = request.get_json(silent=True) or {}
    player_id = data.get('player_id')
    actions = data.get('actions') or []
    approve_value = data.get('approve_value')

    if not player_id:
        return jsonify({'success': False, 'error': 'Missing player_id'}), 400
    if not isinstance(actions, list):
        return jsonify({'success': False, 'error': 'actions must be a list'}), 400
    if not actions:
        return jsonify({'success': True, 'applied': [], 'message': 'Nothing changed.'})

    _ALLOWED = {'approve', 'remove_waitlist', 'remove_sub_pools'}
    unknown = [a for a in actions if a not in _ALLOWED]
    if unknown:
        return jsonify({'success': False,
                        'error': f"Unknown action(s): {', '.join(map(str, unknown))}"}), 400

    try:
        from app.models import Role
        from app.models.admin_config import AdminAuditLog
        from app.models.substitutes import SubstitutePool

        player = db.session.query(Player).options(
            joinedload(Player.user)
        ).filter_by(id=player_id).first()
        if not player:
            return jsonify({'success': False, 'error': 'Player not found'}), 404
        user = player.user if player.user_id else None

        applied, failed = [], []
        approved_here = False

        if 'approve' in actions:
            from app.admin_panel.routes.user_management.approvals import apply_approval
            # ⚠️ approve_league_types lives in integrity_service, NOT in approvals —
            # approvals only imports it inside a function body, so importing it
            # from there raises ImportError at request time.
            from app.services.integrity_service import approve_league_types
            if user is None:
                failed.append('Approve — no user account linked to this player.')
            elif not approve_value:
                failed.append('Approve — no league was resolved for this pass.')
            elif approve_value not in approve_league_types():
                # Validate against the same vocabulary the approvals page uses;
                # never trust a value round-tripped through the browser.
                failed.append(f"Approve — '{approve_value}' is not an approvable league.")
            else:
                prior = (user.approval_status or 'pending')
                try:
                    apply_approval(user, approve_value, approver_id=current_user.id,
                                   notes='Approved from the order page after a pass was assigned.')
                    AdminAuditLog.log_action(
                        user_id=current_user.id, action='approve_user',
                        resource_type='user_approval', resource_id=str(user.id),
                        old_value=prior, new_value=f'approved:{approve_value}',
                        ip_address=request.remote_addr,
                        user_agent=request.headers.get('User-Agent'))
                    applied.append(f'Approved for {approve_value}')
                    approved_here = True
                except ValueError as ve:
                    failed.append(f'Approve — {ve}')

        # Skipped when approve ran: apply_approval already clears the waitlist,
        # and re-running it would report a change that did not happen.
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

        # The spine is recomputed from the source facts we just changed, so it has
        # to run AFTER the commit above or it recomputes from stale state.
        try:
            from app.services.league_membership_sync import resync_player_memberships
            resync_player_memberships(db.session, player.id)
            db.session.commit()
        except Exception:
            logger.exception("membership resync after limbo resolve failed for player %s",
                             player.id)

        logger.info("Admin %s resolved limbo for player %s: applied=%s failed=%s",
                    current_user.id, player_id, applied, failed)

        return jsonify({
            'success': True,
            'applied': applied,
            'failed': failed,
            'message': ('; '.join(applied) if applied else 'Nothing changed.'),
        })

    except Exception as e:
        logger.error(f"Error resolving player limbo: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Internal Server Error'}), 500


@pub_league_orders_admin_bp.route('/pub-league-orders/api/resend-claim', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def api_resend_claim():
    """Resend claim email to recipient."""
    data = request.get_json(silent=True) or {}
    claim_id = data.get('claim_id')

    if not claim_id:
        return jsonify({'success': False, 'error': 'Missing claim_id'}), 400

    try:
        claim = db.session.query(PubLeagueOrderClaim).options(
            joinedload(PubLeagueOrderClaim.line_item),
            joinedload(PubLeagueOrderClaim.order)
        ).filter_by(id=claim_id).first()

        if not claim:
            return jsonify({'success': False, 'error': 'Claim not found'}), 404

        if not claim.recipient_email:
            return jsonify({'success': False, 'error': 'No recipient email on claim'}), 400

        if claim.status != PubLeagueClaimStatus.PENDING.value:
            return jsonify({'success': False, 'error': 'Claim is not pending'}), 400

        # Send claim email
        from app.pub_league.email_helpers import send_claim_link_email
        line_item = claim.line_item
        order = claim.order

        email_sent = send_claim_link_email(
            recipient_email=claim.recipient_email,
            recipient_name=claim.recipient_name,
            claim_token=claim.claim_token,
            division=line_item.division if line_item else 'Pub League',
            sender_name=order.customer_name if order else 'ECS Pub League',
            expires_at=claim.expires_at
        )

        if email_sent:
            claim.email_sent_at = datetime.utcnow()
            db.session.commit()
            logger.info(f"Admin {current_user.id} resent claim email for claim {claim_id}")
            return jsonify({'success': True, 'message': 'Claim email sent'})
        else:
            return jsonify({'success': False, 'error': 'Failed to send email'}), 500

    except Exception as e:
        logger.error(f"Error resending claim email: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Internal Server Error'}), 500


@pub_league_orders_admin_bp.route('/pub-league-orders/api/cancel-claim', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def api_cancel_claim():
    """Cancel a pending claim."""
    data = request.get_json(silent=True) or {}
    claim_id = data.get('claim_id')

    if not claim_id:
        return jsonify({'success': False, 'error': 'Missing claim_id'}), 400

    try:
        claim = db.session.query(PubLeagueOrderClaim).options(
            joinedload(PubLeagueOrderClaim.line_item)
        ).filter_by(id=claim_id).first()

        if not claim:
            return jsonify({'success': False, 'error': 'Claim not found'}), 404

        if claim.status != PubLeagueClaimStatus.PENDING.value:
            return jsonify({'success': False, 'error': 'Claim is not pending'}), 400

        # Cancel the claim
        claim.status = PubLeagueClaimStatus.CANCELLED.value

        # Unlink from line item if needed
        if claim.line_item:
            claim.line_item.claim_id = None

        db.session.commit()
        logger.info(f"Admin {current_user.id} cancelled claim {claim_id}")

        return jsonify({'success': True, 'message': 'Claim cancelled'})

    except Exception as e:
        logger.error(f"Error cancelling claim: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Internal Server Error'}), 500


@pub_league_orders_admin_bp.route('/pub-league-orders/api/refresh-order', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def api_refresh_order():
    """Refresh order data from WooCommerce."""
    data = request.get_json(silent=True) or {}
    order_id = data.get('order_id')

    if not order_id:
        return jsonify({'success': False, 'error': 'Missing order_id'}), 400

    try:
        order = db.session.query(PubLeagueOrder).filter_by(id=order_id).first()

        if not order:
            return jsonify({'success': False, 'error': 'Order not found'}), 404

        # Fetch fresh data from WooCommerce
        from app.pub_league.services import PubLeagueOrderService
        order_data = PubLeagueOrderService.fetch_order_from_woocommerce(order.woo_order_id)

        if not order_data:
            return jsonify({'success': False, 'error': 'Could not fetch order from WooCommerce'}), 500

        # Update cached data
        order.woo_order_data = order_data

        # Update customer info if changed
        billing = order_data.get('billing', {})
        new_name = f"{billing.get('first_name', '')} {billing.get('last_name', '')}".strip()
        new_email = billing.get('email', '')

        if new_name:
            order.customer_name = new_name
        if new_email:
            order.customer_email = new_email

        # Re-derive the money columns off the FRESH payload. This is the only
        # path that picks up a refund issued after purchase, since the webhook
        # copy is frozen at the moment of sale.
        try:
            from app.pub_league.revenue import apply_order_revenue
            apply_order_revenue(order)
        except Exception as rev_err:
            logger.warning(
                f"Could not refresh revenue for order {order_id}: {rev_err}",
                exc_info=True)

        order.updated_at = datetime.utcnow()
        db.session.commit()

        logger.info(f"Admin {current_user.id} refreshed order {order_id} from WooCommerce")

        return jsonify({
            'success': True,
            'message': 'Order data refreshed from WooCommerce',
            'order': order.to_dict()
        })

    except Exception as e:
        logger.error(f"Error refreshing order: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Internal Server Error'}), 500


@pub_league_orders_admin_bp.route('/pub-league-orders/api/scan-missing', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def api_scan_missing_orders():
    """List paid WooCommerce orders that contain league passes but are NOT here.

    The companion to `api_import_order`: it answers "which order numbers do I
    type in?", which otherwise means reconciling WooCommerce against this page
    by hand.

    It exists because a missed order is invisible from BOTH ends. The Woo
    webhook creates a `PubLeagueOrder` only when a line item resolves to a
    program, so anything bought before its program was registered produced no
    row, no ERROR log, and a 200 back to WooCommerce. Nothing in this app knew
    the sale had happened, so nothing could report it as missing.

    READ-ONLY on purpose. It writes nothing and imports nothing — an admin sees
    the list, recognises the names, and imports deliberately. A scan that
    silently bulk-created orders would be very hard to undo if the parser were
    ever wrong about what counts as a league product.

    Re-runs the CURRENT parser over the LIVE order data, so it reports what
    would happen if these were ingested today, not what happened then.
    """
    data = request.get_json(silent=True) or {}

    try:
        days = int(data.get('days') or 180)
    except (TypeError, ValueError):
        days = 180
    days = max(1, min(days, 730))

    # Hard ceilings, not tuning knobs. Each page is one 5s-timeout HTTP call and
    # this runs inside a web request; unbounded paging is a hung worker.
    per_page, max_pages = 100, 5

    try:
        from woocommerce import API
        from app.pub_league.services import PubLeagueOrderService

        # Release the transaction BEFORE the network calls — same rule as
        # fetch_order_from_woocommerce. PgBouncer runs transaction pooling with
        # a 30s idle-transaction timeout, so holding one open across several
        # WooCommerce round trips gets the connection killed under us.
        for _sess in (getattr(g, 'db_session', None), db.session):
            if _sess is None:
                continue
            try:
                if _sess.new or _sess.dirty or _sess.deleted:
                    continue
                _sess.commit()
            except Exception:
                logger.debug("Could not release transaction before Woo scan", exc_info=True)

        wcapi = API(
            url=current_app.config['WOO_API_URL'],
            consumer_key=current_app.config['WOO_CONSUMER_KEY'],
            consumer_secret=current_app.config['WOO_CONSUMER_SECRET'],
            version="wc/v3",
            timeout=15,
        )

        after = (datetime.utcnow() - timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%S')
        fetched, truncated = [], False
        for page in range(1, max_pages + 1):
            resp = wcapi.get("orders", params={
                # 'any' then filtered below: wc/v3 wants repeated status[] params
                # for a multi-status filter, which does not survive a plain dict.
                'status': 'any', 'after': after,
                'page': page, 'per_page': per_page, 'orderby': 'date', 'order': 'desc',
            })
            resp.raise_for_status()
            batch = resp.json()
            if not isinstance(batch, list) or not batch:
                break
            fetched.extend(batch)
            if len(batch) < per_page:
                break
            if page == max_pages:
                truncated = True

        # Only paid orders can be ingested — fetch_order_from_woocommerce
        # rejects anything else, so listing them would produce import failures.
        paid = [o for o in fetched if o.get('status') in ('processing', 'completed')]

        candidates = {}
        for o in paid:
            woo_id = o.get('id')
            if woo_id is None:
                continue
            items = PubLeagueOrderService.extract_pub_league_items(o)
            if not items:
                continue
            billing = o.get('billing') or {}
            candidates[int(woo_id)] = {
                'woo_order_id': int(woo_id),
                'customer_name': f"{billing.get('first_name', '')} {billing.get('last_name', '')}".strip(),
                'customer_email': billing.get('email', ''),
                'date': (o.get('date_paid') or o.get('date_created') or '')[:10],
                'passes': len(items),
                'divisions': ', '.join(sorted({i['division'] for i in items if i.get('division')})),
            }

        known = set()
        if candidates:
            session = getattr(g, 'db_session', db.session)
            known = {
                wid for (wid,) in session.query(PubLeagueOrder.woo_order_id)
                .filter(PubLeagueOrder.woo_order_id.in_(list(candidates)))
                .all()
            }

        missing = [candidates[w] for w in sorted(candidates) if w not in known]
        missing.sort(key=lambda m: m['date'], reverse=True)

        logger.info(f"Admin {current_user.id} scanned {len(paid)} paid Woo orders "
                    f"({days}d): {len(candidates)} with passes, {len(missing)} missing")

        return jsonify({
            'success': True,
            'missing': missing,
            'scanned': len(paid),
            'with_passes': len(candidates),
            # Surfaced so "0 missing" can never quietly mean "we stopped looking".
            'truncated': truncated,
            'days': days,
        })

    except Exception as e:
        logger.error(f"Error scanning WooCommerce for missing orders: {e}", exc_info=True)
        return jsonify({'success': False,
                        'error': 'Could not reach WooCommerce or read its response.'}), 502


@pub_league_orders_admin_bp.route('/pub-league-orders/api/import-order', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def api_import_order():
    """Pull one WooCommerce order into the system by its Woo order number.

    This is the recovery path for a sale that was never ingested at all.

    The Woo webhook creates a `PubLeagueOrder` only `if pub_league_items` — i.e.
    only when a line item resolves to a division. Before a program was in the
    registry (or while it was still `is_active = FALSE`), a purchase of ITS
    product resolved to nothing, so the webhook created NO order row, logged
    nothing at ERROR, and returned 200 to WooCommerce. The sale simply did not
    exist here, and there was no admin surface that could bring it in: every
    other action on this page starts from an order row that is already present,
    and the buyer-facing claim link 302s to the homepage for the same reason.

    Now that the registry resolves the product, re-running the same ingest
    against the live Woo order fills the gap. Idempotent: `create_or_get_order`
    returns the existing row untouched if the order is already here, so this is
    safe to retry and safe to run over a list of order numbers.
    """
    data = request.get_json(silent=True) or {}
    raw = str(data.get('woo_order_id') or '').strip().lstrip('#')

    if not raw.isdigit():
        return jsonify({'success': False, 'error': 'Enter a WooCommerce order number.'}), 400
    woo_order_id = int(raw)

    # ⚠️ `create_or_get_order` writes on `g.db_session`, not `db.session` — this
    # app has two independent sessionmakers. Reading on one and committing the
    # other is the silently-discarded-write bug, so do the whole thing on the
    # session the service itself will use.
    session = getattr(g, 'db_session', db.session)

    try:
        from app.pub_league.services import PubLeagueOrderService

        existing = session.query(PubLeagueOrder).filter_by(woo_order_id=woo_order_id).first()
        if existing:
            return jsonify({
                'success': True,
                'already_existed': True,
                'message': f'Order #{woo_order_id} is already here.',
                'order_url': url_for('pub_league_orders_admin.order_detail', order_id=existing.id),
            })

        order_data = PubLeagueOrderService.fetch_order_from_woocommerce(woo_order_id)
        if not order_data:
            # fetch_order_from_woocommerce also returns None for an order that
            # exists but is not paid (it requires processing/completed), so say
            # both things rather than asserting the order does not exist.
            return jsonify({
                'success': False,
                'error': f'WooCommerce returned nothing for #{woo_order_id}. '
                         'Check the number, and that the order is paid '
                         '(processing or completed).'
            }), 404

        order = PubLeagueOrderService.create_or_get_order(woo_order_id, order_data)
        session.commit()

        # total_passes == 0 means the products on this order matched no program.
        # That is the ONLY outcome that still needs a human, so it is reported as
        # a distinct, non-silent result instead of a cheerful "imported".
        if not order.total_passes:
            return jsonify({
                'success': True,
                'no_passes': True,
                'message': f'Order #{woo_order_id} was imported, but none of its '
                           'products matched a program — nobody was granted a pass. '
                           "Check the program's woo_name_pattern against the product title.",
                'order_url': url_for('pub_league_orders_admin.order_detail', order_id=order.id),
            })

        logger.info(f"Admin {current_user.id} imported Woo order {woo_order_id} "
                    f"({order.total_passes} passes)")
        return jsonify({
            'success': True,
            'message': f'Imported order #{woo_order_id} — {order.total_passes} pass'
                       f'{"es" if order.total_passes != 1 else ""}.',
            'order_url': url_for('pub_league_orders_admin.order_detail', order_id=order.id),
        })

    except Exception as e:
        logger.error(f"Error importing Woo order {woo_order_id}: {e}", exc_info=True)
        session.rollback()
        return jsonify({'success': False, 'error': 'Internal Server Error'}), 500


@pub_league_orders_admin_bp.route('/pub-league-orders/api/delete-order', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def api_delete_order():
    """Delete an entire Pub League order and all its line items and claims."""
    data = request.get_json(silent=True) or {}
    order_id = data.get('order_id')

    if not order_id:
        return jsonify({'success': False, 'error': 'Missing order_id'}), 400

    try:
        order = db.session.query(PubLeagueOrder).filter_by(id=order_id).first()

        if not order:
            return jsonify({'success': False, 'error': 'Order not found'}), 404

        woo_order_id = order.woo_order_id

        # Delete all claims for this order
        db.session.query(PubLeagueOrderClaim).filter_by(order_id=order_id).delete()

        # Delete all line items for this order
        db.session.query(PubLeagueOrderLineItem).filter_by(order_id=order_id).delete()

        # Delete the order itself
        db.session.delete(order)
        db.session.commit()

        logger.info(f"Admin {current_user.id} deleted pub league order {order_id} (WooCommerce #{woo_order_id})")

        return jsonify({
            'success': True,
            'message': f'Order #{woo_order_id} deleted successfully'
        })

    except Exception as e:
        logger.error(f"Error deleting order: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Internal Server Error'}), 500


@pub_league_orders_admin_bp.route('/pub-league-orders/api/unassign-pass', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def api_unassign_pass():
    """Unassign a pass from a player (make it available again)."""
    data = request.get_json(silent=True) or {}
    line_item_id = data.get('line_item_id')

    if not line_item_id:
        return jsonify({'success': False, 'error': 'Missing line_item_id'}), 400

    try:
        line_item = db.session.query(PubLeagueOrderLineItem).options(
            joinedload(PubLeagueOrderLineItem.order),
            joinedload(PubLeagueOrderLineItem.assigned_player)
        ).filter_by(id=line_item_id).first()

        if not line_item:
            return jsonify({'success': False, 'error': 'Line item not found'}), 404

        if line_item.status == PubLeagueLineItemStatus.UNASSIGNED.value:
            return jsonify({'success': False, 'error': 'Pass is already unassigned'}), 400

        old_player_name = line_item.assigned_player.name if line_item.assigned_player else 'Unknown'
        old_player_id = line_item.assigned_player_id
        order = line_item.order

        # Clear assignment AND the generated wallet pass. Clearing the pass link
        # matters: generate-pass short-circuits on a non-null wallet_pass_id and
        # returns the OLD pass, so without this a re-linked line item would never
        # mint a fresh pass — it'd hand back the previous holder's. This returns
        # the line item to a truly clean unassigned state (the right behaviour for
        # both a real reassignment and re-testing the flow).
        line_item.assigned_player_id = None
        line_item.assigned_user_id = None
        line_item.assigned_at = None
        line_item.wallet_pass_id = None
        line_item.pass_created_at = None
        line_item.link_method = None
        line_item.link_confirmed_at = None
        line_item.status = PubLeagueLineItemStatus.UNASSIGNED.value

        # Update order linked count
        if order:
            order.linked_passes = max(0, order.linked_passes - 1)
            order.update_status()

        db.session.commit()

        # A pass is what makes a player current for the season, so removing it
        # deactivates them — UNLESS they still hold another pass for this season
        # (e.g. they own two). Only touches is_current_player, mirroring rollover.
        from app.pub_league.services import PlayerActivationService
        deactivated = PlayerActivationService.deactivate_player_if_no_current_pass(
            old_player_id, order, exclude_line_item_id=line_item.id
        )

        logger.info(
            f"Admin {current_user.id} unassigned line item {line_item_id} "
            f"(was {old_player_name}); player deactivated={deactivated}"
        )

        msg = f'Pass unassigned from {old_player_name}'
        if deactivated:
            msg += ' (no longer active for the season)'
        return jsonify({'success': True, 'message': msg})

    except Exception as e:
        logger.error(f"Error unassigning pass: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Internal Server Error'}), 500


@pub_league_orders_admin_bp.route('/pub-league-orders/api/update-line-item', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def api_update_line_item():
    """Update a line item's division or jersey size."""
    data = request.get_json(silent=True) or {}
    line_item_id = data.get('line_item_id')
    division = data.get('division')
    jersey_size = data.get('jersey_size')

    if not line_item_id:
        return jsonify({'success': False, 'error': 'Missing line_item_id'}), 400

    try:
        line_item = db.session.query(PubLeagueOrderLineItem).filter_by(id=line_item_id).first()

        if not line_item:
            return jsonify({'success': False, 'error': 'Line item not found'}), 404

        changes = []

        if division is not None and division != line_item.division:
            if division not in ['Classic', 'Premier', '']:
                return jsonify({'success': False, 'error': 'Invalid division'}), 400
            old_division = line_item.division
            line_item.division = division if division else None
            changes.append(f"division: {old_division} → {division or 'None'}")

        if jersey_size is not None and jersey_size != line_item.jersey_size:
            old_size = line_item.jersey_size
            line_item.jersey_size = jersey_size if jersey_size else None
            changes.append(f"size: {old_size} → {jersey_size or 'None'}")

        if not changes:
            return jsonify({'success': True, 'message': 'No changes made'})

        db.session.commit()

        logger.info(f"Admin {current_user.id} updated line item {line_item_id}: {', '.join(changes)}")

        return jsonify({
            'success': True,
            'message': f'Updated: {", ".join(changes)}'
        })

    except Exception as e:
        logger.error(f"Error updating line item: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Internal Server Error'}), 500


def _mask_email(email: str) -> str:
    """Mask an email for display (e.g., j***@example.com)."""
    if not email or '@' not in email:
        return None

    local, domain = email.split('@', 1)
    if len(local) <= 2:
        masked_local = local[0] + '*'
    else:
        masked_local = local[0] + '*' * (len(local) - 2) + local[-1]

    return f"{masked_local}@{domain}"


# ============================================================================
# Pre-season party QR codes
# ============================================================================
#
# Passes sell out in about an hour, and first access is earned by showing up to
# the pre-season party. These render the QR you put on the wall / on the table
# at the party. Scanning it opens the app for anyone who has it (and the browser
# for anyone who doesn't), then drops them straight into WooCommerce's own
# checkout — which is where the presale password gate and the card form live.
#
# There is deliberately NO "buy a pass" button inside the app: access to the
# purchase is the thing being rationed, so the QR (and later the public on-sale
# link) is the only way in.

def _buy_url(division: str = None) -> str:
    """
    The Universal Link a QR encodes — a PLAIN /pub-league/buy.

    Deliberately carries NO season and NO product id — only (optionally) the
    division. Everything else is resolved at scan time from whichever Pub League
    season is is_current. That means ONE printed QR survives every rollover:
    scan it this season and it lands on the 2026-fall product, scan the same
    code next season and it lands on 2027-spring.

    Crucially it must NOT carry src=app. The QR serves BOTH populations:
      * App installed -> the OS opens the app (it claims /pub-league/buy*). The
        app shows a native picker and, when it opens WooCommerce checkout, adds
        src=app ITSELF (via buy-options' checkout_url) so the post-payment
        redirect bounces back into the app.
      * No app -> the browser opens the web picker and the whole purchase stays
        in the browser.
    If the QR itself carried src=app, a browser-only buyer would get the
    app-return cookie set and, after paying, be bounced to ecs-fc-scheme:// —
    which does nothing without the app, stranding them on an interstitial. So
    src=app is added by the APP, never baked into the shared QR.
    """
    kwargs = {'_external': True}
    if division:
        kwargs['division'] = division
    return url_for('pub_league.buy', **kwargs)


def _qr_slug(division: str = None) -> str:
    """Filename stem for a downloaded code, e.g. ecs-pub-league-2026-fall-premier."""
    from app.pub_league.services import ProductUrlService

    season = (ProductUrlService.get_current_season_name() or '').strip().lower()
    parts = ['ecs-pub-league'] + season.split() + ([division] if division else [])
    stem = '-'.join(p for p in parts if p)
    return re.sub(r'[^a-z0-9-]', '', stem) or 'ecs-pub-league-qr'


@pub_league_orders_admin_bp.route('/pub-league-orders/qr.png')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def buy_qr_png():
    """
    PNG QR for the buy link.

    No ?division= -> the ONE code for the party: it lands on the division picker.
    ?division=classic|premier -> a code that skips straight to that division,
    for when you want a separate sign at each table.

    ?style=plain -> stock black squares instead of the branded crest version.
    The branded one is measured to scan just as reliably (see app/pub_league/
    qr_image.py), but plain stays available for a bad printer or a fussy scanner.
    ?download=1 -> save it with a sensible filename instead of rendering inline,
    so it can be dropped straight into Discord or handed to a print shop.
    """
    from app.pub_league.qr_image import render_qr_png

    division = (request.args.get('division') or '').lower() or None
    if division and division not in ('classic', 'premier'):
        abort(404)

    style = 'plain' if request.args.get('style') == 'plain' else 'brand'

    png = render_qr_png(_buy_url(division), style)

    response = send_file(
        io.BytesIO(png),
        mimetype='image/png',
        as_attachment=bool(request.args.get('download')),
        download_name='%s-qr%s.png' % (_qr_slug(division), '-plain' if style == 'plain' else ''),
    )
    # The codes are stable for a whole season, but they DO re-resolve on rollover,
    # so let a browser reuse one for an hour and no longer.
    response.headers['Cache-Control'] = 'private, max-age=3600'
    return response


def _qr_codes(style: str = 'brand'):
    """
    The codes on offer, in the order they're shown: the picker first (the one
    code for the party), then the per-division ones. Shared by the admin page,
    the display screen and the print sheet so the three can't drift apart.
    """
    from app.pub_league.services import ProductUrlService

    season_name = ProductUrlService.get_current_season_name()
    options = ProductUrlService.get_buy_options(season_name)

    def png(division=None):
        return url_for(
            'pub_league_orders_admin.buy_qr_png',
            division=division, style=style if style == 'plain' else None,
        )

    codes = [{
        'id': 'picker',
        'name': 'Season Pass',
        'division': None,
        'tagline': "You'll pick Classic or Premier after scanning",
        'buy_url': _buy_url(),
        'qr_png': png(),
        # The picker only dead-ends if BOTH divisions fail to resolve.
        'product_url': next((o['product_url'] for o in options if o['product_url']), None),
        'slug_override': None,
    }]

    codes += [{
        'id': option['division'],
        'name': '%s Division' % option['name'],
        'division': option['division'],
        # Says what this code does that the picker doesn't, rather than repeating
        # the "Scan to buy your pass" headline it sits under.
        'tagline': 'Goes straight to %s — no division picker' % option['name'],
        'buy_url': _buy_url(option['division']),
        'qr_png': png(option['division']),
        # Surfaced so an admin sees at a glance whether the product slug actually
        # resolves. A missing one means the QR dead-ends, and the party is the
        # worst possible place to discover that.
        'product_url': option['product_url'],
        # A hardcoded slug pins the link to ONE product and will NOT follow the
        # next rollover — the whole point of the QR is that it does.
        'slug_override': option['slug_override'],
    } for option in options]

    return season_name, codes


@pub_league_orders_admin_bp.route('/pub-league-orders/qr')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def buy_qr_print():
    """The admin page: preview the codes, show one on a screen, share or print."""
    from app.routes.app_links import _season_pass_deeplinks_enabled

    style = 'plain' if request.args.get('style') == 'plain' else 'brand'
    season_name, codes = _qr_codes(style)

    return render_template(
        'admin/pub_league_buy_qr.html',
        season_name=season_name,
        codes=codes,
        style=style,
        any_available=any(c['product_url'] for c in codes),
        deeplinks_enabled=_season_pass_deeplinks_enabled(),
    )


@pub_league_orders_admin_bp.route('/pub-league-orders/qr/sheet')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def buy_qr_sheet():
    """
    The print sheet: one full-page poster per selected code, and NOTHING else.

    A standalone document rather than a print stylesheet over the admin page,
    because the admin page is wrapped in the panel shell (sidebar, topbar,
    breadcrumbs) and "print" there meant printing the furniture too. This route
    renders only posters, so what you see in the print preview is what comes out.

    ?codes=picker,classic,premier picks which posters; ?style=plain drops the
    branding for an unhappy printer.
    """
    style = 'plain' if request.args.get('style') == 'plain' else 'brand'
    season_name, codes = _qr_codes(style)

    wanted = [c for c in (request.args.get('codes') or 'picker').split(',') if c]
    selected = [c for c in codes if c['id'] in wanted and c['product_url']]
    if not selected:
        # Nothing printable was asked for (or every product URL is dead) — send
        # them back to the page, which explains why, rather than printing blanks.
        return redirect(url_for('pub_league_orders_admin.buy_qr_print'))

    return render_template(
        'admin/pub_league_buy_qr_sheet.html',
        season_name=season_name,
        codes=selected,
        style=style,
    )


@pub_league_orders_admin_bp.route('/pub-league-orders/qr/toggle-deeplinks', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def toggle_deeplinks():
    """
    Flip the iOS season-pass deep-link switch (season_pass_deeplinks_enabled).

    OFF (default): the season-pass URLs open in the phone BROWSER for everyone —
    the reliable baseline that works on any phone, app or no app.
    ON: iOS routes those URLs into the native app. Turn this on ONLY once the
    season-pass app build is LIVE in the App Store — see the warning on the page
    and the docstring in app/routes/app_links.py. (Android is unaffected; it's
    gated by the app's own intent filters, not this flag.)
    """
    from app.models.admin_config import AdminConfig

    data = request.get_json(silent=True) or {}
    enabled = bool(data.get('enabled'))

    AdminConfig.set_setting(
        'season_pass_deeplinks_enabled',
        'true' if enabled else 'false',
        description='Route iOS season-pass Universal Links (/pub-league/buy|link-order|claim) '
                    'into the native app. Turn on only when the app build is live in the App Store.',
        category='mobile',
        data_type='boolean',   # store as boolean so parsed_value returns a real bool
        user_id=current_user.id,
        # No auto_commit: set_setting now writes to the REQUEST session, so a commit
        # here would commit the whole in-flight transaction rather than just this
        # setting. Teardown commits g.db_session once, at the end of the request.
    )

    logger.info(f"Admin {current_user.id} set season_pass_deeplinks_enabled={enabled}")
    return jsonify({
        'success': True,
        'enabled': enabled,
        'message': ('iOS deep links ON — season-pass links now open the app.'
                    if enabled else
                    'iOS deep links OFF — season-pass links open in the browser.'),
    })
