# app/routes/admin_live_reporting.py

"""
Admin Routes for Live Reporting Management

Flask admin interface for managing the enterprise live reporting system.
Provides web UI for scheduling matches, monitoring real-time service, and debugging.
"""

import logging
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user

from app.services.match_scheduler_service import match_scheduler_service
from app.services.realtime_bridge_service import realtime_bridge, check_realtime_health, get_coordination_status
from app.models import LiveReportingSession, Season, League
from app.models.external import MLSMatch
from app.utils.task_session_manager import task_session
from app.decorators import role_required
from app.core import db

logger = logging.getLogger(__name__)

# Create blueprint
admin_live_bp = Blueprint('admin_live', __name__, url_prefix='/admin/live-reporting')


@admin_live_bp.route('/')
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def dashboard():
    """
    Live reporting admin dashboard.
    """
    try:
        with task_session() as session:
            # Get system status
            realtime_health = check_realtime_health()
            coordination_status = get_coordination_status()

            # Get recent activity
            active_sessions = session.query(LiveReportingSession).filter_by(is_active=True).all()
            recent_sessions = session.query(LiveReportingSession).order_by(
                LiveReportingSession.started_at.desc()
            ).limit(10).all()

            # Get upcoming MLS/Sounders matches (not pub league matches)
            from app.models.external import MLSMatch
            upcoming_matches = session.query(MLSMatch).filter(
                MLSMatch.date_time > datetime.utcnow(),
                MLSMatch.date_time < datetime.utcnow() + timedelta(days=14)
            ).order_by(MLSMatch.date_time).limit(10).all()

            return render_template('admin/live_reporting_dashboard.html',
                                   realtime_health=realtime_health,
                                   coordination_status=coordination_status,
                                   active_sessions=active_sessions,
                                   recent_sessions=recent_sessions,
                                   upcoming_matches=upcoming_matches)

    except Exception as e:
        logger.error(f"Error loading live reporting dashboard: {e}")
        flash(f"Error loading dashboard: {e}", 'error')
        return render_template('500.html', error=str(e)), 500


