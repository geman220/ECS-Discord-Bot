"""
Web Configuration Module

This module defines the configuration settings for the Flask application,
including database, session, external service credentials, Celery, and JWT settings.
Values are loaded primarily from environment variables.
"""

from datetime import timedelta, datetime
import os

import pytz

class Config:
    """Application configuration settings."""
    # Basic Flask/App Configuration
    SECRET_KEY = os.getenv('SECRET_KEY')
    MATCH_CHANNEL_ID = os.getenv('MATCH_CHANNEL_ID')
    
    # Security settings
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    PREFERRED_URL_SCHEME = 'https'
    
    # Mobile API settings
    MOBILE_API_KEY = os.getenv('MOBILE_API_KEY', 'ecs-soccer-mobile-key')
    # Set MOBILE_APP_ALLOWED_NETWORKS='' in production to allow access from any IP with valid API key
    # For local development, restrict to local networks
    MOBILE_APP_ALLOWED_NETWORKS = os.getenv('MOBILE_APP_ALLOWED_NETWORKS', '192.168.1.0/24,192.168.0.0/24')
    WEBUI_BASE_URL = os.getenv('WEBUI_BASE_URL', 'https://ecs-soccer.org')
    
    # Security Configuration
    SECURITY_LOG_RETENTION_DAYS = int(os.getenv('SECURITY_LOG_RETENTION_DAYS', 90))  # Keep security logs for 90 days
    SECURITY_BAN_DEFAULT_DURATION = int(os.getenv('SECURITY_BAN_DEFAULT_DURATION', 24))  # Default ban duration in hours
    SECURITY_MAX_REQUESTS_PER_IP = int(os.getenv('SECURITY_MAX_REQUESTS_PER_IP', 200))  # Max requests per hour per IP
    SECURITY_BLACKLIST_THRESHOLD = int(os.getenv('SECURITY_BLACKLIST_THRESHOLD', 50))  # Requests that trigger alerts
    
    # Auto-ban Configuration
    SECURITY_AUTO_BAN_ENABLED = os.getenv('SECURITY_AUTO_BAN_ENABLED', 'true').lower() == 'true'
    SECURITY_AUTO_BAN_ATTACK_THRESHOLD = int(os.getenv('SECURITY_AUTO_BAN_ATTACK_THRESHOLD', 3))  # Auto-ban after 3 attack attempts
    SECURITY_AUTO_BAN_RATE_THRESHOLD = int(os.getenv('SECURITY_AUTO_BAN_RATE_THRESHOLD', 500))  # Auto-ban after 500 requests/hour
    SECURITY_AUTO_BAN_DURATION_HOURS = int(os.getenv('SECURITY_AUTO_BAN_DURATION_HOURS', 1))  # Initial auto-ban for 1 hour
    SECURITY_AUTO_BAN_ESCALATION_ENABLED = os.getenv('SECURITY_AUTO_BAN_ESCALATION_ENABLED', 'true').lower() == 'true'
    SECURITY_AUTO_BAN_MAX_DURATION_HOURS = int(os.getenv('SECURITY_AUTO_BAN_MAX_DURATION_HOURS', 168))  # Max 7 days
    
    # Smart cleanup configuration
    SECURITY_CLEANUP_ENABLED = os.getenv('SECURITY_CLEANUP_ENABLED', 'true').lower() == 'true'
    SECURITY_CLEANUP_UNBAN_GOOD_IPS = os.getenv('SECURITY_CLEANUP_UNBAN_GOOD_IPS', 'true').lower() == 'true'  # Unban IPs with no recent violations
    
    # Database Configuration
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_POOL_SIZE = int(os.getenv('SQLALCHEMY_POOL_SIZE', 5))
    SQLALCHEMY_MAX_OVERFLOW = int(os.getenv('SQLALCHEMY_MAX_OVERFLOW', 10))
    SQLALCHEMY_POOL_TIMEOUT = int(os.getenv('SQLALCHEMY_POOL_TIMEOUT', 20))
    SQLALCHEMY_POOL_RECYCLE = int(os.getenv('SQLALCHEMY_POOL_RECYCLE', 1800))
    
    # Database monitoring settings
    DB_CONNECTION_TIMEOUT = 30
    DB_MONITOR_ENABLED = True
    
    # SQLAlchemy Engine Options (with security enhancements)
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_use_lifo': True,
        'connect_args': {
            'connect_timeout': int(os.getenv('SQLALCHEMY_ENGINE_OPTIONS_CONNECT_TIMEOUT', 5)),
            'application_name': 'ecs_portal',  # More descriptive name
            'options': (
                f"-c statement_timeout={os.getenv('SQLALCHEMY_ENGINE_OPTIONS_STATEMENT_TIMEOUT', 30000)} "
                f"-c idle_in_transaction_session_timeout={os.getenv('SQLALCHEMY_ENGINE_OPTIONS_IDLE_IN_TRANSACTION_SESSION_TIMEOUT', 30000)} "
                f"-c log_statement=none "  # Disable query logging for security
                f"-c log_min_duration_statement=5000"  # Log only slow queries (5s+)
            )
        }
    }
    
    # Login configuration
    LOGIN_MESSAGE = 'Please log in to access this page.'
    LOGIN_MESSAGE_CATEGORY = 'info'
    
    # External Service Configuration
    WOO_CONSUMER_KEY = os.getenv('WC_KEY')
    WOO_CONSUMER_SECRET = os.getenv('WC_SECRET')
    SERVER_ID = os.getenv('SERVER_ID')
    WOO_API_URL = os.getenv('WOO_API_URL')
    DISCORD_CLIENT_ID = os.getenv('DISCORD_CLIENT_ID')
    DISCORD_CLIENT_SECRET = os.getenv('DISCORD_CLIENT_SECRET')
    TEAM_ID = os.getenv('TEAM_ID')
    BOT_API_URL = os.getenv('BOT_API_URL')
    
    # Timezone Settings
    timezone = 'America/Los_Angeles'
    TIMEZONE = pytz.timezone('America/Los_Angeles')
    
    # Redis and Session Configuration
    REDIS_URL = os.getenv('REDIS_URL', 'redis://redis:6379/0')
    SESSION_TYPE = 'redis'
    SESSION_PERMANENT = True
    PERMANENT_SESSION_LIFETIME = timedelta(days=30)  # Extended from 8 to 30 days
    SESSION_USE_SIGNER = True  # Enable session signing for security
    SESSION_KEY_PREFIX = 'flask_session:'
    # Additional session security and persistence settings
    # Use environment variable to determine if we're in production
    IS_PRODUCTION = os.getenv('FLASK_ENV', 'development').lower() == 'production'
    SESSION_COOKIE_SECURE = IS_PRODUCTION  # Secure cookies in production, HTTP in dev
    SESSION_COOKIE_SAMESITE = 'Lax'  # Less strict SameSite policy that works better with redirects
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_NAME = 'session'  # Use standard name for compatibility
    SESSION_REFRESH_EACH_REQUEST = True  # Update session expiry on each request
    
    # Configure Flask-WTF (CSRF Protection)
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600  # 1 hour (in seconds)
    WTF_CSRF_SSL_STRICT = False  # Allow CSRF over HTTP for local development
    WTF_CSRF_CHECK_DEFAULT = True  # Enable CSRF checking by default
    
    # Celery Configuration
    CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', 'redis://redis:6379/0')
    CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', 'redis://redis:6379/0')
    
    # JWT Configuration
    JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY')
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(days=1)
    
    # External Service Keys
    TWILIO_SID = os.getenv('TWILIO_SID')
    TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
    TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER')
    GOOGLE_APPLICATION_CREDENTIALS = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
    TEXTMAGIC_USERNAME = os.getenv('TEXTMAGIC_USERNAME')
    TEXTMAGIC_API_KEY = os.getenv('TEXTMAGIC_API_KEY')
    
    # External API Configuration for third-party integrations (ChatGPT, etc.)
    EXTERNAL_API_KEYS = os.getenv('EXTERNAL_API_KEYS', '').split(',') if os.getenv('EXTERNAL_API_KEYS') else []
    
    # Security Configuration
    SECURITY_PASSWORD_SALT = os.getenv('SECURITY_PASSWORD_SALT', SECRET_KEY)
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max upload
    
    # Rate limiting configuration
    RATELIMIT_STORAGE_URL = REDIS_URL
    RATELIMIT_HEADERS_ENABLED = True
    
    # Content Security Policy (secure)
    CSP = {
        'default-src': "'self'",
        # Remove unsafe-eval, keep unsafe-inline for now but add nonce support in future
        'script-src': "'self' 'unsafe-inline' https://cdn.jsdelivr.net https://unpkg.com https://cdnjs.cloudflare.com",
        'style-src': "'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com",
        'img-src': "'self' data: https: blob:",
        'font-src': "'self' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com",
        'connect-src': "'self' wss: https:",
        'frame-ancestors': "'none'",  # Prevent clickjacking
        'base-uri': "'self'",  # Restrict base tag URLs
        'form-action': "'self'",  # Restrict form submissions
        'object-src': "'none'",  # Block plugins like Flash
        'upgrade-insecure-requests': True  # Upgrade HTTP to HTTPS
    }
    
    # Trusted proxy configuration for DigitalOcean/Traefik
    TRUSTED_PROXIES = [
        '172.16.0.0/12',    # Docker internal networks
        '192.168.0.0/16',   # Private networks
        '10.0.0.0/8',       # Private networks
    ]

    @staticmethod
    def get_current_time():
        """Return the current time in the configured timezone (PST)."""
        return datetime.now(pytz.timezone('America/Los_Angeles'))


