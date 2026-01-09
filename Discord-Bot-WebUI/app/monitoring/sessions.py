# app/monitoring/sessions.py

"""
Session Monitoring Routes

Provides endpoints for monitoring Flask sessions:
- Active sessions
- Long-running sessions
- Session cleanup
"""

import time
import logging
from datetime import datetime

from flask import jsonify, render_template
from flask_login import login_required

from app.monitoring import monitoring_bp
from app.decorators import role_required
from app.utils.session_monitor import get_session_monitor

logger = logging.getLogger(__name__)


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

    return render_template('monitoring/sessions_flowbite.html',
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
