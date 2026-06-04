# app/admin_panel/routes/match_operations/leagues.py

"""
League Management Routes

Routes for league management:
- Manage leagues
- League standings
"""

import logging
from datetime import datetime

from flask import render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user

from app.admin_panel import admin_panel_bp
from app.core import db
from app.models.admin_config import AdminAuditLog
from app.decorators import role_required
from app.utils.db_utils import transactional

logger = logging.getLogger(__name__)


@admin_panel_bp.route('/match-operations/leagues')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def manage_leagues():
    """Manage leagues."""
    try:
        from app.models import League, Team, Match, Season
        from app.models.stats import Standings

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

            # Per-league top-3 standings snapshot. Standings are keyed by team+season,
            # so join through this league's teams filtered to the league's season,
            # ordered by points (then goal difference) desc, limited to 3.
            league.top_standings = []
            if league.team_count > 0:
                top = (
                    Standings.query
                    .join(Team, Standings.team_id == Team.id)
                    .filter(
                        Team.league_id == league.id,
                        Standings.season_id == league.season_id,
                    )
                    .order_by(
                        Standings.points.desc(),
                        Standings.goal_difference.desc(),
                    )
                    .limit(3)
                    .all()
                )
                league.top_standings = [
                    {
                        'team_name': s.team.name if s.team else 'Unknown',
                        'played': s.played or 0,
                        'points': s.points or 0,
                    }
                    for s in top
                ]

        return render_template('admin_panel/match_operations/manage_leagues_flowbite.html',
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
        from app.models.stats import Standings

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

        # Teams in the current season (kept even with no Standings row yet, so
        # newly-added teams still appear in the table).
        teams = (
            Team.query.join(League).filter(League.season_id == current_season.id).all()
            if current_season else Team.query.all()
        )

        # Read the CANONICAL Standings table (app/models/stats.py) — the single
        # source of truth maintained by recompute_team_standings(). It deliberately
        # EXCLUDES self-matches (home==away) and special weeks (BYE/FUN/TST/BONUS),
        # so these numbers now agree with the per-league snapshot and the player app.
        # The previous implementation re-derived standings by looping raw Match rows
        # with no such exclusions, which inflated games played and invented phantom
        # draws on any season containing special-week / unassigned-playoff self-matches.
        standing_rows = {
            s.team_id: s
            for s in Standings.query.filter(
                Standings.season_id == current_season.id
            ).all()
        }

        standings = []
        for team in teams:
            s = standing_rows.get(team.id)
            standings.append({
                'team': team,
                'matches_played': (s.played if s else 0) or 0,
                'wins': (s.wins if s else 0) or 0,
                'draws': (s.draws if s else 0) or 0,
                'losses': (s.losses if s else 0) or 0,
                'goals_for': (s.goals_for if s else 0) or 0,
                'goals_against': (s.goals_against if s else 0) or 0,
                'goal_difference': (s.goal_difference if s else 0) or 0,
                'points': (s.points if s else 0) or 0,
            })

        # Canonical ordering: points, then goal difference, then goals for.
        standings.sort(
            key=lambda x: (x['points'], x['goal_difference'], x['goals_for']),
            reverse=True,
        )

        # Add position
        for i, standing in enumerate(standings, 1):
            standing['position'] = i

        standings_data = {
            'current_season': current_season,
            'standings': standings,
            'total_teams': len(teams)
        }

        return render_template('admin_panel/match_operations/league_standings_flowbite.html',
                               standings_data=standings_data)
    except Exception as e:
        logger.error(f"Error loading league standings: {e}")
        flash('League standings unavailable. Check database connectivity and season data.', 'error')
        return redirect(url_for('admin_panel.match_operations'))


@admin_panel_bp.route('/match-operations/leagues/create', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def create_league():
    """Create a new league."""
    from app.models import League, Season

    name = request.form.get('name')
    season_id = request.form.get('season_id')

    if not name:
        return jsonify({'success': False, 'message': 'League name is required'}), 400

    # Check if season exists
    if season_id:
        season = Season.query.get(season_id)
        if not season:
            return jsonify({'success': False, 'message': 'Selected season not found'}), 400

    # Create new league
    league = League(
        name=name,
        season_id=int(season_id) if season_id else None
    )
    db.session.add(league)
    db.session.flush()

    # Log the action
    AdminAuditLog.log_action(
        user_id=current_user.id,
        action='create_league',
        resource_type='league',
        resource_id=str(league.id),
        new_value=f'Created league: {name}',
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent')
    )

    logger.info(f"League '{name}' created by user {current_user.id}")
    return jsonify({
        'success': True,
        'message': f'League "{name}" created successfully',
        'league_id': league.id
    })


@admin_panel_bp.route('/match-operations/leagues/<int:league_id>/update', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def update_league(league_id):
    """Update an existing league."""
    from app.models import League, Season

    league = League.query.get_or_404(league_id)
    old_name = league.name

    name = request.form.get('name')
    season_id = request.form.get('season_id')

    if not name:
        return jsonify({'success': False, 'message': 'League name is required'}), 400

    # Update league
    league.name = name
    if season_id:
        league.season_id = int(season_id)

    # Log the action
    AdminAuditLog.log_action(
        user_id=current_user.id,
        action='update_league',
        resource_type='league',
        resource_id=str(league_id),
        old_value=old_name,
        new_value=name,
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent')
    )

    logger.info(f"League '{name}' updated by user {current_user.id}")
    return jsonify({
        'success': True,
        'message': f'League "{name}" updated successfully'
    })


@admin_panel_bp.route('/match-operations/leagues/<int:league_id>/delete', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def delete_league(league_id):
    """Delete a league."""
    from app.models import League, Team

    league = League.query.get_or_404(league_id)

    # Check if league has teams
    team_count = Team.query.filter_by(league_id=league_id).count() if hasattr(Team, 'league_id') else 0
    if team_count > 0:
        return jsonify({
            'success': False,
            'message': f'Cannot delete league with {team_count} teams. Move or delete teams first.'
        }), 400

    league_name = league.name

    # Log the action before deletion
    AdminAuditLog.log_action(
        user_id=current_user.id,
        action='delete_league',
        resource_type='league',
        resource_id=str(league_id),
        old_value=league_name,
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent')
    )

    db.session.delete(league)

    logger.info(f"League '{league_name}' deleted by user {current_user.id}")
    return jsonify({
        'success': True,
        'message': f'League "{league_name}" deleted successfully'
    })


@admin_panel_bp.route('/match-operations/leagues/seasons-list')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def leagues_seasons_list():
    """Return seasons as JSON for the Create/Edit League season selector."""
    try:
        from app.models import Season

        seasons = Season.query.order_by(Season.is_current.desc(), Season.name.asc()).all()
        return jsonify({
            'success': True,
            'seasons': [
                {
                    'id': s.id,
                    'name': s.name,
                    'league_type': s.league_type,
                    'is_current': bool(s.is_current)
                }
                for s in seasons
            ]
        })
    except Exception as e:
        logger.error(f"Error listing seasons: {e}")
        return jsonify({'success': False, 'message': 'Failed to load seasons'}), 500


@admin_panel_bp.route('/match-operations/leagues/<int:league_id>/details')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def get_league_details(league_id):
    """Get league details for editing modal."""
    try:
        from app.models import League

        league = League.query.get_or_404(league_id)

        return jsonify({
            'success': True,
            'league': {
                'id': league.id,
                'name': league.name,
                'season_id': league.season_id
            }
        })

    except Exception as e:
        logger.error(f"Error getting league details: {e}")
        return jsonify({'success': False, 'message': 'Failed to get league details'}), 500
