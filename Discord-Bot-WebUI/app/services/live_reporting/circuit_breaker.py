# app/services/live_reporting/circuit_breaker.py

"""
Circuit Breaker Pattern Implementation

Industry standard circuit breaker for fault tolerance and resilience.
Prevents cascading failures by temporarily disabling failing services.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Type, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"         # Failing, requests blocked
    HALF_OPEN = "half_open"  # Testing if service recovered


class CircuitBreakerError(Exception):
    """Raised when circuit breaker is open."""
    pass


@dataclass
class CircuitBreakerMetrics:
    """Circuit breaker metrics."""
    failure_count: int = 0
    success_count: int = 0
    total_requests: int = 0
    last_failure_time: Optional[datetime] = None
    state_change_time: datetime = None
    
    def __post_init__(self):
        if self.state_change_time is None:
            self.state_change_time = datetime.utcnow()


class CircuitBreaker:
    """
    Circuit breaker implementation for fault tolerance.
    
    The circuit breaker operates in three states:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Too many failures, requests are blocked
    - HALF_OPEN: Testing if service has recovered
    
    Features:
    - Configurable failure threshold
    - Automatic recovery attempts
    - Exponential backoff for recovery
    - Metrics tracking
    - Type-safe exception handling
    """
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        expected_exception: Type[Exception] = Exception,
        success_threshold: int = 1
    ):
        """
        Initialize circuit breaker.
        
        Args:
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Seconds to wait before attempting recovery
            expected_exception: Exception type that triggers circuit breaker
            success_threshold: Number of successes needed to close circuit from half-open
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        self.success_threshold = success_threshold
        
        self._state = CircuitState.CLOSED
        self._metrics = CircuitBreakerMetrics()
        self._lock = asyncio.Lock()
    
    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        return self._state
    
    @property
    def metrics(self) -> CircuitBreakerMetrics:
        """Get circuit metrics."""
        return self._metrics
    
    def can_execute(self) -> bool:
        """
        Check if requests can be executed.
        
        Returns:
            bool: True if requests should be allowed
        """
        if self._state == CircuitState.CLOSED:
            return True
        
        if self._state == CircuitState.OPEN:
            # Check if recovery timeout has passed
            if self._should_attempt_reset():
                self._state = CircuitState.HALF_OPEN
                self._metrics.state_change_time = datetime.utcnow()
                logger.info("Circuit breaker moved to HALF_OPEN state")
                return True
            return False
        
        if self._state == CircuitState.HALF_OPEN:
            return True
        
        return False
    
    async def record_success(self):
        """Record a successful operation."""
        async with self._lock:
            self._metrics.success_count += 1
            self._metrics.total_requests += 1
            
            if self._state == CircuitState.HALF_OPEN:
                if self._metrics.success_count >= self.success_threshold:
                    self._reset()
                    logger.info("Circuit breaker reset to CLOSED state after successful recovery")
    
    async def record_failure(self):
        """Record a failed operation."""
        async with self._lock:
            self._metrics.failure_count += 1
            self._metrics.total_requests += 1
            self._metrics.last_failure_time = datetime.utcnow()
            
            if self._state == CircuitState.HALF_OPEN:
                self._trip()
                logger.warning("Circuit breaker tripped during recovery attempt")
            elif self._state == CircuitState.CLOSED:
                if self._metrics.failure_count >= self.failure_threshold:
                    self._trip()
                    logger.error(
                        f"Circuit breaker opened after {self._metrics.failure_count} failures"
                    )
    
    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset."""
        if not self._metrics.last_failure_time:
            return True
        
        elapsed = datetime.utcnow() - self._metrics.last_failure_time
        return elapsed.total_seconds() >= self.recovery_timeout
    
    def _trip(self):
        """Trip the circuit breaker to OPEN state."""
        self._state = CircuitState.OPEN
        self._metrics.state_change_time = datetime.utcnow()
    
    def _reset(self):
        """Reset the circuit breaker to CLOSED state."""
        self._state = CircuitState.CLOSED
        self._metrics.failure_count = 0
        self._metrics.success_count = 0
        self._metrics.state_change_time = datetime.utcnow()
    
    async def call(self, func, *args, **kwargs) -> Any:
        """
        Execute function with circuit breaker protection.
        
        Args:
            func: Function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments
            
        Returns:
            Function result
            
        Raises:
            CircuitBreakerError: If circuit is open
            Any exception from the function
        """
        if not self.can_execute():
            raise CircuitBreakerError(f"Circuit breaker is {self._state.value}")
        
        try:
            result = await func(*args, **kwargs) if asyncio.iscoroutinefunction(func) else func(*args, **kwargs)
            await self.record_success()
            return result
        except self.expected_exception as e:
            await self.record_failure()
            raise e
        except Exception as e:
            # Unexpected exceptions don't trigger circuit breaker
            logger.error(f"Unexpected exception in circuit breaker: {e}")
            raise e
    
    def get_stats(self) -> dict:
        """Get circuit breaker statistics."""
        uptime = datetime.utcnow() - self._metrics.state_change_time
        failure_rate = (
            self._metrics.failure_count / self._metrics.total_requests
            if self._metrics.total_requests > 0 else 0
        )
        
        return {
            'state': self._state.value,
            'failure_count': self._metrics.failure_count,
            'success_count': self._metrics.success_count,
            'total_requests': self._metrics.total_requests,
            'failure_rate': failure_rate,
            'uptime_seconds': uptime.total_seconds(),
            'last_failure_time': self._metrics.last_failure_time.isoformat() if self._metrics.last_failure_time else None,
            'state_change_time': self._metrics.state_change_time.isoformat()
        }