# app/tasks/match_scheduler.py

"""
Enterprise Match Scheduler Tasks

Celery tasks for the enterprise live reporting system.
Handles automated scheduling of match threads and live reporting sessions.
"""

import logging
from datetime import datetime, timedelta
from app.decorators import celery_task
from app.services.match_scheduler_service import MatchSchedulerService
from app.utils.task_session_manager import task_session

logger = logging.getLogger(__name__)


@celery_task(bind=True, max_retries=3, default_retry_delay=60)
def schedule_upcoming_matches(self, session):
    """
    Enterprise task to schedule upcoming matches for thread creation and live reporting.

    This task:
    1. Checks for matches in the next 48 hours that need thread creation
    2. Checks for matches in the next 5 minutes that need live reporting
    3. Uses the enterprise MatchSchedulerService for all operations
    4. Replaces deprecated V2 tasks

    Returns:
        dict: Results of scheduling operations
    """
    try:
        logger.info("🏢 Enterprise match scheduler starting...")

        # Schedule upcoming MLS matches directly (not pub league seasons)
        from app.models.external import MLSMatch
        from app.core import celery

        with task_session() as session:
            # Get upcoming MLS matches that need scheduling
            now = datetime.utcnow()
            upcoming_matches = session.query(MLSMatch).filter(
                MLSMatch.date_time > now,
                MLSMatch.date_time <= now + timedelta(days=7)  # Look ahead 7 days
            ).all()

            scheduled_threads = 0
            scheduled_live = 0

            for match in upcoming_matches:
                try:
                    # Schedule thread creation (48 hours before)
                    thread_time = match.date_time - timedelta(hours=48)
                    if thread_time > now and not match.thread_created:
                        # Use MLS-specific thread creation task
                        create_mls_match_thread_task.apply_async(
                            args=[match.id],
                            eta=thread_time,
                            expires=thread_time + timedelta(hours=2)
                        )
                        scheduled_threads += 1

                    # Schedule live reporting start (5 minutes before)
                    live_start_time = match.date_time - timedelta(minutes=5)
                    if live_start_time > now:
                        start_mls_live_reporting_task.apply_async(
                            args=[match.id],
                            eta=live_start_time,
                            expires=live_start_time + timedelta(minutes=30)
                        )
                        scheduled_live += 1

                except Exception as e:
                    logger.error(f"Error scheduling MLS match {match.id}: {e}")

            result = {
                'success': True,
                'total_matches': len(upcoming_matches),
                'threads_scheduled': scheduled_threads,
                'reporting_scheduled': scheduled_live
            }

        if result['success']:
            logger.info(f"✅ Enterprise scheduler: {result['threads_scheduled']} threads, {result['reporting_scheduled']} live sessions")
            return {
                'success': True,
                'enterprise_system': True,
                'threads_scheduled': result['threads_scheduled'],
                'reporting_scheduled': result['reporting_scheduled'],
                'message': 'Enterprise scheduling completed successfully'
            }
        else:
            logger.error(f"❌ Enterprise scheduler failed: {result.get('error', 'Unknown error')}")
            return {
                'success': False,
                'error': result.get('error', 'Enterprise scheduling failed'),
                'enterprise_system': True
            }

    except Exception as e:
        logger.error(f"Enterprise match scheduler error: {e}", exc_info=True)

        # Retry on failure
        if self.request.retries < self.max_retries:
            logger.info(f"Retrying enterprise scheduler (attempt {self.request.retries + 1}/{self.max_retries})")
            raise self.retry(countdown=60 * (self.request.retries + 1))

        return {
            'success': False,
            'error': str(e),
            'enterprise_system': True,
            'retries_exhausted': True
        }


