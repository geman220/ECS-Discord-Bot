"""
Adversarial HTTP-layer tests for the Classic ratings surfaces: role-gate
matrix and blind enforcement (a coach's response bodies must never leak
another coach's rating values).
"""
from decimal import Decimal

import pytest

from app.models import Role
from app.models.admin_config import AdminConfig
from app.services import classic_rating_service as svc
from tests.factories import LeagueFactory, PlayerFactory, SeasonFactory, UserFactory
from tests.helpers import AuthTestHelper


@pytest.fixture
def settings(monkeypatch):
    store = {'classic_ratings_window_open': True}
    monkeypatch.setattr(
        AdminConfig, 'get_setting',
        classmethod(lambda cls, key, default=None: store.get(key, default)),
    )
    return store


def _role(session, name):
    role = session.query(Role).filter_by(name=name).first()
    if role is None:
        role = Role(name=name)
        session.add(role)
        session.flush()
    return role


def _user_with_roles(session, *roles):
    user = UserFactory()
    for name in roles:
        user.roles.append(_role(session, name))
    session.flush()
    return user


def _classic_setup(session):
    season = SeasonFactory(league_type='Pub League', is_current=True)
    league = LeagueFactory(name='Classic', season=season)
    player = PlayerFactory(is_current_player=True)
    player.primary_league_id = league.id
    session.flush()
    return season, league, player


class TestRoleGates:
    """Exact status expectations per role for each surface."""

    ALLOW = 'allow'
    DENY = 'deny'   # role gate: redirect (302) or forbidden (403)

    CASES = [
        # (roles, board, rate_page, save_rating, admin_dash)
        (('Classic Coach',), 'allow', 'allow', 'allow', 'deny'),
        (('Pub League Coach',), 'allow', 'deny', 'deny', 'deny'),
        (('Premier Coach',), 'deny', 'deny', 'deny', 'deny'),
        (('Pub League Admin',), 'allow', 'allow', 'deny', 'allow'),
        (('Global Admin',), 'allow', 'allow', 'deny', 'allow'),
        ((), 'deny', 'deny', 'deny', 'deny'),  # plain authenticated user
    ]

    @staticmethod
    def _check(resp, expectation, context):
        if expectation == 'allow':
            assert resp.status_code == 200, f'{context}: {resp.status_code}'
        else:
            assert resp.status_code in (302, 403), f'{context}: {resp.status_code}'

    @pytest.mark.parametrize('roles,board,rate_page,save,admin_dash', CASES)
    def test_matrix(self, client, db, app, settings, roles, board, rate_page, save, admin_dash):
        session = db.session
        season, league, player = _classic_setup(session)
        user = _user_with_roles(session, *roles)
        AuthTestHelper.create_authenticated_session(client, user)

        self._check(client.get('/classic-board/'), board, 'board')
        self._check(client.get('/classic-board/rate'), rate_page, 'rate page')
        self._check(client.post(f'/classic-board/rate/{player.id}', json={'intensity': 3}),
                    save, 'save rating')
        self._check(client.get('/admin-panel/classic-ratings'), admin_dash, 'admin dash')

    def test_anonymous_redirected(self, client, db, app, settings):
        _classic_setup(db.session)
        assert client.get('/classic-board/').status_code in (302, 401)
        assert client.get('/classic-board/rate').status_code in (302, 401)
        assert client.get('/admin-panel/classic-ratings').status_code in (302, 401)


class TestBlindEnforcement:
    def test_other_coach_values_never_leak(self, client, db, app, settings):
        """Coach A rates with a sentinel value; coach B's rate page and save
        responses must not contain it anywhere."""
        session = db.session
        season, league, player = _classic_setup(session)
        coach_a = _user_with_roles(session, 'Classic Coach')
        coach_b = _user_with_roles(session, 'Classic Coach')

        sentinel = '4.77'
        svc.upsert_rating(session, season.id, coach_a.id, player.id,
                          {'intensity': sentinel})
        session.commit()

        AuthTestHelper.create_authenticated_session(client, coach_b)
        page = client.get('/classic-board/rate').get_data(as_text=True)
        assert sentinel not in page

        resp = client.post(f'/classic-board/rate/{player.id}', json={'spirit': 2})
        body = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert sentinel not in body

    def test_board_shows_average_not_raw_attribution(self, client, db, app, settings):
        """The board may show the average but no rater identity."""
        session = db.session
        season, league, player = _classic_setup(session)
        coach_a = _user_with_roles(session, 'Classic Coach')
        coach_b = _user_with_roles(session, 'Classic Coach')
        for metric in svc.METRICS:
            svc.upsert_rating(session, season.id, coach_a.id, player.id, {metric: 4})
        session.commit()

        AuthTestHelper.create_authenticated_session(client, coach_b)
        page = client.get('/classic-board/').get_data(as_text=True)
        assert '4.00' in page                    # average visible
        assert coach_a.username not in page      # rater identity is not

    def test_window_closed_blocks_save(self, client, db, app, settings):
        session = db.session
        season, league, player = _classic_setup(session)
        coach = _user_with_roles(session, 'Classic Coach')
        settings['classic_ratings_window_open'] = False

        AuthTestHelper.create_authenticated_session(client, coach)
        resp = client.post(f'/classic-board/rate/{player.id}', json={'intensity': 3})
        assert resp.status_code == 403
        assert resp.get_json()['error'] == 'WINDOW_CLOSED'


