# app/tasks/tasks_live_reporting.py

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import asyncio
from app.extensions import db, socketio
from app.decorators import celery_task, async_task
from app.models import MLSMatch
from app.match_api import process_live_match_updates
from app.discord_utils import create_match_thread
from app.api_utils import fetch_espn_data
from app.utils.match_events_utils import get_new_events

logger = logging.getLogger(__name__)

@celery_task(name='app.tasks.tasks_live_reporting.process_match_update', queue='live_reporting')
def process_match_update(self, match_id: str, thread_id: str, competition: str,
                        last_status: str = None, last_score: str = None,
                        last_event_keys: list = None) -> Dict[str, Any]:
    """Process a single match update iteration."""
    try:
        logger.info(f"Processing update for match {match_id}")
        
        match = MLSMatch.query.filter_by(match_id=match_id).first()
        if not match:
            logger.error(f"Match {match_id} not found")
            return {
                'success': False,
                'message': 'Match not found'
            }
            
        if match.live_reporting_status != 'running':
            logger.error(f"Match {match_id} not in running state")
            return {
                'success': False,
                'message': 'Match not in running state'
            }

        # Initialize last_event_keys if None
        last_event_keys = last_event_keys or []

        # Create event loop for async operations
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # Fetch match data
            full_url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{competition}/scoreboard/{match_id}"
            match_data = loop.run_until_complete(fetch_espn_data(full_url=full_url))

            if not match_data:
                logger.error(f"Failed to fetch data for match {match_id}")
                return {
                    'success': False,
                    'message': 'Failed to fetch match data'
                }

            # Process updates with event keys instead of full events
            match_ended, current_event_keys = loop.run_until_complete(process_live_match_updates(
                match_id=str(match_id),
                thread_id=thread_id,
                match_data=match_data,
                last_status=last_status,
                last_score=last_score,
                last_event_keys=last_event_keys
            ))

        finally:
            loop.close()

        if match_ended:
            logger.info(f"Match {match_id} has ended")
            match.live_reporting_status = 'completed'
            match.live_reporting_started = False
            db.session.commit()
            return {
                'success': True,
                'message': 'Match ended',
                'status': 'completed'
            }

        # Get new status and score for next update
        new_status = match_data["competitions"][0]["status"]["type"]["name"]
        home_score = match_data['competitions'][0]['competitors'][0]['score']
        away_score = match_data['competitions'][0]['competitors'][1]['score']
        new_score = f"{home_score}-{away_score}"

        logger.info(f"Scheduling next update for match {match_id}")
        
        # Schedule next update with current state and event keys
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

    except Exception as e:
        logger.error(f"Error in process_match_update: {str(e)}", exc_info=True)
        return {
            'success': False,
            'message': str(e)
        }

@celery_task(name='app.tasks.tasks_live_reporting.start_live_reporting', queue='live_reporting')
def start_live_reporting(self, match_id: str) -> Dict[str, Any]:
    """Start live match reporting."""
    try:
        logger.info(f"Starting live reporting for match_id: {match_id}")
        
        # Get match with thread ID
        match = MLSMatch.query.filter_by(match_id=match_id).first()
        
        if not match:
            logger.error(f"Match {match_id} not found")
            return {
                'success': False,
                'message': f'Match {match_id} not found'
            }
            
        logger.info(f"Found match {match_id}: {match.opponent}")
        logger.info(f"Thread ID: {match.discord_thread_id}")
        logger.info(f"Current status: {match.live_reporting_status}")
        
        if match.live_reporting_status == 'running':
            return {
                'success': False,
                'message': 'Live reporting already running'
            }

        # Initialize reporting
        match.live_reporting_started = True
        match.live_reporting_status = 'running'
        db.session.commit()
        
        logger.info(f"Updated match status to running")

        # Schedule the first update with empty event keys list
        process_match_update.delay(
            match_id=str(match_id),
            thread_id=str(match.discord_thread_id),
            competition=match.competition,
            last_status=None,
            last_score=None,
            last_event_keys=[]  # Initialize with empty list
        )
        
        return {
            'success': True,
            'message': 'Live reporting started successfully',
            'match_id': match.match_id,
            'thread_id': match.discord_thread_id,
            'status': match.live_reporting_status
        }

    except Exception as e:
        logger.error(f"Error in start_live_reporting: {str(e)}", exc_info=True)
        
        # Update match status on error
        try:
            if match:
                match.live_reporting_status = 'failed'
                match.live_reporting_started = False
                db.session.commit()
        except Exception as inner_e:
            logger.error(f"Error updating match status: {str(inner_e)}")
            
        return {
            'success': False,
            'message': str(e)
        }