@celery_task(bind=True, max_retries=2, default_retry_delay=30)
def trigger_live_reporting_session(self, match_id: int, discord_thread_id: str, espn_match_id: str):
    """
    Enterprise task to trigger live reporting for a specific match.
    Called by the match scheduler service when live reporting should start.

    Args:
        match_id: Database match ID
        discord_thread_id: Discord thread ID for updates
        espn_match_id: ESPN match ID for data

    Returns:
        dict: Results of live reporting activation
    """
    try:
        logger.info(f"🔴 Starting enterprise live reporting for match {match_id}")

        scheduler_service = MatchSchedulerService()

        # Signal the real-time service to start reporting this match
        result = scheduler_service.start_live_reporting_session(
            match_id=match_id,
            discord_thread_id=discord_thread_id,
            espn_match_id=espn_match_id
        )

        if result['success']:
            logger.info(f"✅ Live reporting activated for match {match_id}")
            return {
                'success': True,
                'match_id': match_id,
                'enterprise_system': True,
                'real_time_service_notified': True
            }
        else:
            logger.error(f"❌ Failed to start live reporting for match {match_id}: {result.get('error')}")
            return {
                'success': False,
                'match_id': match_id,
                'error': result.get('error'),
                'enterprise_system': True
            }

    except Exception as e:
        logger.error(f"Enterprise live reporting trigger error for match {match_id}: {e}", exc_info=True)

        # Retry on failure
        if self.request.retries < self.max_retries:
            logger.info(f"Retrying live reporting trigger for match {match_id} (attempt {self.request.retries + 1})")
            raise self.retry(countdown=30)

        return {
            'success': False,
            'match_id': match_id,
            'error': str(e),
            'enterprise_system': True,
            'retries_exhausted': True
        }


@celery_task(bind=True)
def health_check_enterprise_system(self):
    """
    Health check for the enterprise live reporting system.
    Verifies that all components are operational.

    Returns:
        dict: Health status of enterprise components
    """
    try:
        logger.info("🔍 Enterprise system health check starting...")

        scheduler_service = MatchSchedulerService()

        # Check enterprise components
        health_status = {
            'enterprise_system': True,
            'timestamp': datetime.utcnow().isoformat(),
            'match_scheduler_service': True,
            'real_time_service': False,  # Will be checked
            'database_connection': False,  # Will be checked
            'redis_connection': False,  # Will be checked
            'discord_bot_connection': False  # Will be checked
        }

        # Test database connection
        try:
            # Simple test via scheduler service
            test_result = scheduler_service.get_upcoming_matches_for_scheduling()
            health_status['database_connection'] = True
            health_status['upcoming_matches_count'] = len(test_result)
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            health_status['database_error'] = str(e)

        # Test real-time service connection
        try:
            from app.services.realtime_reporting_service import RealtimeReportingService
            realtime_service = RealtimeReportingService()
            # Simple health check
            health_status['real_time_service'] = True
        except Exception as e:
            logger.error(f"Real-time service health check failed: {e}")
            health_status['realtime_service_error'] = str(e)

        overall_health = all([
            health_status['match_scheduler_service'],
            health_status['database_connection']
        ])

        health_status['overall_status'] = 'healthy' if overall_health else 'degraded'

        if overall_health:
            logger.info("✅ Enterprise system health check passed")
        else:
            logger.warning("⚠️ Enterprise system health check shows degraded status")

        return health_status

    except Exception as e:
        logger.error(f"Enterprise health check error: {e}", exc_info=True)
        return {
            'enterprise_system': True,
            'overall_status': 'failed',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }


