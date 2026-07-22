# app/admin_panel/routes/communication/ajax.py

"""
Communication AJAX Routes

AJAX utility routes for communication operations:
- Notification details (modal on the Push Notifications page)
- Notification duplicate
"""

import logging
from datetime import datetime

from flask import request, jsonify
from flask_login import login_required, current_user

from app.admin_panel import admin_panel_bp
from app.core import db
from app.models.admin_config import AdminAuditLog
from app.decorators import role_required
from app.utils.db_utils import transactional

logger = logging.getLogger(__name__)


@admin_panel_bp.route('/push-notifications/<int:notification_id>/details')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def get_notification_details(notification_id):
    """Get detailed notification information for modal display."""
    try:
        from app.models.communication import Notification
        notification = Notification.query.get_or_404(notification_id)

        notification_data = {
            'id': notification.id,
            'content': notification.content,
            'notification_type': notification.notification_type,
            'icon': notification.icon,
            'read': notification.read,
            'created_at': notification.created_at.isoformat() if notification.created_at else None,
            'user_id': notification.user_id,
            'user_name': notification.user.username if notification.user else 'Unknown'
        }

        return jsonify({'success': True, 'notification': notification_data})

    except Exception as e:
        logger.error(f"Error getting notification details: {e}")
        return jsonify({'success': False, 'message': 'Error retrieving notification details'}), 500


@admin_panel_bp.route('/push-notifications/<int:notification_id>/duplicate', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def duplicate_notification(notification_id):
    """Duplicate an existing push notification."""
    try:
        from app.models.communication import Notification

        # Get the original notification
        original = Notification.query.get_or_404(notification_id)

        # Create duplicate
        duplicate = Notification(
            user_id=original.user_id,
            content=f"Copy of {original.content}"[:255],  # column is String(255)
            notification_type=original.notification_type,
            icon=original.icon,
            read=False,
            created_at=datetime.utcnow()
        )

        db.session.add(duplicate)

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='duplicate_notification',
            resource_type='push_notifications',
            resource_id=str(notification_id),
            new_value=f'Created duplicate of notification {notification_id}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({
            'success': True,
            'message': 'Notification duplicated successfully',
            'new_id': duplicate.id
        })

    except Exception as e:
        logger.error(f"Error duplicating notification: {e}")
        return jsonify({'success': False, 'message': 'Failed to duplicate notification'}), 500


