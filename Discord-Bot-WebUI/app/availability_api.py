# app/availability_api.py

"""
Availability API Module

This module defines endpoints for managing match availability, including:
- Scheduling availability polls
- Retrieving and updating match availability
- Storing and fetching message IDs associated with scheduled messages
- Syncing match RSVP data with external systems (Discord, frontend)
- Other utilities related to availability data management
"""

import os
import logging
import ipaddress

# Third-party imports
from flask import Blueprint, request, jsonify, abort, g, current_app
from flask_login import login_required

# Local application imports
from app import csrf
from app.core import celery
from app.models import Match, Availability, Team, Player, ScheduledMessage, User
from app.tasks.tasks_rsvp import (
    notify_discord_of_rsvp_change_task,
    notify_frontend_of_rsvp_change_task,
    update_rsvp
)
from app.tasks.tasks_match_updates import fetch_match_and_team_id_task
from app.availability_api_helpers import (
    validate_date,
    validate_time,
    get_availability_results,
    store_message_ids_for_match,
    get_match_rsvp_data,
    process_availability_update,
    get_message_data,
    get_match_request_data,
    update_discord_rsvp,
    verify_availability_data
)

logger = logging.getLogger(__name__)
availability_bp = Blueprint('availability_api', __name__)
csrf.exempt(availability_bp)


@availability_bp.before_request
def limit_remote_addr():
    """
    Restrict API access to allowed hosts and mobile devices.
    
    This function allows access from:
    1. Specific hosts in the allowed_hosts list
    2. IP ranges using CIDR notation (e.g., local network)
    3. Mobile devices with valid API key
    """
    allowed_hosts = [
        # Server and development hosts
        '127.0.0.1:5000', 
        'localhost:5000', 
        'webui:5000',
        '192.168.1.112:5000',
        
        # Mobile development
        '10.0.2.2:5000',      # Android emulator default
        '192.168.1.0/24',     # Local network (allows any IP in this range)
        '192.168.0.0/24',     # Alternative local network
    ]
    
    # Check if host is in the allowed hosts list (direct match)
    if request.host in allowed_hosts:
        return
    
    # Check IP ranges (CIDR notation)
    client_ip = request.host.split(':')[0]  # Remove port if present
    for allowed in allowed_hosts:
        if '/' in allowed:  # This is a CIDR notation
            try:
                network = ipaddress.ip_network(allowed)
                if ipaddress.ip_address(client_ip) in network:
                    return
            except (ValueError, ipaddress.AddressValueError):
                # Skip invalid IP addresses or networks
                continue
    
    # Check for API key in headers (for mobile app)
    api_key = request.headers.get('X-API-Key')
    if api_key and api_key == current_app.config.get('MOBILE_API_KEY', 'ecs-soccer-mobile-key'):
        return
    
    # If we get here, access is denied
    logger.warning(f"API access denied for host: {request.host}")
    return "Access Denied", 403


@availability_bp.route('/schedule_availability_poll', methods=['POST'], endpoint='schedule_availability_poll')
def schedule_availability_poll():
    """
    Schedule an availability poll for a match.
    
    Expects JSON with required fields:
        - match_id
        - match_date (validated via validate_date)
        - match_time (validated via validate_time)
        - team_id
    """
    logger.debug("Endpoint hit: /schedule_availability_poll")
    session_db = g.db_session
    data = request.json

    required_fields = ['match_id', 'match_date', 'match_time', 'team_id']
    if not all(data.get(field) for field in required_fields):
        logger.error("Missing required data")
        return jsonify({"error": "Missing required data"}), 400

    if not validate_date(data['match_date']) or not validate_time(data['match_time']):
        logger.error("Invalid date or time format")
        return jsonify({"error": "Invalid date or time format"}), 400

    match = session_db.query(Match).get(data['match_id'])
    if not match:
        abort(404)

    team = session_db.query(Team).get(data['team_id'])
    if not team:
        abort(404)

    return jsonify({
        "message": "Poll scheduled successfully",
        "match_id": match.id
    }), 200


@availability_bp.route('/match_availability/<int:match_id>', methods=['GET'], endpoint='get_match_availability')
def get_match_availability(match_id):
    """
    Retrieve availability results for a given match.
    """
    session_db = g.db_session
    match = session_db.query(Match).get(match_id)
    if not match:
        abort(404)

    results = get_availability_results(match_id, session=session_db)
    return jsonify({
        "match_id": match.id,
        "availability": results
    }), 200


