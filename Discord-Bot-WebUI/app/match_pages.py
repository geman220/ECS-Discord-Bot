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
from app.tasks.tasks_rsvp import update_rsvp
from app.utils.user_helpers import safe_current_user
from app.database.db_models import ActiveMatchReporter, LiveMatch, MatchEvent, PlayerShift
from app.decorators import role_required

# Get the logger for this module
logger = logging.getLogger(__name__)

match_pages = Blueprint('match_pages', __name__)


@match_pages.route('/matches/<int:match_id>')
@login_required
def view_match(match_id):
    """
    Display the details of a specific match along with RSVP data.

    The match details are fetched with relationships for home and away team players,
    their availability statuses, and the match schedule. RSVP data is grouped for each team.
    
    Access is restricted to:
    - Admins (Global Admin, Pub League Admin)
    - Coaches (Pub League Coach)
    - Players on the teams playing in the match
    
    Parameters:
        match_id (int): The ID of the match to view.
        
    Returns:
        A rendered HTML page displaying match details and RSVP information.
    """
    session = g.db_session

    # Fetch match details with necessary relationships eagerly loaded
    match = session.query(Match).options(
        joinedload(Match.home_team).joinedload(Team.players),
        joinedload(Match.away_team).joinedload(Team.players),
        joinedload(Match.schedule)
    ).get(match_id)

    if not match:
        # If no match is found, redirect to index (or optionally abort with 404)
        return redirect(url_for('main.index'))

    # Check access permissions using the permission system
    from app.role_impersonation import is_impersonation_active, get_effective_roles, has_effective_permission
    from app.alert_helpers import show_error
    
    if is_impersonation_active():
        user_roles = get_effective_roles()
        can_view_match = has_effective_permission('view_match_page')
    else:
        user = session.merge(safe_current_user)
        user_roles = [role.name for role in user.roles]
        can_view_match = safe_current_user.has_permission('view_match_page')
    
    # Global Admin always has access
    is_global_admin = 'Global Admin' in user_roles
    
    # Check if user is a player on either team (for team-specific access)
    has_team_access = False
    if hasattr(safe_current_user, 'player') and safe_current_user.player:
        player = safe_current_user.player
        user_team_ids = [team.id for team in player.teams]
        has_team_access = (match.home_team_id in user_team_ids or 
                          match.away_team_id in user_team_ids)
    
    # Deny access if user doesn't have proper permissions
    if not (is_global_admin or can_view_match or has_team_access):
        show_error('Access denied: You do not have permission to view this match.')
        return redirect(url_for('main.index'))

    schedule = match.schedule

    def get_rsvp_data(team):
        """
        Aggregate RSVP data for a given team.

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
        # Get availability records for this specific match and team players
        player_ids = [p.id for p in team.players]
        availability_records = session.query(Availability).filter(
            Availability.match_id == match.id,
            Availability.player_id.in_(player_ids)
        ).all()
        
        # Create a lookup dict for faster access
        availability_lookup = {a.player_id: a for a in availability_records}
        
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
        return rsvp_data

    # Check for sorting parameter
    sort_by = request.args.get('sort', 'default')  # Default to no sorting
    
    # Get availability records for sorting purposes
    if sort_by in ['name', 'response']:
        home_player_ids = [p.id for p in match.home_team.players]
        away_player_ids = [p.id for p in match.away_team.players]
        
        # Get availability records for both teams
        home_availability = session.query(Availability).filter(
            Availability.match_id == match.id,
            Availability.player_id.in_(home_player_ids)
        ).all()
        away_availability = session.query(Availability).filter(
            Availability.match_id == match.id,
            Availability.player_id.in_(away_player_ids)
        ).all()
        
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
        
        player_choices[match.id] = {
            match.home_team.name: home_players,
            match.away_team.name: away_players
        }

    return render_template(
        'view_match.html',
        match=match,
        schedule=schedule,
        home_rsvp_data=home_rsvp_data,
        away_rsvp_data=away_rsvp_data,
        player_choices=player_choices,
        sort_by=sort_by
    )


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
    Local implementation of update_rsvp that doesn't use Celery.
    
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
        
        # Verify match and player exist
        match = session.query(Match).get(match_id)
        if not match:
            return {'success': False, 'message': f"Match {match_id} not found"}
            
        player = session.query(Player).get(player_id)
        if not player:
            return {'success': False, 'message': f"Player {player_id} not found"}
        
        # Find existing availability record
        availability = session.query(Availability).filter_by(
            match_id=match_id, player_id=player_id
        ).first()
        
        if availability:
            # Update existing record
            if response == 'no_response':
                session.delete(availability)
                message = "RSVP removed"
            else:
                availability.response = response
                availability.responded_at = datetime.utcnow()
                message = f"RSVP updated to {response}"
        else:
            # Create new record
            if response != 'no_response':
                availability = Availability(
                    match_id=match_id,
                    player_id=player_id,
                    response=response,
                    discord_id=discord_id or '',
                    responded_at=datetime.utcnow()
                )
                session.add(availability)
                message = f"RSVP set to {response}"
            else:
                message = "No action needed"
        
        return {'success': True, 'message': message}
    except Exception as e:
        logger.exception(f"Error in local_update_rsvp: {str(e)}")
        return {'success': False, 'message': str(e)}


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
            # Then trigger the API call to notify Discord
            from app.tasks.tasks_rsvp import notify_discord_of_rsvp_change_task
            from app.tasks.tasks_rsvp import update_discord_rsvp_task
            
            # Get the player to get discord_id if available
            session = g.db_session
            player = session.query(Player).get(player_id)
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
        'live_reporting.html',
        match=match,
        home_players=home_players,
        away_players=away_players,
        team_id=reporting_team_id
    )