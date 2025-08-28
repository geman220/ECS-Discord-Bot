"""
ECS FC API Module

This module provides REST API endpoints for ECS FC schedule management.
All endpoints are protected by authentication and authorization checks.
"""

import logging
from datetime import datetime, date, time
from typing import Dict, Any, List
from flask import Blueprint, request, jsonify, g
from flask_login import login_required, current_user
from sqlalchemy import func

from app import csrf
from app.core import db
from app.core.session_manager import managed_session
from app.models import Team, League, Player, User
from app.models_ecs import EcsFcMatch, EcsFcAvailability, EcsFcScheduleTemplate
from app.models_ecs_subs import EcsFcSubRequest, EcsFcSubResponse, EcsFcSubAssignment, EcsFcSubPool
from app.ecs_fc_schedule import EcsFcScheduleManager, is_user_ecs_fc_coach, get_upcoming_ecs_fc_matches
from app.tasks.tasks_ecs_fc_subs import process_sub_response
from app.decorators import role_required
from app.api_utils import validate_json_request, create_api_response
from app.utils.user_helpers import safe_current_user

logger = logging.getLogger(__name__)

# Create blueprint
ecs_fc_api = Blueprint('ecs_fc_api', __name__, url_prefix='/api/ecs-fc')

# Exempt from CSRF protection since it's an API used by Discord bot
csrf.exempt(ecs_fc_api)


def validate_ecs_fc_coach_access(team_id: int) -> bool:
    """
    Validate that the current user has coach access to the ECS FC team.
    
    Args:
        team_id: ID of the team
        
    Returns:
        True if user has access, False otherwise
    """
    # Check for role impersonation first, then fall back to real roles
    from app.role_impersonation import is_impersonation_active, get_effective_roles
    
    if is_impersonation_active():
        effective_roles = get_effective_roles()
    else:
        effective_roles = [role.name for role in safe_current_user.roles]
    
    # Check if user has proper ECS FC permissions through roles
    has_ecs_fc_access = (
        'Global Admin' in effective_roles or
        'Pub League Admin' in effective_roles or
        'ECS FC Coach' in effective_roles
    )
    
    if not has_ecs_fc_access:
        return False
    
    # Don't allow if user is ONLY a player role
    if effective_roles == ['pl-classic'] or effective_roles == ['pl-ecs-fc'] or effective_roles == ['pl-premier']:
        return False
    
    return True


@ecs_fc_api.route('/matches', methods=['POST'])
@login_required
def create_match():
    """Create a new ECS FC match."""
    try:
        # Validate JSON request
        data = validate_json_request(request)
        if not data:
            return create_api_response(False, "Invalid JSON data", status_code=400)
        
        # Required fields
        required_fields = ['team_id', 'opponent_name', 'match_date', 'match_time', 'location']
        for field in required_fields:
            if field not in data:
                return create_api_response(False, f"Missing required field: {field}", status_code=400)
        
        team_id = data['team_id']
        
        # Check authorization
        if not validate_ecs_fc_coach_access(team_id):
            return create_api_response(False, "Unauthorized access to this team", status_code=403)
        
        # Parse date and time
        try:
            match_date = datetime.strptime(data['match_date'], '%Y-%m-%d').date()
            match_time = datetime.strptime(data['match_time'], '%H:%M').time()
        except ValueError as e:
            return create_api_response(False, f"Invalid date/time format: {str(e)}", status_code=400)
        
        # Parse optional RSVP deadline
        rsvp_deadline = None
        if data.get('rsvp_deadline'):
            try:
                rsvp_deadline = datetime.fromisoformat(data['rsvp_deadline'])
            except ValueError:
                return create_api_response(False, "Invalid RSVP deadline format", status_code=400)
        
        # Create match
        success, message, match = EcsFcScheduleManager.create_match(
            team_id=team_id,
            opponent_name=data['opponent_name'],
            match_date=match_date,
            match_time=match_time,
            location=data['location'],
            field_name=data.get('field_name'),
            is_home_match=data.get('is_home_match', True),
            notes=data.get('notes'),
            created_by=current_user.id,
            rsvp_deadline=rsvp_deadline
        )
        
        if success and match:
            return create_api_response(True, message, {'match': match.to_dict()})
        else:
            return create_api_response(False, message, status_code=400)
            
    except Exception as e:
        logger.error(f"Error creating ECS FC match: {str(e)}")
        return create_api_response(False, f"Internal server error: {str(e)}", status_code=500)


@ecs_fc_api.route('/matches/<int:match_id>', methods=['GET'])
@login_required
def get_match(match_id: int):
    """Get a specific ECS FC match."""
    try:
        match = EcsFcScheduleManager.get_match_by_id(match_id)
        if not match:
            return create_api_response(False, "Match not found", status_code=404)
        
        # Check authorization
        if not validate_ecs_fc_coach_access(match.team_id):
            return create_api_response(False, "Unauthorized access to this match", status_code=403)
        
        return create_api_response(True, "Match found", {
            'match': match.to_dict(include_rsvp=True)
        })
        
    except Exception as e:
        logger.error(f"Error getting ECS FC match {match_id}: {str(e)}")
        return create_api_response(False, f"Internal server error: {str(e)}", status_code=500)


