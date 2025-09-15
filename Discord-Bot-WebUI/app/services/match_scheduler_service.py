# app/services/match_scheduler_service.py

"""
Enterprise Match Scheduler Service

Handles automated scheduling of:
- Discord thread creation (48 hours before match)
- Live reporting start/stop (5 minutes before/after)
- Season-wide batch scheduling
- Health monitoring and status tracking
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from sqlalchemy import and_, or_

from app.models import Match, LiveReportingSession, Schedule, Season, League
from app.services.redis_connection_service import get_redis_service
from app.utils.discord_request_handler import send_to_discord_bot
from app.core import celery
from app.decorators import celery_task
from app.utils.task_session_manager import task_session

logger = logging.getLogger(__name__)


class MatchSchedulerService:
    """
    Enterprise match scheduling service.

    Manages the entire lifecycle of match reporting:
    1. Thread creation (48h before)
    2. Live reporting start (5min before)
    3. Live reporting end (when match finishes)
    4. Status monitoring and health checks
    """

    def __init__(self):
        self.redis_service = get_redis_service()

    def schedule_season_matches(self, season_id: int) -> Dict[str, Any]:
        """
        Schedule all matches for an entire season.

        Creates Celery tasks for thread creation and live reporting
        for all matches in the season.
        """
        try:
            with task_session() as session:
                # Get season and matches
                season = session.query(Season).filter_by(id=season_id).first()
                if not season:
                    return {"success": False, "error": "Season not found"}

                matches = session.query(Match).join(Schedule).filter(
                    Schedule.season_id == season_id,
                    Match.date.isnot(None)
                ).all()

                scheduled_threads = 0
                scheduled_live = 0
                now = datetime.utcnow()

                for match in matches:
                    try:
                        # Schedule thread creation (48 hours before)
                        thread_time = match.date - timedelta(hours=48)
                        if thread_time > now:
                            create_match_thread_task.apply_async(
                                args=[match.id],
                                eta=thread_time,
                                expires=thread_time + timedelta(hours=2)
                            )
                            scheduled_threads += 1

                        # Schedule live reporting start (5 minutes before)
                        live_start_time = match.date - timedelta(minutes=5)
                        if live_start_time > now:
                            start_live_reporting_task.apply_async(
                                args=[match.id],
                                eta=live_start_time,
                                expires=live_start_time + timedelta(minutes=30)
                            )
                            scheduled_live += 1

                        # Schedule live reporting end (2 hours after start)
                        live_end_time = match.date + timedelta(hours=2)
                        if live_end_time > now:
                            stop_live_reporting_task.apply_async(
                                args=[match.id],
                                eta=live_end_time,
                                expires=live_end_time + timedelta(hours=1)
                            )

                    except Exception as e:
                        logger.error(f"Error scheduling match {match.id}: {e}")

                logger.info(f"Scheduled {scheduled_threads} threads and {scheduled_live} live sessions for season {season_id}")

                return {
                    "success": True,
                    "season_id": season_id,
                    "season_name": season.name,
                    "total_matches": len(matches),
                    "scheduled_threads": scheduled_threads,
                    "scheduled_live": scheduled_live
                }

        except Exception as e:
            logger.error(f"Error scheduling season {season_id}: {e}")
            return {"success": False, "error": str(e)}

    def get_scheduling_status(self, season_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Get status of scheduled matches and live reporting sessions.
        """
        try:
            with task_session() as session:
                now = datetime.utcnow()

                # Base query
                query = session.query(Match).join(Schedule)
                if season_id:
                    query = query.filter(Schedule.season_id == season_id)

                matches = query.filter(Match.date.isnot(None)).all()

                # Categorize matches
                upcoming_threads = []
                upcoming_live = []
                active_live = []
                completed = []

                for match in matches:
                    # Convert date to datetime for calculations
                    match_datetime = datetime.combine(match.date, datetime.min.time()) if match.date else None
                    if not match_datetime:
                        continue

                    thread_time = match_datetime - timedelta(hours=48)
                    live_start_time = match_datetime - timedelta(minutes=5)
                    live_end_time = match_datetime + timedelta(hours=2)

                    if now < thread_time:
                        upcoming_threads.append({
                            "match_id": match.id,
                            "home_team": match.home_team.name if match.home_team else "TBD",
                            "away_team": match.away_team.name if match.away_team else "TBD",
                            "match_date": match.date.isoformat(),
                            "thread_eta": thread_time.isoformat()
                        })
                    elif thread_time <= now < live_start_time:
                        upcoming_live.append({
                            "match_id": match.id,
                            "home_team": match.home_team.name if match.home_team else "TBD",
                            "away_team": match.away_team.name if match.away_team else "TBD",
                            "match_date": match.date.isoformat(),
                            "live_eta": live_start_time.isoformat()
                        })
                    elif live_start_time <= now < live_end_time:
                        # Check if actually has active session
                        active_session = session.query(LiveReportingSession).filter_by(
                            match_id=match.id,
                            is_active=True
                        ).first()

                        active_live.append({
                            "match_id": match.id,
                            "home_team": match.home_team.name if match.home_team else "TBD",
                            "away_team": match.away_team.name if match.away_team else "TBD",
                            "match_date": match.date.isoformat(),
                            "has_active_session": bool(active_session),
                            "session_id": active_session.id if active_session else None
                        })
                    else:
                        completed.append({
                            "match_id": match.id,
                            "home_team": match.home_team.name if match.home_team else "TBD",
                            "away_team": match.away_team.name if match.away_team else "TBD",
                            "match_date": match.date.isoformat()
                        })

                return {
                    "timestamp": now.isoformat(),
                    "season_id": season_id,
                    "upcoming_threads": upcoming_threads,
                    "upcoming_live": upcoming_live,
                    "active_live": active_live,
                    "completed": completed,
                    "counts": {
                        "upcoming_threads": len(upcoming_threads),
                        "upcoming_live": len(upcoming_live),
                        "active_live": len(active_live),
                        "completed": len(completed)
                    }
                }

        except Exception as e:
            logger.error(f"Error getting scheduling status: {e}")
            return {"error": str(e)}


