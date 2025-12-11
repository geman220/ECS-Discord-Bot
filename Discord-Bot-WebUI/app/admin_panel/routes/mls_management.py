# app/admin_panel/routes/mls_management.py

"""
Admin Panel MLS Match Management Routes

This module contains routes for MLS match management including:
- Match scheduling and thread creation
- Live reporting controls
- ESPN data fetching
- Match task monitoring
"""

import logging
from datetime import datetime, timedelta
import pytz
from flask import render_template, request, jsonify, g, redirect, url_for
from flask_login import login_required, current_user

from .. import admin_panel_bp
from app.decorators import role_required
from app.models import MLSMatch
from app.models.admin_config import AdminAuditLog
from app.models.match_status import MatchStatus
from app.tasks.tasks_live_reporting import (
    force_create_mls_thread_task,
    schedule_all_mls_threads_task,
    schedule_mls_thread_task
)
from app.utils.task_monitor import get_task_info

logger = logging.getLogger(__name__)


# Competition code mappings
COMPETITION_MAPPINGS = {
    "MLS": "usa.1",
    "US Open Cup": "usa.open",
    "FIFA Club World Cup": "fifa.cwc",
    "Concacaf": "concacaf.league",
    "Concacaf Champions League": "concacaf.champions",
    "Leagues Cup": "concacaf.leagues.cup",
}


# -----------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------

def get_status_color(status):
    """Returns Bootstrap color class for match status."""
    # Use MatchStatus enum methods for standardized status values
    return MatchStatus.get_color_class(status)


def get_status_icon(status):
    """Returns icon class for match status."""
    # Use MatchStatus enum methods for standardized status values
    return MatchStatus.get_icon_class(status)


def get_status_display(status):
    """Returns human-readable status text."""
    # Use MatchStatus enum methods for standardized status values
    return MatchStatus.get_display_name(status)


# -----------------------------------------------------------
# MLS Match Dashboard Routes
# -----------------------------------------------------------

@admin_panel_bp.route('/mls')
@login_required
@role_required(['Global Admin', 'Discord Admin', 'Pub League Admin'])
def mls_overview():
    """MLS match management overview dashboard."""
    session = g.db_session
    try:
        now = datetime.now(pytz.UTC)

        # Get match counts
        total_matches = session.query(MLSMatch).count()
        upcoming_matches = session.query(MLSMatch).filter(MLSMatch.date_time > now).count()
        live_matches = session.query(MLSMatch).filter(MLSMatch.live_reporting_status == MatchStatus.RUNNING).count()
        finished_matches = session.query(MLSMatch).filter(
            MLSMatch.live_reporting_status.in_([MatchStatus.COMPLETED, MatchStatus.STOPPED])
        ).count()

        # Get recent and upcoming matches for quick view
        recent_cutoff = now - timedelta(days=3)
        future_cutoff = now + timedelta(days=14)

        visible_matches = session.query(MLSMatch).filter(
            MLSMatch.date_time >= recent_cutoff,
            MLSMatch.date_time <= future_cutoff
        ).order_by(MLSMatch.date_time).limit(10).all()

        # Add status data for display
        for match in visible_matches:
            match.status_color = get_status_color(match.live_reporting_status)
            match.status_icon = get_status_icon(match.live_reporting_status)
            match.status_display = get_status_display(match.live_reporting_status)

        stats = {
            'total_matches': total_matches,
            'upcoming_matches': upcoming_matches,
            'live_matches': live_matches,
            'finished_matches': finished_matches
        }

        return render_template('admin_panel/mls/overview.html',
                             stats=stats,
                             matches=visible_matches,
                             competition_mappings=COMPETITION_MAPPINGS)
    except Exception as e:
        logger.error(f"Error loading MLS overview: {e}")
        return render_template('admin_panel/mls/overview.html',
                             stats={'total_matches': 0, 'upcoming_matches': 0,
                                   'live_matches': 0, 'finished_matches': 0},
                             matches=[],
                             competition_mappings=COMPETITION_MAPPINGS,
                             error=str(e))


