# app/admin/reports_routes.py

"""
Reports and Analytics Routes

This module contains routes for admin reports, RSVP status,
match statistics, and RSVP updates.
"""

import logging
from datetime import datetime, timedelta
from flask import Blueprint, request, redirect, url_for, abort, g, render_template, jsonify
from flask_login import login_required
from app.decorators import role_required
from app.alert_helpers import show_error, show_success, show_info
from app.admin_helpers import get_rsvp_status_data, get_ecs_fc_rsvp_status_data
from app.models import Feedback, Match, Player, Availability, User
from app.models_ecs import EcsFcMatch, EcsFcAvailability
from app.ecs_fc_schedule import EcsFcScheduleManager
from app.utils.user_helpers import safe_current_user

logger = logging.getLogger(__name__)

# Import the shared admin blueprint
from app.admin.blueprint import admin_bp

# Import CSRF utilities
from flask_wtf.csrf import CSRFProtect, generate_csrf

# Initialize CSRF protection
csrf = CSRFProtect()

# Create a more robust decorator to handle CSRF exemption
def csrf_exempt(route_func):
    """Decorator to exempt a route from CSRF protection and handle token issues."""
    route_func.csrf_exempt = True
    
    # Create a wrapper function to handle the request
    def wrapped_route(*args, **kwargs):
        # The route is already exempt, but we still add extra logging
        logger.info(f"CSRF exempt route called: {route_func.__name__}")
        
        # Proceed with the original route function
        return route_func(*args, **kwargs)
        
    # Preserve the route name and other attributes
    wrapped_route.__name__ = route_func.__name__
    wrapped_route.__module__ = route_func.__module__
    
    return wrapped_route


# -----------------------------------------------------------
# Reports & Analytics
# -----------------------------------------------------------

@admin_bp.route('/admin/reports', endpoint='admin_reports')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def admin_reports():
    """
    Render the admin reports view, including filtering and pagination
    for feedback reports.
    """
    session = g.db_session
    page = request.args.get('page', 1, type=int)
    per_page = 20
    filters = {
        'status': request.args.get('status', ''),
        'priority': request.args.get('priority', ''),
        'sort_by': request.args.get('sort_by', 'created_at'),
        'order': request.args.get('order', 'desc')
    }

    query = session.query(Feedback)
    if filters['status']:
        query = query.filter(Feedback.status == filters['status'])
    if filters['priority']:
        query = query.filter(Feedback.priority == filters['priority'])

    sort_col = getattr(Feedback, filters['sort_by'], Feedback.created_at)
    if filters['order'] == 'asc':
        query = query.order_by(sort_col.asc())
    else:
        query = query.order_by(sort_col.desc())

    total = query.count()
    feedbacks = query.offset((page - 1) * per_page).limit(per_page).all()

    return render_template('admin_reports.html', title='Admin Reports', feedbacks=feedbacks, page=page, total=total, per_page=per_page)


@admin_bp.route('/admin/rsvp_status/<match_id>', endpoint='rsvp_status')
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'Pub League Coach'])
def rsvp_status(match_id):
    """
    Display RSVP status details for a specific match.
    Supports both regular matches and ECS FC matches.
    """
    session = g.db_session
    
    # Check if this is an ECS FC match
    is_ecs_fc_match = isinstance(match_id, str) and match_id.startswith('ecs_')
    
    if is_ecs_fc_match:
        # Extract the actual ECS FC match ID
        actual_match_id = int(match_id[4:])  # Remove 'ecs_' prefix
        
        # Fetch ECS FC match details
        ecs_match = EcsFcScheduleManager.get_match_by_id(actual_match_id)
        if not ecs_match:
            abort(404)
        
        # Get ECS FC specific RSVP data
        rsvp_data = get_ecs_fc_rsvp_status_data(ecs_match, session=session)
        match = None  # No regular match object
        
        # Get the active substitute request for this ECS FC match
        from app.models_ecs_subs import EcsFcSubRequest
        ecs_sub_request = session.query(EcsFcSubRequest).filter_by(
            match_id=actual_match_id,
            status='OPEN'
        ).first()
        
    else:
        # Handle regular pub league match
        try:
            actual_match_id = int(match_id)
        except ValueError:
            abort(404)
        
        match = session.query(Match).get(actual_match_id)
        if not match:
            abort(404)
        rsvp_data = get_rsvp_status_data(match, session=session)
        ecs_match = None
        ecs_sub_request = None
    
    return render_template('admin/rsvp_status.html', 
                         title='RSVP Status', 
                         match=match, 
                         ecs_match=ecs_match,
                         ecs_sub_request=ecs_sub_request,
                         rsvps=rsvp_data, 
                         is_ecs_fc_match=is_ecs_fc_match)


