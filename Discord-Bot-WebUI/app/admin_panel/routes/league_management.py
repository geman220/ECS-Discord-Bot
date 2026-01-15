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
# Dashboard Routes
# =============================================================================

@admin_panel_bp.route('/league-management')
@admin_panel_bp.route('/league-management/')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def league_management_dashboard():
    """
    League Management Hub Dashboard.

    Provides an overview of all league types, current seasons, and quick stats.
    This is the central entry point for all league management operations.
    """
    try:
        from app.models import Season, League, Team, Match, Schedule, Player
        from app.services.league_management_service import LeagueManagementService

        # Log access
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='access_league_management_hub',
            resource_type='league_management',
            resource_id='dashboard',
            new_value='Accessed League Management Hub dashboard',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        # Initialize service and get dashboard stats
        service = LeagueManagementService(db.session)
        stats = service.get_dashboard_stats()

        return render_template(
            'admin_panel/league_management/dashboard_flowbite.html',
            stats=stats,
            page_title='League Management Hub'
        )

    except ImportError as e:
        logger.warning(f"Service import error, falling back to basic stats: {e}")
        # Fallback to basic stats without service
        return _render_dashboard_fallback()
    except Exception as e:
        logger.error(f"Error loading league management dashboard: {e}", exc_info=True)
        flash('League Management Hub temporarily unavailable. Please try again.', 'error')
        return redirect(url_for('admin_panel.dashboard'))


def _render_dashboard_fallback():
    """Fallback dashboard rendering without service layer."""
    from app.models import Season, League, Team, Match, Schedule

    # Get Pub League stats
    pub_league_season = Season.query.filter_by(
        is_current=True,
        league_type='Pub League'
    ).first()

    # Get ECS FC stats
    ecs_fc_season = Season.query.filter_by(
        is_current=True,
        league_type='ECS FC'
    ).first()

    # Calculate basic statistics
    stats = {
        'pub_league': {
            'current_season': pub_league_season,
            'teams_count': 0,
            'matches_total': 0,
            'matches_played': 0,
            'matches_upcoming': 0,
        },
        'ecs_fc': {
            'current_season': ecs_fc_season,
            'teams_count': 0,
            'matches_total': 0,
            'matches_played': 0,
            'matches_upcoming': 0,
        },
        'total_seasons': Season.query.count(),
        'total_teams': Team.query.count(),
        'total_matches': Match.query.count(),
        'recent_activity': []
    }

    if pub_league_season:
        pub_league_ids = [l.id for l in League.query.filter_by(season_id=pub_league_season.id).all()]
        if pub_league_ids:
            stats['pub_league']['teams_count'] = Team.query.filter(
                Team.league_id.in_(pub_league_ids)
            ).count()

    if ecs_fc_season:
        ecs_fc_league_ids = [l.id for l in League.query.filter_by(season_id=ecs_fc_season.id).all()]
        if ecs_fc_league_ids:
            stats['ecs_fc']['teams_count'] = Team.query.filter(
                Team.league_id.in_(ecs_fc_league_ids)
            ).count()

    return render_template(
        'admin_panel/league_management/dashboard_flowbite.html',
        stats=stats,
        page_title='League Management Hub'
    )


@admin_panel_bp.route('/league-management/api/dashboard-stats')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def league_management_dashboard_stats():
    """
    API endpoint for dashboard statistics (AJAX refresh).

    Returns JSON stats for real-time dashboard updates.
    """
    try:
        from app.services.league_management_service import LeagueManagementService

        service = LeagueManagementService(db.session)
        stats = service.get_dashboard_stats()

        return jsonify({
            'success': True,
            'stats': stats,
            'timestamp': datetime.utcnow().isoformat()
        })

    except Exception as e:
        logger.error(f"Error fetching dashboard stats: {e}")
        return jsonify({
            'success': False,
            'message': 'Failed to load statistics'
        }), 500


# =============================================================================
# Season Wizard Routes
# =============================================================================

