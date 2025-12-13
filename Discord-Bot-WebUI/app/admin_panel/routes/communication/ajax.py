# app/admin_panel/routes/communication/ajax.py

"""
Communication AJAX Routes

AJAX utility routes for communication operations including:
- Scheduled message details
- Notification details
- Template preview
"""

import logging
import re
from datetime import datetime

from flask import request, jsonify
from flask_login import login_required, current_user

from app.admin_panel import admin_panel_bp
from app.core import db
from app.models.admin_config import AdminAuditLog
from app.models.communication import Notification
from app.decorators import role_required

logger = logging.getLogger(__name__)


def extract_template_variables(content):
    """Extract template variables from content."""
    # Match {{variable}} and {variable} patterns
    pattern = r'\{\{?\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}?\}'
    variables = re.findall(pattern, content)
    return list(set(variables))  # Remove duplicates


@admin_panel_bp.route('/scheduled-messages/details')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def get_scheduled_message_details():
    """Get scheduled message details via AJAX."""
    try:
        message_id = request.args.get('message_id')

        if not message_id:
            return jsonify({'success': False, 'message': 'Message ID is required'})

        # Get scheduled message details from ScheduledMessage model
        try:
            from app.models import ScheduledMessage
            message = ScheduledMessage.query.get(message_id)

            if not message:
                return jsonify({'success': False, 'message': 'Scheduled message not found'})

            details_html = f"""
            <div class="scheduled-message-details">
                <div class="row">
                    <div class="col-md-6">
                        <strong>Subject:</strong> {message.subject or 'No subject'}<br>
                        <strong>Message Type:</strong> {message.message_type or 'General'}<br>
                        <strong>Recipients:</strong> {message.recipient_type or 'All users'}<br>
                        <strong>Scheduled Time:</strong> {message.scheduled_time.strftime('%Y-%m-%d %H:%M') if message.scheduled_time else 'Not scheduled'}<br>
                    </div>
                    <div class="col-md-6">
                        <strong>Status:</strong> {message.status or 'Pending'}<br>
                        <strong>Created:</strong> {message.created_at.strftime('%Y-%m-%d %H:%M') if message.created_at else 'Unknown'}<br>
                        <strong>Created by:</strong> {message.created_by_user.username if hasattr(message, 'created_by_user') and message.created_by_user else 'System'}<br>
                        <strong>Priority:</strong> {getattr(message, 'priority', 'Normal')}<br>
                    </div>
                </div>
                <div class="row mt-3">
                    <div class="col-12">
                        <div class="message-content p-3 bg-light rounded">
                            <strong>Message Content:</strong><br>
                            {message.content[:500]}{'...' if len(message.content) > 500 else '' if message.content else 'No content'}
                        </div>
                    </div>
                </div>
            </div>
            """

            return jsonify({'success': True, 'html': details_html})

        except ImportError:
            # Fallback if ScheduledMessage model not available
            details_html = f"""
            <div class="alert alert-info">
                <strong>Message ID:</strong> {message_id}<br>
                <p>Scheduled message system is not fully configured. Please check your message models configuration.</p>
            </div>
            """
            return jsonify({'success': True, 'html': details_html})

        except Exception as model_error:
            logger.error(f"Error loading scheduled message {message_id}: {model_error}")
            details_html = f"""
            <div class="alert alert-warning">
                <strong>Message ID:</strong> {message_id}<br>
                <p>Could not load message details. Please check the message exists and try again.</p>
            </div>
            """
            return jsonify({'success': True, 'html': details_html})
    except Exception as e:
        logger.error(f"Error getting scheduled message details: {e}")
        return jsonify({'success': False, 'message': 'Error loading message details'})


