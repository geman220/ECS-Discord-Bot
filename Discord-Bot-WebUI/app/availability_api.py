from flask import Blueprint, request, jsonify, current_app, abort, g
from flask_login import login_required
from app import csrf
from app.core import celery
from app.models import Match, Availability, Team, Player, ScheduledMessage
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
import os
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
def schedule_availability_poll():
    logger.debug("Endpoint hit: /api/schedule_availability_poll")
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

@availability_bp.route('/match_availability/<int:match_id>', endpoint='get_match_availability', methods=['GET'])
def get_match_availability(match_id):
    session_db = g.db_session
    match = session_db.query(Match).get(match_id)
    if not match:
        abort(404)

    results = get_availability_results(match_id, session=session_db)
    return jsonify({
        "match_id": match.id,
        "availability": results
    }), 200

@availability_bp.route('/update_availability', endpoint='update_availability', methods=['POST'])
def update_availability():
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

    notify_discord_of_rsvp_change_task.delay(data['match_id'])
    notify_frontend_of_rsvp_change_task.delay(data['match_id'], player.id, data['response'])

    return jsonify({"message": "Availability updated successfully"}), 200

@availability_bp.route('/store_message_ids', endpoint='store_message_ids', methods=['POST'])
def store_message_ids():
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

@availability_bp.route('/get_match_id_from_message/<string:message_id>', endpoint='get_match_id_from_message', methods=['GET'])
def get_match_id_from_message(message_id):
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

@availability_bp.route('/update_availability_web', endpoint='update_availability_web', methods=['POST'])
@login_required
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
       data['response'],
       session=g.db_session
    )
   
    if success:
       return jsonify({"message": message}), 200
    return jsonify({"error": "Failed to update availability"}), 500

@availability_bp.route('/sync_match_rsvps/<int:match_id>', endpoint='sync_match_rsvps', methods=['POST'])
@login_required
def sync_match_rsvps(match_id):
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
                logger.info(f"Player {availability.player_id} doesn't have a Discord account. Skipping Discord update.")

        return jsonify({"message": "Match RSVPs synced successfully"}), 200
    except Exception as e:
        logger.error(f"Error syncing match RSVPs: {str(e)}")
        return jsonify({"error": "Internal Server Error"}), 500

@availability_bp.route('/get_match_rsvps/<int:match_id>', endpoint='get_match_rsvps', methods=['GET'])
def get_match_rsvps(match_id):
    session_db = g.db_session
    team_id = request.args.get('team_id', type=int)
    logger.debug(f"Fetching RSVPs for match_id={match_id}, team_id={team_id}")
    
    verify_availability_data(match_id, team_id, session=session_db)
    
    rsvp_data = get_match_rsvp_data(match_id, team_id, session=session_db)
    logger.debug(f"Returning RSVP data: {rsvp_data}")
    return jsonify(rsvp_data), 200

@availability_bp.route('/update_availability_from_discord', endpoint='update_availability_from_discord', methods=['POST'])
def update_availability_from_discord():
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
def get_message_ids(match_id):
    session_db = g.db_session
    logger.info(f"Received request for message IDs for match_id {match_id}")
    message_data = get_message_data(match_id, session=session_db)
    if not message_data:
        logger.warning(f"No scheduled message found for match_id {match_id}")
        return jsonify({'error': 'No scheduled message found'}), 404
    logger.info(f"Returning message data for match_id {match_id}: {message_data}")
    return jsonify(message_data), 200

@availability_bp.route('/get_match_and_team_id_from_message', endpoint='get_match_and_team_id_from_message', methods=['GET'])
def get_match_and_team_id_from_message():
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
        error_msg = f"Failed to process request for message_id: {request.args.get('message_id')}, channel_id: {request.args.get('channel_id')}. Error: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return jsonify({
            'status': 'error',
            'error': error_msg
        }), 500

@availability_bp.route('/is_user_on_team', endpoint='is_user_on_team', methods=['POST'])
def is_user_on_team():
   session_db = g.db_session
   data = request.json
   discord_id = data.get('discord_id')
   team_id = data.get('team_id')

   if not discord_id or not team_id:
       return jsonify({'error': 'Missing required fields'}), 400

   player = session_db.query(Player).filter_by(discord_id=str(discord_id)).first()
   return jsonify({
       'is_team_member': bool(player and player.team_id == team_id)
   }), 200

@availability_bp.route('/get_scheduled_messages', endpoint='get_scheduled_messages', methods=['GET'])
def get_scheduled_messages():
   session_db = g.db_session
   messages = (
       session_db.query(ScheduledMessage, Match)
       .join(Match, Match.id == ScheduledMessage.match_id)
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

@availability_bp.route('/get_player_id_from_discord/<string:discord_id>', methods=['GET'])
def get_player_id_from_discord(discord_id):
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
def get_match_request(match_id):
   session_db = g.db_session
   match_data = get_match_request_data(match_id, session=session_db)
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
