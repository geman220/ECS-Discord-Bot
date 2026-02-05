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
from app.services.realtime_bridge_service import realtime_bridge, check_realtime_health, get_coordination_status
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
    from app.models import ScheduledTask, TaskState
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

        # Get failed tasks count for alert banner
        failed_tasks_count = session.query(ScheduledTask).filter(
            ScheduledTask.state == TaskState.FAILED.value
        ).count()

        # Get recent failed tasks for the alert (last 5)
        recent_failed_tasks = session.query(ScheduledTask).filter(
            ScheduledTask.state == TaskState.FAILED.value
        ).order_by(ScheduledTask.updated_at.desc()).limit(5).all()

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
            'finished_matches': finished_matches,
            'failed_tasks': failed_tasks_count
        }

        return render_template('admin_panel/mls/overview_flowbite.html',
                             stats=stats,
                             matches=visible_matches,
                             failed_tasks=recent_failed_tasks,
                             competition_mappings=COMPETITION_MAPPINGS)
    except Exception as e:
        logger.error(f"Error loading MLS overview: {e}")
        return render_template('admin_panel/mls/overview_flowbite.html',
                             stats={'total_matches': 0, 'upcoming_matches': 0,
                                   'live_matches': 0, 'finished_matches': 0},
                             matches=[],
                             competition_mappings=COMPETITION_MAPPINGS,
                             error=str(e))


