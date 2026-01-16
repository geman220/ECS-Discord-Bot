"""
ECS FC Routes Module

This module provides web routes for ECS FC match management, including
match details, RSVP management, and integration with the admin system.
"""

import logging
from datetime import datetime
from flask import Blueprint, request, render_template, redirect, url_for, flash, abort, jsonify, g
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload

from app.core import db
from app.models import Team, League, Player
from app.models_ecs import EcsFcMatch, EcsFcAvailability
from app.models.ecs_fc import EcsFcPlayerEvent
from app.ecs_fc_schedule import EcsFcScheduleManager, is_user_ecs_fc_coach
from app.decorators import role_required

logger = logging.getLogger(__name__)

# Create blueprint
ecs_fc_routes = Blueprint('ecs_fc', __name__, url_prefix='/ecs-fc')


def check_ecs_fc_access(match_id: int) -> bool:
    """Check if current user has access to ECS FC match."""
    # Global/Pub League admins have access
    if (current_user.has_role('Global Admin') or 
        current_user.has_role('Pub League Admin')):
        return True
    
    # Check if user is ECS FC coach
    if current_user.has_role('ECS FC Coach'):
        match = EcsFcMatch.query.get(match_id)
        if match:
            coached_teams = is_user_ecs_fc_coach(current_user.id)
            return match.team_id in coached_teams
    
    return False


@ecs_fc_routes.route('/matches/<int:match_id>')
@login_required
def match_details(match_id: int):
    """Display ECS FC match details with RSVP information."""
    try:
        # Get the match with related data
        match = EcsFcMatch.query.options(
            joinedload(EcsFcMatch.team).joinedload(Team.players),
            joinedload(EcsFcMatch.availabilities).joinedload(EcsFcAvailability.player)
        ).get_or_404(match_id)
        
        # Check access permissions
        can_manage = check_ecs_fc_access(match_id)
        
        # If user doesn't have management access, check if they're a player on the team
        if not can_manage:
            if current_user.player and current_user.player in match.team.players:
                # Player can view their own team's matches
                pass
            else:
                abort(403)
        
        # Get RSVP summary
        rsvp_summary = match.get_rsvp_summary()
        
        # Build RSVP responses dictionary for easier template access
        rsvp_responses = {}
        for availability in match.availabilities:
            rsvp_responses[availability.player_id] = availability
        
        return render_template(
            'ecs_fc_match_details_flowbite.html',
            match=match,
            rsvp_summary=rsvp_summary,
            rsvp_responses=rsvp_responses,
            can_manage=can_manage
        )
        
    except Exception as e:
        logger.error(f"Error displaying ECS FC match {match_id}: {str(e)}")
        flash('Error loading match details', 'error')
        return redirect(url_for('main.index'))


@ecs_fc_routes.route('/rsvp/<int:match_id>')
@login_required
def rsvp_form(match_id: int):
    """Display RSVP form for ECS FC match."""
    try:
        # Get the match
        match = EcsFcMatch.query.options(
            joinedload(EcsFcMatch.team).joinedload(Team.players)
        ).get_or_404(match_id)
        
        # Check if user is a player on the team
        if not current_user.player or current_user.player not in match.team.players:
            abort(403)
        
        # Get existing RSVP if any
        existing_rsvp = EcsFcAvailability.query.filter_by(
            ecs_fc_match_id=match_id,
            player_id=current_user.player.id
        ).first()
        
        return render_template(
            'ecs_fc_rsvp_form_flowbite.html',
            match=match,
            existing_rsvp=existing_rsvp
        )
        
    except Exception as e:
        logger.error(f"Error displaying ECS FC RSVP form for match {match_id}: {str(e)}")
        flash('Error loading RSVP form', 'error')
        return redirect(url_for('main.index'))


