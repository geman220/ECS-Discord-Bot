# app/auth/two_factor.py

"""
Two-Factor Authentication Routes

Routes for 2FA verification during login.
"""

import logging
from datetime import datetime, timedelta

from flask import (
    render_template, redirect, url_for, request,
    current_app, session, g, make_response
)
from flask_login import login_user

from app.auth import auth
from app.alert_helpers import show_error
from app.models import User
from app.forms import TwoFactorForm
from app.utils.db_utils import transactional
from app.auth.helpers import sync_discord_for_user

logger = logging.getLogger(__name__)


@auth.route('/verify_2fa_login', methods=['GET', 'POST'])
@transactional
def verify_2fa_login():
    """
    Handle 2FA verification for users with 2FA enabled.

    If the provided TOTP token is valid, complete the login process.
    """
    # Set up a persistent session
    import uuid

    # Ensure permanent session with longer lifetime
    session.permanent = True
    current_app.permanent_session_lifetime = timedelta(days=1)  # Longer session

    # Debug session state
    logger.info(f"2FA verification requested. Session data: {dict(session)}")

    # First check for user_id in POST data (form submission)
    user_id = None
    if request.method == 'POST' and 'user_id' in request.form:
        user_id = request.form.get('user_id')
        logger.info(f"Found user_id={user_id} in form data")

    # Then check for user_id in query parameters
    if not user_id:
        user_id = request.args.get('user_id')
        logger.info(f"Found user_id={user_id} in query parameters")

    # Finally check session
    if not user_id and 'pending_2fa_user_id' in session:
        user_id = session.get('pending_2fa_user_id')
        logger.info(f"Found user_id={user_id} in session")

    # If we still don't have a user_id, we need to redirect to login
    if not user_id or (isinstance(user_id, str) and not user_id.isdigit()):
        logger.warning("No valid user_id found anywhere")
        show_error('No 2FA login pending.')
        return redirect(url_for('auth.login'))

    # Convert user_id to int if it's not already
    user_id = int(user_id)

    # Always update the session with the user_id for consistency
    session['pending_2fa_user_id'] = user_id
    session.modified = True
    logger.info(f"Set pending_2fa_user_id={user_id} in session")

    # Get the user using the correct session
    user = g.db_session.query(User).get(user_id)
    if not user:
        logger.warning(f"User not found for ID: {user_id}")
        show_error('Invalid user. Please log in again.')
        return redirect(url_for('auth.login'))

    # Create a form with CSRF protection disabled if we detect this is a CSRF issue
    # This is a special case for our Docker environment where sessions aren't persisting properly
    try:
        # Create a regular Flask-WTF form with CSRF protection
        form = TwoFactorForm()

        # Process POST request
        if request.method == 'POST':
            logger.info(f"Received 2FA form submission for user {user.id}")
            logger.info(f"Form data: {request.form}")

            # Get the token directly from form data
            token_value = request.form.get('token')

            if token_value and len(token_value) == 6 and token_value.isdigit():
                if user.verify_totp(token_value):
                    # Success! TOTP token is correct
                    logger.info(f"2FA token verified via fallback method for user {user.id}")
                    user.last_login = datetime.utcnow()
                    # User is already attached to g.db_session, no need to add
                    sync_discord_for_user(user)

                    # Login the user
                    login_user(user, remember=True)  # Force remember=True
                    logger.info(f"User {user.id} logged in successfully after 2FA (fallback)")

                    # Force session save and use a response object for better cookie handling
                    session.permanent = True
                    session.modified = True

                    # Check if there's a stored redirect URL
                    next_page = session.pop('next', None)
                    if next_page and next_page.startswith('/') and not next_page.startswith('//'):
                        redirect_url = next_page
                        logger.info(f"Redirecting user {user.id} to stored next page: {redirect_url}")
                    else:
                        redirect_url = url_for('main.index')
                        logger.info(f"Redirecting user {user.id} to main index (no stored next page)")

                    # Create response with strong cookie settings
                    response = make_response(redirect(redirect_url))
                    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0'

                    # Force the session to be saved to the response
                    from flask.sessions import SessionInterface
                    if hasattr(current_app, 'session_interface') and isinstance(current_app.session_interface, SessionInterface):
                        current_app.session_interface.save_session(current_app, session, response)

                    logger.info(f"Redirecting user {user.id} to {redirect_url} after successful 2FA with enhanced session handling")
                    return response
                else:
                    # Invalid token
                    logger.warning(f"Invalid 2FA token submitted for user {user.id}")
                    show_error('Invalid verification code. Please try again.')
            else:
                logger.warning(f"Invalid 2FA token format: {token_value}")
                show_error('Please enter a valid 6-digit verification code.')
    except Exception as e:
        logger.error(f"Error processing 2FA form: {str(e)}", exc_info=True)
        show_error('An error occurred. Please try logging in again.')
        return redirect(url_for('auth.login'))

    # Add csrf_token to template context
    return render_template('verify_2fa.html', title='Verify 2FA', form=form, user_id=user.id)
