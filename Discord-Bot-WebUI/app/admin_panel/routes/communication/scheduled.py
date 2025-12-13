# app/admin_panel/routes/communication/scheduled.py

"""
Scheduled Messages Management Routes

Routes for scheduled message management including queue, history, and creation.
"""

import logging
from datetime import datetime

from flask import render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user

from app.admin_panel import admin_panel_bp
from app.core import db
from app.models.admin_config import AdminAuditLog
from app.models.communication import ScheduledMessage
from app.decorators import role_required

logger = logging.getLogger(__name__)


@admin_panel_bp.route('/communication/scheduled-messages')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def scheduled_messages():
    """Scheduled messages management page."""
    try:
        # Get real scheduled message data
        scheduled_messages = ScheduledMessage.query.order_by(
            ScheduledMessage.scheduled_send_time.desc()
        ).limit(50).all()

        pending_messages = ScheduledMessage.query.filter_by(status='PENDING').count()
        sent_messages = ScheduledMessage.query.filter_by(status='SENT').count()
        failed_messages = ScheduledMessage.query.filter_by(status='FAILED').count()

        return render_template('admin_panel/communication/scheduled_messages.html',
                             scheduled_messages=scheduled_messages,
                             pending_messages=pending_messages,
                             sent_messages=sent_messages,
                             failed_messages=failed_messages,
                             now=datetime.utcnow())
    except Exception as e:
        logger.error(f"Error loading scheduled messages: {e}")
        flash('Scheduled messages unavailable. Verify database connection and message data.', 'error')
        return redirect(url_for('admin_panel.communication_hub'))


