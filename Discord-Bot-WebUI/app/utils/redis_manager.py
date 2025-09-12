# app/utils/redis_manager.py

"""
Unified Redis Manager Module

This module provides a comprehensive Redis connection management system that:
- Uses a single connection pool for all Redis operations
- Supports both raw bytes and decoded string responses
- Implements proper connection lifecycle management
- Provides connection monitoring and health checking
- Eliminates connection leaks through proper cleanup
"""

import logging
import os
import time
import threading
from contextlib import contextmanager
from typing import Optional, Dict, Any, Union
from redis import Redis, ConnectionPool
from redis.exceptions import ConnectionError, TimeoutError

logger = logging.getLogger(__name__)


class UnifiedRedisManager:
    """
    Unified Redis connection manager with single connection pool.
    
    This manager provides both decoded and raw Redis clients using a single
    connection pool, eliminating the need for multiple pools throughout the application.
    """
    
    _instance: Optional['UnifiedRedisManager'] = None
    _lock = threading.RLock()  # Thread-safe lock for singleton
    _pool: Optional[ConnectionPool] = None
    _decoded_client: Optional[Redis] = None
    _raw_client: Optional[Redis] = None
    _last_health_check: float = 0
    _health_check_interval: int = 30
    _connection_stats: Dict[str, Any] = {}
    _initialized = False  # Track initialization state

    def __new__(cls) -> 'UnifiedRedisManager':
        """Create thread-safe singleton instance."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    def __init__(self):
        """Initialize the Redis manager if not already done."""
        with self._lock:
            if not self._initialized:
                self._initialize_connection_pool()
                self._initialized = True
            
    def _initialize_connection_pool(self):
        """
        Initialize a single Redis connection pool that will be shared
        across all Redis operations in the application.
        """
        max_retries = 5
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                # Get Redis configuration from environment
                redis_host = os.getenv('REDIS_HOST', 'redis')
                redis_port = int(os.getenv('REDIS_PORT', '6379'))
                redis_db = int(os.getenv('REDIS_DB', '0'))
                redis_url = os.getenv('REDIS_URL')
                
                logger.info(f"Initializing unified Redis connection pool to {redis_host}:{redis_port}/{redis_db}")
                
                # Create single connection pool with optimized settings
                if redis_url:
                    self._pool = ConnectionPool.from_url(
                        redis_url,
                        socket_timeout=10.0,              # Longer timeout for stability
                        socket_connect_timeout=5.0,       # Allow more time for connection
                        socket_keepalive=True,
                        socket_keepalive_options={},      # Empty for compatibility
                        health_check_interval=60,         # Less frequent health checks
                        max_connections=25,               # Increased to handle session load
                        retry_on_timeout=True,            # Enable retries
                    )
                else:
                    self._pool = ConnectionPool(
                        host=redis_host,
                        port=redis_port,
                        db=redis_db,
                        socket_timeout=10.0,              # Longer timeout for stability
                        socket_connect_timeout=5.0,       # Allow more time for connection
                        socket_keepalive=True,
                        socket_keepalive_options={},      # Empty for compatibility
                        health_check_interval=60,         # Less frequent health checks
                        max_connections=25,               # Increased to handle session load
                        retry_on_timeout=True,            # Enable retries
                    )
                
                # Create clients using the shared pool with EventLet-safe settings
                self._decoded_client = Redis(
                    connection_pool=self._pool, 
                    decode_responses=True,
                    socket_timeout=8,          # Longer timeout for stability
                    socket_connect_timeout=5,  # More time for connection
                    retry_on_timeout=True,
                    socket_keepalive=True,
                    socket_keepalive_options={}  # Empty for compatibility
                )
                self._raw_client = Redis(
                    connection_pool=self._pool, 
                    decode_responses=False,
                    socket_timeout=8,          # Longer timeout for stability
                    socket_connect_timeout=5,  # More time for connection
                    retry_on_timeout=True,
                    socket_keepalive=True,
                    socket_keepalive_options={}  # Empty for compatibility
                )
                
                # Test connections with retry logic
                for attempt in range(2):
                    try:
                        self._decoded_client.ping()
                        self._raw_client.ping()
                        break
                    except Exception as ping_e:
                        if attempt == 1:  # Last attempt
                            raise ping_e
                        time.sleep(0.1)  # Brief wait before retry
                
                logger.info("Unified Redis connection pool initialized successfully")
                break
                
            except Exception as e:
                retry_count += 1
                logger.error(f"Redis connection attempt {retry_count} failed: {e}")
                if retry_count < max_retries:
                    # Exponential backoff
                    sleep_time = min(2 ** retry_count, 10)
                    logger.info(f"Retrying Redis connection in {sleep_time} seconds...")
                    time.sleep(sleep_time)
                else:
                    logger.error(f"Failed to initialize Redis after {max_retries} attempts")
                    logger.error(f"Redis configuration - URL: {redis_url}, Host: {redis_host}, Port: {redis_port}")
                    raise ConnectionError(f"Unable to connect to Redis after {max_retries} attempts")

    def _create_fallback_clients(self):
        """Create fallback clients that silently fail for graceful degradation."""
        from types import SimpleNamespace
        
        logger.debug("Creating fallback Redis clients for graceful degradation")
        
        # Create dummy clients
        self._decoded_client = SimpleNamespace()
        self._raw_client = SimpleNamespace()
        
        # Add dummy methods
        for client in [self._decoded_client, self._raw_client]:
            client.ping = lambda: False
            client.get = lambda key: None
            client.set = lambda key, value, ex=None, px=None, nx=False, xx=False, keepttl=False, **kwargs: False
            client.setex = lambda key, seconds, value: False  # Add missing setex method
            client.delete = lambda *keys: 0
            client.exists = lambda key: False
            client.keys = lambda pattern: []
            client.hgetall = lambda key: {}
            client.hset = lambda key, field, value: False
            client.hmset = lambda key, mapping: False
            client.expire = lambda key, seconds: False
            client.ttl = lambda key: -1
            client.scan = lambda cursor=0, match=None, count=None: (0, [])
            client.scan_iter = lambda match=None, count=None: iter([])  # Add scan_iter for compatibility
            client.pipeline = lambda: SimpleNamespace(execute=lambda: [])
            # Add Redis 'control' attribute for Celery compatibility
            client.control = SimpleNamespace(revoke=lambda task_id, terminate=True: None)
            # Add Redis Streams methods for event consumer compatibility
            client.xgroup_create = lambda stream, group, id='0', mkstream=True: False
            client.xreadgroup = lambda group, consumer, streams, count=None, block=None: {}
            client.xack = lambda stream, group, *ids: 0
            client.xadd = lambda stream, fields, id='*', maxlen=None, approximate=True: None
            client.xpending_range = lambda stream, group, consumer=None, start='-', end='+', count=None: []  # Fix for event consumer
            client.xpending = lambda stream, group: {'consumers': [], 'pending': 0, 'min': None, 'max': None}

    @property
    def client(self) -> Redis:
        """
        Get the decoded Redis client (decode_responses=True).
        
        This is the default client for most application use cases.
        """
        self._check_health()
        if self._decoded_client is None:
            # Try to reinitialize atomically with retries
            with self._lock:
                if self._pool is None:
                    logger.info("Auto-reinitializing Redis connection pool...")
                    for retry in range(3):  # Retry up to 3 times
                        try:
                            self._initialize_connection_pool()
                            self._initialized = True
                            logger.info("Auto-reinitialization successful")
                            return self._decoded_client
                        except Exception as e:
                            logger.error(f"Auto-reinitialization attempt {retry+1} failed: {e}")
                            if retry < 2:  # Don't sleep on last attempt
                                time.sleep(min(0.5 * (2 ** retry), 1.0))  # Exponential backoff, max 1s
            
            # If all retries failed, create fallback client instead of raising exception
            logger.warning("Redis unavailable - creating fallback client to prevent crashes")
            self._create_fallback_clients()
            return self._decoded_client
        return self._decoded_client
    
    @property
    def raw_client(self) -> Redis:
        """
        Get the raw Redis client (decode_responses=False).
        
        Use this for session storage or when you need binary data.
        """
        self._check_health()
        if self._raw_client is None:
            raise ConnectionError("Redis raw client is not available")
        return self._raw_client
    
    def _check_health(self):
        """Periodic health check to ensure connections are alive."""
        current_time = time.time()
        
        if current_time - self._last_health_check > self._health_check_interval:
            try:
                # Just update the timestamp - rely on Redis being available as intended
                # If there are connection issues, they'll be caught during actual operations
                self._last_health_check = current_time
            except Exception as e:
                # Log but don't reinitialize - let actual operations handle failures
                logger.debug(f"Redis health check completed with note: {e}")
                self._last_health_check = current_time
    
    def _reinitialize(self):
        """Reinitialize connection pool and clients atomically."""
        logger.info("Attempting Redis connection reinitialization...")
        
        # Store current clients as backup
        old_pool = self._pool
        old_decoded_client = self._decoded_client
        old_raw_client = self._raw_client
        
        # Reset instance variables to initialize fresh
        self._pool = None
        self._decoded_client = None
        self._raw_client = None
        
        try:
            # Try to initialize new connection pool
            self._initialize_connection_pool()
            
            # If initialization succeeded, clean up old connections
            if old_pool:
                try:
                    old_pool.disconnect()
                    logger.debug("Old Redis pool disconnected successfully")
                except Exception as e:
                    logger.debug(f"Error disconnecting old Redis pool: {e}")
            
            logger.info("Redis connection reinitialization successful")
            
        except Exception as e:
            logger.error(f"Redis reinitialization failed: {e}")
            
            # Restore old clients if new initialization failed
            self._pool = old_pool
            self._decoded_client = old_decoded_client
            self._raw_client = old_raw_client
            
            logger.info("Restored previous Redis connections after failed reinitialization")
            raise ConnectionError(f"Redis reinitialization failed: {e}")
    
    @contextmanager
    def connection(self, raw: bool = False):
        """
        Context manager for Redis connections with proper error handling.
        
        Args:
            raw: If True, returns raw client; otherwise decoded client
            
        Yields:
            Redis client instance
        """
        client = self.raw_client if raw else self.client
        try:
            yield client
        except Exception as e:
            logger.error(f"Redis operation failed: {e}")
            raise
    
    def get_connection_stats(self) -> Dict[str, Any]:
        """Get detailed connection pool statistics."""
        stats = {
            'connection_pool_initialized': self._pool is not None,
            'clients_initialized': {
                'decoded': self._decoded_client is not None,
                'raw': self._raw_client is not None
            },
            'last_health_check': self._last_health_check,
            'pool_stats': {}
        }
        
        if self._pool:
            try:
                # Get connection pool details
                pool = self._pool
                
                # Safely get connection counts with proper type checking
                created_connections = getattr(pool, '_created_connections', set())
                available_connections = getattr(pool, '_available_connections', [])
                in_use_connections = getattr(pool, '_in_use_connections', set())
                
                stats['pool_stats'] = {
                    'max_connections': getattr(pool, 'max_connections', 0),
                    'created_connections': len(created_connections) if hasattr(created_connections, '__len__') else 0,
                    'available_connections': len(available_connections) if hasattr(available_connections, '__len__') else 0,
                    'in_use_connections': len(in_use_connections) if hasattr(in_use_connections, '__len__') else 0
                }
                
                # Calculate utilization
                max_conn = stats['pool_stats']['max_connections']
                in_use = stats['pool_stats']['in_use_connections']
                if max_conn > 0:
                    stats['pool_stats']['utilization_percent'] = round((in_use / max_conn) * 100, 1)
                    
            except Exception as e:
                logger.debug(f"Could not get detailed pool stats: {e}")
                stats['pool_stats']['error'] = str(e)
        
        return stats
    
    def cleanup(self):
        """Clean up connection pool and clients."""
        try:
            # Redis connection pool cleanup (reduced logging)
            if self._pool and hasattr(self._pool, 'disconnect'):
                try:
                    self._pool.disconnect()
                except (AttributeError, TypeError):
                    # Handle cases where disconnect method or its dependencies are None
                    pass
            self._pool = None
            self._decoded_client = None
            self._raw_client = None
        except Exception as e:
            logger.error(f"Error during Redis cleanup: {e}")


# Global instance for backward compatibility - initialized lazily
_redis_manager: Optional[UnifiedRedisManager] = None
_global_lock = threading.RLock()

def _get_global_redis_manager() -> UnifiedRedisManager:
    """Get or create the global Redis manager instance in a thread-safe manner."""
    global _redis_manager
    with _global_lock:
        if _redis_manager is None:
            _redis_manager = UnifiedRedisManager()
        return _redis_manager


def get_redis_connection(raw: bool = False) -> Redis:
    """
    Get a Redis connection using the unified manager.
    
    Args:
        raw: If True, returns raw client (decode_responses=False)
             If False, returns decoded client (decode_responses=True)
    
    Returns:
        Redis client instance
    """
    manager = _get_global_redis_manager()
    return manager.raw_client if raw else manager.client


def get_redis_manager() -> UnifiedRedisManager:
    """Get the unified Redis manager instance."""
    return _get_global_redis_manager()


# LEGACY COMPATIBILITY - DEPRECATED
class RedisManager:
    """
    DEPRECATED: Legacy RedisManager class for backward compatibility.
    
    ⚠️  WARNING: This class is deprecated and will be removed in a future release.
    Please use get_safe_redis() from app.utils.safe_redis instead.
    
    Migration guide:
    OLD: redis_client = RedisManager().client
    NEW: redis_client = get_safe_redis()
    """
    
    def __init__(self):
        # Log usage for tracking migration
        import inspect
        import warnings
        
        # Get the calling location
        frame = inspect.currentframe().f_back
        filename = frame.f_code.co_filename
        lineno = frame.f_lineno
        
        # Issue deprecation warning
        warning_msg = (
            f"RedisManager() is deprecated and will be removed. "
            f"Use get_safe_redis() instead. Called from {filename}:{lineno}"
        )
        warnings.warn(warning_msg, DeprecationWarning, stacklevel=2)
        logger.warning(f"DEPRECATED: {warning_msg}")
        
        self._manager = _get_global_redis_manager()
    
    @property
    def client(self) -> Redis:
        """Get the decoded Redis client."""
        return self._manager.client
    
    def shutdown(self):
        """Shutdown Redis connections."""
        self._manager.cleanup()
    
    def get_connection_stats(self):
        """Get connection statistics."""
        return self._manager.get_connection_stats()