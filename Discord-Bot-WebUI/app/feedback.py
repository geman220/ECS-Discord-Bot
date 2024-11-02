# feedback.py
from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user
from app.forms import FeedbackForm, FeedbackReplyForm
from app.models import db, Feedback, User, FeedbackReply, User, Role
from app.email import send_email
from app.decorators import with_session
from functools import wraps
from datetime import datetime

feedback_bp = Blueprint('feedback', __name__, template_folder='templates')

def get_admin_emails():
    admin_role = Role.query.filter_by(name='Global Admin').first()
    if admin_role:
        admin_users = User.query.filter(User.roles.contains(admin_role)).all()
        return [user.email for user in admin_users]
    return []

@feedback_bp.route('/submit_feedback', methods=['GET', 'POST'])
def submit_feedback():
    form = FeedbackForm()
    page = request.args.get('page', 1, type=int)
    per_page = 10
    search_query = request.args.get('q', '', type=str).strip()

    if current_user.is_authenticated:
        feedback_query = Feedback.query.filter_by(user_id=current_user.id)
    else:
        feedback_query = Feedback.query.filter_by(user_id=None)
        
    if search_query:
        feedback_query = feedback_query.filter(
            Feedback.title.ilike(f'%{search_query}%') |
            Feedback.category.ilike(f'%{search_query}%')
        )
    
    feedback_query = feedback_query.order_by(Feedback.created_at.desc())
    user_feedbacks = feedback_query.paginate(page=page, per_page=per_page, error_out=False)

    total_count = user_feedbacks.total

    if form.validate_on_submit():
        if current_user.is_authenticated:
            user_id = current_user.id
            name = current_user.username
        else:
            user_id = None
            name = form.name.data

        new_feedback = Feedback(
            user_id=user_id,
            name=name,
            category=form.category.data,
            title=form.title.data,
            description=form.description.data
        )

        try:
            db.session.add(new_feedback)
            db.session.commit()

            admin_emails = get_admin_emails()
            if admin_emails:
                send_email(
                    to=admin_emails,
                    subject=f"New Feedback Submitted: {new_feedback.title}",
                    body=render_template('emails/new_feedback_notification.html', feedback=new_feedback)
                )

            flash('Your feedback has been submitted successfully!', 'success')
            return redirect(url_for('feedback.view_feedback', feedback_id=new_feedback.id))

        except Exception as e:
            db.session.rollback()
            flash(f"An error occurred while submitting feedback: {str(e)}", 'danger')

    return render_template('feedback/submit_feedback.html', 
                           form=form, 
                           feedbacks=user_feedbacks, 
                           search_query=search_query,
                           total_count=total_count, 
                           per_page=per_page,
                           page=page)

@feedback_bp.route('/feedback/<int:feedback_id>', methods=['GET', 'POST'])
@login_required
@with_session  # Add session management decorator
def view_feedback(feedback_id):
    feedback = Feedback.query.get_or_404(feedback_id)
    
    if feedback.user_id != current_user.id:
        abort(403)
    
    form = FeedbackReplyForm()
    
    if form.validate_on_submit():
        reply = FeedbackReply(
            feedback_id=feedback.id,
            user_id=current_user.id, 
            content=form.content.data
        )
        db.session.add(reply)
        # No need to commit here - decorator handles it
        
        flash('Reply added successfully!', 'success')
        return redirect(url_for('feedback.view_feedback', feedback_id=feedback.id))
        
    return render_template('view_feedback_user.html', feedback=feedback, form=form)

@feedback_bp.route('/feedback/<int:feedback_id>/close', methods=['POST'])
@login_required
def close_feedback(feedback_id):
    feedback = Feedback.query.get_or_404(feedback_id)
    
    if feedback.user_id != current_user.id:
        abort(403)
    
    try:
        feedback.status = 'Closed'
        feedback.closed_at = datetime.utcnow()
        db.session.commit()

        flash('Your feedback has been closed successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f"An error occurred while closing the feedback: {str(e)}", 'danger')
    finally:
        db.session.close()

    return redirect(url_for('feedback.view_feedback', feedback_id=feedback.id))