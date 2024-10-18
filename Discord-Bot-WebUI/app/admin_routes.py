# app/admin_routes.py

import aiohttp
import asyncio
from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    flash,
    request,
    current_app,
    jsonify
)
from flask_login import login_required, current_user
from flask_paginate import Pagination, get_page_parameter
from functools import wraps
from sqlalchemy import or_
from sqlalchemy.orm import joinedload
from datetime import datetime, timedelta
from twilio.rest import Client
from app.decorators import role_required
from app.email import send_email
from app.models import (
    Team,
    Match,
    Availability,
    Player,
    Announcement,
    Role,
    Permission,
    User,
    Feedback,
    Feedback, 
    Note,
    League,
    ScheduledMessage,
    FeedbackReply,
    MLSMatch
)
from app.forms import AnnouncementForm, EditUserForm, ResetPasswordForm, AdminFeedbackForm, NoteForm, FeedbackReplyForm
from app.discord_utils import process_role_updates, get_expected_roles, update_player_roles, create_match_thread
from app.tasks import schedule_season_availability, send_availability_message, create_scheduled_mls_match_threads, create_mls_match_thread
from app import db
import pytz
import docker
import logging
import requests

# Initialize logger
logger = logging.getLogger(__name__)

# Initialize Blueprint
admin_bp = Blueprint('admin', __name__, template_folder='templates')

# --------------------
# Helper Functions
# --------------------