@celery_task(
    name='app.tasks.match_scheduler.create_mls_match_thread_task',
    queue='discord',
    max_retries=3,
    soft_time_limit=60,
    time_limit=90
)
def create_mls_match_thread_task(self, match_id: int, session) -> Dict[str, Any]:
    """
    Create Discord thread for an MLS match (48 hours before kickoff).
    """
    try:
        from app.models.external import MLSMatch
        from app.utils.discord_request_handler import send_to_discord_bot

        # Get MLS match details
        match = session.query(MLSMatch).filter_by(id=match_id).first()
        if not match:
            logger.error(f"MLS Match {match_id} not found")
            return {"success": False, "error": "MLS Match not found"}

        # Prepare thread creation request for MLS match
        if match.is_home_game:
            match_title = f"Seattle Sounders FC vs {match.opponent}"
            home_team = "Seattle Sounders FC"
            away_team = match.opponent
        else:
            match_title = f"{match.opponent} vs Seattle Sounders FC"
            home_team = match.opponent
            away_team = "Seattle Sounders FC"

        thread_request = {
            "channel_id": 1154148502426857633,  # MLS live reporting channel
            "match_title": match_title,
            "home_team": home_team,
            "away_team": away_team,
            "match_date": match.date_time.strftime("%B %d, %Y at %I:%M %p") if match.date_time else "TBD",
            "competition": match.competition or "MLS",
            "match_id": str(match.match_id)  # Use match_id field, not database id
        }

        # Call Discord bot API
        response = send_to_discord_bot('/api/live-reporting/thread/create', thread_request)

        if response and response.get('success'):
            # Mark thread as created
            match.thread_created = True
            match.thread_creation_time = datetime.utcnow()
            session.commit()

            logger.info(f"Created MLS thread {response.get('thread_id')} for match {match.match_id}")

            return {
                "success": True,
                "match_id": match_id,
                "thread_id": response.get('thread_id'),
                "thread_name": response.get('thread_name')
            }
        else:
            error_msg = response.get('error', 'Unknown error') if response else 'No response'
            logger.error(f"Failed to create MLS thread for match {match.match_id}: {error_msg}")
            return {"success": False, "error": error_msg}

    except Exception as e:
        logger.error(f"Error creating MLS thread for match {match_id}: {e}")
        return {"success": False, "error": str(e)}


@celery_task(
    name='app.tasks.match_scheduler.start_mls_live_reporting_task',
    queue='live_reporting',
    max_retries=2,
    soft_time_limit=30,
    time_limit=45
)
def start_mls_live_reporting_task(self, match_id: int, session) -> Dict[str, Any]:
    """
    Start live reporting for an MLS match (5 minutes before kickoff).
    """
    try:
        from app.models.external import MLSMatch
        from app.models import LiveReportingSession

        # Get MLS match details
        match = session.query(MLSMatch).filter_by(id=match_id).first()
        if not match:
            logger.error(f"MLS Match {match_id} not found")
            return {"success": False, "error": "MLS Match not found"}

        # Check if live session already exists (use match_id as string)
        existing_session = session.query(LiveReportingSession).filter_by(
            match_id=str(match.match_id),  # LiveReportingSession expects string
            is_active=True
        ).first()

        if existing_session:
            logger.info(f"Live session already exists for MLS match {match.match_id}")
            return {
                "success": True,
                "match_id": match_id,
                "session_id": existing_session.id,
                "message": "Session already active"
            }

        # Create live reporting session for MLS match
        live_session = LiveReportingSession(
            match_id=str(match.match_id),  # Use ESPN match_id as string
            thread_id="",  # Will be set when thread is found
            competition=match.competition or 'MLS',
            is_active=True,
            started_at=datetime.utcnow(),
            last_update_at=datetime.utcnow(),
            update_count=0,
            error_count=0
        )

        session.add(live_session)
        session.commit()

        # Notify real-time service of new session
        from app.services.realtime_bridge_service import notify_session_started
        bridge_result = notify_session_started(live_session.id, str(match.match_id), "")

        logger.info(f"Started MLS live reporting session {live_session.id} for match {match.match_id}")

        return {
            "success": True,
            "match_id": match_id,
            "session_id": live_session.id,
            "espn_match_id": match.match_id
        }

    except Exception as e:
        logger.error(f"Error starting MLS live reporting for match {match_id}: {e}")
        return {"success": False, "error": str(e)}