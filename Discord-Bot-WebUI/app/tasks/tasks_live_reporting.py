# app/tasks/tasks_live_reporting.py

"""
Live Reporting Tasks Module

This module defines Celery tasks for live match reporting. Tasks include:
  - Processing live match updates via ESPN data.
  - Starting live reporting for a match.
  - Scheduling live reporting for upcoming matches.
  - Creating Discord threads for matches.
  - Scheduling thread creation (individually or in batch).
  - Force-creating a Discord thread for a match.
  - Ending match reporting and cleaning up.

Tasks leverage async HTTP calls to ESPN and Discord APIs, and update the live
reporting status on MLSMatch objects.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
import asyncio
from flask import current_app, g
from sqlalchemy.exc import SQLAlchemyError
from app.core import socketio
from app.core.session_manager import managed_session
from app.core.helpers import get_match
from app.decorators import celery_task, async_task
from app.models import MLSMatch, Prediction
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
                         last_event_keys: Optional[list] = None,
                         task_id: Optional[str] = None,
                         task_chain_length: int = 0) -> Dict[str, Any]:
    """
    Process a single live match update iteration.

    This task:
      - Verifies the match exists and is in 'running' state.
      - Fetches ESPN match data asynchronously.
      - Processes live updates via an async helper.
      - If the match has ended, updates its status.
      - Otherwise, updates current status and score,
        then schedules the next update in 30 seconds.

    Returns:
        A dictionary with the update result (success, message, status, score, match_status).

    Raises:
        Retries the task on SQLAlchemy or general exceptions.
    """
    try:
        logger.info(f"Processing update for match {match_id}")

        match = get_match(session, match_id)
        if not match:
            logger.error(f"Match {match_id} not found")
            return {'success': False, 'message': 'Match not found'}

        if match.live_reporting_status != 'running':
            logger.error(f"Match {match_id} not in running state")
            return {'success': False, 'message': 'Match not in running state'}

        # Check if this is a duplicate task execution - ADDED CODE
        current_task_id = self.request.id
        if task_id and current_task_id != task_id:
            logger.warning(f"Detected duplicate task execution for match {match_id}. "
                          f"Expected task ID: {task_id}, Current task ID: {current_task_id}")
            # Stop processing duplicate tasks to prevent spam
            return {'success': False, 'message': 'Duplicate task execution detected'}

        last_event_keys = last_event_keys or []

        # Log task execution for debugging
        logger.info(f"Processing match update with task ID: {self.request.id}, previous task ID: {task_id}")
        
        # Use async_to_sync utility to safely run async functions
        from app.api_utils import async_to_sync
        
        # Fetch match data from ESPN
        full_url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{competition}/scoreboard/{match_id}"
        match_data = async_to_sync(fetch_espn_data(full_url=full_url))
        if not match_data:
            logger.error(f"Failed to fetch data for match {match_id}")
            return {'success': False, 'message': 'Failed to fetch match data'}

        # Process live match updates using async_to_sync to avoid nested event loops
        match_ended, current_event_keys = async_to_sync(
            process_live_match_updates(
                match_id=str(match_id),
                thread_id=thread_id,
                match_data=match_data,
                last_status=last_status,
                last_score=last_score,
                last_event_keys=last_event_keys
            )
        )

        if match_ended:
            logger.info(f"Match {match_id} has ended")
            try:
                # Extract final scores from the ESPN data.
                final_home_score = int(match_data['competitions'][0]['competitors'][0]['score'])
                final_away_score = int(match_data['competitions'][0]['competitors'][1]['score'])
                # Finalize predictions based on the final scores.
                finalize_predictions_for_match(match_id, final_home_score, final_away_score)
                logger.info(f"Predictions finalized for match {match_id}")
            except Exception as fe:
                logger.error(f"Error finalizing predictions for match {match_id}: {str(fe)}", exc_info=True)
    
            # Build update_data including the match_id
            update_data = {
                "match_id": match_id,  # This is the key update.
                "home_team": match_data['competitions'][0]['competitors'][0],
                "away_team": match_data['competitions'][0]['competitors'][1],
                "home_score": final_home_score,
                "away_score": final_away_score
            }
    
            match = get_match(session, match_id)
            if match:
                match.live_reporting_status = 'completed'
                match.live_reporting_started = False
                match.live_reporting_task_id = None  # ADDED CODE: Clear task ID

            # Return the update data so that the Discord bot can use it to build the full-time embed.
            return {
                'success': True,
                'message': 'Match ended',
                'status': 'completed',
                'update_data': update_data
            }

        # Extract new status and score from ESPN data.
        new_status = match_data["competitions"][0]["status"]["type"]["name"]
        home_score = match_data['competitions'][0]['competitors'][0]['score']
        away_score = match_data['competitions'][0]['competitors'][1]['score']
        new_score = f"{home_score}-{away_score}"

        # Update match with new status, score, and timestamp.
        match = get_match(session, match_id)
        if match:
            match.current_status = new_status
            match.current_score = new_score
            match.last_update_time = datetime.utcnow()

        # Schedule the next update with updated parameters.
        # Store the task ID to prevent duplicate executions
        try:
            # Check if we've been running too long to prevent infinite chains
            max_chain_length = 120  # 120 × 30 seconds = 1 hour maximum per match
            task_chain_length = getattr(self.request, 'task_chain_length', 0) + 1
            
            if task_chain_length > max_chain_length:
                logger.warning(
                    f"Match {match_id} reached maximum chain length of {max_chain_length}. "
                    f"Stopping automatic updates to prevent runaway tasks."
                )
                return {
                    'success': False,
                    'message': f'Maximum chain length ({max_chain_length}) reached',
                    'status': 'stopped',
                    'score': new_score,
                    'match_status': new_status
                }
                
            logger.info(f"Scheduling next update for match {match_id}, chain length: {task_chain_length}/{max_chain_length}")
            
            # Create the next task
            next_task = self.apply_async(
                args=[match_id, thread_id, competition],
                kwargs={
                    'last_status': new_status,
                    'last_score': new_score,
                    'last_event_keys': current_event_keys,
                    'task_id': None,  # This will be ignored by duplicate detection logic on first run
                    'task_chain_length': task_chain_length  # Track how many times this task has chained itself
                },
                countdown=30,
                queue='live_reporting'
            )
            logger.info(f"Scheduled next task with ID: {next_task.id}")
        except Exception as e:
            logger.error(f"Error scheduling next task: {str(e)}", exc_info=True)
            # Create a minimal task result object for error handling
            from collections import namedtuple
            MockTask = namedtuple('MockTask', ['id'])
            next_task = MockTask(id="error-scheduling-task")
        
        # Store the new task ID in the database
        if match:
            match.live_reporting_task_id = next_task.id
            logger.info(f"Scheduled next update with task ID: {next_task.id} for match {match_id}")
            
        # We no longer need to update task kwargs since we're using the dictionary directly
        # and it was already updated above

        return {
            'success': True,
            'message': 'Update processed',
            'status': 'running',
            'score': new_score,
            'match_status': new_status,
            'next_task_id': next_task.id  # ADDED CODE: Return the next task ID
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
    """
    Start live match reporting for a specific match.

    This task:
      - Retrieves the match by its identifier (using the get_match helper).
      - Checks if reporting is already running.
      - Updates match status to running and records start time.
      - Triggers the initial match update task.
      - Stores the task ID to prevent duplicate executions.

    Returns:
        A dictionary indicating the reporting start result.

    Raises:
        Retries the task on SQLAlchemy or general errors.
    """
    try:
        logger.info(f"Starting live reporting for match_id: {match_id}")

        # Always use get_match to retrieve the match.
        match = get_match(session, match_id)

        if not match:
            logger.error(f"Match {match_id} not found")
            return {'success': False, 'message': f'Match {match_id} not found'}

        if match.live_reporting_status == 'running':
            logger.warning(f"Live reporting already running for match {match_id}")
            # If a task ID exists but the task is no longer active, we should reset it
            if match.live_reporting_task_id:
                task = process_match_update.AsyncResult(match.live_reporting_task_id)
                if not task.ready() and task.state != 'REVOKED':
                    return {'success': False, 'message': 'Live reporting already running'}
                logger.info(f"Task {match.live_reporting_task_id} is no longer active, restarting live reporting")
                # Task is done or doesn't exist, we can restart
            
        # Mark the match as running.
        match.live_reporting_started = True
        match.live_reporting_status = 'running'
        match.reporting_start_time = datetime.utcnow()
        # Clear any previous task ID
        match.live_reporting_task_id = None

        match_data = {
            'match_id': match.match_id,
            'thread_id': match.discord_thread_id,
            'competition': match.competition
        }

        logger.info(f"Updated match status to running for {match_id}")

        # Trigger the update task asynchronously and store its ID.
        task = process_match_update.delay(
            match_id=str(match_data['match_id']),
            thread_id=str(match_data['thread_id']),
            competition=match_data['competition'],
            last_status=None,
            last_score=None,
            last_event_keys=[],
            task_id=None  # Will be set to the actual task ID
        )
        
        # Store the task ID to track this execution chain
        match.live_reporting_task_id = task.id
        logger.info(f"Started live reporting with initial task ID: {task.id}")

        return {
            'success': True,
            'message': 'Live reporting started successfully',
            'match_id': match_data['match_id'],
            'thread_id': match_data['thread_id'],
            'status': 'running',
            'task_id': task.id
        }

    except SQLAlchemyError as e:
        logger.error(f"Database error in start_live_reporting: {str(e)}", exc_info=True)
        try:
            app = current_app._get_current_object()
            error_session = app.SessionLocal()
            # Use get_match here as well.
            match = get_match(error_session, match_id)
            if match:
                match.live_reporting_status = 'failed'
                match.live_reporting_started = False
                match.live_reporting_task_id = None
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
    """
    Schedule live reporting for upcoming matches.

    This task:
      - Queries for matches within the next 48 hours that haven't started live reporting.
      - Schedules each match to start live reporting at the appropriate time.
      - Marks matches as scheduled.

    Returns:
        A summary dictionary with the number of matches scheduled.

    Raises:
        Retries the task on errors.
    """
    try:
        now = datetime.utcnow()
        upcoming_matches = session.query(MLSMatch).filter(
            MLSMatch.date_time >= now,
            MLSMatch.date_time <= now + timedelta(hours=48),
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
    """
    Create a Discord thread for a match with retries.

    This async task:
      - Retrieves the match by ID.
      - If a thread does not already exist, creates one via the Discord API.
      - Emits a socketio event on successful thread creation.

    Returns:
        A dictionary indicating success or failure, along with the thread ID if successful.

    Raises:
        Retries on SQLAlchemy or general errors.
    """
    try:
        match = get_match(session, match_id)
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
    """
    Check for matches with scheduled thread creation and trigger thread creation.

    Returns:
        A dictionary summarizing the number of match threads scheduled for creation.

    Raises:
        Retries the task on error.
    """
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
def force_create_mls_thread_task(self, injected_session, match_id: str, force: bool = False) -> Dict[str, Any]:
    """
    Force the immediate creation of a Discord thread for an MLS match.
    Returns a dictionary with the creation result and thread ID if successful.
    """
    session = current_app.SessionLocal()
    try:
        logger.info(f"Starting thread creation for match {match_id}")
        match = get_match(session, match_id)

        if not match:
            logger.error(f"Match {match_id} not found")
            return {'success': False, 'message': f'Match {match_id} not found'}

        if match.thread_created and not force:
            logger.info(f"Thread already exists for match {match_id}")
            return {'success': True, 'message': 'Thread already exists'}

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            thread_id = loop.run_until_complete(create_match_thread(session, match))
            if thread_id:
                match.thread_created = True
                match.discord_thread_id = thread_id
                session.commit()

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
            # Ensure connections are properly cleaned up after asyncio operations
            from app.utils.db_connection_monitor import ensure_connections_cleanup
            ensure_connections_cleanup()

    except SQLAlchemyError as e:
        session.rollback()
        logger.error(f"Database error creating thread for match {match_id}: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        session.rollback()
        logger.error(f"Error creating thread for match {match_id}: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)
    finally:
        session.close()


@celery_task(
    name='app.tasks.tasks_live_reporting.schedule_mls_thread_task',
    queue='live_reporting',
    max_retries=2
)
def schedule_mls_thread_task(self, session, match_id: int, hours_before: int = 48) -> Dict[str, Any]:
    """
    Schedule the creation of a Discord thread for an MLS match.

    Args:
        match_id: The ID of the match.
        hours_before: Number of hours before the match to schedule thread creation.

    Returns:
        A dictionary with scheduling result.
    """
    try:
        match = get_match(session, match_id)
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
def schedule_all_mls_threads_task(self, session, default_hours_before: int = 48) -> Dict[str, Any]:
    """
    Schedule thread creation for all unscheduled MLS matches.

    Returns:
        A summary dictionary indicating the number of match threads scheduled.

    Raises:
        Retries the task on errors.
    """
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
    """
    End live match reporting and perform cleanup.

    This async helper:
      - Retrieves the match via the current Flask application context.
      - Sets the live reporting status to 'completed' and marks reporting as stopped.
      - Commits and closes the session if it was newly created.
    """
    try:
        session = getattr(g, 'db_session', None)
        if session is None:
            app = current_app._get_current_object()
            session = app.SessionLocal()
            new_session = True
        else:
            new_session = False

        match = get_match(session, match_id)
        if match:
            match.live_reporting_status = 'completed'
            match.live_reporting_started = False
            logger.info(f"Live reporting ended for match {match_id}")

        if new_session:
            session.commit()
            session.close()

    except Exception as e:
        logger.error(f"Error ending match reporting: {str(e)}")

def finalize_predictions_for_match(match_id: str, final_home_score: int, final_away_score: int):
    """
    Finalize predictions for a match by comparing each prediction with the final score.
    Marks predictions as correct if they exactly match the final scores,
    and returns a list of Discord user IDs that predicted correctly.
    """
    logger.info(f"Finalizing predictions for match {match_id}: Final Score {final_home_score}-{final_away_score}")
    correct_users = []
    with managed_session() as session:
        predictions = session.query(Prediction).filter_by(match_id=match_id).all()
        for pred in predictions:
            if pred.home_score == final_home_score and pred.opponent_score == final_away_score:
                pred.is_correct = True
                pred.season_correct_count += 1
                correct_users.append(pred.discord_user_id)
            else:
                pred.is_correct = False
        session.commit()
    return correct_users