# app/admin_panel/routes/communication/messaging_settings.py

"""
In-App Messaging Settings Routes

This module contains routes for configuring the in-app direct messaging system:
- Global messaging settings (enable/disable, message limits)
- Role-to-role permission matrix
- Messaging statistics
"""

import logging
from flask import render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user

from app.admin_panel import admin_panel_bp
from app.core import db
from app.models import Role
from app.models.messages import MessagingSettings, MessagingPermission, DirectMessage
from app.models.admin_config import AdminAuditLog
from app.decorators import role_required

logger = logging.getLogger(__name__)


@admin_panel_bp.route('/communication/messaging-settings')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def messaging_settings():
    """In-app messaging settings page with permission matrix."""
    try:
        # Get current settings
        settings = MessagingSettings.get_settings()

        # Get all roles for the permission matrix
        roles = Role.query.order_by(Role.name).all()

        # Get existing permissions as a dictionary
        permissions = {}
        for perm in MessagingPermission.query.all():
            key = f"{perm.sender_role_id}_{perm.recipient_role_id}"
            permissions[key] = perm.is_allowed

        # Get messaging statistics
        total_messages = DirectMessage.query.count()
        messages_today = DirectMessage.query.filter(
            db.func.date(DirectMessage.created_at) == db.func.current_date()
        ).count()

        # Get unique conversation count (approximate)
        conversations = db.session.query(
            db.func.count(db.distinct(
                db.case(
                    (DirectMessage.sender_id < DirectMessage.recipient_id,
                     db.func.concat(DirectMessage.sender_id, '_', DirectMessage.recipient_id)),
                    else_=db.func.concat(DirectMessage.recipient_id, '_', DirectMessage.sender_id)
                )
            ))
        ).scalar() or 0

        stats = {
            'total_messages': total_messages,
            'messages_today': messages_today,
            'total_conversations': conversations,
            'unread_messages': DirectMessage.query.filter_by(is_read=False).count()
        }

        return render_template(
            'admin_panel/communication/messaging_settings_flowbite.html',
            settings=settings,
            roles=roles,
            permissions=permissions,
            stats=stats
        )

    except Exception as e:
        logger.error(f"Error loading messaging settings: {e}")
        flash('Messaging settings unavailable. Check database connectivity.', 'error')
        return redirect(url_for('admin_panel.communication_hub'))


