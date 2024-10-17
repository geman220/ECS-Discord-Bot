from app import celery as celery_app
from flask import Blueprint, render_template, redirect, url_for, request, jsonify
from flask_login import login_required
from app.routes import load_match_dates, save_match_dates
from app import db
from app.tasks import start_live_reporting
from app.db_utils import (
    insert_mls_match,
    update_mls_match,
    delete_mls_match,
    load_match_dates_from_db,
    format_match_display_data,
)
from app.api_utils import async_to_sync, fetch_espn_data, extract_match_details
from app.decorators import role_required
from app.models import Match, MLSMatch
from datetime import datetime
from dateutil import parser
import json
import logging

# Initialize logger
logger = logging.getLogger(__name__)

bot_admin_bp = Blueprint('bot_admin', __name__, url_prefix='/bot/admin')

# Define competition mappings
COMPETITION_MAPPINGS = {
    "MLS": "usa.1",
    "US Open Cup": "usa.open",
    "FIFA Club World Cup": "fifa.cwc",
    "Concacaf": "concacaf.league"
}

# Create inverse mappings to convert JSON value to friendly name
INVERSE_COMPETITION_MAPPINGS = {v: k for k, v in COMPETITION_MAPPINGS.items()}

def load_match_dates_from_db():
    matches = MLSMatch.query.all()
    return [
        {
            'match_id': match.match_id,
            'opponent': match.opponent,
            'date': match.date_time.isoformat(),
            'venue': match.venue,
            'is_home_game': match.is_home_game,
            'summary_link': match.summary_link,
            'stats_link': match.stats_link,
            'commentary_link': match.commentary_link,
            'competition': match.competition
        }
        for match in matches
    ]

# Bot Management Page
@bot_admin_bp.route('/')
@login_required
def bot_management():
    return render_template('bot_management.html', title='Bot Management')

# View Roles
@bot_admin_bp.route('/roles')
@login_required
def roles():
    return render_template('roles.html', title='Current Roles')

# View Sounders Matches (MLS)
@bot_admin_bp.route('/matches')
@login_required
def matches():
    match_dates = load_match_dates_from_db()
    
    for match in match_dates:
        if isinstance(match['date'], str):
            dt_object = parser.parse(match['date'])
            match['date'] = dt_object
            match['formatted_date'] = dt_object.strftime('%m/%d/%Y %I:%M %p')
        
        # Add live reporting status to the match dictionary
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
    match = MLSMatch.query.filter_by(match_id=match_id).first()
    if not match:
        return jsonify({'success': False, 'message': 'Match not found'}), 404
    
    if match.live_reporting_status in ['running', 'scheduled']:
        return jsonify({'success': False, 'message': 'Live reporting already started or scheduled'}), 400
    
    # Schedule the task
    try:
        task = start_live_reporting.apply_async(args=[match_id])
        match.live_reporting_status = 'scheduled'
        match.live_reporting_task_id = task.id
        db.session.commit()
        return jsonify({'success': True, 'message': 'Live reporting scheduled'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f"Error scheduling live reporting: {str(e)}"}), 500

