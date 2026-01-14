"""
Pytest configuration and shared fixtures for all tests.

These fixtures create model instances that match the actual database schema.
"""
import os
import sys
import pytest
from datetime import datetime, date, time, timedelta
from unittest.mock import Mock, patch, MagicMock

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# =============================================================================
# MOCK REDIS CLIENT (module-level so available to all fixtures)
# =============================================================================

_mock_redis_client = MagicMock()
_mock_redis_client.get.return_value = None
_mock_redis_client.set.return_value = True
_mock_redis_client.delete.return_value = 1
_mock_redis_client.exists.return_value = 0
_mock_redis_client.expire.return_value = True
_mock_redis_client.incr.return_value = 1
_mock_redis_client.ping.return_value = True
_mock_redis_client.hget.return_value = None
_mock_redis_client.hset.return_value = True
_mock_redis_client.hgetall.return_value = {}
_mock_redis_client.keys.return_value = []
_mock_redis_client.scan_iter.return_value = iter([])
_mock_redis_client.pipeline.return_value = _mock_redis_client
_mock_redis_client.execute.return_value = []

_mock_redis_manager = MagicMock()
_mock_redis_manager.client = _mock_redis_client
_mock_redis_manager.raw_client = _mock_redis_client
_mock_redis_manager._client = _mock_redis_client
_mock_redis_manager._decoded_client = _mock_redis_client
_mock_redis_manager.get_connection_stats.return_value = {'status': 'mocked'}
_mock_redis_manager.cleanup.return_value = None


@pytest.fixture(scope='session')
def app():
    """Create application for testing with Redis mocked."""
    # Create a wrapper that returns our mock
    mock_redis_wrapper = MagicMock()
    mock_redis_wrapper.client = _mock_redis_client
    mock_redis_wrapper.raw_client = _mock_redis_client
    mock_redis_wrapper.get_connection_stats.return_value = {'status': 'mocked'}

    # Patch Redis BEFORE importing app modules to avoid connection attempts
    # Must patch at all locations where Redis is imported/used
    with patch('app.utils.redis_manager.get_redis_manager', return_value=_mock_redis_manager), \
         patch('app.utils.redis_manager._get_global_redis_manager', return_value=_mock_redis_manager), \
         patch('app.utils.redis_manager.get_redis_connection', return_value=_mock_redis_client), \
         patch('app.utils.redis_manager.UnifiedRedisManager', return_value=_mock_redis_manager), \
         patch('app.services.redis_connection_service.get_redis_service', return_value=mock_redis_wrapper), \
         patch('app.utils.queue_monitor.get_redis_service', return_value=mock_redis_wrapper):

        from app import create_app
        app = create_app('web_config.TestingConfig')

    # Override config for testing
    app.config.update({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'WTF_CSRF_ENABLED': False,
        'SECRET_KEY': 'test-secret-key',
        'JWT_SECRET_KEY': 'test-jwt-secret',
        'REDIS_URL': 'redis://localhost:6379/15',
        'CELERY_TASK_ALWAYS_EAGER': True,  # Execute tasks synchronously
        'CELERY_TASK_EAGER_PROPAGATES': True,
        'SERVER_NAME': 'localhost:5000',
        'PREFERRED_URL_SCHEME': 'http',
        # Disable Redis-based session storage for tests
        'SESSION_TYPE': 'filesystem',
        'SESSION_USE_SIGNER': False,
        'SESSION_PERMANENT': False,
    })

    # Create application context
    ctx = app.app_context()
    ctx.push()

    yield app

    ctx.pop()


@pytest.fixture(scope='session')
def _database(app):
    """Create database for tests."""
    from app.core import db as _db
    _db.create_all()
    yield _db
    _db.drop_all()


@pytest.fixture
def db(_database, app):
    """Create clean database for each test by deleting data after."""
    from tests.factories import set_factory_session

    # Ensure clean session state at START of test (handles previous test failures)
    _database.session.rollback()

    # Set factory session
    set_factory_session(_database.session)

    yield _database

    # Clean up after test - delete all data from tables
    # Order matters due to foreign keys
    with app.app_context():
        _database.session.rollback()  # Clear any pending transaction

        # Delete in order to avoid FK constraint issues
        tables_to_clean = [
            'availability', 'player_teams', 'matches', 'schedules',
            'players', 'teams', 'leagues', 'seasons',
            'user_roles', 'users', 'roles'
        ]

        for table in tables_to_clean:
            try:
                _database.session.execute(_database.text(f'DELETE FROM {table}'))
            except Exception:
                pass  # Table might not exist or other issue

        _database.session.commit()
        _database.session.remove()