@ecs_fc_api.route('/matches/<int:match_id>', methods=['PUT'])
@login_required
def update_match(match_id: int):
    """Update an existing ECS FC match."""
    try:
        # Validate JSON request
        data = validate_json_request(request)
        if not data:
            return create_api_response(False, "Invalid JSON data", status_code=400)
        
        # Get the match first to check authorization
        match = EcsFcScheduleManager.get_match_by_id(match_id)
        if not match:
            return create_api_response(False, "Match not found", status_code=404)
        
        # Check authorization
        if not validate_ecs_fc_coach_access(match.team_id):
            return create_api_response(False, "Unauthorized access to this match", status_code=403)
        
        # Parse date and time if provided
        if 'match_date' in data:
            try:
                data['match_date'] = datetime.strptime(data['match_date'], '%Y-%m-%d').date()
            except ValueError as e:
                return create_api_response(False, f"Invalid date format: {str(e)}", status_code=400)
        
        if 'match_time' in data:
            try:
                data['match_time'] = datetime.strptime(data['match_time'], '%H:%M').time()
            except ValueError as e:
                return create_api_response(False, f"Invalid time format: {str(e)}", status_code=400)
        
        # Parse RSVP deadline if provided
        if 'rsvp_deadline' in data and data['rsvp_deadline']:
            try:
                data['rsvp_deadline'] = datetime.fromisoformat(data['rsvp_deadline'])
            except ValueError:
                return create_api_response(False, "Invalid RSVP deadline format", status_code=400)
        
        # Update match
        success, message, updated_match = EcsFcScheduleManager.update_match(match_id, **data)
        
        if success and updated_match:
            return create_api_response(True, message, {'match': updated_match.to_dict()})
        else:
            return create_api_response(False, message, status_code=400)
            
    except Exception as e:
        logger.error(f"Error updating ECS FC match {match_id}: {str(e)}")
        return create_api_response(False, f"Internal server error: {str(e)}", status_code=500)


@ecs_fc_api.route('/matches/<int:match_id>', methods=['DELETE'])
@login_required
def delete_match(match_id: int):
    """Delete an ECS FC match."""
    try:
        # Get the match first to check authorization
        match = EcsFcScheduleManager.get_match_by_id(match_id)
        if not match:
            return create_api_response(False, "Match not found", status_code=404)
        
        # Check authorization
        if not validate_ecs_fc_coach_access(match.team_id):
            return create_api_response(False, "Unauthorized access to this match", status_code=403)
        
        # Delete match
        success, message = EcsFcScheduleManager.delete_match(match_id)
        
        if success:
            return create_api_response(True, message)
        else:
            return create_api_response(False, message, status_code=400)
            
    except Exception as e:
        logger.error(f"Error deleting ECS FC match {match_id}: {str(e)}")
        return create_api_response(False, f"Internal server error: {str(e)}", status_code=500)


@ecs_fc_api.route('/teams/<int:team_id>/matches', methods=['GET'])
@login_required
def get_team_matches(team_id: int):
    """Get matches for a specific team."""
    try:
        # Check authorization
        if not validate_ecs_fc_coach_access(team_id):
            return create_api_response(False, "Unauthorized access to this team", status_code=403)
        
        # Parse query parameters
        upcoming_only = request.args.get('upcoming_only', 'false').lower() == 'true'
        limit = request.args.get('limit', type=int)
        offset = request.args.get('offset', type=int, default=0)
        
        # Get matches
        matches = EcsFcScheduleManager.get_team_matches(
            team_id=team_id,
            upcoming_only=upcoming_only,
            limit=limit,
            offset=offset
        )
        
        # Convert to dict format
        matches_data = [match.to_dict() for match in matches]
        
        return create_api_response(True, f"Found {len(matches)} matches", {
            'matches': matches_data,
            'total': len(matches_data)
        })
        
    except Exception as e:
        logger.error(f"Error getting team matches for team {team_id}: {str(e)}")
        return create_api_response(False, f"Internal server error: {str(e)}", status_code=500)


@ecs_fc_api.route('/teams/<int:team_id>/matches/calendar', methods=['GET'])
@login_required
def get_team_calendar(team_id: int):
    """Get calendar data for a specific team."""
    try:
        # Check authorization
        if not validate_ecs_fc_coach_access(team_id):
            return create_api_response(False, "Unauthorized access to this team", status_code=403)
        
        # Parse date range parameters
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')
        
        if not start_date_str or not end_date_str:
            return create_api_response(False, "Missing start_date or end_date parameters", status_code=400)
        
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except ValueError as e:
            return create_api_response(False, f"Invalid date format: {str(e)}", status_code=400)
        
        # Get matches in date range
        matches = EcsFcScheduleManager.get_matches_for_date_range(team_id, start_date, end_date)
        
        # Format for calendar
        calendar_events = []
        for match in matches:
            event = {
                'id': match.id,
                'title': f"vs {match.opponent_name}",
                'start': f"{match.match_date}T{match.match_time}",
                'backgroundColor': '#3498db' if match.is_home_match else '#e74c3c',
                'textColor': '#ffffff',
                'extendedProps': {
                    'opponent': match.opponent_name,
                    'location': match.location,
                    'field_name': match.field_name,
                    'is_home_match': match.is_home_match,
                    'notes': match.notes,
                    'status': match.status
                }
            }
            calendar_events.append(event)
        
        return create_api_response(True, f"Found {len(calendar_events)} calendar events", {
            'events': calendar_events
        })
        
    except Exception as e:
        logger.error(f"Error getting team calendar for team {team_id}: {str(e)}")
        return create_api_response(False, f"Internal server error: {str(e)}", status_code=500)


