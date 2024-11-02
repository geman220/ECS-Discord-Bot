from datetime import datetime, timedelta
import logging
from typing import Dict, Any, Optional
from redis import Redis
from app.extensions import db, celery
from app.models import MLSMatch
from app.utils.redis_manager import RedisManager
from app.tasks.tasks_live_reporting import (
    start_live_reporting,
    create_match_thread_task,
    force_create_mls_thread_task
)

logger = logging.getLogger(__name__)

class MatchScheduler:
    """Handles scheduling of match threads and live reporting."""
    
    THREAD_CREATE_HOURS_BEFORE = 24
    LIVE_REPORTING_MINUTES_BEFORE = 5
    REDIS_KEY_PREFIX = "match_scheduler:"
    
    def __init__(self):
        self.redis = RedisManager().client
        
    def schedule_match_tasks(self, match_id: int) -> Dict[str, Any]:
        """Schedule both thread creation and live reporting for a match."""
        try:
            # Test Redis connection
            try:
                self.redis.ping()
                logger.info("Redis connection successful")
            except Exception as e:
                logger.error(f"Redis connection failed: {str(e)}")
                return {
                    'success': False,
                    'message': f'Redis connection failed: {str(e)}'
                }

            match = MLSMatch.query.get(match_id)
            if not match:
                logger.error(f"Match {match_id} not found in database")
                return {
                    'success': False,
                    'message': f'Match {match_id} not found'
                }
        
            # Calculate scheduling times
            thread_time = match.date_time - timedelta(hours=self.THREAD_CREATE_HOURS_BEFORE)
            reporting_time = match.date_time - timedelta(minutes=self.LIVE_REPORTING_MINUTES_BEFORE)
            
            logger.info(f"Scheduling for match {match_id}:")
            logger.info(f"Match time: {match.date_time}")
            logger.info(f"Thread creation time: {thread_time}")
            logger.info(f"Live reporting time: {reporting_time}")
        
            tasks_scheduled = []
        
            # Schedule thread creation
            thread_key = self._get_redis_key(str(match_id), "thread")
            logger.info(f"Checking thread Redis key: {thread_key}")
            
            existing_thread_task = self.redis.get(thread_key)
            if existing_thread_task:
                logger.info(f"Found existing thread task: {existing_thread_task.decode('utf-8')}")
            
            if not self.redis.exists(thread_key):
                logger.info("Scheduling new thread creation task")
                thread_task = force_create_mls_thread_task.apply_async(
                    args=[match_id],
                    eta=thread_time
                )
                logger.info(f"Created thread task with ID: {thread_task.id}")
                
                # Set Redis key with extended logging
                try:
                    expiry = int(timedelta(days=2).total_seconds())
                    self.redis.setex(
                        thread_key,
                        expiry,
                        thread_task.id
                    )
                    logger.info(f"Set Redis key {thread_key} with task ID {thread_task.id} and expiry {expiry}s")
                except Exception as e:
                    logger.error(f"Failed to set Redis key for thread task: {str(e)}")
                    
                tasks_scheduled.append('thread_creation')
        
            # Schedule live reporting
            reporting_key = self._get_redis_key(str(match_id), "reporting")
            logger.info(f"Checking reporting Redis key: {reporting_key}")
            
            existing_reporting_task = self.redis.get(reporting_key)
            if existing_reporting_task:
                logger.info(f"Found existing reporting task: {existing_reporting_task.decode('utf-8')}")
            
            if not self.redis.exists(reporting_key):
                logger.info("Scheduling new live reporting task")
                reporting_task = start_live_reporting.apply_async(
                    args=[str(match_id)],
                    eta=reporting_time
                )
                logger.info(f"Created reporting task with ID: {reporting_task.id}")
                
                # Set Redis key with extended logging
                try:
                    expiry = int(timedelta(days=2).total_seconds())
                    self.redis.setex(
                        reporting_key,
                        expiry,
                        reporting_task.id
                    )
                    logger.info(f"Set Redis key {reporting_key} with task ID {reporting_task.id} and expiry {expiry}s")
                except Exception as e:
                    logger.error(f"Failed to set Redis key for reporting task: {str(e)}")
                    
                tasks_scheduled.append('live_reporting')
        
            # Update match record
            try:
                match.thread_creation_time = thread_time
                match.live_reporting_scheduled = True
                db.session.commit()
                logger.info(f"Updated match record with thread_creation_time: {thread_time}")
            except Exception as e:
                logger.error(f"Failed to update match record: {str(e)}")
                raise
        
            # Verify Redis keys were set
            verification = {
                'thread_key': bool(self.redis.exists(thread_key)),
                'reporting_key': bool(self.redis.exists(reporting_key)),
                'thread_ttl': self.redis.ttl(thread_key),
                'reporting_ttl': self.redis.ttl(reporting_key)
            }
            logger.info(f"Redis key verification: {verification}")
        
            return {
                'success': True,
                'message': 'Match tasks scheduled successfully',
                'tasks_scheduled': tasks_scheduled,
                'thread_time': thread_time.isoformat(),
                'reporting_time': reporting_time.isoformat(),
                'redis_verification': verification
            }
        
        except Exception as e:
            logger.error(f"Error scheduling match tasks: {str(e)}", exc_info=True)
            return {
                'success': False,
                'message': str(e)
            }
    
    def _get_redis_key(self, match_id: str, task_type: str) -> str:
        """Generate Redis key for scheduled task."""
        return f"{self.REDIS_KEY_PREFIX}{match_id}:{task_type}"

    def monitor_scheduled_tasks(self) -> Dict[str, Any]:
        """Monitor currently scheduled tasks in Redis."""
        try:
            # Get all keys matching our prefix
            all_keys = self.redis.keys(f"{self.REDIS_KEY_PREFIX}*")
        
            scheduled_tasks = {}
            for key in all_keys:
                key_str = key.decode('utf-8')
                task_id = self.redis.get(key)
                ttl = self.redis.ttl(key)
            
                # Parse match_id and task_type from key
                _, match_id, task_type = key_str.split(':')
            
                if match_id not in scheduled_tasks:
                    scheduled_tasks[match_id] = {}
                
                scheduled_tasks[match_id][task_type] = {
                    'task_id': task_id.decode('utf-8') if task_id else None,
                    'ttl': ttl
                }
            
            # Get associated matches from database
            match_ids = list(scheduled_tasks.keys())
            matches = MLSMatch.query.filter(MLSMatch.match_id.in_(match_ids)).all()
        
            # Add match details
            for match in matches:
                if str(match.match_id) in scheduled_tasks:
                    scheduled_tasks[str(match.match_id)]['match_details'] = {
                        'opponent': match.opponent,
                        'date_time': match.date_time.isoformat(),
                        'thread_creation_time': match.thread_creation_time.isoformat() if match.thread_creation_time else None,
                        'live_reporting_scheduled': match.live_reporting_scheduled,
                        'live_reporting_status': match.live_reporting_status
                    }
        
            return {
                'success': True,
                'scheduled_tasks': scheduled_tasks,
                'total_keys': len(all_keys)
            }
        
        except Exception as e:
            logger.error(f"Error monitoring scheduled tasks: {str(e)}", exc_info=True)
            return {
                'success': False,
                'message': str(e)
            }