"""
Mobile contract tests for the Player Hub gap endpoints:

    GET    /api/v1/admin/players/<id>/orders            (per-player order history)
    GET    /api/v1/players/<id>/events                  (individual match events)
    POST   /api/v1/admin/pub-league/orders/<id>/line-item
    DELETE /api/v1/admin/pub-league/orders/<id>

The first three are thin shells over app/services/pub_league_order_admin.py, which
the WEB order desk calls too — so a regression here is a regression on both
surfaces.

Two contracts are load-bearing beyond "does it work":

* A 404 must ALWAYS carry a body. The client's FeatureAvailability helper reads a
  BODYLESS 404 as "this endpoint isn't deployed" and hides the whole section, so a
  bodyless 404 turns a real error into a silently missing screen.
* "This person has no orders" is 200 with `orders: []`, never a 404 — an empty
  list and a hidden section state different facts.
"""
import pytest
from datetime import date, datetime, timedelta

from flask_jwt_extended import create_access_token

from app.models import Role
from app.models.pub_league_order import (
    PubLeagueOrder, PubLeagueOrderLineItem, PubLeagueOrderClaim,
    PubLeagueLineItemStatus, PubLeagueClaimStatus,
)
from app.models.stats import PlayerEvent, PlayerEventType
from tests.factories import (
    LeagueFactory, MatchFactory, PlayerFactory, SeasonFactory, TeamFactory,
    UserFactory,
)


def _role(session, name):
    role = session.query(Role).filter_by(name=name).first()
    if role is None:
        role = Role(name=name)
        session.add(role)
        session.flush()
    return role


@pytest.fixture
def admin(db):
    u = UserFactory()
    u.roles.append(_role(db.session, 'Global Admin'))
    db.session.flush()
    return u


def _auth(app, user):
    with app.app_context():
        token = create_access_token(identity=str(user.id),
                                    additional_claims={'approved': True})
    return {'Authorization': f'Bearer {token}'}


_ORDER_SEQ = [1000]


def _order(db, **kw):
    """A PubLeagueOrder with the NOT NULL columns satisfied."""
    _ORDER_SEQ[0] += 1
    n = _ORDER_SEQ[0]
    kw.setdefault('woo_order_id', n)
    kw.setdefault('verification_token', f'tok-{n}')
    kw.setdefault('created_at', datetime.utcnow())
    kw.setdefault('total_passes', 0)
    kw.setdefault('linked_passes', 0)
    order = PubLeagueOrder(**kw)
    db.session.add(order)
    db.session.flush()
    return order


def _line_item(db, order, **kw):
    kw.setdefault('product_name', 'Premier Season Pass')
    kw.setdefault('division', 'Premier')
    kw.setdefault('status', PubLeagueLineItemStatus.UNASSIGNED.value)
    li = PubLeagueOrderLineItem(order_id=order.id, **kw)
    db.session.add(li)
    db.session.flush()
    return li


# ---------------------------------------------------------------------------
# §1  GET /admin/players/<id>/orders
# ---------------------------------------------------------------------------

