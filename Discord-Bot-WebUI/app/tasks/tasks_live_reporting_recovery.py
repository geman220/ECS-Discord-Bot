"""
Live Reporting Recovery Task

This module ensures that matches that should be in live reporting
but aren't currently active get started. This catches any matches that
fall through the cracks due to timing issues or failures.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any

from celery import current_app as celery
from sqlalchemy.exc import SQLAlchemyError

from app.decorators import celery_task
from app.utils.task_session_manager import task_session
from app.models import MLSMatch
from app.models.live_reporting_session import LiveReportingSession

logger = logging.getLogger(__name__)


@celery_task(
    name='app.tasks.tasks_live_reporting_recovery.check_and_start_missing_live_reporting',
    queue='live_reporting',
    max_retries=3,
    soft_time_limit=180,  # 3 minutes soft timeout
    time_limit=300,       # 5 minutes hard timeout
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True
)
def check_and_start_missing_live_reporting(self, session) -> Dict[str, Any]:
    """
    Check for matches that should be in live reporting but aren't.
    
    This task catches matches that:
    - Are currently happening (within -5 min to +2 hours of start time)
    - Have a Discord thread created
    - Are NOT currently in live reporting
    - Don't have an active LiveReportingSession
    
    Returns:
        Dictionary with status and count of matches started
    """
    try:
        from datetime import timezone
        from app.tasks.tasks_live_reporting_v2 import start_live_reporting_v2
        
        now = datetime.now(timezone.utc)
        
        # Find matches that should be reporting now
        # (5 minutes before start to 2 hours after)
        reporting_window_start = now - timedelta(hours=2)
        reporting_window_end = now + timedelta(minutes=5)
        
        # Get matches in the reporting window
        matches_in_window = session.query(MLSMatch).filter(
            MLSMatch.date_time >= reporting_window_start,
            MLSMatch.date_time <= reporting_window_end,
            MLSMatch.discord_thread_id.isnot(None),  # Must have a thread
            MLSMatch.live_reporting_started == False  # Not marked as started
        ).all()
        
        started_count = 0
        skipped_count = 0
        
        for match in matches_in_window:
            # Check if match should be reporting (within window)
            match_start = match.date_time
            reporting_start = match_start - timedelta(minutes=5)
            reporting_end = match_start + timedelta(hours=2)
            
            if now < reporting_start or now > reporting_end:
                continue  # Outside reporting window
            
            # Check if there's already an active session
            existing_session = session.query(LiveReportingSession).filter(
                LiveReportingSession.match_id == str(match.match_id),
                LiveReportingSession.is_active == True
            ).first()
            
            if existing_session:
                logger.info(f"Match {match.match_id} already has active session {existing_session.id}")
                skipped_count += 1
                continue
            
            # Start live reporting immediately
            logger.warning(
                f"Match {match.match_id} ({match.home_team} vs {match.away_team}) "
                f"should be reporting but isn't - starting recovery"
            )
            
            try:
                task = start_live_reporting_v2.apply_async(
                    args=[
                        str(match.match_id),
                        str(match.discord_thread_id),
                        match.competition or 'usa.1'
                    ],
                    queue='live_reporting'
                )
                
                # Update match status
                match.live_reporting_scheduled = True
                match.live_reporting_started = True
                match.live_reporting_task_id = task.id
                match.live_reporting_status = 'active'
                
                started_count += 1
                logger.info(
                    f"Successfully started recovery live reporting for match {match.match_id} "
                    f"with task {task.id}"
                )
                
            except Exception as e:
                logger.error(
                    f"Failed to start recovery live reporting for match {match.match_id}: {e}",
                    exc_info=True
                )
        
        # Also check for orphaned sessions (active but match is way past)
        old_cutoff = now - timedelta(hours=4)
        orphaned_sessions = session.query(LiveReportingSession).filter(
            LiveReportingSession.is_active == True,
            LiveReportingSession.started_at < old_cutoff
        ).all()
        
        for orphan in orphaned_sessions:
            logger.warning(f"Deactivating orphaned session {orphan.id} for match {orphan.match_id}")
            orphan.is_active = False
            orphan.ended_at = now
            orphan.last_error = "Session orphaned - deactivated by recovery task"
        
        session.commit()
        
        return {
            'success': True,
            'message': f'Started {started_count} missing live reporting sessions',
            'started_count': started_count,
            'skipped_count': skipped_count,
            'orphaned_cleaned': len(orphaned_sessions)
        }
        
    except SQLAlchemyError as e:
        error_msg = str(e).lower()
        # Check for connection errors that should be retried with backoff
        if any(err in error_msg for err in [
            'server closed the connection',
            'server login has been failing',
            'discard all cannot run',
            'resourceclosederror'
        ]):
            logger.warning(f"Database connection error in live reporting recovery, retrying: {str(e)[:200]}")
            # Session rollback already handled by managed_session
            # Use exponential backoff
            countdown = min(60 * (2 ** self.request.retries), 300)
            raise self.retry(exc=e, countdown=countdown)
        else:
            logger.error(f"Database error in live reporting recovery: {str(e)}", exc_info=True)
            raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error in live reporting recovery: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)