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
# PATCH JSONB FOR SQLITE COMPATIBILITY (must be done before importing models)
# =============================================================================
# SQLite doesn't support JSONB, so we patch it to use JSON instead.
# This must happen before any models that use JSONB are imported.

from sqlalchemy import JSON
from sqlalchemy.dialects import postgresql

# Create a JSON type that behaves like JSONB for SQLite
class SQLiteCompatibleJSONB(JSON):
    """JSONB replacement that works with SQLite - just uses JSON."""
    pass

# Patch the JSONB in postgresql dialects so imports use our compatible version
postgresql.JSONB = SQLiteCompatibleJSONB
postgresql.json.JSONB = SQLiteCompatibleJSONB

# =============================================================================
# MOCK REDIS CLIENT (must be done before any app imports)
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

# Apply patches globally at the module level
patch('app.utils.redis_manager.get_redis_manager', return_value=_mock_redis_manager).start()
patch('app.utils.redis_manager._get_global_redis_manager', return_value=_mock_redis_manager).start()
patch('app.utils.redis_manager.get_redis_connection', return_value=_mock_redis_client).start()
patch('app.utils.redis_manager.UnifiedRedisManager', return_value=_mock_redis_manager).start()
patch('app.services.redis_connection_service.get_redis_service', return_value=_mock_redis_manager).start()
patch('app.utils.queue_monitor.get_redis_service', return_value=_mock_redis_manager).start()

@pytest.fixture(scope='session')
def app():
    """Create application for testing with Redis mocked."""
    from app import create_app
    app = create_app('web_config.TestingConfig')

    # Local development: Use SQLite in-memory with StaticPool
    # StaticPool is CRITICAL for SQLite in-memory databases - without it,
    # each connection creates a new empty database.
    from sqlalchemy.pool import StaticPool
    app.config.update({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_ENGINE_OPTIONS': {
            'poolclass': StaticPool,
            'connect_args': {'check_same_thread': False},
        },
        'WTF_CSRF_ENABLED': False,
        'SECRET_KEY': 'test-secret-key',
        'JWT_SECRET_KEY': 'test-jwt-secret',
        'REDIS_URL': 'redis://localhost:6379/15',
        'CELERY_TASK_ALWAYS_EAGER': True,
        'CELERY_TASK_EAGER_PROPAGATES': True,
        'SERVER_NAME': 'localhost:5000',
        'PREFERRED_URL_SCHEME': 'http',
        'SESSION_TYPE': 'filesystem',
        'SESSION_USE_SIGNER': False,
        'SESSION_PERMANENT': False,
    })

    # Create application context
    ctx = app.app_context()
    ctx.push()
    
    # Sync g.db_session to ensure it exists in the pushed context
    from flask import g
    from app.core import db as _db
    g.db_session = _db.session

    yield app

    # Cleanup after yield
    from flask import has_app_context
    if has_app_context():
        # Clear session to avoid leaks between tests
        _db.session.remove()
    
    ctx.pop()


@pytest.fixture(scope='session')
def _database(app):
    """Create database for tests."""
    from app.core import db as _db

    # Create all tables once for the test session
    _db.create_all()
    
    # CRITICAL: Prevent DetachedInstanceError after commit globally
    _db.session.expire_on_commit = False
    
    yield _db
    _db.drop_all()


@pytest.fixture
def db(_database, app):
    """Create clean database for each test by deleting data after."""
    from tests.factories import set_factory_session
    from flask import g, has_app_context

    # Ensure a clean state for EVERY test
    _database.session.rollback()
    _database.session.expunge_all()
    
    # CRITICAL: Prevent DetachedInstanceError after commit
    _database.session.expire_on_commit = False

    # Sync g.db_session if we have an app context
    if has_app_context():
        g.db_session = _database.session

    # Set factory session
    set_factory_session(_database.session)

    yield _database

    # Clean up after test - delete all data from tables
    with app.app_context():
        _database.session.rollback()  # Clear any pending transaction
        
        # Re-sync g.db_session for cleanup phase
        g.db_session = _database.session

        # Disable FK constraints for SQLite during cleanup
        try:
            _database.session.execute(_database.text('PRAGMA foreign_keys = OFF'))
        except Exception:
            pass

        # Delete in order to avoid FK constraint issues
        tables_to_clean = [
            'admin_audit_log', 'audit_logs', 'stat_change_logs', 'player_stat_audits',
            'player_season_stats', 'player_career_stats',
            'match_events', 'sub_requests', 'availability', 'match_predictions',
            'mls_matches', 'match_dates',
            'player_teams', 'player_league', 'player_team_season',
            'matches', 'schedule', 'week_configurations',
            'device_tokens', 'progress', 'sms_logs', 'discord_bot_status',
            'help_topics', 'feedback_replies', 'feedbacks', 'notes',
            'player', 'team', 'league', 'season',
            'notifications', 'announcements',
            'user_roles', 'role_permissions',
            'users', 'roles', 'permissions'
        ]

        for table in tables_to_clean:
            try:
                _database.session.execute(_database.text(f'DELETE FROM {table}'))
            except Exception:
                pass

        # Re-enable FK constraints
        try:
            _database.session.execute(_database.text('PRAGMA foreign_keys = ON'))
        except Exception:
            pass

        _database.session.commit()
        # CRITICAL: Ensure session is removed after cleanup
        _database.session.remove()


