# app/routes/admin_live_reporting.py

"""
DEPRECATED: Admin Routes for Live Reporting Management

This blueprint is deprecated. All functionality has been consolidated into
the admin_panel MLS management routes at /admin-panel/mls/*.

All page routes now redirect to their System C equivalents.
API routes are kept as thin forwards for backwards compatibility.
"""

import logging
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, redirect, url_for
from flask_login import login_required

from app.services.realtime_bridge_service import realtime_bridge, check_realtime_health, get_coordination_status
from app.models import LiveReportingSession
from app.models.external import MLSMatch
from app.utils.task_session_manager import task_session
from app.decorators import role_required

logger = logging.getLogger(__name__)

# Create blueprint
admin_live_bp = Blueprint('admin_live', __name__, url_prefix='/admin/live-reporting')


# -----------------------------------------------------------
# Page Routes - All redirect to System C (admin_panel.mls_*)
# -----------------------------------------------------------

@admin_live_bp.route('/')
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def dashboard():
    """Redirect to System C live reporting dashboard."""
    return redirect(url_for('admin_panel.live_reporting_dashboard'), code=301)


@admin_live_bp.route('/schedule-season', methods=['GET', 'POST'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def schedule_season():
    """Redirect to System C matches page (Schedule All + auto-scheduler covers this)."""
    return redirect(url_for('admin_panel.mls_matches'), code=301)


@admin_live_bp.route('/matches')
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def matches():
    """Redirect to System C matches page."""
    return redirect(url_for('admin_panel.mls_matches'), code=301)


@admin_live_bp.route('/match/<int:match_id>')
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def match_detail(match_id):
    """Redirect to System C matches page."""
    return redirect(url_for('admin_panel.mls_matches'), code=301)


@admin_live_bp.route('/sessions')
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def sessions():
    """Redirect to System C sessions page."""
    return redirect(url_for('admin_panel.mls_sessions'), code=301)


@admin_live_bp.route('/realtime-status')
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def realtime_status():
    """Redirect to System C live reporting dashboard (includes service status)."""
    return redirect(url_for('admin_panel.live_reporting_dashboard'), code=301)


# -----------------------------------------------------------
# API Routes - Thin forwards for backwards compatibility
# -----------------------------------------------------------

@admin_live_bp.route('/api/health')
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def api_health():
    """API endpoint for health status."""
    try:
        health = check_realtime_health()
        return jsonify(health)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_live_bp.route('/api/coordination')
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def api_coordination():
    """API endpoint for coordination status."""
    try:
        status = get_coordination_status()
        return jsonify(status)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_live_bp.route('/api/schedule-match/<int:match_id>', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def api_schedule_match(match_id):
    """API endpoint to schedule a specific match."""
    try:
        with task_session() as session:
            match = session.query(MLSMatch).filter_by(id=match_id).first()
            if not match:
                return jsonify({'error': 'Match not found'}), 404

            now = datetime.utcnow()

            if match.date_time and match.date_time > now:
                thread_time = match.date_time - timedelta(hours=48)
                if thread_time > now:
                    from app.services.match_scheduler_service import create_match_thread_task
                    create_match_thread_task.apply_async(
                        args=[match.id],
                        eta=thread_time,
                        expires=thread_time + timedelta(hours=2)
                    )

                live_start_time = match.date_time - timedelta(minutes=5)
                if live_start_time > now:
                    from app.services.match_scheduler_service import start_live_reporting_task
                    start_live_reporting_task.apply_async(
                        args=[match.id],
                        eta=live_start_time,
                        expires=live_start_time + timedelta(minutes=30)
                    )

                live_end_time = match.date_time + timedelta(hours=2)
                if live_end_time > now:
                    from app.services.match_scheduler_service import stop_live_reporting_task
                    stop_live_reporting_task.apply_async(
                        args=[match.id],
                        eta=live_end_time,
                        expires=live_end_time + timedelta(hours=1)
                    )

                return jsonify({
                    'success': True,
                    'message': f'Scheduled live reporting for match {match_id}',
                    'match_id': match_id
                })
            else:
                return jsonify({'error': 'Match date is in the past or not set'}), 400

    except Exception as e:
        logger.error(f"Error scheduling individual match: {e}")
        return jsonify({'error': str(e)}), 500


@admin_live_bp.route('/api/force-sync', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def api_force_sync():
    """API endpoint to force synchronization with real-time service."""
    try:
        result = realtime_bridge.force_session_sync()
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error forcing sync: {e}")
        return jsonify({'error': str(e)}), 500


@admin_live_bp.route('/api/send-command', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def api_send_command():
    """API endpoint to send commands to real-time service."""
    try:
        data = request.get_json()
        command = data.get('command')
        params = data.get('params', {})

        if not command:
            return jsonify({'error': 'Command is required'}), 400

        result = realtime_bridge.send_realtime_command(command, params)
        return jsonify(result)

    except Exception as e:
        logger.error(f"Error sending command: {e}")
        return jsonify({'error': str(e)}), 500


@admin_live_bp.route('/api/session/<int:session_id>/stop', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def api_stop_session(session_id):
    """API endpoint to manually stop a live reporting session."""
    try:
        with task_session() as session:
            live_session = session.query(LiveReportingSession).filter_by(id=session_id).first()
            if not live_session:
                return jsonify({'error': 'Session not found'}), 404

            if not live_session.is_active:
                return jsonify({'error': 'Session is not active'}), 400

            live_session.is_active = False
            live_session.ended_at = datetime.utcnow()
            session.commit()

            from app.services.realtime_bridge_service import notify_session_stopped
            notify_session_stopped(live_session.id, live_session.match_id, "Manual stop via admin")

            return jsonify({
                'success': True,
                'message': f'Stopped session {session_id}',
                'session_id': session_id
            })

    except Exception as e:
        logger.error(f"Error stopping session: {e}")
        return jsonify({'error': str(e)}), 500
