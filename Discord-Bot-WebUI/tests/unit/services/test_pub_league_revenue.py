"""Tests for app/pub_league/revenue.py -- money extraction from Woo payloads.

WHY THIS FILE EXISTS
--------------------
These numbers get reported as revenue on the admin orders page and exported to
CSV, so a wrong one is not a rendering bug, it is a wrong answer to "how much
did Summer Sprint take in". Two failure modes are silent and both are pinned
below.

1. DOUBLE COUNTING. A WooCommerce line item covers a whole QUANTITY ("2 x
   Summer Sprint = $70"), while `pub_league_order_line_item` is quantity
   EXPANDED -- one row per pass, so passes can be assigned to different people.
   Copying the line total onto each row reports $140 for a $70 sale. The split
   must also reconcile to the cent, or a season total drifts by pennies per
   multi-pass order and never ties out against WooCommerce.

2. COUNTING THE WRONG MONEY. `order.total` includes merch, shipping and tax
   bought in the same cart. Only the league line items are revenue. And the
   ECS member discount means `subtotal` ($40) is NOT what was collected --
   `total` ($35) is.

Neither failure raises. Both just produce a confident, wrong figure.
"""

from decimal import Decimal

import pytest

from app.pub_league.revenue import (
    apply_order_revenue, _allocate, _dec, _refund_total,
)

D = Decimal


class FakeLineItem:
    """Stands in for PubLeagueOrderLineItem -- only the fields revenue.py touches."""

    def __init__(self, woo_line_item_id, product_name):
        self.woo_line_item_id = woo_line_item_id
        self.product_name = product_name
        self.amount_paid = None
        self.amount_list = None


class FakeOrder:
    def __init__(self, order_data):
        self.woo_order_data = order_data
        self.currency = None
        self.order_total = None
        self.refund_total = None
        self.revenue_synced_at = None


def _line(line_id, name, quantity=1, subtotal=None, total=None):
    """A WooCommerce line item in the shape Woo actually sends (money as strings)."""
    item = {'id': line_id, 'name': name, 'quantity': quantity}
    if subtotal is not None:
        item['subtotal'] = subtotal
    if total is not None:
        item['total'] = total
    return item


def _order(*items, **kwargs):
    data = {'currency': 'USD', 'line_items': list(items)}
    data.update(kwargs)
    return data


class TestAllocateReconciles:
    """The split must sum to the line total EXACTLY -- SUM() is the whole point."""

    @pytest.mark.parametrize('total,count', [
        ('70.00', 2), ('100.00', 3), ('35.00', 1), ('40.00', 3),
        ('0.01', 3), ('105.00', 7), ('0.00', 2), ('99.99', 4), ('120.00', 8),
    ])
    def test_parts_sum_to_total(self, total, count):
        parts = _allocate(D(total), count)
        assert len(parts) == count
        assert sum(parts) == D(total)

    def test_remainder_lands_on_a_row_rather_than_vanishing(self):
        # Rounding each share independently gives 33.33 x3 = 99.99, losing a cent.
        parts = _allocate(D('100.00'), 3)
        assert sorted(str(p) for p in parts) == ['33.33', '33.33', '33.34']

    def test_unpriced_line_yields_nones_not_zeros(self):
        # None means "no price recorded" and is surfaced as a warning. Zero would
        # silently drag the average down and look like a free pass.
        assert _allocate(None, 2) == [None, None]

    def test_zero_rows(self):
        assert _allocate(D('5.00'), 0) == []


class TestDec:
    def test_parses_woo_money_strings(self):
        assert _dec('35.00') == D('35.00')

    def test_floats_do_not_leak_binary_noise(self):
        # Decimal(35.10) is 35.0999...; going via str() keeps it exact.
        assert _dec(35.10) == D('35.10')

    def test_unusable_values_are_none_not_zero(self):
        for value in (None, '', 'abc', object()):
            assert _dec(value) is None


class TestMemberDiscount:
    """The $40 pass an ECS member paid $35 for must count as $35."""

    def test_coupon_discount_records_paid_not_list(self):
        order = FakeOrder(_order(
            _line(11, 'Summer Sprint', subtotal='40.00', total='35.00')))
        rows = [FakeLineItem(11, 'Summer Sprint')]

        assert apply_order_revenue(order, rows) is True
        assert rows[0].amount_paid == D('35.00')
        assert rows[0].amount_list == D('40.00')

    def test_member_price_as_its_own_product_reports_no_phantom_discount(self):
        # If the discount is a separate Woo product rather than a coupon, both
        # fields read 35.00. Paid must still be right; discount must be $0.
        order = FakeOrder(_order(
            _line(11, 'Summer Sprint (ECS Member)', subtotal='35.00', total='35.00')))
        rows = [FakeLineItem(11, 'Summer Sprint (ECS Member)')]

        apply_order_revenue(order, rows)
        assert rows[0].amount_paid == D('35.00')
        assert rows[0].amount_list - rows[0].amount_paid == D('0.00')

    def test_missing_subtotal_does_not_invent_a_full_price_discount(self):
        # Woo omits subtotal on some payloads. Defaulting it to 0 would report a
        # discount equal to the entire price.
        order = FakeOrder(_order(_line(11, 'Summer Sprint', total='35.00')))
        rows = [FakeLineItem(11, 'Summer Sprint')]

        apply_order_revenue(order, rows)
        assert rows[0].amount_list == rows[0].amount_paid == D('35.00')


