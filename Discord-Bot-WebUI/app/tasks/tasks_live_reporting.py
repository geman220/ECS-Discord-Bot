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
from app.decorators import celery_task
from app.utils.task_session_manager import task_session
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
                session=session,
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
                session.add(match)

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
            session.add(match)

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
        session.add(match)

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
            with task_session() as error_session:
                # Use get_match here as well.
                match = get_match(error_session, match_id)
                if match:
                    match.live_reporting_status = 'failed'
                    match.live_reporting_started = False
                    match.live_reporting_task_id = None
                # Commit happens automatically in task_session
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
    max_retries=3,
    soft_time_limit=180,  # 3 minutes soft timeout
    time_limit=300        # 5 minutes hard timeout
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
        from datetime import timezone
        now = datetime.now(timezone.utc)
        upcoming_matches = session.query(MLSMatch).filter(
            MLSMatch.date_time >= now,
            MLSMatch.date_time <= now + timedelta(hours=48),
            MLSMatch.live_reporting_started == False,
            MLSMatch.live_reporting_scheduled == False
        ).all()

        scheduled_count = 0
        for match in upcoming_matches:
            # Calculate the exact ETA for when live reporting should start
            reporting_time = match.date_time - timedelta(minutes=5)  # Start 5 minutes before match
            
            # Skip if the reporting time is in the past
            if reporting_time <= now:
                continue
                
            # Check if already scheduled in Redis to prevent duplicates
            from app.utils.safe_redis import get_safe_redis
            redis_client = get_safe_redis()
            redis_key = f"match_scheduler:{match.match_id}:reporting"
            
            if redis_client.exists(redis_key):
                logger.info(f"Match {match.match_id} already has scheduled live reporting task")
                continue
            
            # Schedule with ETA and store task ID
            task = start_live_reporting.apply_async(
                args=[str(match.match_id)],
                eta=reporting_time,
                queue='live_reporting'
            )
            
            # Store task ID in Redis for tracking
            import json
            data_to_store = json.dumps({
                "task_id": task.id,
                "eta": reporting_time.isoformat()
            })
            expiry = int((reporting_time - now).total_seconds()) + 3600  # Task + 1 hour buffer
            redis_client.setex(redis_key, expiry, data_to_store)
            
            match.live_reporting_scheduled = True
            scheduled_count += 1
            logger.info(f"Scheduled live reporting for match {match.match_id} at {reporting_time} with task ID {task.id}")

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




