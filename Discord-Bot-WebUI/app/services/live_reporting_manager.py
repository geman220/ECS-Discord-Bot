# app/services/live_reporting_manager.py

"""
Live Reporting Manager Service

Industry-standard event-driven live reporting system with circuit breaker protection,
backpressure management, and self-healing capabilities. Replaces the problematic
time-based cron approach with a robust, scalable architecture.
"""

import time
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from enum import Enum
from dataclasses import dataclass

from app.core import db, celery as celery_app
from app.models.live_reporting_session import LiveReportingSession
from app.tasks.tasks_live_reporting_v2 import process_single_match_v2


logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states"""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, blocking requests
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class CircuitBreakerConfig:
    """Circuit breaker configuration"""
    failure_threshold: int = 5  # Failed requests before opening
    recovery_timeout: int = 60  # Seconds before attempting half-open
    success_threshold: int = 2   # Successful requests to close from half-open
    max_queue_size: int = 100   # Maximum queued tasks before backpressure


class LiveReportingCircuitBreaker:
    """
    Circuit breaker for live reporting operations.
    Prevents cascade failures and provides backpressure protection.
    """
    
    def __init__(self, config: CircuitBreakerConfig = None):
        self.config = config or CircuitBreakerConfig()
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = None
        self.redis_key_prefix = "live_reporting_circuit_breaker"
        
    def _get_redis_key(self, suffix: str) -> str:
        """Get Redis key for circuit breaker state"""
        return f"{self.redis_key_prefix}:{suffix}"
    
    def _load_state_from_redis(self):
        """Load circuit breaker state from Redis for persistence"""
        try:
            # Use celery's Redis connection
            redis_client = celery_app.backend.client
            
            state_data = redis_client.hgetall(self._get_redis_key("state"))
            if state_data:
                self.state = CircuitState(state_data.get(b'state', b'closed').decode())
                self.failure_count = int(state_data.get(b'failure_count', b'0'))
                self.success_count = int(state_data.get(b'success_count', b'0'))
                last_failure = state_data.get(b'last_failure_time')
                if last_failure:
                    self.last_failure_time = float(last_failure.decode())
                    
        except Exception as e:
            logger.warning(f"Failed to load circuit breaker state: {e}")
            # Use defaults
    
    def _save_state_to_redis(self):
        """Save circuit breaker state to Redis for persistence"""
        try:
            redis_client = celery_app.backend.client
            
            state_data = {
                'state': self.state.value,
                'failure_count': self.failure_count,
                'success_count': self.success_count,
                'last_failure_time': self.last_failure_time or 0,
                'updated_at': time.time()
            }
            
            redis_client.hset(self._get_redis_key("state"), mapping=state_data)
            redis_client.expire(self._get_redis_key("state"), 3600)  # 1 hour TTL
            
        except Exception as e:
            logger.warning(f"Failed to save circuit breaker state: {e}")
    
    def can_execute(self) -> bool:
        """Check if operation can be executed based on circuit state"""
        self._load_state_from_redis()
        
        if self.state == CircuitState.CLOSED:
            return True
            
        elif self.state == CircuitState.OPEN:
            # Check if enough time has passed to try half-open
            if (self.last_failure_time and 
                time.time() - self.last_failure_time > self.config.recovery_timeout):
                self.state = CircuitState.HALF_OPEN
                self.success_count = 0
                self._save_state_to_redis()
                logger.info("Circuit breaker moving to HALF_OPEN state")
                return True
            return False
            
        elif self.state == CircuitState.HALF_OPEN:
            return True
            
        return False
    
    def record_success(self):
        """Record successful operation"""
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.config.success_threshold:
                self.state = CircuitState.CLOSED
                self.failure_count = 0
                self.success_count = 0
                logger.info("Circuit breaker CLOSED - service recovered")
                
        elif self.state == CircuitState.CLOSED:
            # Reset failure count on success
            self.failure_count = max(0, self.failure_count - 1)
            
        self._save_state_to_redis()
    
    def record_failure(self):
        """Record failed operation"""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.state == CircuitState.CLOSED:
            if self.failure_count >= self.config.failure_threshold:
                self.state = CircuitState.OPEN
                logger.warning(f"Circuit breaker OPEN - too many failures ({self.failure_count})")
                
        elif self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.OPEN
            logger.warning("Circuit breaker OPEN - failed during recovery attempt")
            
        self._save_state_to_redis()


class LiveReportingManager:
    """
    Event-driven live reporting manager with industry-standard patterns.
    
    Features:
    - Circuit breaker protection against cascade failures
    - Backpressure management to prevent queue flooding
    - Self-healing and graceful degradation
    - Persistent state management across restarts
    - Intelligent retry with exponential backoff
    """
    
    def __init__(self):
        self.circuit_breaker = LiveReportingCircuitBreaker()
        
    def get_active_sessions(self) -> List[LiveReportingSession]:
        """Get all active live reporting sessions"""
        try:
            return LiveReportingSession.get_active_sessions(db.session)
        except Exception as e:
            logger.error(f"Failed to get active sessions: {e}")
            return []
    
    def get_queue_size(self) -> int:
        """Get current queue size for backpressure monitoring"""
        try:
            redis_client = celery_app.backend.client
            return redis_client.llen('live_reporting')
        except Exception as e:
            logger.warning(f"Failed to get queue size: {e}")
            return 0
    
    def check_backpressure(self) -> bool:
        """Check if backpressure protection should be applied"""
        queue_size = self.get_queue_size()
        max_size = self.circuit_breaker.config.max_queue_size
        
        if queue_size >= max_size:
            logger.warning(f"Backpressure triggered: queue size {queue_size} >= {max_size}")
            return True
        return False
    
    def schedule_match_processing(self, session: LiveReportingSession) -> bool:
        """
        Schedule processing for a single match with protection mechanisms.
        
        Returns True if task was scheduled, False if blocked by protection.
        """
        # Check circuit breaker
        if not self.circuit_breaker.can_execute():
            logger.info(f"Circuit breaker blocking match {session.match_id}")
            return False
        
        # Check backpressure
        if self.check_backpressure():
            logger.warning(f"Backpressure blocking match {session.match_id}")
            return False
        
        try:
            # Schedule the task with retry policy
            task = process_single_match_v2.apply_async(
                args=[session.match_id],
                queue='live_reporting',
                retry=True,
                retry_policy={
                    'max_retries': 3,
                    'interval_start': 2,
                    'interval_step': 2,
                    'interval_max': 30,
                }
            )
            
            logger.info(f"Scheduled processing for match {session.match_id}, task: {task.id}")
            self.circuit_breaker.record_success()
            return True
            
        except Exception as e:
            logger.error(f"Failed to schedule match {session.match_id}: {e}")
            self.circuit_breaker.record_failure()
            return False
    
    def process_active_sessions(self) -> Dict[str, Any]:
        """
        Process all active sessions with protection mechanisms.
        
        Returns processing statistics.
        """
        start_time = time.time()
        stats = {
            'total_sessions': 0,
            'scheduled_tasks': 0,
            'blocked_by_circuit_breaker': 0,
            'blocked_by_backpressure': 0,
            'processing_time': 0,
            'circuit_breaker_state': self.circuit_breaker.state.value
        }
        
        try:
            active_sessions = self.get_active_sessions()
            stats['total_sessions'] = len(active_sessions)
            
            if not active_sessions:
                logger.info("No active live reporting sessions found")
                return stats
            
            logger.info(f"Processing {len(active_sessions)} active sessions")
            
            for session in active_sessions:
                # Check if session is stale (no updates in 2 hours)
                if (session.last_update and 
                    datetime.utcnow() - session.last_update > timedelta(hours=2)):
                    logger.warning(f"Deactivating stale session: {session.match_id}")
                    session.deactivate(db.session, "Session stale - no updates in 2 hours")
                    db.session.commit()
                    continue
                
                # Schedule processing
                scheduled = self.schedule_match_processing(session)
                if scheduled:
                    stats['scheduled_tasks'] += 1
                else:
                    if not self.circuit_breaker.can_execute():
                        stats['blocked_by_circuit_breaker'] += 1
                    elif self.check_backpressure():
                        stats['blocked_by_backpressure'] += 1
            
        except Exception as e:
            logger.error(f"Error processing active sessions: {e}")
            self.circuit_breaker.record_failure()
        
        stats['processing_time'] = time.time() - start_time
        return stats
    
    def health_check(self) -> Dict[str, Any]:
        """Comprehensive health check for monitoring"""
        return {
            'circuit_breaker_state': self.circuit_breaker.state.value,
            'circuit_breaker_failures': self.circuit_breaker.failure_count,
            'queue_size': self.get_queue_size(),
            'max_queue_size': self.circuit_breaker.config.max_queue_size,
            'active_sessions': len(self.get_active_sessions()),
            'timestamp': datetime.utcnow().isoformat()
        }


# Global manager instance
live_reporting_manager = LiveReportingManager()