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
from datetime import datetime, timedelta

# Third-party imports
from flask import Blueprint, request, jsonify, abort, g, current_app
from flask_login import login_required

# Local application imports
from app import csrf
from app.core import celery, db
from app.core.session_manager import managed_session
from app.models import Match, Availability, Team, Player, ScheduledMessage, User
from app.tasks.tasks_rsvp import (
    notify_discord_of_rsvp_change_task,
    notify_frontend_of_rsvp_change_task,
    update_rsvp,
    force_discord_rsvp_sync
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
    logger.info(f"🔵 [AVAILABILITY_API] schedule_availability_poll called")
    data = request.json
    logger.debug(f"🔵 [AVAILABILITY_API] Request data: {data}")

    required_fields = ['match_id', 'match_date', 'match_time', 'team_id']
    if not all(data.get(field) for field in required_fields):
        logger.error(f"🔴 [AVAILABILITY_API] Missing required data: {data}")
        return jsonify({"error": "Missing required data"}), 400

    if not validate_date(data['match_date']) or not validate_time(data['match_time']):
        logger.error(f"🔴 [AVAILABILITY_API] Invalid date or time format: {data['match_date']}, {data['match_time']}")
        return jsonify({"error": "Invalid date or time format"}), 400

    with managed_session() as session_db:
        logger.debug(f"🔵 [AVAILABILITY_API] Looking up match {data['match_id']} and team {data['team_id']}")
        match = session_db.query(Match).get(data['match_id'])
        if not match:
            logger.warning(f"🟡 [AVAILABILITY_API] Match not found: {data['match_id']}")
            abort(404)

        team = session_db.query(Team).get(data['team_id'])
        if not team:
            logger.warning(f"🟡 [AVAILABILITY_API] Team not found: {data['team_id']}")
            abort(404)

        logger.info(f"🟢 [AVAILABILITY_API] Poll scheduled successfully for match {match.id} ({team.name})")
        return jsonify({
            "message": "Poll scheduled successfully",
            "match_id": match.id
        }), 200


@availability_bp.route('/match_availability/<int:match_id>', methods=['GET'], endpoint='get_match_availability')
def get_match_availability(match_id):
    """
    Retrieve availability results for a given match.
    """
    logger.info(f"🔵 [AVAILABILITY_API] get_match_availability called for match {match_id}")
    
    with managed_session() as session_db:
        logger.debug(f"🔵 [AVAILABILITY_API] Looking up match {match_id}")
        match = session_db.query(Match).get(match_id)
        if not match:
            logger.warning(f"🟡 [AVAILABILITY_API] Match not found: {match_id}")
            abort(404)

        logger.debug(f"🔵 [AVAILABILITY_API] Getting availability results for match {match_id}")
        results = get_availability_results(match_id, session=session_db)
        logger.info(f"🟢 [AVAILABILITY_API] Retrieved availability for match {match_id} - {len(results) if results else 0} responses")
        return jsonify({
            "match_id": match.id,
            "availability": results
        }), 200


@availability_bp.route('/update_availability', methods=['POST'], endpoint='update_availability')
def update_availability():
    """
    DEPRECATED: Legacy availability endpoint - redirects to Enterprise RSVP v2
    
    This endpoint now internally calls the Enterprise RSVP v2 system.

    Expects JSON with:
        - match_id
        - discord_id
        - response
    """
    logger.warning("⚠️ [AVAILABILITY_API] DEPRECATED endpoint called - redirecting to Enterprise RSVP v2")
    
    # Redirect to the Discord legacy handler which already redirects to enterprise
    return update_availability_from_discord()

    required_fields = ['match_id', 'discord_id', 'response']
    if not all(data.get(field) for field in required_fields):
        logger.error(f"🔴 [AVAILABILITY_API] Missing required data: {data}")
        return jsonify({"error": "Invalid data"}), 400

    with managed_session() as session_db:
        logger.debug(f"🔵 [AVAILABILITY_API] Processing availability update for match {data['match_id']}")
        player, message = process_availability_update(
            match_id=data['match_id'],
            discord_id=data['discord_id'],
            response=data['response'],
            session=session_db
        )

        if not player:
            logger.error(f"🔴 [AVAILABILITY_API] Player with Discord ID {data['discord_id']} not found")
            return jsonify({"error": "Player not found"}), 404

        # Trigger notifications
        logger.debug(f"🔵 [AVAILABILITY_API] Triggering notifications for match {data['match_id']}, player {player.id}")
        notify_discord_of_rsvp_change_task.delay(data['match_id'])
        notify_frontend_of_rsvp_change_task.delay(data['match_id'], player.id, data['response'])
        
        # Emit WebSocket event for real-time updates
        from app.sockets.rsvp import emit_rsvp_update
        emit_rsvp_update(
            match_id=data['match_id'],
            player_id=player.id,
            availability=data['response'],
            source='discord',
            player_name=player.name
        )

        logger.info(f"🟢 [AVAILABILITY_API] Availability updated successfully for {player.name} on match {data['match_id']}")
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
    try:
        data = request.json
        logger.info(f"🔵 [AVAILABILITY_API] store_message_ids called for match {data.get('match_id')}")
        
        required_fields = [
            'match_id', 'home_channel_id', 'home_message_id',
            'away_channel_id', 'away_message_id'
        ]
        if not all(field in data for field in required_fields):
            logger.error(f"🔴 [AVAILABILITY_API] Missing required data for message IDs: {data}")
            return jsonify({"error": "Missing required fields"}), 400

        with managed_session() as session_db:
            logger.debug(f"🔵 [AVAILABILITY_API] Storing message IDs for match {data['match_id']}")
            message, status = store_message_ids_for_match(
                match_id=data['match_id'],
                home_channel_id=data['home_channel_id'],
                home_message_id=data['home_message_id'],
                away_channel_id=data['away_channel_id'],
                away_message_id=data['away_message_id'],
                session=session_db
            )

            if not message:
                logger.warning(f"🟡 [AVAILABILITY_API] Failed to store message IDs: {status}")
                return jsonify({"error": status}), 400

            logger.info(f"🟢 [AVAILABILITY_API] Message IDs stored successfully for match {data['match_id']}")
            return jsonify({"message": status}), 200

    except Exception as e:
        logger.error(f"🔴 [AVAILABILITY_API] Error storing message IDs: {str(e)}")
        return jsonify({"error": str(e)}), 500


@availability_bp.route('/get_match_id_from_message/<string:message_id>', methods=['GET'], endpoint='get_match_id_from_message')
def get_match_id_from_message(message_id):
    """
    Retrieve a match ID based on a given message ID.
    """
    logger.info(f"🔵 [AVAILABILITY_API] get_match_id_from_message called for message {message_id}")
    
    with managed_session() as session_db:
        logger.debug(f"🔵 [AVAILABILITY_API] Looking up scheduled message for message_id {message_id}")
        scheduled_message = session_db.query(ScheduledMessage).filter(
            (ScheduledMessage.home_message_id == message_id) |
            (ScheduledMessage.away_message_id == message_id)
        ).first()

        if not scheduled_message:
            logger.warning(f"🟡 [AVAILABILITY_API] No match found for message_id {message_id}")
            return jsonify({'error': 'Match not found'}), 404

        logger.info(f"🟢 [AVAILABILITY_API] Found match {scheduled_message.match_id} for message {message_id}")
        return jsonify({
            'match_id': scheduled_message.match_id
        }), 200


@availability_bp.route('/update_availability_web', methods=['POST'], endpoint='update_availability_web')
@login_required
def update_availability_web():
    """
    DEPRECATED: Legacy web availability endpoint
    
    This endpoint should no longer be used. The web interface should use
    the Enterprise RSVP v2 system directly via JavaScript.
    
    Expects JSON with:
        - match_id
        - player_id
        - response
    """
    logger.warning("⚠️ [AVAILABILITY_API] DEPRECATED web endpoint called - this should be migrated to use Enterprise RSVP v2")
    data = request.json
    logger.info(f"Received web update data: {data}")

    required_fields = ['match_id', 'player_id', 'response']
    if not all(data.get(field) for field in required_fields):
        logger.error("Missing required data")
        return jsonify({"error": "Invalid data"}), 400

    # Get the player record to check for discord_id
    with managed_session() as session_db:
        logger.debug(f"🔵 [AVAILABILITY_API] Looking up player {data['player_id']} for web update")
        player = session_db.query(Player).get(data['player_id'])
        discord_id = None
        
        if player:
            discord_id = player.discord_id
            logger.info(f"🔵 [AVAILABILITY_API] Found player {player.name} with discord_id: {discord_id}")
        
        # Update RSVP in the database
        logger.debug(f"🔵 [AVAILABILITY_API] Updating RSVP for match {data['match_id']}, player {data['player_id']}")
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
    
    # Emit WebSocket event for real-time updates
    from app.sockets.rsvp import emit_rsvp_update
    emit_rsvp_update(
        match_id=data['match_id'],
        player_id=data['player_id'],
        availability=data['response'],
        source='web',
        player_name=player.name if player else None
    )
    
    # If we have a discord_id, also update the reaction
    if discord_id:
        try:
            # Explicitly call the Discord bot to update the reaction
            import requests
            
            # Call the Discord bot's API to update the reaction
            discord_api_url = "http://discord-bot:5001/api/update_user_reaction"
            reaction_data = {
                "match_id": str(data['match_id']),
                "discord_id": str(discord_id),
                "new_response": data['response'],
                "old_response": None  # Let the bot figure out the old response
            }
            
            logger.info(f"Sending reaction update to Discord: {reaction_data}")
            response = requests.post(discord_api_url, json=reaction_data, timeout=10)
            
            if response.status_code == 200:
                logger.info(f"Successfully updated Discord reaction for user {discord_id}")
            else:
                logger.error(f"Failed to update Discord reaction: {response.status_code} - {response.text}")
        except Exception as e:
            logger.error(f"Error updating Discord reaction: {str(e)}", exc_info=True)
    
    return jsonify({"message": message}), 200


@availability_bp.route('/sync_match_rsvps/<int:match_id>', methods=['POST'], endpoint='sync_match_rsvps')
@login_required
def sync_match_rsvps(match_id):
    """
    Sync match RSVPs to update Discord and frontend data.
    """
    logger.info(f"🔵 [AVAILABILITY_API] sync_match_rsvps called for match {match_id}")
    
    try:
        with managed_session() as session_db:
            logger.debug(f"🔵 [AVAILABILITY_API] Looking up match {match_id} for RSVP sync")
            match = session_db.query(Match).get(match_id)
            if not match:
                logger.warning(f"🟡 [AVAILABILITY_API] Match not found for sync: {match_id}")
                abort(404)

            logger.debug(f"🔵 [AVAILABILITY_API] Getting availabilities for match {match_id}")
            availabilities = session_db.query(Availability).filter_by(match_id=match_id).all()
            logger.debug(f"🔵 [AVAILABILITY_API] Found {len(availabilities)} availabilities to sync")

            for availability in availabilities:
                if availability.player.discord_id:
                    logger.debug(f"🔵 [AVAILABILITY_API] Updating Discord RSVP for player {availability.player.name}")
                    result = update_discord_rsvp(
                        match=match,
                        player=availability.player,
                        new_response=availability.response,
                        old_response=None,
                        session=session_db
                    )
                    if result['status'] != 'success':
                        logger.error(f"🔴 [AVAILABILITY_API] Failed to update Discord RSVP for player {availability.player_id}")
                else:
                    logger.debug(f"🟡 [AVAILABILITY_API] Player {availability.player_id} has no Discord account; skipping update.")

            logger.info(f"🟢 [AVAILABILITY_API] Match RSVPs synced successfully for match {match_id}")
            return jsonify({"message": "Match RSVPs synced successfully"}), 200

    except Exception as e:
        logger.error(f"🔴 [AVAILABILITY_API] Error syncing match RSVPs: {str(e)}")
        return jsonify({"error": "Internal Server Error"}), 500


@availability_bp.route('/get_match_rsvps/<int:match_id>', methods=['GET'], endpoint='get_match_rsvps')
def get_match_rsvps(match_id):
    """
    Retrieve RSVP data for a match.

    Optionally filters by team_id provided as a query parameter.
    Can include discord_ids if include_discord_ids=true is provided.
    """
    team_id = request.args.get('team_id', type=int)
    include_discord_ids = request.args.get('include_discord_ids', 'false').lower() == 'true'
    
    logger.info(f"🔵 [AVAILABILITY_API] get_match_rsvps called for match {match_id}, team_id={team_id}, include_discord_ids={include_discord_ids}")

    with managed_session() as session_db:
        logger.debug(f"🔵 [AVAILABILITY_API] Verifying availability data for match {match_id}")
        verify_availability_data(match_id, team_id, session=session_db)
        
        # Get detailed RSVP data with Discord IDs if requested
        try:
            # Start with the basic query
            logger.debug(f"🔵 [AVAILABILITY_API] Querying availabilities for match {match_id}")
            query = session_db.query(Availability, Player).join(Player).filter(Availability.match_id == match_id)
            
            # OPTIMIZATION: Only include RSVPs for recent matches to reduce memory usage
            from app.utils.rsvp_filters import filter_availability_active, is_match_active_for_rsvp
            from app.models import Match
            
            # Check if this match is still "active" for RSVP purposes
            match = session_db.query(Match).get(match_id)
            if match and not is_match_active_for_rsvp(match.date):
                logger.debug(f"🟡 [AVAILABILITY_API] Match {match_id} on {match.date} is too old for active RSVP processing")
                # Return empty results for old matches to save memory
                return {
                    'success': True,
                    'total_count': 0,
                    'responses': {},
                    'availability_records': [],
                    'message': f'Match on {match.date} is outside active RSVP window'
                }
            
            # Apply active RSVP filtering (joins with Match table for date filtering)
            query = filter_availability_active(query)
            
            # If a team_id is provided, use the player_teams association table to filter by team
            if team_id:
                from app.models import player_teams
                query = query.join(player_teams, Player.id == player_teams.c.player_id).filter(player_teams.c.team_id == team_id)
                logger.debug(f"Filtering by team_id: {team_id}")

            # Get the availability records with discord_ids if requested
            if include_discord_ids:
                availability_records = query.with_entities(
                    Availability.response, 
                    Player.name,
                    Player.id,
                    Player.discord_id
                ).all()
            else:
                availability_records = query.with_entities(
                    Availability.response, 
                    Player.name,
                    Player.id
                ).all()
            
            logger.debug(f"Retrieved {len(availability_records)} availability records")

            # Organize data by response type
            rsvp_data = {'yes': [], 'no': [], 'maybe': []}
            
            # Process each record
            for record in availability_records:
                if include_discord_ids:
                    response, player_name, player_id, discord_id = record
                    player_data = {
                        'player_name': player_name,
                        'player_id': player_id,
                        'discord_id': discord_id
                    }
                else:
                    response, player_name, player_id = record
                    player_data = {
                        'player_name': player_name,
                        'player_id': player_id
                    }
                    
                if response in rsvp_data:
                    rsvp_data[response].append(player_data)
            
            logger.info(f"Returning RSVP data for match {match_id}, team {team_id} with {len(availability_records)} entries")
            return jsonify(rsvp_data), 200
            
        except Exception as e:
            logger.exception(f"Error getting RSVPs for match {match_id}, team {team_id}: {str(e)}")
            rsvp_data = {'yes': [], 'no': [], 'maybe': [], 'error': str(e)}
            return jsonify(rsvp_data), 200


@availability_bp.route('/update_availability_from_discord', methods=['POST'], endpoint='update_availability_from_discord')
def update_availability_from_discord():
    """
    DEPRECATED: Legacy Discord API endpoint - redirects to Enterprise RSVP v2
    
    This endpoint now internally calls the Enterprise RSVP v2 system to ensure
    all Discord bot requests get enterprise reliability features.

    Expects JSON with:
        - match_id
        - discord_id
        - response
        - optionally, responded_at
    """
    logger.info(f"🔄 [AVAILABILITY_API] Legacy Discord endpoint redirecting to Enterprise RSVP v2")
    
    try:
        data = request.json
        
        # Validate required fields
        required_fields = ['match_id', 'discord_id', 'response']
        if not all(field in data for field in required_fields):
            logger.error(f"🔴 [AVAILABILITY_API] Missing required fields: {data}")
            return jsonify({
                'status': 'error',
                'error': 'Missing required fields'
            }), 400
        
        # Import Enterprise RSVP function
        from app.api_enterprise_rsvp import update_rsvp_enterprise_from_discord
        
        # Transform legacy request to enterprise format
        enterprise_request_data = {
            'match_id': data['match_id'],
            'discord_id': str(data['discord_id']),
            'response': data['response'],  # Enterprise uses 'response' for Discord
            'source': 'discord_legacy',
            'operation_id': str(__import__('uuid').uuid4())  # Generate operation ID
        }
        
        # Temporarily replace request.json with enterprise format
        original_json = request.json
        request.json = enterprise_request_data
        
        try:
            # Call the enterprise endpoint internally
            logger.info(f"🔄 Redirecting legacy Discord API call to Enterprise RSVP v2: match={data['match_id']}, discord_id={data['discord_id']}")
            response = update_rsvp_enterprise_from_discord()
            
            # Transform enterprise response back to legacy format for compatibility
            if response[1] == 200:  # Success response
                enterprise_data = response[0].get_json()
                legacy_response = {
                    'status': 'success',
                    'message': enterprise_data.get('message', 'RSVP updated successfully'),
                    'match_id': enterprise_data.get('match_id'),
                    'player_id': enterprise_data.get('player_id'),
                    # Include enterprise metadata for debugging
                    '_enterprise': {
                        'trace_id': enterprise_data.get('trace_id'),
                        'operation_id': enterprise_data.get('operation_id'),
                        'via_v2': True
                    }
                }
                return jsonify(legacy_response), 200
            else:
                # Enterprise endpoint failed, return the error
                return response
                
        finally:
            # Restore original request data
            request.json = original_json
            
    except Exception as e:
        logger.error(f"❌ Legacy Discord API redirect to enterprise failed: {str(e)}", exc_info=True)
        # Fallback to original legacy implementation if enterprise redirect fails
        pass
    
    # FALLBACK: Original legacy implementation (only if enterprise redirect fails)
    logger.warning("⚠️ Using legacy Discord RSVP implementation - enterprise redirect failed")
    logger.info(f"🔵 [AVAILABILITY_API] update_availability_from_discord called")
    
    try:
        data = request.json
        logger.debug(f"🔵 [AVAILABILITY_API] Received data from Discord: {data}")

        required_fields = ['match_id', 'discord_id', 'response']
        if not all(field in data for field in required_fields):
            logger.error(f"🔴 [AVAILABILITY_API] Missing required fields: {data}")
            return jsonify({
                'status': 'error',
                'error': 'Missing required fields'
            }), 400

        with managed_session() as session_db:
            logger.debug(f"🔵 [AVAILABILITY_API] Processing availability update for match {data['match_id']}, discord_id {data['discord_id']}")
            player_id, result = process_availability_update(
                match_id=data['match_id'],
                discord_id=str(data['discord_id']),
                response=data['response'],
                responded_at=data.get('responded_at'),
                session=session_db
            )

            if not player_id:
                logger.error(f"🔴 [AVAILABILITY_API] No player found for discord_id {data['discord_id']}")
                return jsonify({
                    'status': 'error',
                    'error': result.get('message', 'Player not found')
                }), 404

            if data['response'] != 'no_response':
                logger.debug(f"🔵 [AVAILABILITY_API] Triggering notifications for match {data['match_id']}, player {player_id}")
                notify_discord_of_rsvp_change_task.delay(data['match_id'])
                notify_frontend_of_rsvp_change_task.delay(data['match_id'], player_id, data['response'])
                
                # Emit WebSocket event for real-time updates
                from app.sockets.rsvp import emit_rsvp_update
                # Get player name from result
                player_name = None
                if player_id:
                    p = session_db.query(Player).get(player_id)
                    if p:
                        player_name = p.name
                
                emit_rsvp_update(
                    match_id=data['match_id'],
                    player_id=player_id,
                    availability=data['response'],
                    source='discord',
                    player_name=player_name
                )

            logger.info(f"🟢 [AVAILABILITY_API] Availability updated successfully from Discord for match {data['match_id']}")
            return jsonify({
                'status': 'success',
                'message': result.get('message', 'Update successful')
            }), 200

    except Exception as e:
        logger.error(f"🔴 [AVAILABILITY_API] Error in update_availability_from_discord: {str(e)}", exc_info=True)
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


@availability_bp.route('/update_poll_response_from_discord', methods=['POST'], endpoint='update_poll_response_from_discord')
def update_poll_response_from_discord():
    """
    Update poll response data based on information received from Discord.

    Expects JSON with:
        - poll_id
        - discord_id
        - response ('yes', 'no', 'maybe')
        - optionally, responded_at
    """
    logger.info(f"🔵 [AVAILABILITY_API] update_poll_response_from_discord called")
    
    try:
        data = request.json
        logger.debug(f"🔵 [AVAILABILITY_API] Received poll response from Discord: {data}")

        required_fields = ['poll_id', 'discord_id', 'response']
        if not all(field in data for field in required_fields):
            logger.error(f"🔴 [AVAILABILITY_API] Missing required fields for poll response: {data}")
            return jsonify({
                'status': 'error',
                'error': 'Missing required fields'
            }), 400

        poll_id = data['poll_id']
        discord_id = str(data['discord_id'])
        response = data['response']
        
        if response not in ['yes', 'no', 'maybe']:
            logger.error(f"🔴 [AVAILABILITY_API] Invalid response value: {response}")
            return jsonify({
                'status': 'error',
                'error': 'Invalid response value'
            }), 400

        with managed_session() as session_db:
            # Find the player by Discord ID
            from app.models import Player, LeaguePoll, LeaguePollResponse
            logger.debug(f"🔵 [AVAILABILITY_API] Looking up player with discord_id {discord_id}")
            player = session_db.query(Player).filter(Player.discord_id == discord_id).first()
            if not player:
                logger.error(f"🔴 [AVAILABILITY_API] No player found for discord_id {discord_id}")
                return jsonify({
                    'status': 'error',
                    'error': 'Player not found'
                }), 404

            # Check if poll exists and is active
            logger.debug(f"🔵 [AVAILABILITY_API] Checking poll {poll_id} status")
            poll = session_db.query(LeaguePoll).filter(
                LeaguePoll.id == poll_id,
                LeaguePoll.status == 'ACTIVE'
            ).first()
            if not poll:
                logger.error(f"🔴 [AVAILABILITY_API] Poll {poll_id} not found or not active")
                return jsonify({
                    'status': 'error',
                    'error': 'Poll not found or not active'
                }), 404

            # Check if response already exists
            logger.debug(f"🔵 [AVAILABILITY_API] Checking for existing response for poll {poll_id}, player {player.id}")
            existing_response = session_db.query(LeaguePollResponse).filter(
                LeaguePollResponse.poll_id == poll_id,
                LeaguePollResponse.player_id == player.id
            ).first()

            if existing_response:
                # Update existing response
                old_response = existing_response.response
                existing_response.response = response
                existing_response.responded_at = datetime.utcnow()
                logger.info(f"🟢 [AVAILABILITY_API] Updated poll response for player {player.name} (ID: {player.id}) from {old_response} to {response}")
            else:
                # Create new response
                new_response = LeaguePollResponse(
                    poll_id=poll_id,
                    player_id=player.id,
                    discord_id=discord_id,
                    response=response
                )
                session_db.add(new_response)
                logger.info(f"🟢 [AVAILABILITY_API] Created new poll response for player {player.name} (ID: {player.id}): {response}")

            return jsonify({
                'status': 'success',
                'message': f'Poll response recorded: {response}',
                'player_name': player.name
            }), 200

    except Exception as e:
        logger.error(f"🔴 [AVAILABILITY_API] Error in update_poll_response_from_discord: {str(e)}", exc_info=True)
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500



@availability_bp.route('/get_message_ids/<int:match_id>', methods=['GET'], endpoint='get_message_ids')
def get_message_ids(match_id):
    """
    Retrieve message IDs associated with a match.
    """
    logger.info(f"🔵 [AVAILABILITY_API] get_message_ids called for match {match_id}")
    
    with managed_session() as session_db:
        logger.debug(f"🔵 [AVAILABILITY_API] Getting message data for match {match_id}")
        message_data = get_message_data(match_id, session=session_db)
        if not message_data:
            logger.warning(f"🟡 [AVAILABILITY_API] No scheduled message found for match_id {match_id}")
            return jsonify({'error': 'No scheduled message found'}), 404
            
        logger.info(f"🟢 [AVAILABILITY_API] Returning message data for match_id {match_id}: {message_data}")
        return jsonify(message_data), 200


# Simple circuit breaker to prevent overload
_request_failures = {}
_circuit_breaker_threshold = 10  # Increased from 5 to allow more retries
_circuit_breaker_window = 300  # 5 minutes
_circuit_breaker_reset_time = {}  # Track when circuit was opened

def _is_circuit_open(endpoint):
    """Check if circuit breaker is open for this endpoint."""
    import time
    now = time.time()
    
    # Check if circuit should be reset (30 seconds after opening)
    if endpoint in _circuit_breaker_reset_time:
        if now - _circuit_breaker_reset_time[endpoint] > 30:
            # Reset the circuit breaker
            logger.info(f"Resetting circuit breaker for {endpoint}")
            _request_failures[endpoint] = []
            del _circuit_breaker_reset_time[endpoint]
            return False
    
    if endpoint not in _request_failures:
        return False
    
    recent_failures = [t for t in _request_failures[endpoint] if now - t < _circuit_breaker_window]
    _request_failures[endpoint] = recent_failures
    
    is_open = len(recent_failures) >= _circuit_breaker_threshold
    if is_open and endpoint not in _circuit_breaker_reset_time:
        _circuit_breaker_reset_time[endpoint] = now
        logger.warning(f"Circuit breaker opened for {endpoint} - will reset in 30 seconds")
    
    return is_open

def _record_failure(endpoint):
    """Record a failure for circuit breaker."""
    import time
    if endpoint not in _request_failures:
        _request_failures[endpoint] = []
    _request_failures[endpoint].append(time.time())

@availability_bp.route('/get_match_and_team_id_from_message', methods=['GET'], endpoint='get_match_and_team_id_from_message')
def get_match_and_team_id_from_message():
    """
    Retrieve match and team IDs based on a provided message_id and channel_id.
    """
    # Circuit breaker check
    if _is_circuit_open('get_match_and_team_id_from_message'):
        logger.warning("Circuit breaker open - rejecting request to prevent overload")
        return jsonify({
            'status': 'error',
            'error': 'Service temporarily unavailable due to high load'
        }), 503
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

        # Try direct database query first as a fallback if the queue is overloaded
        try:
            # Quick synchronous check first to avoid queueing if possible
            from app.models import ScheduledMessage
            from sqlalchemy import or_
            
            with managed_session() as session_db:
                logger.debug(f"🔵 [AVAILABILITY_API] Trying direct query for message_id {message_id}, channel_id {channel_id}")
                scheduled_msg = session_db.query(ScheduledMessage).filter(
                    or_(
                        (ScheduledMessage.home_channel_id == channel_id) & (ScheduledMessage.home_message_id == message_id),
                        (ScheduledMessage.away_channel_id == channel_id) & (ScheduledMessage.away_message_id == message_id)
                    )
                ).first()
                
                if scheduled_msg:
                    # Found in direct query - return immediately without using Celery
                    if scheduled_msg.home_channel_id == channel_id and scheduled_msg.home_message_id == message_id:
                        team_id = scheduled_msg.match.home_team_id
                    else:
                        team_id = scheduled_msg.match.away_team_id
                    
                    logger.info(f"🟢 [AVAILABILITY_API] Found match via direct query: match_id={scheduled_msg.match_id}, team_id={team_id}")
                    return jsonify({
                        'status': 'success',
                        'data': {
                            'match_id': scheduled_msg.match_id,
                            'team_id': team_id
                        }
                    }), 200
        except Exception as e:
            logger.warning(f"🟡 [AVAILABILITY_API] Direct query failed, falling back to Celery task: {e}")
        
        # Use a lower priority queue to avoid blocking other critical tasks
        task = fetch_match_and_team_id_task.apply_async(
            args=[message_id, channel_id],  # Pass as positional args, not kwargs
            queue='discord',  # Use discord queue which should have proper worker allocation
            priority=5,  # Lower priority to avoid blocking critical tasks
            expires=25  # Task expires after 25 seconds
        )

        try:
            # Reduce timeout to 10 seconds to fail faster and avoid connection pool exhaustion
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
            _record_failure('get_match_and_team_id_from_message')
            return jsonify({
                'status': 'error',
                'error': 'Task timed out'
            }), 504

    except Exception as e:
        error_msg = (f"Failed to process request for message_id: {request.args.get('message_id')}, "
                     f"channel_id: {request.args.get('channel_id')}. Error: {str(e)}")
        logger.error(error_msg, exc_info=True)
        _record_failure('get_match_and_team_id_from_message')
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
    logger.info(f"🔵 [AVAILABILITY_API] is_user_on_team called")
    
    data = request.json
    discord_id = data.get('discord_id')
    team_id = data.get('team_id')
    
    logger.debug(f"🔵 [AVAILABILITY_API] Checking if discord_id {discord_id} is on team {team_id}")

    if not discord_id or not team_id:
        logger.error(f"🔴 [AVAILABILITY_API] Missing required fields: discord_id={discord_id}, team_id={team_id}")
        return jsonify({'error': 'Missing required fields'}), 400

    with managed_session() as session_db:
        logger.debug(f"🔵 [AVAILABILITY_API] Looking up player with discord_id {discord_id}")
        player = session_db.query(Player).filter_by(discord_id=str(discord_id)).first()
        
        # Check if player exists and if they're on the specified team
        is_team_member = False
        if player:
            # Use the teams relationship to check if the player is on the team
            team_ids = [team.id for team in player.teams]
            is_team_member = int(team_id) in team_ids
            logger.debug(f"🔵 [AVAILABILITY_API] Player {player.id} teams: {team_ids}, checking team_id: {team_id}, is_member: {is_team_member}")
        else:
            logger.warning(f"🟡 [AVAILABILITY_API] No player found for discord_id {discord_id}")
        
        logger.info(f"🟢 [AVAILABILITY_API] Team membership check result: {is_team_member}")
        return jsonify({
            'is_team_member': is_team_member
        }), 200


@availability_bp.route('/get_scheduled_messages', methods=['GET'])
def get_scheduled_messages():
    """
    Retrieve all scheduled messages along with associated match and team IDs.
    Includes both pub league matches and ECS FC matches.
    """
    with managed_session() as session_db:
        # Get pub league messages (existing logic)
        pub_league_messages = (
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

        # Get ECS FC messages (new logic)
        ecs_fc_messages = (
            session_db.query(ScheduledMessage)
            .filter(
                ScheduledMessage.message_type == 'ecs_fc_rsvp',
                ScheduledMessage.match_id.is_(None)
            )
            .all()
        )
        
        # Debug logging
        logger.info(f"Found {len(pub_league_messages)} pub league messages and {len(ecs_fc_messages)} ECS FC messages")

    # Format pub league messages (existing format)
    pub_league_data = [{
        'match_id': m.match_id,
        'home_channel_id': m.home_channel_id,
        'home_message_id': m.home_message_id,
        'away_channel_id': m.away_channel_id,
        'away_message_id': m.away_message_id,
        'home_team_id': m.home_team_id,
        'away_team_id': m.away_team_id,
        'message_type': 'pub_league'
    } for m in pub_league_messages]

    # Format ECS FC messages (new format)
    ecs_fc_data = []
    for m in ecs_fc_messages:
        metadata = m.message_metadata or {}
        discord_message_id = metadata.get('discord_message_id')
        discord_channel_id = metadata.get('discord_channel_id')
        ecs_fc_match_id = metadata.get('ecs_fc_match_id')
        
        logger.debug(f"ECS FC message {m.id}: metadata={metadata}")
        
        if discord_message_id and discord_channel_id:
            ecs_fc_data.append({
                'match_id': f'ecs_{ecs_fc_match_id}',  # Use ECS FC format
                'ecs_fc_match_id': ecs_fc_match_id,
                'home_channel_id': discord_channel_id,
                'home_message_id': discord_message_id,
                'away_channel_id': None,  # ECS FC only has one team
                'away_message_id': None,
                'home_team_id': ecs_fc_match_id,  # Use match ID as team identifier
                'away_team_id': None,
                'message_type': 'ecs_fc'
            })

    # Combine both types of messages
    all_messages = pub_league_data + ecs_fc_data

    return jsonify(all_messages), 200


@availability_bp.route('/get_player_id_from_discord/<string:discord_id>', methods=['GET'])
def get_player_id_from_discord(discord_id):
    """
    Retrieve a player's ID and basic profile data based on their Discord ID.
    """
    logger.info(f"🔵 [AVAILABILITY_API] get_player_id_from_discord called for discord_id {discord_id}")
    
    with managed_session() as session_db:
        logger.debug(f"🔵 [AVAILABILITY_API] Looking up player with discord_id {discord_id}")
        player = session_db.query(Player).filter_by(discord_id=discord_id).first()
        if not player:
            logger.warning(f"🟡 [AVAILABILITY_API] Player not found for discord_id {discord_id}")
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
        
        logger.info(f"🟢 [AVAILABILITY_API] Retrieved player data for {player.name} (ID: {player.id})")
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
    logger.info(f"🔵 [AVAILABILITY_API] get_match_request called for match {match_id}")
    
    with managed_session() as session_db:
        logger.debug(f"🔵 [AVAILABILITY_API] Getting match request data for match {match_id}")
        match_data = get_match_request_data(match_id, session=session_db)
        if not match_data:
            logger.warning(f"🟡 [AVAILABILITY_API] Match not found: {match_id}")
            return jsonify({'error': 'Match not found'}), 404
            
        logger.info(f"🟢 [AVAILABILITY_API] Retrieved match request data for match {match_id}")
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


@availability_bp.route('/get_message_info/<message_id>', methods=['GET'], endpoint='get_message_info')
def get_message_info(message_id):
    """
    Get information about a Discord message, including its channel ID, match ID, and team ID.
    
    This endpoint is used by the Discord bot's synchronization system to identify which
    match and team a message belongs to, so it can properly update the correct RSVPs.
    
    Args:
        message_id: The Discord message ID to look up
        
    Returns:
        JSON response containing channel_id, match_id, and team_id if found
    """
    logger.info(f"🔵 [AVAILABILITY_API] get_message_info called for message ID: {message_id}")
    
    try:
        # Try cache first to reduce database connections
        from app.cache_helpers import get_cached_message_info
        cached_result = get_cached_message_info(message_id)
        if cached_result:
            logger.info(f"🔵 [AVAILABILITY_API] Found cached message info for {message_id}: {cached_result}")
            return jsonify(cached_result)
        
        # Cache miss - continue with database lookup
        # Convert the message ID to a string for lookups (database columns are VARCHAR)
        message_id_str = str(message_id)
        
        with managed_session() as session_db:
            # Find a scheduled message with this home or away message ID
            logger.debug(f"🔵 [AVAILABILITY_API] Querying for scheduled message with home_message_id or away_message_id = {message_id_str}")
            scheduled_msg = session_db.query(ScheduledMessage).filter(
                (ScheduledMessage.home_message_id == message_id_str) | 
                (ScheduledMessage.away_message_id == message_id_str)
            ).first()
            
            if not scheduled_msg:
                # Let's log all message IDs for debugging
                all_msgs = session_db.query(
                    ScheduledMessage.id, 
                    ScheduledMessage.home_message_id, 
                    ScheduledMessage.away_message_id
                ).all()
                logger.warning(f"🟡 [AVAILABILITY_API] No scheduled message found for message ID {message_id}. Available IDs: {all_msgs}")
                return jsonify({'error': 'Message not found'}), 404
                
            # Determine if this is a home or away message
            is_home = scheduled_msg.home_message_id == message_id
            
            # Get the associated match
            match = scheduled_msg.match
            if not match:
                logger.warning(f"🟡 [AVAILABILITY_API] No match associated with scheduled message {scheduled_msg.id}")
                return jsonify({'error': 'No match associated with this message'}), 404
                
            # Get the appropriate team ID and channel ID
            team_id = match.home_team_id if is_home else match.away_team_id
            channel_id = scheduled_msg.home_channel_id if is_home else scheduled_msg.away_channel_id
            
            # Check if match is recent (within last 7 days) to avoid processing old matches
            week_ago = datetime.utcnow().date() - timedelta(days=7) 
            is_recent_match = match.date >= week_ago
            
            # Build response
            response = {
                'channel_id': channel_id,
                'match_id': match.id,
                'team_id': team_id,
                'is_home': is_home,
                'message_type': 'home' if is_home else 'away',
                'match_date': match.date.isoformat(),
                'match_time': match.time.isoformat() if match.time else None,
                'is_recent_match': is_recent_match
            }
            logger.info(f"🟢 [AVAILABILITY_API] Found message info for {message_id}: {response}")
            
            # Return the information needed for syncing
            return jsonify(response)
        
    except ValueError:
        logger.error(f"🔴 [AVAILABILITY_API] Invalid message ID format: {message_id}")
        return jsonify({'error': 'Invalid message ID format'}), 400
    except Exception as e:
        logger.error(f"🔴 [AVAILABILITY_API] Error retrieving message info for {message_id}: {str(e)}", exc_info=True)
        return jsonify({'error': f'Server error: {str(e)}'}), 500


@availability_bp.route('/force_discord_sync', methods=['POST'], endpoint='force_discord_sync')
@login_required
def force_discord_sync():
    """
    Force a synchronization between Flask app RSVPs and Discord embeds/reactions.
    
    This endpoint is useful for maintaining consistency after bot crashes or network issues.
    It requires admin privileges to run due to potential performance impact.
    
    Returns:
        JSON response indicating request has been sent to the Discord bot
    """
    # Only allow admin users to trigger the sync
    if not g.user.is_admin:
        logger.warning(f"Non-admin user {g.user.id} attempted to force Discord sync")
        return jsonify({'error': 'Admin privileges required'}), 403
        
    try:
        # First, trigger the Celery task to mark failed records for resync
        task = force_discord_rsvp_sync.delay()
        
        # Then call the Discord bot's sync endpoint
        import requests
        discord_bot_url = "http://discord-bot:5001/api/force_rsvp_sync"
        
        response = requests.post(discord_bot_url, timeout=5)
        
        if response.status_code == 200:
            logger.info(f"Discord sync triggered by admin user {g.user.id}")
            return jsonify({
                'success': True,
                'message': 'Discord synchronization triggered successfully',
                'response': response.json(),
                'task_id': task.id
            }), 200
        else:
            logger.error(f"Failed to trigger Discord sync: {response.status_code} - {response.text}")
            return jsonify({
                'success': False,
                'message': f'Discord synchronization failed: {response.text}',
                'task_id': task.id
            }), 500
            
    except requests.RequestException as e:
        logger.error(f"Error connecting to Discord bot for sync: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Could not connect to Discord bot: {str(e)}'
        }), 500
    except Exception as e:
        logger.exception(f"Unexpected error during Discord sync: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Unexpected error: {str(e)}'
        }), 500