@pytest.fixture(autouse=True)
def mock_celery_tasks(monkeypatch):
    """Mock Celery tasks to prevent Redis/broker connection errors."""
    from unittest.mock import MagicMock

    # Create mock tasks that don't require Celery broker
    mock_task = MagicMock()
    mock_task.delay = MagicMock(return_value=MagicMock(id='mock-task-id'))
    mock_task.apply_async = MagicMock(return_value=MagicMock(id='mock-task-id'))

    # Mock RSVP-related Celery tasks
    try:
        import app.match_pages as match_pages
        monkeypatch.setattr(match_pages, 'notify_discord_of_rsvp_change_task', mock_task, raising=False)
        monkeypatch.setattr(match_pages, 'update_discord_rsvp_task', mock_task, raising=False)
    except (ImportError, AttributeError):
        pass

    try:
        import app.tasks.tasks_rsvp as tasks_rsvp
        monkeypatch.setattr(tasks_rsvp, 'notify_discord_of_rsvp_change_task', mock_task, raising=False)
    except (ImportError, AttributeError):
        pass


@pytest.fixture
def client(app, db):
    """Create Flask test client."""
    return app.test_client()


@pytest.fixture
def runner(app):
    """Create Flask CLI runner."""
    return app.test_cli_runner()


@pytest.fixture
def authenticated_client(client, user):
    """Create authenticated test client."""
    with client.session_transaction() as session:
        # Flask-Login uses _user_id as the session key
        session['_user_id'] = user.id
        session['_fresh'] = True
    return client


@pytest.fixture
def admin_client(client, admin_user):
    """Create admin authenticated test client."""
    with client.session_transaction() as session:
        # Flask-Login uses _user_id as the session key
        session['_user_id'] = admin_user.id
        session['_fresh'] = True
    return client


# =============================================================================
# ROLE FIXTURES
# =============================================================================

@pytest.fixture
def user_role(db):
    """Create or get user role with basic permissions."""
    from app.models import Role, Permission

    role = Role.query.filter_by(name='User').first()
    if not role:
        role = Role(name='User', description='Regular user')
        db.session.add(role)
        db.session.flush()

    # Add view_rsvps permission if not already present
    view_rsvps = Permission.query.filter_by(name='view_rsvps').first()
    if not view_rsvps:
        view_rsvps = Permission(name='view_rsvps', description='Can view and manage RSVPs')
        db.session.add(view_rsvps)
        db.session.flush()

    if view_rsvps not in role.permissions:
        role.permissions.append(view_rsvps)

    db.session.commit()
    return role


@pytest.fixture
def admin_role(db):
    """Create or get admin role."""
    from app.models import Role
    role = Role.query.filter_by(name='Admin').first()
    if not role:
        role = Role(name='Admin', description='Administrator')
        db.session.add(role)
        db.session.commit()
    return role


# =============================================================================
# USER FIXTURES
# =============================================================================

@pytest.fixture
def user(db, user_role):
    """Create test user."""
    from app.models import User
    user = User(
        username='testuser',
        email='test@example.com',
        is_approved=True,
        approval_status='approved'
    )
    user.set_password('password123')
    user.roles.append(user_role)
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def admin_user(db, admin_role):
    """Create admin user."""
    from app.models import User
    admin = User(
        username='admin',
        email='admin@example.com',
        is_approved=True,
        approval_status='approved'
    )
    admin.set_password('admin123')
    admin.roles.append(admin_role)
    db.session.add(admin)
    db.session.commit()
    return admin


# =============================================================================
# SEASON & LEAGUE FIXTURES
# =============================================================================

@pytest.fixture
def season(db):
    """
    Create test season.

    Season model fields:
    - name: String, required
    - league_type: String, required
    - is_current: Boolean
    """
    from app.models import Season
    season = Season(
        name='Test Season 2024',
        league_type='CLASSIC',
        is_current=True
    )
    db.session.add(season)
    db.session.commit()
    return season


