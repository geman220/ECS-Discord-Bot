# app/admin_panel/routes/discord_management.py

"""
Admin Panel Discord Management Routes

This module contains routes for Discord server management including:
- Discord role synchronization
- Player Discord status monitoring
- Onboarding management and testing
- Discord server statistics
"""

import logging
from datetime import datetime
from flask import render_template, request, jsonify, g, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload

from .. import admin_panel_bp
from app.decorators import role_required
from app.models import Player, Team, User, Season, League
from app.models.admin_config import AdminAuditLog
from app.tasks.tasks_discord import (
    update_player_discord_roles,
    fetch_role_status,
    process_discord_role_updates
)

logger = logging.getLogger(__name__)


# -----------------------------------------------------------
# Discord Overview & Dashboard Routes
# -----------------------------------------------------------

@admin_panel_bp.route('/discord')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def discord_overview():
    """Discord management dashboard with overview statistics."""
    session = g.db_session
    try:
        # Get Discord statistics
        total_players = session.query(Player).filter(Player.discord_id.isnot(None)).count()
        players_in_server = session.query(Player).filter(
            Player.discord_id.isnot(None),
            Player.discord_in_server == True
        ).count()
        players_not_in_server = session.query(Player).filter(
            Player.discord_id.isnot(None),
            Player.discord_in_server == False
        ).count()
        players_unknown = session.query(Player).filter(
            Player.discord_id.isnot(None),
            Player.discord_in_server.is_(None)
        ).count()

        # Get players needing role sync
        players_needing_sync = session.query(Player).filter(
            Player.discord_id.isnot(None),
            Player.discord_roles_synced == False
        ).count()

        stats = {
            'total_players': total_players,
            'in_server': players_in_server,
            'not_in_server': players_not_in_server,
            'unknown_status': players_unknown,
            'needs_sync': players_needing_sync
        }

        return render_template('admin_panel/discord/overview.html', stats=stats)
    except Exception as e:
        logger.error(f"Error loading Discord overview: {e}")
        return render_template('admin_panel/discord/overview.html',
                             stats={'total_players': 0, 'in_server': 0, 'not_in_server': 0,
                                   'unknown_status': 0, 'needs_sync': 0},
                             error=str(e))


@admin_panel_bp.route('/discord/players')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def discord_players():
    """
    Discord player status management - shows players with Discord status filtering.
    """
    session = g.db_session
    try:
        # Get pagination and filter parameters
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        status_filter = request.args.get('status', 'not_in_server')

        per_page = max(10, min(per_page, 100))

        # Get current seasons for team filtering
        current_seasons = session.query(Season).filter(Season.is_current == True).all()
        current_season_ids = [season.id for season in current_seasons]

        # Base query for players with Discord IDs
        base_query = session.query(Player).options(
            joinedload(Player.teams).joinedload(Team.league).joinedload(League.season),
            joinedload(Player.user)
        ).filter(Player.discord_id.isnot(None))

        # Get all players for statistics
        all_players = base_query.all()

        # Build current teams mapping
        player_current_teams = {}
        for player in all_players:
            if player.teams:
                current_season_teams = [
                    team for team in player.teams
                    if team.league and team.league.season_id in current_season_ids
                ]
                player_current_teams[player.id] = current_season_teams
            else:
                player_current_teams[player.id] = []

        # Calculate statistics
        stats = {
            'total_players': len(all_players),
            'in_server': sum(1 for p in all_players if p.discord_in_server is True),
            'not_in_server': sum(1 for p in all_players if p.discord_in_server is False),
            'unknown_status': sum(1 for p in all_players if p.discord_in_server is None)
        }

        # Apply status filter
        section_titles = {
            'not_in_server': 'Players Not In Discord Server',
            'unknown': 'Players with Unknown Discord Status',
            'in_server': 'Players In Discord Server',
            'all': 'All Players with Discord'
        }

        if status_filter == 'not_in_server':
            filtered_query = base_query.filter(Player.discord_in_server == False)
        elif status_filter == 'unknown':
            filtered_query = base_query.filter(Player.discord_in_server.is_(None))
        elif status_filter == 'in_server':
            filtered_query = base_query.filter(Player.discord_in_server == True)
        else:
            filtered_query = base_query

        current_section = section_titles.get(status_filter, 'All Players with Discord')

        # Order and paginate
        filtered_query = filtered_query.order_by(
            Player.discord_last_checked.nulls_first(),
            Player.discord_last_checked.asc()
        )

        # Manual pagination
        total = filtered_query.count()
        players = filtered_query.offset((page - 1) * per_page).limit(per_page).all()
        pages = (total + per_page - 1) // per_page

        pagination = {
            'has_prev': page > 1,
            'prev_num': page - 1 if page > 1 else None,
            'page': page,
            'has_next': page < pages,
            'next_num': page + 1 if page < pages else None,
            'pages': pages,
            'total': total,
            'per_page': per_page
        }

        return render_template('admin_panel/discord/players.html',
                             stats=stats,
                             players=players,
                             pagination=pagination,
                             status_filter=status_filter,
                             current_section=current_section,
                             per_page=per_page,
                             player_current_teams=player_current_teams)

    except Exception as e:
        logger.error(f"Error loading Discord players page: {e}")
        return render_template('admin_panel/discord/players.html',
                             stats={'total_players': 0, 'in_server': 0, 'not_in_server': 0, 'unknown_status': 0},
                             players=[],
                             pagination={'has_prev': False, 'prev_num': None, 'page': 1,
                                        'has_next': False, 'next_num': None, 'pages': 1,
                                        'total': 0, 'per_page': 20},
                             status_filter='not_in_server',
                             current_section='Players Not In Discord Server',
                             per_page=20,
                             player_current_teams={},
                             error=str(e))