class TestPlayerOrders:

    def test_unknown_player_404_carries_a_body(self, client, db, app, admin):
        """A bodyless 404 would make the client hide the section instead of
        showing the admin that the player does not exist."""
        r = client.get('/api/v1/admin/players/999999/orders',
                       headers=_auth(app, admin))
        assert r.status_code == 404
        assert r.get_json()['error'] == 'Player not found'

    def test_no_orders_is_200_with_empty_list_not_404(self, client, db, app, admin):
        """"They bought nothing" and "this screen isn't deployed" are different
        facts. Only 200 + [] can say the first one."""
        player = PlayerFactory()
        db.session.flush()

        r = client.get(f'/api/v1/admin/players/{player.id}/orders',
                       headers=_auth(app, admin))
        assert r.status_code == 200
        body = r.get_json()
        assert body['success'] is True
        assert body['orders'] == []
        assert body['player_id'] == player.id

    def test_holder_relationship(self, client, db, app, admin):
        """Someone else paid; this player holds the pass."""
        buyer = UserFactory(email='buyer@example.com')
        player = PlayerFactory()
        order = _order(db, customer_email='buyer@example.com',
                       customer_name='Someone Else', primary_user_id=buyer.id)
        _line_item(db, order, assigned_player_id=player.id,
                   status=PubLeagueLineItemStatus.PASS_CREATED.value)

        r = client.get(f'/api/v1/admin/players/{player.id}/orders',
                       headers=_auth(app, admin))
        orders = r.get_json()['orders']
        assert len(orders) == 1
        assert orders[0]['relationship'] == 'holder'

    def test_buyer_relationship_matches_on_billing_email(self, client, db, app, admin):
        """She paid for her partner — she is on the order, but holds no pass.

        Matched on the billing email, because primary_user_id is only set once an
        account is resolved; a guest checkout carries only the email.
        """
        user = UserFactory(email='jane@example.com')
        player = PlayerFactory(user=user)
        other = PlayerFactory()
        order = _order(db, customer_email='JANE@example.com',  # case-insensitive
                       customer_name='Jane Doe')
        _line_item(db, order, assigned_player_id=other.id,
                   status=PubLeagueLineItemStatus.PASS_CREATED.value)

        r = client.get(f'/api/v1/admin/players/{player.id}/orders',
                       headers=_auth(app, admin))
        orders = r.get_json()['orders']
        assert len(orders) == 1
        assert orders[0]['relationship'] == 'buyer'

    def test_buyer_and_holder_relationship(self, client, db, app, admin):
        user = UserFactory(email='jane@example.com')
        player = PlayerFactory(user=user)
        order = _order(db, customer_email='jane@example.com', customer_name='Jane Doe')
        _line_item(db, order, assigned_player_id=player.id,
                   status=PubLeagueLineItemStatus.PASS_CREATED.value)

        r = client.get(f'/api/v1/admin/players/{player.id}/orders',
                       headers=_auth(app, admin))
        orders = r.get_json()['orders']
        assert len(orders) == 1
        assert orders[0]['relationship'] == 'buyer_and_holder'

    def test_a_same_named_stranger_is_not_returned(self, client, db, app, admin):
        """The whole reason this endpoint exists: the desk's free-text search
        matches customer_name, so it returns a DIFFERENT human with the same
        name. Resolving by id must not."""
        mine = PlayerFactory(name='Jane Doe', user=UserFactory(email='jane1@example.com'))
        theirs = PlayerFactory(name='Jane Doe', user=UserFactory(email='jane2@example.com'))
        order = _order(db, customer_email='jane2@example.com', customer_name='Jane Doe')
        _line_item(db, order, assigned_player_id=theirs.id,
                   status=PubLeagueLineItemStatus.PASS_CREATED.value)

        r = client.get(f'/api/v1/admin/players/{mine.id}/orders',
                       headers=_auth(app, admin))
        assert r.get_json()['orders'] == []

    def test_not_season_scoped_and_newest_first(self, client, db, app, admin):
        """No season filter: on ONE person, last season's order is exactly what
        an admin is asking about."""
        player = PlayerFactory()
        old_season = SeasonFactory(league_type='Pub League', is_current=False)
        new_season = SeasonFactory(league_type='Pub League', is_current=True)

        old = _order(db, season_id=old_season.id, season_name=old_season.name,
                     created_at=datetime.utcnow() - timedelta(days=400))
        _line_item(db, old, assigned_player_id=player.id,
                   status=PubLeagueLineItemStatus.PASS_CREATED.value)
        new = _order(db, season_id=new_season.id, season_name=new_season.name,
                     created_at=datetime.utcnow())
        _line_item(db, new, assigned_player_id=player.id,
                   status=PubLeagueLineItemStatus.PASS_CREATED.value)

        r = client.get(f'/api/v1/admin/players/{player.id}/orders',
                       headers=_auth(app, admin))
        orders = r.get_json()['orders']
        assert [o['id'] for o in orders] == [new.id, old.id]

    def test_line_items_carry_the_desk_shape(self, client, db, app, admin):
        """Serialized by _serialize_line_item verbatim, so the app's existing
        OrderLineItem model parses it with no new client model."""
        player = PlayerFactory(name='Jane Doe')
        order = _order(db, total_passes=1, linked_passes=1)
        claim = PubLeagueOrderClaim(
            order_id=order.id, claim_token='claim-tok-1',
            recipient_email='friend@example.com',
            status=PubLeagueClaimStatus.PENDING.value,
            expires_at=datetime.utcnow() + timedelta(days=7))
        db.session.add(claim)
        db.session.flush()
        li = _line_item(db, order, assigned_player_id=player.id, jersey_size='L',
                        claim_id=claim.id,
                        status=PubLeagueLineItemStatus.PASS_CREATED.value)

        r = client.get(f'/api/v1/admin/players/{player.id}/orders',
                       headers=_auth(app, admin))
        item = r.get_json()['orders'][0]['line_items'][0]
        assert item['id'] == li.id
        assert item['player_name'] == 'Jane Doe'
        assert item['jersey_size'] == 'L'
        # quantity is ALWAYS 1: line items are quantity-EXPANDED at import.
        assert item['quantity'] == 1
        # claim_id is what the app keys Resend/Cancel on — without it those
        # buttons never render.
        assert item['claim_id'] == claim.id
        assert item['claim_email'] == 'friend@example.com'

    def test_requires_admin_role(self, client, db, app):
        plain = UserFactory()
        db.session.flush()
        player = PlayerFactory()
        db.session.flush()
        r = client.get(f'/api/v1/admin/players/{player.id}/orders',
                       headers=_auth(app, plain))
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# §2  GET /players/<id>/events
# ---------------------------------------------------------------------------

