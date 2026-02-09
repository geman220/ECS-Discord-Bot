# app/admin_panel/routes/user_management/comprehensive.py

"""
Comprehensive User Management Routes

Routes for comprehensive user management:
- Comprehensive user listing page
- User edit/update operations
- Quick approve/deactivate actions
- Bulk actions from comprehensive view
"""

import logging
from datetime import datetime, timedelta

from flask import render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import or_
from sqlalchemy.orm import joinedload

from app.admin_panel import admin_panel_bp
from app.core import db
from app.models.admin_config import AdminAuditLog
from app.models.core import User, Role, League
from app.models import Player, Team, Season
from app.models.players import PlayerTeamHistory, PlayerTeamSeason
from app.models.ecs_fc import is_ecs_fc_team
from app.decorators import role_required
from app.utils.db_utils import transactional
from app.utils.user_locking import lock_user_for_role_update, LockAcquisitionError
from app.utils.deferred_discord import defer_discord_sync, defer_discord_removal, execute_deferred_discord, clear_deferred_discord, DeferredDiscordQueue
from app.tasks.tasks_discord import assign_roles_to_player_task, remove_player_roles_task

logger = logging.getLogger(__name__)

# Mapping from league names to role names
LEAGUE_TO_ROLE_MAP = {
    'classic': 'pl-classic',
    'premier': 'pl-premier',
    'ecs fc': 'pl-ecs-fc',
    'ecs-fc': 'pl-ecs-fc',
}

# Mapping from league names to sub role names
LEAGUE_TO_SUB_ROLE_MAP = {
    'classic': 'Classic Sub',
    'premier': 'Premier Sub',
    'ecs fc': 'ECS FC Sub',
    'ecs-fc': 'ECS FC Sub',
}

# All league-related roles that should be managed (including subs)
LEAGUE_ROLES = ['pl-classic', 'pl-premier', 'pl-ecs-fc']
SUB_ROLES = ['Classic Sub', 'Premier Sub', 'ECS FC Sub']
ALL_LEAGUE_RELATED_ROLES = LEAGUE_ROLES + SUB_ROLES


def get_role_for_league(league):
    """Get the appropriate role name for a league."""
    if not league:
        return None
    league_name = league.name.lower().strip()
    return LEAGUE_TO_ROLE_MAP.get(league_name)


# Mapping from DB league names to draft room names used by SocketIO
DB_LEAGUE_TO_DRAFT_ROOM = {
    'classic': 'classic',
    'premier': 'premier',
    'ecs fc': 'ecs_fc',
}


def _build_player_socket_data(player):
    """Build player data dict for draft page socket emission."""
    return {
        'id': player.id,
        'name': player.name,
        'profile_picture_url': player.profile_picture_url or '/static/img/default_player.png',
        'profile_picture_medium': getattr(player, 'profile_picture_medium', None) or player.profile_picture_url or '/static/img/default_player.png',
        'profile_picture_webp': getattr(player, 'profile_picture_webp', None) or player.profile_picture_url or '/static/img/default_player.png',
        'favorite_position': player.favorite_position or 'Any',
        'other_positions': player.other_positions or '',
        'positions_not_to_play': player.positions_not_to_play or '',
        'career_goals': player.career_stats[0].goals if player.career_stats else 0,
        'career_assists': player.career_stats[0].assists if player.career_stats else 0,
        'career_yellow_cards': player.career_stats[0].yellow_cards if player.career_stats else 0,
        'career_red_cards': player.career_stats[0].red_cards if player.career_stats else 0,
        'league_experience_seasons': 0,
        'attendance_estimate': 75,
        'experience_level': 'New Player',
        'current_position': 'bench',
    }


@admin_panel_bp.route('/users/manage')
@admin_panel_bp.route('/users-management')  # Alias for template compatibility
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def users_comprehensive():
    """Comprehensive user management page."""
    try:
        # Get filter parameters
        search = request.args.get('search', '').strip()
        role_filter = request.args.get('role', '').strip()
        approved_filter = request.args.get('approved', '').strip()
        active_filter = request.args.get('active', '').strip()
        league_filter = request.args.get('league', '').strip()
        page = request.args.get('page', 1, type=int)
        per_page = 50

        # Build query with eager loading
        query = User.query.options(
            joinedload(User.roles),
            joinedload(User.player)
        )

        # Apply filters
        if search:
            search_term = f'%{search}%'
            # Note: User.email is encrypted, so we can only search username with ILIKE
            # For exact email match, we check the email_hash
            # Player.name IS a real column and can be searched with ILIKE
            from app.utils.pii_encryption import create_hash
            email_hash = create_hash(search.lower()) if '@' in search else None

            if email_hash:
                # If search looks like an email, try exact match via hash
                query = query.filter(
                    or_(
                        User.username.ilike(search_term),
                        User.email_hash == email_hash
                    )
                )
            else:
                # Search by real name (Player.name) and username
                # Use outerjoin with explicit condition to avoid conflict with joinedload
                query = query.outerjoin(Player, Player.user_id == User.id).filter(
                    or_(
                        Player.name.ilike(search_term),
                        User.username.ilike(search_term)
                    )
                )

        if role_filter:
            query = query.join(User.roles).filter(Role.name == role_filter)

        if approved_filter:
            if approved_filter == 'true':
                query = query.filter(User.is_approved == True)
            elif approved_filter == 'false':
                query = query.filter(
                    or_(User.is_approved == False, User.is_approved == None)
                )

        if active_filter:
            if active_filter == 'true':
                query = query.filter(User.is_active == True)
            elif active_filter == 'false':
                query = query.filter(
                    or_(User.is_active == False, User.is_active == None)
                )

        # Order and paginate
        query = query.order_by(User.username)
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        users = pagination.items

        # Get all roles and leagues for filter dropdowns
        all_roles = Role.query.order_by(Role.name).all()
        # Get leagues from current seasons only, with teams eager-loaded for the edit form
        all_leagues = League.query.options(
            joinedload(League.teams)
        ).join(Season).filter(Season.is_current == True).order_by(League.name).all()

        # Calculate statistics (for stat cards)
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        stats = {
            'total_users': User.query.count(),
            'active_users': User.query.filter(User.is_active == True).count(),
            'approved_users': User.query.filter(User.is_approved == True).count(),
            'pending_approval': User.query.filter(
                or_(User.is_approved == False, User.is_approved == None)
            ).count(),
            'recent_registrations': User.query.filter(
                User.created_at >= thirty_days_ago
            ).count(),
            'total_roles': len(all_roles)
        }

        return render_template('admin_panel/users/manage_users_comprehensive_flowbite.html',
                               users=users,
                               roles=all_roles,
                               Role=Role,  # Pass Role model for template
                               stats=stats,
                               pagination=pagination,
                               leagues=all_leagues,
                               search=search,
                               role_filter=role_filter,
                               approved_filter=approved_filter,
                               active_filter=active_filter,
                               league_filter=league_filter)
    except Exception as e:
        logger.error(f"Error loading user management: {e}")
        flash('User management unavailable. Verify database connection and user models.', 'error')
        return redirect(url_for('admin_panel.user_management'))


