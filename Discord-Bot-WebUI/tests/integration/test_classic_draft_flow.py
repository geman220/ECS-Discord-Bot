"""
Adversarial integration tests for the balanced-draft surfaces: board-state
correctness against a real session, endpoint role gates, the /draft/classic
template branch + rollback toggle, and config changes reflecting immediately.
"""
import pytest

from app.models import Role
from app.models.admin_config import AdminConfig
from app.services import classic_draft_service
from tests.factories import LeagueFactory, PlayerFactory, SeasonFactory, TeamFactory, UserFactory
from tests.helpers import AuthTestHelper


@pytest.fixture
def settings(monkeypatch):
    store = {
        'classic_ratings_window_open': True,
        'classic_balanced_draft_enabled': True,
    }
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


def _coach_user(session):
    user = UserFactory()
    user.roles.append(_role(session, 'Classic Coach'))
    session.flush()
    return user


def _setup_league(session, team_names=('Team A', 'Team B')):
    season = SeasonFactory(league_type='Pub League', is_current=True)
    league = LeagueFactory(name='Classic', season=season)
    teams = [TeamFactory(name=n, league=league) for n in team_names]
    TeamFactory(name='Practice', league=league)  # must be excluded everywhere
    session.flush()
    return season, league, teams


def _player(session, league, name=None, team=None):
    kwargs = {'is_current_player': True}
    if name:
        kwargs['name'] = name
    player = PlayerFactory(**kwargs)
    player.primary_league_id = league.id
    if team is not None:
        player.teams.append(team)
    session.flush()
    return player


class TestBoardState:
    def test_state_shape_and_practice_exclusion(self, db, app, settings):
        session = db.session
        season, league, teams = _setup_league(session)
        pool_player = _player(session, league, name='Pool Person')
        rostered = _player(session, league, name='Rostered Person', team=teams[0])

        state = classic_draft_service.get_board_state(session)
        assert state['season_id'] == season.id
        team_names = [t['name'] for t in state['teams']]
        assert 'Practice' not in team_names
        assert set(team_names) == {'Team A', 'Team B'}

        pool_ids = [p['id'] for p in state['pool']]
        assert pool_player.id in pool_ids
        assert rostered.id not in pool_ids
        team_a = next(t for t in state['teams'] if t['name'] == 'Team A')
        assert rostered.id in [p['id'] for p in team_a['roster']]

        assert set(state['gaps'].keys()) == set(classic_draft_service.METRICS)
        assert state['config']['max_metric_gap'] == 3.0

    def test_unrated_players_imputed_in_totals(self, db, app, settings):
        session = db.session
        season, league, teams = _setup_league(session)
        _player(session, league, team=teams[0])
        _player(session, league, team=teams[0])

        state = classic_draft_service.get_board_state(session)
        team_a = next(t for t in state['teams'] if t['name'] == 'Team A')
        # 2 unrated players x default 3.0 = 6.0 total per metric
        assert team_a['totals']['metrics']['intensity']['total'] == 6.0
        assert team_a['totals']['unrated_count'] == 2
        # And the gap vs the empty Team B is 6 (over the default limit of 3)
        assert state['gaps']['intensity']['gap'] == 6.0
        assert state['gaps']['intensity']['within_limit'] is False

    def test_suggest_for_team_and_unknown_team(self, db, app, settings):
        session = db.session
        season, league, teams = _setup_league(session)
        _player(session, league)
        suggestions = classic_draft_service.suggest_for_team(session, teams[0].id)
        assert len(suggestions) == 1
        with pytest.raises(ValueError):
            classic_draft_service.suggest_for_team(session, 999999)


class TestEndpoints:
    def test_state_endpoint_role_gate(self, client, db, app, settings):
        session = db.session
        _setup_league(session)
        coach = _coach_user(session)
        AuthTestHelper.create_authenticated_session(client, coach)
        resp = client.get('/classic-draft/state.json')
        assert resp.status_code == 200
        assert resp.get_json()['success'] is True

    def test_state_endpoint_denies_plain_user(self, client, db, app, settings):
        session = db.session
        _setup_league(session)
        user = UserFactory()
        session.flush()
        AuthTestHelper.create_authenticated_session(client, user)
        assert client.get('/classic-draft/state.json').status_code in (302, 403)

    def test_suggestions_endpoint(self, client, db, app, settings):
        session = db.session
        season, league, teams = _setup_league(session)
        _player(session, league)
        coach = _coach_user(session)
        AuthTestHelper.create_authenticated_session(client, coach)

        assert client.get('/classic-draft/suggestions').status_code == 400
        assert client.get('/classic-draft/suggestions?team_id=999999').status_code == 404
        resp = client.get(f'/classic-draft/suggestions?team_id={teams[0].id}')
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['success'] and len(body['suggestions']) == 1
        suggestion = body['suggestions'][0]
        assert 'projection' in suggestion and 'fit_score' in suggestion

    def test_check_endpoint_validation_and_projection(self, client, db, app, settings):
        session = db.session
        season, league, teams = _setup_league(session)
        player = _player(session, league)
        coach = _coach_user(session)
        AuthTestHelper.create_authenticated_session(client, coach)

        assert client.post('/classic-draft/check', json={}).status_code == 400
        resp = client.post('/classic-draft/check', json={
            'assignments': [{'player_id': player.id, 'team_id': teams[0].id}]})
        assert resp.status_code == 200
        step = resp.get_json()['steps'][0]
        assert step['team_id'] == teams[0].id and 'gaps' in step

        resp = client.post('/classic-draft/check', json={
            'assignments': [{'player_id': 999999, 'team_id': teams[0].id}]})
        assert resp.get_json()['steps'][0].get('error')