@availability_bp.route('/update_availability', methods=['POST'], endpoint='update_availability')
def update_availability():
    """
    Update availability based on data received from Discord.

    Expects JSON with:
        - match_id
        - discord_id
        - response
    """
    session_db = g.db_session
    data = request.json
    logger.info(f"Received data from Discord: {data}")

    required_fields = ['match_id', 'discord_id', 'response']
    if not all(data.get(field) for field in required_fields):
        logger.error("Missing required data")
        return jsonify({"error": "Invalid data"}), 400

    player, message = process_availability_update(
        match_id=data['match_id'],
        discord_id=data['discord_id'],
        response=data['response'],
        session=session_db
    )

    if not player:
        logger.error(f"Player with Discord ID {data['discord_id']} not found")
        return jsonify({"error": "Player not found"}), 404

    # Trigger notifications
    notify_discord_of_rsvp_change_task.delay(data['match_id'])
    notify_frontend_of_rsvp_change_task.delay(data['match_id'], player.id, data['response'])

    return jsonify({"message": "Availability updated successfully"}), 200


@availability_bp.route('/store_message_ids', methods=['POST'], endpoint='store_message_ids')
def store_message_ids():
    """
    Store message IDs for a match's scheduled messages.
    
    Expects JSON with:
        - match_id
        - home_channel_id
        - home_message_id
        - away_channel_id
        - away_message_id
    """
    session_db = g.db_session
    try:
        data = request.json
        required_fields = [
            'match_id', 'home_channel_id', 'home_message_id',
            'away_channel_id', 'away_message_id'
        ]
        if not all(field in data for field in required_fields):
            logger.error("Missing required data for message IDs")
            return jsonify({"error": "Missing required fields"}), 400

        message, status = store_message_ids_for_match(
            match_id=data['match_id'],
            home_channel_id=data['home_channel_id'],
            home_message_id=data['home_message_id'],
            away_channel_id=data['away_channel_id'],
            away_message_id=data['away_message_id'],
            session=session_db
        )

        if not message:
            return jsonify({"error": status}), 400

        return jsonify({"message": status}), 200

    except Exception as e:
        logger.error(f"Error storing message IDs: {str(e)}")
        return jsonify({"error": str(e)}), 500


@availability_bp.route('/get_match_id_from_message/<string:message_id>', methods=['GET'], endpoint='get_match_id_from_message')
def get_match_id_from_message(message_id):
    """
    Retrieve a match ID based on a given message ID.
    """
    session_db = g.db_session
    scheduled_message = session_db.query(ScheduledMessage).filter(
        (ScheduledMessage.home_message_id == message_id) |
        (ScheduledMessage.away_message_id == message_id)
    ).first()

    if not scheduled_message:
        return jsonify({'error': 'Match not found'}), 404

    return jsonify({
        'match_id': scheduled_message.match_id
    }), 200


@availability_bp.route('/update_availability_web', methods=['POST'], endpoint='update_availability_web')
@login_required
def update_availability_web():
    """
    Update a player's availability via the web interface.
    
    Expects JSON with:
        - match_id
        - player_id
        - response
    """
    data = request.json
    logger.info(f"Received web update data: {data}")

    required_fields = ['match_id', 'player_id', 'response']
    if not all(data.get(field) for field in required_fields):
        logger.error("Missing required data")
        return jsonify({"error": "Invalid data"}), 400

    # Get the player record to check for discord_id
    session_db = g.db_session
    player = session_db.query(Player).get(data['player_id'])
    discord_id = None
    
    if player:
        discord_id = player.discord_id
        logger.info(f"Found player with discord_id: {discord_id}")
    
    # Update RSVP in the database
    success, message = update_rsvp(
        data['match_id'],
        data['player_id'],
        data['response'],
        discord_id=discord_id,
        session=session_db
    )

    if not success:
        logger.error("Failed to update availability")
        return jsonify({"error": "Failed to update availability"}), 500
    
    # Always notify Discord of the change to update embeds
    notify_discord_of_rsvp_change_task.delay(data['match_id'])
    
    # If we have a discord_id, also update the reaction
    if discord_id:
        try:
            # Instead of creating a new task, make sure the existing update_rsvp task will handle this
            # The changes in tasks_rsvp.py will take care of updating the Discord reaction
            logger.info(f"Discord ID found, update will include Discord reaction for user {discord_id}")
        except Exception as e:
            logger.error(f"Error queueing Discord reaction update: {str(e)}")
    
    return jsonify({"message": message}), 200