@admin_live_bp.route('/schedule-season', methods=['GET', 'POST'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def schedule_season():
    """
    Schedule live reporting for an entire season.
    """
    if request.method == 'POST':
        try:
            season_id = int(request.form['season_id'])

            # Schedule the season
            result = match_scheduler_service.schedule_season_matches(season_id)

            if result['success']:
                flash(f"Successfully scheduled {result['scheduled_threads']} threads and {result['scheduled_live']} live sessions for season {result['season_name']}", 'success')
            else:
                flash(f"Error scheduling season: {result['error']}", 'error')

            return redirect(url_for('admin_live.schedule_season'))

        except Exception as e:
            logger.error(f"Error scheduling season: {e}")
            flash(f"Error scheduling season: {e}", 'error')

    # GET request - show form
    try:
        with task_session() as session:
            seasons = session.query(Season).join(League).order_by(Season.year.desc()).all()

            return render_template('admin/schedule_season.html', seasons=seasons)

    except Exception as e:
        logger.error(f"Error loading season scheduling form: {e}")
        flash(f"Error: {e}", 'error')
        return redirect(url_for('admin_live.dashboard'))


@admin_live_bp.route('/matches')
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def matches():
    """
    View and manage individual matches.
    """
    try:
        page = int(request.args.get('page', 1))
        per_page = 20

        with task_session() as session:
            # Get MLS matches with pagination
            matches_query = session.query(MLSMatch).filter(
                MLSMatch.date_time.isnot(None)
            ).order_by(MLSMatch.date_time.desc())

            total_matches = matches_query.count()
            matches_list = matches_query.offset((page - 1) * per_page).limit(per_page).all()

            # Get live reporting sessions for these matches
            # MLSMatch uses match_id field, not id
            match_ids = [m.match_id for m in matches_list]  # Use match_id field
            sessions = session.query(LiveReportingSession).filter(
                LiveReportingSession.match_id.in_(match_ids)
            ).all()

            # Create sessions lookup
            sessions_by_match = {s.match_id: s for s in sessions}

            return render_template('admin/matches.html',
                                   matches=matches_list,
                                   sessions_by_match=sessions_by_match,
                                   page=page,
                                   per_page=per_page,
                                   total_matches=total_matches)

    except Exception as e:
        logger.error(f"Error loading matches: {e}")
        flash(f"Error loading matches: {e}", 'error')
        return redirect(url_for('admin_live.dashboard'))


@admin_live_bp.route('/match/<int:match_id>')
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def match_detail(match_id):
    """
    Detailed view of a specific match and its live reporting status.
    """
    try:
        with task_session() as session:
            # Use MLSMatch for live reporting, not pub league Match
            match = session.query(MLSMatch).filter_by(id=match_id).first()
            if not match:
                flash("Match not found", 'error')
                return redirect(url_for('admin_live.matches'))

            # Get live reporting session (use match.match_id for MLSMatch)
            live_session = session.query(LiveReportingSession).filter_by(match_id=match.match_id if match else str(match_id)).first()

            # Get scheduling status for this match
            scheduling_status = match_scheduler_service.get_scheduling_status()

            # Find this match in scheduling status
            match_scheduling = None
            for category in ['upcoming_threads', 'upcoming_live', 'active_live', 'completed']:
                for match_info in scheduling_status.get(category, []):
                    if match_info.get('match_id') == (match.match_id if match else str(match_id)):
                        match_scheduling = match_info
                        match_scheduling['category'] = category
                        break

            return render_template('admin/match_detail.html',
                                   match=match,
                                   live_session=live_session,
                                   match_scheduling=match_scheduling)

    except Exception as e:
        logger.error(f"Error loading match detail: {e}")
        flash(f"Error loading match detail: {e}", 'error')
        return redirect(url_for('admin_live.matches'))


@admin_live_bp.route('/sessions')
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def sessions():
    """
    View and manage live reporting sessions.
    """
    try:
        status_filter = request.args.get('status', 'all')

        with task_session() as session:
            query = session.query(LiveReportingSession)

            if status_filter == 'active':
                query = query.filter_by(is_active=True)
            elif status_filter == 'inactive':
                query = query.filter_by(is_active=False)

            sessions_list = query.order_by(LiveReportingSession.created_at.desc()).limit(50).all()

            return render_template('admin/sessions.html',
                                   sessions=sessions_list,
                                   status_filter=status_filter)

    except Exception as e:
        logger.error(f"Error loading sessions: {e}")
        flash(f"Error loading sessions: {e}", 'error')
        return redirect(url_for('admin_live.dashboard'))


@admin_live_bp.route('/realtime-status')
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def realtime_status():
    """
    Real-time service status and monitoring.
    """
    try:
        health = check_realtime_health()
        coordination = get_coordination_status()

        return render_template('admin/realtime_status.html',
                               health=health,
                               coordination=coordination)

    except Exception as e:
        logger.error(f"Error loading real-time status: {e}")
        flash(f"Error loading real-time status: {e}", 'error')
        return redirect(url_for('admin_live.dashboard'))


# API endpoints for AJAX calls (web admin)
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

            # Create individual scheduling (simulate season scheduling for one match)
            now = datetime.utcnow()

            if match.date_time and match.date_time > now:
                # Schedule thread creation (48 hours before)
                thread_time = match.date_time - timedelta(hours=48)
                if thread_time > now:
                    from app.services.match_scheduler_service import create_match_thread_task
                    create_match_thread_task.apply_async(
                        args=[match.id],
                        eta=thread_time,
                        expires=thread_time + timedelta(hours=2)
                    )

                # Schedule live reporting start (5 minutes before)
                live_start_time = match.date_time - timedelta(minutes=5)
                if live_start_time > now:
                    from app.services.match_scheduler_service import start_live_reporting_task
                    start_live_reporting_task.apply_async(
                        args=[match.id],
                        eta=live_start_time,
                        expires=live_start_time + timedelta(minutes=30)
                    )

                # Schedule live reporting end (2 hours after start)
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
                    'message': f'Scheduled live reporting for {"Seattle Sounders FC" if match.is_home_game else match.opponent} vs {match.opponent if match.is_home_game else "Seattle Sounders FC"}',
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

            # Stop the session
            live_session.is_active = False
            live_session.ended_at = datetime.utcnow()
            session.commit()

            # Notify real-time service
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