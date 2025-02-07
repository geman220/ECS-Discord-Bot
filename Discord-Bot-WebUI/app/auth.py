import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

from flask import (
    Blueprint, render_template, redirect, url_for, flash, 
    request, current_app, jsonify, session, g, session as flask_session
)
from flask_login import login_user, logout_user, login_required
from sqlalchemy import func
from itsdangerous import URLSafeTimedSerializer
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload

from app.models import User, Role, Player, League, Team
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
# 1) HELPER FUNCTION: Central point for linking Discord + assigning roles
# ----------------------------------------------------------------------
def sync_discord_for_user(user: User, discord_id: Optional[str] = None):
    """
    Ensures the user's discord_id is set if missing, then triggers
    a Celery task to assign roles to that user on Discord.
    
    NOTE: We are intentionally *only adding roles* within the Celery task
    so we don't remove any roles that exist outside our app.
    """
    db_session = g.db_session  # from @transactional or Flask global

    # Safety check
    if not user:
        return

    # If there's no Player record or no new Discord ID, do nothing special
    if not user.player:
        return

    # Link the Discord ID if it's missing
    if not user.player.discord_id and discord_id:
        user.player.discord_id = discord_id
        db_session.add(user.player)
        logger.info(f"Linked discord_id={discord_id} to player {user.player.id}")

    # Kick off the Celery task to (re)assign roles. This only *adds* our relevant roles.
    assign_roles_to_player_task.delay(player_id=user.player.id, only_add=True)
    logger.info(f"Triggered Discord role sync for player {user.player.id} (only_add=True)")


# ----------------------------------------------------------------------
# 2) DISCORD AUTH ROUTES
# ----------------------------------------------------------------------
@auth.route('/discord_login')
def discord_login():
    """Redirects user to Discord's OAuth2 page."""
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
    """Handles the OAuth2 callback from Discord."""
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

        if not discord_email:
            flash('Unable to access Discord email.', 'danger')
            return redirect(url_for('auth.login'))

        user = db_session.query(User).filter(func.lower(User.email) == discord_email).first()
        if not user:
            # If no user in the DB with that email, go to the verification/purchase check
            return redirect(url_for('auth.verify_purchase', 
                                    discord_email=discord_email, 
                                    discord_id=discord_id))

        # ---------------------
        # Link + Assign Roles
        # ---------------------
        sync_discord_for_user(user, discord_id)

        # If user has 2FA turned on, route them to 2FA check
        if user.is_2fa_enabled:
            flask_session['pending_2fa_user_id'] = user.id
            flask_session['remember_me'] = False
            return redirect(url_for('auth.verify_2fa_login'))

        # Otherwise, log them in normally
        user.last_login = datetime.utcnow()
        login_user(user)
        
        return redirect(url_for('main.index'))

    except Exception as e:
        logger.error(f"Discord auth error: {str(e)}", exc_info=True)
        flash('Authentication failed.', 'danger')
        return redirect(url_for('auth.login'))


@auth.route('/verify_purchase', methods=['GET', 'POST'])
@transactional
def verify_purchase():
    """
    If a user doesn't exist in the DB but we have a Discord email,
    ask them for a WooCommerce Order ID to verify purchase,
    then link the user if found.
    """
    session_db = g.db_session  # Avoid shadowing "session"
    discord_email = request.args.get('discord_email')
    discord_id = request.args.get('discord_id')

    if request.method == 'POST':
        order_id = request.form.get('order_id')
        
        order_info = fetch_order_by_id(order_id)
        if not order_info:
            flash('Invalid Order ID or order not found.', 'danger')
            return redirect(url_for('auth.verify_purchase'))

        woo_email = order_info['billing'].get('email')
        user = User.query.filter_by(email=woo_email).first()

        if user:
            if user.player and not user.player.discord_id:
                user.player.discord_id = discord_id
                user.email = discord_email
                session_db.add(user.player)
                session_db.add(user)

                # Roles assignment
                assign_roles_to_player_task.delay(player_id=user.player.id)
                logger.info(f"Linked Discord after purchase verification for player {user.player.id}")

                flash('Purchase verified and Discord account linked.', 'success')
                login_user(user)
                return redirect(url_for('main.index'))
            else:
                flash('Player profile not found or Discord already linked.', 'danger')
        else:
            flash('No matching user account found.', 'danger')

    return render_template('verify_purchase.html')


