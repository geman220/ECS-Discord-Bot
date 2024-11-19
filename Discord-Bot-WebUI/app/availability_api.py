from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required
from app import csrf
from app.core import celery
from app.models import Match, Availability, Team, Player, ScheduledMessage
from app.decorators import handle_db_operation, query_operation
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
import logging

logger = logging.getLogger(__name__)
availability_bp = Blueprint('availability_api', __name__)
csrf.exempt(availability_bp)

@availability_bp.before_request
def limit_remote_addr():
    allowed_hosts = ['127.0.0.1:5000', 'localhost:5000', 'webui:5000']
    if request.host not in allowed_hosts:
        return "Access Denied", 403

@availability_bp.route('/schedule_availability_poll', endpoint='schedule_availability_poll', methods=['POST'])
@handle_db_operation()
def schedule_availability_poll():
    logger.debug("Endpoint hit: /api/schedule_availability_poll")
    data = request.json
    required_fields = ['match_id', 'match_date', 'match_time', 'team_id']
    
    if not all(data.get(field) for field in required_fields):
        logger.error("Missing required data")
        return jsonify({"error": "Missing required data"}), 400
        
    if not validate_date(data['match_date']) or not validate_time(data['match_time']):
        logger.error("Invalid date or time format")
        return jsonify({"error": "Invalid date or time format"}), 400

    match = Match.query.get_or_404(data['match_id'])
    team = Team.query.get_or_404(data['team_id'])

    return jsonify({
        "message": "Poll scheduled successfully",
        "match_id": match.id
    }), 200

@availability_bp.route('/match_availability/<int:match_id>', endpoint='get_match_availability', methods=['GET'])
@query_operation
def get_match_availability(match_id):
    match = Match.query.get_or_404(match_id)
    results = get_availability_results(match_id)
    return jsonify({
        "match_id": match.id,
        "availability": results
    }), 200

@availability_bp.route('/update_availability', endpoint='update_availability', methods=['POST'])
@handle_db_operation()
def update_availability():
    data = request.json
    logger.info(f"Received data from Discord: {data}")
    
    required_fields = ['match_id', 'discord_id', 'response']
    if not all(data.get(field) for field in required_fields):
        logger.error("Missing required data")
        return jsonify({"error": "Invalid data"}), 400

    player, message = process_availability_update(
        match_id=data['match_id'],
        discord_id=data['discord_id'],
        response=data['response']
    )

    if not player:
        logger.error(f"Player with Discord ID {data['discord_id']} not found")
        return jsonify({"error": "Player not found"}), 404

    notify_discord_of_rsvp_change_task.delay(data['match_id'])
    notify_frontend_of_rsvp_change_task.delay(data['match_id'], player.id, data['response'])

    return jsonify({"message": "Availability updated successfully"}), 200

@availability_bp.route('/store_message_ids', endpoint='store_message_ids', methods=['POST'])
@handle_db_operation()
def store_message_ids():
    """Store message IDs with validation"""
    try:
        data = request.json
        required_fields = [
            'match_id', 'home_channel_id', 'home_message_id',
            'away_channel_id', 'away_message_id'
        ]
        
        if not all(field in data for field in required_fields):
            logger.error("Missing required data for message IDs")
            return jsonify({"error": "Missing required fields"}), 400

        message, status = store_message_ids_for_match(**{
            field: data[field] for field in required_fields
        })
        
        if not message:
            return jsonify({"error": status}), 400
            
        return jsonify({"message": status}), 200
        
    except Exception as e:
        logger.error(f"Error storing message IDs: {str(e)}")
        return jsonify({"error": str(e)}), 500

@availability_bp.route('/get_match_id_from_message/<string:message_id>', endpoint='get_match_id_from_message', methods=['GET'])
@query_operation
def get_match_id_from_message(message_id):
   scheduled_message = ScheduledMessage.query.filter(
       (ScheduledMessage.home_message_id == message_id) |
       (ScheduledMessage.away_message_id == message_id)
   ).first()
   
   if not scheduled_message:
       return jsonify({'error': 'Match not found'}), 404
   
   return jsonify({
       'match_id': scheduled_message.match_id
   }), 200

