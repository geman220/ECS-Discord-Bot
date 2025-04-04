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
    Blueprint, render_template, redirect, url_for, flash,
    request, jsonify, abort, g, current_app
)
from sqlalchemy import func
from flask_login import login_required
from sqlalchemy.orm import joinedload

from app.admin_helpers import (
    get_filtered_users, handle_user_action, get_container_data,
    manage_docker_container, get_container_logs, send_sms_message,
    handle_announcement_update, get_role_permissions_data,
    get_rsvp_status_data, handle_permissions_update
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
    Player, Availability, User
)
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
                flash('Error processing user action.', 'danger')
            return redirect(url_for('admin.admin_dashboard'))

        # Handle announcement creation/update
        elif action == 'create_announcement':
            title = request.form.get('title')
            content = request.form.get('content')
            success = handle_announcement_update(title=title, content=content, session=session)
            if not success:
                flash('Error creating announcement.', 'danger')
            return redirect(url_for('admin.admin_dashboard'))

        # Handle permissions update
        elif action == 'update_permissions':
            role_id = request.form.get('role_id')
            permissions = request.form.getlist('permissions')
            success = handle_permissions_update(role_id, permissions)
            if not success:
                flash('Error updating permissions.', 'danger')
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
        flash("Failed to manage container.", "danger")
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
        flash("Phone number and message body are required.", "danger")
        return redirect(url_for('admin.admin_dashboard'))

    success = send_sms_message(to_phone, message)
    if not success:
        flash("Failed to send SMS.", "danger")
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
        flash("Announcement created successfully.", "success")
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
            flash('Title and content are required.', 'danger')
            return redirect(url_for('admin.admin_dashboard'))

    announcement = session.query(Announcement).get(announcement_id)
    if not announcement:
        if request.method == 'PUT':
            return jsonify({'error': 'Announcement not found.'}), 404
        else:
            flash('Announcement not found.', 'danger')
            return redirect(url_for('admin.admin_dashboard'))

    announcement.title = title
    announcement.content = content
    session.commit()
    
    if request.method == 'PUT':
        return jsonify({'success': True})
    else:
        flash('Announcement updated successfully.', 'success')
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
            flash('Announcement not found.', 'danger')
            return redirect(url_for('admin.admin_dashboard'))

    session.delete(announcement)
    session.commit()
    
    if request.method == 'DELETE':
        return jsonify({'success': True})
    else:
        flash('Announcement deleted successfully.', 'success')
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
@role_required('Global Admin')
def schedule_season():
    """
    Initiate the task to schedule season availability.
    """
    task = schedule_season_availability.delay()
    flash('Season scheduling task has been initiated.', 'success')
    return redirect(url_for('admin.view_scheduled_messages'))


@admin_bp.route('/admin/scheduled_messages', endpoint='view_scheduled_messages')
@login_required
@role_required('Global Admin')
def view_scheduled_messages():
    """
    View a list of scheduled messages.
    """
    session = g.db_session
    messages = session.query(ScheduledMessage).order_by(ScheduledMessage.scheduled_send_time).all()
    return render_template('admin/scheduled_messages.html', title='Discord Scheduled Messages', messages=messages)


@admin_bp.route('/admin/force_send/<int:message_id>', endpoint='force_send_message', methods=['POST'])
@login_required
@role_required('Global Admin')
def force_send_message(message_id):
    """
    Force-send a scheduled message immediately.
    """
    session = g.db_session
    message = session.query(ScheduledMessage).get(message_id)
    if not message:
        abort(404)

    try:
        send_availability_message_task.delay(scheduled_message_id=message.id)
        message.status = 'QUEUED'
        flash('Message is being sent.', 'success')
    except Exception as e:
        logger.error(f"Error queuing message {message_id}: {str(e)}")
        flash('Error queuing message for sending.', 'danger')

    return redirect(url_for('admin.view_scheduled_messages'))


@admin_bp.route('/admin/schedule_next_week', endpoint='schedule_next_week', methods=['POST'])
@login_required
@role_required('Global Admin')
def schedule_next_week():
    """
    Initiate the scheduling task specifically for the next week's Sunday matches.
    Schedules RSVP messages to be sent on Monday mornings.
    """
    from app.tasks.tasks_rsvp import schedule_weekly_match_availability
    
    task = schedule_weekly_match_availability.delay()
    flash('Next week\'s Sunday matches scheduling task has been initiated.', 'success')
    return redirect(url_for('admin.view_scheduled_messages'))


# -----------------------------------------------------------
# RSVP Status and Reports
# -----------------------------------------------------------