@pytest.fixture
def league(db, season):
    """
    Create test league.

    League model fields:
    - name: String, required
    - season_id: ForeignKey, required
    """
    from app.models import League
    league = League(
        name='Test League',
        season_id=season.id
    )
    db.session.add(league)
    db.session.commit()
    return league


# =============================================================================
# TEAM FIXTURES
# =============================================================================

@pytest.fixture
def team(db, league):
    """
    Create test team.

    Team model fields:
    - name: String, required
    - league_id: ForeignKey, required
    """
    from app.models import Team
    team = Team(
        name='Test Team',
        league_id=league.id
    )
    db.session.add(team)
    db.session.commit()
    return team


@pytest.fixture
def opponent_team(db, league):
    """Create opponent team for matches."""
    from app.models import Team
    team = Team(
        name='Opponent Team',
        league_id=league.id
    )
    db.session.add(team)
    db.session.commit()
    return team


# =============================================================================
# PLAYER FIXTURES
# =============================================================================

@pytest.fixture
def player(db, user, team):
    """
    Create test player linked to user.

    Player model fields:
    - name: String, required
    - user_id: ForeignKey to users.id, required
    - discord_id: String, unique
    - jersey_number, jersey_size, etc.

    Note: Player-Team is many-to-many via player_teams table.
    """
    import uuid
    from app.models import Player
    player = Player(
        name='Test Player',
        user_id=user.id,
        discord_id=f'test_discord_{uuid.uuid4().hex[:12]}',  # Unique per test
        jersey_number=10,
        jersey_size='M'
    )
    db.session.add(player)
    db.session.flush()
    # Add to team via relationship
    player.teams.append(team)
    db.session.commit()
    return player


# =============================================================================
# SCHEDULE & MATCH FIXTURES
# =============================================================================

@pytest.fixture
def schedule(db, season, team, opponent_team):
    """
    Create test schedule.

    Schedule model fields:
    - week: String, required
    - date: Date, required
    - time: Time, required
    - opponent: ForeignKey to team.id, required
    - location: String, required
    - team_id: ForeignKey, required
    - season_id: ForeignKey
    """
    from app.models import Schedule
    schedule = Schedule(
        week='Week 1',
        date=date.today() + timedelta(days=7),
        time=time(19, 0),  # 7 PM
        opponent=opponent_team.id,
        location='Main Field',
        team_id=team.id,
        season_id=season.id
    )
    db.session.add(schedule)
    db.session.commit()
    return schedule


@pytest.fixture
def match(db, schedule, team, opponent_team):
    """
    Create test match.

    Match model fields:
    - date: Date, required
    - time: Time, required
    - location: String, required
    - home_team_id, away_team_id: ForeignKey, required
    - schedule_id: ForeignKey, required
    """
    from app.models import Match
    match = Match(
        date=schedule.date,
        time=schedule.time,
        location=schedule.location,
        home_team_id=team.id,
        away_team_id=opponent_team.id,
        schedule_id=schedule.id
    )
    db.session.add(match)
    db.session.commit()
    return match


# =============================================================================
# AVAILABILITY/RSVP FIXTURES
# =============================================================================

@pytest.fixture
def availability(db, match, player):
    """
    Create test availability (RSVP).

    Availability model fields:
    - match_id: ForeignKey, required
    - player_id: ForeignKey
    - discord_id: String, required
    - response: String ('yes', 'no', 'maybe')
    """
    from app.models import Availability
    avail = Availability(
        match_id=match.id,
        player_id=player.id,
        discord_id=player.discord_id,
        response='yes'
    )
    db.session.add(avail)
    db.session.commit()
    return avail


# =============================================================================
# MOCK FIXTURES
# =============================================================================

@pytest.fixture(autouse=True)
def mock_redis():
    """Return the module-level mocked Redis client for tests that need it.

    Note: Redis is already mocked at module level before app import.
    This fixture just provides access to the mock for assertions.
    """
    return _mock_redis_client


@pytest.fixture
def mock_celery(monkeypatch):
    """Mock Celery tasks."""
    mock = Mock()
    monkeypatch.setattr('app.core.celery', mock)
    return mock


