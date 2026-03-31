# app/admin_panel/routes/match_operations/teams.py

"""
Team Management Routes

Routes for team management:
- Manage teams
- Team rosters
"""

import logging

from flask import render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user
from sqlalchemy import func
from sqlalchemy.orm import joinedload, selectinload

from app.admin_panel import admin_panel_bp
from app.core import db
from app.models.admin_config import AdminAuditLog
from app.decorators import role_required

logger = logging.getLogger(__name__)


@admin_panel_bp.route('/match-operations/teams')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def manage_teams():
    """Redirect to canonical teams management in league_management."""
    return redirect(url_for('admin_panel.league_management_teams', **request.args), code=302)


@admin_panel_bp.route('/match-operations/rosters')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def team_rosters():
    """Manage team rosters."""
    try:
        from app.models import Team, Player, Season, League

        # Log the access to team rosters
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='access_team_rosters',
            resource_type='match_operations',
            resource_id='rosters',
            new_value='Accessed team rosters interface',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        # Get current season
        current_season = db.session.query(Season).filter_by(is_current=True).first()

        # Filter teams by current season
        if current_season:
            teams_with_rosters = db.session.query(Team).join(
                League, Team.league_id == League.id, isouter=True
            ).filter(
                League.season_id == current_season.id
            ).join(
                Team.players, isouter=True
            ).options(joinedload(Team.players)).all()
        else:
            teams_with_rosters = db.session.query(Team).join(
                Team.players, isouter=True
            ).options(joinedload(Team.players)).all()

        # Get teams without players
        teams_without_players = [team for team in teams_with_rosters if not team.players]

        # Get roster statistics
        total_players = db.session.query(func.count(Player.id)).scalar()
        players_assigned = db.session.query(func.count(Player.id)).filter(
            Player.teams.any()
        ).scalar()

        roster_stats = {
            'total_teams': len(teams_with_rosters),
            'teams_with_players': len([t for t in teams_with_rosters if t.players]),
            'teams_without_players': len(teams_without_players),
            'total_players': total_players,
            'assigned_players': players_assigned,
            'unassigned_players': total_players - players_assigned,
            'current_season': current_season.name if current_season else 'All Seasons'
        }

        return render_template(
            'admin_panel/match_operations/team_rosters_flowbite.html',
            teams=teams_with_rosters,
            teams_without_players=teams_without_players[:10],  # Show first 10
            stats=roster_stats
        )
    except Exception as e:
        logger.error(f"Error loading team rosters: {e}")
        flash('Team rosters unavailable. Verify database connection and player-team relationships.', 'error')
        return redirect(url_for('admin_panel.match_operations'))


