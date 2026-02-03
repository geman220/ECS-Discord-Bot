# app/admin_panel/routes/user_management/bulk_operations.py

"""
Bulk User Operations Routes

Routes for bulk user operations:
- Bulk operations page
- Bulk approve users
- Bulk role assignment
- Bulk waitlist processing
"""

import logging
from datetime import datetime

from flask import render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import or_
from sqlalchemy.orm import joinedload

from app.admin_panel import admin_panel_bp
from app.core import db
from app.models.admin_config import AdminAuditLog
from app.models.core import User, Role
from app.decorators import role_required
from app.utils.db_utils import transactional
from app.tasks.tasks_discord import assign_roles_to_player_task, remove_player_roles_task
from app.utils.user_helpers import safe_current_user

logger = logging.getLogger(__name__)


@admin_panel_bp.route('/users/bulk-operations')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def bulk_operations():
    """Bulk user operations management page."""
    try:
        # Get user statistics for bulk operations
        pending_users = User.query.filter_by(approval_status='pending').count()
        waitlist_users = User.query.join(User.roles).filter(Role.name == 'pl-waitlist').count()

        # Get role statistics for bulk assignments
        roles = Role.query.order_by(Role.name).all()
        role_stats = {}
        for role in roles:
            role_stats[role.name] = len(role.users)

        # Get recent bulk operations from audit logs
        recent_bulk_ops = AdminAuditLog.query.filter(
            or_(
                AdminAuditLog.action.contains('bulk'),
                AdminAuditLog.resource_id == 'bulk'
            )
        ).order_by(AdminAuditLog.timestamp.desc()).limit(10).all()

        bulk_stats = {
            'pending_users': pending_users,
            'waitlist_users': waitlist_users,
            'total_roles': len(roles),
            'recent_operations': len(recent_bulk_ops)
        }

        return render_template('admin_panel/users/bulk_operations_flowbite.html',
                               bulk_stats=bulk_stats,
                               roles=roles,
                               role_stats=role_stats,
                               recent_bulk_ops=recent_bulk_ops)
    except Exception as e:
        logger.error(f"Error loading bulk operations: {e}")
        flash('Bulk operations unavailable. Check database connectivity and user models.', 'error')
        return redirect(url_for('admin_panel.user_management'))


