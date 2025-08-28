# app/admin/mls_routes.py

"""
MLS Match Management Routes

This module contains routes for MLS match scheduling, thread creation,
and live reporting management.
"""

import logging
from datetime import datetime, timedelta
from flask import render_template, request, jsonify, redirect, url_for, g
from flask_login import login_required
from app.decorators import role_required
from app.models import MLSMatch
from app.alert_helpers import show_success, show_error, show_warning
from app.tasks.tasks_live_reporting import (
    force_create_mls_thread_task,
    schedule_all_mls_threads_task,
    schedule_mls_thread_task
)
from app.utils.task_monitor import get_task_info

logger = logging.getLogger(__name__)

# Import the shared admin blueprint
from app.admin.blueprint import admin_bp


# -----------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------

def get_status_color(status):
    """Returns Bootstrap color class for match status."""
    status_colors = {
        'UNKNOWN': 'secondary',
        'SCHEDULED': 'info',
        'LIVE': 'warning',
        'FINISHED': 'success',
        'POSTPONED': 'dark',
        'CANCELLED': 'danger'
    }
    return status_colors.get(status, 'secondary')


def get_status_icon(status):
    """Returns FontAwesome icon class for match status."""
    status_icons = {
        'UNKNOWN': 'fas fa-question',
        'SCHEDULED': 'fas fa-clock',
        'LIVE': 'fas fa-play',
        'FINISHED': 'fas fa-check',
        'POSTPONED': 'fas fa-pause',
        'CANCELLED': 'fas fa-times'
    }
    return status_icons.get(status, 'fas fa-question')


def get_status_display(status):
    """Returns human-readable status text."""
    status_display = {
        'UNKNOWN': 'Unknown',
        'SCHEDULED': 'Scheduled',
        'LIVE': 'Live',
        'FINISHED': 'Finished',
        'POSTPONED': 'Postponed',
        'CANCELLED': 'Cancelled'
    }
    return status_display.get(status, 'Unknown')


def get_match_task_details(match_id):
    """Get task details for a specific match from Redis scheduler keys."""
    try:
        from app.utils.safe_redis import get_safe_redis
        import json
        
        redis_client = get_safe_redis()
        
        # Check Redis keys for scheduled tasks (this is more reliable than Celery inspect)
        thread_key = f"match_scheduler:{match_id}:thread"
        reporting_key = f"match_scheduler:{match_id}:reporting"
        
        task_details = []
        
        # Check for thread creation task
        if redis_client.exists(thread_key):
            thread_data = redis_client.get(thread_key)
            if thread_data:
                try:
                    thread_info = json.loads(thread_data.decode('utf-8'))
                    ttl = redis_client.ttl(thread_key)
                    task_details.append({
                        'type': 'Thread Creation',
                        'task_id': thread_info.get('task_id'),
                        'eta': thread_info.get('eta'),
                        'ttl_seconds': ttl
                    })
                except (json.JSONDecodeError, AttributeError):
                    # Handle legacy format where task_id was stored directly
                    task_details.append({
                        'type': 'Thread Creation',
                        'task_id': thread_data.decode('utf-8') if isinstance(thread_data, bytes) else str(thread_data),
                        'eta': 'Unknown',
                        'ttl_seconds': redis_client.ttl(thread_key)
                    })
        
        # Check for live reporting task
        if redis_client.exists(reporting_key):
            reporting_data = redis_client.get(reporting_key)
            if reporting_data:
                try:
                    reporting_info = json.loads(reporting_data.decode('utf-8'))
                    ttl = redis_client.ttl(reporting_key)
                    task_details.append({
                        'type': 'Live Reporting',
                        'task_id': reporting_info.get('task_id'),
                        'eta': reporting_info.get('eta'),
                        'ttl_seconds': ttl
                    })
                except (json.JSONDecodeError, AttributeError):
                    # Handle legacy format where task_id was stored directly
                    task_details.append({
                        'type': 'Live Reporting',
                        'task_id': reporting_data.decode('utf-8') if isinstance(reporting_data, bytes) else str(reporting_data),
                        'eta': 'Unknown',
                        'ttl_seconds': redis_client.ttl(reporting_key)
                    })
        
        # Also check the database for any running live reporting task
        session = g.db_session
        match = session.query(MLSMatch).get(match_id)
        if match and match.live_reporting_task_id and match.live_reporting_status == 'running':
            task_details.append({
                'type': 'Live Reporting (Active)',
                'task_id': match.live_reporting_task_id,
                'eta': 'Running',
                'ttl_seconds': None
            })
        
        # Format the response with active and scheduled tasks for the frontend
        active_tasks = []
        scheduled_tasks = []
        
        for task in task_details:
            if task.get('ttl_seconds', 0) > 0:  # Task is still scheduled
                scheduled_tasks.append({
                    'task_id': task.get('task_id'),
                    'name': task.get('type'),
                    'eta': task.get('eta'),
                    'ttl': task.get('ttl_seconds')
                })
        
        if task_details:
            return {
                'status': 'SCHEDULED',
                'message': f'{len(task_details)} scheduled task(s) found',
                'active_tasks': active_tasks,
                'scheduled_tasks': scheduled_tasks,
                'tasks': task_details  # Keep backward compatibility
            }
        else:
            return {
                'status': 'NOT_FOUND',
                'message': 'No scheduled tasks found',
                'active_tasks': [],
                'scheduled_tasks': []
            }
            
    except Exception as e:
        logger.error(f"Error getting match task details from Redis: {str(e)}")
        return {'status': 'ERROR', 'error': str(e)}


