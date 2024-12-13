from flask import Blueprint, render_template, redirect, url_for, request, jsonify, current_app, flash, g, abort
from flask_login import login_required
from app.core import celery
from app.tasks.tasks_live_reporting import (
    start_live_reporting,
    create_match_thread_task,
    force_create_mls_thread_task
)
from app.db_utils import load_match_dates_from_db, insert_mls_match, update_mls_match
from app.api_utils import async_to_sync, fetch_espn_data, extract_match_details
from app.decorators import role_required
from app.models import Match, MLSMatch
from app.match_scheduler import MatchScheduler
from datetime import datetime
from dateutil import parser
import json
import logging

logger = logging.getLogger(__name__)

bot_admin_bp = Blueprint('bot_admin', __name__, url_prefix='/bot/admin')

def get_scheduler():
    """Get or create MatchScheduler instance."""
    if not hasattr(current_app, 'match_scheduler'):
        current_app.match_scheduler = MatchScheduler()
    return current_app.match_scheduler

COMPETITION_MAPPINGS = {
    "MLS": "usa.1",
    "US Open Cup": "usa.open",
    "FIFA Club World Cup": "fifa.cwc",
    "Concacaf": "concacaf.league"
}

INVERSE_COMPETITION_MAPPINGS = {v: k for k, v in COMPETITION_MAPPINGS.items()}

@bot_admin_bp.route('/')
@login_required
def bot_management():
    return render_template('bot_management.html', title='Bot Management')

@bot_admin_bp.route('/roles')
@login_required
def roles():
    return render_template('roles.html', title='Current Roles')

@bot_admin_bp.route('/matches')
@login_required
def matches():
    session_db = g.db_session
    match_dates = load_match_dates_from_db(session=session_db)

    for match in match_dates:
        if isinstance(match['date'], str):
            dt_object = parser.parse(match['date'])
            match['date'] = dt_object
            match['formatted_date'] = dt_object.strftime('%m/%d/%Y %I:%M %p')
        match['live_reporting_scheduled'] = match.get('live_reporting_scheduled', False)
        match['live_reporting_started'] = match.get('live_reporting_started', False)

    match_dates.sort(key=lambda x: x['date'])

    return render_template(
        'matches.html',
        title='Sounders Match Dates',
        matches=match_dates,
        competition_mappings=COMPETITION_MAPPINGS,
        inverse_competition_mappings=INVERSE_COMPETITION_MAPPINGS
    )

@bot_admin_bp.route('/start_live_reporting/<match_id>', methods=['POST'])
@login_required
def start_live_reporting_route(match_id):
    session_db = g.db_session
    try:
        logger.info(f"Starting live reporting for match_id: {match_id}")
        match = session_db.query(MLSMatch).filter(MLSMatch.match_id == str(match_id)).first()
        
        if not match:
            logger.error(f"Match not found in mls_matches with match_id: {match_id}")
            return jsonify({'success': False, 'message': f'Match {match_id} not found'}), 404

        if match.live_reporting_status == 'running':
            logger.warning(f"Match {match_id} already running")
            return jsonify({'success': False, 'message': 'Live reporting already running'}), 400

        task = start_live_reporting.delay(str(match.match_id))
        match.live_reporting_status = 'scheduled'
        match.live_reporting_task_id = task.id
        match.live_reporting_scheduled = True

        logger.info(f"Successfully started live reporting for match {match_id}, task_id: {task.id}, status: {match.live_reporting_status}")

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