class TestPlayerEvents:

    def _match(self, db, when):
        season = SeasonFactory(league_type='Pub League', is_current=True)
        league = LeagueFactory(season=season)
        home = TeamFactory(league=league, name='ECS FC Rangers')
        away = TeamFactory(league=league, name='ECS FC United')
        return MatchFactory(home_team=home, away_team=away, date=when,
                            season=season)

    def test_unknown_player_404_carries_a_body(self, client, db, app, admin):
        r = client.get('/api/v1/players/999999/events', headers=_auth(app, admin))
        assert r.status_code == 404
        assert r.get_json()['msg'] == 'Player not found'

    def test_events_carry_the_match_and_both_teams(self, client, db, app, admin):
        """The whole point: /stats gives "7 goals", this gives WHICH matches."""
        player = PlayerFactory()
        match = self._match(db, date(2026, 4, 15))
        db.session.add(PlayerEvent(player_id=player.id, match_id=match.id,
                                   event_type=PlayerEventType.GOAL, minute='37'))
        db.session.flush()

        r = client.get(f'/api/v1/players/{player.id}/events',
                       headers=_auth(app, admin))
        assert r.status_code == 200
        body = r.get_json()
        assert body['total'] == 1
        ev = body['events'][0]
        assert ev['event_type'] == 'GOAL'
        assert ev['match_id'] == match.id
        assert ev['match_date'] == '2026-04-15'
        assert ev['home_team_name'] == 'ECS FC Rangers'
        assert ev['away_team_name'] == 'ECS FC United'

    def test_minute_stays_a_string_and_zero_survives(self, client, db, app, admin):
        """"0" means UNTIMED, not "first minute". Coercing it to an int (or
        treating it as falsy and nulling it) would invent a fact."""
        player = PlayerFactory()
        match = self._match(db, date(2026, 4, 15))
        db.session.add(PlayerEvent(player_id=player.id, match_id=match.id,
                                   event_type=PlayerEventType.ASSIST, minute='0'))
        db.session.add(PlayerEvent(player_id=player.id, match_id=match.id,
                                   event_type=PlayerEventType.YELLOW_CARD, minute=None))
        db.session.flush()

        r = client.get(f'/api/v1/players/{player.id}/events',
                       headers=_auth(app, admin))
        minutes = [e['minute'] for e in r.get_json()['events']]
        assert '0' in minutes          # a string, not 0 and not None
        assert None in minutes

    def test_newest_match_first(self, client, db, app, admin):
        player = PlayerFactory()
        older = self._match(db, date(2026, 3, 1))
        newer = self._match(db, date(2026, 5, 1))
        db.session.add(PlayerEvent(player_id=player.id, match_id=older.id,
                                   event_type=PlayerEventType.GOAL, minute='5'))
        db.session.add(PlayerEvent(player_id=player.id, match_id=newer.id,
                                   event_type=PlayerEventType.GOAL, minute='9'))
        db.session.flush()

        r = client.get(f'/api/v1/players/{player.id}/events',
                       headers=_auth(app, admin))
        assert [e['match_id'] for e in r.get_json()['events']] == [newer.id, older.id]

    def test_limit_is_capped_and_the_cap_is_stated(self, client, db, app, admin):
        """A silent cap reads as "that's everything". `total` and `limit_cap` are
        what let the client say "showing 1 of 3" instead."""
        player = PlayerFactory()
        match = self._match(db, date(2026, 4, 15))
        for _ in range(3):
            db.session.add(PlayerEvent(player_id=player.id, match_id=match.id,
                                       event_type=PlayerEventType.GOAL, minute='1'))
        db.session.flush()

        r = client.get(f'/api/v1/players/{player.id}/events?limit=1',
                       headers=_auth(app, admin))
        body = r.get_json()
        assert len(body['events']) == 1
        assert body['limit'] == 1
        assert body['limit_cap'] == 200
        assert body['total'] == 3

        r = client.get(f'/api/v1/players/{player.id}/events?limit=9999',
                       headers=_auth(app, admin))
        assert r.get_json()['limit'] == 200

    def test_open_to_any_authenticated_user(self, client, db, app):
        """Same visibility as /players/<id>/stats — no role gate."""
        plain = UserFactory()
        db.session.flush()
        player = PlayerFactory()
        db.session.flush()
        r = client.get(f'/api/v1/players/{player.id}/events',
                       headers=_auth(app, plain))
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# §3.1  POST /admin/pub-league/orders/<id>/line-item
# ---------------------------------------------------------------------------

