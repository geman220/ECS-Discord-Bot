# app/admin_routes.py

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
from flask_login import login_required
from flask_paginate import Pagination, get_page_parameter
from sqlalchemy import or_
from datetime import datetime
from twilio.rest import Client
from app.decorators import role_required
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
    League
)
from app.forms import AnnouncementForm, EditUserForm, ResetPasswordForm, UpdateFeedbackForm
from app.tasks import schedule_post_availability
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

            if action == 'approve':
                user.is_approved = True
                db.session.commit()
                flash(f'User {user.username} approved successfully.', 'success')
            elif action == 'remove':
                db.session.delete(user)
                db.session.commit()
                flash(f'User {user.username} removed successfully.', 'success')
            elif action == 'reset_password':
                # Implement password reset logic here
                flash(f'Password reset for {user.username} is not yet implemented.', 'warning')

        elif action == 'create_announcement':  # Handle announcement creation
            title = request.form.get('title')
            content = request.form.get('content')

            # Assuming there's a model called Announcement with title and content fields
            new_announcement = Announcement(title=title, content=content)
            db.session.add(new_announcement)
            db.session.commit()

            flash('Announcement created successfully!', 'success')

        elif action == 'update_permissions':
            role_id = request.form.get('role_id')
            selected_permissions = request.form.getlist('permissions')

            role = Role.query.get(role_id)
            if not role:
                flash('Role not found.', 'danger')
                return redirect(url_for('admin.admin_dashboard'))

            # Update permissions for the selected role
            role.permissions = Permission.query.filter(Permission.id.in_(selected_permissions)).all()
            db.session.commit()
            flash(f"Permissions updated for role '{role.name}'.", 'success')

        else:
            flash('Invalid action.', 'danger')

        # Redirect to the dashboard after POST to prevent form re-submission and reload with GET context
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
    """
    Create and view announcements.
    """
    form = AnnouncementForm()
    if form.validate_on_submit():
        # Determine the next position
        max_position = db.session.query(db.func.max(Announcement.position)).scalar() or 0

        # Create a new announcement with the next position
        new_announcement = Announcement(
            title=form.title.data,
            content=form.content.data,
            position=max_position + 1
        )
        db.session.add(new_announcement)
        db.session.commit()

        flash('Announcement created successfully.', 'success')
        return redirect(url_for('admin.manage_announcements'))

    # Fetch all announcements ordered by position
    announcements = Announcement.query.order_by(Announcement.position).all()
    return render_template('admin_dashboard.html', announcements=announcements, announcement_form=form)

@admin_bp.route('/admin/announcements/<int:announcement_id>/edit', methods=['PUT'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def edit_announcement(announcement_id):
    """
    Edit an existing announcement.
    """
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
    """
    Delete an existing announcement.
    """
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
    """
    Reorder announcements based on the provided order.
    """
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
# Schedule Availability Task
# --------------------

@admin_bp.route('/admin/schedule_availability', methods=['POST'])
@login_required
@role_required('Global Admin')
def schedule_availability():
    """
    Schedule an availability task between two teams at a specified time.
    """
    try:
        team1_id = int(request.form.get('team1_id'))
        team2_id = int(request.form.get('team2_id'))
        schedule_time_str = request.form.get('schedule_time')

        if not team1_id or not team2_id or not schedule_time_str:
            flash("Please select both teams and provide a schedule time.", "danger")
            return redirect(url_for('admin.admin_dashboard'))

        # Parse and localize schedule time
        local_tz = pytz.timezone('America/Los_Angeles')
        schedule_time = datetime.strptime(schedule_time_str, '%Y-%m-%dT%H:%M')
        schedule_time = local_tz.localize(schedule_time)

        match_date = schedule_time.strftime('%Y-%m-%d')
        match_time = schedule_time.strftime('%H:%M:%S')

        # Schedule the Celery task
        schedule_post_availability.apply_async(
            args=[team1_id, team2_id, match_date, match_time],
            countdown=30  # Adjust as needed
        )

        flash("Availability task scheduled successfully.", "success")
        return redirect(url_for('admin.admin_dashboard'))

    except Exception as e:
        logger.error(f"Error scheduling availability task: {e}")
        flash(f"Error scheduling task: {e}", "danger")
        return redirect(url_for('admin.admin_dashboard'))

# --------------------
# Additional Routes (If Needed)
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

# admin_routes.py
@admin_bp.route('/admin/reports')
@role_required('Global Admin')
def admin_reports():
    search = request.args.get('search', '')
    category = request.args.get('category', '')
    status = request.args.get('status', '')
    priority = request.args.get('priority', '')
    sort_by = request.args.get('sort_by', 'created_at')
    order = request.args.get('order', 'desc')  # 'asc' or 'desc'

    query = Feedback.query

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            db.or_(
                Feedback.title.ilike(search_term),
                Feedback.description.ilike(search_term)
            )
        )
    if category:
        query = query.filter_by(category=category)
    if status:
        query = query.filter_by(status=status)
    if priority:
        query = query.filter_by(priority=priority)

    # Sorting
    if sort_by == 'priority':
        if order == 'asc':
            query = query.order_by(Feedback.priority.asc())
        else:
            query = query.order_by(Feedback.priority.desc())
    elif sort_by == 'status':
        if order == 'asc':
            query = query.order_by(Feedback.status.asc())
        else:
            query = query.order_by(Feedback.status.desc())
    else:
        # Default sorting by created_at
        if order == 'asc':
            query = query.order_by(Feedback.created_at.asc())
        else:
            query = query.order_by(Feedback.created_at.desc())

    feedbacks = query.all()
    return render_template('admin_reports.html', feedbacks=feedbacks)

@admin_bp.route('/admin/report/<int:feedback_id>', methods=['GET', 'POST'])
@role_required('Global Admin')  # Using your existing role_required decorator
def view_feedback(feedback_id):
    feedback = Feedback.query.get_or_404(feedback_id)
    form = UpdateFeedbackForm(obj=feedback)  # Populate form with existing feedback data
    if form.validate_on_submit():
        feedback.priority = form.priority.data
        feedback.status = form.status.data
        feedback.notes = form.notes.data  # Update notes
        db.session.commit()
        flash('Feedback updated successfully.', 'success')
        return redirect(url_for('admin.admin_reports'))
    return render_template('admin_report_detail.html', feedback=feedback, form=form)