@celery_task(name='app.tasks.tasks_live_reporting.schedule_live_reporting', queue='live_reporting')
def schedule_live_reporting(self) -> Dict[str, Any]:
    """Schedule live reporting for upcoming matches."""
    try:
        now = datetime.utcnow()
        upcoming_matches = MLSMatch.query.filter(
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

        db.session.commit()
        return {
            'success': True,
            'message': f'Scheduled {scheduled_count} matches for reporting',
            'scheduled_count': scheduled_count
        }

    except Exception as e:
        logger.error(f"Error scheduling live reporting: {str(e)}", exc_info=True)
        return {'success': False, 'message': str(e)}

@async_task(name='app.tasks.tasks_live_reporting.create_match_thread_task', queue='live_reporting')
async def create_match_thread_task(self, match_id: str) -> Dict[str, Any]:
    """Create match thread with proper error handling and retries."""
    try:
        match = MLSMatch.query.get(match_id)
        if not match:
            return {
                'success': False,
                'message': f'Match {match_id} not found'
            }

        if match.thread_created:
            return {
                'success': True,
                'message': f'Thread already exists for match {match_id}'
            }

        thread_id = await create_match_thread(match)
        if thread_id:
            match.thread_created = True
            match.discord_thread_id = thread_id
            db.session.commit()
            
            socketio.emit('thread_created', {
                'match_id': match_id,
                'thread_id': thread_id
            })
            
            return {
                'success': True,
                'message': f'Thread created successfully',
                'thread_id': thread_id
            }

        return {
            'success': False,
            'message': 'Failed to create thread'
        }

    except Exception as e:
        logger.error(f"Error creating match thread: {str(e)}", exc_info=True)
        return {'success': False, 'message': str(e)}

@celery_task(name='app.tasks.tasks_live_reporting.check_and_create_scheduled_threads', 
             queue='live_reporting')
def check_and_create_scheduled_threads(self) -> Dict[str, Any]:
    """Check for and create scheduled match threads."""
    try:
        now = datetime.utcnow()
        due_matches = MLSMatch.query.filter(
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

    except Exception as e:
        logger.error(f"Error checking scheduled threads: {str(e)}", exc_info=True)
        return {'success': False, 'message': str(e)}

@celery_task(name='app.tasks.tasks_live_reporting.force_create_mls_thread_task', bind_self=False)
def force_create_mls_thread_task(match_id: str):
    """Force immediate creation of Discord thread for MLS match."""
    try:
        logger.info(f"Starting thread creation for match {match_id}")
        
        # Get match from database
        match = MLSMatch.query.filter_by(match_id=match_id).first()
        if not match:
            logger.error(f"Match {match_id} not found")
            return {
                'success': False,
                'message': f'Match {match_id} not found'
            }

        if match.thread_created:
            logger.info(f"Thread already exists for match {match_id}")
            return {
                'success': True,
                'message': f'Thread already exists for match against {match.opponent}'
            }

        thread_id = asyncio.run(create_match_thread(match))
        if thread_id:
            match.thread_created = True
            match.discord_thread_id = thread_id
            db.session.commit()
            
            logger.info(f"Created thread {thread_id} for match {match_id}")
            
            return {
                'success': True,
                'message': f'Thread created successfully. ID: {thread_id}',
                'thread_id': thread_id
            }

        logger.error(f"Failed to create thread for match {match_id}")
        return {
            'success': False,
            'message': 'Failed to create thread'
        }

    except Exception as e:
        logger.error(f"Error creating thread for match {match_id}: {str(e)}", exc_info=True)
        return {
            'success': False,
            'message': str(e)
        }

@celery_task(name='app.tasks.tasks_live_reporting.schedule_mls_thread_task', 
             queue='live_reporting', max_retries=2)
def schedule_mls_thread_task(self, match_id: int, hours_before: int = 24) -> Dict[str, Any]:
    """Schedule creation of Discord thread for MLS match."""
    try:
        match = MLSMatch.query.get(match_id)
        if not match:
            return {
                'success': False,
                'message': f'Match {match_id} not found'
            }

        match.thread_creation_time = match.date_time - timedelta(hours=hours_before)
        db.session.commit()

        return {
            'success': True,
            'message': f'Match thread for {match.opponent} scheduled for {match.thread_creation_time}'
        }

    except Exception as e:
        logger.error(f"Error scheduling MLS thread: {str(e)}", exc_info=True)
        return {'success': False, 'message': str(e)}

@celery_task(name='app.tasks.tasks_live_reporting.schedule_all_mls_threads_task', 
             queue='live_reporting', max_retries=2)
def schedule_all_mls_threads_task(self, default_hours_before: int = 24) -> Dict[str, Any]:
    """Schedule thread creation for all unscheduled MLS matches."""
    try:
        matches = MLSMatch.query.filter(
            MLSMatch.thread_created == False,
            MLSMatch.thread_creation_time.is_(None)
        ).all()
        
        for match in matches:
            schedule_mls_thread_task.delay(match.id, default_hours_before)
        
        return {
            'success': True,
            'message': f'Successfully scheduled {len(matches)} match threads',
            'scheduled_count': len(matches)
        }

    except Exception as e:
        logger.error(f"Error scheduling all MLS threads: {str(e)}", exc_info=True)
        return {'success': False, 'message': str(e)}

async def end_match_reporting(match_id: str) -> None:
    """End match reporting and cleanup."""
    try:
        match = MLSMatch.query.filter_by(match_id=match_id).first()
        if match:
            match.live_reporting_status = 'completed'
            match.live_reporting_started = False
            db.session.commit()
            logger.info(f"Live reporting ended for match {match_id}")
    except Exception as e:
        logger.error(f"Error ending match reporting: {str(e)}")

@celery_task(name='app.tasks.tasks_live_reporting.check_upcoming_matches', queue='live_reporting')
def check_upcoming_matches(self) -> Dict[str, Any]:
    """Check for upcoming matches that need scheduling."""
    try:
        from flask import current_app
        
        # Get Redis client from app context
        redis_client = current_app.extensions.get('redis')
        if not redis_client:
            redis_client = current_app.config['SESSION_REDIS']
        
        # Get matches in the next 48 hours that aren't scheduled
        future_time = datetime.utcnow() + timedelta(hours=48)
        matches = MLSMatch.query.filter(
            MLSMatch.date_time <= future_time,
            MLSMatch.date_time >= datetime.utcnow(),
            MLSMatch.live_reporting_scheduled.is_(False)
        ).all()
        
        scheduler = MatchScheduler(redis_client)
        
        # First check existing scheduled tasks
        monitoring_status = scheduler.monitor_scheduled_tasks()
        if not monitoring_status['success']:
            logger.error(f"Failed to monitor tasks: {monitoring_status.get('message')}")
            return monitoring_status
            
        scheduled_tasks = monitoring_status.get('scheduled_tasks', {})
        logger.info(f"Found {len(scheduled_tasks)} existing scheduled tasks")
        
        scheduled_count = 0
        for match in matches:
            # Check if match already has tasks scheduled
            match_tasks = scheduled_tasks.get(str(match.id), {})
            if 'thread' not in match_tasks and 'reporting' not in match_tasks:
                logger.info(f"Scheduling new tasks for match {match.id}")
                result = scheduler.schedule_match_tasks(match.id)
                if result['success']:
                    scheduled_count += 1
                    logger.info(f"Scheduled match {match.id} successfully: {result}")
                else:
                    logger.error(f"Failed to schedule match {match.id}: {result['message']}")
            else:
                logger.info(f"Match {match.id} already has tasks scheduled: {match_tasks}")
                
        return {
            'success': True,
            'message': f'Scheduled {scheduled_count} matches',
            'scheduled_count': scheduled_count,
            'existing_tasks': len(scheduled_tasks)
        }
        
    except Exception as e:
        logger.error(f"Error checking upcoming matches: {str(e)}", exc_info=True)
        return {
            'success': False,
            'message': str(e)
        }

@celery_task(name='app.tasks.tasks_live_reporting.check_redis_connection', queue='live_reporting')
def check_redis_connection(self):
    try:
        redis_client = current_app.extensions.get('redis')
        if not redis_client:
            redis_client = current_app.config['SESSION_REDIS']
            
        # Test connection
        redis_client.ping()
        
        # Try to set and get a test value
        test_key = "test_connection"
        redis_client.setex(test_key, 60, "test_value")
        test_value = redis_client.get(test_key)
        
        return {
            'success': True,
            'message': 'Redis connection working',
            'test_value': test_value.decode('utf-8') if test_value else None
        }
    except Exception as e:
        return {
            'success': False,
            'message': f'Redis connection failed: {str(e)}'
        }

@celery_task(name='app.tasks.tasks_live_reporting.verify_scheduled_tasks', queue='live_reporting')
def verify_scheduled_tasks(self, match_id: str):
    try:
        match = MLSMatch.query.get(match_id)
        if not match:
            return {'success': False, 'message': 'Match not found'}
            
        # Get Redis client
        redis_client = current_app.extensions.get('redis') or current_app.config['SESSION_REDIS']
        
        # Check thread creation task
        thread_key = f"match_scheduler:{match_id}:thread"
        thread_task_id = redis_client.get(thread_key)
        
        # Check reporting task
        reporting_key = f"match_scheduler:{match_id}:reporting"
        reporting_task_id = redis_client.get(reporting_key)
        
        # Check scheduled times
        thread_time = match.date_time - timedelta(hours=24)
        reporting_time = match.date_time - timedelta(minutes=5)
        
        return {
            'success': True,
            'match_details': {
                'id': match.id,
                'opponent': match.opponent,
                'match_time': match.date_time.isoformat(),
                'thread_creation_time': thread_time.isoformat(),
                'reporting_start_time': reporting_time.isoformat()
            },
            'scheduled_tasks': {
                'thread_task_id': thread_task_id.decode('utf-8') if thread_task_id else None,
                'reporting_task_id': reporting_task_id.decode('utf-8') if reporting_task_id else None,
                'thread_created': match.thread_created,
                'live_reporting_scheduled': match.live_reporting_scheduled,
                'live_reporting_status': match.live_reporting_status
            }
        }
    except Exception as e:
        return {
            'success': False,
            'message': f'Verification failed: {str(e)}'
        }

@celery_task(name='app.tasks.tasks_live_reporting.monitor_all_matches',
             queue='live_reporting')
def monitor_all_matches(self) -> Dict[str, Any]:
    """Monitor and verify all scheduled match tasks."""
    try:
        from app.utils.task_monitor import task_monitor
        result = task_monitor.monitor_all_matches()
        
        if not result['success']:
            logger.error(f"Task monitoring failed: {result.get('message')}")
            return result
            
        # Log monitoring results
        logger.info(f"Monitored {result['total_matches']} matches")
        for match_id, status in result['matches'].items():
            if not status['success']:
                logger.error(f"Issues found with match {match_id}: {status.get('message')}")
            else:
                logger.info(f"Match {match_id} tasks verified successfully")
                
        return result
        
    except Exception as e:
        logger.error(f"Error in monitor_all_matches: {str(e)}", exc_info=True)
        return {
            'success': False,
            'message': str(e)
        }

@celery_task(name='app.tasks.tasks_live_reporting.verify_redis_tasks',
             queue='live_reporting')
def verify_redis_tasks(self) -> Dict[str, Any]:
    """Verify Redis task entries and clean up stale ones."""
    try:
        redis_client = RedisManager().client
        
        # Get all scheduler keys
        scheduler_keys = redis_client.keys('match_scheduler:*')
        results = {
            'checked': len(scheduler_keys),
            'valid': 0,
            'cleaned': 0,
            'errors': []
        }
        
        for key in scheduler_keys:
            try:
                key_str = key.decode('utf-8')
                task_id = redis_client.get(key)
                
                if task_id:
                    task_id = task_id.decode('utf-8')
                    status = AsyncResult(task_id, app=celery).status
                    
                    if status in ['FAILURE', 'REVOKED']:
                        # Clean up failed or revoked tasks
                        redis_client.delete(key)
                        results['cleaned'] += 1
                    else:
                        results['valid'] += 1
                else:
                    # Clean up empty keys
                    redis_client.delete(key)
                    results['cleaned'] += 1
                    
            except Exception as e:
                results['errors'].append(f"Error processing key {key_str}: {str(e)}")
                
        return {
            'success': True,
            'results': results
        }
        
    except Exception as e:
        logger.error(f"Error in verify_redis_tasks: {str(e)}", exc_info=True)
        return {
            'success': False,
            'message': str(e)
        }