@admin_panel_bp.route('/push-notifications/details')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def get_notification_details_legacy():
    """Get notification details via AJAX."""
    try:
        notification_id = request.args.get('notification_id', type=int)

        if not notification_id:
            return jsonify({'success': False, 'message': 'Notification ID is required'})

        # Get notification details
        notification = Notification.query.get(notification_id)
        if not notification:
            return jsonify({'success': False, 'message': 'Notification not found'})

        # Generate details HTML
        details_html = f"""
        <div class="notification-details">
            <div class="row">
                <div class="col-md-6">
                    <strong>ID:</strong> {notification.id}<br>
                    <strong>User:</strong> {notification.user.username if notification.user else 'Unknown'}<br>
                    <strong>Type:</strong> {notification.notification_type}<br>
                    <strong>Status:</strong> {'Read' if notification.read else 'Unread'}
                </div>
                <div class="col-md-6">
                    <strong>Created:</strong> {notification.created_at.strftime('%Y-%m-%d %H:%M:%S')}<br>
                    <strong>Icon:</strong> {notification.icon or 'Default'}<br>
                </div>
            </div>
            <div class="row mt-3">
                <div class="col-12">
                    <strong>Content:</strong><br>
                    <div class="notification-content p-2 bg-light rounded">
                        {notification.content}
                    </div>
                </div>
            </div>
        </div>
        """

        return jsonify({'success': True, 'html': details_html})
    except Exception as e:
        logger.error(f"Error getting notification details: {e}")
        return jsonify({'success': False, 'message': 'Error loading notification details'})


@admin_panel_bp.route('/push-notifications/<int:notification_id>/details')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def get_notification_details(notification_id):
    """Get detailed notification information for modal display."""
    try:
        from app.models.notifications import Notification
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
def duplicate_notification(notification_id):
    """Duplicate an existing push notification."""
    try:
        from app.models.notifications import Notification

        # Get the original notification
        original = Notification.query.get_or_404(notification_id)

        # Create duplicate
        duplicate = Notification(
            user_id=original.user_id,
            content=f"Copy of {original.content}",
            notification_type=original.notification_type,
            icon=original.icon,
            read=False,
            created_at=datetime.utcnow()
        )

        db.session.add(duplicate)
        db.session.commit()

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


@admin_panel_bp.route('/api/templates/preview', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def preview_template():
    """Preview template with sample data."""
    try:
        data = request.get_json()
        content = data.get('content', '')

        # Sample data for preview
        sample_data = {
            'user_name': 'John Doe',
            'first_name': 'John',
            'last_name': 'Doe',
            'match_date': '2025-08-15',
            'match_time': '7:00 PM',
            'team_name': 'ECS FC',
            'league_name': 'Premier League',
            'venue': 'Memorial Stadium',
            'opponent': 'Rival FC',
            'season': 'Summer 2025',
            'week': '3',
            'score': '2-1',
            'position': 'Midfielder'
        }

        # Replace variables
        rendered_content = content
        for key, value in sample_data.items():
            rendered_content = rendered_content.replace(f'{{{{{key}}}}}', str(value))
            rendered_content = rendered_content.replace(f'{{{key}}}', str(value))

        return jsonify({
            'success': True,
            'rendered_content': rendered_content,
            'variables_found': extract_template_variables(content)
        })

    except Exception as e:
        logger.error(f"Template preview error: {e}")
        return jsonify({
            'success': False,
            'message': 'Preview failed'
        }), 500


@admin_panel_bp.route('/api/templates/<int:template_id>/preview')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def preview_template_by_id(template_id):
    """Preview specific template with sample data."""
    try:
        from app.models.communication import MessageTemplate
        template = MessageTemplate.query.get_or_404(template_id)

        # Use existing preview_template function logic
        sample_data = {
            'user_name': 'John Doe',
            'first_name': 'John',
            'last_name': 'Doe',
            'match_date': '2025-08-15',
            'match_time': '7:00 PM',
            'team_name': 'ECS FC',
            'league_name': 'Premier League',
            'venue': 'Memorial Stadium',
            'opponent': 'Rival FC',
            'season': 'Summer 2025'
        }

        rendered_content = template.content
        for key, value in sample_data.items():
            rendered_content = rendered_content.replace(f'{{{{{key}}}}}', str(value))
            rendered_content = rendered_content.replace(f'{{{key}}}', str(value))

        return jsonify({
            'success': True,
            'rendered_content': rendered_content,
            'template_name': template.name,
            'variables_found': extract_template_variables(template.content)
        })

    except Exception as e:
        logger.error(f"Template preview error: {e}")
        return jsonify({'success': False, 'message': 'Preview failed'}), 500
