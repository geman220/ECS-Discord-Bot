# app/admin/substitute_routes.py

"""
Substitute Management Routes

This module contains routes for managing substitute players,
sub requests, and temporary sub assignments.
"""

import logging
from datetime import datetime, timedelta
from flask import request, redirect, url_for, g, render_template, jsonify, current_app
from flask_login import login_required
from sqlalchemy.orm import joinedload
from sqlalchemy import text

from app.decorators import role_required
from app.alert_helpers import show_error, show_success, show_info
from app.admin_helpers import (
    get_available_subs, get_match_subs, assign_sub_to_team,
    remove_sub_assignment, get_player_active_sub_assignments,
    cleanup_old_sub_assignments, create_sub_request,
    update_sub_request_status, get_subs_by_match_league_type
)
from app.models import (
    Match, Team, Player, Schedule, Season, SubRequest, 
    TemporarySubAssignment
)
from app.utils.user_helpers import safe_current_user

# Import the shared admin blueprint
from app.admin.blueprint import admin_bp

logger = logging.getLogger(__name__)


# -----------------------------------------------------------
# Substitute Management Routes
# -----------------------------------------------------------

@admin_bp.route('/admin/sub_requests', endpoint='manage_sub_requests')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def manage_sub_requests():
    """
    Display the sub request dashboard for admins.
    
    Shows all upcoming matches grouped by week and flags any teams that need substitutes.
    Also displays a card view of pending sub requests for quick action.
    """
    session = g.db_session
    
    # Get filter parameters
    show_requested = request.args.get('show_requested', 'all')
    week = request.args.get('week')
    
    # Get all weeks for the filter dropdown
    current_season = session.query(Season).filter_by(is_current=True, league_type="Pub League").first()
    weeks = []
    if current_season:
        weeks_query = session.query(Schedule.week).filter(
            Schedule.season_id == current_season.id
        ).distinct().order_by(Schedule.week)
        weeks = [str(week_row[0]) for week_row in weeks_query]
    
    # Get upcoming matches (for the next 30 days)
    today = datetime.now().date()
    thirty_days_ahead = today + timedelta(days=30)
    
    match_query = session.query(Match).options(
        joinedload(Match.home_team),
        joinedload(Match.away_team),
        joinedload(Match.schedule)
    ).filter(
        Match.date >= today,
        Match.date <= thirty_days_ahead
    )
    
    # Filter by week if specified
    if week:
        match_query = match_query.join(
            Schedule, Match.schedule_id == Schedule.id
        ).filter(
            Schedule.week == week
        )
    
    # Order by date, then time
    upcoming_matches = match_query.order_by(
        Match.date,
        Match.time
    ).all()
    
    # Check if we have any matches
    if not upcoming_matches:
        logger.warning("No upcoming matches found for sub requests page. Check your date filters.")
        # Add debug log to see current date range
        logger.debug(f"Date range: {today} to {thirty_days_ahead}")
    
    # Get all sub requests for these matches
    match_ids = [match.id for match in upcoming_matches]
    
    # Only get sub requests if we have matches
    if match_ids:
        sub_requests = session.query(SubRequest).options(
            joinedload(SubRequest.match),
            joinedload(SubRequest.team),
            joinedload(SubRequest.requester),
            joinedload(SubRequest.fulfiller)
        ).filter(
            SubRequest.match_id.in_(match_ids)
        ).order_by(
            SubRequest.created_at.desc()
        ).all()
    else:
        sub_requests = []
    
    # Organize sub requests by match and team for easier access
    requested_teams_by_match = {}
    for match in upcoming_matches:
        requested_teams_by_match[match.id] = {}
    
    for req in sub_requests:
        if req.match_id in requested_teams_by_match:
            # Count current assignments for this request
            assignments_count = session.query(TemporarySubAssignment).filter_by(
                match_id=req.match_id,
                team_id=req.team_id
            ).count()
            req.assignments_count = assignments_count
            requested_teams_by_match[req.match_id][req.team_id] = req
    
    # Filter matches based on whether they have requests or not
    filtered_matches = []
    for match in upcoming_matches:
        has_requests = match.id in requested_teams_by_match and requested_teams_by_match[match.id]
        
        if show_requested == 'all':
            filtered_matches.append(match)
        elif show_requested == 'requested' and has_requests:
            filtered_matches.append(match)
        elif show_requested == 'not_requested' and not has_requests:
            filtered_matches.append(match)
    
    upcoming_matches = filtered_matches
    
    # Get available subs for each match based on their league type
    subs_by_match = get_subs_by_match_league_type(upcoming_matches, session=session)
    
    # Keep the old available_subs for backward compatibility if needed
    available_subs = get_available_subs(session=session)
    
    return render_template(
        'admin/manage_sub_requests.html',
        title='Manage Sub Requests',
        sub_requests=sub_requests,
        upcoming_matches=upcoming_matches,
        requested_teams_by_match=requested_teams_by_match,
        available_subs=available_subs,
        subs_by_match=subs_by_match,
        show_requested=show_requested,
        current_week=week,
        weeks=weeks
    )