@availability_bp.route('/sync_discord_rsvps', methods=['POST'], endpoint='sync_discord_rsvps')
def sync_discord_rsvps():
    """
    Receive RSVP updates from Discord bot to update the Flask database.
    
    This endpoint allows the Discord bot to inform Flask of RSVPs discovered during 
    a sync operation that might be missing in the Flask database.
    
    Expected JSON payload:
    {
        "match_id": 123,
        "rsvps": [
            {"discord_id": "123456789", "response": "yes"},
            {"discord_id": "987654321", "response": "no"}
        ]
    }
    
    Returns:
        JSON response indicating success or failure
    """
    logger.info(f"🔵 [AVAILABILITY_API] sync_discord_rsvps called")
    
    try:
        data = request.json
        logger.debug(f"🔵 [AVAILABILITY_API] Received Discord RSVP sync data: {data}")
        
        if not data:
            logger.error(f"🔴 [AVAILABILITY_API] No JSON data provided")
            return jsonify({'error': 'No JSON data provided'}), 400
            
        match_id = data.get('match_id')
        rsvps = data.get('rsvps', [])
        
        if not match_id or not isinstance(rsvps, list):
            logger.error(f"🔴 [AVAILABILITY_API] Invalid data format: match_id={match_id}, rsvps={type(rsvps)}")
            return jsonify({'error': 'Invalid data format'}), 400
            
        with managed_session() as session_db:
            # Verify the match exists
            logger.debug(f"🔵 [AVAILABILITY_API] Verifying match {match_id} exists")
            match = session_db.query(Match).get(match_id)
            if not match:
                logger.warning(f"🟡 [AVAILABILITY_API] Match {match_id} not found")
                return jsonify({'error': f'Match {match_id} not found'}), 404
                
            # Process each RSVP update
            updates = []
            logger.debug(f"🔵 [AVAILABILITY_API] Processing {len(rsvps)} RSVP updates")
            
            for rsvp_data in rsvps:
                discord_id = rsvp_data.get('discord_id')
                response = rsvp_data.get('response')
                
                if not discord_id or not response:
                    logger.debug(f"🟡 [AVAILABILITY_API] Skipping incomplete RSVP data: {rsvp_data}")
                    continue
                    
                # Find the player by Discord ID
                logger.debug(f"🔵 [AVAILABILITY_API] Looking up player with discord_id {discord_id}")
                player = session_db.query(Player).filter_by(discord_id=discord_id).first()
                if not player:
                    logger.warning(f"🟡 [AVAILABILITY_API] Player with Discord ID {discord_id} not found")
                    continue
                    
                # Check if an availability record exists
                logger.debug(f"🔵 [AVAILABILITY_API] Checking availability for match {match_id}, player {player.id}")
                availability = session_db.query(Availability).filter_by(
                    match_id=match_id, 
                    player_id=player.id
                ).first()
                
                if availability:
                    if availability.response != response:
                        old_response = availability.response
                        availability.response = response
                        availability.responded_at = datetime.utcnow()
                        updates.append({
                            'player_id': player.id,
                            'name': player.name,
                            'old_response': old_response,
                            'new_response': response,
                            'action': 'updated'
                        })
                        logger.debug(f"🔵 [AVAILABILITY_API] Updated availability for {player.name}: {old_response} -> {response}")
                else:
                    # Create new availability record
                    new_availability = Availability(
                        match_id=match_id,
                        player_id=player.id,
                        response=response,
                        discord_id=discord_id,
                        responded_at=datetime.utcnow()
                    )
                    session_db.add(new_availability)
                    updates.append({
                        'player_id': player.id,
                        'name': player.name,
                        'new_response': response,
                        'action': 'created'
                    })
                    logger.debug(f"🔵 [AVAILABILITY_API] Created new availability for {player.name}: {response}")
                    
            # If we made any updates, notify the frontend
            if updates:
                logger.debug(f"🔵 [AVAILABILITY_API] Triggering frontend notifications for {len(updates)} updates")
                for update in updates:
                    notify_frontend_of_rsvp_change_task.delay(
                        match_id=match_id,
                        player_id=update['player_id'],
                        response=update['new_response']
                    )
                
            logger.info(f"🟢 [AVAILABILITY_API] Successfully processed {len(updates)} RSVP updates for match {match_id}")
            return jsonify({
                'success': True,
                'message': f'Successfully processed {len(updates)} RSVP updates',
                'updates': updates
            })
            
    except Exception as e:
        logger.error(f"🔴 [AVAILABILITY_API] Error syncing Discord RSVPs: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'message': f'Error processing RSVP updates: {str(e)}'
        }), 500


