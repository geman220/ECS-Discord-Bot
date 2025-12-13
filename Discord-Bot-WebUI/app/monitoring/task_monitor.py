# app/monitoring/task_monitor.py

"""
Task Monitor Utility

Provides the TaskMonitor class for monitoring Celery tasks and their statuses.
"""

import json
import logging
from datetime import datetime

from celery.result import AsyncResult

from app.utils.safe_redis import get_safe_redis
from app.core import celery
from app.core.session_manager import managed_session
from app.models import MLSMatch

logger = logging.getLogger(__name__)


class TaskMonitor:
    """Monitor Celery tasks and their statuses via Redis keys."""

    def __init__(self):
        self.redis = get_safe_redis()

    def get_task_status(self, task_id: str) -> dict:
        """
        Get the status of a specific Celery task.

        Parameters:
            task_id (str): The task ID to check.

        Returns:
            dict: A dictionary with task ID, status, info, readiness, and success flag.
        """
        try:
            result = AsyncResult(task_id, app=celery)
            # Handle result.info properly based on its type
            info_data = None
            if result.info:
                if isinstance(result.info, dict):
                    # Convert dictionary to a simplified format
                    info_data = result.info
                elif hasattr(result.info, '__dict__'):
                    # Handle custom objects by converting to dict
                    info_data = result.info.__dict__
                else:
                    # Convert to string for all other types
                    info_data = str(result.info)

            return {
                'id': task_id,
                'status': result.status or 'PENDING',
                'info': info_data,
                'ready': result.ready(),
                'successful': result.successful() if result.ready() else None
            }
        except Exception as e:
            logger.error(f"Error getting task status for task_id {task_id}: {e}", exc_info=True)
            return {'id': task_id, 'status': 'ERROR', 'error': str(e)}

    def verify_scheduled_tasks(self, match_id: str) -> dict:
        """
        Retrieve scheduled thread and reporting task statuses for a given match.

        Parameters:
            match_id (str): The match identifier.

        Returns:
            dict: A dictionary containing thread and reporting task details.
        """
        try:
            thread_key = f"match_scheduler:{match_id}:thread"
            reporting_key = f"match_scheduler:{match_id}:reporting"

            def parse_value(data):
                if data:
                    s = data.decode('utf-8') if isinstance(data, bytes) else str(data)
                    try:
                        obj = json.loads(s)
                        return obj.get("task_id", s)
                    except Exception:
                        return s
                return None

            thread_task_id = parse_value(self.redis.get(thread_key))
            reporting_task_id = parse_value(self.redis.get(reporting_key))

            # Get detailed task status information
            thread_status = self.get_task_status(thread_task_id) if thread_task_id else None
            reporting_status = self.get_task_status(reporting_task_id) if reporting_task_id else None

            # Get Redis key TTL information
            thread_ttl = self.redis.ttl(thread_key) if thread_task_id else None
            reporting_ttl = self.redis.ttl(reporting_key) if reporting_task_id else None

            return {
                'success': True,
                'thread_task': {
                    'id': thread_task_id,
                    'status': thread_status,
                    'redis_key': thread_key,
                    'ttl': thread_ttl,
                    'is_scheduled': thread_task_id is not None,
                    'summary': self._get_task_summary(thread_status, 'Thread Creation')
                },
                'reporting_task': {
                    'id': reporting_task_id,
                    'status': reporting_status,
                    'redis_key': reporting_key,
                    'ttl': reporting_ttl,
                    'is_scheduled': reporting_task_id is not None,
                    'summary': self._get_task_summary(reporting_status, 'Live Reporting')
                }
            }
        except Exception as e:
            logger.error(f"Error verifying tasks for match {match_id}: {e}", exc_info=True)
            return {'success': False, 'error': str(e)}

    def _get_task_summary(self, task_status: dict, task_type: str) -> str:
        """
        Generate a human-readable summary of task status.

        Parameters:
            task_status (dict): Task status information
            task_type (str): Type of task (e.g., 'Thread Creation', 'Live Reporting')

        Returns:
            str: Human-readable task summary
        """
        if not task_status:
            return f"{task_type}: Not scheduled"

        status = task_status.get('status', 'UNKNOWN')

        # Try to extract ETA from task info for better display
        eta_info = ""
        if task_status.get('info') and isinstance(task_status['info'], dict):
            eta = task_status['info'].get('eta')
            if eta:
                try:
                    eta_date = datetime.fromisoformat(eta.replace('Z', '+00:00'))
                    eta_info = f" (scheduled for {eta_date.strftime('%Y-%m-%d %H:%M:%S UTC')})"
                except:
                    pass

        if status == 'PENDING':
            return f"{task_type}: Scheduled and waiting to execute{eta_info}"
        elif status == 'SUCCESS':
            return f"{task_type}: Completed successfully"
        elif status == 'FAILURE':
            error_info = task_status.get('info', 'Unknown error')
            return f"{task_type}: Failed - {error_info}"
        elif status == 'RETRY':
            return f"{task_type}: Retrying after failure"
        elif status == 'REVOKED':
            return f"{task_type}: Task was cancelled"
        elif status == 'STARTED':
            return f"{task_type}: Currently executing"
        else:
            return f"{task_type}: Status {status}"

    def monitor_all_matches(self) -> dict:
        """
        Monitor all matches that have live reporting scheduled.

        Returns:
            dict: A dictionary mapping match IDs to their scheduled task details.
        """
        try:
            with managed_session() as session:
                matches = session.query(MLSMatch).filter(MLSMatch.live_reporting_scheduled == True).all()
                results = {}
                for match in matches:
                    results[str(match.id)] = self.verify_scheduled_tasks(str(match.id))
                return {'success': True, 'matches': results}
        except Exception as e:
            logger.error(f"Error monitoring matches: {e}", exc_info=True)
            return {'success': False, 'error': str(e)}

    def _process_redis_keys(self, keys: list) -> dict:
        """
        Process Redis keys to extract scheduled task details.

        Parameters:
            keys (list): List of Redis keys (bytes).

        Returns:
            dict: A mapping of match IDs to their task information.
        """
        scheduled_tasks = {}
        for key in keys:
            key_str = key.decode('utf-8') if isinstance(key, bytes) else str(key)
            task_data = self.redis.get(key)
            if task_data and isinstance(task_data, bytes):
                task_data = task_data.decode('utf-8')
            ttl = self.redis.ttl(key)
            # Expected key format: match_scheduler:<match_id>:<task_type>
            try:
                _, match_id, task_type = key_str.split(':')
            except ValueError:
                logger.error(f"Unexpected Redis key format: {key_str}")
                continue
            if match_id not in scheduled_tasks:
                scheduled_tasks[match_id] = {}
            scheduled_tasks[match_id][task_type] = {'task_id': task_data, 'ttl': ttl}
        return scheduled_tasks


# Singleton instance
task_monitor = TaskMonitor()
