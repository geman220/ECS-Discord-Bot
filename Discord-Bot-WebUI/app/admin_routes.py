# app/admin_routes.py

from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    flash,
    request,
    jsonify,
    current_app
)
from flask_login import login_required, current_user
from app.decorators import role_required, db_operation, query_operation
from app.models import (
    User, Role, Permission, MLSMatch, ScheduledMessage,
    Announcement, Feedback, FeedbackReply, Note, Team, Match,
    Availability, Player, League
)
from app.forms import (
    AnnouncementForm, EditUserForm, ResetPasswordForm,
    AdminFeedbackForm, NoteForm, FeedbackReplyForm
)
from app.admin_helpers import (
    get_filtered_users, handle_user_action, get_container_data,
    manage_docker_container, get_container_logs, send_sms_message,
    handle_announcement_update, get_role_permissions_data,
    get_rsvp_status_data, handle_permissions_update,
    get_initial_role_status
)
from app.tasks.tasks_discord import (
    update_player_discord_roles,
    fetch_role_status,
    process_discord_role_updates
)
from app.discord_utils import (
    get_expected_roles,
    process_role_updates
)
from app.tasks.tasks_core import (
    schedule_season_availability,
    send_availability_message_task
)
from app.tasks.tasks_live_reporting import (
    start_live_reporting,
    process_match_update,
    schedule_live_reporting,
    force_create_mls_thread_task,
    schedule_all_mls_threads_task,
    schedule_mls_thread_task
)
from app.email import send_email
from datetime import datetime, timedelta
from app.extensions import celery
from sqlalchemy.orm import joinedload
import asyncio
import logging

logger = logging.getLogger(__name__)
admin_bp = Blueprint('admin', __name__)

# Main Dashboard Route
@admin_bp.route('/admin/dashboard', methods=['GET', 'POST'])
@login_required
@role_required('Global Admin')
def admin_dashboard():
    if request.method == 'POST':
        action = request.form.get('action')

        if action in ['approve', 'remove', 'reset_password']:
            user_id = request.form.get('user_id')
            success = handle_user_action(action, user_id)
            if not success:
                flash('Error processing user action.', 'danger')
            return redirect(url_for('admin.admin_dashboard'))

        elif action == 'create_announcement':
            title = request.form.get('title')
            content = request.form.get('content')
            success = handle_announcement_update(title=title, content=content)
            if not success:
                flash('Error creating announcement.', 'danger')
            return redirect(url_for('admin.admin_dashboard'))

        elif action == 'update_permissions':
            role_id = request.form.get('role_id')
            permissions = request.form.getlist('permissions')
            success = handle_permissions_update(role_id, permissions)
            if not success:
                flash('Error updating permissions.', 'danger')
            return redirect(url_for('admin.admin_dashboard'))

    # GET request handling
    page = request.args.get('page', 1, type=int)
    filters = {
        'search': request.args.get('search', ''),
        'role': request.args.get('role', ''),
        'league': request.args.get('league', ''),
        'active': request.args.get('active', ''),
        'approved': request.args.get('approved', '')
    }

    users_query = get_filtered_users(filters)
    pagination = users_query.paginate(page=page, per_page=10)

    template_data = {
        'users': pagination.items,
        'pagination': pagination,
        'roles': Role.query.all(),
        'permissions': Permission.query.all(),
        'announcements': Announcement.query.order_by(Announcement.created_at.desc()).all(),
        'teams': Team.query.all(),
        'edit_form': EditUserForm(),
        'reset_password_form': ResetPasswordForm(),
        'announcement_form': AnnouncementForm()
    }

    return render_template('admin_dashboard.html', **template_data)

# Docker Container Management Routes
@admin_bp.route('/admin/container/<container_id>/<action>', methods=['POST'])
@login_required
@role_required('Global Admin')
def manage_container(container_id, action):
    success = manage_docker_container(container_id, action)
    if not success:
        flash("Failed to manage container.", "danger")
    return redirect(url_for('admin.admin_dashboard'))

@admin_bp.route('/admin/view_logs/<container_id>', methods=['GET'])
@login_required
@role_required('Global Admin')
def view_logs(container_id):
    logs = get_container_logs(container_id)
    if logs is None:
        return jsonify({"error": "Failed to retrieve logs"}), 500
    return jsonify({"logs": logs})

@admin_bp.route('/admin/docker_status', methods=['GET'])
@login_required
@role_required('Global Admin')
def docker_status():
    containers = get_container_data()
    if containers is None:
        return jsonify({"error": "Failed to fetch container data"}), 500
    return jsonify(containers)

