# app/admin_panel/routes/match_operations/substitutes.py

"""
Substitute Management Routes

Routes for substitute management:
- Substitute management dashboard
- Assign substitute
"""

import logging
from datetime import datetime

from flask import render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user

from app.admin_panel import admin_panel_bp
from app.core import db
from app.models.admin_config import AdminAuditLog
from app.decorators import role_required

logger = logging.getLogger(__name__)


@admin_panel_bp.route('/substitute-management')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def substitute_management():
    """Substitute management dashboard."""
    try:
        from app.models import Match, Team, User
        from app.models.substitutes import SubstituteRequest, SubstituteAssignment

        # Log the access to substitute management
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='access_substitute_management',
            resource_type='match_operations',
            resource_id='substitute_management',
            new_value='Accessed substitute management dashboard',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        # Get filter parameters
        show_requested = request.args.get('show_requested', 'all')
        week_filter = request.args.get('week', type=int)

        # Get upcoming matches
        upcoming_matches_query = Match.query.filter(
            Match.date >= datetime.utcnow().date()
        ).order_by(Match.date.asc(), Match.time.asc())

        if week_filter:
            # Filter by week if implemented
            pass

        upcoming_matches = upcoming_matches_query.limit(20).all()

        # Get substitute requests
        sub_requests_query = SubstituteRequest.query.filter(
            SubstituteRequest.status.in_(['PENDING', 'APPROVED'])
        ).order_by(SubstituteRequest.created_at.desc())

        if show_requested == 'requested':
            # Filter logic for matches with requests
            pass

        sub_requests = sub_requests_query.limit(50).all()

        # Get available substitutes (users who can sub)
        available_subs = User.query.filter_by(
            is_active=True,
            is_approved=True
        ).limit(100).all()

        # Calculate statistics
        stats = {
            'total_requests': SubstituteRequest.query.count(),
            'active_requests': SubstituteRequest.query.filter(
                SubstituteRequest.status.in_(['PENDING', 'APPROVED'])
            ).count(),
            'available_subs': len(available_subs),
            'upcoming_matches': len(upcoming_matches)
        }

        # Group requests by match for easier template processing
        requested_teams_by_match = {}
        for sub_request in sub_requests:
            match_id = sub_request.match_id
            if match_id not in requested_teams_by_match:
                requested_teams_by_match[match_id] = {}
            requested_teams_by_match[match_id][sub_request.team_id] = sub_request

        # Get available weeks (placeholder)
        weeks = list(range(1, 21))  # Assuming 20 weeks in a season
        current_week = week_filter or 1

        return render_template(
            'admin_panel/substitute_management_flowbite.html',
            stats=stats,
            sub_requests=sub_requests,
            upcoming_matches=upcoming_matches,
            available_subs=available_subs,
            requested_teams_by_match=requested_teams_by_match,
            weeks=weeks,
            current_week=current_week,
            show_requested=show_requested
        )
    except Exception as e:
        logger.error(f"Error loading substitute management: {e}")
        flash('Substitute management unavailable. Verify database connection and substitute models.', 'error')
        return redirect(url_for('admin_panel.match_operations'))


@admin_panel_bp.route('/assign-substitute', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def assign_substitute():
    """Assign a substitute to a match."""
    try:
        from app.models.substitutes import SubstituteAssignment, SubstituteRequest, SubstituteResponse
        from app.utils.substitute_helpers import create_temp_sub_assignment
        from app.services.substitute_notification_service import get_notification_service

        match_id = request.form.get('match_id', type=int)
        team_id = request.form.get('team_id', type=int)
        player_id = request.form.get('player_id', type=int)
        request_id = request.form.get('request_id', type=int)
        position_assigned = request.form.get('position_assigned')
        notes = request.form.get('notes')
        send_confirmation = request.form.get('send_confirmation', 'true').lower() == 'true'

        if not all([match_id, team_id, player_id]):
            flash('Missing required information for substitute assignment.', 'error')
            return redirect(url_for('admin_panel.substitute_management'))

        # Get the outreach methods from the response if available
        outreach_methods = None
        if request_id:
            response = db.session.query(SubstituteResponse).filter_by(
                request_id=request_id,
                player_id=player_id
            ).first()
            if response and response.notification_methods:
                outreach_methods = response.notification_methods

        # Create substitute assignment
        assignment = SubstituteAssignment(
            request_id=request_id,
            player_id=player_id,
            assigned_by=current_user.id,
            assigned_at=datetime.utcnow(),
            position_assigned=position_assigned,
            notes=notes,
            outreach_methods=outreach_methods
        )

        db.session.add(assignment)
        db.session.flush()  # Get the assignment ID

        # Create TemporarySubAssignment for stat attribution
        temp_assignment = create_temp_sub_assignment(
            match_id=match_id,
            player_id=player_id,
            team_id=team_id,
            assigned_by=current_user.id,
            request_id=request_id,
            assignment_id=assignment.id,
            notes=notes,
            session=db.session
        )

        # Update the substitute request status if all spots filled
        if request_id:
            sub_request = db.session.query(SubstituteRequest).get(request_id)
            if sub_request:
                assignments_count = len(sub_request.assignments)
                if assignments_count >= sub_request.substitutes_needed:
                    sub_request.status = 'FILLED'
                    sub_request.filled_at = datetime.utcnow()

        db.session.commit()

        # Send confirmation notification if requested
        if send_confirmation:
            notification_service = get_notification_service()
            notification_service.send_confirmation(assignment.id)

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='assign_substitute',
            resource_type='match_operations',
            resource_id=f'match_{match_id}_team_{team_id}',
            new_value=f'Assigned player {player_id} as substitute',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        flash('Substitute assigned successfully!', 'success')
        return redirect(url_for('admin_panel.substitute_management'))

    except Exception as e:
        logger.error(f"Error assigning substitute: {e}")
        db.session.rollback()
        flash('Substitute assignment failed. Check database connectivity and input validation.', 'error')
        return redirect(url_for('admin_panel.substitute_management'))
