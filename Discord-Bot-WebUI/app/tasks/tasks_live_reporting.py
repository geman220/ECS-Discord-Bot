# app/tasks/tasks_live_reporting.py

import logging
import asyncio
import aiohttp
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from app.core import socketio
from app.utils.db_utils import celery_transactional_task
from app.models import MLSMatch
from app.match_scheduler import MatchScheduler
from app.match_api import process_live_match_updates
from app.discord_utils import create_match_thread
from app.api_utils import fetch_espn_data
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import SQLAlchemyError
from app.db_management import db_manager
from redis import Redis
from flask import current_app

logger = logging.getLogger(__name__)

@celery_transactional_task(
    name='app.tasks.tasks_live_reporting.process_match_update',
    bind=True,
    queue='live_reporting'
)
def process_match_update(self, match_id: str, thread_id: str,
                        last_status: str = None, last_score: str = None,
                        last_event_keys: list = None) -> Dict[str, Any]:
    """Process a single match update iteration."""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_process_match_update_async(
                match_id, thread_id, last_status, last_score, last_event_keys))
            return result
        finally:
            loop.close()
    except SQLAlchemyError as e:
        logger.error(f"Database error in process_match_update: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error in process_match_update: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)

async def _process_match_update_async(match_id: str, thread_id: str,
                                    last_status: str = None, last_score: str = None,
                                    last_event_keys: list = None) -> Dict[str, Any]:
    """Async helper for process_match_update."""
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        def get_match_data_sync() -> Optional[Dict[str, Any]]:
            from app import create_app
            app = create_app()
            
            with app.app_context():
                with db_manager.session_scope(transaction_name='get_match_update_data') as session:
                    match = session.query(MLSMatch).options(
                        joinedload(MLSMatch.home_team),
                        joinedload(MLSMatch.away_team)
                    ).get(match_id)

                    if not match or match.live_reporting_status != 'running':
                        return None

                    return {
                        'id': match.id,
                        'match_id': match.match_id,
                        'competition': match.competition,
                        'live_reporting_status': match.live_reporting_status,
                        'discord_thread_id': match.discord_thread_id
                    }

        match_data = await asyncio.get_event_loop().run_in_executor(executor, get_match_data_sync)
        if not match_data:
            logger.error(f"Match {match_id} not found or not in running state")
            return {
                'success': False,
                'message': 'Match not found or not in running state'
            }

        espn_data = await fetch_espn_data(
            f"https://site.api.espn.com/apis/site/v2/sports/soccer/{match_data['competition']}/scoreboard/{match_id}"
        )
        if not espn_data:
            logger.error(f"Failed to fetch data for match {match_id}")
            return {'success': False, 'message': 'Failed to fetch match data'}

        match_ended, current_event_keys = await process_live_match_updates(
            match_id=str(match_id),
            thread_id=thread_id,
            match_data=espn_data,
            last_status=last_status,
            last_score=last_score,
            last_event_keys=last_event_keys or []
        )

        if match_ended:
            def update_match_status_sync():
                from app import create_app
                app = create_app()
                
                with app.app_context():
                    with db_manager.session_scope(transaction_name='update_match_end_status') as session:
                        match = session.query(MLSMatch).get(match_id)
                        if match:
                            match.live_reporting_status = 'completed'
                            match.live_reporting_started = False
                            match.completed_at = datetime.utcnow()
                            return True
                        return False

            updated = await asyncio.get_event_loop().run_in_executor(executor, update_match_status_sync)
            if updated:
                return {
                    'success': True,
                    'message': 'Match ended',
                    'status': 'completed'
                }
            return {
                'success': False,
                'message': 'Failed to update match status'
            }

        new_status = espn_data["competitions"][0]["status"]["type"]["name"]
        new_score = (f"{espn_data['competitions'][0]['competitors'][0]['score']}-"
                     f"{espn_data['competitions'][0]['competitors'][1]['score']}")

        # Update match status in database
        def update_match_info_sync():
            from app import create_app
            app = create_app()
            
            with app.app_context():
                with db_manager.session_scope(transaction_name='update_match_info') as session:
                    match = session.query(MLSMatch).get(match_id)
                    if match:
                        match.current_status = new_status
                        match.current_score = new_score
                        match.last_update_time = datetime.utcnow()
                        return True
                    return False

        await asyncio.get_event_loop().run_in_executor(executor, update_match_info_sync)

        return {
            'success': True,
            'message': 'Update processed',
            'status': 'running',
            'score': new_score,
            'match_status': new_status,
            'current_event_keys': current_event_keys
        }

    except SQLAlchemyError as e:
        logger.error(f"Database error in _process_match_update_async: {str(e)}", exc_info=True)
        raise
    except Exception as e:
        logger.error(f"Error in _process_match_update_async: {str(e)}", exc_info=True)
        raise
    finally:
        executor.shutdown()

@celery_transactional_task(
    name='app.tasks.tasks_live_reporting.start_live_reporting',
    bind=True,
    queue='live_reporting',
    max_retries=3,
    retry_backoff=True
)
def start_live_reporting(self, match_id: str) -> Dict[str, Any]:
    """Start live match reporting."""
    try:
        # Use a single session for all operations
        with db_manager.session_scope(transaction_name='start_live_reporting') as session:
            # Get match data
            match = session.query(MLSMatch).options(
                joinedload(MLSMatch.home_team),
                joinedload(MLSMatch.away_team)
            ).filter_by(match_id=match_id).first()

            if not match:
                logger.error(f"Match {match_id} not found")
                return {
                    'success': False,
                    'message': f'Match {match_id} not found'
                }

            if match.live_reporting_status == 'running':
                logger.info(f"Live reporting already running for match {match_id}")
                return {
                    'success': False,
                    'message': 'Live reporting already running'
                }

            # Update match status
            match.live_reporting_started = True
            match.live_reporting_status = 'running'
            match.reporting_start_time = datetime.utcnow()
            
            # Create response data
            updated_data = {
                'match_id': match.match_id,
                'discord_thread_id': match.discord_thread_id,
                'competition': match.competition,
                'status': match.live_reporting_status
            }

            session.flush()  # Ensure all changes are synchronized

        # Queue the update task
        process_match_update.apply_async(
            kwargs={
                'match_id': str(match_id),
                'thread_id': str(updated_data['discord_thread_id']),
                'last_status': None,
                'last_score': None,
                'last_event_keys': []
            },
            countdown=5  # Small delay to ensure database updates are complete
        )

        logger.info(f"Live reporting started for match {match_id}")
        return {
            'success': True,
            'message': 'Live reporting started successfully',
            'match_id': match_id,
            'thread_id': updated_data['discord_thread_id'],
            'status': updated_data['status']
        }

    except SQLAlchemyError as e:
        logger.error(f"Database error in start_live_reporting: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error in start_live_reporting: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)

@celery_transactional_task(
    name='app.tasks.tasks_live_reporting.create_match_thread_task',
    queue='live_reporting',
    bind=True,
    max_retries=3,
    retry_backoff=True
)
def create_match_thread_task(self, match_id: str) -> Dict[str, Any]:
    """Create match thread with proper error handling and retries."""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_create_match_thread_async(match_id))
            return result
        finally:
            loop.close()
    except SQLAlchemyError as e:
        logger.error(f"Database error creating match thread: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error creating match thread: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)

async def _create_match_thread_async(match_id: str) -> Dict[str, Any]:
    """Async helper for create_match_thread_task."""
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        def get_match_data_sync() -> Optional[Dict[str, Any]]:
            from app import create_app
            app = create_app()
            
            with app.app_context():
                with db_manager.session_scope(transaction_name='get_match_thread_data') as session:
                    match = session.query(MLSMatch).options(
                        joinedload(MLSMatch.home_team),
                        joinedload(MLSMatch.away_team)
                    ).get(match_id)
                    
                    if not match:
                        return None

                    return {
                        'id': match.id,
                        'thread_created': match.thread_created,
                        'opponent': match.opponent,
                        'home_team': {
                            'name': match.home_team.name,
                            'channel_id': match.home_team.discord_channel_id
                        },
                        'away_team': {
                            'name': match.away_team.name,
                            'channel_id': match.away_team.discord_channel_id
                        },
                        'date': match.date,
                        'time': match.time
                    }

        match_data = await asyncio.get_event_loop().run_in_executor(executor, get_match_data_sync)
        if not match_data:
            logger.error(f"Match {match_id} not found")
            return {
                'success': False,
                'message': f'Match {match_id} not found'
            }

        if match_data['thread_created']:
            logger.info(f"Thread already exists for match {match_id}")
            return {
                'success': True,
                'message': f'Thread already exists for match {match_id}'
            }

        thread_id = await create_match_thread(match_data)
        if not thread_id:
            logger.error(f"Failed to create thread for match {match_id}")
            return {
                'success': False,
                'message': 'Failed to create thread'
            }

        def update_thread_info_sync(thread_id: str):
            from app import create_app
            app = create_app()
            
            with app.app_context():
                with db_manager.session_scope(transaction_name='update_thread_info') as session:
                    match = session.query(MLSMatch).get(match_id)
                    if match:
                        match.thread_created = True
                        match.discord_thread_id = thread_id
                        match.thread_created_at = datetime.utcnow()
                        session.flush()

        await asyncio.get_event_loop().run_in_executor(executor, update_thread_info_sync, thread_id)
        
        socketio.emit('thread_created', {
            'match_id': match_id,
            'thread_id': thread_id,
            'timestamp': datetime.utcnow().isoformat()
        })
        
        logger.info(f"Successfully created thread {thread_id} for match {match_id}")
        return {
            'success': True,
            'message': 'Thread created successfully',
            'thread_id': thread_id,
            'created_at': datetime.utcnow().isoformat()
        }

    except SQLAlchemyError as e:
        logger.error(f"Database error in _create_match_thread_async: {str(e)}", exc_info=True)
        raise
    except Exception as e:
        logger.error(f"Error in _create_match_thread_async: {str(e)}", exc_info=True)
        raise
    finally:
        executor.shutdown()

@celery_transactional_task(
    name='app.tasks.tasks_live_reporting.check_and_create_scheduled_threads',
    queue='live_reporting',
    bind=True,
    max_retries=3
)
def check_and_create_scheduled_threads(self) -> Dict[str, Any]:
    """Check for and create scheduled match threads."""
    try:
        # Query for matches needing threads
        with db_manager.session_scope(transaction_name='check_scheduled_threads') as session:
            now = datetime.utcnow()
            matches = session.query(MLSMatch).options(
                joinedload(MLSMatch.home_team),
                joinedload(MLSMatch.away_team)
            ).filter(
                MLSMatch.thread_creation_time <= now,
                MLSMatch.thread_created == False
            ).all()

            due_matches_data = [{
                'id': match.id,
                'match_id': match.match_id,
                'thread_creation_time': match.thread_creation_time,
                'opponent': match.opponent
            } for match in matches]

        scheduled_count = 0
        failed_matches = []

        # Schedule thread creation tasks outside of database session
        for match_data in due_matches_data:
            try:
                # Use apply_async instead of delay for more control
                create_match_thread_task.apply_async(
                    args=[match_data['match_id']],
                    countdown=5 * scheduled_count,  # Stagger the creation of threads
                    expires=3600  # Tasks expire after 1 hour
                )
                scheduled_count += 1
                logger.info(f"Scheduled thread creation for match {match_data['match_id']} vs {match_data['opponent']}")
            except Exception as e:
                logger.error(f"Failed to schedule thread creation for match {match_data['match_id']}: {str(e)}")
                failed_matches.append({
                    'match_id': match_data['match_id'],
                    'error': str(e)
                })

        result = {
            'success': True,
            'message': f'Scheduled {scheduled_count} match threads for creation',
            'scheduled_count': scheduled_count,
            'failed_count': len(failed_matches),
            'failed_matches': failed_matches,
            'checked_at': datetime.utcnow().isoformat()
        }

        # Log results
        if scheduled_count > 0:
            logger.info(f"Successfully scheduled {scheduled_count} match threads")
        if failed_matches:
            logger.warning(f"Failed to schedule {len(failed_matches)} match threads")

        return result

    except SQLAlchemyError as e:
        logger.error(f"Database error checking scheduled threads: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error checking scheduled threads: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)

@celery_transactional_task(
    name='app.tasks.tasks_live_reporting.monitor_all_matches',
    queue='live_reporting',
    bind=True,
    max_retries=3
)
def monitor_all_matches(self) -> Dict[str, Any]:
    """Monitor and verify all scheduled match tasks."""
    try:
        # Get active matches data
        with db_manager.session_scope(transaction_name='get_active_matches') as session:
            matches = session.query(MLSMatch).options(
                joinedload(MLSMatch.home_team),
                joinedload(MLSMatch.away_team)
            ).filter(
                MLSMatch.live_reporting_scheduled == True,
                MLSMatch.live_reporting_status.in_(['scheduled', 'running'])
            ).all()

            active_matches_data = [{
                'id': match.id,
                'match_id': match.match_id,
                'status': match.live_reporting_status,
                'home_team_id': match.home_team_id,
                'away_team_id': match.away_team_id,
                'last_update_time': match.last_update_time,
                'opponent': match.opponent
            } for match in matches]

        # Process monitoring outside database session
        monitoring_results = []
        for match_data in active_matches_data:
            try:
                # Check if match needs attention
                if (match_data['last_update_time'] and 
                    datetime.utcnow() - match_data['last_update_time'] > timedelta(minutes=5)):
                    
                    # Attempt to recover the match reporting
                    logger.warning(f"Match {match_data['match_id']} may be stalled, attempting recovery")
                    process_match_update.apply_async(
                        kwargs={
                            'match_id': match_data['match_id'],
                            'recovery': True
                        },
                        countdown=5
                    )
                
                monitoring_results.append({
                    'match_id': match_data['match_id'],
                    'status': 'recovered',
                    'message': 'Recovery task scheduled'
                })
            except Exception as e:
                logger.error(f"Error monitoring match {match_data['match_id']}: {str(e)}")
                monitoring_results.append({
                    'match_id': match_data['match_id'],
                    'status': 'error',
                    'error': str(e)
                })

        # Update monitoring status in database
        with db_manager.session_scope(transaction_name='update_monitoring_status') as session:
            for result in monitoring_results:
                match = session.query(MLSMatch).filter_by(
                    match_id=result['match_id']
                ).first()
                
                if match:
                    match.last_monitoring_check = datetime.utcnow()
                    match.monitoring_status = result['status']
                    if 'error' in result:
                        match.last_monitoring_error = result['error']

        return {
            'success': True,
            'message': f'Monitored {len(active_matches_data)} matches',
            'monitoring_results': monitoring_results,
            'timestamp': datetime.utcnow().isoformat()
        }

    except SQLAlchemyError as e:
        logger.error(f"Database error in monitor_all_matches: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error in monitor_all_matches: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)

@celery_transactional_task(
    name='app.tasks.tasks_live_reporting.verify_scheduled_tasks',
    queue='live_reporting',
    bind=True,
    max_retries=3
)
def verify_scheduled_tasks(self, match_id: str) -> Dict[str, Any]:
    """Verify scheduled tasks for a specific match."""
    try:
        # Get match details
        with db_manager.session_scope(transaction_name='verify_match_tasks') as session:
            match = session.query(MLSMatch).options(
                joinedload(MLSMatch.home_team),
                joinedload(MLSMatch.away_team)
            ).get(match_id)

            if not match:
                return {
                    'success': False,
                    'message': 'Match not found',
                    'verified_at': datetime.utcnow().isoformat()
                }

            match_data = {
                'id': match.id,
                'match_id': match.match_id,
                'opponent': match.opponent,
                'date_time': match.date_time,
                'thread_created': match.thread_created,
                'live_reporting_scheduled': match.live_reporting_scheduled,
                'live_reporting_status': match.live_reporting_status,
                'thread_creation_time': match.date_time - timedelta(hours=24),
                'reporting_start_time': match.date_time - timedelta(minutes=5)
            }

            # Update verification timestamp
            match.last_verification = datetime.utcnow()
            session.flush()

        # Get Redis client from Flask app context
        redis_client = current_app.extensions.get('redis') or current_app.config['SESSION_REDIS']

        # Check Redis tasks outside database session
        thread_key = f"match_scheduler:{match_id}:thread"
        reporting_key = f"match_scheduler:{match_id}:reporting"

        thread_task_id = redis_client.get(thread_key)
        reporting_task_id = redis_client.get(reporting_key)

        verification_result = {
            'match_details': {
                'id': match_data['id'],
                'opponent': match_data['opponent'],
                'match_time': match_data['date_time'].isoformat(),
                'thread_creation_time': match_data['thread_creation_time'].isoformat(),
                'reporting_start_time': match_data['reporting_start_time'].isoformat()
            },
            'scheduled_tasks': {
                'thread_task_id': thread_task_id.decode('utf-8') if thread_task_id else None,
                'reporting_task_id': reporting_task_id.decode('utf-8') if reporting_task_id else None,
                'thread_created': match_data['thread_created'],
                'live_reporting_scheduled': match_data['live_reporting_scheduled'],
                'live_reporting_status': match_data['live_reporting_status']
            },
            'verification_time': datetime.utcnow().isoformat()
        }

        # Log verification results
        logger.info(f"Task verification completed for match {match_id}", extra={
            'verification_result': verification_result
        })

        return {
            'success': True,
            'message': 'Tasks verified successfully',
            **verification_result
        }

    except SQLAlchemyError as e:
        logger.error(f"Database error verifying tasks: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error verifying tasks: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)

async def end_match_reporting(match_id: str) -> Dict[str, Any]:
    """Helper function to end match reporting and cleanup."""
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        def update_match_status_sync():
            from app import create_app
            app = create_app()
            
            with app.app_context():
                with db_manager.session_scope(transaction_name='end_match_reporting') as session:
                    match = session.query(MLSMatch).filter_by(match_id=match_id).first()
                    if match:
                        match.live_reporting_status = 'completed'
                        match.live_reporting_started = False
                        match.completed_at = datetime.utcnow()
                        match.final_update_time = datetime.utcnow()
                        
                        # Archive match data if needed
                        match.archived = True
                        match.archived_at = datetime.utcnow()
                        
                        session.flush()
                        return {
                            'match_id': match.match_id,
                            'opponent': match.opponent,
                            'final_score': match.current_score
                        }
                    return None

        result = await asyncio.get_event_loop().run_in_executor(executor, update_match_status_sync)
        if result:
            logger.info(f"Match {match_id} reporting ended successfully", extra={
                'match_data': result
            })
            return {
                'success': True,
                'message': 'Match reporting ended successfully',
                'data': result
            }
        else:
            logger.error(f"Match {match_id} not found during end reporting")
            return {
                'success': False,
                'message': 'Match not found'
            }

    except SQLAlchemyError as e:
        logger.error(f"Database error ending match reporting: {str(e)}", exc_info=True)
        return {
            'success': False,
            'message': f'Database error: {str(e)}'
        }
    except Exception as e:
        logger.error(f"Error ending match reporting: {str(e)}", exc_info=True)
        return {
            'success': False,
            'message': str(e)
        }
    finally:
        executor.shutdown()

@celery_transactional_task(
    name='app.tasks.tasks_live_reporting.check_upcoming_matches',
    queue='live_reporting',
    bind=True,
    max_retries=3
)
def check_upcoming_matches(self) -> Dict[str, Any]:
    """Check for upcoming matches that need scheduling."""
    try:
        redis_client = current_app.extensions.get('redis')
        if not redis_client:
            redis_client = current_app.config['SESSION_REDIS']

        executor = ThreadPoolExecutor(max_workers=1)

        # Get matches from database
        with db_manager.session_scope(transaction_name='get_upcoming_matches') as session:
            future_time = datetime.utcnow() + timedelta(hours=48)
            matches = session.query(MLSMatch).filter(
                MLSMatch.date_time <= future_time,
                MLSMatch.date_time >= datetime.utcnow(),
                MLSMatch.live_reporting_scheduled.is_(False)
            ).all()

            matches_data = [{
                'id': match.id,
                'match_id': match.match_id,
                'date_time': match.date_time,
                'opponent': match.opponent
            } for match in matches]

        scheduler = MatchScheduler(redis_client)
        monitoring_status = scheduler.monitor_scheduled_tasks()

        if not monitoring_status['success']:
            logger.error(f"Failed to monitor tasks: {monitoring_status.get('message')}")
            return monitoring_status

        scheduled_tasks = monitoring_status.get('scheduled_tasks', {})
        logger.info(f"Found {len(scheduled_tasks)} existing scheduled tasks")

        scheduled_count = 0
        scheduling_results = []

        for match_data in matches_data:
            match_tasks = scheduled_tasks.get(str(match_data['id']), {})
            if 'thread' not in match_tasks and 'reporting' not in match_tasks:
                logger.info(f"Scheduling new tasks for match {match_data['id']}")
                
                def schedule_match_sync(match_id):
                    from app import create_app
                    app = create_app()
                    
                    with app.app_context():
                        result = scheduler.schedule_match_tasks(match_id)
                        if result['success']:
                            # Update database with scheduling info
                            with db_manager.session_scope(transaction_name='update_match_scheduling') as session:
                                match = session.query(MLSMatch).get(match_id)
                                if match:
                                    match.live_reporting_scheduled = True
                                    match.scheduling_time = datetime.utcnow()
                                    session.flush()
                        return result

                result = executor.submit(schedule_match_sync, match_data['id']).result()
                
                if result['success']:
                    scheduled_count += 1
                    scheduling_results.append({
                        'match_id': match_data['match_id'],
                        'opponent': match_data['opponent'],
                        'status': 'scheduled',
                        'scheduled_for': match_data['date_time'].isoformat()
                    })
                    logger.info(f"Scheduled match {match_data['id']} successfully: {result}")
                else:
                    logger.error(f"Failed to schedule match {match_data['id']}: {result['message']}")
                    scheduling_results.append({
                        'match_id': match_data['match_id'],
                        'opponent': match_data['opponent'],
                        'status': 'failed',
                        'error': result['message']
                    })
            else:
                logger.info(f"Match {match_data['id']} already has tasks scheduled: {match_tasks}")

        return {
            'success': True,
            'message': f'Scheduled {scheduled_count} matches',
            'scheduled_count': scheduled_count,
            'existing_tasks': len(scheduled_tasks),
            'scheduling_results': scheduling_results,
            'checked_at': datetime.utcnow().isoformat()
        }

    except SQLAlchemyError as e:
        logger.error(f"Database error checking upcoming matches: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error checking upcoming matches: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)
    finally:
        if 'executor' in locals():
            executor.shutdown()

@celery_transactional_task(
    name='app.tasks.tasks_live_reporting.schedule_live_reporting',
    bind=True,
    queue='live_reporting',
    max_retries=3
)
def schedule_live_reporting(self) -> Dict[str, Any]:
    """Schedule live reporting for upcoming matches."""
    try:
        # Get upcoming matches
        with db_manager.session_scope(transaction_name='get_upcoming_schedule') as session:
            now = datetime.utcnow()
            matches = session.query(MLSMatch).options(
                joinedload(MLSMatch.home_team),
                joinedload(MLSMatch.away_team)
            ).filter(
                MLSMatch.date_time >= now,
                MLSMatch.date_time <= now + timedelta(hours=24),
                MLSMatch.live_reporting_started == False,
                MLSMatch.live_reporting_scheduled == False
            ).all()

            upcoming_matches = [{
                'id': match.id,
                'match_id': match.match_id,
                'date_time': match.date_time,
                'opponent': match.opponent
            } for match in matches]

        scheduled_count = 0
        schedule_results = []
        match_ids = []

        # Schedule each match
        for match_data in upcoming_matches:
            try:
                time_diff = match_data['date_time'] - now
                
                # Schedule the live reporting task
                start_live_reporting.apply_async(
                    args=[match_data['match_id']],
                    countdown=max(0, int(time_diff.total_seconds())),
                    queue='live_reporting',
                    expires=match_data['date_time'] + timedelta(hours=4)  # Task expires 4 hours after match time
                )
                
                match_ids.append(match_data['match_id'])
                scheduled_count += 1
                
                schedule_results.append({
                    'match_id': match_data['match_id'],
                    'opponent': match_data['opponent'],
                    'scheduled_time': match_data['date_time'].isoformat(),
                    'status': 'scheduled'
                })
                
                logger.info(f"Scheduled live reporting for match {match_data['match_id']} vs {match_data['opponent']}")
                
            except Exception as e:
                logger.error(f"Failed to schedule match {match_data['match_id']}: {str(e)}")
                schedule_results.append({
                    'match_id': match_data['match_id'],
                    'opponent': match_data['opponent'],
                    'status': 'failed',
                    'error': str(e)
                })

        # Update database for successfully scheduled matches
        if match_ids:
            with db_manager.session_scope(transaction_name='update_scheduled_matches') as session:
                matches = session.query(MLSMatch).filter(
                    MLSMatch.match_id.in_(match_ids)
                ).all()
                
                for match in matches:
                    match.live_reporting_scheduled = True
                    match.scheduling_time = datetime.utcnow()
                    match.schedule_status = 'scheduled'
                
                session.flush()

        result = {
            'success': True,
            'message': f'Scheduled {scheduled_count} matches for reporting',
            'scheduled_count': scheduled_count,
            'total_checked': len(upcoming_matches),
            'scheduled_matches': schedule_results,
            'scheduled_at': datetime.utcnow().isoformat()
        }

        # Log final results
        logger.info("Live reporting scheduling completed", extra={
            'scheduled_count': scheduled_count,
            'total_matches': len(upcoming_matches),
            'failed_count': len(upcoming_matches) - scheduled_count
        })

        return result

    except SQLAlchemyError as e:
        logger.error(f"Database error scheduling live reporting: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error scheduling live reporting: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)

@celery_transactional_task(
    name='app.tasks.tasks_live_reporting.schedule_mls_thread_task',
    queue='live_reporting',
    bind=True,
    max_retries=2
)
def schedule_mls_thread_task(self, match_id: int, hours_before: int = 24) -> Dict[str, Any]:
    """Schedule creation of Discord thread for MLS match."""
    try:
        with db_manager.session_scope(transaction_name='schedule_mls_thread') as session:
            match = session.query(MLSMatch).options(
                joinedload(MLSMatch.home_team),
                joinedload(MLSMatch.away_team)
            ).get(match_id)

            if not match:
                logger.error(f"Match {match_id} not found")
                return {
                    'success': False,
                    'message': f'Match {match_id} not found'
                }

            # Calculate thread creation time
            thread_time = match.date_time - timedelta(hours=hours_before)
            match.thread_creation_time = thread_time
            match.thread_scheduling_status = 'scheduled'
            match.last_scheduling_update = datetime.utcnow()
            
            session.flush()

            result_data = {
                'match_id': match.match_id,
                'opponent': match.opponent,
                'thread_creation_time': thread_time.isoformat(),
                'match_time': match.date_time.isoformat()
            }

        logger.info(f"Scheduled thread creation for match {match_id}", extra=result_data)
        
        return {
            'success': True,
            'message': f'Match thread for {result_data["opponent"]} scheduled for {result_data["thread_creation_time"]}',
            'data': result_data
        }

    except SQLAlchemyError as e:
        logger.error(f"Database error scheduling MLS thread: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error scheduling MLS thread: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)

@celery_transactional_task(
    name='app.tasks.tasks_live_reporting.schedule_all_mls_threads_task',
    queue='live_reporting',
    bind=True,
    max_retries=2
)
def schedule_all_mls_threads_task(self, default_hours_before: int = 24) -> Dict[str, Any]:
    """Schedule thread creation for all unscheduled MLS matches."""
    try:
        # Get unscheduled matches
        with db_manager.session_scope(transaction_name='get_unscheduled_matches') as session:
            matches = session.query(MLSMatch).options(
                joinedload(MLSMatch.home_team),
                joinedload(MLSMatch.away_team)
            ).filter(
                MLSMatch.thread_created == False,
                MLSMatch.thread_creation_time.is_(None)
            ).all()

            matches_data = [{
                'id': match.id,
                'match_id': match.match_id,
                'opponent': match.opponent,
                'date_time': match.date_time
            } for match in matches]

        scheduled_matches = []
        failed_matches = []

        # Schedule each match
        for match_data in matches_data:
            try:
                # Use apply_async for more control over task execution
                schedule_mls_thread_task.apply_async(
                    kwargs={
                        'match_id': match_data['id'],
                        'hours_before': default_hours_before
                    },
                    countdown=5 * len(scheduled_matches),  # Stagger the scheduling
                    expires=match_data['date_time'] - timedelta(hours=default_hours_before+1)
                )
                
                scheduled_matches.append({
                    'match_id': match_data['match_id'],
                    'opponent': match_data['opponent'],
                    'scheduled_time': (
                        match_data['date_time'] - timedelta(hours=default_hours_before)
                    ).isoformat(),
                    'match_time': match_data['date_time'].isoformat()
                })
                
                logger.info(f"Scheduled thread for match {match_data['match_id']} vs {match_data['opponent']}")
                
            except Exception as e:
                error_msg = f"Failed to schedule thread for match {match_data['id']}: {str(e)}"
                logger.error(error_msg)
                failed_matches.append({
                    'match_id': match_data['match_id'],
                    'opponent': match_data['opponent'],
                    'error': str(e)
                })

        result = {
            'success': True,
            'message': f'Successfully scheduled {len(scheduled_matches)} match threads',
            'scheduled_count': len(scheduled_matches),
            'failed_count': len(failed_matches),
            'scheduled_matches': scheduled_matches,
            'failed_matches': failed_matches,
            'scheduled_at': datetime.utcnow().isoformat()
        }

        logger.info("Completed scheduling all MLS threads", extra={
            'scheduled_count': len(scheduled_matches),
            'failed_count': len(failed_matches)
        })

        return result

    except SQLAlchemyError as e:
        logger.error(f"Database error scheduling all MLS threads: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error scheduling all MLS threads: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)









def force_create_mls_thread_task(self, match_id: str) -> Dict[str, Any]:
    """Force immediate creation of Discord thread for MLS match."""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_force_create_mls_thread_async(match_id))
            return result
        finally:
            loop.close()
    except Exception as e:
        logger.error(f"Error forcing thread creation: {str(e)}", exc_info=True)
        raise self.retry(exc=e)

async def _force_create_mls_thread_async(match_id: str) -> Dict[str, Any]:
    """Async helper for force_create_mls_thread_task."""
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        def get_match_data_sync() -> Optional[Dict[str, Any]]:
            from app import create_app
            app = create_app()
            
            with app.app_context():
                with session_context():
                    match = db.session.query(MLSMatch).options(
                        joinedload(MLSMatch.home_team),
                        joinedload(MLSMatch.away_team)
                    ).filter_by(match_id=match_id).first()

                    if not match:
                        return None

                    return {
                        'id': match.id,
                        'match_id': match.match_id,
                        'thread_created': match.thread_created,
                        'opponent': match.opponent,
                        'home_team': {
                            'name': match.home_team.name,
                            'channel_id': match.home_team.discord_channel_id
                        },
                        'away_team': {
                            'name': match.away_team.name,
                            'channel_id': match.away_team.discord_channel_id
                        },
                        'date': match.date,
                        'time': match.time
                    }

        match_data = await asyncio.get_event_loop().run_in_executor(executor, get_match_data_sync)
        if not match_data:
            logger.error(f"Match {match_id} not found")
            return {
                'success': False,
                'message': f'Match {match_id} not found'
            }

        if match_data['thread_created']:
            logger.info(f"Thread already exists for match {match_id}")
            return {
                'success': True,
                'message': f"Thread already exists for match against {match_data['opponent']}"
            }

        thread_id = await create_match_thread(match_data)
        if not thread_id:
            logger.error(f"Failed to create thread for match {match_id}")
            return {
                'success': False,
                'message': 'Failed to create thread'
            }

        def update_thread_status_sync():
            from app import create_app
            app = create_app()
            
            with app.app_context():
                with session_context():
                    match = db.session.query(MLSMatch).get(match_data['id'])
                    if match:
                        match.thread_created = True
                        match.discord_thread_id = thread_id

        await asyncio.get_event_loop().run_in_executor(executor, update_thread_status_sync)
        logger.info(f"Created thread {thread_id} for match {match_id}")

        return {
            'success': True,
            'message': f'Thread created successfully. ID: {thread_id}',
            'thread_id': thread_id
        }

    finally:
        executor.shutdown()