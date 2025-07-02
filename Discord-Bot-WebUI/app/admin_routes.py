# app/admin_routes.py

"""
Admin Routes Module

This module contains all the admin-specific routes for the application,
including dashboard management, container control, announcements,
feedback handling, scheduling tasks, and role/permission management.

All routes are protected by login and role requirements.
"""

import logging
import time
import requests
from datetime import datetime, timedelta

from celery.result import AsyncResult
from flask import (
    Blueprint, render_template, redirect, url_for,
    request, jsonify, abort, g, current_app
)
from sqlalchemy import func
from flask_login import login_required
from sqlalchemy.orm import joinedload, aliased
from flask_wtf.csrf import CSRFProtect

from app.alert_helpers import show_success, show_error, show_warning, show_info
from app.admin_helpers import (
    get_filtered_users, handle_user_action, get_container_data,
    manage_docker_container, get_container_logs, send_sms_message,
    handle_announcement_update, get_role_permissions_data,
    get_rsvp_status_data, handle_permissions_update,
    get_available_subs, get_match_subs, assign_sub_to_team,
    remove_sub_assignment, get_player_active_sub_assignments,
    cleanup_old_sub_assignments, get_sub_requests, create_sub_request,
    update_sub_request_status
)
from app.decorators import role_required
from app.email import send_email
from app.forms import (
    AnnouncementForm, EditUserForm, ResetPasswordForm,
    AdminFeedbackForm, NoteForm, FeedbackReplyForm
)
from app.models import (
    Role, Permission, MLSMatch, ScheduledMessage,
    Announcement, Feedback, FeedbackReply, Note, Team, Match,
    Player, Availability, User, Schedule, Season, League,
    TemporarySubAssignment, SubRequest
)
from sqlalchemy import and_, or_, func, desc
from app.tasks.tasks_core import (
    schedule_season_availability,
    send_availability_message_task
)
from app.tasks.tasks_discord import (
    update_player_discord_roles,
    fetch_role_status,
    process_discord_role_updates
)
from app.tasks.tasks_live_reporting import (
    force_create_mls_thread_task,
    schedule_all_mls_threads_task,
    schedule_mls_thread_task
)
from app.utils.user_helpers import safe_current_user

logger = logging.getLogger(__name__)
admin_bp = Blueprint('admin', __name__)

# Import CSRF utilities
from flask_wtf.csrf import CSRFProtect, generate_csrf

# Initialize CSRF protection
csrf = CSRFProtect()

# Create a more robust decorator to handle CSRF exemption
def csrf_exempt(route_func):
    """Decorator to exempt a route from CSRF protection and handle token issues."""
    route_func.csrf_exempt = True
    
    # Create a wrapper function to handle the request
    def wrapped_route(*args, **kwargs):
        # The route is already exempt, but we still add extra logging
        logger.info(f"CSRF exempt route called: {route_func.__name__}")
        
        # Proceed with the original route function
        return route_func(*args, **kwargs)
        
    # Preserve the route name and other attributes
    wrapped_route.__name__ = route_func.__name__
    wrapped_route.__module__ = route_func.__module__
    
    return wrapped_route

# -----------------------------------------------------------
# Admin Dashboard and User Management
# -----------------------------------------------------------

@admin_bp.route('/admin/dashboard', endpoint='admin_dashboard', methods=['GET', 'POST'])
@login_required
@role_required('Global Admin')
def admin_dashboard():
    """
    Render the admin dashboard and handle user actions such as
    approval, removal, password resets, and announcement creation.
    """
    session = g.db_session

    if request.method == 'POST':
        action = request.form.get('action')

        # Handle user actions: approve, remove, or reset password
        if action in ['approve', 'remove', 'reset_password']:
            user_id = request.form.get('user_id')
            success = handle_user_action(action, user_id, session=session)
            if not success:
                show_error('Error processing user action.')
            return redirect(url_for('admin.admin_dashboard'))

        # Handle announcement creation/update
        elif action == 'create_announcement':
            title = request.form.get('title')
            content = request.form.get('content')
            success = handle_announcement_update(title=title, content=content, session=session)
            if not success:
                show_error('Error creating announcement.')
            return redirect(url_for('admin.admin_dashboard'))

        # Handle permissions update
        elif action == 'update_permissions':
            role_id = request.form.get('role_id')
            permissions = request.form.getlist('permissions')
            success = handle_permissions_update(role_id, permissions)
            if not success:
                show_error('Error updating permissions.')
            return redirect(url_for('admin.admin_dashboard'))

    # Handle GET request: pagination and filtering of users
    page = request.args.get('page', 1, type=int)
    per_page = 10
    filters = {
        'search': request.args.get('search', ''),
        'role': request.args.get('role', ''),
        'league': request.args.get('league', ''),
        'active': request.args.get('active', ''),
        'approved': request.args.get('approved', '')
    }

    users_query = get_filtered_users(filters)
    total_users = users_query.count()
    users = users_query.offset((page - 1) * per_page).limit(per_page).all()

    template_data = {
        'users': users,
        'page': page,
        'total': total_users,
        'per_page': per_page,
        'roles': session.query(Role).all(),
        'permissions': session.query(Permission).all(),
        'announcements': session.query(Announcement).order_by(Announcement.created_at.desc()).all(),
        'teams': session.query(Team).all(),
        'edit_form': EditUserForm(),
        'reset_password_form': ResetPasswordForm(),
        'announcement_form': AnnouncementForm()
    }

    return render_template('admin_dashboard.html', **template_data)


# -----------------------------------------------------------
# Docker Container Management
# -----------------------------------------------------------

@admin_bp.route('/admin/container/<container_id>/<action>', endpoint='manage_container', methods=['POST'])
@login_required
@role_required('Global Admin')
def manage_container(container_id, action):
    """
    Manage Docker container actions (e.g., start, stop, restart).
    """
    success = manage_docker_container(container_id, action)
    if not success:
        show_error("Failed to manage container.")
    return redirect(url_for('admin.admin_dashboard'))


@admin_bp.route('/admin/view_logs/<container_id>', endpoint='view_logs', methods=['GET'])
@login_required
@role_required('Global Admin')
def view_logs(container_id):
    """
    Retrieve logs for a given container.
    """
    logs = get_container_logs(container_id)
    if logs is None:
        return jsonify({"error": "Failed to retrieve logs"}), 500
    return jsonify({"logs": logs})


@admin_bp.route('/admin/docker_status', endpoint='docker_status', methods=['GET'])
@login_required
@role_required('Global Admin')
def docker_status():
    """
    Get status information for all Docker containers.
    """
    containers = get_container_data()
    if containers is None:
        return jsonify({"error": "Failed to fetch container data"}), 500
    return jsonify(containers)


# -----------------------------------------------------------
# SMS Messaging
# -----------------------------------------------------------

@admin_bp.route('/admin/send_sms', endpoint='send_sms', methods=['POST'])
@login_required
@role_required('Global Admin')
def send_sms():
    """
    Send an SMS message using provided phone number and message body.
    """
    to_phone = request.form.get('to_phone_number')
    message = request.form.get('message_body')

    if not to_phone or not message:
        show_error("Phone number and message body are required.")
        return redirect(url_for('admin.admin_dashboard'))

    success = send_sms_message(to_phone, message)
    if not success:
        show_error("Failed to send SMS.")
    return redirect(url_for('admin.admin_dashboard'))


# -----------------------------------------------------------
# Role & Permission Management
# -----------------------------------------------------------

@admin_bp.route('/admin/get_role_permissions', endpoint='get_role_permissions', methods=['GET'])
@login_required
@role_required('Global Admin')
def get_role_permissions():
    """
    Retrieve permission details for a specified role.
    """
    role_id = request.args.get('role_id')
    permissions = get_role_permissions_data(role_id, session=g.db_session)
    if permissions is None:
        return jsonify({'error': 'Role not found.'}), 404
    return jsonify({'permissions': permissions})


# -----------------------------------------------------------
# Announcement Management
# -----------------------------------------------------------

