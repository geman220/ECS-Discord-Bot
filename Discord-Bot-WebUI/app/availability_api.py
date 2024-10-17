#availability_api.py

from app import csrf, socketio, celery
from flask import Blueprint, request, jsonify, current_app as app
from flask_login import login_required, current_user
from app import db
from app.celery import celery
from app.models import Match, Availability, Team, Player, ScheduledMessage
from datetime import datetime
from app.tasks import update_discord_rsvp_task, fetch_match_and_team_id_task, notify_discord_of_rsvp_change_task, notify_frontend_of_rsvp_change_task, update_rsvp
from concurrent.futures import ThreadPoolExecutor
import asyncio
import aiohttp
import logging
import re
import requests

logger = logging.getLogger(__name__)

availability_bp = Blueprint('availability_api', __name__)
csrf.exempt(availability_bp)
executor = ThreadPoolExecutor()

def validate_date(date_text):
    try:
        datetime.strptime(date_text, '%Y-%m-%d')
        return True
    except ValueError:
        return False

def validate_time(time_text):
    return re.match(r"^\d{2}:\d{2}(:\d{2})?$", time_text) is not None

async def send_discord_rsvp_update(bot_api_url, data):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(bot_api_url, json=data) as response:
                if response.status != 200:
                    logger.error(f"Failed to update Discord RSVP. Status: {response.status}, Response: {await response.text()}")
                    return {"status": "error", "message": "Failed to update Discord RSVP."}
                logger.info("Discord RSVP update successful")
                return {"status": "success", "message": "RSVP recorded; Discord update successful."}
    except aiohttp.ClientError as e:
        logger.error(f"Failed to update Discord RSVP: {str(e)}")
        return {"status": "error", "message": f"Failed to update Discord RSVP: {str(e)}"}

async def update_discord_rsvp(match, player, new_response, old_response):
    scheduled_message = ScheduledMessage.query.filter_by(match_id=match.id).first()  
    if not scheduled_message:
        app.logger.debug(f"No scheduled message found for match {match.id}")
        return {"status": "success", "message": "RSVP recorded; Discord messages do not exist yet."}

    message_ids = []
    if scheduled_message.home_message_id and scheduled_message.home_channel_id:
        message_ids.append(f"{scheduled_message.home_channel_id}-{scheduled_message.home_message_id}")
    if scheduled_message.away_message_id and scheduled_message.away_channel_id:
        message_ids.append(f"{scheduled_message.away_channel_id}-{scheduled_message.away_message_id}")

    if not message_ids:
        app.logger.debug(f"No Discord messages to update for match {match.id}")
        return {"status": "success", "message": "RSVP recorded; Discord messages do not exist yet."}

    data = {
        "match_id": match.id,
        "discord_id": player.discord_id,
        "new_response": new_response,
        "old_response": old_response,
        "message_ids": message_ids
    }

    # Use Celery to handle the task asynchronously
    update_discord_rsvp_task.delay(data)

    return {"status": "success", "message": "RSVP update task queued"}

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
    app.logger.info(f"Received data from Discord: {data}")

    match_id = data.get('match_id')
    discord_id = data.get('discord_id')
    response = data.get('response')

    if not all([match_id, discord_id, response]):
        app.logger.error("Invalid data received from Discord")
        return jsonify({"error": "Invalid data"}), 400

    try:
        match = Match.query.get_or_404(match_id)
        player = Player.query.filter_by(discord_id=discord_id).first_or_404()

        availability = Availability.query.filter_by(match_id=match_id, player_id=player.id).first()
        
        if response == 'no_response':
            if availability:
                db.session.delete(availability)
                app.logger.info("Removed availability entry due to no response")
        else:
            if not availability:
                availability = Availability(match_id=match_id, player_id=player.id, discord_id=player.discord_id, response=response)
                db.session.add(availability)
                app.logger.info("Created new availability entry")
            else:
                availability.response = response
                app.logger.info("Updated existing availability entry")

        db.session.commit()
        app.logger.info("Availability updated successfully from Discord")

        return jsonify({"message": "Availability updated successfully"}), 200

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error updating availability from Discord: {str(e)}")
        return jsonify({"error": "Internal Server Error"}), 500