@ecs_fc_api.route('/matches/<int:match_id>/rsvp', methods=['POST'])
@login_required
def submit_rsvp(match_id: int):
    """Submit RSVP for a match."""
    try:
        # Validate JSON request
        data = validate_json_request(request)
        if not data:
            return create_api_response(False, "Invalid JSON data", status_code=400)
        
        # Required fields
        if 'response' not in data:
            return create_api_response(False, "Missing required field: response", status_code=400)
        
        response = data['response']
        if response not in ['yes', 'no', 'maybe']:
            return create_api_response(False, "Invalid response value", status_code=400)
        
        # Get player ID - could be from data or current user's player
        player_id = data.get('player_id')
        if not player_id:
            # Try to get player from current user
            if hasattr(current_user, 'player') and current_user.player:
                player_id = current_user.player.id
            else:
                return create_api_response(False, "No player ID provided and user has no associated player", status_code=400)
        
        # Submit RSVP
        success, message = EcsFcScheduleManager.submit_rsvp(
            match_id=match_id,
            player_id=player_id,
            response=response,
            user_id=current_user.id,
            discord_id=data.get('discord_id'),
            notes=data.get('notes')
        )
        
        if success:
            return create_api_response(True, message)
        else:
            return create_api_response(False, message, status_code=400)
            
    except Exception as e:
        logger.error(f"Error submitting RSVP for match {match_id}: {str(e)}")
        return create_api_response(False, f"Internal server error: {str(e)}", status_code=500)


@ecs_fc_api.route('/matches/<int:match_id>/rsvp', methods=['GET'])
@login_required
def get_rsvp_summary(match_id: int):
    """Get RSVP summary for a match."""
    try:
        # Get the match first to check authorization
        match = EcsFcScheduleManager.get_match_by_id(match_id)
        if not match:
            return create_api_response(False, "Match not found", status_code=404)
        
        # Check authorization
        if not validate_ecs_fc_coach_access(match.team_id):
            return create_api_response(False, "Unauthorized access to this match", status_code=403)
        
        # Get RSVP summary
        summary = EcsFcScheduleManager.get_rsvp_summary(match_id)
        
        if 'error' in summary:
            return create_api_response(False, summary['error'], status_code=400)
        
        return create_api_response(True, "RSVP summary retrieved", {'rsvp_summary': summary})
        
    except Exception as e:
        logger.error(f"Error getting RSVP summary for match {match_id}: {str(e)}")
        return create_api_response(False, f"Internal server error: {str(e)}", status_code=500)


@ecs_fc_api.route('/matches/<int:match_id>/remind', methods=['POST'])
@login_required
def send_rsvp_reminders(match_id: int):
    """Send RSVP reminders for a match."""
    try:
        # Get the match first to check authorization
        match = EcsFcScheduleManager.get_match_by_id(match_id)
        if not match:
            return create_api_response(False, "Match not found", status_code=404)
        
        # Check authorization
        if not validate_ecs_fc_coach_access(match.team_id):
            return create_api_response(False, "Unauthorized access to this match", status_code=403)
        
        # Parse optional target players
        data = request.get_json() or {}
        target_players = data.get('target_players')
        
        # Send reminders
        success, message = EcsFcScheduleManager.send_rsvp_reminders(match_id, target_players)
        
        if success:
            return create_api_response(True, message)
        else:
            return create_api_response(False, message, status_code=400)
            
    except Exception as e:
        logger.error(f"Error sending RSVP reminders for match {match_id}: {str(e)}")
        return create_api_response(False, f"Internal server error: {str(e)}", status_code=500)


@ecs_fc_api.route('/matches/import', methods=['POST'])
@login_required
def bulk_import_matches():
    """Bulk import matches from CSV data."""
    try:
        # Validate JSON request
        data = validate_json_request(request)
        if not data:
            return create_api_response(False, "Invalid JSON data", status_code=400)
        
        # Required fields
        if 'team_id' not in data or 'matches' not in data:
            return create_api_response(False, "Missing required fields: team_id, matches", status_code=400)
        
        team_id = data['team_id']
        matches_data = data['matches']
        
        # Check authorization
        if not validate_ecs_fc_coach_access(team_id):
            return create_api_response(False, "Unauthorized access to this team", status_code=403)
        
        # Validate matches data
        if not isinstance(matches_data, list):
            return create_api_response(False, "Matches data must be a list", status_code=400)
        
        # Import matches
        success, message, created_match_ids = EcsFcScheduleManager.bulk_import_matches(
            team_id=team_id,
            matches_data=matches_data,
            created_by=current_user.id
        )
        
        response_data = {
            'created_matches': created_match_ids,
            'total_created': len(created_match_ids)
        }
        
        if success:
            return create_api_response(True, message, response_data)
        else:
            return create_api_response(False, message, response_data, status_code=400)
            
    except Exception as e:
        logger.error(f"Error bulk importing matches: {str(e)}")
        return create_api_response(False, f"Internal server error: {str(e)}", status_code=500)


