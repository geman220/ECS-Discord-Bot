"""
Queue Health Monitor

Monitors Celery queue health and automatically cleans up problematic queues
to prevent the recurring clogging issues.
"""

import logging
from typing import Dict, Any, List
from datetime import datetime, timedelta

from celery import current_app as celery_app
from app.decorators import celery_task
from app.utils.task_session_manager import task_session
from app.services.redis_connection_service import get_redis_service
from app.utils.queue_monitor import queue_monitor

logger = logging.getLogger(__name__)


@celery_task(
    name='app.tasks.queue_health_monitor.monitor_and_cleanup_queues',
    queue='celery',
    max_retries=3,
    soft_time_limit=60,
    time_limit=90
)
def monitor_and_cleanup_queues(self, session) -> Dict[str, Any]:
    """
    Monitor queue health and automatically clean up problematic queues.
    
    This prevents the recurring issue where tasks build up faster than
    they can be processed, leading to queue clogging.
    """
    try:
        redis_service = get_redis_service()
        cleanup_actions = []
        
        # Check each critical queue
        queues_to_monitor = [
            'live_reporting',
            'discord', 
            'celery'
        ]
        
        # Use enhanced queue monitor for comprehensive health check
        health_check = queue_monitor.check_queue_health()

        # Log alerts
        for alert in health_check.get('alerts', []):
            if 'EMERGENCY' in alert:
                logger.critical(alert)
            elif 'CRITICAL' in alert:
                logger.error(alert)
            else:
                logger.warning(alert)

        # Add enhanced monitoring to legacy monitoring
        for queue_name in queues_to_monitor:
            queue_stats = _get_queue_stats(redis_service, queue_name)

            # Enhanced monitoring already handled critical cases
            # Only do additional cleanup for moderate cases
            if queue_stats['needs_cleanup'] and queue_stats['length'] < 100:
                cleanup_result = _cleanup_queue(redis_service, queue_name, queue_stats)
                cleanup_actions.append({
                    'queue': queue_name,
                    'before': queue_stats,
                    'cleanup': cleanup_result
                })
        
        # Check for stuck processing locks
        stuck_locks = _cleanup_stuck_locks(redis_service)
        
        if cleanup_actions or stuck_locks:
            logger.info(
                f"Queue cleanup completed: {len(cleanup_actions)} queues cleaned, "
                f"{stuck_locks} stuck locks cleared"
            )
        
        return {
            'success': True,
            'message': f'Enhanced monitoring: {len(health_check.get("actions_taken", []))} actions taken',
            'cleanup_actions': cleanup_actions,
            'stuck_locks_cleared': stuck_locks,
            'health_check': health_check,
            'queue_summary': queue_monitor.get_queue_summary()
        }
        
    except Exception as e:
        logger.error(f"Error monitoring queues: {e}", exc_info=True)
        raise self.retry(exc=e, countdown=60)


def _get_queue_stats(redis_service, queue_name: str) -> Dict[str, Any]:
    """Get queue statistics and determine if cleanup is needed."""
    try:
        # Get queue length from Redis
        queue_length = redis_service.llen(queue_name)
        
        # Count expired tasks (approximate by checking TTL)
        expired_count = 0
        if queue_length > 0:
            # Sample first 10 tasks to check for expired ones
            sample_size = min(10, queue_length)
            for i in range(sample_size):
                task_data = redis_service.lindex(queue_name, i)
                if task_data:
                    # Tasks that have been in queue too long are likely expired
                    # This is an approximation since we can't easily check individual TTLs
                    pass
        
        # Determine cleanup thresholds
        cleanup_threshold = {
            'live_reporting': 5,  # Should never have more than 2-3 tasks
            'discord': 20,
            'celery': 50
        }.get(queue_name, 30)
        
        needs_cleanup = queue_length > cleanup_threshold
        
        return {
            'length': queue_length,
            'expired_count': expired_count,
            'threshold': cleanup_threshold,
            'needs_cleanup': needs_cleanup
        }
        
    except Exception as e:
        logger.error(f"Error getting stats for queue {queue_name}: {e}")
        return {
            'length': 0,
            'expired_count': 0,
            'threshold': 0,
            'needs_cleanup': False
        }


def _cleanup_queue(redis_service, queue_name: str, stats: Dict[str, Any]) -> Dict[str, Any]:
    """Clean up a problematic queue."""
    try:
        initial_length = stats['length']
        
        # For live_reporting queue, be aggressive - it should be nearly empty
        if queue_name == 'live_reporting':
            # Keep only the 2 most recent tasks
            if initial_length > 2:
                # Remove oldest tasks, keep newest 2
                tasks_to_remove = initial_length - 2
                for _ in range(tasks_to_remove):
                    redis_service.lpop(queue_name)  # Remove from head (oldest)
                
                final_length = redis_service.llen(queue_name)
                removed_count = initial_length - final_length
                
                logger.info(f"Cleaned {queue_name}: removed {removed_count} old tasks")
                return {
                    'action': 'truncate',
                    'removed_count': removed_count,
                    'final_length': final_length
                }
        
        # For other queues, remove only very old tasks
        else:
            # This is more complex - for now just log the issue
            logger.warning(f"Queue {queue_name} has {initial_length} tasks - manual review needed")
            return {
                'action': 'logged',
                'removed_count': 0,
                'final_length': initial_length
            }
        
        return {'action': 'none', 'removed_count': 0, 'final_length': initial_length}
        
    except Exception as e:
        logger.error(f"Error cleaning queue {queue_name}: {e}")
        return {'action': 'error', 'error': str(e)}


def _cleanup_stuck_locks(redis_service) -> int:
    """
    Clean up the live-reporting processing lock if it is stuck without a TTL.

    This used to run THREE wildcard `KEYS` scans (live_reporting:*:processing,
    match_scheduler:*:reporting, match_scheduler:*:thread) on every pass, every 3
    minutes — 1,440 full-keyspace walks a day. Redis is single-threaded, and this
    instance is also the Celery broker, the result backend AND the Flask session
    store, so each scan BLOCKS every worker's BRPOP and every web greenlet's cache
    read for its duration. It is the reason this task showed up at 6.2s in the
    logs.

    The scans were redundant anyway: the match_scheduler keys are created with a
    2-day TTL (see match_scheduler.py), so Redis already expires them.

    Worse, the sweep was actively harmful. The TTL test below hardcoded a 24h
    assumption -- `ttl < (24*60*60 - 300)` is true for ANY key whose TTL is under
    ~23h55m, so it was DELETING still-valid scheduler markers roughly a day after
    they were set, for keys that were never stuck at all.

    What remains is the one lock that genuinely can hang without a TTL, checked
    with an O(1) EXISTS.
    """
    try:
        key = 'live_reporting:v2:processing_lock'

        if not redis_service.execute_command('exists', key):
            return 0

        ttl = redis_service.execute_command('ttl', key)

        # -1 means the key exists with NO expiry: nothing will ever clean it up,
        # so a crashed live-reporting run would block the next one forever. That
        # is the only case worth clearing. A key WITH a TTL is not stuck - it is
        # simply in use, and Redis will expire it on its own.
        if ttl == -1:
            logger.warning(f"Clearing stuck lock with no expiry: {key}")
            redis_service.execute_command('delete', key)
            return 1

        return 0

    except Exception as e:
        logger.error(f"Error cleaning stuck locks: {e}")
        return 0