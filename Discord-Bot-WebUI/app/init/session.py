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
        from redis.retry import Retry
        from redis.backoff import ExponentialBackoff
        from redis.exceptions import BusyLoadingError, ConnectionError as RedisConnectionError, TimeoutError as RedisTimeoutError
        redis_url = app.config.get('REDIS_URL', 'redis://redis:6379/0')
        session_pool = ConnectionPool.from_url(
            redis_url,
            max_connections=50,
            socket_timeout=5.0,
            socket_connect_timeout=3.0,
            retry_on_timeout=True,
        )
        # Retry transient errors so a Redis restart doesn't 500 every request.
        # BusyLoadingError fires while Redis reloads its RDB (~1-3s); ConnectionError
        # covers the brief window the socket is refused during container restart.
        session_redis_client = Redis(
            connection_pool=session_pool,
            decode_responses=False,
            retry=Retry(ExponentialBackoff(cap=2.0, base=0.1), retries=3),
            retry_on_error=[BusyLoadingError, RedisConnectionError, RedisTimeoutError],
        )

        app.config.update({
            'SESSION_TYPE': 'redis',
            'SESSION_REDIS': session_redis_client,
            'PERMANENT_SESSION_LIFETIME': timedelta(days=7),
            'SESSION_KEY_PREFIX': 'session:',
            'SESSION_USE_SIGNER': True
        })
        Session(app)

        # Backstop for a Redis outage. The client above RETRIES transient errors,
        # which absorbs the common ~1-3s reload blip. But when Redis is down or
        # reloading LONGER than the retry budget, the exception still escapes
        # Flask-Session's open_session/save_session and Flask turns it into a 500
        # (plus a secondary "session has not yet been opened" crash in the error
        # handler). Wrap the low-level store helpers so a prolonged outage
        # degrades to a transient, non-persisted session instead of a hard error.
        _make_session_resilient(app)
    else:
        # Use Flask's default session implementation for testing
        app.logger.info("Testing mode: Using Flask default sessions instead of Redis")

    # Configure CORS — restrict to known origins (configurable via CORS_ALLOWED_ORIGINS env var)
    allowed_origins = app.config.get('CORS_ALLOWED_ORIGINS', ['*'])
    CORS(app, resources={r"/api/*": {"origins": allowed_origins}}, supports_credentials=True)


def _make_session_resilient(app):
    """Make the Redis session interface fail soft during a Redis outage.

    When Redis is unreachable/reloading past the client's retry budget:
      * reads behave as "no saved session" -> Flask-Session issues a fresh
        session, so the request proceeds (unauthenticated for that request), and
      * writes/deletes are skipped for that one request.

    The user keeps browsing instead of hitting a 500; normal persistence resumes
    the instant Redis is back. We wrap the low-level store helpers (rather than
    open_session/save_session) so Flask-Session's own logic still builds the
    session objects — keeping this independent of the library version.
    """
    from redis.exceptions import (
        BusyLoadingError,
        ConnectionError as RedisConnectionError,
        TimeoutError as RedisTimeoutError,
    )

    redis_errors = (BusyLoadingError, RedisConnectionError, RedisTimeoutError)
    interface = getattr(app, 'session_interface', None)
    if interface is None:
        return

    def guard(method_name, fallback):
        original = getattr(interface, method_name, None)
        if not callable(original):
            return

        def wrapper(*args, **kwargs):
            try:
                return original(*args, **kwargs)
            except redis_errors as e:
                logger.warning(
                    "Session store unavailable in %s; degrading gracefully (%s)",
                    method_name, e,
                )
                return fallback

        setattr(interface, method_name, wrapper)

    # None from _retrieve_session_data reads as "no session" -> fresh session.
    guard('_retrieve_session_data', fallback=None)
    # Persistence helpers become no-ops during the outage; the response still returns.
    guard('_upsert_session', fallback=None)
    guard('_delete_session', fallback=None)
