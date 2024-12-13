# app/tasks/tasks_live_reporting.py

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
import asyncio
from concurrent.futures import ThreadPoolExecutor
from flask import current_app
from sqlalchemy.exc import SQLAlchemyError
from app.core import socketio
from app.decorators import celery_task, async_task
from app.models import MLSMatch
from app.match_api import process_live_match_updates
from app.discord_utils import create_match_thread
from app.api_utils import fetch_espn_data

logger = logging.getLogger(__name__)

@celery_task(
    name='app.tasks.tasks_live_reporting.process_match_update',
    bind=True,
    queue='live_reporting',
    max_retries=3
)
def process_match_update(self, session, match_id: str, thread_id: str, competition: str,
                         last_status: Optional[str] = None,
                         last_score: Optional[str] = None,
                         last_event_keys: Optional[list] = None) -> Dict[str, Any]:
    """Process a single match update iteration."""
    try:
        logger.info(f"Processing update for match {match_id}")

        match = session.query(MLSMatch).filter_by(match_id=match_id).first()
        if not match:
            logger.error(f"Match {match_id} not found")
            return {'success': False, 'message': 'Match not found'}

        if match.live_reporting_status != 'running':
            logger.error(f"Match {match_id} not in running state")
            return {'success': False, 'message': 'Match not in running state'}

        last_event_keys = last_event_keys or []

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            full_url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{competition}/scoreboard/{match_id}"
            match_data = loop.run_until_complete(fetch_espn_data(full_url=full_url))

            if not match_data:
                logger.error(f"Failed to fetch data for match {match_id}")
                return {'success': False, 'message': 'Failed to fetch match data'}

            # Process live updates
            match_ended, current_event_keys = loop.run_until_complete(
                process_live_match_updates(
                    match_id=str(match_id),
                    thread_id=thread_id,
                    match_data=match_data,
                    last_status=last_status,
                    last_score=last_score,
                    last_event_keys=last_event_keys
                )
            )
        finally:
            loop.close()

        if match_ended:
            logger.info(f"Match {match_id} has ended")
            match = session.query(MLSMatch).filter_by(match_id=match_id).first()
            if match:
                match.live_reporting_status = 'completed'
                match.live_reporting_started = False
            return {'success': True, 'message': 'Match ended', 'status': 'completed'}

        # Extract new status and score
        new_status = match_data["competitions"][0]["status"]["type"]["name"]
        home_score = match_data['competitions'][0]['competitors'][0]['score']
        away_score = match_data['competitions'][0]['competitors'][1]['score']
        new_score = f"{home_score}-{away_score}"

        # Update match info in DB
        match = session.query(MLSMatch).filter_by(match_id=match_id).first()
        if match:
            match.current_status = new_status
            match.current_score = new_score
            match.last_update_time = datetime.utcnow()

        self.apply_async(
            args=[match_id, thread_id, competition],
            kwargs={
                'last_status': new_status,
                'last_score': new_score,
                'last_event_keys': current_event_keys
            },
            countdown=30,
            queue='live_reporting'
        )

        return {
            'success': True,
            'message': 'Update processed',
            'status': 'running',
            'score': new_score,
            'match_status': new_status
        }

    except SQLAlchemyError as e:
        logger.error(f"Database error in process_match_update: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error in process_match_update: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)

@celery_task(
    name='app.tasks.tasks_live_reporting.start_live_reporting',
    bind=True,
    queue='live_reporting',
    max_retries=3
)
def start_live_reporting(self, session, match_id: str) -> Dict[str, Any]:
    """Start live match reporting."""
    try:
        logger.info(f"Starting live reporting for match_id: {match_id}")

        match = session.query(MLSMatch).filter_by(match_id=match_id).first()
        if not match:
            logger.error(f"Match {match_id} not found")
            return {'success': False, 'message': f'Match {match_id} not found'}

        if match.live_reporting_status == 'running':
            return {'success': False, 'message': 'Live reporting already running'}

        match.live_reporting_started = True
        match.live_reporting_status = 'running'
        match.reporting_start_time = datetime.utcnow()

        match_data = {
            'match_id': match.match_id,
            'thread_id': match.discord_thread_id,
            'competition': match.competition
        }

        logger.info(f"Updated match status to running for {match_id}")

        # Schedule the first update
        process_match_update.delay(
            match_id=str(match_data['match_id']),
            thread_id=str(match_data['thread_id']),
            competition=match_data['competition'],
            last_status=None,
            last_score=None,
            last_event_keys=[]
        )

        return {
            'success': True,
            'message': 'Live reporting started successfully',
            'match_id': match_data['match_id'],
            'thread_id': match_data['thread_id'],
            'status': 'running'
        }

    except SQLAlchemyError as e:
        logger.error(f"Database error in start_live_reporting: {str(e)}", exc_info=True)
        # Attempt to update match status on error
        try:
            # create a fresh session to update match on error if needed
            app = current_app._get_current_object()
            error_session = app.SessionLocal()
            match = error_session.query(MLSMatch).filter_by(match_id=match_id).first()
            if match:
                match.live_reporting_status = 'failed'
                match.live_reporting_started = False
            error_session.commit()
            error_session.close()
        except Exception as inner_e:
            logger.error(f"Error updating match status on failure: {str(inner_e)}")
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error in start_live_reporting: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)

