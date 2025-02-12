from datetime import datetime, timedelta
import logging
from typing import Dict, Any, Optional, List
from flask import g
import json
from redis import Redis
from app.models import MLSMatch
from app.utils.redis_manager import RedisManager
from app.core import celery as celery_app

logger = logging.getLogger(__name__)

class MatchScheduler:
    """Handles scheduling of match threads and live reporting."""
    
    THREAD_CREATE_HOURS_BEFORE = 48
    LIVE_REPORTING_MINUTES_BEFORE = 5
    REDIS_KEY_PREFIX = "match_scheduler:"
    
    def __init__(self):
        self.redis = RedisManager().client

    def _get_match(self, match_id: int) -> Optional[MLSMatch]:
        session = g.db_session
        return session.query(MLSMatch).get(match_id)

    def _update_match_schedule(self, match_id: int, thread_time: datetime) -> Optional[MLSMatch]:
        session = g.db_session
        match = session.query(MLSMatch).get(match_id)
        if match:
            match.thread_creation_time = thread_time
            match.live_reporting_scheduled = True
        return match
        
    def schedule_match_tasks(self, match_id: int, force: bool = False) -> Dict[str, Any]:
        try:
            # Test Redis connection
            try:
                self.redis.ping()
                logger.info("Redis connection successful")
            except Exception as e:
                logger.error(f"Redis connection failed: {str(e)}")
                return {
                    'success': False,
                    'message': f"Redis connection failed: {str(e)}"
                }

            match = self._get_match(match_id)
            if not match:
                logger.error(f"Match {match_id} not found in database")
                return {
                    'success': False,
                    'message': f"Match {match_id} not found"
                }
        
            # Calculate scheduling times
            thread_time = match.date_time - timedelta(hours=self.THREAD_CREATE_HOURS_BEFORE)
            reporting_time = match.date_time - timedelta(minutes=self.LIVE_REPORTING_MINUTES_BEFORE)
            
            logger.info(f"Scheduling for match {match_id}:")
            logger.info(f"Match time: {match.date_time}")
            logger.info(f"Thread creation time: {thread_time}")
            logger.info(f"Live reporting time: {reporting_time}")
        
            tasks_scheduled = []
        
            # Schedule thread creation with force option
            thread_task_info = self._schedule_thread_task(match_id, thread_time, force=force)
            if thread_task_info.get('scheduled'):
                tasks_scheduled.append('thread_creation')

            # Schedule live reporting with force option
            reporting_task_info = self._schedule_reporting_task(match_id, reporting_time, force=force)
            if reporting_task_info.get('scheduled'):
                tasks_scheduled.append('live_reporting')
        
            # Update match record
            updated_match = self._update_match_schedule(match_id, thread_time)
            if not updated_match:
                logger.error("Failed to update match record")
                return {
                    'success': False,
                    'message': "Failed to update match record"
                }
        
            # Verify Redis keys were set
            verification = self._verify_redis_keys(match_id)
            logger.info(f"Redis key verification: {verification}")
        
            return {
                'success': True,
                'message': "Match tasks scheduled successfully",
                'tasks_scheduled': tasks_scheduled,
                'thread_time': thread_time.isoformat(),
                'reporting_time': reporting_time.isoformat(),
                'redis_verification': verification,
                'thread_task': thread_task_info,
                'reporting_task': reporting_task_info
            }
        
        except Exception as e:
            logger.error(f"Error scheduling match tasks: {str(e)}", exc_info=True)
            return {
                'success': False,
                'message': str(e)
            }

    def _schedule_thread_task(self, match_id: int, thread_time: datetime, force: bool = False) -> Dict[str, Any]:
        from app.tasks.tasks_live_reporting import force_create_mls_thread_task
        thread_key = self._get_redis_key(str(match_id), "thread")
        logger.info(f"Checking thread Redis key: {thread_key}")
    
        if force and self.redis.exists(thread_key):
            existing_data = self.redis.get(thread_key)
            if existing_data:
                try:
                    existing_obj = json.loads(existing_data.decode('utf-8'))
                    existing_task = existing_obj.get("task_id")
                except Exception:
                    existing_task = existing_data.decode('utf-8')
            try:
                celery_app.control.revoke(existing_task, terminate=True)
            except Exception as e:
                logger.error(f"Error revoking existing thread task: {e}")
            self.redis.delete(thread_key)
            logger.info("Existing thread task revoked and key cleared.")
    
        if self.redis.exists(thread_key):
            existing_data = self.redis.get(thread_key)
            if existing_data:
                try:
                    existing_obj = json.loads(existing_data.decode('utf-8'))
                    existing_task = existing_obj.get("task_id")
                    existing_eta = existing_obj.get("eta")
                except Exception:
                    existing_task = existing_data.decode('utf-8')
                    existing_eta = None
            logger.info(f"Found existing thread task: {existing_task}")
            return {'scheduled': False, 'existing_task': existing_task, 'eta': existing_eta}
    
        try:
            thread_task = force_create_mls_thread_task.apply_async(
                args=[match_id],
                eta=thread_time
            )
            logger.info(f"Created thread task with ID: {thread_task.id}")
            expiry = int(timedelta(days=2).total_seconds())
            data_to_store = json.dumps({
                "task_id": thread_task.id,
                "eta": thread_time.isoformat()
            })
            self.redis.setex(thread_key, expiry, data_to_store)
            return {
                'scheduled': True,
                'task_id': thread_task.id,
                'expiry': expiry,
                'eta': thread_time.isoformat()
            }
        except Exception as e:
            logger.error(f"Failed to schedule thread task: {str(e)}")
            return {
                'scheduled': False,
                'error': str(e)
            }

    def _schedule_reporting_task(self, match_id: int, reporting_time: datetime, force: bool = False) -> Dict[str, Any]:
        from app.tasks.tasks_live_reporting import start_live_reporting
        reporting_key = self._get_redis_key(str(match_id), "reporting")
        logger.info(f"Checking reporting Redis key: {reporting_key}")
    
        if force and self.redis.exists(reporting_key):
            existing_data = self.redis.get(reporting_key)
            if existing_data:
                try:
                    existing_obj = json.loads(existing_data.decode('utf-8'))
                    existing_task = existing_obj.get("task_id")
                except Exception:
                    existing_task = existing_data.decode('utf-8')
            try:
                celery_app.control.revoke(existing_task, terminate=True)
            except Exception as e:
                logger.error(f"Error revoking existing reporting task: {e}")
            self.redis.delete(reporting_key)
            logger.info("Existing reporting task revoked and key cleared.")
    
        if self.redis.exists(reporting_key):
            existing_data = self.redis.get(reporting_key)
            if existing_data:
                try:
                    existing_obj = json.loads(existing_data.decode('utf-8'))
                    existing_task = existing_obj.get("task_id")
                    existing_eta = existing_obj.get("eta")
                except Exception:
                    existing_task = existing_data.decode('utf-8')
                    existing_eta = None
            logger.info(f"Found existing reporting task: {existing_task}")
            return {'scheduled': False, 'existing_task': existing_task, 'eta': existing_eta}
    
        try:
            reporting_task = start_live_reporting.apply_async(
                args=[str(match_id)],
                eta=reporting_time
            )
            logger.info(f"Created reporting task with ID: {reporting_task.id}")
            expiry = int(timedelta(days=2).total_seconds())
            data_to_store = json.dumps({
                "task_id": reporting_task.id,
                "eta": reporting_time.isoformat()
            })
            self.redis.setex(reporting_key, expiry, data_to_store)
            return {
                'scheduled': True,
                'task_id': reporting_task.id,
                'expiry': expiry,
                'eta': reporting_time.isoformat()
            }
        except Exception as e:
            logger.error(f"Failed to schedule reporting task: {str(e)}")
            return {
                'scheduled': False,
                'error': str(e)
            }
    
    def _get_redis_key(self, match_id: str, task_type: str) -> str:
        return f"{self.REDIS_KEY_PREFIX}{match_id}:{task_type}"

    def _verify_redis_keys(self, match_id: int) -> Dict[str, Any]:
        thread_key = self._get_redis_key(str(match_id), "thread")
        reporting_key = self._get_redis_key(str(match_id), "reporting")
        return {
            'thread_key': bool(self.redis.exists(thread_key)),
            'reporting_key': bool(self.redis.exists(reporting_key)),
            'thread_ttl': self.redis.ttl(thread_key),
            'reporting_ttl': self.redis.ttl(reporting_key)
        }

    def monitor_scheduled_tasks(self) -> Dict[str, Any]:
        try:
            all_keys = self.redis.keys(f"{self.REDIS_KEY_PREFIX}*")
            scheduled_tasks = self._process_redis_keys(all_keys)
        
            match_ids = list(scheduled_tasks.keys())
            session = g.db_session
            matches = session.query(MLSMatch).filter(MLSMatch.match_id.in_(match_ids)).all()
    
            for match in matches:
                match_id = str(match.match_id)
                if match_id in scheduled_tasks:
                    scheduled_tasks[match_id]['match_details'] = {
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
    
    def _process_redis_keys(self, keys: List[bytes]) -> Dict[str, Dict]:
        scheduled_tasks = {}
        for key in keys:
            key_str = key.decode('utf-8') if isinstance(key, bytes) else str(key)
            task_id = self.redis.get(key)
            if task_id and isinstance(task_id, bytes):
                task_id = task_id.decode('utf-8')
            ttl = self.redis.ttl(key)
            
            _, match_id, task_type = key_str.split(':')
            
            if match_id not in scheduled_tasks:
                scheduled_tasks[match_id] = {}
            
            scheduled_tasks[match_id][task_type] = {
                'task_id': task_id,
                'ttl': ttl
            }
            
        return scheduled_tasks