@admin_bp.route('/admin/match_stats', endpoint='get_match_statistics', methods=['GET'])
@login_required
@role_required('Global Admin')
def get_match_statistics():
    """
    Retrieve match statistics.
    """
    stats = get_match_stats(g.db_session)
    return jsonify(stats)


@admin_bp.route('/admin/update_rsvp', methods=['POST'], endpoint='update_rsvp')
@csrf_exempt
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'Pub League Coach'])
def update_rsvp():
    """
    ENTERPRISE: Admin RSVP update endpoint using Enterprise RSVP v2 system
    
    Update a player's RSVP status for a match with enterprise reliability features.
    
    Expects:
    - player_id: ID of the player
    - match_id: ID of the match
    - response: The RSVP response ('yes', 'no', 'maybe', 'no_response')
    """
    from app.tasks.tasks_rsvp import notify_discord_of_rsvp_change_task, notify_frontend_of_rsvp_change_task
    from app.tasks.tasks_rsvp_ecs import update_ecs_fc_rsvp, notify_ecs_fc_discord_of_rsvp_change_task
    
    session = g.db_session
    player_id = request.form.get('player_id')
    match_id = request.form.get('match_id')
    response = request.form.get('response')
    
    if not player_id or not match_id or not response:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Missing required fields'}), 400
        show_error('Player ID, match ID, and response are required.')
        return redirect(url_for('admin.rsvp_status', match_id=match_id))
    
    # Check if this is an ECS FC match
    is_ecs_fc_match = isinstance(match_id, str) and match_id.startswith('ecs_')
    
    # Check if the player exists
    player = session.query(Player).get(player_id)
    
    if is_ecs_fc_match:
        # Handle ECS FC match
        actual_match_id = int(match_id[4:])  # Remove 'ecs_' prefix
        ecs_match = session.query(EcsFcMatch).get(actual_match_id)
        if not ecs_match:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': 'ECS FC match not found'}), 404
            show_error('ECS FC match not found.')
            return redirect(url_for('admin.rsvp_status', match_id=match_id))
        match = None
    else:
        # Handle regular match
        match = session.query(Match).get(match_id)
        if not match:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': 'Match not found'}), 404
            show_error('Match not found.')
            return redirect(url_for('admin.rsvp_status', match_id=match_id))
        ecs_match = None
    if not player:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Player not found'}), 404
        show_error('Player not found.')
        return redirect(url_for('admin.rsvp_status', match_id=match_id))
    
    # If clearing the response
    if response == 'no_response':
        try:
            if is_ecs_fc_match:
                # Handle ECS FC match
                availability = session.query(EcsFcAvailability).filter_by(
                    player_id=player_id, 
                    ecs_fc_match_id=actual_match_id
                ).first()
                
                if availability:
                    session.delete(availability)
                    session.commit()
                    logger.info(f"Admin {safe_current_user.id} cleared ECS FC RSVP for player {player_id}, match {actual_match_id}")
                    
                    # Notify Discord of the change for ECS FC
                    notify_ecs_fc_discord_of_rsvp_change_task.delay(match_id=actual_match_id)
                    
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        return jsonify({'success': True, 'message': 'ECS FC RSVP cleared successfully'})
                    show_success('ECS FC RSVP cleared successfully.')
                else:
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        return jsonify({'success': True, 'message': 'No ECS FC RSVP found to clear'})
                    show_info('No ECS FC RSVP found to clear.')
            else:
                # Handle regular match
                availability = session.query(Availability).filter_by(
                    player_id=player_id, 
                    match_id=match_id
                ).first()
                
                if availability:
                    session.delete(availability)
                    session.commit()
                    logger.info(f"Admin {safe_current_user.id} cleared RSVP for player {player_id}, match {match_id}")
                    
                    # Notify Discord and frontend of the change
                    notify_discord_of_rsvp_change_task.delay(match_id=match_id)
                    
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        return jsonify({'success': True, 'message': 'RSVP cleared successfully'})
                    show_success('RSVP cleared successfully.')
                else:
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        return jsonify({'success': True, 'message': 'No RSVP found to clear'})
                    show_info('No RSVP found to clear.')
        except Exception as e:
            logger.error(f"Error clearing RSVP: {str(e)}")
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': f'Error clearing RSVP: {str(e)}'})
            show_error(f'Error clearing RSVP: {str(e)}')
    else:
        try:
            if is_ecs_fc_match:
                # Handle ECS FC match
                availability = session.query(EcsFcAvailability).filter_by(
                    ecs_fc_match_id=actual_match_id,
                    player_id=player_id
                ).first()
                
                old_response = availability.response if availability else None
                
                if availability:
                    availability.response = response
                    availability.response_time = datetime.utcnow()
                else:
                    # Create new ECS FC availability record
                    availability = EcsFcAvailability(
                        ecs_fc_match_id=actual_match_id,
                        player_id=player_id,
                        response=response,
                        discord_id=player.discord_id,
                        user_id=player.user_id,
                        response_time=datetime.utcnow()
                    )
                    session.add(availability)
                
                session.commit()
                logger.info(f"Admin {safe_current_user.id} updated ECS FC RSVP for player {player_id}, match {actual_match_id} to {response}")
                
                # Use ECS FC specific task
                update_ecs_fc_rsvp.delay(
                    match_id=actual_match_id,
                    player_id=player_id,
                    new_response=response,
                    discord_id=player.discord_id,
                    user_id=player.user_id
                )
                
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'success': True, 'message': 'ECS FC RSVP updated successfully'})
                show_success('ECS FC RSVP updated successfully.')
            else:
                # Handle regular match
                availability = session.query(Availability).filter_by(
                    match_id=match_id,
                    player_id=player_id
                ).first()
                
                old_response = availability.response if availability else None
                
                if availability:
                    availability.response = response
                    availability.responded_at = datetime.utcnow()
                else:
                    # If discord_id is null but it's required, add a fallback value
                    discord_id = player.discord_id
                    if discord_id is None:
                        # Use a placeholder value if discord_id is required but not available
                        discord_id = "admin_added"
                    
                    availability = Availability(
                        match_id=match_id,
                        player_id=player_id,
                        response=response,
                        discord_id=discord_id,
                        responded_at=datetime.utcnow()
                    )
                    session.add(availability)
                
                session.commit()
                logger.info(f"Admin {safe_current_user.id} updated RSVP for player {player_id}, match {match_id} to {response}")
                
                # Notify Discord and frontend of the change
                notify_discord_of_rsvp_change_task.delay(match_id=match_id)
                notify_frontend_of_rsvp_change_task.delay(match_id=match_id, player_id=player_id, response=response)
                
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'success': True, 'message': 'RSVP updated successfully'})
                show_success('RSVP updated successfully.')
        except Exception as e:
            logger.error(f"Error updating RSVP: {str(e)}")
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': f'Error updating RSVP: {str(e)}'})
            show_error(f'Error updating RSVP: {str(e)}')
    
    return redirect(url_for('admin.rsvp_status', match_id=match_id))