@bot_admin_bp.route('/stop_live_reporting/<match_id>', methods=['POST'])
@login_required
def stop_live_reporting_route(match_id):
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

        endpoint = f"sports/soccer/{competition}/scoreboard?dates={formatted_date}"
        match_data = async_to_sync(fetch_espn_data(endpoint))

        if not match_data or 'events' not in match_data:
            logger.error(f"No events found for date {formatted_date} and competition {competition}")
            return jsonify(success=False, message="No events found."), 400
        
        for event in match_data['events']:
            if 'Seattle Sounders FC' in event.get("name", ""):
                match_details = extract_match_details(event)
                try:
                    match = insert_mls_match(
                        match_id=match_details['match_id'],
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

                    if not match:
                        logger.error("Failed to create match record")
                        flash("Failed to create match record", "error")
                        return redirect(url_for('bot_admin.matches'))

                    scheduler = get_scheduler()
                    scheduler_result = scheduler.schedule_match_tasks(match.id)

                    if not scheduler_result['success']:
                        logger.error(f"Failed to schedule match tasks: {scheduler_result['message']}")
                        flash(f"Match added but scheduling failed: {scheduler_result['message']}", "warning")
                    else:
                        logger.info(f"Successfully scheduled match tasks for match {match.id}")
                        flash("Match added and scheduled successfully", "success")

                    return redirect(url_for('bot_admin.matches'))

                except Exception as e:
                    logger.error(f"Error processing match: {str(e)}", exc_info=True)
                    flash(f"Error processing match: {str(e)}", "error")
                    return redirect(url_for('bot_admin.matches'))

        logger.warning("No Sounders match found in the event data")
        return jsonify(success=False, message="No relevant match found."), 400
        
    except Exception as e:
        logger.error(f"Error adding match: {str(e)}", exc_info=True)
        return jsonify(success=False, message=f"Error adding match: {str(e)}"), 500

@bot_admin_bp.route('/update_match/<int:match_id>', methods=['POST'])
@login_required
def update_mls_match_route(match_id):
    session_db = g.db_session
    try:
        logger.debug(f"Received update request for match_id: {match_id}")

        if request.is_json:
            data = request.get_json()
            date = data.get('date')
            competition_friendly = data.get('competition')
        else:
            date = request.form.get('date')
            competition_friendly = request.form.get('competition')

        logger.debug(f"Data received - Date: {date}, Competition: {competition_friendly}")

        competition = COMPETITION_MAPPINGS.get(competition_friendly)

        if not date or not competition:
            logger.error(f"Missing date or competition: Date={date}, Competition={competition}")
            return jsonify(success=False, message="Date and competition are required."), 400

        date_only = date.split(" ")[0]
        formatted_date = datetime.strptime(date_only, "%Y-%m-%d").strftime("%Y%m%d")

        endpoint = f"sports/soccer/{competition}/scoreboard?dates={formatted_date}"
        logger.debug(f"Fetching data from ESPN API: {endpoint}")
        match_data = async_to_sync(fetch_espn_data(endpoint))

        if not match_data or 'events' not in match_data:
            logger.error(f"No events found for date {formatted_date} and competition {competition}")
            return jsonify(success=False, message="No events found."), 400

        for event in match_data['events']:
            if 'Seattle Sounders FC' in event.get("name", ""):
                match_details = extract_match_details(event)
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

@bot_admin_bp.route('/matches/remove/<int:match_id>', methods=['POST'])
@login_required
def remove_mls_match(match_id):
    session_db = g.db_session
    try:
        match = session_db.query(MLSMatch).get(match_id)
        if not match:
            return jsonify(success=False, message="Match not found."), 404

        redis_client = current_app.extensions['redis']
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
    session_db = g.db_session
    try:
        matches = session_db.query(MLSMatch).all()
        logger.debug(f"Found {len(matches)} matches in mls_matches table")

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
    session_db = g.db_session
    try:
        match = session_db.query(MLSMatch).filter_by(id=match_id).first()
        if not match:
            return jsonify({'success': False, 'message': 'Match not found'}), 404

        if not match.match_id:
            return jsonify({'success': False, 'message': 'No ESPN match ID found'}), 400

        if match.thread_created:
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
    session_db = g.db_session
    try:
        match = session_db.query(MLSMatch).filter_by(id=match_id).first()
        if not match:
            return jsonify({'success': False, 'message': 'Match not found'}), 404

        scheduler = get_scheduler()
        result = scheduler.schedule_match_tasks(match_id)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error scheduling match {match_id}: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500

@bot_admin_bp.route('/check-redis', methods=['GET'])
@login_required
def check_redis():
    from app.redis_manager import RedisManager  # Ensure redis_manager is refactored too
    try:
        redis_manager = RedisManager()
        connection_status = redis_manager.check_connection()

        scheduler = get_scheduler()
        tasks_status = scheduler.monitor_scheduled_tasks()

        return jsonify({
            'redis_connected': connection_status,
            'scheduled_tasks': tasks_status.get('scheduled_tasks', {}),
            'total_tasks': tasks_status.get('total_keys', 0)
        })
    except Exception as e:
        logger.error(f"Redis health check failed: {str(e)}")
        return jsonify({'redis_connected': False, 'error': str(e)}), 500

@bot_admin_bp.route('/check-redis', methods=['GET'])
@login_required
def check_redis_health():
    from app.redis_manager import RedisManager
    try:
        redis_client = RedisManager().client
        result = redis_client.ping()
        keys = redis_client.keys('match_scheduler:*')

        return jsonify({
            'redis_connected': bool(result),
            'keys': [k.decode('utf-8') for k in keys],
            'ttls': {k.decode('utf-8'): redis_client.ttl(k) for k in keys}
        })
    except Exception as e:
        return jsonify({'redis_connected': False, 'error': str(e)}), 500
