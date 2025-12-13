# app/init/redis.py

"""
Redis Initialization

Initialize unified Redis connection manager and register shutdown handlers.
"""

import logging
import atexit

logger = logging.getLogger(__name__)


def init_redis(app):
    """
    Initialize Redis connection manager for the Flask application.

    Args:
        app: The Flask application instance.

    Returns:
        The Redis manager instance.
    """
    from app.utils.redis_manager import get_redis_manager

    # Get the unified Redis manager instance
    redis_manager = get_redis_manager()

    # Use the unified manager for all Redis operations
    app.redis = redis_manager.client  # Decoded client for general use
    app.session_redis = redis_manager.raw_client  # Raw client for sessions
    app.redis_manager = redis_manager

    # Test unified Redis connections
    try:
        app.redis.ping()
        app.session_redis.ping()
        logger.info("Unified Redis connections established successfully")

        # Log connection pool statistics
        stats = redis_manager.get_connection_stats()
        logger.info(f"Unified Redis connection pool: {stats}")

    except Exception as e:
        logger.error(f"Redis connection failed: {e}")
        # Continue anyway - the unified manager will handle reconnection attempts

    # Register shutdown handler only for application shutdown (not request teardown)
    def cleanup_redis_on_shutdown():
        try:
            # Signal event consumers to shutdown gracefully
            if hasattr(app, '_consumer_shutdown'):
                logger.info("Signaling event consumers to shutdown...")
                app._consumer_shutdown.set()

            redis_manager.cleanup()
            logger.info("Unified Redis connections cleaned up on application shutdown")
        except Exception as e:
            logger.error(f"Error during Redis shutdown: {e}")

    atexit.register(cleanup_redis_on_shutdown)

    return redis_manager
