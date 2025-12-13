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
        # Create a Redis client specifically for sessions that shares the connection pool
        from redis import Redis
        session_redis_client = Redis(connection_pool=redis_manager._pool, decode_responses=False)

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

    # Configure CORS
    CORS(app, resources={r"/api/*": {"origins": "*"}})
