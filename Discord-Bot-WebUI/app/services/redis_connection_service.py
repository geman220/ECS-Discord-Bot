# app/services/redis_connection_service.py

"""
Centralized Redis Connection Service

Industry-grade Redis connection management with:
- Connection pooling
- Circuit breaker pattern
- Automatic failover
- Comprehensive monitoring
- Thread-safe operations
"""

import logging
import time
import threading
import redis
from typing import Dict, Any, Optional, Union
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Circuit breaker tripped
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class ConnectionMetrics:
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    pool_exhaustion_count: int = 0
    circuit_breaker_trips: int = 0
    last_failure_time: float = 0
    uptime_start: float = 0


class RedisConnectionService:
    """
    Enterprise-grade Redis connection service with connection pooling,
    circuit breaker pattern, and comprehensive monitoring.
    """
    
    def __init__(self, 
                 host: str = 'redis',
                 port: int = 6379,
                 db: int = 0,
                 max_connections: int = 20,
                 socket_timeout: int = 5,
                 socket_connect_timeout: int = 5,
                 failure_threshold: int = 5,
                 recovery_timeout: int = 60,
                 half_open_max_calls: int = 3):
        
        self.host = host
        self.port = port
        self.db = db
        self.max_connections = max_connections
        self.socket_timeout = socket_timeout
        self.socket_connect_timeout = socket_connect_timeout
        
        # Circuit breaker configuration
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        
        # State management
        self._pool = None
        self._circuit_state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0
        self._half_open_calls = 0
        self._lock = threading.RLock()
        
        # Metrics
        self.metrics = ConnectionMetrics(uptime_start=time.time())
        
        # Initialize connection pool
        self._initialize_pool()
    
    def _initialize_pool(self) -> None:
        """Initialize Redis connection pool with proper configuration."""
        try:
            with self._lock:
                self._pool = redis.ConnectionPool(
                    host=self.host,
                    port=self.port,
                    db=self.db,
                    decode_responses=True,
                    socket_timeout=self.socket_timeout,
                    socket_connect_timeout=self.socket_connect_timeout,
                    max_connections=self.max_connections,
                    retry_on_timeout=True,
                    health_check_interval=30
                )
                logger.info(f"Redis connection pool initialized: {self.max_connections} max connections")
                
        except Exception as e:
            logger.error(f"Failed to initialize Redis connection pool: {e}")
            raise
    
    def _is_circuit_open(self) -> bool:
        """Check if circuit breaker is open."""
        with self._lock:
            if self._circuit_state == CircuitState.OPEN:
                # Check if recovery timeout has passed
                if time.time() - self._last_failure_time >= self.recovery_timeout:
                    self._circuit_state = CircuitState.HALF_OPEN
                    self._half_open_calls = 0
                    logger.info("Circuit breaker moving to HALF_OPEN state")
                    return False
                return True
            return False
    
    def _record_success(self) -> None:
        """Record successful operation and potentially close circuit."""
        with self._lock:
            self.metrics.successful_requests += 1
            
            if self._circuit_state == CircuitState.HALF_OPEN:
                self._half_open_calls += 1
                if self._half_open_calls >= self.half_open_max_calls:
                    self._circuit_state = CircuitState.CLOSED
                    self._failure_count = 0
                    logger.info("Circuit breaker CLOSED - service recovered")
            elif self._circuit_state == CircuitState.CLOSED:
                # Reset failure count on successful operation
                if self._failure_count > 0:
                    self._failure_count = max(0, self._failure_count - 1)
    
    def _record_failure(self, error: Exception) -> None:
        """Record failed operation and potentially open circuit."""
        with self._lock:
            self.metrics.failed_requests += 1
            self._failure_count += 1
            self._last_failure_time = time.time()
            self.metrics.last_failure_time = self._last_failure_time
            
            if isinstance(error, (redis.ConnectionError, redis.TimeoutError)):
                self.metrics.pool_exhaustion_count += 1
            
            # Trip circuit breaker if failure threshold reached
            if (self._circuit_state == CircuitState.CLOSED and 
                self._failure_count >= self.failure_threshold):
                
                self._circuit_state = CircuitState.OPEN
                self.metrics.circuit_breaker_trips += 1
                logger.error(
                    f"Circuit breaker OPEN - {self._failure_count} consecutive failures. "
                    f"Will retry in {self.recovery_timeout} seconds"
                )
            
            elif self._circuit_state == CircuitState.HALF_OPEN:
                # Half-open test failed, go back to open
                self._circuit_state = CircuitState.OPEN
                logger.warning("Circuit breaker back to OPEN - half-open test failed")
    
    @contextmanager
    def get_connection(self):
        """
        Get a Redis connection with automatic cleanup and circuit breaker protection.
        
        Usage:
            with redis_service.get_connection() as conn:
                result = conn.get('key')
        """
        if self._is_circuit_open():
            raise redis.ConnectionError("Circuit breaker is OPEN")
        
        connection = None
        try:
            self.metrics.total_requests += 1
            
            if not self._pool:
                self._initialize_pool()
            
            connection = redis.Redis(connection_pool=self._pool)
            
            # Test connection with ping
            connection.ping()
            
            self._record_success()
            yield connection
            
        except Exception as e:
            self._record_failure(e)
            logger.error(f"Redis connection error: {e}")
            raise
        finally:
            # Connection automatically returns to pool when Redis object is garbage collected
            pass
    
    def execute_command(self, command: str, *args, **kwargs) -> Any:
        """
        Execute a Redis command with automatic retry and circuit breaker protection.
        
        Args:
            command: Redis command to execute
            *args: Command arguments
            **kwargs: Command keyword arguments
            
        Returns:
            Command result
        """
        with self.get_connection() as conn:
            method = getattr(conn, command)
            return method(*args, **kwargs)
    
    def is_healthy(self) -> bool:
        """Check if Redis service is healthy."""
        try:
            with self.get_connection() as conn:
                conn.ping()
                return True
        except:
            return False
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get comprehensive service metrics."""
        with self._lock:
            current_time = time.time()
            uptime = current_time - self.metrics.uptime_start
            
            total_ops = self.metrics.successful_requests + self.metrics.failed_requests
            success_rate = (self.metrics.successful_requests / total_ops * 100) if total_ops > 0 else 100
            
            pool_info = {}
            if self._pool:
                try:
                    pool_info = {
                        'created_connections': self._pool.created_connections,
                        'available_connections': self._pool.available_connections,
                        'in_use_connections': self._pool.created_connections - self._pool.available_connections,
                        'max_connections': self.max_connections
                    }
                except:
                    pool_info = {'error': 'Unable to get pool stats'}
            
            return {
                'service_status': {
                    'healthy': self.is_healthy(),
                    'circuit_state': self._circuit_state.value,
                    'failure_count': self._failure_count,
                    'uptime_seconds': round(uptime, 2)
                },
                'connection_pool': pool_info,
                'metrics': {
                    'total_requests': self.metrics.total_requests,
                    'successful_requests': self.metrics.successful_requests,
                    'failed_requests': self.metrics.failed_requests,
                    'success_rate_percent': round(success_rate, 2),
                    'pool_exhaustion_count': self.metrics.pool_exhaustion_count,
                    'circuit_breaker_trips': self.metrics.circuit_breaker_trips
                },
                'configuration': {
                    'host': self.host,
                    'port': self.port,
                    'max_connections': self.max_connections,
                    'failure_threshold': self.failure_threshold,
                    'recovery_timeout': self.recovery_timeout
                }
            }
    
    def reset_circuit_breaker(self) -> None:
        """Manually reset circuit breaker (for admin use)."""
        with self._lock:
            self._circuit_state = CircuitState.CLOSED
            self._failure_count = 0
            self._half_open_calls = 0
            logger.info("Circuit breaker manually reset")
    
    def close(self) -> None:
        """Close connection pool and cleanup resources."""
        with self._lock:
            if self._pool:
                self._pool.disconnect()
                self._pool = None
                logger.info("Redis connection pool closed")


# Global service instance
_redis_service = None
_service_lock = threading.Lock()


def get_redis_service():
    """Get the global Redis service instance - now using UnifiedRedisManager for connection efficiency."""
    from app.utils.redis_manager import UnifiedRedisManager
    
    # Return a wrapper that maintains API compatibility with existing code
    class UnifiedRedisManagerWrapper:
        def __init__(self):
            self._manager = UnifiedRedisManager()
        
        def get_connection(self):
            """Get Redis connection - maintains API compatibility"""
            from contextlib import contextmanager
            
            @contextmanager
            def _connection_context():
                client = self._manager.client
                try:
                    yield client
                except Exception as e:
                    logger.error(f"Redis operation error: {e}")
                    raise
                
            return _connection_context()
        
        def execute_with_retry(self, operation, *args, **kwargs):
            """Execute operation with retry - maintains API compatibility"""
            try:
                client = self._manager.client
                return operation(client, *args, **kwargs)
            except Exception as e:
                logger.error(f"Redis operation failed: {e}")
                raise
        
        # Maintain other API methods that existing code might use
        def get_metrics(self):
            return self._manager.get_connection_stats()
        
        # Circuit breaker compatibility
        def is_healthy(self):
            try:
                client = self._manager.client
                result = client.ping()
                return bool(result)
            except Exception as e:
                logger.error(f"Redis health check failed: {e}")
                return False
        
        # Add missing Redis methods that tasks expect
        def llen(self, name):
            """Get the length of a list - for queue monitoring"""
            try:
                client = self._manager.client
                return client.llen(name)
            except Exception as e:
                logger.error(f"Redis llen failed for {name}: {e}")
                return 0
        
        def lindex(self, name, index):
            """Get list element by index - for queue monitoring"""
            try:
                client = self._manager.client
                return client.lindex(name, index)
            except Exception as e:
                logger.error(f"Redis lindex failed for {name}[{index}]: {e}")
                return None

        def get(self, key):
            """Get value by key - for basic Redis operations"""
            try:
                client = self._manager.client
                return client.get(key)
            except Exception as e:
                logger.error(f"Redis get failed for {key}: {e}")
                return None

        def set(self, key, value, **kwargs):
            """Set value by key - for basic Redis operations"""
            try:
                client = self._manager.client
                return client.set(key, value, **kwargs)
            except Exception as e:
                logger.error(f"Redis set failed for {key}: {e}")
                return False

        def setex(self, key, time, value):
            """Set value by key with expiration time - for basic Redis operations"""
            try:
                client = self._manager.client
                return client.setex(key, time, value)
            except Exception as e:
                logger.error(f"Redis setex failed for {key}: {e}")
                return False
        
        def execute_command(self, *args, **kwargs):
            """Execute Redis command - for advanced operations"""
            try:
                client = self._manager.client
                
                # Handle special cases where we should use the client method instead of execute_command
                if len(args) >= 1 and args[0].lower() == 'set':
                    # Convert 'set' execute_command to client.set() method call
                    if len(args) >= 3:
                        key, value = args[1], args[2]
                        return client.set(key, value, **kwargs)
                    else:
                        logger.error(f"Invalid SET command args: {args}")
                        return False
                elif len(args) >= 1 and args[0].lower() == 'get':
                    # Convert 'get' execute_command to client.get() method call
                    if len(args) >= 2:
                        key = args[1]
                        return client.get(key)
                    else:
                        logger.error(f"Invalid GET command args: {args}")
                        return None
                elif len(args) >= 1 and args[0].lower() == 'delete':
                    # Convert 'delete' execute_command to client.delete() method call
                    if len(args) >= 2:
                        keys = args[1:]
                        return client.delete(*keys)
                    else:
                        logger.error(f"Invalid DELETE command args: {args}")
                        return 0
                
                # For all other commands, use execute_command
                return client.execute_command(*args, **kwargs)
            except Exception as e:
                logger.error(f"Redis execute_command failed: {e}")
                raise
    
    global _redis_service
    
    if _redis_service is None:
        with _service_lock:
            if _redis_service is None:
                _redis_service = UnifiedRedisManagerWrapper()
    
    return _redis_service


def reset_redis_service() -> None:
    """Reset the global Redis service (for testing/debugging)."""
    global _redis_service
    
    with _service_lock:
        if _redis_service:
            _redis_service.close()
        _redis_service = None