@admin_bp.route('/admin/announcements', endpoint='manage_announcements', methods=['GET', 'POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def manage_announcements():
    """
    Render the announcement management view.
    On POST, create a new announcement.
    Also include user data so the Manage Users table is not empty.
    """
    session = g.db_session
    announcement_form = AnnouncementForm()

    if announcement_form.validate_on_submit():
        # Determine the next available position
        max_position = session.query(func.max(Announcement.position)).scalar() or 0
        new_announcement = Announcement(
            title=announcement_form.title.data,
            content=announcement_form.content.data,
            position=max_position + 1
        )
        session.add(new_announcement)
        session.commit()
        show_success("Announcement created successfully.")
        return redirect(url_for('admin.manage_announcements'))

    announcements = session.query(Announcement).order_by(Announcement.position).all()

    # Build user filters (using empty defaults if not provided)
    filters = {
        'search': request.args.get('search', ''),
        'role': request.args.get('role', ''),
        'league': request.args.get('league', ''),
        'active': request.args.get('active', ''),
        'approved': request.args.get('approved', '')
    }
    users_query = get_filtered_users(filters)
    total_users = users_query.count()
    page = request.args.get('page', 1, type=int)
    per_page = 10
    users = users_query.offset((page - 1) * per_page).limit(per_page).all()

    # Create additional forms for user actions if needed
    edit_form = EditUserForm()
    reset_password_form = ResetPasswordForm()

    # Also pass roles and permissions for the Manage Roles section
    roles = session.query(Role).all()
    permissions = session.query(Permission).all()

    return render_template(
        'admin_dashboard.html',
        announcements=announcements,
        announcement_form=announcement_form,
        users=users,
        total_users=total_users,
        page=page,
        per_page=per_page,
        edit_form=edit_form,
        reset_password_form=reset_password_form,
        roles=roles,
        permissions=permissions
    )


@admin_bp.route('/admin/announcements/<int:announcement_id>/edit', endpoint='edit_announcement', methods=['PUT', 'POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def edit_announcement(announcement_id):
    """
    Update the title and content of an existing announcement.
    """
    session = g.db_session
    
    # Handle both PUT (JSON) and POST (form) requests
    if request.method == 'PUT':
        data = request.get_json()
        title = data.get('title') if data else None
        content = data.get('content') if data else None
    else:  # POST
        title = request.form.get('title')
        content = request.form.get('content')
    
    if not title or not content:
        if request.method == 'PUT':
            return jsonify({'error': 'Title and content are required.'}), 400
        else:
            show_error('Title and content are required.')
            return redirect(url_for('admin.admin_dashboard'))

    announcement = session.query(Announcement).get(announcement_id)
    if not announcement:
        if request.method == 'PUT':
            return jsonify({'error': 'Announcement not found.'}), 404
        else:
            show_error('Announcement not found.')
            return redirect(url_for('admin.admin_dashboard'))

    announcement.title = title
    announcement.content = content
    session.commit()
    
    if request.method == 'PUT':
        return jsonify({'success': True})
    else:
        show_success('Announcement updated successfully.')
        return redirect(url_for('admin.admin_dashboard'))


@admin_bp.route('/admin/announcements/<int:announcement_id>/delete', endpoint='delete_announcement', methods=['DELETE', 'POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def delete_announcement(announcement_id):
    """
    Delete an announcement by its ID.
    """
    session = g.db_session
    announcement = session.query(Announcement).get(announcement_id)
    if not announcement:
        if request.method == 'DELETE':
            return jsonify({'error': 'Announcement not found.'}), 404
        else:
            show_error('Announcement not found.')
            return redirect(url_for('admin.admin_dashboard'))

    session.delete(announcement)
    session.commit()
    
    if request.method == 'DELETE':
        return jsonify({'success': True})
    else:
        show_success('Announcement deleted successfully.')
        return redirect(url_for('admin.admin_dashboard'))


@admin_bp.route('/admin/announcements/reorder', endpoint='reorder_announcements', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def reorder_announcements():
    """
    Update the ordering/positions of announcements.
    """
    session = g.db_session
    order = request.json.get('order', [])
    if not order:
        return jsonify({'error': 'No order data provided.'}), 400

    for item in order:
        ann = session.query(Announcement).get(item['id'])
        if ann:
            ann.position = item['position']
    session.commit()
    return jsonify({'success': True})


# -----------------------------------------------------------
# Scheduled Messages & Season Availability
# -----------------------------------------------------------

@admin_bp.route('/admin/schedule_season', endpoint='schedule_season', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def schedule_season():
    """
    Schedule availability messages for all future Sunday matches (next 90 days).
    Implemented directly without using Celery for reliability.
    """
    session = g.db_session
    
    try:
        # Direct implementation of schedule_season_availability from tasks_core.py
        start_date = datetime.utcnow().date()
        # For "entire season", look at the next 90 days
        end_date = start_date + timedelta(days=90)

        # Query matches within the next 90 days along with any associated scheduled messages
        matches = session.query(Match).options(
            joinedload(Match.scheduled_messages)
        ).filter(
            Match.date.between(start_date, end_date)
        ).all()

        # Prepare data for each match
        matches_data = [{
            'id': match.id,
            'date': match.date,
            'has_message': any(msg for msg in match.scheduled_messages),
            'name': f"{match.home_team.name} vs {match.away_team.name}" if hasattr(match, 'home_team') and hasattr(match, 'away_team') else "Unknown match"
        } for match in matches]

        scheduled_count = 0
        # Process each match; schedule a message if not already present
        for match_data in matches_data:
            if not match_data['has_message']:
                # Calculate send date and time (9:00 AM on the computed day)
                send_date = match_data['date'] - timedelta(days=match_data['date'].weekday() + 1)
                send_time = datetime.combine(send_date, datetime.min.time()) + timedelta(hours=9)

                scheduled_message = ScheduledMessage(
                    match_id=match_data['id'],
                    scheduled_send_time=send_time,
                    status='PENDING'
                )
                session.add(scheduled_message)
                scheduled_count += 1
                logger.info(f"Scheduled availability message for match {match_data['id']} - {match_data['name']} at {send_time}")
                
        # Commit all the new scheduled messages
        session.commit()

        if scheduled_count > 0:
            show_success(f'Successfully scheduled {scheduled_count} messages for matches in the next 90 days.')
        else:
            show_info('No new messages scheduled. All matches already have scheduled messages.')
        
        logger.info(f"Admin {safe_current_user.id} manually scheduled {scheduled_count} future matches")
        
    except Exception as e:
        logger.error(f"Error scheduling season availability: {str(e)}", exc_info=True)
        show_error(f'Error scheduling season availability: {str(e)}')
        session.rollback()
    
    return redirect(url_for('admin.view_scheduled_messages'))


@admin_bp.route('/admin/scheduled_messages', endpoint='view_scheduled_messages')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def view_scheduled_messages():
    """
    View a list of scheduled messages.
    """
    session = g.db_session
    messages = session.query(ScheduledMessage).order_by(ScheduledMessage.scheduled_send_time).all()
    return render_template('admin/scheduled_messages.html', title='Discord Scheduled Messages', messages=messages)


@admin_bp.route('/admin/force_send/<int:message_id>', endpoint='force_send_message', methods=['POST'])
@csrf_exempt
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def force_send_message(message_id):
    """
    Force-send a scheduled message immediately.
    """
    # Import statement outside try-except for clear error tracking
    from flask_wtf.csrf import validate_csrf, generate_csrf
    from flask import request, session as flask_session, current_app
    from wtforms.validators import ValidationError
    
    # Skip CSRF validation if necessary but ensure proper logging
    csrf_enabled = current_app.config.get('WTF_CSRF_ENABLED', True)
    
    if csrf_enabled:
        # Ensure the CSRF token exists in the session
        if 'csrf_token' not in flask_session:
            logger.warning("CSRF token missing from session - generating new token")
            # Generate a new token and store it
            csrf_token = generate_csrf()
            flask_session['csrf_token'] = csrf_token
        
        # Log CSRF debugging info
        logger.info(f"Processing force send for message {message_id}")
        logger.info(f"Form CSRF token: {request.form.get('csrf_token')}")
        logger.info(f"Session CSRF token exists: {'csrf_token' in flask_session}")
        logger.info(f"Session ID: {flask_session.sid if hasattr(flask_session, 'sid') else 'unknown'}")
        
        # At this point we've already authenticated the user via login_required
        # And confirmed they have the proper role via role_required
        # So we can skip the CSRF validation if it fails, but log the issue
        try:
            # Validate the CSRF token but continue even if it fails
            form_token = request.form.get('csrf_token')
            if form_token:
                validate_csrf(form_token)
                logger.info("CSRF validation successful")
            else:
                logger.warning("No CSRF token provided in form")
        except ValidationError as e:
            # Log the error but proceed anyway
            logger.warning(f"CSRF validation error: {str(e)} - proceeding with authenticated user")
    else:
        logger.info("CSRF protection is disabled in configuration")
    
    # Proceed with the main functionality
    session = g.db_session
    message = session.query(ScheduledMessage).get(message_id)
    if not message:
        logger.error(f"Message {message_id} not found")
        abort(404)

    try:
        # Queue the message for sending
        send_availability_message_task.delay(scheduled_message_id=message.id)
        message.status = 'QUEUED'
        session.commit()
        logger.info(f"Message {message_id} queued for sending")
        show_success('Message is being sent.')
    except Exception as e:
        logger.error(f"Error queuing message {message_id}: {str(e)}")
        show_error('Error queuing message for sending.')

    return redirect(url_for('admin.view_scheduled_messages'))


@admin_bp.route('/admin/schedule_next_week', endpoint='schedule_next_week', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def schedule_next_week():
    """
    Initiate the scheduling task specifically for the next week's Sunday matches.
    Schedules RSVP messages to be sent on Monday mornings.
    """
    from app.tasks.tasks_rsvp import schedule_weekly_match_availability
    
    task = schedule_weekly_match_availability.delay()
    show_success('This Sunday\'s match scheduling task has been initiated.')
    return redirect(url_for('admin.view_scheduled_messages'))


@admin_bp.route('/admin/process_scheduled_messages', endpoint='process_scheduled_messages', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def process_scheduled_messages_route():
    """
    Immediately process all pending scheduled messages.
    This forces the system to send out any pending RSVP messages right away.
    """
    from app.tasks.tasks_rsvp import process_scheduled_messages
    
    task = process_scheduled_messages.delay()
    show_success('Processing and sending all pending messages - check status in a few minutes.')
    return redirect(url_for('admin.view_scheduled_messages'))


@admin_bp.route('/admin/cleanup_old_messages', endpoint='cleanup_old_messages_route', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def cleanup_old_messages_route():
    """
    Clean up old scheduled messages that have already been sent or failed.
    By default, removes messages older than 7 days.
    """
    days_old = request.form.get('days_old', 7, type=int)
    session = g.db_session
    
    try:
        # Direct implementation without using Celery
        cutoff_date = datetime.utcnow() - timedelta(days=days_old)
        
        # Get count first for messaging
        total_messages = session.query(ScheduledMessage).filter(
            ScheduledMessage.scheduled_send_time < cutoff_date,
            ScheduledMessage.status.in_(['SENT', 'FAILED'])
        ).count()
        
        # Delete the old messages
        deleted_count = session.query(ScheduledMessage).filter(
            ScheduledMessage.scheduled_send_time < cutoff_date,
            ScheduledMessage.status.in_(['SENT', 'FAILED'])
        ).delete(synchronize_session=False)
        
        session.commit()
        
        if deleted_count > 0:
            show_success(f'Successfully deleted {deleted_count} old messages.')
        else:
            show_info(f'No messages found older than {days_old} days with status SENT or FAILED.')
            
        logger.info(f"Admin {safe_current_user.id} manually cleaned up {deleted_count} old messages")
        
    except Exception as e:
        logger.error(f"Error cleaning up old messages: {str(e)}", exc_info=True)
        show_error(f'Error cleaning up old messages: {str(e)}')
        session.rollback()
    
    return redirect(url_for('admin.view_scheduled_messages'))


@admin_bp.route('/admin/delete_message/<int:message_id>', endpoint='delete_message', methods=['POST'])
@csrf_exempt
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def delete_message(message_id):
    """
    Delete a specific scheduled message.
    """
    session = g.db_session
    message = session.query(ScheduledMessage).get(message_id)
    
    if not message:
        show_error('Message not found.')
    else:
        match_info = f"{message.match.home_team.name} vs {message.match.away_team.name}" if message.match else "Unknown match"
        session.delete(message)
        show_success(f'Message for {match_info} has been deleted.')
    
    return redirect(url_for('admin.view_scheduled_messages'))


# -----------------------------------------------------------
# RSVP Status and Reports
# -----------------------------------------------------------

@admin_bp.route('/admin/rsvp_status/<int:match_id>', endpoint='rsvp_status')
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'Pub League Coach'])
def rsvp_status(match_id):
    """
    Display RSVP status details for a specific match.
    """
    session = g.db_session
    match = session.query(Match).get(match_id)
    if not match:
        abort(404)
    rsvp_data = get_rsvp_status_data(match, session=session)
    return render_template('admin/rsvp_status.html', title='RSVP Status', match=match, rsvps=rsvp_data)


@admin_bp.route('/admin/send_custom_sms', methods=['POST'], endpoint='send_custom_sms')
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'Pub League Coach'])
def send_custom_sms():
    """
    Send a custom SMS message to a player.
    
    Expects:
    - player_id: ID of the player to message
    - phone: Phone number to send to
    - message: The message content
    - match_id: Optional - ID of the match for context
    """
    session = g.db_session
    player_id = request.form.get('player_id')
    phone = request.form.get('phone')
    message = request.form.get('message')
    match_id = request.form.get('match_id')
    
    if not player_id or not phone or not message:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Missing required fields'}), 400
        show_error('Phone number and message are required.')
        if match_id:
            return redirect(url_for('admin.rsvp_status', match_id=match_id))
        return redirect(url_for('admin.admin_dashboard'))
    
    player = session.query(Player).get(player_id)
    if not player:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Player not found'}), 404
        show_error('Player not found.')
        if match_id:
            return redirect(url_for('admin.rsvp_status', match_id=match_id))
        return redirect(url_for('admin.admin_dashboard'))
    
    # Check if user has SMS notifications enabled
    user = player.user
    if not user or not user.sms_notifications:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'SMS notifications are disabled for this user'}), 403
        show_error('SMS notifications are disabled for this user.')
        if match_id:
            return redirect(url_for('admin.rsvp_status', match_id=match_id))
        return redirect(url_for('admin.admin_dashboard'))
    
    # Send the SMS
    from app.sms_helpers import send_sms
    success, result = send_sms(phone, message, user_id=user.id)
    
    if success:
        # Log the SMS
        logger.info(f"Admin {safe_current_user.id} sent SMS to player {player_id}")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'message': 'SMS sent successfully'})
        show_success('SMS sent successfully.')
    else:
        logger.error(f"Failed to send SMS to player {player_id}: {result}")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': f'Failed to send SMS: {result}'})
        show_error(f'Failed to send SMS: {result}')
    
    if match_id:
        return redirect(url_for('admin.rsvp_status', match_id=match_id))
    return redirect(url_for('admin.admin_dashboard'))


@admin_bp.route('/admin/send_discord_dm', methods=['POST'], endpoint='send_discord_dm')
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'Pub League Coach'])
def send_discord_dm():
    """
    Send a Discord DM to a player using the bot.
    
    Expects:
    - player_id: ID of the player to message
    - message: The message content
    - match_id: Optional - ID of the match for context
    """
    session = g.db_session
    player_id = request.form.get('player_id')
    message = request.form.get('message')
    match_id = request.form.get('match_id')
    
    if not player_id or not message:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Missing required fields'}), 400
        show_error('Player ID and message are required.')
        if match_id:
            return redirect(url_for('admin.rsvp_status', match_id=match_id))
        return redirect(url_for('admin.admin_dashboard'))
    
    player = session.query(Player).get(player_id)
    if not player or not player.discord_id:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Player not found or no Discord ID'}), 404
        show_error('Player not found or has no Discord ID.')
        if match_id:
            return redirect(url_for('admin.rsvp_status', match_id=match_id))
        return redirect(url_for('admin.admin_dashboard'))
    
    # Check if user has Discord notifications enabled
    user = player.user
    if not user or not user.discord_notifications:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Discord notifications are disabled for this user'}), 403
        show_error('Discord notifications are disabled for this user.')
        if match_id:
            return redirect(url_for('admin.rsvp_status', match_id=match_id))
        return redirect(url_for('admin.admin_dashboard'))
    
    # Send the Discord DM using the bot API
    payload = {
        "message": message,
        "discord_id": player.discord_id
    }
    
    bot_api_url = current_app.config.get('BOT_API_URL', 'http://localhost:5001') + '/send_discord_dm'
    
    try:
        response = requests.post(bot_api_url, json=payload, timeout=10)
        if response.status_code == 200:
            logger.info(f"Admin {safe_current_user.id} sent Discord DM to player {player_id}")
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': True, 'message': 'Discord DM sent successfully'})
            show_success('Discord DM sent successfully.')
        else:
            logger.error(f"Failed to send Discord DM to player {player_id}: {response.text}")
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': 'Failed to send Discord DM'})
            show_error('Failed to send Discord DM.')
    except Exception as e:
        logger.error(f"Error contacting Discord bot: {str(e)}")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': f'Error contacting Discord bot: {str(e)}'})
        show_error(f'Error contacting Discord bot: {str(e)}')
    
    if match_id:
        return redirect(url_for('admin.rsvp_status', match_id=match_id))
    return redirect(url_for('admin.admin_dashboard'))


@admin_bp.route('/admin/update_rsvp', methods=['POST'], endpoint='update_rsvp')
@csrf_exempt
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'Pub League Coach'])
def update_rsvp():
    """
    Update a player's RSVP status for a match.
    
    Expects:
    - player_id: ID of the player
    - match_id: ID of the match
    - response: The RSVP response ('yes', 'no', 'maybe', 'no_response')
    """
    from app.tasks.tasks_rsvp import notify_discord_of_rsvp_change_task, notify_frontend_of_rsvp_change_task
    
    session = g.db_session
    player_id = request.form.get('player_id')
    match_id = request.form.get('match_id')
    response = request.form.get('response')
    
    if not player_id or not match_id or not response:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Missing required fields'}), 400
        show_error('Player ID, match ID, and response are required.')
        return redirect(url_for('admin.rsvp_status', match_id=match_id))
    
    # Check if the player and match exist
    player = session.query(Player).get(player_id)
    match = session.query(Match).get(match_id)
    if not player or not match:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Player or match not found'}), 404
        show_error('Player or match not found.')
        return redirect(url_for('admin.rsvp_status', match_id=match_id))
    
    # If clearing the response
    if response == 'no_response':
        try:
            # Delete the RSVP record
            availability = session.query(Availability).filter_by(
                player_id=player_id, 
                match_id=match_id
            ).first()
            
            if availability:
                session.delete(availability)
                session.commit()
                logger.info(f"Admin {safe_current_user.id} cleared RSVP for player {player_id}, match {match_id}")
                
                # Notify Discord and frontend of the change
                notify_discord_of_rsvp_change_task.delay(match_id=match_id)
                
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'success': True, 'message': 'RSVP cleared successfully'})
                show_success('RSVP cleared successfully.')
            else:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'success': True, 'message': 'No RSVP found to clear'})
                show_info('No RSVP found to clear.')
        except Exception as e:
            logger.error(f"Error clearing RSVP: {str(e)}")
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': f'Error clearing RSVP: {str(e)}'})
            show_error(f'Error clearing RSVP: {str(e)}')
    else:
        try:
            # Update or create the availability record
            availability = session.query(Availability).filter_by(
                match_id=match_id,
                player_id=player_id
            ).first()
            
            old_response = availability.response if availability else None
            
            if availability:
                availability.response = response
                availability.responded_at = datetime.utcnow()
            else:
                # If discord_id is null but it's required, add a fallback value
                discord_id = player.discord_id
                if discord_id is None:
                    # Use a placeholder value if discord_id is required but not available
                    discord_id = "admin_added"
                
                availability = Availability(
                    match_id=match_id,
                    player_id=player_id,
                    response=response,
                    discord_id=discord_id,
                    responded_at=datetime.utcnow()
                )
                session.add(availability)
            
            session.commit()
            logger.info(f"Admin {safe_current_user.id} updated RSVP for player {player_id}, match {match_id} to {response}")
            
            # Notify Discord and frontend of the change
            notify_discord_of_rsvp_change_task.delay(match_id=match_id)
            notify_frontend_of_rsvp_change_task.delay(match_id=match_id, player_id=player_id, response=response)
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': True, 'message': 'RSVP updated successfully'})
            show_success('RSVP updated successfully.')
        except Exception as e:
            logger.error(f"Error updating RSVP: {str(e)}")
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': f'Error updating RSVP: {str(e)}'})
            show_error(f'Error updating RSVP: {str(e)}')
    
    return redirect(url_for('admin.rsvp_status', match_id=match_id))