# -----------------------------------------------------------
# Discord Role Synchronization Routes
# -----------------------------------------------------------

@admin_panel_bp.route('/discord/roles')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def discord_roles():
    """Discord role synchronization management page."""
    session = g.db_session
    try:
        # Get players needing sync
        players_needing_sync = session.query(Player).filter(
            Player.discord_id.isnot(None),
            Player.discord_roles_synced == False
        ).count()

        players_needs_update = session.query(Player).filter(
            Player.discord_id.isnot(None),
            Player.discord_needs_update == True
        ).count()

        return render_template('admin_panel/discord/roles.html',
                             players_needing_sync=players_needing_sync,
                             players_needs_update=players_needs_update)
    except Exception as e:
        logger.error(f"Error loading Discord roles page: {e}")
        return render_template('admin_panel/discord/roles.html',
                             players_needing_sync=0,
                             players_needs_update=0,
                             error=str(e))


@admin_panel_bp.route('/discord/roles/check-status/<task_id>')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def discord_check_role_status(task_id):
    """Check the status of a Discord role update task."""
    try:
        task = fetch_role_status.AsyncResult(task_id)
        if task.ready():
            if task.successful():
                task_result = task.get()
                return jsonify({
                    'state': 'COMPLETE',
                    'results': task_result.get('results', [])
                })
            else:
                return jsonify({
                    'state': 'FAILED',
                    'error': str(task.result)
                })
        return jsonify({'state': 'PENDING'})
    except Exception as e:
        logger.error(f"Error checking task status: {e}")
        return jsonify({'state': 'ERROR', 'error': str(e)}), 500


