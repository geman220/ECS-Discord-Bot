# app/admin_panel/routes/match_operations/transfers.py

"""
Player Transfer Routes

Routes for player transfer management.
"""

import logging

from flask import render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user

from app.admin_panel import admin_panel_bp
from app.models.admin_config import AdminAuditLog
from app.decorators import role_required

logger = logging.getLogger(__name__)


@admin_panel_bp.route('/match-operations/transfers')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def player_transfers():
    """Manage player transfers."""
    try:
        from app.models import User, Team, Season, Player, League

        # Log the access to player transfers
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='access_player_transfers',
            resource_type='match_operations',
            resource_id='transfers',
            new_value='Accessed player transfers interface',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        # Get current season
        current_season = Season.query.filter_by(is_current=True).first()

        if not current_season:
            flash('No active season found. Please create a season first.', 'warning')
            return redirect(url_for('admin_panel.match_operations'))

        # Get recent transfers (placeholder - would need a transfers table)
        recent_transfers = []

        # Get available players (not currently on a team or available for transfer)
        available_players = User.query.filter_by(is_active=True).all()  # Simplified

        # Get all teams for transfer destinations
        teams = Team.query.join(League).filter(League.season_id == current_season.id).all() if current_season else Team.query.all()

        # Get pending transfer requests (placeholder)
        pending_requests = []

        transfers_data = {
            'current_season': current_season,
            'recent_transfers': recent_transfers,
            'available_players': available_players[:50],  # Limit for performance
            'teams': teams,
            'pending_requests': pending_requests,
            'total_transfers': len(recent_transfers),
            'pending_count': len(pending_requests)
        }

        return render_template('admin_panel/match_operations/player_transfers.html',
                               transfers_data=transfers_data)
    except Exception as e:
        logger.error(f"Error loading player transfers: {e}")
        flash('Player transfers unavailable. Check database connectivity and transfer data.', 'error')
        return redirect(url_for('admin_panel.match_operations'))
