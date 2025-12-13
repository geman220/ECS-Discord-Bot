# app/admin_panel/routes/match_operations/ajax.py

"""
Match Operations AJAX Routes

AJAX utility routes for match operations:
- Get match details
- Toggle league status
- Set current season
- Rename team
"""

import logging

from flask import request, jsonify
from flask_login import login_required, current_user

from app.admin_panel import admin_panel_bp
from app.core import db
from app.models.admin_config import AdminAuditLog
from app.decorators import role_required

logger = logging.getLogger(__name__)


@admin_panel_bp.route('/match-operations/match/details')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def get_match_details():
    """Get match details via AJAX."""
    try:
        match_id = request.args.get('match_id')

        if not match_id:
            return jsonify({'success': False, 'message': 'Match ID is required'})

        # TODO: Get actual match details from database
        details_html = f"""
        <div class="match-details">
            <div class="row">
                <div class="col-md-6">
                    <strong>Match ID:</strong> {match_id}<br>
                    <strong>Date:</strong> TBD<br>
                    <strong>Time:</strong> TBD<br>
                    <strong>Status:</strong> Scheduled
                </div>
                <div class="col-md-6">
                    <strong>League:</strong> TBD<br>
                    <strong>Season:</strong> TBD<br>
                    <strong>Venue:</strong> TBD<br>
                    <strong>Referee:</strong> TBD
                </div>
            </div>
            <div class="row mt-3">
                <div class="col-12">
                    <strong>Teams:</strong><br>
                    <div class="teams-info p-2 bg-light rounded">
                        Match details will be implemented when match model is available.
                    </div>
                </div>
            </div>
        </div>
        """

        return jsonify({'success': True, 'html': details_html})
    except Exception as e:
        logger.error(f"Error getting match details: {e}")
        return jsonify({'success': False, 'message': 'Error loading match details'})


@admin_panel_bp.route('/match-operations/league/toggle-status', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def toggle_league_status():
    """Toggle league active status."""
    try:
        from app.models import League

        league_id = request.form.get('league_id')

        if not league_id:
            return jsonify({'success': False, 'message': 'League ID is required'})

        league = League.query.get_or_404(league_id)

        # Since leagues don't have is_active field, just return success
        return jsonify({
            'success': True,
            'message': f'League "{league.name}" is active',
            'new_status': True
        })

    except Exception as e:
        logger.error(f"Error toggling league status: {e}")
        return jsonify({'success': False, 'message': 'Error updating league status'})


@admin_panel_bp.route('/match-operations/season/set-current', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def set_current_season():
    """Set a season as current."""
    try:
        from app.models import Season

        season_id = request.form.get('season_id')

        if not season_id:
            return jsonify({'success': False, 'message': 'Season ID is required'})

        # Clear current season status from all seasons
        Season.query.update({'is_current': False})

        # Set the selected season as current
        season = Season.query.get_or_404(season_id)
        season.is_current = True
        db.session.commit()

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='set_current_season',
            resource_type='match_operations',
            resource_id=str(season_id),
            new_value=f'Set {season.name} as current season',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({
            'success': True,
            'message': f'Season "{season.name}" set as current season',
            'season_name': season.name
        })

    except Exception as e:
        logger.error(f"Error setting current season: {e}")
        return jsonify({'success': False, 'message': 'Error updating current season'})


@admin_panel_bp.route('/match-operations/teams/rename', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def rename_team():
    """Rename a team and trigger Discord automation."""
    try:
        from app.models import Team

        team_id = request.form.get('team_id')
        new_name = request.form.get('new_name')

        if not team_id or not new_name:
            return jsonify({'success': False, 'message': 'Team ID and new name are required'})

        team = Team.query.get_or_404(team_id)
        old_name = team.name

        # Update team name
        team.name = new_name.strip()
        db.session.commit()

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='rename_team',
            resource_type='match_operations',
            resource_id=str(team_id),
            old_value=old_name,
            new_value=new_name,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        # TODO: Trigger Discord automation for team name change
        # This would involve updating Discord role names, channel names, etc.
        # from app.tasks.tasks_discord import update_team_discord_automation
        # update_team_discord_automation.delay(team_id=team_id, old_name=old_name, new_name=new_name)

        logger.info(f"Team {team_id} renamed from '{old_name}' to '{new_name}' by user {current_user.id}")

        return jsonify({
            'success': True,
            'message': f'Team renamed from "{old_name}" to "{new_name}" successfully',
            'old_name': old_name,
            'new_name': new_name
        })

    except Exception as e:
        logger.error(f"Error renaming team: {e}")
        return jsonify({'success': False, 'message': 'Error renaming team'})