class TestScoreBlindnessOnDraftSurfaces:
    """The balanced payloads carry averaged final scores — only SCORE_ACCESS
    (Classic Coach/admins/Classic team coaches) may see them (review finding)."""

    def _user_with_role(self, session, role_name):
        user = UserFactory()
        user.roles.append(_role(session, role_name))
        session.flush()
        return user

    @pytest.mark.parametrize('role_name', ['Pub League Coach', 'Premier Coach'])
    def test_state_json_denied_to_non_score_roles(self, client, db, app, settings, role_name):
        session = db.session
        _setup_league(session)
        user = self._user_with_role(session, role_name)
        AuthTestHelper.create_authenticated_session(client, user)
        assert client.get('/classic-draft/state.json').status_code in (302, 403)

    def test_balanced_page_falls_back_to_legacy_for_pub_league_coach(self, client, db, app, settings):
        session = db.session
        _setup_league(session)
        user = self._user_with_role(session, 'Pub League Coach')
        AuthTestHelper.create_authenticated_session(client, user)
        resp = client.get('/draft/classic', follow_redirects=False)
        assert 'draft-balanced-root' not in resp.get_data(as_text=True)

    def test_classic_team_coach_without_role_gets_access(self, client, db, app, settings):
        """Draft-night reality: coach-ness may live only on player_teams."""
        from app.models import player_teams
        from sqlalchemy import update
        session = db.session
        season, league, teams = _setup_league(session)
        coach_player = _player(session, league, team=teams[0])
        session.execute(update(player_teams).where(
            player_teams.c.player_id == coach_player.id,
            player_teams.c.team_id == teams[0].id,
        ).values(is_coach=True))
        session.flush()
        AuthTestHelper.create_authenticated_session(client, coach_player.user)
        assert client.get('/classic-draft/state.json').status_code == 200

    def test_state_json_strips_admin_gender_override(self, client, db, app, settings):
        session = db.session
        season, league, teams = _setup_league(session)
        player = _player(session, league)
        player.balance_gender = 'F'
        session.flush()
        coach = _coach_user(session)
        AuthTestHelper.create_authenticated_session(client, coach)
        body = client.get('/classic-draft/state.json').get_json()
        entry = next(p for p in body['pool'] if p['id'] == player.id)
        assert 'balance_gender' not in entry
        assert entry['gender'] == 'F'   # derived value still present


class TestXssHardening:
    def test_balanced_page_escapes_script_breakout_in_player_fields(self, client, db, app, settings):
        """json.dumps+|safe would let a player named </script>… break out of the
        bootstrap script element (review HIGH finding). tojson must escape it."""
        session = db.session
        season, league, teams = _setup_league(session)
        hostile = _player(session, league, name='</script><script>alert(1)</script>')
        hostile.frequency_play_goal = '</script><img src=x onerror=alert(2)>'
        session.flush()
        coach = _coach_user(session)
        AuthTestHelper.create_authenticated_session(client, coach)
        resp = client.get('/draft/classic')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'draft-balanced-root' in html
        assert '</script><script>alert(1)' not in html
        assert '<img src=x onerror' not in html


class TestDraftPageBranch:
    def test_toggle_on_serves_balanced_board(self, client, db, app, settings):
        session = db.session
        _setup_league(session)
        coach = _coach_user(session)
        AuthTestHelper.create_authenticated_session(client, coach)
        resp = client.get('/draft/classic')
        assert resp.status_code == 200
        assert 'draft-balanced-root' in resp.get_data(as_text=True)

    def test_toggle_off_serves_legacy(self, client, db, app, settings):
        settings['classic_balanced_draft_enabled'] = False
        session = db.session
        _setup_league(session)
        coach = _coach_user(session)
        AuthTestHelper.create_authenticated_session(client, coach)
        resp = client.get('/draft/classic', follow_redirects=False)
        # Legacy path: whatever it renders, it must NOT be the balanced board.
        assert 'draft-balanced-root' not in resp.get_data(as_text=True)

    def test_premier_never_gets_balanced_board(self, client, db, app, settings):
        session = db.session
        season = SeasonFactory(league_type='Pub League', is_current=True)
        LeagueFactory(name='Premier', season=season)
        coach = UserFactory()
        coach.roles.append(_role(session, 'Premier Coach'))
        session.flush()
        AuthTestHelper.create_authenticated_session(client, coach)
        resp = client.get('/draft/premier', follow_redirects=False)
        assert 'draft-balanced-root' not in resp.get_data(as_text=True)


class TestConfigLiveReload:
    def test_gap_change_reflected_next_request(self, db, app, settings, monkeypatch):
        session = db.session
        season, league, teams = _setup_league(session)
        _player(session, league, team=teams[0])
        _player(session, league, team=teams[0])

        state = classic_draft_service.get_board_state(session)
        assert state['gaps']['intensity']['within_limit'] is False  # gap 6 > 3

        settings['classic_draft_max_metric_gap'] = '10'
        state = classic_draft_service.get_board_state(session)
        assert state['gaps']['intensity']['within_limit'] is True