@availability_bp.route('/update_availability_web', endpoint='update_availability_web', methods=['POST'])
@login_required
@handle_db_operation()
def update_availability_web():
   data = request.json
   logger.info(f"Received web update data: {data}")
   
   required_fields = ['match_id', 'player_id', 'response']
   if not all(data.get(field) for field in required_fields):
       logger.error("Missing required data")
       return jsonify({"error": "Invalid data"}), 400
   
   success, message = update_rsvp(
       data['match_id'],
       data['player_id'], 
       data['response']
   )
   
   if success:
       return jsonify({"message": message}), 200
   return jsonify({"error": "Failed to update availability"}), 500

@availability_bp.route('/sync_match_rsvps/<int:match_id>', endpoint='sync_match_rsvps', methods=['POST'])
@login_required
@handle_db_operation()
def sync_match_rsvps(match_id):
    try:
        match = Match.query.get_or_404(match_id)
        availabilities = Availability.query.filter_by(match_id=match_id).all()

        for availability in availabilities:
            if availability.player.discord_id:
                result = update_discord_rsvp(
                    match=match,
                    player=availability.player,
                    new_response=availability.response,
                    old_response=None
                )
                if result['status'] != 'success':
                    logger.error(f"Failed to update Discord RSVP for player {availability.player_id}")
            else:
                logger.info(f"Player {availability.player_id} doesn't have a Discord account. Skipping Discord update.")

        return jsonify({"message": "Match RSVPs synced successfully"}), 200
    except Exception as e:
        logger.error(f"Error syncing match RSVPs: {str(e)}")
        return jsonify({"error": "Internal Server Error"}), 500

@availability_bp.route('/get_match_rsvps/<int:match_id>', endpoint='get_match_rsvps', methods=['GET'])
@query_operation
def get_match_rsvps(match_id):
    """Get match RSVPs with error handling"""
    team_id = request.args.get('team_id', type=int)
    logger.debug(f"Fetching RSVPs for match_id={match_id}, team_id={team_id}")
    
    # First verify the data state
    verify_availability_data(match_id, team_id)
    
    # Get the RSVP data
    rsvp_data = get_match_rsvp_data(match_id, team_id)
    
    # Log the final response
    logger.debug(f"Returning RSVP data: {rsvp_data}")
    return jsonify(rsvp_data), 200

@availability_bp.route('/update_availability_from_discord', endpoint='update_availability_from_discord', methods=['POST'])
@handle_db_operation()
def update_availability_from_discord():
    """Update availability from Discord webhook."""
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
            discord_id=str(data['discord_id']),  # Ensure discord_id is string
            response=data['response'],
            responded_at=data.get('responded_at')
        )

        if not player_id:
            logger.error(f"No player found for discord_id {data['discord_id']}")
            return jsonify({
                'status': 'error',
                'error': result.get('message', 'Player not found')
            }), 404

        # Queue the notification tasks
        if data['response'] != 'no_response':
            notify_discord_of_rsvp_change_task.delay(data['match_id'])
            notify_frontend_of_rsvp_change_task.delay(
                data['match_id'],
                player_id,
                data['response']
            )

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

@availability_bp.route('/get_message_ids/<int:match_id>', endpoint='get_message_ids', methods=['GET'])
@query_operation
def get_message_ids(match_id):
    logger.info(f"Received request for message IDs for match_id {match_id}")
    message_data = get_message_data(match_id)
    if not message_data:
        logger.warning(f"No scheduled message found for match_id {match_id}")
        return jsonify({'error': 'No scheduled message found'}), 404
    logger.info(f"Returning message data for match_id {match_id}: {message_data}")
    return jsonify(message_data), 200

