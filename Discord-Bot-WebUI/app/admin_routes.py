# app/admin_routes.py

import logging
from flask import (
    Blueprint, render_template, redirect, url_for, flash, request,
    jsonify, current_app, abort
)
from flask_login import login_required
from app.decorators import role_required
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
    get_rsvp_status_data, handle_permissions_update
)
from app.tasks.tasks_discord import (
    update_player_discord_roles,
    fetch_role_status,
    process_discord_role_updates
)
from app.tasks.tasks_core import (
    schedule_season_availability,
    send_availability_message_task
)
from app.tasks.tasks_live_reporting import (
    force_create_mls_thread_task,
    schedule_all_mls_threads_task,
    schedule_mls_thread_task
)
from app.email import send_email
from datetime import datetime, timedelta
from sqlalchemy.orm import joinedload
from flask import g
from app.utils.user_helpers import safe_current_user

logger = logging.getLogger(__name__)
admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/admin/dashboard', endpoint='admin_dashboard', methods=['GET', 'POST'])
@login_required
@role_required('Global Admin')
def admin_dashboard():
    session = g.db_session

    if request.method == 'POST':
        action = request.form.get('action')

        if action in ['approve', 'remove', 'reset_password']:
            user_id = request.form.get('user_id')
            success = handle_user_action(action, user_id, session=session)
            if not success:
                flash('Error processing user action.', 'danger')
            return redirect(url_for('admin.admin_dashboard'))

        elif action == 'create_announcement':
            title = request.form.get('title')
            content = request.form.get('content')
            success = handle_announcement_update(title=title, content=content, session=session)
            if not success:
                flash('Error creating announcement.', 'danger')
            return redirect(url_for('admin.admin_dashboard'))

        elif action == 'update_permissions':
            role_id = request.form.get('role_id')
            permissions = request.form.getlist('permissions')
            success = handle_permissions_update(role_id, permissions, session=session)
            if not success:
                flash('Error updating permissions.', 'danger')
            return redirect(url_for('admin.admin_dashboard'))

    # GET request handling
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


@admin_bp.route('/admin/container/<container_id>/<action>', endpoint='manage_container', methods=['POST'])
@login_required
@role_required('Global Admin')
def manage_container(container_id, action):
    success = manage_docker_container(container_id, action)
    if not success:
        flash("Failed to manage container.", "danger")
    return redirect(url_for('admin.admin_dashboard'))


@admin_bp.route('/admin/view_logs/<container_id>', endpoint='view_logs', methods=['GET'])
@login_required
@role_required('Global Admin')
def view_logs(container_id):
    logs = get_container_logs(container_id)
    if logs is None:
        return jsonify({"error": "Failed to retrieve logs"}), 500
    return jsonify({"logs": logs})


@admin_bp.route('/admin/docker_status', endpoint='docker_status', methods=['GET'])
@login_required
@role_required('Global Admin')
def docker_status():
    containers = get_container_data()
    if containers is None:
        return jsonify({"error": "Failed to fetch container data"}), 500
    return jsonify(containers)


@admin_bp.route('/admin/send_sms', endpoint='send_sms', methods=['POST'])
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


@admin_bp.route('/admin/get_role_permissions', endpoint='get_role_permissions', methods=['GET'])
@login_required
@role_required('Global Admin')
def get_role_permissions():
    role_id = request.args.get('role_id')
    permissions = get_role_permissions_data(role_id, session=g.db_session)
    if permissions is None:
        return jsonify({'error': 'Role not found.'}), 404
    return jsonify({'permissions': permissions})


