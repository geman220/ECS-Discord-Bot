from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from app.models import Match, Schedule, Availability
from app import db
from datetime import datetime

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
    response = data.get('response')
    player_id = data.get('player_id')
    discord_id = data.get('discord_id') or None  # Handle case where discord_id might be missing

    if response not in ['yes', 'no', 'maybe', 'no_response']:
        return jsonify({'success': False, 'message': 'Invalid response'}), 400

    # Update the player's availability in the database
    availability = Availability.query.filter_by(match_id=match_id, player_id=player_id).first()

    if availability:
        if response == 'no_response':
            db.session.delete(availability)
        else:
            availability.response = response
            availability.responded_at = datetime.utcnow()
    else:
        # If no availability record exists and it's not "no_response", create one
        if response != 'no_response':
            availability = Availability(
                match_id=match_id,
                player_id=player_id,
                response=response,
                discord_id=discord_id,
                responded_at=datetime.utcnow()
            )
            db.session.add(availability)

    db.session.commit()
    return jsonify({'success': True, 'message': 'RSVP updated successfully'})

@match_pages.route('/rsvp/status/<int:match_id>', methods=['GET'])
@login_required
def get_rsvp_status(match_id):
    player_id = current_user.player.id  # Assuming the user has a player profile
    availability = Availability.query.filter_by(match_id=match_id, player_id=player_id).first()

    if availability:
        return jsonify({'response': availability.response})
    else:
        return jsonify({'response': 'no_response'})  # Default to "no response" if not found