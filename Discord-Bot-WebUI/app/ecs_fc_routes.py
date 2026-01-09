"""
ECS FC Routes Module

This module provides web routes for ECS FC match management, including
match details, RSVP management, and integration with the admin system.
"""

import logging
from flask import Blueprint, request, render_template, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload

from app.core import db
from app.models import Team, League, Player
from app.models_ecs import EcsFcMatch, EcsFcAvailability
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
            'ecs_fc_rsvp_form.html',
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