@admin_panel_bp.route('/users/update-status', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def update_user_status():
    """Update user approval status via AJAX."""
    user_id = request.form.get('user_id')
    status = request.form.get('status')

    if not all([user_id, status]):
        return jsonify({'success': False, 'message': 'Missing required parameters'})

    if status not in ['approved', 'pending', 'denied']:
        return jsonify({'success': False, 'message': 'Invalid status'})

    user = User.query.options(joinedload(User.player)).get_or_404(user_id)
    old_status = user.approval_status
    user.approval_status = status

    # Also update is_approved based on status
    if status == 'approved':
        user.is_approved = True
    elif status == 'pending':
        user.is_approved = None  # Reset to pending state
    elif status == 'denied':
        user.is_approved = False

    # Trigger Discord sync based on status change
    if user.player and user.player.discord_id:
        if status == 'approved':
            assign_roles_to_player_task.delay(player_id=user.player.id, only_add=False)
            logger.info(f"Triggered Discord role sync for approved user {user.id}")
        elif status == 'denied':
            remove_player_roles_task.delay(player_id=user.player.id)
            logger.info(f"Triggered Discord role removal for denied user {user.id}")
        elif status == 'pending':
            # Remove roles when set back to pending
            remove_player_roles_task.delay(player_id=user.player.id)
            logger.info(f"Triggered Discord role removal for pending user {user.id}")

    # Log the action
    AdminAuditLog.log_action(
        user_id=current_user.id,
        action='update_user_status',
        resource_type='user_management',
        resource_id=str(user_id),
        old_value=old_status,
        new_value=status,
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent')
    )

    return jsonify({'success': True, 'message': f'User status updated to {status}'})


@admin_panel_bp.route('/users/update-active', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def update_user_active():
    """Update user active status via AJAX."""
    user_id = request.form.get('user_id')
    active = request.form.get('active', 'false').lower() == 'true'

    if not user_id:
        return jsonify({'success': False, 'message': 'User ID is required'})

    user = User.query.options(joinedload(User.player)).get_or_404(user_id)
    old_active = user.is_active
    user.is_active = active

    # Also update player.is_current_player to stay in sync
    if user.player:
        user.player.is_current_player = active

    # Trigger Discord sync based on active status change
    if user.player and user.player.discord_id:
        if active:
            assign_roles_to_player_task.delay(player_id=user.player.id, only_add=False)
            logger.info(f"Triggered Discord role sync for activated user {user.id}")
        else:
            remove_player_roles_task.delay(player_id=user.player.id)
            logger.info(f"Triggered Discord role removal for deactivated user {user.id}")

    # Log the action
    AdminAuditLog.log_action(
        user_id=current_user.id,
        action='update_user_active',
        resource_type='user_management',
        resource_id=str(user_id),
        old_value=str(old_active),
        new_value=str(active),
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent')
    )

    action_word = 'activated' if active else 'deactivated'
    return jsonify({'success': True, 'message': f'User {action_word} successfully'})


@admin_panel_bp.route('/users/<int:user_id>/edit', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional(max_retries=3)
def edit_user_comprehensive(user_id):
    """
    Comprehensive user edit via modal form.

    Uses pessimistic locking to prevent concurrent modifications and
    defers Discord operations until after the transaction commits.
    """
    try:
        # Debug log form data - print() bypasses logging config, guaranteed visible in stdout
        import sys
        print(f"[EDIT_USER] === ENDPOINT HIT === user_id={user_id}", flush=True)
        print(f"[EDIT_USER] Form data: {dict(request.form)}", flush=True)
        print(f"[EDIT_USER] Request URL: {request.url}", flush=True)
        sys.stdout.flush()
        logger.info(f"Edit user {user_id} - Form data received: {dict(request.form)}")

        draft_socket_events = []

        # Acquire lock on user to prevent concurrent modifications.
        # Use nowait=False with a 5s timeout so brief lock contention (e.g., from
        # a Celery task syncing Discord roles) is handled gracefully by waiting
        # instead of failing immediately.
        with lock_user_for_role_update(user_id, session=db.session, nowait=False, timeout=5) as user:

            # Get form data
            username = request.form.get('username')
            email = request.form.get('email')
            real_name = request.form.get('real_name')
            is_approved = request.form.get('is_approved') == 'on'
            is_active = request.form.get('is_active') == 'on'
            is_current_player = request.form.get('is_current_player') == 'on'
            role_ids = request.form.getlist('roles')

            # Read league type selections from the form FIRST (needed to validate team IDs)
            primary_league_type = request.form.get('primary_league_type', '').strip().lower()
            secondary_league_type = request.form.get('secondary_league_type', '').strip().lower()
            tertiary_league_type = request.form.get('tertiary_league_type', '').strip().lower()

            # Handle both old and new form field names for team assignments
            # New form uses three-tier system: primary_team_id, secondary_team_id, tertiary_team_id
            team_id = request.form.get('primary_team_id') or request.form.get('team_id')
            secondary_team_id = request.form.get('secondary_team_id')
            tertiary_team_id = request.form.get('tertiary_team_id')

            # Ignore stale team IDs from hidden form dropdowns when no league is selected
            if not primary_league_type:
                team_id = None
            if not secondary_league_type:
                secondary_team_id = None
            if not tertiary_league_type:
                tertiary_team_id = None

            # Helper to get league ID from league type name
            def get_league_id_from_type(league_type):
                """Get the league ID from a league type name (classic, premier, ecsfc)."""
                if not league_type:
                    return None
                # Map league type to league name pattern
                type_to_name = {
                    'classic': 'Classic',
                    'premier': 'Premier',
                    'ecsfc': 'ECS FC',
                }
                league_name = type_to_name.get(league_type)
                if league_name:
                    # Find the league with this name in current season
                    league = League.query.join(Season).filter(
                        Season.is_current == True,
                        League.name.ilike(f'%{league_name}%')
                    ).first()
                    if league:
                        return str(league.id)
                return None

            # Determine league_id - prioritize league type selection, fallback to deriving from team
            league_id = None
            if primary_league_type:
                league_id = get_league_id_from_type(primary_league_type)
            if not league_id and team_id:
                primary_team = Team.query.get(int(team_id))
                if primary_team and primary_team.league_id:
                    league_id = str(primary_team.league_id)

            # Determine secondary_league_id - prioritize league type selection, fallback to deriving from team
            secondary_league_id = None
            if secondary_league_type:
                secondary_league_id = get_league_id_from_type(secondary_league_type)
            if not secondary_league_id and secondary_team_id:
                sec_team = Team.query.get(int(secondary_team_id))
                if sec_team and sec_team.league_id:
                    secondary_league_id = str(sec_team.league_id)

            # Determine tertiary_league_id for role management
            tertiary_league_id = None
            if tertiary_league_type:
                tertiary_league_id = get_league_id_from_type(tertiary_league_type)

            # Store old values for audit log
            old_values = {
                'username': user.username,
                'email': user.email,
                'is_approved': user.is_approved,
                'is_active': user.is_active,
                'roles': [r.id for r in user.roles],
                'league_id': user.player.primary_league_id if user.player else None,
                'team_id': user.player.primary_team_id if user.player else None,
                'is_current_player': user.player.is_current_player if user.player else None
            }

            # Update user fields
            if username:
                user.username = username
            if email:
                user.email = email
            user.is_approved = is_approved
            user.is_active = is_active

            # Update player profile if exists
            if user.player:
                if real_name:
                    user.player.name = real_name

                # Primary league and team
                user.player.primary_league_id = int(league_id) if league_id else None
                user.player.primary_team_id = int(team_id) if team_id else None

                # Active player status
                user.player.is_current_player = is_current_player

                # Handle secondary and tertiary leagues (clear existing and set new)
                user.player.other_leagues.clear()
                logger.info(f"User {user_id} league assignments: primary={league_id}, secondary={secondary_league_id}, tertiary={tertiary_league_id}")
                if secondary_league_id:
                    secondary_league = League.query.get(int(secondary_league_id))
                    # Compare IDs to avoid issues with lazy-loaded relationships
                    if secondary_league and str(secondary_league.id) != str(league_id):
                        user.player.other_leagues.append(secondary_league)
                        logger.info(f"Added secondary league {secondary_league.name} (ID: {secondary_league.id}) to player {user.player.id}")
                if tertiary_league_id:
                    tertiary_league = League.query.get(int(tertiary_league_id))
                    # Check it's not the primary league and not already added as secondary
                    if tertiary_league and str(tertiary_league.id) != str(league_id):
                        if tertiary_league not in user.player.other_leagues:
                            user.player.other_leagues.append(tertiary_league)
                            logger.info(f"Added tertiary league {tertiary_league.name} (ID: {tertiary_league.id}) to player {user.player.id}")

                # Get ECS FC team IDs from the three-tier form fields
                # Support both old format (ecs_fc_team_ids[]) and new format (primary/secondary/tertiary_ecsfc_teams)
                ecs_fc_team_ids = request.form.getlist('ecs_fc_team_ids[]')
                if not ecs_fc_team_ids:
                    # Try new three-tier format
                    ecs_fc_team_ids = []
                    ecs_fc_team_ids.extend(request.form.getlist('primary_ecsfc_teams'))
                    ecs_fc_team_ids.extend(request.form.getlist('secondary_ecsfc_teams'))
                    ecs_fc_team_ids.extend(request.form.getlist('tertiary_ecsfc_teams'))
                ecs_fc_team_ids = [int(tid) for tid in ecs_fc_team_ids if tid]

                # Build the list of teams the player should be on
                target_team_ids = set()

                # Always keep the primary team
                if user.player.primary_team_id:
                    target_team_ids.add(user.player.primary_team_id)

                # Add secondary team if specified (for non-ECS FC leagues)
                if secondary_team_id:
                    target_team_ids.add(int(secondary_team_id))

                # Add tertiary team if specified
                if tertiary_team_id:
                    target_team_ids.add(int(tertiary_team_id))

                # Add all selected ECS FC teams
                target_team_ids.update(ecs_fc_team_ids)

                # Current team IDs
                current_team_ids = {t.id for t in user.player.teams}

                # Remove teams that should no longer be assigned
                # (except keep ECS FC teams - they're handled by the multi-select)
                teams_to_remove = []
                for team in user.player.teams:
                    team_is_ecs_fc = is_ecs_fc_team(team.id)
                    # For ECS FC teams: only remove if not in selected ecs_fc_team_ids
                    # For non-ECS FC teams: only keep primary and secondary
                    if team_is_ecs_fc:
                        if team.id not in ecs_fc_team_ids:
                            teams_to_remove.append(team)
                    else:
                        if team.id not in target_team_ids:
                            teams_to_remove.append(team)

                logger.info(f"Player {user.player.id} team removal: target_team_ids={target_team_ids}, "
                            f"current_team_ids={current_team_ids}, teams_to_remove={[t.id for t in teams_to_remove]}")

                print(f"[EDIT_USER] target_team_ids={target_team_ids}, current_team_ids={current_team_ids}, teams_to_remove={[t.id for t in teams_to_remove]}", flush=True)

                if teams_to_remove:
                    from sqlalchemy import delete
                    from app.models import player_teams as pt_table

                    remove_team_ids = [team.id for team in teams_to_remove]

                    # Use explicit SQL DELETE on player_teams for reliable removal
                    result = db.session.execute(
                        delete(pt_table).where(
                            pt_table.c.player_id == user.player.id,
                            pt_table.c.team_id.in_(remove_team_ids)
                        )
                    )
                    print(f"[EDIT_USER] DELETE result: {result.rowcount} rows deleted from player_teams for player {user.player.id}, teams {remove_team_ids}", flush=True)
                    logger.info(f"Deleted {result.rowcount} player_teams rows for player {user.player.id}, teams {remove_team_ids}")

                    # Clear primary_team_id if it was one of the removed teams
                    if user.player.primary_team_id in remove_team_ids:
                        user.player.primary_team_id = None
                        logger.info(f"Cleared primary_team_id for player {user.player.id}")

                    # Expire the teams relationship so ORM picks up the change
                    db.session.expire(user.player, ['teams'])

                for team in teams_to_remove:
                    # Update PlayerTeamHistory - set left_date
                    history_record = PlayerTeamHistory.query.filter_by(
                        player_id=user.player.id,
                        team_id=team.id,
                        left_date=None
                    ).first()
                    if history_record:
                        history_record.left_date = datetime.utcnow()
                        logger.info(f"Updated team history: player {user.player.id} left team {team.id}")

                    # Remove PlayerTeamSeason records for current season
                    if team.league and team.league.season_id:
                        pts_records = PlayerTeamSeason.query.filter_by(
                            player_id=user.player.id,
                            team_id=team.id,
                            season_id=team.league.season_id
                        ).all()
                        for pts in pts_records:
                            db.session.delete(pts)
                        if pts_records:
                            logger.info(f"Removed {len(pts_records)} PlayerTeamSeason records for player {user.player.id}, team {team.id}")

                    logger.info(f"Removed player {user.player.id} from team {team.id}")

                    # Track for draft page socket notification
                    if team.league:
                        room_name = DB_LEAGUE_TO_DRAFT_ROOM.get(team.league.name.lower())
                        if room_name:
                            draft_socket_events.append({
                                'type': 'removed',
                                'team_id': team.id,
                                'team_name': team.name,
                                'league_name': room_name,
                            })

                # Add new teams
                for team_id in target_team_ids:
                    if team_id not in current_team_ids:
                        team_to_add = Team.query.get(team_id)
                        if team_to_add and team_to_add not in user.player.teams:
                            # Use add_player_to_team helper to preserve coach status
                            from app.models.players import add_player_to_team
                            add_player_to_team(user.player, team_to_add, db.session)
                            # Create PlayerTeamHistory record
                            team_history = PlayerTeamHistory(
                                player_id=user.player.id,
                                team_id=team_id,
                                joined_date=datetime.utcnow(),
                                is_coach=user.player.is_coach
                            )
                            db.session.add(team_history)
                            # Create PlayerTeamSeason record for current season (if not already exists)
                            if team_to_add.league and team_to_add.league.season_id:
                                existing_pts = PlayerTeamSeason.query.filter_by(
                                    player_id=user.player.id,
                                    team_id=team_id,
                                    season_id=team_to_add.league.season_id
                                ).first()
                                if not existing_pts:
                                    player_team_season = PlayerTeamSeason(
                                        player_id=user.player.id,
                                        team_id=team_id,
                                        season_id=team_to_add.league.season_id
                                    )
                                    db.session.add(player_team_season)
                            logger.info(f"Added player {user.player.id} to team {team_id} (with history and season records)")

                            # Track for draft page socket notification
                            if team_to_add.league:
                                room_name = DB_LEAGUE_TO_DRAFT_ROOM.get(team_to_add.league.name.lower())
                                if room_name:
                                    draft_socket_events.append({
                                        'type': 'drafted',
                                        'team_id': team_to_add.id,
                                        'team_name': team_to_add.name,
                                        'league_name': room_name,
                                    })

                # Build player data for any pending draft socket notifications
                if draft_socket_events:
                    player_data = _build_player_socket_data(user.player)
                    for event in draft_socket_events:
                        event['player'] = player_data

            # Update roles - including auto league-to-role mapping
            if role_ids:
                # First, fix any duplicate user_roles entries that could cause StaleDataError
                # This can happen due to race conditions or data migration issues
                from sqlalchemy import text
                db.session.execute(text("""
                    DELETE FROM user_roles
                    WHERE ctid IN (
                        SELECT ctid FROM (
                            SELECT ctid, ROW_NUMBER() OVER (PARTITION BY user_id, role_id ORDER BY ctid) as rn
                            FROM user_roles
                            WHERE user_id = :user_id
                        ) t WHERE rn > 1
                    )
                """), {'user_id': user_id})

                # Expire the user object to refresh its roles collection from the database
                db.session.expire(user, ['roles'])

                new_roles = Role.query.filter(Role.id.in_(role_ids)).all()
                user.roles = new_roles

            # Auto-manage league roles based on league assignments
            if user.player:
                # Refresh user roles from database to avoid stale data issues
                db.session.refresh(user, ['roles'])

                # Determine which league roles the user should have
                required_league_roles = set()

                # Primary league role
                if league_id:
                    primary_league = League.query.get(int(league_id))
                    primary_role_name = get_role_for_league(primary_league)
                    if primary_role_name:
                        required_league_roles.add(primary_role_name)

                # Secondary league role
                if secondary_league_id:
                    secondary_league = League.query.get(int(secondary_league_id))
                    secondary_role_name = get_role_for_league(secondary_league)
                    if secondary_role_name:
                        required_league_roles.add(secondary_role_name)

                # Tertiary league role
                if tertiary_league_id:
                    tertiary_league = League.query.get(int(tertiary_league_id))
                    tertiary_role_name = get_role_for_league(tertiary_league)
                    if tertiary_role_name:
                        required_league_roles.add(tertiary_role_name)

                # Get current role names for comparison
                current_role_names = {r.name for r in user.roles}

                # Determine which sub roles should be kept based on leagues
                required_sub_roles = set()
                if league_id:
                    primary_league = League.query.get(int(league_id))
                    if primary_league:
                        sub_role = LEAGUE_TO_SUB_ROLE_MAP.get(primary_league.name.lower().strip())
                        if sub_role:
                            required_sub_roles.add(sub_role)
                if secondary_league_id:
                    secondary_league = League.query.get(int(secondary_league_id))
                    if secondary_league:
                        sub_role = LEAGUE_TO_SUB_ROLE_MAP.get(secondary_league.name.lower().strip())
                        if sub_role:
                            required_sub_roles.add(sub_role)
                if tertiary_league_id:
                    tertiary_league = League.query.get(int(tertiary_league_id))
                    if tertiary_league:
                        sub_role = LEAGUE_TO_SUB_ROLE_MAP.get(tertiary_league.name.lower().strip())
                        if sub_role:
                            required_sub_roles.add(sub_role)

                # Remove league roles that are no longer needed
                for league_role in LEAGUE_ROLES:
                    if league_role in current_role_names and league_role not in required_league_roles:
                        role_to_remove = Role.query.filter_by(name=league_role).first()
                        if role_to_remove and role_to_remove in user.roles:
                            user.roles.remove(role_to_remove)
                            logger.info(f"Auto-removed role {league_role} from user {user.id}")

                # Remove sub roles for leagues the user is no longer in
                for sub_role in SUB_ROLES:
                    if sub_role in current_role_names and sub_role not in required_sub_roles:
                        role_to_remove = Role.query.filter_by(name=sub_role).first()
                        if role_to_remove and role_to_remove in user.roles:
                            user.roles.remove(role_to_remove)
                            logger.info(f"Auto-removed sub role {sub_role} from user {user.id}")

                # Add league roles that should be present
                for required_role in required_league_roles:
                    if required_role not in current_role_names:
                        role_to_add = Role.query.filter_by(name=required_role).first()
                        if role_to_add and role_to_add not in user.roles:
                            user.roles.append(role_to_add)
                            logger.info(f"Auto-added role {required_role} to user {user.id}")

            # Queue Discord role sync for AFTER transaction commits
            if user.player and user.player.discord_id:
                defer_discord_sync(user.player.id, only_add=False)
                logger.info(f"Queued Discord role sync for user {user.id}")

            # Log the action
            AdminAuditLog.log_action(
                user_id=current_user.id,
                action='edit_user_comprehensive',
                resource_type='user_management',
                resource_id=str(user_id),
                old_value=str(old_values),
                new_value=str({
                    'username': user.username,
                    'email': user.email,
                    'is_approved': user.is_approved,
                    'is_active': user.is_active,
                    'roles': [r.id for r in user.roles]
                }),
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )

            updated_username = user.username

            # Track league changes for cache invalidation
            old_league_id = old_values.get('league_id')
            new_league_id = user.player.primary_league_id if user.player else None
            old_was_current = old_values.get('is_current_player')
            new_is_current = user.player.is_current_player if user.player else False

            # Get league names for cache clearing (need to do this inside the lock context)
            leagues_to_clear = set()
            if old_league_id:
                old_league = League.query.get(old_league_id)
                if old_league:
                    leagues_to_clear.add(old_league.name.lower())
            if new_league_id:
                new_league = League.query.get(new_league_id)
                if new_league:
                    leagues_to_clear.add(new_league.name.lower())

        # Execute deferred Discord operations AFTER transaction commits
        execute_deferred_discord()

        # Emit socket events to update draft pages in real-time
        if draft_socket_events:
            from app.core import socketio
            for event in draft_socket_events:
                event_name = 'player_drafted_enhanced' if event['type'] == 'drafted' else 'player_removed_enhanced'
                room = f"draft_{event['league_name']}"
                socketio.emit(event_name, {
                    'success': True,
                    'player': event['player'],
                    'team_id': event['team_id'],
                    'team_name': event['team_name'],
                    'league_name': event['league_name'],
                }, room=room, namespace='/')
                logger.info(f"Emitted {event_name} to {room} after user management edit")

        # Clear draft cache if league changed, is_current_player changed, or teams changed
        all_leagues_to_clear = set()
        if leagues_to_clear and (old_league_id != new_league_id or old_was_current != new_is_current):
            all_leagues_to_clear.update(leagues_to_clear)
        for event in draft_socket_events:
            db_name = {'classic': 'classic', 'premier': 'premier', 'ecs_fc': 'ecs fc'}.get(event['league_name'])
            if db_name:
                all_leagues_to_clear.add(db_name)
        if all_leagues_to_clear:
            try:
                from app.draft_cache_service import DraftCacheService
                for league_name in all_leagues_to_clear:
                    DraftCacheService.clear_all_league_caches(league_name)
                logger.info(f"Cleared draft caches for {all_leagues_to_clear} after editing user {user_id}")
            except Exception as e:
                logger.warning(f"Could not clear draft cache: {e}")

        print(f"[EDIT_USER] === SUCCESS === Returning JSON success for user {updated_username}", flush=True)
        return jsonify({
            'success': True,
            'message': f'User {updated_username} updated successfully'
        })

    except LockAcquisitionError:
        clear_deferred_discord()
        # CRITICAL: Rollback the aborted transaction BEFORE returning.
        # PostgreSQL aborts the entire transaction after a FOR UPDATE NOWAIT failure.
        # If we don't rollback here, @transactional's commit() will fail on the
        # aborted transaction, turning our nice 409 JSON into an unhandled 500.
        db.session.rollback()
        print(f"[EDIT_USER] === LOCK FAILED === user_id={user_id}", flush=True)
        logger.warning(f"Lock acquisition failed for user {user_id}")
        return jsonify({
            'success': False,
            'message': 'User is currently being modified by another request. Please try again.'
        }), 409

    except Exception as e:
        clear_deferred_discord()
        # CRITICAL: Rollback to undo any partial changes and clear error state.
        # Without this, @transactional's commit() would either commit partial
        # changes (data integrity bug) or fail on an aborted transaction.
        db.session.rollback()
        print(f"[EDIT_USER] === EXCEPTION === user_id={user_id}: {type(e).__name__}: {e}", flush=True)
        import traceback
        traceback.print_exc()
        logger.exception(f"Error editing user {user_id}: {e}")
        return jsonify({
            'success': False,
            'message': f'Error updating user: {str(e)}'
        }), 500


@admin_panel_bp.route('/users/<int:user_id>/approve', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional(max_retries=3)
def approve_user_comprehensive(user_id):
    """
    Quick approve user via AJAX from comprehensive management.

    Uses pessimistic locking to prevent concurrent modifications.
    """
    try:
        with lock_user_for_role_update(user_id, session=db.session) as user:
            old_status = user.is_approved

            user.is_approved = True
            user.approval_status = 'approved'

            # Also set player as current player when approved
            if user.player:
                user.player.is_current_player = True

            # Queue Discord role sync for AFTER transaction commits
            if user.player and user.player.discord_id:
                defer_discord_sync(user.player.id, only_add=False)
                logger.info(f"Queued Discord role sync for approved user {user.id}")

            # Log the action
            AdminAuditLog.log_action(
                user_id=current_user.id,
                action='approve_user_quick',
                resource_type='user_management',
                resource_id=str(user_id),
                old_value=str(old_status),
                new_value='True',
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )

            username = user.username

        # Execute deferred Discord operations AFTER transaction commits
        execute_deferred_discord()

        return jsonify({'success': True, 'message': f'User {username} approved successfully'})

    except LockAcquisitionError:
        clear_deferred_discord()
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'User is currently being modified by another request. Please try again.'
        }), 409


@admin_panel_bp.route('/users/<int:user_id>/deactivate', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional(max_retries=3)
def deactivate_user_comprehensive(user_id):
    """
    Quick deactivate user via AJAX from comprehensive management.

    Uses pessimistic locking to prevent concurrent modifications.
    """
    try:
        with lock_user_for_role_update(user_id, session=db.session) as user:
            old_status = user.is_active

            user.is_active = False

            # Also set player as not current
            if user.player:
                user.player.is_current_player = False

            # Queue Discord role removal for AFTER transaction commits
            if user.player and user.player.discord_id:
                defer_discord_removal(user.player.id)
                logger.info(f"Queued Discord role removal for deactivated user {user.id}")

            # Log the action
            AdminAuditLog.log_action(
                user_id=current_user.id,
                action='deactivate_user_quick',
                resource_type='user_management',
                resource_id=str(user_id),
                old_value=str(old_status),
                new_value='False',
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )

            username = user.username

        # Execute deferred Discord operations AFTER transaction commits
        execute_deferred_discord()

        return jsonify({'success': True, 'message': f'User {username} deactivated successfully'})

    except LockAcquisitionError:
        clear_deferred_discord()
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'User is currently being modified by another request. Please try again.'
        }), 409


@admin_panel_bp.route('/users/<int:user_id>/activate', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional(max_retries=3)
def activate_user_comprehensive(user_id):
    """
    Quick activate user via AJAX from comprehensive management.

    Uses pessimistic locking to prevent concurrent modifications.
    Also invalidates draft cache so player appears immediately in draft pool.
    """
    try:
        league_name_for_cache = None

        with lock_user_for_role_update(user_id, session=db.session) as user:
            old_status = user.is_active

            user.is_active = True

            # Also set player as current
            if user.player:
                user.player.is_current_player = True

                # Get league name for cache invalidation
                if user.player.primary_league:
                    league_name_for_cache = user.player.primary_league.name

            # Queue Discord role sync for AFTER transaction commits
            if user.player and user.player.discord_id:
                defer_discord_sync(user.player.id, only_add=False)
                logger.info(f"Queued Discord role sync for activated user {user.id}")

            # Log the action
            AdminAuditLog.log_action(
                user_id=current_user.id,
                action='activate_user_quick',
                resource_type='user_management',
                resource_id=str(user_id),
                old_value=str(old_status),
                new_value='True',
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )

            username = user.username

        # Execute deferred Discord operations AFTER transaction commits
        execute_deferred_discord()

        # Invalidate draft cache so player appears immediately
        if league_name_for_cache:
            try:
                from app.draft_cache_service import DraftCacheService
                DraftCacheService.clear_all_league_caches(league_name_for_cache.lower())
                logger.info(f"Cleared draft cache for {league_name_for_cache} after activating user {user_id}")
            except Exception as e:
                logger.warning(f"Could not clear draft cache: {e}")

        return jsonify({'success': True, 'message': f'User {username} activated successfully'})

    except LockAcquisitionError:
        clear_deferred_discord()
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'User is currently being modified by another request. Please try again.'
        }), 409


