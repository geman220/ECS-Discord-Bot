# app/utils/task_monitor.py

import logging
from datetime import datetime
from typing import Dict, Any, Optional
from celery.result import AsyncResult
from celery.schedules import crontab
from flask import g
from app.core import celery
from app.models import MLSMatch
from app.utils.redis_manager import RedisManager
from app.tasks.tasks_live_reporting import force_create_mls_thread_task, start_live_reporting

logger = logging.getLogger(__name__)

class TaskMonitor:
    """Monitor and manage Celery tasks for match scheduling."""
    
    def __init__(self):
        self.redis = RedisManager().client
        
    def get_task_status(self, task_id: str) -> Dict[str, Any]:
        """Get detailed status of a Celery task."""
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
            
            # Get task ETA if available
            if hasattr(result, 'eta'):
                status['eta'] = result.eta.isoformat() if result.eta else None
                
            return status
        except Exception as e:
            logger.error(f"Error getting task status for {task_id}: {str(e)}")
            return {
                'id': task_id,
                'status': 'ERROR',
                'error': str(e)
            }
    
    def verify_scheduled_tasks(self, match_id: str, session=None) -> Dict[str, Any]:
        """Verify and potentially repair scheduled tasks for a match."""
        if session is None:
            # Fall back to g.db_session if no session provided
            session = getattr(g, 'db_session', None)
            if session is None:
                logger.error("No database session available in verify_scheduled_tasks.")
                return {'success': False, 'message': 'No session available'}

        try:
            match = session.query(MLSMatch).get(match_id)
            if not match:
                return {'success': False, 'message': 'Match not found'}
            
            # Get scheduled task IDs from Redis
            thread_key = f"match_scheduler:{match_id}:thread"
            reporting_key = f"match_scheduler:{match_id}:reporting"
            
            thread_task_id = self.redis.get(thread_key)
            reporting_task_id = self.redis.get(reporting_key)
            
            # Check thread creation task
            thread_status = None
            if thread_task_id:
                thread_task_id = thread_task_id.decode('utf-8')
                thread_status = self.get_task_status(thread_task_id)
                
                # Reschedule if task failed or doesn't exist
                if thread_status.get('failed') or thread_status.get('status') == 'ERROR':
                    logger.warning(f"Thread task {thread_task_id} failed or error, rescheduling")
                    new_thread_task = force_create_mls_thread_task.apply_async(
                        args=[match_id],
                        eta=match.thread_creation_time
                    )
                    self.redis.setex(
                        thread_key,
                        172800,  # 48 hours
                        new_thread_task.id
                    )
                    thread_status = self.get_task_status(new_thread_task.id)
            
            # Check live reporting task
            reporting_status = None
            if reporting_task_id:
                reporting_task_id = reporting_task_id.decode('utf-8')
                reporting_status = self.get_task_status(reporting_task_id)
                
                # Reschedule if task failed or doesn't exist
                if reporting_status.get('failed') or reporting_status.get('status') == 'ERROR':
                    logger.warning(f"Reporting task {reporting_task_id} failed or error, rescheduling")
                    new_reporting_task = start_live_reporting.apply_async(
                        args=[str(match_id)],
                        eta=match.date_time
                    )
                    self.redis.setex(
                        reporting_key,
                        172800,  # 48 hours
                        new_reporting_task.id
                    )
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
        """Monitor all scheduled matches and their tasks."""
        if session is None:
            # Fall back to g.db_session if no session provided
            session = getattr(g, 'db_session', None)
            if session is None:
                logger.error("No database session available in monitor_all_matches.")
                return {'success': False, 'message': 'No session available'}

        try:
            # Get all matches with scheduled tasks
            matches = session.query(MLSMatch).filter(
                (MLSMatch.live_reporting_scheduled == True) |
                (MLSMatch.thread_creation_time.isnot(None))
            ).all()
            
            results = {}
            for match in matches:
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

task_monitor = TaskMonitor()