@pytest.fixture
def mock_twilio(monkeypatch):
    """Mock SMS sending functionality."""
    mock = Mock()
    mock.return_value = (True, 'TEST_MESSAGE_SID')
    monkeypatch.setattr('app.sms_helpers.send_sms', mock)
    return mock


@pytest.fixture
def mock_discord(monkeypatch):
    """Mock Discord operations - provides mock for Discord API calls."""
    mock = Mock()
    # This is a general-purpose mock that tests can configure as needed
    return mock


@pytest.fixture
def mock_smtp(monkeypatch):
    """Mock email sending functionality."""
    mock = Mock()
    mock.return_value = {'id': 'TEST_EMAIL_ID'}
    monkeypatch.setattr('app.email.send_email', mock)
    return mock


# =============================================================================
# HELPER FIXTURES
# =============================================================================

@pytest.fixture
def auth_headers(user):
    """Create JWT auth headers."""
    from flask_jwt_extended import create_access_token
    token = create_access_token(identity=user.id)
    return {'Authorization': f'Bearer {token}'}


@pytest.fixture
def api_key_headers():
    """Create API key headers."""
    return {'X-API-Key': 'test-api-key-123'}


# =============================================================================
# PLAYWRIGHT FIXTURES - Mobile Browser Automation
# =============================================================================

from playwright.sync_api import sync_playwright
import threading
from werkzeug.serving import make_server

# MOBILE DEVICE CONFIGURATIONS
MOBILE_DEVICES = {
    'iphone_13': {
        'viewport': {'width': 390, 'height': 844},
        'user_agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1',
        'device_scale_factor': 3,
        'is_mobile': True,
        'has_touch': True,
    },
    'iphone_13_pro_max': {
        'viewport': {'width': 428, 'height': 926},
        'user_agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1',
        'device_scale_factor': 3,
        'is_mobile': True,
        'has_touch': True,
    },
    'ipad_air': {
        'viewport': {'width': 820, 'height': 1180},
        'user_agent': 'Mozilla/5.0 (iPad; CPU OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1',
        'device_scale_factor': 2,
        'is_mobile': True,
        'has_touch': True,
    },
    'samsung_s21': {
        'viewport': {'width': 360, 'height': 800},
        'user_agent': 'Mozilla/5.0 (Linux; Android 11; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.120 Mobile Safari/537.36',
        'device_scale_factor': 3,
        'is_mobile': True,
        'has_touch': True,
    },
}


@pytest.fixture(scope='session')
def live_server(app):
    """Start Flask test server in background thread."""
    server = make_server('127.0.0.1', 5555, app)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()

    # Return server URL
    class LiveServer:
        @staticmethod
        def url():
            return 'http://127.0.0.1:5555'

    yield LiveServer()
    server.shutdown()


@pytest.fixture(scope='session')
def browser():
    """Launch browser instance for entire test session."""
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=['--disable-dev-shm-usage']  # Prevent crashes in CI
        )
        yield browser
        browser.close()


@pytest.fixture
def mobile_context(browser, request):
    """Create mobile browser context with device emulation."""
    device_name = getattr(request, 'param', 'iphone_13')
    device = MOBILE_DEVICES.get(device_name, MOBILE_DEVICES['iphone_13'])

    context = browser.new_context(**device)
    yield context
    context.close()


@pytest.fixture
def mobile_page(mobile_context, live_server):
    """Create mobile page connected to Flask test server."""
    page = mobile_context.new_page()
    page.goto(live_server.url())
    yield page
    page.close()


@pytest.fixture
def authenticated_mobile_page(mobile_page, app, user):
    """Mobile page with authenticated session."""
    # Use Flask test client to create session
    with app.test_client() as client:
        # Login via test endpoint
        response = client.post('/login', data={
            'username': user.username,
            'password': 'testpassword'
        }, follow_redirects=True)

        # Copy session cookies to Playwright
        if hasattr(client, 'cookie_jar'):
            for cookie in client.cookie_jar:
                mobile_page.context.add_cookies([{
                    'name': cookie.name,
                    'value': cookie.value,
                    'domain': 'localhost',
                    'path': cookie.path or '/',
                    'expires': -1  # Session cookie
                }])

    mobile_page.reload()
    yield mobile_page
