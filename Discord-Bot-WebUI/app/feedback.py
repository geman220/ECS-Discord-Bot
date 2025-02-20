# app/feedback.py

"""
Feedback Module

This module defines the blueprint endpoints and helper functions for handling user feedback.
It includes routes for submitting feedback, viewing individual feedback entries with replies,
and closing feedback. The module also sends notification emails to administrators upon feedback
submission and manages database transactions and error handling to ensure a smooth user experience.
"""

import logging
from datetime import datetime

from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required
from sqlalchemy.orm import joinedload

from app.forms import FeedbackForm, FeedbackReplyForm
from app.models import Feedback, User, FeedbackReply, Role
from app.email import send_email
from app.utils.db_utils import transactional
from app.core import db
from app.utils.user_helpers import safe_current_user

logger = logging.getLogger(__name__)
feedback_bp = Blueprint('feedback', __name__, template_folder='templates')


def get_admin_emails():
    """
    Retrieve email addresses of all Global Admin users.
    
    Returns:
        list: A list of email addresses for users with the 'Global Admin' role.
    """
    admin_role = Role.query.filter_by(name='Global Admin').first()
    if admin_role:
        admin_users = User.query.filter(User.roles.contains(admin_role)).all()
        return [user.email for user in admin_users]
    return []


@transactional
def create_feedback_entry(form_data, user_id=None, username=None):
    """
    Creates a new feedback entry in the database.

    Parameters:
        form_data (dict): Data from the feedback form.
        user_id (int, optional): ID of the user submitting the feedback.
        username (str, optional): Username of the feedback submitter.

    Returns:
        Feedback: The newly created feedback object.
    """
    try:
        new_feedback = Feedback(
            user_id=user_id,
            name=username or form_data.get('name'),
            category=form_data.get('category'),
            title=form_data.get('title'),
            description=form_data.get('description'),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.session.add(new_feedback)
        logger.info(f"Created new feedback: {new_feedback.id}")
        return new_feedback
    except Exception as e:
        logger.error(f"Error creating feedback: {str(e)}")
        raise


def get_user_feedbacks(user_id, page, per_page, search_query):
    """
    Retrieves paginated feedback entries for a specific user.

    Parameters:
        user_id (int): ID of the user.
        page (int): The current page number.
        per_page (int): Number of feedbacks per page.
        search_query (str): Optional search query to filter feedbacks by title or category.

    Returns:
        Pagination: A paginated object containing the user's feedback entries.
    """
    try:
        feedback_query = Feedback.query.filter_by(user_id=user_id if user_id else None)
        
        if search_query:
            feedback_query = feedback_query.filter(
                Feedback.title.ilike(f'%{search_query}%') |
                Feedback.category.ilike(f'%{search_query}%')
            )
        
        feedback_query = feedback_query.order_by(Feedback.created_at.desc())
        return feedback_query.paginate(page=page, per_page=per_page, error_out=False)
    except Exception as e:
        logger.error(f"Error getting user feedbacks: {str(e)}")
        raise


@feedback_bp.route('/submit_feedback', methods=['GET', 'POST'])
@transactional
def submit_feedback():
    """
    Handles the submission of new feedback.

    Renders the feedback submission form and processes form submissions.
    Upon successful submission, sends a notification email to administrators
    and redirects the user to view the submitted feedback.
    """
    try:
        form = FeedbackForm()
        page = request.args.get('page', 1, type=int)
        per_page = 10
        search_query = request.args.get('q', '', type=str).strip()
        
        user_id = safe_current_user.id if safe_current_user.is_authenticated else None
        username = safe_current_user.username if safe_current_user.is_authenticated else None
        
        user_feedbacks = get_user_feedbacks(user_id, page, per_page, search_query)
        
        if form.validate_on_submit():
            try:
                form_data = {
                    'name': form.name.data,
                    'category': form.category.data,
                    'title': form.title.data,
                    'description': form.description.data
                }
                
                new_feedback = create_feedback_entry(form_data, user_id, username)
                
                try:
                    admin_emails = get_admin_emails()
                    if admin_emails:
                        send_email(
                            to=admin_emails,
                            subject=f"New Feedback Submitted: {new_feedback.title}",
                            body=render_template('emails/new_feedback_notification.html', feedback=new_feedback)
                        )
                except Exception as email_error:
                    logger.error(f"Failed to send notification email: {str(email_error)}")
                
                flash('Your feedback has been submitted successfully!', 'success')
                return redirect(url_for('feedback.view_feedback', feedback_id=new_feedback.id))
                
            except Exception as e:
                logger.error(f"Error in feedback submission: {str(e)}", exc_info=True)
                flash('An error occurred while submitting your feedback. Please try again.', 'danger')
                return redirect(url_for('feedback.submit_feedback'))
        
        return render_template(
            'feedback/submit_feedback.html',
            title='Submit Feedback',
            form=form,
            feedbacks=user_feedbacks,
            search_query=search_query,
            total_count=user_feedbacks.total,
            per_page=per_page,
            page=page
        )
        
    except Exception as e:
        logger.error(f"Unexpected error in submit_feedback route: {str(e)}", exc_info=True)
        flash('An unexpected error occurred. Please try again.', 'danger')
        return redirect(url_for('main.index'))


@feedback_bp.route('/feedback/<int:feedback_id>', methods=['GET', 'POST'])
@login_required
@transactional
def view_feedback(feedback_id):
    """
    Displays a specific feedback entry along with its replies.

    Allows the user to view the details of their feedback and add a reply.
    Only the owner of the feedback is permitted to view or reply.
    """
    try:
        feedback = Feedback.query.options(
            joinedload(Feedback.replies).joinedload(FeedbackReply.user),
            joinedload(Feedback.user)
        ).get_or_404(feedback_id)
        
        if feedback.user_id != safe_current_user.id:
            abort(403)
        
        form = FeedbackReplyForm()
        
        if form.validate_on_submit():
            try:
                reply = FeedbackReply(
                    feedback_id=feedback.id,
                    user_id=safe_current_user.id, 
                    content=form.content.data,
                    created_at=datetime.utcnow()
                )
                db.session.add(reply)
                feedback.replies.append(reply)
                
                flash('Reply added successfully!', 'success')
                return redirect(url_for('feedback.view_feedback', feedback_id=feedback.id))
                
            except Exception as e:
                logger.error(f"Error adding reply to feedback {feedback.id}: {str(e)}", exc_info=True)
                flash('Error adding reply. Please try again.', 'danger')
                raise
            
        return render_template(
            'view_feedback_user.html',
            title='View Feedback',
            feedback=feedback,
            form=form
        )

    except Exception as e:
        logger.error(f"Error viewing feedback {feedback_id}: {str(e)}", exc_info=True)
        flash('An error occurred while viewing the feedback.', 'danger')
        return redirect(url_for('feedback.submit_feedback'))


@feedback_bp.route('/feedback/<int:feedback_id>/close', methods=['POST'])
@login_required
@transactional
def close_feedback(feedback_id):
    """
    Closes an existing feedback entry.

    Sets the feedback status to 'Closed' and records the closure time.
    Only the owner of the feedback is allowed to perform this action.
    """
    feedback = Feedback.query.get_or_404(feedback_id)
    
    if feedback.user_id != safe_current_user.id:
        abort(403)
    
    try:
        feedback.status = 'Closed'
        feedback.closed_at = datetime.utcnow()
        flash('Your feedback has been closed successfully.', 'success')
    except Exception as e:
        flash(f"An error occurred while closing the feedback: {str(e)}", 'danger')
        raise

    return redirect(url_for('feedback.view_feedback', feedback_id=feedback.id))