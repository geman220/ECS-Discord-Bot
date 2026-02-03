# app/admin_panel/routes/league_management.py

"""
League Management Hub Routes

This module provides a centralized hub for managing:
- Seasons (Pub League, ECS FC)
- Teams across all divisions (Premier, Classic, ECS FC)
- Schedules and match configuration
- Discord resource integration
- Season lifecycle (creation, rollover, archival)

Routes are organized under /admin-panel/league-management/
"""

import logging
from datetime import datetime, timedelta
from typing import Optional
from flask import render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload
from sqlalchemy import func, or_, and_

from .. import admin_panel_bp
from app.core import db
from app.models.admin_config import AdminAuditLog
from app.decorators import role_required
from app.utils.db_utils import transactional

logger = logging.getLogger(__name__)


# =============================================================================
# Dashboard Routes (Redirects to Admin Panel)
# =============================================================================

@admin_panel_bp.route('/league-management')
@admin_panel_bp.route('/league-management/')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def league_management_dashboard():
    """
    League Management Hub - Redirects to Admin Panel dashboard.

    The League Management functionality is now accessed through the Admin Panel
    dashboard, which contains a dedicated League Management card with links to:
    - Create New Season (Auto Schedule)
    - Teams management
    - Seasons management
    - Pub League Orders
    """
    return redirect(url_for('admin_panel.dashboard'))


# =============================================================================
# Team Management Routes
# =============================================================================

@admin_panel_bp.route('/league-management/teams')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def league_management_teams():
    """
    Team Management Hub.

    Lists all teams across all seasons with filtering options.
    """
    try:
        from app.models import Team, League, Season

        # Log access
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='access_team_management',
            resource_type='league_management',
            resource_id='teams',
            new_value='Accessed Team Management Hub',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        # Get filter parameters
        season_id = request.args.get('season_id', type=int)
        league_type = request.args.get('league_type')

        # Get all seasons for filter dropdown (ordered by id since Season has no created_at)
        seasons = Season.query.order_by(Season.id.desc()).all()

        # Build teams query
        query = Team.query.options(
            joinedload(Team.league).joinedload(League.season)
        )

        if season_id:
            query = query.join(League).filter(League.season_id == season_id)

        if league_type:
            query = query.join(League).join(Season).filter(Season.league_type == league_type)

        teams = query.order_by(Team.name).all()

        # Calculate stats
        stats = {
            'total_teams': len(teams),
            'teams_with_discord': len([t for t in teams if t.discord_channel_id]),
            'teams_by_league_type': {}
        }

        for team in teams:
            if team.league and team.league.season:
                lt = team.league.season.league_type
                if lt not in stats['teams_by_league_type']:
                    stats['teams_by_league_type'][lt] = 0
                stats['teams_by_league_type'][lt] += 1

        return render_template(
            'admin_panel/league_management/teams/index_flowbite.html',
            teams=teams,
            seasons=seasons,
            stats=stats,
            current_season_id=season_id,
            current_league_type=league_type,
            page_title='Team Management'
        )

    except Exception as e:
        logger.error(f"Error loading team management: {e}", exc_info=True)
        flash('Team management temporarily unavailable.', 'error')
        return redirect(url_for('admin_panel.league_management_dashboard'))


@admin_panel_bp.route('/league-management/teams/<int:team_id>')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def league_management_team_detail(team_id):
    """
    Team detail view.

    Shows team information, roster, stats, and Discord integration.
    """
    try:
        from app.models import Team, Player

        team = Team.query.options(
            joinedload(Team.league).joinedload(League.season),
            joinedload(Team.players)
        ).get_or_404(team_id)

        return render_template(
            'admin_panel/league_management/teams/team_detail_flowbite.html',
            team=team,
            page_title=f'Team: {team.name}'
        )

    except Exception as e:
        logger.error(f"Error loading team detail: {e}", exc_info=True)
        flash('Team details unavailable.', 'error')
        return redirect(url_for('admin_panel.league_management_teams'))


