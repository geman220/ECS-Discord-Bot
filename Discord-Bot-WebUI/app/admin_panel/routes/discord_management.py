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
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from .. import admin_panel_bp
from app.decorators import role_required
from app.utils.db_utils import transactional
from app.models import Player, Team, User, Season, League
from app.models import DiscordRelinkRequest, DiscordRelinkStatus
from app.models.admin_config import AdminAuditLog, AdminConfig
from app.services.discord_relink_service import (
    apply_discord_id,
    clear_discord_id,
    sync_roles_after_relink,
    RelinkError,
)
from app.tasks.tasks_discord import (
    update_player_discord_roles,
    fetch_role_status,
    process_discord_role_updates
)

logger = logging.getLogger(__name__)


# -----------------------------------------------------------
# Discord Onboarding "Approval Gate" configuration
# -----------------------------------------------------------
# These are stored as generic AdminConfig key/value rows (category
# 'onboarding') so no schema change is required. The reminder-window choices
# are constrained to a fixed allow-list; anything else is rejected on save.
ONBOARDING_REMINDER_WINDOWS = ['24h', '48h', '72h', '1w', '2w', 'never']

ONBOARDING_CONFIG_KEYS = {
    'onboarding_auto_approve_linked': {
        'description': 'Auto-approve members once their Discord ID is verified (skip manual review).',
        'data_type': 'boolean',
        'default': 'false',
    },
    'onboarding_approval_notify_channel': {
        'description': 'Discord channel name used for approval notifications.',
        'data_type': 'string',
        'default': '',
    },
    'onboarding_reminder_window': {
        'description': 'How long a signup can sit pending before the weekly reminder mentions them (24h/48h/72h/1w/2w/never).',
        'data_type': 'string',
        'default': 'never',
    },
}


