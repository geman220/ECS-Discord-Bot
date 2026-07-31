# app/pub_league/revenue.py

"""
Money extraction for Pub League / Summer Sprint orders.

WHAT THIS SOLVES
----------------
`pub_league_order.woo_order_data` has always held the entire WooCommerce order
payload, line totals included. Nothing read it, so the orders page could report
how many passes sold but not what they sold for. This module lifts those
figures onto columns the page can aggregate in SQL.

THE ONE SUBTLETY THAT MATTERS
-----------------------------
A WooCommerce line item covers a whole QUANTITY ("2 x Summer Sprint = $70"),
while `pub_league_order_line_item` is quantity-EXPANDED -- one row per pass, so
each pass can be assigned to a different person. Summing a Woo line total onto
each of its rows would report $140 for a $70 sale.

So the line's money is SPLIT across its rows, and split to the cent:
`_allocate` walks running subtotals rather than dividing and rounding each
share, so three passes on a $100 line come out 33.34 / 33.33 / 33.33 and still
sum to exactly $100.00. The invariant this module maintains is:

    SUM(line_item.amount_paid for an order) == sum of that order's league line
    totals in WooCommerce

which is what makes season revenue a trustworthy `SUM()`.

PAID vs LIST
------------
Woo gives two figures per line:
    subtotal -> BEFORE coupons   -> amount_list  ($40 Summer Sprint)
    total    -> AFTER coupons    -> amount_paid  ($35 for an ECS member)
`amount_paid` is the money actually taken, which is the number to report.
The gap between them is the discount given, worth showing on its own.

If the member price is a separate Woo product rather than a coupon, both fields
read 35.00 and the discount column is simply $0 -- the paid figure stays right
either way, which is why it, not a computed list-price-times-count, is the
source of truth.

BOTH EXCLUDE TAX AND SHIPPING. They are the league's take, not the customer's
card charge; `PubLeagueOrder.order_total` carries the gross charge for
reconciliation. Keeping them separate is deliberate -- silently folding tax into
"revenue" is the kind of number nobody can later explain.
"""

import logging
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

logger = logging.getLogger(__name__)

CENT = Decimal('0.01')
ZERO = Decimal('0.00')


def _dec(value):
    """Coerce a WooCommerce money field to Decimal, or None if unusable.

    Woo normally sends money as decimal STRINGS ("35.00"), but plugins and older
    payloads have been seen sending floats and empty strings. Going through
    `str()` keeps float inputs from dragging binary-float noise into a Decimal
    (Decimal(35.10) is 35.099999...), which would then round oddly one sale in a
    few hundred.
    """
    if value is None or value == '':
        return None
    try:
        return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        return None


def _allocate(total, count):
    """Split `total` across `count` rows so the parts sum to `total` EXACTLY.

    Dividing and rounding each share independently loses or invents cents:
    $100/3 rounds to 33.33 three times and reports $99.99. Walking the running
    subtotal instead puts the remainder on the earliest rows and always
    reconciles, which is what lets season revenue be a plain SUM().
    """
    if count <= 0:
        return []
    if total is None:
        return [None] * count

    parts, previous = [], ZERO
    for index in range(1, count + 1):
        running = (total * index / count).quantize(CENT, rounding=ROUND_HALF_UP)
        parts.append(running - previous)
        previous = running
    return parts


def _woo_line_money(order_data):
    """Map Woo line item id -> (paid, list) for every line on the order.

    Keyed by id because that is what `pub_league_order_line_item` stores. Name
    is kept as a secondary key for rows whose `woo_line_item_id` is NULL (older
    imports predate it).
    """
    by_id, by_name = {}, {}
    for item in (order_data.get('line_items') or []):
        paid = _dec(item.get('total'))
        listed = _dec(item.get('subtotal'))
        # A line with no `total` at all is unpriced, not free -- leave it None so
        # it surfaces as "unpriced" rather than dragging revenue down as $0.
        if paid is None and listed is None:
            continue
        # Woo omits `subtotal` on some payloads; with no coupon in play the two
        # are equal, so falling back keeps the discount column at $0 instead of
        # reporting a phantom discount equal to the whole price.
        if listed is None:
            listed = paid
        if paid is None:
            paid = listed

        money = (paid, listed)
        if item.get('id') is not None:
            by_id[item['id']] = money
        name = item.get('name') or ''
        if name:
            by_name.setdefault(name, money)
    return by_id, by_name


def _refund_total(order_data):
    """Sum Woo's refunds[], returned POSITIVE. None when the order has none.

    Woo reports refund totals as negative strings ("-35.00"). Stored positive so
    the column reads the way an admin says it out loud ("$35 refunded") and so
    nobody has to remember the sign when subtracting it.
    """
    refunds = order_data.get('refunds') or []
    if not refunds:
        return None
    total = ZERO
    for refund in refunds:
        amount = _dec(refund.get('total'))
        if amount is not None:
            total += abs(amount)
    return total or None


def apply_order_revenue(order, line_items=None):
    """Derive money columns for one order from its cached WooCommerce payload.

    Mutates `order` and its line items in place; the CALLER commits. It does not
    touch the network -- everything comes from `woo_order_data`, so this is safe
    to run in bulk and safe inside a request.

    Args:
        order: PubLeagueOrder instance.
        line_items: the order's line items, when the caller already has them in
            hand (order creation, where they are not queryable yet). Omit to
            read them off the relationship.

    Returns:
        True if at least one pass got priced, False otherwise (no payload, or a
        payload carrying no usable line totals).
    """
    order_data = order.woo_order_data
    if not isinstance(order_data, dict):
        return False

    if line_items is None:
        # lazy='dynamic', so this is a query, not a loaded collection.
        line_items = order.line_items.all()
    line_items = list(line_items)

    order.currency = (order_data.get('currency') or None)
    order.order_total = _dec(order_data.get('total'))
    order.refund_total = _refund_total(order_data)
    order.revenue_synced_at = datetime.utcnow()

    if not line_items:
        return False

    by_id, by_name = _woo_line_money(order_data)
    if not by_id and not by_name:
        return False

    # Group the expanded rows back into the Woo line they came from, so each
    # line's money is split across exactly its own passes. Rows whose
    # `woo_line_item_id` is NULL fall back to the product name.
    groups = {}
    for row in line_items:
        if row.woo_line_item_id is not None and row.woo_line_item_id in by_id:
            key = ('id', row.woo_line_item_id)
        elif row.product_name in by_name:
            key = ('name', row.product_name)
        else:
            # No match: leave amounts NULL rather than guessing. An unpriced
            # pass is visible and fixable; a guessed one silently skews revenue.
            row.amount_paid = None
            row.amount_list = None
            continue
        groups.setdefault(key, []).append(row)

    priced = False
    for (kind, key), rows in groups.items():
        paid_total, list_total = (by_id if kind == 'id' else by_name)[key]

        # Split across the rows we ACTUALLY have, not across Woo's `quantity`.
        # If the two ever disagree, keeping the order's total right matters more
        # than keeping any single pass's share right -- revenue stays correct
        # and the discrepancy shows up as an odd per-pass price.
        for row, paid, listed in zip(rows,
                                     _allocate(paid_total, len(rows)),
                                     _allocate(list_total, len(rows))):
            row.amount_paid = paid
            row.amount_list = listed
            priced = True

    return priced
