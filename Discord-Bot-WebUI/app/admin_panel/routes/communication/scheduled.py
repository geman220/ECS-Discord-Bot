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


def _pst_form_time_to_utc(value):
    """Parse a 'YYYY-MM-DDTHH:MM' form value entered as PST and return a naive
    UTC datetime (the storage convention for scheduled_send_time)."""
    import pytz
    local_dt = datetime.strptime(value, '%Y-%m-%dT%H:%M')
    pst = pytz.timezone('America/Los_Angeles')
    return pst.localize(local_dt).astimezone(pytz.utc).replace(tzinfo=None)


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
        total_messages = ScheduledMessage.query.count()

        # The template (both Classic and Modern branches) reads `stats` + `messages`;
        # provide them here so the KPI band + table render real data instead of empties.
        pub_league_count = sum(
            1 for m in scheduled_messages
            if not getattr(m, 'message_type', None) or getattr(m, 'message_type', None) == 'standard'
        )
        stats = {
            'total': total_messages,
            'pending': pending_messages,
            'sent': sent_messages,
            'failed': failed_messages,
            'queued': pending_messages,
            'filtered_count': len(scheduled_messages),
            'pub_league': pub_league_count,
            'ecs_fc': len(scheduled_messages) - pub_league_count,
        }

        return render_template('admin_panel/communication/scheduled_messages_flowbite.html',
                             scheduled_messages=scheduled_messages,
                             messages=scheduled_messages,
                             stats=stats,
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
        if not match_id:
            flash('Please select a match.', 'error')
            return redirect(url_for('admin_panel.schedule_new_message'))
        if not scheduled_time:
            flash('Scheduled time is required.', 'error')
            return redirect(url_for('admin_panel.schedule_new_message'))

        # Parse scheduled time. The form collects PST (the labels say so) but
        # scheduled_send_time is stored in UTC — the dispatcher compares it
        # against datetime.utcnow() (tasks_core.py), so convert before storing.
        try:
            scheduled_send_time = _pst_form_time_to_utc(scheduled_time)
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
        db.session.flush()  # assign the id before it goes into the audit log

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
        # Get pending scheduled messages. Manual queue_order (set by the
        # move-up/move-down buttons) takes precedence; rows that have never been
        # manually ordered (queue_order IS NULL) fall back to chronological order.
        pending_messages = ScheduledMessage.query.filter_by(status='PENDING').order_by(
            ScheduledMessage.queue_order.asc().nullslast(),
            ScheduledMessage.scheduled_send_time.asc(),
            ScheduledMessage.id.asc()
        ).all()

        stats = {
            'pending_count': len(pending_messages),
            'next_message': pending_messages[0] if pending_messages else None
        }

        return render_template('admin_panel/communication/scheduled_messages_queue_flowbite.html',
                             pending_messages=pending_messages,
                             # The template calls now() — pass the callable, not an instance.
                             now=datetime.utcnow,
                             **stats)
    except Exception as e:
        logger.exception(f"Error loading scheduled messages queue: {e}")
        flash('Queue unavailable. Check database connectivity.', 'error')
        return redirect(url_for('admin_panel.communication_hub'))


@admin_panel_bp.route('/communication/scheduled-messages/queue/reorder', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def reorder_message_queue():
    """Move a pending scheduled message up or down in the queue.

    The pending set is ordered by queue_order (NULLS last) then
    scheduled_send_time. To make a move durable we first backfill sequential
    queue_order values across the current pending ordering, then swap the
    target row's queue_order with its neighbor in the requested direction.
    """
    try:
        data = request.get_json(silent=True) or {}
        message_id = data.get('message_id', request.form.get('message_id'))
        direction = data.get('direction', request.form.get('direction'))

        if not message_id or direction not in ('up', 'down'):
            return jsonify({'success': False, 'message': 'message_id and direction (up/down) are required.'}), 400
        message_id = int(message_id)

        # Load the full pending set in current display order.
        pending = ScheduledMessage.query.filter_by(status='PENDING').order_by(
            ScheduledMessage.queue_order.asc().nullslast(),
            ScheduledMessage.scheduled_send_time.asc(),
            ScheduledMessage.id.asc()
        ).all()

        # Backfill sequential queue_order so positions are well-defined.
        for position, msg in enumerate(pending):
            msg.queue_order = position

        index = next((i for i, m in enumerate(pending) if m.id == message_id), None)
        if index is None:
            return jsonify({'success': False, 'message': 'Message is not in the pending queue.'}), 404

        swap_index = index - 1 if direction == 'up' else index + 1
        if swap_index < 0 or swap_index >= len(pending):
            # Already at the boundary — no-op, but report it honestly.
            return jsonify({'success': True, 'message': 'Message is already at the edge of the queue.', 'moved': False})

        a, b = pending[index], pending[swap_index]
        a.queue_order, b.queue_order = b.queue_order, a.queue_order
        a.updated_at = datetime.utcnow()
        b.updated_at = datetime.utcnow()

        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='reorder_message_queue',
            resource_type='scheduled_message',
            resource_id=str(message_id),
            new_value=f'Moved {direction} (position {index} -> {swap_index})',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        return jsonify({
            'success': True,
            'message': f'Message moved {direction}.',
            'moved': True,
            'message_id': message_id,
            'new_position': swap_index
        })
    except Exception as e:
        logger.error(f"Error reordering message queue: {e}")
        return jsonify({'success': False, 'message': 'Failed to reorder queue.'}), 500


@admin_panel_bp.route('/communication/scheduled-messages/new')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def schedule_new_message():
    """Form for scheduling a match RSVP post.

    The form POSTs to create_scheduled_message. The old POST branch here was
    dead code: it passed columns ScheduledMessage doesn't have (title/content/
    recipient_type) so it could never succeed, and the form never targeted it.
    """
    from app.models import Match

    # Upcoming matches that don't already have a scheduled message.
    scheduled_match_ids = db.session.query(ScheduledMessage.match_id).filter(
        ScheduledMessage.match_id.isnot(None),
        ScheduledMessage.status.in_(['PENDING', 'QUEUED'])
    ).subquery()
    matches = Match.query.filter(
        Match.date >= datetime.utcnow().date(),
        ~Match.id.in_(scheduled_match_ids)
    ).order_by(Match.date, Match.time).limit(100).all()

    recent_messages = ScheduledMessage.query.filter(
        ScheduledMessage.match_id.isnot(None)
    ).order_by(ScheduledMessage.created_at.desc()).limit(5).all()

    # The template shows send times in PST; stamp the converted value the same
    # way admin/scheduling_routes.py does.
    import pytz
    pst = pytz.timezone('America/Los_Angeles')
    utc = pytz.utc
    for message in recent_messages:
        if message.scheduled_send_time:
            message.scheduled_send_time_pst = utc.localize(message.scheduled_send_time).astimezone(pst)

    return render_template('admin_panel/communication/schedule_new_message_flowbite.html',
                           matches=matches,
                           recent_messages=recent_messages)


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

        # Update fields (form time is PST; the column is UTC)
        if scheduled_time:
            try:
                message.scheduled_send_time = _pst_form_time_to_utc(scheduled_time)
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


@admin_panel_bp.route('/communication/scheduled-messages/queue/process', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def process_message_queue():
    """Manually trigger processing of all due pending scheduled messages."""
    try:
        from app.tasks.tasks_core import send_scheduled_messages
        task = send_scheduled_messages.delay()

        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='process_message_queue',
            resource_type='scheduled_message',
            resource_id='queue',
            new_value='Manually triggered scheduled message processing',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        return jsonify({
            'success': True,
            'message': 'Queue processing started. Due messages are being sent.',
            'task_id': task.id
        })
    except Exception as e:
        logger.error(f"Error processing message queue: {e}")
        return jsonify({'success': False, 'message': 'Failed to start queue processing.'}), 500


@admin_panel_bp.route('/communication/scheduled-messages/<int:message_id>/send-now', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def send_scheduled_message_now(message_id):
    """Immediately queue a pending scheduled message for delivery."""
    try:
        message = ScheduledMessage.query.get_or_404(message_id)

        if message.status not in ('PENDING', 'QUEUED'):
            return jsonify({'success': False, 'message': 'Only pending messages can be sent now.'}), 400

        from app.tasks.tasks_core import send_availability_message_task
        message.scheduled_send_time = datetime.utcnow()
        message.status = 'QUEUED'
        message.updated_at = datetime.utcnow()
        task = send_availability_message_task.delay(message.id)

        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='send_scheduled_message_now',
            resource_type='scheduled_message',
            resource_id=str(message_id),
            new_value='Force-sent scheduled message',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        return jsonify({'success': True, 'message': 'Message queued for immediate delivery.', 'task_id': task.id})
    except Exception as e:
        logger.error(f"Error sending scheduled message {message_id} now: {e}")
        return jsonify({'success': False, 'message': 'Failed to send message.'}), 500


@admin_panel_bp.route('/communication/scheduled-messages/queue/bulk', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def bulk_queue_action():
    """Bulk cancel/delete/send selected pending scheduled messages."""
    try:
        data = request.get_json() or {}
        action = data.get('action')
        ids = data.get('ids') or []
        ids = [int(i) for i in ids if str(i).isdigit()]

        if not action or not ids:
            return jsonify({'success': False, 'message': 'Action and message IDs are required.'}), 400

        messages = ScheduledMessage.query.filter(ScheduledMessage.id.in_(ids)).all()
        affected = 0

        if action == 'cancel':
            for m in messages:
                if m.status in ('PENDING', 'QUEUED'):
                    m.status = 'CANCELLED'
                    m.updated_at = datetime.utcnow()
                    affected += 1
        elif action == 'delete':
            for m in messages:
                db.session.delete(m)
                affected += 1
        elif action == 'send':
            from app.tasks.tasks_core import send_availability_message_task
            for m in messages:
                if m.status in ('PENDING', 'QUEUED'):
                    m.scheduled_send_time = datetime.utcnow()
                    m.status = 'QUEUED'
                    m.updated_at = datetime.utcnow()
                    send_availability_message_task.delay(m.id)
                    affected += 1
        else:
            return jsonify({'success': False, 'message': 'Unknown bulk action.'}), 400

        AdminAuditLog.log_action(
            user_id=current_user.id,
            action=f'bulk_queue_{action}',
            resource_type='scheduled_message',
            resource_id=','.join(str(i) for i in ids),
            new_value=f'Bulk {action} on {affected} message(s)',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        return jsonify({'success': True, 'message': f'{affected} message(s) {action}ed.', 'affected': affected})
    except Exception as e:
        logger.error(f"Error performing bulk queue action: {e}")
        return jsonify({'success': False, 'message': 'Failed to perform bulk action.'}), 500


@admin_panel_bp.route('/communication/scheduled-messages/bulk-schedule', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def bulk_schedule_messages():
    """Bulk-schedule RSVP messages for upcoming matches without one.

    scope: 'sunday' (this coming Sunday), 'week' (next 7 days), 'season' (next 90 days).
    Reuses the same send-time logic as the schedule_season_availability task.
    """
    try:
        from datetime import timedelta
        from sqlalchemy.orm import joinedload
        from app.models import Match

        data = request.get_json() or {}
        scope = data.get('scope', 'week')

        start_date = datetime.utcnow().date()
        if scope == 'season':
            end_date = start_date + timedelta(days=90)
        elif scope == 'sunday':
            # The next Sunday (weekday 6) inclusive of today if today is Sunday.
            days_ahead = (6 - start_date.weekday()) % 7
            end_date = start_date + timedelta(days=days_ahead)
            start_date = end_date  # only that Sunday
        else:  # 'week'
            end_date = start_date + timedelta(days=7)

        matches = Match.query.options(
            joinedload(Match.scheduled_messages)
        ).filter(Match.date.between(start_date, end_date)).all()

        scheduled_count = 0
        for match in matches:
            if any(msg for msg in match.scheduled_messages):
                continue
            match_date = match.date
            if match_date.weekday() == 6:  # Sunday match → send the prior Monday
                send_date = match_date - timedelta(days=6)
            else:
                days_since_monday = match_date.weekday()
                send_date = match_date - timedelta(days=days_since_monday if days_since_monday > 0 else 7)
            send_time = datetime.combine(send_date, datetime.min.time()) + timedelta(hours=16)

            db.session.add(ScheduledMessage(
                match_id=match.id,
                scheduled_send_time=send_time,
                status='PENDING',
                created_by=current_user.id,
                message_metadata={'created_via': 'bulk_schedule', 'scope': scope}
            ))
            scheduled_count += 1

        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='bulk_schedule_messages',
            resource_type='scheduled_message',
            resource_id=scope,
            new_value=f'Bulk-scheduled {scheduled_count} message(s) for scope {scope}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        return jsonify({
            'success': True,
            'message': f'Scheduled {scheduled_count} message(s) for {len(matches)} match(es).',
            'scheduled_count': scheduled_count
        })
    except Exception as e:
        logger.error(f"Error bulk-scheduling messages: {e}")
        return jsonify({'success': False, 'message': 'Failed to bulk-schedule messages.'}), 500


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


@admin_panel_bp.route('/communication/scheduled-messages/cleanup', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def cleanup_scheduled_message_history():
    """Delete completed (SENT/FAILED) scheduled-message history older than N days.

    Real, bounded cleanup — only touches terminal-state rows past the cutoff so it
    never removes pending/queued messages. Returns the real deleted count (JSON)."""
    from datetime import timedelta
    try:
        days = request.get_json(silent=True) or {}
        days = int(days.get('days', request.form.get('days', 90)))
    except (TypeError, ValueError):
        days = 90
    days = max(1, min(days, 3650))
    cutoff = datetime.utcnow() - timedelta(days=days)
    try:
        deleted = ScheduledMessage.query.filter(
            ScheduledMessage.status.in_(['SENT', 'FAILED']),
            ScheduledMessage.created_at < cutoff
        ).delete(synchronize_session=False)
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='CLEANUP_SCHEDULED_MESSAGE_HISTORY',
            resource_type='ScheduledMessage',
            resource_id='bulk',
            new_value=f'Deleted {deleted} SENT/FAILED messages older than {days} days',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        logger.info(f"Cleaned up {deleted} scheduled messages older than {days}d by user {current_user.id}")
        return jsonify({'success': True, 'deleted': deleted, 'days': days})
    except Exception as e:
        logger.error(f"Error cleaning up scheduled message history: {e}")
        return jsonify({'success': False, 'message': 'Cleanup failed'}), 500
