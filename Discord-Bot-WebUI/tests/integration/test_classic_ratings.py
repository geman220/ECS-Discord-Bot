"""
Adversarial integration tests for the Classic rating service against a real
session: eligibility, blindness, window gating, upsert/aggregation/override
behavior, and season rollover.
"""
from decimal import Decimal

import pytest

from app.models import Role, Season
from app.models.admin_config import AdminConfig, AdminAuditLog
from app.services import classic_rating_service as svc
from tests.factories import LeagueFactory, PlayerFactory, SeasonFactory, UserFactory


@pytest.fixture
def settings(monkeypatch):
    """Deterministic AdminConfig backing store; tests mutate the dict."""
    store = {'classic_ratings_window_open': True}
    monkeypatch.setattr(
        AdminConfig, 'get_setting',
        classmethod(lambda cls, key, default=None: store.get(key, default)),
    )
    return store


@pytest.fixture
def audit_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(
        AdminAuditLog, 'log_action',
        classmethod(lambda cls, **kwargs: calls.append(kwargs)),
    )
    return calls


def _classic_league(session):
    season = SeasonFactory(league_type='Pub League', is_current=True)
    league = LeagueFactory(name='Classic', season=season)
    return season, league


def _coach_role(session):
    role = session.query(Role).filter_by(name='Classic Coach').first()
    if role is None:
        role = Role(name='Classic Coach')
        session.add(role)
        session.flush()
    return role


def _make_coach(session):
    user = UserFactory()
    user.roles.append(_coach_role(session))
    session.flush()
    return user


def _make_player(session, league, **kwargs):
    player = PlayerFactory(is_current_player=True, **kwargs)
    player.primary_league_id = league.id
    session.flush()
    return player


class TestEligibility:
    def test_rateable_excludes_classic_coach_role_holders(self, db, app):
        session = db.session
        season, league = _classic_league(session)
        player = _make_player(session, league)
        coach_user = _make_coach(session)
        coach_player = _make_player(session, league, user=coach_user)

        ids = {p.id for p in svc.get_rateable_players(session, league)}
        assert player.id in ids
        assert coach_player.id not in ids

    def test_rateable_excludes_inactive_and_other_league(self, db, app):
        session = db.session
        season, league = _classic_league(session)
        premier = LeagueFactory(name='Premier', season=season)
        active = _make_player(session, league)
        inactive = _make_player(session, league)
        inactive.is_current_player = False
        premier_player = _make_player(session, premier)
        session.flush()

        ids = {p.id for p in svc.get_rateable_players(session, league)}
        assert active.id in ids
        assert inactive.id not in ids
        assert premier_player.id not in ids

    def test_no_current_season_returns_empty(self, db, app):
        session = db.session
        assert svc.get_rateable_players(session) == []


class TestUpsert:
    def test_upsert_and_partial_autosave(self, db, app, settings):
        session = db.session
        season, league = _classic_league(session)
        coach = _make_coach(session)
        player = _make_player(session, league)

        row = svc.upsert_rating(session, season.id, coach.id, player.id,
                                {'intensity': '2.75'})
        assert row.intensity == Decimal('2.75')
        assert not row.is_complete

        row2 = svc.upsert_rating(session, season.id, coach.id, player.id,
                                 {'on_ball_skill': 3, 'spirit': '4.25',
                                  'knowledge_movement': 3.5})
        assert row2.id == row.id  # upsert, not duplicate
        assert row2.intensity == Decimal('2.75')  # untouched keys preserved
        assert row2.is_complete

    def test_window_closed_rejected(self, db, app, settings):
        session = db.session
        season, league = _classic_league(session)
        coach = _make_coach(session)
        player = _make_player(session, league)
        settings['classic_ratings_window_open'] = False
        with pytest.raises(svc.RatingWindowClosed):
            svc.upsert_rating(session, season.id, coach.id, player.id, {'intensity': 3})

    def test_non_coach_rejected(self, db, app, settings):
        session = db.session
        season, league = _classic_league(session)
        outsider = UserFactory()
        player = _make_player(session, league)
        with pytest.raises(PermissionError):
            svc.upsert_rating(session, season.id, outsider.id, player.id, {'intensity': 3})

    def test_rating_a_coach_rejected(self, db, app, settings):
        session = db.session
        season, league = _classic_league(session)
        rater = _make_coach(session)
        other_coach_player = _make_player(session, league, user=_make_coach(session))
        with pytest.raises(svc.NotRateable):
            svc.upsert_rating(session, season.id, rater.id, other_coach_player.id,
                              {'intensity': 3})

    def test_non_current_season_rejected(self, db, app, settings):
        session = db.session
        season, league = _classic_league(session)
        old_season = SeasonFactory(league_type='Pub League', is_current=False)
        coach = _make_coach(session)
        player = _make_player(session, league)
        with pytest.raises(svc.NotRateable):
            svc.upsert_rating(session, old_season.id, coach.id, player.id, {'intensity': 3})

    def test_unknown_metric_and_bad_values_rejected(self, db, app, settings):
        session = db.session
        season, league = _classic_league(session)
        coach = _make_coach(session)
        player = _make_player(session, league)
        with pytest.raises(ValueError):
            svc.upsert_rating(session, season.id, coach.id, player.id, {'speed': 3})
        with pytest.raises(ValueError):
            svc.upsert_rating(session, season.id, coach.id, player.id, {'intensity': '5.5'})


