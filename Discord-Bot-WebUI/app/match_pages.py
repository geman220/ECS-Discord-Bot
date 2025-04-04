# app/match_pages.py

"""
Match Pages Module

This module defines the blueprint endpoints for viewing match details and managing RSVP responses.
It provides routes to display match information, including RSVP breakdown for home and away teams,
and endpoints to update or fetch RSVP status for a match.
"""

import logging
from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, jsonify, g
from flask_login import login_required
from sqlalchemy.orm import joinedload

from app.models import Match, Availability, Player, Team
from app.tasks.tasks_rsvp import update_rsvp
from app.utils.user_helpers import safe_current_user

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
    
    Parameters:
        match_id (int): The ID of the match to view.
        
    Returns:
        A rendered HTML page displaying match details and RSVP information.
    """
    session = g.db_session

    # Fetch match details with necessary relationships eagerly loaded
    match = session.query(Match).options(
        joinedload(Match.home_team).joinedload(Team.players).joinedload(Player.availability),
        joinedload(Match.away_team).joinedload(Team.players).joinedload(Player.availability),
        joinedload(Match.schedule)
    ).get(match_id)

    if not match:
        # If no match is found, redirect to index (or optionally abort with 404)
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
        for player in team.players:
            # Find the availability entry for the current match
            availability = next((a for a in player.availability if a.match_id == match.id), None)
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

    home_rsvp_data = get_rsvp_data(match.home_team)
    away_rsvp_data = get_rsvp_data(match.away_team)

    return render_template(
        'view_match.html',
        match=match,
        schedule=schedule,
        home_rsvp_data=home_rsvp_data,
        away_rsvp_data=away_rsvp_data
    )


# Debug route to trace RSVP issues
@match_pages.route('/rsvp/debug/<int:match_id>', methods=['GET'])
@login_required
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
        
        # Use local implementation to update RSVP instead of Celery task
        result = local_update_rsvp(match_id, player_id, new_response, discord_id)
        success = result.get('success', False)
        message = result.get('message', 'RSVP updated')
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
        logger.debug(f"Checking availability for player {player_id} and match {match_id}")
        
        availability = session.query(Availability).filter_by(match_id=match_id, player_id=player_id).first()

        if availability:
            logger.debug(f"Found availability status: {availability.response}")
            return jsonify({'response': availability.response})
        else:
            logger.debug(f"No availability record found, returning 'no_response'")
            return jsonify({'response': 'no_response'})
            
    except Exception as e:
        logger.exception(f"Error fetching RSVP status: {str(e)}")
        return jsonify({'response': 'no_response', 'error': str(e)})