@admin_panel_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@login_required
@role_required(['Global Admin'])
@transactional
def delete_user_comprehensive(user_id):
    """Delete user completely via AJAX from comprehensive management."""
    user = User.query.options(joinedload(User.player)).get_or_404(user_id)
    username = user.username
    player_id = user.player.id if user.player else None
    discord_id = user.player.discord_id if user.player else None

    # Log before deletion
    AdminAuditLog.log_action(
        user_id=current_user.id,
        action='delete_user',
        resource_type='user_management',
        resource_id=str(user_id),
        old_value=username,
        new_value='deleted',
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent')
    )

    # Delete the user (cascades to player if configured)
    db.session.delete(user)

    # Remove Discord roles AFTER successful delete
    if player_id and discord_id:
        remove_player_roles_task.delay(player_id=player_id)
        logger.info(f"Triggered Discord role removal for deleted user {user_id}")

    return jsonify({'success': True, 'message': f'User {username} deleted successfully'})


@admin_panel_bp.route('/users/bulk-actions', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def bulk_user_comprehensive_actions():
    """Handle bulk user actions from comprehensive management page."""
    try:
        action = request.form.get('action')
        user_ids = request.form.getlist('user_ids')

        if not action or not user_ids:
            return jsonify({'success': False, 'message': 'Action and user IDs are required'})

        users = User.query.options(joinedload(User.player)).filter(User.id.in_(user_ids)).all()
        if not users:
            return jsonify({'success': False, 'message': 'No users found'})

        count = 0
        users_to_sync = []
        users_to_remove_roles = []

        for user in users:
            if action == 'approve':
                user.is_approved = True
                user.approval_status = 'approved'
                users_to_sync.append(user)
                count += 1
            elif action == 'deactivate':
                user.is_active = False
                users_to_remove_roles.append(user)
                count += 1
            elif action == 'activate':
                user.is_active = True
                users_to_sync.append(user)
                count += 1
            elif action == 'deny':
                user.is_approved = False
                user.approval_status = 'denied'
                users_to_remove_roles.append(user)
                count += 1

        # Trigger Discord sync for affected users
        for user in users_to_sync:
            if user.player and user.player.discord_id:
                assign_roles_to_player_task.delay(player_id=user.player.id, only_add=False)

        for user in users_to_remove_roles:
            if user.player and user.player.discord_id:
                remove_player_roles_task.delay(player_id=user.player.id)

        if users_to_sync or users_to_remove_roles:
            logger.info(f"Bulk action '{action}': triggered Discord sync for {len(users_to_sync)} users, role removal for {len(users_to_remove_roles)} users")

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action=f'bulk_{action}_users',
            resource_type='user_management',
            resource_id=','.join(user_ids),
            old_value=None,
            new_value=f'{count} users',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        action_past = {'approve': 'approved', 'deactivate': 'deactivated', 'activate': 'activated', 'deny': 'denied'}
        return jsonify({
            'success': True,
            'message': f'{count} user(s) {action_past.get(action, action)} successfully'
        })

    except Exception as e:
        logger.error(f"Error in bulk user action: {e}")
        return jsonify({'success': False, 'message': 'Error processing bulk action'}), 500


@admin_panel_bp.route('/users/bulk-update', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def bulk_update_users():
    """Bulk update users via AJAX."""
    try:
        data = request.get_json()
        user_ids = data.get('user_ids', [])
        action = data.get('action')

        if not user_ids or not action:
            return jsonify({'success': False, 'message': 'Missing required parameters'})

        users = User.query.options(joinedload(User.player)).filter(User.id.in_(user_ids)).all()

        users_to_sync = []
        users_to_remove_roles = []

        if action == 'update_status':
            status = data.get('status')
            if status not in ['approved', 'pending', 'denied']:
                return jsonify({'success': False, 'message': 'Invalid status'})

            for user in users:
                user.approval_status = status
                # Also update is_approved
                if status == 'approved':
                    user.is_approved = True
                    users_to_sync.append(user)
                elif status == 'denied':
                    user.is_approved = False
                    users_to_remove_roles.append(user)

            message = f'{len(users)} users updated to {status} status'

        elif action == 'update_active':
            active = data.get('active', True)
            for user in users:
                user.is_active = active
                if active:
                    users_to_sync.append(user)
                else:
                    users_to_remove_roles.append(user)

            action_word = 'activated' if active else 'deactivated'
            message = f'{len(users)} users {action_word}'

        else:
            return jsonify({'success': False, 'message': 'Invalid action'})

        # Trigger Discord sync for affected users
        for user in users_to_sync:
            if user.player and user.player.discord_id:
                assign_roles_to_player_task.delay(player_id=user.player.id, only_add=False)

        for user in users_to_remove_roles:
            if user.player and user.player.discord_id:
                remove_player_roles_task.delay(player_id=user.player.id)

        if users_to_sync or users_to_remove_roles:
            logger.info(f"Bulk update '{action}': triggered Discord sync for {len(users_to_sync)} users, role removal for {len(users_to_remove_roles)} users")

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action=f'bulk_{action}',
            resource_type='user_management',
            resource_id=','.join(map(str, user_ids)),
            new_value=f'{action}:{len(users)} users',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({'success': True, 'message': message})
    except Exception as e:
        logger.error(f"Error bulk updating users: {e}")
        return jsonify({'success': False, 'message': 'Error updating users'})


@admin_panel_bp.route('/admin/repair-season-assignments', methods=['POST'])
@login_required
@role_required(['Global Admin'])
@transactional
def repair_season_assignments():
    """
    Bulk fix all active players with stale (old season) league assignments.

    This endpoint finds players whose primary_league_id points to a non-current
    season league and updates them to the equivalent current season league.

    For example:
    - Player has primary_league_id = 11 (2024 Fall Classic)
    - This updates them to primary_league_id = 25 (2026 Spring Classic)

    Returns:
        JSON with counts of found/fixed/failed players
    """
    from app.services.season_sync_service import SeasonSyncService

    try:
        # Find all stale players (active players in old season leagues)
        stale_players = SeasonSyncService.find_all_stale_players(db.session)

        result = {
            'found': len(stale_players),
            'fixed': 0,
            'failed': 0,
            'players': []
        }

        for player in stale_players:
            try:
                old_league_id = player.primary_league_id
                if SeasonSyncService.sync_player_to_current_season(db.session, player):
                    result['fixed'] += 1
                    result['players'].append({
                        'id': player.id,
                        'name': player.name,
                        'old_league_id': old_league_id,
                        'new_league_id': player.primary_league_id,
                        'status': 'fixed'
                    })
            except Exception as e:
                result['failed'] += 1
                result['players'].append({
                    'id': player.id,
                    'name': player.name,
                    'status': 'failed',
                    'error': str(e)
                })
                logger.error(f"Failed to sync player {player.id}: {e}")

        db.session.commit()

        # Clear all draft caches after bulk repair
        try:
            from app.draft_cache_service import DraftCacheService
            DraftCacheService.clear_all_league_caches('classic')
            DraftCacheService.clear_all_league_caches('premier')
            DraftCacheService.clear_all_league_caches('ecs fc')
            logger.info("Cleared all draft caches after season assignment repair")
        except Exception as e:
            logger.warning(f"Could not clear draft caches: {e}")

        # Log the admin action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='repair_season_assignments',
            resource_type='player_management',
            resource_id='bulk',
            new_value=f"Found {result['found']}, fixed {result['fixed']}, failed {result['failed']}",
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        logger.info(f"Season assignment repair: found {result['found']}, fixed {result['fixed']}, failed {result['failed']}")

        return jsonify({
            'success': True,
            'message': f"Repaired {result['fixed']} of {result['found']} stale player assignments",
            **result
        })

    except Exception as e:
        logger.error(f"Error repairing season assignments: {e}")
        return jsonify({
            'success': False,
            'message': f'Error repairing season assignments: {str(e)}'
        }), 500


@admin_panel_bp.route('/admin/check-stale-players', methods=['GET'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def check_stale_players():
    """
    Check for active players with stale (old season) league assignments.

    This is a read-only diagnostic endpoint that returns information about
    players who need their league assignments repaired.

    Returns:
        JSON with list of stale players and their current/expected leagues
    """
    from app.services.season_sync_service import SeasonSyncService

    try:
        stale_players = SeasonSyncService.find_all_stale_players(db.session)

        players_info = []
        for player in stale_players:
            current_league = player.primary_league
            expected_league = None

            # Find the expected current season league
            if current_league and current_league.season:
                expected_league = SeasonSyncService.get_current_league_by_name(
                    db.session,
                    current_league.name,
                    current_league.season.league_type
                )

            players_info.append({
                'id': player.id,
                'name': player.name,
                'is_current_player': player.is_current_player,
                'current_league': {
                    'id': current_league.id if current_league else None,
                    'name': current_league.name if current_league else None,
                    'season': current_league.season.name if current_league and current_league.season else None,
                    'is_current_season': current_league.season.is_current if current_league and current_league.season else None
                } if current_league else None,
                'expected_league': {
                    'id': expected_league.id if expected_league else None,
                    'name': expected_league.name if expected_league else None,
                    'season': expected_league.season.name if expected_league and expected_league.season else None
                } if expected_league else None
            })

        return jsonify({
            'success': True,
            'stale_count': len(stale_players),
            'players': players_info
        })

    except Exception as e:
        logger.error(f"Error checking stale players: {e}")
        return jsonify({
            'success': False,
            'message': f'Error checking stale players: {str(e)}'
        }), 500