@pytest.fixture(autouse=True)
def mock_celery_tasks(monkeypatch):
    """Mock Celery tasks to prevent Redis/broker connection errors."""
    mock_task = MagicMock()
    mock_task.delay = MagicMock(return_value=MagicMock(id='mock-task-id'))
    mock_task.apply_async = MagicMock(return_value=MagicMock(id='mock-task-id'))

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
def authenticated_client(client, user, db):
    """Create authenticated test client."""
    # Ensure user is attached to session
    if user not in db.session:
        user = db.session.merge(user)
    
    user_id = user.id
    
    with client.session_transaction() as session:
        session['_user_id'] = user_id
        session['_fresh'] = True
    return client

@pytest.fixture
def admin_client(client, admin_user, db):
    """Create admin authenticated test client."""
    # Ensure user is attached to session
    if admin_user not in db.session:
        admin_user = db.session.merge(admin_user)
    
    user_id = admin_user.id
    
    with client.session_transaction() as session:
        session['_user_id'] = user_id
        session['_fresh'] = True
    return client


# =============================================================================
# ROLE FIXTURES
# =============================================================================

@pytest.fixture
def user_role(db):
    """Create or get user role with basic permissions."""
    from app.models import Role, Permission

    role = db.session.query(Role).filter_by(name='User').first()
    if not role:
        role = Role(name='User', description='Regular user')
        db.session.add(role)
        db.session.flush()

    view_rsvps = db.session.query(Permission).filter_by(name='view_rsvps').first()
    if not view_rsvps:
        view_rsvps = Permission(name='view_rsvps', description='Can view and manage RSVPs')
        db.session.add(view_rsvps)
        db.session.flush()

    if view_rsvps not in role.permissions:
        role.permissions.append(view_rsvps)

    db.session.flush()
    return role


@pytest.fixture
def admin_role(db):
    """Create or get admin role."""
    from app.models import Role
    role = db.session.query(Role).filter_by(name='Admin').first()
    if not role:
        role = Role(name='Admin', description='Administrator')
        db.session.add(role)
        db.session.flush()
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
    db.session.flush()
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
    db.session.flush()
    return admin


# =============================================================================
# SEASON & LEAGUE FIXTURES
# =============================================================================

@pytest.fixture
def season(db):
    """Create test season."""
    from app.models import Season
    season = Season(
        name='Test Season 2024',
        league_type='CLASSIC',
        is_current=True
    )
    db.session.add(season)
    db.session.flush()
    return season


@pytest.fixture
def league(db, season):
    """Create test league."""
    from app.models import League
    league = League(
        name='Test League',
        season_id=season.id
    )
    db.session.add(league)
    db.session.flush()
    return league


# =============================================================================
# TEAM FIXTURES
# =============================================================================

@pytest.fixture
def team(db, league):
    """Create test team."""
    from app.models import Team
    team = Team(
        name='Test Team',
        league_id=league.id
    )
    db.session.add(team)
    db.session.flush()
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
    db.session.flush()
    return team


# =============================================================================
# PLAYER FIXTURES
# =============================================================================

@pytest.fixture
def player(db, user, team):
    """Create test player linked to user."""
    import uuid
    from app.models import Player
    
    # Ensure user and team are attached to the session
    if user not in db.session:
        user = db.session.merge(user)
    if team not in db.session:
        team = db.session.merge(team)
        
    user_id = user.id
    
    player = Player(
        name='Test Player',
        user_id=user_id,
        discord_id=f'test_discord_{uuid.uuid4().hex[:12]}',
        jersey_number=10,
        jersey_size='M'
    )
    db.session.add(player)
    db.session.flush()
    player.teams.append(team)
    db.session.flush()
    return player


# =============================================================================
# SCHEDULE & MATCH FIXTURES
# =============================================================================

@pytest.fixture
def schedule(db, season, team, opponent_team):
    """Create test schedule."""
    from app.models import Schedule
    schedule = Schedule(
        week='Week 1',
        date=date.today() + timedelta(days=7),
        time=time(19, 0),
        location='Test Field',
        opponent=opponent_team.id,
        team_id=team.id,
        season_id=season.id
    )
    db.session.add(schedule)
    db.session.flush()
    return schedule


@pytest.fixture
def match(db, schedule, team, opponent_team):
    """Create test match."""
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
    db.session.flush()
    
    # Critical: Link schedule back to match if needed (circular FK often causes issues)
    schedule.match_id = match.id
    db.session.flush()
    
    return match


# =============================================================================
# AVAILABILITY/RSVP FIXTURES
# =============================================================================

@pytest.fixture
def availability(db, match, player):
    """Create test availability (RSVP)."""
    from app.models import Availability
    avail = Availability(
        match_id=match.id,
        player_id=player.id,
        discord_id=player.discord_id,
        response='yes'
    )
    db.session.add(avail)
    db.session.flush()
    return avail


# =============================================================================
# MOCK FIXTURES
# =============================================================================

@pytest.fixture(autouse=True)
def mock_redis():
    """Return the module-level mocked Redis client."""
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
    """Mock Discord operations."""
    mock = Mock()
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
# PLAYWRIGHT FIXTURES
# =============================================================================

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

import threading
from werkzeug.serving import make_server

@pytest.fixture(scope='session')
def live_server(app):
    """Start Flask test server."""
    server = make_server('127.0.0.1', 5555, app)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()

    class LiveServer:
        @staticmethod
        def url():
            return 'http://127.0.0.1:5555'

    yield LiveServer()
    server.shutdown()


@pytest.fixture(scope='session')
def browser():
    """Launch browser instance."""
    if not PLAYWRIGHT_AVAILABLE:
        pytest.skip("Playwright not installed")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()