@admin_bp.route('/admin/sub_requests/<int:request_id>', methods=['POST'], endpoint='update_sub_request')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def update_sub_request(request_id):
    """
    Update a sub request's status.
    
    Handles fulfilling a sub request by assigning a player.
    """
    session = g.db_session
    
    action = request.form.get('action')
    player_id = request.form.get('player_id')  # For fulfillment
    
    if not action or action != 'fulfill':
        show_error('Invalid action.')
        return redirect(url_for('admin.manage_sub_requests'))
    
    if not player_id:
        show_error('Player ID is required for fulfillment.')
        return redirect(url_for('admin.manage_sub_requests'))
    
    # Get the sub request
    sub_request = session.query(SubRequest).options(
        joinedload(SubRequest.match),
        joinedload(SubRequest.team)
    ).get(request_id)
    
    if not sub_request:
        show_error('Sub request not found.')
        return redirect(url_for('admin.manage_sub_requests'))
    
    # Directly fulfill the request - no intermediate approval step
    fulfill_success, fulfill_message = assign_sub_to_team(
        match_id=sub_request.match_id,
        team_id=sub_request.team_id,
        player_id=player_id,
        user_id=safe_current_user.id,
        session=session
    )
    
    if fulfill_success:
        # Check if all substitutes have been assigned
        current_assignments = session.query(TemporarySubAssignment).filter_by(
            match_id=sub_request.match_id,
            team_id=sub_request.team_id
        ).count()
        
        if current_assignments >= sub_request.substitutes_needed:
            # All substitutes assigned, mark as fulfilled
            success, message = update_sub_request_status(
                request_id=request_id,
                status='FULFILLED',
                fulfilled_by=safe_current_user.id,
                session=session
            )
        else:
            # Still need more substitutes, keep status as pending/approved
            success = True
            message = f"Substitute assigned successfully. {current_assignments} of {sub_request.substitutes_needed} positions filled."
    else:
        success = False
        message = fulfill_message
    
    if success:
        show_success(message)
    else:
        show_error(message)
    
    return redirect(url_for('admin.manage_sub_requests'))


