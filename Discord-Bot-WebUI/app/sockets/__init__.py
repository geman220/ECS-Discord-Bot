# app/sockets/__init__.py

"""
Socket Modules Package

This package contains modules related to WebSocket functionality,
particularly for real-time communication features like live match
reporting and Discord role updates.
"""

import json
import logging

logger = logging.getLogger(__name__)


# Utility for Socket.IO session data management using Redis
class SocketSessionManager:
    """
    Manages Socket.IO session data across events using Redis.

    Benefits over in-memory storage:
    - No memory leaks (Redis handles TTL expiration automatically)
    - Works across multiple workers/processes
    - Survives worker restarts
    - No manual cleanup needed
    """

    # Session TTL in seconds (2 hours)
    SESSION_TTL = 7200

    # Redis key prefix for socket sessions
    KEY_PREFIX = "socketio:session:"

    @classmethod
    def _get_redis(cls):
        """Get Redis connection lazily to avoid import cycles."""
        from app.utils.redis_manager import get_redis_connection
        return get_redis_connection()

    @classmethod
    def _make_key(cls, sid):
        """Create Redis key for a session ID."""
        return f"{cls.KEY_PREFIX}{sid}"

    @staticmethod
    def get_session_data(sid):
        """Get session data for a given Socket.IO session ID."""
        try:
            redis = SocketSessionManager._get_redis()
            key = SocketSessionManager._make_key(sid)
            data = redis.get(key)
            if data:
                # Refresh TTL on access (keep session alive while active)
                redis.expire(key, SocketSessionManager.SESSION_TTL)
                return json.loads(data)
            return {}
        except Exception as e:
            logger.error(f"Error getting Socket.IO session data from Redis: {e}")
            return {}

    @staticmethod
    def save_session_data(sid, data):
        """Save session data for a given Socket.IO session ID."""
        try:
            redis = SocketSessionManager._get_redis()
            key = SocketSessionManager._make_key(sid)
            # Set with TTL - Redis automatically expires the key
            redis.setex(key, SocketSessionManager.SESSION_TTL, json.dumps(data))
            return True
        except Exception as e:
            logger.error(f"Error saving Socket.IO session data to Redis: {e}")
            return False

    @staticmethod
    def clear_session_data(sid):
        """Clear session data for a given Socket.IO session ID."""
        try:
            redis = SocketSessionManager._get_redis()
            key = SocketSessionManager._make_key(sid)
            redis.delete(key)
            return True
        except Exception as e:
            logger.error(f"Error clearing Socket.IO session data from Redis: {e}")
            return False

    @classmethod
    def get_session_count(cls):
        """Get current number of stored sessions (useful for monitoring)."""
        try:
            redis = cls._get_redis()
            # Count keys matching our prefix
            keys = redis.keys(f"{cls.KEY_PREFIX}*")
            return len(keys) if keys else 0
        except Exception as e:
            logger.error(f"Error counting Socket.IO sessions in Redis: {e}")
            return 0

    @classmethod
    def force_cleanup(cls):
        """
        Force cleanup is no longer needed - Redis handles TTL expiration automatically.
        This method is kept for API compatibility but is now a no-op.
        """
        pass

# Import socket handler modules to register their events after class definition
# The import order matters - base functionality first
from . import session  # Session management
from . import rsvp  # RSVP handlers
from . import live_reporting  # Live match reporting


def register_socket_handlers():
    """
    Register all Socket.IO event handlers.

    This function imports all handler modules which causes the @socketio.on
    decorators to register the handlers. Must be called after socketio.init_app().
    """
    # Import handler modules to register their events
    # The decorators in these modules register the handlers when imported
    from . import auth  # JWT auth and connect/disconnect handlers
    from . import draft  # Draft room and player drafting handlers
    from . import discord_roles  # Discord role management handlers
    from . import match_events  # Match room and event reporting handlers
    from . import test_handlers  # Test/debug handlers


__all__ = ['SocketSessionManager', 'register_socket_handlers']