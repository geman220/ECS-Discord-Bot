# app/init/session.py

"""
Session Configuration

Configure Flask session to use Redis backend.
"""

import logging
from datetime import timedelta

from flask_session import Session
from flask_cors import CORS

logger = logging.getLogger(__name__)


def init_session(app, redis_manager):
    """
    Configure session management to use Redis.

    Args:
        app: The Flask application instance.
        redis_manager: The Redis manager instance.
    """
    if not app.config.get('TESTING'):
        # Create a DEDICATED Redis connection pool for Flask-Session.
        # This MUST NOT share the pool with SocketIO or other components
        # that run in background native threads, because gevent's
        # monkey-patched sockets don't support cross-thread usage.
        # Sharing the pool causes "Cannot switch to a different thread" crashes.
        from redis import Redis, ConnectionPool
        redis_url = app.config.get('REDIS_URL', 'redis://redis:6379/0')
        session_pool = ConnectionPool.from_url(
            redis_url,
            max_connections=50,
            socket_timeout=5.0,
            socket_connect_timeout=3.0,
            retry_on_timeout=True,
        )
        session_redis_client = Redis(
            connection_pool=session_pool,
            decode_responses=False
        )

        app.config.update({
            'SESSION_TYPE': 'redis',
            'SESSION_REDIS': session_redis_client,
            'PERMANENT_SESSION_LIFETIME': timedelta(days=7),
            'SESSION_KEY_PREFIX': 'session:',
            'SESSION_USE_SIGNER': True
        })
        Session(app)
    else:
        # Use Flask's default session implementation for testing
        app.logger.info("Testing mode: Using Flask default sessions instead of Redis")

    # Configure CORS — restrict to known origins (configurable via CORS_ALLOWED_ORIGINS env var)
    allowed_origins = app.config.get('CORS_ALLOWED_ORIGINS', ['*'])
    CORS(app, resources={r"/api/*": {"origins": allowed_origins}}, supports_credentials=True)
