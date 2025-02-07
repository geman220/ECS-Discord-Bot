# feedback.py

from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required
from app.forms import FeedbackForm, FeedbackReplyForm
from app.models import Feedback, User, FeedbackReply, Role
from app.email import send_email
from app.utils.db_utils import transactional
from app.core import db
from app.utils.user_helpers import safe_current_user
from sqlalchemy.orm import joinedload
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

feedback_bp = Blueprint('feedback', __name__, template_folder='templates')

def get_admin_emails():
    """Get admin emails"""
    admin_role = Role.query.filter_by(name='Global Admin').first()
    if admin_role:
        admin_users = User.query.filter(User.roles.contains(admin_role)).all()
        return [user.email for user in admin_users]
    return []

@transactional
def create_feedback_entry(form_data, user_id=None, username=None):
    """Creates a new feedback entry"""
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
    """Retrieves paginated user feedbacks"""
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