@availability_bp.route('/store_message_ids', methods=['POST'])
def store_message_ids():
    data = request.json
    app.logger.debug(f"Received data to store message IDs: {data}")
    match_id = data.get('match_id')
    home_channel_id = data.get('home_channel_id')
    home_message_id = data.get('home_message_id')
    away_channel_id = data.get('away_channel_id')
    away_message_id = data.get('away_message_id')

    if not all([match_id, home_channel_id, home_message_id, away_channel_id, away_message_id]):
        app.logger.error("Invalid data received for storing message IDs")
        return jsonify({"error": "Invalid data"}), 400

    try:
        scheduled_message = ScheduledMessage.query.filter_by(match_id=match_id).first()
        if not scheduled_message:
            scheduled_message = ScheduledMessage(match_id=match_id)
            db.session.add(scheduled_message)
            app.logger.debug("Created new ScheduledMessage entry")

        scheduled_message.home_channel_id = home_channel_id
        scheduled_message.home_message_id = home_message_id
        scheduled_message.away_channel_id = away_channel_id
        scheduled_message.away_message_id = away_message_id
        db.session.commit()
        app.logger.info(f"Message IDs stored successfully for match_id: {match_id}")

        return jsonify({"message": "Message IDs stored successfully"}), 200
    except Exception as e:
        db.session.rollback()
        app.logger.exception(f"Error storing message IDs: {str(e)}")
        return jsonify({"error": "Internal Server Error"}), 500

@availability_bp.route('/get_match_id_from_message/<string:message_id>', methods=['GET'])
def get_match_id_from_message(message_id):
    try:
        scheduled_message = ScheduledMessage.query.filter(
            (ScheduledMessage.home_message_id == message_id) |
            (ScheduledMessage.away_message_id == message_id)
        ).first()
        if scheduled_message:
            return jsonify({'match_id': scheduled_message.match_id}), 200
        else:
            return jsonify({'error': 'Match not found'}), 404
    except Exception as e:
        app.logger.error(f"Error fetching match ID: {str(e)}")
        return jsonify({"error": "Internal Server Error"}), 500

@availability_bp.route('/update_availability_web', methods=['POST'])
@login_required
def update_availability_web():
    data = request.json
    app.logger.info(f"Received web update data: {data}")
    match_id = data.get('match_id')
    player_id = data.get('player_id')
    new_response = data.get('response')
    
    if not all([match_id, player_id, new_response]):
        app.logger.error("Invalid data received from web")
        return jsonify({"error": "Invalid data"}), 400
    
    success, message = update_rsvp(match_id, player_id, new_response)
    
    if success:
        return jsonify({"message": message}), 200
    else:
        app.logger.error(f"Error updating availability from web: {message}")
        return jsonify({"error": "Internal Server Error"}), 500

@availability_bp.route('/sync_match_rsvps/<int:match_id>', methods=['POST'])
@login_required
def sync_match_rsvps(match_id):
    try:
        match = Match.query.get_or_404(match_id)
        availabilities = Availability.query.filter_by(match_id=match_id).all()

        for availability in availabilities:
            if availability.player.discord_id:
                update_discord_rsvp(match, availability.player, availability.response)
            else:
                app.logger.info(f"Player {availability.player_id} doesn't have a Discord account. Skipping Discord update.")

        return jsonify({"message": "Match RSVPs synced successfully"}), 200
    except Exception as e:
        app.logger.error(f"Error syncing match RSVPs: {str(e)}")
        return jsonify({"error": "Internal Server Error"}), 500

@availability_bp.route('get_match_rsvps/<int:match_id>', methods=['GET'])
def get_match_rsvps(match_id):
    team_id = request.args.get('team_id', type=int)
    app.logger.debug(f"Fetching RSVPs for match_id={match_id}, team_id={team_id}")

    try:
        query = db.session.query(
            Availability.response, Player.name
        ).join(Player).filter(
            Availability.match_id == match_id
        )

        if team_id:
            query = query.filter(Player.team_id == team_id)

        availability_records = query.all()

        rsvp_data = {'yes': [], 'no': [], 'maybe': []}
        for response, player_name in availability_records:
            if response in rsvp_data:
                rsvp_data[response].append({'player_name': player_name})

        return jsonify(rsvp_data), 200
    except Exception as e:
        app.logger.exception(f"Error fetching RSVPs: {str(e)}")
        return jsonify({"error": "Internal Server Error"}), 500

