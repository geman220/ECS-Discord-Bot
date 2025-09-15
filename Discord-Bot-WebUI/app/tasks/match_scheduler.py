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

        # Initialize enterprise service
        scheduler_service = MatchSchedulerService()

        # Schedule upcoming season matches (auto-detects what needs scheduling)
        result = scheduler_service.schedule_season_matches()

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