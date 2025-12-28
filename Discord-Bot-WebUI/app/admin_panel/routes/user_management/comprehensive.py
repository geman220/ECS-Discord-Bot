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
from app.decorators import role_required
from app.utils.db_utils import transactional
from app.tasks.tasks_discord import assign_roles_to_player_task, remove_player_roles_task

logger = logging.getLogger(__name__)

# Mapping from league names to role names
LEAGUE_TO_ROLE_MAP = {
    'classic': 'pl-classic',
    'premier': 'pl-premier',
    'ecs fc': 'pl-ecs-fc',
    'ecs-fc': 'pl-ecs-fc',
}

# All league-related roles that should be managed
LEAGUE_ROLES = ['pl-classic', 'pl-premier', 'pl-ecs-fc']


def get_role_for_league(league):
    """Get the appropriate role name for a league."""
    if not league:
        return None
    league_name = league.name.lower().strip()
    return LEAGUE_TO_ROLE_MAP.get(league_name)


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
                # Search username and player name (via outerjoin)
                query = query.outerjoin(Player, User.player).filter(
                    or_(
                        User.username.ilike(search_term),
                        Player.name.ilike(search_term)
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
        # Get leagues from current seasons only
        all_leagues = League.query.join(Season).filter(Season.is_current == True).order_by(League.name).all()

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

        return render_template('admin_panel/users/manage_users_comprehensive.html',
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
def update_user_status():
    """Update user approval status via AJAX."""
    try:
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
        elif status == 'denied':
            user.is_approved = False

        db.session.commit()

        # Trigger Discord sync based on status change
        if user.player and user.player.discord_id:
            if status == 'approved':
                assign_roles_to_player_task.delay(player_id=user.player.id, only_add=False)
                logger.info(f"Triggered Discord role sync for approved user {user.id}")
            elif status == 'denied':
                remove_player_roles_task.delay(player_id=user.player.id)
                logger.info(f"Triggered Discord role removal for denied user {user.id}")

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
    except Exception as e:
        logger.error(f"Error updating user status: {e}")
        return jsonify({'success': False, 'message': 'Error updating user status'})


@admin_panel_bp.route('/users/update-active', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def update_user_active():
    """Update user active status via AJAX."""
    try:
        user_id = request.form.get('user_id')
        active = request.form.get('active').lower() == 'true'

        if not user_id:
            return jsonify({'success': False, 'message': 'User ID is required'})

        user = User.query.options(joinedload(User.player)).get_or_404(user_id)
        old_active = user.is_active
        user.is_active = active

        db.session.commit()

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
    except Exception as e:
        logger.error(f"Error updating user active status: {e}")
        return jsonify({'success': False, 'message': 'Error updating user status'})


@admin_panel_bp.route('/users/<int:user_id>/edit', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def edit_user_comprehensive(user_id):
    """Comprehensive user edit via modal form."""
    try:
        user = User.query.options(
            joinedload(User.player),
            joinedload(User.roles)
        ).get_or_404(user_id)

        # Get form data
        username = request.form.get('username')
        email = request.form.get('email')
        real_name = request.form.get('real_name')
        is_approved = request.form.get('is_approved') == 'on'
        is_active = request.form.get('is_active') == 'on'
        is_current_player = request.form.get('is_current_player') == 'on'
        role_ids = request.form.getlist('roles')
        league_id = request.form.get('league_id')
        team_id = request.form.get('team_id')
        secondary_league_id = request.form.get('secondary_league_id')
        secondary_team_id = request.form.get('secondary_team_id')

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

            # Handle secondary league (clear existing and set new)
            user.player.other_leagues.clear()
            if secondary_league_id:
                secondary_league = League.query.get(int(secondary_league_id))
                if secondary_league and secondary_league != user.player.primary_league:
                    user.player.other_leagues.append(secondary_league)

            # Handle secondary team (remove non-primary teams, add new if specified)
            teams_to_remove = [t for t in user.player.teams if t.id != user.player.primary_team_id]
            for team in teams_to_remove:
                user.player.teams.remove(team)
            if secondary_team_id:
                secondary_team = Team.query.get(int(secondary_team_id))
                if secondary_team and secondary_team.id != user.player.primary_team_id:
                    if secondary_team not in user.player.teams:
                        user.player.teams.append(secondary_team)

        # Update roles - including auto league-to-role mapping
        if role_ids:
            new_roles = Role.query.filter(Role.id.in_(role_ids)).all()
            user.roles = new_roles

        # Auto-manage league roles based on league assignments
        if user.player:
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

            # Get current role names for comparison
            current_role_names = {r.name for r in user.roles}

            # Remove league roles that are no longer needed
            for league_role in LEAGUE_ROLES:
                if league_role in current_role_names and league_role not in required_league_roles:
                    role_to_remove = Role.query.filter_by(name=league_role).first()
                    if role_to_remove and role_to_remove in user.roles:
                        user.roles.remove(role_to_remove)
                        logger.info(f"Auto-removed role {league_role} from user {user.id}")

            # Add league roles that should be present
            for required_role in required_league_roles:
                if required_role not in current_role_names:
                    role_to_add = Role.query.filter_by(name=required_role).first()
                    if role_to_add and role_to_add not in user.roles:
                        user.roles.append(role_to_add)
                        logger.info(f"Auto-added role {required_role} to user {user.id}")

        db.session.commit()

        # Trigger Discord role sync if player has Discord ID
        if user.player and user.player.discord_id:
            assign_roles_to_player_task.delay(player_id=user.player.id, only_add=False)
            logger.info(f"Triggered Discord role sync for user {user.id}")

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

        flash(f'User {user.username} updated successfully', 'success')
        return redirect(url_for('admin_panel.users_comprehensive'))

    except Exception as e:
        logger.error(f"Error editing user {user_id}: {e}")
        flash('Error updating user', 'error')
        return redirect(url_for('admin_panel.users_comprehensive'))


@admin_panel_bp.route('/users/<int:user_id>/approve', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def approve_user_comprehensive(user_id):
    """Quick approve user via AJAX from comprehensive management."""
    try:
        user = User.query.options(joinedload(User.player)).get_or_404(user_id)
        old_status = user.is_approved

        user.is_approved = True
        user.approval_status = 'approved'
        db.session.commit()

        # Trigger Discord role sync if player has Discord ID
        if user.player and user.player.discord_id:
            assign_roles_to_player_task.delay(player_id=user.player.id, only_add=False)
            logger.info(f"Triggered Discord role sync for approved user {user.id}")

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

        return jsonify({'success': True, 'message': f'User {user.username} approved successfully'})

    except Exception as e:
        logger.error(f"Error approving user {user_id}: {e}")
        return jsonify({'success': False, 'message': 'Error approving user'}), 500


@admin_panel_bp.route('/users/<int:user_id>/deactivate', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def deactivate_user_comprehensive(user_id):
    """Quick deactivate user via AJAX from comprehensive management."""
    try:
        user = User.query.options(joinedload(User.player)).get_or_404(user_id)
        old_status = user.is_active

        user.is_active = False
        db.session.commit()

        # Remove Discord roles for deactivated user
        if user.player and user.player.discord_id:
            remove_player_roles_task.delay(player_id=user.player.id)
            logger.info(f"Triggered Discord role removal for deactivated user {user.id}")

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

        return jsonify({'success': True, 'message': f'User {user.username} deactivated successfully'})

    except Exception as e:
        logger.error(f"Error deactivating user {user_id}: {e}")
        return jsonify({'success': False, 'message': 'Error deactivating user'}), 500


@admin_panel_bp.route('/users/<int:user_id>/activate', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def activate_user_comprehensive(user_id):
    """Quick activate user via AJAX from comprehensive management."""
    try:
        user = User.query.options(joinedload(User.player)).get_or_404(user_id)
        old_status = user.is_active

        user.is_active = True
        db.session.commit()

        # Sync Discord roles for activated user
        if user.player and user.player.discord_id:
            assign_roles_to_player_task.delay(player_id=user.player.id)
            logger.info(f"Triggered Discord role sync for activated user {user.id}")

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

        return jsonify({'success': True, 'message': f'User {user.username} activated successfully'})

    except Exception as e:
        logger.error(f"Error activating user {user_id}: {e}")
        return jsonify({'success': False, 'message': 'Error activating user'}), 500


@admin_panel_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def delete_user_comprehensive(user_id):
    """Delete user completely via AJAX from comprehensive management."""
    try:
        user = User.query.options(joinedload(User.player)).get_or_404(user_id)
        username = user.username

        # Remove Discord roles first if player exists
        if user.player and user.player.discord_id:
            remove_player_roles_task.delay(player_id=user.player.id)
            logger.info(f"Triggered Discord role removal for deleted user {user.id}")

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
        db.session.commit()

        return jsonify({'success': True, 'message': f'User {username} deleted successfully'})

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting user {user_id}: {e}")
        return jsonify({'success': False, 'message': 'Error deleting user'}), 500


@admin_panel_bp.route('/users/bulk-actions', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
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

        db.session.commit()

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

        db.session.commit()

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