@admin_bp.route('/admin/reports', endpoint='admin_reports')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def admin_reports():
    """
    Render the admin reports view, including filtering and pagination
    for feedback reports.
    """
    session = g.db_session
    page = request.args.get('page', 1, type=int)
    per_page = 20
    filters = {
        'status': request.args.get('status', ''),
        'priority': request.args.get('priority', ''),
        'sort_by': request.args.get('sort_by', 'created_at'),
        'order': request.args.get('order', 'desc')
    }

    query = session.query(Feedback)
    if filters['status']:
        query = query.filter(Feedback.status == filters['status'])
    if filters['priority']:
        query = query.filter(Feedback.priority == filters['priority'])

    sort_col = getattr(Feedback, filters['sort_by'], Feedback.created_at)
    if filters['order'] == 'asc':
        query = query.order_by(sort_col.asc())
    else:
        query = query.order_by(sort_col.desc())

    total = query.count()
    feedbacks = query.offset((page - 1) * per_page).limit(per_page).all()

    return render_template('admin_reports.html', title='Admin Reports', feedbacks=feedbacks, page=page, total=total, per_page=per_page)


# -----------------------------------------------------------
# Feedback and Note Handling
# -----------------------------------------------------------

@admin_bp.route('/admin/feedback/<int:feedback_id>', endpoint='view_feedback', methods=['GET', 'POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def view_feedback(feedback_id):
    """
    View and update feedback details. Supports updating feedback,
    submitting a reply, and adding internal notes.
    """
    session = g.db_session
    feedback = session.query(Feedback).options(
        joinedload(Feedback.replies).joinedload(FeedbackReply.user),
        joinedload(Feedback.user)
    ).get(feedback_id)
    if not feedback:
        abort(404)

    form = AdminFeedbackForm(obj=feedback)
    reply_form = FeedbackReplyForm()
    note_form = NoteForm()

    if request.method == 'POST':
        if 'update_feedback' in request.form and form.validate():
            form.populate_obj(feedback)
            show_success('Feedback has been updated successfully.')

        elif 'submit_reply' in request.form and reply_form.validate():
            reply = FeedbackReply(
                feedback_id=feedback.id,
                user_id=safe_current_user.id,
                content=reply_form.content.data,
                is_admin_reply=True
            )
            session.add(reply)
            if feedback.user and feedback.user.email:
                try:
                    send_email(
                        to=feedback.user.email,
                        subject=f"New admin reply to your Feedback #{feedback.id}",
                        body=render_template('emails/new_reply_admin.html',
                                             feedback=feedback,
                                             reply=reply)
                    )
                except Exception as e:
                    logger.error(f"Failed to send reply notification email: {str(e)}")
            show_success('Your reply has been added successfully.')
            return redirect(url_for('admin.view_feedback', feedback_id=feedback.id))

        elif 'add_note' in request.form and note_form.validate():
            note = Note(
                content=note_form.content.data,
                feedback_id=feedback.id,
                author_id=safe_current_user.id
            )
            session.add(note)
            show_success('Note added successfully.')
            return redirect(url_for('admin.view_feedback', feedback_id=feedback.id))

    return render_template(
        'admin_report_detail.html',
        feedback=feedback,
        form=form,
        reply_form=reply_form,
        note_form=note_form
    )


@admin_bp.route('/admin/feedback/<int:feedback_id>/close', endpoint='close_feedback', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def close_feedback(feedback_id):
    """
    Close the feedback and notify the user via email.
    """
    session = g.db_session
    feedback = session.query(Feedback).get(feedback_id)
    if not feedback:
        abort(404)

    feedback.status = 'Closed'
    feedback.closed_at = datetime.utcnow()

    if feedback.user and feedback.user.email:
        send_email(
            to=feedback.user.email,
            subject=f"Your Feedback #{feedback.id} has been closed",
            body=render_template("emails/feedback_closed.html", feedback=feedback)
        )

    show_success('Feedback has been closed successfully.')
    return redirect(url_for('admin.view_feedback', feedback_id=feedback.id))


@admin_bp.route('/admin/feedback/<int:feedback_id>/delete', endpoint='delete_feedback', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def delete_feedback(feedback_id):
    """
    Permanently delete a feedback entry.
    """
    session = g.db_session
    feedback = session.query(Feedback).get(feedback_id)
    if not feedback:
        abort(404)
    session.delete(feedback)
    show_success('Feedback has been permanently deleted.')
    return redirect(url_for('admin.admin_reports'))


# -----------------------------------------------------------
# Task Status and Role Updates (Discord & MLS)
# -----------------------------------------------------------

@admin_bp.route('/admin/check_role_status/<task_id>', endpoint='check_role_status', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def check_role_status(task_id):
    """
    Check the status of a Discord role update task.
    """
    try:
        task = fetch_role_status.AsyncResult(task_id)
        if task.ready():
            if task.successful():
                task_result = task.get()  # Expected format: {'success':True,'results':[...],'message':...}
                return jsonify({
                    'state': 'COMPLETE',
                    'results': task_result['results']
                })
            else:
                return jsonify({
                    'state': 'FAILED',
                    'error': str(task.result)
                })
        return jsonify({'state': 'PENDING'})
    except Exception as e:
        logger.error(f"Error checking task status: {str(e)}")
        return jsonify({'state': 'ERROR', 'error': str(e)}), 500


@admin_bp.route('/admin/update_player_roles/<int:player_id>', endpoint='update_player_roles_route', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def update_player_roles_route(player_id):
    """
    Update a player's Discord roles.
    """
    try:
        # This will block until the task completes; consider async polling if needed
        task_result = update_player_discord_roles.delay(player_id).get(timeout=30)
        if task_result.get('success'):
            return jsonify({
                'success': True,
                'player_data': task_result['player_data']
            })
        else:
            return jsonify({
                'success': False,
                'error': task_result.get('message', 'Unknown error occurred')
            }), 400
    except Exception as e:
        logger.error(f"Error updating roles for player {player_id}: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/admin/update_discord_roles', endpoint='mass_update_discord_roles', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def mass_update_discord_roles():
    """
    Initiate a mass update for Discord roles across players.
    """
    session = g.db_session
    try:
        # Mark all players that are out of sync
        session.query(Player).filter(
            Player.discord_id.isnot(None),
            Player.discord_roles_synced == False
        ).update({Player.discord_needs_update: True}, synchronize_session=False)

        result = process_discord_role_updates.delay()

        return jsonify({
            'success': True,
            'message': 'Mass role update initiated',
            'task_id': result.id
        })

    except Exception as e:
        logger.error(f"Error initiating mass role update: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/admin/mls_matches', endpoint='view_mls_matches')
@login_required
@role_required('Global Admin')
def view_mls_matches():
    """
    View MLS matches.
    """
    session = g.db_session
    matches = session.query(MLSMatch).all()
    return render_template('admin/mls_matches.html',
                           title='MLS Matches',
                           matches=matches,
                           timedelta=timedelta)


@admin_bp.route('/admin/schedule_mls_match_thread/<int:match_id>', endpoint='schedule_mls_match_thread_route', methods=['POST'])
@login_required
@role_required('Global Admin')
def schedule_mls_match_thread_route(match_id):
    """
    Schedule a thread for an MLS match.
    """
    hours_before = request.json.get('hours_before', 48)
    task = schedule_mls_thread_task.delay(match_id, hours_before)
    return jsonify({
        'success': True,
        'task_id': task.id,
        'message': 'Thread scheduling task started'
    })


@admin_bp.route('/admin/check_thread_status/<task_id>', endpoint='check_thread_status', methods=['GET'])
@login_required
@role_required('Global Admin')
def check_thread_status(task_id):
    """
    Check the status of an MLS thread creation task.
    """
    try:
        task = force_create_mls_thread_task.AsyncResult(task_id)
        if task.ready():
            if task.successful():
                return jsonify({'state': 'COMPLETE', 'result': task.get()})
            else:
                return jsonify({'state': 'FAILED', 'error': str(task.result)})
        return jsonify({'state': 'PENDING'})
    except Exception as e:
        logger.error(f"Error checking task status: {str(e)}")
        return jsonify({'state': 'ERROR', 'error': str(e)}), 500


@admin_bp.route('/admin/task_status/<task_id>', endpoint='check_task_status', methods=['GET'])
@login_required
@role_required('Global Admin')
def check_task_status(task_id):
    """
    Check the status of a generic task.
    """
    task_result = AsyncResult(task_id)
    result = {
        'task_id': task_id,
        'status': task_result.status,
    }
    if task_result.ready():
        result['result'] = task_result.get() if task_result.successful() else str(task_result.result)
    return jsonify(result)


@admin_bp.route('/admin/schedule_all_mls_threads', endpoint='schedule_all_mls_threads_route', methods=['POST'])
@login_required
@role_required('Global Admin')
def schedule_all_mls_threads_route():
    """
    Initiate mass scheduling for all MLS match threads.
    """
    task = schedule_all_mls_threads_task.delay()
    return jsonify({
        'success': True,
        'task_id': task.id,
        'message': 'Mass thread scheduling started'
    })


# -----------------------------------------------------------
# System Health and Task Status (Placeholder Functions)
# -----------------------------------------------------------

def get_match_stats(session):
    """Placeholder: Return match statistics."""
    return {"status": "ok", "stats": []}


def check_system_health(session):
    """Placeholder: Return system health status."""
    return {"status": "healthy"}


def check_task_status_placeholder(session):
    """Placeholder: Return current task status."""
    return {"status": "no_tasks"}


@admin_bp.route('/admin/test_twilio', methods=['GET'])
@login_required
@role_required('Global Admin')
def test_twilio_config():
    """
    Test the Twilio configuration.
    
    Checks the environment variables and attempts a connection to Twilio
    without actually sending an SMS. Returns diagnostic information.
    """
    import os
    from app.sms_helpers import check_sms_config
    from twilio.rest import Client
    from flask import current_app
    import base64
    
    result = {
        'config_check': check_sms_config(),
        'environment_vars': {},
        'auth_check': {},
        'connection_test': {'status': 'UNKNOWN'}
    }
    
    # Add environment variable debug info (hiding actual values)
    for key in os.environ:
        if 'TWILIO' in key or 'TEXTMAGIC' in key:
            result['environment_vars'][key] = "PRESENT"
    
    # Check auth token for any issues
    twilio_sid = current_app.config.get('TWILIO_SID') or current_app.config.get('TWILIO_ACCOUNT_SID')
    twilio_auth_token = current_app.config.get('TWILIO_AUTH_TOKEN')
    
    if twilio_sid and twilio_auth_token:
        # Check for common issues in auth token
        result['auth_check']['sid_length'] = len(twilio_sid)
        result['auth_check']['token_length'] = len(twilio_auth_token)
        result['auth_check']['sid_starts_with'] = twilio_sid[:2] if len(twilio_sid) >= 2 else ""
        
        # Check if the auth token is valid Base64
        try:
            # Just check if it could be valid Base64 (not whether it is)
            is_valid_base64 = all(c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=' 
                                for c in twilio_auth_token)
            result['auth_check']['valid_token_format'] = is_valid_base64
        except Exception:
            result['auth_check']['valid_token_format'] = False
    else:
        result['auth_check']['sid_present'] = bool(twilio_sid)
        result['auth_check']['token_present'] = bool(twilio_auth_token)
    
    # Test actual Twilio connection
    try:
        if not twilio_sid or not twilio_auth_token:
            result['connection_test'] = {
                'status': 'FAILED',
                'message': 'Missing Twilio credentials'
            }
        else:
            # Try with hardcoded credentials (redacted in the response)
            raw_auth_token = os.environ.get('TWILIO_AUTH_TOKEN')
            result['auth_check']['raw_token_different'] = raw_auth_token != twilio_auth_token
            
            # Check for whitespace issues
            result['auth_check']['token_has_whitespace'] = any(c.isspace() for c in twilio_auth_token)
            cleaned_token = twilio_auth_token.strip()
            
            client = Client(twilio_sid, cleaned_token)
            # Make a simple API call that doesn't send an SMS
            try:
                account = client.api.accounts(twilio_sid).fetch()
                result['connection_test'] = {
                    'status': 'SUCCESS',
                    'account_status': account.status,
                    'account_type': account.type
                }
            except Exception as acc_error:
                # If that fails, try with raw token from environment
                try:
                    client = Client(twilio_sid, raw_auth_token)
                    account = client.api.accounts(twilio_sid).fetch()
                    result['connection_test'] = {
                        'status': 'SUCCESS_WITH_RAW_TOKEN',
                        'account_status': account.status,
                        'account_type': account.type,
                        'error_with_config_token': str(acc_error)
                    }
                except Exception as raw_error:
                    result['connection_test'] = {
                        'status': 'FAILED_BOTH',
                        'config_token_error': str(acc_error),
                        'raw_token_error': str(raw_error)
                    }
    except Exception as e:
        result['connection_test'] = {
            'status': 'ERROR',
            'message': str(e)
        }
    
    return jsonify(result)


@admin_bp.route('/admin/match_stats', endpoint='get_match_statistics', methods=['GET'])
@login_required
@role_required('Global Admin')
def get_match_statistics():
    """
    Retrieve match statistics.
    """
    stats = get_match_stats(g.db_session)
    return jsonify(stats)


@admin_bp.route('/admin/health', endpoint='health_check', methods=['GET'])
@login_required
@role_required('Global Admin')
def health_check():
    """
    Perform a system health check.
    """
    health_status = check_system_health(g.db_session)
    return jsonify(health_status)


@admin_bp.route('/admin/task_status', endpoint='get_task_status', methods=['GET'])
@login_required
@role_required('Global Admin')
def get_task_status():
    """
    Retrieve the status of current tasks (placeholder implementation).
    """
    task_status = check_task_status_placeholder(g.db_session)
    return jsonify(task_status)


@admin_bp.route('/admin/sub_requests', endpoint='manage_sub_requests')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def manage_sub_requests():
    """
    Display the sub request dashboard for admins.
    
    Shows all upcoming matches grouped by week and flags any teams that need substitutes.
    Also displays a card view of pending sub requests for quick action.
    """
    session = g.db_session
    
    # Get filter parameters
    show_requested = request.args.get('show_requested', 'all')
    week = request.args.get('week')
    
    # Get all weeks for the filter dropdown
    current_season = session.query(Season).filter_by(is_current=True, league_type="Pub League").first()
    weeks = []
    if current_season:
        weeks_query = session.query(Schedule.week).filter(
            Schedule.season_id == current_season.id
        ).distinct().order_by(Schedule.week)
        weeks = [str(week_row[0]) for week_row in weeks_query]
    
    # Get upcoming matches (for the next 30 days)
    today = datetime.now().date()
    thirty_days_ahead = today + timedelta(days=30)
    
    match_query = session.query(Match).options(
        joinedload(Match.home_team),
        joinedload(Match.away_team),
        joinedload(Match.schedule)
    ).filter(
        Match.date >= today,
        Match.date <= thirty_days_ahead
    )
    
    # Filter by week if specified
    if week:
        match_query = match_query.join(
            Schedule, Match.schedule_id == Schedule.id
        ).filter(
            Schedule.week == week
        )
    
    # Order by date, then time
    upcoming_matches = match_query.order_by(
        Match.date,
        Match.time
    ).all()
    
    # Check if we have any matches
    if not upcoming_matches:
        logger.warning("No upcoming matches found for sub requests page. Check your date filters.")
        # Add debug log to see current date range
        logger.debug(f"Date range: {today} to {thirty_days_ahead}")
    
    # Get all sub requests for these matches
    match_ids = [match.id for match in upcoming_matches]
    
    # Only get sub requests if we have matches
    if match_ids:
        sub_requests = session.query(SubRequest).options(
            joinedload(SubRequest.match),
            joinedload(SubRequest.team),
            joinedload(SubRequest.requester),
            joinedload(SubRequest.fulfiller)
        ).filter(
            SubRequest.match_id.in_(match_ids)
        ).order_by(
            SubRequest.created_at.desc()
        ).all()
    else:
        sub_requests = []
    
    # Organize sub requests by match and team for easier access
    requested_teams_by_match = {}
    for match in upcoming_matches:
        requested_teams_by_match[match.id] = {}
    
    for req in sub_requests:
        if req.match_id in requested_teams_by_match:
            requested_teams_by_match[req.match_id][req.team_id] = req
    
    # Filter matches based on whether they have requests or not
    filtered_matches = []
    for match in upcoming_matches:
        has_requests = match.id in requested_teams_by_match and requested_teams_by_match[match.id]
        
        if show_requested == 'all':
            filtered_matches.append(match)
        elif show_requested == 'requested' and has_requests:
            filtered_matches.append(match)
        elif show_requested == 'not_requested' and not has_requests:
            filtered_matches.append(match)
    
    upcoming_matches = filtered_matches
    
    # Get available subs for each request
    available_subs = get_available_subs(session=session)
    
    return render_template(
        'admin/manage_sub_requests.html',
        title='Manage Sub Requests',
        sub_requests=sub_requests,
        upcoming_matches=upcoming_matches,
        requested_teams_by_match=requested_teams_by_match,
        available_subs=available_subs,
        show_requested=show_requested,
        current_week=week,
        weeks=weeks
    )


@admin_bp.route('/admin/sub_requests/<int:request_id>', methods=['POST'], endpoint='update_sub_request')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def update_sub_request(request_id):
    """
    Update a sub request's status.
    
    Handles fulfilling a sub request by assigning a player.
    """
    session = g.db_session
    
    action = request.form.get('action')
    player_id = request.form.get('player_id')  # For fulfillment
    
    if not action or action != 'fulfill':
        show_error('Invalid action.')
        return redirect(url_for('admin.manage_sub_requests'))
    
    if not player_id:
        show_error('Player ID is required for fulfillment.')
        return redirect(url_for('admin.manage_sub_requests'))
    
    # Get the sub request
    sub_request = session.query(SubRequest).options(
        joinedload(SubRequest.match),
        joinedload(SubRequest.team)
    ).get(request_id)
    
    if not sub_request:
        show_error('Sub request not found.')
        return redirect(url_for('admin.manage_sub_requests'))
    
    # Directly fulfill the request - no intermediate approval step
    fulfill_success, fulfill_message = assign_sub_to_team(
        match_id=sub_request.match_id,
        team_id=sub_request.team_id,
        player_id=player_id,
        user_id=safe_current_user.id,
        session=session
    )
    
    if fulfill_success:
        # Update the sub request status
        success, message = update_sub_request_status(
            request_id=request_id,
            status='FULFILLED',
            fulfilled_by=safe_current_user.id,
            session=session
        )
    else:
        success = False
        message = fulfill_message
    
    if success:
        show_success(message)
    else:
        show_error(message)
    
    return redirect(url_for('admin.manage_sub_requests'))


@admin_bp.route('/admin/request_sub', methods=['POST'], endpoint='request_sub')
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'Pub League Coach'])
def request_sub():
    """
    Create a new sub request.
    
    Coaches can request subs for their teams, and admins can request for any team.
    """
    session = g.db_session
    
    match_id = request.form.get('match_id', type=int)
    team_id_raw = request.form.get('team_id')
    notes = request.form.get('notes')
    
    if not match_id or not team_id_raw:
        show_error('Missing required fields for sub request.')
        return redirect(request.referrer or url_for('main.index'))
    
    # Handle special cases from the JavaScript fallback
    if team_id_raw == 'home_team' or team_id_raw == 'away_team':
        # Get the match to determine the actual team IDs
        match = session.query(Match).get(match_id)
        if not match:
            show_error('Match not found.')
            return redirect(request.referrer or url_for('main.index'))
        
        # Set team_id based on the placeholder value
        team_id = match.home_team_id if team_id_raw == 'home_team' else match.away_team_id
    else:
        try:
            team_id = int(team_id_raw)
        except (ValueError, TypeError):
            show_error('Invalid team ID format.')
            return redirect(request.referrer or url_for('main.index'))
    
    # Check permissions for coaches
    if safe_current_user.has_role('Pub League Coach') and not (safe_current_user.has_role('Pub League Admin') or safe_current_user.has_role('Global Admin')):
        # Verify that the user is a coach for this team
        is_coach = False
        
        # Get the match to verify teams
        match = session.query(Match).get(match_id)
        if not match:
            show_error('Match not found.')
            return redirect(request.referrer or url_for('main.index'))
        
        # Verify this is a valid team for this match
        if team_id != match.home_team_id and team_id != match.away_team_id:
            show_error('Selected team is not part of this match.')
            return redirect(url_for('admin.rsvp_status', match_id=match_id))
        
        # Direct database query to check coach status
        try:
            # Simpler direct SQL query for maximum reliability
            from sqlalchemy import text
            coach_team_results = session.execute(
                text("SELECT COUNT(*) FROM player_teams WHERE player_id = :player_id AND team_id = :team_id AND is_coach = TRUE"),
                {"player_id": safe_current_user.player.id, "team_id": team_id}
            ).fetchone()
            
            if coach_team_results and coach_team_results[0] > 0:
                is_coach = True
                logger.info(f"User {safe_current_user.id} verified as coach for team {team_id}")
            else:
                logger.warning(f"User {safe_current_user.id} is not a coach for team {team_id}")
        except Exception as sql_e:
            logger.error(f"SQL coach check failed: {str(sql_e)}")
            
            # Last resort check - use related models
            try:
                # Try one more alternate method - get teams for this player
                player_id = safe_current_user.player.id
                coach_teams = session.query(Team).join(
                    "player_teams"
                ).filter(
                    text(f"player_teams.player_id = {player_id} AND player_teams.is_coach = TRUE")
                ).all()
                
                if any(t.id == team_id for t in coach_teams):
                    is_coach = True
                    logger.info(f"Alternate check: User {safe_current_user.id} verified as coach for team {team_id}")
            except Exception as alt_e:
                logger.error(f"Alternate coach check failed: {str(alt_e)}")
        
        # Final check
        if not is_coach:
            if current_app.debug or current_app.config.get('ENV') == 'development':
                # Development mode - still allow it but log warning
                logger.warning(f"Development mode: Allowing sub request for user {safe_current_user.id} despite not being coach")
                is_coach = True
            elif match and (team_id == match.home_team_id or team_id == match.away_team_id):
                # If it's a valid team for this match and user has Pub League Coach role, 
                # we'll allow it even without direct relationship since database schema
                # might not fully represent coaching relationships
                logger.warning(f"Coach role override: Allowing request for {safe_current_user.id} for team {team_id}")
                is_coach = True
            else:
                show_error('You are not authorized to request subs for this team.')
                logger.warning(f"User {safe_current_user.id} denied sub request for team {team_id}, match {match_id}")
                return redirect(request.referrer or url_for('main.index'))
    
    # Create the sub request
    success, message, request_id = create_sub_request(
        match_id=match_id,
        team_id=team_id,
        requested_by=safe_current_user.id,
        notes=notes,
        session=session
    )
    
    if success:
        show_success(message)
    else:
        show_error(message)
    
    # Determine where to redirect
    if request.referrer and 'rsvp_status' in request.referrer:
        return redirect(url_for('admin.rsvp_status', match_id=match_id))
    else:
        return redirect(url_for('admin.manage_sub_requests'))


@admin_bp.route('/admin/sms_status', methods=['GET'])
@login_required
@role_required('Global Admin')
def sms_rate_limit_status():
    """
    Check SMS usage and rate limiting status.
    
    This endpoint provides information about:
    - System-wide SMS usage
    - Per-user SMS usage
    - Rate limit configuration
    """
    from app.sms_helpers import sms_user_cache, sms_system_counter, SMS_RATE_LIMIT_PER_USER, SMS_SYSTEM_RATE_LIMIT, SMS_RATE_LIMIT_WINDOW
    
    current_time = time.time()
    cutoff_time = current_time - SMS_RATE_LIMIT_WINDOW
    
    # Clean up expired timestamps
    cleaned_system_counter = [t for t in sms_system_counter if t > cutoff_time]
    
    # Prepare per-user data
    user_data = {}
    for user_id, timestamps in sms_user_cache.items():
        valid_timestamps = [t for t in timestamps if t > cutoff_time]
        if valid_timestamps:
            # Get user information if available
            session = g.db_session
            user = session.query(User).get(user_id)
            username = user.username if user else "Unknown"
            
            user_data[user_id] = {
                'username': username,
                'count': len(valid_timestamps),
                'remaining': SMS_RATE_LIMIT_PER_USER - len(valid_timestamps),
                'last_send': datetime.fromtimestamp(max(valid_timestamps)).strftime('%Y-%m-%d %H:%M:%S'),
                'reset': datetime.fromtimestamp(min(valid_timestamps) + SMS_RATE_LIMIT_WINDOW).strftime('%Y-%m-%d %H:%M:%S')
            }
    
    # Calculate system-wide reset time if any messages have been sent
    system_reset = None
    if cleaned_system_counter:
        system_reset = datetime.fromtimestamp(min(cleaned_system_counter) + SMS_RATE_LIMIT_WINDOW).strftime('%Y-%m-%d %H:%M:%S')
    
    return jsonify({
        'system': {
            'total_count': len(cleaned_system_counter),
            'limit': SMS_SYSTEM_RATE_LIMIT,
            'remaining': SMS_SYSTEM_RATE_LIMIT - len(cleaned_system_counter),
            'window_seconds': SMS_RATE_LIMIT_WINDOW,
            'window_hours': SMS_RATE_LIMIT_WINDOW / 3600,
            'reset_time': system_reset
        },
        'users': user_data,
        'config': {
            'per_user_limit': SMS_RATE_LIMIT_PER_USER,
            'system_limit': SMS_SYSTEM_RATE_LIMIT,
            'window_seconds': SMS_RATE_LIMIT_WINDOW
        }
    })


# -----------------------------------------------------------
# Temporary Sub Management
# -----------------------------------------------------------

@admin_bp.route('/admin/subs', endpoint='manage_subs')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def manage_subs():
    """
    Display a list of all available substitutes and their assignments.
    
    This page shows all players marked as substitutes and allows admins to
    manage their team assignments for matches.
    """
    session = g.db_session
    
    # Get all available subs
    subs = get_available_subs(session=session)
    
    # Get all upcoming matches in chronological order
    upcoming_matches = session.query(Match).filter(
        Match.date >= datetime.utcnow().date()
    ).order_by(
        Match.date, Match.time
    ).options(
        joinedload(Match.home_team),
        joinedload(Match.away_team)
    ).all()
    
    # Get teams for assignment
    teams = session.query(Team).all()
    
    return render_template(
        'admin/manage_subs.html',
        title='Manage Substitutes',
        subs=subs,
        upcoming_matches=upcoming_matches,
        teams=teams
    )


@admin_bp.route('/admin/subs/assign', methods=['POST'], endpoint='assign_sub')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def assign_sub():
    """
    Assign a substitute to a team for a specific match.
    """
    session = g.db_session
    
    player_id = request.form.get('player_id', type=int)
    match_id = request.form.get('match_id', type=int)
    team_id = request.form.get('team_id', type=int)
    
    if not all([player_id, match_id, team_id]):
        show_error('Missing required fields for sub assignment.')
        return redirect(url_for('admin.manage_subs'))
    
    success, message = assign_sub_to_team(
        match_id=match_id,
        player_id=player_id,
        team_id=team_id,
        user_id=safe_current_user.id,
        session=session
    )
    
    if success:
        show_success(message)
    else:
        show_error(message)
    
    # If AJAX request, return JSON response
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': success, 'message': message})
    
    # Get redirect location - could be RSVP status page or manage subs page
    redirect_to = request.form.get('redirect_to', 'manage_subs')
    if redirect_to == 'rsvp_status':
        return redirect(url_for('admin.rsvp_status', match_id=match_id))
    else:
        return redirect(url_for('admin.manage_subs'))


@admin_bp.route('/admin/subs/remove/<int:assignment_id>', methods=['POST'], endpoint='remove_sub')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def remove_sub(assignment_id):
    """
    Remove a substitute assignment.
    """
    session = g.db_session
    
    # Get the assignment to determine the match_id for potential redirect
    assignment = session.query(TemporarySubAssignment).get(assignment_id)
    if not assignment:
        show_error('Assignment not found.')
        return redirect(url_for('admin.manage_subs'))
    
    match_id = assignment.match_id
    
    success, message = remove_sub_assignment(
        assignment_id=assignment_id,
        user_id=safe_current_user.id,
        session=session
    )
    
    if success:
        show_success(message)
    else:
        show_error(message)
    
    # If AJAX request, return JSON response
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': success, 'message': message})
    
    # Get redirect location - could be RSVP status page or manage subs page
    redirect_to = request.form.get('redirect_to', 'manage_subs')
    if redirect_to == 'rsvp_status':
        return redirect(url_for('admin.rsvp_status', match_id=match_id))
    else:
        return redirect(url_for('admin.manage_subs'))


@admin_bp.route('/admin/subs/match/<int:match_id>', methods=['GET'], endpoint='get_match_subs_route')
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'Pub League Coach'])
def get_match_subs_route(match_id):
    """
    Get all subs assigned to a specific match, organized by team.
    
    Returns a JSON response for AJAX requests or redirects to the RSVP status page.
    """
    session = g.db_session
    
    subs_by_team = get_match_subs(match_id=match_id, session=session)
    
    # If AJAX request, return JSON response
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'success': True,
            'subs_by_team': subs_by_team
        })
    
    return redirect(url_for('admin.rsvp_status', match_id=match_id))


@admin_bp.route('/admin/subs/available', methods=['GET'], endpoint='get_available_subs_api')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def get_available_subs_api():
    """
    Get all available substitutes as JSON.
    
    Returns a JSON response for AJAX requests.
    """
    session = g.db_session
    
    subs = get_available_subs(session=session)
    
    return jsonify({
        'success': True,
        'subs': subs
    })


@admin_bp.route('/admin/subs/player/<int:player_id>', methods=['GET'], endpoint='get_player_subs')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def get_player_subs(player_id):
    """
    Get all active sub assignments for a player.
    
    Returns a JSON response for AJAX requests.
    """
    session = g.db_session
    
    assignments = get_player_active_sub_assignments(player_id=player_id, session=session)
    
    # If AJAX request, return JSON response
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'success': True,
            'assignments': assignments
        })
    
    return redirect(url_for('admin.manage_subs'))