class TestingConfig(Config):
    """Testing configuration settings."""
    TESTING = True
    
    # Use in-memory SQLite for testing
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    
    # Remove PostgreSQL-specific pool settings for SQLite
    SQLALCHEMY_POOL_SIZE = None
    SQLALCHEMY_MAX_OVERFLOW = None
    SQLALCHEMY_POOL_TIMEOUT = None
    SQLALCHEMY_POOL_RECYCLE = None
    
    # SQLite engine options
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': False,  # Not needed for SQLite
        'echo': False
    }
    
    # Disable CSRF for testing
    WTF_CSRF_ENABLED = False
    
    # Disable Redis session storage for tests - use Flask's default
    SESSION_TYPE = None  # Use Flask's default session implementation  
    SESSION_REDIS = None
    REDIS_URL = 'redis://localhost:6379/15'  # Will be mocked anyway
    
    # Test secrets
    SECRET_KEY = 'test-secret-key-for-testing'
    JWT_SECRET_KEY = 'test-jwt-secret-for-testing'
    
    # Disable security features for testing
    SESSION_COOKIE_SECURE = False
    PREFERRED_URL_SCHEME = 'http'
    
    # Mock external services
    CELERY_TASK_ALWAYS_EAGER = True
    CELERY_TASK_EAGER_PROPAGATES = True
    
    # Server name for URL generation in tests
    SERVER_NAME = 'localhost:5000'
    
    # Disable file logging for tests to avoid permission issues
    LOG_TO_FILE = False