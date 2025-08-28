# app/bot_admin.py

"""
Bot Admin Module

This module defines administrative endpoints for managing live reporting,
match scheduling, and MLS match data. Endpoints include starting/stopping
live reporting, adding/updating/removing matches, scheduling tasks, and
checking background task and Redis health statuses.
"""

# Standard library imports
from datetime import datetime
from app.utils.safe_redis import get_safe_redis
import logging

# Third-party imports
import pytz
from dateutil import parser
from flask import (
    Blueprint, render_template, redirect, url_for, request,
    jsonify, current_app, g
)
from flask_login import login_required

# Local application imports
from app.core import celery
from app.tasks.tasks_live_reporting import force_create_mls_thread_task
try:
    from app.tasks.tasks_live_reporting_v2 import start_live_reporting_v2
    V2_AVAILABLE = True
except ImportError:
    V2_AVAILABLE = False
    start_live_reporting_v2 = None
from app.alert_helpers import show_success, show_error, show_warning, show_info
from app.db_utils import load_match_dates_from_db, insert_mls_match, update_mls_match
from app.api_utils import async_to_sync, extract_match_details
from app.services.espn_service import get_espn_service
from app.decorators import role_required
from app.models import Match, MLSMatch, Player
from app.match_scheduler import MatchScheduler

logger = logging.getLogger(__name__)

# Log V2 availability after logger is defined
if V2_AVAILABLE:
    logger.info("✅ Live Reporting V2 system is AVAILABLE for bot admin operations")
else:
    logger.warning("⚠️  Live Reporting V2 system NOT AVAILABLE for bot admin - using Robust system")
bot_admin_bp = Blueprint('bot_admin', __name__, url_prefix='/bot/admin')

# ------------------------
# Helper Functions
# ------------------------

