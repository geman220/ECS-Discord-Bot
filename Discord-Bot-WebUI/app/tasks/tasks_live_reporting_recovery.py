"""
Live Reporting Recovery Task (Enhanced with Database Tracking)

This module ensures that matches that should have tasks running don't fall through the cracks.
Uses database-backed task tracking to catch missed operations even when Redis expires.

Key improvements over V1:
- Database is source of truth (survives Redis TTL expiration)
- Catches tasks scheduled >2 days in advance
- Comprehensive logging for debugging
- Cleans up stale/expired tasks
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any

from celery import current_app as celery
from sqlalchemy.exc import SQLAlchemyError

from app.decorators import celery_task
from app.utils.task_session_manager import task_session
from app.models import MLSMatch, ScheduledTask, TaskType, TaskState, MatchStatus
from app.models.live_reporting_session import LiveReportingSession

logger = logging.getLogger(__name__)


@celery_task(
    name='app.tasks.tasks_live_reporting_recovery.recover_missing_tasks',
    queue='monitoring',
    max_retries=1,
    soft_time_limit=120,  # 2 minutes
    time_limit=180,       # 3 minutes
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,
    autoretry_for=(Exception,),
    default_retry_delay=60
)
def recover_missing_tasks(self, session) -> Dict[str, Any]:
    """
    Enhanced recovery task using database-backed task tracking.

    Recovers:
    1. Thread creations that were scheduled but never executed
    2. Live reporting sessions that should have started but didn't
    3. Cleans up expired tasks

    Returns:
        Dictionary with recovery statistics
    """
    try:
        from datetime import timezone
        from app.tasks.match_scheduler import (
            create_mls_match_thread_task,
            start_mls_live_reporting_task
        )
        from app.utils.safe_redis import get_safe_redis

        # Prevent duplicate execution using Redis lock
        redis_client = get_safe_redis()
        lock_key = "task_lock:recover_missing_tasks"
        lock_acquired = False

        if redis_client and redis_client.is_available:
            lock_acquired = redis_client.set(lock_key, self.request.id, nx=True, ex=240)
            if not lock_acquired:
                logger.info("Another recovery instance is running, skipping")
                return {
                    'success': True,
                    'message': 'Skipped - another instance running',
                    'recovered': 0
                }

        try:
            now = datetime.now(timezone.utc)
            recovered_threads = 0
            recovered_reporting = 0
            expired_tasks = 0

            logger.info("=" * 70)
            logger.info(f"🔍 Starting task recovery at {now.isoformat()}")
            logger.info("=" * 70)

            # ===================================================================
            # STEP 1: Recover thread creation tasks that are overdue
            # ===================================================================
            logger.info("\n📋 Step 1: Checking for missing thread creations...")

            pending_thread_tasks = ScheduledTask.get_pending_tasks(
                session,
                task_type=TaskType.THREAD_CREATION,
                now=now
            )

            logger.info(f"Found {len(pending_thread_tasks)} overdue thread creation tasks")

            for task in pending_thread_tasks:
                try:
                    match = session.query(MLSMatch).get(task.match_id)
                    if not match:
                        logger.warning(f"Task {task.id}: Match {task.match_id} not found, marking expired")
                        task.mark_expired()
                        continue

                    if match.thread_created:
                        logger.info(f"Task {task.id}: Thread already created for match {task.match_id}, marking completed")
                        task.mark_completed()
                        continue

                    # Check if thread creation time is way overdue (>6 hours)
                    overdue_duration = now - task.scheduled_time
                    if overdue_duration > timedelta(hours=6):
                        logger.warning(f"Task {task.id}: Thread creation for match {task.match_id} is {overdue_duration} overdue, marking expired")
                        task.mark_expired()
                        expired_tasks += 1
                        continue

                    # Recover: create thread immediately
                    logger.warning(f"🔧 RECOVERING: Thread creation for match {task.match_id} ({match.opponent})")
                    logger.warning(f"   Scheduled: {task.scheduled_time.isoformat()}, Overdue by: {overdue_duration}")

                    celery_task = create_mls_match_thread_task.apply_async(args=[match.id])
                    task.mark_running(celery_task.id)
                    recovered_threads += 1

                    logger.info(f"   ✅ Rescheduled with task_id: {celery_task.id}")

                except Exception as e:
                    logger.error(f"Error recovering thread task {task.id}: {e}", exc_info=True)
                    task.mark_failed(str(e))

            # ===================================================================
            # STEP 2: Recover live reporting tasks that are overdue
            # ===================================================================
            logger.info("\n📺 Step 2: Checking for missing live reporting sessions...")

            pending_reporting_tasks = ScheduledTask.get_pending_tasks(
                session,
                task_type=TaskType.LIVE_REPORTING_START,
                now=now
            )

            logger.info(f"Found {len(pending_reporting_tasks)} overdue live reporting tasks")

            for task in pending_reporting_tasks:
                try:
                    match = session.query(MLSMatch).get(task.match_id)
                    if not match:
                        logger.warning(f"Task {task.id}: Match {task.match_id} not found, marking expired")
                        task.mark_expired()
                        continue

                    if not match.thread_created or not match.discord_thread_id:
                        logger.warning(f"Task {task.id}: Match {task.match_id} has no thread, marking expired")
                        task.mark_expired()
                        expired_tasks += 1
                        continue

                    # Check if session already exists
                    existing_session = session.query(LiveReportingSession).filter(
                        LiveReportingSession.match_id == str(match.match_id),
                        LiveReportingSession.is_active == True
                    ).first()

                    if existing_session:
                        logger.info(f"Task {task.id}: Live session already exists for match {task.match_id}, marking completed")
                        task.mark_completed()
                        continue

                    # Check if match has already finished (>3 hours past start)
                    match_age = now - match.date_time
                    if match_age > timedelta(hours=3):
                        logger.warning(f"Task {task.id}: Match {task.match_id} finished {match_age} ago, marking expired")
                        task.mark_expired()
                        expired_tasks += 1
                        continue

                    # Recover: start live reporting immediately
                    overdue_duration = now - task.scheduled_time
                    logger.warning(f"🔧 RECOVERING: Live reporting for match {task.match_id} ({match.opponent})")
                    logger.warning(f"   Scheduled: {task.scheduled_time.isoformat()}, Overdue by: {overdue_duration}")

                    celery_task = start_mls_live_reporting_task.apply_async(args=[match.id])
                    task.mark_running(celery_task.id)
                    match.live_reporting_status = MatchStatus.RUNNING
                    recovered_reporting += 1

                    logger.info(f"   ✅ Rescheduled with task_id: {celery_task.id}")

                except Exception as e:
                    logger.error(f"Error recovering reporting task {task.id}: {e}", exc_info=True)
                    task.mark_failed(str(e))

            # ===================================================================
            # STEP 3: Clean up very old expired tasks (>7 days overdue)
            # ===================================================================
            logger.info("\n🧹 Step 3: Cleaning up very old tasks...")

            expiry_cutoff = now - timedelta(days=7)
            very_old_tasks = session.query(ScheduledTask).filter(
                ScheduledTask.state == TaskState.SCHEDULED,
                ScheduledTask.scheduled_time < expiry_cutoff
            ).all()

            logger.info(f"Found {len(very_old_tasks)} very old tasks to expire")

            for task in very_old_tasks:
                task.mark_expired()
                expired_tasks += 1
                logger.debug(f"Expired task {task.id} (scheduled {task.scheduled_time.isoformat()})")

            # ===================================================================
            # STEP 4: Mark old "not_started" matches as completed
            # ===================================================================
            logger.info("\n🏁 Step 4: Marking old not_started matches as completed...")

            completed_old_matches = 0
            old_match_cutoff = now - timedelta(hours=6)

            old_not_started_matches = session.query(MLSMatch).filter(
                MLSMatch.live_reporting_status == MatchStatus.NOT_STARTED,
                MLSMatch.date_time < old_match_cutoff
            ).all()

            logger.info(f"Found {len(old_not_started_matches)} old not_started matches")

            for match in old_not_started_matches:
                match.live_reporting_status = MatchStatus.COMPLETED
                completed_old_matches += 1
                logger.info(f"Marked old match {match.id} ({match.opponent}) as completed")

            # Commit all changes
            session.commit()

            # ===================================================================
            # Summary
            # ===================================================================
            logger.info("\n" + "=" * 70)
            logger.info("📊 Recovery Summary")
            logger.info("=" * 70)
            logger.info(f"   Threads recovered: {recovered_threads}")
            logger.info(f"   Reporting recovered: {recovered_reporting}")
            logger.info(f"   Tasks expired: {expired_tasks}")
            logger.info(f"   Old matches marked completed: {completed_old_matches}")
            logger.info("=" * 70)

            return {
                'success': True,
                'timestamp': now.isoformat(),
                'recovered_threads': recovered_threads,
                'recovered_reporting': recovered_reporting,
                'expired_tasks': expired_tasks,
                'completed_old_matches': completed_old_matches,
                'total_recovered': recovered_threads + recovered_reporting + completed_old_matches
            }

        finally:
            # Release Redis lock
            if redis_client and redis_client.is_available and lock_acquired:
                redis_client.delete(lock_key)

    except SQLAlchemyError as e:
        logger.error(f"Database error in recovery task: {e}", exc_info=True)
        session.rollback()
        return {
            'success': False,
            'error': str(e),
            'error_type': 'database'
        }

    except Exception as e:
        logger.error(f"Unexpected error in recovery task: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e),
            'error_type': 'general'
        }


# Keep the old function name for backward compatibility
check_and_start_missing_live_reporting = recover_missing_tasks
