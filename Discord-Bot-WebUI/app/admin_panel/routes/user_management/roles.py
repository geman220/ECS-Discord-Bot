# app/admin_panel/routes/user_management/roles.py

"""
User Roles Routes

Routes for role management:
- Roles management page
- Role details
- Role assignment
- Role search
"""

import logging

from flask import render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload

from app.admin_panel import admin_panel_bp
from app.core import db
from app.models.admin_config import AdminAuditLog
from app.models.core import User, Role, Permission
from app.decorators import role_required
from app.utils.db_utils import transactional
from app.tasks.tasks_discord import assign_roles_to_player_task
from app.services.discord_role_sync_service import sync_role_assignment, sync_role_removal

logger = logging.getLogger(__name__)


def sync_ecs_fc_coach_status(user, is_adding_role: bool):
    """
    Sync ECS FC Coach role to player_teams.is_coach flag.

    When "ECS FC Coach" role is assigned, set is_coach=True for all
    the user's ECS FC teams. When removed, set is_coach=False.

    Args:
        user: User object with player relationship loaded
        is_adding_role: True if adding the role, False if removing
    """
    from app.models.players import player_teams, Team
    from app.models.core import League
    from sqlalchemy import and_, text

    if not user.player:
        logger.info(f"User {user.id} has no player profile, skipping ECS FC coach sync")
        return

    player = user.player

    # Find all ECS FC teams the player is on
    ecs_fc_team_ids = db.session.query(player_teams.c.team_id).join(
        Team, Team.id == player_teams.c.team_id
    ).join(
        League, League.id == Team.league_id
    ).filter(
        player_teams.c.player_id == player.id,
        League.name.contains('ECS FC')
    ).all()

    ecs_fc_team_ids = [t[0] for t in ecs_fc_team_ids]

    if not ecs_fc_team_ids:
        logger.info(f"Player {player.id} is not on any ECS FC teams, skipping coach sync")
        return

    # Update is_coach for all ECS FC teams
    for team_id in ecs_fc_team_ids:
        db.session.execute(
            text("UPDATE player_teams SET is_coach = :is_coach WHERE player_id = :player_id AND team_id = :team_id"),
            {"is_coach": is_adding_role, "player_id": player.id, "team_id": team_id}
        )

    logger.info(f"Updated is_coach={is_adding_role} for player {player.id} on ECS FC teams: {ecs_fc_team_ids}")


@admin_panel_bp.route('/users/roles')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def roles_management():
    """Roles and permissions management page."""
    try:
        roles = Role.query.order_by(Role.name).all()
        users = User.query.order_by(User.username).all()

        # Get all permissions from database
        permissions = Permission.query.order_by(Permission.name).all()

        # Get statistics
        users_with_roles = User.query.join(User.roles).distinct().count()
        admin_roles = len([r for r in roles if 'Admin' in r.name])

        return render_template('admin_panel/users/roles_flowbite.html',
                               roles=roles,
                               users=users,
                               permissions=permissions,
                               users_with_roles=users_with_roles,
                               admin_roles=admin_roles)
    except Exception as e:
        logger.error(f"Error loading roles management: {e}")
        flash('Roles management unavailable. Verify database connection and role models.', 'error')
        return redirect(url_for('admin_panel.user_management'))