def ensure_utc(dt):
    """
    Convert a datetime object to UTC.
    If the datetime is naive, assume it's in UTC.
    Otherwise, convert it to UTC.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=pytz.UTC)
    else:
        return dt.astimezone(pytz.UTC)


def get_scheduler():
    """
    Get or create a MatchScheduler instance.
    """
    if not hasattr(current_app, 'match_scheduler'):
        current_app.match_scheduler = MatchScheduler()
    return current_app.match_scheduler


COMPETITION_MAPPINGS = {
    "MLS": "usa.1",
    "US Open Cup": "usa.open",
    "FIFA Club World Cup": "fifa.cwc",
    "Concacaf": "concacaf.league",
    "Concacaf Champions League": "concacaf.champions",
    "Leagues Cup": "concacaf.leagues.cup",
}
INVERSE_COMPETITION_MAPPINGS = {v: k for k, v in COMPETITION_MAPPINGS.items()}


# ------------------------
# Routes
# ------------------------

@bot_admin_bp.route('/')
@login_required
def bot_management():
    """
    Render the Bot Management dashboard.
    """
    return render_template('bot_management.html', title='Bot Management')


@bot_admin_bp.route('/roles')
@login_required
def roles():
    """
    Render a page displaying current roles.
    """
    return render_template('roles.html', title='Current Roles')


# DEPRECATED ROUTE - MARKED FOR DELETION
# This route has been replaced by /admin/match_management
# TODO: Remove this route and related templates after new system is verified in production
@bot_admin_bp.route('/matches')
@login_required
def matches():
    """
    DEPRECATED: Retrieve and display match dates for live reporting.
    
    This route has been deprecated and replaced by the unified match_management route.
    It will be removed in a future update once the new system is verified.
    
    Converts stored UTC dates to Pacific Time for display.
    """
    session_db = g.db_session
    match_dates = load_match_dates_from_db(session=session_db)
    pacific_tz = pytz.timezone('America/Los_Angeles')

    for match in match_dates:
        # 'match["date"]' is assumed stored in UTC.
        dt_object = parser.parse(match['date']) if isinstance(match['date'], str) else match['date']
        if not dt_object.tzinfo:
            dt_object = dt_object.replace(tzinfo=pytz.UTC)
        dt_pst = dt_object.astimezone(pacific_tz)
        match['date_time'] = dt_pst
        match['formatted_date'] = dt_pst.strftime('%m/%d/%Y %I:%M %p')
        match.setdefault('live_reporting_scheduled', False)
        match.setdefault('live_reporting_started', False)

    match_dates.sort(key=lambda x: x['date'])
    return render_template(
        'matches.html',
        title='Sounders Match Dates',
        matches=match_dates,
        competition_mappings=COMPETITION_MAPPINGS,
        inverse_competition_mappings=INVERSE_COMPETITION_MAPPINGS
    )


@bot_admin_bp.route('/start_live_reporting/<int:match_id>', methods=['POST'])
@login_required
def start_live_reporting_route(match_id):
    """
    Start live reporting for a given MLS match.
    """
    session_db = g.db_session
    try:
        logger.info(f"Starting live reporting for match_id: {match_id}")
        match = session_db.query(MLSMatch).filter_by(id=match_id).first()
        if not match:
            logger.error(f"Match {match_id} not found in MLS matches")
            return jsonify({'success': False, 'message': f'Match {match_id} not found'}), 404

        if match.live_reporting_status == 'running':
            logger.warning(f"Match {match_id} already running")
            return jsonify({'success': False, 'message': 'Live reporting already running'}), 400

        # Use V2 live reporting if available, fallback to robust
        if V2_AVAILABLE:
            logger.info(f"🚀 [BOT_ADMIN] Starting V2 live reporting for match {match.match_id} in thread {match.discord_thread_id}")
            task = start_live_reporting_v2.delay(
                str(match.match_id), 
                str(match.discord_thread_id), 
                match.competition or 'usa.1'
            )
            reporting_type = "V2"
        else:
            logger.error(f"❌ [BOT_ADMIN] V2 not available, no fallback system. Cannot start live reporting for match {match.match_id}")
            return jsonify({
                'success': False, 
                'message': 'V2 live reporting system not available and no fallback configured'
            }), 500
        match.live_reporting_status = 'scheduled'
        match.live_reporting_task_id = task.id
        match.live_reporting_scheduled = True

        logger.info(f"Live reporting scheduled for match {match_id}, task_id: {task.id}")
        return jsonify({
            'success': True,
            'message': 'Live reporting started',
            'task_id': task.id,
            'match_id': match.match_id,
            'status': match.live_reporting_status
        })
    except Exception as e:
        logger.error(f"Error starting live reporting for match {match_id}: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': f'Internal server error: {str(e)}'}), 500


@bot_admin_bp.route('/stop_live_reporting/<int:match_id>', methods=['POST'])
@login_required
def stop_live_reporting_route(match_id):
    """
    Stop live reporting for a given MLS match.
    """
    session_db = g.db_session
    try:
        match = session_db.query(MLSMatch).filter_by(id=match_id).first()
        if not match:
            return jsonify({'success': False, 'message': 'Match not found'}), 404

        if match.live_reporting_status not in ['running', 'scheduled']:
            return jsonify({'success': False, 'message': 'Live reporting is not active'}), 400

        match.live_reporting_status = 'stopped'
        if match.live_reporting_task_id:
            celery.control.revoke(match.live_reporting_task_id, terminate=True)
            match.live_reporting_task_id = None

        return jsonify({'success': True, 'message': 'Live reporting stopped'})
    except Exception as e:
        logger.error(f"Error stopping live reporting: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


@bot_admin_bp.route('/matches/add', methods=['POST'])
@login_required
def add_mls_match():
    """
    Add a new MLS match by fetching event data from the ESPN API.
    
    Filters for "Seattle Sounders FC" events, converts dates to UTC,
    inserts the match record, and schedules match tasks.
    """
    session_db = g.db_session
    try:
        date = request.form.get('date')
        competition_friendly = request.form.get('competition')
        competition = COMPETITION_MAPPINGS.get(competition_friendly)

        if not date or not competition:
            logger.error("Missing required fields: date or competition")
            return jsonify(success=False, message="Date and competition are required."), 400

        date_only = date.split(" ")[0]
        formatted_date = datetime.strptime(date_only, "%Y-%m-%d").strftime("%Y%m%d")
        espn_service = get_espn_service()
        match_data = async_to_sync(espn_service.get_scoreboard(competition, formatted_date))

        if not match_data or 'events' not in match_data:
            logger.error(f"No events found for date {formatted_date} and competition {competition}")
            return jsonify(success=False, message="No events found."), 400

        for event in match_data['events']:
            if 'Seattle Sounders FC' in event.get("name", ""):
                match_details = extract_match_details(event)
                match_details['date_time'] = ensure_utc(match_details['date_time'])
                try:
                    match = insert_mls_match(
                        session_db,
                        match_details['match_id'],
                        match_details['opponent'],
                        match_details['date_time'],
                        match_details['is_home_game'],
                        match_details['match_summary_link'],
                        match_details['match_stats_link'],
                        match_details['match_commentary_link'],
                        match_details['venue'],
                        competition
                    )
                    session_db.flush()
                    if not match:
                        logger.error("Failed to create match record")
                        show_error("Failed to create match record")
                        return redirect(url_for('bot_admin.matches'))

                    scheduler = get_scheduler()
                    scheduler_result = scheduler.schedule_match_tasks(match.id)
                    if not scheduler_result.get('success'):
                        logger.error(f"Failed to schedule match tasks: {scheduler_result.get('message')}")
                        show_warning(f"Match added but scheduling failed: {scheduler_result.get('message')}")
                    else:
                        logger.info(f"Successfully scheduled match tasks for match {match.id}")
                        show_success("Match added and scheduled successfully")
                    return redirect(url_for('bot_admin.matches'))

                except Exception as e:
                    logger.error(f"Error processing match: {str(e)}", exc_info=True)
                    show_error(f"Error processing match: {str(e)}")
                    return redirect(url_for('bot_admin.matches'))

        logger.warning("No Sounders match found in the event data")
        return jsonify(success=False, message="No relevant match found."), 400

    except Exception as e:
        logger.error(f"Error adding match: {str(e)}", exc_info=True)
        return jsonify(success=False, message=f"Error adding match: {str(e)}"), 500


@bot_admin_bp.route('/update_match/<int:match_id>', methods=['POST'])
@login_required
def update_mls_match_route(match_id):
    """
    Update an existing MLS match by fetching updated event data from the ESPN API.
    """
    session_db = g.db_session
    try:
        logger.debug(f"Received update request for match_id: {match_id}")
        data = request.get_json() if request.is_json else request.form
        date = data.get('date')
        competition_friendly = data.get('competition')
        logger.debug(f"Data received - Date: {date}, Competition: {competition_friendly}")
        competition = COMPETITION_MAPPINGS.get(competition_friendly)

        if not date or not competition:
            logger.error(f"Missing date or competition: Date={date}, Competition={competition}")
            return jsonify(success=False, message="Date and competition are required."), 400

        date_only = date.split(" ")[0]
        formatted_date = datetime.strptime(date_only, "%Y-%m-%d").strftime("%Y%m%d")
        logger.debug(f"Fetching scoreboard data for {competition} on {formatted_date}")
        espn_service = get_espn_service()
        match_data = async_to_sync(espn_service.get_scoreboard(competition, formatted_date))

        if not match_data or 'events' not in match_data:
            logger.error(f"No events found for date {formatted_date} and competition {competition}")
            return jsonify(success=False, message="No events found."), 400

        for event in match_data['events']:
            if 'Seattle Sounders FC' in event.get("name", ""):
                match_details = extract_match_details(event)
                match_details['date_time'] = ensure_utc(match_details['date_time'])
                update_mls_match(
                    match_id=match_id,
                    opponent=match_details['opponent'],
                    date_time=match_details['date_time'],
                    is_home_game=match_details['is_home_game'],
                    summary_link=match_details['match_summary_link'],
                    stats_link=match_details['match_stats_link'],
                    commentary_link=match_details['match_commentary_link'],
                    venue=match_details['venue'],
                    competition=competition,
                    session=session_db
                )
                logger.debug(f"Successfully updated match with ID {match_id}.")
                return jsonify(success=True)
        logger.error("No relevant match found for the Seattle Sounders.")
        return jsonify(success=False, message="No relevant match found."), 400

    except Exception as e:
        logger.exception(f"Error updating match with ID {match_id}: {e}")
        raise


@bot_admin_bp.route('/matches/remove/<match_id>', methods=['POST'])
@login_required
def remove_mls_match(match_id):
    session_db = g.db_session
    try:
        match = session_db.query(MLSMatch).filter_by(match_id=match_id).first()
        if not match:
            return jsonify(success=False, message="Match not found."), 404

        redis_client = get_safe_redis()
        thread_key = f"match_scheduler:{match_id}:thread"
        reporting_key = f"match_scheduler:{match_id}:reporting"

        task_ids = [redis_client.get(thread_key), redis_client.get(reporting_key)]
        for task_id in task_ids:
            if task_id:
                celery.control.revoke(task_id.decode('utf-8'), terminate=True)

        redis_client.delete(thread_key, reporting_key)
        session_db.delete(match)
        logger.info(f"Match {match_id} and associated tasks removed successfully.")
        return jsonify(success=True, message="Match removed successfully.")
    except Exception as e:
        logger.error(f"Error removing match {match_id}: {str(e)}")
        raise


@bot_admin_bp.route('/clear_all_mls_matches', methods=['POST'])
@login_required
@role_required('Global Admin')
def clear_all_mls_matches():
    """
    Clear all MLS match records from the database.
    """
    session_db = g.db_session
    try:
        session_db.query(Match).delete()
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Error clearing all MLS matches: {str(e)}")
        raise


@bot_admin_bp.route('/get_all_match_statuses', methods=['GET'])
@login_required
def get_all_match_statuses():
    """
    Retrieve the statuses of all MLS matches.
    """
    session_db = g.db_session
    try:
        matches = session_db.query(MLSMatch).all()
        logger.debug(f"Found {len(matches)} matches in MLS matches table")
        statuses = {}
        for match in matches:
            status_data = {
                'status': match.live_reporting_status,
                'task_id': match.live_reporting_task_id,
                'match_id': match.match_id,
                'opponent': match.opponent,
                'scheduled': match.live_reporting_scheduled,
                'started': match.live_reporting_started
            }
            statuses[str(match.match_id)] = status_data
            logger.debug(f"Match {match.match_id} ({match.opponent}) status: {status_data}")
        return jsonify(statuses)
    except Exception as e:
        logger.error(f"Error getting match statuses: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@bot_admin_bp.route('/match/<int:match_id>/create-thread', methods=['POST'])
@login_required
def create_match_thread(match_id):
    """
    Create a thread for a match by triggering a Celery task.
    """
    session_db = g.db_session
    force = request.args.get('force', 'false').lower() == 'true'
    
    try:
        match = session_db.query(MLSMatch).filter_by(id=match_id).first()
        if not match:
            return jsonify({'success': False, 'message': 'Match not found'}), 404
        if not match.match_id:
            return jsonify({'success': False, 'message': 'No ESPN match ID found'}), 400
        # Only block thread creation if one already exists and force isn't True
        if match.thread_created and not force:
            return jsonify({'success': False, 'message': 'Thread already exists'}), 400

        task = force_create_mls_thread_task.delay(match.match_id)
        logger.info(f"Created thread task for match {match_id} (ESPN ID: {match.match_id}), task_id: {task.id}")
        return jsonify({'success': True, 'message': 'Thread creation started', 'task_id': task.id})
    except Exception as e:
        logger.error(f"Error creating thread for match {match_id}: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


@bot_admin_bp.route('/match/schedule/<int:match_id>', methods=['POST'])
@login_required
def schedule_match(match_id):
    """
    Schedule tasks for a match.

    Accepts an optional 'force' query parameter to force rescheduling.
    """
    session_db = g.db_session
    try:
        force = request.args.get('force', 'false').lower() == 'true'
        match = session_db.query(MLSMatch).filter_by(id=match_id).first()
        if not match:
            return jsonify({'success': False, 'message': 'Match not found'}), 404

        scheduler = get_scheduler()
        result = scheduler.schedule_match_tasks(match_id, force=force)
        return jsonify(result)
    except Exception as e:
        current_app.logger.error(f"Error scheduling match {match_id}: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


@bot_admin_bp.route('/check-redis', methods=['GET'])
@login_required
def check_redis_health():
    """
    Check Redis health by pinging and retrieving scheduler keys and TTLs.
    """
    try:
        redis_client = get_safe_redis()
        result = redis_client.ping()
        keys = redis_client.keys('match_scheduler:*')
        return jsonify({
            'redis_connected': bool(result),
            'keys': [k.decode('utf-8') for k in keys],
            'ttls': {k.decode('utf-8'): redis_client.ttl(k) for k in keys}
        })
    except Exception as e:
        logger.error(f"Redis health check failed: {str(e)}")
        return jsonify({'redis_connected': False, 'error': str(e)}), 500


@bot_admin_bp.route('/get_player_id_from_discord/<string:discord_id>', methods=['GET'])
def get_player_id_from_discord(discord_id):
    """
    Retrieve a player's ID and basic profile data based on their Discord ID.
    """
    import os
    session_db = g.db_session
    player = session_db.query(Player).filter_by(discord_id=discord_id).first()
    if not player:
        return jsonify({'error': 'Player not found'}), 404

    base_url = os.getenv("WEBUI_BASE_URL", "https://portal.ecsfc.com").rstrip('/')
    raw_pic_path = player.profile_picture_url or ""
    if raw_pic_path and not raw_pic_path.startswith("http"):
        raw_pic_path = f"{base_url}/{raw_pic_path.lstrip('/')}"

    final_data = {
        'player_id': player.id,
        'player_name': player.name,
        'teams': [team.name for team in player.teams],
        'profile_picture_url': raw_pic_path
    }
    return jsonify(final_data), 200


@bot_admin_bp.route('/task_status/<task_id>', methods=['GET'], endpoint='task_status')
def task_status(task_id):
    """
    Retrieve the status of a background Celery task.
    """
    task = celery.AsyncResult(task_id)
    response = {
        'state': task.state,
        'status': _get_task_status(task)
    }
    if task.state == 'SUCCESS':
        response['result'] = task.result
    elif task.state == 'FAILURE':
        response['error'] = str(task.result)
    return jsonify(response)


@bot_admin_bp.route('/get_match_request/<int:match_id>', methods=['GET'], endpoint='get_match_request')
def get_match_request(match_id):
    """
    Retrieve match request data for a specific match.
    """
    from app.availability_api_helpers import get_match_request_data
    session_db = g.db_session
    match_data = get_match_request_data(match_id, session=session_db)
    if not match_data:
        return jsonify({'error': 'Match not found'}), 404
    return jsonify(match_data), 200


def _get_task_status(task):
    """
    Helper function to interpret a Celery task's state.
    """
    if task.state == 'PENDING':
        return 'Pending...'
    elif task.state == 'SUCCESS':
        return task.result
    elif task.state == 'FAILURE':
        return str(task.info)
    return 'In progress...'