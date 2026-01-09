# app/monitoring/database.py

"""
Database Monitoring Routes

Provides endpoints for monitoring database connections:
- Connection status
- Connection stats
- Connection cleanup
- Historical monitoring data
"""

import logging
from datetime import datetime, timedelta

from flask import jsonify, request, render_template
from flask_login import login_required
from sqlalchemy import text

from app.monitoring import monitoring_bp
from app.decorators import role_required
from app.db_management import db_manager
from app.core import db
from app.core.session_manager import managed_session
from app.database.db_models import DBMonitoringSnapshot

logger = logging.getLogger(__name__)


@monitoring_bp.route('/db', endpoint='db_monitoring')
@login_required
@role_required(['Global Admin'])
def db_monitoring():
    """
    Render the database monitoring page.
    """
    return render_template('db_monitoring_flowbite.html', title='DB Monitoring')


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
        details = db_manager.get_transaction_details(pid) if hasattr(db_manager, 'get_transaction_details') else None

        if not details:
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
                    'stack_trace': "No captured Python stack trace available."
                }
            else:
                details = {'stack_trace': "No transaction details found."}

        return jsonify({'success': True, 'pid': pid, 'details': details})
    except Exception as e:
        logger.error(f"Error getting transaction details for pid {pid}: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