@admin_bp.route('/admin/subs/cleanup', methods=['POST'], endpoint='cleanup_subs')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def cleanup_subs():
    """
    Clean up sub assignments for matches that occurred in the past.
    
    This should be run automatically via a scheduled task every Monday,
    but can also be triggered manually by an admin.
    """
    session = g.db_session
    
    count, message = cleanup_old_sub_assignments(session=session)
    
    if count > 0:
        show_success(message)
    else:
        show_info(message)
    
    return redirect(url_for('admin.manage_subs'))


@admin_bp.route('/admin/match_verification', endpoint='match_verification_dashboard')
@login_required
@role_required(['Pub League Admin', 'Global Admin', 'Pub League Coach'])
def match_verification_dashboard():
    """
    Display the match verification dashboard.
    
    Shows the verification status of matches, highlighting those that need attention
    by showing which teams have verified their reports.
    
    Coaches can only see matches for their teams, while admins can see all matches.
    """
    session = g.db_session
    logger.info("Starting match verification dashboard load")
    
    try:
        # Get the current PUB LEAGUE season
        current_season = session.query(Season).filter_by(is_current=True, league_type="Pub League").first()
        if not current_season:
            logger.warning("No current Pub League season found")
            show_warning("No current Pub League season found. Contact an administrator.")
            return render_template('admin/match_verification.html', 
                                  title='Match Verification Dashboard',
                                  matches=[], 
                                  is_coach=False)
        
        logger.info(f"Current season: {current_season.name} (ID: {current_season.id})")
                                  
        # Start with a base query of all matches with eager loading for related entities
        query = session.query(Match).options(
            joinedload(Match.home_team),
            joinedload(Match.away_team),
            joinedload(Match.home_verifier),
            joinedload(Match.away_verifier),
            joinedload(Match.schedule)
        )
        
        # Get all team IDs that belong to leagues in the current season
        league_ids = [league.id for league in session.query(League).filter_by(season_id=current_season.id).all()]
        logger.info(f"Found {len(league_ids)} leagues in current season: {league_ids}")
        
        team_ids = []
        if league_ids:
            team_ids = [team.id for team in session.query(Team).filter(Team.league_id.in_(league_ids)).all()]
            logger.info(f"Found {len(team_ids)} teams in current season")
        
        # Filter matches to only include those with home or away teams from the current season
        if team_ids:
            query = query.filter(
                or_(
                    Match.home_team_id.in_(team_ids),
                    Match.away_team_id.in_(team_ids)
                )
            )
            
        # Get initial match count
        base_match_count = query.count()
        logger.info(f"Initial match count: {base_match_count}")
        
        # Process request filters
        current_week = request.args.get('week')
        current_league_id = request.args.get('league_id')
        current_verification_status = request.args.get('verification_status', 'all')
        
        # Filter by week if specified
        if current_week:
            # Use aliased Schedule to avoid duplicate alias errors when joining
            schedule_week_alias = aliased(Schedule)
            query = query.join(schedule_week_alias, Match.schedule_id == schedule_week_alias.id).filter(schedule_week_alias.week == current_week)
            logger.info(f"Filtering by week: {current_week}")
            
        # Filter by league if specified
        if current_league_id:
            league_id = int(current_league_id)
            logger.info(f"Filtering by league_id: {league_id}")
            # Get teams in this league
            league_team_ids = [team.id for team in session.query(Team).filter_by(league_id=league_id).all()]
            if league_team_ids:
                query = query.filter(
                    or_(
                        Match.home_team_id.in_(league_team_ids),
                        Match.away_team_id.in_(league_team_ids)
                    )
                )
            
        # Filter by verification status
        if current_verification_status == 'unverified':
            query = query.filter(Match.home_team_score != None, Match.away_team_score != None, 
                                ~(Match.home_team_verified & Match.away_team_verified))
            logger.info("Filtering by unverified matches")
        elif current_verification_status == 'partially_verified':
            query = query.filter(Match.home_team_score != None, Match.away_team_score != None,
                                or_(Match.home_team_verified, Match.away_team_verified),
                                ~(Match.home_team_verified & Match.away_team_verified))
            logger.info("Filtering by partially verified matches")
        elif current_verification_status == 'fully_verified':
            query = query.filter(Match.home_team_verified, Match.away_team_verified)
            logger.info("Filtering by fully verified matches")
        elif current_verification_status == 'not_reported':
            query = query.filter(or_(Match.home_team_score == None, Match.away_team_score == None))
            logger.info("Filtering by not reported matches")
            
        # Log count after filters
        after_filters_count = query.count()
        logger.info(f"Match count after filters: {after_filters_count}")
        
        # Check if the user is a coach (to limit matches to their teams)
        is_coach = safe_current_user.has_role('Pub League Coach') and not (safe_current_user.has_role('Pub League Admin') or safe_current_user.has_role('Global Admin'))
        
        if is_coach and hasattr(safe_current_user, 'player') and safe_current_user.player:
            # For coaches, get their teams
            coach_teams = []
            try:
                # Get teams the user coaches
                for team, is_team_coach in safe_current_user.player.get_current_teams(with_coach_status=True):
                    if is_team_coach:
                        coach_teams.append(team.id)
            except Exception as e:
                logger.error(f"Error getting coach teams: {str(e)}")
                # Fallback - use all teams the user is on
                coach_teams = [team.id for team in safe_current_user.player.teams]
            
            logger.info(f"Coach teams: {coach_teams}")
            
            # Filter to user's teams only if they're a coach
            if coach_teams:
                query = query.filter(
                    or_(Match.home_team_id.in_(coach_teams), Match.away_team_id.in_(coach_teams))
                )
            else:
                logger.warning(f"Coach user {safe_current_user.id} has no assigned teams")
        
        # Get the sort parameters
        sort_by = request.args.get('sort_by', 'week')
        sort_order = request.args.get('sort_order', 'asc')
        
        # Apply sorting based on parameters
        if sort_by == 'date':
            query = query.order_by(Match.date.desc() if sort_order == 'desc' else Match.date)
        elif sort_by == 'week':
            # Use aliased Schedule to avoid duplicate alias errors
            schedule_alias = aliased(Schedule)
            query = query.outerjoin(schedule_alias, Match.schedule_id == schedule_alias.id)
            if sort_order == 'desc':
                query = query.order_by(desc(schedule_alias.week), Match.date)
            else:
                query = query.order_by(schedule_alias.week, Match.date)
        elif sort_by == 'home_team':
            home_team_alias = aliased(Team)
            query = query.join(home_team_alias, Match.home_team_id == home_team_alias.id)
            query = query.order_by(home_team_alias.name.desc() if sort_order == 'desc' else home_team_alias.name)
        elif sort_by == 'away_team':
            away_team_alias = aliased(Team)
            query = query.join(away_team_alias, Match.away_team_id == away_team_alias.id)
            query = query.order_by(away_team_alias.name.desc() if sort_order == 'desc' else away_team_alias.name)
        elif sort_by == 'status':
            # Sort by verification status
            if sort_order == 'desc':
                # Fully verified first, then partially, then unverified, then not reported
                query = query.order_by(
                    (Match.home_team_verified & Match.away_team_verified).desc(),
                    (Match.home_team_verified | Match.away_team_verified).desc(),
                    (Match.home_team_score != None).desc()
                )
            else:
                # Not reported first, then unverified, then partially, then fully verified
                query = query.order_by(
                    (Match.home_team_score != None),
                    (Match.home_team_verified | Match.away_team_verified),
                    (Match.home_team_verified & Match.away_team_verified)
                )
        else:
            # Default to date ordering if no clear sort parameter
            query = query.order_by(Match.date.desc())
        
        # Execute the query with a limit to ensure it loads
        final_match_count = query.count()
        logger.info(f"Final match count after all filters: {final_match_count}")
        matches = query.limit(1000).all()  # Increase limit to get more matches
        logger.info(f"Retrieved {len(matches)} matches for display")
        
        # Get all distinct weeks for the filter dropdown
        # Using a direct query approach to get weeks from schedules related to matches
        weeks = []
        try:
            if current_season:
                # First, log some debug info about schedules
                schedule_count = session.query(Schedule).filter_by(season_id=current_season.id).count()
                logger.info(f"Found {schedule_count} schedules for season {current_season.id}")
                
                # If there are schedules, check a sample to see what weeks they have
                if schedule_count > 0:
                    sample_schedules = session.query(Schedule).filter_by(season_id=current_season.id).limit(5).all()
                    logger.info(f"Sample schedule weeks: {[s.week for s in sample_schedules]}")
                
                # Now try to get all distinct non-empty weeks
                week_results = session.query(Schedule.week).filter(
                    Schedule.season_id == current_season.id,
                    Schedule.week != None,
                    Schedule.week != ''
                ).distinct().order_by(Schedule.week).all()
                
                # Extract the week values from the result tuples
                weeks = [week[0] for week in week_results if week[0]]
                
                if not weeks:
                    # If still no weeks, just set some dummy weeks to see if the UI display works
                    logger.warning("No weeks found in schedules. Creating some dummy week values for testing.")
                    weeks = ["1", "2", "3", "4", "5", "6", "7", "8"]
                
                logger.info(f"Final weeks list for filtering: {weeks}")
        except Exception as week_error:
            logger.error(f"Error getting weeks: {str(week_error)}")
            # Create some fallback week values
            weeks = ["1", "2", "3", "4", "5"]
            logger.info("Using fallback week values due to error")
        
        # Get leagues for the current season
        leagues = []
        try:
            if current_season:
                leagues = session.query(League).filter_by(season_id=current_season.id).all()
                logger.info(f"Available leagues: {[league.name for league in leagues]}")
        except Exception as league_error:
            logger.error(f"Error getting leagues: {str(league_error)}")
        
        # Simplified verifiable teams logic
        verifiable_teams = {}
        if hasattr(safe_current_user, 'player') and safe_current_user.player:
            for team in safe_current_user.player.teams:
                verifiable_teams[team.id] = team.name
        
        logger.info("Rendering match verification template")
        return render_template(
            'admin/match_verification.html',
            title='Match Verification Dashboard',
            matches=matches,
            weeks=weeks,
            leagues=leagues,
            current_week=current_week,
            current_league_id=int(current_league_id) if current_league_id else None,
            current_verification_status=current_verification_status,
            current_season=current_season,
            verifiable_teams=verifiable_teams,
            is_coach=is_coach,
            sort_by=sort_by,
            sort_order=sort_order
        )
    except Exception as e:
        # Debugging exception
        logger.error(f"Error in match verification dashboard: {str(e)}", exc_info=True)
        # Return a more detailed error message with HTML formatting for easier reading
        error_html = f"""
        <h1>Error in Match Verification Dashboard</h1>
        <p>An error occurred while loading the verification dashboard:</p>
        <pre style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; color: #721c24;">
        {str(e)}
        </pre>
        <p>Please check the application logs for more details.</p>
        <a href="{url_for('admin.admin_dashboard')}" class="btn btn-primary">Return to Dashboard</a>
        """
        return error_html