@admin_panel_bp.route('/users/roles/details')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def get_role_details():
    """Get role details via AJAX."""
    try:
        role_id = request.args.get('role_id')
        role = Role.query.get_or_404(role_id)

        # Build role details HTML
        details_html = f"""
        <div class="row">
            <div class="col-md-6">
                <div class="card">
                    <div class="card-header">
                        <h6 class="mb-0">Role Information</h6>
                    </div>
                    <div class="card-body">
                        <div class="row mb-2">
                            <div class="col-sm-4"><strong>Name:</strong></div>
                            <div class="col-sm-8">{role.name}</div>
                        </div>
                        <div class="row mb-2">
                            <div class="col-sm-4"><strong>Description:</strong></div>
                            <div class="col-sm-8">{role.description or 'No description'}</div>
                        </div>
                        <div class="row mb-2">
                            <div class="col-sm-4"><strong>Users:</strong></div>
                            <div class="col-sm-8">{len(role.users)} users</div>
                        </div>
                        <div class="row mb-2">
                            <div class="col-sm-4"><strong>Permissions:</strong></div>
                            <div class="col-sm-8">{len(role.permissions)} permissions</div>
                        </div>
                    </div>
                </div>
            </div>
            <div class="col-md-6">
                <div class="card">
                    <div class="card-header">
                        <h6 class="mb-0">Users with this Role</h6>
                    </div>
                    <div class="card-body">
                        {"<br>".join([user.username for user in role.users[:10]]) if role.users else "No users assigned"}
                        {"<br><small class='text-muted'>... and " + str(len(role.users) - 10) + " more</small>" if len(role.users) > 10 else ""}
                    </div>
                </div>
            </div>
        </div>
        """

        return jsonify({'success': True, 'html': details_html})
    except Exception as e:
        logger.error(f"Error getting role details: {e}")
        return jsonify({'success': False, 'message': 'Error loading role details'})


