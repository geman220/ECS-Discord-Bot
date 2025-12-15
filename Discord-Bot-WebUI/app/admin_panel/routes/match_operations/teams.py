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
from sqlalchemy.orm import joinedload

from app.admin_panel import admin_panel_bp
from app.core import db
from app.models.admin_config import AdminAuditLog
from app.decorators import role_required

logger = logging.getLogger(__name__)


@admin_panel_bp.route('/match-operations/teams')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def manage_teams():
    """Manage teams across all Pub League divisions (Premier, Classic, ECS FC)."""
    try:
        from app.models import Team, League, Player, Season

        # Get current Pub League season
        current_season = Season.query.filter_by(is_current=True, league_type="Pub League").first()
        if not current_season:
            # Fallback to any current season
            current_season = Season.query.filter_by(is_current=True).first()

        # Get filter parameters
        league_filter = request.args.get('league_id', type=int)

        # Get all leagues for the current season (Premier, Classic, ECS FC)
        if current_season:
            leagues = League.query.filter_by(season_id=current_season.id).order_by(League.name.asc()).all()
        else:
            leagues = League.query.order_by(League.name.asc()).all()

        # Build teams query - show ALL teams from all leagues in the current season
        if current_season:
            teams_query = Team.query.join(
                League, Team.league_id == League.id
            ).filter(
                League.season_id == current_season.id
            )
        else:
            teams_query = Team.query

        # Apply league filter if specified
        if league_filter:
            teams_query = teams_query.filter(Team.league_id == league_filter)

        teams = teams_query.order_by(Team.name.asc()).all()

        # Get team statistics
        stats = {
            'total_teams': len(teams),
            'active_teams': len([t for t in teams if getattr(t, 'is_active', True)]),
            'teams_by_league': {},
            'teams_with_players': 0,
            'current_season': current_season.name if current_season else 'All Seasons'
        }

        # Group teams by league
        for team in teams:
            league_name = team.league.name if team.league else 'No League'
            if league_name not in stats['teams_by_league']:
                stats['teams_by_league'][league_name] = 0
            stats['teams_by_league'][league_name] += 1

            # Count teams that have players (if player-team relationship exists)
            if hasattr(team, 'players') and team.players:
                stats['teams_with_players'] += 1

        return render_template(
            'admin_panel/match_operations/manage_teams.html',
            teams=teams,
            leagues=leagues,
            stats=stats,
            current_league_id=league_filter,
            current_season=current_season
        )
    except Exception as e:
        logger.error(f"Error loading manage teams: {e}")
        flash('Team management unavailable. Check database connectivity and team data.', 'error')
        return redirect(url_for('admin_panel.match_operations'))


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
        current_season = Season.query.filter_by(is_current=True).first()

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
            'admin_panel/match_operations/team_rosters.html',
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
def create_team():
    """Create a new team."""
    try:
        from app.models import Team, League

        name = request.form.get('name')
        league_id = request.form.get('league_id')

        if not name:
            return jsonify({'success': False, 'message': 'Team name is required'}), 400

        # Check if league exists
        if league_id:
            league = League.query.get(league_id)
            if not league:
                return jsonify({'success': False, 'message': 'Selected league not found'}), 400

        # Create new team
        team = Team(
            name=name,
            league_id=int(league_id) if league_id else None
        )
        db.session.add(team)
        db.session.commit()

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
        return jsonify({
            'success': True,
            'message': f'Team "{name}" created successfully',
            'team_id': team.id
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating team: {e}")
        return jsonify({'success': False, 'message': 'Failed to create team'}), 500


@admin_panel_bp.route('/match-operations/teams/<int:team_id>/update', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def update_team(team_id):
    """Update an existing team."""
    try:
        from app.models import Team, League

        team = Team.query.get_or_404(team_id)
        old_name = team.name

        name = request.form.get('name')
        league_id = request.form.get('league_id')

        if not name:
            return jsonify({'success': False, 'message': 'Team name is required'}), 400

        # Update team
        team.name = name
        if league_id:
            team.league_id = int(league_id)

        db.session.commit()

        # Trigger Discord automation for team name change if name changed
        if old_name != name:
            try:
                from app.tasks.tasks_discord import update_team_discord_resources_task
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

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating team {team_id}: {e}")
        return jsonify({'success': False, 'message': 'Failed to update team'}), 500


@admin_panel_bp.route('/match-operations/teams/<int:team_id>/delete', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def delete_team(team_id):
    """Delete a team."""
    try:
        from app.models import Team, Player, Match

        team = Team.query.get_or_404(team_id)

        # Check if team has players
        player_count = len(team.players) if hasattr(team, 'players') else 0
        if player_count > 0:
            return jsonify({
                'success': False,
                'message': f'Cannot delete team with {player_count} players. Remove players first.'
            }), 400

        # Check if team has matches
        match_count = Match.query.filter(
            (Match.home_team_id == team_id) | (Match.away_team_id == team_id)
        ).count()
        if match_count > 0:
            return jsonify({
                'success': False,
                'message': f'Cannot delete team with {match_count} matches. Delete or reassign matches first.'
            }), 400

        team_name = team.name

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
        db.session.commit()

        logger.info(f"Team '{team_name}' deleted by user {current_user.id}")
        return jsonify({
            'success': True,
            'message': f'Team "{team_name}" deleted successfully'
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting team {team_id}: {e}")
        return jsonify({'success': False, 'message': 'Failed to delete team'}), 500


@admin_panel_bp.route('/match-operations/teams/<int:team_id>/details')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def get_team_details(team_id):
    """Get team details for editing modal."""
    try:
        from app.models import Team

        team = Team.query.get_or_404(team_id)

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
