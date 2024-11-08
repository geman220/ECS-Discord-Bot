# app/tasks/tasks_live_reporting.py

import logging
import asyncio
import aiohttp
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Union
from app.extensions import socketio
from app.decorators import celery_task, session_context, db_operation, query_operation
from app.models import MLSMatch
from app.match_scheduler import MatchScheduler
from app.match_api import process_live_match_updates
from app.discord_utils import create_match_thread
from app.api_utils import fetch_espn_data
from sqlalchemy.orm import joinedload
from redis import Redis
from flask import current_app

logger = logging.getLogger(__name__)

@celery_task(
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
    except Exception as e:
        logger.error(f"Error in process_match_update: {str(e)}", exc_info=True)
        raise self.retry(exc=e)

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
                with session_context():
                    match = db.session.query(MLSMatch).options(
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
                    with session_context():
                        match = db.session.query(MLSMatch).get(match_id)
                        if match:
                            match.live_reporting_status = 'completed'
                            match.live_reporting_started = False
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

        return {
            'success': True,
            'message': 'Update processed',
            'status': 'running',
            'score': new_score,
            'match_status': new_status,
            'current_event_keys': current_event_keys
        }

    finally:
        executor.shutdown()

@celery_task(
    name='app.tasks.tasks_live_reporting.start_live_reporting',
    bind=True,
    queue='live_reporting'
)
def start_live_reporting(self, match_id: str) -> Dict[str, Any]:
    """Start live match reporting."""
    try:
        with session_context():
            @query_operation
            def get_match_data() -> Optional[Dict[str, Any]]:
                match = db.session.query(MLSMatch).options(
                    joinedload(MLSMatch.home_team),
                    joinedload(MLSMatch.away_team)
                ).filter_by(match_id=match_id).first()

                if not match:
                    return None

                return {
                    'id': match.id,
                    'match_id': match.match_id,
                    'opponent': match.opponent,
                    'discord_thread_id': match.discord_thread_id,
                    'competition': match.competition,
                    'live_reporting_status': match.live_reporting_status
                }

            match_data = get_match_data()
            if not match_data:
                return {
                    'success': False,
                    'message': f'Match {match_id} not found'
                }

            if match_data['live_reporting_status'] == 'running':
                return {
                    'success': False,
                    'message': 'Live reporting already running'
                }

            @db_operation
            def update_match_status() -> Optional[Dict[str, Any]]:
                match = db.session.query(MLSMatch).filter_by(match_id=match_id).first()
                if match:
                    match.live_reporting_started = True
                    match.live_reporting_status = 'running'
                    return {
                        'match_id': match.match_id,
                        'discord_thread_id': match.discord_thread_id,
                        'competition': match.competition,
                        'status': match.live_reporting_status
                    }
                return None

            updated_data = update_match_status()
            if not updated_data:
                return {
                    'success': False,
                    'message': 'Failed to update match status'
                }

        process_match_update.delay(
            match_id=str(match_id),
            thread_id=str(updated_data['discord_thread_id']),
            last_status=None,
            last_score=None,
            last_event_keys=[]
        )

        return {
            'success': True,
            'message': 'Live reporting started successfully',
            'match_id': match_id,
            'thread_id': updated_data['discord_thread_id'],
            'status': updated_data['status']
        }

    except Exception as e:
        logger.error(f"Error in start_live_reporting: {str(e)}", exc_info=True)
        raise self.retry(exc=e)

@celery_task(
    name='app.tasks.tasks_live_reporting.create_match_thread_task',
    queue='live_reporting',
    bind=True
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
    except Exception as e:
        logger.error(f"Error creating match thread: {str(e)}", exc_info=True)
        raise self.retry(exc=e)

async def _create_match_thread_async(match_id: str) -> Dict[str, Any]:
    """Async helper for create_match_thread_task."""
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
            return {
                'success': False,
                'message': f'Match {match_id} not found'
            }

        if match_data['thread_created']:
            return {
                'success': True,
                'message': f'Thread already exists for match {match_id}'
            }

        thread_id = await create_match_thread(match_data)
        if not thread_id:
            return {
                'success': False,
                'message': 'Failed to create thread'
            }

        def update_thread_info_sync():
            from app import create_app
            app = create_app()
            
            with app.app_context():
                with session_context():
                    match = db.session.query(MLSMatch).get(match_id)
                    if match:
                        match.thread_created = True
                        match.discord_thread_id = thread_id

        await asyncio.get_event_loop().run_in_executor(executor, update_thread_info_sync)

        socketio.emit('thread_created', {
            'match_id': match_id,
            'thread_id': thread_id
        })

        return {
            'success': True,
            'message': 'Thread created successfully',
            'thread_id': thread_id
        }

    finally:
        executor.shutdown()

@celery_task(
    name='app.tasks.tasks_live_reporting.force_create_mls_thread_task',
    queue='live_reporting',
    bind=True
)
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

@celery_task(
    name='app.tasks.tasks_live_reporting.check_and_create_scheduled_threads',
    queue='live_reporting',
    bind=True
)
def check_and_create_scheduled_threads(self) -> Dict[str, Any]:
    """Check for and create scheduled match threads."""
    try:
        with session_context():
            @query_operation
            def get_due_matches_data() -> List[Dict[str, Any]]:
                now = datetime.utcnow()
                matches = db.session.query(MLSMatch).options(
                    joinedload(MLSMatch.home_team),
                    joinedload(MLSMatch.away_team)
                ).filter(
                    MLSMatch.thread_creation_time <= now,
                    MLSMatch.thread_created == False
                ).all()

                return [{
                    'id': match.id,
                    'match_id': match.match_id,
                    'thread_creation_time': match.thread_creation_time
                } for match in matches]

            due_matches_data = get_due_matches_data()

        # Schedule thread creation tasks outside of database session
        for match_data in due_matches_data:
            create_match_thread_task.delay(match_data['match_id'])

        return {
            'success': True,
            'message': f'Scheduled {len(due_matches_data)} match threads for creation',
            'scheduled_count': len(due_matches_data)
        }

    except Exception as e:
        logger.error(f"Error checking scheduled threads: {str(e)}", exc_info=True)
        raise self.retry(exc=e)

@celery_task(
    name='app.tasks.tasks_live_reporting.schedule_mls_thread_task',
    queue='live_reporting',
    bind=True,
    max_retries=2
)
def schedule_mls_thread_task(self, match_id: int, hours_before: int = 24) -> Dict[str, Any]:
    """Schedule creation of Discord thread for MLS match."""
    try:
        with session_context():
            @query_operation
            def get_match_data() -> Optional[Dict[str, Any]]:
                match = db.session.query(MLSMatch).options(
                    joinedload(MLSMatch.home_team),
                    joinedload(MLSMatch.away_team)
                ).get(match_id)

                if not match:
                    return None

                return {
                    'id': match.id,
                    'match_id': match.match_id,
                    'opponent': match.opponent,
                    'date_time': match.date_time
                }

            match_data = get_match_data()
            if not match_data:
                return {
                    'success': False,
                    'message': f'Match {match_id} not found'
                }

            @db_operation
            def update_thread_creation_time():
                match = db.session.query(MLSMatch).get(match_id)
                if match:
                    thread_time = match.date_time - timedelta(hours=hours_before)
                    match.thread_creation_time = thread_time
                    return {
                        'match_id': match.match_id,
                        'opponent': match.opponent,
                        'thread_creation_time': thread_time.isoformat()
                    }
                return None

            updated_data = update_thread_creation_time()
            if not updated_data:
                return {
                    'success': False,
                    'message': f'Failed to update match {match_id}'
                }

        return {
            'success': True,
            'message': f'Match thread for {updated_data["opponent"]} scheduled for {updated_data["thread_creation_time"]}'
        }

    except Exception as e:
        logger.error(f"Error scheduling MLS thread: {str(e)}", exc_info=True)
        raise self.retry(exc=e)

@celery_task(
    name='app.tasks.tasks_live_reporting.schedule_all_mls_threads_task',
    queue='live_reporting',
    bind=True,
    max_retries=2
)
def schedule_all_mls_threads_task(self, default_hours_before: int = 24) -> Dict[str, Any]:
    """Schedule thread creation for all unscheduled MLS matches."""
    try:
        with session_context():
            @query_operation
            def get_unscheduled_matches_data() -> List[Dict[str, Any]]:
                matches = db.session.query(MLSMatch).options(
                    joinedload(MLSMatch.home_team),
                    joinedload(MLSMatch.away_team)
                ).filter(
                    MLSMatch.thread_created == False,
                    MLSMatch.thread_creation_time.is_(None)
                ).all()

                return [{
                    'id': match.id,
                    'match_id': match.match_id,
                    'opponent': match.opponent,
                    'date_time': match.date_time
                } for match in matches]

            matches_data = get_unscheduled_matches_data()
            
        scheduled_matches = []
        for match_data in matches_data:
            try:
                schedule_mls_thread_task.delay(match_data['id'], default_hours_before)
                scheduled_matches.append({
                    'match_id': match_data['match_id'],
                    'opponent': match_data['opponent'],
                    'scheduled_time': (
                        match_data['date_time'] - timedelta(hours=default_hours_before)
                    ).isoformat()
                })
            except Exception as e:
                logger.error(f"Failed to schedule thread for match {match_data['id']}: {str(e)}")

        return {
            'success': True,
            'message': f'Successfully scheduled {len(scheduled_matches)} match threads',
            'scheduled_count': len(scheduled_matches),
            'scheduled_matches': scheduled_matches
        }

    except Exception as e:
        logger.error(f"Error scheduling all MLS threads: {str(e)}", exc_info=True)
        raise self.retry(exc=e)

@celery_task(
    name='app.tasks.tasks_live_reporting.monitor_all_matches',
    queue='live_reporting',
    bind=True
)
def monitor_all_matches(self) -> Dict[str, Any]:
    """Monitor and verify all scheduled match tasks."""
    try:
        with session_context():
            @query_operation
            def get_active_matches_data() -> List[Dict[str, Any]]:
                matches = db.session.query(MLSMatch).options(
                    joinedload(MLSMatch.home_team),
                    joinedload(MLSMatch.away_team)
                ).filter(
                    MLSMatch.live_reporting_scheduled == True,
                    MLSMatch.live_reporting_status.in_(['scheduled', 'running'])
                ).all()

                return [{
                    'id': match.id,
                    'match_id': match.match_id,
                    'status': match.live_reporting_status,
                    'home_team_id': match.home_team_id,
                    'away_team_id': match.away_team_id
                } for match in matches]

            matches_data = get_active_matches_data()

        # Perform monitoring outside of session
        monitoring_result = task_monitor.monitor_matches(matches_data)

        if not monitoring_result['success']:
            logger.error(f"Task monitoring failed: {monitoring_result.get('message')}")
            return monitoring_result

        # Update database in fresh session
        with session_context():
            @db_operation
            def update_match_statuses():
                for match_id, status in monitoring_result['matches'].items():
                    match = db.session.query(MLSMatch).get(match_id)
                    if match:
                        match.monitoring_status = 'error' if not status['success'] else 'ok'
                        match.last_monitoring_error = status.get('message') if not status['success'] else None

            update_match_statuses()

        return monitoring_result

    except Exception as e:
        logger.error(f"Error in monitor_all_matches: {str(e)}", exc_info=True)
        raise self.retry(exc=e)

async def end_match_reporting(match_id: str) -> None:
    """Helper function to end match reporting and cleanup."""
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        def update_match_status_sync():
            from app import create_app
            app = create_app()
            
            with app.app_context():
                with session_context():
                    match = db.session.query(MLSMatch).filter_by(match_id=match_id).first()
                    if match:
                        match.live_reporting_status = 'completed'
                        match.live_reporting_started = False

        await asyncio.get_event_loop().run_in_executor(executor, update_match_status_sync)
        logger.info(f"Live reporting ended for match {match_id}")

    except Exception as e:
        logger.error(f"Error ending match reporting: {str(e)}")
    finally:
        executor.shutdown()

@celery_task(
    name='app.tasks.tasks_live_reporting.verify_scheduled_tasks',
    queue='live_reporting',
    bind=True
)
def verify_scheduled_tasks(self, match_id: str) -> Dict[str, Any]:
    """Verify scheduled tasks for a specific match."""
    try:
        with session_context():
            @query_operation
            def get_match_details() -> Optional[Dict[str, Any]]:
                match = db.session.query(MLSMatch).options(
                    joinedload(MLSMatch.home_team),
                    joinedload(MLSMatch.away_team)
                ).get(match_id)

                if not match:
                    return None

                return {
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

            match_data = get_match_details()
            if not match_data:
                return {'success': False, 'message': 'Match not found'}

        # Get Redis client from Flask app context
        redis_client = current_app.extensions.get('redis') or current_app.config['SESSION_REDIS']

        # Check Redis tasks outside database session
        thread_key = f"match_scheduler:{match_id}:thread"
        reporting_key = f"match_scheduler:{match_id}:reporting"

        task_data = {
            'thread_task_id': redis_client.get(thread_key),
            'reporting_task_id': redis_client.get(reporting_key)
        }

        return {
            'success': True,
            'match_details': {
                'id': match_data['id'],
                'opponent': match_data['opponent'],
                'match_time': match_data['date_time'].isoformat(),
                'thread_creation_time': match_data['thread_creation_time'].isoformat(),
                'reporting_start_time': match_data['reporting_start_time'].isoformat()
            },
            'scheduled_tasks': {
                'thread_task_id': task_data['thread_task_id'].decode('utf-8') if task_data['thread_task_id'] else None,
                'reporting_task_id': task_data['reporting_task_id'].decode('utf-8') if task_data['reporting_task_id'] else None,
                'thread_created': match_data['thread_created'],
                'live_reporting_scheduled': match_data['live_reporting_scheduled'],
                'live_reporting_status': match_data['live_reporting_status']
            }
        }

    except Exception as e:
        logger.error(f"Task verification failed: {str(e)}", exc_info=True)
        raise self.retry(exc=e)

@celery_task(
    name='app.tasks.tasks_live_reporting.verify_redis_tasks',
    queue='live_reporting',
    bind=True
)
def verify_redis_tasks(self) -> Dict[str, Any]:
    """Verify Redis task entries and clean up stale ones."""
    try:
        from celery.result import AsyncResult
        from app.utils.redis_manager import RedisManager

        redis_client = RedisManager().client
        scheduler_keys = redis_client.keys('match_scheduler:*')
        executor = ThreadPoolExecutor(max_workers=1)

        results = {
            'checked': len(scheduler_keys),
            'valid': 0,
            'cleaned': 0,
            'errors': [],
            'processed_matches': []
        }

        for key in scheduler_keys:
            try:
                key_str = key.decode('utf-8')
                task_id = redis_client.get(key)

                if task_id:
                    task_id = task_id.decode('utf-8')
                    match_id = key_str.split(':')[1]

                    def check_match_status_sync():
                        from app import create_app
                        app = create_app()
                        
                        with app.app_context():
                            with session_context():
                                match = db.session.query(MLSMatch).get(match_id)
                                if match:
                                    return {
                                        'id': match.id,
                                        'match_id': match.match_id,
                                        'thread_created': match.thread_created,
                                        'live_reporting_scheduled': match.live_reporting_scheduled
                                    }
                                return None

                    match_data = executor.submit(check_match_status_sync).result()

                    if not match_data:
                        redis_client.delete(key)
                        results['cleaned'] += 1
                        continue

                    status = AsyncResult(task_id).status

                    if status in ['FAILURE', 'REVOKED']:
                        redis_client.delete(key)
                        results['cleaned'] += 1

                        def reset_match_status_sync():
                            from app import create_app
                            app = create_app()
                            
                            with app.app_context():
                                with session_context():
                                    match = db.session.query(MLSMatch).get(match_id)
                                    if match:
                                        if 'thread' in key_str:
                                            match.thread_created = False
                                        elif 'reporting' in key_str:
                                            match.live_reporting_scheduled = False

                        executor.submit(reset_match_status_sync).result()

                        results['processed_matches'].append({
                            'match_id': match_data['match_id'],
                            'action': 'reset',
                            'task_type': 'thread' if 'thread' in key_str else 'reporting'
                        })
                    else:
                        results['valid'] += 1
                        results['processed_matches'].append({
                            'match_id': match_data['match_id'],
                            'status': status,
                            'task_type': 'thread' if 'thread' in key_str else 'reporting'
                        })
                else:
                    redis_client.delete(key)
                    results['cleaned'] += 1

            except Exception as e:
                error_msg = f"Error processing key {key_str}: {str(e)}"
                logger.error(error_msg)
                results['errors'].append(error_msg)

        return {
            'success': True,
            'results': results
        }

    except Exception as e:
        logger.error(f"Error in verify_redis_tasks: {str(e)}", exc_info=True)
        raise self.retry(exc=e)
    finally:
        if 'executor' in locals():
            executor.shutdown()

@celery_task(
    name='app.tasks.tasks_live_reporting.recover_failed_matches',
    queue='live_reporting',
    bind=True
)
def recover_failed_matches(self) -> Dict[str, Any]:
    """Attempt to recover matches that failed during live reporting."""
    try:
        with session_context():
            @query_operation
            def get_failed_matches():
                return db.session.query(MLSMatch).filter(
                    MLSMatch.live_reporting_status == 'failed'
                ).all()

            failed_matches = get_failed_matches()

        recovery_results = []
        recovered_count = 0

        for match in failed_matches:
            with session_context():
                @db_operation
                def reset_match_status() -> Optional[Dict[str, Any]]:
                    match_update = db.session.query(MLSMatch).get(match.id)
                    if match_update:
                        match_update.live_reporting_status = 'not_started'
                        match_update.live_reporting_started = False
                        match_update.live_reporting_scheduled = False
                        return {
                            'id': match_update.id,
                            'match_id': match_update.match_id,
                            'opponent': match_update.opponent
                        }
                    return None

                reset_data = reset_match_status()

            if reset_data:
                try:
                    # Schedule new reporting task
                    start_live_reporting.delay(reset_data['match_id'])
                    recovered_count += 1
                    recovery_results.append({
                        'match_id': reset_data['match_id'],
                        'opponent': reset_data['opponent'],
                        'status': 'recovered'
                    })
                except Exception as e:
                    recovery_results.append({
                        'match_id': reset_data['match_id'],
                        'opponent': reset_data['opponent'],
                        'status': 'failed',
                        'error': str(e)
                    })

        return {
            'success': True,
            'message': f'Recovered {recovered_count} failed matches',
            'recovered_count': recovered_count,
            'total_attempts': len(failed_matches),
            'recovery_results': recovery_results
        }

    except Exception as e:
        logger.error(f"Error recovering failed matches: {str(e)}", exc_info=True)
        raise self.retry(exc=e)

@celery_task(
    name='app.tasks.tasks_live_reporting.check_upcoming_matches',
    queue='live_reporting',
    bind=True
)
def check_upcoming_matches(self) -> Dict[str, Any]:
    """Check for upcoming matches that need scheduling."""
    try:
        redis_client = current_app.extensions.get('redis')
        if not redis_client:
            redis_client = current_app.config['SESSION_REDIS']

        executor = ThreadPoolExecutor(max_workers=1)

        def get_matches_sync() -> List[Dict[str, Any]]:
            from app import create_app
            app = create_app()
            
            with app.app_context():
                with session_context():
                    future_time = datetime.utcnow() + timedelta(hours=48)
                    matches = db.session.query(MLSMatch).filter(
                        MLSMatch.date_time <= future_time,
                        MLSMatch.date_time >= datetime.utcnow(),
                        MLSMatch.live_reporting_scheduled.is_(False)
                    ).all()

                    return [{
                        'id': match.id,
                        'match_id': match.match_id,
                        'date_time': match.date_time
                    } for match in matches]

        matches_data = executor.submit(get_matches_sync).result()

        scheduler = MatchScheduler(redis_client)
        monitoring_status = scheduler.monitor_scheduled_tasks()

        if not monitoring_status['success']:
            logger.error(f"Failed to monitor tasks: {monitoring_status.get('message')}")
            return monitoring_status

        scheduled_tasks = monitoring_status.get('scheduled_tasks', {})
        logger.info(f"Found {len(scheduled_tasks)} existing scheduled tasks")

        scheduled_count = 0
        for match_data in matches_data:
            match_tasks = scheduled_tasks.get(str(match_data['id']), {})
            if 'thread' not in match_tasks and 'reporting' not in match_tasks:
                logger.info(f"Scheduling new tasks for match {match_data['id']}")
                
                def schedule_match_sync(match_id):
                    from app import create_app
                    app = create_app()
                    
                    with app.app_context():
                        result = scheduler.schedule_match_tasks(match_id)
                        return result

                result = executor.submit(schedule_match_sync, match_data['id']).result()
                
                if result['success']:
                    scheduled_count += 1
                    logger.info(f"Scheduled match {match_data['id']} successfully: {result}")
                else:
                    logger.error(f"Failed to schedule match {match_data['id']}: {result['message']}")
            else:
                logger.info(f"Match {match_data['id']} already has tasks scheduled: {match_tasks}")

        return {
            'success': True,
            'message': f'Scheduled {scheduled_count} matches',
            'scheduled_count': scheduled_count,
            'existing_tasks': len(scheduled_tasks)
        }

    except Exception as e:
        logger.error(f"Error checking upcoming matches: {str(e)}", exc_info=True)
        raise self.retry(exc=e)
    finally:
        if 'executor' in locals():
            executor.shutdown()

@celery_task(
    name='app.tasks.tasks_live_reporting.schedule_live_reporting',
    bind=True,
    queue='live_reporting'
)
def schedule_live_reporting(self) -> Dict[str, Any]:
    """Schedule live reporting for upcoming matches."""
    try:
        with session_context():
            @query_operation
            def get_upcoming_matches() -> List[Dict[str, Any]]:
                now = datetime.utcnow()
                matches = db.session.query(MLSMatch).filter(
                    MLSMatch.date_time >= now,
                    MLSMatch.date_time <= now + timedelta(hours=24),
                    MLSMatch.live_reporting_started == False,
                    MLSMatch.live_reporting_scheduled == False
                ).all()

                return [{
                    'id': match.id,
                    'match_id': match.match_id,
                    'date_time': match.date_time
                } for match in matches]

            upcoming_matches = get_upcoming_matches()
            now = datetime.utcnow()
            scheduled_count = 0
            match_ids = []

            for match_data in upcoming_matches:
                time_diff = match_data['date_time'] - now
                start_live_reporting.apply_async(
                    args=[match_data['match_id']],
                    countdown=max(0, int(time_diff.total_seconds())),
                    queue='live_reporting'
                )
                match_ids.append(match_data['match_id'])
                scheduled_count += 1

            if match_ids:
                @db_operation
                def mark_matches_scheduled():
                    matches = db.session.query(MLSMatch).filter(
                        MLSMatch.match_id.in_(match_ids)
                    ).all()
                    for match in matches:
                        match.live_reporting_scheduled = True

                mark_matches_scheduled()

            return {
                'success': True,
                'message': f'Scheduled {scheduled_count} matches for reporting',
                'scheduled_count': scheduled_count,
                'scheduled_matches': match_ids
            }

    except Exception as e:
        logger.error(f"Error scheduling live reporting: {str(e)}", exc_info=True)
        raise self.retry(exc=e)
