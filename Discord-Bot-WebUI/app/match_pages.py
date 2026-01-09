# app/match_pages.py

"""
Match Pages Module

This module defines the blueprint endpoints for viewing match details, managing RSVP responses,
and live match reporting.

It provides routes to:
1. Display match information, including RSVP breakdown for home and away teams
2. Update or fetch RSVP status for a match
3. Enable live match reporting with multi-user synchronization
"""

import logging
from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, jsonify, g
from flask_login import login_required
from sqlalchemy.orm import joinedload

from app.models import Match, Availability, Player, Team
from app.models_ecs import EcsFcMatch, EcsFcAvailability
from app.tasks.tasks_rsvp import update_rsvp
from app.utils.user_helpers import safe_current_user
from app.database.db_models import ActiveMatchReporter, LiveMatch, MatchEvent, PlayerShift
from app.decorators import role_required
from app.ecs_fc_schedule import EcsFcScheduleManager
from app.alert_helpers import show_error

# Get the logger for this module
logger = logging.getLogger(__name__)

match_pages = Blueprint('match_pages', __name__)


@match_pages.route('/matches/<match_id>')
@login_required
def view_match(match_id):
    """
    Display the details of a specific match along with RSVP data.
    Supports both regular pub league matches and ECS FC matches.

    The match details are fetched with relationships for home and away team players,
    their availability statuses, and the match schedule. RSVP data is grouped for each team.
    
    Access is restricted to:
    - Admins (Global Admin, Pub League Admin)
    - Coaches (Pub League Coach)
    - Players on the teams playing in the match
    - ECS FC coaches for ECS FC matches
    
    Parameters:
        match_id (str): The ID of the match to view. Can be regular match ID or "ecs_<id>" for ECS FC matches.
        
    Returns:
        A rendered HTML page displaying match details and RSVP information.
    """
    session = g.db_session
    
    try:
        # Ensure we start with a clean transaction state
        try:
            session.rollback()
        except Exception:
            pass  # Ignore any rollback errors at startup
            
        print(f"DEBUG: Starting view_match for match_id: {match_id}")
        # Check if this is an ECS FC match
        is_ecs_fc_match = isinstance(match_id, str) and match_id.startswith('ecs_')
        print(f"DEBUG: is_ecs_fc_match: {is_ecs_fc_match}")
        
        if is_ecs_fc_match:
            # Extract the actual ECS FC match ID
            actual_match_id = int(match_id[4:])  # Remove 'ecs_' prefix
        
            # Fetch ECS FC match details
            ecs_match = EcsFcScheduleManager.get_match_by_id(actual_match_id)
            if not ecs_match:
                return redirect(url_for('main.index'))
            
            # Get the team for the ECS FC match
            team = session.query(Team).options(joinedload(Team.players)).get(ecs_match.team_id)
            if not team:
                return redirect(url_for('main.index'))
            
            match = None  # No regular match object for ECS FC
        else:
            # Handle regular pub league match
            try:
                actual_match_id = int(match_id)
            except ValueError:
                logger.error(f"Invalid match_id format: {match_id}")
                return redirect(url_for('main.index'))
            
            # Fetch match details with necessary relationships eagerly loaded
            match = session.query(Match).options(
                joinedload(Match.home_team).joinedload(Team.players),
                joinedload(Match.away_team).joinedload(Team.players),
                joinedload(Match.schedule)
            ).get(actual_match_id)
            
            logger.info(f"Fetched match for ID {actual_match_id}: {match}")
            ecs_match = None  # No ECS FC match object for regular matches

        if not match and not ecs_match:
            # If no match is found, redirect to index (or optionally abort with 404)
            logger.error(f"No match found - match: {match}, ecs_match: {ecs_match}")
            return redirect(url_for('main.index'))

        # Check access permissions using the permission system
        from app.role_impersonation import is_impersonation_active, get_effective_roles, has_effective_permission
    
        if is_impersonation_active():
            user_roles = get_effective_roles()
            can_view_match = has_effective_permission('view_match_page')
        else:
            user = session.merge(safe_current_user)
            user_roles = [role.name for role in user.roles]
            can_view_match = safe_current_user.has_permission('view_match_page')
    
        # Global Admin always has access
        is_global_admin = 'Global Admin' in user_roles
    
        # Check if user is a referee for this match (refs can view matches they're assigned to)
        is_assigned_ref = False
        if not is_ecs_fc_match and hasattr(safe_current_user, 'player') and safe_current_user.player:
            player = safe_current_user.player
            if player.is_ref and match.ref_id == player.id:
                is_assigned_ref = True
    
        # Check ECS FC access for ECS FC matches
        can_view_ecs_fc = False
        if is_ecs_fc_match:
            from app.ecs_fc_api import validate_ecs_fc_coach_access
            can_view_ecs_fc = validate_ecs_fc_coach_access(ecs_match.team_id)
    
        # Permission check: different rules for ECS FC vs regular matches
        if is_ecs_fc_match:
            if not (is_global_admin or can_view_ecs_fc):
                show_error('Access denied: You do not have permission to view this ECS FC match.')
                return redirect(url_for('main.index'))
        else:
            # Players cannot view match pages at all - only coaches, admins, and assigned refs
            if not (is_global_admin or can_view_match or is_assigned_ref):
                show_error('Access denied: You do not have permission to view this match.')
                return redirect(url_for('main.index'))

        schedule = match.schedule if match else None

        def get_rsvp_data(team):
            """
            Aggregate RSVP data for a given team.
            Handles both regular matches and ECS FC matches.

            Parameters:
                team (Team): The team whose players' RSVP statuses are to be processed.
        
            Returns:
                dict: A dictionary containing lists of players for each RSVP category.
            """
            rsvp_data = {
                'available': [],
                'not_available': [],
                'maybe': [],
                'no_response': []
            }
            
            try:
                # Get availability records for this specific match and team players
                player_ids = [p.id for p in team.players]
            
                if is_ecs_fc_match:
                    # Use ECS FC availability records
                    logger.debug(f"Querying ECS FC availability for match_id={actual_match_id}, player_ids={player_ids}")
                    availability_records = session.query(EcsFcAvailability).filter(
                        EcsFcAvailability.ecs_fc_match_id == actual_match_id,
                        EcsFcAvailability.player_id.in_(player_ids)
                    ).all()
                else:
                    # Use regular availability records
                    logger.debug(f"Querying regular availability for match_id={actual_match_id}, player_ids={player_ids}")
                    availability_records = session.query(Availability).filter(
                        Availability.match_id == actual_match_id,
                        Availability.player_id.in_(player_ids)
                    ).all()
            
                # Create a lookup dict for faster access
                availability_lookup = {a.player_id: a for a in availability_records}
            except Exception as e:
                logger.error(f"ERROR: Failed to query availability records for match {actual_match_id}")
                logger.error(f"ERROR TYPE: {type(e)}")
                logger.error(f"ERROR MESSAGE: {str(e)}")
                logger.error(f"PLAYER IDS: {player_ids}")
                logger.error(f"IS ECS FC MATCH: {is_ecs_fc_match}")
                import traceback
                logger.error(f"FULL TRACEBACK: {traceback.format_exc()}")
                session.rollback()
                availability_lookup = {}
        
            for player in team.players:
                availability = availability_lookup.get(player.id)
                if availability:
                    if availability.response == 'yes':
                        rsvp_data['available'].append(player)
                    elif availability.response == 'no':
                        rsvp_data['not_available'].append(player)
                    elif availability.response == 'maybe':
                        rsvp_data['maybe'].append(player)
                else:
                    rsvp_data['no_response'].append(player)
        
            # Add substitute assignments to the available list
            try:
                from app.models_substitute_pools import SubstituteAssignment, SubstituteRequest
            
                # Determine league type and match filter
                if is_ecs_fc_match:
                    league_type = 'ECS FC'
                    match_filter = SubstituteRequest.match_id == actual_match_id
                else:
                    # For regular pub league matches, could be Classic or Premier
                    league_type = None  # Will match any league type for regular matches
                    match_filter = SubstituteRequest.match_id == actual_match_id
            
                # Build query for unified substitute assignments
                query = session.query(SubstituteAssignment).join(
                    SubstituteRequest
                ).options(
                    joinedload(SubstituteAssignment.player)
                ).filter(match_filter)
            
                # Add league type filter for ECS FC matches
                if is_ecs_fc_match:
                    query = query.filter(SubstituteRequest.league_type == league_type)
            
                unified_assignments = query.all()
            
                for assignment in unified_assignments:
                    if assignment.player and assignment.player not in rsvp_data['available']:
                        rsvp_data['available'].append(assignment.player)
            except ImportError:
                pass
            except Exception as e:
                logger.error(f"ERROR: Failed to query unified substitute assignments for match {actual_match_id}")
                logger.error(f"ERROR TYPE: {type(e)}")
                logger.error(f"ERROR MESSAGE: {str(e)}")
                import traceback
                logger.error(f"FULL TRACEBACK: {traceback.format_exc()}")
                session.rollback()
        
            # Add ECS FC specific substitute assignments for ECS FC matches
            if is_ecs_fc_match:
                try:
                    from app.models_ecs_subs import EcsFcSubAssignment
                
                    ecs_fc_assignments = session.query(EcsFcSubAssignment).join(
                        EcsFcSubAssignment.request
                    ).options(
                        joinedload(EcsFcSubAssignment.player)
                    ).filter(
                        EcsFcSubAssignment.request.has(match_id=actual_match_id)
                    ).all()
                
                    for assignment in ecs_fc_assignments:
                        if assignment.player and assignment.player not in rsvp_data['available']:
                            rsvp_data['available'].append(assignment.player)
                except ImportError:
                    pass
                except Exception as e:
                    logger.error(f"ERROR: Failed to query ECS FC substitute assignments for match {actual_match_id}")
                    logger.error(f"ERROR TYPE: {type(e)}")
                    logger.error(f"ERROR MESSAGE: {str(e)}")
                    import traceback
                    logger.error(f"FULL TRACEBACK: {traceback.format_exc()}")
                    session.rollback()
        
            return rsvp_data

        # Check for sorting parameter
        sort_by = request.args.get('sort', 'default')  # Default to no sorting
    
        if is_ecs_fc_match:
            # Handle ECS FC match data collection
            if sort_by in ['name', 'response']:
                team_player_ids = [p.id for p in team.players]
            
                # Get availability records for the team
                try:
                    if is_ecs_fc_match:
                        team_availability = session.query(EcsFcAvailability).filter(
                            EcsFcAvailability.ecs_fc_match_id == actual_match_id,
                            EcsFcAvailability.player_id.in_(team_player_ids)
                        ).all()
                except Exception as e:
                    logger.error(f"ERROR: Failed to query ECS FC availability for sorting, match {actual_match_id}")
                    logger.error(f"ERROR TYPE: {type(e)}")
                    logger.error(f"ERROR MESSAGE: {str(e)}")
                    logger.error(f"TEAM PLAYER IDS: {team_player_ids}")
                    import traceback
                    logger.error(f"FULL TRACEBACK: {traceback.format_exc()}")
                    session.rollback()
                    team_availability = []
            
                # Create lookup dict
                team_availability_lookup = {a.player_id: a for a in team_availability}
            
                # Sort based on selected option
                if sort_by == 'name':
                    team.players.sort(key=lambda p: p.name.lower())
                elif sort_by == 'response':
                    # Sort by response priority: yes, maybe, no, no_response
                    response_priority = {'yes': 1, 'maybe': 2, 'no': 3, None: 4}
                
                    team.players.sort(key=lambda p: (
                        response_priority.get(
                            team_availability_lookup.get(p.id).response if team_availability_lookup.get(p.id) else None,
                            4
                        ),
                        p.name.lower()  # Secondary sort by name
                    ))
        
            # For ECS FC matches, only get RSVP data for the one team
            home_rsvp_data = get_rsvp_data(team)
            away_rsvp_data = None  # No away team for ECS FC matches
        
            # Generate player choices for ECS FC match reporting (only one team)
            player_choices = {}
            team_players = {str(p.id): p.name for p in team.players}
            player_choices[f'ecs_{actual_match_id}'] = {
                team.name: team_players
            }
        
        else:
            # Handle regular pub league match data collection
            if sort_by in ['name', 'response']:
                home_player_ids = [p.id for p in match.home_team.players]
                away_player_ids = [p.id for p in match.away_team.players]
            
                # Get availability records for both teams
                try:
                    home_availability = session.query(Availability).filter(
                        Availability.match_id == actual_match_id,
                        Availability.player_id.in_(home_player_ids)
                    ).all()
                    away_availability = session.query(Availability).filter(
                        Availability.match_id == actual_match_id,
                        Availability.player_id.in_(away_player_ids)
                    ).all()
                except Exception as e:
                    logger.error(f"ERROR: Failed to query availability for sorting, match {actual_match_id}")
                    logger.error(f"ERROR TYPE: {type(e)}")
                    logger.error(f"ERROR MESSAGE: {str(e)}")
                    logger.error(f"HOME PLAYER IDS: {home_player_ids}")
                    logger.error(f"AWAY PLAYER IDS: {away_player_ids}")
                    import traceback
                    logger.error(f"FULL TRACEBACK: {traceback.format_exc()}")
                    session.rollback()
                    home_availability = []
                    away_availability = []
            
                # Create lookup dicts
                home_availability_lookup = {a.player_id: a for a in home_availability}
                away_availability_lookup = {a.player_id: a for a in away_availability}
            
                # Sort based on selected option
                if sort_by == 'name':
                    match.home_team.players.sort(key=lambda p: p.name.lower())
                    match.away_team.players.sort(key=lambda p: p.name.lower())
                elif sort_by == 'response':
                    # Sort by response priority: yes, maybe, no, no_response
                    response_priority = {'yes': 1, 'maybe': 2, 'no': 3, None: 4}
                
                    match.home_team.players.sort(key=lambda p: (
                        response_priority.get(
                            home_availability_lookup.get(p.id).response if home_availability_lookup.get(p.id) else None,
                            4
                        ),
                        p.name.lower()  # Secondary sort by name
                    ))
                    match.away_team.players.sort(key=lambda p: (
                        response_priority.get(
                            away_availability_lookup.get(p.id).response if away_availability_lookup.get(p.id) else None,
                            4
                        ),
                        p.name.lower()  # Secondary sort by name
                    ))
        
            home_rsvp_data = get_rsvp_data(match.home_team)
            away_rsvp_data = get_rsvp_data(match.away_team)
        
            # Generate player choices dictionary for the report match modal
            player_choices = {}
            if match.home_team and match.away_team:
                home_players = {str(p.id): p.name for p in match.home_team.players}
                away_players = {str(p.id): p.name for p in match.away_team.players}
            
                player_choices[actual_match_id] = {
                    match.home_team.name: home_players,
                    match.away_team.name: away_players
                }

        return render_template(
            'view_match_flowbite.html',
            match=match if not is_ecs_fc_match else None,
            ecs_match=ecs_match if is_ecs_fc_match else None,
            team=team if is_ecs_fc_match else None,
            schedule=schedule,
            home_rsvp_data=home_rsvp_data,
            away_rsvp_data=away_rsvp_data,
            player_choices=player_choices,
            sort_by=sort_by,
                is_ecs_fc_match=is_ecs_fc_match
            )
    except Exception as e:
        print(f"EXCEPTION IN VIEW_MATCH FOR {match_id}: {str(e)}")
        print(f"EXCEPTION TYPE: {type(e)}")
        import traceback
        print(f"FULL TRACEBACK: {traceback.format_exc()}")
        logger.error(f"Error in view_match for match_id {match_id}: {str(e)}")
        logger.exception("Full traceback:")
        try:
            session.rollback()
        except Exception as rollback_error:
            logger.error(f"Error during rollback: {str(rollback_error)}")
        show_error('An error occurred while loading the match. Please try again.')
        return redirect(url_for('main.index'))


