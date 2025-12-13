# app/monitoring.py

"""
Monitoring Module

This module defines endpoints and utilities for application monitoring, including task
status, Redis key inspection, database connection statistics, system resource usage,
and debugging information. These endpoints help administrators (Global Admin)
track live reporting tasks, inspect Redis keys, monitor DB connections, and gather
performance data from the system.

Improvements in this version:
   Enhanced logging with more context (including raw timestamp fields).
   Warnings for transactions running longer than a defined threshold.
   Better error messages and additional details returned in JSON responses.
   More modular code with additional comments.
"""

import json
import logging
import psutil
import time
from datetime import datetime, timedelta

from flask import Blueprint, render_template, jsonify, current_app, request
from flask_login import login_required
from celery.result import AsyncResult
from sqlalchemy import text, or_

from app.decorators import role_required
from app.utils.redis_manager import get_redis_manager
from app.utils.safe_redis import get_safe_redis
from app.utils.session_monitor import get_session_monitor
from app.db_management import db_manager
from app.core import celery, db
from app.core.helpers import get_match
from app.models import MLSMatch
from app.database.db_models import DBMonitoringSnapshot
from app.tasks.tasks_live_reporting import start_live_reporting, force_create_mls_thread_task
from app.core.session_manager import managed_session

logger = logging.getLogger(__name__)

monitoring_bp = Blueprint('monitoring', __name__, url_prefix='/monitoring')


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


task_monitor = TaskMonitor()


@monitoring_bp.route('/', endpoint='monitor_dashboard')
@login_required
@role_required('Global Admin')
def monitor_dashboard():
    """
    Render the monitoring dashboard page.
    
    Accessible only to Global Admin users.
    """
    return render_template('monitoring.html', title='Monitoring Dashboard')