@admin_bp.route('/admin/announcements', endpoint='manage_announcements', methods=['GET', 'POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def manage_announcements():
    session = g.db_session
    form = AnnouncementForm()
    announcements = session.query(Announcement).order_by(Announcement.position).all()
    return render_template(
        'admin_dashboard.html',
        announcements=announcements,
        announcement_form=form
    )


@admin_bp.route('/admin/announcements/<int:announcement_id>/edit', endpoint='edit_announcement', methods=['PUT'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def edit_announcement(announcement_id):
    session = g.db_session
    data = request.get_json()
    if not data or not data.get('title') or not data.get('content'):
        return jsonify({'error': 'Title and content are required.'}), 400

    announcement = session.query(Announcement).get(announcement_id)
    if not announcement:
        abort(404)

    announcement.title = data['title']
    announcement.content = data['content']
    return jsonify({'success': True})


@admin_bp.route('/admin/announcements/<int:announcement_id>/delete', endpoint='delete_announcement', methods=['DELETE'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def delete_announcement(announcement_id):
    session = g.db_session
    announcement = session.query(Announcement).get(announcement_id)
    if not announcement:
        abort(404)

    session.delete(announcement)
    flash('Announcement deleted successfully.', 'success')
    return jsonify({'success': True})


@admin_bp.route('/admin/announcements/reorder', endpoint='reorder_announcements', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def reorder_announcements():
    session = g.db_session
    order = request.json.get('order', [])
    if not order:
        return jsonify({'error': 'No order data provided.'}), 400

    for item in order:
        ann = session.query(Announcement).get(item['id'])
        if ann:
            ann.position = item['position']
    return jsonify({'success': True})


@admin_bp.route('/admin/schedule_season', endpoint='schedule_season', methods=['POST'])
@login_required
@role_required('Global Admin')
def schedule_season():
    task = schedule_season_availability.delay()
    flash('Season scheduling task has been initiated.', 'success')
    return redirect(url_for('admin.view_scheduled_messages'))


@admin_bp.route('/admin/scheduled_messages', endpoint='view_scheduled_messages')
@login_required
@role_required('Global Admin')
def view_scheduled_messages():
    session = g.db_session
    messages = session.query(ScheduledMessage).order_by(ScheduledMessage.scheduled_send_time).all()
    return render_template('admin/scheduled_messages.html', messages=messages)


@admin_bp.route('/admin/force_send/<int:message_id>', endpoint='force_send_message', methods=['POST'])
@login_required
@role_required('Global Admin')
def force_send_message(message_id):
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


@admin_bp.route('/admin/rsvp_status/<int:match_id>', endpoint='rsvp_status')
@login_required
@role_required('Global Admin')
def rsvp_status(match_id):
    session = g.db_session
    match = session.query(Match).get(match_id)
    if not match:
        abort(404)
    rsvp_data = get_rsvp_status_data(match, session=session)
    return render_template('admin/rsvp_status.html', match=match, rsvps=rsvp_data)


@admin_bp.route('/admin/reports', endpoint='admin_reports')
@login_required
@role_required('Global Admin')
def admin_reports():
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
    feedbacks = query.offset((page - 1)*per_page).limit(per_page).all()

    return render_template('admin_reports.html', feedbacks=feedbacks, page=page, total=total, per_page=per_page)


@admin_bp.route('/admin/feedback/<int:feedback_id>', endpoint='view_feedback', methods=['GET', 'POST'])
@login_required
@role_required('Global Admin')
def view_feedback(feedback_id):
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


@admin_bp.route('/admin/schedule_next_week', endpoint='schedule_next_week', methods=['POST'])
@login_required
@role_required('Global Admin')
def schedule_next_week():
    task = schedule_season_availability.delay()
    flash('Next week scheduling task has been initiated.', 'success')
    return redirect(url_for('admin.view_scheduled_messages'))


@admin_bp.route('/admin/feedback/<int:feedback_id>/close', endpoint='close_feedback', methods=['POST'])
@login_required
@role_required('Global Admin')
def close_feedback(feedback_id):
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


@admin_bp.route('/admin/check_role_status/<task_id>', endpoint='check_role_status', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def check_role_status(task_id):
    try:
        task = fetch_role_status.AsyncResult(task_id)
        if task.ready():
            if task.successful():
                task_result = task.get()  # {'success':True,'results':[...],'message':...}
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
    try:
        # This will block until the task completes, consider async polling if needed
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
    session = g.db_session
    matches = session.query(MLSMatch).all()
    return render_template('admin/mls_matches.html',
                           matches=matches,
                           timedelta=timedelta)


@admin_bp.route('/admin/schedule_mls_match_thread/<int:match_id>', endpoint='schedule_mls_match_thread_route', methods=['POST'])
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


@admin_bp.route('/admin/check_thread_status/<task_id>', endpoint='check_thread_status', methods=['GET'])
@login_required
@role_required('Global Admin')
def check_thread_status(task_id):
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
    from celery.result import AsyncResult
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
    task = schedule_all_mls_threads_task.delay()
    return jsonify({
        'success': True,
        'task_id': task.id,
        'message': 'Mass thread scheduling started'
    })


# Placeholder implementations for any missing endpoints
def get_match_stats(session):
    return {"status": "ok", "stats": []}


def check_system_health(session):
    return {"status": "healthy"}


def check_task_status(session):
    return {"status": "no_tasks"}


@admin_bp.route('/admin/match_stats', endpoint='get_match_statistics', methods=['GET'])
@login_required
@role_required('Global Admin')
def get_match_statistics():
    stats = get_match_stats(g.db_session)
    return jsonify(stats)


@admin_bp.route('/admin/health', endpoint='health_check', methods=['GET'])
@login_required
@role_required('Global Admin')
def health_check():
    health_status = check_system_health(g.db_session)
    return jsonify(health_status)


@admin_bp.route('/admin/task_status', endpoint='get_task_status', methods=['GET'])
@login_required
@role_required('Global Admin')
def get_task_status():
    task_status = check_task_status(g.db_session)
    return jsonify(task_status)


@admin_bp.route('/admin/feedback/<int:feedback_id>/delete', endpoint='delete_feedback', methods=['POST'])
@login_required
@role_required('Global Admin')
def delete_feedback(feedback_id):
    session = g.db_session
    feedback = session.query(Feedback).get(feedback_id)
    if not feedback:
        abort(404)
    session.delete(feedback)
    flash('Feedback has been permanently deleted.', 'success')
    return redirect(url_for('admin.admin_reports'))