@availability_bp.route('/record_poll_response', methods=['POST'])
def record_poll_response():
    """
    Records a poll response from Discord.
    
    Expected JSON:
    {
        "poll_id": int,
        "discord_id": str,
        "response": str ("yes", "no", "maybe"),
        "responded_at": str (ISO datetime)
    }
    """
    logger.info(f"🔵 [AVAILABILITY_API] record_poll_response called")
    
    try:
        data = request.get_json()
        logger.debug(f"🔵 [AVAILABILITY_API] Recording poll response: {data}")
        
        if not data:
            logger.error(f"🔴 [AVAILABILITY_API] No data provided")
            return jsonify({'error': 'No data provided'}), 400
        
        poll_id = data.get('poll_id')
        discord_id = data.get('discord_id')
        response = data.get('response')
        responded_at = data.get('responded_at')
        
        if not all([poll_id, discord_id, response]):
            logger.error(f"🔴 [AVAILABILITY_API] Missing required fields: poll_id={poll_id}, discord_id={discord_id}, response={response}")
            return jsonify({'error': 'Missing required fields'}), 400
        
        if response not in ['yes', 'no', 'maybe']:
            logger.error(f"🔴 [AVAILABILITY_API] Invalid response: {response}")
            return jsonify({'error': 'Invalid response. Must be yes, no, or maybe'}), 400
        
        with managed_session() as session_db:
            # Import models
            from app.models import LeaguePoll, LeaguePollResponse, Player
            
            # Check if poll exists and is active
            logger.debug(f"🔵 [AVAILABILITY_API] Checking poll {poll_id} status")
            poll = session_db.query(LeaguePoll).get(poll_id)
            if not poll:
                logger.error(f"🔴 [AVAILABILITY_API] Poll {poll_id} not found")
                return jsonify({'error': 'Poll not found'}), 404
                
            if poll.status != 'ACTIVE':
                logger.error(f"🔴 [AVAILABILITY_API] Poll {poll_id} is not active (status: {poll.status})")
                return jsonify({'error': 'Poll is not active'}), 400
            
            # Find player by Discord ID
            logger.debug(f"🔵 [AVAILABILITY_API] Looking up player with discord_id {discord_id}")
            player = session_db.query(Player).filter_by(discord_id=discord_id).first()
            if not player:
                logger.error(f"🔴 [AVAILABILITY_API] Player not found with Discord ID {discord_id}")
                return jsonify({'error': 'Player not found with this Discord ID'}), 403
            
            # Check if player has already responded
            logger.debug(f"🔵 [AVAILABILITY_API] Checking for existing response for poll {poll_id}, player {player.id}")
            existing_response = session_db.query(LeaguePollResponse).filter_by(
                poll_id=poll_id,
                player_id=player.id
            ).first()
            
            if existing_response:
                # Update existing response
                old_response = existing_response.response
                existing_response.response = response
                existing_response.responded_at = datetime.fromisoformat(responded_at) if responded_at else datetime.utcnow()
                action = 'updated'
                
                logger.info(f"🟢 [AVAILABILITY_API] Updated poll response for player {player.name} ({player.id}) "
                           f"from {old_response} to {response} for poll {poll_id}")
            else:
                # Create new response
                new_response = LeaguePollResponse(
                    poll_id=poll_id,
                    player_id=player.id,
                    discord_id=discord_id,
                    response=response,
                    responded_at=datetime.fromisoformat(responded_at) if responded_at else datetime.utcnow()
                )
                session_db.add(new_response)
                action = 'created'
                
                logger.info(f"🟢 [AVAILABILITY_API] Created new poll response for player {player.name} ({player.id}) "
                           f"with response {response} for poll {poll_id}")
            
            # Get updated response counts
            response_counts = poll.get_response_counts()
            
            logger.info(f"🟢 [AVAILABILITY_API] Poll response recorded successfully for poll {poll_id}")
            return jsonify({
                'success': True,
                'action': action,
                'player_name': player.name,
                'response': response,
                'poll_id': poll_id,
                'response_counts': response_counts
            })
        
    except Exception as e:
        logger.error(f"🔴 [AVAILABILITY_API] Error recording poll response: {str(e)}", exc_info=True)
        return jsonify({
            'error': f'Error recording poll response: {str(e)}'
        }), 500