@availability_bp.route('/update_availability_from_discord', methods=['POST'])
def update_availability_from_discord():
    # Log request headers and body for debugging purposes
    app.logger.info(f"Request headers: {request.headers}")
    app.logger.info(f"Request body: {request.get_data()}")

    try:
        # Parse the JSON request data
        data = request.get_json()
        app.logger.info(f"Received raw data from Discord: {data}")

        match_id = data.get('match_id')
        discord_id = data.get('discord_id')
        response = data.get('response')
        responded_at = data.get('responded_at')

        app.logger.debug(f"Parsed data - match_id: {match_id}, discord_id: {discord_id}, response: {response}, responded_at: {responded_at}")

        # Validate required fields
        if not all([match_id, discord_id, response]):
            app.logger.error(f"Missing required fields. match_id={match_id}, discord_id={discord_id}, response={response}")
            return jsonify({'error': 'Missing required fields'}), 400

        # Fetch player by Discord ID
        app.logger.info(f"Querying Player with discord_id={discord_id}")
        player = Player.query.filter_by(discord_id=str(discord_id)).first()
        if not player:
            app.logger.error(f"Player with Discord ID {discord_id} not found")
            return jsonify({'error': 'Player not found'}), 404

        # Log player information for debugging purposes
        app.logger.debug(f"Found player: {player}")

        # Fetch availability record for the given match and player
        app.logger.info(f"Querying Availability for match_id={match_id} and player_id={player.id}")
        availability = Availability.query.filter_by(match_id=match_id, player_id=player.id).first()

        # Update or create availability record
        if availability:
            if response == 'no_response':
                db.session.delete(availability)
                app.logger.info(f"Deleted availability for player {player.id} in match {match_id}")
            else:
                old_response = availability.response
                availability.response = response
                availability.responded_at = responded_at
                availability.discord_id = discord_id  # Ensure discord_id is updated properly
                app.logger.info(f"Updated availability for player {player.id} in match {match_id} from {old_response} to {response}")
        else:
            if response != 'no_response':
                availability = Availability(
                    match_id=match_id,
                    player_id=player.id,
                    discord_id=discord_id,  # Assign discord_id correctly when creating a new record
                    response=response,
                    responded_at=responded_at
                )
                db.session.add(availability)
                app.logger.info(f"Created new availability for player {player.id} in match {match_id}: {response}")

        # Log the state of availability before committing
        app.logger.debug(f"Availability record state before commit: {availability}")

        # Commit changes to the database
        db.session.commit()
        app.logger.info(f"Database changes committed successfully for match {match_id}, player {player.id}")

        # Notify Discord and frontend of the changes using Celery
        notify_discord_of_rsvp_change_task.delay(match_id)
        notify_frontend_of_rsvp_change_task.delay(match_id, player.id, response)

        return jsonify({'status': 'success'}), 200

    except Exception as e:
        # Rollback the session in case of an exception and log the error
        db.session.rollback()
        app.logger.exception(f"Error updating availability from Discord for match_id={match_id}, discord_id={discord_id}: {str(e)}")
        return jsonify({'error': 'Internal Server Error'}), 500

@availability_bp.route('/get_message_ids/<int:match_id>', methods=['GET'])
def get_message_ids(match_id):
    try:
        logger.debug(f"Fetching message IDs for match {match_id}")
        scheduled_message = db.session.query(ScheduledMessage).filter_by(match_id=match_id).first()

        if not scheduled_message:
            logger.warning(f"No scheduled message found for match {match_id}")
            return jsonify({'error': 'No scheduled message found for this match'}), 404

        data = {
            'home_message_id': scheduled_message.home_message_id,
            'home_channel_id': scheduled_message.home_channel_id,
            'home_team_id': scheduled_message.match.home_team_id,
            'away_message_id': scheduled_message.away_message_id,
            'away_channel_id': scheduled_message.away_channel_id,
            'away_team_id': scheduled_message.match.away_team_id
        }
        logger.debug(f"Successfully fetched message IDs for match {match_id}: {data}")
        return jsonify(data), 200
    except Exception as e:
        logger.exception(f"Error fetching message IDs for match {match_id}: {str(e)}")
        return jsonify({"error": "Internal Server Error"}), 500