# Discord Bot Integration Endpoints

@ecs_fc_api.route('/matches/<int:match_id>/rsvp-summary', methods=['GET'])
def get_match_rsvp_summary(match_id: int):
    """Get RSVP summary for a specific match - used by Discord bot."""
    try:
        logger.info(f"🔵 [ECS_FC_API] Getting RSVP summary for match {match_id}")
        
        match = EcsFcScheduleManager.get_match_by_id(match_id)
        if not match:
            logger.warning(f"🔵 [ECS_FC_API] Match {match_id} not found")
            return create_api_response(False, "Match not found", status_code=404)
        
        response_counts = match.get_rsvp_summary()
        logger.info(f"🔵 [ECS_FC_API] Retrieved RSVP summary for match {match_id}: {response_counts}")
        
        return create_api_response(True, "RSVP summary retrieved", {
            'match_id': match_id,
            'response_counts': response_counts
        })
        
    except Exception as e:
        logger.error(f"🔵 [ECS_FC_API] Error getting RSVP summary for match {match_id}: {str(e)}", exc_info=True)
        return create_api_response(False, f"Internal server error: {str(e)}", status_code=500)


@ecs_fc_api.route('/store_rsvp_message', methods=['POST'])
def store_rsvp_message():
    """Store RSVP message information for future updates - used by Discord bot."""
    try:
        logger.info("🔵 [ECS_FC_API] Processing store_rsvp_message request")
        
        data = validate_json_request(request)
        if not data:
            logger.warning("🔵 [ECS_FC_API] Invalid JSON data received")
            return create_api_response(False, "Invalid JSON data", status_code=400)
        
        required_fields = ['match_id', 'message_id', 'channel_id']
        for field in required_fields:
            if field not in data:
                logger.warning(f"🔵 [ECS_FC_API] Missing required field: {field}")
                return create_api_response(False, f"Missing required field: {field}", status_code=400)
        
        logger.info(f"🔵 [ECS_FC_API] Storing RSVP message for match {data['match_id']}, message {data['message_id']}")
        
        with managed_session() as session_db:
            # Check if this message is already stored (idempotency)
            from app.models import ScheduledMessage
            
            existing_message = session_db.query(ScheduledMessage).filter(
                ScheduledMessage.message_type == 'ecs_fc_rsvp',
                ScheduledMessage.message_metadata.op('->>')('discord_message_id') == str(data['message_id'])
            ).first()
            
            if existing_message:
                logger.info(f"🔵 [ECS_FC_API] RSVP message {data['message_id']} already stored with ID {existing_message.id}")
                return create_api_response(True, "RSVP message information already stored", {
                    'scheduled_message_id': existing_message.id
                })
            
            # Store in scheduled_message table with ECS FC metadata
            scheduled_message = ScheduledMessage(
                match_id=None,  # ECS FC matches don't use the regular match_id field
                scheduled_send_time=datetime.utcnow(),  # Required field - set to now since already sent
                status='SENT',  # Message has already been sent
                message_type='ecs_fc_rsvp',
                message_metadata={
                    'ecs_fc_match_id': data['match_id'],
                    'discord_message_id': data['message_id'],
                    'discord_channel_id': data['channel_id']
                },
                sent_at=datetime.utcnow()
            )
            
            session_db.add(scheduled_message)
            session_db.commit()
            
            logger.info(f"🔵 [ECS_FC_API] Successfully stored RSVP message {data['message_id']} with scheduled_message_id {scheduled_message.id}")
            
            return create_api_response(True, "RSVP message information stored", {
                'scheduled_message_id': scheduled_message.id
            })
        
    except Exception as e:
        logger.error(f"🔵 [ECS_FC_API] Error storing RSVP message: {str(e)}", exc_info=True)
        return create_api_response(False, f"Internal server error: {str(e)}", status_code=500)


@ecs_fc_api.route('/rsvp_message/<int:match_id>', methods=['GET'])
def get_rsvp_message(match_id: int):
    """Get stored RSVP message information for a match - used by Discord bot."""
    try:
        logger.info(f"🔵 [ECS_FC_API] Getting RSVP message for match {match_id}")
        
        with managed_session() as session_db:
            from app.models import ScheduledMessage
            
            # Look specifically for the message that contains Discord message ID
            scheduled_message = session_db.query(ScheduledMessage).filter(
                ScheduledMessage.message_type == 'ecs_fc_rsvp',
                ScheduledMessage.message_metadata.op('->>')('ecs_fc_match_id') == str(match_id),
                ScheduledMessage.message_metadata.has_key('discord_message_id')
            ).first()
            
            if not scheduled_message:
                logger.warning(f"🔵 [ECS_FC_API] RSVP message not found for match {match_id}")
                return create_api_response(False, "RSVP message not found", status_code=404)
            
            metadata = scheduled_message.message_metadata or {}
            logger.info(f"🔵 [ECS_FC_API] Found RSVP message for match {match_id}: {metadata.get('discord_message_id')}")
            
            return create_api_response(True, "RSVP message found", {
                'message_id': metadata.get('discord_message_id'),
                'channel_id': metadata.get('discord_channel_id'),
                'metadata': metadata
            })
        
    except Exception as e:
        logger.error(f"🔵 [ECS_FC_API] Error getting RSVP message for match {match_id}: {str(e)}", exc_info=True)
        return create_api_response(False, f"Internal server error: {str(e)}", status_code=500)