@availability_bp.route('/sync_match_rsvps/<int:match_id>', methods=['POST'], endpoint='sync_match_rsvps')
@login_required
def sync_match_rsvps(match_id):
    """
    Sync match RSVPs to update Discord and frontend data.
    """
    session_db = g.db_session
    try:
        match = session_db.query(Match).get(match_id)
        if not match:
            abort(404)

        availabilities = session_db.query(Availability).filter_by(match_id=match_id).all()

        for availability in availabilities:
            if availability.player.discord_id:
                result = update_discord_rsvp(
                    match=match,
                    player=availability.player,
                    new_response=availability.response,
                    old_response=None,
                    session=session_db
                )
                if result['status'] != 'success':
                    logger.error(f"Failed to update Discord RSVP for player {availability.player_id}")
            else:
                logger.info(f"Player {availability.player_id} has no Discord account; skipping update.")

        return jsonify({"message": "Match RSVPs synced successfully"}), 200

    except Exception as e:
        logger.error(f"Error syncing match RSVPs: {str(e)}")
        return jsonify({"error": "Internal Server Error"}), 500


@availability_bp.route('/get_match_rsvps/<int:match_id>', methods=['GET'], endpoint='get_match_rsvps')
def get_match_rsvps(match_id):
    """
    Retrieve RSVP data for a match.

    Optionally filters by team_id provided as a query parameter.
    """
    session_db = g.db_session
    team_id = request.args.get('team_id', type=int)
    logger.debug(f"Fetching RSVPs for match_id={match_id}, team_id={team_id}")

    verify_availability_data(match_id, team_id, session=session_db)
    rsvp_data = get_match_rsvp_data(match_id, team_id, session=session_db)
    logger.debug(f"Returning RSVP data: {rsvp_data}")
    return jsonify(rsvp_data), 200


@availability_bp.route('/update_availability_from_discord', methods=['POST'], endpoint='update_availability_from_discord')
def update_availability_from_discord():
    """
    Update availability data based on information received from Discord.

    Expects JSON with:
        - match_id
        - discord_id
        - response
        - optionally, responded_at
    """
    session_db = g.db_session
    try:
        data = request.json
        logger.info(f"Received data from Discord: {data}")

        required_fields = ['match_id', 'discord_id', 'response']
        if not all(field in data for field in required_fields):
            logger.error("Missing required fields")
            return jsonify({
                'status': 'error',
                'error': 'Missing required fields'
            }), 400

        player_id, result = process_availability_update(
            match_id=data['match_id'],
            discord_id=str(data['discord_id']),
            response=data['response'],
            responded_at=data.get('responded_at'),
            session=session_db
        )

        if not player_id:
            logger.error(f"No player found for discord_id {data['discord_id']}")
            return jsonify({
                'status': 'error',
                'error': result.get('message', 'Player not found')
            }), 404

        if data['response'] != 'no_response':
            notify_discord_of_rsvp_change_task.delay(data['match_id'])
            notify_frontend_of_rsvp_change_task.delay(data['match_id'], player_id, data['response'])

        return jsonify({
            'status': 'success',
            'message': result.get('message', 'Update successful')
        }), 200

    except Exception as e:
        logger.error(f"Error in update_availability_from_discord: {str(e)}", exc_info=True)
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


@availability_bp.route('/get_message_ids/<int:match_id>', methods=['GET'], endpoint='get_message_ids')
def get_message_ids(match_id):
    """
    Retrieve message IDs associated with a match.
    """
    session_db = g.db_session
    logger.info(f"Received request for message IDs for match_id {match_id}")
    message_data = get_message_data(match_id, session=session_db)
    if not message_data:
        logger.warning(f"No scheduled message found for match_id {match_id}")
        return jsonify({'error': 'No scheduled message found'}), 404
    logger.info(f"Returning message data for match_id {match_id}: {message_data}")
    return jsonify(message_data), 200