class TestBlindnessAndAggregation:
    def test_get_my_ratings_returns_only_own_rows(self, db, app, settings):
        session = db.session
        season, league = _classic_league(session)
        coach_a, coach_b = _make_coach(session), _make_coach(session)
        player = _make_player(session, league)
        svc.upsert_rating(session, season.id, coach_a.id, player.id, {'intensity': '4.75'})

        mine_b = svc.get_my_ratings(session, season.id, coach_b.id)
        assert mine_b == {}
        mine_a = svc.get_my_ratings(session, season.id, coach_a.id)
        assert mine_a[player.id].intensity == Decimal('4.75')

    def test_averages_skip_nulls_per_metric(self, db, app, settings):
        session = db.session
        season, league = _classic_league(session)
        a, b = _make_coach(session), _make_coach(session)
        player = _make_player(session, league)
        svc.upsert_rating(session, season.id, a.id, player.id,
                          {'intensity': 4, 'spirit': 2})
        svc.upsert_rating(session, season.id, b.id, player.id,
                          {'intensity': 3})  # no spirit

        avgs = svc.get_player_averages(session, season.id)[player.id]
        assert avgs['intensity']['avg'] == Decimal('3.5')
        assert avgs['intensity']['count'] == 2
        assert avgs['spirit']['avg'] == Decimal('2')
        assert avgs['spirit']['count'] == 1
        assert avgs['on_ball_skill']['avg'] is None

    def test_override_beats_average_and_revert_restores(self, db, app, settings, audit_calls):
        session = db.session
        season, league = _classic_league(session)
        coach = _make_coach(session)
        admin = UserFactory()
        player = _make_player(session, league)
        svc.upsert_rating(session, season.id, coach.id, player.id,
                          {'intensity': 3, 'on_ball_skill': 3, 'spirit': 3,
                           'knowledge_movement': 3})

        svc.set_override(session, season.id, player.id, 'intensity', '4.50',
                         admin.id, reason='league knowledge')
        finals = svc.get_final_scores(session, season.id)
        m = finals[player.id]['metrics']['intensity']
        assert m['value'] == Decimal('4.50') and m['overridden'] and m['avg'] == Decimal('3.00')
        # other metrics untouched
        assert finals[player.id]['metrics']['spirit']['value'] == Decimal('3.00')
        # composite uses the override: 0.4*4.5 + 0.6*3 = 3.60
        assert finals[player.id]['composite'] == Decimal('3.60')

        assert svc.clear_override(session, season.id, player.id, 'intensity', admin.id)
        finals = svc.get_final_scores(session, season.id)
        assert finals[player.id]['metrics']['intensity']['value'] == Decimal('3.00')
        assert not finals[player.id]['metrics']['intensity']['overridden']
        assert [c['action'] for c in audit_calls] == ['set_override', 'clear_override']

    def test_override_with_zero_ratings_works(self, db, app, settings, audit_calls):
        session = db.session
        season, league = _classic_league(session)
        admin = UserFactory()
        player = _make_player(session, league)  # nobody rated them
        for metric in svc.METRICS:
            svc.set_override(session, season.id, player.id, metric, 3, admin.id)
        finals = svc.get_final_scores(session, season.id)
        assert finals[player.id]['is_rated']
        assert finals[player.id]['composite'] == Decimal('3.00')

    def test_decimal_round_trip_exact(self, db, app, settings):
        session = db.session
        season, league = _classic_league(session)
        coach = _make_coach(session)
        player = _make_player(session, league)
        svc.upsert_rating(session, season.id, coach.id, player.id, {'intensity': 2.75})
        stored = svc.get_my_ratings(session, season.id, coach.id)[player.id]
        assert stored.to_dict()['intensity'] == 2.75


class TestSeasonRollover:
    def test_new_current_season_starts_blank_and_history_intact(self, db, app, settings):
        session = db.session
        old_season, old_league = _classic_league(session)
        coach = _make_coach(session)
        player = _make_player(session, old_league)
        svc.upsert_rating(session, old_season.id, coach.id, player.id,
                          {'intensity': 4, 'on_ball_skill': 4, 'spirit': 4,
                           'knowledge_movement': 4})

        # Roll over: old season no longer current, new season + Classic league
        old_season.is_current = False
        new_season = SeasonFactory(league_type='Pub League', is_current=True)
        new_league = LeagueFactory(name='Classic', season=new_season)
        session.flush()

        # Rateable set now derives from the NEW league; the old player isn't in it
        assert svc.get_rateable_players(session) == []
        returning = _make_player(session, new_league)
        assert [p.id for p in svc.get_rateable_players(session)] == [returning.id]

        # New season is blank; old-season data intact for trends
        assert svc.get_final_scores(session, new_season.id) == {}
        assert svc.get_final_scores(session, old_season.id)[player.id]['is_rated']

        # Ratings against the old season are now rejected
        with pytest.raises(svc.NotRateable):
            svc.upsert_rating(session, old_season.id, coach.id, player.id, {'intensity': 3})
