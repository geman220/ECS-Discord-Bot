# app/monitoring/debug.py

"""
Debug Monitoring Routes

Provides endpoints for debugging and system stats:
- Debug logs
- Slow queries
- System statistics
"""

import logging
import psutil
from datetime import datetime

from flask import jsonify, current_app
from flask_login import login_required
from sqlalchemy import text

from app.monitoring import monitoring_bp
from app.decorators import role_required
from app.core.session_manager import managed_session

logger = logging.getLogger(__name__)


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
