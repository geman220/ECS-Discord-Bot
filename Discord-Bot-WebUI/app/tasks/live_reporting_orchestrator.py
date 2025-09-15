# app/tasks/live_reporting_orchestrator.py

"""
Live Reporting Event-Driven Orchestrator

[DEPRECATED - V2 Real-Time System Active]

WARNING: This orchestrator is deprecated in favor of V2 real-time system.
The V2 system (tasks_live_reporting_v2.py) provides:
- Real-time updates every 10-30 seconds for live matches
- Self-scheduling based on match status
- Direct ESPN API integration with caching
- Better error handling and recovery

This module is kept for reference but should not be used.
"""

import logging
from typing import Dict, Any
from datetime import datetime

from app.decorators import celery_task
from app.utils.task_session_manager import task_session
from app.services.live_reporting_manager import live_reporting_manager

logger = logging.getLogger(__name__)


@celery_task(
    name='app.tasks.live_reporting_orchestrator.orchestrate_live_reporting',
    queue='live_reporting',
    max_retries=2,
    soft_time_limit=30,
    time_limit=45
)
def orchestrate_live_reporting(self, session) -> Dict[str, Any]:
    """
    Event-driven orchestrator for live reporting.
    
    Intelligently processes active sessions with circuit breaker protection
    and backpressure management. Only runs when there are active sessions,
    preventing the task flooding that occurred with the cron-based approach.
    
    This replaces the problematic `process_all_active_sessions_v2` cron task
    that was running every 30 seconds regardless of active sessions.
    """
    task_id = self.request.id
    start_time = datetime.utcnow()
    
    logger.info(f"Starting live reporting orchestration: {task_id}")
    
    try:
        # Use the industry-standard manager with protection mechanisms
        stats = live_reporting_manager.process_active_sessions()
        
        # Log comprehensive statistics
        logger.info(
            f"Orchestration complete - "
            f"Sessions: {stats['total_sessions']}, "
            f"Scheduled: {stats['scheduled_tasks']}, "
            f"Circuit blocks: {stats['blocked_by_circuit_breaker']}, "
            f"Backpressure blocks: {stats['blocked_by_backpressure']}, "
            f"Circuit state: {stats['circuit_breaker_state']}, "
            f"Duration: {stats['processing_time']:.2f}s"
        )
        
        # Schedule next orchestration if there are still active sessions
        if stats['total_sessions'] > 0 and stats['scheduled_tasks'] > 0:
            # Dynamic scheduling based on activity
            delay = _calculate_next_run_delay(stats)
            orchestrate_live_reporting.apply_async(countdown=delay)
            logger.info(f"Scheduled next orchestration in {delay} seconds")
        else:
            logger.info("No active sessions or tasks blocked - not scheduling next run")
        
        return {
            'success': True,
            'task_id': task_id,
            'started_at': start_time.isoformat(),
            'completed_at': datetime.utcnow().isoformat(),
            **stats
        }
        
    except Exception as e:
        logger.error(f"Error in live reporting orchestration {task_id}: {e}", exc_info=True)
        
        # Schedule retry with backoff if there might be active sessions
        active_count = len(live_reporting_manager.get_active_sessions())
        if active_count > 0:
            # Exponential backoff for retries
            retry_delay = min(300, 30 * (self.request.retries + 1))  # Max 5 minutes
            orchestrate_live_reporting.apply_async(countdown=retry_delay)
            logger.info(f"Scheduled retry in {retry_delay} seconds due to error")
        
        return {
            'success': False,
            'task_id': task_id,
            'error': str(e),
            'started_at': start_time.isoformat(),
            'failed_at': datetime.utcnow().isoformat()
        }


def _calculate_next_run_delay(stats: Dict[str, Any]) -> int:
    """
    Calculate intelligent delay for next orchestration run.
    
    Dynamic scheduling based on system state and activity levels.
    """
    # Base delay for normal operation
    base_delay = 30
    
    # Adjust based on circuit breaker state
    if stats['circuit_breaker_state'] == 'open':
        # Circuit is open - wait longer before retry
        return min(300, base_delay * 4)  # Max 5 minutes
    elif stats['circuit_breaker_state'] == 'half_open':
        # Circuit is testing - be more conservative
        return base_delay * 2
    
    # Adjust for backpressure
    if stats['blocked_by_backpressure'] > 0:
        # System is under pressure - slow down
        backpressure_factor = min(3, 1 + stats['blocked_by_backpressure'] / 10)
        return int(base_delay * backpressure_factor)
    
    # Adjust for activity level
    if stats['total_sessions'] > 5:
        # High activity - shorter delays for responsiveness  
        return max(20, base_delay - 10)
    elif stats['total_sessions'] == 1:
        # Low activity - standard delay
        return base_delay
    
    return base_delay


@celery_task(
    name='app.tasks.live_reporting_orchestrator.health_check_live_reporting',
    queue='live_reporting',
    max_retries=1,
    soft_time_limit=15,
    time_limit=20
)
def health_check_live_reporting(self, session) -> Dict[str, Any]:
    """
    Health check task for live reporting system monitoring.
    
    Provides comprehensive system health information for monitoring
    and alerting systems.
    """
    try:
        health_data = live_reporting_manager.health_check()
        
        # Add task-specific information
        health_data.update({
            'task_id': self.request.id,
            'check_time': datetime.utcnow().isoformat(),
            'success': True
        })
        
        # Log health status
        logger.info(
            f"Health check - "
            f"Circuit: {health_data['circuit_breaker_state']}, "
            f"Queue: {health_data['queue_size']}/{health_data['max_queue_size']}, "
            f"Active sessions: {health_data['active_sessions']}"
        )
        
        return health_data
        
    except Exception as e:
        logger.error(f"Health check failed: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e),
            'task_id': self.request.id,
            'check_time': datetime.utcnow().isoformat()
        }


@celery_task(
    name='app.tasks.live_reporting_orchestrator.start_orchestration',
    queue='live_reporting',
    max_retries=1
)
def start_orchestration(self, session) -> Dict[str, Any]:
    """
    Start the event-driven orchestration system.
    
    This is triggered when a new live reporting session is created
    to ensure immediate processing begins.
    """
    try:
        logger.info("Starting live reporting orchestration system")
        
        # Check if orchestration is already running
        active_sessions = live_reporting_manager.get_active_sessions()
        if not active_sessions:
            logger.info("No active sessions found - orchestration not started")
            return {
                'success': True,
                'message': 'No active sessions - orchestration not needed'
            }
        
        # Start orchestration immediately
        task = orchestrate_live_reporting.apply_async()
        
        logger.info(f"Orchestration started with task ID: {task.id}")
        
        return {
            'success': True,
            'orchestration_task_id': task.id,
            'active_sessions': len(active_sessions),
            'message': 'Live reporting orchestration started'
        }
        
    except Exception as e:
        logger.error(f"Failed to start orchestration: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }