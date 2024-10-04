# feedback.py
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app.forms import FeedbackForm
from app.models import db, Feedback, User
from functools import wraps

feedback_bp = Blueprint('feedback', __name__, template_folder='templates')

# Route to display the feedback submission form
@feedback_bp.route('/submit_feedback', methods=['GET', 'POST'])
def submit_feedback():
    form = FeedbackForm()
    if form.validate_on_submit():
        feedback = Feedback(
            user_id=current_user.id if current_user.is_authenticated else None,
            category=form.category.data,
            title=form.title.data,
            description=form.description.data
        )
        db.session.add(feedback)
        db.session.commit()
        flash('Your feedback has been submitted successfully!', 'success')
        return redirect(url_for('main.index'))  # Adjust 'main.index' as per your main route
    return render_template('submit_feedback.html', form=form)
