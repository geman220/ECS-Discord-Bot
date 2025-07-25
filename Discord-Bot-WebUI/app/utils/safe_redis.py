# app/utils/safe_redis.py

"""
Safe Redis Wrapper Module

This module provides a safer interface to Redis operations that gracefully handles
connection failures and provides consistent behavior when Redis is unavailable.
"""

import logging
from typing import Any, Optional, Union, List, Dict
from contextlib import contextmanager

from app.utils.redis_manager import get_redis_manager, UnifiedRedisManager

logger = logging.getLogger(__name__)


class SafeRedisClient:
    """
    A wrapper around Redis client that provides safe access with proper error handling
    and fallback behavior when Redis is unavailable.
    """
    
    def __init__(self, redis_manager: Optional[UnifiedRedisManager] = None):
        """Initialize with optional redis manager."""
        self._manager = redis_manager or get_redis_manager()
        self._warned = False
    
    @property
    def client(self):
        """Get the underlying Redis client."""
        return self._manager.client
    
    @property
    def is_available(self) -> bool:
        """Check if Redis is actually available (not a fallback client)."""
        try:
            client = self.client
            if client is None:
                return False
            # Try to ping - fallback clients return False
            return bool(client.ping())
        except Exception:
            return False
    
    def _warn_once(self, operation: str):
        """Warn once about Redis unavailability."""
        if not self._warned:
            logger.warning(f"Redis is not available for operation: {operation}. Using fallback behavior.")
            self._warned = True
    
    @contextmanager
    def safe_operation(self, operation_name: str, default_return: Any = None):
        """
        Context manager for safe Redis operations.
        
        Usage:
            with redis.safe_operation("get_user", default_return=None) as (client, should_proceed):
                if should_proceed:
                    return client.get("user:123")
                return None  # or handle the fallback case
        """
        if not self.is_available:
            self._warn_once(operation_name)
            yield (None, False)
            return
        
        try:
            yield (self.client, True)
        except Exception as e:
            logger.error(f"Redis operation '{operation_name}' failed: {str(e)}")
            # Don't yield again - just return
    
    # Safe wrapper methods for common Redis operations
    
    def get(self, key: str, default: Any = None) -> Any:
        """Safely get a value from Redis."""
        with self.safe_operation("get", default) as (client, should_proceed):
            if should_proceed:
                value = client.get(key)
                return value if value is not None else default
            return default
    
    def set(self, key: str, value: Any, **kwargs) -> bool:
        """Safely set a value in Redis."""
        with self.safe_operation("set", False) as (client, should_proceed):
            if should_proceed:
                return bool(client.set(key, value, **kwargs))
            return False
    
    def setex(self, key: str, seconds: int, value: Any) -> bool:
        """Safely set a value with expiration in Redis."""
        with self.safe_operation("setex", False) as (client, should_proceed):
            if should_proceed:
                return bool(client.setex(key, seconds, value))
            return False
    
    def delete(self, *keys: str) -> int:
        """Safely delete keys from Redis."""
        with self.safe_operation("delete", 0) as (client, should_proceed):
            if should_proceed:
                return client.delete(*keys)
            return 0
    
    def exists(self, key: str) -> bool:
        """Safely check if a key exists in Redis."""
        with self.safe_operation("exists", False) as (client, should_proceed):
            if should_proceed:
                return bool(client.exists(key))
            return False
    
    def keys(self, pattern: str = '*') -> List[str]:
        """Safely get keys matching a pattern."""
        with self.safe_operation("keys", []) as (client, should_proceed):
            if should_proceed:
                keys = client.keys(pattern)
                # Handle both bytes and string returns
                return [k.decode('utf-8') if isinstance(k, bytes) else k for k in keys]
            return []
    
    def ttl(self, key: str) -> int:
        """Safely get TTL of a key."""
        with self.safe_operation("ttl", -2) as (client, should_proceed):
            if should_proceed:
                return client.ttl(key)
            return -2  # -2 means key doesn't exist
    
    def ping(self) -> bool:
        """Safely ping Redis."""
        with self.safe_operation("ping", False) as (client, should_proceed):
            if should_proceed:
                return bool(client.ping())
            return False
    
    def hget(self, key: str, field: str, default: Any = None) -> Any:
        """Safely get a hash field value."""
        with self.safe_operation("hget", default) as (client, should_proceed):
            if should_proceed:
                value = client.hget(key, field)
                return value if value is not None else default
            return default
    
    def hset(self, key: str, field: str, value: Any) -> bool:
        """Safely set a hash field value."""
        with self.safe_operation("hset", False) as (client, should_proceed):
            if should_proceed:
                return bool(client.hset(key, field, value))
            return False
    
    def hmset(self, key: str, mapping: Dict[str, Any]) -> bool:
        """Safely set multiple hash fields."""
        with self.safe_operation("hmset", False) as (client, should_proceed):
            if should_proceed:
                return bool(client.hset(key, mapping=mapping))
            return False
    
    def hgetall(self, key: str) -> Dict[str, Any]:
        """Safely get all hash fields."""
        with self.safe_operation("hgetall", {}) as (client, should_proceed):
            if should_proceed:
                return client.hgetall(key) or {}
            return {}
    
    def expire(self, key: str, seconds: int) -> bool:
        """Safely set expiration on a key."""
        with self.safe_operation("expire", False) as (client, should_proceed):
            if should_proceed:
                return bool(client.expire(key, seconds))
            return False
    
    def scan(self, cursor: int = 0, match: str = None, count: int = None):
        """Safely scan Redis keys."""
        with self.safe_operation("scan", (0, [])) as (client, should_proceed):
            if should_proceed:
                return client.scan(cursor=cursor, match=match, count=count)
            return (0, [])
    
    def pipeline(self):
        """Get a pipeline for batch operations."""
        if not self.is_available:
            self._warn_once("pipeline")
            # Return a dummy pipeline that does nothing
            from types import SimpleNamespace
            return SimpleNamespace(
                execute=lambda: [],
                set=lambda *args, **kwargs: None,
                get=lambda *args: None,
                delete=lambda *args: None,
                expire=lambda *args: None,
                hmset=lambda *args, **kwargs: None,
                hset=lambda *args, **kwargs: None,
                hgetall=lambda *args: {},
            )
        return self.client.pipeline()


# Global safe Redis instance
_safe_redis_client: Optional[SafeRedisClient] = None


def get_safe_redis() -> SafeRedisClient:
    """
    Get the global safe Redis client instance.
    
    This is the recommended way to access Redis throughout the application.
    It provides consistent error handling and fallback behavior.
    """
    global _safe_redis_client
    if _safe_redis_client is None:
        _safe_redis_client = SafeRedisClient()
    return _safe_redis_client


def redis_required(func):
    """
    Decorator that ensures Redis is available before executing a function.
    
    If Redis is not available, the function returns None and logs a warning.
    """
    def wrapper(*args, **kwargs):
        redis = get_safe_redis()
        if not redis.is_available:
            logger.warning(f"Function {func.__name__} requires Redis but it's not available")
            return None
        return func(*args, **kwargs)
    return wrapper