@ecs_fc_api.route('/rsvp/update', methods=['POST'])
def update_rsvp():
    """Update a player's RSVP response - used by Discord bot."""
    try:
        logger.info("🔵 [ECS_FC_API] Processing RSVP update request")
        
        data = validate_json_request(request)
        if not data:
            logger.warning("🔵 [ECS_FC_API] Invalid JSON data received for RSVP update")
            return create_api_response(False, "Invalid JSON data", status_code=400)
        
        required_fields = ['match_id', 'response']
        for field in required_fields:
            if field not in data:
                logger.warning(f"🔵 [ECS_FC_API] Missing required field for RSVP update: {field}")
                return create_api_response(False, f"Missing required field: {field}", status_code=400)
        
        match_id = data['match_id']
        response = data['response']
        discord_id = data.get('discord_id')
        player_id = data.get('player_id')
        
        logger.info(f"🔵 [ECS_FC_API] Updating RSVP for match {match_id}, response: {response}, discord_id: {discord_id}, player_id: {player_id}")
        
        with managed_session() as session_db:
            # If no player_id provided, look up by discord_id
            if not player_id and discord_id:
                player = session_db.query(Player).filter(Player.discord_id == str(discord_id)).first()
                if not player:
                    logger.warning(f"🔵 [ECS_FC_API] No player found with Discord ID {discord_id}")
                    return create_api_response(False, f"No player found with Discord ID {discord_id}", status_code=404)
                player_id = player.id
                logger.info(f"🔵 [ECS_FC_API] Found player {player_id} for Discord ID {discord_id}")
            elif not player_id:
                logger.warning("🔵 [ECS_FC_API] Neither player_id nor discord_id provided")
                return create_api_response(False, "Either player_id or discord_id must be provided", status_code=400)
            
            # Validate response value
            if response not in ['yes', 'no', 'maybe', 'no_response']:
                logger.warning(f"🔵 [ECS_FC_API] Invalid response value: {response}")
                return create_api_response(False, "Invalid response value", status_code=400)
            
            # Get or create availability record
            from app.models_ecs import EcsFcAvailability
            
            availability = session_db.query(EcsFcAvailability).filter(
                EcsFcAvailability.ecs_fc_match_id == match_id,
                EcsFcAvailability.player_id == player_id
            ).first()
            
            if response == 'no_response':
                # Remove the availability record
                if availability:
                    logger.info(f"🔵 [ECS_FC_API] Removing RSVP record for player {player_id}, match {match_id}")
                    session_db.delete(availability)
                else:
                    logger.info(f"🔵 [ECS_FC_API] No RSVP record to remove for player {player_id}, match {match_id}")
            else:
                # Update or create availability record
                if availability:
                    logger.info(f"🔵 [ECS_FC_API] Updating existing RSVP for player {player_id}, match {match_id}")
                    availability.response = response
                    availability.response_time = datetime.utcnow()
                    availability.discord_id = discord_id
                else:
                    logger.info(f"🔵 [ECS_FC_API] Creating new RSVP for player {player_id}, match {match_id}")
                    availability = EcsFcAvailability(
                        ecs_fc_match_id=match_id,
                        player_id=player_id,
                        response=response,
                        response_time=datetime.utcnow(),
                        discord_id=discord_id
                    )
                    session_db.add(availability)
            
            session_db.commit()
            
            # Emit WebSocket update for real-time sync
            try:
                from app.sockets.rsvp import emit_rsvp_update
                
                # Get player details for WebSocket emission
                player = session_db.query(Player).get(player_id)
                
                if player:
                    # For ECS FC matches, use the match_id as team_id
                    # Note: ECS FC matches use a different format than regular matches
                    emit_rsvp_update(
                        match_id=f"ecs_{match_id}",  # Use ECS FC match format
                        player_id=player_id,
                        availability=response,
                        source='ecs_fc',
                        player_name=player.name,
                        team_id=match_id  # For ECS FC, match_id serves as team identifier
                    )
                    
                    logger.info(f"📤 WebSocket RSVP update emitted from ECS FC: match=ecs_{match_id}, player={player.name}, response={response}")
                    
            except Exception as e:
                logger.error(f"⚠️ Failed to emit WebSocket RSVP update from ECS FC: {e}")
                # Don't fail the ECS FC RSVP - database update was successful
            
            logger.info(f"🔵 [ECS_FC_API] Successfully updated RSVP for player {player_id}, match {match_id}, response: {response}")
            
            return create_api_response(True, "RSVP updated successfully", {
                'match_id': match_id,
                'player_id': player_id,
                'response': response
            })
        
    except Exception as e:
        logger.error(f"🔵 [ECS_FC_API] Error updating RSVP: {str(e)}", exc_info=True)
        return create_api_response(False, f"Internal server error: {str(e)}", status_code=500)