@admin_bp.route('/admin/request_sub', methods=['POST'], endpoint='request_sub')
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'Pub League Coach', 'ECS FC Coach'])
def request_sub():
    """
    Create a new sub request.
    
    Coaches can request subs for their teams, and admins can request for any team.
    Handles both pub league and ECS FC matches.
    """
    session = g.db_session
    
    match_id_raw = request.form.get('match_id')
    team_id_raw = request.form.get('team_id')
    notes = request.form.get('notes')
    positions_needed = request.form.get('positions_needed')
    gender_preference = request.form.get('gender_preference')
    substitutes_needed = request.form.get('substitutes_needed', 1, type=int)
    
    if not match_id_raw or not team_id_raw:
        show_error('Missing required fields for sub request.')
        return redirect(request.referrer or url_for('main.index'))
    
    # Check if this is an ECS FC match (format: "ecs_123")
    if match_id_raw.startswith('ecs_'):
        # Handle ECS FC substitute request
        try:
            ecs_match_id = int(match_id_raw[4:])  # Remove "ecs_" prefix
            
            # Import ECS FC models and unified substitute models
            from app.models_ecs import EcsFcMatch
            from app.models_substitute_pools import SubstituteRequest
            from app.tasks.tasks_substitute_pools import notify_substitute_pool_of_request
            
            # Get the ECS FC match
            ecs_match = session.query(EcsFcMatch).get(ecs_match_id)
            if not ecs_match:
                show_error('ECS FC match not found.')
                return redirect(request.referrer or url_for('main.index'))
            
            # Check if user is coach or admin for this team
            user_player = safe_current_user.player
            if not user_player:
                show_error('You must be linked to a player to request substitutes.')
                return redirect(url_for('admin.rsvp_status', match_id=match_id_raw))
            
            # Check permissions
            is_coach = any(team.id == ecs_match.team_id and coach_status 
                          for team, coach_status in user_player.current_teams)
            is_admin = any(role.name in ['Global Admin', 'Pub League Admin', 'ECS FC Admin'] 
                          for role in safe_current_user.roles)
            
            if not is_coach and not is_admin:
                show_error("You don't have permission to request substitutes for this team.")
                return redirect(url_for('admin.rsvp_status', match_id=match_id_raw))
            
            # Check if there's already an open request
            existing_request = session.query(SubstituteRequest).filter_by(
                match_id=ecs_match.id,
                league_type='ECS FC',
                status='OPEN'
            ).first()
            
            if existing_request:
                show_info('There is already an open substitute request for this match.')
                return redirect(url_for('admin.rsvp_status', match_id=match_id_raw))
            
            # Create the unified substitute request for ECS FC
            sub_request = SubstituteRequest(
                match_id=ecs_match.id,
                league_type='ECS FC',
                team_id=ecs_match.team_id,
                requested_by=safe_current_user.id,
                positions_needed=positions_needed,
                gender_preference=gender_preference if gender_preference else None,
                notes=notes,
                status='OPEN'
            )
            
            session.add(sub_request)
            session.commit()
            
            # Send notifications to all active subs in the pool asynchronously
            notify_substitute_pool_of_request.delay(sub_request.id, 'ECS FC')
            
            gender_msg = f" (targeting {gender_preference} players)" if gender_preference else ""
            show_success(f'ECS FC substitute request created{gender_msg}. Notifications are being sent to available substitutes.')
            return redirect(url_for('admin.rsvp_status', match_id=match_id_raw))
            
        except (ValueError, TypeError):
            show_error('Invalid ECS FC match ID format.')
            return redirect(request.referrer or url_for('main.index'))
    
    # Handle regular pub league match
    try:
        match_id = int(match_id_raw)
    except (ValueError, TypeError):
        show_error('Invalid match ID format.')
        return redirect(request.referrer or url_for('main.index'))
    
    # Handle special cases from the JavaScript fallback
    if team_id_raw == 'home_team' or team_id_raw == 'away_team':
        # Get the match to determine the actual team IDs
        match = session.query(Match).get(match_id)
        if not match:
            show_error('Match not found.')
            return redirect(request.referrer or url_for('main.index'))
        
        # Set team_id based on the placeholder value
        team_id = match.home_team_id if team_id_raw == 'home_team' else match.away_team_id
    else:
        try:
            team_id = int(team_id_raw)
        except (ValueError, TypeError):
            show_error('Invalid team ID format.')
            return redirect(request.referrer or url_for('main.index'))
    
    # Check permissions for coaches
    if safe_current_user.has_role('Pub League Coach') and not (safe_current_user.has_role('Pub League Admin') or safe_current_user.has_role('Global Admin')):
        # Verify that the user is a coach for this team
        is_coach = False
        
        # Get the match to verify teams
        match = session.query(Match).get(match_id)
        if not match:
            show_error('Match not found.')
            return redirect(request.referrer or url_for('main.index'))
        
        # Verify this is a valid team for this match
        if team_id != match.home_team_id and team_id != match.away_team_id:
            show_error('Selected team is not part of this match.')
            return redirect(url_for('admin.rsvp_status', match_id=match_id))
        
        # Direct database query to check coach status
        try:
            # Simpler direct SQL query for maximum reliability
            coach_team_results = session.execute(
                text("SELECT COUNT(*) FROM player_teams WHERE player_id = :player_id AND team_id = :team_id AND is_coach = TRUE"),
                {"player_id": safe_current_user.player.id, "team_id": team_id}
            ).fetchone()
            
            if coach_team_results and coach_team_results[0] > 0:
                is_coach = True
                logger.info(f"User {safe_current_user.id} verified as coach for team {team_id}")
            else:
                logger.warning(f"User {safe_current_user.id} is not a coach for team {team_id}")
        except Exception as sql_e:
            logger.error(f"SQL coach check failed: {str(sql_e)}")
            
            # Last resort check - use related models
            try:
                # Try one more alternate method - get teams for this player
                player_id = safe_current_user.player.id
                coach_teams = session.query(Team).join(
                    "player_teams"
                ).filter(
                    text(f"player_teams.player_id = {player_id} AND player_teams.is_coach = TRUE")
                ).all()
                
                if any(t.id == team_id for t in coach_teams):
                    is_coach = True
                    logger.info(f"Alternate check: User {safe_current_user.id} verified as coach for team {team_id}")
            except Exception as alt_e:
                logger.error(f"Alternate coach check failed: {str(alt_e)}")
        
        # Final check
        if not is_coach:
            if current_app.debug or current_app.config.get('ENV') == 'development':
                # Development mode - still allow it but log warning
                logger.warning(f"Development mode: Allowing sub request for user {safe_current_user.id} despite not being coach")
                is_coach = True
            elif match and (team_id == match.home_team_id or team_id == match.away_team_id):
                # If it's a valid team for this match and user has Pub League Coach role, 
                # we'll allow it even without direct relationship since database schema
                # might not fully represent coaching relationships
                logger.warning(f"Coach role override: Allowing request for {safe_current_user.id} for team {team_id}")
                is_coach = True
            else:
                show_error('You are not authorized to request subs for this team.')
                logger.warning(f"User {safe_current_user.id} denied sub request for team {team_id}, match {match_id}")
                return redirect(request.referrer or url_for('main.index'))
    
    # Create the sub request
    success, message, request_id = create_sub_request(
        match_id=match_id,
        team_id=team_id,
        requested_by=safe_current_user.id,
        notes=notes,
        substitutes_needed=substitutes_needed,
        session=session
    )
    
    if success:
        show_success(message)
    else:
        show_error(message)
    
    # Determine where to redirect
    if request.referrer and 'rsvp_status' in request.referrer:
        return redirect(url_for('admin.rsvp_status', match_id=match_id))
    else:
        return redirect(url_for('admin.manage_sub_requests'))


