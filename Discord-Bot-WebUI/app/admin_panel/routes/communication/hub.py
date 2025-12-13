# app/admin_panel/routes/communication/hub.py

"""
Communication Hub Routes

Main communication dashboard with statistics.
"""

import logging
from datetime import datetime, timedelta

from flask import render_template, flash, redirect, url_for
from flask_login import login_required

from app.admin_panel import admin_panel_bp
from app.models import MessageCategory, MessageTemplate
from app.models.communication import ScheduledMessage, DeviceToken, Notification
from app.decorators import role_required

logger = logging.getLogger(__name__)


@admin_panel_bp.route('/communication')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def communication_hub():
    """Communication hub page."""
    try:
        # Get communication statistics
        total_templates = MessageTemplate.query.count()
        total_categories = MessageCategory.query.count()

        # Get real scheduled message statistics
        scheduled_messages_count = ScheduledMessage.query.filter_by(status='PENDING').count()
        scheduled_messages_sent = ScheduledMessage.query.filter_by(status='SENT').count()
        scheduled_messages_failed = ScheduledMessage.query.filter_by(status='FAILED').count()

        # Get notification statistics from device tokens (approximation of push notification capability)
        push_subscriptions = DeviceToken.query.filter_by(is_active=True).count()

        # Get recent notification activity
        recent_notifications = Notification.query.filter(
            Notification.created_at >= datetime.utcnow() - timedelta(days=7)
        ).count()

        stats = {
            'total_templates': total_templates,
            'total_categories': total_categories,
            'scheduled_messages': scheduled_messages_count,
            'scheduled_messages_sent': scheduled_messages_sent,
            'scheduled_messages_failed': scheduled_messages_failed,
            'push_subscriptions': push_subscriptions,
            'recent_notifications': recent_notifications,
            'active_channels': 3  # Discord, Email, Push
        }

        return render_template('admin_panel/communication.html', stats=stats)
    except Exception as e:
        logger.error(f"Error loading communication hub: {e}")
        flash('Communication hub unavailable. Check database connectivity and message models.', 'error')
        return redirect(url_for('admin_panel.dashboard'))
