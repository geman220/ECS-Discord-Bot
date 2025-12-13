# app/sockets/utils.py

"""
Socket.IO Utility Functions

Redis distributed locks and shared utilities for socket handlers.
"""

import logging

logger = logging.getLogger(__name__)


def get_draft_lock(player_id: int):
    """
    Get a Redis distributed lock for a specific player draft operation.

    Returns a Redis lock object that can be used as a context manager or
    with acquire()/release() methods.

    The lock auto-expires after 30 seconds to prevent deadlocks if a worker crashes.
    """
    from app.utils.redis_manager import get_redis_connection
    redis_client = get_redis_connection()

    # Create a Redis lock with:
    # - timeout=30: Lock auto-expires after 30 seconds (prevents deadlock on crash)
    # - blocking_timeout=5: Wait up to 5 seconds to acquire (matches old behavior)
    # - thread_local=False: Required for eventlet compatibility
    return redis_client.lock(
        name=f"draft:player:{player_id}",
        timeout=30,
        blocking_timeout=5,
        thread_local=False
    )


def cleanup_draft_lock(player_id: int):
    """
    Clean up the lock for a player after operation completes.

    Note: With Redis locks, cleanup happens automatically via the lock's release()
    method or timeout expiration. This function is kept for API compatibility
    but is now a no-op since Redis handles cleanup automatically.
    """
    # Redis locks are cleaned up automatically when released or when they expire.
    # No manual cleanup needed - this is kept for backward compatibility.
    pass