# Singleton instance
match_scheduler_service = MatchSchedulerService()


# Celery Tasks
@celery_task(
    name='app.services.match_scheduler_service.create_match_thread_task',
    queue='discord',
    max_retries=3,
    soft_time_limit=60,
    time_limit=90
)
def create_match_thread_task(self, match_id: int, session) -> Dict[str, Any]:
    """
    Create Discord thread for a match (48 hours before kickoff).
    """
    try:
        # Get match details
        match = session.query(Match).filter_by(id=match_id).first()
        if not match:
            logger.error(f"Match {match_id} not found")
            return {"success": False, "error": "Match not found"}

        # Prepare thread creation request
        thread_request = {
            "channel_id": int(match.discord_channel_id) if match.discord_channel_id else None,
            "match_title": f"{match.home_team.name if match.home_team else 'TBD'} vs {match.away_team.name if match.away_team else 'TBD'}",
            "home_team": match.home_team.name if match.home_team else "TBD",
            "away_team": match.away_team.name if match.away_team else "TBD",
            "match_date": match.date.strftime("%B %d, %Y at %I:%M %p") if match.date else "TBD",
            "competition": match.schedule.season.league.name if match.schedule and match.schedule.season and match.schedule.season.league else "Unknown",
            "match_id": str(match_id)
        }

        if not thread_request["channel_id"]:
            logger.error(f"No Discord channel configured for match {match_id}")
            return {"success": False, "error": "No Discord channel configured"}

        # Call Discord bot API
        response = send_to_discord_bot('/api/live-reporting/thread/create', thread_request)

        if response and response.get('success'):
            # Store thread ID in match
            match.discord_thread_id = response.get('thread_id')
            session.commit()

            logger.info(f"Created thread {response.get('thread_id')} for match {match_id}")

            return {
                "success": True,
                "match_id": match_id,
                "thread_id": response.get('thread_id'),
                "thread_name": response.get('thread_name')
            }
        else:
            error_msg = response.get('error', 'Unknown error') if response else 'No response'
            logger.error(f"Failed to create thread for match {match_id}: {error_msg}")
            return {"success": False, "error": error_msg}

    except Exception as e:
        logger.error(f"Error creating thread for match {match_id}: {e}")
        return {"success": False, "error": str(e)}