@admin_panel_bp.route('/discord/roles/update-player/<int:player_id>', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def discord_update_player_roles(player_id):
    """Update a specific player's Discord roles."""
    try:
        task_result = update_player_discord_roles.delay(player_id).get(timeout=30)

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='discord_role_update',
            resource_type='player',
            resource_id=str(player_id),
            new_value=f"Role update: {task_result.get('success', False)}",
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        if task_result.get('success'):
            return jsonify({
                'success': True,
                'player_data': task_result.get('player_data')
            })
        else:
            return jsonify({
                'success': False,
                'error': task_result.get('message', 'Unknown error occurred')
            }), 400
    except Exception as e:
        logger.error(f"Error updating roles for player {player_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/discord/roles/sync-all', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def discord_mass_sync_roles():
    """Initiate a mass update for Discord roles across all players."""
    session = g.db_session
    try:
        # Mark all players that need sync
        updated = session.query(Player).filter(
            Player.discord_id.isnot(None),
            Player.discord_roles_synced == False
        ).update({Player.discord_needs_update: True}, synchronize_session=False)

        result = process_discord_role_updates.delay()

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='discord_mass_role_sync',
            resource_type='system',
            resource_id='discord',
            new_value=f'Mass sync initiated for {updated} players',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({
            'success': True,
            'message': f'Mass role update initiated for {updated} players',
            'task_id': result.id
        })

    except Exception as e:
        logger.error(f"Error initiating mass role update: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# -----------------------------------------------------------
# Discord Status Refresh Routes
# -----------------------------------------------------------

@admin_panel_bp.route('/discord/refresh-all-status', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def discord_refresh_all_status():
    """Refresh Discord status for all players with Discord IDs."""
    session = g.db_session
    try:
        players_with_discord = session.query(Player).filter(
            Player.discord_id.isnot(None)
        ).all()

        success_count = 0
        error_count = 0
        batch_size = 10

        for i in range(0, len(players_with_discord), batch_size):
            batch = players_with_discord[i:i + batch_size]
            batch_updates = []

            for player in batch:
                try:
                    if player.check_discord_status():
                        success_count += 1
                        batch_updates.append(player)
                    else:
                        error_count += 1
                except Exception as e:
                    logger.error(f"Error refreshing Discord status for player {player.id}: {e}")
                    error_count += 1

            if batch_updates:
                for player in batch_updates:
                    session.add(player)
                try:
                    session.commit()
                except Exception as e:
                    logger.error(f"Error committing batch: {e}")
                    session.rollback()

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='discord_refresh_all_status',
            resource_type='system',
            resource_id='discord',
            new_value=f'Refreshed {success_count} players, {error_count} errors',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({
            'success': True,
            'message': f'Refreshed Discord status for {success_count} players',
            'success_count': success_count,
            'error_count': error_count,
            'total_processed': len(players_with_discord)
        })

    except Exception as e:
        session.rollback()
        logger.error(f"Error in refresh_all_discord_status: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/discord/refresh-unknown-status', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def discord_refresh_unknown_status():
    """Refresh Discord status for players with unknown status only."""
    session = g.db_session
    try:
        players_unknown_status = session.query(Player).filter(
            Player.discord_id.isnot(None),
            Player.discord_in_server.is_(None)
        ).all()

        success_count = 0
        error_count = 0
        batch_size = 10

        for i in range(0, len(players_unknown_status), batch_size):
            batch = players_unknown_status[i:i + batch_size]
            batch_updates = []

            for player in batch:
                try:
                    if player.check_discord_status():
                        success_count += 1
                        batch_updates.append(player)
                    else:
                        error_count += 1
                except Exception as e:
                    logger.error(f"Error refreshing Discord status for player {player.id}: {e}")
                    error_count += 1

            if batch_updates:
                for player in batch_updates:
                    session.add(player)
                try:
                    session.commit()
                except Exception as e:
                    logger.error(f"Error committing batch: {e}")
                    session.rollback()

        return jsonify({
            'success': True,
            'message': f'Checked Discord status for {success_count} players with unknown status',
            'success_count': success_count,
            'error_count': error_count,
            'total_processed': len(players_unknown_status)
        })

    except Exception as e:
        session.rollback()
        logger.error(f"Error in refresh_unknown_discord_status: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# -----------------------------------------------------------
# Discord Onboarding Routes
# -----------------------------------------------------------

@admin_panel_bp.route('/discord/onboarding')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def discord_onboarding():
    """Discord onboarding overview and management - shows all onboarding status."""
    try:
        from sqlalchemy.orm import joinedload
        from app.models import User, Player

        # Get all users with their onboarding/verification status using ORM
        users = db.session.query(User).options(
            joinedload(User.player),
            joinedload(User.roles)
        ).order_by(User.created_at.desc()).limit(100).all()

        # Build overview data showing all onboarding status
        overview_data = []
        stats = {'completed': 0, 'pending_discord': 0, 'pending_approval': 0}

        for u in users:
            has_discord = u.player and u.player.discord_id
            is_verified = u.approval_status == 'approved' or u.is_approved

            # Determine onboarding status
            if has_discord and is_verified:
                status = 'completed'
                stats['completed'] += 1
            elif not has_discord:
                status = 'pending_discord'
                stats['pending_discord'] += 1
            else:
                status = 'pending_approval'
                stats['pending_approval'] += 1

            overview_data.append({
                'id': u.id,
                'username': u.username,
                'email': u.email,
                'discord_id': u.player.discord_id if u.player else None,
                'discord_linked': has_discord,
                'approval_status': u.approval_status or ('approved' if u.is_approved else 'pending'),
                'onboarding_status': status,
                'created_at': u.created_at.isoformat() if u.created_at else None,
                'roles': [r.name for r in u.roles] if u.roles else [],
                'player_name': u.player.name if u.player else None,
                'bot_interaction_status': getattr(u, 'bot_interaction_status', None),
                'last_bot_contact_at': getattr(u, 'last_bot_contact_at', None)
            })

        return render_template('admin_panel/discord/onboarding.html',
                             overview_data=overview_data,
                             stats=stats)
    except Exception as e:
        logger.error(f"Error loading onboarding page: {e}", exc_info=True)
        return render_template('admin_panel/discord/onboarding.html',
                             overview_data=[],
                             stats={'completed': 0, 'pending_discord': 0, 'pending_approval': 0},
                             error=str(e))


@admin_panel_bp.route('/discord/onboarding/api')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def discord_onboarding_api():
    """API endpoint for onboarding status overview."""
    try:
        from sqlalchemy.orm import joinedload
        from app.models import User, Player

        # Get all users with their onboarding/verification status using ORM
        users = db.session.query(User).options(
            joinedload(User.player),
            joinedload(User.roles)
        ).order_by(User.created_at.desc()).limit(100).all()

        # Build overview data
        overview_data = []
        stats = {'completed': 0, 'pending_discord': 0, 'pending_approval': 0}

        for u in users:
            has_discord = u.player and u.player.discord_id
            is_verified = u.approval_status == 'approved' or u.is_approved

            if has_discord and is_verified:
                status = 'completed'
                stats['completed'] += 1
            elif not has_discord:
                status = 'pending_discord'
                stats['pending_discord'] += 1
            else:
                status = 'pending_approval'
                stats['pending_approval'] += 1

            overview_data.append({
                'id': u.id,
                'username': u.username,
                'email': u.email,
                'discord_id': u.player.discord_id if u.player else None,
                'discord_linked': has_discord,
                'approval_status': u.approval_status or ('approved' if u.is_approved else 'pending'),
                'onboarding_status': status,
                'created_at': u.created_at.isoformat() if u.created_at else None,
                'roles': [r.name for r in u.roles] if u.roles else [],
                'player_name': u.player.name if u.player else None
            })

        return jsonify({
            'overview': overview_data,
            'stats': stats,
            'total_count': len(overview_data)
        })

    except Exception as e:
        logger.error(f"Error getting onboarding overview: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@admin_panel_bp.route('/discord/onboarding/retry/<int:user_id>', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def discord_retry_onboarding_contact(user_id):
    """Manually trigger bot contact retry for a user."""
    session = g.db_session
    try:
        user = session.query(User).get(user_id)
        if not user:
            return jsonify({'error': 'User not found'}), 404

        # Reset bot interaction status to allow retry
        user.bot_interaction_status = 'not_contacted'
        user.last_bot_contact_at = None
        session.add(user)
        session.commit()

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='discord_onboarding_retry',
            resource_type='user',
            resource_id=str(user_id),
            new_value=f'Retry enabled for {user.username}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({
            'success': True,
            'message': f'Contact retry enabled for {user.username}'
        })

    except Exception as e:
        session.rollback()
        logger.error(f"Error enabling contact retry: {e}")
        return jsonify({'error': str(e)}), 500


# -----------------------------------------------------------
# Discord Statistics API Routes
# -----------------------------------------------------------

@admin_panel_bp.route('/discord/api/stats')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def discord_stats_api():
    """API endpoint for Discord statistics."""
    session = g.db_session
    try:
        total_players = session.query(Player).filter(Player.discord_id.isnot(None)).count()
        players_in_server = session.query(Player).filter(
            Player.discord_id.isnot(None),
            Player.discord_in_server == True
        ).count()
        players_not_in_server = session.query(Player).filter(
            Player.discord_id.isnot(None),
            Player.discord_in_server == False
        ).count()
        players_unknown = session.query(Player).filter(
            Player.discord_id.isnot(None),
            Player.discord_in_server.is_(None)
        ).count()
        players_needing_sync = session.query(Player).filter(
            Player.discord_id.isnot(None),
            Player.discord_roles_synced == False
        ).count()

        return jsonify({
            'total_players': total_players,
            'in_server': players_in_server,
            'not_in_server': players_not_in_server,
            'unknown_status': players_unknown,
            'needs_sync': players_needing_sync,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Error getting Discord stats: {e}")
        return jsonify({'error': str(e)}), 500
