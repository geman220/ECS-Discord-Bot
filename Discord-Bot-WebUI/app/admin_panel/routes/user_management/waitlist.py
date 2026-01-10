# app/admin_panel/routes/user_management/waitlist.py

"""
User Waitlist Routes

Routes for waitlist management:
- Waitlist management page
- Remove from waitlist
- Contact waitlist users
- Process waitlist users
"""

import logging
from datetime import datetime, timedelta

from flask import render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from app.admin_panel import admin_panel_bp
from app.core import db
from app.models.admin_config import AdminAuditLog
from app.models.core import User, Role
from app.decorators import role_required
from app.utils.db_utils import transactional
from app.tasks.tasks_discord import assign_roles_to_player_task, remove_player_roles_task
from app.utils.user_helpers import safe_current_user
from app.admin_panel.routes.user_management.helpers import (
    calculate_avg_wait_time,
    calculate_processing_rate,
    calculate_conversion_rate,
)

logger = logging.getLogger(__name__)


@admin_panel_bp.route('/users/waitlist')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def user_waitlist():
    """
    Display the user waitlist management interface.
    Shows users on the waitlist.
    """
    try:
        current_user_safe = safe_current_user

        # Get all users with pl-waitlist role
        waitlist_users = db.session.query(User).options(
            joinedload(User.player),
            joinedload(User.roles)
        ).join(User.roles).filter(
            Role.name == 'pl-waitlist'
        ).order_by(User.created_at.desc()).all()

        # Get audit log entries for waitlist actions
        audit_logs = []
        try:
            audit_logs = db.session.query(AdminAuditLog).options(
                joinedload(AdminAuditLog.user)
            ).filter(
                AdminAuditLog.resource_type == 'user_waitlist'
            ).order_by(AdminAuditLog.timestamp.desc()).limit(20).all()
        except Exception as e:
            logger.error(f"Error loading audit logs: {str(e)}")
            audit_logs = []

        # Get recent approval actions (users processed from waitlist or regular approvals)
        recent_actions = []
        try:
            recent_actions = db.session.query(User).options(
                joinedload(User.player),
                joinedload(User.roles)
            ).filter(
                User.approval_status.in_(['approved', 'denied']),
                User.approved_at.isnot(None)
            ).order_by(User.approved_at.desc()).limit(20).all()

            # Add approved_by_user information
            for user in recent_actions:
                if user.approved_by:
                    user.approved_by_user = db.session.query(User).filter_by(id=user.approved_by).first()
        except Exception as e:
            logger.error(f"Error loading recent actions: {str(e)}")
            recent_actions = []

        # Count statistics
        stats = {
            'waitlist_count': len(waitlist_users),
            'total_registered': db.session.query(func.count(User.id)).scalar(),
            'total_approved': db.session.query(func.count(User.id)).filter(User.approval_status == 'approved').scalar(),
            'processed_count': db.session.query(func.count(User.id)).filter(
                User.approval_status == 'approved',
                User.approved_at >= datetime.utcnow() - timedelta(days=30)
            ).scalar(),
            'avg_wait_time': calculate_avg_wait_time(),
            'processing_rate': calculate_processing_rate(),
            'conversion_rate': calculate_conversion_rate()
        }

        return render_template(
            'admin_panel/users/user_waitlist_flowbite.html',
            waitlist_users=waitlist_users,
            recent_actions=recent_actions,
            audit_logs=audit_logs,
            now=datetime.utcnow(),
            stats=stats
        )
    except Exception as e:
        logger.error(f"Error loading user waitlist: {e}")
        flash('User waitlist unavailable. Check database connectivity and waitlist data.', 'error')
        return redirect(url_for('admin_panel.user_management'))