@ecs_fc_api.route('/rsvp/update_v2', methods=['POST'])
def update_rsvp_enterprise():
    """
    Enterprise RSVP update endpoint for Discord bot with full reliability.
    
    Provides the same interface as the legacy endpoint but uses the enterprise
    RSVP service with idempotency, event publishing, and circuit breaker protection.
    """
    import asyncio
    from app.events.rsvp_events import RSVPSource
    from app.services.rsvp_service import create_rsvp_service
    
    try:
        logger.info("🔵 [ECS_FC_API_V2] Processing enterprise RSVP update request")
        
        data = validate_json_request(request)
        if not data:
            logger.warning("🔵 [ECS_FC_API_V2] Invalid JSON data received")
            return create_api_response(False, "Invalid JSON data", status_code=400)
        
        required_fields = ['match_id', 'response']
        for field in required_fields:
            if field not in data:
                logger.warning(f"🔵 [ECS_FC_API_V2] Missing required field: {field}")
                return create_api_response(False, f"Missing required field: {field}", status_code=400)
        
        match_id = data['match_id']
        response = data['response']
        discord_id = data.get('discord_id')
        player_id = data.get('player_id')
        operation_id = data.get('operation_id')  # For idempotency
        
        logger.info(f"🔵 [ECS_FC_API_V2] Enterprise RSVP update: match={match_id}, response={response}, "
                   f"discord_id={discord_id}, player_id={player_id}, operation_id={operation_id}")
        
        with managed_session() as session_db:
            # If no player_id provided, look up by discord_id
            if not player_id and discord_id:
                from app.models import Player
                player = session_db.query(Player).filter(Player.discord_id == str(discord_id)).first()
                if not player:
                    logger.warning(f"🔵 [ECS_FC_API_V2] No player found with Discord ID {discord_id}")
                    return create_api_response(False, f"No player found with Discord ID {discord_id}", status_code=404)
                player_id = player.id
                logger.info(f"🔵 [ECS_FC_API_V2] Found player {player_id} for Discord ID {discord_id}")
            elif not player_id:
                logger.warning("🔵 [ECS_FC_API_V2] Neither player_id nor discord_id provided")
                return create_api_response(False, "Either player_id or discord_id must be provided", status_code=400)
            
            # Validate response value
            if response not in ['yes', 'no', 'maybe', 'no_response']:
                logger.warning(f"🔵 [ECS_FC_API_V2] Invalid response value: {response}")
                return create_api_response(False, "Invalid response value", status_code=400)
            
            # Verify match exists (for regular Match table, not ECS FC specific)
            from app.models import Match
            match = session_db.query(Match).get(match_id)
            if not match:
                logger.warning(f"🔵 [ECS_FC_API_V2] Match {match_id} not found")
                return create_api_response(False, "Match not found", status_code=404)
            
            # Collect context for audit trail
            user_context = {
                'ip_address': request.remote_addr,
                'user_agent': request.headers.get('User-Agent'),
                'source_endpoint': 'ecs_fc_api_v2',
                'discord_id': discord_id
            }
            
            # Use synchronous RSVP update for Flask compatibility
            from app.utils.sync_discord_client import get_sync_discord_client
            
            try:
                # Use synchronous Discord operations instead of async
                discord_client = get_sync_discord_client()
                
                # Simple synchronous RSVP update logic
                success = True
                message = "RSVP updated successfully"
                event = None
                
                # Update the player's RSVP in database
                from app.models import Match, Player, RSVP, RSVPStatus
                match = session_db.query(Match).get(match_id)
                player = session_db.query(Player).get(player_id)
                
                if match and player:
                    # Find or create RSVP record
                    rsvp = session_db.query(RSVP).filter_by(
                        match_id=match_id, 
                        player_id=player_id
                    ).first()
                    
                    if not rsvp:
                        rsvp = RSVP(match_id=match_id, player_id=player_id)
                        session_db.add(rsvp)
                    
                    # Update RSVP response
                    rsvp.response = response
                    rsvp.updated_at = datetime.utcnow()
                    session_db.commit()
                    
                    logger.info(f"Updated RSVP for player {player_id} match {match_id}: {response}")
                else:
                    success = False
                    message = "Match or player not found"
                    logger.error(f"Match {match_id} or player {player_id} not found")
                    
            except Exception as e:
                success = False
                message = f"Error updating RSVP: {str(e)}"
                logger.error(f"Error in sync RSVP update: {e}")
            
            if success:
                response_data = {
                    'match_id': match_id,
                    'player_id': player_id,
                    'response': response
                }
                
                # Include enterprise metadata
                if event:
                    response_data.update({
                        'trace_id': event.trace_id,
                        'operation_id': event.operation_id,
                        'event_id': event.event_id
                    })
                
                logger.info(f"✅ [ECS_FC_API_V2] Enterprise RSVP update successful: {message}, "
                           f"trace_id={event.trace_id if event else 'none'}")
                
                return create_api_response(True, message, response_data)
            else:
                logger.warning(f"⚠️ [ECS_FC_API_V2] Enterprise RSVP update failed: {message}")
                return create_api_response(False, message, status_code=400)
        
    except Exception as e:
        logger.error(f"❌ [ECS_FC_API_V2] Error in enterprise RSVP update: {str(e)}", exc_info=True)
        return create_api_response(False, f"Internal server error: {str(e)}", status_code=500)


