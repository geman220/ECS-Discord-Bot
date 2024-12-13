# app/monitoring.py

from flask import Blueprint, render_template, jsonify, current_app, request, g
from flask_login import login_required
from app.decorators import role_required
from app.utils.redis_manager import RedisManager
from app.db_management import db_manager
from celery.result import AsyncResult
from app.core import celery, db
from app.models import MLSMatch
from datetime import datetime, timedelta
from app.database.db_models import DBMonitoringSnapshot
from app.tasks.tasks_live_reporting import (
    start_live_reporting,
    create_match_thread_task,
    force_create_mls_thread_task
)
from sqlalchemy import text
import psutil
import logging

logger = logging.getLogger(__name__)

# Define the blueprint BEFORE using it in decorators
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
            thread_key = f"match_scheduler:{match_id}:thread"
            reporting_key = f"match_scheduler:{match_id}:reporting"
            
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
            session = g.db_session
            matches = session.query(MLSMatch).filter(
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

task_monitor = TaskMonitor()

@monitoring_bp.route('/', endpoint='monitor_dashboard')
@login_required
@role_required('Global Admin')
def monitor_dashboard():
    return render_template('monitoring.html')

@monitoring_bp.route('/tasks/all', endpoint='get_all_tasks')
@login_required
@role_required('Global Admin')
def get_all_tasks():
    try:
        result = task_monitor.monitor_all_matches()
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error getting tasks: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@monitoring_bp.route('/tasks/match/<match_id>', endpoint='get_match_tasks')
@login_required
def get_match_tasks(match_id):
    try:
        result = task_monitor.verify_scheduled_tasks(match_id)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error getting match tasks: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@monitoring_bp.route('/redis/keys', endpoint='get_redis_keys')
@login_required
@role_required('Global Admin')
def get_redis_keys():
    try:
        redis_client = RedisManager().client
        scheduler_keys = redis_client.keys('match_scheduler:*')
        
        result = {}
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

@monitoring_bp.route('/redis/test', endpoint='test_redis')
@login_required
@role_required('Global Admin')
def test_redis():
    try:
        redis_client = RedisManager().client
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

@monitoring_bp.route('/tasks/revoke', endpoint='revoke_task', methods=['POST'])
@login_required
@role_required('Global Admin')
def revoke_task():
    session = g.db_session
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
        
        celery.control.revoke(task_id, terminate=True)
        
        redis_client = RedisManager().client
        redis_client.delete(key)
        
        if 'thread' in key:
            match_id = key.split(':')[1]
            match = session.query(MLSMatch).get(match_id)
            if match:
                match.thread_creation_time = None
        elif 'reporting' in key:
            match_id = key.split(':')[1]
            match = session.query(MLSMatch).get(match_id)
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

@monitoring_bp.route('/tasks/revoke-all', endpoint='revoke_all_tasks', methods=['POST'])
@login_required
@role_required('Global Admin')
def revoke_all_tasks():
    session = g.db_session
    try:
        redis_client = RedisManager().client
        keys = redis_client.keys('match_scheduler:*')
        
        revoked_count = 0
        failed_tasks = []
        
        logger.info(f"Attempting to revoke {len(keys)} tasks")
        
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
        
        matches = session.query(MLSMatch).all()
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

@monitoring_bp.route('/tasks/reschedule', endpoint='reschedule_task', methods=['POST'])
@login_required
@role_required('Global Admin')
def reschedule_task():
    session = g.db_session
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
        
        match_id = key.split(':')[1]
        match = session.query(MLSMatch).get(match_id)
        if not match:
            return jsonify({
                'success': False,
                'error': 'Match not found'
            }), 404
            
        celery.control.revoke(task_id, terminate=True)
        redis_client = RedisManager().client
        redis_client.delete(key)
        
        if 'thread' in key:
            thread_time = match.date_time - timedelta(hours=24)
            new_task = force_create_mls_thread_task.apply_async(
                args=[match_id],
                eta=thread_time
            )
            match.thread_creation_time = thread_time
            redis_client.setex(key, 172800, new_task.id)
        else:
            reporting_time = match.date_time - timedelta(minutes=5)
            new_task = start_live_reporting.apply_async(
                args=[str(match_id)],
                eta=reporting_time
            )
            match.live_reporting_scheduled = True
            redis_client.setex(key, 172800, new_task.id)
        
        return jsonify({
            'success': True,
            'message': f'Task rescheduled successfully. New task ID: {new_task.id}',
            'new_task_id': new_task.id
        })
        
    except Exception as e:
        logger.error(f"Error rescheduling task: {str(e)}", exc_info=True)
        raise

@monitoring_bp.route('/db', endpoint='db_monitoring')
@login_required
@role_required(['Global Admin'])
def db_monitoring():
    return render_template('db_monitoring.html')

@monitoring_bp.route('/db/connections', endpoint='check_connections')
@role_required(['Global Admin'])
def check_connections():
    try:
        session = g.db_session
        result = session.execute(text("""
            SELECT 
                pid,
                usename,
                application_name,
                client_addr,
                backend_start,
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

        connections = []
        # transaction_metadata usage commented out or removed if db_manager no longer has transaction_metadata
        # For now, assume we no longer rely on db_manager.transaction_metadata
        for row in result:
            connections.append(dict(row._mapping))

        return jsonify({'success': True, 'connections': connections})
    except Exception as e:
        logger.error(f"Error checking connections: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500

@monitoring_bp.route('/db/cleanup', endpoint='cleanup_connections', methods=['POST'])
@role_required(['Global Admin'])
def cleanup_connections():
    try:
        # Check for leaked connections
        db_manager.check_for_leaked_connections()
        
        session = g.db_session
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

        return jsonify({
            'success': True,
            'message': f'Cleaned up {terminated} connections'
        })
    except Exception as e:
        logger.error(f"Error cleaning up connections: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@monitoring_bp.route('/db/stats', endpoint='connection_stats')
@role_required(['Global Admin'])
def connection_stats():
    try:
        pool_stats = db_manager.get_pool_stats()  # Allowed
        engine = db.get_engine()

        session = g.db_session
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
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@monitoring_bp.route('/db/terminate', endpoint='terminate_connection', methods=['POST'])
@role_required(['Global Admin'])
def terminate_connection():
    try:
        data = request.get_json()
        pid = data.get('pid')
        
        if not pid:
            return jsonify({
                'success': False,
                'error': 'Missing pid'
            }), 400
            
        session = g.db_session
        session.execute(
            text("SELECT pg_terminate_backend(:pid)"),
            {"pid": pid}
        )
        
        return jsonify({
            'success': True,
            'message': f'Connection {pid} terminated'
        })
    except Exception as e:
        logger.error(f"Error terminating connection: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@monitoring_bp.route('/db/monitoring_data', endpoint='get_db_monitoring_data')
@login_required
@role_required(['Global Admin'])
def get_db_monitoring_data():
    try:
        hours = int(request.args.get('hours', 24))
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=hours)

        # DBMonitoringSnapshot is a Flask-SQLAlchemy model, so just query using db.session
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

        return jsonify({
            'success': True,
            'data': data
        })
    except Exception as e:
        logger.error(f"Error fetching monitoring data: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500

@monitoring_bp.route('/debug/logs', endpoint='get_debug_logs')
@login_required
@role_required('Global Admin')
def get_debug_logs():
    try:
        # This code attempts to read from a MemoryHandler, ensure you have such a handler if needed.
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
        
        return jsonify({
            'success': True,
            'logs': logs
        })
    except Exception as e:
        current_app.logger.error(f"Error getting debug logs: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@monitoring_bp.route('/debug/queries', endpoint='get_debug_queries')
@login_required
@role_required('Global Admin')
def get_debug_queries():
    try:
        session = g.db_session
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
            
        return jsonify({
            'success': True,
            'queries': queries
        })
    except Exception as e:
        current_app.logger.error(f"Error getting debug queries: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@monitoring_bp.route('/debug/system', endpoint='get_system_stats')
@login_required
@role_required('Global Admin')
def get_system_stats():
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
        
        return jsonify({
            'success': True,
            'stats': stats
        })
    except Exception as e:
        current_app.logger.error(f"Error getting system stats: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@monitoring_bp.route('/db/connections/<int:pid>/stack', endpoint='get_stack_trace')
@login_required
@role_required('Global Admin')
def get_stack_trace(pid):
    try:
        logger.debug(f"Looking up transaction details for PID: {pid}")
        logger.debug(f"Current metadata keys: {list(db_manager.transaction_metadata.keys()) if hasattr(db_manager, 'transaction_metadata') else 'No transaction_metadata'}")

        # If db_manager.get_transaction_details(pid) depends on old transaction metadata logic, you may remove it.
        details = db_manager.get_transaction_details(pid) if hasattr(db_manager, 'get_transaction_details') else None

        if not details:
            session = g.db_session
            result = session.execute(text("""
                SELECT pid, query, state, xact_start, query_start
                FROM pg_stat_activity 
                WHERE pid = :pid
            """), {"pid": pid}).first()
            
            if result:
                return jsonify({
                    'success': True,
                    'pid': pid,
                    'details': {
                        'transaction_name': 'Active Query',
                        'query': result.query,
                        'state': result.state,
                        'timing': {
                            'transaction_start': result.xact_start.isoformat() if result.xact_start else None,
                            'query_start': result.query_start.isoformat() if result.query_start else None
                        }
                    }
                })

        return jsonify({
            'success': True,
            'pid': pid,
            'details': details
        })
        
    except Exception as e:
        logger.error(f"Error getting transaction details for pid {pid}: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