@admin_panel_bp.route('/communication/messaging-settings/update', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def update_messaging_settings():
    """Update global messaging settings."""
    try:
        settings = MessagingSettings.get_settings()

        # Track changes for audit log
        changes = []

        # Update enabled status
        new_enabled = request.form.get('enabled') == 'on'
        if settings.enabled != new_enabled:
            changes.append(f"enabled: {settings.enabled} -> {new_enabled}")
            settings.enabled = new_enabled

        # Update max message length
        new_max_length = request.form.get('max_message_length', type=int)
        if new_max_length and 100 <= new_max_length <= 10000:
            if settings.max_message_length != new_max_length:
                changes.append(f"max_message_length: {settings.max_message_length} -> {new_max_length}")
                settings.max_message_length = new_max_length

        # Update retention days
        new_retention = request.form.get('message_retention_days', type=int)
        if new_retention and 7 <= new_retention <= 365:
            if settings.message_retention_days != new_retention:
                changes.append(f"message_retention_days: {settings.message_retention_days} -> {new_retention}")
                settings.message_retention_days = new_retention

        # Update typing indicators
        new_typing = request.form.get('typing_indicators') == 'on'
        if settings.typing_indicators != new_typing:
            changes.append(f"typing_indicators: {settings.typing_indicators} -> {new_typing}")
            settings.typing_indicators = new_typing

        # Update read receipts
        new_receipts = request.form.get('read_receipts') == 'on'
        if settings.read_receipts != new_receipts:
            changes.append(f"read_receipts: {settings.read_receipts} -> {new_receipts}")
            settings.read_receipts = new_receipts

        db.session.commit()

        # Log the action
        if changes:
            AdminAuditLog.log_action(
                user_id=current_user.id,
                action='update_messaging_settings',
                resource_type='messaging_settings',
                resource_id='global',
                new_value='; '.join(changes),
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )

        flash('Messaging settings updated successfully!', 'success')
        return redirect(url_for('admin_panel.messaging_settings'))

    except Exception as e:
        logger.error(f"Error updating messaging settings: {e}")
        db.session.rollback()
        flash('Failed to update settings. Check database connectivity.', 'error')
        return redirect(url_for('admin_panel.messaging_settings'))


@admin_panel_bp.route('/communication/messaging-settings/permissions', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def update_messaging_permissions():
    """Update role-to-role messaging permissions."""
    try:
        data = request.get_json()

        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400

        sender_role_id = data.get('sender_role_id')
        recipient_role_id = data.get('recipient_role_id')
        is_allowed = data.get('is_allowed', False)

        if not sender_role_id or not recipient_role_id:
            return jsonify({'success': False, 'error': 'Missing role IDs'}), 400

        # Find or create permission
        permission = MessagingPermission.query.filter_by(
            sender_role_id=sender_role_id,
            recipient_role_id=recipient_role_id
        ).first()

        if permission:
            old_value = permission.is_allowed
            permission.is_allowed = is_allowed
            permission.updated_by = current_user.id
        else:
            permission = MessagingPermission(
                sender_role_id=sender_role_id,
                recipient_role_id=recipient_role_id,
                is_allowed=is_allowed,
                updated_by=current_user.id
            )
            db.session.add(permission)
            old_value = None

        db.session.commit()

        # Log the action
        sender_role = Role.query.get(sender_role_id)
        recipient_role = Role.query.get(recipient_role_id)

        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='update_messaging_permission',
            resource_type='messaging_permissions',
            resource_id=f'{sender_role_id}_{recipient_role_id}',
            old_value=str(old_value) if old_value is not None else 'new',
            new_value=str(is_allowed),
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({
            'success': True,
            'message': f'Permission updated: {sender_role.name} -> {recipient_role.name} = {is_allowed}'
        })

    except Exception as e:
        logger.error(f"Error updating messaging permission: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Failed to update permission'}), 500


@admin_panel_bp.route('/communication/messaging-settings/permissions/bulk', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def bulk_update_messaging_permissions():
    """Bulk update permissions from the matrix form."""
    try:
        # Get all roles
        roles = Role.query.all()
        role_ids = [r.id for r in roles]

        changes = []

        # Process each permission checkbox
        for sender_id in role_ids:
            for recipient_id in role_ids:
                key = f"perm_{sender_id}_{recipient_id}"
                is_allowed = request.form.get(key) == 'on'

                # Find or create permission
                permission = MessagingPermission.query.filter_by(
                    sender_role_id=sender_id,
                    recipient_role_id=recipient_id
                ).first()

                if permission:
                    if permission.is_allowed != is_allowed:
                        changes.append(f"{sender_id}->{recipient_id}: {permission.is_allowed}->{is_allowed}")
                        permission.is_allowed = is_allowed
                        permission.updated_by = current_user.id
                else:
                    # Only create if allowing (default is deny)
                    if is_allowed:
                        permission = MessagingPermission(
                            sender_role_id=sender_id,
                            recipient_role_id=recipient_id,
                            is_allowed=is_allowed,
                            updated_by=current_user.id
                        )
                        db.session.add(permission)
                        changes.append(f"{sender_id}->{recipient_id}: new->True")

        db.session.commit()

        # Log the action
        if changes:
            AdminAuditLog.log_action(
                user_id=current_user.id,
                action='bulk_update_messaging_permissions',
                resource_type='messaging_permissions',
                resource_id='bulk',
                new_value=f'{len(changes)} permissions updated',
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )

        flash(f'Messaging permissions updated! ({len(changes)} changes)', 'success')
        return redirect(url_for('admin_panel.messaging_settings'))

    except Exception as e:
        logger.error(f"Error bulk updating messaging permissions: {e}")
        db.session.rollback()
        flash('Failed to update permissions. Check database connectivity.', 'error')
        return redirect(url_for('admin_panel.messaging_settings'))


@admin_panel_bp.route('/communication/messaging-settings/stats')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def messaging_stats_api():
    """Get messaging statistics via AJAX."""
    try:
        from datetime import datetime, timedelta

        # Messages over time (last 7 days)
        daily_counts = []
        for i in range(6, -1, -1):
            date = datetime.utcnow().date() - timedelta(days=i)
            count = DirectMessage.query.filter(
                db.func.date(DirectMessage.created_at) == date
            ).count()
            daily_counts.append({
                'date': date.strftime('%b %d'),
                'count': count
            })

        # Top messagers
        top_senders = db.session.query(
            DirectMessage.sender_id,
            db.func.count(DirectMessage.id).label('count')
        ).group_by(DirectMessage.sender_id).order_by(
            db.desc('count')
        ).limit(5).all()

        from app.models import User
        top_users = []
        for sender_id, count in top_senders:
            user = User.query.get(sender_id)
            if user:
                top_users.append({
                    'name': user.player.name if user.player else user.username,
                    'count': count
                })

        return jsonify({
            'success': True,
            'daily_counts': daily_counts,
            'top_users': top_users,
            'total': DirectMessage.query.count(),
            'unread': DirectMessage.query.filter_by(is_read=False).count()
        })

    except Exception as e:
        logger.error(f"Error getting messaging stats: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
