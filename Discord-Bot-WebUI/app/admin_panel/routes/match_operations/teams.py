# app/admin_panel/routes/match_operations/teams.py

"""
Team Management Routes

Routes for team management:
- Manage teams
- Team rosters
"""

import logging

from flask import render_template, request, flash, redirect, url_for
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
