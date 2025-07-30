# app/utils/circuit_breaker.py

"""
Circuit Breaker Pattern Implementation

Provides fault tolerance for external service calls with:
- Automatic failure detection
- Fast failure during outages  
- Automatic recovery testing
- Configurable thresholds and timeouts
- Detailed metrics and logging
"""

import asyncio
import time
import logging
from enum import Enum
from typing import Callable, Any, Optional, Dict, Type
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from functools import wraps

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"        # Normal operation - requests pass through
    OPEN = "open"           # Failing fast - requests immediately fail
    HALF_OPEN = "half_open" # Testing recovery - limited requests pass through


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker behavior."""
    
    # Failure detection
    failure_threshold: int = 5          # Failures before opening circuit
    success_threshold: int = 3          # Successes to close from half-open
    timeout: int = 60                   # Seconds before attempting recovery
    
    # Monitoring window
    monitoring_window: int = 300        # Seconds to track failures (5 minutes)
    
    # Expected exceptions that trigger circuit breaker
    expected_exceptions: tuple = (Exception,)
    
    # Rate limiting in half-open state
    half_open_max_requests: int = 5     # Max requests allowed in half-open
    
    # Timeouts
    call_timeout: float = 30.0          # Max time for individual calls
    
    # Recovery behavior
    recovery_backoff_multiplier: float = 1.5  # Exponential backoff
    max_recovery_timeout: int = 300     # Max timeout between recovery attempts


@dataclass
class CircuitBreakerMetrics:
    """Metrics tracked by circuit breaker."""
    
    # Counters
    total_requests: int = 0
    successful_requests: int = 0 
    failed_requests: int = 0
    circuit_opened_count: int = 0
    
    # State tracking
    current_state: CircuitState = CircuitState.CLOSED
    last_state_change: Optional[datetime] = None
    last_failure_time: Optional[datetime] = None
    
    # Recent failures for monitoring window
    recent_failures: list = field(default_factory=list)
    
    # Performance
    avg_response_time: float = 0.0
    last_request_time: Optional[datetime] = None
    
    def add_success(self, response_time: float):
        """Record a successful request."""
        self.total_requests += 1
        self.successful_requests += 1
        self.last_request_time = datetime.utcnow()
        
        # Update average response time (exponential moving average)
        if self.avg_response_time == 0:
            self.avg_response_time = response_time
        else:
            self.avg_response_time = (self.avg_response_time * 0.9) + (response_time * 0.1)
    
    def add_failure(self):
        """Record a failed request."""
        self.total_requests += 1
        self.failed_requests += 1
        self.last_failure_time = datetime.utcnow()
        self.last_request_time = datetime.utcnow()
        
        # Add to recent failures for monitoring window
        self.recent_failures.append(time.time())
    
    def get_failure_rate(self, window_seconds: int) -> float:
        """Get failure rate within the specified time window."""
        if not self.recent_failures:
            return 0.0
        
        cutoff_time = time.time() - window_seconds
        recent = [f for f in self.recent_failures if f > cutoff_time]
        
        # Update recent_failures to remove old entries
        self.recent_failures = recent
        
        if self.total_requests == 0:
            return 0.0
        
        return len(recent) / max(self.total_requests, 1)
    
    def get_success_rate(self) -> float:
        """Get overall success rate."""
        if self.total_requests == 0:
            return 1.0
        return self.successful_requests / self.total_requests


class CircuitBreaker:
    """
    Circuit breaker implementation with enterprise features.
    
    Provides automatic fault tolerance for external service calls by:
    1. Monitoring failure rates
    2. Opening circuit when threshold exceeded  
    3. Failing fast during outages
    4. Automatically testing recovery
    5. Closing circuit when service recovers
    """
    
    def __init__(
        self,
        name: str,
        config: Optional[CircuitBreakerConfig] = None
    ):
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self.metrics = CircuitBreakerMetrics()
        
        # State management
        self._state_lock = asyncio.Lock()
        self._half_open_requests = 0
        self._next_recovery_attempt = None
        
        logger.info(f"🔒 Initialized circuit breaker '{name}' with config: {self.config}")
    
    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function with circuit breaker protection.
        
        Args:
            func: Async function to execute
            *args, **kwargs: Arguments to pass to function
            
        Returns:
            Function result
            
        Raises:
            CircuitBreakerOpenError: When circuit is open
            Original exception: When function fails and circuit allows
        """
        async with self._state_lock:
            # Check if we should allow this request
            if not await self._should_allow_request():
                raise CircuitBreakerOpenError(
                    f"Circuit breaker '{self.name}' is OPEN - failing fast"
                )
            
            # Track half-open requests
            if self.metrics.current_state == CircuitState.HALF_OPEN:
                self._half_open_requests += 1
        
        # Execute the function with timeout protection
        start_time = time.time()
        try:
            # Apply timeout to prevent hanging
            result = await asyncio.wait_for(
                func(*args, **kwargs),
                timeout=self.config.call_timeout
            )
            
            # Record success
            response_time = time.time() - start_time
            await self._record_success(response_time)
            
            return result
            
        except asyncio.TimeoutError as e:
            await self._record_failure(e)
            raise CircuitBreakerTimeoutError(
                f"Circuit breaker '{self.name}' call timeout after {self.config.call_timeout}s"
            ) from e
            
        except self.config.expected_exceptions as e:
            await self._record_failure(e)
            raise
        
        except Exception as e:
            # Unexpected exception - don't trigger circuit breaker
            logger.warning(f"⚠️ Unexpected exception in circuit breaker '{self.name}': {e}")
            raise
    
    async def _should_allow_request(self) -> bool:
        """Determine if request should be allowed based on current state."""
        
        if self.metrics.current_state == CircuitState.CLOSED:
            return True
        
        elif self.metrics.current_state == CircuitState.OPEN:
            # Check if enough time has passed to attempt recovery
            if self._should_attempt_recovery():
                await self._transition_to_half_open()
                return True
            return False
        
        elif self.metrics.current_state == CircuitState.HALF_OPEN:
            # Allow limited requests in half-open state
            return self._half_open_requests < self.config.half_open_max_requests
        
        return False
    
    def _should_attempt_recovery(self) -> bool:
        """Check if enough time has passed to attempt recovery."""
        if self._next_recovery_attempt is None:
            return True
        
        return time.time() >= self._next_recovery_attempt
    
    async def _record_success(self, response_time: float):
        """Record successful request and potentially close circuit."""
        async with self._state_lock:
            self.metrics.add_success(response_time)
            
            logger.debug(f"✅ Circuit breaker '{self.name}' - successful call ({response_time:.3f}s)")
            
            # If in half-open state, check if we should close
            if self.metrics.current_state == CircuitState.HALF_OPEN:
                if self.metrics.successful_requests >= self.config.success_threshold:
                    await self._transition_to_closed()
    
    async def _record_failure(self, exception: Exception):
        """Record failed request and potentially open circuit."""
        async with self._state_lock:
            self.metrics.add_failure()
            
            logger.warning(f"❌ Circuit breaker '{self.name}' - failed call: {exception}")
            
            # Check if we should open the circuit
            if self.metrics.current_state in [CircuitState.CLOSED, CircuitState.HALF_OPEN]:
                failure_rate = self.metrics.get_failure_rate(self.config.monitoring_window)
                recent_failures = len([
                    f for f in self.metrics.recent_failures 
                    if f > (time.time() - self.config.monitoring_window)
                ])
                
                should_open = (
                    recent_failures >= self.config.failure_threshold or
                    (self.metrics.total_requests >= self.config.failure_threshold and 
                     failure_rate > 0.5)  # 50% failure rate
                )
                
                if should_open:
                    await self._transition_to_open()
                elif self.metrics.current_state == CircuitState.HALF_OPEN:
                    # Failed during recovery - go back to open
                    await self._transition_to_open()
    
    async def _transition_to_open(self):
        """Transition circuit breaker to OPEN state."""
        if self.metrics.current_state != CircuitState.OPEN:
            self.metrics.current_state = CircuitState.OPEN
            self.metrics.last_state_change = datetime.utcnow()
            self.metrics.circuit_opened_count += 1
            
            # Calculate next recovery attempt with exponential backoff
            backoff = min(
                self.config.timeout * (self.config.recovery_backoff_multiplier ** self.metrics.circuit_opened_count),
                self.config.max_recovery_timeout
            )
            self._next_recovery_attempt = time.time() + backoff
            
            logger.warning(f"🚨 Circuit breaker '{self.name}' OPENED - will attempt recovery in {backoff:.1f}s")
    
    async def _transition_to_half_open(self):
        """Transition circuit breaker to HALF_OPEN state."""
        if self.metrics.current_state != CircuitState.HALF_OPEN:
            self.metrics.current_state = CircuitState.HALF_OPEN
            self.metrics.last_state_change = datetime.utcnow()
            self._half_open_requests = 0
            
            logger.info(f"🔄 Circuit breaker '{self.name}' entering HALF_OPEN state - testing recovery")
    
    async def _transition_to_closed(self):
        """Transition circuit breaker to CLOSED state."""
        if self.metrics.current_state != CircuitState.CLOSED:
            self.metrics.current_state = CircuitState.CLOSED
            self.metrics.last_state_change = datetime.utcnow()
            self._half_open_requests = 0
            self._next_recovery_attempt = None
            
            # Reset some metrics for fresh start
            self.metrics.recent_failures.clear()
            
            logger.info(f"✅ Circuit breaker '{self.name}' CLOSED - service recovered")
    
    def get_status(self) -> Dict[str, Any]:
        """Get current circuit breaker status and metrics."""
        return {
            'name': self.name,
            'state': self.metrics.current_state.value,
            'last_state_change': self.metrics.last_state_change.isoformat() if self.metrics.last_state_change else None,
            'total_requests': self.metrics.total_requests,
            'successful_requests': self.metrics.successful_requests,
            'failed_requests': self.metrics.failed_requests,
            'success_rate': self.metrics.get_success_rate(),
            'failure_rate_5m': self.metrics.get_failure_rate(300),
            'avg_response_time': self.metrics.avg_response_time,
            'circuit_opened_count': self.metrics.circuit_opened_count,
            'next_recovery_attempt': self._next_recovery_attempt,
            'config': {
                'failure_threshold': self.config.failure_threshold,
                'timeout': self.config.timeout,
                'call_timeout': self.config.call_timeout
            }
        }
    
    async def force_open(self):
        """Manually open the circuit breaker."""
        async with self._state_lock:
            await self._transition_to_open()
            logger.warning(f"🔒 Circuit breaker '{self.name}' manually OPENED")
    
    async def force_close(self):
        """Manually close the circuit breaker."""
        async with self._state_lock:
            await self._transition_to_closed()
            logger.info(f"🔓 Circuit breaker '{self.name}' manually CLOSED")


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open and failing fast."""
    pass


class CircuitBreakerTimeoutError(Exception):
    """Raised when circuit breaker call times out."""
    pass


def circuit_breaker(
    name: str,
    config: Optional[CircuitBreakerConfig] = None
):
    """
    Decorator for adding circuit breaker protection to async functions.
    
    Usage:
        @circuit_breaker("discord_api", CircuitBreakerConfig(failure_threshold=3))
        async def update_discord_embed(message_id):
            # This function is now protected by circuit breaker
            pass
    """
    breaker = CircuitBreaker(name, config)
    
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await breaker.call(func, *args, **kwargs)
        
        # Attach circuit breaker instance for external access
        wrapper._circuit_breaker = breaker
        return wrapper
    
    return decorator


# Global registry of circuit breakers for monitoring
_circuit_breakers: Dict[str, CircuitBreaker] = {}

def register_circuit_breaker(breaker: CircuitBreaker):
    """Register circuit breaker for global monitoring."""
    _circuit_breakers[breaker.name] = breaker

def get_circuit_breaker(name: str) -> Optional[CircuitBreaker]:
    """Get circuit breaker by name."""
    return _circuit_breakers.get(name)

def get_all_circuit_breakers() -> Dict[str, CircuitBreaker]:
    """Get all registered circuit breakers."""
    return _circuit_breakers.copy()

async def get_circuit_breaker_health() -> Dict[str, Any]:
    """Get health status of all circuit breakers."""
    health = {
        'overall_status': 'healthy',
        'total_breakers': len(_circuit_breakers),
        'breakers': {}
    }
    
    open_count = 0
    for name, breaker in _circuit_breakers.items():
        status = breaker.get_status()
        health['breakers'][name] = status
        
        if status['state'] == 'open':
            open_count += 1
    
    if open_count > 0:
        health['overall_status'] = 'degraded' if open_count < len(_circuit_breakers) else 'critical'
        health['open_breakers'] = open_count
    
    return health