@ecs_fc_routes.route('/rsvp/<int:match_id>', methods=['POST'])
@login_required
def submit_rsvp(match_id: int):
    """Submit RSVP response for ECS FC match."""
    try:
        # Get the match
        match = EcsFcMatch.query.options(
            joinedload(EcsFcMatch.team).joinedload(Team.players)
        ).get_or_404(match_id)
        
        # Check if user is a player on the team
        if not current_user.player or current_user.player not in match.team.players:
            abort(403)
        
        # Get form data
        response = request.form.get('response')
        notes = request.form.get('notes', '').strip()
        
        if response not in ['yes', 'no', 'maybe']:
            flash('Invalid response', 'error')
            return redirect(url_for('ecs_fc.rsvp_form', match_id=match_id))
        
        # Submit RSVP using the schedule manager
        success, message = EcsFcScheduleManager.submit_rsvp(
            match_id=match_id,
            player_id=current_user.player.id,
            response=response,
            user_id=current_user.id,
            discord_id=getattr(current_user, 'discord_id', None),
            notes=notes if notes else None
        )
        
        if success:
            flash('RSVP submitted successfully', 'success')
            return redirect(url_for('ecs_fc.match_details', match_id=match_id))
        else:
            flash(f'Error submitting RSVP: {message}', 'error')
            return redirect(url_for('ecs_fc.rsvp_form', match_id=match_id))
        
    except Exception as e:
        logger.error(f"Error submitting ECS FC RSVP for match {match_id}: {str(e)}")
        flash('Error submitting RSVP', 'error')
        return redirect(url_for('ecs_fc.rsvp_form', match_id=match_id))


# Error handlers
@ecs_fc_routes.errorhandler(403)
def forbidden(error):
    """Handle 403 errors."""
    flash('You do not have permission to access this resource', 'error')
    return redirect(url_for('main.index'))


@ecs_fc_routes.errorhandler(404)
def not_found(error):
    """Handle 404 errors."""
    flash('The requested ECS FC match was not found', 'error')
    return redirect(url_for('main.index'))


@ecs_fc_routes.route('/report/<int:match_id>', methods=['GET'])
@login_required
def report_match_get(match_id: int):
    """
    Get ECS FC match data for reporting modal.
    Returns JSON data for the match report form.
    """
    session = g.db_session

    try:
        # Get the match with related data
        match = session.query(EcsFcMatch).options(
            joinedload(EcsFcMatch.team).joinedload(Team.players),
            joinedload(EcsFcMatch.events).joinedload(EcsFcPlayerEvent.player)
        ).get(match_id)

        if not match:
            return jsonify({'success': False, 'message': 'Match not found'}), 404

        # Check access permissions
        if not check_ecs_fc_access(match_id):
            return jsonify({'success': False, 'message': 'Access denied'}), 403

        # Build player choices for the team
        team_players = {}
        if match.team and match.team.players:
            for player in match.team.players:
                team_players[str(player.id)] = player.name

        # Get existing events grouped by type
        goals = []
        assists = []
        yellow_cards = []
        red_cards = []
        own_goals = []

        for event in match.events:
            event_data = {
                'id': event.id,
                'player_id': str(event.player_id) if event.player_id else None,
                'player_name': event.player.name if event.player else 'Unknown',
                'minute': event.minute
            }

            if event.event_type == 'goal':
                goals.append(event_data)
            elif event.event_type == 'assist':
                assists.append(event_data)
            elif event.event_type == 'yellow_card':
                yellow_cards.append(event_data)
            elif event.event_type == 'red_card':
                red_cards.append(event_data)
            elif event.event_type == 'own_goal':
                event_data['team_id'] = str(event.team_id) if event.team_id else None
                own_goals.append(event_data)

        # Return match data
        response_data = {
            'success': True,
            'match_id': f'ecs_{match_id}',
            'is_ecs_fc': True,
            'home_team_name': match.team.name if match.team else 'Unknown',
            'away_team_name': match.opponent_name or 'Unknown',
            'home_team_score': match.home_score or 0,
            'away_team_score': match.away_score or 0,
            'notes': match.notes or '',
            'reported': match.status == 'COMPLETED',
            'match_date': match.match_date.strftime('%Y-%m-%d') if match.match_date else None,
            'match_time': match.match_time.strftime('%H:%M') if match.match_time else None,
            'location': match.location,
            'player_choices': {
                match.team.name if match.team else 'Team': team_players
            },
            'goals': goals,
            'assists': assists,
            'yellow_cards': yellow_cards,
            'red_cards': red_cards,
            'own_goals': own_goals,
            'version': 1  # For optimistic locking compatibility
        }

        return jsonify(response_data)

    except Exception as e:
        logger.error(f"Error fetching ECS FC match data for reporting {match_id}: {str(e)}")
        return jsonify({'success': False, 'message': 'Error loading match data'}), 500


