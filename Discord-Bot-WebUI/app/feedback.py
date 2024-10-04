# feedback.py
from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user
from app.forms import FeedbackForm
from app.models import db, Feedback, User
from functools import wraps

feedback_bp = Blueprint('feedback', __name__, template_folder='templates')

@feedback_bp.route('/submit_feedback', methods=['GET', 'POST'])
def submit_feedback():
    form = FeedbackForm()
    page = request.args.get('page', 1, type=int)
    per_page = 10  # Number of feedbacks per page
    search_query = request.args.get('q', '', type=str).strip()

    feedback_query = Feedback.query

    if current_user.is_authenticated:
        feedback_query = feedback_query.filter_by(user_id=current_user.id)

    if search_query:
        feedback_query = feedback_query.filter(
            Feedback.title.ilike(f'%{search_query}%') |
            Feedback.category.ilike(f'%{search_query}%')
        )

    feedback_query = feedback_query.order_by(Feedback.created_at.desc())

    user_feedbacks = feedback_query.paginate(page=page, per_page=per_page, error_out=False)

    if form.validate_on_submit():
        # Handle feedback submission as before
        if not current_user.is_authenticated:
            if not form.name.data.strip():
                form.name.errors.append('Name is required.')
                return render_template('submit_feedback.html', form=form, feedbacks=user_feedbacks, search_query=search_query)
            name = form.name.data.strip()
            user_id = None
        else:
            name = current_user.username
            user_id = current_user.id

        feedback = Feedback(
            user_id=user_id,
            name=name,
            category=form.category.data,
            title=form.title.data,
            description=form.description.data
        )
        db.session.add(feedback)
        db.session.commit()
        flash('Your feedback has been submitted successfully!', 'success')

        # Redirect to the same page to display updated feedbacks
        return redirect(url_for('feedback.submit_feedback'))

    return render_template('submit_feedback.html', form=form, feedbacks=user_feedbacks, search_query=search_query)

@feedback_bp.route('/feedback/<int:feedback_id>', methods=['GET'])
@login_required
def view_feedback(feedback_id):
    feedback = Feedback.query.get_or_404(feedback_id)
    
    # Ensure the feedback belongs to the current user
    if feedback.user_id != current_user.id:
        abort(403)  # Forbidden
    
    return render_template('view_feedback_user.html', feedback=feedback)