@availability_bp.route('/update_poll_message', methods=['POST'])
def update_poll_message():
    """
    Updates the Discord message ID for a poll message after it's sent.
    
    Expected JSON:
    {
        "message_record_id": int,
        "message_id": str,
        "sent_at": str (ISO datetime)
    }
    """
    logger.info(f"🔵 [AVAILABILITY_API] update_poll_message called")
    
    try:
        data = request.get_json()
        logger.debug(f"🔵 [AVAILABILITY_API] Updating poll message: {data}")
        
        if not data:
            logger.error(f"🔴 [AVAILABILITY_API] No data provided")
            return jsonify({'error': 'No data provided'}), 400
        
        message_record_id = data.get('message_record_id')
        message_id = data.get('message_id')
        sent_at = data.get('sent_at')
        
        if not all([message_record_id, message_id]):
            logger.error(f"🔴 [AVAILABILITY_API] Missing required fields: message_record_id={message_record_id}, message_id={message_id}")
            return jsonify({'error': 'Missing required fields'}), 400
        
        with managed_session() as session_db:
            from app.models import LeaguePollDiscordMessage
            
            # Find the message record
            logger.debug(f"🔵 [AVAILABILITY_API] Looking up message record {message_record_id}")
            message_record = session_db.query(LeaguePollDiscordMessage).get(message_record_id)
            if not message_record:
                logger.error(f"🔴 [AVAILABILITY_API] Message record {message_record_id} not found")
                return jsonify({'error': 'Message record not found'}), 404
            
            # Update the message ID and sent timestamp
            message_record.message_id = message_id
            message_record.sent_at = datetime.fromisoformat(sent_at) if sent_at else datetime.utcnow()
            
            logger.info(f"🟢 [AVAILABILITY_API] Updated poll message record {message_record_id} with Discord message ID {message_id}")
            
            return jsonify({
                'success': True,
                'message': 'Poll message record updated successfully'
            })
        
    except Exception as e:
        logger.error(f"🔴 [AVAILABILITY_API] Error updating poll message: {str(e)}", exc_info=True)
        return jsonify({
            'error': f'Error updating poll message: {str(e)}'
        }), 500