@ecs_fc_routes.route('/report/<int:match_id>', methods=['POST'])
@login_required
def report_match_post(match_id: int):
    """
    Submit ECS FC match report.
    Accepts JSON data with score and events.
    """
    session = g.db_session

    try:
        # Get the match
        match = session.query(EcsFcMatch).options(
            joinedload(EcsFcMatch.team),
            joinedload(EcsFcMatch.events)
        ).get(match_id)

        if not match:
            return jsonify({'success': False, 'message': 'Match not found'}), 404

        # Check access permissions
        if not check_ecs_fc_access(match_id):
            return jsonify({'success': False, 'message': 'Access denied'}), 403

        # Get JSON data
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data provided'}), 400

        # Update match score
        home_score = data.get('home_team_score')
        away_score = data.get('away_team_score')
        notes = data.get('notes', '')

        if home_score is not None:
            match.home_score = int(home_score)
        if away_score is not None:
            match.away_score = int(away_score)
        if notes:
            match.notes = notes

        # Mark as completed
        match.status = 'COMPLETED'
        match.updated_at = datetime.utcnow()

        # Process event additions
        user_id = current_user.id

        # Add goals
        for goal in data.get('goals_to_add', []):
            player_id = goal.get('player_id')
            if player_id:
                event = EcsFcPlayerEvent(
                    player_id=int(player_id),
                    ecs_fc_match_id=match_id,
                    event_type='goal',
                    minute=goal.get('minute'),
                    created_by=user_id
                )
                session.add(event)

        # Add assists
        for assist in data.get('assists_to_add', []):
            player_id = assist.get('player_id')
            if player_id:
                event = EcsFcPlayerEvent(
                    player_id=int(player_id),
                    ecs_fc_match_id=match_id,
                    event_type='assist',
                    minute=assist.get('minute'),
                    created_by=user_id
                )
                session.add(event)

        # Add yellow cards
        for card in data.get('yellow_cards_to_add', []):
            player_id = card.get('player_id')
            if player_id:
                event = EcsFcPlayerEvent(
                    player_id=int(player_id),
                    ecs_fc_match_id=match_id,
                    event_type='yellow_card',
                    minute=card.get('minute'),
                    created_by=user_id
                )
                session.add(event)

        # Add red cards
        for card in data.get('red_cards_to_add', []):
            player_id = card.get('player_id')
            if player_id:
                event = EcsFcPlayerEvent(
                    player_id=int(player_id),
                    ecs_fc_match_id=match_id,
                    event_type='red_card',
                    minute=card.get('minute'),
                    created_by=user_id
                )
                session.add(event)

        # Add own goals
        for own_goal in data.get('own_goals_to_add', []):
            team_id = own_goal.get('team_id')
            if team_id:
                event = EcsFcPlayerEvent(
                    team_id=int(team_id),
                    ecs_fc_match_id=match_id,
                    event_type='own_goal',
                    minute=own_goal.get('minute'),
                    created_by=user_id
                )
                session.add(event)

        # Process event removals
        events_to_remove = (
            data.get('goals_to_remove', []) +
            data.get('assists_to_remove', []) +
            data.get('yellow_cards_to_remove', []) +
            data.get('red_cards_to_remove', []) +
            data.get('own_goals_to_remove', [])
        )

        for event_id in events_to_remove:
            if event_id:
                event = session.query(EcsFcPlayerEvent).get(int(event_id))
                if event and event.ecs_fc_match_id == match_id:
                    session.delete(event)

        session.commit()

        logger.info(f"ECS FC match {match_id} reported successfully by user {user_id}")

        return jsonify({
            'success': True,
            'message': 'Match report submitted successfully',
            'home_team_verified': True,
            'away_team_verified': True
        })

    except Exception as e:
        session.rollback()
        logger.error(f"Error submitting ECS FC match report {match_id}: {str(e)}")
        return jsonify({'success': False, 'message': f'Error submitting report: {str(e)}'}), 500