@celery_task(
    name='app.tasks.tasks_live_reporting.check_and_create_scheduled_threads',
    queue='live_reporting',
    max_retries=3,
    soft_time_limit=300,  # 5 minutes soft timeout
    time_limit=600        # 10 minutes hard timeout
)
def check_and_create_scheduled_threads(self, session) -> Dict[str, Any]:
    """
    Check for matches with scheduled thread creation and trigger thread creation.
    
    Uses staggered execution to:
    1. Prevent Discord API rate limits by spacing out thread creation
    2. Batch process matches in small groups
    3. Add variable delays based on match priority
    4. Prevent concurrent creation of similar threads

    Returns:
        A dictionary summarizing the number of match threads scheduled for creation.

    Raises:
        Retries the task on error.
    """
    try:
        from datetime import timezone
        now = datetime.now(timezone.utc)
        # Include matches that are slightly overdue (up to 6 hours)
        # and sort by creation time to process oldest first
        # First, clean up any stale scheduled tasks (older than 2 hours)
        stale_threshold = now - timedelta(hours=2)
        stale_matches = session.query(MLSMatch).filter(
            MLSMatch.thread_creation_scheduled == True,
            MLSMatch.thread_created == False,
            MLSMatch.last_thread_scheduling_attempt < stale_threshold
        ).all()
        
        for stale_match in stale_matches:
            logger.warning(f"Resetting stale thread scheduling for match {stale_match.match_id}")
            stale_match.thread_creation_scheduled = False
            stale_match.thread_creation_task_id = None
        
        # Commit the stale cleanup changes to prevent long-running transactions
        if stale_matches:
            session.commit()
            logger.info(f"Reset {len(stale_matches)} stale scheduled threads")
        
        # Now get matches that need thread creation
        due_matches = session.query(MLSMatch).filter(
            MLSMatch.thread_creation_time <= now + timedelta(hours=6),
            MLSMatch.thread_created == False,
            MLSMatch.thread_creation_scheduled == False
        ).order_by(MLSMatch.thread_creation_time).all()
        
        # Get Redis client for the entire function
        redis_client = None
        try:
            from app.utils.safe_redis import get_safe_redis
            redis_client = get_safe_redis()
            if not redis_client.is_available:
                redis_client = None
        except Exception as e:
            logger.warning(f"Redis connection failed: {e}")
        
        # Filter out matches that already have Redis-scheduled tasks (with timeout)
        filtered_matches = []
        if redis_client:
            for match in due_matches:
                redis_key = f"match_scheduler:{match.id}:thread"
                try:
                    # Use a quick timeout to prevent hanging
                    # The RedisManager already has 10s timeout, but let's be extra careful
                    exists = redis_client.exists(redis_key)
                    if not exists:
                        filtered_matches.append(match)
                    else:
                        logger.info(f"Skipping match {match.id} - already has Redis-scheduled thread task")
                except Exception as e:
                    logger.warning(f"Redis check failed for match {match.id}: {e}")
                    # Include match anyway to be safe
                    filtered_matches.append(match)
        else:
            # No Redis connection, process all matches
            filtered_matches = due_matches
        
        due_matches = filtered_matches

        if not due_matches:
            return {
                'success': True,
                'message': 'No match threads due for creation',
                'scheduled_count': 0
            }
            
        # Calculate priorities - matches closer to now should be processed first
        matches_with_priority = []
        for match in due_matches:
            # Calculate priority based on how overdue the thread is
            if match.thread_creation_time <= now:
                # Overdue threads get high priority
                priority = "high"
                # More overdue = higher priority
                minutes_overdue = (now - match.thread_creation_time).total_seconds() / 60
                delay = max(0, 30 - min(minutes_overdue, 30))  # 0-30 minute delay inversely proportional to how overdue
            else:
                # Future threads get lower priority
                priority = "medium" if match.date_time - now < timedelta(days=1) else "low"
                # Further in future = more delay
                minutes_until_due = (match.thread_creation_time - now).total_seconds() / 60
                delay = 30 + min(minutes_until_due, 30)  # 30-60 minute delay based on time until due
                
            matches_with_priority.append({
                'match': match,
                'priority': priority,
                'delay': delay
            })
        
        # Sort by priority (high first) and then by delay (lower delay first)
        priority_order = {"high": 0, "medium": 1, "low": 2}
        matches_with_priority.sort(
            key=lambda x: (priority_order[x['priority']], x['delay'])
        )
        
        # Process in small batches with staggered execution
        batch_size = 3  # Process max 3 matches in each batch
        base_delay = 60  # 60 seconds between batches
        
        scheduled_count = 0
        scheduled_details = []
        
        for i, match_info in enumerate(matches_with_priority):
            match = match_info['match']
            batch_num = i // batch_size
            position_in_batch = i % batch_size
            
            # Check if thread creation is already in progress for this match
            if redis_client:
                lock_key = f"thread_creation_lock:{match.match_id}"
                try:
                    # The RedisManager already has 10s timeout, but let's be extra careful
                    exists = redis_client.exists(lock_key)
                    if exists:
                        logger.info(f"Thread creation already in progress for match {match.match_id}, skipping")
                        continue
                except Exception as e:
                    logger.warning(f"Redis lock check failed for match {match.match_id}: {e}")
                    # Continue without lock check rather than hang
            
            # Calculate delay: batch delay + position delay + priority-based delay
            total_delay = (batch_num * base_delay) + (position_in_batch * 20) + match_info['delay']
            
            # Schedule thread creation with appropriate delay
            result = force_create_mls_thread_task.apply_async(
                args=[match.id],
                countdown=int(total_delay)
            )
            
            # Mark the match as having a scheduled thread creation task
            match.thread_creation_scheduled = True
            match.thread_creation_task_id = result.id
            match.last_thread_scheduling_attempt = now
            
            scheduled_count += 1
            scheduled_details.append({
                'match_id': match.match_id,
                'opponent': match.opponent,
                'date': match.date_time.isoformat() if match.date_time else None,
                'priority': match_info['priority'],
                'delay': total_delay,
                'batch': batch_num + 1,
                'position': position_in_batch + 1
            })
            
            logger.info(
                f"Scheduled thread creation for match {match.match_id} ({match.opponent}) "
                f"with {total_delay}s delay (batch {batch_num+1}, position {position_in_batch+1}, priority {match_info['priority']})"
            )
        
        # Commit all the scheduled changes to prevent long-running transactions
        if scheduled_count > 0:
            session.commit()
            logger.info(f"Committed {scheduled_count} scheduled thread creation tasks")
            
        return {
            'success': True,
            'message': f'Scheduled {scheduled_count} match threads for creation using staggered execution',
            'scheduled_count': scheduled_count,
            'batches': (scheduled_count + batch_size - 1) // batch_size if scheduled_count > 0 else 0,
            'details': scheduled_details
        }

    except SQLAlchemyError as e:
        logger.error(f"Database error checking scheduled threads: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error checking scheduled threads: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)


def _extract_mls_thread_data(session, match_id: str, force: bool = False):
    """Extract match data for MLS thread creation."""
    match = get_match(session, match_id)
    
    if not match:
        raise ValueError(f"Match {match_id} not found")
    
    return {
        'match_id': match_id,
        'force': force,
        'thread_created': match.thread_created,
        'match_data': {
            'id': match.id,
            'home_team': 'Seattle Sounders FC' if match.is_home_game else match.opponent,
            'away_team': match.opponent if match.is_home_game else 'Seattle Sounders FC',
            'opponent': match.opponent,
            'is_home_game': match.is_home_game,
            'date_time': match.date_time.isoformat() if match.date_time else None,
            'venue': getattr(match, 'venue', None),
            'competition': getattr(match, 'competition', None),
            'summary_link': getattr(match, 'summary_link', None),
            'stats_link': getattr(match, 'stats_link', None),
            'commentary_link': getattr(match, 'commentary_link', None)
        }
    }


async def _execute_mls_thread_creation_async(data):
    """Execute MLS thread creation without database session."""
    if data['thread_created'] and not data['force']:
        return {'success': True, 'message': 'Thread already exists'}
    
    # Create thread using async-only approach  
    from app.discord_utils import create_match_thread_async_only
    
    thread_id = await create_match_thread_async_only(data['match_data'])
    
    if thread_id:
        return {
            'success': True,
            'thread_id': thread_id,
            'match_id': data['match_id'],
            'message': f'Created thread {thread_id} for match {data["match_id"]}'
        }
    else:
        return {
            'success': False,
            'match_id': data['match_id'],
            'message': 'Failed to create thread'
        }


def _update_match_after_thread_creation(session, result):
    """Update match record after thread creation."""
    if not result.get('success'):
        return result
    
    match = get_match(session, result['match_id'])
    if match and result.get('thread_id'):
        match.thread_created = True
        match.discord_thread_id = result['thread_id']
        session.add(match)
    
    return result


@celery_task(
    name='app.tasks.tasks_live_reporting.force_create_mls_thread_task',
    bind=True,
    queue='live_reporting',
    max_retries=2
)
async def force_create_mls_thread_task(self, session, match_id: str, force: bool = False) -> Dict[str, Any]:
    """
    Force the immediate creation of a Discord thread for an MLS match using two-phase pattern.
    Returns a dictionary with the creation result and thread ID if successful.
    """
    # Handle Redis locking in the task since it's not database-related
    try:
        logger.info(f"Starting thread creation for match {match_id}")
        
        # Use Redis to ensure only one worker processes this match at a time
        from app.utils.safe_redis import get_safe_redis
        redis = get_safe_redis()
        lock_key = f"thread_creation_lock:{match_id}"
        lock_value = f"{self.request.id}"  # Use task ID as lock value
        
        # Try to acquire lock with 5 minute expiry
        if not redis.set(lock_key, lock_value, nx=True, ex=300):
            logger.info(f"Another worker is already creating thread for match {match_id}")
            
            # Check if thread was already created by another worker
            from app.utils.task_session_manager import task_session
            with task_session() as check_session:
                match = get_match(check_session, match_id)
                if match and match.thread_created:
                    logger.info(f"Thread was created by another worker for match {match_id}")
                    return {'success': True, 'message': 'Thread already exists'}
            
            # If not created yet, retry this task after a delay
            logger.info(f"Retrying thread creation for match {match_id} after delay")
            raise self.retry(countdown=5, max_retries=5)
        
        try:
            # The two-phase pattern will be handled by the decorator automatically
            pass
        finally:
            # Release the Redis lock
            try:
                # Only release if we still own the lock
                lua_script = """
                if redis.call('get', KEYS[1]) == ARGV[1] then
                    return redis.call('del', KEYS[1])
                else
                    return 0
                end
                """
                redis.eval(lua_script, 1, lock_key, lock_value)
                logger.debug(f"Released Redis lock for match {match_id}")
            except Exception as e:
                logger.warning(f"Failed to release Redis lock for match {match_id}: {e}")
        
    except Exception as e:
        logger.error(f"Error in force_create_mls_thread_task: {e}", exc_info=True)
        raise


# Attach phase methods
force_create_mls_thread_task._extract_data = _extract_mls_thread_data
force_create_mls_thread_task._execute_async = _execute_mls_thread_creation_async
force_create_mls_thread_task._requires_final_db_update = True
force_create_mls_thread_task._final_db_update = _update_match_after_thread_creation
force_create_mls_thread_task._two_phase = True


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
      - Uses managed_session for proper session handling.
    """
    try:
        # Use managed_session which handles Flask request context properly
        with managed_session() as session:
            match = get_match(session, match_id)
            if match:
                match.live_reporting_status = 'completed'
                match.live_reporting_started = False
                session.add(match)
                logger.info(f"Live reporting ended for match {match_id}")
                # Commit happens automatically in managed_session

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