@admin_panel_bp.route('/users/roles/assign', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def assign_user_roles():
    """Assign roles to a user."""
    user_id = request.form.get('user_id')
    role_ids = request.form.getlist('role_ids')

    if not user_id:
        flash('User ID is required', 'error')
        return redirect(url_for('admin_panel.roles_management'))

    user = User.query.options(joinedload(User.player)).get_or_404(user_id)

    # Track roles for sync
    old_roles = set(user.roles)
    new_roles = set()

    # Clear existing roles and assign new ones
    user.roles.clear()
    for role_id in role_ids:
        role = Role.query.get(role_id)
        if role:
            user.roles.append(role)
            new_roles.add(role)

    # Sync Flask->Discord role mappings
    roles_added = new_roles - old_roles
    roles_removed = old_roles - new_roles

    for role in roles_added:
        if role.discord_role_id and role.sync_enabled:
            try:
                sync_role_assignment(user, role)
                logger.info(f"Synced Discord role {role.name} for user {user.username}")
            except Exception as e:
                logger.error(f"Failed to sync Discord role {role.name}: {e}")

    for role in roles_removed:
        if role.discord_role_id and role.sync_enabled:
            try:
                sync_role_removal(user, role)
                logger.info(f"Removed Discord role {role.name} from user {user.username}")
            except Exception as e:
                logger.error(f"Failed to remove Discord role {role.name}: {e}")

    # Sync ECS FC Coach role to player_teams.is_coach
    ecs_fc_coach_added = any(role.name == 'ECS FC Coach' for role in roles_added)
    ecs_fc_coach_removed = any(role.name == 'ECS FC Coach' for role in roles_removed)

    if ecs_fc_coach_added:
        try:
            sync_ecs_fc_coach_status(user, is_adding_role=True)
        except Exception as e:
            logger.error(f"Failed to sync ECS FC Coach status for user {user.id}: {e}")

    if ecs_fc_coach_removed:
        try:
            sync_ecs_fc_coach_status(user, is_adding_role=False)
        except Exception as e:
            logger.error(f"Failed to remove ECS FC Coach status for user {user.id}: {e}")

    # Trigger Discord role sync if player has Discord ID (for team-based roles)
    if user.player and user.player.discord_id:
        assign_roles_to_player_task.delay(player_id=user.player.id, only_add=False)
        logger.info(f"Triggered Discord role sync for user {user.id} after role assignment")

    # Log the action
    AdminAuditLog.log_action(
        user_id=current_user.id,
        action='assign_roles',
        resource_type='user_roles',
        resource_id=str(user_id),
        new_value=f"Assigned roles: {', '.join([Role.query.get(rid).name for rid in role_ids if Role.query.get(rid)])}",
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent')
    )

    flash(f'Roles assigned to "{user.name or user.username}" successfully', 'success')
    return redirect(url_for('admin_panel.roles_management'))


@admin_panel_bp.route('/users/roles/search', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def search_users_by_role():
    """Search users by role."""
    try:
        role_id = request.form.get('role_id')

        if not role_id:
            flash('Role ID is required', 'error')
            return redirect(url_for('admin_panel.roles_management'))

        role = Role.query.get_or_404(role_id)
        search_results = role.users
        search_role_name = role.name

        # Get all roles and users for the template
        roles = Role.query.order_by(Role.name).all()
        users = User.query.order_by(User.username).all()
        users_with_roles = User.query.join(User.roles).distinct().count()
        admin_roles = len([r for r in roles if 'Admin' in r.name])

        return render_template('admin_panel/users/roles_flowbite.html',
                               roles=roles,
                               users=users,
                               permissions=[],
                               users_with_roles=users_with_roles,
                               admin_roles=admin_roles,
                               search_results=search_results,
                               search_role_name=search_role_name)
    except Exception as e:
        logger.error(f"Error searching users by role: {e}")
        flash('User role search failed. Verify database connection and role data.', 'error')
        return redirect(url_for('admin_panel.roles_management'))


@admin_panel_bp.route('/users/get-roles')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def get_user_roles():
    """Get user roles for management modal via AJAX."""
    try:
        user_id = request.args.get('user_id')
        if not user_id:
            return jsonify({'success': False, 'message': 'User ID is required'})

        user = User.query.options(joinedload(User.roles)).get_or_404(user_id)
        all_roles = Role.query.order_by(Role.name).all()

        # Build HTML for role management interface
        html = f"""
        <div class="user-info mb-3">
            <div class="d-flex align-items-center">
                <div class="avatar-sm me-3">
                    {'<img src="' + (user.profile_picture or '') + '" class="rounded-circle avatar-40">' if user.profile_picture else '<div class="rounded-circle bg-primary d-flex align-items-center justify-content-center text-white avatar-40"><strong>' + (user.username[0].upper() if user.username else 'U') + '</strong></div>'}
                </div>
                <div>
                    <h6 class="mb-1">{user.username or 'N/A'}</h6>
                    <small class="text-muted">{user.email or 'No email'}</small>
                </div>
            </div>
        </div>

        <div class="row">
            <div class="col-md-6">
                <h6>Current Roles</h6>
                <div id="currentRoles" class="border rounded p-3 mb-3 min-h-200">
        """

        if user.roles:
            for role in user.roles:
                html += f"""
                    <div class="d-flex justify-content-between align-items-center mb-2 role-item" data-role-id="{role.id}">
                        <span class="badge bg-info">{role.name}</span>
                        <button class="btn btn-sm btn-outline-danger" data-action="remove-role" data-user-id="{user.id}" data-role-id="{role.id}" data-role-name="{role.name}">
                            <i class="ti ti-x"></i>
                        </button>
                    </div>
                """
        else:
            html += '<p class="text-muted">No roles assigned</p>'

        html += """
                </div>
            </div>
            <div class="col-md-6">
                <h6>Available Roles</h6>
                <div class="border rounded p-3 min-h-200">
        """

        user_role_ids = [r.id for r in user.roles]
        available_roles = [r for r in all_roles if r.id not in user_role_ids]

        if available_roles:
            for role in available_roles:
                html += f"""
                    <div class="d-flex justify-content-between align-items-center mb-2">
                        <span>{role.name}</span>
                        <button class="btn btn-sm btn-outline-success" data-action="add-role" data-user-id="{user.id}" data-role-id="{role.id}" data-role-name="{role.name}">
                            <i class="ti ti-plus"></i>
                        </button>
                    </div>
                """
        else:
            html += '<p class="text-muted">All roles assigned</p>'

        html += """
                </div>
            </div>
        </div>
        """

        return jsonify({'success': True, 'html': html})
    except Exception as e:
        logger.error(f"Error getting user roles: {e}")
        return jsonify({'success': False, 'message': 'Error loading user roles'})


@admin_panel_bp.route('/users/assign-role', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def assign_user_role():
    """Assign or remove role from user via AJAX."""
    try:
        user_id = request.form.get('user_id')
        role_id = request.form.get('role_id')
        action = request.form.get('action')  # 'add' or 'remove'

        if not all([user_id, role_id, action]):
            return jsonify({'success': False, 'message': 'Missing required parameters'})

        user = User.query.options(joinedload(User.player)).get_or_404(user_id)
        role = Role.query.get_or_404(role_id)

        # Refresh user roles from database to avoid stale data issues
        db.session.refresh(user, ['roles'])

        if action == 'add':
            if role not in user.roles:
                user.roles.append(role)
                message = f'Role "{role.name}" added to user "{user.username}"'
                audit_action = 'assign_role'
            else:
                return jsonify({'success': False, 'message': 'User already has this role'})
        elif action == 'remove':
            if role in user.roles:
                user.roles.remove(role)
                message = f'Role "{role.name}" removed from user "{user.username}"'
                audit_action = 'remove_role'
            else:
                return jsonify({'success': False, 'message': 'User does not have this role'})
        else:
            return jsonify({'success': False, 'message': 'Invalid action'})

        db.session.commit()

        # Sync the specific Flask->Discord role mapping if exists
        if role.discord_role_id and role.sync_enabled:
            try:
                if action == 'add':
                    sync_role_assignment(user, role)
                    logger.info(f"Synced Flask->Discord role mapping for {role.name} to user {user.username}")
                else:
                    sync_role_removal(user, role)
                    logger.info(f"Removed Discord role mapping for {role.name} from user {user.username}")
            except Exception as e:
                logger.error(f"Failed to sync Discord role mapping: {e}")

        # Sync ECS FC Coach role to player_teams.is_coach
        if role.name == 'ECS FC Coach':
            try:
                sync_ecs_fc_coach_status(user, is_adding_role=(action == 'add'))
                db.session.commit()  # Commit the player_teams update
            except Exception as e:
                logger.error(f"Failed to sync ECS FC Coach status for user {user.id}: {e}")

        # Trigger Discord role sync if player has Discord ID (for team-based roles)
        if user.player and user.player.discord_id:
            assign_roles_to_player_task.delay(player_id=user.player.id, only_add=False)
            logger.info(f"Triggered Discord role sync for user {user.id} after role {action}")

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action=audit_action,
            resource_type='user_management',
            resource_id=str(user_id),
            new_value=f'{action}:{role.name}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({'success': True, 'message': message})
    except Exception as e:
        logger.error(f"Error assigning user role: {e}")
        return jsonify({'success': False, 'message': 'Error updating user role'})


@admin_panel_bp.route('/users/roles/export', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def export_roles():
    """Export all roles and their permissions as JSON."""
    try:
        roles = Role.query.options(joinedload(Role.permissions)).order_by(Role.name).all()

        export_data = {
            'roles': [],
            'exported_at': db.func.now().compile().string if hasattr(db.func.now().compile(), 'string') else str(db.func.now()),
            'total_roles': len(roles)
        }

        for role in roles:
            role_data = {
                'id': role.id,
                'name': role.name,
                'description': role.description if hasattr(role, 'description') else None,
                'permissions': [p.name for p in role.permissions] if role.permissions else [],
                'user_count': len(role.users) if hasattr(role, 'users') else 0
            }
            export_data['roles'].append(role_data)

        # Log the export action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='export_roles',
            resource_type='role_management',
            resource_id='all',
            new_value=f'Exported {len(roles)} roles',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        from datetime import datetime
        return jsonify({
            'success': True,
            'message': f'Exported {len(roles)} roles successfully',
            'export_data': export_data,
            'filename': f'roles-export-{datetime.now().strftime("%Y%m%d-%H%M%S")}.json'
        })
    except Exception as e:
        logger.error(f"Error exporting roles: {e}")
        return jsonify({'success': False, 'message': 'Failed to export roles'})