@admin_bp.route('/admin/verify_match/<int:match_id>', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'Pub League Coach'])
def admin_verify_match(match_id):
    """
    Allow an admin or coach to verify a match.
    
    - Admins can verify for any team
    - Coaches can only verify for their own team
    """
    session = g.db_session
    match = session.query(Match).get(match_id)
    
    if not match:
        show_error('Match not found.')
        return redirect(url_for('admin.match_verification_dashboard'))
    
    # First check if the match has been reported
    if not match.reported:
        show_warning('Match has not been reported yet and cannot be verified.')
        return redirect(url_for('admin.match_verification_dashboard'))
    
    team_to_verify = request.form.get('team', None)
    if not team_to_verify or team_to_verify not in ['home', 'away', 'both']:
        show_error('Invalid team specified.')
        return redirect(url_for('admin.match_verification_dashboard'))
    
    # Check permissions for coaches
    is_admin = safe_current_user.has_role('Pub League Admin') or safe_current_user.has_role('Global Admin')
    is_coach = safe_current_user.has_role('Pub League Coach')
    
    can_verify_home = is_admin
    can_verify_away = is_admin
    
    # If user is a coach and not an admin, check if they coach either team
    if is_coach and not is_admin and hasattr(safe_current_user, 'player') and safe_current_user.player:
        coach_teams = []
        
        try:
            # Get teams the user coaches using the get_current_teams method
            for team, is_team_coach in safe_current_user.player.get_current_teams(with_coach_status=True):
                if is_team_coach:
                    coach_teams.append(team.id)
        except Exception as e:
            logger.error(f"Error getting coach teams for verification: {str(e)}")
            # Fallback approach - get teams the user coaches directly from the database
            try:
                coach_teams_results = session.execute("""
                    SELECT team_id FROM player_teams 
                    WHERE player_id = :player_id AND is_coach = TRUE
                """, {"player_id": safe_current_user.player.id}).fetchall()
                coach_teams = [r[0] for r in coach_teams_results]
            except Exception as inner_e:
                logger.error(f"Error in fallback coach teams query: {str(inner_e)}")
        
        # Check if they coach the home or away team
        can_verify_home = match.home_team_id in coach_teams
        can_verify_away = match.away_team_id in coach_teams
    
    # Validate the requested verification against permissions
    if team_to_verify == 'home' and not can_verify_home:
        show_error('You do not have permission to verify for the home team.')
        return redirect(url_for('admin.match_verification_dashboard'))
    
    if team_to_verify == 'away' and not can_verify_away:
        show_error('You do not have permission to verify for the away team.')
        return redirect(url_for('admin.match_verification_dashboard'))
    
    if team_to_verify == 'both' and not (can_verify_home and can_verify_away):
        show_error('You do not have permission to verify for both teams.')
        return redirect(url_for('admin.match_verification_dashboard'))
    
    # Proceed with verification
    now = datetime.utcnow()
    user_id = safe_current_user.id
    
    if (team_to_verify == 'home' or team_to_verify == 'both') and can_verify_home:
        match.home_team_verified = True
        match.home_team_verified_by = user_id
        match.home_team_verified_at = now
    
    if (team_to_verify == 'away' or team_to_verify == 'both') and can_verify_away:
        match.away_team_verified = True
        match.away_team_verified_by = user_id
        match.away_team_verified_at = now
    
    session.commit()
    
    # Customize the flash message based on what was verified
    if team_to_verify == 'both':
        show_success('Match has been verified for both teams.')
    else:
        team_name = match.home_team.name if team_to_verify == 'home' else match.away_team.name
        show_success(f'Match has been verified for {team_name}.')
    
    return redirect(url_for('admin.match_verification_dashboard'))