# SMS Management Route
@admin_bp.route('/admin/send_sms', methods=['POST'])
@login_required
@role_required('Global Admin')
def send_sms():
    to_phone = request.form.get('to_phone_number')
    message = request.form.get('message_body')

    if not to_phone or not message:
        flash("Phone number and message body are required.", "danger")
        return redirect(url_for('admin.admin_dashboard'))

    success = send_sms_message(to_phone, message)
    if not success:
        flash("Failed to send SMS.", "danger")
    return redirect(url_for('admin.admin_dashboard'))

# Role Management Routes
@admin_bp.route('/admin/get_role_permissions', methods=['GET'])
@login_required
@role_required('Global Admin')
def get_role_permissions():
    role_id = request.args.get('role_id')
    permissions = get_role_permissions_data(role_id)
    if permissions is None:
        return jsonify({'error': 'Role not found.'}), 404
    return jsonify({'permissions': permissions})

# Announcement Management Routes
@admin_bp.route('/admin/announcements', methods=['GET', 'POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
@query_operation
def manage_announcements():
    form = AnnouncementForm()
    announcements = Announcement.query.order_by(Announcement.position).all()
    return render_template(
        'admin_dashboard.html',
        announcements=announcements,
        announcement_form=form
    )

@admin_bp.route('/admin/announcements/<int:announcement_id>/edit', methods=['PUT'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
@db_operation
def edit_announcement(announcement_id):
    data = request.get_json()
    if not data or not data.get('title') or not data.get('content'):
        return jsonify({'error': 'Title and content are required.'}), 400

    announcement = Announcement.query.get_or_404(announcement_id)
    announcement.title = data['title']
    announcement.content = data['content']
    return jsonify({'success': True})

@admin_bp.route('/admin/announcements/<int:announcement_id>/delete', methods=['DELETE'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
@db_operation
def delete_announcement(announcement_id):
    announcement = Announcement.query.get_or_404(announcement_id)
    db.session.delete(announcement)
    return jsonify({'success': True})

@admin_bp.route('/admin/announcements/reorder', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
@db_operation
def reorder_announcements():
    order = request.json.get('order', [])
    if not order:
        return jsonify({'error': 'No order data provided.'}), 400

    for item in order:
        announcement = Announcement.query.get(item['id'])
        if announcement:
            announcement.position = item['position']
    return jsonify({'success': True})

# Schedule Management Routes
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
@query_operation
def view_scheduled_messages():
    messages = ScheduledMessage.query.order_by(
        ScheduledMessage.scheduled_send_time
    ).all()
    return render_template('admin/scheduled_messages.html', messages=messages)

@admin_bp.route('/admin/force_send/<int:message_id>', methods=['POST'])
@login_required
@db_operation
def force_send_message(message_id):
    try:
        message = ScheduledMessage.query.get_or_404(message_id)
        # Queue the task with proper parameter name
        task = send_availability_message_task.delay(scheduled_message_id=message.id)
        
        # Update message status to indicate it's being processed
        message.status = 'QUEUED'
        flash('Message is being sent.', 'success')
        
    except Exception as e:
        logger.error(f"Error queuing message {message_id}: {str(e)}")
        flash('Error queuing message for sending.', 'danger')
        
    return redirect(url_for('admin.view_scheduled_messages'))

@admin_bp.route('/admin/rsvp_status/<int:match_id>')
@login_required
@role_required('Global Admin')
@query_operation
def rsvp_status(match_id):
    match = Match.query.get_or_404(match_id)
    rsvp_data = get_rsvp_status_data(match)
    return render_template('admin/rsvp_status.html', match=match, rsvps=rsvp_data)

# Feedback Management Routes
@admin_bp.route('/admin/reports')
@login_required
@role_required('Global Admin')
@query_operation
def admin_reports():
    page = request.args.get('page', 1, type=int)
    filters = {
        'status': request.args.get('status', ''),
        'priority': request.args.get('priority', ''),
        'sort_by': request.args.get('sort_by', 'created_at'),
        'order': request.args.get('order', 'desc')
    }

    query = Feedback.query

    if filters['status']:
        query = query.filter(Feedback.status == filters['status'])
    if filters['priority']:
        query = query.filter(Feedback.priority == filters['priority'])

    if filters['order'] == 'asc':
        query = query.order_by(getattr(Feedback, filters['sort_by']).asc())
    else:
        query = query.order_by(getattr(Feedback, filters['sort_by']).desc())

    feedbacks = query.paginate(page=page, per_page=20, error_out=False)
    return render_template('admin_reports.html', feedbacks=feedbacks)

@admin_bp.route('/admin/feedback/<int:feedback_id>', methods=['GET', 'POST'])
@login_required
@role_required('Global Admin')
@db_operation
def view_feedback(feedback_id):
    """Handle viewing and updating admin feedback."""
    try:
        feedback = Feedback.query.options(
            db.joinedload(Feedback.replies).joinedload(FeedbackReply.user),
            db.joinedload(Feedback.user)
        ).get_or_404(feedback_id)

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
                    user_id=current_user.id,
                    content=reply_form.content.data,
                    is_admin_reply=True
                )
                db.session.add(reply)

                # Send email notification if user exists
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
                        # Continue even if email fails

                flash('Your reply has been added successfully.', 'success')
                return redirect(url_for('admin.view_feedback', feedback_id=feedback.id))

            elif 'add_note' in request.form and note_form.validate():
                note = Note(
                    content=note_form.content.data,
                    feedback_id=feedback.id,
                    author_id=current_user.id
                )
                db.session.add(note)
                flash('Note added successfully.', 'success')
                return redirect(url_for('admin.view_feedback', feedback_id=feedback.id))

        return render_template(
            'admin_report_detail.html',
            feedback=feedback,
            form=form,
            reply_form=reply_form,
            note_form=note_form
        )

    except Exception as e:
        logger.error(f"Error handling feedback {feedback_id}: {str(e)}", exc_info=True)
        flash('An error occurred while processing the feedback.', 'danger')
        return redirect(url_for('admin.admin_reports'))

@admin_bp.route('/admin/schedule_next_week', methods=['POST'])
@login_required
@role_required('Global Admin')
def schedule_next_week():
    task = schedule_season_availability.delay()
    flash('Next week scheduling task has been initiated.', 'success')
    return redirect(url_for('admin.view_scheduled_messages'))

@admin_bp.route('/admin/feedback/<int:feedback_id>/close', methods=['POST'])
@login_required
@role_required('Global Admin')
@db_operation
def close_feedback(feedback_id):
    feedback = Feedback.query.get_or_404(feedback_id)
    feedback.status = 'Closed'
    feedback.closed_at = datetime.utcnow()

    send_email(
        to=feedback.user.email,
        subject=f"Your Feedback #{feedback.id} has been closed",
        body=render_template('emails/feedback_closed.html', feedback=feedback)
    )
    flash('Feedback has been closed successfully.', 'success')
    return redirect(url_for('admin.view_feedback', feedback_id=feedback.id))

@admin_bp.route('/admin/check_role_status/<task_id>', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def check_role_status(task_id):
    """Check the status of a role sync task."""
    try:
        task = fetch_role_status.AsyncResult(task_id)
        if task.ready():
            if task.successful():
                return jsonify({
                    'state': 'COMPLETE',
                    'results': task.get()
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

@admin_bp.route('/admin/discord_role_status', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
@query_operation
def discord_role_status():
    """Get Discord role status for all players with Discord IDs."""
    try:
        # Start the Celery task to fetch role status asynchronously
        task = fetch_role_status.delay()

        # Render the page immediately, passing the task ID and an empty players array
        return render_template('discord_role_status.html', task_id=task.id, players=[])

    except Exception as e:
        logger.error(f"Error loading Discord role status page: {str(e)}", exc_info=True)
        flash('Error loading Discord role status.', 'danger')
        return render_template('discord_role_status.html', task_id=None, players=[])

async def get_player_data(players):
    """Asynchronously get player data including expected roles."""
    player_data = []
    for player in players:
        # Use stored roles for initial display
        current_roles = player.discord_roles or []
        # Use async get_expected_roles when needed
        expected_roles = await get_expected_roles(player)

        # Determine status
        if not player.discord_last_verified:
            status_class = 'info'
            status_text = 'Never Verified'
        elif sorted(current_roles) == sorted(expected_roles):
            status_class = 'success'
            status_text = 'Synced'
        else:
            status_class = 'warning'
            status_text = 'Out of Sync'

        player_data.append({
            'id': player.id,
            'name': player.name,
            'discord_id': player.discord_id,
            'team': player.team.name if player.team else 'No Team',
            'league': player.team.league.name if player.team and player.team.league else 'No League',
            'current_roles': current_roles,
            'expected_roles': expected_roles,
            'status_class': status_class,
            'status_text': status_text,
            'last_verified': player.discord_last_verified.strftime('%Y-%m-%d %H:%M:%S') if player.discord_last_verified else 'Never'
        })
    return player_data

@admin_bp.route('/admin/update_player_roles/<int:player_id>', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def update_player_roles_route(player_id):
    """Update Discord roles for a specific player."""
    try:
        # Initiate the Celery task to update roles
        task_result = update_player_discord_roles.delay(player_id).get(timeout=30)

        # Parse task result
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
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@admin_bp.route('/admin/update_discord_roles', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
@db_operation
def mass_update_discord_roles():
    """Trigger mass update of Discord roles."""
    try:
        # Mark all players with Discord IDs that are out of sync for update
        Player.query.filter(
            Player.discord_id.isnot(None),
            Player.discord_roles_synced == False
        ).update({Player.discord_needs_update: True}, synchronize_session=False)

        db.session.commit()

        # Queue the mass update task
        result = process_discord_role_updates.delay()

        return jsonify({
            'success': True,
            'message': 'Mass role update initiated',
            'task_id': result.id
        })

    except Exception as e:
        logger.error(f"Error initiating mass role update: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# MLS Match Management Routes
@admin_bp.route('/admin/mls_matches')
@login_required
@role_required('Global Admin')
@query_operation
def view_mls_matches():
    matches = MLSMatch.query.all()
    return render_template('admin/mls_matches.html',
                           matches=matches,
                           timedelta=timedelta)

@admin_bp.route('/admin/schedule_mls_match_thread/<int:match_id>', methods=['POST'])
@login_required
@role_required('Global Admin')
def schedule_mls_match_thread_route(match_id):
    hours_before = request.json.get('hours_before', 24)
    task = schedule_mls_thread_task.delay(match_id, hours_before)
    return jsonify({
        'success': True,
        'task_id': task.id,
        'message': 'Thread scheduling task started'
    })

@admin_bp.route('/admin/check_thread_status/<task_id>', methods=['GET'])
@login_required
@role_required('Global Admin')
def check_thread_status(task_id):
    """Check the status of a thread creation task."""
    try:
        task = force_create_mls_thread_task.AsyncResult(task_id)
        if task.ready():
            if task.successful():
                return jsonify({
                    'state': 'COMPLETE',
                    'result': task.get()
                })
            else:
                return jsonify({
                    'state': 'FAILED',
                    'error': str(task.result)
                })
        return jsonify({'state': 'PENDING'})
    except Exception as e:
        logger.error(f"Error checking task status: {str(e)}")
        return jsonify({
            'state': 'ERROR',
            'error': str(e)
        }), 500

@admin_bp.route('/admin/task_status/<task_id>', methods=['GET'])
@login_required
@role_required('Global Admin')
def check_task_status(task_id):
    """Check the status of a task."""
    task_result = AsyncResult(task_id)
    result = {
        'task_id': task_id,
        'status': task_result.status,
    }
    
    if task_result.ready():
        result['result'] = task_result.get() if task_result.successful() else str(task_result.result)
    
    return jsonify(result)

@admin_bp.route('/admin/schedule_all_mls_threads', methods=['POST'])
@login_required
@role_required('Global Admin')
def schedule_all_mls_threads_route():
    task = schedule_all_mls_threads_task.delay()
    return jsonify({
        'success': True,
        'task_id': task.id,
        'message': 'Mass thread scheduling started'
    })

@admin_bp.route('/admin/match_stats', methods=['GET'])
@login_required
@role_required('Global Admin')
@query_operation
def get_match_statistics():
    """Get statistics for matches."""
    stats = get_match_stats()
    return jsonify(stats)

# Health Check Routes
@admin_bp.route('/admin/health', methods=['GET'])
@login_required
@role_required('Global Admin')
def health_check():
    """System health check endpoint."""
    health_status = check_system_health()
    return jsonify(health_status)

@admin_bp.route('/admin/task_status', methods=['GET'])
@login_required
@role_required('Global Admin')
def get_task_status():
    """Get status of background tasks."""
    task_status = check_task_status()
    return jsonify(task_status)

@admin_bp.route('/admin/feedback/<int:feedback_id>/delete', methods=['POST'])
@login_required
@role_required('Global Admin')
@db_operation
def delete_feedback(feedback_id):
    feedback = Feedback.query.get_or_404(feedback_id)
    db.session.delete(feedback)
    flash('Feedback has been permanently deleted.', 'success')
    return redirect(url_for('admin.admin_reports'))