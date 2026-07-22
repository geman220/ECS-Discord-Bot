# app/admin_panel/routes/communication/hub.py

"""
Communication Hub Routes

Task-oriented landing page for the Comms section: "what do you want to do?"
cards plus real cross-channel activity stats.
"""

import logging
from datetime import datetime, timedelta

from flask import render_template, flash, redirect, url_for
from flask_login import login_required

from app.admin_panel import admin_panel_bp
from app.core import db
from app.models.communication import ScheduledMessage, Notification
from app.models.notifications import UserFCMToken
from app.decorators import role_required

logger = logging.getLogger(__name__)


@admin_panel_bp.route('/communication')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def communication_hub():
    """Communication hub page."""
    try:
        # Scheduled RSVP-post queue
        scheduled_pending = ScheduledMessage.query.filter_by(status='PENDING').count()
        scheduled_sent = ScheduledMessage.query.filter_by(status='SENT').count()
        scheduled_failed = ScheduledMessage.query.filter_by(status='FAILED').count()

        # Push devices
        push_subscriptions = UserFCMToken.query.filter_by(is_active=True).count()

        # In-app notification volume, last 7 days
        recent_notifications = Notification.query.filter(
            Notification.created_at >= datetime.utcnow() - timedelta(days=7)
        ).count()

        # Email blasts sent in the last 30 days (partially_sent still delivered
        # mail, so it counts). Defensive: table may lag code.
        emails_sent_30d = 0
        try:
            from app.models.email_campaigns import EmailCampaign
            emails_sent_30d = EmailCampaign.query.filter(
                EmailCampaign.status.in_(['sent', 'partially_sent']),
                EmailCampaign.sent_at >= datetime.utcnow() - timedelta(days=30)
            ).count()
        except Exception:
            db.session.rollback()

        # SMS sent in the last 30 days. Defensive for the same reason.
        sms_sent_30d = 0
        try:
            from app.models.communication import SMSLog
            sms_sent_30d = SMSLog.query.filter(
                SMSLog.sent_at >= datetime.utcnow() - timedelta(days=30)
            ).count()
        except Exception:
            db.session.rollback()

        # Push master toggle (the key the mobile app actually reads)
        from app.models.admin_config import AdminConfig
        push_enabled_val = AdminConfig.get_setting('mobile_push_notifications', 'true')
        push_notifications_enabled = str(push_enabled_val).lower() in ('true', '1', 'yes', 'on')

        stats = {
            'scheduled_messages': scheduled_pending,
            'scheduled_messages_sent': scheduled_sent,
            'scheduled_messages_failed': scheduled_failed,
            'push_subscriptions': push_subscriptions,
            'recent_notifications': recent_notifications,
            'emails_sent_30d': emails_sent_30d,
            'sms_sent_30d': sms_sent_30d,
        }

        return render_template('admin_panel/communication_flowbite.html',
                             stats=stats,
                             push_notifications_enabled=push_notifications_enabled)
    except Exception as e:
        logger.exception(f"Error loading communication hub: {e}")
        flash('The Communication Hub failed to load. The error has been logged — check the server log for details.', 'error')
        return redirect(url_for('admin_panel.dashboard'))