# -----------------------------------------------------------
# Statistics Helper Functions
# -----------------------------------------------------------

def get_match_stats(session):
    """
    Generate comprehensive match statistics for admin reporting.
    
    Returns statistics about matches, RSVPs, verifications, and other metrics
    useful for administrative oversight and reporting.
    """
    try:
        from app.models import Match, Availability, Season
        from sqlalchemy import func, and_
        
        # Get current season
        current_season = session.query(Season).filter_by(is_current=True).first()
        if not current_season:
            return {"status": "no_season", "stats": []}
        
        # Calculate date ranges
        now = datetime.now()
        week_ago = now - timedelta(days=7)
        month_ago = now - timedelta(days=30)
        
        stats = {
            "status": "ok",
            "timestamp": now.isoformat(),
            "season": {
                "id": current_season.id,
                "name": current_season.name
            },
            "matches": {},
            "rsvps": {},
            "verification": {}
        }
        
        # Match statistics
        total_matches = session.query(Match).count()
        recent_matches = session.query(Match).filter(Match.date >= week_ago).count()
        upcoming_matches = session.query(Match).filter(Match.date >= now).count()
        
        stats["matches"] = {
            "total": total_matches,
            "recent_week": recent_matches,
            "upcoming": upcoming_matches
        }
        
        # RSVP statistics
        total_rsvps = session.query(Availability).count()
        recent_rsvps = session.query(Availability).filter(Availability.responded_at >= week_ago).count()
        
        # RSVP response breakdown
        rsvp_breakdown = session.query(
            Availability.response,
            func.count(Availability.id)
        ).group_by(Availability.response).all()
        
        stats["rsvps"] = {
            "total": total_rsvps,
            "recent_week": recent_rsvps,
            "breakdown": {response: count for response, count in rsvp_breakdown}
        }
        
        # Match verification statistics
        verified_matches = session.query(Match).filter(
            and_(Match.home_team_verified == True, Match.away_team_verified == True)
        ).count()
        
        partially_verified = session.query(Match).filter(
            and_(
                Match.reported == True,
                ~and_(Match.home_team_verified == True, Match.away_team_verified == True),
                (Match.home_team_verified == True) | (Match.away_team_verified == True)
            )
        ).count()
        
        stats["verification"] = {
            "fully_verified": verified_matches,
            "partially_verified": partially_verified
        }
        
        return stats
        
    except Exception as e:
        logger.error(f"Error generating match statistics: {str(e)}")
        return {
            "status": "error", 
            "message": f"Failed to generate statistics: {str(e)}",
            "timestamp": datetime.now().isoformat()
        }