@admin_panel_bp.route('/mls/matches')
@login_required
@role_required(['Global Admin', 'Discord Admin', 'Pub League Admin'])
def mls_matches():
    """Full MLS match management page."""
    session = g.db_session
    try:
        now = datetime.now(pytz.UTC)

        # Define time ranges
        recent_cutoff = now - timedelta(days=3)
        future_cutoff = now + timedelta(days=60)
        historical_cutoff = now - timedelta(days=30)

        # Get recent/future matches (shown by default)
        visible_matches = session.query(MLSMatch).filter(
            MLSMatch.date_time >= recent_cutoff,
            MLSMatch.date_time <= future_cutoff
        ).order_by(MLSMatch.date_time).all()

        # Get older historical matches (collapsed by default)
        historical_matches = session.query(MLSMatch).filter(
            MLSMatch.date_time >= historical_cutoff,
            MLSMatch.date_time < recent_cutoff
        ).order_by(MLSMatch.date_time.desc()).all()

        # Add enhanced data for visible matches
        for match in visible_matches:
            match.status_color = get_status_color(match.live_reporting_status)
            match.status_icon = get_status_icon(match.live_reporting_status)
            match.status_display = get_status_display(match.live_reporting_status)
            match.task_details = {'status': 'LOADING'}

        # Add enhanced data for historical matches
        for match in historical_matches:
            match.status_color = get_status_color(match.live_reporting_status)
            match.status_icon = get_status_icon(match.live_reporting_status)
            match.status_display = get_status_display(match.live_reporting_status)
            match.task_details = {'status': 'HISTORICAL'}

        return render_template(
            'admin_panel/mls/matches.html',
            matches=visible_matches,
            historical_matches=historical_matches,
            historical_count=len(historical_matches),
            current_time=datetime.utcnow(),
            timedelta=timedelta,
            competition_mappings=COMPETITION_MAPPINGS
        )
    except Exception as e:
        logger.error(f"Error loading MLS matches: {e}")
        return render_template('admin_panel/mls/matches.html',
                             matches=[],
                             historical_matches=[],
                             historical_count=0,
                             current_time=datetime.utcnow(),
                             timedelta=timedelta,
                             competition_mappings=COMPETITION_MAPPINGS,
                             error=str(e))


# -----------------------------------------------------------
# MLS Match Actions Routes
# -----------------------------------------------------------