@bot_admin_bp.route('/stop_live_reporting/<match_id>', methods=['POST'])
@login_required
def stop_live_reporting(match_id):
    match = MLSMatch.query.filter_by(match_id=match_id).first()
    if not match:
        return jsonify({'success': False, 'message': 'Match not found'}), 404
    
    if match.live_reporting_status not in ['running', 'scheduled']:
        return jsonify({'success': False, 'message': 'Live reporting is not running or scheduled for this match'}), 400

    try:
        match.live_reporting_status = 'stopped'
        db.session.commit()

        # If there's a running task, revoke it
        if match.live_reporting_task_id:
            celery_app.control.revoke(match.live_reporting_task_id, terminate=True)

        return jsonify({'success': True, 'message': 'Live reporting stopped successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f"Error stopping live reporting: {str(e)}"}), 500

# Add New MLS Match
@bot_admin_bp.route('/matches/add', methods=['POST'])
@login_required
def add_mls_match():
    date = request.form.get('date')
    competition_friendly = request.form.get('competition')

    # Convert the user-friendly competition name to the corresponding value
    competition = COMPETITION_MAPPINGS.get(competition_friendly)

    if not date or not competition:
        return jsonify(success=False, message="Date and competition are required."), 400

    # Strip the time part if present
    date_only = date.split(" ")[0]  # This removes the time part if it exists

    # Format the date to match the API requirement (YYYYMMDD)
    formatted_date = datetime.strptime(date_only, "%Y-%m-%d").strftime("%Y%m%d")

    # Fetch data from ESPN API
    endpoint = f"sports/soccer/{competition}/scoreboard?dates={formatted_date}"
    match_data = async_to_sync(fetch_espn_data(endpoint))

    if not match_data or 'events' not in match_data:
        return jsonify(success=False, message="No events found for the given date and competition."), 400

    for event in match_data['events']:
        if 'Seattle Sounders FC' in event.get("name", ""):
            match_details = extract_match_details(event)

            # Add to Database
            insert_mls_match(
                match_id=match_details['match_id'],
                opponent=match_details['opponent'],
                date_time=match_details['date_time'],  # This will include the correct time from the API
                is_home_game=match_details['is_home_game'],
                summary_link=match_details['match_summary_link'],  # Update this key to match the dictionary
                stats_link=match_details['match_stats_link'],
                commentary_link=match_details['match_commentary_link'],
                venue=match_details['venue'],
                competition=competition
            )

            return redirect(url_for('bot_admin.matches'))

    return jsonify(success=False, message="No relevant match found for the Seattle Sounders."), 400

# Update MLS match endpoint
@bot_admin_bp.route('/update_match/<int:match_id>', methods=['POST'])
@login_required
def update_mls_match(match_id):
    try:
        logger.debug(f"Received update request for match_id: {match_id}")

        # Check if the request is JSON
        if request.is_json:
            data = request.get_json()
            date = data.get('date')
            competition_friendly = data.get('competition')
        else:
            date = request.form.get('date')
            competition_friendly = request.form.get('competition')

        logger.debug(f"Data received - Date: {date}, Competition: {competition_friendly}")

        # Convert the user-friendly competition name to the corresponding value
        competition = COMPETITION_MAPPINGS.get(competition_friendly)

        if not date or not competition:
            logger.error(f"Missing date or competition: Date={date}, Competition={competition}")
            return jsonify(success=False, message="Date and competition are required."), 400

        # Strip the time part if present
        date_only = date.split(" ")[0]  # This removes the time part if it exists

        # Format the date to match the API requirement (YYYYMMDD)
        formatted_date = datetime.strptime(date_only, "%Y-%m-%d").strftime("%Y%m%d")

        # Fetch data from ESPN API
        endpoint = f"sports/soccer/{competition}/scoreboard?dates={formatted_date}"
        logger.debug(f"Fetching data from ESPN API: {endpoint}")
        match_data = async_to_sync(fetch_espn_data(endpoint))

        if not match_data or 'events' not in match_data:
            logger.error(f"No events found for date {formatted_date} and competition {competition}")
            return jsonify(success=False, message="No events found for the given date and competition."), 400

        # Look for the specific match in the event data
        for event in match_data['events']:
            if 'Seattle Sounders FC' in event.get("name", ""):
                match_details = extract_match_details(event)

                # Update the match in the database
                update_mls_match(
                    match_id=match_id,
                    opponent=match_details['opponent'],
                    date_time=match_details['date_time'],  # This will include the correct time from the API
                    is_home_game=match_details['is_home_game'],
                    summary_link=match_details['match_summary_link'],  # Use the correct key name
                    stats_link=match_details['match_stats_link'],      # Use the correct key name
                    commentary_link=match_details['match_commentary_link'],  # Use the correct key name
                    venue=match_details['venue'],
                    competition=competition
                )

                logger.debug(f"Successfully updated match with ID {match_id}.")
                return jsonify(success=True)

        logger.error(f"No relevant match found for the Seattle Sounders in the event data.")
        return jsonify(success=False, message="No relevant match found for the Seattle Sounders."), 400

    except Exception as e:
        logger.exception(f"Error updating match with ID {match_id}: {e}")
        return jsonify(success=False, message=f"An error occurred while updating the match: {str(e)}"), 500

# Remove Match
@bot_admin_bp.route('/matches/remove/<int:match_id>', methods=['POST'])
@login_required
def remove_mls_match(match_id):
    try:
        match = MLSMatch.query.get(match_id)
        if not match:
            return jsonify(success=False, message="Match not found."), 404
        
        # Remove from the database
        db.session.delete(match)
        db.session.commit()
        
        logger.info(f"Match {match_id} removed successfully.")
        return jsonify(success=True, message="Match removed successfully.")
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error removing match {match_id}: {str(e)}")
        return jsonify(success=False, message="An error occurred while removing the match."), 500

@bot_admin_bp.route('/clear_all_mls_matches', methods=['POST'])
@login_required
@role_required('Global Admin')
def clear_all_mls_matches():
    try:
        # Logic to delete all matches
        db.session.query(Match).delete()
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@bot_admin_bp.route('/get_all_match_statuses', methods=['GET'])
@login_required
def get_all_match_statuses():
    matches = MLSMatch.query.all()
    match_statuses = {match.match_id: match.live_reporting_status for match in matches}
    return jsonify(match_statuses)