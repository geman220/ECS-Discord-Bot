"""
Emergency Recovery Tasks

Last-resort automated recovery mechanisms for when the system gets into trouble.
"""

import logging
from typing import Dict, Any
from datetime import datetime, timedelta

from app.decorators import celery_task
from app.utils.queue_monitor import queue_monitor
from app.services.redis_connection_service import get_redis_service
from app.utils.task_session_manager import task_session

logger = logging.getLogger(__name__)


@celery_task(
    name='app.tasks.emergency_recovery.emergency_queue_recovery',
    queue='celery',
    max_retries=1,
    soft_time_limit=90,
    time_limit=120
)
def emergency_queue_recovery(self, session) -> Dict[str, Any]:
    """
    Emergency recovery task - only runs when queues are severely backed up.

    This is a last-resort mechanism that should rarely trigger.
    """
    try:
        logger.warning("Emergency queue recovery initiated")

        redis_service = get_redis_service()
        recovery_actions = []

        # Check if we're in a true emergency state
        queue_summary = queue_monitor.get_queue_summary()
        total_tasks = queue_summary['total_tasks']

        # Emergency thresholds
        EMERGENCY_TOTAL_THRESHOLD = 1000  # Total tasks across all queues
        INDIVIDUAL_EMERGENCY_THRESHOLDS = {
            'celery': 500,
            'live_reporting': 100,
            'discord': 400
        }

        emergency_state = (
            total_tasks > EMERGENCY_TOTAL_THRESHOLD or
            any(
                queue_summary['queues'].get(q, 0) > threshold
                for q, threshold in INDIVIDUAL_EMERGENCY_THRESHOLDS.items()
            )
        )

        if not emergency_state:
            logger.info("No emergency state detected, skipping emergency recovery")
            return {
                'success': True,
                'message': 'No emergency recovery needed',
                'total_tasks': total_tasks,
                'emergency_triggered': False
            }

        logger.critical(f"EMERGENCY STATE: {total_tasks} total tasks detected - initiating recovery")

        # Emergency Recovery Actions

        # 1. Clear expired beat locks that might be causing duplicate scheduling
        beat_locks_cleared = _clear_beat_locks(redis_service)
        if beat_locks_cleared:
            recovery_actions.append(f"Cleared {beat_locks_cleared} beat locks")

        # 2. Clear stuck worker locks
        worker_locks_cleared = _clear_worker_locks(redis_service)
        if worker_locks_cleared:
            recovery_actions.append(f"Cleared {worker_locks_cleared} worker locks")

        # 3. Force queue cleanup through monitor
        health_check = queue_monitor.check_queue_health()
        emergency_cleanups = len(health_check.get('actions_taken', []))
        if emergency_cleanups:
            recovery_actions.append(f"Emergency cleanups: {emergency_cleanups}")

        # 4. Clear any Redis keys that might be causing issues
        problem_keys_cleared = _clear_problem_keys(redis_service)
        if problem_keys_cleared:
            recovery_actions.append(f"Cleared {problem_keys_cleared} problem keys")

        # Final check
        final_summary = queue_monitor.get_queue_summary()
        final_total = final_summary['total_tasks']
        reduction = total_tasks - final_total

        logger.critical(
            f"Emergency recovery completed: "
            f"Reduced from {total_tasks} to {final_total} tasks "
            f"({reduction} tasks removed)"
        )

        return {
            'success': True,
            'emergency_triggered': True,
            'before_total': total_tasks,
            'after_total': final_total,
            'tasks_removed': reduction,
            'recovery_actions': recovery_actions,
            'health_check': health_check,
            'timestamp': datetime.utcnow().isoformat()
        }

    except Exception as e:
        logger.error(f"Error in emergency recovery: {e}", exc_info=True)
        raise self.retry(exc=e, countdown=300)  # Wait 5 minutes before retry


def _clear_beat_locks(redis_service) -> int:
    """Clear expired Celery beat locks that might cause duplicate scheduling."""
    try:
        # Look for celery beat locks
        beat_keys = redis_service.execute_command('KEYS', 'celery-beat-lock*')
        cleared = 0

        for key in beat_keys:
            try:
                # Check if lock is old (more than 10 minutes)
                ttl = redis_service.execute_command('TTL', key)
                if ttl == -1 or ttl > 600:  # No expiry or more than 10 minutes
                    redis_service.execute_command('DEL', key)
                    cleared += 1
                    logger.info(f"Cleared beat lock: {key}")
            except Exception as e:
                logger.warning(f"Could not clear beat lock {key}: {e}")

        return cleared

    except Exception as e:
        logger.error(f"Error clearing beat locks: {e}")
        return 0


def _clear_worker_locks(redis_service) -> int:
    """Clear stuck worker locks."""
    try:
        # Look for worker-related locks
        worker_patterns = ['*worker*lock*', '*celery*lock*']
        cleared = 0

        for pattern in worker_patterns:
            keys = redis_service.execute_command('KEYS', pattern)
            for key in keys:
                try:
                    # Check if lock is old
                    ttl = redis_service.execute_command('TTL', key)
                    if ttl == -1 or ttl > 300:  # No expiry or more than 5 minutes
                        redis_service.execute_command('DEL', key)
                        cleared += 1
                        logger.info(f"Cleared worker lock: {key}")
                except Exception as e:
                    logger.warning(f"Could not clear worker lock {key}: {e}")

        return cleared

    except Exception as e:
        logger.error(f"Error clearing worker locks: {e}")
        return 0


def _clear_problem_keys(redis_service) -> int:
    """Clear Redis keys that might be causing issues."""
    try:
        cleared = 0

        # Clear old task results that might be accumulating
        result_keys = redis_service.execute_command('KEYS', 'celery-task-meta-*')
        old_threshold = datetime.utcnow() - timedelta(hours=2)

        for key in result_keys[:100]:  # Limit to 100 to avoid timeout
            try:
                # Get creation time approximation from key expiry
                ttl = redis_service.execute_command('TTL', key)
                if ttl == -1 or ttl > 7200:  # No expiry or more than 2 hours
                    redis_service.execute_command('DEL', key)
                    cleared += 1
            except:
                pass  # Skip problematic keys

        return cleared

    except Exception as e:
        logger.error(f"Error clearing problem keys: {e}")
        return 0