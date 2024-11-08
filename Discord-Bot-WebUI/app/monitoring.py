# app/monitoring.py

from flask import Blueprint, render_template, jsonify, current_app, request
from flask_login import login_required
from app.decorators import role_required, db_operation
from app.utils.redis_manager import RedisManager
from celery.result import AsyncResult
from app.extensions import celery, db
from app.models import MLSMatch
from datetime import datetime, timedelta
from app.tasks.tasks_live_reporting import (
    start_live_reporting,
    create_match_thread_task,
    force_create_mls_thread_task
)
from sqlalchemy import text 
import logging

logger = logging.getLogger(__name__)

# Initialize blueprint
monitoring_bp = Blueprint('monitoring', __name__, url_prefix='/monitoring')

class TaskMonitor:
    """Monitor Celery tasks and their status."""
    
    def __init__(self):
        self.redis = RedisManager().client
    
    def get_task_status(self, task_id: str):
        """Get status of a specific task."""
        try:
            result = AsyncResult(task_id, app=celery)
            return {
                'id': task_id,
                'status': result.status,
                'info': str(result.info) if result.info else None,
                'ready': result.ready(),
                'successful': result.successful() if result.ready() else None
            }
        except Exception as e:
            logger.error(f"Error getting task status: {str(e)}")
            return {
                'id': task_id,
                'status': 'ERROR',
                'error': str(e)
            }
    
    def verify_scheduled_tasks(self, match_id: str):
        """Get status of scheduled tasks for a match."""
        try:
            # Get Redis keys for match
            thread_key = f"match_scheduler:{match_id}:thread"
            reporting_key = f"match_scheduler:{match_id}:reporting"
            
            # Get task IDs
            thread_task_id = self.redis.get(thread_key)
            reporting_task_id = self.redis.get(reporting_key)
            
            return {
                'success': True,
                'thread_task': {
                    'id': thread_task_id.decode('utf-8') if thread_task_id else None,
                    'status': self.get_task_status(thread_task_id.decode('utf-8')) if thread_task_id else None
                },
                'reporting_task': {
                    'id': reporting_task_id.decode('utf-8') if reporting_task_id else None,
                    'status': self.get_task_status(reporting_task_id.decode('utf-8')) if reporting_task_id else None
                }
            }
        except Exception as e:
            logger.error(f"Error verifying tasks: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def monitor_all_matches(self):
        """Monitor all matches and their tasks."""
        try:
            matches = MLSMatch.query.filter(
                MLSMatch.live_reporting_scheduled == True
            ).all()
            
            results = {}
            for match in matches:
                results[str(match.id)] = self.verify_scheduled_tasks(str(match.id))
            
            return {
                'success': True,
                'matches': results
            }
        except Exception as e:
            logger.error(f"Error monitoring matches: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }

# Initialize task monitor
task_monitor = TaskMonitor()

@monitoring_bp.route('/')
@login_required
@role_required('Global Admin')
def monitor_dashboard():
    """Render the monitoring dashboard."""
    return render_template('monitoring.html')

@monitoring_bp.route('/tasks/all')
@login_required
@role_required('Global Admin')
def get_all_tasks():
    """Get status of all tasks."""
    try:
        result = task_monitor.monitor_all_matches()
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error getting tasks: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@monitoring_bp.route('/tasks/match/<match_id>')
@login_required
def get_match_tasks(match_id):
    """Get status of specific match tasks."""
    try:
        result = task_monitor.verify_scheduled_tasks(match_id)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error getting match tasks: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@monitoring_bp.route('/redis/keys')
@login_required
@role_required('Global Admin')
def get_redis_keys():
    """Get all scheduler-related Redis keys."""
    try:
        redis_client = RedisManager().client
        scheduler_keys = redis_client.keys('match_scheduler:*')
        
        result = {}
        for key in scheduler_keys:
            try:
                # Handle key string
                key_str = key.decode('utf-8') if isinstance(key, bytes) else str(key)
                
                # Get value
                value = redis_client.get(key)
                if value is not None:
                    try:
                        value = value.decode('utf-8') if isinstance(value, bytes) else str(value)
                    except (UnicodeDecodeError, AttributeError):
                        value = str(value)
                
                # Get TTL
                ttl = redis_client.ttl(key)
                
                # Check if value is a task ID
                task_status = None
                if value and len(value) == 36:  # UUID length
                    try:
                        task = AsyncResult(value, app=celery)
                        task_status = {
                            'id': value,
                            'status': task.status,
                            'ready': task.ready(),
                            'successful': task.successful() if task.ready() else None
                        }
                    except Exception as task_error:
                        logger.warning(f"Error getting task status for {value}: {str(task_error)}")
                
                result[key_str] = {
                    'value': value,
                    'ttl': ttl,
                    'task_status': task_status
                }
                
            except Exception as key_error:
                logger.error(f"Error processing key {key}: {str(key_error)}")
                result[str(key)] = {
                    'error': str(key_error)
                }
        
        return jsonify({
            'success': True,
            'keys': result,
            'total': len(result)
        })
        
    except Exception as e:
        logger.error(f"Error getting Redis keys: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@monitoring_bp.route('/redis/test')
@login_required
@role_required('Global Admin')
def test_redis():
    """Test Redis connection and list scheduler-related keys."""
    try:
        redis_client = RedisManager().client
        
        # Test connection
        ping_result = redis_client.ping()
        
        # Get all scheduler-related keys
        scheduler_keys = redis_client.keys('match_scheduler:*')
        keys_info = {}
        
        for key in scheduler_keys:
            try:
                # Handle key string
                key_str = key.decode('utf-8') if isinstance(key, bytes) else str(key)
                
                # Get raw value
                value = redis_client.get(key)
                if value is not None:
                    try:
                        value = value.decode('utf-8') if isinstance(value, bytes) else str(value)
                    except (UnicodeDecodeError, AttributeError):
                        value = str(value)
                
                # Get TTL
                ttl = redis_client.ttl(key)
                
                # Get task status if it looks like a task ID
                task_status = None
                if value and len(value) == 36:  # UUID length
                    try:
                        task = AsyncResult(value, app=celery)
                        task_status = {
                            'id': value,
                            'status': task.status,
                            'ready': task.ready(),
                            'successful': task.successful() if task.ready() else None
                        }
                    except Exception as task_error:
                        logger.warning(f"Error getting task status for {value}: {str(task_error)}")
                
                keys_info[key_str] = {
                    'value': value,
                    'ttl': ttl,
                    'task_status': task_status
                }
                
            except Exception as key_error:
                logger.error(f"Error processing key {key}: {str(key_error)}")
                keys_info[str(key)] = {
                    'error': str(key_error)
                }
        
        # Log the results
        logger.info(f"Redis connection test: {ping_result}")
        logger.info(f"Found {len(scheduler_keys)} scheduler keys")
        
        return jsonify({
            'success': True,
            'ping': ping_result,
            'total_keys': len(scheduler_keys),
            'keys': keys_info
        })
        
    except Exception as e:
        logger.error(f"Redis test failed: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@monitoring_bp.route('/tasks/revoke', methods=['POST'])
@login_required
@role_required('Global Admin')
@db_operation
def revoke_task():
    """Revoke a scheduled task and clean up Redis."""
    try:
        data = request.get_json()
        key = data.get('key')
        task_id = data.get('task_id')
        
        if not key or not task_id:
            return jsonify({
                'success': False,
                'error': 'Missing key or task_id'
            }), 400
            
        logger.info(f"Revoking task {task_id} and cleaning up Redis key {key}")
        
        # Revoke the Celery task
        celery.control.revoke(task_id, terminate=True)
        
        # Remove the Redis key
        redis_client = RedisManager().client
        redis_client.delete(key)
        
        # Update match status if needed - db_operation decorator will handle commit
        if 'thread' in key:
            match_id = key.split(':')[1]
            match = MLSMatch.query.get(match_id)
            if match:
                match.thread_creation_time = None
        elif 'reporting' in key:
            match_id = key.split(':')[1]
            match = MLSMatch.query.get(match_id)
            if match:
                match.live_reporting_scheduled = False
                match.live_reporting_started = False
                match.live_reporting_status = 'not_started'
        
        return jsonify({
            'success': True,
            'message': f'Task {task_id} revoked and Redis key {key} removed'
        })
        
    except Exception as e:
        logger.error(f"Error revoking task: {str(e)}", exc_info=True)
        raise

@monitoring_bp.route('/tasks/revoke-all', methods=['POST'])
@login_required
@role_required('Global Admin')
@db_operation
def revoke_all_tasks():
    """Revoke all scheduled tasks and clean up Redis."""
    try:
        redis_client = RedisManager().client
        keys = redis_client.keys('match_scheduler:*')
        
        revoked_count = 0
        failed_tasks = []
        
        logger.info(f"Attempting to revoke {len(keys)} tasks")
        
        # First handle Redis and Celery tasks
        for key in keys:
            try:
                key_str = key.decode('utf-8') if isinstance(key, bytes) else str(key)
                value = redis_client.get(key)
                
                if value:
                    task_id = value.decode('utf-8') if isinstance(value, bytes) else str(value)
                    logger.info(f"Revoking task {task_id} for key {key_str}")
                    
                    try:
                        celery.control.revoke(task_id, terminate=True)
                        logger.info(f"Successfully revoked task {task_id}")
                    except Exception as revoke_error:
                        logger.error(f"Error revoking task {task_id}: {str(revoke_error)}")
                        failed_tasks.append({
                            'task_id': task_id,
                            'error': str(revoke_error)
                        })
                    
                    redis_client.delete(key)
                    revoked_count += 1
                    
            except Exception as key_error:
                logger.error(f"Error processing key {key}: {str(key_error)}")
                failed_tasks.append({
                    'key': str(key),
                    'error': str(key_error)
                })
        
        # Then handle database updates - db_operation decorator will handle commit
        matches = MLSMatch.query.all()
        for match in matches:
            match.thread_creation_time = None
            match.live_reporting_scheduled = False
            match.live_reporting_started = False
            match.live_reporting_status = 'not_started'
        
        response_data = {
            'success': True,
            'message': f'Revoked {revoked_count} tasks and cleaned up Redis',
            'revoked_count': revoked_count
        }
        
        if failed_tasks:
            response_data['failed_tasks'] = failed_tasks
            response_data['warning'] = 'Some tasks failed to revoke'
            
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"Error revoking all tasks: {str(e)}", exc_info=True)
        raise

@monitoring_bp.route('/tasks/reschedule', methods=['POST'])
@login_required
@role_required('Global Admin')
@db_operation
def reschedule_task():
    """Reschedule a task with a new ETA."""
    try:
        data = request.get_json()
        key = data.get('key')
        task_id = data.get('task_id')
        
        if not key or not task_id:
            return jsonify({
                'success': False,
                'error': 'Missing key or task_id'
            }), 400
            
        logger.info(f"Rescheduling task {task_id} for key {key}")
        
        # Get match ID and type from key
        match_id = key.split(':')[1]
        is_thread = 'thread' in key
        
        # Get match
        match = MLSMatch.query.get(match_id)
        if not match:
            return jsonify({
                'success': False,
                'error': 'Match not found'
            }), 404
            
        # Revoke existing task
        celery.control.revoke(task_id, terminate=True)
        redis_client = RedisManager().client
        redis_client.delete(key)
        
        # Schedule new task
        if is_thread:
            thread_time = match.date_time - timedelta(hours=24)
            new_task = force_create_mls_thread_task.apply_async(
                args=[match_id],
                eta=thread_time
            )
            match.thread_creation_time = thread_time
            redis_client.setex(
                key,
                172800,  # 48 hours
                new_task.id
            )
        else:
            reporting_time = match.date_time - timedelta(minutes=5)
            new_task = start_live_reporting.apply_async(
                args=[str(match_id)],
                eta=reporting_time
            )
            match.live_reporting_scheduled = True
            redis_client.setex(
                key,
                172800,  # 48 hours
                new_task.id
            )
        
        return jsonify({
            'success': True,
            'message': f'Task rescheduled successfully. New task ID: {new_task.id}',
            'new_task_id': new_task.id
        })
        
    except Exception as e:
        logger.error(f"Error rescheduling task: {str(e)}", exc_info=True)
        raise

@monitoring_bp.route('/db')
@login_required
@role_required(['Global Admin'])
def db_monitoring():
    """Render the database monitoring dashboard."""
    return render_template('db_monitoring.html')

@monitoring_bp.route('/db/connections')
@role_required(['Global Admin'])
def check_connections():
    """Get all long-running database connections"""
    try:
        connections = current_app.db_monitor.get_long_running_connections()
        return jsonify({
            'success': True,
            'connections': [
                {
                    'pid': conn['pid'],
                    'duration': round(conn['duration'], 2),
                    'query': conn['query'][:200] + '...' if len(conn['query']) > 200 else conn['query'],
                    'state': conn['state'],
                    'application': conn['application_name']
                }
                for conn in connections
            ]
        })
    except Exception as e:
        logger.error(f"Error checking connections: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@monitoring_bp.route('/db/cleanup', methods=['POST'])
@role_required(['Global Admin'])
def cleanup_connections():
    """Terminate stuck database connections"""
    try:
        terminated = current_app.db_monitor.terminate_stuck_connections()
        return jsonify({
            'success': True,
            'terminated_count': terminated
        })
    except Exception as e:
        logger.error(f"Error cleaning up connections: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@monitoring_bp.route('/db/stats')
@role_required(['Global Admin'])
def connection_stats():
    """Get database connection statistics"""
    try:
        with current_app.db_monitor.monitor_transaction('connection_stats'):
            with db.engine.connect() as conn:
                # Fetch basic stats with NULLIF to handle empty results
                result = conn.execute(text("""
                    SELECT 
                        COALESCE(count(*), 0) as total_connections,
                        COALESCE(count(*) filter (where state = 'active'), 0) as active_connections,
                        COALESCE(count(*) filter (where state = 'idle'), 0) as idle_connections,
                        COALESCE(
                            NULLIF(
                                extract(epoch from now() - min(backend_start))::integer,
                                NULL
                            ),
                            0
                        ) as oldest_connection_age
                    FROM pg_stat_activity 
                    WHERE pid != pg_backend_pid()
                """))
                row = result.first()
                base_stats = {
                    'total_connections': row[0],
                    'active_connections': row[1],
                    'idle_connections': row[2],
                    'oldest_connection_age': row[3]
                }

                # Fetch state-specific stats with proper NULL handling
                result = conn.execute(text("""
                    SELECT 
                        COALESCE(state, 'unknown') as state,
                        count(*) as count,
                        COALESCE(
                            NULLIF(
                                max(extract(epoch from now() - query_start))::integer,
                                NULL
                            ),
                            0
                        ) as longest_query_duration
                    FROM pg_stat_activity 
                    WHERE pid != pg_backend_pid()
                    GROUP BY state
                """))
                
                state_stats = {}
                for row in result:
                    state_stats[row[0]] = {
                        'count': row[1],
                        'longest_duration': row[2]
                    }

                return jsonify({
                    'success': True,
                    'stats': {
                        **base_stats,
                        'states': state_stats,
                        'timestamp': datetime.now().isoformat()
                    }
                })
    except Exception as e:
        logger.error(f"Error getting connection stats: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
