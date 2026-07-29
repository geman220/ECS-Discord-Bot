"""Tests for PubLeagueOrderService.extract_pub_league_items().

WHY THIS FILE EXISTS
--------------------
This function is the gate that decides whether a paying customer becomes a real
row. `create_or_get_order()` calls it and uses the result for `total_passes`, for
the season lookup, and for every `PubLeagueOrderLineItem` it writes. If it
returns `[]`, the order row is still created but with ZERO line items, no season,
and nothing to activate -- so the buyer paid and, as far as the app is concerned,
bought nothing. No exception, no log line at error level, nothing on the orders
page.

That is not hypothetical. Both legacy regexes require a `(Spring|Fall)` token AND
a `(Classic|Premier)` token:

    r'(\\d{4})\\s+(Spring|Fall)\\s+ECS\\s+Pub\\s+League.*?(Classic|Premier)'

The real 2026 product is titled "2026 ECS Pub League – Summer Sprint Season",
which has NEITHER -- and uses an EN DASH. It matched nothing, which is why the
program registry is consulted first now.

Everything below pins a behaviour whose failure mode is silent.
"""

import pytest

from app.pub_league.services import PubLeagueOrderService


def _order(*items):
    """Minimal WooCommerce order payload with the line-item shape Woo sends."""
    return {'line_items': list(items)}


def _item(name, product_id=None, quantity=1, line_id=1):
    return {'id': line_id, 'name': name, 'product_id': product_id,
            'quantity': quantity}


extract = PubLeagueOrderService.extract_pub_league_items


class TestSummerResolvesViaRegistry:
    REAL_TITLE = '2026 ECS Pub League – Summer Sprint Season'

    def test_real_summer_title_produces_a_line_item(self, db, app):
        """The exact live product title must resolve. This is the whole bug."""
        items = extract(_order(_item(self.REAL_TITLE)))

        assert len(items) == 1, (
            "the live Summer product produced ZERO line items -- the buyer would "
            "have an order row with nothing in it and would never be activated"
        )

    def test_division_is_the_LEAGUE_NAME_not_the_key_or_display_name(self, db, app):
        """`division` is later resolved to a League row BY NAME.

        So it must be `program.league_name` ('Summer Sprint'), not the key
        ('pl_third') and not some display variant. If this drifts, the line item
        is written successfully and the League lookup downstream quietly finds
        nothing -- a broken order that looks fine in the database.
        """
        items = extract(_order(_item(self.REAL_TITLE)))

        assert items[0]['division'] == 'Summer Sprint', (
            f"division is {items[0]['division']!r}; it must equal League.name or "
            f"the downstream league lookup silently fails"
        )

    def test_en_dash_and_hyphen_both_work(self, db, app):
        """The real title uses U+2013. A pattern anchored on the dash matches
        nothing, and the failure is invisible."""
        en_dash = extract(_order(_item('2026 ECS Pub League – Summer Sprint Season')))
        hyphen = extract(_order(_item('2026 ECS Pub League - Summer Sprint Season')))

        assert len(en_dash) == 1, "en dash title did not resolve"
        assert len(hyphen) == 1, "hyphen title did not resolve"
        assert en_dash[0]['division'] == hyphen[0]['division'] == 'Summer Sprint'


class TestLegacyDivisionsStillWork:
    """Regression guard. The registry was added in front of these regexes, so a
    mistake there breaks Premier/Classic -- the programs that actually have
    paying customers today."""

    @pytest.mark.parametrize('title,expected', [
        ('2026 Spring ECS Pub League Premier Division', 'Premier'),
        ('2026 Fall ECS Pub League Classic Division', 'Classic'),
        ('Spring 2026 ECS Pub League Premier Division', 'Premier'),
        ('Fall 2026 ECS Pub League Classic Division', 'Classic'),
    ])
    def test_legacy_titles_resolve(self, db, app, title, expected):
        items = extract(_order(_item(title)))
        assert len(items) == 1, f"{title!r} produced no line item"
        assert items[0]['division'] == expected


class TestNonProgramProductsAreIgnored:
    def test_unrelated_product_produces_nothing(self, db, app):
        """A scarf in the same order must not become a league pass."""
        items = extract(_order(_item('ECS FC Supporters Scarf')))
        assert items == []

    def test_mixed_order_keeps_only_the_league_items(self, db, app):
        """Real orders contain merch alongside passes."""
        items = extract(_order(
            _item('ECS FC Supporters Scarf', line_id=1),
            _item('2026 ECS Pub League – Summer Sprint Season', line_id=2),
            _item('2026 Spring ECS Pub League Premier Division', line_id=3),
        ))

        divisions = sorted(i['division'] for i in items)
        assert divisions == ['Premier', 'Summer Sprint'], (
            f"expected exactly the two league items, got {divisions}"
        )


class TestQuantityBecomesOnePassEach:
    def test_quantity_three_yields_three_passes(self, db, app):
        """Someone buying for friends gets N passes, not one.

        `total_passes` is len() of this list, so an off-by-one here undercounts
        what the customer paid for.
        """
        items = extract(_order(_item(
            '2026 ECS Pub League – Summer Sprint Season', quantity=3)))

        assert len(items) == 3
        assert all(i['division'] == 'Summer Sprint' for i in items)
        assert all(i['woo_line_item_id'] == 1 for i in items), (
            "each pass should still reference the originating Woo line item"
        )

    def test_missing_quantity_defaults_to_one(self, db, app):
        """Woo omits quantity in some payload shapes; default must be 1, not 0."""
        payload = {'line_items': [{'id': 9, 'name':
                   '2026 ECS Pub League – Summer Sprint Season'}]}
        assert len(extract(payload)) == 1


class TestJerseySize:
    def test_na_jersey_size_is_stored_as_none(self, db, app):
        """'N/A' must become NULL, not the literal string.

        The orders export and the Division/size badges read this column; a
        literal 'N/A' shows up as a real size in the admin UI and in exports.
        """
        items = extract(_order(_item('2026 ECS Pub League – Summer Sprint Season')))
        assert items[0]['jersey_size'] is None


class TestDegenerateInput:
    """`create_or_get_order` passes whatever Woo sent. None of these should raise
    -- a webhook that 500s is retried by Woo and can double-create."""

    @pytest.mark.parametrize('payload', [
        {},
        {'line_items': []},
        {'line_items': [{}]},
        {'line_items': [{'name': None}]},
        {'line_items': [{'name': ''}]},
    ])
    def test_no_crash_on_degenerate_payloads(self, db, app, payload):
        assert extract(payload) == []