# ----------------------------------------------------------------------
# 3) STANDARD LOGIN
# ----------------------------------------------------------------------
@auth.route('/login', methods=['GET', 'POST'])
@transactional
def login():
    logger.debug(f"Starting login route - Method: {request.method}")
    logger.debug(f"Next URL: {request.args.get('next')}")
    logger.debug(f"Current session: {session}")
   
    try:
        # If user is already logged in, check whether we should re-sync roles
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
            return render_template('login.html', form=form)
           
        logger.debug("Processing login POST request")
        if not form.validate_on_submit():
            logger.debug(f"Form validation failed: {form.errors}")
            flash('Please check your form inputs.', 'danger')
            return render_template('login.html', form=form)
           
        email = form.email.data.lower()
        logger.debug(f"Attempting login for email: {email}")
       
        users = User.query.filter_by(email=email).all()
        if not users:
            logger.debug("No user found with provided email")
            flash('Invalid email or password', 'danger')
            return render_template('login.html', form=form)
           
        if len(users) > 1:
            logger.debug(f"Multiple users found for email {email}")
            players = Player.query.filter_by(email=email).all()
            problematic_players = [p for p in players if p.needs_manual_review]
            if problematic_players:
                flash('Multiple profiles found. Please contact an admin.', 'warning')
                return render_template('login.html', form=form)
               
        user = users[0]
        logger.debug(f"Found user: {user.id}")
       
        if not user.check_password(form.password.data):
            logger.debug("Invalid password")
            flash('Invalid email or password', 'danger')
            return render_template('login.html', form=form)
           
        if not user.is_approved:
            logger.debug("User not approved")
            flash('Your account is not approved yet.', 'info')
            return render_template('login.html', form=form)
           
        # If 2FA enabled, route to 2FA
        if user.is_2fa_enabled:
            logger.debug("2FA enabled, redirecting to verification")
            session['pending_2fa_user_id'] = user.id
            session['remember_me'] = form.remember.data
            session['next_url'] = request.args.get('next')
            return redirect(url_for('auth.verify_2fa_login'))
       
        try:
            # If we can update last_login, proceed
            if update_last_login(user):
                logger.debug("Updated last login successfully")

                # Use our central sync helper to link Discord (if needed) + assign roles
                # Because in a normal form-based login, we typically don't get a new discord_id here
                # But if user.player.discord_id is already set, we'll just assign roles
                sync_discord_for_user(user)

                # Log them in
                login_user(user, remember=form.remember.data)
                logger.debug(f"User {user.id} logged in successfully")
               
                # handle "next" page
                next_page = request.args.get('next')
                if next_page:
                    if next_page.startswith('/') and not next_page.startswith('//'):
                        if not next_page.startswith('/login'):
                            logger.debug(f"Redirecting to next_page: {next_page}")
                            return redirect(next_page)
               
                logger.debug("Redirecting to index")
                return redirect(url_for('main.index'))
            else:
                logger.error("Failed to update last login")
                flash('Login failed. Please try again.', 'danger')
                return render_template('login.html', form=form)
               
        except Exception as e:
            logger.error(f"Error during login: {str(e)}", exc_info=True)
            flash('Login failed. Please try again.', 'danger')
            return render_template('login.html', form=form)
           
    except Exception as e:
        logger.error(f"Unexpected error in login route: {str(e)}", exc_info=True)
        flash('An unexpected error occurred. Please try again.', 'danger')
        return render_template('login.html', form=form)


# ----------------------------------------------------------------------
# 4) 2FA VERIFICATION
# ----------------------------------------------------------------------
@auth.route('/verify_2fa_login', methods=['GET', 'POST'])
@transactional
def verify_2fa_login():
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

            # Once TOTP is valid, unify the "link + role sync"
            sync_discord_for_user(user)

            # Then finalize the login
            login_user(user, remember=session.get('remember_me', False))
            session.pop('pending_2fa_user_id', None)
            session.pop('remember_me', None)
            return redirect(url_for('main.index'))

        flash('Invalid 2FA token.', 'danger')

    return render_template('verify_2fa.html', form=form)


# ----------------------------------------------------------------------
# 5) MISC ROUTES / FORGOT PASSWORD / REGISTER / ETC
# ----------------------------------------------------------------------
@auth.route('/auth-check')
def auth_check():
    """Debug route to check authentication status."""
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
            
    return render_template('register.html', form=form)


@auth.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
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

    return render_template('forgot_password.html', form=form)


@auth.route('/reset_password/<token>', methods=['GET', 'POST'])
@transactional
def reset_password_token(token):
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

    return render_template('reset_password.html', form=form, token=token)


@auth.route('/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))


# Error handlers
@auth.errorhandler(404)
def not_found_error(error):
    logger.error(f"404 error: {error}")
    return render_template('404.html'), 404

@auth.errorhandler(500)
def internal_error(error):
    logger.error(f"500 error: {error}")
    return render_template('500.html'), 500