@admin_panel_bp.route('/users/bulk-operations/approve', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def bulk_approve_users():
    """Bulk approve users with specified league assignments."""
    try:
        current_user_safe = safe_current_user
        data = request.get_json()

        user_ids = data.get('user_ids', [])
        default_league = data.get('default_league', 'classic')
        send_notifications = data.get('send_notifications', True)

        if not user_ids:
            return jsonify({'success': False, 'message': 'No users selected'}), 400

        # Validate league type
        valid_leagues = ['classic', 'premier', 'ecs-fc', 'sub-classic', 'sub-premier', 'sub-ecs-fc']
        if default_league not in valid_leagues:
            return jsonify({'success': False, 'message': 'Invalid league type'}), 400

        # Get role mapping
        role_mapping = {
            'classic': 'pl-classic',
            'premier': 'pl-premier',
            'ecs-fc': 'pl-ecs-fc',
            'sub-classic': 'Classic Sub',
            'sub-premier': 'Premier Sub',
            'sub-ecs-fc': 'ECS FC Sub'
        }

        new_role_name = role_mapping[default_league]
        new_role = Role.query.filter_by(name=new_role_name).first()

        if not new_role:
            return jsonify({'success': False, 'message': f'Role {new_role_name} not found'}), 404

        # Get unverified role to remove
        unverified_role = Role.query.filter_by(name='pl-unverified').first()

        approved_count = 0
        failed_users = []

        for user_id in user_ids:
            try:
                user = User.query.options(
                    joinedload(User.player),
                    joinedload(User.roles)
                ).get(user_id)

                if not user or user.approval_status != 'pending':
                    failed_users.append({'id': user_id, 'reason': 'User not found or not pending'})
                    continue

                # Refresh user roles from database to avoid stale data issues
                db.session.refresh(user, ['roles'])

                # Remove unverified role
                if unverified_role and unverified_role in user.roles:
                    user.roles.remove(unverified_role)

                # Add new role
                if new_role not in user.roles:
                    user.roles.append(new_role)

                # Update approval status
                user.approval_status = 'approved'
                user.is_approved = True
                user.approval_league = default_league
                user.approved_by = current_user_safe.id
                user.approved_at = datetime.utcnow()
                user.approval_notes = f'Bulk approved for {default_league} league'

                # Queue Discord role sync
                if user.player and user.player.discord_id:
                    assign_roles_to_player_task.delay(player_id=user.player.id, only_add=False)

                approved_count += 1

            except Exception as e:
                logger.error(f"Error bulk approving user {user_id}: {e}")
                failed_users.append({'id': user_id, 'reason': str(e)})

        # Log the bulk action
        AdminAuditLog.log_action(
            user_id=current_user_safe.id,
            action='bulk_approve_users',
            resource_type='user_approval',
            resource_id='bulk',
            new_value=f'Approved {approved_count} users for {default_league} league',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        result_message = f'Successfully approved {approved_count} users'
        if failed_users:
            result_message += f' ({len(failed_users)} failed)'

        return jsonify({
            'success': True,
            'message': result_message,
            'approved_count': approved_count,
            'failed_count': len(failed_users),
            'failed_users': failed_users
        })

    except Exception as e:
        logger.error(f"Error in bulk approve users: {e}")
        return jsonify({'success': False, 'message': 'Bulk approval failed'}), 500


@admin_panel_bp.route('/users/bulk-operations/role-assign', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def bulk_assign_roles():
    """Bulk assign roles to multiple users."""
    try:
        current_user_safe = safe_current_user
        data = request.get_json()

        user_ids = data.get('user_ids', [])
        role_ids = data.get('role_ids', [])
        operation = data.get('operation', 'add')  # add, remove, replace

        if not user_ids or not role_ids:
            return jsonify({'success': False, 'message': 'Users and roles must be selected'}), 400

        # Get roles to assign
        roles = Role.query.filter(Role.id.in_(role_ids)).all()
        if len(roles) != len(role_ids):
            return jsonify({'success': False, 'message': 'One or more roles not found'}), 404

        processed_count = 0
        failed_users = []

        for user_id in user_ids:
            try:
                user = User.query.options(
                    joinedload(User.roles),
                    joinedload(User.player)
                ).get(user_id)
                if not user:
                    failed_users.append({'id': user_id, 'reason': 'User not found'})
                    continue

                # Refresh user roles from database to avoid stale data issues
                db.session.refresh(user, ['roles'])

                if operation == 'replace':
                    # Clear all existing roles and assign new ones
                    user.roles.clear()
                    for role in roles:
                        user.roles.append(role)
                elif operation == 'add':
                    # Add roles if not already present
                    for role in roles:
                        if role not in user.roles:
                            user.roles.append(role)
                elif operation == 'remove':
                    # Remove specified roles
                    for role in roles:
                        if role in user.roles:
                            user.roles.remove(role)

                # Sync Discord roles if player has Discord integration
                if user.player and user.player.discord_id:
                    assign_roles_to_player_task.delay(player_id=user.player.id, only_add=False)

                processed_count += 1

            except Exception as e:
                logger.error(f"Error bulk assigning roles to user {user_id}: {e}")
                failed_users.append({'id': user_id, 'reason': str(e)})

        # Log the bulk action
        role_names = [role.name for role in roles]
        AdminAuditLog.log_action(
            user_id=current_user_safe.id,
            action='bulk_assign_roles',
            resource_type='user_roles',
            resource_id='bulk',
            new_value=f'{operation.title()} roles [{", ".join(role_names)}] for {processed_count} users',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        result_message = f'Successfully {operation}ed roles for {processed_count} users'
        if failed_users:
            result_message += f' ({len(failed_users)} failed)'

        return jsonify({
            'success': True,
            'message': result_message,
            'processed_count': processed_count,
            'failed_count': len(failed_users),
            'failed_users': failed_users
        })

    except Exception as e:
        logger.error(f"Error in bulk role assignment: {e}")
        return jsonify({'success': False, 'message': 'Bulk role assignment failed'}), 500


@admin_panel_bp.route('/users/bulk-operations/waitlist-process', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def bulk_process_waitlist():
    """Bulk process waitlist users to pending approval."""
    try:
        current_user_safe = safe_current_user
        data = request.get_json()

        user_ids = data.get('user_ids', [])
        action = data.get('action', 'move_to_pending')  # move_to_pending, remove_from_waitlist

        if not user_ids:
            return jsonify({'success': False, 'message': 'No users selected'}), 400

        # Get roles
        waitlist_role = Role.query.filter_by(name='pl-waitlist').first()
        unverified_role = Role.query.filter_by(name='pl-unverified').first()

        if not waitlist_role:
            return jsonify({'success': False, 'message': 'Waitlist role not found'}), 404

        processed_count = 0
        failed_users = []

        for user_id in user_ids:
            try:
                user = User.query.options(
                    joinedload(User.roles),
                    joinedload(User.player)
                ).get(user_id)
                if not user:
                    failed_users.append({'id': user_id, 'reason': 'User not found'})
                    continue

                # Refresh user roles from database to avoid stale data issues
                db.session.refresh(user, ['roles'])

                if waitlist_role not in user.roles:
                    failed_users.append({'id': user_id, 'reason': 'User not on waitlist'})
                    continue

                # Remove from waitlist
                user.roles.remove(waitlist_role)

                if action == 'move_to_pending':
                    # Add unverified role and set to pending
                    if unverified_role and unverified_role not in user.roles:
                        user.roles.append(unverified_role)
                    user.approval_status = 'pending'
                elif action == 'remove_from_waitlist':
                    # Just remove from waitlist without adding to pending
                    pass

                user.updated_at = datetime.utcnow()

                # Sync Discord roles
                if user.player and user.player.discord_id:
                    if action == 'move_to_pending':
                        assign_roles_to_player_task.delay(player_id=user.player.id, only_add=False)
                    else:
                        remove_player_roles_task.delay(player_id=user.player.id)

                processed_count += 1

            except Exception as e:
                logger.error(f"Error processing waitlist user {user_id}: {e}")
                failed_users.append({'id': user_id, 'reason': str(e)})

        # Log the bulk action
        AdminAuditLog.log_action(
            user_id=current_user_safe.id,
            action='bulk_process_waitlist',
            resource_type='user_waitlist',
            resource_id='bulk',
            new_value=f'{action} for {processed_count} users',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        result_message = f'Successfully processed {processed_count} waitlist users'
        if failed_users:
            result_message += f' ({len(failed_users)} failed)'

        return jsonify({
            'success': True,
            'message': result_message,
            'processed_count': processed_count,
            'failed_count': len(failed_users),
            'failed_users': failed_users
        })

    except Exception as e:
        logger.error(f"Error in bulk waitlist processing: {e}")
        return jsonify({'success': False, 'message': 'Bulk waitlist processing failed'}), 500
