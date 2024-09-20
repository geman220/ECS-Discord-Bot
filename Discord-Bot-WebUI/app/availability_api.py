from app import csrf
from flask import Blueprint, request, jsonify, current_app as app
from flask_login import login_required, current_user
from app import db
from app.models import Match, Availability, Team, Player
from datetime import datetime
import re

availability_bp = Blueprint('availability_api', __name__)
csrf.exempt(availability_bp)

def validate_date(date_text):
    try:
        datetime.strptime(date_text, '%Y-%m-%d')
        return True
    except ValueError:
        return False

def validate_time(time_text):
    return re.match(r"^\d{2}:\d{2}(:\d{2})?$", time_text) is not None

@availability_bp.before_request
def limit_remote_addr():
    allowed_hosts = ['127.0.0.1:5000', 'localhost:5000', 'webui:5000']
    if request.host not in allowed_hosts:
        return "Access Denied", 403

@availability_bp.route('/schedule_availability_poll', methods=['POST'])
def schedule_availability_poll():
    app.logger.debug("Endpoint hit: /api/schedule_availability_poll")

    data = request.json
    match_id = data.get('match_id')
    match_date = data.get('match_date')
    match_time = data.get('match_time')
    team_id = data.get('team_id')

    # Validate inputs
    if not all([match_id, match_date, match_time, team_id]):
        app.logger.debug("Missing data in request")
        return jsonify({"error": "Missing data"}), 400
    if not validate_date(match_date) or not validate_time(match_time):
        app.logger.debug("Invalid date or time format")
        return jsonify({"error": "Invalid date or time format"}), 400

    app.logger.debug(f"Attempting to fetch team with ID: {team_id}")
    try:
        team = Team.query.get_or_404(team_id)
        app.logger.debug(f"Team found: {team.name}")
    except Exception as e:
        app.logger.error(f"Error fetching team: {e}")
        return jsonify({"error": "Failed to fetch team"}), 500

    app.logger.debug(f"Attempting to fetch match with ID: {match_id}")
    try:
        match = Match.query.get_or_404(match_id)
        app.logger.debug(f"Match found: {match}")
    except Exception as e:
        app.logger.error(f"Error fetching match: {e}")
        return jsonify({"error": "Failed to fetch match"}), 500

    app.logger.debug("Database queries successful")
    return jsonify({"message": "Poll scheduled successfully", "match_id": match_id}), 200

# Endpoint to retrieve availability results
@availability_bp.route('/match_availability/<int:match_id>', methods=['GET'])
def get_match_availability(match_id):
    # Fetch availability responses for the match
    match = Match.query.get_or_404(match_id)
    availability = Availability.query.filter_by(match_id=match.id).all()

    results = {
        "yes": sum(1 for a in availability if a.response == 'yes'),
        "no": sum(1 for a in availability if a.response == 'no'),
        "maybe": sum(1 for a in availability if a.response == 'maybe'),
        "responses": [{
            "player_id": a.player_id,
            "response": a.response
        } for a in availability]
    }

    return jsonify({"match_id": match.id, "availability": results}), 200

# Endpoint to update availability based on bot reactions
@availability_bp.route('/update_availability', methods=['POST'])
def update_availability():
    data = request.json
    app.logger.info(f"Received data: {data}")

    match_id = data.get('match_id')
    discord_id = data.get('discord_id')
    response = data.get('response')

    if not all([match_id, discord_id, response]):
        app.logger.error("Invalid data received")
        return jsonify({"error": "Invalid data"}), 400

    try:
        match = Match.query.get_or_404(match_id)
        app.logger.info(f"Found match: {match}")

        player = Player.query.filter_by(discord_id=discord_id).first_or_404()
        app.logger.info(f"Found player: {player.name} with Discord ID: {player.discord_id}")

        availability = Availability.query.filter_by(match_id=match_id, player_id=player.id).first()
        
        if response == 'no_response':
            if availability:
                db.session.delete(availability)  # Remove the availability entry
                app.logger.info("Removed availability entry due to no response")
        else:
            if not availability:
                availability = Availability(match_id=match_id, player_id=player.id, discord_id=player.discord_id, response=response)
                db.session.add(availability)
                app.logger.info("Created new availability entry")
            else:
                availability.response = response
                app.logger.info("Updated existing availability entry")

        app.logger.info(f"Final availability to commit: {availability}")
        db.session.commit()
        app.logger.info("Availability updated successfully")

        return jsonify({"message": "Availability updated successfully"}), 200

    except Exception as e:
        app.logger.error(f"Error updating availability: {str(e)}")
        return jsonify({"error": "Internal Server Error"}), 500

@availability_bp.route('/store_message_ids', methods=['POST'])
def store_message_ids():
    data = request.json
    match_id = data.get('match_id')
    home_message_id = data.get('home_message_id')
    away_message_id = data.get('away_message_id')

    if not match_id or not home_message_id or not away_message_id:
        return jsonify({"error": "Missing match_id or message_ids"}), 400

    match = Match.query.get_or_404(match_id)
    match.home_team_message_id = home_message_id
    match.away_team_message_id = away_message_id
    db.session.commit()

    return jsonify({"message": "Message IDs stored successfully"}), 200

@availability_bp.route('/get_match_id_from_message/<string:message_id>', methods=['GET'])
def get_match_id_from_message(message_id):
    match = Match.query.filter(
        (Match.home_team_message_id == message_id) | 
        (Match.away_team_message_id == message_id)
    ).first()

    if match:
        return jsonify({"match_id": match.id}), 200
    else:
        return jsonify({"error": "Match not found"}), 404