@availability_bp.route('/get_match_and_team_id_from_message', endpoint='get_match_and_team_id_from_message', methods=['GET'])
@query_operation
def get_match_and_team_id_from_message():
    """Get match and team ID from message details."""
    try:
        # Retrieve message_id and channel_id from request
        message_id = request.args.get('message_id')
        channel_id = request.args.get('channel_id')
        
        logger.debug(f"Received request with message_id: {message_id}, channel_id: {channel_id}")
        
        # Check for missing parameters
        if not message_id or not channel_id:
            logger.error("Missing required parameters")
            return jsonify({
                'status': 'error',
                'error': 'Missing required parameters'
            }), 400
            
        # Call the Celery task asynchronously
        task = fetch_match_and_team_id_task.apply_async(
            kwargs={
                'message_id': message_id,
                'channel_id': channel_id
            }
        )
        
        try:
            # Fetch result from the task with a timeout
            result = task.get(timeout=10)
            logger.debug(f"Task result received: {result}")

            # Ensure result is in expected format
            if not isinstance(result, dict):
                logger.error(f"Unexpected result format: {result}")
                return jsonify({
                    'status': 'error',
                    'error': 'Invalid result format'
                }), 500

            # Handle result based on the 'status' field
            status = result.get('status')
            if status == 'success':
                data = result.get('data')
                if not data:
                    logger.error("No data in success response")
                    return jsonify({
                        'status': 'error',
                        'error': 'No data in response'
                    }), 500
                    
                # Return success response with data
                return jsonify(result), 200
                
            elif status == 'error':
                error_msg = result.get('message', 'Unknown error')
                logger.error(f"Task returned error: {error_msg}")
                # Return 404 if error message indicates not found, else 500
                return jsonify(result), 404 if 'not found' in error_msg.lower() else 500
                
            else:
                logger.error(f"Unknown status in result: {status}")
                return jsonify({
                    'status': 'error',
                    'error': 'Unknown response status'
                }), 500

        except TimeoutError:
            # Handle task timeout
            logger.error("Task timed out")
            return jsonify({
                'status': 'error',
                'error': 'Task timed out'
            }), 504
            
    except Exception as e:
        # Handle unexpected exceptions
        error_msg = f"Failed to process request for message_id: {message_id}, channel_id: {channel_id}. Error: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return jsonify({
            'status': 'error',
            'error': error_msg
        }), 500

@availability_bp.route('/is_user_on_team', endpoint='is_user_on_team', methods=['POST'])
@query_operation
def is_user_on_team():
   data = request.json
   discord_id = data.get('discord_id')
   team_id = data.get('team_id')

   if not discord_id or not team_id:
       return jsonify({'error': 'Missing required fields'}), 400

   player = Player.query.filter_by(discord_id=str(discord_id)).first()
   return jsonify({
       'is_team_member': bool(player and player.team_id == team_id)
   }), 200

@availability_bp.route('/get_scheduled_messages', endpoint='get_scheduled_messages', methods=['GET'])
@query_operation
def get_scheduled_messages():
   messages = (
       ScheduledMessage.query
       .join(Match)
       .with_entities(
           ScheduledMessage.match_id,
           ScheduledMessage.home_channel_id,
           ScheduledMessage.home_message_id,
           ScheduledMessage.away_channel_id,
           ScheduledMessage.away_message_id,
           Match.home_team_id,
           Match.away_team_id
       )
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

@availability_bp.route('/get_player_id_from_discord/<string:discord_id>', endpoint='get_player_id_from_discord', methods=['GET'])
@query_operation
def get_player_id_from_discord(discord_id):
   player = Player.query.filter_by(discord_id=discord_id).first()
   if not player:
       return jsonify({'error': 'Player not found'}), 404
   return jsonify({
       'player_id': player.id, 
       'team_id': player.team_id
   }), 200

@availability_bp.route('/task_status/<task_id>', endpoint='task_status', methods=['GET'])
def task_status(task_id):
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

@availability_bp.route('/get_match_request/<int:match_id>', endpoint='get_match_request', methods=['GET'])
@query_operation
def get_match_request(match_id):
   match_data = get_match_request_data(match_id)
   if not match_data:
       return jsonify({'error': 'Match not found'}), 404
   return jsonify(match_data), 200

def _get_task_status(task):
   if task.state == 'PENDING':
       return 'Pending...'
   elif task.state == 'SUCCESS':
       return task.result
   elif task.state == 'FAILURE':
       return str(task.info)
   return 'In progress...'
