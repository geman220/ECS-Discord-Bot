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
    # Set registration mode to False to indicate this is a login attempt
    session['discord_registration_mode'] = False 
    discord_login_url = (
        f"{DISCORD_OAUTH2_URL}?client_id={discord_client_id}"
        f"&redirect_uri={redirect_uri}&response_type=code&scope={scope}"
    )
    return redirect(discord_login_url)


@auth.route('/discord_register')
def discord_register():
    """
    Redirect the user to Discord's OAuth2 login page for registration.
    This uses the same OAuth2 flow but indicates registration intent
    """
    discord_client_id = current_app.config['DISCORD_CLIENT_ID']
    redirect_uri = url_for('auth.discord_callback', _external=True)
    scope = 'identify email'
    # Set registration mode to True to indicate this is a registration attempt
    session['discord_registration_mode'] = True
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

        # Get registration mode from session (default to False if not set)
        is_registration = session.get('discord_registration_mode', False)
        
        # Check if the user already exists
        user = db_session.query(User).filter(func.lower(User.email) == discord_email).first()
        
        # If user exists and this is a registration attempt
        if user and is_registration:
            flash('An account with this email already exists. Please login instead.', 'info')
            return redirect(url_for('auth.login'))
            
        # If user doesn't exist and this is a login attempt
        if not user and not is_registration:
            flash('No account found. Please register first.', 'info')
            # Redirect to registration with the same Discord auth data
            session['pending_discord_email'] = discord_email
            session['pending_discord_id'] = discord_id
            session['pending_discord_username'] = discord_username
            session['discord_registration_mode'] = True
            return redirect(url_for('auth.register_with_discord'))
            
        # If user doesn't exist and this is a registration attempt
        if not user and is_registration:
            # Store Discord info in session for registration flow
            session['pending_discord_email'] = discord_email
            session['pending_discord_id'] = discord_id
            session['pending_discord_username'] = discord_username
            
            # Proceed to Discord registration flow
            return redirect(url_for('auth.register_with_discord'))

        # User exists and this is a login attempt - normal login flow
        
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
        
        # Clear any registration mode flag
        session.pop('discord_registration_mode', None)
        
        return redirect(url_for('main.index'))

    except Exception as e:
        logger.error(f"Discord auth error: {str(e)}", exc_info=True)
        flash('Authentication failed.', 'danger')
        return redirect(url_for('auth.login'))


