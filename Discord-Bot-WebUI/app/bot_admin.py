from flask import Blueprint, render_template, redirect, url_for, request, jsonify
from flask_login import login_required
from app.routes import load_match_dates, save_match_dates
from app import db
from app.db_utils import (
    insert_match_schedule,
    update_match_in_db,
    delete_match_from_db,
    load_existing_dates,
    load_match_dates_from_db,
    format_match_data,
    format_match_display_data,
    PREDICTIONS_DB_PATH
)
from app.api_utils import async_to_sync, fetch_espn_data, extract_match_details
from app.decorators import role_required
from app.models import Match
import json
import logging
from datetime import datetime

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
    # Fetch match dates directly from the database
    match_dates = load_match_dates_from_db()
    
    # Format the match dates
    match_dates = format_match_display_data(match_dates)

    # Sort matches by date
    match_dates.sort(key=lambda x: datetime.strptime(x['date'], "%Y-%m-%d %H:%M:%S%z"))

    return render_template(
        'matches.html', 
        title='Sounders Match Dates', 
        matches=match_dates, 
        competition_mappings=COMPETITION_MAPPINGS,
        inverse_competition_mappings=INVERSE_COMPETITION_MAPPINGS
    )

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
            insert_match_schedule(
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
                update_match_in_db(
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
@bot_admin_bp.route('/matches/remove/<int:match_index>', methods=['POST'])
@login_required
def remove_mls_match(match_index):
    # Fetch matches from the DB
    matches = load_match_dates_from_db()

    if match_index < 0 or match_index >= len(matches):
        return jsonify(success=False, message="Invalid match index."), 400

    # Find the match to remove using its index
    match_to_remove = matches[match_index]
    match_id = match_to_remove['match_id']  # Use match_id for the DB
    date = match_to_remove['date'].split(' ')[0].replace('-', '')  # Convert to match JSON format (YYYYMMDD)
    competition = match_to_remove['competition']

    # Remove from the database using match_id
    delete_match_from_db(match_id)

    # Update JSON by matching date and competition
    match_dates = load_match_dates()
    match_dates = [
        m for m in match_dates
        if not (m['date'] == date and m['competition'] == competition)
    ]
    save_match_dates(match_dates)

    return jsonify(success=True)  # No redirection, just a JSON response

@bot_admin_bp.route('/clear_all_mls_matches', methods=['POST'])
@login_required
@role_required('Global Admin')
def clear_all_mls_matches():
    try:
        # Logic to delete all matches
        # Example: Match.query.delete() (Make sure to adjust based on your ORM and models)
        db.session.query(Match).delete()
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