@availability_bp.route('/get_match_and_team_id_from_message', methods=['GET'])
def get_match_and_team_id_from_message():
    message_id = request.args.get('message_id')
    channel_id = request.args.get('channel_id')

    app.logger.info(f"Received request for message_id: {message_id}, channel_id: {channel_id}")

    if not message_id or not channel_id:
        app.logger.error("Missing message_id or channel_id in request")
        return jsonify({'error': 'Missing message_id or channel_id'}), 400

    # Trigger the Celery task
    task = fetch_match_and_team_id_task.delay(message_id, channel_id)

    app.logger.info(f"Task ID {task.id} started to fetch match and team ID")
    return jsonify({'task_id': task.id}), 202

@availability_bp.route('/is_user_on_team', methods=['POST'])
def is_user_on_team():
    data = request.get_json()
    discord_id = data.get('discord_id')
    team_id = data.get('team_id')

    if not discord_id or not team_id:
        return jsonify({'error': 'Missing required fields'}), 400

    try:
        player = Player.query.filter_by(discord_id=str(discord_id)).first()
        if player and player.team_id == team_id:
            return jsonify({'is_team_member': True}), 200
        else:
            return jsonify({'is_team_member': False}), 200
    except Exception as e:
        app.logger.exception(f"Error checking team membership: {str(e)}")
        return jsonify({"error": "Internal Server Error"}), 500

@availability_bp.route('/get_scheduled_messages', methods=['GET'])
def get_scheduled_messages():
    try:
        scheduled_messages = db.session.query(ScheduledMessage).all()
        messages_data = []
        for message in scheduled_messages:
            match = db.session.query(Match).get(message.match_id)
            if match:
                messages_data.append({
                    'match_id': match.id,
                    'home_channel_id': message.home_channel_id,
                    'home_message_id': message.home_message_id,
                    'away_channel_id': message.away_channel_id,
                    'away_message_id': message.away_message_id,
                    'home_team_id': match.home_team_id,
                    'away_team_id': match.away_team_id
                })
        return jsonify(messages_data), 200
    except Exception as e:
        app.logger.exception(f"Error fetching scheduled messages: {str(e)}")
        return jsonify({"error": "Internal Server Error"}), 500

@availability_bp.route('/get_player_id_from_discord/<string:discord_id>', methods=['GET'])
async def get_player_id_from_discord(discord_id):
    try:
        player = await db.session.query(Player).filter_by(discord_id=discord_id).first()
        if player:
            return jsonify({'player_id': player.id, 'team_id': player.team_id}), 200
        else:
            return jsonify({'error': 'Player not found'}), 404
    except Exception as e:
        app.logger.exception(f"Error fetching player info for Discord ID: {str(e)}")
        return jsonify({"error": "Internal Server Error"}), 500

@availability_bp.route('/task_status/<task_id>', methods=['GET'])
def task_status(task_id):
    try:
        task = celery.AsyncResult(task_id)
        if task.state == 'PENDING':
            response = {'state': task.state, 'status': 'Pending...'}
        elif task.state == 'SUCCESS':
            response = {'state': task.state, 'result': task.result}
        elif task.state == 'FAILURE':
            response = {'state': task.state, 'status': str(task.info), 'error': str(task.result)}
        else:
            response = {'state': task.state, 'status': 'In progress...'}
        return jsonify(response)
    except Exception as e:
        app.logger.error(f"Error checking task status: {str(e)}")
        return jsonify({'error': 'Internal Server Error'}), 500

@availability_bp.route('/get_match_request/<int:match_id>', methods=['GET'])
def get_match_request(match_id):
    try:
        match = Match.query.get_or_404(match_id)
        home_team = Team.query.get_or_404(match.home_team_id)
        away_team = Team.query.get_or_404(match.away_team_id)

        match_data = {
            'match_id': match.id,
            'home_team_name': home_team.name,
            'away_team_name': away_team.name,
            'match_date': match.date.strftime('%Y-%m-%d'),
            'match_time': match.time.strftime('%H:%M:%S'),
            'home_team_id': match.home_team_id,
            'away_team_id': match.away_team_id
        }

        return jsonify(match_data), 200
    except Exception as e:
        app.logger.error(f"Error fetching match request data: {str(e)}")
        return jsonify({"error": "Internal Server Error"}), 500