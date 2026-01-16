# app/admin_panel/routes/roles.py

"""
Admin Panel Role Management Routes

This module provides comprehensive role management functionality
for the admin panel, including role CRUD operations, permission
management, and role assignment tracking.
"""

import logging
from datetime import datetime
from flask import render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy import func

from .. import admin_panel_bp
from app.core import db
from app.models.admin_config import AdminAuditLog
from app.models import User, Role, user_roles, Player
from app.decorators import role_required
from app.utils.db_utils import transactional
from app.tasks.tasks_discord import assign_roles_to_player_task

# Set up the module logger
logger = logging.getLogger(__name__)


@admin_panel_bp.route('/roles-management')
@login_required
@role_required(['Global Admin'])
def roles_comprehensive():
    """Role management dashboard."""
    try:
        # Get all roles with user counts
        roles_query = db.session.query(
            Role,
            func.count(user_roles.c.user_id).label('user_count')
        ).outerjoin(user_roles).group_by(Role.id).order_by(Role.name)
        
        roles_data = roles_query.all()
        
        # Get role statistics
        stats = {
            'total_roles': Role.query.count(),
            'admin_roles': Role.query.filter(Role.name.ilike('%admin%')).count(),
            'player_roles': Role.query.filter(Role.name.ilike('%pl-%')).count(),
            'coach_roles': Role.query.filter(Role.name.ilike('%coach%')).count(),
            'total_assignments': db.session.query(user_roles).count()
        }
        
        # Get recent role assignments (last 30 days)
        recent_assignments = db.session.query(
            User.username,
            Role.name.label('role_name'),
            User.created_at
        ).select_from(User).join(user_roles).join(Role).filter(
            User.created_at >= datetime.utcnow().replace(day=1)
        ).order_by(User.created_at.desc()).limit(10).all()
        
        return render_template('admin_panel/roles/manage_roles_flowbite.html',
                             roles_data=roles_data,
                             stats=stats,
                             recent_assignments=recent_assignments)
                             
    except Exception as e:
        logger.error(f"Error loading role management: {e}")
        flash('Error loading role management. Please try again.', 'error')
        return redirect(url_for('admin_panel.dashboard'))


@admin_panel_bp.route('/roles-management/<int:role_id>')
@login_required
@role_required(['Global Admin'])
def role_comprehensive_details(role_id):
    """Get detailed information about a role."""
    try:
        role = Role.query.get_or_404(role_id)
        
        # Get users with this role
        users_with_role = User.query.join(user_roles).filter(
            user_roles.c.role_id == role_id
        ).order_by(User.username).all()
        
        return jsonify({
            'success': True,
            'role': {
                'id': role.id,
                'name': role.name,
                'description': role.description,
                'created_at': None,  # Role model doesn't have created_at field
                'user_count': len(users_with_role),
                'users': [
                    {
                        'id': user.id,
                        'username': user.username,
                        'email': user.email,
                        'is_approved': user.is_approved,
                        'is_active': user.is_active
                    }
                    for user in users_with_role
                ]
            }
        })
        
    except Exception as e:
        logger.error(f"Error getting role details: {e}")
        return jsonify({'success': False, 'message': 'Error loading role details'})


@admin_panel_bp.route('/roles-management/create', methods=['POST'])
@login_required
@role_required(['Global Admin'])
@transactional
def create_role_comprehensive():
    """Create a new role."""
    try:
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        
        if not name:
            return jsonify({'success': False, 'message': 'Role name is required'})
        
        # Check if role already exists
        existing_role = Role.query.filter_by(name=name).first()
        if existing_role:
            return jsonify({'success': False, 'message': 'Role with this name already exists'})
        
        # Create new role
        role = Role(
            name=name,
            description=description
        )
        
        db.session.add(role)

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='create_role',
            resource_type='role',
            resource_id=str(role.id),
            new_value=f'Created role: {role.name}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        flash(f'Role "{role.name}" created successfully!', 'success')
        return jsonify({'success': True, 'message': 'Role created successfully', 'role_id': role.id})
        
    except Exception as e:
        logger.error(f"Error creating role: {e}")
        return jsonify({'success': False, 'message': 'Error creating role'})