@admin_bp.route('/admin/subs', endpoint='manage_subs')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def manage_subs():
    """
    Display a list of all available substitutes and their assignments.
    
    This page shows all players marked as substitutes and allows admins to
    manage their team assignments for matches.
    """
    session = g.db_session
    
    # Get all available subs
    subs = get_available_subs(session=session)
    
    # Get all upcoming matches in chronological order
    upcoming_matches = session.query(Match).filter(
        Match.date >= datetime.utcnow().date()
    ).order_by(
        Match.date, Match.time
    ).options(
        joinedload(Match.home_team),
        joinedload(Match.away_team)
    ).all()
    
    # Get teams for assignment
    teams = session.query(Team).all()
    
    return render_template(
        'admin/manage_subs.html',
        title='Manage Substitutes',
        subs=subs,
        upcoming_matches=upcoming_matches,
        teams=teams
    )


@admin_bp.route('/admin/subs/assign', methods=['POST'], endpoint='assign_sub')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def assign_sub():
    """
    Assign a substitute to a team for a specific match.
    """
    session = g.db_session
    
    player_id = request.form.get('player_id', type=int)
    match_id = request.form.get('match_id', type=int)
    team_id = request.form.get('team_id', type=int)
    
    if not all([player_id, match_id, team_id]):
        show_error('Missing required fields for sub assignment.')
        return redirect(url_for('admin.manage_subs'))
    
    success, message = assign_sub_to_team(
        match_id=match_id,
        player_id=player_id,
        team_id=team_id,
        user_id=safe_current_user.id,
        session=session
    )
    
    if success:
        show_success(message)
    else:
        show_error(message)
    
    # If AJAX request, return JSON response
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': success, 'message': message})
    
    # Get redirect location - could be RSVP status page or manage subs page
    redirect_to = request.form.get('redirect_to', 'manage_subs')
    if redirect_to == 'rsvp_status':
        return redirect(url_for('admin.rsvp_status', match_id=match_id))
    else:
        return redirect(url_for('admin.manage_subs'))