@admin_panel_bp.route('/mls/schedule/<int:match_id>', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def mls_schedule_match(match_id):
    """Schedule match tasks (thread creation and live reporting)."""
    session = g.db_session

    match = session.query(MLSMatch).get(match_id)
    if not match:
        return jsonify({'success': False, 'error': 'Match not found'}), 404

    try:
        task_result = schedule_mls_thread_task.delay(match_id)

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='mls_match_schedule',
            resource_type='mls_match',
            resource_id=str(match_id),
            new_value=f'Scheduled match vs {match.opponent}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        home_team = 'Seattle Sounders FC' if match.is_home_game else match.opponent
        away_team = match.opponent if match.is_home_game else 'Seattle Sounders FC'
        return jsonify({
            'success': True,
            'message': f'Match thread scheduled for {home_team} vs {away_team}',
            'task_id': task_result.id
        })
    except Exception as e:
        logger.error(f"Error scheduling match task: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/mls/create-thread/<int:match_id>', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def mls_create_thread(match_id):
    """Create thread immediately for a match."""
    session = g.db_session

    match = session.query(MLSMatch).get(match_id)
    if not match:
        return jsonify({'success': False, 'error': 'Match not found'}), 404

    try:
        task_result = force_create_mls_thread_task.delay(match_id)

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='mls_thread_create',
            resource_type='mls_match',
            resource_id=str(match_id),
            new_value=f'Thread created for match vs {match.opponent}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        home_team = 'Seattle Sounders FC' if match.is_home_game else match.opponent
        away_team = match.opponent if match.is_home_game else 'Seattle Sounders FC'
        return jsonify({
            'success': True,
            'message': f'Thread creation initiated for {home_team} vs {away_team}',
            'task_id': task_result.id
        })
    except Exception as e:
        logger.error(f"Error creating match thread: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/mls/start-reporting/<int:match_id>', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def mls_start_reporting(match_id):
    """Start live reporting for a match."""
    session = g.db_session

    match = session.query(MLSMatch).get(match_id)
    if not match:
        return jsonify({'success': False, 'error': 'Match not found'}), 404

    try:
        if match.live_reporting_status == 'running':
            return jsonify({'success': False, 'error': 'Live reporting already running'}), 400

        from app.models import LiveReportingSession

        # Check if live session already exists
        existing_session = session.query(LiveReportingSession).filter_by(
            match_id=str(match.match_id),
            is_active=True
        ).first()

        if existing_session:
            return jsonify({
                'success': True,
                'match_id': match.match_id,
                'session_id': existing_session.id,
                'message': 'Session already active'
            })

        # Create live reporting session
        live_session = LiveReportingSession(
            match_id=str(match.match_id),
            thread_id=str(match.discord_thread_id),
            competition=match.competition or 'usa.1',
            is_active=True,
            started_at=datetime.utcnow(),
            last_update=datetime.utcnow()
        )

        session.add(live_session)
        session.commit()

        # Update match status
        match.live_reporting_status = 'running'
        match.live_reporting_task_id = f"session_{live_session.id}"
        match.live_reporting_started = True
        match.live_reporting_scheduled = True
        session.commit()

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='mls_live_reporting_start',
            resource_type='mls_match',
            resource_id=str(match_id),
            new_value=f'Live reporting started for match vs {match.opponent}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        home_team = 'Seattle Sounders FC' if match.is_home_game else match.opponent
        away_team = match.opponent if match.is_home_game else 'Seattle Sounders FC'
        return jsonify({
            'success': True,
            'message': f'Live reporting started for {home_team} vs {away_team}',
            'session_id': live_session.id
        })
    except Exception as e:
        logger.error(f"Error starting live reporting: {e}")
        session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/mls/stop-reporting/<int:match_id>', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def mls_stop_reporting(match_id):
    """Stop live reporting for a match."""
    session = g.db_session

    match = session.query(MLSMatch).get(match_id)
    if not match:
        return jsonify({'success': False, 'error': 'Match not found'}), 404

    try:
        from app.utils.safe_redis import get_safe_redis
        from app.core import celery
        import json

        revoked_tasks = []

        # Stop active live reporting task
        if match.live_reporting_task_id:
            try:
                celery.control.revoke(match.live_reporting_task_id, terminate=True)
                revoked_tasks.append(f"Active task: {match.live_reporting_task_id}")
                match.live_reporting_task_id = None
            except Exception as e:
                logger.warning(f"Could not revoke active task: {e}")

        # Stop scheduled live reporting task from Redis
        redis_client = get_safe_redis()
        reporting_key = f"match_scheduler:{match.id}:reporting"

        if redis_client.exists(reporting_key):
            reporting_data = redis_client.get(reporting_key)
            if reporting_data:
                try:
                    reporting_info = json.loads(reporting_data.decode('utf-8'))
                    task_id = reporting_info.get('task_id')
                    if task_id:
                        celery.control.revoke(task_id, terminate=True)
                        revoked_tasks.append(f"Scheduled task: {task_id}")
                except (json.JSONDecodeError, AttributeError):
                    task_id = reporting_data.decode('utf-8') if isinstance(reporting_data, bytes) else str(reporting_data)
                    celery.control.revoke(task_id, terminate=True)
                    revoked_tasks.append(f"Scheduled task: {task_id}")

                redis_client.delete(reporting_key)

        # Update match status
        match.live_reporting_started = False
        match.live_reporting_status = 'stopped'
        match.live_reporting_scheduled = False
        session.commit()

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='mls_live_reporting_stop',
            resource_type='mls_match',
            resource_id=str(match_id),
            new_value=f'Live reporting stopped for match vs {match.opponent}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        home_team = 'Seattle Sounders FC' if match.is_home_game else match.opponent
        away_team = match.opponent if match.is_home_game else 'Seattle Sounders FC'

        message = f'Live reporting stopped for {home_team} vs {away_team}'
        if revoked_tasks:
            message += f'. Revoked tasks: {", ".join(revoked_tasks)}'

        return jsonify({
            'success': True,
            'message': message,
            'revoked_tasks': revoked_tasks
        })
    except Exception as e:
        logger.error(f"Error stopping live reporting: {e}")
        session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/mls/schedule-all', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def mls_schedule_all():
    """Schedule all upcoming matches."""
    try:
        task_result = schedule_all_mls_threads_task.delay()

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='mls_schedule_all',
            resource_type='system',
            resource_id='mls',
            new_value='All match scheduling initiated',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({
            'success': True,
            'message': 'All match scheduling initiated',
            'task_id': task_result.id
        })
    except Exception as e:
        logger.error(f"Error scheduling all matches: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# -----------------------------------------------------------
# ESPN Data Fetching Routes
# -----------------------------------------------------------

@admin_panel_bp.route('/mls/fetch-espn', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def mls_fetch_espn():
    """Fetch all upcoming Seattle Sounders matches from ESPN."""
    try:
        from app.api_utils import async_to_sync, extract_match_details
        from app.services.espn_service import get_espn_service
        from app.db_utils import insert_mls_match

        session = g.db_session
        total_matches_added = 0
        competitions_checked = []
        espn_service = get_espn_service()

        for competition_name, competition_code in COMPETITION_MAPPINGS.items():
            try:
                team_endpoint = f"sports/soccer/{competition_code}/teams/9726/schedule"
                team_data = async_to_sync(espn_service.fetch_data(endpoint=team_endpoint))

                if team_data and 'events' in team_data:
                    competitions_checked.append(competition_name)

                    for event in team_data['events']:
                        try:
                            event_date = datetime.strptime(event['date'], "%Y-%m-%dT%H:%MZ")
                            if event_date < datetime.utcnow():
                                continue

                            match_details = extract_match_details(event)

                            existing_match = session.query(MLSMatch).filter_by(
                                match_id=match_details['match_id']
                            ).first()

                            if existing_match:
                                continue

                            match = insert_mls_match(
                                session,
                                match_details['match_id'],
                                match_details['opponent'],
                                match_details['date_time'],
                                match_details['is_home_game'],
                                match_details['match_summary_link'],
                                match_details['match_stats_link'],
                                match_details['match_commentary_link'],
                                match_details['venue'],
                                competition_code
                            )

                            session.commit()

                            if match:
                                total_matches_added += 1

                                # Auto-schedule tasks
                                try:
                                    from app.match_scheduler import MatchScheduler
                                    scheduler = MatchScheduler()
                                    scheduler.schedule_match_tasks(match.id, force=False)
                                except Exception as sched_e:
                                    logger.error(f"Error scheduling tasks: {sched_e}")

                        except Exception as e:
                            logger.error(f"Error processing match: {e}")
                            continue

            except Exception as e:
                logger.error(f"Error fetching {competition_name} matches: {e}")
                continue

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='mls_fetch_espn',
            resource_type='system',
            resource_id='espn',
            new_value=f'Fetched {total_matches_added} new matches',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        if total_matches_added > 0:
            return jsonify({
                'success': True,
                'message': f'Successfully added {total_matches_added} new matches',
                'count': total_matches_added,
                'competitions_checked': competitions_checked
            })
        else:
            return jsonify({
                'success': True,
                'message': 'No new matches found',
                'count': 0,
                'competitions_checked': competitions_checked
            })

    except Exception as e:
        logger.error(f"Error fetching ESPN matches: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/mls/remove/<int:match_id>', methods=['POST', 'DELETE'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def mls_remove_match(match_id):
    """Remove a specific match and clean up all associated tasks."""
    session = g.db_session

    match = session.query(MLSMatch).get(match_id)
    if not match:
        return jsonify({'success': False, 'error': 'Match not found'}), 404

    try:
        from app.utils.safe_redis import get_safe_redis
        from app.core import celery
        import json

        match_info = f"{match.opponent}"
        revoked_tasks = []
        cleaned_keys = []

        # Stop active live reporting task
        if match.live_reporting_task_id:
            try:
                celery.control.revoke(match.live_reporting_task_id, terminate=True)
                revoked_tasks.append(f"Active task: {match.live_reporting_task_id}")
            except Exception as e:
                logger.warning(f"Could not revoke active task: {e}")

        # Clean up Redis scheduled tasks
        redis_client = get_safe_redis()
        thread_key = f"match_scheduler:{match.id}:thread"
        reporting_key = f"match_scheduler:{match.id}:reporting"

        for key_name, redis_key in [('thread', thread_key), ('reporting', reporting_key)]:
            if redis_client.exists(redis_key):
                data = redis_client.get(redis_key)
                if data:
                    try:
                        task_info = json.loads(data.decode('utf-8'))
                        task_id = task_info.get('task_id')
                        if task_id:
                            celery.control.revoke(task_id, terminate=True)
                            revoked_tasks.append(f"Scheduled {key_name}: {task_id}")
                    except (json.JSONDecodeError, AttributeError):
                        task_id = data.decode('utf-8') if isinstance(data, bytes) else str(data)
                        celery.control.revoke(task_id, terminate=True)
                        revoked_tasks.append(f"Scheduled {key_name}: {task_id}")

                redis_client.delete(redis_key)
                cleaned_keys.append(redis_key)

        # Remove the match from database
        session.delete(match)
        session.commit()

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='mls_match_remove',
            resource_type='mls_match',
            resource_id=str(match_id),
            new_value=f'Removed match vs {match_info}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        message = f'Removed match: {match_info}'
        if revoked_tasks:
            message += f'. Revoked {len(revoked_tasks)} task(s)'
        if cleaned_keys:
            message += f'. Cleaned {len(cleaned_keys)} Redis key(s)'

        return jsonify({
            'success': True,
            'message': message,
            'revoked_tasks': revoked_tasks,
            'cleaned_keys': cleaned_keys
        })
    except Exception as e:
        logger.error(f"Error removing match: {e}")
        session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


# -----------------------------------------------------------
# Task Monitoring API Routes
# -----------------------------------------------------------

@admin_panel_bp.route('/mls/task-details/<task_id>')
@login_required
@role_required(['Global Admin', 'Discord Admin', 'Pub League Admin'])
def mls_task_details(task_id):
    """Get detailed information about a specific task."""
    try:
        task_info = get_task_info(task_id)
        return jsonify(task_info)
    except Exception as e:
        logger.error(f"Error getting task details: {e}")
        return jsonify({'error': str(e)}), 500


@admin_panel_bp.route('/mls/match-tasks/<int:match_id>')
@login_required
@role_required(['Global Admin', 'Discord Admin', 'Pub League Admin'])
def mls_match_tasks(match_id):
    """Get detailed task information for a specific match."""
    try:
        from app.utils.task_status_helper import get_enhanced_match_task_status

        result = get_enhanced_match_task_status(match_id, use_cache=True)
        response = jsonify(result)
        response.headers['Cache-Control'] = 'max-age=60, public'
        return response

    except Exception as e:
        logger.error(f"Error getting match tasks for {match_id}: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'match_id': match_id
        }), 500


@admin_panel_bp.route('/mls/api/statuses')
@login_required
@role_required(['Global Admin', 'Discord Admin', 'Pub League Admin'])
def mls_match_statuses_api():
    """Get match statuses for AJAX updates."""
    session = g.db_session

    try:
        now = datetime.now(pytz.UTC)
        cutoff_start = now - timedelta(days=7)
        cutoff_end = now + timedelta(days=30)

        matches = session.query(MLSMatch).filter(
            MLSMatch.date_time >= cutoff_start,
            MLSMatch.date_time <= cutoff_end
        ).all()

        statuses = []
        for match in matches:
            statuses.append({
                'id': match.id,
                'status': match.live_reporting_status,
                'status_color': get_status_color(match.live_reporting_status),
                'status_icon': get_status_icon(match.live_reporting_status),
                'status_display': get_status_display(match.live_reporting_status)
            })

        return jsonify({'statuses': statuses})
    except Exception as e:
        logger.error(f"Error getting match statuses: {e}")
        return jsonify({'error': str(e)}), 500


# -----------------------------------------------------------
# Task Monitoring & Debugging Routes
# -----------------------------------------------------------

@admin_panel_bp.route('/mls/task-monitoring')
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def mls_task_monitoring():
    """Task monitoring dashboard for scheduled match tasks."""
    from app.models import ScheduledTask, TaskType, TaskState

    session = g.db_session
    now = datetime.now(pytz.UTC)

    # Get filter parameters
    task_type_filter = request.args.get('task_type', 'all')
    state_filter = request.args.get('state', 'all')
    days_back = int(request.args.get('days', '7'))

    # Base query
    query = session.query(ScheduledTask)

    # Apply filters
    if task_type_filter != 'all':
        query = query.filter(ScheduledTask.task_type == task_type_filter)

    if state_filter != 'all':
        query = query.filter(ScheduledTask.state == state_filter)
    else:
        # Show active/recent tasks by default
        cutoff = now - timedelta(days=days_back)
        query = query.filter(
            (ScheduledTask.scheduled_time >= cutoff) |
            (ScheduledTask.state.in_([TaskState.SCHEDULED, TaskState.RUNNING]))
        )

    # Order by scheduled time descending
    tasks = query.order_by(ScheduledTask.scheduled_time.desc()).all()

    # Get statistics
    total_scheduled = session.query(ScheduledTask).filter(
        ScheduledTask.state == TaskState.SCHEDULED
    ).count()

    total_running = session.query(ScheduledTask).filter(
        ScheduledTask.state == TaskState.RUNNING
    ).count()

    total_failed = session.query(ScheduledTask).filter(
        ScheduledTask.state == TaskState.FAILED,
        ScheduledTask.updated_at >= now - timedelta(days=1)
    ).count()

    overdue_tasks = session.query(ScheduledTask).filter(
        ScheduledTask.state == TaskState.SCHEDULED,
        ScheduledTask.scheduled_time < now
    ).count()

    # Enrich tasks with match info
    task_list = []
    for task in tasks:
        match = session.query(MLSMatch).get(task.match_id)
        task_dict = task.to_dict()
        task_dict['match'] = {
            'opponent': match.opponent if match else 'Unknown',
            'date_time': match.date_time.isoformat() if match and match.date_time else None,
            'thread_created': match.thread_created if match else False,
            'live_reporting_status': match.live_reporting_status if match else 'unknown'
        } if match else None
        task_dict['is_overdue'] = task.state == TaskState.SCHEDULED and task.scheduled_time < now
        task_list.append(task_dict)

    stats = {
        'total_scheduled': total_scheduled,
        'total_running': total_running,
        'total_failed': total_failed,
        'overdue_tasks': overdue_tasks
    }

    return render_template(
        'admin_panel/mls/task_monitoring.html',
        tasks=task_list,
        stats=stats,
        task_types=[t.value for t in TaskType],
        task_states=[s.value for s in TaskState],
        current_filters={
            'task_type': task_type_filter,
            'state': state_filter,
            'days': days_back
        }
    )


@admin_panel_bp.route('/mls/task/<int:task_id>/retry', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def task_retry(task_id):
    """Manually retry a failed task."""
    from app.models import ScheduledTask, TaskType
    from app.tasks.match_scheduler import (
        create_mls_match_thread_task,
        start_mls_live_reporting_task
    )

    session = g.db_session

    try:
        task = session.query(ScheduledTask).get(task_id)
        if not task:
            return jsonify({'success': False, 'error': 'Task not found'}), 404

        # Get associated match
        match = session.query(MLSMatch).get(task.match_id)
        if not match:
            return jsonify({'success': False, 'error': 'Match not found'}), 404

        # Retry based on task type
        if task.task_type == TaskType.THREAD_CREATION:
            celery_task = create_mls_match_thread_task.apply_async(args=[match.id])
            task.mark_running(celery_task.id)
            message = f"Thread creation task rescheduled for match {match.opponent}"

        elif task.task_type == TaskType.LIVE_REPORTING_START:
            celery_task = start_mls_live_reporting_task.apply_async(args=[match.id])
            task.mark_running(celery_task.id)
            match.live_reporting_status = MatchStatus.RUNNING
            message = f"Live reporting task rescheduled for match {match.opponent}"

        else:
            return jsonify({'success': False, 'error': 'Unknown task type'}), 400

        session.commit()

        # Log action
        AdminAuditLog.log_action(
            session,
            current_user.id,
            'task_retry',
            f"Manually retried task {task_id} for match {match.opponent}",
            {'task_id': task_id, 'match_id': match.id, 'task_type': task.task_type}
        )

        logger.info(f"Task {task_id} manually retried by {current_user.username}")

        return jsonify({
            'success': True,
            'message': message,
            'celery_task_id': celery_task.id
        })

    except Exception as e:
        logger.error(f"Error retrying task {task_id}: {e}", exc_info=True)
        session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/mls/task/<int:task_id>/expire', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def task_expire(task_id):
    """Manually expire a task."""
    from app.models import ScheduledTask

    session = g.db_session

    try:
        task = session.query(ScheduledTask).get(task_id)
        if not task:
            return jsonify({'success': False, 'error': 'Task not found'}), 404

        task.mark_expired()
        session.commit()

        # Log action
        AdminAuditLog.log_action(
            session,
            current_user.id,
            'task_expire',
            f"Manually expired task {task_id}",
            {'task_id': task_id}
        )

        logger.info(f"Task {task_id} manually expired by {current_user.username}")

        return jsonify({
            'success': True,
            'message': 'Task marked as expired'
        })

    except Exception as e:
        logger.error(f"Error expiring task {task_id}: {e}", exc_info=True)
        session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/mls/match/<int:match_id>/debug')
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def match_debug(match_id):
    """Comprehensive match debugging information."""
    from app.models import ScheduledTask, TaskType, TaskState
    from app.models.live_reporting_session import LiveReportingSession

    session = g.db_session

    try:
        match = session.query(MLSMatch).get(match_id)
        if not match:
            return jsonify({'success': False, 'error': 'Match not found'}), 404

        # Get scheduled tasks
        tasks = session.query(ScheduledTask).filter(
            ScheduledTask.match_id == match_id
        ).order_by(ScheduledTask.created_at.desc()).all()

        # Get live reporting session
        live_session = session.query(LiveReportingSession).filter(
            LiveReportingSession.match_id == str(match.match_id)
        ).first()

        # Build debug info
        debug_info = {
            'match': {
                'id': match.id,
                'match_id': match.match_id,
                'opponent': match.opponent,
                'date_time': match.date_time.isoformat() if match.date_time else None,
                'thread_created': match.thread_created,
                'discord_thread_id': match.discord_thread_id,
                'live_reporting_status': match.live_reporting_status,
                'competition': match.competition,
                'venue': match.venue
            },
            'tasks': [task.to_dict() for task in tasks],
            'live_session': {
                'exists': live_session is not None,
                'is_active': live_session.is_active if live_session else False,
                'started_at': live_session.started_at.isoformat() if live_session and live_session.started_at else None,
                'last_update': live_session.last_update_at.isoformat() if live_session and live_session.last_update_at else None,
                'update_count': live_session.update_count if live_session else 0,
                'error_count': live_session.error_count if live_session else 0,
                'last_error': live_session.last_error if live_session else None
            } if live_session else None,
            'system_health': {
                'current_time': datetime.now(pytz.UTC).isoformat(),
                'thread_creation_deadline': (match.date_time - timedelta(hours=48)).isoformat() if match.date_time else None,
                'live_reporting_start_time': (match.date_time - timedelta(minutes=5)).isoformat() if match.date_time else None
            }
        }

        return jsonify(debug_info)

    except Exception as e:
        logger.error(f"Error getting debug info for match {match_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/mls/match/<int:match_id>/resync', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def match_resync(match_id):
    """Resync a match - check and fix any missing tasks or threads."""
    from app.models import ScheduledTask, TaskType, TaskState
    from app.tasks.match_scheduler import (
        create_mls_match_thread_task,
        start_mls_live_reporting_task
    )

    session = g.db_session
    actions_taken = []

    try:
        match = session.query(MLSMatch).get(match_id)
        if not match:
            return jsonify({'success': False, 'error': 'Match not found'}), 404

        now = datetime.now(pytz.UTC)

        # Check 1: Thread creation
        thread_deadline = match.date_time - timedelta(hours=48)
        if now >= thread_deadline and not match.thread_created:
            # Thread should exist but doesn't - create it now
            existing_thread_task = ScheduledTask.find_existing_task(
                session, match.id, TaskType.THREAD_CREATION
            )

            if not existing_thread_task or existing_thread_task.state in [TaskState.FAILED, TaskState.EXPIRED]:
                celery_task = create_mls_match_thread_task.apply_async(args=[match.id])

                if existing_thread_task:
                    existing_thread_task.mark_running(celery_task.id)
                else:
                    new_task = ScheduledTask(
                        task_type=TaskType.THREAD_CREATION,
                        match_id=match.id,
                        celery_task_id=celery_task.id,
                        scheduled_time=thread_deadline,
                        state=TaskState.RUNNING
                    )
                    session.add(new_task)

                actions_taken.append(f"✅ Scheduled thread creation (task: {celery_task.id})")

        # Check 2: Live reporting
        reporting_start = match.date_time - timedelta(minutes=5)
        match_end = match.date_time + timedelta(hours=3)

        if now >= reporting_start and now < match_end:
            if match.thread_created and match.live_reporting_status != MatchStatus.RUNNING:
                # Should be live reporting but isn't
                existing_reporting_task = ScheduledTask.find_existing_task(
                    session, match.id, TaskType.LIVE_REPORTING_START
                )

                if not existing_reporting_task or existing_reporting_task.state in [TaskState.FAILED, TaskState.EXPIRED]:
                    celery_task = start_mls_live_reporting_task.apply_async(args=[match.id])

                    if existing_reporting_task:
                        existing_reporting_task.mark_running(celery_task.id)
                    else:
                        new_task = ScheduledTask(
                            task_type=TaskType.LIVE_REPORTING_START,
                            match_id=match.id,
                            celery_task_id=celery_task.id,
                            scheduled_time=reporting_start,
                            state=TaskState.RUNNING
                        )
                        session.add(new_task)

                    match.live_reporting_status = MatchStatus.RUNNING
                    actions_taken.append(f"✅ Started live reporting (task: {celery_task.id})")
            elif not match.thread_created:
                actions_taken.append("⚠️ Cannot start live reporting - thread not created")

        # Check 3: Task consistency
        all_tasks = session.query(ScheduledTask).filter(
            ScheduledTask.match_id == match.id
        ).all()

        for task in all_tasks:
            if task.state == TaskState.SCHEDULED and task.scheduled_time < (now - timedelta(hours=6)):
                task.mark_expired()
                actions_taken.append(f"🧹 Expired old task {task.id} ({task.task_type})")

        session.commit()

        # Log action
        AdminAuditLog.log_action(
            session,
            current_user.id,
            'match_resync',
            f"Resynced match {match.opponent}",
            {'match_id': match.id, 'actions': actions_taken}
        )

        logger.info(f"Match {match_id} resynced by {current_user.username}: {actions_taken}")

        return jsonify({
            'success': True,
            'message': f'Resync complete - {len(actions_taken)} action(s) taken',
            'actions': actions_taken
        })

    except Exception as e:
        logger.error(f"Error resyncing match {match_id}: {e}", exc_info=True)
        session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