# -----------------------------------------------------------
# MLS Match Management Routes
# -----------------------------------------------------------

@admin_bp.route('/admin/mls_matches', endpoint='view_mls_matches')
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def view_mls_matches():
    """
    View MLS matches (DEPRECATED - Use /admin/match_management instead).
    """
    session = g.db_session
    matches = session.query(MLSMatch).order_by(MLSMatch.date_time).all()
    
    # Add status colors and icons for display
    for match in matches:
        match.status_color = get_status_color(match.live_reporting_status)
        match.status_icon = get_status_icon(match.live_reporting_status)
        match.status_display = get_status_display(match.live_reporting_status)
    
    return render_template('admin/mls_matches.html', matches=matches, title='MLS Matches (DEPRECATED)')


@admin_bp.route('/admin/match_management', endpoint='match_management')
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def match_management():
    """
    Unified match management dashboard.
    
    Provides comprehensive match management including MLS match scheduling,
    Discord thread creation, live reporting controls, and task monitoring.
    """
    session = g.db_session
    
    # Get matches with smart categorization for better UX
    import pytz
    now = datetime.now(pytz.UTC)
    
    # Define time ranges
    recent_cutoff = now - timedelta(days=3)    # Show last 3 days by default
    future_cutoff = now + timedelta(days=60)   # Show next 60 days
    historical_cutoff = now - timedelta(days=30)  # Historical matches up to 30 days ago
    
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
        # Skip slow task details during initial load - will be loaded via AJAX
        match.task_details = {'status': 'LOADING'}
    
    # Add enhanced data for historical matches (lighter processing)
    for match in historical_matches:
        match.status_color = get_status_color(match.live_reporting_status)
        match.status_icon = get_status_icon(match.live_reporting_status)
        match.status_display = get_status_display(match.live_reporting_status)
        # Historical matches get minimal task details to reduce load
        match.task_details = {'status': 'HISTORICAL'}
    
    return render_template(
        'admin/match_management.html', 
        matches=visible_matches,
        historical_matches=historical_matches,
        historical_count=len(historical_matches),
        title='Match Management', 
        current_time=datetime.utcnow(), 
        timedelta=timedelta
    )