@admin_panel_bp.route('/mls/live-reporting')
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def live_reporting_dashboard():
    """
    Live Reporting Dashboard - Real-time service monitoring and control.

    Provides system status, active sessions, and recent activity for the
    ESPN-based live reporting system.
    """
    session = g.db_session
    try:
        from app.models import LiveReportingSession
        from app.services.realtime_bridge_service import check_realtime_health, get_coordination_status

        now = datetime.now(pytz.UTC)

        # Get system status
        realtime_health = check_realtime_health()
        coordination_status = get_coordination_status()

        # Get active sessions
        active_sessions = session.query(LiveReportingSession).filter_by(is_active=True).all()

        # Get recent sessions (last 24 hours)
        recent_cutoff = now - timedelta(hours=24)
        recent_sessions = session.query(LiveReportingSession).filter(
            LiveReportingSession.started_at >= recent_cutoff
        ).order_by(LiveReportingSession.started_at.desc()).limit(20).all()

        # Get upcoming matches for the next 14 days
        upcoming_matches = session.query(MLSMatch).filter(
            MLSMatch.date_time > now,
            MLSMatch.date_time < now + timedelta(days=14)
        ).order_by(MLSMatch.date_time).limit(10).all()

        # Add status info to matches
        for match in upcoming_matches:
            match.status_color = get_status_color(match.live_reporting_status)
            match.status_icon = get_status_icon(match.live_reporting_status)
            match.status_display = get_status_display(match.live_reporting_status)

        # Statistics
        stats = {
            'active_sessions': len(active_sessions),
            'recent_sessions': len(recent_sessions),
            'upcoming_matches': len(upcoming_matches),
            'service_status': realtime_health.get('health', 'unknown')
        }

        # Log the access
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='access_live_reporting_dashboard',
            resource_type='mls',
            resource_id='live_reporting',
            new_value='Accessed live reporting dashboard',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return render_template('admin_panel/mls/live_reporting_dashboard_flowbite.html',
                             realtime_health=realtime_health,
                             coordination_status=coordination_status,
                             active_sessions=active_sessions,
                             recent_sessions=recent_sessions,
                             upcoming_matches=upcoming_matches,
                             stats=stats)

    except Exception as e:
        logger.error(f"Error loading live reporting dashboard: {e}")
        return render_template('admin_panel/mls/live_reporting_dashboard_flowbite.html',
                             realtime_health={'health': 'unknown', 'heartbeat_age_seconds': None},
                             coordination_status={},
                             active_sessions=[],
                             recent_sessions=[],
                             upcoming_matches=[],
                             stats={'active_sessions': 0, 'recent_sessions': 0, 'upcoming_matches': 0, 'service_status': 'error'},
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
            'admin_panel/mls/matches_flowbite.html',
            matches=visible_matches,
            historical_matches=historical_matches,
            historical_count=len(historical_matches),
            current_time=datetime.utcnow(),
            timedelta=timedelta,
            competition_mappings=COMPETITION_MAPPINGS
        )
    except Exception as e:
        logger.error(f"Error loading MLS matches: {e}")
        return render_template('admin_panel/mls/matches_flowbite.html',
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


@admin_panel_bp.route('/mls/create', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def mls_create_match():
    """Manually create a new match (for non-ESPN competitions like friendlies)."""
    session = g.db_session

    try:
        import re

        def simple_slugify(text, max_length=30):
            """Simple slugify function - converts text to lowercase with hyphens."""
            text = str(text).lower().strip()
            text = re.sub(r'[^\w\s-]', '', text)
            text = re.sub(r'[\s_-]+', '-', text)
            text = re.sub(r'^-+|-+$', '', text)
            return text[:max_length]

        data = request.get_json() or {}

        # Validate required fields
        if not data.get('opponent'):
            return jsonify({'success': False, 'error': 'Opponent name is required'}), 400
        if not data.get('date_time'):
            return jsonify({'success': False, 'error': 'Date/time is required'}), 400

        # Parse date/time
        try:
            match_date_time = datetime.fromisoformat(data['date_time'].replace('Z', '+00:00'))
            if match_date_time.tzinfo is None:
                match_date_time = pytz.UTC.localize(match_date_time)
        except ValueError as e:
            return jsonify({'success': False, 'error': f'Invalid date format: {e}'}), 400

        # Generate unique match_id for manual matches
        opponent_slug = simple_slugify(data['opponent'], max_length=30)
        timestamp = int(match_date_time.timestamp())
        match_id = f"manual_{timestamp}_{opponent_slug}"

        # Check if match_id already exists
        existing = session.query(MLSMatch).filter_by(match_id=match_id).first()
        if existing:
            return jsonify({'success': False, 'error': 'A match with this opponent at this time already exists'}), 400

        # Get optional fields
        is_home_game = data.get('is_home_game', True)
        venue = data.get('venue', '')
        competition = data.get('competition', 'usa.1')

        # Create the match
        new_match = MLSMatch(
            match_id=match_id,
            opponent=data['opponent'],
            date_time=match_date_time,
            is_home_game=is_home_game,
            venue=venue,
            competition=competition,
            thread_created=False,
            live_reporting_status=MatchStatus.PENDING
        )

        session.add(new_match)
        session.commit()

        # Auto-schedule tasks if requested (default: true)
        auto_schedule = data.get('auto_schedule', True)
        tasks_scheduled = False

        if auto_schedule and match_date_time > datetime.now(pytz.UTC):
            try:
                from app.match_scheduler import MatchScheduler
                scheduler = MatchScheduler()
                scheduler.schedule_match_tasks(new_match.id, force=False)
                tasks_scheduled = True
            except Exception as sched_e:
                logger.error(f"Error scheduling tasks for new match: {sched_e}")

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='mls_match_create',
            resource_type='mls_match',
            resource_id=str(new_match.id),
            new_value=f'Created manual match vs {data["opponent"]} at {match_date_time}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        home_team = 'Seattle Sounders FC' if is_home_game else data['opponent']
        away_team = data['opponent'] if is_home_game else 'Seattle Sounders FC'

        return jsonify({
            'success': True,
            'message': f'Match {home_team} vs {away_team} created',
            'match_id': new_match.id,
            'espn_match_id': match_id,
            'tasks_scheduled': tasks_scheduled
        })

    except Exception as e:
        logger.error(f"Error creating manual match: {e}")
        session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/mls/edit/<int:match_id>', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def mls_edit_match(match_id):
    """Edit an existing match's details (date/time, venue, competition)."""
    session = g.db_session

    match = session.query(MLSMatch).get(match_id)
    if not match:
        return jsonify({'success': False, 'error': 'Match not found'}), 404

    try:
        data = request.get_json() or {}

        old_date_time = match.date_time
        changes_made = []

        # Update date/time if provided
        if 'date_time' in data and data['date_time']:
            try:
                new_date_time = datetime.fromisoformat(data['date_time'].replace('Z', '+00:00'))
                if new_date_time.tzinfo is None:
                    new_date_time = pytz.UTC.localize(new_date_time)
                match.date_time = new_date_time
                changes_made.append(f"Date/time: {old_date_time} → {new_date_time}")
            except ValueError as e:
                return jsonify({'success': False, 'error': f'Invalid date format: {e}'}), 400

        # Update venue if provided
        if 'venue' in data:
            old_venue = match.venue
            match.venue = data['venue'] or None
            if old_venue != match.venue:
                changes_made.append(f"Venue: {old_venue} → {match.venue}")

        # Update competition if provided
        if 'competition' in data:
            old_competition = match.competition
            match.competition = data['competition'] or 'usa.1'
            if old_competition != match.competition:
                changes_made.append(f"Competition: {old_competition} → {match.competition}")

        # Update opponent if provided (for manual matches)
        if 'opponent' in data and data['opponent']:
            old_opponent = match.opponent
            match.opponent = data['opponent']
            if old_opponent != match.opponent:
                changes_made.append(f"Opponent: {old_opponent} → {match.opponent}")

        # Update home/away if provided
        if 'is_home_game' in data:
            old_is_home = match.is_home_game
            match.is_home_game = bool(data['is_home_game'])
            if old_is_home != match.is_home_game:
                changes_made.append(f"Home game: {old_is_home} → {match.is_home_game}")

        session.commit()

        # Reschedule tasks if date/time changed and not already past
        tasks_rescheduled = False
        if old_date_time != match.date_time and match.date_time > datetime.now(pytz.UTC):
            try:
                from app.models import ScheduledTask, TaskType, TaskState
                from app.models.admin_config import AdminConfig
                from app.core import celery
                from app.tasks.match_scheduler import create_mls_match_thread_task, start_mls_live_reporting_task

                # Get configurable timing
                thread_creation_hours = AdminConfig.get_setting('mls_thread_creation_hours_before', 48)
                live_reporting_minutes = AdminConfig.get_setting('mls_live_reporting_minutes_before', 5)

                now = datetime.now(pytz.UTC)
                match_dt = match.date_time
                if match_dt.tzinfo is None:
                    match_dt = pytz.UTC.localize(match_dt)

                # Reschedule thread creation task
                thread_time = match_dt - timedelta(hours=thread_creation_hours)
                thread_task = ScheduledTask.find_existing_task(session, match.id, TaskType.THREAD_CREATION)

                if thread_task and thread_task.state == TaskState.SCHEDULED:
                    # Revoke old task
                    try:
                        celery.control.revoke(thread_task.celery_task_id, terminate=True)
                    except Exception:
                        pass

                    # Create new scheduled task
                    if thread_time > now and not match.thread_created:
                        new_celery_task = create_mls_match_thread_task.apply_async(
                            args=[match.id],
                            eta=thread_time,
                            expires=thread_time + timedelta(hours=2)
                        )
                        thread_task.celery_task_id = new_celery_task.id
                        thread_task.scheduled_time = thread_time
                        changes_made.append(f"Thread task rescheduled for {thread_time}")
                        tasks_rescheduled = True

                # Reschedule live reporting task
                live_start_time = match_dt - timedelta(minutes=live_reporting_minutes)
                reporting_task = ScheduledTask.find_existing_task(session, match.id, TaskType.LIVE_REPORTING_START)

                if reporting_task and reporting_task.state == TaskState.SCHEDULED:
                    # Revoke old task
                    try:
                        celery.control.revoke(reporting_task.celery_task_id, terminate=True)
                    except Exception:
                        pass

                    # Create new scheduled task
                    if live_start_time > now:
                        new_celery_task = start_mls_live_reporting_task.apply_async(
                            args=[match.id],
                            eta=live_start_time,
                            expires=live_start_time + timedelta(minutes=30)
                        )
                        reporting_task.celery_task_id = new_celery_task.id
                        reporting_task.scheduled_time = live_start_time
                        changes_made.append(f"Live reporting task rescheduled for {live_start_time}")
                        tasks_rescheduled = True

                session.commit()

            except Exception as e:
                logger.error(f"Error rescheduling tasks for match {match_id}: {e}")
                # Don't fail the edit, just note the error
                changes_made.append(f"Warning: Could not reschedule tasks: {e}")

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='mls_match_edit',
            resource_type='mls_match',
            resource_id=str(match_id),
            old_value=str({'date_time': str(old_date_time)}),
            new_value=str({'changes': changes_made}),
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        home_team = 'Seattle Sounders FC' if match.is_home_game else match.opponent
        away_team = match.opponent if match.is_home_game else 'Seattle Sounders FC'

        return jsonify({
            'success': True,
            'message': f'Match {home_team} vs {away_team} updated',
            'changes': changes_made,
            'tasks_rescheduled': tasks_rescheduled
        })

    except Exception as e:
        logger.error(f"Error editing match {match_id}: {e}")
        session.rollback()
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
        'admin_panel/mls/task_monitoring_flowbite.html',
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


@admin_panel_bp.route('/mls/task/<int:task_id>/pause', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def task_pause(task_id):
    """Pause a scheduled task by revoking its Celery task."""
    from app.models import ScheduledTask, TaskState
    from app.celery_config import celery

    session = g.db_session

    try:
        task = session.query(ScheduledTask).get(task_id)
        if not task:
            return jsonify({'success': False, 'error': 'Task not found'}), 404

        # Only scheduled tasks can be paused
        if task.state != TaskState.SCHEDULED.value:
            return jsonify({
                'success': False,
                'error': f'Cannot pause task in state: {task.state}. Only scheduled tasks can be paused.'
            }), 400

        # Revoke the Celery task if it exists
        if task.celery_task_id:
            try:
                celery.control.revoke(task.celery_task_id, terminate=False)
                logger.info(f"Revoked Celery task {task.celery_task_id} for pausing")
            except Exception as revoke_error:
                logger.warning(f"Could not revoke Celery task {task.celery_task_id}: {revoke_error}")

        # Mark task as paused (stores original celery_task_id)
        task.mark_paused()
        session.commit()

        # Log action
        AdminAuditLog.log_action(
            session,
            current_user.id,
            'task_pause',
            f"Paused task {task_id} for match {task.match_id}",
            {'task_id': task_id, 'task_type': task.task_type, 'match_id': task.match_id}
        )

        logger.info(f"Task {task_id} paused by {current_user.username}")

        return jsonify({
            'success': True,
            'message': 'Task paused successfully'
        })

    except Exception as e:
        logger.error(f"Error pausing task {task_id}: {e}", exc_info=True)
        session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/mls/task/<int:task_id>/resume', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def task_resume(task_id):
    """Resume a paused task by rescheduling it with Celery."""
    from app.models import ScheduledTask, TaskState, TaskType
    from app.tasks.match_scheduler import (
        create_mls_match_thread_task,
        start_mls_live_reporting_task
    )

    session = g.db_session

    try:
        task = session.query(ScheduledTask).get(task_id)
        if not task:
            return jsonify({'success': False, 'error': 'Task not found'}), 404

        # Only paused tasks can be resumed
        if task.state != TaskState.PAUSED.value:
            return jsonify({
                'success': False,
                'error': f'Cannot resume task in state: {task.state}. Only paused tasks can be resumed.'
            }), 400

        now = datetime.now(pytz.UTC)
        scheduled_time = task.scheduled_time

        # Determine if scheduled time has passed
        if scheduled_time.tzinfo is None:
            scheduled_time = pytz.UTC.localize(scheduled_time)

        time_passed = now >= scheduled_time

        # Schedule the task based on type
        if task.task_type == TaskType.THREAD_CREATION.value:
            if time_passed:
                # Execute immediately
                celery_task = create_mls_match_thread_task.apply_async(args=[task.match_id])
            else:
                # Schedule for original time
                celery_task = create_mls_match_thread_task.apply_async(
                    args=[task.match_id],
                    eta=scheduled_time
                )
        elif task.task_type == TaskType.LIVE_REPORTING_START.value:
            if time_passed:
                # Execute immediately
                celery_task = start_mls_live_reporting_task.apply_async(args=[task.match_id])
            else:
                # Schedule for original time
                celery_task = start_mls_live_reporting_task.apply_async(
                    args=[task.match_id],
                    eta=scheduled_time
                )
        else:
            return jsonify({
                'success': False,
                'error': f'Unknown task type: {task.task_type}'
            }), 400

        # Mark task as resumed with new Celery task ID
        task.mark_resumed(celery_task.id)
        session.commit()

        # Build message based on timing
        if time_passed:
            message = f'Task resumed and executing immediately (scheduled time passed)'
        else:
            message = f'Task resumed and scheduled for {scheduled_time.strftime("%Y-%m-%d %H:%M %Z")}'

        # Log action
        AdminAuditLog.log_action(
            session,
            current_user.id,
            'task_resume',
            f"Resumed task {task_id} for match {task.match_id}",
            {
                'task_id': task_id,
                'task_type': task.task_type,
                'match_id': task.match_id,
                'immediate': time_passed,
                'new_celery_task_id': celery_task.id
            }
        )

        logger.info(f"Task {task_id} resumed by {current_user.username}, new Celery ID: {celery_task.id}")

        return jsonify({
            'success': True,
            'message': message,
            'celery_task_id': celery_task.id,
            'immediate': time_passed
        })

    except Exception as e:
        logger.error(f"Error resuming task {task_id}: {e}", exc_info=True)
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
                'last_update': live_session.last_update.isoformat() if live_session and live_session.last_update else None,
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


# -----------------------------------------------------------
# MLS Sync & Task Management Routes
# -----------------------------------------------------------

@admin_panel_bp.route('/mls/trigger-sync', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def mls_trigger_sync():
    """
    Trigger MLS data synchronization.

    This schedules a Celery task to fetch and update MLS match data from ESPN.
    """
    try:
        # Import the task for scheduling
        task_result = schedule_all_mls_threads_task.delay()

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='mls_trigger_sync',
            resource_type='mls',
            resource_id='sync',
            new_value=f'Triggered MLS sync task: {task_result.id}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        logger.info(f"MLS sync triggered by {current_user.username}, task_id: {task_result.id}")

        return jsonify({
            'success': True,
            'message': 'MLS synchronization task has been triggered',
            'task_id': task_result.id
        })

    except Exception as e:
        logger.error(f"Error triggering MLS sync: {e}")
        return jsonify({
            'success': False,
            'error': f'Failed to trigger MLS sync: {str(e)}'
        }), 500


@admin_panel_bp.route('/mls/cancel-task', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def mls_cancel_task():
    """
    Cancel an MLS task.

    Accepts JSON with 'task_id' field to identify the Celery task to cancel.
    """
    try:
        from app.core import celery

        data = request.get_json() or {}
        task_id = data.get('task_id')

        if not task_id:
            return jsonify({
                'success': False,
                'error': 'Task ID is required'
            }), 400

        # Attempt to revoke the task
        celery.control.revoke(task_id, terminate=True)

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='mls_task_cancel',
            resource_type='mls',
            resource_id=task_id,
            new_value=f'Cancelled task: {task_id}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        logger.info(f"MLS task {task_id} cancelled by {current_user.username}")

        return jsonify({
            'success': True,
            'message': f'Task {task_id} has been cancelled',
            'task_id': task_id
        })

    except Exception as e:
        logger.error(f"Error cancelling MLS task: {e}")
        return jsonify({
            'success': False,
            'error': f'Failed to cancel task: {str(e)}'
        }), 500


# -----------------------------------------------------------
# MLS Settings Routes
# -----------------------------------------------------------

@admin_panel_bp.route('/mls/settings')
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def mls_settings():
    """MLS settings configuration page."""
    from app.models.admin_config import AdminConfig

    session = g.db_session

    # Get all MLS-related settings
    settings = {
        'thread_creation_hours_before': AdminConfig.get_value(
            session, 'mls_thread_creation_hours_before', '48'
        ),
        'live_reporting_minutes_before': AdminConfig.get_value(
            session, 'mls_live_reporting_minutes_before', '5'
        ),
        'live_reporting_timeout_hours': AdminConfig.get_value(
            session, 'mls_live_reporting_timeout_hours', '3'
        ),
        'max_session_duration_hours': AdminConfig.get_value(
            session, 'mls_max_session_duration_hours', '4'
        ),
        'no_update_timeout_minutes': AdminConfig.get_value(
            session, 'mls_no_update_timeout_minutes', '30'
        )
    }

    return render_template(
        'admin_panel/mls/settings_flowbite.html',
        settings=settings,
        competition_mappings=COMPETITION_MAPPINGS
    )


@admin_panel_bp.route('/mls/settings/update', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def mls_settings_update():
    """Update MLS configuration settings."""
    from app.models.admin_config import AdminConfig

    session = g.db_session

    try:
        data = request.get_json() or {}

        # Define valid settings and their validation rules
        valid_settings = {
            'mls_thread_creation_hours_before': {'min': 1, 'max': 168, 'type': 'integer'},  # 1h to 7 days
            'mls_live_reporting_minutes_before': {'min': 0, 'max': 60, 'type': 'integer'},  # 0 to 60 min
            'mls_live_reporting_timeout_hours': {'min': 1, 'max': 6, 'type': 'integer'},    # 1 to 6 hours
            'mls_max_session_duration_hours': {'min': 2, 'max': 8, 'type': 'integer'},      # 2 to 8 hours
            'mls_no_update_timeout_minutes': {'min': 10, 'max': 120, 'type': 'integer'}     # 10 to 120 min
        }

        updated_settings = []
        errors = []

        for key, value in data.items():
            if key not in valid_settings:
                errors.append(f"Unknown setting: {key}")
                continue

            rules = valid_settings[key]

            # Type validation
            try:
                if rules['type'] == 'integer':
                    value = int(value)
            except (ValueError, TypeError):
                errors.append(f"Invalid value for {key}: must be a number")
                continue

            # Range validation
            if value < rules['min'] or value > rules['max']:
                errors.append(f"Invalid value for {key}: must be between {rules['min']} and {rules['max']}")
                continue

            # Update the setting
            AdminConfig.set_value(session, key, str(value), category='mls', data_type='integer')
            updated_settings.append(key)

        if errors and not updated_settings:
            return jsonify({
                'success': False,
                'error': '; '.join(errors)
            }), 400

        session.commit()

        # Log action
        AdminAuditLog.log_action(
            session,
            current_user.id,
            'mls_settings_update',
            f"Updated MLS settings: {', '.join(updated_settings)}",
            {'settings': data, 'updated': updated_settings, 'errors': errors}
        )

        logger.info(f"MLS settings updated by {current_user.username}: {updated_settings}")

        message = f"Updated {len(updated_settings)} setting(s)"
        if errors:
            message += f" ({len(errors)} error(s))"

        return jsonify({
            'success': True,
            'message': message,
            'updated': updated_settings,
            'errors': errors
        })

    except Exception as e:
        logger.error(f"Error updating MLS settings: {e}", exc_info=True)
        session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


# -----------------------------------------------------------
# Session Management Routes
# -----------------------------------------------------------

@admin_panel_bp.route('/mls/sessions')
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def mls_sessions():
    """List live reporting sessions with status filter."""
    from app.models import LiveReportingSession
    from app.utils.task_session_manager import task_session

    status_filter = request.args.get('status', 'all')

    try:
        with task_session() as session:
            query = session.query(LiveReportingSession)

            if status_filter == 'active':
                query = query.filter_by(is_active=True)
            elif status_filter == 'inactive':
                query = query.filter_by(is_active=False)

            sessions_list = query.order_by(LiveReportingSession.started_at.desc()).limit(50).all()

            return render_template(
                'admin_panel/mls/sessions_flowbite.html',
                sessions=sessions_list,
                status_filter=status_filter
            )

    except Exception as e:
        logger.error(f"Error loading sessions: {e}", exc_info=True)
        return render_template('admin_panel/500_flowbite.html', error=str(e)), 500


@admin_panel_bp.route('/mls/api/session/<int:session_id>/stop', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def mls_stop_session(session_id):
    """Stop an active live reporting session."""
    from app.models import LiveReportingSession
    from app.services.realtime_bridge_service import notify_session_stopped
    from app.utils.task_session_manager import task_session

    try:
        with task_session() as session:
            live_session = session.query(LiveReportingSession).filter_by(id=session_id).first()
            if not live_session:
                return jsonify({'success': False, 'error': 'Session not found'}), 404

            if not live_session.is_active:
                return jsonify({'success': False, 'error': 'Session is not active'}), 400

            live_session.is_active = False
            live_session.ended_at = datetime.utcnow()
            session.commit()

            notify_session_stopped(live_session.id, live_session.match_id, "Manual stop via admin panel")

            AdminAuditLog.log_action(
                session,
                current_user.id,
                'mls_session_stop',
                f"Stopped live reporting session {session_id} for match {live_session.match_id}",
                {'session_id': session_id, 'match_id': live_session.match_id}
            )

            return jsonify({
                'success': True,
                'message': f'Stopped session {session_id}',
                'session_id': session_id
            })

    except Exception as e:
        logger.error(f"Error stopping session {session_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


# -----------------------------------------------------------
# Service Control Routes
# -----------------------------------------------------------

@admin_panel_bp.route('/mls/api/force-sync', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def mls_force_sync():
    """Force synchronization between database and real-time service."""
    try:
        result = realtime_bridge.force_session_sync()
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error forcing sync: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/mls/api/send-command', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def mls_send_command():
    """Send commands to real-time service."""
    try:
        data = request.get_json()
        command = data.get('command')
        params = data.get('params', {})

        if not command:
            return jsonify({'success': False, 'error': 'Command is required'}), 400

        result = realtime_bridge.send_realtime_command(command, params)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error sending command: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/mls/api/health')
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def mls_api_health():
    """API endpoint for health status."""
    try:
        health = check_realtime_health()
        return jsonify(health)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_panel_bp.route('/mls/api/coordination')
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def mls_api_coordination():
    """API endpoint for coordination status."""
    try:
        status = get_coordination_status()
        return jsonify(status)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