@celery_task(
    name='app.services.match_scheduler_service.start_live_reporting_task',
    queue='live_reporting',
    max_retries=2,
    soft_time_limit=30,
    time_limit=45
)
def start_live_reporting_task(self, match_id: int, session) -> Dict[str, Any]:
    """
    Start live reporting for a match (5 minutes before kickoff).
    """
    try:
        # Get match details
        match = session.query(Match).filter_by(id=match_id).first()
        if not match:
            logger.error(f"Match {match_id} not found")
            return {"success": False, "error": "Match not found"}

        if not match.discord_thread_id:
            logger.error(f"No Discord thread for match {match_id}")
            return {"success": False, "error": "No Discord thread found"}

        # Check if live session already exists
        existing_session = session.query(LiveReportingSession).filter_by(
            match_id=match_id,
            is_active=True
        ).first()

        if existing_session:
            logger.info(f"Live session already exists for match {match_id}")
            return {
                "success": True,
                "match_id": match_id,
                "session_id": existing_session.id,
                "message": "Session already active"
            }

        # Create live reporting session
        live_session = LiveReportingSession(
            match_id=match_id,
            thread_id=match.discord_thread_id,
            competition=match.schedule.season.league.name if match.schedule and match.schedule.season and match.schedule.season.league else 'eng.1',
            is_active=True,
            created_at=datetime.utcnow(),
            last_update_at=datetime.utcnow(),
            update_count=0,
            error_count=0
        )

        session.add(live_session)
        session.commit()

        # Notify real-time service of new session (hybrid architecture)
        from app.services.realtime_bridge_service import notify_session_started
        bridge_result = notify_session_started(live_session.id, match_id, match.discord_thread_id)

        # Fallback to V2 system if real-time service not available
        if not bridge_result.get('success'):
            logger.warning("Real-time service unavailable, using V2 fallback")
            from app.tasks.tasks_live_reporting_v2 import process_all_active_sessions_v2
            process_all_active_sessions_v2.apply_async(countdown=10)

        logger.info(f"Started live reporting session {live_session.id} for match {match_id}")

        return {
            "success": True,
            "match_id": match_id,
            "session_id": live_session.id,
            "thread_id": match.discord_thread_id
        }

    except Exception as e:
        logger.error(f"Error starting live reporting for match {match_id}: {e}")
        return {"success": False, "error": str(e)}


@celery_task(
    name='app.services.match_scheduler_service.stop_live_reporting_task',
    queue='live_reporting',
    max_retries=1,
    soft_time_limit=30,
    time_limit=45
)
def stop_live_reporting_task(self, match_id: int, session) -> Dict[str, Any]:
    """
    Stop live reporting for a match (after match ends).
    """
    try:
        # Find active live session
        live_session = session.query(LiveReportingSession).filter_by(
            match_id=match_id,
            is_active=True
        ).first()

        if not live_session:
            logger.info(f"No active live session for match {match_id}")
            return {"success": True, "message": "No active session"}

        # Deactivate session
        live_session.is_active = False
        live_session.ended_at = datetime.utcnow()
        session.commit()

        # Notify real-time service of session stop
        from app.services.realtime_bridge_service import notify_session_stopped
        notify_session_stopped(live_session.id, match_id, "Scheduled stop")

        logger.info(f"Stopped live reporting session {live_session.id} for match {match_id}")

        return {
            "success": True,
            "match_id": match_id,
            "session_id": live_session.id,
            "message": "Live reporting stopped"
        }

    except Exception as e:
        logger.error(f"Error stopping live reporting for match {match_id}: {e}")
        return {"success": False, "error": str(e)}