def _load_onboarding_config():
    """Read the onboarding approval-gate settings from AdminConfig.

    Returns a plain dict the template can render directly. Reads are defensive:
    AdminConfig.get_setting already swallows DB errors and returns the default.
    """
    reminder = AdminConfig.get_setting('onboarding_reminder_window', 'never')
    if reminder not in ONBOARDING_REMINDER_WINDOWS:
        reminder = 'never'
    return {
        'auto_approve_linked': bool(AdminConfig.get_setting('onboarding_auto_approve_linked', False)),
        'approval_notify_channel': AdminConfig.get_setting('onboarding_approval_notify_channel', '') or '',
        'reminder_window': reminder,
    }


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

        return render_template('admin_panel/discord/overview_flowbite.html', stats=stats)
    except Exception as e:
        logger.error(f"Error loading Discord overview: {e}")
        return render_template('admin_panel/discord/overview_flowbite.html',
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
        search_query = request.args.get('search', '').strip()
        team_filter = request.args.get('team', None, type=int)
        sort_by = request.args.get('sort', 'last_checked')
        sort_dir = request.args.get('sort_dir', 'asc')

        per_page = max(10, min(per_page, 100))

        # Get current seasons for team filtering
        current_seasons = session.query(Season).filter(Season.is_current == True).all()
        current_season_ids = [season.id for season in current_seasons]

        # Get current teams for filter dropdown
        current_teams = session.query(Team).join(Team.league).join(League.season).filter(
            Season.is_current == True
        ).order_by(Team.name).all()

        # Base query for players with Discord IDs
        base_query = session.query(Player).options(
            joinedload(Player.teams).joinedload(Team.league).joinedload(League.season),
            joinedload(Player.user)
        ).filter(Player.discord_id.isnot(None))

        # Get all players for statistics (before search/team filter)
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
            'unknown_status': sum(1 for p in all_players if p.discord_in_server is None),
            # Counted separately -- these players are excluded from base_query
            # by definition, but they are the ones an admin needs to FIND in
            # order to link a Discord account for the first time (or after a
            # recovery unlink).
            'unlinked': session.query(func.count(Player.id)).filter(
                Player.discord_id.is_(None)
            ).scalar() or 0,
        }

        # Apply status filter
        section_titles = {
            'not_in_server': 'Players Not In Discord Server',
            'unknown': 'Players with Unknown Discord Status',
            'in_server': 'Players In Discord Server',
            'unlinked': 'Players With No Discord Linked',
            'all': 'All Players with Discord'
        }

        if status_filter == 'not_in_server':
            filtered_query = base_query.filter(Player.discord_in_server == False)
        elif status_filter == 'unknown':
            filtered_query = base_query.filter(Player.discord_in_server.is_(None))
        elif status_filter == 'in_server':
            filtered_query = base_query.filter(Player.discord_in_server == True)
        elif status_filter == 'unlinked':
            # Deliberately NOT built on base_query, which requires a Discord ID.
            # Without this branch a player with no Discord is invisible on the
            # only page that can link one -- so unlinking someone (or anyone who
            # never linked) became unreachable, which is exactly backwards for
            # account recovery.
            filtered_query = session.query(Player).options(
                joinedload(Player.teams).joinedload(Team.league).joinedload(League.season),
                joinedload(Player.user)
            ).filter(Player.discord_id.is_(None))
        else:
            filtered_query = base_query

        current_section = section_titles.get(status_filter, 'All Players with Discord')

        # Apply search filter
        if search_query:
            search_pattern = f'%{search_query}%'
            filtered_query = filtered_query.filter(
                (Player.name.ilike(search_pattern)) |
                (Player.discord_id.ilike(search_pattern)) |
                (Player.discord_username.ilike(search_pattern)) |
                (Player.user.has(User.username.ilike(search_pattern)))
            )

        # Apply team filter
        if team_filter:
            filtered_query = filtered_query.filter(
                Player.teams.any(Team.id == team_filter)
            )

        # Apply sorting
        if sort_by == 'name':
            order_col = Player.name.asc() if sort_dir == 'asc' else Player.name.desc()
            filtered_query = filtered_query.order_by(order_col)
        elif sort_by == 'status':
            order_col = Player.discord_in_server.asc() if sort_dir == 'asc' else Player.discord_in_server.desc()
            filtered_query = filtered_query.order_by(order_col)
        else:
            # Default: last_checked
            if sort_dir == 'desc':
                filtered_query = filtered_query.order_by(
                    Player.discord_last_checked.nulls_last(),
                    Player.discord_last_checked.desc()
                )
            else:
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

        return render_template('admin_panel/discord/players_flowbite.html',
                             stats=stats,
                             players=players,
                             pagination=pagination,
                             status_filter=status_filter,
                             current_section=current_section,
                             per_page=per_page,
                             player_current_teams=player_current_teams,
                             search_query=search_query,
                             team_filter=team_filter,
                             sort_by=sort_by,
                             sort_dir=sort_dir,
                             current_teams=current_teams)

    except Exception as e:
        logger.error(f"Error loading Discord players page: {e}")
        return render_template('admin_panel/discord/players_flowbite.html',
                             stats={'total_players': 0, 'in_server': 0, 'not_in_server': 0,
                                    'unknown_status': 0, 'unlinked': 0},
                             players=[],
                             pagination={'has_prev': False, 'prev_num': None, 'page': 1,
                                        'has_next': False, 'next_num': None, 'pages': 1,
                                        'total': 0, 'per_page': 20},
                             status_filter='not_in_server',
                             current_section='Players Not In Discord Server',
                             per_page=20,
                             player_current_teams={},
                             search_query='',
                             team_filter=None,
                             sort_by='last_checked',
                             sort_dir='asc',
                             current_teams=[],
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
        # Base query: players with a linked Discord account whose roles are not synced
        needing_sync_query = session.query(Player).filter(
            Player.discord_id.isnot(None),
            Player.discord_roles_synced == False
        )

        # KPI count for the stat cards / sync buttons
        players_needing_sync = needing_sync_query.count()

        # Actual rows for the "Players Needing Sync" table (cap to keep the
        # page light; the bulk sync action still operates on every player).
        players_needing_sync_list = (
            needing_sync_query
            .order_by(Player.name.asc())
            .limit(100)
            .all()
        )

        players_needs_update = session.query(Player).filter(
            Player.discord_id.isnot(None),
            Player.discord_needs_update == True
        ).count()

        return render_template('admin_panel/discord/roles_flowbite.html',
                             players_needing_sync=players_needing_sync,
                             players_needing_sync_list=players_needing_sync_list,
                             players_needs_update=players_needs_update)
    except Exception as e:
        logger.error(f"Error loading Discord roles page: {e}")
        return render_template('admin_panel/discord/roles_flowbite.html',
                             players_needing_sync=0,
                             players_needing_sync_list=[],
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
        return jsonify({'state': 'ERROR', 'error': 'Internal Server Error'}), 500


@admin_panel_bp.route('/discord/roles/update-player/<int:player_id>', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def discord_update_player_roles(player_id):
    """Queue a Discord role update for one player (runs in the background)."""
    try:
        # Fire-and-forget: queue the task and return immediately instead of
        # blocking the web worker on .get(timeout=30). The JS caller only reads
        # success/error, not the task result, so nothing downstream needs the wait.
        update_player_discord_roles.delay(player_id)

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='discord_role_update',
            resource_type='player',
            resource_id=str(player_id),
            new_value="Role update queued",
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({
            'success': True,
            'message': 'Role sync queued — updates apply in the background.'
        })
    except Exception as e:
        logger.error(f"Error queuing role update for player {player_id}: {e}")
        return jsonify({'success': False, 'error': 'Internal Server Error'}), 500


@admin_panel_bp.route('/discord/players/<int:player_id>/update-discord-id', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def discord_update_player_discord_id(player_id):
    """Update or unlink a player's Discord ID.

    The actual relink lives in ``app.services.discord_relink_service`` so this
    route and the Account Recovery queue cannot drift apart.

    ``take_from_other`` lets an admin pull the ID off a player that already
    holds it -- the duplicate-account case that otherwise deadlocks recovery.
    Off unless explicitly requested, so the default is still a loud 409.
    """
    session = g.db_session
    player = session.query(Player).get(player_id)
    if not player:
        return jsonify({'success': False, 'error': 'Player not found'}), 404

    # A body is REQUIRED here. Defaulting to {} would make `discord_id` absent,
    # which the unlink branch below reads as "clear this player's Discord ID" —
    # so a bodyless POST would silently unlink instead of erroring. Unlinking
    # must be an explicit `{"discord_id": null}`, never an omission.
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({'success': False, 'error': 'A JSON request body is required'}), 400
    new_discord_id = data.get('discord_id')

    # Unlink case
    if new_discord_id is None:
        clear_discord_id(
            session, player,
            actor_user_id=current_user.id,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent'),
        )
        return jsonify({
            'success': True,
            'message': f'Discord ID unlinked from {player.name}'
        })

    try:
        result = apply_discord_id(
            session, player, new_discord_id,
            actor_user_id=current_user.id,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent'),
            take_from_other=bool(data.get('take_from_other')),
        )
    except RelinkError as e:
        payload = {'success': False, 'error': e.message}
        payload.update(e.details)
        return jsonify(payload), e.code

    # Commit before dispatching so the Celery worker reads the NEW discord_id.
    session.commit()

    role_sync_message = sync_roles_after_relink(player.id, wait_seconds=30)
    displaced = result['displaced_player_name']
    displaced_note = f' Unlinked from {displaced} first.' if displaced else ''

    return jsonify({
        'success': True,
        'message': f"Discord ID updated for {result['player_name']}.{displaced_note} {role_sync_message}"
    })


# -----------------------------------------------------------
# Account Recovery queue (blocked Discord relink attempts)
# -----------------------------------------------------------
# Discord OAuth is the only way into the portal, so a member who loses their
# Discord account cannot self-serve back in. The identity matcher refuses
# their new Discord (correctly -- it is indistinguishable from a hijack), and
# that refusal now lands here instead of dead-ending at "contact an admin".

@admin_panel_bp.route('/discord/account-recovery')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def discord_account_recovery():
    """Review queue of Discord logins that were refused as possible relinks."""
    session = g.db_session

    pending = session.query(DiscordRelinkRequest).filter(
        DiscordRelinkRequest.status == DiscordRelinkStatus.PENDING
    ).order_by(DiscordRelinkRequest.last_seen_at.desc()).all()

    resolved = session.query(DiscordRelinkRequest).filter(
        DiscordRelinkRequest.status != DiscordRelinkStatus.PENDING
    ).order_by(DiscordRelinkRequest.resolved_at.desc()).limit(25).all()

    # The ambiguous case has no single candidate -- the admin picks from a
    # list, so resolve those player rows for display in one query.
    ambiguous_ids = set()
    for req in pending:
        ambiguous_ids.update(req.candidate_player_id_list)
    candidate_players = {}
    if ambiguous_ids:
        for player in session.query(Player).options(
            joinedload(Player.user)
        ).filter(Player.id.in_(ambiguous_ids)).all():
            candidate_players[player.id] = player

    return render_template(
        'admin_panel/discord/account_recovery_flowbite.html',
        title='Account Recovery',
        pending_requests=pending,
        resolved_requests=resolved,
        candidate_players=candidate_players,
    )


@admin_panel_bp.route('/discord/account-recovery/<int:request_id>/approve', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def discord_account_recovery_approve(request_id):
    """Move the requested Discord ID onto the member's real player row.

    ``player_id`` in the body overrides the detected candidate -- required for
    the ambiguous case, where by definition we refused to guess.
    """
    session = g.db_session
    relink_request = session.query(DiscordRelinkRequest).get(request_id)
    if not relink_request:
        return jsonify({'success': False, 'error': 'Request not found'}), 404
    if not relink_request.is_pending:
        return jsonify({
            'success': False,
            'error': f'This request was already {relink_request.status}.'
        }), 409

    data = request.get_json(silent=True) or {}
    target_player_id = data.get('player_id') or relink_request.candidate_player_id
    if not target_player_id:
        return jsonify({
            'success': False,
            'error': 'No player selected. Pick which account this Discord belongs to.'
        }), 400

    player = session.query(Player).get(int(target_player_id))
    if not player:
        return jsonify({'success': False, 'error': 'Player not found'}), 404

    # Guard the ambiguous case: only players the matcher itself surfaced are
    # selectable, so a typo cannot hand someone's account to the wrong person.
    allowed = set(relink_request.candidate_player_id_list)
    if relink_request.candidate_player_id:
        allowed.add(relink_request.candidate_player_id)
    if allowed and player.id not in allowed:
        return jsonify({
            'success': False,
            'error': 'That player is not one of the candidates for this request.'
        }), 400

    try:
        result = apply_discord_id(
            session, player, relink_request.requested_discord_id,
            actor_user_id=current_user.id,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent'),
            take_from_other=bool(data.get('take_from_other')),
            reason=f'account recovery request #{relink_request.id}',
        )
    except RelinkError as e:
        payload = {'success': False, 'error': e.message}
        payload.update(e.details)
        return jsonify(payload), e.code

    note = data.get('note') or ''
    relink_request.resolve(
        DiscordRelinkStatus.APPROVED,
        current_user.id,
        note=(f'Relinked to player {player.id} ({player.name}). {note}').strip(),
    )

    AdminAuditLog.log_action(
        user_id=current_user.id,
        action='discord_relink_approved',
        resource_type='discord_relink_request',
        resource_id=str(relink_request.id),
        old_value=result['old_discord_id'],
        new_value=result['new_discord_id'],
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent'),
    )

    # Commit before dispatching so the Celery worker reads the NEW discord_id.
    session.commit()

    role_sync_message = sync_roles_after_relink(player.id, wait_seconds=30)
    displaced = result['displaced_player_name']
    displaced_note = f' Unlinked from {displaced} first.' if displaced else ''

    return jsonify({
        'success': True,
        'message': (
            f"{player.name} is now linked to the new Discord account."
            f"{displaced_note} {role_sync_message} "
            f"Tell them to log in with it."
        )
    })


@admin_panel_bp.route('/discord/account-recovery/<int:request_id>/reject', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def discord_account_recovery_reject(request_id):
    """Dismiss a request -- either a genuine hijack attempt or already handled."""
    session = g.db_session
    relink_request = session.query(DiscordRelinkRequest).get(request_id)
    if not relink_request:
        return jsonify({'success': False, 'error': 'Request not found'}), 404
    if not relink_request.is_pending:
        return jsonify({
            'success': False,
            'error': f'This request was already {relink_request.status}.'
        }), 409

    data = request.get_json(silent=True) or {}
    relink_request.resolve(
        DiscordRelinkStatus.REJECTED,
        current_user.id,
        note=data.get('note') or 'Dismissed by admin.',
    )

    AdminAuditLog.log_action(
        user_id=current_user.id,
        action='discord_relink_rejected',
        resource_type='discord_relink_request',
        resource_id=str(relink_request.id),
        old_value=relink_request.requested_discord_id,
        new_value=relink_request.resolution_note,
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent'),
    )

    return jsonify({'success': True, 'message': 'Request dismissed.'})


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
        return jsonify({'success': False, 'error': 'Internal Server Error'}), 500


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
        return jsonify({'success': False, 'error': 'Internal Server Error'}), 500


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
        return jsonify({'success': False, 'error': 'Internal Server Error'}), 500


# -----------------------------------------------------------
# Discord Onboarding Routes
# -----------------------------------------------------------

@admin_panel_bp.route('/discord/onboarding')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def discord_onboarding():
    """Discord onboarding overview and management - shows all onboarding status."""
    session = g.db_session
    try:
        # Get all users with their onboarding/verification status using ORM
        users = session.query(User).options(
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

        return render_template('admin_panel/discord/onboarding_flowbite.html',
                             overview_data=overview_data,
                             stats=stats,
                             onboarding_config=_load_onboarding_config(),
                             reminder_windows=ONBOARDING_REMINDER_WINDOWS)
    except Exception as e:
        logger.error(f"Error loading onboarding page: {e}", exc_info=True)
        # Still surface the (defensive) config so the settings panel renders.
        try:
            cfg = _load_onboarding_config()
        except Exception:
            cfg = {'auto_approve_linked': False, 'approval_notify_channel': '', 'reminder_window': 'never'}
        return render_template('admin_panel/discord/onboarding_flowbite.html',
                             overview_data=[],
                             stats={'completed': 0, 'pending_discord': 0, 'pending_approval': 0},
                             onboarding_config=cfg,
                             reminder_windows=ONBOARDING_REMINDER_WINDOWS,
                             error=str(e))


@admin_panel_bp.route('/discord/onboarding/api')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def discord_onboarding_api():
    """API endpoint for onboarding status overview."""
    session = g.db_session
    try:
        # Get all users with their onboarding/verification status using ORM
        users = session.query(User).options(
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
        return jsonify({'error': 'Internal Server Error'}), 500


@admin_panel_bp.route('/discord/onboarding/retry/<int:user_id>', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def discord_retry_onboarding_contact(user_id):
    """Manually trigger bot contact retry for a user."""
    session = g.db_session
    user = session.query(User).get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    # Reset bot interaction status to allow retry
    user.bot_interaction_status = 'not_contacted'
    user.last_bot_contact_at = None
    session.add(user)

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


@admin_panel_bp.route('/discord/onboarding/config', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def discord_save_onboarding_config():
    """Save the onboarding approval-gate settings to AdminConfig.

    Accepts a JSON body with any subset of:
      - auto_approve_linked  (bool)
      - approval_notify_channel (str; trimmed, max 100 chars)
      - reminder_window (one of ONBOARDING_REMINDER_WINDOWS)
    Validates each field before persisting. Unknown/invalid values are rejected.
    """
    data = request.get_json(silent=True) or {}

    changes = []

    # auto_approve_linked (boolean)
    if 'auto_approve_linked' in data:
        new_value = 'true' if bool(data.get('auto_approve_linked')) else 'false'
        meta = ONBOARDING_CONFIG_KEYS['onboarding_auto_approve_linked']
        AdminConfig.set_setting(
            key='onboarding_auto_approve_linked', value=new_value,
            description=meta['description'], category='onboarding',
            data_type=meta['data_type'], user_id=current_user.id,
        )
        changes.append(f"auto_approve_linked={new_value}")

    # approval_notify_channel (string, optional, capped length)
    if 'approval_notify_channel' in data:
        channel = (data.get('approval_notify_channel') or '').strip()[:100]
        meta = ONBOARDING_CONFIG_KEYS['onboarding_approval_notify_channel']
        AdminConfig.set_setting(
            key='onboarding_approval_notify_channel', value=channel,
            description=meta['description'], category='onboarding',
            data_type=meta['data_type'], user_id=current_user.id,
        )
        changes.append(f"approval_notify_channel={channel or '(none)'}")

    # reminder_window (constrained allow-list)
    if 'reminder_window' in data:
        window = (data.get('reminder_window') or '').strip()
        if window not in ONBOARDING_REMINDER_WINDOWS:
            return jsonify({
                'success': False,
                'error': f"Invalid reminder window. Must be one of: {', '.join(ONBOARDING_REMINDER_WINDOWS)}"
            }), 400
        meta = ONBOARDING_CONFIG_KEYS['onboarding_reminder_window']
        AdminConfig.set_setting(
            key='onboarding_reminder_window', value=window,
            description=meta['description'], category='onboarding',
            data_type=meta['data_type'], user_id=current_user.id,
        )
        changes.append(f"reminder_window={window}")

    if not changes:
        return jsonify({'success': False, 'error': 'No valid settings provided'}), 400

    AdminAuditLog.log_action(
        user_id=current_user.id,
        action='discord_onboarding_config_update',
        resource_type='admin_config',
        resource_id='onboarding',
        new_value='; '.join(changes),
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent')
    )

    return jsonify({
        'success': True,
        'message': 'Onboarding flow settings saved',
        'config': _load_onboarding_config()
    })


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
        return jsonify({'error': 'Internal Server Error'}), 500


# -----------------------------------------------------------
# Discord Role Mapping Routes
# -----------------------------------------------------------

@admin_panel_bp.route('/discord/role-mapping')
@login_required
@role_required(['Global Admin'])
def discord_role_mapping():
    """Legacy Discord role-mapping page — folded into the Access Control center.

    Mapping now lives at Access Control → Discord mapping (alongside Roles &
    Permissions, which all edit the same Role). The endpoint name is kept so any
    lingering link lands on the new surface. The mapping action endpoints below
    (update/auto-map/sync/preview/create-role) are unchanged — the Access Control
    page calls them directly.
    """
    return redirect(url_for('admin_panel.access_control', tab='discord'))


@admin_panel_bp.route('/discord/role-mapping/update', methods=['POST'])
@login_required
@role_required(['Global Admin'])
@transactional
def update_role_mapping():
    """Update the Discord role mapping for a Flask role."""
    from app.models import Role

    session = g.db_session
    data = request.json

    role_id = data.get('role_id')
    discord_role_id = data.get('discord_role_id')
    discord_role_name = data.get('discord_role_name')
    sync_enabled = data.get('sync_enabled', True)

    role = session.query(Role).get(role_id)
    if not role:
        return jsonify({'success': False, 'error': 'Role not found'}), 404

    role.discord_role_id = discord_role_id if discord_role_id else None
    role.discord_role_name = discord_role_name if discord_role_name else None
    role.sync_enabled = sync_enabled
    role.last_synced_at = datetime.utcnow()

    # Log the action
    AdminAuditLog.log_action(
        user_id=current_user.id,
        action='update_role_mapping',
        resource_type='role',
        resource_id=str(role_id),
        new_value=f"Discord role: {discord_role_name} ({discord_role_id})",
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent')
    )

    return jsonify({
        'success': True,
        'message': f'Role "{role.name}" mapped to Discord role "{discord_role_name}"'
    })


@admin_panel_bp.route('/discord/role-mapping/auto-map', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def auto_map_role_mapping():
    """Auto-fill Flask->Discord role mappings from live Discord roles.

    Fetches the live Discord role list from the bot and matches each Flask role
    to its Discord counterpart by name (using the canonical mapping table).
    POST body {apply: false} returns a dry-run preview; {apply: true} persists.

    Note: intentionally NOT @transactional. The Discord fetch is a multi-second
    blocking HTTP call to the bot; we must do it BEFORE opening any DB
    transaction, then commit the (short) write phase explicitly. Wrapping the
    whole view in a transaction would hold a PgBouncer slot across the HTTP call
    and re-issue the HTTP request on the decorator's retry loop.
    """
    from app.services.discord_role_sync_service import (
        fetch_discord_roles_sync, auto_map_flask_roles
    )

    session = g.db_session
    data = request.get_json(silent=True) or {}
    apply = bool(data.get('apply', False))

    # --- HTTP phase: fetch live Discord roles BEFORE touching the DB. ---
    try:
        discord_roles = fetch_discord_roles_sync()
    except Exception as e:
        logger.warning(f"Auto-map could not fetch Discord roles: {e}")
        discord_roles = []

    if not discord_roles:
        return jsonify({
            'success': False,
            'error': 'Discord bot is offline or returned no roles. Cannot auto-map.'
        }), 503

    # --- DB phase: match and (optionally) persist, then commit explicitly. ---
    try:
        result = auto_map_flask_roles(session, discord_roles, apply=apply)
        if apply:
            session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"Auto-map failed during DB phase: {e}")
        return jsonify({'success': False, 'error': 'Internal Server Error'}), 500

    if apply:
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='auto_map_role_mapping',
            resource_type='role',
            resource_id='*',
            new_value=(f"Auto-mapped {result.get('applied', 0)} roles "
                       f"({result.get('matched', 0)} matched, "
                       f"{result.get('app_only', 0)} app-only, "
                       f"{result.get('unmatched', 0)} unmatched)"),
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

    return jsonify(result)


@admin_panel_bp.route('/discord/role-mapping/sync', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def sync_role_to_discord():
    """Sync a Flask role to Discord - assign/remove Discord role for all users with this role."""
    from app.models import Role
    from app.services.discord_role_sync_service import get_discord_role_sync_service

    session = g.db_session
    data = request.json

    role_id = data.get('role_id')

    try:
        role = session.query(Role).get(role_id)
        if not role:
            return jsonify({'success': False, 'error': 'Role not found'}), 404

        if not role.discord_role_id:
            return jsonify({'success': False, 'error': 'No Discord role mapped'}), 400

        # Use the sync service for the operation (synchronous; gevent-safe)
        service = get_discord_role_sync_service()

        result = service.sync_flask_role_to_discord(role)

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='sync_role_to_discord',
            resource_type='role',
            resource_id=str(role_id),
            new_value=f"Synced {result.get('synced', 0)} users, {result.get('failed', 0)} errors",
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({
            'success': result.get('success', False),
            'message': f"Synced {result.get('synced', 0)} users to Discord role",
            'summary': {
                'total': result.get('total_users', 0),
                'success': result.get('synced', 0),
                'skipped': result.get('skipped', 0),
                'errors': result.get('failed', 0)
            }
        })

    except Exception as e:
        logger.error(f"Error syncing role to Discord: {e}")
        return jsonify({'success': False, 'error': 'Internal Server Error'}), 500


@admin_panel_bp.route('/discord/role-mapping/preview/<int:role_id>')
@login_required
@role_required(['Global Admin'])
def preview_role_sync(role_id):
    """Preview which users would be affected by syncing a role."""
    from app.services.discord_role_sync_service import get_discord_role_sync_service

    try:
        service = get_discord_role_sync_service()
        result = service.preview_role_sync(role_id)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error previewing role sync: {e}")
        return jsonify({'success': False, 'error': 'Internal Server Error'}), 500


@admin_panel_bp.route('/discord/role-mapping/create-role', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def create_discord_role():
    """
    Create a new Discord role on the server via the bot API.

    This allows admins to create Discord roles directly from the admin panel
    without having to go to Discord's server settings.
    """
    import os
    import requests

    try:
        data = request.get_json()
        role_name = data.get('name', '').strip()
        role_color = data.get('color', '#7C3AED')
        mentionable = data.get('mentionable', False)

        if not role_name:
            return jsonify({'success': False, 'error': 'Role name is required'}), 400

        # Get bot API URL and guild ID
        bot_api_url = os.getenv('BOT_API_URL', 'http://discord-bot:5001')
        guild_id = os.getenv('SERVER_ID')

        if not guild_id:
            return jsonify({'success': False, 'error': 'SERVER_ID not configured'}), 500

        # Convert hex color to Discord color integer (remove # and convert to int)
        color_int = 0
        if role_color and role_color.startswith('#'):
            try:
                color_int = int(role_color[1:], 16)
            except ValueError:
                color_int = 0

        # Call bot API to create the role
        response = requests.post(
            f"{bot_api_url}/api/server/guilds/{guild_id}/roles",
            json={
                'name': role_name,
                'color': color_int,
                'mentionable': mentionable
            },
            timeout=15
        )

        if response.status_code == 200:
            result = response.json()
            logger.info(f"Created Discord role '{role_name}' with ID {result.get('id')}")
            return jsonify({
                'success': True,
                'role_id': result.get('id'),
                'role_name': role_name,
                'message': f"Discord role '{role_name}' created successfully"
            })
        else:
            error_msg = response.text
            logger.error(f"Bot API error creating role: {response.status_code} - {error_msg}")
            return jsonify({
                'success': False,
                'error': f"Bot API error: {error_msg}"
            }), response.status_code

    except requests.exceptions.Timeout:
        logger.error("Timeout connecting to bot API")
        return jsonify({'success': False, 'error': 'Bot API timeout - is the bot running?'}), 504
    except requests.exceptions.ConnectionError:
        logger.error("Connection error to bot API")
        return jsonify({'success': False, 'error': 'Cannot connect to bot - is it running?'}), 503
    except Exception as e:
        logger.error(f"Error creating Discord role: {e}")
        return jsonify({'success': False, 'error': 'Internal Server Error'}), 500
