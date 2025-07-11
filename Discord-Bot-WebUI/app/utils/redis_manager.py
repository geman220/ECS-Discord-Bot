# app/utils/redis_manager.py

"""
Redis Manager Module

This module defines the RedisManager class, a singleton that manages the Redis client
connection. It initializes the client using configuration from environment variables,
with a retry mechanism for establishing the connection, and provides a property to
access the client, reinitializing it if needed.
"""

import logging
from redis import Redis
from typing import Optional
import os

logger = logging.getLogger(__name__)


class RedisManager:
    _instance: Optional['RedisManager'] = None
    _client: Optional[Redis] = None

    def __new__(cls) -> 'RedisManager':
        """
        Create a singleton instance of RedisManager.
        
        Returns:
            A RedisManager instance.
        """
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """
        Initialize the RedisManager.
        
        If the Redis client is not already initialized, initialize it.
        """
        if self._client is None:
            self._initialize_client()
            
    def shutdown(self):
        """
        Close the Redis client connection pool and release resources.
        
        This should be called during application shutdown, not during regular requests.
        """
        # Only actually close the connection pool during application shutdown
        import os
        
        try:
            if self._client and hasattr(self._client, 'connection_pool'):
                # Check if this is actual application shutdown or just a request ending
                is_app_shutdown = os.environ.get('FLASK_APP_SHUTTING_DOWN') == 'true'
                
                if is_app_shutdown:
                    logger.info("Application shutdown: Closing Redis connection pool")
                    self._client.connection_pool.disconnect()
                    self._client = None
                else:
                    # For normal requests, don't close the connection pool
                    logger.debug("Maintaining persistent Redis connection pool")
                    return
        except Exception as e:
            logger.error(f"Error in Redis connection pool management: {e}")
            # Don't set client to None during normal operation

    def _initialize_client(self):
        """
        Initialize the Redis client with retries.

        Attempts to create a Redis client using environment variables (or default values)
        and pings the server to verify connectivity. Retries up to 3 times on failure.
        Uses a connection pool with proper configuration to manage connections efficiently.
        """
        max_retries = 3
        retry_count = 0
        import time

        while retry_count < max_retries:
            try:
                # Retrieve Redis connection parameters from environment variables.
                redis_host = os.getenv('REDIS_HOST', 'redis')
                redis_port = int(os.getenv('REDIS_PORT', '6379'))
                redis_db = int(os.getenv('REDIS_DB', '0'))
                
                logger.debug(f"Attempting Redis connection to {redis_host}:{redis_port}/{redis_db}")

                # Create a Redis connection pool with optimized settings compatible with installed version
                from redis import ConnectionPool
                pool = ConnectionPool(
                    host=redis_host,
                    port=redis_port,
                    db=redis_db,
                    socket_timeout=10.0,  # Increased to match session pool
                    socket_connect_timeout=10.0,  # Increased to match session pool
                    decode_responses=True,
                    socket_keepalive=True,
                    socket_keepalive_options={},
                    health_check_interval=30,  # Match session pool settings
                    max_connections=50,  # Match session pool size
                    retry_on_timeout=True  # Auto-retry on socket timeouts
                )

                # Create the Redis client using the connection pool
                self._client = Redis(connection_pool=pool)
                
                # Test the connection by pinging the server.
                self._client.ping()
                logger.debug(f"Redis connection established to {redis_host}:{redis_port}")
                break
            except Exception as e:
                retry_count += 1
                logger.error(f"Redis connection attempt {retry_count} failed: {e}")
                # Add a small delay between retries to prevent hammering the Redis server
                if retry_count < max_retries:
                    time.sleep(0.5)
                if retry_count == max_retries:
                    # Instead of raising, just log and set client to None
                    logger.error(f"Failed to connect to Redis after {max_retries} attempts")
                    self._client = None
                    break

    @property
    def client(self) -> Redis:
        """
        Get the Redis client.

        If the client is uninitialized or the connection is not healthy, reinitialize it.
        Periodically checks and closes idle connections to reduce memory usage.

        Returns:
            A Redis client instance.
        """
        import time
        current_time = time.time()
        
        # Periodically check and close idle connections (every 10 minutes)
        if hasattr(self, '_last_connection_cleanup'):
            if current_time - self._last_connection_cleanup > 600:  # 10 minutes (increased from 5)
                self._cleanup_idle_connections()
                self._last_connection_cleanup = current_time
        else:
            self._last_connection_cleanup = current_time
            
        try:
            if self._client is None:
                self._initialize_client()
            elif not hasattr(self._client, 'ping'):
                logger.warning("Redis client has no ping method, reinitializing")
                self._initialize_client()
            else:
                try:
                    # Try ping but catch failures to prevent cascading errors
                    self._client.ping()
                except Exception as e:
                    logger.warning(f"Redis ping failed, reinitializing connection: {e}")
                    # Explicitly clean up old client if it exists
                    if hasattr(self._client, 'connection_pool') and hasattr(self._client.connection_pool, 'disconnect'):
                        try:
                            self._client.connection_pool.disconnect()
                        except:
                            pass
                    self._initialize_client()
        except Exception as e:
            logger.error(f"Error getting Redis client: {e}")
            # Create an emergency fallback - a dummy Redis client that does nothing
            from types import SimpleNamespace
            if self._client is None:
                self._client = SimpleNamespace()
                # Add dummy methods that won't crash the application
                self._client.ping = lambda: False
                self._client.get = lambda key: None
                self._client.set = lambda key, value, **kwargs: False
                self._client.delete = lambda key: 0
                self._client.keys = lambda pattern: []
                logger.error("Created dummy Redis client that will silently fail")
        
        return self._client
        
    def _cleanup_idle_connections(self):
        """
        Clean up idle Redis connections to prevent memory leaks.
        This helps reduce overall memory usage by the Redis connection pool.
        Uses only compatible methods with the current Redis version.
        """
        if not self._client or not hasattr(self._client, 'connection_pool'):
            return
            
        try:
            # Force connection pool to release connections
            pool = self._client.connection_pool
            if hasattr(pool, 'disconnect'):
                # Simple disconnect call that's available in most Redis versions
                logger.debug("Running Redis connection pool cleanup")
                pool.disconnect()
                
                # Reinitialize the client to ensure a clean state
                self._initialize_client()
                logger.debug("Redis connection pool cleaned and reinitialized")
        except Exception as e:
            logger.warning(f"Error during Redis connection cleanup: {e}")
        
    def get_connection_stats(self):
        """
        Get statistics about the Redis connection pool.
        
        Returns:
            dict: A dictionary containing connection pool statistics
        """
        stats = {
            'connection_pool': False,
            'in_use': 0,
            'created': 0,
            'max': 0,
            'utilization_percent': 0
        }
        
        if self._client and hasattr(self._client, 'connection_pool'):
            pool = self._client.connection_pool
            stats['connection_pool'] = True
            
            # Check current connections vs max connections
            if hasattr(pool, '_in_use_connections') and hasattr(pool, '_available_connections'):
                in_use = len(pool._in_use_connections)
                created = len(pool._available_connections) + in_use
                max_conn = pool.max_connections if hasattr(pool, 'max_connections') else 0
                
                stats.update({
                    'in_use': in_use,
                    'created': created,
                    'max': max_conn,
                    'utilization_percent': (in_use / max_conn * 100) if max_conn else 0
                })
                
                # Log warning if too many connections are in use
                if max_conn and in_use > max_conn * 0.8:  # 80% of max connections
                    logger.warning(f"Redis connection pool nearing capacity: {in_use}/{max_conn} connections in use")
            elif hasattr(pool, 'max_connections'):
                # Fallback for different Redis versions
                max_conn = pool.max_connections
                stats.update({
                    'max': max_conn,
                    'created': getattr(pool, '_created_connections', 0),
                    'in_use': 'unknown'
                })
        
        return stats


# Global function to get Redis connection
def get_redis_connection():
    """
    Get a Redis connection using the singleton RedisManager.
    
    Returns:
        Redis: A Redis client instance
    """
    manager = RedisManager()
    return manager.client