@availability_bp.route('/get_match_and_team_id_from_message', methods=['GET'], endpoint='get_match_and_team_id_from_message')
def get_match_and_team_id_from_message():
    """
    Retrieve match and team IDs based on a provided message_id and channel_id.
    """
    try:
        message_id = request.args.get('message_id')
        channel_id = request.args.get('channel_id')
        logger.debug(f"Received request with message_id: {message_id}, channel_id: {channel_id}")

        if not message_id or not channel_id:
            logger.error("Missing required parameters")
            return jsonify({
                'status': 'error',
                'error': 'Missing required parameters'
            }), 400

        task = fetch_match_and_team_id_task.apply_async(
            kwargs={
                'message_id': message_id,
                'channel_id': channel_id
            }
        )

        try:
            result = task.get(timeout=10)
            logger.debug(f"Task result received: {result}")

            if not isinstance(result, dict):
                logger.error(f"Unexpected result format: {result}")
                return jsonify({
                    'status': 'error',
                    'error': 'Invalid result format'
                }), 500

            # Check for 'success' key as per fetch_match_and_team_id_task implementation
            if 'success' in result:
                if result['success']:
                    # Format the response to match API expectations
                    response = {
                        'status': 'success',
                        'data': {
                            'match_id': result.get('match_id'),
                            'team_id': result.get('team_id')
                        }
                    }
                    return jsonify(response), 200
                else:
                    error_msg = result.get('message', 'Unknown error')
                    logger.error(f"Task returned error: {error_msg}")
                    
                    response = {
                        'status': 'error',
                        'error': error_msg
                    }
                    
                    if 'not found' in error_msg.lower():
                        return jsonify(response), 404
                    else:
                        return jsonify(response), 500
            else:
                # Legacy format check (status key)
                status = result.get('status')
                if status == 'success':
                    data = result.get('data')
                    if not data:
                        logger.error("No data in success response")
                        return jsonify({
                            'status': 'error',
                            'error': 'No data in response'
                        }), 500
                    return jsonify(result), 200
                elif status == 'error':
                    error_msg = result.get('message', 'Unknown error')
                    logger.error(f"Task returned error: {error_msg}")
                    if 'not found' in error_msg.lower():
                        return jsonify(result), 404
                    else:
                        return jsonify(result), 500
                else:
                    logger.error(f"Unknown status in result: {status}")
                    return jsonify({
                        'status': 'error', 
                        'error': 'Unknown response status'
                    }), 500

        except TimeoutError:
            logger.error("Task timed out")
            return jsonify({
                'status': 'error',
                'error': 'Task timed out'
            }), 504

    except Exception as e:
        error_msg = (f"Failed to process request for message_id: {request.args.get('message_id')}, "
                     f"channel_id: {request.args.get('channel_id')}. Error: {str(e)}")
        logger.error(error_msg, exc_info=True)
        return jsonify({
            'status': 'error',
            'error': error_msg
        }), 500


@availability_bp.route('/is_user_on_team', methods=['POST'], endpoint='is_user_on_team')
def is_user_on_team():
    """
    Check if a user (by Discord ID) is a member of a specific team.

    Expects JSON with:
        - discord_id
        - team_id
    """
    session_db = g.db_session
    data = request.json
    discord_id = data.get('discord_id')
    team_id = data.get('team_id')

    if not discord_id or not team_id:
        return jsonify({'error': 'Missing required fields'}), 400

    player = session_db.query(Player).filter_by(discord_id=str(discord_id)).first()
    
    # Check if player exists and if they're on the specified team
    is_team_member = False
    if player:
        # Use the teams relationship to check if the player is on the team
        team_ids = [team.id for team in player.teams]
        is_team_member = int(team_id) in team_ids
        logger.debug(f"Player {player.id} teams: {team_ids}, checking team_id: {team_id}, is_member: {is_team_member}")
    
    return jsonify({
        'is_team_member': is_team_member
    }), 200


@availability_bp.route('/get_scheduled_messages', methods=['GET'])
def get_scheduled_messages():
    """
    Retrieve all scheduled messages along with associated match and team IDs.
    """
    from app.core.session_manager import managed_session

    with managed_session() as session_db:
        messages = (
            session_db.query(
                ScheduledMessage.match_id,
                ScheduledMessage.home_channel_id,
                ScheduledMessage.home_message_id,
                ScheduledMessage.away_channel_id,
                ScheduledMessage.away_message_id,
                Match.home_team_id,
                Match.away_team_id
            )
            .join(Match, Match.id == ScheduledMessage.match_id)
            .all()
        )

    messages_data = [{
        'match_id': m.match_id,
        'home_channel_id': m.home_channel_id,
        'home_message_id': m.home_message_id,
        'away_channel_id': m.away_channel_id,
        'away_message_id': m.away_message_id,
        'home_team_id': m.home_team_id,
        'away_team_id': m.away_team_id
    } for m in messages]

    return jsonify(messages_data), 200


@availability_bp.route('/get_player_id_from_discord/<string:discord_id>', methods=['GET'])
def get_player_id_from_discord(discord_id):
    """
    Retrieve a player's ID and basic profile data based on their Discord ID.
    """
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


@availability_bp.route('/task_status/<task_id>', methods=['GET'], endpoint='task_status')
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


@availability_bp.route('/get_match_request/<int:match_id>', methods=['GET'], endpoint='get_match_request')
def get_match_request(match_id):
    """
    Retrieve match request data for a specific match.
    """
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