@celery_task(
    name='app.tasks.tasks_live_reporting.schedule_live_reporting',
    bind=True,
    queue='live_reporting',
    max_retries=3
)
def schedule_live_reporting(self, session) -> Dict[str, Any]:
    """Schedule live reporting for upcoming matches."""
    try:
        now = datetime.utcnow()
        upcoming_matches = session.query(MLSMatch).filter(
            MLSMatch.date_time >= now,
            MLSMatch.date_time <= now + timedelta(hours=24),
            MLSMatch.live_reporting_started == False,
            MLSMatch.live_reporting_scheduled == False
        ).all()

        scheduled_count = 0
        for match in upcoming_matches:
            time_diff = match.date_time - now
            start_live_reporting.apply_async(
                args=[match.match_id],
                countdown=max(0, int(time_diff.total_seconds())),
                queue='live_reporting'
            )
            match.live_reporting_scheduled = True
            scheduled_count += 1

        return {
            'success': True,
            'message': f'Scheduled {scheduled_count} matches for reporting',
            'scheduled_count': scheduled_count
        }

    except SQLAlchemyError as e:
        logger.error(f"Database error scheduling live reporting: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error scheduling live reporting: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)

@async_task(
    name='app.tasks.tasks_live_reporting.create_match_thread_task',
    queue='live_reporting',
    max_retries=3
)
async def create_match_thread_task(session, match_id: str) -> Dict[str, Any]:
    """Create match thread with retries."""
    try:
        match = session.query(MLSMatch).filter_by(match_id=match_id).first()
        if not match:
            return {'success': False, 'message': f'Match {match_id} not found'}

        if match.thread_created:
            return {'success': True, 'message': f'Thread already exists for match {match_id}'}

        thread_id = await create_match_thread(match)
        if thread_id:
            match.thread_created = True
            match.discord_thread_id = thread_id

            socketio.emit('thread_created', {
                'match_id': match_id,
                'thread_id': thread_id
            })

            return {
                'success': True,
                'message': f'Thread created successfully',
                'thread_id': thread_id
            }

        return {'success': False, 'message': 'Failed to create thread'}

    except SQLAlchemyError as e:
        logger.error(f"Database error creating match thread: {str(e)}", exc_info=True)
        raise create_match_thread_task.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error creating match thread: {str(e)}", exc_info=True)
        raise create_match_thread_task.retry(exc=e, countdown=30)

@celery_task(
    name='app.tasks.tasks_live_reporting.check_and_create_scheduled_threads',
    queue='live_reporting',
    max_retries=3
)
def check_and_create_scheduled_threads(self, session) -> Dict[str, Any]:
    """Check for and create scheduled match threads."""
    try:
        now = datetime.utcnow()
        due_matches = session.query(MLSMatch).filter(
            MLSMatch.thread_creation_time <= now,
            MLSMatch.thread_created == False
        ).all()

        for match in due_matches:
            create_match_thread_task.delay(match.match_id)

        return {
            'success': True,
            'message': f'Scheduled {len(due_matches)} match threads for creation',
            'scheduled_count': len(due_matches)
        }

    except SQLAlchemyError as e:
        logger.error(f"Database error checking scheduled threads: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error checking scheduled threads: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)


@celery_task(
    name='app.tasks.tasks_live_reporting.force_create_mls_thread_task',
    bind=True,
    queue='live_reporting',
    max_retries=2
)
def force_create_mls_thread_task(self, session, match_id: str) -> Dict[str, Any]:
    """Force immediate creation of Discord thread for MLS match."""
    try:
        logger.info(f"Starting thread creation for match {match_id}")
        match = session.query(MLSMatch).filter_by(match_id=match_id).first()
        if not match:
            logger.error(f"Match {match_id} not found")
            return {'success': False, 'message': f'Match {match_id} not found'}

        if match.thread_created:
            logger.info(f"Thread already exists for match {match_id}")
            return {'success': True, 'message': 'Thread already exists'}

        # Since create_match_thread is async, let's run it in an async loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            thread_id = loop.run_until_complete(create_match_thread(session, match))
            if thread_id:
                match.thread_created = True
                match.discord_thread_id = thread_id

                logger.info(f"Created thread {thread_id} for match {match_id}")
                return {
                    'success': True,
                    'message': f'Thread created successfully. ID: {thread_id}',
                    'thread_id': thread_id
                }

            logger.error(f"Failed to create thread for match {match_id}")
            return {'success': False, 'message': 'Failed to create thread'}

        finally:
            loop.close()

    except SQLAlchemyError as e:
        logger.error(f"Database error creating thread for match {match_id}: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error creating thread for match {match_id}: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)


@celery_task(
    name='app.tasks.tasks_live_reporting.schedule_mls_thread_task',
    queue='live_reporting',
    max_retries=2
)
def schedule_mls_thread_task(self, session, match_id: int, hours_before: int = 24) -> Dict[str, Any]:
    """Schedule creation of Discord thread for MLS match."""
    try:
        match = session.query(MLSMatch).get(match_id)
        if not match:
            return {'success': False, 'message': f'Match {match_id} not found'}

        match.thread_creation_time = match.date_time - timedelta(hours=hours_before)

        return {
            'success': True,
            'message': f'Match thread for {match.opponent} scheduled for {match.thread_creation_time}'
        }

    except SQLAlchemyError as e:
        logger.error(f"Database error scheduling MLS thread: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error scheduling MLS thread: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)


@celery_task(
    name='app.tasks.tasks_live_reporting.schedule_all_mls_threads_task',
    queue='live_reporting',
    max_retries=2
)
def schedule_all_mls_threads_task(self, session, default_hours_before: int = 24) -> Dict[str, Any]:
    """Schedule thread creation for all unscheduled MLS matches."""
    try:
        matches = session.query(MLSMatch).filter(
            MLSMatch.thread_created == False,
            MLSMatch.thread_creation_time.is_(None)
        ).all()

        scheduled_count = 0
        for match in matches:
            schedule_mls_thread_task.delay(match.id, default_hours_before)
            scheduled_count += 1

        return {
            'success': True,
            'message': f'Successfully scheduled {scheduled_count} match threads',
            'scheduled_count': scheduled_count
        }

    except SQLAlchemyError as e:
        logger.error(f"Database error scheduling all MLS threads: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error scheduling all MLS threads: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)


async def end_match_reporting(match_id: str) -> None:
    """End match reporting and cleanup."""
    try:
        # Attempt to get a session from g if in request context, otherwise create one:
        from flask import g
        session = getattr(g, 'db_session', None)
        if session is None:
            # No request context or g.db_session, create a new session:
            app = current_app._get_current_object()
            session = app.SessionLocal()

            new_session = True
        else:
            new_session = False

        match = session.query(MLSMatch).filter_by(match_id=match_id).first()
        if match:
            match.live_reporting_status = 'completed'
            match.live_reporting_started = False
            logger.info(f"Live reporting ended for match {match_id}")

        if new_session:
            session.commit()
            session.close()

    except Exception as e:
        logger.error(f"Error ending match reporting: {str(e)}")