@admin_bp.route('/admin/match_management/match-tasks/<int:match_id>', endpoint='get_match_tasks', methods=['GET'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def get_match_tasks(match_id):
    """Get detailed task information for a specific match."""
    try:
        # Use the shared enhanced task status function with cache-first approach
        from app.utils.task_status_helper import get_enhanced_match_task_status
        
        result = get_enhanced_match_task_status(match_id, use_cache=True)
        response = jsonify(result)
        # Cache for 60 seconds to reduce load
        response.headers['Cache-Control'] = 'max-age=60, public'
        return response
        
    except Exception as e:
        logger.error(f"Error getting match tasks for {match_id}: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e),
            'match_id': match_id
        }), 500


@admin_bp.route('/admin/match_management/system-health', endpoint='system_health', methods=['GET'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def get_system_health():
    """Get comprehensive system health metrics for monitoring."""
    try:
        from app.utils.task_status_helper import get_task_status_metrics
        
        metrics = get_task_status_metrics()
        
        # Add database connection pool info
        try:
            from app.core import db
            engine = db.engine
            pool = engine.pool
            
            metrics['database_pool'] = {
                'pool_size': pool.size(),
                'checked_in': pool.checkedin(),
                'checked_out': pool.checkedout(),
                'overflow': pool.overflow(),
                'invalidated': pool.invalid(),
                'healthy': pool.checkedout() < pool.size() + pool.overflow()
            }
        except Exception as e:
            metrics['database_pool'] = {'error': str(e), 'healthy': False}
        
        # Overall system health
        metrics['system_healthy'] = (
            metrics['healthy'] and 
            metrics['database_pool'].get('healthy', False)
        )
        
        response = jsonify(metrics)
        response.headers['Cache-Control'] = 'no-cache'
        return response
        
    except Exception as e:
        logger.error(f"Error getting system health: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e),
            'system_healthy': False
        }), 500


@admin_bp.route('/admin/match_management/revoke-task', endpoint='revoke_match_task', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def revoke_match_task():
    """Revoke a specific task for a match."""
    try:
        data = request.get_json()
        task_id = data.get('task_id')
        match_id = data.get('match_id')
        task_type = data.get('task_type')  # 'thread' or 'reporting'
        
        if not task_id or not match_id:
            return jsonify({
                'success': False,
                'error': 'task_id and match_id are required'
            }), 400
        
        # Revoke the Celery task
        from celery.result import AsyncResult
        from app.core import celery
        
        task_result = AsyncResult(task_id)
        task_result.revoke(terminate=True)
        
        # Remove from Redis scheduler
        from app.utils.safe_redis import get_safe_redis
        redis_client = get_safe_redis()
        
        if redis_client and hasattr(redis_client, 'is_available') and redis_client.is_available:
            redis_key = f"match_scheduler:{match_id}:{task_type}"
            redis_client.delete(redis_key)
        
        logger.info(f"Revoked task {task_id} for match {match_id} ({task_type})")
        
        return jsonify({
            'success': True,
            'message': f'Task {task_id} has been revoked',
            'task_id': task_id
        })
        
    except Exception as e:
        logger.error(f"Error revoking task: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@admin_bp.route('/admin/match_management/redis-test', endpoint='redis_test', methods=['GET'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def redis_test():
    """Test Redis connection directly."""
    try:
        import redis
        # Test direct connection
        r = redis.Redis(host='redis', port=6379, db=0, decode_responses=True)
        ping_result = r.ping()
        
        # Test safe Redis
        from app.utils.safe_redis import get_safe_redis, reset_safe_redis
        reset_safe_redis()
        safe_client = get_safe_redis()
        
        return jsonify({
            'success': True,
            'direct_redis_ping': ping_result,
            'safe_redis_available': safe_client.is_available if safe_client else False,
            'queue_lengths': {
                'live_reporting': r.llen('live_reporting'),
                'discord': r.llen('discord'), 
                'celery': r.llen('celery'),
                'player_sync': r.llen('player_sync')
            }
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@admin_bp.route('/admin/match_management/statuses', endpoint='get_match_statuses', methods=['GET'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def get_match_statuses():
    """Get match statuses for AJAX updates."""
    session = g.db_session
    
    try:
        # Only get matches from last 7 days and next 30 days to avoid checking old matches
        from datetime import datetime, timedelta
        import pytz
        
        # Use timezone-aware datetime to match database format
        now = datetime.now(pytz.UTC)
        cutoff_start = now - timedelta(days=7)
        cutoff_end = now + timedelta(days=30)
        
        matches = session.query(MLSMatch).filter(
            MLSMatch.date_time >= cutoff_start,
            MLSMatch.date_time <= cutoff_end
        ).all()
        
        statuses = []
        
        for match in matches:
            # Only get task details for matches that might have active tasks
            task_window_start = now - timedelta(hours=6)
            task_window_end = now + timedelta(days=7)
            
            if (match.date_time >= task_window_start and 
                match.date_time <= task_window_end):
                task_details = get_match_task_details(match.id)
            else:
                # For older/far future matches, don't check task status
                task_details = {'status': 'NOT_FOUND'}
            
            statuses.append({
                'id': match.id,
                'status': match.live_reporting_status,
                'status_color': get_status_color(match.live_reporting_status),
                'status_icon': get_status_icon(match.live_reporting_status),
                'status_display': get_status_display(match.live_reporting_status),
                'task_details': task_details
            })
        
        return jsonify({'statuses': statuses})
    except Exception as e:
        logger.error(f"Error getting match statuses: {str(e)}")
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/admin/match_management/schedule/<int:match_id>', endpoint='schedule_match_task', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def schedule_match_task(match_id):
    """Schedule match tasks (thread creation and live reporting)."""
    session = g.db_session
    
    match = session.query(MLSMatch).get(match_id)
    if not match:
        return jsonify({'success': False, 'error': 'Match not found'}), 404
    
    try:
        # Schedule the match thread task
        task_result = schedule_mls_thread_task.delay(match_id)
        
        home_team = 'FC Cincinnati' if match.is_home_game else match.opponent
        away_team = match.opponent if match.is_home_game else 'FC Cincinnati'
        return jsonify({
            'success': True,
            'message': f'Match thread scheduled for {home_team} vs {away_team}',
            'task_id': task_result.id
        })
    except Exception as e:
        logger.error(f"Error scheduling match task: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/admin/match_management/create-thread/<int:match_id>', endpoint='create_match_thread', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def create_match_thread(match_id):
    """Create thread immediately for a match."""
    session = g.db_session
    
    match = session.query(MLSMatch).get(match_id)
    if not match:
        return jsonify({'success': False, 'error': 'Match not found'}), 404
    
    try:
        # Force create the thread immediately
        task_result = force_create_mls_thread_task.delay(match_id)
        
        home_team = 'FC Cincinnati' if match.is_home_game else match.opponent
        away_team = match.opponent if match.is_home_game else 'FC Cincinnati'
        return jsonify({
            'success': True,
            'message': f'Thread creation initiated for {home_team} vs {away_team}',
            'task_id': task_result.id
        })
    except Exception as e:
        logger.error(f"Error creating match thread: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/admin/match_management/start-reporting/<int:match_id>', endpoint='start_match_reporting', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def start_match_reporting(match_id):
    """Start live reporting for a match immediately or schedule it."""
    session = g.db_session
    
    match = session.query(MLSMatch).get(match_id)
    if not match:
        return jsonify({'success': False, 'error': 'Match not found'}), 404
    
    try:
        try:
            from app.tasks.tasks_live_reporting_v2 import start_live_reporting_v2
            v2_available = True
        except ImportError:
            # No fallback system - V2 is the only live reporting system
            v2_available = False
        
        # Check if already running
        if match.live_reporting_status == 'running':
            return jsonify({'success': False, 'error': 'Live reporting already running'}), 400
        
        # Start live reporting immediately (V2 if available, otherwise robust)
        if v2_available:
            logger.info(f"🚀 [ADMIN] Starting V2 live reporting for match {match.match_id} in thread {match.discord_thread_id}")
            task_result = start_live_reporting_v2.delay(
                str(match.match_id),
                str(match.discord_thread_id),
                match.competition or 'usa.1'
            )
            reporting_type = "V2"
        else:
            logger.error(f"❌ [ADMIN] V2 not available, cannot start live reporting for match {match.match_id}")
            return jsonify({
                'success': False, 
                'error': 'V2 live reporting system not available'
            }), 500
        
        # Update match status
        match.live_reporting_status = 'scheduled'
        match.live_reporting_task_id = task_result.id
        match.live_reporting_scheduled = True
        session.commit()
        
        home_team = 'FC Cincinnati' if match.is_home_game else match.opponent
        away_team = match.opponent if match.is_home_game else 'FC Cincinnati'
        return jsonify({
            'success': True,
            'message': f'Live reporting started for {home_team} vs {away_team}',
            'task_id': task_result.id
        })
    except Exception as e:
        logger.error(f"Error starting live reporting: {str(e)}")
        session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/admin/match_management/stop-reporting/<int:match_id>', endpoint='stop_match_reporting', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def stop_match_reporting(match_id):
    """Stop live reporting for a match and revoke associated tasks."""
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
                logger.warning(f"Could not revoke active task {match.live_reporting_task_id}: {str(e)}")
        
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
                    # Handle legacy format
                    task_id = reporting_data.decode('utf-8') if isinstance(reporting_data, bytes) else str(reporting_data)
                    celery.control.revoke(task_id, terminate=True)
                    revoked_tasks.append(f"Scheduled task: {task_id}")
                
                # Remove the Redis key
                redis_client.delete(reporting_key)
        
        # Update match status
        match.live_reporting_started = False
        match.live_reporting_status = 'stopped'
        match.live_reporting_scheduled = False
        session.commit()
        
        home_team = 'FC Cincinnati' if match.is_home_game else match.opponent
        away_team = match.opponent if match.is_home_game else 'FC Cincinnati'
        
        message = f'Live reporting stopped for {home_team} vs {away_team}'
        if revoked_tasks:
            message += f'. Revoked tasks: {", ".join(revoked_tasks)}'
        
        return jsonify({
            'success': True,
            'message': message,
            'revoked_tasks': revoked_tasks
        })
    except Exception as e:
        logger.error(f"Error stopping live reporting: {str(e)}")
        session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/admin/match_management/task-details/<task_id>', endpoint='get_match_task_details', methods=['GET'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def get_match_task_details_route(task_id):
    """Get detailed information about a specific task."""
    try:
        task_info = get_task_info(task_id)
        return jsonify(task_info)
    except Exception as e:
        logger.error(f"Error getting task details: {str(e)}")
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/admin/match_management/schedule-all', endpoint='schedule_all_matches', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def schedule_all_matches():
    """Schedule all upcoming matches."""
    try:
        task_result = schedule_all_mls_threads_task.delay()
        
        return jsonify({
            'success': True,
            'message': 'All match scheduling initiated',
            'task_id': task_result.id
        })
    except Exception as e:
        logger.error(f"Error scheduling all matches: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/admin/match_management/add-by-date', endpoint='add_match_by_date', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def add_match_by_date():
    """Add a match by date from ESPN."""
    try:
        match_date = request.form.get('date')
        competition = request.form.get('competition', 'MLS')  # Default to MLS
        
        if not match_date:
            return jsonify({'success': False, 'error': 'Match date is required'}), 400
        
        # Import ESPN integration modules
        from app.api_utils import async_to_sync, extract_match_details
        from app.services.espn_service import get_espn_service
        from app.db_utils import insert_mls_match
        from app.bot_admin import COMPETITION_MAPPINGS, ensure_utc
        
        # Debug logging to understand the mapping
        logger.info(f"Received competition from form: '{competition}'")
        logger.info(f"Available mappings: {COMPETITION_MAPPINGS}")
        
        # Map competition name to code
        competition_code = COMPETITION_MAPPINGS.get(competition, 'usa.1')  # Default to MLS
        
        logger.info(f"Mapped competition '{competition}' to code: '{competition_code}'")
        
        # Format date for ESPN API
        date_only = match_date.split(" ")[0]
        formatted_date = datetime.strptime(date_only, "%Y-%m-%d").strftime("%Y%m%d")
        
        logger.info(f"Fetching match data from ESPN for {match_date} in {competition} (code: {competition_code})")
        
        # Fetch match data from ESPN using centralized service
        espn_service = get_espn_service()
        match_data = async_to_sync(espn_service.get_scoreboard(competition_code, formatted_date))
        
        if not match_data or 'events' not in match_data:
            return jsonify({
                'success': False,
                'error': f'No events found for {match_date} in {competition}'
            })
        
        session = g.db_session
        
        # Look for Seattle Sounders match
        matches_found = 0
        for event in match_data['events']:
            if 'Seattle Sounders FC' in event.get("name", ""):
                try:
                    match_details = extract_match_details(event)
                    # extract_match_details already converts to UTC, no need for ensure_utc()
                    
                    # Check if match already exists
                    existing_match = session.query(MLSMatch).filter_by(
                        match_id=match_details['match_id']
                    ).first()
                    
                    if existing_match:
                        return jsonify({
                            'success': False,
                            'error': f'Match against {match_details["opponent"]} already exists'
                        })
                    
                    # Insert new match
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
                    
                    # Commit to get the database ID
                    session.commit()
                    
                    if match:
                        matches_found += 1
                        logger.info(f"Successfully added match: {match_details['opponent']} on {match_date}")
                        
                        # Automatically schedule tasks for the new match
                        try:
                            from app.match_scheduler import MatchScheduler
                            scheduler = MatchScheduler()
                            scheduling_result = scheduler.schedule_match_tasks(match.id, force=False)
                            
                            if scheduling_result.get('success'):
                                logger.info(f"Successfully scheduled tasks for match {match.id}: {scheduling_result.get('tasks_scheduled', [])}")
                            else:
                                logger.warning(f"Failed to schedule tasks for match {match.id}: {scheduling_result.get('message')}")
                        except Exception as sched_e:
                            logger.error(f"Error scheduling tasks for match {match.id}: {str(sched_e)}")
                            # Don't fail the match creation if scheduling fails
                    
                except Exception as e:
                    logger.error(f"Error processing match: {str(e)}")
                    continue
        
        if matches_found > 0:
            return jsonify({
                'success': True,
                'message': f'Successfully added {matches_found} match(es) for {match_date}'
            })
        else:
            return jsonify({
                'success': False,
                'error': f'No Seattle Sounders FC matches found for {match_date}'
            })
            
    except Exception as e:
        logger.error(f"Error adding match by date: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/admin/match_management/fetch-all-from-espn', endpoint='fetch_all_espn_matches', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def fetch_all_espn_matches():
    """Fetch all upcoming Seattle Sounders matches from ESPN."""
    try:
        # Import ESPN integration modules
        from app.api_utils import async_to_sync, extract_match_details
        from app.services.espn_service import get_espn_service
        from app.db_utils import insert_mls_match
        from app.bot_admin import COMPETITION_MAPPINGS, ensure_utc
        
        logger.info("Fetching all upcoming Seattle Sounders matches from ESPN")
        
        session = g.db_session
        total_matches_added = 0
        competitions_checked = []
        espn_service = get_espn_service()
        
        # Check multiple competitions for Seattle Sounders matches
        for competition_name, competition_code in COMPETITION_MAPPINGS.items():
            try:
                logger.info(f"Checking {competition_name} ({competition_code}) for matches")
                
                # Fetch team schedule (this gets all upcoming matches for the season)
                team_endpoint = f"sports/soccer/{competition_code}/teams/9726/schedule"
                team_data = async_to_sync(espn_service.fetch_data(endpoint=team_endpoint))
                
                if team_data and 'events' in team_data:
                    competitions_checked.append(competition_name)
                    matches_in_competition = 0
                    
                    for event in team_data['events']:
                        try:
                            # Only add future matches (not completed ones)
                            event_date = datetime.strptime(event['date'], "%Y-%m-%dT%H:%MZ")
                            if event_date < datetime.utcnow():
                                continue  # Skip past matches
                                
                            match_details = extract_match_details(event)
                            # extract_match_details already converts to UTC, no need for ensure_utc()
                            
                            # Check if match already exists
                            existing_match = session.query(MLSMatch).filter_by(
                                match_id=match_details['match_id']
                            ).first()
                            
                            if existing_match:
                                logger.debug(f"Match {match_details['match_id']} already exists, skipping")
                                continue
                            
                            # Insert new match
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
                            
                            # Commit to get the database ID
                            session.commit()
                            
                            if match:
                                matches_in_competition += 1
                                total_matches_added += 1
                                logger.info(f"Added match: {match_details['opponent']} ({competition_name})")
                                
                                # Automatically schedule tasks for the new match
                                try:
                                    from app.match_scheduler import MatchScheduler
                                    scheduler = MatchScheduler()
                                    scheduling_result = scheduler.schedule_match_tasks(match.id, force=False)
                                    
                                    if scheduling_result.get('success'):
                                        logger.info(f"Successfully scheduled tasks for match {match.id}: {scheduling_result.get('tasks_scheduled', [])}")
                                    else:
                                        logger.warning(f"Failed to schedule tasks for match {match.id}: {scheduling_result.get('message')}")
                                except Exception as sched_e:
                                    logger.error(f"Error scheduling tasks for match {match.id}: {str(sched_e)}")
                                    # Don't fail the match creation if scheduling fails
                        
                        except Exception as e:
                            logger.error(f"Error processing match in {competition_name}: {str(e)}")
                            continue
                    
                    logger.info(f"Added {matches_in_competition} matches from {competition_name}")
                
            except Exception as e:
                logger.error(f"Error fetching {competition_name} matches: {str(e)}")
                continue
        
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
                'message': 'No new matches found (all upcoming matches may already be in the system)',
                'count': 0,
                'competitions_checked': competitions_checked
            })
            
    except Exception as e:
        logger.error(f"Error fetching ESPN matches: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/admin/match_management/clear-all', endpoint='clear_all_matches', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def clear_all_matches():
    """Clear all matches from the database."""
    session = g.db_session
    
    try:
        count = session.query(MLSMatch).count()
        session.query(MLSMatch).delete()
        session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Cleared {count} matches from database'
        })
    except Exception as e:
        logger.error(f"Error clearing matches: {str(e)}")
        session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/admin/match_management/remove/<int:match_id>', endpoint='remove_specific_match', methods=['POST', 'DELETE'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def remove_specific_match(match_id):
    """Remove a specific match and clean up all associated tasks."""
    session = g.db_session
    
    match = session.query(MLSMatch).get(match_id)
    if not match:
        return jsonify({'success': False, 'error': 'Match not found'}), 404
    
    try:
        from app.utils.safe_redis import get_safe_redis
        from app.core import celery
        import json
        
        home_team = 'FC Cincinnati' if match.is_home_game else match.opponent
        away_team = match.opponent if match.is_home_game else 'FC Cincinnati'
        match_info = f"{home_team} vs {away_team}"
        
        revoked_tasks = []
        cleaned_keys = []
        
        # Stop active live reporting task
        if match.live_reporting_task_id:
            try:
                celery.control.revoke(match.live_reporting_task_id, terminate=True)
                revoked_tasks.append(f"Active task: {match.live_reporting_task_id}")
            except Exception as e:
                logger.warning(f"Could not revoke active task {match.live_reporting_task_id}: {str(e)}")
        
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
                        # Handle legacy format
                        task_id = data.decode('utf-8') if isinstance(data, bytes) else str(data)
                        celery.control.revoke(task_id, terminate=True)
                        revoked_tasks.append(f"Scheduled {key_name}: {task_id}")
                
                # Remove the Redis key
                redis_client.delete(redis_key)
                cleaned_keys.append(redis_key)
        
        # Remove the match from database
        session.delete(match)
        session.commit()
        
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
        logger.error(f"Error removing match: {str(e)}")
        session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/admin/match_management/queue-status', endpoint='get_queue_status', methods=['GET'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def get_queue_status():
    """Get comprehensive Celery queue status with match integration."""
    try:
        from app.core import celery
        from app.utils.safe_redis import get_safe_redis
        import json
        
        inspect = celery.control.inspect()
        redis_client = get_safe_redis()
        
        # Get active and scheduled tasks from Celery
        active = inspect.active() or {}
        scheduled = inspect.scheduled() or {}
        
        # Get all scheduled tasks from Redis
        redis_keys = redis_client.keys('match_scheduler:*')
        redis_tasks = {}
        
        for key in redis_keys:
            key_str = key.decode('utf-8')
            data = redis_client.get(key)
            ttl = redis_client.ttl(key)
            
            if data:
                try:
                    task_info = json.loads(data.decode('utf-8'))
                    redis_tasks[key_str] = {
                        'task_id': task_info.get('task_id'),
                        'eta': task_info.get('eta'),
                        'ttl': ttl
                    }
                except (json.JSONDecodeError, AttributeError):
                    redis_tasks[key_str] = {
                        'task_id': data.decode('utf-8') if isinstance(data, bytes) else str(data),
                        'eta': 'Unknown',
                        'ttl': ttl
                    }
        
        # Get match information for context
        session = g.db_session
        matches = session.query(MLSMatch).all()
        match_info = {}
        
        for match in matches:
            match_info[str(match.match_id)] = {
                'id': match.id,
                'opponent': match.opponent,
                'date_time': match.date_time.isoformat() if match.date_time else None,
                'live_reporting_status': match.live_reporting_status,
                'live_reporting_task_id': match.live_reporting_task_id,
                'thread_created': match.thread_created
            }
        
        return jsonify({
            'active_tasks': active,
            'scheduled_tasks': scheduled,
            'redis_scheduled_tasks': redis_tasks,
            'match_info': match_info,
            'timestamp': datetime.utcnow().isoformat(),
            'summary': {
                'total_active': sum(len(tasks) for tasks in active.values()),
                'total_scheduled': sum(len(tasks) for tasks in scheduled.values()),
                'total_redis_scheduled': len(redis_tasks)
            }
        })
    except Exception as e:
        logger.error(f"Error getting queue status: {str(e)}")
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/admin/match_management/force-schedule/<int:match_id>', endpoint='force_schedule_match', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def force_schedule_match(match_id):
    """Force schedule all tasks for a match, overriding existing ones."""
    session = g.db_session
    
    match = session.query(MLSMatch).get(match_id)
    if not match:
        return jsonify({'success': False, 'error': 'Match not found'}), 404
    
    try:
        from app.match_scheduler import MatchScheduler
        
        scheduler = MatchScheduler()
        result = scheduler.schedule_match_tasks(match_id, force=True)
        
        home_team = 'FC Cincinnati' if match.is_home_game else match.opponent
        away_team = match.opponent if match.is_home_game else 'FC Cincinnati'
        
        if result.get('success'):
            return jsonify({
                'success': True,
                'message': f'All tasks force-scheduled for {home_team} vs {away_team}',
                'details': result
            })
        else:
            return jsonify({
                'success': False,
                'error': result.get('message', 'Unknown error'),
                'details': result
            })
    except Exception as e:
        logger.error(f"Error force scheduling match: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/admin/match_management/debug-tasks/<int:match_id>', endpoint='debug_match_tasks', methods=['GET'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def debug_match_tasks(match_id):
    """Get comprehensive debug information for all tasks related to a match."""
    session = g.db_session
    
    match = session.query(MLSMatch).get(match_id)
    if not match:
        return jsonify({'success': False, 'error': 'Match not found'}), 404
    
    try:
        from app.utils.safe_redis import get_safe_redis
        from app.core import celery
        import json
        
        redis_client = get_safe_redis()
        debug_info = {
            'match_info': {
                'id': match.id,
                'match_id': match.match_id,
                'opponent': match.opponent,
                'date_time': match.date_time.isoformat() if match.date_time else None,
                'live_reporting_status': match.live_reporting_status,
                'live_reporting_task_id': match.live_reporting_task_id,
                'live_reporting_started': match.live_reporting_started,
                'live_reporting_scheduled': match.live_reporting_scheduled,
                'thread_created': match.thread_created,
                'thread_creation_time': match.thread_creation_time.isoformat() if match.thread_creation_time else None
            },
            'redis_tasks': {},
            'celery_tasks': {},
            'recommendations': []
        }
        
        # Check Redis scheduled tasks  
        thread_key = f"match_scheduler:{match.id}:thread"
        reporting_key = f"match_scheduler:{match.id}:reporting"
        
        for key_name, redis_key in [('thread', thread_key), ('reporting', reporting_key)]:
            if redis_client.exists(redis_key):
                data = redis_client.get(redis_key)
                ttl = redis_client.ttl(redis_key)
                
                try:
                    task_info = json.loads(data.decode('utf-8'))
                    debug_info['redis_tasks'][key_name] = {
                        'exists': True,
                        'task_id': task_info.get('task_id'),
                        'eta': task_info.get('eta'),
                        'ttl_seconds': ttl,
                        'raw_data': task_info
                    }
                except (json.JSONDecodeError, AttributeError):
                    debug_info['redis_tasks'][key_name] = {
                        'exists': True,
                        'task_id': data.decode('utf-8') if isinstance(data, bytes) else str(data),
                        'eta': 'Unknown',
                        'ttl_seconds': ttl,
                        'raw_data': str(data)
                    }
            else:
                debug_info['redis_tasks'][key_name] = {'exists': False}
        
        # Check Celery task status for active tasks
        if match.live_reporting_task_id:
            try:
                task_result = celery.AsyncResult(match.live_reporting_task_id)
                debug_info['celery_tasks']['active_task'] = {
                    'task_id': match.live_reporting_task_id,
                    'state': task_result.state,
                    'ready': task_result.ready(),
                    'successful': task_result.successful() if task_result.ready() else None,
                    'failed': task_result.failed(),
                    'result': str(task_result.result) if task_result.ready() else None
                }
            except Exception as e:
                debug_info['celery_tasks']['active_task'] = {
                    'task_id': match.live_reporting_task_id,
                    'error': str(e)
                }
        
        # Generate recommendations
        recommendations = []
        
        if not match.thread_created and not debug_info['redis_tasks']['thread']['exists']:
            recommendations.append("Thread not created and no thread task scheduled. Consider scheduling thread creation.")
        
        if match.live_reporting_status == 'not_started' and not debug_info['redis_tasks']['reporting']['exists']:
            recommendations.append("Live reporting not started and no reporting task scheduled. Consider scheduling live reporting.")
        
        if match.live_reporting_task_id and debug_info['celery_tasks'].get('active_task', {}).get('failed'):
            recommendations.append("Active live reporting task has failed. Consider restarting live reporting.")
        
        if debug_info['redis_tasks']['thread'].get('ttl_seconds', 0) < 0:
            recommendations.append("Thread task has expired in Redis. Consider rescheduling.")
        
        if debug_info['redis_tasks']['reporting'].get('ttl_seconds', 0) < 0:
            recommendations.append("Reporting task has expired in Redis. Consider rescheduling.")
        
        debug_info['recommendations'] = recommendations
        
        return jsonify({
            'success': True,
            'debug_info': debug_info,
            'timestamp': datetime.utcnow().isoformat()
        })
    except Exception as e:
        logger.error(f"Error debugging match tasks: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


# -----------------------------------------------------------
# DEPRECATED Routes (for backwards compatibility)
# -----------------------------------------------------------

@admin_bp.route('/admin/schedule_mls_match_thread/<int:match_id>', endpoint='schedule_mls_match_thread', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def schedule_mls_match_thread(match_id):
    """
    Schedule MLS match thread (DEPRECATED - Use /admin/match_management/schedule/<match_id> instead).
    """
    session = g.db_session
    
    match = session.query(MLSMatch).get(match_id)
    if not match:
        show_error('Match not found.')
        return redirect(url_for('admin.view_mls_matches'))
    
    try:
        task_result = schedule_mls_thread_task.delay(match_id)
        home_team = 'FC Cincinnati' if match.is_home_game else match.opponent
        away_team = match.opponent if match.is_home_game else 'FC Cincinnati'
        show_success(f'Match thread scheduled for {home_team} vs {away_team}. Task ID: {task_result.id}')
    except Exception as e:
        logger.error(f"Error scheduling match thread: {str(e)}")
        show_error(f'Error scheduling match thread: {str(e)}')
    
    return redirect(url_for('admin.view_mls_matches'))


@admin_bp.route('/admin/check_thread_status/<task_id>', endpoint='check_thread_status', methods=['GET'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def check_thread_status(task_id):
    """
    Check thread creation status (DEPRECATED - Use /admin/match_management/task-details/<task_id> instead).
    """
    try:
        task_info = get_task_info(task_id)
        return jsonify(task_info)
    except Exception as e:
        logger.error(f"Error checking thread status: {str(e)}")
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/admin/schedule_all_mls_threads', endpoint='schedule_all_mls_threads', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def schedule_all_mls_threads():
    """
    Schedule all MLS threads (DEPRECATED - Use /admin/match_management/schedule-all instead).
    """
    try:
        task_result = schedule_all_mls_threads_task.delay()
        show_success(f'All MLS threads scheduled. Task ID: {task_result.id}')
    except Exception as e:
        logger.error(f"Error scheduling all threads: {str(e)}")
        show_error(f'Error scheduling all threads: {str(e)}')
    
    return redirect(url_for('admin.view_mls_matches'))


@admin_bp.route('/admin/match_management/cache-status', endpoint='get_cache_status', methods=['GET'])
@login_required
@role_required(['Global Admin', 'Discord Admin'])
def get_cache_status():
    """Get cache system status and statistics."""
    try:
        from app.services.task_status_cache import task_status_cache
        
        redis_client = task_status_cache.get_redis_client()
        
        # Get cache statistics
        cache_keys = redis_client.keys(f"{task_status_cache.CACHE_PREFIX}:*")
        cache_count = len(cache_keys)
        
        # Sample cache entries for health check
        sample_size = min(10, cache_count)
        valid_entries = 0
        total_size_bytes = 0
        
        if sample_size > 0:
            import random
            sample_keys = random.sample(cache_keys, sample_size)
            
            for key in sample_keys:
                try:
                    data = redis_client.get(key)
                    if data:
                        import json
                        json.loads(data)  # Validate JSON
                        valid_entries += 1
                        total_size_bytes += len(data)
                except Exception:
                    pass
        
        avg_entry_size = (total_size_bytes / sample_size) if sample_size > 0 else 0
        health_score = (valid_entries / sample_size * 100) if sample_size > 0 else 100
        estimated_total_size = avg_entry_size * cache_count
        
        # Get active matches count for comparison
        from app.models import MLSMatch
        from app.core.session_manager import managed_session
        from datetime import datetime, timedelta
        
        with managed_session() as session:
            now = datetime.utcnow()
            active_matches = session.query(MLSMatch).filter(
                MLSMatch.date_time >= now - timedelta(days=2),
                MLSMatch.date_time <= now + timedelta(days=7)
            ).count()
        
        cache_coverage = (cache_count / active_matches * 100) if active_matches > 0 else 0
        
        return jsonify({
            'success': True,
            'cache_stats': {
                'total_entries': cache_count,
                'active_matches': active_matches,
                'cache_coverage_percent': cache_coverage,
                'health_score_percent': health_score,
                'sample_size': sample_size,
                'valid_entries': valid_entries,
                'avg_entry_size_bytes': int(avg_entry_size),
                'estimated_total_size_bytes': int(estimated_total_size),
                'ttl_seconds': task_status_cache.CACHE_TTL
            },
            'timestamp': datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error getting cache status: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500