@admin_panel_bp.route('/communication/scheduled-messages/create', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def create_scheduled_message():
    """Create a new scheduled message."""
    try:
        # Get form data
        match_id = request.form.get('match_id', type=int)
        message_type = request.form.get('message_type', 'standard')
        scheduled_time = request.form.get('scheduled_time')

        # Validate inputs
        if not scheduled_time:
            flash('Scheduled time is required.', 'error')
            return redirect(url_for('admin_panel.scheduled_messages'))

        # Parse scheduled time
        try:
            scheduled_send_time = datetime.strptime(scheduled_time, '%Y-%m-%dT%H:%M')
        except ValueError:
            flash('Invalid date format. Please use the date picker.', 'error')
            return redirect(url_for('admin_panel.scheduled_messages'))

        # Create scheduled message
        scheduled_message = ScheduledMessage(
            match_id=match_id,
            message_type=message_type,
            scheduled_send_time=scheduled_send_time,
            status='PENDING',
            created_by=current_user.id,
            message_metadata={'created_via': 'admin_panel'}
        )

        db.session.add(scheduled_message)
        db.session.commit()

        # Log the action
        audit_log = AdminAuditLog(
            admin_id=current_user.id,
            action='CREATE_SCHEDULED_MESSAGE',
            target_type='ScheduledMessage',
            target_id=scheduled_message.id,
            details=f'Created scheduled message for {scheduled_send_time}'
        )
        db.session.add(audit_log)
        db.session.commit()

        flash('Scheduled message created successfully!', 'success')
        return redirect(url_for('admin_panel.scheduled_messages'))
    except Exception as e:
        logger.error(f"Error creating scheduled message: {e}")
        flash('Scheduled message creation failed. Check database connectivity and input validation.', 'error')
        return redirect(url_for('admin_panel.scheduled_messages'))


@admin_panel_bp.route('/communication/scheduled-messages/queue')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def scheduled_messages_queue():
    """View scheduled messages queue (pending messages)."""
    try:
        # Get pending scheduled messages
        pending_messages = ScheduledMessage.query.filter_by(status='PENDING').order_by(
            ScheduledMessage.scheduled_send_time.asc()
        ).all()

        stats = {
            'pending_count': len(pending_messages),
            'next_message': pending_messages[0] if pending_messages else None
        }

        return render_template('admin_panel/communication/scheduled_messages_queue.html',
                             pending_messages=pending_messages,
                             **stats)
    except Exception as e:
        logger.error(f"Error loading scheduled messages queue: {e}")
        flash('Queue unavailable. Check database connectivity.', 'error')
        return redirect(url_for('admin_panel.communication_hub'))


@admin_panel_bp.route('/communication/scheduled-messages/new', methods=['GET', 'POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def schedule_new_message():
    """Create/schedule a new message."""
    if request.method == 'GET':
        # Show form for creating new scheduled message
        return render_template('admin_panel/communication/schedule_new_message.html')

    try:
        # Handle form submission
        message_type = request.form.get('message_type', 'discord')  # discord, sms, push, discord_dm
        recipient_type = request.form.get('recipient_type', 'all')
        title = request.form.get('title')
        content = request.form.get('content')
        scheduled_time = request.form.get('scheduled_time')

        # Additional fields for different message types
        discord_channel = request.form.get('discord_channel')
        sms_template = request.form.get('sms_template')
        push_priority = request.form.get('push_priority', 'normal')
        dm_individual = request.form.get('dm_individual') == 'on'

        # Validate inputs
        if not title or not content or not scheduled_time:
            flash('Title, content, and scheduled time are required.', 'error')
            return render_template('admin_panel/communication/schedule_new_message.html')

        # Parse scheduled time
        try:
            scheduled_datetime = datetime.strptime(scheduled_time, '%Y-%m-%dT%H:%M')
        except ValueError:
            flash('Invalid scheduled time format.', 'error')
            return render_template('admin_panel/communication/schedule_new_message.html')

        # Create message metadata based on type
        message_metadata = {}
        if message_type == 'discord' and discord_channel:
            message_metadata['discord_channel'] = discord_channel
        elif message_type == 'sms':
            message_metadata['sms_template'] = sms_template or 'default'
        elif message_type == 'push':
            message_metadata['priority'] = push_priority
        elif message_type == 'discord_dm':
            message_metadata['individual_dm'] = dm_individual

        # Create scheduled message
        scheduled_message = ScheduledMessage(
            message_type=message_type,
            recipient_type=recipient_type,
            title=title,
            content=content,
            scheduled_send_time=scheduled_datetime,
            status='PENDING',
            created_by=current_user.id,
            metadata=str(message_metadata) if message_metadata else None
        )

        db.session.add(scheduled_message)
        db.session.commit()

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='schedule_message',
            resource_type='scheduled_messages',
            resource_id=str(scheduled_message.id),
            new_value=f'Scheduled {message_type} message: {title}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        flash(f'Message "{title}" scheduled for {scheduled_datetime.strftime("%Y-%m-%d %H:%M")}!', 'success')
        return redirect(url_for('admin_panel.scheduled_messages_queue'))

    except Exception as e:
        logger.error(f"Error scheduling message: {e}")
        flash('Failed to schedule message. Check database connectivity.', 'error')
        return render_template('admin_panel/communication/schedule_new_message.html')


@admin_panel_bp.route('/communication/scheduled-messages/history')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def scheduled_messages_history():
    """View message history (sent/failed messages)."""
    try:
        # Get sent and failed messages
        sent_messages = ScheduledMessage.query.filter_by(status='SENT').order_by(
            ScheduledMessage.sent_at.desc()
        ).limit(50).all()

        failed_messages = ScheduledMessage.query.filter_by(status='FAILED').order_by(
            ScheduledMessage.updated_at.desc()
        ).limit(20).all()

        stats = {
            'total_sent': ScheduledMessage.query.filter_by(status='SENT').count(),
            'total_failed': ScheduledMessage.query.filter_by(status='FAILED').count(),
            'success_rate': 0
        }

        # Calculate success rate
        total_processed = stats['total_sent'] + stats['total_failed']
        if total_processed > 0:
            stats['success_rate'] = round((stats['total_sent'] / total_processed) * 100, 1)

        return render_template('admin_panel/communication/scheduled_messages_history.html',
                             sent_messages=sent_messages,
                             failed_messages=failed_messages,
                             **stats)
    except Exception as e:
        logger.error(f"Error loading message history: {e}")
        flash('Message history unavailable. Check database connectivity.', 'error')
        return redirect(url_for('admin_panel.communication_hub'))


@admin_panel_bp.route('/communication/scheduled-messages/edit')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def edit_scheduled_message():
    """Edit scheduled message page."""
    try:
        message_id = request.args.get('message_id')
        if not message_id:
            flash('Message ID is required.', 'error')
            return redirect(url_for('admin_panel.scheduled_messages'))

        # Get the scheduled message
        message = ScheduledMessage.query.get(message_id)
        if not message:
            flash('Scheduled message not found.', 'error')
            return redirect(url_for('admin_panel.scheduled_messages'))

        # For now, redirect to the details page since we don't have an edit form
        # In a full implementation, this would render an edit form
        flash(f'Edit functionality for message {message_id} coming soon!', 'info')
        return redirect(url_for('admin_panel.scheduled_messages'))

    except Exception as e:
        logger.error(f"Error loading scheduled message for edit: {e}")
        flash('Scheduled message data unavailable. Verify database connection and message models.', 'error')
        return redirect(url_for('admin_panel.scheduled_messages'))