@availability_bp.route('/get_active_poll_messages', methods=['GET'])
def get_active_poll_messages():
    """
    Get all active poll messages with their Discord message IDs.
    Returns data needed by the Discord bot to track poll reactions.
    """
    logger.info(f"🔵 [AVAILABILITY_API] get_active_poll_messages called")
    
    try:
        with managed_session() as session_db:
            from app.models import LeaguePoll, LeaguePollDiscordMessage
            
            # Get all active polls with their Discord messages
            logger.debug(f"🔵 [AVAILABILITY_API] Querying for active poll messages")
            active_poll_messages = session_db.query(
                LeaguePollDiscordMessage
            ).join(
                LeaguePoll, LeaguePoll.id == LeaguePollDiscordMessage.poll_id
            ).filter(
                LeaguePoll.status == 'ACTIVE',
                LeaguePollDiscordMessage.message_id.isnot(None)
            ).all()
            
            result = []
            for msg in active_poll_messages:
                result.append({
                    'poll_id': msg.poll_id,
                    'team_id': msg.team_id,
                    'channel_id': msg.channel_id,
                    'message_id': msg.message_id
                })
            
            logger.info(f"🟢 [AVAILABILITY_API] Returning {len(result)} active poll messages")
            return jsonify(result)
        
    except Exception as e:
        logger.error(f"🔴 [AVAILABILITY_API] Error getting active poll messages: {str(e)}", exc_info=True)
        return jsonify({
            'error': f'Error getting active poll messages: {str(e)}'
        }), 500