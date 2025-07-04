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

from app.core import db
from app.models import Team, League, Player, User
from app.models_ecs import EcsFcMatch, EcsFcAvailability, EcsFcScheduleTemplate
from app.ecs_fc_schedule import EcsFcScheduleManager, is_user_ecs_fc_coach, get_upcoming_ecs_fc_matches
from app.decorators import role_required
from app.api_utils import validate_json_request, create_api_response

logger = logging.getLogger(__name__)

# Create blueprint
ecs_fc_api = Blueprint('ecs_fc_api', __name__, url_prefix='/api/ecs-fc')


def validate_ecs_fc_coach_access(team_id: int) -> bool:
    """
    Validate that the current user has coach access to the ECS FC team.
    
    Args:
        team_id: ID of the team
        
    Returns:
        True if user has access, False otherwise
    """
    # Check if user is admin
    if (current_user.has_role('Global Admin') or 
        current_user.has_role('Pub League Admin')):
        return True
    
    coached_teams = is_user_ecs_fc_coach(current_user.id)
    return team_id in coached_teams


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
        match = EcsFcScheduleManager.get_match_by_id(match_id)
        if not match:
            return create_api_response(False, "Match not found", status_code=404)
        
        response_counts = match.get_rsvp_summary()
        return create_api_response(True, "RSVP summary retrieved", {
            'match_id': match_id,
            'response_counts': response_counts
        })
        
    except Exception as e:
        logger.error(f"Error getting RSVP summary for match {match_id}: {str(e)}")
        return create_api_response(False, f"Internal server error: {str(e)}", status_code=500)


@ecs_fc_api.route('/store_rsvp_message', methods=['POST'])
def store_rsvp_message():
    """Store RSVP message information for future updates - used by Discord bot."""
    try:
        data = validate_json_request(request)
        if not data:
            return create_api_response(False, "Invalid JSON data", status_code=400)
        
        required_fields = ['match_id', 'message_id', 'channel_id']
        for field in required_fields:
            if field not in data:
                return create_api_response(False, f"Missing required field: {field}", status_code=400)
        
        # Store in scheduled_message table with ECS FC metadata
        from app.models import ScheduledMessage
        
        scheduled_message = ScheduledMessage(
            match_id=data['match_id'],
            message_id=data['message_id'],
            channel_id=data['channel_id'],
            message_type='ecs_fc_rsvp',
            metadata={
                'ecs_fc_match_id': data['match_id'],
                'discord_message_id': data['message_id'],
                'discord_channel_id': data['channel_id']
            },
            sent_at=datetime.utcnow()
        )
        
        db.session.add(scheduled_message)
        db.session.commit()
        
        return create_api_response(True, "RSVP message information stored", {
            'scheduled_message_id': scheduled_message.id
        })
        
    except Exception as e:
        logger.error(f"Error storing RSVP message: {str(e)}")
        db.session.rollback()
        return create_api_response(False, f"Internal server error: {str(e)}", status_code=500)


@ecs_fc_api.route('/rsvp_message/<int:match_id>', methods=['GET'])
def get_rsvp_message(match_id: int):
    """Get stored RSVP message information for a match - used by Discord bot."""
    try:
        from app.models import ScheduledMessage
        
        scheduled_message = db.session.query(ScheduledMessage).filter(
            ScheduledMessage.match_id == match_id,
            ScheduledMessage.message_type == 'ecs_fc_rsvp'
        ).first()
        
        if not scheduled_message:
            return create_api_response(False, "RSVP message not found", status_code=404)
        
        return create_api_response(True, "RSVP message found", {
            'message_id': scheduled_message.message_id,
            'channel_id': scheduled_message.channel_id,
            'metadata': scheduled_message.metadata
        })
        
    except Exception as e:
        logger.error(f"Error getting RSVP message for match {match_id}: {str(e)}")
        return create_api_response(False, f"Internal server error: {str(e)}", status_code=500)


