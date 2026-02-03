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
from sqlalchemy.orm import joinedload

from app.admin_panel import admin_panel_bp
from app.core import db
from app.models.admin_config import AdminAuditLog
from app.models.matches import Match
from app.decorators import role_required
from app.utils.db_utils import transactional

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

        # Query match with related data using eager loading to avoid N+1
        match = Match.query.options(
            joinedload(Match.home_team),
            joinedload(Match.away_team),
            joinedload(Match.ref),
            joinedload(Match.schedule)
        ).get(match_id)

        if not match:
            return jsonify({'success': False, 'message': 'Match not found'})

        # Get league and season info from schedule relationship
        league_name = 'N/A'
        season_name = 'N/A'
        if match.schedule and match.schedule.season:
            season_name = match.schedule.season.name
            # Get league from team relationship
            if match.home_team and match.home_team.league:
                league_name = match.home_team.league.name

        # Format date and time
        date_str = match.date.strftime('%B %d, %Y') if match.date else 'Not scheduled'
        time_str = match.time.strftime('%I:%M %p') if match.time else 'Not scheduled'

        # Get match status
        if match.fully_verified:
            status = 'Verified'
            status_class = 'text-success'
        elif match.reported:
            status = 'Reported (Pending Verification)'
            status_class = 'text-warning'
        else:
            status = 'Scheduled'
            status_class = 'text-info'

        # Get referee name
        ref_name = match.ref.name if match.ref else 'Not assigned'

        # Get scores if reported
        score_html = ''
        if match.reported:
            score_html = f"""
            <div class="row mt-3">
                <div class="col-12">
                    <strong>Score:</strong>
                    <div class="score-info p-2 bg-light rounded">
                        {match.home_team.name}: {match.home_team_score} -
                        {match.away_team.name}: {match.away_team_score}
                    </div>
                </div>
            </div>
            """

        details_html = f"""
        <div class="match-details">
            <div class="row">
                <div class="col-md-6">
                    <strong>Match ID:</strong> {match.id}<br>
                    <strong>Date:</strong> {date_str}<br>
                    <strong>Time:</strong> {time_str}<br>
                    <strong>Status:</strong> <span class="{status_class}">{status}</span>
                </div>
                <div class="col-md-6">
                    <strong>League:</strong> {league_name}<br>
                    <strong>Season:</strong> {season_name}<br>
                    <strong>Venue:</strong> {match.location or 'Not specified'}<br>
                    <strong>Referee:</strong> {ref_name}
                </div>
            </div>
            <div class="row mt-3">
                <div class="col-12">
                    <strong>Teams:</strong><br>
                    <div class="teams-info p-2 bg-light rounded">
                        <strong>Home:</strong> {match.home_team.name if match.home_team else 'Unknown'}<br>
                        <strong>Away:</strong> {match.away_team.name if match.away_team else 'Unknown'}
                    </div>
                </div>
            </div>
            {score_html}
            {f'<div class="row mt-2"><div class="col-12"><small class="text-muted">Week Type: {match.week_type}</small></div></div>' if match.week_type != 'REGULAR' else ''}
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
@transactional
def set_current_season():
    """
    Set a season as current.

    When switching to a season, automatically restores player-team memberships
    from PlayerTeamSeason history so players are on their correct teams for that season.
    """
    from app.models import Season
    from app.season_routes import restore_season_memberships

    season_id = request.form.get('season_id')

    if not season_id:
        return jsonify({'success': False, 'message': 'Season ID is required'})

    # Clear current season status from all seasons
    Season.query.update({'is_current': False})

    # Set the selected season as current
    season = Season.query.get_or_404(season_id)
    season.is_current = True

    # Restore player-team memberships from PlayerTeamSeason history
    # This ensures players are on their correct teams when switching between seasons
    restore_result = {'restored': 0, 'message': 'No restoration needed'}
    try:
        restore_result = restore_season_memberships(db.session, season)
        logger.info(f"Season membership restoration: {restore_result}")
    except Exception as e:
        logger.error(f"Failed to restore season memberships: {e}")
        restore_result = {'restored': 0, 'message': f'Restoration failed: {str(e)}'}

    # Log the action
    AdminAuditLog.log_action(
        user_id=current_user.id,
        action='set_current_season',
        resource_type='match_operations',
        resource_id=str(season_id),
        new_value=f'Set {season.name} as current season (restored {restore_result.get("restored", 0)} team assignments)',
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent')
    )

    return jsonify({
        'success': True,
        'message': f'Season "{season.name}" set as current season',
        'season_name': season.name,
        'restoration': restore_result
    })


@admin_panel_bp.route('/match-operations/teams/rename', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def rename_team():
    """Rename a team and trigger Discord automation."""
    from app.models import Team

    team_id = request.form.get('team_id')
    new_name = request.form.get('new_name')

    if not team_id or not new_name:
        return jsonify({'success': False, 'message': 'Team ID and new name are required'})

    team = Team.query.get_or_404(team_id)
    old_name = team.name

    # Update team name
    team.name = new_name.strip()

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

    # Trigger Discord automation for team name change
    # Updates Discord role names, channel names, etc.
    try:
        from app.tasks.tasks_discord import update_team_discord_resources_task
        update_team_discord_resources_task.delay(team_id=int(team_id), new_team_name=new_name)
        logger.info(f"Discord automation task queued for team {team_id} rename")
    except Exception as discord_err:
        logger.warning(f"Could not queue Discord automation task: {discord_err}")
        # Don't fail the rename if Discord task fails to queue

    logger.info(f"Team {team_id} renamed from '{old_name}' to '{new_name}' by user {current_user.id}")

    return jsonify({
        'success': True,
        'message': f'Team renamed from "{old_name}" to "{new_name}" successfully',
        'old_name': old_name,
        'new_name': new_name
    })
