# app/auth.py

"""
Authentication Module

This module defines the authentication blueprint for the application,
handling standard login, logout, registration, password resets, and Discord
OAuth2 authentication (including 2FA flows). It also includes helper functions
to sync Discord roles with the local user profile.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

# Third-party imports
from flask import (
    Blueprint, render_template, redirect, url_for, flash, request,
    current_app, jsonify, session, g
)
from flask_login import login_user, logout_user, login_required
from sqlalchemy import func

# Local application imports
from app.models import User, Role, Player
from app.forms import (
    LoginForm, RegistrationForm, ResetPasswordForm,
    ForgotPasswordForm, TwoFactorForm
)
from app.utils.db_utils import transactional
from app.utils.user_helpers import safe_current_user
from app.woocommerce import fetch_order_by_id
from app.tasks.tasks_discord import assign_roles_to_player_task
from app.auth_helpers import (
    generate_reset_token,
    verify_reset_token,
    send_reset_email,
    send_reset_confirmation_email,
    get_discord_user_data,
    exchange_discord_code,
    update_last_login,
    DISCORD_OAUTH2_URL
)

logger = logging.getLogger(__name__)
auth = Blueprint('auth', __name__)


# ----------------------------------------------------------------------
# Helper Functions
# ----------------------------------------------------------------------
def sync_discord_for_user(user: User, discord_id: Optional[str] = None):
    """
    Link a user's Discord account and trigger a Celery task to assign roles on Discord.

    This function checks if the player's Discord ID is missing and, if provided,
    updates it. Then, it triggers a task to add (but not remove) relevant roles.

    Args:
        user (User): The user instance.
        discord_id (Optional[str]): The Discord ID to link.
    """
    db_session = g.db_session  # from @transactional or Flask global

    if not user or not user.player:
        return

    # Link the Discord ID if it's missing and one is provided
    if not user.player.discord_id and discord_id:
        user.player.discord_id = discord_id
        db_session.add(user.player)
        logger.info(f"Linked discord_id={discord_id} to player {user.player.id}")

    # Trigger the Celery task to sync roles (only adds our roles)
    assign_roles_to_player_task.delay(player_id=user.player.id, only_add=True)
    logger.info(f"Triggered Discord role sync for player {user.player.id} (only_add=True)")


# ----------------------------------------------------------------------
# Discord Authentication Routes
# ----------------------------------------------------------------------
@auth.route('/discord_login')
def discord_login():
    """
    Redirect the user to Discord's OAuth2 login page.
    """
    discord_client_id = current_app.config['DISCORD_CLIENT_ID']
    redirect_uri = url_for('auth.discord_callback', _external=True)
    scope = 'identify email'
    discord_login_url = (
        f"{DISCORD_OAUTH2_URL}?client_id={discord_client_id}"
        f"&redirect_uri={redirect_uri}&response_type=code&scope={scope}"
    )
    return redirect(discord_login_url)


@auth.route('/discord_callback')
@transactional
def discord_callback():
    """
    Handle the Discord OAuth2 callback.

    This route exchanges the provided code for an access token, retrieves the user's
    Discord information, and either creates a new account (if needed) or logs the user in.
    It also initiates the sync of Discord roles.
    """
    db_session = g.db_session
    code = request.args.get('code')
    if not code:
        flash('Login failed. Please try again.', 'danger')
        return redirect(url_for('auth.login'))

    try:
        token_data = exchange_discord_code(
            code=code,
            redirect_uri=url_for('auth.discord_callback', _external=True)
        )
        user_data = get_discord_user_data(token_data['access_token'])
        discord_email = user_data.get('email', '').lower()
        discord_id = user_data.get('id')
        discord_username = user_data.get('username', 'Discord User')

        if not discord_email:
            flash('Unable to access Discord email.', 'danger')
            return redirect(url_for('auth.login'))

        user = db_session.query(User).filter(func.lower(User.email) == discord_email).first()
        if not user:
            # If user not found, route to purchase verification.
            return redirect(url_for('auth.verify_purchase',
                                    discord_email=discord_email,
                                    discord_username=discord_username,
                                    discord_id=discord_id))

        # Link Discord account and assign roles.
        sync_discord_for_user(user, discord_id)

        # If 2FA is enabled, store pending user info and redirect.
        if user.is_2fa_enabled:
            session['pending_2fa_user_id'] = user.id
            session['remember_me'] = False
            return redirect(url_for('auth.verify_2fa_login'))

        # Log in the user normally.
        user.last_login = datetime.utcnow()
        login_user(user)
        
        # Set theme from user preferences if available
        try:
            player = Player.query.get(user.id)
            if player and hasattr(player, 'preferences') and player.preferences:
                if 'theme' in player.preferences:
                    session['theme'] = player.preferences['theme']
                    logger.debug(f"Set theme to {player.preferences['theme']} from user preferences")
        except Exception as e:
            logger.error(f"Error loading user theme preference: {e}")
        
        return redirect(url_for('main.index'))

    except Exception as e:
        logger.error(f"Discord auth error: {str(e)}", exc_info=True)
        flash('Authentication failed.', 'danger')
        return redirect(url_for('auth.login'))


@auth.route('/verify_purchase', methods=['GET'])
@transactional
def verify_purchase():
    """
    Render the purchase verification page for new Discord users.

    This page is shown when a user authenticates via Discord and does not have
    an associated local account.
    """
    discord_email = request.args.get('discord_email', 'your Discord email')
    discord_username = request.args.get('discord_username', 'Discord User')
    return render_template('verify_purchase.html',
                           title='Discord Error',
                           discord_email=discord_email,
                           discord_username=discord_username)


# ----------------------------------------------------------------------
# Standard Login Routes
# ----------------------------------------------------------------------
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

    try:
        if safe_current_user.is_authenticated:
            logger.debug("User already authenticated, redirecting to index")
            if safe_current_user.player and safe_current_user.player.discord_id:
                last_sync = safe_current_user.player.last_sync_attempt
                if not last_sync or (datetime.utcnow() - last_sync > timedelta(minutes=30)):
                    assign_roles_to_player_task.delay(player_id=safe_current_user.player.id)
                    logger.info(f"Triggered Discord role sync for player {safe_current_user.player.id}")
            return redirect(url_for('main.index'))

        form = LoginForm()

        if request.method == 'GET':
            logger.debug("GET request - rendering login form")
            return render_template('login.html', title='Login', form=form)

        logger.debug("Processing login POST request")
        if not form.validate_on_submit():
            logger.debug(f"Form validation failed: {form.errors}")
            flash('Please check your form inputs.', 'danger')
            return render_template('login.html', title='Login', form=form)

        email = form.email.data.lower()
        logger.debug(f"Attempting login for email: {email}")

        users = User.query.filter_by(email=email).all()
        if not users:
            logger.debug("No user found with provided email")
            flash('Invalid email or password', 'danger')
            return render_template('login.html', title='Login', form=form)

        if len(users) > 1:
            logger.debug(f"Multiple users found for email {email}")
            players = Player.query.filter_by(email=email).all()
            problematic_players = [p for p in players if p.needs_manual_review]
            if problematic_players:
                flash('Multiple profiles found. Please contact an admin.', 'warning')
                return render_template('login.html', title='Login', form=form)

        user = users[0]
        logger.debug(f"Found user: {user.id}")

        if not user.check_password(form.password.data):
            logger.debug("Invalid password")
            flash('Invalid email or password', 'danger')
            return render_template('login.html', title='Login', form=form)

        if not user.is_approved:
            logger.debug("User not approved")
            flash('Your account is not approved yet.', 'info')
            return render_template('login.html', title='Login', form=form)

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

                next_page = request.args.get('next')
                if next_page and next_page.startswith('/') and not next_page.startswith('//') and not next_page.startswith('/login'):
                    logger.debug(f"Redirecting to next_page: {next_page}")
                    return redirect(next_page)

                logger.debug("Redirecting to index")
                return redirect(url_for('main.index'))
            else:
                logger.error("Failed to update last login")
                flash('Login failed. Please try again.', 'danger')
                return render_template('login.html', title='Login', form=form)

        except Exception as e:
            logger.error(f"Error during login: {str(e)}", exc_info=True)
            flash('Login failed. Please try again.', 'danger')
            return render_template('login.html', title='Login', form=form)

    except Exception as e:
        logger.error(f"Unexpected error in login route: {str(e)}", exc_info=True)
        flash('An unexpected error occurred. Please try again.', 'danger')
        return render_template('login.html', title='Login', form=form)


# ----------------------------------------------------------------------
# 2FA Verification Route
# ----------------------------------------------------------------------
@auth.route('/verify_2fa_login', methods=['GET', 'POST'])
@transactional
def verify_2fa_login():
    """
    Handle 2FA verification for users with 2FA enabled.

    If the provided TOTP token is valid, complete the login process.
    """
    if 'pending_2fa_user_id' not in session:
        flash('No 2FA login pending.', 'danger')
        return redirect(url_for('auth.login'))

    user = User.query.get(session['pending_2fa_user_id'])
    if not user:
        flash('Invalid user. Please log in again.', 'danger')
        return redirect(url_for('auth.login'))

    form = TwoFactorForm()
    if form.validate_on_submit():
        if user.verify_totp(form.token.data):
            user.last_login = datetime.utcnow()
            sync_discord_for_user(user)
            login_user(user, remember=session.get('remember_me', False))
            session.pop('pending_2fa_user_id', None)
            session.pop('remember_me', None)
            
            # Set theme from user preferences if available
            try:
                player = Player.query.get(user.id)
                if player and hasattr(player, 'preferences') and player.preferences:
                    if 'theme' in player.preferences:
                        session['theme'] = player.preferences['theme']
                        logger.debug(f"Set theme to {player.preferences['theme']} from user preferences")
            except Exception as e:
                logger.error(f"Error loading user theme preference: {e}")
            
            return redirect(url_for('main.index'))

        flash('Invalid 2FA token.', 'danger')

    return render_template('verify_2fa.html', title='Verify 2FA', form=form)


# ----------------------------------------------------------------------
# Miscellaneous Routes (Auth Check, Register, Password Reset)
# ----------------------------------------------------------------------
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


@auth.route('/register', methods=['GET', 'POST'])
@transactional
def register():
    """
    Handle user registration.

    Creates a new user account with the specified roles and sends a confirmation.
    """
    if safe_current_user.is_authenticated:
        return redirect(url_for('main.index'))

    form = RegistrationForm()
    if form.validate_on_submit():
        try:
            roles = Role.query.filter(Role.name.in_(form.roles.data)).all()
            user = User(
                username=form.username.data,
                email=form.email.data,
                is_approved=False,
                roles=roles
            )
            user.set_password(form.password.data)
            flash('Account created and pending approval.')
            return user, redirect(url_for('auth.login'))
        except Exception as e:
            logger.error(f"Registration error: {str(e)}")
            flash('Registration failed. Please try again.', 'danger')

    return render_template('register.html', title='Register', form=form)


@auth.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    """
    Handle forgot password requests.

    If an account exists for the given email, send a reset email.
    """
    if safe_current_user.is_authenticated:
        return redirect(url_for('main.index'))

    form = ForgotPasswordForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user:
            token = generate_reset_token(user)
            if token and send_reset_email(user.email, token):
                flash('Password reset instructions sent to your email.', 'info')
                return redirect(url_for('auth.login'))
        flash('No account found with that email.', 'danger')
        return redirect(url_for('auth.forgot_password'))

    return render_template('forgot_password.html', title='Forgot Password', form=form)


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
        flash('Invalid or expired reset link.', 'danger')
        return redirect(url_for('auth.forgot_password'))

    user = User.query.get(user_id)
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('auth.forgot_password'))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        try:
            user.set_password(form.password.data)
            if send_reset_confirmation_email(user.email):
                flash('Password updated successfully. Please log in.', 'success')
                return redirect(url_for('auth.login'))
        except Exception as e:
            logger.error(f"Password reset error: {str(e)}")
            flash('Password reset failed. Please try again.', 'danger')

    return render_template('reset_password.html', title='Reset Password', form=form, token=token)


@auth.route('/logout', methods=['POST'])
@login_required
def logout():
    """
    Log the user out and redirect to the login page.
    """
    logout_user()
    return redirect(url_for('auth.login'))


# ----------------------------------------------------------------------
# Error Handlers
# ----------------------------------------------------------------------
@auth.errorhandler(404)
def not_found_error(error):
    logger.error(f"404 error: {error}")
    return render_template('404.html', title='404',), 404


@auth.errorhandler(500)
def internal_error(error):
    logger.error(f"500 error: {error}")
    return render_template('500.html', title='500',), 500