class TestUpdateLineItem:

    def test_noop_is_success_but_reports_no_change(self, client, db, app, admin):
        """The app must not report "No changes made" as a change."""
        order = _order(db)
        li = _line_item(db, order, division='Premier', jersey_size='L')

        r = client.post(f'/api/v1/admin/pub-league/orders/{order.id}/line-item',
                        headers=_auth(app, admin),
                        json={'line_item_id': li.id, 'division': 'Premier',
                              'jersey_size': 'L'})
        assert r.status_code == 200
        body = r.get_json()
        assert body['success'] is True
        assert body['changed'] is False
        assert body['message'] == 'No changes made'

    def test_omitted_field_is_left_alone_but_empty_string_clears_it(
            self, client, db, app, admin):
        """`None` (absent) and `''` (clear) are DIFFERENT instructions — a client
        that sends '' for "unchanged" would wipe the value."""
        order = _order(db)
        li = _line_item(db, order, division='Premier', jersey_size='L')

        # jersey_size omitted entirely -> untouched
        r = client.post(f'/api/v1/admin/pub-league/orders/{order.id}/line-item',
                        headers=_auth(app, admin),
                        json={'line_item_id': li.id, 'division': 'Classic'})
        assert r.status_code == 200
        assert li.division == 'Classic'
        assert li.jersey_size == 'L'

        # jersey_size '' -> cleared
        r = client.post(f'/api/v1/admin/pub-league/orders/{order.id}/line-item',
                        headers=_auth(app, admin),
                        json={'line_item_id': li.id, 'jersey_size': ''})
        assert r.status_code == 200
        assert li.jersey_size is None

    def test_unknown_division_is_400_and_lists_the_valid_ones(
            self, client, db, app, admin):
        order = _order(db)
        li = _line_item(db, order)

        r = client.post(f'/api/v1/admin/pub-league/orders/{order.id}/line-item',
                        headers=_auth(app, admin),
                        json={'line_item_id': li.id, 'division': 'Not A Division'})
        assert r.status_code == 400
        body = r.get_json()
        assert body['success'] is False
        assert 'valid_divisions' in body

    def test_division_is_stored_in_registry_casing(self, client, db, app, admin):
        """extract_pub_league_items writes program.league_name, so a lowercase
        'premier' row would not match a 'Premier' filter."""
        order = _order(db)
        li = _line_item(db, order, division='Classic')

        r = client.post(f'/api/v1/admin/pub-league/orders/{order.id}/line-item',
                        headers=_auth(app, admin),
                        json={'line_item_id': li.id, 'division': 'premier'})
        assert r.status_code == 200
        assert li.division == 'Premier'

    def test_line_item_from_another_order_is_404_not_a_cross_order_write(
            self, client, db, app, admin):
        order_a = _order(db)
        order_b = _order(db)
        li_b = _line_item(db, order_b, division='Premier')

        r = client.post(f'/api/v1/admin/pub-league/orders/{order_a.id}/line-item',
                        headers=_auth(app, admin),
                        json={'line_item_id': li_b.id, 'division': 'Classic'})
        assert r.status_code == 404
        assert r.get_json()['error']          # body, never bodyless
        assert li_b.division == 'Premier'     # untouched


