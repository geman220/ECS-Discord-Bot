# app/admin_panel/routes/communication/scheduled.py

"""
Scheduled Messages Management Routes

Routes for scheduled message management including queue, history, and creation.
"""

import logging
from datetime import datetime

from flask import render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user

from app.admin_panel import admin_panel_bp
from app.core import db
from app.models.admin_config import AdminAuditLog
from app.models.communication import ScheduledMessage
from app.decorators import role_required
from app.utils.db_utils import transactional

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

        return render_template('admin_panel/communication/scheduled_messages_flowbite.html',
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
@transactional
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

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='CREATE_SCHEDULED_MESSAGE',
            resource_type='ScheduledMessage',
            resource_id=str(scheduled_message.id),
            new_value=f'Created scheduled message for {scheduled_send_time}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

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

        return render_template('admin_panel/communication/scheduled_messages_queue_flowbite.html',
                             pending_messages=pending_messages,
                             now=datetime.utcnow(),
                             **stats)
    except Exception as e:
        logger.error(f"Error loading scheduled messages queue: {e}")
        flash('Queue unavailable. Check database connectivity.', 'error')
        return redirect(url_for('admin_panel.communication_hub'))


@admin_panel_bp.route('/communication/scheduled-messages/new', methods=['GET', 'POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def schedule_new_message():
    """Create/schedule a new message."""
    if request.method == 'GET':
        # Show form for creating new scheduled message
        return render_template('admin_panel/communication/schedule_new_message_flowbite.html')

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
            return render_template('admin_panel/communication/schedule_new_message_flowbite.html')

        # Parse scheduled time
        try:
            scheduled_datetime = datetime.strptime(scheduled_time, '%Y-%m-%dT%H:%M')
        except ValueError:
            flash('Invalid scheduled time format.', 'error')
            return render_template('admin_panel/communication/schedule_new_message_flowbite.html')

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
        return render_template('admin_panel/communication/schedule_new_message_flowbite.html')


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

        return render_template('admin_panel/communication/scheduled_messages_history_flowbite.html',
                             sent_messages=sent_messages,
                             failed_messages=failed_messages,
                             **stats)
    except Exception as e:
        logger.error(f"Error loading message history: {e}")
        flash('Message history unavailable. Check database connectivity.', 'error')
        return redirect(url_for('admin_panel.communication_hub'))


@admin_panel_bp.route('/communication/scheduled-messages/<int:message_id>/details')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def scheduled_message_detail(message_id):
    """Get scheduled message details for viewing modal."""
    try:
        message = ScheduledMessage.query.get_or_404(message_id)

        # Build details HTML
        html = f'''
        <div class="row">
            <div class="col-md-6">
                <p><strong>Message ID:</strong> {message.id}</p>
                <p><strong>Type:</strong> {message.message_type or 'Standard'}</p>
                <p><strong>Status:</strong> <span class="badge bg-{'success' if message.status == 'SENT' else 'danger' if message.status == 'FAILED' else 'warning'}">{message.status}</span></p>
                <p><strong>Match ID:</strong> {message.match_id or 'N/A'}</p>
            </div>
            <div class="col-md-6">
                <p><strong>Scheduled For:</strong> {message.scheduled_send_time.strftime('%Y-%m-%d %H:%M') if message.scheduled_send_time else 'Not set'}</p>
                <p><strong>Created:</strong> {message.created_at.strftime('%Y-%m-%d %H:%M') if message.created_at else 'N/A'}</p>
                <p><strong>Sent At:</strong> {message.sent_at.strftime('%Y-%m-%d %H:%M') if message.sent_at else 'Not sent'}</p>
                <p><strong>Created By:</strong> {message.creator.username if message.creator else 'System'}</p>
            </div>
        </div>
        '''

        if message.send_error:
            html += f'<div class="alert alert-danger mt-3"><strong>Error:</strong> {message.send_error}</div>'

        if message.message_metadata:
            html += f'<div class="mt-3"><strong>Metadata:</strong><pre class="bg-light p-2 rounded">{message.message_metadata}</pre></div>'

        return jsonify({
            'success': True,
            'html': html,
            'message': {
                'id': message.id,
                'match_id': message.match_id,
                'message_type': message.message_type,
                'scheduled_send_time': message.scheduled_send_time.isoformat() if message.scheduled_send_time else None,
                'status': message.status,
                'task_name': message.task_name
            }
        })

    except Exception as e:
        logger.error(f"Error getting scheduled message details: {e}")
        return jsonify({'success': False, 'message': 'Failed to get message details'}), 500


@admin_panel_bp.route('/communication/scheduled-messages/edit')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def edit_scheduled_message():
    """Edit scheduled message page - redirects with message data for modal editing."""
    try:
        message_id = request.args.get('message_id')
        if not message_id:
            flash('Message ID is required.', 'error')
            return redirect(url_for('admin_panel.scheduled_messages'))

        message = ScheduledMessage.query.get(message_id)
        if not message:
            flash('Scheduled message not found.', 'error')
            return redirect(url_for('admin_panel.scheduled_messages'))

        if message.status != 'PENDING':
            flash('Only pending messages can be edited.', 'warning')
            return redirect(url_for('admin_panel.scheduled_messages'))

        # Redirect back with edit flag - JavaScript will handle the modal
        flash(f'edit_message:{message_id}', 'edit_trigger')
        return redirect(url_for('admin_panel.scheduled_messages'))

    except Exception as e:
        logger.error(f"Error loading scheduled message for edit: {e}")
        flash('Scheduled message data unavailable. Verify database connection and message models.', 'error')
        return redirect(url_for('admin_panel.scheduled_messages'))


@admin_panel_bp.route('/communication/scheduled-messages/<int:message_id>/update', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def update_scheduled_message(message_id):
    """Update an existing scheduled message."""
    try:
        message = ScheduledMessage.query.get_or_404(message_id)

        if message.status != 'PENDING':
            return jsonify({'success': False, 'message': 'Only pending messages can be edited'}), 400

        # Get form data
        scheduled_time = request.form.get('scheduled_time')
        message_type = request.form.get('message_type')

        old_time = message.scheduled_send_time

        # Update fields
        if scheduled_time:
            try:
                message.scheduled_send_time = datetime.strptime(scheduled_time, '%Y-%m-%dT%H:%M')
            except ValueError:
                return jsonify({'success': False, 'message': 'Invalid date format'}), 400

        if message_type:
            message.message_type = message_type

        message.updated_at = datetime.utcnow()

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='update_scheduled_message',
            resource_type='scheduled_message',
            resource_id=str(message_id),
            old_value=str(old_time),
            new_value=str(message.scheduled_send_time),
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        logger.info(f"Scheduled message {message_id} updated by user {current_user.id}")
        return jsonify({
            'success': True,
            'message': 'Scheduled message updated successfully'
        })

    except Exception as e:
        logger.error(f"Error updating scheduled message {message_id}: {e}")
        return jsonify({'success': False, 'message': 'Failed to update message'}), 500


@admin_panel_bp.route('/communication/scheduled-messages/cancel', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def cancel_scheduled_message():
    """Cancel a pending scheduled message."""
    try:
        message_id = request.form.get('message_id')
        if not message_id:
            flash('Message ID is required.', 'error')
            return redirect(url_for('admin_panel.scheduled_messages'))

        message = ScheduledMessage.query.get_or_404(message_id)

        if message.status != 'PENDING':
            flash('Only pending messages can be cancelled.', 'warning')
            return redirect(url_for('admin_panel.scheduled_messages'))

        old_status = message.status
        message.status = 'CANCELLED'
        message.updated_at = datetime.utcnow()

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='cancel_scheduled_message',
            resource_type='scheduled_message',
            resource_id=str(message_id),
            old_value=old_status,
            new_value='CANCELLED',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        logger.info(f"Scheduled message {message_id} cancelled by user {current_user.id}")
        flash('Scheduled message cancelled successfully.', 'success')
        return redirect(url_for('admin_panel.scheduled_messages'))

    except Exception as e:
        logger.error(f"Error cancelling scheduled message: {e}")
        flash('Failed to cancel message. Please try again.', 'error')
        return redirect(url_for('admin_panel.scheduled_messages'))


@admin_panel_bp.route('/communication/scheduled-messages/retry', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def retry_scheduled_message():
    """Retry a failed scheduled message."""
    try:
        message_id = request.form.get('message_id')
        if not message_id:
            flash('Message ID is required.', 'error')
            return redirect(url_for('admin_panel.scheduled_messages'))

        message = ScheduledMessage.query.get_or_404(message_id)

        if message.status != 'FAILED':
            flash('Only failed messages can be retried.', 'warning')
            return redirect(url_for('admin_panel.scheduled_messages'))

        old_status = message.status
        message.status = 'PENDING'
        message.send_error = None
        message.scheduled_send_time = datetime.utcnow()  # Reschedule for now
        message.updated_at = datetime.utcnow()

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='retry_scheduled_message',
            resource_type='scheduled_message',
            resource_id=str(message_id),
            old_value=old_status,
            new_value='PENDING (retry)',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        logger.info(f"Scheduled message {message_id} queued for retry by user {current_user.id}")
        flash('Message queued for retry.', 'success')
        return redirect(url_for('admin_panel.scheduled_messages'))

    except Exception as e:
        logger.error(f"Error retrying scheduled message: {e}")
        flash('Failed to retry message. Please try again.', 'error')
        return redirect(url_for('admin_panel.scheduled_messages'))