@admin_panel_bp.route('/league-management/wizard')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def season_wizard():
    """
    Unified Season Creation Wizard.

    Multi-step wizard for creating new seasons with:
    - Step 1: Season type and basic info
    - Step 2: Team configuration
    - Step 3: Schedule configuration
    - Step 4: Discord preview
    - Step 5: Review and create
    """
    try:
        from app.models import Season, League

        # Log access
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='access_season_wizard',
            resource_type='league_management',
            resource_id='wizard',
            new_value='Accessed Season Creation Wizard',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        # Get existing seasons for reference (ordered by id since Season has no created_at)
        existing_seasons = Season.query.order_by(Season.id.desc()).limit(10).all()

        # Get current seasons for rollover options
        current_pub_league = Season.query.filter_by(
            is_current=True,
            league_type='Pub League'
        ).first()

        current_ecs_fc = Season.query.filter_by(
            is_current=True,
            league_type='ECS FC'
        ).first()

        return render_template(
            'admin_panel/league_management/season_wizard/wizard_flowbite.html',
            existing_seasons=existing_seasons,
            current_pub_league=current_pub_league,
            current_ecs_fc=current_ecs_fc,
            page_title='Create New Season'
        )

    except Exception as e:
        logger.error(f"Error loading season wizard: {e}", exc_info=True)
        flash('Season wizard temporarily unavailable.', 'error')
        return redirect(url_for('admin_panel.league_management_dashboard'))


