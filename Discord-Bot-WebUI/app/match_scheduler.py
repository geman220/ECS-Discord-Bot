# app/match_scheduler.py

"""
Match Scheduler Module

This module handles scheduling of match threads and live reporting tasks.
It interacts with Redis to manage scheduling keys, updates match records in the database,
and uses Celery to schedule tasks for thread creation and live reporting.
Additional utilities are provided to verify scheduled tasks and monitor the overall
match scheduling status.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

from flask import g
from app.models import MLSMatch
from app.services.redis_connection_service import get_redis_service
from app.core import celery as celery_app
from app.core.helpers import get_match
from app.core.session_manager import managed_session
from app.tasks.tasks_live_reporting import start_live_reporting, force_create_mls_thread_task

logger = logging.getLogger(__name__)


class MatchScheduler:
    """Handles scheduling of match threads and live reporting tasks."""
    
    THREAD_CREATE_HOURS_BEFORE = 48
    LIVE_REPORTING_MINUTES_BEFORE = 5
    REDIS_KEY_PREFIX = "match_scheduler:"

    def __init__(self):
        self._redis_service = get_redis_service()
    
    @property
    def redis_service(self):
        """Get centralized Redis service with connection pooling."""
        return self._redis_service

    def _get_match(self, match_id: int) -> Optional[MLSMatch]:
        """
        Retrieve a match from the database by its match_id.
        
        Parameters:
            match_id (int): The identifier of the match.
        
        Returns:
            Optional[MLSMatch]: The match object if found, otherwise None.
        """
        session = g.db_session
        return session.query(MLSMatch).get(match_id)

    def _update_match_schedule(self, match_id: int, thread_time: datetime) -> Optional[MLSMatch]:
        """
        Update the match record with thread creation time and mark live reporting as scheduled.
        
        Parameters:
            match_id (int): The identifier of the match.
            thread_time (datetime): The scheduled thread creation time.
        
        Returns:
            Optional[MLSMatch]: The updated match object if found, otherwise None.
        """
        session = g.db_session
        match = get_match(session, match_id)
        if match:
            match.thread_creation_time = thread_time
            match.live_reporting_scheduled = True
        return match

    def schedule_match_tasks(self, match_id: int, force: bool = False) -> Dict[str, Any]:
        """
        Schedule tasks for a match including thread creation and live reporting.
        
        Parameters:
            match_id (int): The identifier of the match.
            force (bool): If True, revoke any existing scheduled tasks.
        
        Returns:
            Dict[str, Any]: A dictionary with scheduling details and status.
        """
        try:
            # SafeRedisClient will handle unavailability gracefully
            # No need to pre-check availability since SafeRedisClient provides fallback behavior

            match = self._get_match(match_id)
            if not match:
                logger.error(f"Match {match_id} not found in database")
                return {'success': False, 'message': f"Match {match_id} not found"}

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
                return {'success': False, 'message': "Failed to update match record"}
        
            # Verify Redis keys were set
            verification = self._verify_redis_keys(match_id)
            logger.info(f"Redis key verification: {verification}")
        
            # Invalidate and warm cache for this match
            try:
                from app.tasks.tasks_cache_management import warm_cache_for_match
                warm_cache_for_match.delay(match_id)
                logger.debug(f"Scheduled cache warming for match {match_id}")
            except Exception as cache_error:
                logger.warning(f"Failed to schedule cache warming for match {match_id}: {cache_error}")
            
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
            return {'success': False, 'message': str(e)}

    def _schedule_thread_task(self, match_id: int, thread_time: datetime, force: bool = False) -> Dict[str, Any]:
        """
        Schedule the thread creation task for a match.
        
        Parameters:
            match_id (int): The match identifier.
            thread_time (datetime): The time to create the thread.
            force (bool): If True, revoke and reschedule any existing task.
        
        Returns:
            Dict[str, Any]: Details about the scheduled thread task.
        """
        thread_key = self._get_redis_key(str(match_id), "thread")
        logger.info(f"Checking thread Redis key: {thread_key}")
        
        # Check if the thread_time is in the past
        now = datetime.utcnow()
        if thread_time.tzinfo:
            # Make now timezone-aware if thread_time is
            import pytz
            now = datetime.now(pytz.UTC)
        
        is_past_due = thread_time <= now
        if is_past_due:
            logger.info(f"Thread time {thread_time} is past due (now: {now}), will execute immediately")
    
        with self.redis_service.get_connection() as redis_client:
            if force and redis_client.exists(thread_key):
                existing_data = redis_client.get(thread_key)
                if existing_data:
                    try:
                        existing_obj = json.loads(existing_data)
                        existing_task = existing_obj.get("task_id")
                    except Exception:
                        existing_task = existing_data
                try:
                    celery_app.control.revoke(existing_task, terminate=True)
                except Exception as e:
                    logger.error(f"Error revoking existing thread task: {e}")
                redis_client.delete(thread_key)
                logger.info("Existing thread task revoked and key cleared.")
        
            if redis_client.exists(thread_key):
                existing_data = redis_client.get(thread_key)
                if existing_data:
                    try:
                        existing_obj = json.loads(existing_data)
                        existing_task = existing_obj.get("task_id")
                        existing_eta = existing_obj.get("eta")
                    except Exception:
                        existing_task = existing_data
                        existing_eta = None
                    logger.info(f"Found existing thread task: {existing_task}")
                    return {'scheduled': False, 'existing_task': existing_task, 'eta': existing_eta}
    
        try:
            # If the time is past due, execute immediately without eta
            if is_past_due:
                thread_task = force_create_mls_thread_task.apply_async(args=[match_id])
                logger.info(f"Created immediate thread task with ID: {thread_task.id}")
            else:
                thread_task = force_create_mls_thread_task.apply_async(args=[match_id], eta=thread_time)
                logger.info(f"Created scheduled thread task with ID: {thread_task.id}")
            
            expiry = int(timedelta(days=2).total_seconds())
            data_to_store = json.dumps({
                "task_id": thread_task.id,
                "eta": thread_time.isoformat()
            })
            
            with self.redis_service.get_connection() as redis_client:
                redis_client.setex(thread_key, expiry, data_to_store)
            return {
                'scheduled': True,
                'task_id': thread_task.id,
                'expiry': expiry,
                'eta': thread_time.isoformat(),
                'immediate': is_past_due
            }
        except Exception as e:
            logger.error(f"Failed to schedule thread task: {str(e)}")
            return {'scheduled': False, 'error': str(e)}

    def _schedule_reporting_task(self, match_id: int, reporting_time: datetime, force: bool = False) -> Dict[str, Any]:
        """
        Schedule the live reporting task for a match.
        
        Parameters:
            match_id (int): The match identifier.
            reporting_time (datetime): The time to start live reporting.
            force (bool): If True, revoke and reschedule any existing reporting task.
        
        Returns:
            Dict[str, Any]: Details about the scheduled reporting task.
        """
        reporting_key = self._get_redis_key(str(match_id), "reporting")
        logger.info(f"Checking reporting Redis key: {reporting_key}")
        
        # Check if the reporting_time is in the past
        now = datetime.utcnow()
        if reporting_time.tzinfo:
            # Make now timezone-aware if reporting_time is
            import pytz
            now = datetime.now(pytz.UTC)
        
        is_past_due = reporting_time <= now
        if is_past_due:
            logger.info(f"Reporting time {reporting_time} is past due (now: {now}), will execute immediately")
    
        with self.redis_service.get_connection() as redis_client:
            if force and redis_client.exists(reporting_key):
                existing_data = redis_client.get(reporting_key)
                if existing_data:
                    try:
                        existing_obj = json.loads(existing_data)
                        existing_task = existing_obj.get("task_id")
                    except Exception:
                        existing_task = existing_data
                try:
                    celery_app.control.revoke(existing_task, terminate=True)
                except Exception as e:
                    logger.error(f"Error revoking existing reporting task: {e}")
                redis_client.delete(reporting_key)
                logger.info("Existing reporting task revoked and key cleared.")
        
            if redis_client.exists(reporting_key):
                existing_data = redis_client.get(reporting_key)
                if existing_data:
                    try:
                        existing_obj = json.loads(existing_data)
                        existing_task = existing_obj.get("task_id")
                        existing_eta = existing_obj.get("eta")
                    except Exception:
                        existing_task = existing_data
                        existing_eta = None
                    logger.info(f"Found existing reporting task: {existing_task}")
                    return {'scheduled': False, 'existing_task': existing_task, 'eta': existing_eta}
    
        try:
            # If the time is past due, execute immediately without eta
            if is_past_due:
                reporting_task = start_live_reporting.apply_async(args=[str(match_id)])
                logger.info(f"Created immediate reporting task with ID: {reporting_task.id}")
            else:
                reporting_task = start_live_reporting.apply_async(args=[str(match_id)], eta=reporting_time)
                logger.info(f"Created scheduled reporting task with ID: {reporting_task.id}")
            
            expiry = int(timedelta(days=2).total_seconds())
            data_to_store = json.dumps({
                "task_id": reporting_task.id,
                "eta": reporting_time.isoformat()
            })
            
            with self.redis_service.get_connection() as redis_client:
                redis_client.setex(reporting_key, expiry, data_to_store)
            return {
                'scheduled': True,
                'task_id': reporting_task.id,
                'expiry': expiry,
                'eta': reporting_time.isoformat(),
                'immediate': is_past_due
            }
        except Exception as e:
            logger.error(f"Failed to schedule reporting task: {str(e)}")
            return {'scheduled': False, 'error': str(e)}

    def unschedule_match_tasks(self, match_id: int) -> Dict[str, Any]:
        """
        Unschedule all tasks for a match and clean up Redis/database.
        
        Parameters:
            match_id (int): The identifier of the match.
            
        Returns:
            Dict[str, Any]: Result of the unscheduling operation.
        """
        try:
            results = {
                'unscheduled_tasks': 0,
                'cleaned_redis_keys': 0,
                'database_updated': False,
                'details': []
            }
            
            # Get Redis keys for this match
            thread_key = f"{self.REDIS_KEY_PREFIX}{match_id}:thread"
            reporting_key = f"{self.REDIS_KEY_PREFIX}{match_id}:reporting"
            
            # Extract and revoke task IDs using centralized Redis service
            with self.redis_service.get_connection() as redis_client:
                for key_name, redis_key in [("thread", thread_key), ("reporting", reporting_key)]:
                    try:
                        value = redis_client.get(redis_key)
                        if value:
                            import json
                            data = json.loads(value)
                            task_id = data.get('task_id')
                            
                            if task_id:
                                # Revoke the task
                                from app.core import celery
                                celery.control.revoke(task_id, terminate=True)
                                results['unscheduled_tasks'] += 1
                                results['details'].append(f"Revoked {key_name} task {task_id}")
                            
                            # Delete the Redis key
                            redis_client.delete(redis_key)
                            results['cleaned_redis_keys'] += 1
                            results['details'].append(f"Deleted Redis key {redis_key}")
                            
                    except Exception as e:
                        results['details'].append(f"Error processing {key_name} task: {str(e)}")
            
            # Update database flags
            try:
                with managed_session() as session:
                    match = session.query(MLSMatch).get(match_id)
                    if match:
                        match.live_reporting_scheduled = False
                        match.thread_creation_scheduled = False
                        match.thread_creation_time = None
                        session.commit()
                        results['database_updated'] = True
                        results['details'].append(f"Reset database flags for match {match_id}")
            except Exception as e:
                results['details'].append(f"Database update error: {str(e)}")
            
            logger.info(f"Unscheduled tasks for match {match_id}: {results}")
            return {
                'success': True,
                'match_id': match_id,
                **results
            }
            
        except Exception as e:
            logger.error(f"Failed to unschedule tasks for match {match_id}: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'match_id': match_id
            }

    def _get_redis_key(self, match_id: str, task_type: str) -> str:
        """
        Construct a Redis key for storing task information.
        
        Parameters:
            match_id (str): The match identifier.
            task_type (str): The type of task ("thread" or "reporting").
        
        Returns:
            str: The constructed Redis key.
        """
        return f"{self.REDIS_KEY_PREFIX}{match_id}:{task_type}"

    def _verify_redis_keys(self, match_id: int) -> Dict[str, Any]:
        """
        Verify the existence and TTL of scheduled task keys in Redis.
        
        Parameters:
            match_id (int): The match identifier.
        
        Returns:
            Dict[str, Any]: A dictionary with verification details for thread and reporting keys.
        """
        thread_key = self._get_redis_key(str(match_id), "thread")
        reporting_key = self._get_redis_key(str(match_id), "reporting")
        
        with self.redis_service.get_connection() as redis_client:
            return {
                'thread_key': bool(redis_client.exists(thread_key)),
                'reporting_key': bool(redis_client.exists(reporting_key)),
                'thread_ttl': redis_client.ttl(thread_key),
                'reporting_ttl': redis_client.ttl(reporting_key)
            }

    def monitor_scheduled_tasks(self) -> Dict[str, Any]:
        """
        Monitor and report on all scheduled match tasks stored in Redis.
        
        Returns:
            Dict[str, Any]: A dictionary containing details of scheduled tasks and total keys.
        """
        try:
            with self.redis_service.get_connection() as redis_client:
                all_keys = redis_client.keys(f"{self.REDIS_KEY_PREFIX}*")
                scheduled_tasks = self._process_redis_keys(all_keys, redis_client)
        
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
            return {'success': False, 'message': str(e)}

    def _process_redis_keys(self, keys: List[bytes], redis_client) -> Dict[str, Dict]:
        """
        Process Redis keys to extract scheduled task details.
        
        Parameters:
            keys (List[bytes]): A list of Redis keys.
            redis_client: Active Redis client connection.
        
        Returns:
            Dict[str, Dict]: A mapping of match IDs to their task details.
        """
        scheduled_tasks = {}
        for key in keys:
            key_str = key if isinstance(key, str) else str(key)
            task_data = redis_client.get(key)
            ttl = redis_client.ttl(key)
            # Expected key format: match_scheduler:<match_id>:<task_type>
            _, match_id, task_type = key_str.split(':')
            if match_id not in scheduled_tasks:
                scheduled_tasks[match_id] = {}
            scheduled_tasks[match_id][task_type] = {'task_id': task_data, 'ttl': ttl}
        return scheduled_tasks