# ---------------------------------------------------------------------------
# §3.2  DELETE /admin/pub-league/orders/<id>
# ---------------------------------------------------------------------------

class TestDeleteOrder:

    def test_missing_confirmation_is_rejected(self, client, db, app, admin):
        """A mistap on a phone must not be able to destroy an order."""
        order = _order(db)
        _line_item(db, order)

        r = client.delete(f'/api/v1/admin/pub-league/orders/{order.id}',
                          headers=_auth(app, admin), json={})
        assert r.status_code == 400
        assert r.get_json()['expected_order_number'] == str(order.woo_order_id)
        assert db.session.query(PubLeagueOrder).filter_by(id=order.id).first()

    def test_wrong_confirmation_is_rejected(self, client, db, app, admin):
        order = _order(db)
        r = client.delete(f'/api/v1/admin/pub-league/orders/{order.id}',
                          headers=_auth(app, admin),
                          json={'confirm_order_number': '1'})
        assert r.status_code == 400
        assert db.session.query(PubLeagueOrder).filter_by(id=order.id).first()

    def test_live_wallet_pass_blocks_deletion_with_409(self, client, db, app, admin):
        """Deleting the row behind a live pass leaves a pass in someone's Apple
        Wallet with nothing backing it, and nothing later reconciles that."""
        player = PlayerFactory(name='Jane Doe')
        order = _order(db)
        li = _line_item(db, order, assigned_player_id=player.id,
                        status=PubLeagueLineItemStatus.PASS_CREATED.value)
        li.wallet_pass_id = 12345
        db.session.flush()

        r = client.delete(f'/api/v1/admin/pub-league/orders/{order.id}',
                          headers=_auth(app, admin),
                          json={'confirm_order_number': str(order.woo_order_id)})
        assert r.status_code == 409
        body = r.get_json()
        assert body['wallet_pass_line_item_ids'] == [li.id]
        assert 'Jane Doe' in body['error']
        assert db.session.query(PubLeagueOrder).filter_by(id=order.id).first()

    def test_delete_states_what_it_destroyed(self, client, db, app, admin):
        """An admin who expected one pass and destroyed three needs to find that
        out now, not next Thursday."""
        order = _order(db)
        claim = PubLeagueOrderClaim(
            order_id=order.id, claim_token='claim-tok-del',
            recipient_email='friend@example.com',
            status=PubLeagueClaimStatus.PENDING.value,
            expires_at=datetime.utcnow() + timedelta(days=7))
        db.session.add(claim)
        db.session.flush()
        _line_item(db, order)
        _line_item(db, order)

        woo = order.woo_order_id
        r = client.delete(f'/api/v1/admin/pub-league/orders/{order.id}',
                          headers=_auth(app, admin),
                          json={'confirm_order_number': str(woo)})
        assert r.status_code == 200
        body = r.get_json()
        assert body['deleted'] == {'line_items': 2, 'claims': 1}
        assert body['message'] == f'Order #{woo} deleted'
        assert db.session.query(PubLeagueOrder).filter_by(id=order.id).first() is None

    def test_unknown_order_404_carries_a_body(self, client, db, app, admin):
        r = client.delete('/api/v1/admin/pub-league/orders/999999',
                          headers=_auth(app, admin),
                          json={'confirm_order_number': '1'})
        assert r.status_code == 404
        assert r.get_json()['error'] == 'Order not found'
