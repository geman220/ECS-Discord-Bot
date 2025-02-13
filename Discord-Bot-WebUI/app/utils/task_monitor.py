# app/utils/task_monitor.py

"""
Task Monitor Module

This module defines the TaskMonitor class, which provides methods to retrieve the status
of Celery tasks and to verify and monitor scheduled tasks for match scheduling and live reporting.
It interacts with Redis to store and retrieve task IDs and reschedule tasks if necessary.
A global instance of TaskMonitor is created for convenience.
"""

import logging
from typing import Dict, Any
from celery.result import AsyncResult
from flask import g
from app.core import celery
from app.models import MLSMatch
from app.utils.redis_manager import RedisManager
from app.tasks.tasks_live_reporting import force_create_mls_thread_task, start_live_reporting

logger = logging.getLogger(__name__)


class TaskMonitor:
    """Monitor and manage Celery tasks for match scheduling and live reporting."""
    
    def __init__(self):
        # Initialize Redis client from the RedisManager singleton.
        self.redis = RedisManager().client
        
    def get_task_status(self, task_id: str) -> Dict[str, Any]:
        """
        Retrieve detailed status information of a Celery task.
        
        Args:
            task_id: The Celery task ID.
        
        Returns:
            A dictionary containing task status details such as status, whether it is ready,
            if it succeeded or failed, and any available task info.
        """
        try:
            result = AsyncResult(task_id, app=celery)
            status = {
                'id': task_id,
                'status': result.status,
                'successful': result.successful() if result.ready() else None,
                'failed': result.failed() if result.ready() else None,
                'ready': result.ready(),
                'info': str(result.info) if result.info else None
            }
            
            # Include ETA if available.
            if hasattr(result, 'eta') and result.eta:
                status['eta'] = result.eta.isoformat()
                
            return status
        except Exception as e:
            logger.error(f"Error getting task status for {task_id}: {str(e)}")
            return {
                'id': task_id,
                'status': 'ERROR',
                'error': str(e)
            }
    
    def verify_scheduled_tasks(self, match_id: str, session=None) -> Dict[str, Any]:
        """
        Verify and potentially repair scheduled tasks for a given match.

        Retrieves scheduled task IDs from Redis and checks their statuses.
        If a task has failed or returned an error, it reschedules the task.

        Args:
            match_id: The ID of the match (as a string).
            session: An optional database session; if not provided, attempts to use g.db_session.

        Returns:
            A dictionary summarizing the status of thread and reporting tasks.
        """
        if session is None:
            # Use g.db_session if available.
            session = getattr(g, 'db_session', None)
            if session is None:
                logger.error("No database session available in verify_scheduled_tasks.")
                return {'success': False, 'message': 'No session available'}

        try:
            match = session.query(MLSMatch).get(match_id)
            if not match:
                return {'success': False, 'message': 'Match not found'}
            
            # Define Redis keys for scheduled thread and reporting tasks.
            thread_key = f"match_scheduler:{match_id}:thread"
            reporting_key = f"match_scheduler:{match_id}:reporting"
            
            thread_task_id = self.redis.get(thread_key)
            reporting_task_id = self.redis.get(reporting_key)
            
            # Check the thread creation task status.
            thread_status = None
            if thread_task_id:
                thread_task_id = thread_task_id.decode('utf-8')
                thread_status = self.get_task_status(thread_task_id)
                
                # If the task failed or returned an error, reschedule it.
                if thread_status.get('failed') or thread_status.get('status') == 'ERROR':
                    logger.warning(f"Thread task {thread_task_id} failed or error, rescheduling")
                    new_thread_task = force_create_mls_thread_task.apply_async(
                        args=[match_id],
                        eta=match.thread_creation_time
                    )
                    self.redis.setex(thread_key, 172800, new_thread_task.id)  # 48 hours
                    thread_status = self.get_task_status(new_thread_task.id)
            
            # Check the live reporting task status.
            reporting_status = None
            if reporting_task_id:
                reporting_task_id = reporting_task_id.decode('utf-8')
                reporting_status = self.get_task_status(reporting_task_id)
                
                # If the task failed or returned an error, reschedule it.
                if reporting_status.get('failed') or reporting_status.get('status') == 'ERROR':
                    logger.warning(f"Reporting task {reporting_task_id} failed or error, rescheduling")
                    new_reporting_task = start_live_reporting.apply_async(
                        args=[str(match_id)],
                        eta=match.date_time
                    )
                    self.redis.setex(reporting_key, 172800, new_reporting_task.id)  # 48 hours
                    reporting_status = self.get_task_status(new_reporting_task.id)
            
            return {
                'success': True,
                'match_id': match_id,
                'thread_task': {
                    'id': thread_task_id,
                    'status': thread_status
                },
                'reporting_task': {
                    'id': reporting_task_id,
                    'status': reporting_status
                }
            }
            
        except Exception as e:
            logger.error(f"Error verifying scheduled tasks: {str(e)}")
            return {
                'success': False,
                'message': str(e)
            }
    
    def monitor_all_matches(self, session=None) -> Dict[str, Any]:
        """
        Monitor all scheduled matches and their associated tasks.

        Retrieves all matches with scheduled live reporting or thread creation tasks,
        verifies their task statuses, and returns a summary.

        Args:
            session: An optional database session; if not provided, attempts to use g.db_session.

        Returns:
            A dictionary with a summary of monitored matches, including total count and details.
        """
        if session is None:
            session = getattr(g, 'db_session', None)
            if session is None:
                logger.error("No database session available in monitor_all_matches.")
                return {'success': False, 'message': 'No session available'}

        try:
            # Query matches that either have scheduled live reporting or a defined thread creation time.
            matches = session.query(MLSMatch).filter(
                (MLSMatch.live_reporting_scheduled == True) |
                (MLSMatch.thread_creation_time.isnot(None))
            ).all()
            
            results = {}
            for match in matches:
                # Verify scheduled tasks for each match.
                match_status = self.verify_scheduled_tasks(str(match.id), session=session)
                results[str(match.id)] = match_status
            
            return {
                'success': True,
                'matches': results,
                'total_matches': len(results)
            }
        except Exception as e:
            logger.error(f"Error monitoring matches: {str(e)}")
            return {
                'success': False,
                'message': str(e)
            }


# Create a global instance of TaskMonitor for convenient access.
task_monitor = TaskMonitor()