@auth.route('/register_with_discord', methods=['GET', 'POST'])
@transactional
def register_with_discord():
    """
    Handle the registration process for users authenticating with Discord.
    
    This route checks if the user is in the Discord server,
    invites them if needed, assigns the SUB role, and creates
    a new user account with appropriate Discord association.
    """
    import aiohttp
    import asyncio
    from app.discord_utils import assign_role_to_member, invite_user_to_server
    from app.utils.discord_request_handler import make_discord_request

    db_session = g.db_session
    discord_email = session.get('pending_discord_email')
    discord_id = session.get('pending_discord_id')
    discord_username = session.get('pending_discord_username')
    
    if not discord_email or not discord_id:
        flash('Missing Discord information. Please try again.', 'danger')
        return redirect(url_for('auth.login'))
    
    if request.method == 'GET':
        return render_template('register_discord.html', 
                              title='Complete Registration',
                              discord_email=discord_email,
                              discord_username=discord_username)
    
    try:
        # Create a new event loop for async operations
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Check if user is in the Discord server
        async def check_server_membership():
            async with aiohttp.ClientSession() as session:
                # Check if the user is already in the server
                url = f"{current_app.config['BOT_API_URL']}/guilds/{current_app.config['SERVER_ID']}/members/{discord_id}"
                result = await make_discord_request('GET', url, session)
                
                if not result:
                    # User is not in the server, invite them
                    try:
                        invite_result = await invite_user_to_server(discord_id)
                        if invite_result.get('success'):
                            # Store the invite link or code in the Flask session for later use
                            from flask import session as flask_session
                            if invite_result.get('invite_code'):
                                invite_code = invite_result.get('invite_code')
                                flask_session['discord_invite_link'] = f"https://discord.gg/{invite_code}"
                                logger.info(f"Created personalized Discord invite: https://discord.gg/{invite_code}")
                            elif invite_result.get('invite_link'):
                                flask_session['discord_invite_link'] = invite_result.get('invite_link')
                                logger.info(f"Using generic Discord invite: {invite_result.get('invite_link')}")
                        else:
                            logger.warning(f"Could not invite user to Discord server: {invite_result.get('message')}")
                            # Continue despite invite failure - we'll show a message to the user later
                    except Exception as e:
                        logger.error(f"Error inviting user to Discord server: {str(e)}")
                        # Continue despite invite failure - we'll handle Discord role assignment separately
                
                # Try to assign the SUB role (ID: 1357770021157212430)
                try:
                    sub_role_id = "1357770021157212430"
                    await assign_role_to_member(
                        int(current_app.config['SERVER_ID']), 
                        discord_id, 
                        sub_role_id, 
                        session
                    )
                    logger.info(f"Successfully assigned SUB role to Discord user {discord_id}")
                except Exception as e:
                    logger.error(f"Error assigning SUB role to Discord user {discord_id}: {str(e)}")
                    # Continue despite role assignment failure - registration can still proceed
                
                return {'success': True}
        
        try:
            discord_result = loop.run_until_complete(check_server_membership())
            loop.close()
            
            # Log Discord integration status but continue regardless
            if not discord_result.get('success'):
                logger.warning(f"Discord integration warning: {discord_result.get('message')}")
                flash("Discord integration had some issues. You have been registered, but you may need to join the Discord server manually.", 'warning')
        except Exception as e:
            logger.error(f"Error with Discord server integration: {str(e)}")
            flash("Could not connect to Discord server. Your account will be created, but you'll need to join the Discord server manually.", 'warning')
        
        # Find the SUB role in database
        sub_role = db_session.query(Role).filter_by(name='SUB').first()
        if not sub_role:
            # Create the role if it doesn't exist
            sub_role = Role(name='SUB', description='Substitute Player')
            db_session.add(sub_role)
            db_session.flush()
        
        # Create the user
        username = discord_username.split('#')[0] if '#' in discord_username else discord_username
        # Generate a random password - user can reset it later
        import secrets
        import string
        temp_password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))
        
        new_user = User(
            username=username,
            email=discord_email,
            is_approved=True,  # Auto-approve Discord users
            roles=[sub_role]   # Assign SUB role
        )
        new_user.set_password(temp_password)
        db_session.add(new_user)
        db_session.flush()
        
        # Create a player record linked to the user
        player = Player(
            name=username,
            user_id=new_user.id,
            discord_id=discord_id,
            is_current_player=True
        )
        db_session.add(player)
        db_session.flush()
        
        # Log in the user
        login_user(new_user)
        
        # Clear session variables
        session.pop('pending_discord_email', None)
        session.pop('pending_discord_id', None)
        session.pop('pending_discord_username', None)
        
        # Ensure onboarding flags are properly set to trigger the onboarding modal
        new_user.has_completed_onboarding = False
        new_user.has_skipped_profile_creation = False
        new_user.has_completed_tour = False
        db_session.add(new_user)
        db_session.commit()  # Commit to ensure all flags are saved
        
        # Use flask.session to avoid confusion with SQLAlchemy session
        from flask import session as flask_session
        
        # Set session flag to ensure onboarding is shown
        flask_session['force_onboarding'] = True
        
        # Set Discord server invite information in the session
        default_invite_link = "https://discord.gg/weareecs"
        flask_session['discord_invite_link'] = default_invite_link
        flask_session['needs_discord_join'] = True
        
        flash('Registration successful! Please join our Discord server and complete your profile.', 'success')
        # Redirect to dedicated onboarding page instead of index
        return redirect(url_for('main.onboarding'))
        
    except Exception as e:
        logger.error(f"Discord registration error: {str(e)}", exc_info=True)
        flash('Registration failed. Please try again later.', 'danger')
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
# Role Management Routes
# ----------------------------------------------------------------------
@auth.route('/sync_discord_roles', methods=['POST'])
@login_required
@transactional
def sync_discord_roles():
    """
    Force a full sync of Discord roles for the currently logged-in user.
    This will properly add and remove roles based on the user's current status.
    """
    user = safe_current_user
    if not user or not user.player or not user.player.discord_id:
        flash('No Discord account linked to your profile.', 'warning')
        return redirect(url_for('main.index'))
    
    # Trigger a complete role sync (not just adding roles)
    assign_roles_to_player_task.delay(player_id=user.player.id, only_add=False)
    logger.info(f"Triggered complete Discord role sync for player {user.player.id}")
    
    flash('Discord roles sync requested. Changes should take effect within a minute.', 'success')
    return redirect(url_for('main.index'))


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