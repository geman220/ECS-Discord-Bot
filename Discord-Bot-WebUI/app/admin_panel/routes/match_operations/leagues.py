# app/admin_panel/routes/match_operations/leagues.py

"""
League Management Routes

Routes for league management:
- Manage leagues
- League standings
"""

import logging
from datetime import datetime

from flask import render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user

from app.admin_panel import admin_panel_bp
from app.models.admin_config import AdminAuditLog
from app.decorators import role_required

logger = logging.getLogger(__name__)


@admin_panel_bp.route('/match-operations/leagues')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def manage_leagues():
    """Manage leagues."""
    try:
        from app.models import League, Team, Match, Season

        # Get all leagues
        leagues = League.query.order_by(League.name.asc()).all()

        # Get league statistics
        stats = {
            'total_leagues': len(leagues),
            'active_leagues': len(leagues),
            'leagues_with_teams': 0,
            'leagues_with_matches': 0
        }

        # Add details for each league
        for league in leagues:
            # Get team count
            league.team_count = Team.query.filter_by(league_id=league.id).count() if hasattr(Team, 'league_id') else 0

            # Get match count (if matches have league relationship)
            if hasattr(Match, 'league_id'):
                league.match_count = Match.query.filter_by(league_id=league.id).count()
            else:
                # Fallback: count matches through teams
                league_teams = Team.query.filter_by(league_id=league.id).all() if hasattr(Team, 'league_id') else []
                league.match_count = 0
                for team in league_teams:
                    league.match_count += Match.query.filter(
                        (Match.home_team_id == team.id) | (Match.away_team_id == team.id)
                    ).count()

            # Update statistics
            if league.team_count > 0:
                stats['leagues_with_teams'] += 1
            if league.match_count > 0:
                stats['leagues_with_matches'] += 1

            # Set league status (all leagues are considered active)
            league.status = 'active'

        return render_template('admin_panel/match_operations/manage_leagues.html',
                               leagues=leagues, stats=stats)
    except Exception as e:
        logger.error(f"Error loading manage leagues: {e}")
        flash('League management unavailable. Verify database connection and league data.', 'error')
        return redirect(url_for('admin_panel.match_operations'))


@admin_panel_bp.route('/match-operations/standings')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def league_standings():
    """View league standings."""
    try:
        from app.models import Team, Season, League
        from app.models.matches import Match

        # Log the access to league standings
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='access_league_standings',
            resource_type='match_operations',
            resource_id='standings',
            new_value='Accessed league standings interface',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        # Get current season
        current_season = Season.query.filter_by(is_current=True).first()

        if not current_season:
            flash('No active season found. Please create a season first.', 'warning')
            return redirect(url_for('admin_panel.match_operations'))

        # Get all teams in current season
        teams = Team.query.join(League).filter(League.season_id == current_season.id).all() if current_season else Team.query.all()

        # Calculate standings for each team
        standings = []
        for team in teams:
            # Get team's matches (both home and away)
            home_matches = Match.query.filter_by(home_team_id=team.id).all()
            away_matches = Match.query.filter_by(away_team_id=team.id).all() if hasattr(Match, 'away_team_id') else []

            wins = losses = draws = goals_for = goals_against = 0
            matches_played = len(home_matches) + len(away_matches)

            # Calculate stats (this would need actual match results)
            # For now, using placeholder calculations
            wins = matches_played // 3 if matches_played > 0 else 0
            draws = matches_played // 3 if matches_played > 0 else 0
            losses = matches_played - wins - draws
            goals_for = wins * 2 + draws
            goals_against = losses * 2 + draws

            points = wins * 3 + draws
            goal_difference = goals_for - goals_against

            standings.append({
                'team': team,
                'matches_played': matches_played,
                'wins': wins,
                'draws': draws,
                'losses': losses,
                'goals_for': goals_for,
                'goals_against': goals_against,
                'goal_difference': goal_difference,
                'points': points
            })

        # Sort by points, then goal difference
        standings.sort(key=lambda x: (x['points'], x['goal_difference']), reverse=True)

        # Add position
        for i, standing in enumerate(standings, 1):
            standing['position'] = i

        standings_data = {
            'current_season': current_season,
            'standings': standings,
            'total_teams': len(teams)
        }

        return render_template('admin_panel/match_operations/league_standings.html',
                               standings_data=standings_data)
    except Exception as e:
        logger.error(f"Error loading league standings: {e}")
        flash('League standings unavailable. Check database connectivity and season data.', 'error')
        return redirect(url_for('admin_panel.match_operations'))