# Debug route to trace RSVP issues
@match_pages.route('/rsvp/debug/<int:match_id>', methods=['GET'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def debug_rsvp(match_id):
    """Debug endpoint to help troubleshoot RSVP issues."""
    try:
        session = g.db_session
        match = session.query(Match).get(match_id)
        player_id = safe_current_user.player.id if hasattr(safe_current_user, 'player') and safe_current_user.player else None
        player = session.query(Player).get(player_id) if player_id else None
        
        # Get availability record if it exists
        availability = None
        if player_id:
            availability = session.query(Availability).filter_by(match_id=match_id, player_id=player_id).first()
        
        # Build debug info
        debug_info = {
            'match': {
                'id': match.id,
                'date': match.date.isoformat() if match.date else None,
                'home_team': match.home_team.name if match.home_team else 'Unknown',
                'away_team': match.away_team.name if match.away_team else 'Unknown',
                'exists': match is not None
            } if match else None,
            'player': {
                'id': player.id,
                'name': player.name,
                'exists': player is not None
            } if player else None,
            'current_user': {
                'id': safe_current_user.id,
                'is_authenticated': safe_current_user.is_authenticated,
                'has_player': hasattr(safe_current_user, 'player') and safe_current_user.player is not None
            },
            'availability': {
                'exists': availability is not None,
                'response': availability.response if availability else None,
                'responded_at': availability.responded_at.isoformat() if availability and availability.responded_at else None
            } if availability else None
        }
        
        return jsonify(debug_info)
    except Exception as e:
        logger.exception(f"Error in debug RSVP: {str(e)}")
        return jsonify({'error': str(e)}), 500

def local_update_rsvp(match_id, player_id, response, discord_id=None):
    """
    Enterprise RSVP implementation that uses the same reliable system as Discord bot and SMS.
    
    This function now uses the enterprise-grade RSVP service providing idempotent operations,
    event-driven updates, and full audit trail for maximum reliability.
    
    Args:
        match_id: The match ID.
        player_id: The player ID.
        response: The RSVP response.
        discord_id: Optional Discord ID.
        
    Returns:
        dict: A dictionary with success and message keys.
    """
    try:
        session = g.db_session
        
        # Validate response
        if response not in ['yes', 'no', 'maybe', 'no_response']:
            return {
                'success': False,
                'message': f"Invalid response: {response}. Must be 'yes', 'no', 'maybe', or 'no_response'."
            }
        
        # Use the enterprise RSVP service for reliability and real-time sync
        from app.services.rsvp_service import create_rsvp_service_sync
        from app.events.rsvp_events import RSVPSource
        from flask import request
        import uuid
        
        # Generate operation ID for idempotency and audit trail
        operation_id = str(uuid.uuid4())
        
        # Collect user context for audit trail
        user_context = {
            'ip_address': request.remote_addr if request else None,
            'user_agent': request.headers.get('User-Agent') if request else 'Web Interface',
            'source_endpoint': 'web_rsvp_interface',
            'request_id': f'web_{operation_id}'
        }
        
        # Create enterprise RSVP service
        rsvp_service = create_rsvp_service_sync(session)
        
        # Process RSVP update with enterprise reliability
        success, message, event = rsvp_service.update_rsvp_sync(
            match_id=match_id,
            player_id=player_id,
            new_response=response,
            source=RSVPSource.WEB,  # Web interface updates
            operation_id=operation_id,
            user_context=user_context
        )
        
        if success:
            logger.info(f"✅ Enterprise Web RSVP update successful: player={player_id}, match={match_id}, "
                       f"response={response}, operation_id={operation_id}")
            return {'success': True, 'message': message}
        else:
            logger.warning(f"⚠️ Enterprise Web RSVP update failed: {message}, operation_id={operation_id}")
            return {'success': False, 'message': message}
        
    except Exception as e:
        logger.exception(f"Error in enterprise web RSVP update: {str(e)}")
        return {'success': False, 'message': f"Update failed: {str(e)}"}


@match_pages.route('/rsvp/<int:match_id>', methods=['POST'])
@login_required
def rsvp(match_id):
    """
    Update the RSVP status for a player for a given match.

    Expects a JSON payload containing:
        - response: The new RSVP response.
        - player_id: The player's identifier.
        - discord_id (optional): The player's Discord ID.

    Returns:
        JSON response indicating success or failure.
    """
    try:
        # Check RSVP permissions
        from app.role_impersonation import is_impersonation_active, has_effective_permission
        
        if is_impersonation_active():
            can_rsvp = has_effective_permission('view_rsvps')
        else:
            can_rsvp = safe_current_user.has_permission('view_rsvps')
        
        if not can_rsvp:
            return jsonify({"success": False, "message": "Access denied: You do not have permission to RSVP"}), 403
        
        # Log request info for debugging
        logger.debug(f"RSVP request for match {match_id} with content type: {request.content_type}")
        
        # Properly handle JSON data
        data = request.get_json(silent=True)
        if data is None:
            logger.error(f"Failed to parse JSON from request: {request.data}")
            return jsonify({"success": False, "message": "Invalid JSON payload"}), 400
            
        # Extract data from request
        new_response = data.get('response')
        player_id = data.get('player_id')
        discord_id = data.get('discord_id') or None
        
        logger.debug(f"RSVP data: match_id={match_id}, player_id={player_id}, response={new_response}")
        
        # Use the availability_api.update_availability_web endpoint instead of local implementation
        from app.availability_api import update_availability_web
        
        # First do the local database update for immediate response
        # This ensures we have a response for the user immediately
        result = local_update_rsvp(match_id, player_id, new_response, discord_id)
        success = result.get('success', False)
        message = result.get('message', 'RSVP updated')
        
        if success:
            # Emit WebSocket event for real-time updates
            from app.sockets.rsvp import emit_rsvp_update
            session = g.db_session
            player = session.query(Player).get(player_id)
            if player:
                # Determine team_id
                match = session.query(Match).get(match_id)
                team_id = None
                if match:
                    if player in match.home_team.players:
                        team_id = match.home_team_id
                    elif player in match.away_team.players:
                        team_id = match.away_team_id
                
                emit_rsvp_update(
                    match_id=match_id,
                    player_id=player.id,
                    availability=new_response,
                    source='web',
                    player_name=player.name,
                    team_id=team_id
                )
                logger.info(f"📤 Emitted WebSocket RSVP update: {player.name} -> {new_response} for match {match_id}")
            
            # Then trigger the API call to notify Discord
            from app.tasks.tasks_rsvp import notify_discord_of_rsvp_change_task
            from app.tasks.tasks_rsvp import update_discord_rsvp_task
            
            # Get the player to get discord_id if available
            if player and player.discord_id:
                discord_id = player.discord_id
            
            # Schedule the Discord notification
            logger.info(f"Scheduling Discord notification for match {match_id}")
            notify_discord_of_rsvp_change_task.delay(match_id)
            
            # If we have a discord_id, also update the reaction
            if discord_id:
                # Get the current availability record to determine old_response
                availability = session.query(Availability).filter_by(
                    match_id=match_id, player_id=player_id
                ).first()
                old_response = availability.response if availability else None
                
                logger.info(f"Player {player_id} has discord_id {discord_id}, will update reaction")
                update_discord_rsvp_task.delay(
                    match_id=match_id,
                    discord_id=discord_id,
                    new_response=new_response,
                    old_response=old_response
                )
            
    except Exception as e:
        logger.exception(f"Error processing RSVP: {str(e)}")
        return jsonify({"success": False, "message": f"Server error: {str(e)}"}), 500

    if success:
        logger.info(f"RSVP updated successfully: {message}")
        return jsonify({'success': True, 'message': message})
    else:
        logger.error(f"Error updating RSVP: {message}")
        return jsonify({'success': False, 'message': message}), 500


@match_pages.route('/rsvp/status/<int:match_id>', methods=['GET'])
@login_required
def get_rsvp_status(match_id):
    """
    Retrieve the current RSVP status for the logged-in user's player profile for a match.

    Returns:
        JSON response with the RSVP status ('yes', 'no', 'maybe', or 'no_response').
    """
    try:
        session = g.db_session
        
        # Log request for debugging
        logger.debug(f"RSVP status request for match {match_id}")

        # Ensure the user has an associated player profile
        if not hasattr(safe_current_user, 'player') or safe_current_user.player is None:
            logger.debug(f"User {safe_current_user.id} has no player profile, returning 'no_response'")
            return jsonify({'response': 'no_response'})

        player_id = safe_current_user.player.id
        # Query without detailed logging
        availability = session.query(Availability).filter_by(match_id=match_id, player_id=player_id).first()

        if availability:
            return jsonify({'response': availability.response})
        else:
            return jsonify({'response': 'no_response'})
            return jsonify({'response': 'no_response'})
            
    except Exception as e:
        logger.exception(f"Error fetching RSVP status: {str(e)}")
        return jsonify({'response': 'no_response', 'error': str(e)})


@match_pages.route('/matches/<int:match_id>/live-report', methods=['GET'])
@login_required
def live_report_match(match_id):
    """
    Live match reporting interface with multi-user collaboration.
    
    This interface allows multiple coaches to report on the same match simultaneously
    with synchronized match state (score, timer, events) but team-specific player shifts.
    
    Args:
        match_id: ID of the match to report
        
    Returns:
        Rendered live reporting template
    """
    session = g.db_session
    
    # Get match with team data preloaded
    match = session.query(Match).options(
        joinedload(Match.home_team),
        joinedload(Match.away_team)
    ).get(match_id)
    
    if not match:
        logger.warning(f"Match not found for live reporting: {match_id}")
        return redirect(url_for('main.index'))
    
    # Check if user is authorized to report on this match
    player = safe_current_user.player if hasattr(safe_current_user, 'player') else None
    if not player:
        logger.warning(f"User {safe_current_user.id} has no player profile, cannot report")
        return redirect(url_for('match_pages.view_match', match_id=match_id))
    
    # Get team IDs that the user is associated with
    user_teams = player.teams
    user_team_ids = [team.id for team in user_teams]
    
    # Check if user is part of either team in the match
    if match.home_team_id not in user_team_ids and match.away_team_id not in user_team_ids:
        logger.warning(f"User {safe_current_user.id} not authorized to report match {match_id}")
        return redirect(url_for('match_pages.view_match', match_id=match_id))
    
    # Determine which team the user is reporting for (prioritize coach team)
    reporting_team_id = None
    
    # Check if user is a coach for either team
    for team_id in [match.home_team_id, match.away_team_id]:
        if team_id in user_team_ids:
            # Query player_teams association table to check if player is coach
            stmt = """
                SELECT is_coach FROM player_teams 
                WHERE player_id = :player_id AND team_id = :team_id
            """
            result = session.execute(stmt, {
                'player_id': player.id, 
                'team_id': team_id
            }).fetchone()
            
            if result and result[0]:  # is_coach is True
                reporting_team_id = team_id
                break
    
    # If not a coach, use any team the player is on
    if not reporting_team_id:
        if match.home_team_id in user_team_ids:
            reporting_team_id = match.home_team_id
        elif match.away_team_id in user_team_ids:
            reporting_team_id = match.away_team_id
    
    # Get player lists for both teams
    home_players = []
    for player in match.home_team.players:
        home_players.append({
            'id': player.id,
            'name': player.name
        })
    
    away_players = []
    for player in match.away_team.players:
        away_players.append({
            'id': player.id,
            'name': player.name
        })
    
    logger.info(f"User {safe_current_user.id} reporting match {match_id} for team {reporting_team_id}")
    
    return render_template(
        'live_reporting_flowbite.html',
        match=match,
        home_players=home_players,
        away_players=away_players,
        team_id=reporting_team_id
    )