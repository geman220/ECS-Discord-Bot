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
from datetime import datetime, timedelta

from flask import Blueprint, render_template, jsonify, current_app, request
from flask_login import login_required
from celery.result import AsyncResult
from sqlalchemy import text

from app.decorators import role_required
from app.utils.redis_manager import RedisManager
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
        self.redis = RedisManager().client

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
            return {
                'id': task_id,
                'status': result.status,
                'info': str(result.info) if result.info else None,
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

            return {
                'success': True,
                'thread_task': {
                    'id': thread_task_id,
                    'status': self.get_task_status(thread_task_id) if thread_task_id else None
                },
                'reporting_task': {
                    'id': reporting_task_id,
                    'status': self.get_task_status(reporting_task_id) if reporting_task_id else None
                }
            }
        except Exception as e:
            logger.error(f"Error verifying tasks for match {match_id}: {e}", exc_info=True)
            return {'success': False, 'error': str(e)}

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
    Retrieve the scheduled tasks for all matches.
    
    Returns:
        JSON response with scheduled tasks details.
    """
    try:
        result = task_monitor.monitor_all_matches()
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error getting all tasks: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@monitoring_bp.route('/tasks/match/<match_id>', endpoint='get_match_tasks')
@login_required
def get_match_tasks(match_id):
    """
    Retrieve scheduled tasks for a specific match.
    
    Parameters:
        match_id (str): The match identifier.
    
    Returns:
        JSON response with the scheduled tasks for the match.
    """
    try:
        result = task_monitor.verify_scheduled_tasks(match_id)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error getting tasks for match {match_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@monitoring_bp.route('/redis/keys', endpoint='get_redis_keys')
@login_required
@role_required('Global Admin')
def get_redis_keys():
    """
    Retrieve all Redis keys related to match scheduling.
    
    Returns:
        JSON response with key details including value, TTL, and task status.
    """
    try:
        # Use Redis manager with persistent connection
        redis_manager = RedisManager()
        redis_client = redis_manager.client
        scheduler_keys = redis_client.keys('match_scheduler:*')
        result = {}
        for key in scheduler_keys:
            try:
                key_str = key.decode('utf-8') if isinstance(key, bytes) else str(key)
                value = redis_client.get(key)
                stored_value = None
                if value is not None:
                    value_str = value.decode('utf-8') if isinstance(value, bytes) else str(value)
                    try:
                        stored_obj = json.loads(value_str)
                        stored_value = stored_obj.get("task_id", value_str)
                    except Exception:
                        stored_value = value_str
                ttl = redis_client.ttl(key)
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
        return jsonify({'success': True, 'keys': result, 'total': len(result)})
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
    
    Expects JSON payload with 'key' and 'task_id'.
    
    Returns:
        JSON response indicating revocation status.
    """
    try:
        data = request.get_json()
        key = data.get('key')
        task_id = data.get('task_id')
        if not key or not task_id:
            return jsonify({'success': False, 'error': 'Missing key or task_id'}), 400
        logger.info(f"Revoking task {task_id} and cleaning up Redis key {key}")
        celery.control.revoke(task_id, terminate=True)
        redis_client = RedisManager().client
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
    except Exception as e:
        logger.error(f"Error revoking task {task_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@monitoring_bp.route('/tasks/revoke-all', endpoint='revoke_all_tasks', methods=['POST'])
@login_required
@role_required('Global Admin')
def revoke_all_tasks():
    """
    Revoke all scheduled tasks by cleaning up all Redis keys and updating match records.
    
    Returns:
        JSON response with the number of revoked tasks and any failures.
    """
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
                        logger.error(f"Error revoking task {task_id}: {revoke_error}")
                        failed_tasks.append({'task_id': task_id, 'error': str(revoke_error)})
                    redis_client.delete(key)
                    revoked_count += 1
            except Exception as key_error:
                logger.error(f"Error processing key {key}: {key_error}")
                failed_tasks.append({'key': str(key), 'error': str(key_error)})
        with managed_session() as session:
            matches = session.query(MLSMatch).all()
            for match in matches:
                match.thread_creation_time = None
                match.live_reporting_scheduled = False
                match.live_reporting_started = False
                match.live_reporting_status = 'not_started'
        response_data = {'success': True, 'message': f'Revoked {revoked_count} tasks and cleaned up Redis', 'revoked_count': revoked_count}
        if failed_tasks:
            response_data['failed_tasks'] = failed_tasks
            response_data['warning'] = 'Some tasks failed to revoke'
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
            redis_client = RedisManager().client
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