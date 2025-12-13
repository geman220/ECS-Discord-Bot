# app/auth/password.py

"""
Password Reset Routes

Routes for forgot password and password reset token handling.
"""

import logging

from flask import render_template, redirect, url_for, g
from flask_wtf import FlaskForm

from app.auth import auth
from app.alert_helpers import show_error, show_success
from app.models import User
from app.forms import ResetPasswordForm
from app.utils.db_utils import transactional
from app.utils.user_helpers import safe_current_user
from app.auth_helpers import verify_reset_token, send_reset_confirmation_email

logger = logging.getLogger(__name__)


@auth.route('/forgot_password', methods=['GET'])
def forgot_password():
    """
    Display information about the Discord login system.

    This page provides guidance for users who are trying to reset their password,
    redirecting them to Discord for authentication issues since we only use Discord login.
    """
    if safe_current_user.is_authenticated:
        return redirect(url_for('main.index'))

    # Create a blank form just to satisfy the template structure
    dummy_form = FlaskForm()

    return render_template('forgot_password.html', title='Login Help', form=dummy_form)


@auth.route('/reset_password/<token>', methods=['GET', 'POST'])
@transactional
def reset_password_token(token):
    """
    Handle password reset using a token.

    Verifies the token and allows the user to set a new password.
    """
    if safe_current_user.is_authenticated:
        return redirect(url_for('main.index'))

    user_id = verify_reset_token(token)
    if not user_id:
        show_error('Invalid or expired reset link.')
        return redirect(url_for('auth.forgot_password'))

    user = g.db_session.query(User).get(user_id)
    if not user:
        show_error('User not found.')
        return redirect(url_for('auth.forgot_password'))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        try:
            user.set_password(form.password.data)
            if send_reset_confirmation_email(user.email):
                show_success('Password updated successfully. Please log in.')
                return redirect(url_for('auth.login'))
        except Exception as e:
            logger.error(f"Password reset error: {str(e)}")
            show_error('Password reset failed. Please try again.')

    return render_template('reset_password.html', title='Reset Password', form=form, token=token)