@admin_panel_bp.route('/roles-management/<int:role_id>/edit', methods=['POST'])
@login_required
@role_required(['Global Admin'])
@transactional
def edit_role_comprehensive(role_id):
    """Edit a role."""
    try:
        role = Role.query.get_or_404(role_id)
        
        old_data = {
            'name': role.name,
            'description': role.description
        }
        
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        
        if not name:
            return jsonify({'success': False, 'message': 'Role name is required'})
        
        # Check if another role has this name
        existing_role = Role.query.filter(Role.name == name, Role.id != role_id).first()
        if existing_role:
            return jsonify({'success': False, 'message': 'Another role with this name already exists'})
        
        # Update role
        role.name = name
        role.description = description

        # Log the action
        new_data = {
            'name': role.name,
            'description': role.description
        }
        
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='edit_role',
            resource_type='role',
            resource_id=str(role.id),
            old_value=str(old_data),
            new_value=str(new_data),
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        flash(f'Role "{role.name}" updated successfully!', 'success')
        return jsonify({'success': True, 'message': 'Role updated successfully'})
        
    except Exception as e:
        logger.error(f"Error editing role: {e}")
        return jsonify({'success': False, 'message': 'Error updating role'})


@admin_panel_bp.route('/roles-management/<int:role_id>/delete', methods=['POST'])
@login_required
@role_required(['Global Admin'])
@transactional
def delete_role_comprehensive(role_id):
    """Delete a role."""
    try:
        role = Role.query.get_or_404(role_id)
        
        # Check if role is in use
        user_count = db.session.query(user_roles).filter_by(role_id=role_id).count()
        if user_count > 0:
            return jsonify({
                'success': False, 
                'message': f'Cannot delete role "{role.name}" - it is assigned to {user_count} user(s)'
            })
        
        # Check if it's a system role
        system_roles = ['Global Admin', 'Pub League Admin', 'Discord Admin']
        if role.name in system_roles:
            return jsonify({
                'success': False,
                'message': f'Cannot delete system role "{role.name}"'
            })
        
        role_name = role.name
        db.session.delete(role)

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='delete_role',
            resource_type='role',
            resource_id=str(role_id),
            old_value=f'Deleted role: {role_name}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        flash(f'Role "{role_name}" deleted successfully!', 'success')
        return jsonify({'success': True, 'message': 'Role deleted successfully'})
        
    except Exception as e:
        logger.error(f"Error deleting role: {e}")
        return jsonify({'success': False, 'message': 'Error deleting role'})


@admin_panel_bp.route('/roles-management/<int:role_id>/users')
@login_required
@role_required(['Global Admin'])
def role_comprehensive_users(role_id):
    """Get users assigned to a specific role."""
    try:
        role = Role.query.get_or_404(role_id)
        
        # Get users with this role with pagination
        page = request.args.get('page', 1, type=int)
        per_page = 25
        
        users_query = User.query.join(user_roles).filter(
            user_roles.c.role_id == role_id
        ).order_by(User.username)
        
        users_pagination = users_query.paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        return render_template('admin_panel/roles/role_users_flowbite.html',
                             role=role,
                             users=users_pagination.items,
                             pagination=users_pagination)
                             
    except Exception as e:
        logger.error(f"Error loading role users: {e}")
        flash('Error loading role users. Please try again.', 'error')
        return redirect(url_for('admin_panel.roles_comprehensive'))


@admin_panel_bp.route('/roles-management/<int:role_id>/assign-user', methods=['POST'])
@login_required
@role_required(['Global Admin'])
@transactional
def assign_role_to_user_comprehensive(role_id):
    """Assign a role to a user."""
    try:
        role = Role.query.get_or_404(role_id)
        user_id = request.form.get('user_id', type=int)
        
        if not user_id:
            return jsonify({'success': False, 'message': 'User ID is required'})
        
        user = User.query.get_or_404(user_id)
        
        # Check if user already has this role
        if role in user.roles:
            return jsonify({'success': False, 'message': f'User already has role "{role.name}"'})
        
        # Add role to user
        user.roles.append(role)

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='assign_role',
            resource_type='user_role',
            resource_id=f'{user_id}:{role_id}',
            new_value=f'Assigned role "{role.name}" to user "{user.username}"',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        # Trigger Discord role sync
        if user.player and user.player.discord_id:
            assign_roles_to_player_task.delay(player_id=user.player.id, only_add=False)
            logger.info(f"Triggered Discord role sync for user {user.id} after role assignment")

        flash(f'Role "{role.name}" assigned to user "{user.username}" successfully!', 'success')
        return jsonify({'success': True, 'message': 'Role assigned successfully'})
        
    except Exception as e:
        logger.error(f"Error assigning role: {e}")
        return jsonify({'success': False, 'message': 'Error assigning role'})


