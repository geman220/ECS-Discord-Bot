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

    # Create choices dictionary for all matches the user might have access to
    with managed_session() as session:
        # Get all matches
        matches = session.query(Match).all()
        
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
        
        # Render the modals template
        return render_template('modals/match_modals.html', 
                               matches=matches,
                               player_choices=player_choices,
                               safe_current_user=safe_current_user)