@monitoring_bp.route('/tasks/all', endpoint='get_all_tasks')
@login_required
@role_required('Global Admin')
def get_all_tasks():
    """
    Retrieve the scheduled tasks for all matches with detailed match information.
    
    Returns:
        JSON response with scheduled tasks details including match names and teams.
    """
    try:
        with managed_session() as session:
            # Get active matches (same criteria as cache system)
            from datetime import datetime, timedelta
            now = datetime.utcnow()
            matches = session.query(MLSMatch).filter(
                MLSMatch.date_time >= now - timedelta(days=2),
                MLSMatch.date_time <= now + timedelta(days=7)
            ).order_by(MLSMatch.date_time).all()
            
            # Collect all tasks for the frontend (flattened format)
            all_tasks = []
            matches_info = []
            
            for match in matches:
                # Use enhanced task status with cache
                try:
                    from app.utils.task_status_helper import get_enhanced_match_task_status
                    tasks_info = get_enhanced_match_task_status(match.id)
                except ImportError:
                    # Fallback to original monitoring logic
                    tasks_info = task_monitor.verify_scheduled_tasks(str(match.id))
                
                # Create match info
                match_info = {
                    'id': match.id,
                    'match_id': match.match_id,
                    'home_team': 'Seattle Sounders FC' if match.is_home_game else match.opponent,
                    'away_team': match.opponent if match.is_home_game else 'Seattle Sounders FC',
                    'opponent': match.opponent,
                    'date': match.date_time.isoformat() if match.date_time else None,
                    'venue': match.venue,
                    'competition': match.competition,
                    'is_home_game': match.is_home_game,
                    'discord_thread_id': match.discord_thread_id,
                    'tasks': tasks_info
                }
                matches_info.append(match_info)
                
                # Flatten tasks for the frontend
                if tasks_info.get('success') and tasks_info.get('tasks'):
                    tasks = tasks_info['tasks']
                    match_display = f"{'Sounders vs ' + match.opponent if match.is_home_game else match.opponent + ' vs Sounders'}"
                    
                    # Add thread creation task if exists
                    if 'thread' in tasks:
                        thread_task = tasks['thread']
                        all_tasks.append({
                            'name': f"Thread Creation - {match_display}",
                            'type': 'Thread Creation',
                            'match_id': match.id,
                            'status': thread_task.get('status', 'UNKNOWN'),
                            'task_id': thread_task.get('task_id', 'unknown'),
                            'eta': thread_task.get('eta'),
                            'result': thread_task.get('result'),
                            'message': thread_task.get('message', ''),
                            'fallback': thread_task.get('fallback', False),
                            'timestamp': tasks_info.get('timestamp')
                        })
                    
                    # Add live reporting task if exists
                    if 'reporting' in tasks:
                        reporting_task = tasks['reporting']
                        all_tasks.append({
                            'name': f"Live Reporting - {match_display}",
                            'type': 'Live Reporting', 
                            'match_id': match.id,
                            'status': reporting_task.get('status', 'UNKNOWN'),
                            'task_id': reporting_task.get('task_id', 'unknown'),
                            'eta': reporting_task.get('eta'),
                            'result': reporting_task.get('result'),
                            'message': reporting_task.get('message', ''),
                            'fallback': reporting_task.get('fallback', False),
                            'timestamp': tasks_info.get('timestamp')
                        })
            
            return jsonify({
                'success': True,
                'matches': matches_info,
                'tasks': all_tasks,  # Flattened for frontend compatibility
                'total_matches': len(matches_info),
                'total_tasks': len(all_tasks)
            })
    except Exception as e:
        logger.error(f"Error getting all tasks: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@monitoring_bp.route('/tasks/dashboard', endpoint='get_task_dashboard')
@login_required
@role_required('Global Admin')
def get_task_dashboard():
    """
    Enhanced task monitoring dashboard with comprehensive match and task details.
    
    Returns:
        JSON response with detailed task monitoring information including:
        - Match details (teams, venue, competition, dates)
        - Task status summaries
        - Redis key information
        - Task execution times and TTL
        - Overall system health
    """
    try:
        with managed_session() as session:
            # Only show matches that are upcoming or recently completed (within 3 hours)
            cutoff_time = datetime.utcnow() - timedelta(hours=3)
            
            matches = session.query(MLSMatch).filter(
                (MLSMatch.date_time >= cutoff_time) &
                (
                    (MLSMatch.live_reporting_scheduled == True) |
                    (MLSMatch.thread_creation_scheduled == True) |
                    (MLSMatch.thread_created == True) |
                    (MLSMatch.live_reporting_started == True)
                )
            ).order_by(MLSMatch.date_time.asc()).all()
            
            dashboard_data = {
                'success': True,
                'summary': {
                    'total_matches': len(matches),
                    'live_reporting_scheduled': 0,
                    'thread_creation_scheduled': 0,
                    'active_tasks': 0,
                    'failed_tasks': 0
                },
                'matches': []
            }
            
            for match in matches:
                tasks_info = task_monitor.verify_scheduled_tasks(str(match.id))
                
                # Count task statuses for summary
                if tasks_info.get('success') and tasks_info.get('thread_task', {}).get('is_scheduled'):
                    dashboard_data['summary']['thread_creation_scheduled'] += 1
                    thread_status = tasks_info['thread_task']['status']
                    if thread_status and thread_status.get('status') in ['PENDING', 'STARTED']:
                        dashboard_data['summary']['active_tasks'] += 1
                    elif thread_status and thread_status.get('status') == 'FAILURE':
                        dashboard_data['summary']['failed_tasks'] += 1
                
                if tasks_info.get('success') and tasks_info.get('reporting_task', {}).get('is_scheduled'):
                    dashboard_data['summary']['live_reporting_scheduled'] += 1
                    reporting_status = tasks_info['reporting_task']['status']
                    if reporting_status and reporting_status.get('status') in ['PENDING', 'STARTED']:
                        dashboard_data['summary']['active_tasks'] += 1
                    elif reporting_status and reporting_status.get('status') == 'FAILURE':
                        dashboard_data['summary']['failed_tasks'] += 1
                
                # Enhanced match information for dashboard
                match_info = {
                    'id': match.id,
                    'match_id': match.match_id,
                    'display_name': f"{'vs' if not match.is_home_game else ''} {match.opponent}",
                    'home_team': 'Seattle Sounders FC' if match.is_home_game else match.opponent,
                    'away_team': match.opponent if match.is_home_game else 'Seattle Sounders FC',
                    'opponent': match.opponent,
                    'date': match.date_time.isoformat() if match.date_time else None,
                    'venue': match.venue,
                    'competition': match.competition,
                    'is_home_game': match.is_home_game,
                    'match_status': {
                        'live_reporting_scheduled': match.live_reporting_scheduled,
                        'live_reporting_started': match.live_reporting_started,
                        'live_reporting_status': match.live_reporting_status,
                        'thread_created': match.thread_created,
                        'thread_creation_scheduled': match.thread_creation_scheduled,
                        'discord_thread_id': match.discord_thread_id
                    },
                    'scheduling_info': {
                        'thread_creation_time': match.thread_creation_time.isoformat() if match.thread_creation_time else None,
                        'last_thread_scheduling_attempt': match.last_thread_scheduling_attempt.isoformat() if match.last_thread_scheduling_attempt else None,
                        'live_reporting_task_id': match.live_reporting_task_id,
                        'thread_creation_task_id': match.thread_creation_task_id
                    },
                    'tasks': tasks_info,
                    'links': {
                        'summary_link': match.summary_link,
                        'stats_link': match.stats_link,
                        'commentary_link': match.commentary_link
                    }
                }
                dashboard_data['matches'].append(match_info)
            
            return jsonify(dashboard_data)
            
    except Exception as e:
        logger.error(f"Error generating task dashboard: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@monitoring_bp.route('/tasks/match/<match_id>', endpoint='get_match_tasks')
@login_required
def get_match_tasks(match_id):
    """
    Retrieve scheduled tasks for a specific match using enhanced logic.
    
    Parameters:
        match_id (str): The match identifier.
    
    Returns:
        JSON response with the scheduled tasks for the match.
    """
    try:
        # For now, use the enhanced logic by importing the utility function
        # We'll create a shared utility function in a future update
        
        # Try to call the enhanced task status logic directly
        try:
            from app.utils.task_status_helper import get_enhanced_match_task_status
            result = get_enhanced_match_task_status(int(match_id))
            response = jsonify(result)
            response.headers['Cache-Control'] = 'max-age=30, public'
            return response
            
        except ImportError:
            # Fallback to original monitoring logic if helper doesn't exist yet
            result = task_monitor.verify_scheduled_tasks(match_id)
            return jsonify(result)
            
    except Exception as e:
        logger.error(f"Error getting tasks for match {match_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@monitoring_bp.route('/queues/status', endpoint='get_queue_status')
@login_required
def get_queue_status():
    """
    Get real-time queue lengths and health status.
    
    Returns:
        JSON response with queue lengths, health status, and alerts.
    """
    try:
        # Try direct Redis connection first to bypass any safe_redis issues
        try:
            from app.utils.redis_manager import UnifiedRedisManager
            redis_manager = UnifiedRedisManager()
            direct_redis = redis_manager.get_decoded_client()
            direct_redis.ping()
            logger.info("Direct Redis connection successful")
            
            # Use direct connection for queue operations
            redis_client = direct_redis
            
        except Exception as e:
            logger.error(f"Direct Redis connection failed: {e}")
            return jsonify({
                'success': False, 
                'error': f'Redis connection failed: {str(e)}',
                'queues': {},
                'alerts': []
            })
        
        queues = ['live_reporting', 'discord', 'celery', 'player_sync']
        queue_thresholds = {
            'live_reporting': 50,
            'discord': 25, 
            'celery': 100,
            'player_sync': 15
        }
        
        queue_data = {}
        alerts = []
        total_tasks = 0
        
        for queue_name in queues:
            try:
                length = redis_client.llen(queue_name)
                threshold = queue_thresholds.get(queue_name, 50)
                
                status = 'healthy'
                if length > threshold * 2:
                    status = 'critical'
                    alerts.append({
                        'queue': queue_name,
                        'message': f'Queue {queue_name} critically backed up: {length} tasks',
                        'severity': 'error'
                    })
                elif length > threshold:
                    status = 'warning'
                    alerts.append({
                        'queue': queue_name,
                        'message': f'Queue {queue_name} growing: {length} tasks',
                        'severity': 'warning'
                    })
                
                queue_data[queue_name] = {
                    'length': length,
                    'threshold': threshold,
                    'status': status,
                    'percentage': min(100, (length / threshold) * 100) if threshold > 0 else 0
                }
                total_tasks += length
                
            except Exception as e:
                queue_data[queue_name] = {
                    'error': str(e),
                    'status': 'error',
                    'length': 0
                }
        
        return jsonify({
            'success': True,
            'queues': queue_data,
            'total_tasks': total_tasks,
            'alerts': alerts,
            'timestamp': datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error getting queue status: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@monitoring_bp.route('/queue/details', endpoint='get_queue_details')
@login_required
def get_queue_details():
    """
    Get detailed information about tasks in all queues.
    
    Returns:
        JSON response with detailed task information for each queue.
    """
    try:
        # Use direct Redis connection
        try:
            from app.utils.redis_manager import UnifiedRedisManager
            redis_manager = UnifiedRedisManager()
            direct_redis = redis_manager.get_decoded_client()
            direct_redis.ping()
            logger.info("Direct Redis connection successful for queue details")
            redis_client = direct_redis
        except Exception as e:
            logger.error(f"Direct Redis connection failed for queue details: {e}")
            return jsonify({'success': False, 'error': f'Redis connection failed: {str(e)}'}), 500
        
        # Use Celery inspect to get detailed queue information
        timeout = 2.0  # 2 second timeout
        i = celery.control.inspect(timeout=timeout)
        
        # Get scheduled, reserved, and active tasks
        scheduled = i.scheduled() or {}
        reserved = i.reserved() or {}
        active = i.active() or {}
        
        # Organize tasks by queue
        queues = {}
        
        # Process scheduled tasks
        for worker_name, tasks in scheduled.items():
            for task in tasks:
                queue_name = task.get('delivery_info', {}).get('routing_key', 'celery')
                if queue_name not in queues:
                    queues[queue_name] = []
                
                task_info = {
                    'id': task.get('id', ''),
                    'name': task.get('request', {}).get('task') or task.get('name', 'Unknown'),
                    'args': task.get('request', {}).get('args', []),
                    'kwargs': task.get('request', {}).get('kwargs', {}),
                    'eta': task.get('eta'),
                    'priority': task.get('priority'),
                    'worker': worker_name,
                    'status': 'scheduled'
                }
                queues[queue_name].append(task_info)
        
        # Process reserved tasks
        for worker_name, tasks in reserved.items():
            for task in tasks:
                queue_name = task.get('delivery_info', {}).get('routing_key', 'celery')
                if queue_name not in queues:
                    queues[queue_name] = []
                
                task_info = {
                    'id': task.get('id', ''),
                    'name': task.get('name', 'Unknown'),
                    'args': task.get('args', []),
                    'kwargs': task.get('kwargs', {}),
                    'eta': task.get('eta'),
                    'priority': task.get('priority'),
                    'worker': worker_name,
                    'status': 'reserved'
                }
                queues[queue_name].append(task_info)
        
        # Process active tasks
        for worker_name, tasks in active.items():
            for task in tasks:
                queue_name = task.get('delivery_info', {}).get('routing_key', 'celery')
                if queue_name not in queues:
                    queues[queue_name] = []
                
                task_info = {
                    'id': task.get('id', ''),
                    'name': task.get('name', 'Unknown'),
                    'args': task.get('args', []),
                    'kwargs': task.get('kwargs', {}),
                    'eta': None,  # Active tasks don't have ETA
                    'priority': None,
                    'worker': worker_name,
                    'status': 'active'
                }
                queues[queue_name].append(task_info)
        
        # Also check Redis directly for any queued messages
        try:
            # Check common Celery queue names in Redis
            queue_names = ['celery', 'live_reporting', 'thread_creation', 'default']
            for queue_name in queue_names:
                redis_key = queue_name
                queue_length = redis_client.llen(redis_key)
                
                if queue_length > 0:
                    if queue_name not in queues:
                        queues[queue_name] = []
                    
                    # Get a sample of tasks from Redis queue (up to 10)
                    sample_tasks = redis_client.lrange(redis_key, 0, 9)
                    logger.info(f"Found {len(sample_tasks)} tasks in {queue_name} queue")
                    
                    for i, task_data in enumerate(sample_tasks):
                        try:
                            logger.debug(f"Processing task {i}: {task_data[:200]}...")  # Log first 200 chars
                            
                            # Try different parsing approaches
                            task_json = None
                            if isinstance(task_data, str):
                                try:
                                    task_json = json.loads(task_data)
                                except json.JSONDecodeError:
                                    # Maybe it's base64 encoded?
                                    try:
                                        import base64
                                        decoded = base64.b64decode(task_data)
                                        task_json = json.loads(decoded.decode('utf-8'))
                                    except:
                                        pass
                            else:
                                task_json = task_data
                            
                            if task_json:
                                # Try different field names for task information
                                task_name = (
                                    task_json.get('task') or 
                                    task_json.get('name') or
                                    task_json.get('headers', {}).get('task') or
                                    task_json.get('properties', {}).get('correlation_id') or
                                    'Unknown Task'
                                )
                                
                                task_id = (
                                    task_json.get('id') or
                                    task_json.get('uuid') or
                                    task_json.get('headers', {}).get('id') or
                                    task_json.get('properties', {}).get('correlation_id') or
                                    f"queue_item_{i}"
                                )
                                
                                # Handle different body formats
                                body = task_json.get('body', task_json)
                                if isinstance(body, list) and len(body) >= 2:
                                    args = body[0] if isinstance(body[0], list) else []
                                    kwargs = body[1] if isinstance(body[1], dict) else {}
                                else:
                                    args = task_json.get('args', body.get('args', []) if isinstance(body, dict) else [])
                                    kwargs = task_json.get('kwargs', body.get('kwargs', {}) if isinstance(body, dict) else {})
                                
                                task_info = {
                                    'id': task_id,
                                    'name': task_name,
                                    'args': args,
                                    'kwargs': kwargs,
                                    'eta': task_json.get('eta') or task_json.get('headers', {}).get('eta'),
                                    'priority': task_json.get('priority') or task_json.get('headers', {}).get('priority'),
                                    'worker': 'N/A',
                                    'status': 'queued_in_redis',
                                    'raw_data': str(task_data)[:100] + '...' if len(str(task_data)) > 100 else str(task_data)
                                }
                                logger.info(f"Parsed task: {task_name} with ID {task_id}")
                            else:
                                # Could not parse JSON, create a basic entry with raw data
                                task_info = {
                                    'id': f"unparsed_{i}",
                                    'name': f'Raw Redis Entry',
                                    'args': [],
                                    'kwargs': {},
                                    'eta': None,
                                    'priority': None,
                                    'worker': 'N/A',
                                    'status': 'queued_in_redis',
                                    'raw_data': str(task_data)[:200] + '...' if len(str(task_data)) > 200 else str(task_data)
                                }
                                logger.warning(f"Could not parse task data, storing raw: {str(task_data)[:100]}...")
                            
                            queues[queue_name].append(task_info)
                            
                        except Exception as task_error:
                            logger.error(f"Error processing task {i}: {task_error}", exc_info=True)
                            # Add a basic entry for problematic tasks
                            task_info = {
                                'id': f"error_{i}",
                                'name': f'Error parsing task',
                                'args': [],
                                'kwargs': {},
                                'eta': None,
                                'priority': None,
                                'worker': 'N/A',
                                'status': 'parse_error',
                                'raw_data': str(task_data)[:100] + '...' if len(str(task_data)) > 100 else str(task_data)
                            }
                            queues[queue_name].append(task_info)
        except Exception as redis_error:
            logger.error(f"Error checking Redis queues directly: {redis_error}", exc_info=True)
        
        return jsonify({
            'success': True,
            'queues': queues,
            'total_tasks': sum(len(tasks) for tasks in queues.values())
        })
        
    except Exception as e:
        logger.error(f"Error getting queue details: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@monitoring_bp.route('/redis/keys', endpoint='get_redis_keys')
@login_required
@role_required('Global Admin')
def get_redis_keys():
    """
    Retrieve all Redis keys related to match scheduling.
    Only shows recent keys (within 24 hours) to reduce clutter.
    
    Returns:
        JSON response with key details including value, TTL, and task status.
    """
    try:
        # Use safe Redis client like the rest of the monitoring system
        redis_client = get_safe_redis()
        scheduler_keys = redis_client.keys('match_scheduler:*')
        result = {}
        filtered_count = 0
        
        for key in scheduler_keys:
            try:
                key_str = key.decode('utf-8') if isinstance(key, bytes) else str(key)
                value = redis_client.get(key)
                ttl = redis_client.ttl(key)
                
                # Skip keys that have already expired or will expire very soon (< 60 seconds)
                if ttl < 60 and ttl != -1:
                    filtered_count += 1
                    continue
                
                stored_value = None
                if value is not None:
                    value_str = value.decode('utf-8') if isinstance(value, bytes) else str(value)
                    try:
                        stored_obj = json.loads(value_str)
                        stored_value = stored_obj.get("task_id", value_str)
                    except Exception:
                        stored_value = value_str
                
                task_status = None
                if stored_value and len(stored_value) == 36:
                    try:
                        task = AsyncResult(stored_value, app=celery)
                        task_status = {
                            'id': stored_value,
                            'status': task.status,
                            'ready': task.ready(),
                            'successful': task.successful() if task.ready() else None
                        }
                        
                        # Skip completed tasks that are old
                        if task.ready() and task.successful() and ttl > 3600:  # Completed more than 1 hour ago
                            filtered_count += 1
                            continue
                            
                    except Exception as task_error:
                        logger.warning(f"Error getting task status for {stored_value}: {task_error}")
                
                result[key_str] = {
                    'value': value.decode('utf-8') if isinstance(value, bytes) else value,
                    'ttl': ttl,
                    'task_status': task_status
                }
            except Exception as key_error:
                logger.error(f"Error processing Redis key {key}: {key_error}", exc_info=True)
                result[str(key)] = {'error': str(key_error)}
        
        return jsonify({
            'success': True, 
            'keys': result, 
            'total': len(result),
            'filtered_count': filtered_count,
            'total_found': len(scheduler_keys)
        })
    except Exception as e:
        logger.error(f"Error getting Redis keys: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@monitoring_bp.route('/redis/test', endpoint='test_redis')
@login_required
@role_required('Global Admin')
def test_redis():
    """
    Test Redis connection and retrieve scheduler keys information.
    
    Returns:
        JSON response with ping result, total keys, and detailed key info.
    """
    try:
        redis_client = get_safe_redis()
        ping_result = redis_client.ping()
        scheduler_keys = redis_client.keys('match_scheduler:*')
        keys_info = {}
        for key in scheduler_keys:
            try:
                key_str = key.decode('utf-8') if isinstance(key, bytes) else str(key)
                value = redis_client.get(key)
                if value is not None:
                    try:
                        value = value.decode('utf-8') if isinstance(value, bytes) else str(value)
                    except (UnicodeDecodeError, AttributeError):
                        value = str(value)
                ttl = redis_client.ttl(key)
                task_status = None
                if value and len(value) == 36:
                    try:
                        task = AsyncResult(value, app=celery)
                        task_status = {
                            'id': value,
                            'status': task.status,
                            'ready': task.ready(),
                            'successful': task.successful() if task.ready() else None
                        }
                    except Exception as task_error:
                        logger.warning(f"Error getting task status for {value}: {task_error}")
                keys_info[key_str] = {'value': value, 'ttl': ttl, 'task_status': task_status}
            except Exception as key_error:
                logger.error(f"Error processing key {key}: {key_error}", exc_info=True)
                keys_info[str(key)] = {'error': str(key_error)}
        logger.info(f"Redis connection test: {ping_result}")
        logger.info(f"Found {len(scheduler_keys)} scheduler keys")
        return jsonify({
            'success': True,
            'ping': ping_result,
            'total_keys': len(scheduler_keys),
            'keys': keys_info
        })
    except Exception as e:
        logger.error(f"Redis test failed: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@monitoring_bp.route('/tasks/revoke', endpoint='revoke_task', methods=['POST'])
@login_required
@role_required('Global Admin')
def revoke_task():
    """
    Revoke a specific scheduled task and clean up its Redis key.
    
    Expects JSON payload with either:
    1. 'key' and 'task_id' (for Redis-based tasks)
    2. 'worker' and either 'task_name' or 'task_id' (for scheduled tasks on workers)
    
    Returns:
        JSON response indicating revocation status.
    """
    try:
        # Log the raw payload for debugging
        data = request.get_json()
        logger.info(f"Revoke task request payload: {data}")
        
        if not data:
            return jsonify({'success': False, 'error': 'No JSON payload provided'}), 400
            
        key = data.get('key')
        task_id = data.get('task_id')
        worker = data.get('worker')
        task_name = data.get('task_name')
        
        logger.info(f"Parsed parameters: key={key}, task_id={task_id}, worker={worker}, task_name={task_name}")
        
        # Check which mode we're operating in
        if key and task_id:
            # Mode 1: Revoke Redis-based task
            logger.info(f"Revoking task {task_id} and cleaning up Redis key {key}")
            celery.control.revoke(task_id, terminate=True)
            redis_client = get_safe_redis()
            redis_client.delete(key)
            with managed_session() as session:
                if 'thread' in key:
                    match_id = key.split(':')[1]
                    match = get_match(session, match_id)
                    if match:
                        match.thread_creation_time = None
                elif 'reporting' in key:
                    match_id = key.split(':')[1]
                    match = get_match(session, match_id)
                    if match:
                        match.live_reporting_scheduled = False
                        match.live_reporting_started = False
                        match.live_reporting_status = 'not_started'
            return jsonify({'success': True, 'message': f'Task {task_id} revoked and Redis key {key} removed'})
        
        elif worker:
            # Mode 2: Revoke a scheduled task on a worker - try with any provided ID
            logger.info(f"Revoking task on worker {worker}")
            
            # If we have a task_id, use it directly
            if task_id:
                try:
                    celery.control.revoke(task_id, terminate=True, destination=[worker])
                    logger.info(f"Directly revoked task {task_id} on worker {worker}")
                    return jsonify({'success': True, 'message': f'Task {task_id} revoked on worker {worker}'})
                except Exception as e:
                    logger.warning(f"Direct revoke failed, trying without destination: {e}")
                    celery.control.revoke(task_id, terminate=True)
                    logger.info(f"Revoked task {task_id} globally")
                    return jsonify({'success': True, 'message': f'Task {task_id} revoked globally'})
            
            # No task_id but we have a worker and maybe task_name - try to find scheduled tasks
            # Add a short timeout to avoid blocking
            i = celery.control.inspect(timeout=3.0)
            
            # Get current scheduled tasks with better error handling
            scheduled = {}
            worker_tasks = []
            
            try:
                # Try first approach - get all scheduled tasks
                scheduled = i.scheduled() or {}
                worker_tasks = scheduled.get(worker, [])
                
                if not worker_tasks:
                    # Try targeted approach - explicitly specify worker
                    scheduled = i.scheduled([worker]) or {}
                    worker_tasks = scheduled.get(worker, [])
                
                # If still no tasks, try alternative API
                if not worker_tasks:
                    # Try to get active tasks
                    active = i.active([worker]) or {}
                    active_tasks = active.get(worker, [])
                    
                    # Try to get reserved tasks
                    reserved = i.reserved([worker]) or {}
                    reserved_tasks = reserved.get(worker, [])
                    
                    # Combine all tasks
                    worker_tasks = worker_tasks + active_tasks + reserved_tasks
                    
                    logger.info(f"Found additional tasks: {len(active_tasks)} active, {len(reserved_tasks)} reserved")
            except Exception as e:
                logger.warning(f"Error getting scheduled tasks: {e}")
            
            logger.info(f"Found {len(worker_tasks)} scheduled tasks on worker {worker}")
            
            # If no specific task name, revoke all for this worker - even if no tasks found, try additional methods
            if not task_name:
                logger.info(f"Attempting to revoke tasks on worker {worker} - found {len(worker_tasks)} scheduled tasks")
                
                # Log the task details to debug
                task_ids = []
                for i, task in enumerate(worker_tasks):
                    task_id = task.get('id')
                    task_name = task.get('name')
                    eta = task.get('eta')
                    logger.info(f"Task {i+1}: id={task_id}, name={task_name}, eta={eta}")
                    if task_id:
                        task_ids.append(task_id)
                
                # First try to revoke each task individually
                revoked_count = 0
                
                # If we have task_ids, try revoking them individually
                if task_ids:
                    for task_id in task_ids:
                        try:
                            logger.info(f"Attempting to revoke individual task {task_id}")
                            celery.control.revoke(task_id, terminate=True)
                            revoked_count += 1
                            logger.info(f"Successfully revoked task {task_id}")
                        except Exception as e:
                            logger.warning(f"Error revoking task {task_id}: {e}")
                
                # Also try direct revocation by worker name and queue purging
                try:
                    logger.info(f"Attempting to revoke all tasks for worker {worker}")
                    
                    # First, try to purge all known queues that might be on this worker
                    queue_names = ['celery', 'live_reporting', 'default', 'high', 'low']
                    for queue_name in queue_names:
                        try:
                            purge_result = celery.control.purge(queue_name)
                            if purge_result and worker in purge_result:
                                purged = purge_result[worker]
                                if purged > 0:
                                    logger.info(f"Purged {purged} tasks from queue {queue_name} on worker {worker}")
                                    revoked_count += purged
                        except Exception as e:
                            logger.warning(f"Error purging queue {queue_name}: {e}")
                    
                    # Then try to revoke all tasks for this worker
                    result = celery.control.revoke(None, destination=[worker], terminate=True)
                    logger.info(f"Revocation by worker result: {result}")
                    # Count this as at least one revoked task
                    revoked_count += 1
                    
                    # Finally, restart the worker pool to clear any stuck tasks
                    try:
                        celery.control.pool_restart(destination=[worker])
                        logger.info(f"Restarted worker pool for {worker}")
                    except Exception as e:
                        logger.warning(f"Error restarting worker pool: {e}")
                        
                except Exception as e:
                    logger.warning(f"Error revoking all tasks for worker {worker}: {e}")
                
                # Always try direct task deletion via direct Redis access
                try:
                    logger.info("Attempting direct Redis task deletion")
                    redis_client = get_safe_redis()
                    
                    # Try to find and delete scheduled task entries directly in Redis
                    # Common Celery Redis keys for scheduled tasks
                    scheduled_task_keys = [
                        f"unacked_{worker}",  # Unacknowledged tasks
                        f"unacked.{worker}",
                        f"{worker}.unacked",
                        "celery",             # Default queue
                        "celery-schedule",    # Celery beat schedule
                        "_kombu.binding.celery", # Celery bindings
                    ]
                    
                    # Search for keys that contain the worker name
                    all_keys = redis_client.keys("*")
                    worker_keys = []
                    
                    for key in all_keys:
                        key_str = key.decode('utf-8') if isinstance(key, bytes) else str(key)
                        # Check if this key might be related to our worker
                        if worker in key_str or "celery" in key_str.lower():
                            worker_keys.append(key)
                            
                    # Add our specific known keys
                    for key_pattern in scheduled_task_keys:
                        pattern_matches = redis_client.keys(key_pattern)
                        worker_keys.extend(pattern_matches)
                        
                    # Remove duplicates
                    worker_keys = list(set(worker_keys))
                    
                    logger.info(f"Found {len(worker_keys)} potential Redis keys for worker {worker}")
                    
                    # Try to examine and clean each key
                    cleaned_keys = 0
                    for key in worker_keys:
                        try:
                            key_str = key.decode('utf-8') if isinstance(key, bytes) else str(key)
                            logger.info(f"Examining Redis key: {key_str}")
                            
                            # For each key, try to determine the type and clean appropriately
                            key_type = redis_client.type(key)
                            key_type_str = key_type.decode('utf-8') if isinstance(key_type, bytes) else str(key_type)
                            
                            if key_type_str == 'hash':
                                # Hash - try to get all values
                                hash_data = redis_client.hgetall(key)
                                logger.info(f"Hash data keys: {list(hash_data.keys())}")
                                # Delete the hash
                                redis_client.delete(key)
                                cleaned_keys += 1
                            elif key_type_str == 'list':
                                # List - get length and clean
                                list_len = redis_client.llen(key)
                                logger.info(f"List length: {list_len}")
                                redis_client.delete(key)
                                cleaned_keys += 1
                            elif key_type_str == 'set':
                                # Set - get members and clean
                                set_members = redis_client.smembers(key)
                                logger.info(f"Set has {len(set_members)} members")
                                redis_client.delete(key)
                                cleaned_keys += 1
                            elif key_type_str == 'zset':
                                # Sorted set - get count and clean
                                zset_count = redis_client.zcard(key)
                                logger.info(f"Sorted set has {zset_count} members")
                                redis_client.delete(key)
                                cleaned_keys += 1
                            elif key_type_str == 'string':
                                # String - get value and clean
                                string_val = redis_client.get(key)
                                logger.info(f"String value length: {len(string_val) if string_val else 0}")
                                redis_client.delete(key)
                                cleaned_keys += 1
                            else:
                                # Unknown type - just delete
                                logger.info(f"Unknown Redis key type: {key_type_str}")
                                redis_client.delete(key)
                                cleaned_keys += 1
                                
                        except Exception as e:
                            logger.warning(f"Error cleaning Redis key {key}: {e}")
                    
                    logger.info(f"Cleaned {cleaned_keys} Redis keys for worker {worker}")
                    revoked_count += cleaned_keys
                except Exception as redis_error:
                    logger.warning(f"Error during direct Redis cleanup: {redis_error}")
                
                # Even if Redis cleanup worked, still try purging the queue
                try:
                    # Get task information for more specific purging
                    queues_to_purge = set()
                    for task in worker_tasks:
                        if 'request' in task and 'delivery_info' in task['request']:
                            queue = task['request']['delivery_info'].get('routing_key', 'celery')
                            queues_to_purge.add(queue)
                    
                    if not queues_to_purge:
                        queues_to_purge.add('celery')  # Default queue
                        
                    # Purge all relevant queues
                    for queue in queues_to_purge:
                        try:
                            result = celery.control.purge(queue)
                            logger.info(f"Purged queue {queue}: {result}")
                            if result:
                                revoked_count += int(result)
                        except Exception as e:
                            logger.warning(f"Error purging queue {queue}: {e}")
                            
                    # Try to cancel all scheduled tasks for this worker
                    try:
                        celery.control.cancel_consumer(queue='celery', destination=[worker])
                        logger.info(f"Canceled consumer for worker {worker}")
                    except Exception as e:
                        logger.warning(f"Error canceling consumer: {e}")
                    
                    # Try direct Celery Beat schedule manipulation
                    try:
                        # Try to clear the beat schedule
                        redis_client = get_safe_redis()
                        redis_client.delete('celery-schedule')
                        logger.info("Cleared Celery Beat schedule")
                        revoked_count += 1
                    except Exception as e:
                        logger.warning(f"Error clearing beat schedule: {e}")
                    
                    # Force restart the worker to ensure tasks are cleared
                    try:
                        celery.control.pool_restart(destination=[worker])
                        logger.info(f"Restarted worker pool for {worker}")
                    except Exception as e:
                        logger.warning(f"Error restarting worker pool: {e}")
                    
                    # If we did any cleanup, consider it success
                    if revoked_count > 0:
                        return jsonify({'success': True, 'message': f'Revoked {revoked_count} tasks and cleared queues for worker {worker}'})
                    
                    # Even if no tasks were explicitly revoked, report success since we tried all methods
                    return jsonify({'success': True, 'message': f'Attempted all cleanup methods for worker {worker}'})
                except Exception as purge_error:
                    logger.warning(f"Error during queue purge: {purge_error}")
                    
                # If we revoked at least one task individually, consider it a success
                if revoked_count > 0:
                    logger.info(f"Revoked {revoked_count} tasks on worker {worker}")
                    return jsonify({'success': True, 'message': f'Revoked {revoked_count} tasks on worker {worker}'})
                else:
                    # Last resort - try purging the default queue
                    try:
                        result = celery.control.purge()
                        logger.info(f"Purged all queues: {result}")
                        return jsonify({'success': True, 'message': f'Purged all queues: {result}'})
                    except Exception as e:
                        logger.warning(f"Error purging all queues: {e}")
                        return jsonify({'success': False, 'error': f'Failed to revoke tasks on worker {worker}. Please manually restart the worker.'}), 500
            
            # Otherwise, we need either task_id or task_name
            return jsonify({'success': False, 'error': f'Task identification not provided for worker {worker}'}), 400

        else:
            return jsonify({'success': False, 'error': 'Missing required parameters. Need either (key and task_id) or (worker)'}), 400
            
    except Exception as e:
        logger.error(f"Error revoking task: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@monitoring_bp.route('/tasks/revoke-all', endpoint='revoke_all_tasks', methods=['POST'])
@login_required
@role_required('Global Admin')
def revoke_all_tasks():
    """
    Revoke all scheduled tasks by cleaning up all Redis keys and updating match records.
    Uses multiple methods to ensure tasks are properly terminated.
    
    Returns:
        JSON response with the number of revoked tasks and any failures.
    """
    try:
        redis_client = get_safe_redis()
        
        # Step 1: Get all scheduler keys
        keys = redis_client.keys('match_scheduler:*')
        revoked_count = 0
        failed_tasks = []
        task_ids = []
        
        logger.info(f"Attempting to revoke {len(keys)} scheduled tasks")
        
        # Step 2: Process each key and collect task IDs
        for key in keys:
            try:
                key_str = key.decode('utf-8') if isinstance(key, bytes) else str(key)
                value = redis_client.get(key)
                if value:
                    # Parse task ID from value
                    value_str = value.decode('utf-8') if isinstance(value, bytes) else str(value)
                    try:
                        # Try to parse as JSON first
                        task_data = json.loads(value_str)
                        task_id = task_data.get('task_id', value_str)
                    except:
                        # If not JSON, assume it's just the task ID
                        task_id = value_str
                    
                    if task_id and len(task_id) == 36:  # Valid UUID
                        task_ids.append(task_id)
                        logger.info(f"Found task {task_id} for key {key_str}")
                    
                    # Delete the Redis key regardless
                    redis_client.delete(key)
                    revoked_count += 1
                else:
                    # Empty key, just delete it
                    redis_client.delete(key)
                    logger.info(f"Deleted empty key: {key_str}")
                    
            except Exception as key_error:
                logger.error(f"Error processing key {key}: {key_error}")
                failed_tasks.append({'key': str(key), 'error': str(key_error)})
        
        # Step 3: Revoke all collected task IDs
        successfully_revoked = 0
        for task_id in task_ids:
            try:
                logger.info(f"Revoking task {task_id}")
                celery.control.revoke(task_id, terminate=True)
                successfully_revoked += 1
            except Exception as revoke_error:
                logger.error(f"Error revoking task {task_id}: {revoke_error}")
                failed_tasks.append({'task_id': task_id, 'error': str(revoke_error)})
        
        # Step 4: Additional cleanup - purge all queues
        try:
            logger.info("Purging all Celery queues")
            purge_result = celery.control.purge()
            logger.info(f"Queue purge result: {purge_result}")
        except Exception as purge_error:
            logger.warning(f"Error purging queues: {purge_error}")
        
        # Step 5: Enhanced worker scheduled tasks cleanup
        try:
            logger.info("Cleaning up worker scheduled tasks (enhanced)")
            i = celery.control.inspect(timeout=3.0)
            scheduled = i.scheduled() or {}
            
            # First pass: revoke individual tasks
            for worker_name, tasks in scheduled.items():
                if tasks:
                    logger.info(f"Found {len(tasks)} scheduled tasks on worker {worker_name}")
                    for task in tasks:
                        task_id = task.get('id')
                        if task_id:
                            try:
                                celery.control.revoke(task_id, terminate=True, destination=[worker_name])
                                successfully_revoked += 1
                                logger.info(f"Revoked task {task_id} on worker {worker_name}")
                            except Exception as e:
                                logger.warning(f"Error revoking worker task {task_id}: {e}")
            
            # Second pass: purge all known queues
            queue_names = ['celery', 'live_reporting', 'default', 'high', 'low']
            for queue_name in queue_names:
                try:
                    purge_result = celery.control.purge(queue_name)
                    if purge_result:
                        total_purged = sum(count for count in purge_result.values() if count)
                        if total_purged > 0:
                            logger.info(f"Purged {total_purged} tasks from queue {queue_name}")
                            successfully_revoked += total_purged
                except Exception as e:
                    logger.warning(f"Error purging queue {queue_name}: {e}")
            
            # Third pass: force worker restart to clear any remaining tasks
            try:
                stats = i.stats() or {}
                for worker_name in stats.keys():
                    try:
                        celery.control.pool_restart(destination=[worker_name])
                        logger.info(f"Restarted worker pool for {worker_name}")
                    except Exception as e:
                        logger.warning(f"Error restarting worker {worker_name}: {e}")
            except Exception as restart_error:
                logger.warning(f"Error during worker restart: {restart_error}")
                
        except Exception as worker_error:
            logger.warning(f"Error cleaning worker tasks: {worker_error}")
        
        # Step 6: Reset match statuses in database
        try:
            with managed_session() as session:
                matches = session.query(MLSMatch).all()
                reset_count = 0
                for match in matches:
                    if (match.thread_creation_time or 
                        match.live_reporting_scheduled or 
                        match.live_reporting_started or 
                        match.live_reporting_status != 'not_started'):
                        
                        match.thread_creation_time = None
                        match.thread_creation_scheduled = False
                        match.live_reporting_scheduled = False
                        match.live_reporting_started = False
                        match.live_reporting_status = 'not_started'
                        reset_count += 1
                
                logger.info(f"Reset {reset_count} match statuses")
        except Exception as db_error:
            logger.error(f"Error resetting match statuses: {db_error}")
            failed_tasks.append({'error': f'Database reset failed: {str(db_error)}'})
        
        # Prepare response
        total_revoked = successfully_revoked + revoked_count
        message = f'Revoked {total_revoked} tasks ({successfully_revoked} task IDs, {revoked_count} Redis keys) and cleaned up Redis'
        
        response_data = {
            'success': True, 
            'message': message,
            'revoked_count': total_revoked,
            'task_ids_revoked': successfully_revoked,
            'redis_keys_cleaned': revoked_count
        }
        
        if failed_tasks:
            response_data['failed_tasks'] = failed_tasks
            response_data['warning'] = f'Some operations failed ({len(failed_tasks)} failures)'
            
        logger.info(f"Revoke all completed: {message}")
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"Error revoking all tasks: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@monitoring_bp.route('/tasks/reschedule', endpoint='reschedule_task', methods=['POST'])
@login_required
@role_required('Global Admin')
def reschedule_task():
    """
    Reschedule a task by revoking the existing task and scheduling a new one.
    
    Expects JSON payload with key and task_id
    
    Returns:
        JSON response with new task ID and status.
    """
    try:
        data = request.get_json()
        key = data.get('key')
        task_id = data.get('task_id')
        if not key or not task_id:
            return jsonify({'success': False, 'error': 'Missing key or task_id'}), 400
        logger.info(f"Rescheduling task {task_id} for key {key}")
        match_id = key.split(':')[1]
        with managed_session() as session:
            match = get_match(session, match_id)
            if not match:
                return jsonify({'success': False, 'error': 'Match not found'}), 404
            celery.control.revoke(task_id, terminate=True)
            redis_client = get_safe_redis()
            redis_client.delete(key)
            if 'thread' in key:
                thread_time = match.date_time - timedelta(hours=48)
                new_task = force_create_mls_thread_task.apply_async(args=[match_id], eta=thread_time)
                match.thread_creation_time = thread_time
                redis_client.setex(key, 172800, new_task.id)
            else:
                reporting_time = match.date_time - timedelta(minutes=5)
                new_task = start_live_reporting.apply_async(args=[str(match_id)], eta=reporting_time)
                match.live_reporting_scheduled = True
                redis_client.setex(key, 172800, new_task.id)
        return jsonify({'success': True, 'message': f'Task rescheduled successfully. New task ID: {new_task.id}', 'new_task_id': new_task.id})
    except Exception as e:
        logger.error(f"Error rescheduling task {task_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@monitoring_bp.route('/queue/purge', endpoint='purge_queue', methods=['POST'])
@login_required
@role_required('Global Admin')
def purge_queue():
    """
    Emergency queue purge - clears all tasks from a specific queue.
    
    Expects JSON payload with 'queue' name.
    
    Returns:
        JSON response indicating purge status.
    """
    try:
        data = request.get_json()
        queue_name = data.get('queue', 'live_reporting')
        
        logger.info(f"Emergency purge requested for queue: {queue_name}")
        
        # Purge the specific queue - try multiple methods
        total_purged = 0
        try:
            # Method 1: Try direct queue purge
            result = celery.control.purge(queue_name)
            logger.info(f"Purge result for queue {queue_name}: {result}")
            
            # Count how many tasks were purged across all workers
            if result:
                for worker, count in result.items():
                    if count:
                        total_purged += count
                        
        except Exception as purge_error:
            logger.warning(f"Error during direct queue purge: {purge_error}")
            
            # Method 2: Try using broker management API if available
            try:
                from celery.app.control import Inspect
                inspect = Inspect(app=celery)
                
                # Get active queues and try to purge them individually
                active_queues = inspect.active_queues()
                if active_queues:
                    for worker, queues in active_queues.items():
                        for queue_info in queues:
                            if queue_info.get('name') == queue_name:
                                try:
                                    # Try worker-specific purge
                                    worker_result = celery.control.purge(queue_name, destination=[worker])
                                    if worker_result and worker in worker_result:
                                        total_purged += worker_result[worker] or 0
                                        logger.info(f"Purged {worker_result[worker]} tasks from {queue_name} on {worker}")
                                except Exception as worker_purge_error:
                                    logger.warning(f"Error purging {queue_name} on {worker}: {worker_purge_error}")
                                    
            except Exception as inspect_error:
                logger.warning(f"Error using inspect API: {inspect_error}")
                
            # Method 3: If all else fails, try Redis-based cleanup
            try:
                redis_client = get_safe_redis()
                
                # Look for Celery queue keys in Redis
                celery_keys = redis_client.keys(f"celery*{queue_name}*") + redis_client.keys(f"*{queue_name}*")
                
                for key in celery_keys:
                    try:
                        key_str = key.decode('utf-8') if isinstance(key, bytes) else str(key)
                        # Check if this looks like a queue key
                        if any(pattern in key_str.lower() for pattern in ['queue', 'task', 'job']):
                            redis_client.delete(key)
                            total_purged += 1
                            logger.info(f"Deleted Redis queue key: {key_str}")
                    except Exception as key_error:
                        logger.warning(f"Error deleting Redis key {key}: {key_error}")
                        
            except Exception as redis_purge_error:
                logger.warning(f"Error during Redis-based purge: {redis_purge_error}")
        
        # Also try to revoke any scheduled tasks in that queue
        try:
            i = celery.control.inspect(timeout=2.0)
            scheduled = i.scheduled() or {}
            
            revoked_scheduled = 0
            for worker_name, tasks in scheduled.items():
                for task in tasks:
                    # Check if task is in the target queue
                    task_queue = 'default'
                    if 'request' in task and 'delivery_info' in task['request']:
                        task_queue = task['request']['delivery_info'].get('routing_key', 'default')
                    elif 'delivery_info' in task:
                        task_queue = task['delivery_info'].get('routing_key', 'default')
                    elif 'queue' in task:
                        task_queue = task['queue']
                    
                    if task_queue == queue_name:
                        task_id = task.get('id')
                        if task_id:
                            try:
                                celery.control.revoke(task_id, terminate=True)
                                revoked_scheduled += 1
                                logger.info(f"Revoked scheduled task {task_id} from queue {queue_name}")
                            except Exception as e:
                                logger.warning(f"Error revoking scheduled task {task_id}: {e}")
                                
        except Exception as scheduled_error:
            logger.warning(f"Error revoking scheduled tasks: {scheduled_error}")
            revoked_scheduled = 0
        
        # Clean up any Redis keys related to the queue/tasks if needed
        redis_cleaned = 0
        try:
            redis_client = get_safe_redis()
            
            # Clean up any live reporting related keys if purging live_reporting queue
            if queue_name == 'live_reporting':
                reporting_keys = redis_client.keys('match_scheduler:*:reporting')
                for key in reporting_keys:
                    redis_client.delete(key)
                    redis_cleaned += 1
                    logger.info(f"Cleaned up Redis key: {key}")
                    
        except Exception as redis_error:
            logger.warning(f"Error cleaning Redis keys: {redis_error}")
        
        message = f"Emergency purge of queue '{queue_name}' completed. "
        message += f"Purged {total_purged} queued tasks, "
        message += f"revoked {revoked_scheduled} scheduled tasks, "
        message += f"cleaned {redis_cleaned} Redis keys."
        
        return jsonify({
            'success': True,
            'message': message,
            'queue': queue_name,
            'purged_tasks': total_purged,
            'revoked_scheduled': revoked_scheduled,
            'redis_cleaned': redis_cleaned
        })
        
    except Exception as e:
        logger.error(f"Error purging queue: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@monitoring_bp.route('/tasks/nuclear_reset', methods=['POST'], endpoint='nuclear_reset')
@login_required
@role_required('Global Admin')
def nuclear_reset():
    """
    Nuclear reset - completely restart the task system from scratch.
    
    This is the most aggressive approach to clear stuck tasks.
    """
    try:
        logger.warning("NUCLEAR RESET - Restarting entire task system")
        
        results = {
            'containers_restarted': 0,
            'redis_flushed': False,
            'details': []
        }
        
        # Step 1: Kill all worker containers
        try:
            import docker
            client = docker.from_env()
            
            containers_to_restart = [
                'celery-worker', 'celery-live-reporting-worker', 
                'celery-discord-worker', 'celery-player-sync-worker',
                'celery-beat'  # Also restart the scheduler
            ]
            
            for container in client.containers.list():
                if any(name in container.name for name in containers_to_restart):
                    try:
                        logger.warning(f"KILLING container: {container.name}")
                        container.kill()  # Force kill, don't restart gracefully
                        container.start()  # Start fresh
                        results['containers_restarted'] += 1
                        results['details'].append(f"Killed and restarted {container.name}")
                    except Exception as e:
                        results['details'].append(f"Failed to restart {container.name}: {str(e)}")
                        
        except Exception as e:
            results['details'].append(f"Docker operations failed: {str(e)}")
        
        # Step 2: Nuclear Redis cleanup - flush task-related data
        try:
            redis_client = get_safe_redis()
            
            # Get all keys that could contain tasks
            patterns = [
                'match_scheduler:*',
                'celery-*',
                '_kombu*',
                'live_reporting*',
                'scheduled_*'
            ]
            
            deleted_count = 0
            for pattern in patterns:
                try:
                    keys = redis_client.keys(pattern)
                    if keys:
                        redis_client.delete(*keys)
                        deleted_count += len(keys)
                        logger.warning(f"Deleted {len(keys)} keys matching {pattern}")
                except Exception as e:
                    results['details'].append(f"Pattern {pattern} cleanup failed: {str(e)}")
            
            results['redis_flushed'] = deleted_count > 0
            results['details'].append(f"Deleted {deleted_count} Redis keys")
            
        except Exception as e:
            results['details'].append(f"Redis cleanup failed: {str(e)}")
        
        # Step 3: Clear database scheduling flags
        try:
            with managed_session() as session:
                # Reset all scheduling flags in the database
                matches = session.query(MLSMatch).filter(
                    or_(
                        MLSMatch.live_reporting_scheduled == True,
                        MLSMatch.thread_creation_scheduled == True
                    )
                ).all()
                
                reset_count = 0
                for match in matches:
                    match.live_reporting_scheduled = False
                    match.thread_creation_scheduled = False
                    match.thread_creation_time = None
                    reset_count += 1
                
                session.commit()
                results['details'].append(f"Reset scheduling flags for {reset_count} matches")
                
        except Exception as e:
            results['details'].append(f"Database cleanup failed: {str(e)}")
        
        # Step 4: Wait and verify
        import time
        time.sleep(3)  # Give containers time to restart
        
        logger.warning(f"Nuclear reset completed: {results}")
        
        return jsonify({
            'success': True,
            'message': f"Nuclear reset completed. Restarted {results['containers_restarted']} containers, cleared Redis",
            'results': results
        })
        
    except Exception as e:
        logger.error(f"Nuclear reset failed: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@monitoring_bp.route('/db', endpoint='db_monitoring')
@login_required
@role_required(['Global Admin'])
def db_monitoring():
    """
    Render the database monitoring page.
    """
    return render_template('db_monitoring.html', title='DB Monitoring')


@monitoring_bp.route('/db/connections', endpoint='check_connections')
@role_required(['Global Admin'])
def check_connections():
    """
    Check current database connections.
    
    Returns:
        JSON response with details of active connections, including raw timestamps.
    """
    try:
        with managed_session() as session:
            result = session.execute(text("""
                SELECT 
                    pid,
                    usename,
                    application_name,
                    client_addr,
                    backend_start,
                    query_start,
                    xact_start,
                    state,
                    COALESCE(EXTRACT(EPOCH FROM (NOW() - backend_start)), 0) as age,
                    CASE WHEN state = 'idle in transaction' 
                         THEN COALESCE(EXTRACT(EPOCH FROM (NOW() - xact_start)), 0)
                         ELSE 0 
                    END as transaction_age,
                    query
                FROM pg_stat_activity 
                WHERE pid != pg_backend_pid()
                ORDER BY age DESC
            """))
            connections = [dict(row._mapping) for row in result]
            # Flag long-running transactions (threshold: 300 seconds)
            for conn in connections:
                if conn.get('transaction_age', 0) > 300:
                    logger.warning(
                        f"Long-running transaction detected: PID {conn.get('pid')}, "
                        f"transaction_age {conn.get('transaction_age')}s, "
                        f"query_start {conn.get('query_start')}, xact_start {conn.get('xact_start')}, "
                        f"query: {conn.get('query')[:200]}"
                    )
        return jsonify({'success': True, 'connections': connections})
    except Exception as e:
        logger.error(f"Error checking connections: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@monitoring_bp.route('/db/cleanup', endpoint='cleanup_connections', methods=['POST'])
@role_required(['Global Admin'])
def cleanup_connections():
    """
    Terminate long-running or idle database connections.
    
    Returns:
        JSON response indicating the number of terminated connections.
    """
    try:
        db_manager.check_for_leaked_connections()
        with managed_session() as session:
            result = session.execute(text("""
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE pid != pg_backend_pid()
                  AND state != 'idle'
                  AND (
                    (state = 'active' AND query_start < NOW() - INTERVAL '5 minutes')
                    OR (state = 'idle in transaction' AND xact_start < NOW() - INTERVAL '10 minutes')
                    OR (backend_start < NOW() - INTERVAL '1 hour')
                  )
            """))
            terminated = result.rowcount
        logger.info(f"Terminated {terminated} long-running/idle connections during cleanup.")
        return jsonify({'success': True, 'message': f'Cleaned up {terminated} connections'})
    except Exception as e:
        logger.error(f"Error cleaning up connections: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@monitoring_bp.route('/db/stats', endpoint='connection_stats')
@role_required(['Global Admin'])
def connection_stats():
    """
    Retrieve database connection statistics and pool metrics.
    
    Returns:
        JSON response with detailed connection statistics and pool usage.
    """
    try:
        pool_stats = db_manager.get_pool_stats()
        engine = db.get_engine()
        with managed_session() as session:
            result = session.execute(text("""
                SELECT 
                    COALESCE(count(*), 0) as total_connections,
                    COALESCE(count(*) filter (where state = 'active'), 0) as active_connections,
                    COALESCE(count(*) filter (where state = 'idle'), 0) as idle_connections,
                    COALESCE(count(*) filter (where state = 'idle in transaction'), 0) as idle_in_transaction,
                    COALESCE(EXTRACT(epoch FROM (now() - min(backend_start)))::integer, 0) as oldest_connection_age
                FROM pg_stat_activity 
                WHERE pid != pg_backend_pid()
            """))
            basic_stats = dict(result.mappings().first())
        return jsonify({
            'success': True,
            'stats': {
                'total_connections': basic_stats['total_connections'],
                'active_connections': basic_stats['active_connections'],
                'idle_connections': basic_stats['idle_connections'],
                'idle_transactions': basic_stats['idle_in_transaction'],
                'oldest_connection_age': basic_stats['oldest_connection_age'],
                'current_pool_size': engine.pool.size(),
                'max_pool_size': engine.pool.size() + engine.pool._max_overflow,
                'checkins': pool_stats.get('checkins', 0),
                'checkouts': pool_stats.get('checkouts', 0),
                'leaked_connections': pool_stats.get('leaked_connections', 0)
            }
        })
    except Exception as e:
        logger.error(f"Error getting connection stats: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@monitoring_bp.route('/db/terminate', endpoint='terminate_connection', methods=['POST'])
@role_required(['Global Admin'])
def terminate_connection():
    """
    Terminate a specific database connection by PID.
    
    Expects JSON payload with 'pid'.
    
    Returns:
        JSON response indicating whether the connection was terminated.
    """
    try:
        data = request.get_json()
        pid = data.get('pid')
        if not pid:
            return jsonify({'success': False, 'error': 'Missing pid'}), 400
        with managed_session() as session:
            session.execute(text("SELECT pg_terminate_backend(:pid)"), {"pid": pid})
        logger.info(f"Connection {pid} terminated successfully.")
        return jsonify({'success': True, 'message': f'Connection {pid} terminated'})
    except Exception as e:
        logger.error(f"Error terminating connection {pid}: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@monitoring_bp.route('/db/monitoring_data', endpoint='get_db_monitoring_data')
@login_required
@role_required(['Global Admin'])
def get_db_monitoring_data():
    """
    Retrieve historical database monitoring data snapshots.
    
    Query parameter:
        hours (int): Number of hours to look back (default 24).
    
    Returns:
        JSON response with a list of monitoring data snapshots.
    """
    try:
        hours = int(request.args.get('hours', 24))
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=hours)
        snapshots = DBMonitoringSnapshot.query.filter(
            DBMonitoringSnapshot.timestamp.between(start_time, end_time)
        ).order_by(DBMonitoringSnapshot.timestamp.asc()).all()
        data = []
        for snapshot in snapshots:
            data.append({
                'timestamp': snapshot.timestamp.isoformat(),
                'pool_stats': snapshot.pool_stats,
                'active_connections': snapshot.active_connections,
                'long_running_transactions': snapshot.long_running_transactions,
                'recent_events': snapshot.recent_events,
                'session_monitor': snapshot.session_monitor,
            })
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        logger.error(f"Error fetching monitoring data: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@monitoring_bp.route('/debug/logs', endpoint='get_debug_logs')
@login_required
@role_required('Global Admin')
def get_debug_logs():
    """
    Retrieve debug logs from the root logger's handlers that support buffering.
    
    Returns:
        JSON response with a list of log entries.
    """
    try:
        logs = []
        logger_root = logging.getLogger()
        for handler in logger_root.handlers:
            if hasattr(handler, 'buffer'):
                for record in handler.buffer:
                    logs.append({
                        'timestamp': datetime.fromtimestamp(record.created).isoformat(),
                        'level': record.levelname,
                        'message': record.getMessage(),
                        'logger': record.name
                    })
        return jsonify({'success': True, 'logs': logs})
    except Exception as e:
        current_app.logger.error(f"Error getting debug logs: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@monitoring_bp.route('/inspect-task/<task_id>', endpoint='inspect_task')
@login_required
@role_required('Global Admin')
def inspect_task(task_id):
    """
    Get detailed information about a specific task.
    
    Parameters:
        task_id: The ID of the task to inspect.
    
    Returns:
        JSON response with task details.
    """
    try:
        # Get task result object
        task = AsyncResult(task_id, app=celery)
        
        # Check basic task status
        result = {
            'id': task_id,
            'state': task.state,
            'ready': task.ready(),
            'successful': task.successful() if task.ready() else None,
            'result': str(task.result) if task.ready() else None,
            'traceback': str(task.traceback) if task.failed() else None
        }
        
        # Try to get additional info from Redis or worker
        redis_client = get_safe_redis()
        
        # Check if task is in any Redis key
        keys = redis_client.keys('*')
        related_keys = []
        
        for key in keys:
            key_str = key.decode('utf-8') if isinstance(key, bytes) else str(key)
            value = redis_client.get(key)
            if value:
                value_str = value.decode('utf-8') if isinstance(value, bytes) else str(value)
                if task_id in value_str:
                    related_keys.append({
                        'key': key_str,
                        'value': value_str,
                        'ttl': redis_client.ttl(key)
                    })
        
        result['related_redis_keys'] = related_keys
        
        # Try to get task info from workers
        i = celery.control.inspect(timeout=1.0)
        
        # Check if task is active, scheduled, or reserved on any worker
        active = i.active() or {}
        scheduled = i.scheduled() or {}
        reserved = i.reserved() or {}
        
        result['active_on'] = []
        result['scheduled_on'] = []
        result['reserved_on'] = []
        
        for worker, tasks in active.items():
            for t in tasks:
                if t.get('id') == task_id:
                    result['active_on'].append({'worker': worker, 'task': t})
                    
        for worker, tasks in scheduled.items():
            for t in tasks:
                if t.get('id') == task_id:
                    result['scheduled_on'].append({'worker': worker, 'task': t})
                    
        for worker, tasks in reserved.items():
            for t in tasks:
                if t.get('id') == task_id:
                    result['reserved_on'].append({'worker': worker, 'task': t})
        
        return jsonify({'success': True, 'task': result})
    except Exception as e:
        logger.error(f"Error inspecting task {task_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@monitoring_bp.route('/cleanup-orphaned-tasks', endpoint='cleanup_orphaned_tasks', methods=['POST'])
@login_required
@role_required('Global Admin')
def cleanup_orphaned_tasks():
    """
    Cleanup orphaned tasks that might be stuck in Redis or in the worker queues.
    This helps when there's a discrepancy between what's displayed and what's actually scheduled.
    
    Returns:
        JSON response with cleanup status and details.
    """
    try:
        # 1. Check for Redis orphaned scheduler keys
        redis_client = get_safe_redis()
        scheduler_keys = redis_client.keys('match_scheduler:*')
        cleaned_keys = []
        
        for key in scheduler_keys:
            try:
                # Check if the key is valid
                key_str = key.decode('utf-8') if isinstance(key, bytes) else str(key)
                parts = key_str.split(':')
                
                if len(parts) != 3:
                    # Malformed key - delete it
                    redis_client.delete(key)
                    cleaned_keys.append(key_str)
                    continue
                
                # Check if the task exists
                value = redis_client.get(key)
                if not value:
                    # Empty value - delete the key
                    redis_client.delete(key)
                    cleaned_keys.append(key_str)
                    continue
                
                # Check if task ID is valid
                task_id = value.decode('utf-8') if isinstance(value, bytes) else str(value)
                if len(task_id) != 36:  # UUID is 36 characters
                    # Invalid task ID - delete the key
                    redis_client.delete(key)
                    cleaned_keys.append(key_str)
                    continue
                
                # Check if the task exists in Celery
                task = AsyncResult(task_id, app=celery)
                if task.state in ('SUCCESS', 'FAILURE', 'REVOKED'):
                    # Task is complete but key still exists - delete the key
                    redis_client.delete(key)
                    cleaned_keys.append(key_str)
            except Exception as e:
                logger.warning(f"Error cleaning up key {key}: {e}")
        
        # 2. Purge any scheduled tasks that might be stuck
        i = celery.control.inspect(timeout=2.0)
        scheduler_workers = []
        
        try:
            stats = i.stats() or {}
            for worker_name in stats.keys():
                if 'schedule' in worker_name.lower() or 'beat' in worker_name.lower():
                    scheduler_workers.append(worker_name)
        except Exception as e:
            logger.warning(f"Error inspecting workers for scheduler: {e}")
        
        # 3. Check for database inconsistencies
        match_ids = []
        try:
            with managed_session() as session:
                # Try to safely check if the table exists first
                table_exists = session.execute(text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_name = 'mls_match'
                    )
                """)).scalar()
                
                if table_exists:
                    # Reset live reporting statuses if needed
                    updated_matches = session.execute(text("""
                        UPDATE mls_match 
                        SET live_reporting_scheduled = false,
                            live_reporting_started = false,
                            live_reporting_status = 'not_started'
                        WHERE live_reporting_status IN ('preparing', 'scheduled')
                        AND date_time < NOW() - INTERVAL '3 hours'
                        RETURNING id
                    """))
                    
                    match_ids = [row[0] for row in updated_matches]
                else:
                    logger.info("Table mls_match does not exist, skipping match updates")
        except Exception as db_error:
            logger.warning(f"Error updating match statuses: {db_error}")
            # Continue execution even if this part fails
            
        return jsonify({
            'success': True,
            'cleaned_redis_keys': len(cleaned_keys),
            'cleaned_keys': cleaned_keys,
            'scheduler_workers': scheduler_workers,
            'reset_matches': len(match_ids),
            'match_ids': match_ids
        })
    except Exception as e:
        logger.error(f"Error cleaning up orphaned tasks: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@monitoring_bp.route('/debug/queries', endpoint='get_debug_queries')
@login_required
@role_required('Global Admin')
def get_debug_queries():
    """
    Retrieve the top 100 slowest queries from pg_stat_statements.
    
    Returns:
        JSON response with query statistics.
    """
    try:
        with managed_session() as session:
            result = session.execute(text("""
                SELECT 
                    query,
                    calls,
                    total_time,
                    min_time,
                    max_time,
                    mean_time,
                    rows
                FROM pg_stat_statements 
                ORDER BY total_time DESC 
                LIMIT 100
            """))
            queries = []
            for row in result:
                queries.append({
                    'query': row.query,
                    'calls': row.calls,
                    'total_time': round(row.total_time, 2),
                    'min_time': round(row.min_time, 2),
                    'max_time': round(row.max_time, 2),
                    'mean_time': round(row.mean_time, 2),
                    'rows': row.rows
                })
        return jsonify({'success': True, 'queries': queries})
    except Exception as e:
        current_app.logger.error(f"Error getting debug queries: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@monitoring_bp.route('/debug/system', endpoint='get_system_stats')
@login_required
@role_required('Global Admin')
def get_system_stats():
    """
    Retrieve system statistics for the current process.
    
    Returns:
        JSON response with memory, CPU, thread, open files, and connection counts.
    """
    try:
        process = psutil.Process()
        stats = {
            'memory': {
                'used': round(process.memory_info().rss / 1024 / 1024, 2),
                'percent': process.memory_percent()
            },
            'cpu': {
                'percent': process.cpu_percent()
            },
            'threads': process.num_threads(),
            'open_files': len(process.open_files()),
            'connections': len(process.connections())
        }
        return jsonify({'success': True, 'stats': stats})
    except Exception as e:
        current_app.logger.error(f"Error getting system stats: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@monitoring_bp.route('/workers', endpoint='get_workers')
@login_required
@role_required('Global Admin')
def get_workers():
    """
    Retrieve information about all Celery workers.
    
    Returns:
        JSON response with details about active Celery workers.
    """
    try:
        # Use direct Redis connection like other endpoints
        try:
            from app.utils.redis_manager import UnifiedRedisManager
            redis_manager = UnifiedRedisManager()
            direct_redis = redis_manager.get_decoded_client()
            direct_redis.ping()
            logger.info("Direct Redis connection successful for workers")
            redis_client = direct_redis
        except Exception as e:
            logger.error(f"Direct Redis connection failed for workers: {e}")
            redis_client = get_safe_redis()
        
        # Cache key for workers data (expires after 15 seconds)
        cache_key = "monitoring:workers_data"
        cache_ttl = 15  # seconds
        
        # Try to get from cache first
        cached_data = redis_client.get(cache_key)
        if cached_data:
            try:
                return jsonify(json.loads(cached_data))
            except (json.JSONDecodeError, TypeError):
                # If cache is corrupted, ignore and proceed with fresh data
                pass
                
        # Set timeout for Celery inspection to avoid slow responses
        # Default timeout is high which can cause the 6+ second delays
        timeout = 1.0  # 1 second timeout
        
        # Create inspector with reduced timeout
        i = celery.control.inspect(timeout=timeout)
        
        # Get all data with a single broadcast call instead of multiple calls
        stats = i.stats() or {}
        active = i.active() or {}
        scheduled = i.scheduled() or {}
        reserved = i.reserved() or {}
        revoked = i.revoked() or {}
        registered = {}
        
        # For registered tasks, only count them (don't get full list) to reduce payload size
        for worker_name, worker_stats in stats.items():
            try:
                registered_count = redis_client.get(f"monitoring:registered_tasks:{worker_name}")
                if registered_count:
                    registered[worker_name] = int(registered_count)
                else:
                    # This is expensive, so cache it longer (1 hour)
                    worker_registered = i.registered(destination=[worker_name]) or {}
                    count = len(worker_registered.get(worker_name, []))
                    registered[worker_name] = count
                    redis_client.setex(f"monitoring:registered_tasks:{worker_name}", 3600, str(count))
            except Exception:
                registered[worker_name] = 0
        
        # Collect scheduled task details for display
        scheduled_task_details = []
        for worker_name, tasks in scheduled.items():
            for task in tasks:
                try:
                    # Extract task info - try multiple ways to get task name
                    task_name = None
                    task_id = task.get('id', '')
                    
                    # Try different ways to extract task name
                    if 'name' in task and task['name']:
                        task_name = task['name']
                    elif 'request' in task and task['request'].get('task'):
                        task_name = task['request']['task']
                    elif 'request' in task and task['request'].get('name'):
                        task_name = task['request']['name']
                    else:
                        # Try to extract from the task structure
                        for key in ['task', 'func', 'function']:
                            if key in task and task[key]:
                                task_name = task[key]
                                break
                    
                    # Default if still not found
                    if not task_name:
                        task_name = 'Unknown Task'
                        logger.warning(f"Could not determine task name for task: {task}")
                    
                    args = task.get('args', [])
                    kwargs = task.get('kwargs', {})
                    eta = task.get('eta')
                    
                    # Extract request details for better task info
                    request = task.get('request', {})
                    delivery_info = request.get('delivery_info', {})
                    queue = delivery_info.get('routing_key', 'Unknown')
                    
                    # Also try to get queue from other locations
                    if queue == 'Unknown':
                        if 'delivery_info' in task and 'routing_key' in task['delivery_info']:
                            queue = task['delivery_info']['routing_key']
                        elif 'queue' in task:
                            queue = task['queue']
                    
                    # Get full task details
                    full_task = {
                        'worker': worker_name,
                        'name': task_name,
                        'args': args,
                        'kwargs': kwargs,
                        'eta': eta,
                        'id': task_id,
                        'queue': queue
                    }
                    
                    # Don't include full details as they cause JS issues
                    # Instead include a simplified version
                    try:
                        simplified_details = {
                            'id': task_id,
                            'name': task_name,
                            'worker': worker_name,
                            'args': str(args),
                            'kwargs': str(kwargs),
                            'eta': str(eta),
                            'queue': queue
                        }
                        full_task['full_details'] = json.dumps(simplified_details)
                    except Exception:
                        full_task['full_details'] = "{}"
                    
                    # Add match ID if we can find it in args or kwargs
                    match_id = None
                    if args and len(args) > 0:
                        # First arg is often a match ID
                        match_id = args[0]
                    elif kwargs and 'match_id' in kwargs:
                        match_id = kwargs['match_id']
                    
                    if match_id:
                        full_task['match_id'] = match_id
                        
                        # Try to get match details from database for more context
                        try:
                            with managed_session() as session:
                                match = get_match(session, match_id)
                                if match:
                                    full_task['match_details'] = {
                                        'opponent': match.opponent if hasattr(match, 'opponent') else 'Unknown',
                                        'date_time': match.date_time.isoformat() if hasattr(match, 'date_time') else None,
                                        'location': match.location if hasattr(match, 'location') else 'Unknown'
                                    }
                        except Exception as e:
                            logger.warning(f"Error fetching match details for task: {e}")
                    
                    scheduled_task_details.append(full_task)
                except Exception as e:
                    logger.warning(f"Error processing scheduled task: {e}")
        
        # Combine all information
        workers_info = {}
        for worker_name in stats.keys():
            # Only include active workers to reduce payload
            worker_scheduled = scheduled.get(worker_name, [])
            workers_info[worker_name] = {
                'active_tasks': active.get(worker_name, []),
                'registered_tasks': registered.get(worker_name, 0),
                'scheduled_tasks': len(worker_scheduled),
                'reserved_tasks': len(reserved.get(worker_name, [])),
                'status': 'online'
            }
        
        # Get worker queues (also minimized)
        queues = {}
        scheduled_task_count = 0
        for worker, worker_stats in stats.items():
            if 'pool' in worker_stats:
                queues[worker] = {
                    'pool_size': worker_stats.get('pool', {}).get('max-concurrency', 0)
                }
            # Count total scheduled tasks across all workers
            scheduled_task_count += len(scheduled.get(worker, []))
        
        result = {
            'success': True, 
            'workers': workers_info,
            'queues': queues,
            'total_workers': len(workers_info),
            'active_workers': len(stats),
            'total_scheduled_tasks': scheduled_task_count,
            'scheduled_tasks': scheduled_task_details
        }
        
        # Cache the result to improve performance
        try:
            redis_client.setex(cache_key, cache_ttl, json.dumps(result))
        except (TypeError, json.JSONEncodeError):
            pass
            
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error getting worker information: {e}", exc_info=True)
        return jsonify({
            'success': True,  # Return success even on error to avoid UI disruption
            'workers': {},
            'queues': {},
            'total_workers': 0,
            'active_workers': 0,
            'total_scheduled_tasks': 0,
            'error': "Timed out waiting for worker response"
        })


@monitoring_bp.route('/db/connections/<int:pid>/stack', endpoint='get_stack_trace')
@login_required
@role_required('Global Admin')
def get_stack_trace(pid):
    """
    Retrieve the full Python stack trace captured at the transaction start for a given DB process ID.
    
    Returns a JSON response with the transaction details including the captured stack trace.
    """
    try:
        logger.debug(f"Looking up transaction details for PID: {pid}")
        # Try to get the captured details (which include the full Python stack trace)
        details = db_manager.get_transaction_details(pid) if hasattr(db_manager, 'get_transaction_details') else None

        if not details:
            # Fallback: query PostgreSQL for runtime details (this won't include the Python stack)
            with managed_session() as session:
                result = session.execute(text("""
                    SELECT pid, query, state, xact_start, query_start
                    FROM pg_stat_activity 
                    WHERE pid = :pid
                """), {"pid": pid}).first()
            if result:
                details = {
                    'transaction_name': 'Active Query',
                    'query': result.query,
                    'state': result.state,
                    'timing': {
                        'transaction_start': result.xact_start.isoformat() if result.xact_start else None,
                        'query_start': result.query_start.isoformat() if result.query_start else None
                    },
                    'stack_trace': "No captured Python stack trace available. Consider instrumenting your transaction begin."
                }
            else:
                details = {'stack_trace': "No transaction details found."}
        return jsonify({'success': True, 'pid': pid, 'details': details})
    except Exception as e:
        logger.error(f"Error getting transaction details for pid {pid}: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@monitoring_bp.route('/sessions')
@login_required
@role_required(['Global Admin'])
def session_monitoring():
    """
    Session monitoring dashboard showing active sessions and potential leaks.
    """
    monitor = get_session_monitor()
    stats = monitor.get_stats()
    active_sessions = monitor.get_active_sessions()
    long_running_sessions = monitor.get_long_running_sessions()
    
    return render_template('monitoring/sessions.html',
                         stats=stats,
                         active_sessions=active_sessions,
                         long_running_sessions=long_running_sessions,
                         title='Session Monitoring')


@monitoring_bp.route('/sessions/api')
@login_required
@role_required(['Global Admin'])
def session_monitoring_api():
    """
    API endpoint for session monitoring data (for AJAX updates).
    """
    monitor = get_session_monitor()
    stats = monitor.get_stats()
    active_sessions = [
        {
            'session_id': session.session_id[:8] + '...',  # Truncate for display
            'route': session.route,
            'user_id': session.user_id,
            'status': session.status,
            'duration': time.time() - session.created_at,
            'created_at': datetime.fromtimestamp(session.created_at).isoformat()
        }
        for session in monitor.get_active_sessions()
    ]
    
    long_running_sessions = [
        {
            'session_id': session.session_id[:8] + '...',
            'route': session.route,
            'user_id': session.user_id,
            'status': session.status,
            'duration': time.time() - session.created_at,
            'created_at': datetime.fromtimestamp(session.created_at).isoformat()
        }
        for session in monitor.get_long_running_sessions()
    ]
    
    return jsonify({
        'stats': stats,
        'active_sessions': active_sessions,
        'long_running_sessions': long_running_sessions,
        'timestamp': datetime.utcnow().isoformat()
    })


@monitoring_bp.route('/sessions/cleanup', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def cleanup_stale_sessions():
    """
    Manually trigger cleanup of stale session records.
    """
    try:
        monitor = get_session_monitor()
        monitor.cleanup_stale_sessions()
        monitor.log_session_report()
        return jsonify({'success': True, 'message': 'Stale sessions cleaned up'})
    except Exception as e:
        logger.error(f"Error during manual session cleanup: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500