@admin_panel_bp.route('/roles-management/<int:role_id>/remove-user/<int:user_id>', methods=['POST'])
@login_required
@role_required(['Global Admin'])
@transactional
def remove_role_from_user_comprehensive(role_id, user_id):
    """Remove a role from a user."""
    try:
        role = Role.query.get_or_404(role_id)
        user = User.query.get_or_404(user_id)
        
        # Check if user has this role
        if role not in user.roles:
            return jsonify({'success': False, 'message': f'User does not have role "{role.name}"'})
        
        # Remove role from user
        user.roles.remove(role)

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='remove_role',
            resource_type='user_role',
            resource_id=f'{user_id}:{role_id}',
            old_value=f'Removed role "{role.name}" from user "{user.username}"',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        # Trigger Discord role sync
        if user.player and user.player.discord_id:
            assign_roles_to_player_task.delay(player_id=user.player.id, only_add=False)
            logger.info(f"Triggered Discord role sync for user {user.id} after role removal")

        flash(f'Role "{role.name}" removed from user "{user.username}" successfully!', 'success')
        return jsonify({'success': True, 'message': 'Role removed successfully'})

    except Exception as e:
        logger.error(f"Error removing role: {e}")
        return jsonify({'success': False, 'message': 'Error removing role'})


@admin_panel_bp.route('/roles-management/<int:role_id>/available-users')
@login_required
@role_required(['Global Admin'])
def get_available_users_for_role(role_id):
    """Get users who don't have the specified role yet."""
    try:
        role = Role.query.get_or_404(role_id)
        search = request.args.get('search', '').strip()

        # Get users who don't have this role (use select() for proper IN clause)
        users_with_role_subq = db.select(user_roles.c.user_id).where(
            user_roles.c.role_id == role_id
        )

        query = User.query.outerjoin(Player, User.id == Player.user_id).filter(
            User.id.not_in(users_with_role_subq)
        )

        # Apply search filter - search by Player name (email/phone are encrypted)
        if search:
            search_term = f'%{search}%'
            query = query.filter(
                db.or_(
                    User.username.ilike(search_term),
                    Player.name.ilike(search_term)
                )
            )

        # Limit results
        users = query.order_by(User.username).limit(100).all()

        return jsonify({
            'success': True,
            'users': [
                {
                    'id': user.id,
                    'username': user.username,
                    'email': user.email,
                    'player_name': user.player.name if user.player else None,
                    'is_active': user.is_active
                }
                for user in users
            ]
        })

    except Exception as e:
        logger.error(f"Error getting available users for role: {e}")
        return jsonify({'success': False, 'message': 'Error loading users'})


@admin_panel_bp.route('/roles-management/all-users')
@login_required
@role_required(['Global Admin'])
def get_all_users_for_roles():
    """Get all users for role management."""
    try:
        search = request.args.get('search', '').strip()

        query = User.query.options(joinedload(User.roles), joinedload(User.player)).outerjoin(
            Player, User.id == Player.user_id
        )

        # Apply search filter - search by Player name (email/phone are encrypted)
        if search:
            search_term = f'%{search}%'
            query = query.filter(
                db.or_(
                    User.username.ilike(search_term),
                    Player.name.ilike(search_term)
                )
            )

        # Limit results
        users = query.order_by(User.username).limit(100).all()

        return jsonify({
            'success': True,
            'users': [
                {
                    'id': user.id,
                    'username': user.username,
                    'email': user.email,
                    'player_name': user.player.name if user.player else None,
                    'is_active': user.is_active,
                    'roles': [r.name for r in user.roles]
                }
                for user in users
            ]
        })

    except Exception as e:
        logger.error(f"Error getting all users: {e}")
        return jsonify({'success': False, 'message': 'Error loading users'})