@admin_panel_bp.route('/users/waitlist/remove/<int:user_id>', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def remove_from_waitlist(user_id: int):
    """
    Remove a user from the waitlist.
    """
    try:
        current_user_safe = safe_current_user

        # Get the user
        user = db.session.query(User).options(
            joinedload(User.player),
            joinedload(User.roles)
        ).filter_by(id=user_id).first()

        if not user:
            return jsonify({'success': False, 'message': 'User not found'}), 404

        # Get the pl-waitlist role
        waitlist_role = db.session.query(Role).filter_by(name='pl-waitlist').first()
        if not waitlist_role:
            return jsonify({'success': False, 'message': 'Waitlist role not found'}), 404

        # Check if user is on waitlist
        if waitlist_role not in user.roles:
            return jsonify({'success': False, 'message': 'User is not on waitlist'}), 400

        # Get removal reason from request
        reason = request.json.get('reason', 'No reason provided')

        # Remove the waitlist role
        user.roles.remove(waitlist_role)

        # Clear waitlist joined timestamp since they're no longer on waitlist
        if hasattr(user, 'waitlist_joined_at'):
            user.waitlist_joined_at = None

        # Update user record
        user.updated_at = datetime.utcnow()

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user_safe.id,
            action='remove_from_waitlist',
            resource_type='user_waitlist',
            resource_id=str(user_id),
            old_value='on_waitlist',
            new_value=f'removed: {reason}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        logger.info(f"User {user.id} ({user.username}) removed from waitlist by {current_user_safe.id} ({current_user_safe.username}). Reason: {reason}")

        # Commit the changes
        db.session.flush()

        # Sync Discord roles if user has Discord integration
        if user.player and user.player.discord_id:
            try:
                # Remove Discord roles (this will remove the waitlist Discord role)
                remove_player_roles_task.delay(player_id=user.player.id)
                logger.info(f"Queued Discord role removal for user {user.id}")
            except Exception as e:
                logger.error(f"Failed to queue Discord role removal for user {user.id}: {str(e)}")

        return jsonify({
            'success': True,
            'message': f'User {user.username} removed from waitlist successfully',
            'user_id': user.id
        })

    except Exception as e:
        logger.error(f"Error removing user {user_id} from waitlist: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': 'Failed to remove user from waitlist'}), 500


@admin_panel_bp.route('/users/waitlist/contact/<int:user_id>', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def contact_waitlist_user(user_id: int):
    """
    Contact a user on the waitlist via email, SMS, or Discord DM.
    """
    try:
        current_user_safe = safe_current_user

        # Get the user
        user = db.session.query(User).options(
            joinedload(User.player),
            joinedload(User.roles)
        ).filter_by(id=user_id).first()

        if not user:
            return jsonify({'success': False, 'message': 'User not found'}), 404

        # Get contact message from request
        message = request.json.get('message', '')
        contact_method = request.json.get('contact_method', 'email')
        subject = request.json.get('subject', 'ECS Pub League - Waitlist Update')

        if not message:
            return jsonify({'success': False, 'message': 'Message content is required'}), 400

        # Send the message based on contact method
        send_result = _send_waitlist_contact(user, contact_method, message, subject)

        if not send_result['success']:
            return jsonify(send_result), 400

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user_safe.id,
            action='contact_waitlist_user',
            resource_type='user_waitlist',
            resource_id=str(user_id),
            new_value=f'contacted via {contact_method}: {message[:50]}...',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        logger.info(f"Contact sent to waitlist user {user.id} ({user.username}) by {current_user_safe.id} ({current_user_safe.username}). Method: {contact_method}")

        return jsonify({
            'success': True,
            'message': send_result['message'],
            'user_id': user.id
        })

    except Exception as e:
        logger.error(f"Error contacting waitlist user {user_id}: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': 'Failed to contact user'}), 500


@admin_panel_bp.route('/users/waitlist/priority/<int:user_id>', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def update_waitlist_priority(user_id: int):
    """
    Update the priority of a user on the waitlist.

    Expected JSON body:
    {
        "priority": "high" | "medium" | "normal" | "auto"
    }
    """
    try:
        current_user_safe = safe_current_user

        # Get the user
        user = db.session.query(User).filter_by(id=user_id).first()

        if not user:
            return jsonify({'success': False, 'message': 'User not found'}), 404

        # Get priority from request
        priority = request.json.get('priority', 'auto')

        # Validate priority value
        valid_priorities = ['high', 'medium', 'normal', 'auto']
        if priority not in valid_priorities:
            return jsonify({
                'success': False,
                'message': f'Invalid priority. Must be one of: {", ".join(valid_priorities)}'
            }), 400

        # Set priority (None means auto-calculated)
        old_priority = user.waitlist_priority
        user.waitlist_priority = None if priority == 'auto' else priority
        user.updated_at = datetime.utcnow()

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user_safe.id,
            action='update_waitlist_priority',
            resource_type='user_waitlist',
            resource_id=str(user_id),
            old_value=old_priority or 'auto',
            new_value=priority,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        logger.info(f"Waitlist priority updated for user {user.id} ({user.username}) from {old_priority or 'auto'} to {priority} by {current_user_safe.id} ({current_user_safe.username})")

        return jsonify({
            'success': True,
            'message': f'Priority updated to {priority}',
            'user_id': user.id,
            'priority': priority
        })

    except Exception as e:
        logger.error(f"Error updating waitlist priority for user {user_id}: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': 'Failed to update priority'}), 500


def _send_waitlist_contact(user, contact_method: str, message: str, subject: str) -> dict:
    """
    Helper function to send contact message via the specified method.

    Args:
        user: User object to contact
        contact_method: One of 'email', 'sms', or 'discord'
        message: The message content
        subject: Email subject (only used for email method)

    Returns:
        dict with 'success' and 'message' keys
    """
    if contact_method == 'email':
        return _send_waitlist_email(user, subject, message)
    elif contact_method == 'sms':
        return _send_waitlist_sms(user, message)
    elif contact_method == 'discord':
        return _send_waitlist_discord_dm(user, message)
    else:
        return {'success': False, 'message': f'Unknown contact method: {contact_method}'}


def _send_waitlist_email(user, subject: str, message: str) -> dict:
    """Send email to waitlist user."""
    if not user.email:
        return {'success': False, 'message': 'User has no email address'}

    try:
        from app.email import send_email

        # Wrap message in basic HTML
        html_body = f"""
        <html>
        <body>
            <p>{message.replace(chr(10), '<br>')}</p>
            <hr>
            <p><small>This message was sent regarding your position on the ECS Pub League waitlist.</small></p>
        </body>
        </html>
        """

        result = send_email(user.email, subject, html_body)

        if result:
            logger.info(f"Email sent to waitlist user {user.id} at {user.email}")
            return {'success': True, 'message': f'Email sent to {user.email}'}
        else:
            logger.error(f"Failed to send email to waitlist user {user.id}")
            return {'success': False, 'message': 'Failed to send email'}

    except Exception as e:
        logger.error(f"Error sending email to waitlist user {user.id}: {e}")
        return {'success': False, 'message': f'Email error: {str(e)}'}


def _send_waitlist_sms(user, message: str) -> dict:
    """Send SMS to waitlist user."""
    if not user.player or not user.player.phone:
        return {'success': False, 'message': 'User has no phone number'}

    if not user.sms_notifications:
        return {'success': False, 'message': 'User has SMS notifications disabled'}

    try:
        from app.sms_helpers import send_sms

        success, result = send_sms(user.player.phone, message, user_id=user.id)

        if success:
            logger.info(f"SMS sent to waitlist user {user.id} at {user.player.phone}")
            return {'success': True, 'message': f'SMS sent to {user.player.phone}'}
        else:
            logger.error(f"Failed to send SMS to waitlist user {user.id}: {result}")
            return {'success': False, 'message': f'Failed to send SMS: {result}'}

    except ImportError:
        return {'success': False, 'message': 'SMS system not configured'}
    except Exception as e:
        logger.error(f"Error sending SMS to waitlist user {user.id}: {e}")
        return {'success': False, 'message': f'SMS error: {str(e)}'}


def _send_waitlist_discord_dm(user, message: str) -> dict:
    """Send Discord DM to waitlist user."""
    if not user.player or not user.player.discord_id:
        return {'success': False, 'message': 'User has no Discord ID'}

    if not user.discord_notifications:
        return {'success': False, 'message': 'User has Discord notifications disabled'}

    try:
        import requests as http_requests
        from flask import current_app

        payload = {
            "message": message,
            "discord_id": user.player.discord_id
        }

        bot_api_url = current_app.config.get('BOT_API_URL', 'http://localhost:5001') + '/send_discord_dm'

        response = http_requests.post(bot_api_url, json=payload, timeout=10)

        if response.status_code == 200:
            logger.info(f"Discord DM sent to waitlist user {user.id}")
            return {'success': True, 'message': 'Discord DM sent successfully'}
        else:
            logger.error(f"Failed to send Discord DM to waitlist user {user.id}: {response.text}")
            return {'success': False, 'message': 'Failed to send Discord DM'}

    except Exception as e:
        logger.error(f"Error sending Discord DM to waitlist user {user.id}: {e}")
        return {'success': False, 'message': f'Discord DM error: {str(e)}'}


@admin_panel_bp.route('/users/waitlist/user/<int:user_id>')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def get_waitlist_user_details(user_id: int):
    """
    Get detailed information about a waitlist user for display in modal.
    """
    try:
        # Get the user with all necessary relationships
        user = db.session.query(User).options(
            joinedload(User.player),
            joinedload(User.roles)
        ).filter_by(id=user_id).first()

        if not user:
            return jsonify({'success': False, 'message': 'User not found'}), 404

        # Build user details dictionary
        user_details = {
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'created_at': user.created_at.strftime('%Y-%m-%d %H:%M:%S') if user.created_at else None,
            'approval_status': user.approval_status,
            'preferred_league': getattr(user, 'preferred_league', None),
            'roles': [role.name for role in user.roles],
            'player': {}
        }

        # Add player information if available
        if user.player:
            user_details['player'] = {
                'id': user.player.id,
                'name': user.player.name,
                'discord_id': user.player.discord_id,
                'phone': user.player.phone,
                'pronouns': user.player.pronouns,
                'jersey_size': user.player.jersey_size,
                'jersey_number': user.player.jersey_number,
                'profile_picture_url': user.player.profile_picture_url,
                'additional_info': user.player.additional_info,
                'player_notes': user.player.player_notes,
                'is_sub': user.player.is_sub,
                'interested_in_sub': user.player.interested_in_sub,
                'favorite_position': user.player.favorite_position,
                'other_positions': user.player.other_positions,
                'positions_not_to_play': user.player.positions_not_to_play,
                'frequency_play_goal': user.player.frequency_play_goal,
                'expected_weeks_available': user.player.expected_weeks_available,
                'willing_to_referee': user.player.willing_to_referee,
                'unavailable_dates': user.player.unavailable_dates
            }

        return jsonify({
            'success': True,
            'user': user_details
        })

    except Exception as e:
        logger.error(f"Error getting waitlist user details for user {user_id}: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': 'Failed to get user details'}), 500


@admin_panel_bp.route('/users/waitlist/process', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def process_waitlist_user():
    """Legacy route for bulk waitlist processing."""
    try:
        action = request.form.get('action')
        user_id = request.form.get('user_id')

        if action == 'process_all':
            # Process all waitlist users - move them to pending approval
            waitlist_users = db.session.query(User).join(User.roles).filter(
                Role.name == 'pl-waitlist'
            ).all()

            processed_count = 0
            for user in waitlist_users:
                try:
                    # Remove waitlist role and add unverified role
                    waitlist_role = db.session.query(Role).filter_by(name='pl-waitlist').first()
                    unverified_role = db.session.query(Role).filter_by(name='pl-unverified').first()

                    if waitlist_role in user.roles:
                        user.roles.remove(waitlist_role)
                    if unverified_role and unverified_role not in user.roles:
                        user.roles.append(unverified_role)

                    user.approval_status = 'pending'
                    processed_count += 1
                except Exception as e:
                    logger.error(f"Error processing waitlist user {user.id}: {e}")

            db.session.commit()

            # Log the action
            AdminAuditLog.log_action(
                user_id=current_user.id,
                action='process_all_waitlist',
                resource_type='user_waitlist',
                resource_id='bulk',
                new_value=f"Moved {processed_count} users from waitlist to pending approval",
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )

            flash(f'{processed_count} users moved from waitlist to pending approval', 'success')

        return redirect(url_for('admin_panel.user_waitlist'))
    except Exception as e:
        logger.error(f"Error processing waitlist users: {e}")
        flash('Waitlist processing failed. Check database connectivity and user operations.', 'error')
        return redirect(url_for('admin_panel.user_waitlist'))