class TestQuantityExpansion:
    """One Woo line, many DB rows: the money is split, never copied."""

    def test_two_passes_split_the_line_total(self):
        order = FakeOrder(_order(
            _line(12, 'Summer Sprint', quantity=2, subtotal='80.00', total='70.00')))
        rows = [FakeLineItem(12, 'Summer Sprint'), FakeLineItem(12, 'Summer Sprint')]

        apply_order_revenue(order, rows)
        assert sum(r.amount_paid for r in rows) == D('70.00')
        assert all(r.amount_paid == D('35.00') for r in rows)

    def test_three_passes_on_an_odd_total_still_reconcile(self):
        order = FakeOrder(_order(
            _line(12, 'Summer Sprint', quantity=3, subtotal='120.00', total='100.00')))
        rows = [FakeLineItem(12, 'Summer Sprint') for _ in range(3)]

        apply_order_revenue(order, rows)
        assert sum(r.amount_paid for r in rows) == D('100.00')

    def test_row_count_disagreeing_with_woo_quantity_keeps_order_total_right(self):
        # If the two ever drift, the ORDER's revenue staying correct matters more
        # than any single pass's share.
        order = FakeOrder(_order(
            _line(12, 'Summer Sprint', quantity=2, subtotal='80.00', total='70.00')))
        rows = [FakeLineItem(12, 'Summer Sprint')]  # only one row exists

        apply_order_revenue(order, rows)
        assert sum(r.amount_paid for r in rows) == D('70.00')


class TestOnlyLeagueMoneyCounts:
    def test_merch_in_the_same_cart_is_not_league_revenue(self):
        order = FakeOrder(_order(
            _line(13, 'Summer Sprint', subtotal='40.00', total='35.00'),
            _line(14, 'ECS Scarf', subtotal='25.00', total='25.00'),
            total='62.50',
        ))
        # Only league passes get DB rows, so only they get priced.
        rows = [FakeLineItem(13, 'Summer Sprint')]

        apply_order_revenue(order, rows)
        assert rows[0].amount_paid == D('35.00')
        # The gross charge is kept separately, never as revenue.
        assert order.order_total == D('62.50')

    def test_separate_leagues_keep_separate_money(self):
        order = FakeOrder(_order(
            _line(15, 'Premier', subtotal='90.00', total='90.00'),
            _line(16, 'Summer Sprint', subtotal='40.00', total='35.00'),
        ))
        premier, summer = FakeLineItem(15, 'Premier'), FakeLineItem(16, 'Summer Sprint')

        apply_order_revenue(order, [premier, summer])
        assert premier.amount_paid == D('90.00')
        assert summer.amount_paid == D('35.00')


class TestUnmatchedRowsStayNull:
    def test_null_woo_line_item_id_falls_back_to_product_name(self):
        # Legacy imports predate woo_line_item_id.
        order = FakeOrder(_order(
            _line(18, 'Summer Sprint', subtotal='40.00', total='35.00')))
        rows = [FakeLineItem(None, 'Summer Sprint')]

        apply_order_revenue(order, rows)
        assert rows[0].amount_paid == D('35.00')

    def test_unmatchable_row_is_left_null_never_guessed(self):
        # A guessed amount silently skews revenue; a NULL one is reported as
        # "unpriced" on the page and can be fixed.
        order = FakeOrder(_order(
            _line(18, 'Summer Sprint', subtotal='40.00', total='35.00')))
        rows = [FakeLineItem(999, 'Something Else Entirely')]

        assert apply_order_revenue(order, rows) is False
        assert rows[0].amount_paid is None

    def test_line_with_no_money_at_all_is_unpriced_not_free(self):
        order = FakeOrder(_order(_line(18, 'Summer Sprint')))
        rows = [FakeLineItem(18, 'Summer Sprint')]

        assert apply_order_revenue(order, rows) is False
        assert rows[0].amount_paid is None


class TestRefunds:
    def test_refund_is_stored_positive(self):
        # Woo sends negative strings; storing positive means nobody has to
        # remember the sign when subtracting.
        assert _refund_total({'refunds': [{'total': '-35.00'}]}) == D('35.00')

    def test_multiple_refunds_sum(self):
        assert _refund_total(
            {'refunds': [{'total': '-35.00'}, {'total': '-5.00'}]}) == D('40.00')

    def test_no_refunds_is_none_not_zero(self):
        assert _refund_total({}) is None
        assert _refund_total({'refunds': []}) is None

    def test_refund_does_not_alter_gross_pass_amounts(self):
        # Refunds are reported alongside revenue, not subtracted from each pass.
        order = FakeOrder(_order(
            _line(17, 'Summer Sprint', subtotal='40.00', total='35.00'),
            refunds=[{'total': '-35.00'}],
        ))
        rows = [FakeLineItem(17, 'Summer Sprint')]

        apply_order_revenue(order, rows)
        assert rows[0].amount_paid == D('35.00')
        assert order.refund_total == D('35.00')


class TestDegradesQuietly:
    """None of these may raise -- this runs inside the Woo webhook, which retries."""

    @pytest.mark.parametrize('payload', [None, {}, [], 'not-a-dict', 42])
    def test_unusable_payload_returns_false(self, payload):
        assert apply_order_revenue(FakeOrder(payload), [FakeLineItem(1, 'x')]) is False

    def test_order_with_no_line_items(self):
        assert apply_order_revenue(FakeOrder(_order()), []) is False

    def test_currency_and_sync_stamp_are_recorded(self):
        order = FakeOrder(_order(
            _line(11, 'Summer Sprint', subtotal='40.00', total='35.00'), total='35.00'))
        apply_order_revenue(order, [FakeLineItem(11, 'Summer Sprint')])

        assert order.currency == 'USD'
        assert order.revenue_synced_at is not None