@ecs_fc_api.route('/team_channel/<int:team_id>', methods=['GET'])
def get_team_channel_id(team_id: int):
    """Get Discord channel ID for a team - used by Discord bot."""
    try:
        logger.info(f"🔵 [ECS_FC_API] Getting Discord channel ID for team {team_id}")
        
        with managed_session() as session_db:
            from app.models import Team
            
            team = session_db.query(Team).filter(Team.id == team_id).first()
            if not team:
                logger.warning(f"🔵 [ECS_FC_API] Team {team_id} not found")
                return create_api_response(False, "Team not found", status_code=404)
            
            if not team.discord_channel_id:
                logger.warning(f"🔵 [ECS_FC_API] Team {team_id} ({team.name}) has no Discord channel ID")
                return create_api_response(False, "Team has no Discord channel", status_code=404)
            
            logger.info(f"🔵 [ECS_FC_API] Found Discord channel {team.discord_channel_id} for team {team_id} ({team.name})")
            
            return create_api_response(True, "Channel ID found", {
                'channel_id': team.discord_channel_id,
                'team_id': team_id,
                'team_name': team.name
            })
        
    except Exception as e:
        logger.error(f"🔵 [ECS_FC_API] Error getting channel ID for team {team_id}: {str(e)}", exc_info=True)
        return create_api_response(False, f"Internal server error: {str(e)}", status_code=500)


@ecs_fc_api.route('/teams', methods=['GET'])
@login_required
def get_user_teams():
    """Get ECS FC teams that the current user can manage."""
    try:
        logger.info(f"🔵 [ECS_FC_API] Getting teams for user {current_user.id}")
        
        # Get teams the user can coach
        coached_teams = is_user_ecs_fc_coach(current_user.id)
        
        if not coached_teams:
            logger.info(f"🔵 [ECS_FC_API] No teams found for user {current_user.id}")
            return create_api_response(True, "No teams found", {'teams': []})
        
        logger.info(f"🔵 [ECS_FC_API] User {current_user.id} can coach teams: {coached_teams}")
        
        with managed_session() as session_db:
            # Get team details
            teams = session_db.query(Team).filter(Team.id.in_(coached_teams)).all()
            
            teams_data = []
            for team in teams:
                team_data = {
                    'id': team.id,
                    'name': team.name,
                    'league_name': team.league.name if team.league else None,
                    'player_count': len(team.players)
                }
                teams_data.append(team_data)
                logger.debug(f"🔵 [ECS_FC_API] Team {team.id}: {team.name} ({len(team.players)} players)")
            
            logger.info(f"🔵 [ECS_FC_API] Found {len(teams_data)} teams for user {current_user.id}")
            return create_api_response(True, f"Found {len(teams_data)} teams", {'teams': teams_data})
        
    except Exception as e:
        logger.error(f"🔵 [ECS_FC_API] Error getting user teams: {str(e)}", exc_info=True)
        return create_api_response(False, f"Internal server error: {str(e)}", status_code=500)


@ecs_fc_api.route('/matches/upcoming', methods=['GET'])
@login_required
def get_upcoming_matches():
    """Get upcoming matches for teams the user can manage."""
    try:
        logger.info(f"🔵 [ECS_FC_API] Getting upcoming matches for user {current_user.id}")
        
        # Get teams the user can coach
        coached_teams = is_user_ecs_fc_coach(current_user.id)
        
        if not coached_teams:
            logger.info(f"🔵 [ECS_FC_API] No teams found for user {current_user.id}")
            return create_api_response(True, "No teams found", {'matches': []})
        
        # Parse days ahead parameter
        days_ahead = request.args.get('days_ahead', type=int, default=7)
        logger.info(f"🔵 [ECS_FC_API] Getting matches {days_ahead} days ahead for teams: {coached_teams}")
        
        # Get upcoming matches for all coached teams
        all_matches = []
        for team_id in coached_teams:
            matches = get_upcoming_ecs_fc_matches(team_id, days_ahead)
            all_matches.extend(matches)
            logger.debug(f"🔵 [ECS_FC_API] Found {len(matches)} matches for team {team_id}")
        
        # Sort by date and time
        all_matches.sort(key=lambda x: (x.match_date, x.match_time))
        
        # Convert to dict format
        matches_data = [match.to_dict() for match in all_matches]
        
        logger.info(f"🔵 [ECS_FC_API] Found {len(matches_data)} total upcoming matches for user {current_user.id}")
        
        return create_api_response(True, f"Found {len(matches_data)} upcoming matches", {
            'matches': matches_data
        })
        
    except Exception as e:
        logger.error(f"🔵 [ECS_FC_API] Error getting upcoming matches: {str(e)}", exc_info=True)
        return create_api_response(False, f"Internal server error: {str(e)}", status_code=500)