@admin_panel_bp.route('/match-operations/teams/create', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def create_team():
    """Create a new team."""
    from app.models import Team, League

    name = request.form.get('name')
    league_id = request.form.get('league_id')

    if not name:
        return jsonify({'success': False, 'message': 'Team name is required'}), 400

    # Check if league exists
    if league_id:
        league = db.session.query(League).get(league_id)
        if not league:
            return jsonify({'success': False, 'message': 'Selected league not found'}), 400

    # Create new team
    team = Team(
        name=name,
        league_id=int(league_id) if league_id else None
    )
    db.session.add(team)
    db.session.flush()

    # Trigger Discord channel/role creation if team has a league
    discord_task_queued = False
    if league_id and create_team_discord_resources_task:
        try:
            create_team_discord_resources_task.delay(team_id=team.id)
            discord_task_queued = True
            logger.info(f"Discord resource creation task queued for team {team.id}")
        except Exception as discord_err:
            logger.warning(f"Could not queue Discord resource creation task: {discord_err}")

    # Log the action
    AdminAuditLog.log_action(
        user_id=current_user.id,
        action='create_team',
        resource_type='team',
        resource_id=str(team.id),
        new_value=f'Created team: {name}',
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent')
    )

    logger.info(f"Team '{name}' created by user {current_user.id}")

    message = f'Team "{name}" created successfully'
    if discord_task_queued:
        message += '. Discord channel creation in progress.'

    return jsonify({
        'success': True,
        'message': message,
        'team_id': team.id
    })


@admin_panel_bp.route('/match-operations/teams/<int:team_id>/update', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def update_team(team_id):
    """Update an existing team."""
    from app.models import Team, League

    team = db.session.query(Team).get_or_404(team_id)
    old_name = team.name

    name = request.form.get('name')
    league_id = request.form.get('league_id')

    if not name:
        return jsonify({'success': False, 'message': 'Team name is required'}), 400

    # Update team
    team.name = name
    if league_id:
        team.league_id = int(league_id)

    # Trigger Discord automation for team name change if name changed
    if old_name != name and update_team_discord_resources_task:
        try:
            update_team_discord_resources_task.delay(team_id=team_id, new_team_name=name)
            logger.info(f"Discord automation task queued for team {team_id} rename")
        except Exception as discord_err:
            logger.warning(f"Could not queue Discord automation task: {discord_err}")

    # Log the action
    AdminAuditLog.log_action(
        user_id=current_user.id,
        action='update_team',
        resource_type='team',
        resource_id=str(team_id),
        old_value=old_name,
        new_value=name,
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent')
    )

    logger.info(f"Team '{name}' updated by user {current_user.id}")
    return jsonify({
        'success': True,
        'message': f'Team "{name}" updated successfully'
    })


@admin_panel_bp.route('/match-operations/teams/<int:team_id>/delete', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def delete_team(team_id):
    """Delete a team."""
    from app.models import Team, Player, Match

    team = db.session.query(Team).get_or_404(team_id)

    # Check if team has players
    player_count = len(team.players) if hasattr(team, 'players') else 0
    if player_count > 0:
        return jsonify({
            'success': False,
            'message': f'Cannot delete team with {player_count} players. Remove players first.'
        }), 400

    # Check if team has matches
    match_count = db.session.query(Match).filter(
        (Match.home_team_id == team_id) | (Match.away_team_id == team_id)
    ).count()
    if match_count > 0:
        return jsonify({
            'success': False,
            'message': f'Cannot delete team with {match_count} matches. Delete or reassign matches first.'
        }), 400

    team_name = team.name
    # Store Discord IDs before deletion for cleanup
    discord_channel_id = team.discord_channel_id
    discord_player_role_id = team.discord_player_role_id
    discord_coach_role_id = team.discord_coach_role_id

    # Log the action before deletion
    AdminAuditLog.log_action(
        user_id=current_user.id,
        action='delete_team',
        resource_type='team',
        resource_id=str(team_id),
        old_value=team_name,
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent')
    )

    db.session.delete(team)

    # Queue Discord cleanup AFTER deleting the team (pass IDs directly)
    if discord_channel_id or discord_player_role_id or discord_coach_role_id:
        try:
            from app.tasks.tasks_discord import delete_discord_resources_by_ids_task
            delete_discord_resources_by_ids_task.delay(
                channel_id=discord_channel_id,
                player_role_id=discord_player_role_id,
                coach_role_id=discord_coach_role_id
            )
            logger.info(f"Discord cleanup task queued for deleted team {team_id}")
        except Exception as discord_err:
            # If the specific task doesn't exist, log and continue
            # Discord resources can be cleaned up manually if needed
            logger.warning(f"Could not queue Discord cleanup task: {discord_err}")

    logger.info(f"Team '{team_name}' deleted by user {current_user.id}")
    return jsonify({
        'success': True,
        'message': f'Team "{team_name}" deleted successfully'
    })


@admin_panel_bp.route('/match-operations/teams/<int:team_id>/details')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def get_team_details(team_id):
    """Get team details for editing modal."""
    try:
        from app.models import Team

        team = db.session.query(Team).get_or_404(team_id)

        return jsonify({
            'success': True,
            'team': {
                'id': team.id,
                'name': team.name,
                'league_id': team.league_id,
                'league_name': team.league.name if team.league else None,
                'player_count': len(team.players) if hasattr(team, 'players') else 0
            }
        })

    except Exception as e:
        logger.error(f"Error getting team details: {e}")
        return jsonify({'success': False, 'message': 'Failed to get team details'}), 500