@ecs_fc_api.route('/rsvp/update', methods=['POST'])
def update_rsvp():
    """Update a player's RSVP response - used by Discord bot."""
    try:
        data = validate_json_request(request)
        if not data:
            return create_api_response(False, "Invalid JSON data", status_code=400)
        
        required_fields = ['match_id', 'player_id', 'response']
        for field in required_fields:
            if field not in data:
                return create_api_response(False, f"Missing required field: {field}", status_code=400)
        
        match_id = data['match_id']
        player_id = data['player_id']
        response = data['response']
        discord_id = data.get('discord_id')
        
        # Validate response value
        if response not in ['yes', 'no', 'maybe', 'no_response']:
            return create_api_response(False, "Invalid response value", status_code=400)
        
        # Get or create availability record
        from app.models_ecs import EcsFcAvailability
        
        availability = db.session.query(EcsFcAvailability).filter(
            EcsFcAvailability.ecs_fc_match_id == match_id,
            EcsFcAvailability.player_id == player_id
        ).first()
        
        if response == 'no_response':
            # Remove the availability record
            if availability:
                db.session.delete(availability)
        else:
            # Update or create availability record
            if availability:
                availability.response = response
                availability.response_time = datetime.utcnow()
                availability.discord_id = discord_id
            else:
                availability = EcsFcAvailability(
                    ecs_fc_match_id=match_id,
                    player_id=player_id,
                    response=response,
                    response_time=datetime.utcnow(),
                    discord_id=discord_id
                )
                db.session.add(availability)
        
        db.session.commit()
        
        return create_api_response(True, "RSVP updated successfully", {
            'match_id': match_id,
            'player_id': player_id,
            'response': response
        })
        
    except Exception as e:
        logger.error(f"Error updating RSVP: {str(e)}")
        db.session.rollback()
        return create_api_response(False, f"Internal server error: {str(e)}", status_code=500)


@ecs_fc_api.route('/team_channel/<int:team_id>', methods=['GET'])
def get_team_channel_id(team_id: int):
    """Get Discord channel ID for a team - used by Discord bot."""
    try:
        from app.models import Team
        
        team = db.session.query(Team).filter(Team.id == team_id).first()
        if not team:
            return create_api_response(False, "Team not found", status_code=404)
        
        if not team.discord_channel_id:
            return create_api_response(False, "Team has no Discord channel", status_code=404)
        
        return create_api_response(True, "Channel ID found", {
            'channel_id': team.discord_channel_id,
            'team_id': team_id,
            'team_name': team.name
        })
        
    except Exception as e:
        logger.error(f"Error getting channel ID for team {team_id}: {str(e)}")
        return create_api_response(False, f"Internal server error: {str(e)}", status_code=500)


@ecs_fc_api.route('/teams', methods=['GET'])
@login_required
def get_user_teams():
    """Get ECS FC teams that the current user can manage."""
    try:
        # Get teams the user can coach
        coached_teams = is_user_ecs_fc_coach(current_user.id)
        
        if not coached_teams:
            return create_api_response(True, "No teams found", {'teams': []})
        
        # Get team details
        teams = db.session.query(Team).filter(Team.id.in_(coached_teams)).all()
        
        teams_data = []
        for team in teams:
            team_data = {
                'id': team.id,
                'name': team.name,
                'league_name': team.league.name if team.league else None,
                'player_count': len(team.players)
            }
            teams_data.append(team_data)
        
        return create_api_response(True, f"Found {len(teams_data)} teams", {'teams': teams_data})
        
    except Exception as e:
        logger.error(f"Error getting user teams: {str(e)}")
        return create_api_response(False, f"Internal server error: {str(e)}", status_code=500)


@ecs_fc_api.route('/matches/upcoming', methods=['GET'])
@login_required
def get_upcoming_matches():
    """Get upcoming matches for teams the user can manage."""
    try:
        # Get teams the user can coach
        coached_teams = is_user_ecs_fc_coach(current_user.id)
        
        if not coached_teams:
            return create_api_response(True, "No teams found", {'matches': []})
        
        # Parse days ahead parameter
        days_ahead = request.args.get('days_ahead', type=int, default=7)
        
        # Get upcoming matches for all coached teams
        all_matches = []
        for team_id in coached_teams:
            matches = get_upcoming_ecs_fc_matches(team_id, days_ahead)
            all_matches.extend(matches)
        
        # Sort by date and time
        all_matches.sort(key=lambda x: (x.match_date, x.match_time))
        
        # Convert to dict format
        matches_data = [match.to_dict() for match in all_matches]
        
        return create_api_response(True, f"Found {len(matches_data)} upcoming matches", {
            'matches': matches_data
        })
        
    except Exception as e:
        logger.error(f"Error getting upcoming matches: {str(e)}")
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