def async_action(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(f(*args, **kwargs))
        finally:
            loop.close()
    return wrapped

def create_status_html(player_data):
    current_roles = set(player_data['current_roles'])
    expected_roles = set(player_data['expected_roles'])

    if not current_roles:
        status = "Not Found"
        status_class = "bg-danger"
    elif expected_roles.issubset(current_roles):
        status = "Synced"
        status_class = "bg-success"
    else:
        status = "Check Roles"
        status_class = "bg-warning"

    return f'<span class="badge {status_class}">{status}</span>'

def get_docker_client():
    """Initialize and return the Docker client."""
    try:
        return docker.from_env()
    except Exception as e:
        logger.error(f"Error initializing Docker client: {e}")
        return None

def fetch_container_data():
    """Fetch and format Docker container data."""
    client = get_docker_client()
    if not client:
        return []
    containers = client.containers.list(all=True)
    container_data = []
    for container in containers:
        friendly_name = container.name  # Full container name
        container_data.append({
            'id': container.id[:12],  # Shorten ID for display
            'name': friendly_name,
            'status': container.status,
            'image': container.image.tags[0] if container.image.tags else 'Unknown'
        })
    return container_data

# --------------------
# Main Admin Dashboard Route
# --------------------

@admin_bp.route('/admin/dashboard', methods=['GET', 'POST'])
@login_required
@role_required('Global Admin')
def admin_dashboard():
    """
    Render the main admin dashboard with user management, roles, announcements,
    scheduling tasks, sending SMS, and Docker container monitoring.
    """
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'approve' or action == 'remove' or action == 'reset_password':
            user_id = request.form.get('user_id')
            user = User.query.get(user_id)

            if not user:
                flash('User not found.', 'danger')
                return redirect(url_for('admin.admin_dashboard'))

            try:
                if action == 'approve':
                    user.is_approved = True
                    db.session.commit()
                    flash(f'User {user.username} approved successfully.', 'success')
                elif action == 'remove':
                    db.session.delete(user)
                    db.session.commit()
                    flash(f'User {user.username} removed successfully.', 'success')
                elif action == 'reset_password':
                    flash(f'Password reset for {user.username} is not yet implemented.', 'warning')
            except Exception as e:
                db.session.rollback()
                flash(f"Error processing {action} for user: {str(e)}", 'danger')

        elif action == 'create_announcement':
            title = request.form.get('title')
            content = request.form.get('content')
            new_announcement = Announcement(title=title, content=content)

            try:
                db.session.add(new_announcement)
                db.session.commit()
                flash('Announcement created successfully!', 'success')
            except Exception as e:
                db.session.rollback()
                flash(f"Error creating announcement: {str(e)}", 'danger')

        elif action == 'update_permissions':
            role_id = request.form.get('role_id')
            selected_permissions = request.form.getlist('permissions')

            role = Role.query.get(role_id)
            if not role:
                flash('Role not found.', 'danger')
                return redirect(url_for('admin.admin_dashboard'))

            try:
                role.permissions = Permission.query.filter(Permission.id.in_(selected_permissions)).all()
                db.session.commit()
                flash(f"Permissions updated for role '{role.name}'.", 'success')
            except Exception as e:
                db.session.rollback()
                flash(f"Error updating permissions for role '{role.name}': {str(e)}", 'danger')

        else:
            flash('Invalid action.', 'danger')

        return redirect(url_for('admin.admin_dashboard'))

    # --------------------
    # Pagination and Filtering for Users
    # --------------------
    
    page = request.args.get('page', 1, type=int)
    per_page = 10

    search = request.args.get('search', '', type=str)
    role = request.args.get('role', '', type=str)
    league = request.args.get('league', '', type=str)
    active = request.args.get('active', '', type=str)
    approved = request.args.get('approved', '', type=str)

    query = User.query.options(db.joinedload(User.league))

    if search:
        query = query.filter(
            or_(
                User.username.ilike(f'%{search}%'),
                User.email.ilike(f'%{search}%')
            )
        )
    if role:
        query = query.join(User.roles).filter(Role.name == role)
    if league:
        if league == 'none':
            query = query.filter(User.league_id.is_(None))
        else:
            query = query.filter(User.league_id == league)
    if active:
        is_active = active.lower() == 'true'
        query = query.filter(User.is_active == is_active)
    if approved:
        is_approved = approved.lower() == 'true'
        query = query.filter(User.is_approved == is_approved)
    
    # Use paginate to handle pagination
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    users = pagination.items  # Get the users for the current page

    roles = Role.query.all()
    permissions = Permission.query.all()
    leagues = League.query.all()

    announcements = Announcement.query.order_by(Announcement.created_at.desc()).all()
    teams = Team.query.all()

    edit_form = EditUserForm()
    reset_password_form = ResetPasswordForm()
    announcement_form = AnnouncementForm()

    return render_template(
        'admin_dashboard.html',
        users=users,
        pagination=pagination,  # Pass pagination to template
        roles=roles,
        permissions=permissions,
        leagues=leagues,
        announcements=announcements,
        teams=teams,
        edit_form=edit_form,
        reset_password_form=reset_password_form,
        announcement_form=announcement_form
    )

# --------------------
# Docker Container Management Routes
# --------------------

@admin_bp.route('/admin/container/<container_id>/<action>', methods=['POST'])
@login_required
@role_required('Global Admin')
def manage_container(container_id, action):
    """
    Manage Docker containers by performing actions: start, stop, restart.
    """
    client = get_docker_client()
    if not client:
        flash("Docker client initialization failed.", "danger")
        return redirect(url_for('admin.admin_dashboard'))
    
    try:
        container = client.containers.get(container_id)
        
        if action == 'start':
            container.start()
            flash(f"Container {container.name} started successfully.", "success")
        elif action == 'stop':
            container.stop()
            flash(f"Container {container.name} stopped successfully.", "success")
        elif action == 'restart':
            container.restart()
            flash(f"Container {container.name} restarted successfully.", "success")
        else:
            flash(f"Invalid action: {action}", "danger")
            return redirect(url_for('admin.admin_dashboard'))
    except docker.errors.NotFound:
        flash(f"Container {container_id} not found.", "danger")
    except Exception as e:
        logger.error(f"Failed to {action} container {container_id}: {e}")
        flash(f"Failed to {action} container: {e}", "danger")
    
    return redirect(url_for('admin.admin_dashboard'))

@admin_bp.route('/admin/view_logs/<container_id>', methods=['GET'])
@login_required
@role_required('Global Admin')
def view_logs(container_id):
    """
    Retrieve and return logs of a specific Docker container.
    """
    client = get_docker_client()
    if not client:
        return jsonify({"error": "Docker client initialization failed."}), 500
    
    try:
        container = client.containers.get(container_id)
        logs = container.logs().decode('utf-8')
        return jsonify({"logs": logs})
    except docker.errors.NotFound:
        return jsonify({"error": "Container not found."}), 404
    except Exception as e:
        logger.error(f"Failed to retrieve logs for container {container_id}: {e}")
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/admin/docker_status', methods=['GET'])
@login_required
@role_required('Global Admin')
def docker_status():
    """
    Return the status of all Docker containers.
    """
    try:
        containers = fetch_container_data()
        return jsonify(containers)
    except Exception as e:
        logger.error(f"Error fetching Docker status: {e}")
        return jsonify({"error": str(e)}), 500

# --------------------
# Send SMS via Twilio
# --------------------

@admin_bp.route('/admin/send_sms', methods=['POST'])
@login_required
@role_required('Global Admin')
def send_sms():
    """
    Send an SMS message using Twilio.
    """
    try:
        # Get data from the form
        to_phone_number = request.form.get('to_phone_number')
        message_body = request.form.get('message_body')

        if not to_phone_number or not message_body:
            flash("Phone number and message body are required.", "danger")
            return redirect(url_for('admin.admin_dashboard'))

        # Initialize the Twilio client with the correct credentials
        client = Client(
            current_app.config.get('TWILIO_ACCOUNT_SID'),
            current_app.config.get('TWILIO_AUTH_TOKEN')
        )

        # Send the SMS
        message = client.messages.create(
            body=message_body,
            from_=current_app.config.get('TWILIO_PHONE_NUMBER'),
            to=to_phone_number
        )

        logger.info(f"SMS sent successfully: {message.sid}")

        flash(f"SMS sent successfully. SID: {message.sid}", "success")
        return redirect(url_for('admin.admin_dashboard'))

    except Exception as e:
        logger.error(f"Failed to send SMS: {e}")
        flash(f"Failed to send SMS: {e}", "danger")
        return redirect(url_for('admin.admin_dashboard'))

# --------------------
# Manage Roles and Permissions
# --------------------

@admin_bp.route('/admin/get_role_permissions', methods=['GET'])
@login_required
@role_required('Global Admin')
def get_role_permissions():
    """
    Fetch permissions associated with a specific role.
    """
    role_id = request.args.get('role_id')
    role = Role.query.get(role_id)
    if role:
        permissions = [perm.id for perm in role.permissions]
        return jsonify({'permissions': permissions})
    return jsonify({'error': 'Role not found.'}), 404

# --------------------
# Manage Announcements
# --------------------

@admin_bp.route('/admin/announcements', methods=['GET', 'POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def manage_announcements():
    form = AnnouncementForm()
    if form.validate_on_submit():
        max_position = db.session.query(db.func.max(Announcement.position)).scalar() or 0
        new_announcement = Announcement(
            title=form.title.data,
            content=form.content.data,
            position=max_position + 1
        )
        try:
            db.session.add(new_announcement)
            db.session.commit()
            flash('Announcement created successfully.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f"Error creating announcement: {str(e)}", 'danger')
        return redirect(url_for('admin.manage_announcements'))

    announcements = Announcement.query.order_by(Announcement.position).all()
    return render_template('admin_dashboard.html', announcements=announcements, announcement_form=form)

@admin_bp.route('/admin/announcements/<int:announcement_id>/edit', methods=['PUT'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def edit_announcement(announcement_id):
    announcement = Announcement.query.get_or_404(announcement_id)
    data = request.get_json()

    if not data:
        return jsonify({'error': 'No data provided.'}), 400

    title = data.get('title')
    content = data.get('content')

    if not title or not content:
        return jsonify({'error': 'Title and content are required.'}), 400

    try:
        announcement.title = title
        announcement.content = content
        db.session.commit()
        flash('Announcement updated successfully.', 'success')
        return jsonify({'success': True}), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating announcement {announcement_id}: {e}")
        return jsonify({'error': 'Failed to update announcement.'}), 500

@admin_bp.route('/admin/announcements/<int:announcement_id>/delete', methods=['DELETE'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def delete_announcement(announcement_id):
    announcement = Announcement.query.get_or_404(announcement_id)
    try:
        db.session.delete(announcement)
        db.session.commit()
        flash('Announcement deleted successfully.', 'success')
        return jsonify({'success': True}), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting announcement {announcement_id}: {e}")
        return jsonify({'error': 'Failed to delete announcement.'}), 500

@admin_bp.route('/admin/announcements/reorder', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def reorder_announcements():
    order = request.json.get('order', [])

    if not order:
        return jsonify({'error': 'No order data provided.'}), 400

    try:
        for item in order:
            announcement = Announcement.query.get(item['id'])
            if announcement:
                announcement.position = item['position']
        db.session.commit()
        flash('Announcements reordered successfully.', 'success')
        return jsonify({'success': True}), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error reordering announcements: {e}")
        return jsonify({'error': 'Failed to reorder announcements.'}), 500

# --------------------
# Schedule Availability
# --------------------

@admin_bp.route('/admin/schedule_season', methods=['POST'])
@login_required
@role_required('Global Admin')
def schedule_season():
    task = schedule_season_availability.delay()
    flash('Season scheduling task has been initiated.', 'success')
    return redirect(url_for('admin.view_scheduled_messages'))

@admin_bp.route('/admin/scheduled_messages')
@login_required
@role_required('Global Admin')
def view_scheduled_messages():
    messages = ScheduledMessage.query.order_by(ScheduledMessage.scheduled_send_time).all()
    return render_template('admin/scheduled_messages.html', messages=messages)

@admin_bp.route('/admin/force_send/<int:message_id>', methods=['POST'])
@login_required
@role_required('Global Admin')
def force_send_message(message_id):
    message = ScheduledMessage.query.get_or_404(message_id)
    task = send_availability_message.delay(message.id)
    flash('Message sending has been initiated.', 'success')
    return redirect(url_for('admin.view_scheduled_messages'))

@admin_bp.route('/admin/rsvp_status/<int:match_id>')
@login_required
@role_required('Global Admin')
def rsvp_status(match_id):
    match = Match.query.get_or_404(match_id)
    
    # Get all players from both teams with their availability for this match
    players_with_availability = db.session.query(Player, Availability).\
        outerjoin(Availability, (Player.id == Availability.player_id) & (Availability.match_id == match_id)).\
        filter((Player.team_id == match.home_team_id) | (Player.team_id == match.away_team_id)).\
        options(joinedload(Player.team)).\
        all()

    rsvp_data = []
    for player, availability in players_with_availability:
        rsvp_data.append({
            'player': player,
            'team': player.team,
            'response': availability.response if availability else 'No Response',
            'responded_at': availability.responded_at if availability else None
        })

    # Sort the data by team name and then by player name
    rsvp_data.sort(key=lambda x: (x['team'].name, x['player'].name))

    return render_template('admin/rsvp_status.html', match=match, rsvps=rsvp_data)

@admin_bp.route('/admin/schedule_next_week', methods=['POST'])
@login_required
@role_required('Global Admin')
def schedule_next_week():
    task = schedule_season_availability.delay()
    flash('Next week scheduling task has been initiated.', 'success')
    return redirect(url_for('admin.view_scheduled_messages'))

# --------------------
# Additional Routes
# --------------------

@admin_bp.route('/admin/celery_tasks', methods=['GET'])
@login_required
@role_required('Global Admin')
def celery_tasks():
    """
    Fetch and return Celery tasks from Flower's API.
    """
    try:
        # Replace 'http://flower:5555' with your Flower server URL
        response = requests.get('http://flower:5555/api/tasks')
        response.raise_for_status()
        tasks = response.json()

        formatted_tasks = []
        for task in tasks:
            formatted_tasks.append({
                'id': task.get('uuid', 'N/A'),
                'name': task.get('name', 'N/A'),
                'state': task.get('state', 'N/A'),
                'received': task.get('received', 'N/A'),
                'started': task.get('started', 'N/A'),
                'succeeded': task.get('succeeded', 'N/A'),
                'failed': task.get('failed', 'N/A'),
            })

        return jsonify(formatted_tasks), 200

    except requests.RequestException as e:
        logger.error(f"Error fetching tasks from Flower: {e}")
        return jsonify({'error': str(e)}), 500

@admin_bp.route('/admin/get_announcement_data', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def get_announcement_data():
    """
    Retrieve announcement data based on announcement_id.
    """
    announcement_id = request.args.get('announcement_id')
    if not announcement_id:
        return jsonify({'error': 'No announcement_id provided.'}), 400
    try:
        announcement_id = int(announcement_id)
    except ValueError:
        return jsonify({'error': 'Invalid announcement_id.'}), 400

    announcement = Announcement.query.get(announcement_id)
    if not announcement:
        return jsonify({'error': 'Announcement not found.'}), 404

    return jsonify({
        'id': announcement.id,
        'title': announcement.title,
        'content': announcement.content
    }), 200


# --------------------
# Feedback Routes
# --------------------

@admin_bp.route('/admin/reports')
@login_required
@role_required('Global Admin')
def admin_reports():
    page = request.args.get('page', 1, type=int)
    per_page = 20  # Number of feedbacks per page
    status_filter = request.args.get('status', '')
    priority_filter = request.args.get('priority', '')
    sort_by = request.args.get('sort_by', 'created_at')
    order = request.args.get('order', 'desc')

    query = Feedback.query

    if status_filter:
        query = query.filter(Feedback.status == status_filter)
    if priority_filter:
        query = query.filter(Feedback.priority == priority_filter)

    if order == 'asc':
        query = query.order_by(getattr(Feedback, sort_by).asc())
    else:
        query = query.order_by(getattr(Feedback, sort_by).desc())

    feedbacks = query.paginate(page=page, per_page=per_page, error_out=False)

    return render_template('admin_reports.html', feedbacks=feedbacks)

@admin_bp.route('/admin/feedback/<int:feedback_id>', methods=['GET', 'POST'])
@login_required
@role_required('Global Admin')
def view_feedback(feedback_id):
    feedback = Feedback.query.get_or_404(feedback_id)
    form = AdminFeedbackForm(obj=feedback)
    reply_form = FeedbackReplyForm()
    note_form = NoteForm()

    if request.method == 'POST':
        try:
            if 'update_feedback' in request.form and form.validate():
                form.populate_obj(feedback)
                db.session.commit()
                flash('Feedback has been updated successfully.', 'success')

            elif 'submit_reply' in request.form and reply_form.validate():
                reply = FeedbackReply(
                    feedback_id=feedback.id,
                    user_id=current_user.id,
                    content=reply_form.content.data,
                    is_admin_reply=True
                )
                db.session.add(reply)
                db.session.commit()

                if feedback.user:
                    send_email(
                        to=feedback.user.email,
                        subject=f"New admin reply to your Feedback #{feedback.id}",
                        body=render_template('emails/new_reply_admin.html', feedback=feedback, reply=reply)
                    )
                flash('Your reply has been added successfully.', 'success')

            elif 'add_note' in request.form and note_form.validate():
                note = Note(
                    content=note_form.content.data,
                    feedback_id=feedback.id,
                    author_id=current_user.id
                )
                db.session.add(note)
                db.session.commit()
                flash('Note added successfully.', 'success')

        except Exception as e:
            db.session.rollback()
            flash(f"Error processing feedback update: {str(e)}", 'danger')

    return render_template('admin_report_detail.html',
                           feedback=feedback,
                           form=form,
                           reply_form=reply_form,
                           note_form=note_form)

@admin_bp.route('/admin/feedback/<int:feedback_id>/close', methods=['POST'])
@login_required
@role_required('Global Admin')
def close_feedback(feedback_id):
    feedback = Feedback.query.get_or_404(feedback_id)
    try:
        feedback.status = 'Closed'
        feedback.closed_at = datetime.utcnow()
        db.session.commit()

        send_email(
            to=feedback.user.email,
            subject=f"Your Feedback #{feedback.id} has been closed",
            body=render_template('emails/feedback_closed.html', feedback=feedback)
        )
        flash('Feedback has been closed successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f"Error closing feedback: {str(e)}", 'danger')

    return redirect(url_for('admin.view_feedback', feedback_id=feedback.id))

@admin_bp.route('/admin/feedback/<int:feedback_id>/delete', methods=['POST'])
@login_required
@role_required('Global Admin')
def delete_feedback(feedback_id):
    feedback = Feedback.query.get_or_404(feedback_id)
    try:
        db.session.delete(feedback)
        db.session.commit()
        flash('Feedback has been permanently deleted.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting feedback: {str(e)}", 'danger')

    return redirect(url_for('admin.admin_reports'))

# --------------------
# Discord Routes
# --------------------

@admin_bp.route('/admin/discord_role_status', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def discord_role_status():
    players = Player.query.filter(Player.discord_id.isnot(None)).all()
    
    player_data = []
    for player in players:
        logger.debug(f"Processing player: {player.name}, discord_roles: {player.discord_roles}")
        
        # Convert discord_roles to a flat list if it's stored as a nested list
        current_roles = []
        if player.discord_roles:
            if isinstance(player.discord_roles, list):
                # Flatten the list if it's nested
                current_roles = [item for sublist in player.discord_roles if isinstance(sublist, list) for item in sublist]
                # Add any string items that might be at the top level
                current_roles.extend([item for item in player.discord_roles if isinstance(item, str)])
            elif isinstance(player.discord_roles, str):
                # If it's a string, split it (assuming it's comma-separated)
                current_roles = [role.strip() for role in player.discord_roles.split(',')]
        
        expected_roles = get_expected_roles(player)
        
        player_info = {
            'id': player.id,
            'name': player.name,
            'discord_id': player.discord_id,
            'team': player.team.name if player.team else 'No Team',
            'league': player.team.league.name if player.team and player.team.league else 'No League',
            'current_roles': current_roles,
            'expected_roles': expected_roles,
            'last_verified': player.discord_last_verified,
            'status_html': create_status_html({
                'current_roles': current_roles,
                'expected_roles': expected_roles
            })
        }
        player_data.append(player_info)
        logger.debug(f"Processed player data: {player_info}")
    
    return render_template('discord_role_status.html', players=player_data)

@admin_bp.route('/admin/update_player_roles/<int:player_id>', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
@async_action
async def update_player_roles_route(player_id):
    player = Player.query.get(player_id)
    if not player:
        return jsonify({'success': False, 'error': 'Player not found'})
    
    async with aiohttp.ClientSession() as session:
        success = await update_player_roles(player, session, force_update=True)
    
    if success:
        player_data = {
            'id': player.id,
            'current_roles': player.discord_roles or [],
            'expected_roles': get_expected_roles(player),
            'status_html': create_status_html({
                'current_roles': player.discord_roles or [],
                'expected_roles': get_expected_roles(player)
            })
        }
        return jsonify({'success': True, 'player_data': player_data})
    else:
        return jsonify({'success': False, 'error': 'Failed to update player roles'})

@admin_bp.route('/admin/update_discord_roles', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
@async_action
async def update_discord_roles():
    success = await process_role_updates(force_update=True)
    return jsonify({'success': success, 'status': 'Role update process completed'})

# --------------------
# MLS Schedule Routes
# --------------------

@admin_bp.route('/admin/mls_matches')
@login_required
@role_required('Global Admin')
def view_mls_matches():
    matches = MLSMatch.query.order_by(MLSMatch.date_time).all()
    return render_template('admin/mls_matches.html', matches=matches)

@admin_bp.route('/admin/schedule_mls_match_thread/<int:match_id>', methods=['POST'])
@login_required
@role_required('Global Admin')
def schedule_mls_match_thread(match_id):
    match = MLSMatch.query.get_or_404(match_id)
    hours_before = int(request.form.get('hours_before', 24))
    match.thread_creation_time = match.date_time - timedelta(hours=hours_before)

    try:
        db.session.commit()
        return jsonify({
            'success': True,
            'message': f'Match thread for {match.opponent} scheduled to be created on {match.thread_creation_time}'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f"Error scheduling thread: {str(e)}"}), 500

@admin_bp.route('/admin/force_create_mls_thread/<int:match_id>', methods=['POST'])
@login_required
@role_required('Global Admin')
def force_create_mls_thread(match_id):
    match = MLSMatch.query.get_or_404(match_id)
    
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        thread_id = loop.run_until_complete(create_match_thread(match))
        
        if thread_id:
            match.thread_created = True
            match.discord_thread_id = thread_id
            db.session.commit()
            return jsonify({
                'success': True,
                'message': f'MLS match thread created successfully. Thread ID: {thread_id}'
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Failed to create MLS match thread. Please check the logs for more information.'
            })
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in force_create_mls_thread: {str(e)}")
        return jsonify({'success': False, 'message': f"An error occurred: {str(e)}"}), 500

@admin_bp.route('/admin/schedule_all_mls_threads', methods=['POST'])
@login_required
@role_required('Global Admin')
def schedule_all_mls_threads():
    matches = MLSMatch.query.filter(MLSMatch.thread_created == False).all()

    try:
        for match in matches:
            if not match.thread_creation_time:
                match.thread_creation_time = match.date_time - timedelta(hours=24)
        db.session.commit()
        return jsonify({'success': True, 'message': 'All unscheduled MLS match threads have been scheduled.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f"Error scheduling all threads: {str(e)}"}), 500