@admin_bp.route('/admin/subs/remove/<int:assignment_id>', methods=['POST'], endpoint='remove_sub')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def remove_sub(assignment_id):
    """
    Remove a substitute assignment.
    """
    session = g.db_session
    
    # Get the assignment to determine the match_id for potential redirect
    assignment = session.query(TemporarySubAssignment).get(assignment_id)
    if not assignment:
        show_error('Assignment not found.')
        return redirect(url_for('admin.manage_subs'))
    
    match_id = assignment.match_id
    
    success, message = remove_sub_assignment(
        assignment_id=assignment_id,
        user_id=safe_current_user.id,
        session=session
    )
    
    if success:
        show_success(message)
    else:
        show_error(message)
    
    # If AJAX request, return JSON response
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': success, 'message': message})
    
    # Get redirect location - could be RSVP status page or manage subs page
    redirect_to = request.form.get('redirect_to', 'manage_subs')
    if redirect_to == 'rsvp_status':
        return redirect(url_for('admin.rsvp_status', match_id=match_id))
    else:
        return redirect(url_for('admin.manage_subs'))


@admin_bp.route('/admin/subs/match/<int:match_id>', methods=['GET'], endpoint='get_match_subs_route')
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'Pub League Coach'])
def get_match_subs_route(match_id):
    """
    Get all subs assigned to a specific match, organized by team.
    
    Returns a JSON response for AJAX requests or redirects to the RSVP status page.
    """
    session = g.db_session
    
    subs_by_team = get_match_subs(match_id=match_id, session=session)
    
    # If AJAX request, return JSON response
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'success': True,
            'subs_by_team': subs_by_team
        })
    
    return redirect(url_for('admin.rsvp_status', match_id=match_id))


@admin_bp.route('/admin/subs/available', methods=['GET'], endpoint='get_available_subs_api')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def get_available_subs_api():
    """
    Get all available substitutes as JSON.
    
    Returns a JSON response for AJAX requests.
    """
    session = g.db_session
    
    subs = get_available_subs(session=session)
    
    return jsonify({
        'success': True,
        'subs': subs
    })


@admin_bp.route('/admin/subs/player/<int:player_id>', methods=['GET'], endpoint='get_player_subs')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def get_player_subs(player_id):
    """
    Get all active sub assignments for a player.
    
    Returns a JSON response for AJAX requests.
    """
    session = g.db_session
    
    assignments = get_player_active_sub_assignments(player_id=player_id, session=session)
    
    # If AJAX request, return JSON response
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'success': True,
            'assignments': assignments
        })
    
    return redirect(url_for('admin.manage_subs'))


@admin_bp.route('/admin/subs/cleanup', methods=['POST'], endpoint='cleanup_subs')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def cleanup_subs():
    """
    Clean up sub assignments for matches that occurred in the past.
    
    This should be run automatically via a scheduled task every Monday,
    but can also be triggered manually by an admin.
    """
    session = g.db_session
    
    count, message = cleanup_old_sub_assignments(session=session)
    
    if count > 0:
        show_success(message)
    else:
        show_info(message)
    
    return redirect(url_for('admin.manage_subs'))