@admin_panel_bp.route('/league-management/wizard/api/validate-step', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def wizard_validate_step():
    """
    Validate wizard step data before proceeding.

    Returns validation result for the current step.
    """
    try:
        data = request.get_json()
        step = data.get('step')
        step_data = data.get('data', {})

        validation_result = _validate_wizard_step(step, step_data)

        return jsonify(validation_result)

    except Exception as e:
        logger.error(f"Error validating wizard step: {e}")
        return jsonify({
            'valid': False,
            'errors': ['An error occurred during validation']
        }), 500


def _validate_wizard_step(step: int, data: dict) -> dict:
    """Validate data for a specific wizard step."""
    from app.models import Season

    errors = []
    warnings = []

    if step == 1:  # Basic info
        if not data.get('league_type'):
            errors.append('League type is required')
        elif data['league_type'] not in ['Pub League', 'ECS FC']:
            errors.append('Invalid league type')

        if not data.get('season_name'):
            errors.append('Season name is required')
        elif len(data['season_name']) < 3:
            errors.append('Season name must be at least 3 characters')
        else:
            # Check for duplicate
            existing = Season.query.filter(
                func.lower(Season.name) == data['season_name'].lower(),
                Season.league_type == data.get('league_type')
            ).first()
            if existing:
                errors.append(f'A season with this name already exists for {data["league_type"]}')

        if data.get('set_as_current'):
            current = Season.query.filter_by(
                is_current=True,
                league_type=data.get('league_type')
            ).first()
            if current:
                warnings.append(f'This will replace "{current.name}" as the current season and trigger a rollover')

    elif step == 2:  # Team configuration
        if data.get('league_type') == 'Pub League':
            premier_count = data.get('premier_team_count', 8)
            classic_count = data.get('classic_team_count', 4)

            if not isinstance(premier_count, int) or premier_count < 2:
                errors.append('Premier division requires at least 2 teams')
            if not isinstance(classic_count, int) or classic_count < 2:
                errors.append('Classic division requires at least 2 teams')
        else:  # ECS FC
            team_count = data.get('team_count', 8)
            if not isinstance(team_count, int) or team_count < 2:
                errors.append('At least 2 teams are required')

    elif step == 3:  # Schedule configuration
        if not data.get('regular_weeks') or data['regular_weeks'] < 1:
            errors.append('At least 1 regular season week is required')

        if not data.get('start_date'):
            errors.append('Season start date is required')

    elif step == 4:  # Discord preview
        # No validation required, just preview
        pass

    elif step == 5:  # Review
        # Final validation before submission
        pass

    return {
        'valid': len(errors) == 0,
        'errors': errors,
        'warnings': warnings
    }


@admin_panel_bp.route('/league-management/wizard/api/preview-discord', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def wizard_preview_discord():
    """
    Generate Discord resource preview without creating.

    Shows what channels and roles will be created.
    """
    try:
        data = request.get_json()

        preview = _generate_discord_preview(data)

        return jsonify({
            'success': True,
            'preview': preview
        })

    except Exception as e:
        logger.error(f"Error generating Discord preview: {e}")
        return jsonify({
            'success': False,
            'message': 'Failed to generate preview'
        }), 500


def _generate_discord_preview(data: dict) -> dict:
    """Generate a preview of Discord resources to be created."""
    preview = {
        'categories': [],
        'channels': [],
        'roles': [],
        'estimated_api_calls': 0
    }

    league_type = data.get('league_type', 'Pub League')
    teams = data.get('teams', [])

    if league_type == 'Pub League':
        # Premier division
        premier_teams = data.get('premier_teams', [])
        if premier_teams:
            preview['categories'].append('ECS FC PL Premier')
            for team_name in premier_teams:
                preview['channels'].append({
                    'name': team_name,
                    'category': 'ECS FC PL Premier'
                })
                preview['roles'].append(f'ECS-FC-PL-{team_name.upper().replace(" ", "-")}-Player')
                preview['roles'].append(f'ECS-FC-PL-{team_name.upper().replace(" ", "-")}-Coach')

        # Classic division
        classic_teams = data.get('classic_teams', [])
        if classic_teams:
            preview['categories'].append('ECS FC PL Classic')
            for team_name in classic_teams:
                preview['channels'].append({
                    'name': team_name,
                    'category': 'ECS FC PL Classic'
                })
                preview['roles'].append(f'ECS-FC-PL-{team_name.upper().replace(" ", "-")}-Player')
                preview['roles'].append(f'ECS-FC-PL-{team_name.upper().replace(" ", "-")}-Coach')
    else:
        # ECS FC
        preview['categories'].append('ECS FC')
        for team_name in teams:
            preview['channels'].append({
                'name': team_name,
                'category': 'ECS FC'
            })
            preview['roles'].append(f'ECS-FC-{team_name.upper().replace(" ", "-")}-Player')
            preview['roles'].append(f'ECS-FC-{team_name.upper().replace(" ", "-")}-Coach')

    # Estimate API calls: 1 per category + 1 per channel + 1 per role + permissions
    preview['estimated_api_calls'] = (
        len(preview['categories']) +
        len(preview['channels']) * 2 +  # Create + permissions
        len(preview['roles'])
    )

    return preview


@admin_panel_bp.route('/league-management/wizard/api/create-season', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def wizard_create_season():
    """
    Create season from wizard data (final submit).

    Handles complete season creation including:
    - Season and league records
    - Team creation
    - Schedule configuration
    - Discord resource queuing
    """
    try:
        from app.services.league_management_service import LeagueManagementService

        data = request.get_json()

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='create_season_wizard',
            resource_type='league_management',
            resource_id='wizard',
            new_value=f'Creating season: {data.get("season_name")} ({data.get("league_type")})',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        service = LeagueManagementService(db.session)
        success, message, season = service.create_season_from_wizard(
            wizard_data=data,
            user_id=current_user.id
        )

        if success:
            return jsonify({
                'success': True,
                'message': message,
                'season_id': season.id if season else None,
                'redirect_url': url_for('admin_panel.league_management_dashboard')
            })
        else:
            return jsonify({
                'success': False,
                'message': message
            }), 400

    except ImportError as e:
        logger.error(f"Service import error: {e}")
        return jsonify({
            'success': False,
            'message': 'Season creation service not available. Please try the legacy wizard.'
        }), 500


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
    """
    from app.models import Season
    from app.services.league_management_service import LeagueManagementService

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

    return jsonify({
        'success': True,
        'message': f'{season.name} is now the current season'
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

    if season.is_current:
        return jsonify({
            'success': False,
            'message': 'Cannot delete current season. Set another season as current first.'
        }), 400

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
