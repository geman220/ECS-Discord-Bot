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

        # Build a per-team season-scoped W-L-D record from the Standings table.
        # Each team's record is scoped to its own league's season (team.league.season_id),
        # which works for both the filtered and unfiltered (all-seasons) views.
        # Teams without a standings row are simply omitted; the template renders a
        # neutral placeholder for them rather than fabricating a record.
        from app.models import Standings

        team_standings = {}
        season_to_team_ids = {}
        for team in teams:
            team_season_id = team.league.season_id if team.league else None
            if team_season_id:
                season_to_team_ids.setdefault(team_season_id, []).append(team.id)

        for season_key, team_ids in season_to_team_ids.items():
            rows = Standings.query.filter(
                Standings.season_id == season_key,
                Standings.team_id.in_(team_ids)
            ).all()
            for row in rows:
                team_standings[row.team_id] = row

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
            team_standings=team_standings,
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
        from app.models import Team, Player, League

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


@admin_panel_bp.route('/league-management/seasons/api/<int:season_id>/update', methods=['PUT'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def league_management_update_season(season_id):
    """
    Update a season's name, start date and end date.
    """
    from app.models import Season

    season = Season.query.get_or_404(season_id)

    data = request.get_json() or {}
    new_name = (data.get('name') or '').strip()

    if not new_name:
        return jsonify({
            'success': False,
            'message': 'Season name is required'
        }), 400

    def _parse_date(value):
        if value in (None, ''):
            return None
        return datetime.strptime(value, '%Y-%m-%d').date()

    try:
        start_date = _parse_date(data.get('start_date'))
        end_date = _parse_date(data.get('end_date'))
    except (ValueError, TypeError):
        return jsonify({
            'success': False,
            'message': 'Dates must be in YYYY-MM-DD format'
        }), 400

    if start_date and end_date and end_date < start_date:
        return jsonify({
            'success': False,
            'message': 'End date cannot be before start date'
        }), 400

    old_value = f'{season.name} ({season.start_date} - {season.end_date})'

    season.name = new_name
    season.start_date = start_date
    season.end_date = end_date

    AdminAuditLog.log_action(
        user_id=current_user.id,
        action='update_season',
        resource_type='season',
        resource_id=str(season_id),
        old_value=old_value,
        new_value=f'{new_name} ({start_date} - {end_date})',
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent')
    )

    return jsonify({
        'success': True,
        'message': f'{new_name} updated successfully'
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


# =============================================================================
# Season Rollover (rendered inside the admin-panel shell)
# =============================================================================

@admin_panel_bp.route('/seasons/rollover', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def season_rollover():
    """Guided Season Rollover wizard, rendered inside the admin-panel shell.

    Served on the admin_panel blueprint so it gets the full admin sidebar +
    top nav (both gated on request.blueprint == 'admin_panel'). The JSON
    preview/backup/execute/restore endpoints remain on publeague.season and are
    called by absolute URL from the page JS, so nothing else has to move.
    """
    from app.models import Season, Role

    is_global_admin = False
    try:
        is_global_admin = current_user.has_role('Global Admin')
    except Exception:
        is_global_admin = False

    pub_current = db.session.query(Season).filter_by(
        league_type='Pub League', is_current=True
    ).first()
    ecs_current = db.session.query(Season).filter_by(
        league_type='ECS FC', is_current=True
    ).first()

    # Division coaches to pre-fill the in-wizard Coaches step. These are the
    # team-independent 'Premier/Classic Coach' roles (they persist across rollover);
    # add/remove here applies live via admin_panel.assign_user_role.
    premier_role = db.session.query(Role).filter_by(name='Premier Coach').first()
    classic_role = db.session.query(Role).filter_by(name='Classic Coach').first()

    return render_template(
        'publeague/season_rollover_flowbite.html',
        title='Guided Season Rollover',
        is_global_admin=is_global_admin,
        pub_current=pub_current,
        ecs_current=ecs_current,
        premier_role_id=premier_role.id if premier_role else None,
        classic_role_id=classic_role.id if classic_role else None,
        premier_coaches=_division_coach_list(premier_role),
        classic_coaches=_division_coach_list(classic_role),
    )


# =============================================================================
# Division Coaches panel (assign Premier / Classic coaches, team-independent)
# =============================================================================

def _division_coach_list(role):
    """Serialize the users holding a division-coach role, name-sorted."""
    if not role:
        return []
    out = []
    for u in role.users:
        name = (u.player.name if u.player else None) or u.username
        out.append({
            'user_id': u.id,
            'name': name,
            'has_discord': bool(u.player and u.player.discord_id),
        })
    return sorted(out, key=lambda x: (x['name'] or '').lower())


@admin_panel_bp.route('/seasons/coaches', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def season_coaches():
    """Assign coaches to Premier / Classic divisions.

    These grant the team-INDEPENDENT 'Premier Coach' / 'Classic Coach' roles,
    which drive the division coach Discord role up front (before drafting).
    Add/remove is done through the existing admin_panel.assign_user_role
    endpoint, which queues the Discord role re-sync.
    """
    from app.models import Role

    premier_role = db.session.query(Role).filter_by(name='Premier Coach').first()
    classic_role = db.session.query(Role).filter_by(name='Classic Coach').first()

    return render_template(
        'admin_panel/seasons/coaches_flowbite.html',
        premier_role_id=premier_role.id if premier_role else None,
        classic_role_id=classic_role.id if classic_role else None,
        premier_coaches=_division_coach_list(premier_role),
        classic_coaches=_division_coach_list(classic_role),
    )


def _season_overview(session, season):
    """Defensive dashboard stats for a season (each metric guarded independently
    so one failing query never breaks the page — mirrors build_attention_queue)."""
    from app.models import League, Team, Role
    from app.models.matches import Match, WeekConfiguration

    ov = {
        'season': season, 'divisions': [], 'league_ids': [],
        'teams_total': 0, 'coaches_total': 0,
        'matches_total': 0, 'matches_reported': 0, 'schedule_generated': False,
        'weeks': 0, 'special_weeks': 0, 'bye_weeks': 0, 'playoff_weeks': 0,
        # Pub League fixtures live in Match + WeekConfiguration; ECS FC uses a
        # separate EcsFcMatch table with no week configs, so the schedule/week/
        # result tiles only apply to Pub League. The template hides them otherwise.
        'schedule_supported': False,
    }
    if not season:
        return ov
    ov['schedule_supported'] = (season.league_type == 'Pub League')

    leagues = session.query(League).filter_by(season_id=season.id).all()
    league_ids = [l.id for l in leagues]
    ov['league_ids'] = league_ids

    # 'Premier/Classic/ECS FC Coach' are team-INDEPENDENT roles that persist across
    # seasons — so these are current role HOLDERS (re-curated each season on the
    # Coaches panel), not a per-season draft count. Matched tolerantly by division
    # name so a renamed league (e.g. 'Premier Division') doesn't silently show 0.
    coach_counts = {}
    for div_name in ('Premier', 'Classic', 'ECS FC'):
        try:
            r = session.query(Role).filter_by(name=f'{div_name} Coach').first()
            coach_counts[div_name] = len(r.users) if r else 0
        except Exception:
            coach_counts[div_name] = 0

    def _coaches_for(name):
        n = (name or '').lower()
        if 'premier' in n:
            return coach_counts.get('Premier', 0)
        if 'classic' in n:
            return coach_counts.get('Classic', 0)
        if 'ecs fc' in n or 'ecsfc' in n:
            return coach_counts.get('ECS FC', 0)
        return 0

    for lg in leagues:
        try:
            team_ct = session.query(Team).filter_by(league_id=lg.id).count()
        except Exception:
            team_ct = 0
        coaches = _coaches_for(lg.name)
        ov['teams_total'] += team_ct
        ov['coaches_total'] += coaches
        ov['divisions'].append({
            'name': lg.name, 'league_id': lg.id, 'teams': team_ct, 'coaches': coaches,
        })

    # Schedule/week/result metrics are Pub-League-shaped (Match + WeekConfiguration).
    if league_ids and ov['schedule_supported']:
        try:
            # Count only REAL, reportable fixtures — exclude the special/BYE/playoff
            # placeholder self-match rows (home == away, is_special_week), mirroring
            # the standings self-match invariant. Otherwise the denominator includes
            # non-reportable rows and "results %" can never reach 100%.
            base = session.query(Match).join(Team, Match.home_team_id == Team.id).filter(
                Team.league_id.in_(league_ids),
                Match.home_team_id != Match.away_team_id,
                Match.is_special_week.isnot(True),
            )
            ov['matches_total'] = base.count()
            ov['matches_reported'] = base.filter(
                Match.home_team_score.isnot(None), Match.away_team_score.isnot(None)
            ).count()
            ov['schedule_generated'] = ov['matches_total'] > 0
        except Exception:
            pass
        try:
            wcs = session.query(WeekConfiguration).filter(
                WeekConfiguration.league_id.in_(league_ids)
            ).all()
            ov['weeks'] = len({w.week_order for w in wcs})
            ov['special_weeks'] = len({w.week_order for w in wcs if (w.week_type or '') in ('TST', 'FUN')})
            ov['bye_weeks'] = len({w.week_order for w in wcs if (w.week_type or '') == 'BYE'})
            ov['playoff_weeks'] = len({w.week_order for w in wcs
                                       if (w.week_type or '') == 'PLAYOFF' or getattr(w, 'is_playoff_week', False)})
        except Exception:
            pass

    return ov


@admin_panel_bp.route('/seasons/manage', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def season_manage():
    """Post-rollover 'Manage Season' dashboard — live status of the current season
    (teams, schedule, coaches, results) plus inline actions and a next-steps
    checklist. Editing links out to the existing schedule/team editors and the
    Coaches panel."""
    from app.models import Season

    pub_current = db.session.query(Season).filter_by(
        league_type='Pub League', is_current=True
    ).first()
    ecs_current = db.session.query(Season).filter_by(
        league_type='ECS FC', is_current=True
    ).first()

    return render_template(
        'admin_panel/seasons/manage_flowbite.html',
        pub_current=pub_current,
        ecs_current=ecs_current,
        pub=_season_overview(db.session, pub_current),
        ecs=_season_overview(db.session, ecs_current),
    )


@admin_panel_bp.route('/seasons/coaches/search', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def season_coaches_search():
    """Search players (with a linked user account) by name, for the Coaches panel."""
    from app.models import Player

    q = (request.args.get('q') or '').strip()
    if len(q) < 2:
        return jsonify({'success': True, 'results': []})

    players = db.session.query(Player).filter(
        Player.name.ilike(f'%{q}%'),
        Player.user_id.isnot(None),
    ).order_by(Player.name).limit(20).all()

    results = [{
        'user_id': p.user_id,
        'name': p.name,
        'has_discord': bool(p.discord_id),
    } for p in players]
    return jsonify({'success': True, 'results': results})


# Redis hash: {user_id: 'ok'|'missing'} — cached live Discord coach-role status so
# the Coaches panel doesn't re-poll the bot for every coach on every page load.
_COACH_STATUS_CACHE_KEY = 'coach_discord_status'
_COACH_STATUS_CACHE_TTL = 900  # 15 min


@admin_panel_bp.route('/seasons/coaches/sync-discord', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def season_coaches_sync_discord():
    """Force-push the division coach Discord roles for everyone currently holding
    the Premier/Classic Coach Flask roles.

    Use this after assigning coaches, or when the normal per-assign sync didn't
    land (e.g. the broker was down during a rollover, or roles were assigned
    before the coach-role mapping fix). It re-runs the CORRECT role calculator
    (update_player_discord_roles), which grants ECS-FC-PL-PREMIER-COACH /
    ECS-FC-PL-CLASSIC-COACH team-independently from the Flask coach roles.
    """
    from app.models import Role
    from app.tasks.tasks_discord import process_discord_role_updates

    # ?all=1 re-syncs everyone; default only syncs coaches NOT already confirmed
    # (cached status != 'ok'), so we don't re-push roles that are already correct.
    sync_all = (request.args.get('all') or '').lower() in ('1', 'true', 'yes')

    cached = {}
    try:
        from app.utils.safe_redis import get_safe_redis
        cached = get_safe_redis().hgetall(_COACH_STATUS_CACHE_KEY) or {}
    except Exception:
        cached = {}

    premier_role = db.session.query(Role).filter_by(name='Premier Coach').first()
    classic_role = db.session.query(Role).filter_by(name='Classic Coach').first()

    seen = set()
    discord_ids = []
    no_discord = 0
    skipped_ok = 0
    for role in (premier_role, classic_role):
        if not role:
            continue
        for u in role.users:
            if u.id in seen:
                continue
            seen.add(u.id)
            did = u.player.discord_id if u.player else None
            if not did:
                no_discord += 1
                continue
            if not sync_all and str(cached.get(str(u.id))) == 'ok':
                skipped_ok += 1
                continue
            discord_ids.append(str(did))

    # Fire ONE batched task rather than N competing ones. The bot paces the
    # per-member Discord writes internally, so we don't trip Discord's role
    # rate limiter (which serialized — and slowed — the old per-user approach).
    queued = len(discord_ids)
    errors = 0
    if discord_ids:
        try:
            process_discord_role_updates.delay(discord_ids)
            # Invalidate the status cache so the page re-verifies (cheap now that
            # the bot reads member roles from its cache, no Discord API calls).
            try:
                get_safe_redis().delete(_COACH_STATUS_CACHE_KEY)
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Failed to queue batched coach Discord sync: {e}")
            errors = queued
            queued = 0

    return jsonify({
        'success': errors == 0,
        'total': len(seen),
        'queued': queued,
        'skipped_ok': skipped_ok,
        'no_discord': no_discord,
        'errors': errors,
    })


@admin_panel_bp.route('/seasons/coaches/discord-status', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def season_coaches_discord_status():
    """Live-verify each division coach actually holds their coach role in Discord.

    Reads each coach's member roles straight from the bot (same source the sync
    uses), so the Coaches panel can show a real green/amber status per coach
    instead of trusting the Flask DB. Returns a map of
    user_id -> 'ok' | 'missing' | 'no_discord' | 'unknown'.

    Cached in Redis (15 min): a normal load returns cached verdicts and only
    polls the bot for coaches with no cached result. Pass ?refresh=1 to re-poll
    everyone (the "Re-check" button).
    """
    import os
    import requests
    from app.models import Role

    refresh = (request.args.get('refresh') or '').lower() in ('1', 'true', 'yes')

    premier_role = db.session.query(Role).filter_by(name='Premier Coach').first()
    classic_role = db.session.query(Role).filter_by(name='Classic Coach').first()

    # Map each coach -> the Discord coach role(s) they're expected to hold.
    want = {}

    def _collect(role, discord_role_name):
        if not role:
            return
        for u in role.users:
            info = want.setdefault(u.id, {'discord_id': None, 'roles': set()})
            info['discord_id'] = u.player.discord_id if u.player else None
            info['roles'].add(discord_role_name)

    _collect(premier_role, 'ECS-FC-PL-PREMIER-COACH')
    _collect(classic_role, 'ECS-FC-PL-CLASSIC-COACH')

    bot_api_url = os.getenv('BOT_API_URL', 'http://discord-bot:5001')
    guild_id = os.getenv('SERVER_ID')
    if not guild_id:
        return jsonify({'success': False, 'available': False,
                        'error': 'Discord guild (SERVER_ID) is not configured.'})

    redis = None
    cached = {}
    try:
        from app.utils.safe_redis import get_safe_redis
        redis = get_safe_redis()
        if not refresh:
            cached = redis.hgetall(_COACH_STATUS_CACHE_KEY) or {}
    except Exception:
        redis, cached = None, {}

    # Serve cached verdicts; only poll the bot for coaches we don't have yet.
    statuses = {}
    to_poll = {}
    for uid, info in want.items():
        if not info['discord_id']:
            statuses[uid] = 'no_discord'
        elif str(uid) in cached:
            statuses[uid] = str(cached[str(uid)])
        else:
            to_poll[uid] = info

    # The bot's /members/<id>/roles endpoint returns role NAMES (not IDs), so we
    # compare expected coach role names directly.
    reachable = not to_poll  # nothing to poll => cache fully served this request
    fresh = {}
    for uid, info in to_poll.items():
        did = info['discord_id']
        try:
            mr = requests.get(
                f"{bot_api_url}/api/server/guilds/{guild_id}/members/{did}/roles", timeout=8)
            if mr.status_code == 404:
                reachable = True
                statuses[uid] = fresh[uid] = 'missing'
                continue
            if mr.status_code != 200:
                statuses[uid] = 'unknown'
                continue
            reachable = True
            data = mr.json() or {}
            raw = data.get('roles', []) or []
            member_role_names = set()
            for r in raw:
                if isinstance(r, dict):
                    if r.get('name'):
                        member_role_names.add(str(r['name']))
                else:
                    member_role_names.add(str(r))
            statuses[uid] = fresh[uid] = 'ok' if (member_role_names & info['roles']) else 'missing'
        except Exception as e:
            logger.warning(f"Coach Discord status check failed for user {uid}: {e}")
            statuses[uid] = 'unknown'

    if to_poll and not reachable:
        # Had to poll but reached the bot for nobody — report unavailable so the
        # UI stays quiet rather than painting everyone amber.
        return jsonify({'success': False, 'available': False,
                        'error': 'Could not reach the Discord bot (is it running?).'})

    # Persist the freshly-polled ok/missing verdicts (skip 'unknown' so a transient
    # blip isn't cached as fact).
    if fresh and redis:
        try:
            redis.hset(_COACH_STATUS_CACHE_KEY, mapping={str(k): v for k, v in fresh.items()})
            redis.expire(_COACH_STATUS_CACHE_KEY, _COACH_STATUS_CACHE_TTL)
        except Exception:
            pass

    return jsonify({'success': True, 'available': True, 'statuses': statuses,
                    'from_cache': bool(cached) and not refresh})
