# app/auth/login.py

"""
Standard Login Routes

Routes for email/password authentication, auth check, and logout.
"""

import logging
from datetime import datetime, timedelta

from flask import (
    render_template, redirect, url_for, request,
    current_app, jsonify, session
)
from flask_login import login_user, logout_user, login_required

from app.auth import auth
from app.alert_helpers import show_error, show_info
from app.models import User, Player
from app.forms import LoginForm
from app.utils.db_utils import transactional
from app.utils.user_helpers import safe_current_user
from app.auth_helpers import update_last_login
from app.auth.helpers import sync_discord_for_user
from app.tasks.tasks_discord import assign_roles_to_player_task

logger = logging.getLogger(__name__)


@auth.route('/login', methods=['GET', 'POST'])
@transactional
def login():
    """
    Standard login route for email/password authentication.

    If a user is already logged in, it optionally triggers a Discord role sync.
    """
    logger.debug(f"Starting login route - Method: {request.method}")
    logger.debug(f"Next URL: {request.args.get('next')}")
    logger.debug(f"Current session: {session}")

    # Initialize form at the start to prevent UnboundLocalError
    form = LoginForm()

    try:
        if safe_current_user.is_authenticated:
            logger.debug("User already authenticated, redirecting to index")
            if safe_current_user.player and safe_current_user.player.discord_id:
                # Safely check for last_sync_attempt attribute
                last_sync = getattr(safe_current_user.player, 'last_sync_attempt', None)
                if not last_sync or (datetime.utcnow() - last_sync > timedelta(minutes=30)):
                    assign_roles_to_player_task.delay(player_id=safe_current_user.player.id)
                    logger.info(f"Triggered Discord role sync for player {safe_current_user.player.id}")
            return redirect(url_for('main.index'))

        form = LoginForm()

        if request.method == 'GET':
            logger.debug("GET request - rendering login form")
            return render_template('login_flowbite.html', title='Login', form=form)

        logger.debug("Processing login POST request")
        if not form.validate_on_submit():
            logger.debug(f"Form validation failed: {form.errors}")
            show_error('Please check your form inputs.')
            return render_template('login_flowbite.html', title='Login', form=form)

        email = form.email.data.lower()
        logger.debug(f"Attempting login for email: {email}")

        users = User.query.filter_by(email=email).all()
        if not users:
            logger.debug("No user found with provided email")
            show_error('Invalid email or password')
            return render_template('login_flowbite.html', title='Login', form=form)

        if len(users) > 1:
            logger.debug(f"Multiple users found for email {email}")
            players = Player.query.filter_by(email=email).all()
            problematic_players = [p for p in players if p.needs_manual_review]
            if problematic_players:
                show_warning('Multiple profiles found. Please contact an admin.')
                return render_template('login_flowbite.html', title='Login', form=form)

        user = users[0]
        logger.debug(f"Found user: {user.id}")

        if not user.check_password(form.password.data):
            logger.debug("Invalid password")
            show_error('Invalid email or password')
            return render_template('login_flowbite.html', title='Login', form=form)

        if not user.is_approved:
            logger.debug("User not approved")
            show_info('Your account is not approved yet.')
            return render_template('login_flowbite.html', title='Login', form=form)

        # If 2FA is enabled, redirect to 2FA verification.
        if user.is_2fa_enabled:
            logger.debug("2FA enabled, redirecting to verification")
            session['pending_2fa_user_id'] = user.id
            session['remember_me'] = form.remember.data
            session['next_url'] = request.args.get('next')
            return redirect(url_for('auth.verify_2fa_login'))

        try:
            if update_last_login(user):
                logger.debug("Updated last login successfully")
                # Sync Discord roles (if applicable)
                sync_discord_for_user(user)
                login_user(user, remember=form.remember.data)
                logger.debug(f"User {user.id} logged in successfully")

                # Set theme from user preferences if available
                try:
                    player = Player.query.get(user.id)
                    if player and hasattr(player, 'preferences') and player.preferences:
                        if 'theme' in player.preferences:
                            session['theme'] = player.preferences['theme']
                            logger.debug(f"Set theme to {player.preferences['theme']} from user preferences")
                except Exception as e:
                    logger.error(f"Error loading user theme preference: {e}")

                # Handle waitlist intent or next page redirect
                waitlist_intent = session.get('waitlist_intent')
                next_page = request.args.get('next') or session.get('next')

                # Clear session flags
                session.pop('waitlist_intent', None)
                session.pop('next', None)

                if waitlist_intent:
                    logger.debug("Waitlist intent detected, redirecting to waitlist register")
                    return redirect(url_for('auth.waitlist_register'))
                elif next_page and next_page.startswith('/') and not next_page.startswith('//') and not next_page.startswith('/login'):
                    logger.debug(f"Redirecting to next_page: {next_page}")
                    return redirect(next_page)

                logger.debug("Redirecting to index")
                return redirect(url_for('main.index'))
            else:
                logger.error("Failed to update last login")
                show_error('Login failed. Please try again.')
                return render_template('login_flowbite.html', title='Login', form=form)

        except Exception as e:
            logger.error(f"Error during login: {str(e)}", exc_info=True)
            show_error('Login failed. Please try again.')
            return render_template('login_flowbite.html', title='Login', form=form)

    except Exception as e:
        logger.error(f"Unexpected error in login route: {str(e)}", exc_info=True)
        show_error('An unexpected error occurred. Please try again.')
        return render_template('login_flowbite.html', title='Login', form=form)


@auth.route('/auth-check')
def auth_check():
    """
    Debug route to check authentication status.
    """
    try:
        logger.debug("=== Auth Check Debug Info ===")
        logger.debug(f"User authenticated: {safe_current_user.is_authenticated}")
        logger.debug(f"Session data: {dict(session)}")
        logger.debug(f"Request headers: {dict(request.headers)}")
        logger.debug(f"Current user object: {safe_current_user}")
        logger.debug(f"Current app name: {current_app.name}")
        logger.debug(f"Login view: {current_app.login_manager.login_view}")
        logger.debug("=== End Auth Check ===")

        session['_permanent'] = True  # Ensure session persistence

        return jsonify({
            'authenticated': safe_current_user.is_authenticated,
            'user_id': safe_current_user.id if safe_current_user.is_authenticated else None,
            'session': dict(session),
            'login_view': current_app.login_manager.login_view,
            'needs_login': not safe_current_user.is_authenticated
        })
    except Exception as e:
        logger.error(f"Error in auth check: {e}", exc_info=True)
        return {'error': str(e)}, 500


@auth.route('/logout', methods=['POST'])
@login_required
def logout():
    """
    Log the user out and redirect to the login page.
    """
    logout_user()
    return redirect(url_for('auth.login'))


# Import warning helper for login route
from app.alert_helpers import show_warning
