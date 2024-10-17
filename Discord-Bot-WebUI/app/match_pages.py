from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from app.models import Match, Schedule, Availability, Player
from app.availability_api import update_discord_rsvp
from app.tasks import update_rsvp
from app import db
from app.tasks import update_discord_rsvp_task
from datetime import datetime
import asyncio
import logging
import requests
import threading

# Get the logger for this module
logger = logging.getLogger(__name__)

match_pages = Blueprint('match_pages', __name__)

@match_pages.route('/matches/<int:match_id>')
@login_required
def view_match(match_id):
    # Fetch the match details from the database
    match = Match.query.get_or_404(match_id)
    schedule = match.schedule
    
    # Create RSVP dictionaries for home and away teams
    def get_rsvp_data(team):
        rsvp_data = {
            'available': [],
            'not_available': [],
            'maybe': [],
            'no_response': []
        }
        for player in team.players:
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
    
    # Calculate RSVP data for home and away teams
    home_rsvp_data = get_rsvp_data(match.home_team)
    away_rsvp_data = get_rsvp_data(match.away_team)
    
    # Render the match page template with the match data and RSVP data
    return render_template(
        'view_match.html', 
        match=match, 
        schedule=schedule,
        home_rsvp_data=home_rsvp_data,
        away_rsvp_data=away_rsvp_data
    )

@match_pages.route('/rsvp/<int:match_id>', methods=['POST'])
@login_required
def rsvp(match_id):
    data = request.get_json()
    new_response = data.get('response')
    player_id = data.get('player_id')
    discord_id = data.get('discord_id') or None
    
    success, message = update_rsvp(match_id, player_id, new_response, discord_id)
    
    if success:
        return jsonify({'success': True, 'message': message})
    else:
        app.logger.error(f"Error updating RSVP: {message}")
        return jsonify({'success': False, 'message': 'An error occurred while updating RSVP'}), 500

@match_pages.route('/rsvp/status/<int:match_id>', methods=['GET'])
@login_required
def get_rsvp_status(match_id):
    player_id = current_user.player.id  # Assuming the user has a player profile
    availability = Availability.query.filter_by(match_id=match_id, player_id=player_id).first()

    if availability:
        return jsonify({'response': availability.response})
    else:
        return jsonify({'response': 'no_response'})  # Default to "no response" if not found