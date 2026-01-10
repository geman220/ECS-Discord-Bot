"""Centralized Module for Modal JS & CSS

This file provides a simple, consistent interface for modal handling 
throughout the application.
"""

from flask import Blueprint, render_template, jsonify, request, current_app
from flask_login import login_required
from app.models import Match, Team, Player
from app.utils.user_helpers import safe_current_user
from app.core.session_manager import managed_session

modals = Blueprint('modals', __name__)

@modals.route('/render_modals')
@login_required
def render_all_modals():
    """Renders a partial template with all modals for the logged-in user's matches."""
    # Import already done at the module level

    # Check if specific match IDs were requested
    requested_ids = request.args.get('match_ids')
    match_id_list = []
    
    if requested_ids:
        try:
            # Parse comma-separated list of match IDs
            match_id_list = [int(id.strip()) for id in requested_ids.split(',') if id.strip().isdigit()]
            current_app.logger.info(f"Requested specific match IDs: {match_id_list}")
        except Exception as e:
            current_app.logger.error(f"Error parsing match IDs: {e}")
    
    # Create choices dictionary for all matches the user might have access to
    with managed_session() as session:
        # Get matches based on request
        if match_id_list:
            # Get specific matches if IDs were provided
            matches = session.query(Match).filter(Match.id.in_(match_id_list)).all()
            current_app.logger.info(f"Found {len(matches)} matches for requested IDs")
        else:
            # Otherwise get all matches (default behavior)
            matches = session.query(Match).all()
            current_app.logger.info(f"Returning all {len(matches)} matches")
        
        # Generate player choices for each match
        player_choices = {}
        for match in matches:
            home_team = match.home_team
            away_team = match.away_team
            
            if home_team and away_team:
                home_players = {p.id: p.name for p in home_team.players}
                away_players = {p.id: p.name for p in away_team.players}
                
                player_choices[match.id] = {
                    home_team.name: home_players,
                    away_team.name: away_players
                }
            else:
                # Even for matches without fully loaded teams, create a minimal entry
                # This ensures the modal can be generated, even if player lists might be empty
                placeholder = {"Players Unavailable": {0: "No players available"}}
                player_choices[match.id] = placeholder
                current_app.logger.warning(f"Match {match.id} missing team data, using placeholder")
        
        # Render the modals template (Flowbite version)
        return render_template('modals/match_modals_flowbite.html',
                               matches=matches,
                               player_choices=player_choices,
                               safe_current_user=safe_current_user)