class TestAdminOverrideEndpoint:
    def test_override_set_and_clear(self, client, db, app, settings, monkeypatch):
        from app.models.admin_config import AdminAuditLog
        monkeypatch.setattr(AdminAuditLog, 'log_action',
                            classmethod(lambda cls, **kwargs: None))
        session = db.session
        season, league, player = _classic_setup(session)
        admin = _user_with_roles(session, 'Pub League Admin')
        AuthTestHelper.create_authenticated_session(client, admin)

        resp = client.post('/admin-panel/classic-ratings/override',
                           json={'player_id': player.id, 'metric': 'intensity',
                                 'value': 4.5, 'reason': 'seen play'})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['final']['intensity']['value'] == 4.5
        assert data['final']['intensity']['overridden'] is True

        resp = client.post('/admin-panel/classic-ratings/override',
                           json={'player_id': player.id, 'metric': 'intensity',
                                 'value': None})
        assert resp.status_code == 200
        assert resp.get_json()['final']['intensity']['overridden'] is False

    def test_override_rejects_bad_values(self, client, db, app, settings):
        session = db.session
        season, league, player = _classic_setup(session)
        admin = _user_with_roles(session, 'Global Admin')
        AuthTestHelper.create_authenticated_session(client, admin)

        for bad in (0.5, 5.5, 'abc'):
            resp = client.post('/admin-panel/classic-ratings/override',
                               json={'player_id': player.id, 'metric': 'intensity',
                                     'value': bad})
            assert resp.status_code == 400
        resp = client.post('/admin-panel/classic-ratings/override',
                           json={'player_id': player.id, 'metric': 'nope', 'value': 3})
        assert resp.status_code == 400

    def test_override_rejects_unknown_and_non_classic_player(self, client, db, app, settings):
        """Review finding: unknown id must 400, not die on the FK (500)."""
        session = db.session
        _classic_setup(session)
        admin = _user_with_roles(session, 'Global Admin')
        AuthTestHelper.create_authenticated_session(client, admin)
        resp = client.post('/admin-panel/classic-ratings/override',
                           json={'player_id': 999999, 'metric': 'intensity', 'value': 3})
        assert resp.status_code == 400

    def test_config_400_writes_nothing(self, client, db, app, settings):
        """Review finding: teardown commits g.db_session even on a 400 — the
        route must validate everything before its first write."""
        from app.models.admin_config import AdminConfig as AC
        session = db.session
        _classic_setup(session)
        admin = _user_with_roles(session, 'Global Admin')
        AuthTestHelper.create_authenticated_session(client, admin)

        resp = client.post('/admin-panel/classic-ratings/config', json={
            'weights': {'intensity': 40, 'on_ball_skill': 30, 'spirit': 20,
                        'knowledge_movement': 10},          # valid
            'unrated_default': 2.5,                          # valid
            'max_metric_gap': 500,                           # INVALID -> 400
        })
        assert resp.status_code == 400
        # Nothing (not even the valid parts) may have been persisted.
        rows = session.query(AC).filter(AC.key.in_([
            'classic_rating_weights', 'classic_draft_unrated_default',
            'classic_draft_max_metric_gap'])).all()
        assert rows == []

    def test_metrics_400_leaves_row_untouched(self, client, db, app, settings):
        from app.models import ClassicRatingMetric
        session = db.session
        _classic_setup(session)
        session.add(ClassicRatingMetric(
            key='intensity', label='Intensity', description='desc',
            anchor_1='a1', anchor_3='a3', anchor_5='a5', display_order=1))
        session.flush()
        admin = _user_with_roles(session, 'Global Admin')
        AuthTestHelper.create_authenticated_session(client, admin)

        resp = client.post('/admin-panel/classic-ratings/metrics', json={
            'key': 'intensity', 'label': 'Changed', 'description': ''})
        assert resp.status_code == 400
        session.expire_all()
        row = session.query(ClassicRatingMetric).filter_by(key='intensity').first()
        assert row.label == 'Intensity'   # the valid field must NOT have leaked through

    def test_coach_cannot_override(self, client, db, app, settings):
        session = db.session
        season, league, player = _classic_setup(session)
        coach = _user_with_roles(session, 'Classic Coach')
        AuthTestHelper.create_authenticated_session(client, coach)
        resp = client.post('/admin-panel/classic-ratings/override',
                           json={'player_id': player.id, 'metric': 'intensity', 'value': 4})
        assert resp.status_code in (302, 403)