@ecs_fc_api.route('/process-sub-response', methods=['POST'])
def process_ecs_fc_sub_response():
    """
    Process a substitute response from Discord or SMS.
    
    Expected JSON payload:
    {
        "discord_id": "123456789012345678",
        "response_text": "YES",
        "response_method": "DISCORD"
    }
    Optional fields:
    {
        "request_id": 1,
        "response_id": 1
    }
    """
    try:
        logger.info("🔵 [ECS_FC_API] Processing substitute response")
        
        if not request.is_json:
            logger.warning("🔵 [ECS_FC_API] Request is not JSON")
            return create_api_response(False, "Request must be JSON", status_code=400)
        
        data = request.json
        
        # Validate required fields
        required_fields = ['discord_id', 'response_text', 'response_method']
        for field in required_fields:
            if field not in data:
                logger.warning(f"🔵 [ECS_FC_API] Missing required field: {field}")
                return create_api_response(False, f"Missing required field: {field}", status_code=400)
        
        discord_id = data['discord_id']
        response_text = data['response_text']
        response_method = data['response_method']
        request_id = data.get('request_id')
        response_id = data.get('response_id')
        
        logger.info(f"🔵 [ECS_FC_API] Processing sub response - Discord ID: {discord_id}, Response: {response_text}, Method: {response_method}")
        
        with managed_session() as session_db:
            # Find the player by Discord ID
            player = session_db.query(Player).filter_by(discord_id=str(discord_id)).first()
            if not player:
                logger.warning(f"🔵 [ECS_FC_API] No player found with Discord ID {discord_id}")
                return create_api_response(False, f"No player found with Discord ID {discord_id}", status_code=404)
            
            logger.info(f"🔵 [ECS_FC_API] Found player {player.id} for Discord ID {discord_id}")
            
            # If request_id and response_id are provided, validate them
            if request_id and response_id:
                logger.info(f"🔵 [ECS_FC_API] Validating specific request {request_id} and response {response_id}")
                
                # Find the specific response record
                response_record = session_db.query(EcsFcSubResponse).filter_by(
                    id=response_id,
                    request_id=request_id,
                    player_id=player.id
                ).first()
                
                if not response_record:
                    logger.warning(f"🔵 [ECS_FC_API] Response record not found: request_id={request_id}, response_id={response_id}, player_id={player.id}")
                    return create_api_response(False, "Response record not found", status_code=404)
                
                # Validate that the request is still open
                sub_request = session_db.query(EcsFcSubRequest).filter_by(
                    id=request_id,
                    status='OPEN'
                ).first()
                
                if not sub_request:
                    logger.warning(f"🔵 [ECS_FC_API] Substitute request {request_id} is no longer open")
                    return create_api_response(False, "This substitute request is no longer open", status_code=400)
                
                logger.info(f"🔵 [ECS_FC_API] Validated request {request_id} and response {response_id}")
            else:
                logger.info(f"🔵 [ECS_FC_API] Finding most recent open request for player {player.id}")
                
                # Find the most recent open request that this player was notified about
                from sqlalchemy import and_
                
                response_record = session_db.query(EcsFcSubResponse).join(
                    EcsFcSubRequest, EcsFcSubResponse.request_id == EcsFcSubRequest.id
                ).filter(
                    and_(
                        EcsFcSubResponse.player_id == player.id,
                        EcsFcSubRequest.status == 'OPEN',
                        EcsFcSubResponse.notification_sent_at.isnot(None)
                    )
                ).order_by(
                    EcsFcSubResponse.notification_sent_at.desc()
                ).first()
                
                if not response_record:
                    logger.warning(f"🔵 [ECS_FC_API] No active substitute request found for player {player.id}")
                    return create_api_response(False, "No active substitute request found for this player", status_code=404)
                
                logger.info(f"🔵 [ECS_FC_API] Found active request {response_record.request_id} for player {player.id}")
            
            # Process the response using the Celery task
            logger.info(f"🔵 [ECS_FC_API] Processing response using Celery task for player {player.id}")
            result = process_sub_response.apply_async(
                args=[player.id, response_text, response_method]
            ).get(timeout=10)
            
            if result.get('success'):
                logger.info(f"🔵 [ECS_FC_API] Successfully processed substitute response for player {player.id}")
                return create_api_response(True, "Response processed successfully", {
                    'is_available': result.get('is_available'),
                    'request_id': result.get('request_id'),
                    'player_id': player.id
                })
            else:
                logger.error(f"🔵 [ECS_FC_API] Failed to process substitute response: {result.get('error', 'Unknown error')}")
                return create_api_response(False, result.get('error', 'Unknown error'), status_code=500)
            
    except Exception as e:
        logger.error(f"🔵 [ECS_FC_API] Error processing ECS FC sub response: {str(e)}", exc_info=True)
        return create_api_response(False, f"Internal server error: {str(e)}", status_code=500)


# Error handlers
@ecs_fc_api.errorhandler(404)
def not_found(error):
    """Handle 404 errors."""
    return create_api_response(False, "Endpoint not found", status_code=404)


@ecs_fc_api.errorhandler(405)
def method_not_allowed(error):
    """Handle 405 errors."""
    return create_api_response(False, "Method not allowed", status_code=405)


@ecs_fc_api.errorhandler(500)
def internal_error(error):
    """Handle 500 errors."""
    logger.error(f"Internal server error: {str(error)}")
    return create_api_response(False, "Internal server error", status_code=500)