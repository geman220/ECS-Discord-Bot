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
            'admin_panel/substitute_management.html',
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
        from app.models.substitutes import SubstituteAssignment

        match_id = request.form.get('match_id')
        team_id = request.form.get('team_id')
        player_id = request.form.get('player_id')

        if not all([match_id, team_id, player_id]):
            flash('Missing required information for substitute assignment.', 'error')
            return redirect(url_for('admin_panel.substitute_management'))

        # Create substitute assignment
        assignment = SubstituteAssignment(
            match_id=match_id,
            team_id=team_id,
            player_id=player_id,
            assigned_by=current_user.id,
            assigned_at=datetime.utcnow(),
            status='ASSIGNED'
        )

        db.session.add(assignment)
        db.session.commit()

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
        flash('Substitute assignment failed. Check database connectivity and input validation.', 'error')
        return redirect(url_for('admin_panel.substitute_management'))