@admin_bp.route('/admin/rsvp_status/<int:match_id>', endpoint='rsvp_status')
@login_required
@role_required('Global Admin')
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
@role_required('Global Admin')
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
        flash('Phone number and message are required.', 'danger')
        if match_id:
            return redirect(url_for('admin.rsvp_status', match_id=match_id))
        return redirect(url_for('admin.admin_dashboard'))
    
    player = session.query(Player).get(player_id)
    if not player:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Player not found'}), 404
        flash('Player not found.', 'danger')
        if match_id:
            return redirect(url_for('admin.rsvp_status', match_id=match_id))
        return redirect(url_for('admin.admin_dashboard'))
    
    # Check if user has SMS notifications enabled
    user = player.user
    if not user or not user.sms_notifications:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'SMS notifications are disabled for this user'}), 403
        flash('SMS notifications are disabled for this user.', 'danger')
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
        flash('SMS sent successfully.', 'success')
    else:
        logger.error(f"Failed to send SMS to player {player_id}: {result}")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': f'Failed to send SMS: {result}'})
        flash(f'Failed to send SMS: {result}', 'danger')
    
    if match_id:
        return redirect(url_for('admin.rsvp_status', match_id=match_id))
    return redirect(url_for('admin.admin_dashboard'))


@admin_bp.route('/admin/send_discord_dm', methods=['POST'], endpoint='send_discord_dm')
@login_required
@role_required('Global Admin')
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
        flash('Player ID and message are required.', 'danger')
        if match_id:
            return redirect(url_for('admin.rsvp_status', match_id=match_id))
        return redirect(url_for('admin.admin_dashboard'))
    
    player = session.query(Player).get(player_id)
    if not player or not player.discord_id:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Player not found or no Discord ID'}), 404
        flash('Player not found or has no Discord ID.', 'danger')
        if match_id:
            return redirect(url_for('admin.rsvp_status', match_id=match_id))
        return redirect(url_for('admin.admin_dashboard'))
    
    # Check if user has Discord notifications enabled
    user = player.user
    if not user or not user.discord_notifications:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Discord notifications are disabled for this user'}), 403
        flash('Discord notifications are disabled for this user.', 'danger')
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
            flash('Discord DM sent successfully.', 'success')
        else:
            logger.error(f"Failed to send Discord DM to player {player_id}: {response.text}")
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': 'Failed to send Discord DM'})
            flash('Failed to send Discord DM.', 'danger')
    except Exception as e:
        logger.error(f"Error contacting Discord bot: {str(e)}")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': f'Error contacting Discord bot: {str(e)}'})
        flash(f'Error contacting Discord bot: {str(e)}', 'danger')
    
    if match_id:
        return redirect(url_for('admin.rsvp_status', match_id=match_id))
    return redirect(url_for('admin.admin_dashboard'))


@admin_bp.route('/admin/update_rsvp', methods=['POST'], endpoint='update_rsvp')
@login_required
@role_required('Global Admin')
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
        flash('Player ID, match ID, and response are required.', 'danger')
        return redirect(url_for('admin.rsvp_status', match_id=match_id))
    
    # Check if the player and match exist
    player = session.query(Player).get(player_id)
    match = session.query(Match).get(match_id)
    if not player or not match:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Player or match not found'}), 404
        flash('Player or match not found.', 'danger')
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
                flash('RSVP cleared successfully.', 'success')
            else:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'success': True, 'message': 'No RSVP found to clear'})
                flash('No RSVP found to clear.', 'info')
        except Exception as e:
            logger.error(f"Error clearing RSVP: {str(e)}")
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': f'Error clearing RSVP: {str(e)}'})
            flash(f'Error clearing RSVP: {str(e)}', 'danger')
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
                availability = Availability(
                    match_id=match_id,
                    player_id=player_id,
                    response=response,
                    discord_id=player.discord_id,
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
            flash('RSVP updated successfully.', 'success')
        except Exception as e:
            logger.error(f"Error updating RSVP: {str(e)}")
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': f'Error updating RSVP: {str(e)}'})
            flash(f'Error updating RSVP: {str(e)}', 'danger')
    
    return redirect(url_for('admin.rsvp_status', match_id=match_id))


@admin_bp.route('/admin/reports', endpoint='admin_reports')
@login_required
@role_required('Global Admin')
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
@role_required('Global Admin')
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
            flash('Feedback has been updated successfully.', 'success')

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
            flash('Your reply has been added successfully.', 'success')
            return redirect(url_for('admin.view_feedback', feedback_id=feedback.id))

        elif 'add_note' in request.form and note_form.validate():
            note = Note(
                content=note_form.content.data,
                feedback_id=feedback.id,
                author_id=safe_current_user.id
            )
            session.add(note)
            flash('Note added successfully.', 'success')
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
@role_required('Global Admin')
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

    flash('Feedback has been closed successfully.', 'success')
    return redirect(url_for('admin.view_feedback', feedback_id=feedback.id))


@admin_bp.route('/admin/feedback/<int:feedback_id>/delete', endpoint='delete_feedback', methods=['POST'])
@login_required
@role_required('Global Admin')
def delete_feedback(feedback_id):
    """
    Permanently delete a feedback entry.
    """
    session = g.db_session
    feedback = session.query(Feedback).get(feedback_id)
    if not feedback:
        abort(404)
    session.delete(feedback)
    flash('Feedback has been permanently deleted.', 'success')
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