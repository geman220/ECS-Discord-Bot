"""
Pytest configuration and shared fixtures for all tests.
"""
import os
import sys
import pytest
from datetime import datetime
from unittest.mock import Mock, patch

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from app.core import db as _db
from app.models import User, Role, League, Season, Team, Player, Match
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

# Import test helpers
from tests.helpers import SMSTestHelper, AuthTestHelper


@pytest.fixture(scope='session')
def app():
    """Create application for testing."""
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
    _db.create_all()
    yield _db
    _db.drop_all()


@pytest.fixture
def db(_database):
    """Create clean database for each test."""
    connection = _database.engine.connect()
    transaction = connection.begin()
    
    # Configure session
    session_factory = sessionmaker(bind=connection)
    _database.session = scoped_session(session_factory)
    
    # Begin nested transaction
    _database.session.begin_nested()
    
    yield _database
    
    # Rollback transaction
    _database.session.rollback()
    transaction.rollback()
    connection.close()
    _database.session.remove()


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
        session['user_id'] = user.id
        session['_fresh'] = True
    return client


@pytest.fixture
def admin_client(client, admin_user):
    """Create admin authenticated test client."""
    with client.session_transaction() as session:
        session['user_id'] = admin_user.id
        session['_fresh'] = True
    return client


# User fixtures
@pytest.fixture
def user_role(db):
    """Create user role."""
    role = Role(name='User', description='Regular user')
    db.session.add(role)
    db.session.commit()
    return role


@pytest.fixture
def admin_role(db):
    """Create admin role."""
    role = Role(name='Admin', description='Administrator')
    db.session.add(role)
    db.session.commit()
    return role


@pytest.fixture
def user(db, user_role):
    """Create test user."""
    user = User(
        username='testuser',
        email='test@example.com',
        is_approved=True
    )
    user.set_password('password123')
    user.roles.append(user_role)
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def admin_user(db, admin_role):
    """Create admin user."""
    admin = User(
        username='admin',
        email='admin@example.com',
        is_approved=True
    )
    admin.set_password('admin123')
    admin.roles.append(admin_role)
    db.session.add(admin)
    db.session.commit()
    return admin


# League/Season fixtures
@pytest.fixture
def season(db):
    """Create test season."""
    season = Season(
        name='Test Season 2024',
        start_date=datetime(2024, 1, 1),
        end_date=datetime(2024, 12, 31),
        is_active=True
    )
    db.session.add(season)
    db.session.commit()
    return season


@pytest.fixture
def league(db, season):
    """Create test league."""
    league = League(
        name='Test League',
        season_id=season.id
    )
    db.session.add(league)
    db.session.commit()
    return league




@pytest.fixture
def team(db, league):
    """Create test team."""
    team = Team(
        name='Test Team',
        league_id=league.id,
        captain_id=None  # Will be set when needed
    )
    db.session.add(team)
    db.session.commit()
    return team


@pytest.fixture
def player(db, user, team):
    """Create test player."""
    player = Player(
        user_id=user.id,
        team_id=team.id,
        jersey_number=10,
        jersey_size='M',
        positions='Forward,Midfielder'
    )
    db.session.add(player)
    db.session.commit()
    return player


@pytest.fixture
def match(db, season, team):
    """Create test match."""
    # Create opponent team
    opponent = Team(
        name='Opponent Team',
        league_id=team.league_id
    )
    db.session.add(opponent)
    db.session.commit()
    
    match = Match(
        season_id=season.id,
        home_team_id=team.id,
        away_team_id=opponent.id,
        scheduled_date=datetime(2024, 6, 1),
        scheduled_time='19:00',
        field_name='Main Field'
    )
    db.session.add(match)
    db.session.commit()
    return match


# Mock fixtures
@pytest.fixture(autouse=True)
def mock_redis(monkeypatch):
    """Mock Redis client - applied automatically to all tests."""
    mock = Mock()
    mock.get.return_value = None
    mock.set.return_value = True
    mock.delete.return_value = 1
    mock.exists.return_value = 0
    mock.expire.return_value = True
    mock.incr.return_value = 1
    mock.pipeline.return_value = mock
    mock.execute.return_value = []
    mock.ping.return_value = True
    
    # Mock the RedisManager class completely
    mock_redis_manager = Mock()
    mock_redis_manager.client = mock
    mock_redis_manager._client = mock
    
    # Replace RedisManager class with our mock
    monkeypatch.setattr('app.utils.redis_manager.RedisManager', lambda: mock_redis_manager)
    
    # Mock Redis connection completely to avoid connection attempts
    def mock_redis_init(*args, **kwargs):
        return mock
    
    monkeypatch.setattr('redis.Redis', mock_redis_init)
    monkeypatch.setattr('redis.from_url', lambda url: mock)
    
    return mock


@pytest.fixture
def mock_celery(monkeypatch):
    """Mock Celery tasks."""
    mock = Mock()
    monkeypatch.setattr('app.core.celery', mock)
    return mock


@pytest.fixture
def mock_twilio(monkeypatch):
    """Mock Twilio client."""
    mock = Mock()
    mock.messages.create.return_value = Mock(sid='TEST_MESSAGE_SID')
    monkeypatch.setattr('app.sms_helpers.twilio_client', mock)
    return mock


@pytest.fixture
def mock_discord(monkeypatch):
    """Mock Discord operations."""
    mock = Mock()
    monkeypatch.setattr('app.discord_utils.discord_client', mock)
    return mock


@pytest.fixture
def mock_smtp(monkeypatch):
    """Mock SMTP for email testing."""
    with patch('app.email.mail') as mock_mail:
        yield mock_mail


# Helper fixtures
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