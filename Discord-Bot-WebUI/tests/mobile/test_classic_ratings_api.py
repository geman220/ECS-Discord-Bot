"""
Mobile contract tests for the Classic ratings + balanced-draft API
(/api/v1/classic-ratings/*, /api/v1/classic-board, /api/v1/draft/classic/balance).
Response shapes here are the contract in docs/flutter-classic-rating-draft-contract.md.
"""
import pytest
from flask_jwt_extended import create_access_token

from app.models import Role
from app.models.admin_config import AdminConfig
from app.services import classic_rating_service as svc
from tests.factories import LeagueFactory, PlayerFactory, SeasonFactory, TeamFactory, UserFactory


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


def _auth(app, user):
    with app.app_context():
        token = create_access_token(identity=str(user.id),
                                    additional_claims={'approved': True})
    return {'Authorization': f'Bearer {token}'}


def _setup(session):
    season = SeasonFactory(league_type='Pub League', is_current=True)
    league = LeagueFactory(name='Classic', season=season)
    team = TeamFactory(name='Team A', league=league)
    player = PlayerFactory(is_current_player=True)
    player.primary_league_id = league.id
    session.flush()
    return season, league, team, player


class TestRatingEndpoints:
    def test_players_blind_and_shape(self, client, db, app, settings):
        session = db.session
        season, league, team, player = _setup(session)
        coach_a = UserFactory(); coach_a.roles.append(_role(session, 'Classic Coach'))
        coach_b = UserFactory(); coach_b.roles.append(_role(session, 'Classic Coach'))
        session.flush()
        svc.upsert_rating(session, season.id, coach_a.id, player.id, {'intensity': '4.77'})
        session.commit()

        resp = client.get('/api/v1/classic-ratings/players', headers=_auth(app, coach_b))
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['success'] and body['window_open'] is True
        entry = next(p for p in body['players'] if p['id'] == player.id)
        assert entry['my_rating'] is None            # blind: coach A's row absent
        assert '4.77' not in resp.get_data(as_text=True)
        # contract fields
        for field in ('name', 'is_new', 'favorite_position', 'other_positions',
                      'gk_willingness', 'attendance_rate', 'career_goals'):
            assert field in entry

    def test_upsert_roundtrip_and_errors(self, client, db, app, settings):
        session = db.session
        season, league, team, player = _setup(session)
        coach = UserFactory(); coach.roles.append(_role(session, 'Classic Coach'))
        session.flush()
        session.commit()
        headers = _auth(app, coach)

        resp = client.put(f'/api/v1/classic-ratings/players/{player.id}',
                          headers=headers, json={'intensity': 2.75, 'spirit': 4})
        assert resp.status_code == 200
        rating = resp.get_json()['rating']
        assert rating['intensity'] == 2.75 and rating['is_complete'] is False

        assert client.put(f'/api/v1/classic-ratings/players/{player.id}',
                          headers=headers, json={'intensity': 9}).status_code == 400
        assert client.put('/api/v1/classic-ratings/players/999999',
                          headers=headers, json={'intensity': 3}).status_code == 404
        assert client.put(f'/api/v1/classic-ratings/players/{player.id}',
                          headers=headers, json={}).status_code == 400

        settings['classic_ratings_window_open'] = False
        resp = client.put(f'/api/v1/classic-ratings/players/{player.id}',
                          headers=headers, json={'intensity': 3})
        assert resp.status_code == 403
        assert resp.get_json()['error'] == 'WINDOW_CLOSED'

    def test_role_gates(self, client, db, app, settings):
        session = db.session
        _setup(session)
        plain = UserFactory()
        session.flush(); session.commit()
        headers = _auth(app, plain)
        assert client.get('/api/v1/classic-ratings/players', headers=headers).status_code == 403
        assert client.get('/api/v1/classic-ratings/config', headers=headers).status_code == 403
        assert client.get('/api/v1/classic-ratings/admin/summary', headers=headers).status_code == 403
        assert client.get('/api/v1/classic-ratings/players').status_code == 401  # no token

    def test_config_shape(self, client, db, app, settings):
        session = db.session
        _setup(session)
        coach = UserFactory(); coach.roles.append(_role(session, 'Classic Coach'))
        session.flush(); session.commit()
        resp = client.get('/api/v1/classic-ratings/config', headers=_auth(app, coach))
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['window_open'] is True and 'max_metric_gap' in body
        assert isinstance(body['metrics'], list)


class TestBoardAndDraftEndpoints:
    def test_board_scores_gated_by_role(self, client, db, app, settings):
        session = db.session
        season, league, team, player = _setup(session)
        classic = UserFactory(); classic.roles.append(_role(session, 'Classic Coach'))
        pub = UserFactory(); pub.roles.append(_role(session, 'Pub League Coach'))
        session.flush(); session.commit()

        body = client.get('/api/v1/classic-board', headers=_auth(app, classic)).get_json()
        entry = next(p for p in body['players'] if p['id'] == player.id)
        assert 'ratings' in entry              # score viewer
        assert 'balance_gender' not in entry   # admin-only field stripped

        body = client.get('/api/v1/classic-board', headers=_auth(app, pub)).get_json()
        entry = next(p for p in body['players'] if p['id'] == player.id)
        assert 'ratings' not in entry          # basic view, no scores

    def test_draft_balance_state(self, client, db, app, settings):
        session = db.session
        season, league, team, player = _setup(session)
        coach = UserFactory(); coach.roles.append(_role(session, 'Classic Coach'))
        session.flush(); session.commit()
        resp = client.get('/api/v1/draft/classic/balance', headers=_auth(app, coach))
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['success']
        assert [t['name'] for t in body['teams']] == ['Team A']
        assert player.id in [p['id'] for p in body['pool']]
        assert set(body['gaps'].keys()) == set(svc.METRICS)

    def test_draft_suggestions_endpoint(self, client, db, app, settings):
        session = db.session
        season, league, team, player = _setup(session)
        coach = UserFactory(); coach.roles.append(_role(session, 'Classic Coach'))
        session.flush(); session.commit()
        headers = _auth(app, coach)
        assert client.get('/api/v1/draft/classic/suggestions', headers=headers).status_code == 400
        resp = client.get(f'/api/v1/draft/classic/suggestions?team_id={team.id}', headers=headers)
        assert resp.status_code == 200
        suggestions = resp.get_json()['suggestions']
        assert suggestions and suggestions[0]['player_id'] == player.id
        assert 'projection' in suggestions[0]

    def test_admin_override_endpoint(self, client, db, app, settings, monkeypatch):
        from app.models.admin_config import AdminAuditLog
        monkeypatch.setattr(AdminAuditLog, 'log_action',
                            classmethod(lambda cls, **kwargs: None))
        session = db.session
        season, league, team, player = _setup(session)
        admin = UserFactory(); admin.roles.append(_role(session, 'Pub League Admin'))
        session.flush(); session.commit()
        headers = _auth(app, admin)

        resp = client.put('/api/v1/classic-ratings/admin/override', headers=headers,
                          json={'player_id': player.id, 'metric': 'spirit', 'value': 4.25})
        assert resp.status_code == 200

        summary = client.get('/api/v1/classic-ratings/admin/summary', headers=headers).get_json()
        final = summary['finals'][str(player.id)]
        assert final['metrics']['spirit']['value'] == 4.25
        assert final['metrics']['spirit']['overridden'] is True
