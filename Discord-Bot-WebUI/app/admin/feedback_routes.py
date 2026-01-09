# app/admin/feedback_routes.py

"""
Feedback Management Routes

This module contains routes for viewing, updating, closing,
and deleting feedback entries, as well as managing replies and notes.
"""

import logging
from datetime import datetime
from flask import Blueprint, request, redirect, url_for, abort, g, render_template
from flask_login import login_required
from sqlalchemy.orm import joinedload

from app.decorators import role_required
from app.alert_helpers import show_success
from app.email import send_email
from app.forms import AdminFeedbackForm, FeedbackReplyForm, NoteForm
from app.models import Feedback, FeedbackReply, Note
from app.utils.user_helpers import safe_current_user

logger = logging.getLogger(__name__)

# Import the shared admin blueprint
from app.admin.blueprint import admin_bp


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
        'admin_report_detail_flowbite.html',
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