@admin_panel_bp.route('/league-management/teams/api/create', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def league_management_create_team():
    """
    Create a new team with automatic Discord resource queuing.
    """
    from app.services.league_management_service import LeagueManagementService

    data = request.get_json()
    name = data.get('name')
    league_id = data.get('league_id')

    if not name or not league_id:
        return jsonify({
            'success': False,
            'message': 'Team name and league are required'
        }), 400

    service = LeagueManagementService(db.session)
    success, message, team = service.create_team(
        name=name,
        league_id=league_id,
        user_id=current_user.id
    )

    if success:
        return jsonify({
            'success': True,
            'message': message,
            'team': {
                'id': team.id,
                'name': team.name
            }
        })
    else:
        return jsonify({
            'success': False,
            'message': message
        }), 400


@admin_panel_bp.route('/league-management/teams/api/<int:team_id>/update', methods=['PUT'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def league_management_update_team(team_id):
    """
    Update team (rename triggers Discord update).
    """
    from app.services.league_management_service import LeagueManagementService

    data = request.get_json()
    new_name = data.get('name')

    if not new_name:
        return jsonify({
            'success': False,
            'message': 'New team name is required'
        }), 400

    service = LeagueManagementService(db.session)
    success, message = service.rename_team(
        team_id=team_id,
        new_name=new_name,
        user_id=current_user.id
    )

    if success:
        return jsonify({
            'success': True,
            'message': message
        })
    else:
        return jsonify({
            'success': False,
            'message': message
        }), 400


@admin_panel_bp.route('/league-management/teams/api/<int:team_id>/delete', methods=['DELETE'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def league_management_delete_team(team_id):
    """
    Delete team with Discord cleanup queue.
    """
    from app.services.league_management_service import LeagueManagementService

    service = LeagueManagementService(db.session)
    success, message = service.delete_team(
        team_id=team_id,
        user_id=current_user.id
    )

    if success:
        return jsonify({
            'success': True,
            'message': message
        })
    else:
        return jsonify({
            'success': False,
            'message': message
        }), 400


@admin_panel_bp.route('/league-management/teams/api/<int:team_id>/sync-discord', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def league_management_sync_team_discord(team_id):
    """
    Manually trigger Discord sync for a team.
    """
    try:
        from app.services.league_management_service import LeagueManagementService

        service = LeagueManagementService(db.session)
        success, message = service.sync_team_discord(team_id)

        return jsonify({
            'success': success,
            'message': message
        })

    except Exception as e:
        logger.error(f"Error syncing team Discord: {e}")
        return jsonify({
            'success': False,
            'message': 'Failed to sync Discord resources'
        }), 500


# =============================================================================
# Season Lifecycle Routes
# =============================================================================

@admin_panel_bp.route('/league-management/seasons')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def league_management_seasons():
    """
    Season listing with filters.

    Shows all seasons (active and historical).
    """
    try:
        from app.models import Season, League, Team

        # Log access
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='access_season_management',
            resource_type='league_management',
            resource_id='seasons',
            new_value='Accessed Season Management',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        # Get filter parameters
        league_type = request.args.get('league_type')
        show_current_only = request.args.get('current_only') == 'true'

        # Build query
        query = Season.query.options(
            joinedload(Season.leagues).joinedload(League.teams)
        )

        if league_type:
            query = query.filter(Season.league_type == league_type)

        if show_current_only:
            query = query.filter(Season.is_current == True)

        seasons = query.order_by(Season.id.desc()).all()

        # Enrich with stats
        for season in seasons:
            season.team_count = sum(len(league.teams) for league in season.leagues)
            season.league_count = len(season.leagues)

        return render_template(
            'admin_panel/league_management/seasons/index_flowbite.html',
            seasons=seasons,
            current_league_type=league_type,
            show_current_only=show_current_only,
            page_title='Season Management'
        )

    except Exception as e:
        logger.error(f"Error loading seasons: {e}", exc_info=True)
        flash('Season management temporarily unavailable.', 'error')
        return redirect(url_for('admin_panel.league_management_dashboard'))


@admin_panel_bp.route('/league-management/seasons/<int:season_id>')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def league_management_season_detail(season_id):
    """
    Season detail view with leagues, teams, schedule summary.
    """
    try:
        from app.models import Season, League, Team, Match, Schedule
        from app.services.league_management_service import LeagueManagementService

        season = Season.query.options(
            joinedload(Season.leagues).joinedload(League.teams)
        ).get_or_404(season_id)

        service = LeagueManagementService(db.session)
        summary = service.get_season_summary(season_id)

        return render_template(
            'admin_panel/league_management/seasons/season_detail_flowbite.html',
            season=season,
            summary=summary,
            page_title=f'Season: {season.name}'
        )

    except ImportError:
        # Fallback without service
        season = Season.query.options(
            joinedload(Season.leagues).joinedload(League.teams)
        ).get_or_404(season_id)

        return render_template(
            'admin_panel/league_management/seasons/season_detail_flowbite.html',
            season=season,
            summary={},
            page_title=f'Season: {season.name}'
        )
    except Exception as e:
        logger.error(f"Error loading season detail: {e}", exc_info=True)
        flash('Season details unavailable.', 'error')
        return redirect(url_for('admin_panel.league_management_seasons'))


@admin_panel_bp.route('/league-management/seasons/api/<int:season_id>/rollover-preview')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def league_management_rollover_preview(season_id):
    """
    Preview what would change during rollover.
    """
    try:
        from app.services.league_management_service import LeagueManagementService

        service = LeagueManagementService(db.session)
        preview = service.get_rollover_preview(season_id, {})

        return jsonify({
            'success': True,
            'preview': preview
        })

    except Exception as e:
        logger.error(f"Error generating rollover preview: {e}")
        return jsonify({
            'success': False,
            'message': 'Failed to generate preview'
        }), 500


@admin_panel_bp.route('/league-management/seasons/api/<int:season_id>/set-current', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def league_management_set_current_season(season_id):
    """
    Set season as current (with optional rollover).

    When switching to a season, automatically restores player-team memberships
    from PlayerTeamSeason history so players are on their correct teams for that season.
    """
    from app.models import Season
    from app.services.league_management_service import LeagueManagementService
    from app.season_routes import restore_season_memberships

    data = request.get_json() or {}
    perform_rollover = data.get('perform_rollover', False)

    season = Season.query.get_or_404(season_id)

    # Log action
    AdminAuditLog.log_action(
        user_id=current_user.id,
        action='set_current_season',
        resource_type='season',
        resource_id=str(season_id),
        new_value=f'Set {season.name} as current (rollover={perform_rollover})',
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent')
    )

    # Get current season of same type
    old_current = Season.query.filter(
        Season.league_type == season.league_type,
        Season.is_current == True,
        Season.id != season_id
    ).first()

    if perform_rollover and old_current:
        service = LeagueManagementService(db.session)
        success = service.perform_rollover(old_current, season, current_user.id)
        if not success:
            return jsonify({
                'success': False,
                'message': 'Rollover failed'
            }), 500

    # Clear old current
    if old_current:
        old_current.is_current = False

    # Set new current
    season.is_current = True

    # Restore player-team memberships from PlayerTeamSeason history
    # This ensures players are on their correct teams when switching between seasons
    restore_result = {'restored': 0, 'message': 'No restoration needed'}
    try:
        restore_result = restore_season_memberships(db.session, season)
        logger.info(f"Season membership restoration: {restore_result}")
    except Exception as e:
        logger.error(f"Failed to restore season memberships: {e}")
        # Don't fail the whole operation - just log the error
        restore_result = {'restored': 0, 'message': f'Restoration failed: {str(e)}'}

    return jsonify({
        'success': True,
        'message': f'{season.name} is now the current season',
        'restoration': restore_result
    })


@admin_panel_bp.route('/league-management/seasons/api/<int:season_id>/delete', methods=['DELETE'])
@login_required
@role_required(['Global Admin'])  # Only Global Admin can delete seasons
@transactional
def league_management_delete_season(season_id):
    """
    Delete season with comprehensive cleanup.
    """
    from app.models import Season
    from app.services.league_management_service import LeagueManagementService

    season = Season.query.get_or_404(season_id)

    # If deleting current season, try to set another season as current first
    if season.is_current:
        # Find another season of the same type to set as current
        other_season = Season.query.filter(
            Season.id != season_id,
            Season.league_type == season.league_type
        ).order_by(Season.id.desc()).first()

        if other_season:
            other_season.is_current = True
            logger.info(f"Setting {other_season.name} as current before deleting {season.name}")

        # Unset current on the season being deleted
        season.is_current = False
        db.session.flush()

    # Log action
    AdminAuditLog.log_action(
        user_id=current_user.id,
        action='delete_season',
        resource_type='season',
        resource_id=str(season_id),
        old_value=season.name,
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent')
    )

    service = LeagueManagementService(db.session)
    success, message = service.delete_season(season_id, current_user.id)

    if success:
        return jsonify({
            'success': True,
            'message': message
        })
    else:
        return jsonify({
            'success': False,
            'message': message
        }), 400


# =============================================================================
# History Routes
# =============================================================================

@admin_panel_bp.route('/league-management/history')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def league_management_history():
    """
    View season history and player team history.
    """
    try:
        from app.models import Season, PlayerTeamSeason
        from app.services.league_management_service import LeagueManagementService

        service = LeagueManagementService(db.session)
        history = service.get_season_history()

        return render_template(
            'admin_panel/league_management/history_flowbite.html',
            history=history,
            page_title='League History'
        )

    except Exception as e:
        logger.error(f"Error loading history: {e}", exc_info=True)
        flash('History unavailable.', 'error')
        return redirect(url_for('admin_panel.league_management_dashboard'))


@admin_panel_bp.route('/league-management/history/api/player/<int:player_id>')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def league_management_player_history(player_id):
    """
    Get player's team history across seasons.
    """
    try:
        from app.services.league_management_service import LeagueManagementService

        service = LeagueManagementService(db.session)
        history = service.get_player_team_history(player_id)

        return jsonify({
            'success': True,
            'history': history
        })

    except Exception as e:
        logger.error(f"Error loading player history: {e}")
        return jsonify({
            'success': False,
            'message': 'Failed to load player history'
        }), 500


@admin_panel_bp.route('/league-management/history/api/search-players')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def league_management_search_players():
    """
    Search for players by name (for player history lookup).
    """
    try:
        from app.services.league_management_service import LeagueManagementService

        query = request.args.get('q', '').strip()
        if len(query) < 2:
            return jsonify({
                'success': True,
                'players': []
            })

        service = LeagueManagementService(db.session)
        players = service.search_players_by_name(query, limit=20)

        return jsonify({
            'success': True,
            'players': players
        })

    except Exception as e:
        logger.error(f"Error searching players: {e}")
        return jsonify({
            'success': False,
            'message': 'Failed to search players'
        }), 500
