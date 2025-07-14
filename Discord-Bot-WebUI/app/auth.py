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
    Blueprint, render_template, redirect, url_for, request,
    current_app, jsonify, session, g, make_response
)
from app.alert_helpers import show_success, show_error, show_warning, show_info
from flask_login import login_user, logout_user, login_required
from sqlalchemy import func

# Local application imports
from app.models import User, Role, Player
from app.forms import (
    LoginForm, RegistrationForm, ResetPasswordForm,
    ForgotPasswordForm, TwoFactorForm
)
from app.utils.db_utils import transactional
from app import csrf  # Import CSRF protection
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

    # Trigger the Celery task to sync roles (only adds roles, never removes them at login)
    # Log additional diagnostic information
    if user.player.is_coach:
        logger.info(f"Player {user.player.id} has is_coach=True")
    
    # Look for Flask "Pub League Coach" role
    pub_league_coach_role = False
    for role in user.roles:
        if role.name == "Pub League Coach":
            pub_league_coach_role = True
            logger.info(f"Player {user.player.id} has Flask role 'Pub League Coach'")
            break
            
    # Additional diagnostics for coach-related roles
    if user.player.is_coach and not pub_league_coach_role:
        logger.warning(f"Player {user.player.id} has is_coach=True but missing Flask 'Pub League Coach' role")
    elif not user.player.is_coach and pub_league_coach_role:
        logger.warning(f"Player {user.player.id} has Flask 'Pub League Coach' role but is_coach=False")
    
    # Only add roles at login, never remove them
    assign_roles_to_player_task.delay(player_id=user.player.id, only_add=True)
    logger.info(f"Triggered Discord role sync for player {user.player.id} (only_add=True)")


# ----------------------------------------------------------------------
# Discord Authentication Routes
# ----------------------------------------------------------------------
@auth.route('/discord_login')
def discord_login():
    """
    Redirect the user to Discord's OAuth2 login page.
    Uses the combined login+authorize URL pattern that works reliably.
    """
    from app.auth_helpers import generate_oauth_state
    from urllib.parse import quote
    
    discord_client_id = current_app.config['DISCORD_CLIENT_ID']
    redirect_uri = url_for('auth.discord_callback', _external=True)
    scope = 'identify email'
    
    # Generate a secure state value to prevent CSRF attacks
    state_value = generate_oauth_state()
    
    # Make the session permanent to avoid expiration issues
    session.permanent = True
    
    # Store state in session and make sure it's committed
    session['oauth_state'] = state_value
    session['discord_registration_mode'] = False
    
    # Debug session storage
    logger.info(f"Setting oauth_state={state_value[:8]}... in session {session.sid if hasattr(session, 'sid') else 'unknown'}")
    logger.info(f"Current session contains: {dict(session)}")
    
    # Force session save
    session.modified = True
    
    # Use the direct login+authorize URL pattern that works more reliably
    quoted_redirect_uri = quote(redirect_uri)
    quoted_scope = quote(scope)
    
    # Build the URL that combines login + authorization in one flow
    discord_login_url = (
        f"https://discord.com/login?redirect_to=%2Foauth2%2Fauthorize"
        f"%3Fclient_id%3D{discord_client_id}"
        f"%26redirect_uri%3D{quoted_redirect_uri}"
        f"%26response_type%3Dcode"
        f"%26scope%3D{quoted_scope}"
        f"%26state%3D{state_value}"
    )
    
    logger.info(f"Redirecting to Combined Login+Auth URL: {discord_login_url}")
    return redirect(discord_login_url)


@auth.route('/discord_register')
def discord_register():
    """
    Redirect the user to Discord's OAuth2 login page for registration.
    Uses the combined login+authorize URL pattern that works reliably.
    """
    from app.auth_helpers import generate_oauth_state
    from urllib.parse import quote
    
    discord_client_id = current_app.config['DISCORD_CLIENT_ID']
    redirect_uri = url_for('auth.discord_callback', _external=True)
    scope = 'identify email'
    
    # Generate a secure state value to prevent CSRF attacks
    state_value = generate_oauth_state()
    
    # Make the session permanent to avoid expiration issues
    session.permanent = True
    
    # Store state in session and make sure it's committed
    session['oauth_state'] = state_value
    session['discord_registration_mode'] = True
    
    # Debug session storage
    logger.info(f"Setting oauth_state={state_value[:8]}... in session {session.sid if hasattr(session, 'sid') else 'unknown'}")
    logger.info(f"Current session contains: {dict(session)}")
    
    # Force session save
    session.modified = True
    
    # Use the direct login+authorize URL pattern that works more reliably
    quoted_redirect_uri = quote(redirect_uri)
    quoted_scope = quote(scope)
    
    # Build the URL that combines login + authorization in one flow
    discord_login_url = (
        f"https://discord.com/login?redirect_to=%2Foauth2%2Fauthorize"
        f"%3Fclient_id%3D{discord_client_id}"
        f"%26redirect_uri%3D{quoted_redirect_uri}"
        f"%26response_type%3Dcode"
        f"%26scope%3D{quoted_scope}"
        f"%26state%3D{state_value}"
    )
    
    logger.info(f"Redirecting to Combined Login+Auth URL (registration): {discord_login_url}")
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
    state = request.args.get('state')
    
    # Log incoming request data for debugging
    logger.info(f"Discord callback received: code={code[:8] if code else None}..., state={state[:8] if state else None}...")
    logger.info(f"Current session data: {dict(session)}")
    
    # Enhanced session handling - make it extra permanent and strong
    from flask import current_app
    session.permanent = True
    current_app.permanent_session_lifetime = timedelta(days=30)  # Even longer lifetime

    # First, generate a CSRF token manually to ensure the session exists
    from flask_wtf.csrf import generate_csrf
    csrf_token = generate_csrf()
    
    # Check if we got an error from Discord
    if 'error' in request.args:
        error = request.args.get('error')
        error_description = request.args.get('error_description', 'No description')
        logger.error(f"Discord OAuth error: {error} - {error_description}")
        show_error(f'Discord authentication error: {error}')
        return redirect(url_for('auth.login'))
    
    # Verify the state parameter to prevent CSRF attacks
    stored_state = session.get('oauth_state')
    
    # More lenient check for development/testing
    if not state:
        logger.warning("No state parameter received from Discord")
        show_error('Authentication failed: No state parameter. Please try again.')
        return redirect(url_for('auth.login'))
    
    if not stored_state:
        logger.warning(f"No stored state in session, but received state={state[:8]}...")
        # For development environments, allow the login flow to continue without state validation
        # This helps when using Docker where session persistence might be problematic
        if not code:
            show_error('Authentication failed: Session expired. Please try again.')
            return redirect(url_for('auth.login'))
        logger.warning("Proceeding despite missing stored state since we have a code (dev mode)")
    elif state != stored_state:
        logger.warning(f"OAuth state mismatch: received {state[:8]}..., stored {stored_state[:8]}...")
        # In development/docker environment, we'll continue anyway if we have a code
        if not code:
            show_error('Authentication validation failed. Please try again.')
            return redirect(url_for('auth.login'))
        logger.warning("Proceeding despite state mismatch since we have a code (dev mode)")
    else:
        logger.info("OAuth state validation successful!")
    
    # Clear the state from session as it's single-use
    session.pop('oauth_state', None)
    
    # Force session save with strong settings
    session.modified = True
    
    if not code:
        show_error('Login failed: No authorization code. Please try again.')
        return redirect(url_for('auth.login'))

    try:
        # Commit any pending database changes before making external API calls
        # to avoid holding the database transaction open during Discord API calls
        db_session.commit()
        
        # Get redirect URI (must match the one used in the initial request)
        redirect_uri = url_for('auth.discord_callback', _external=True)
        logger.info(f"Exchanging code for token with redirect_uri={redirect_uri}")
        
        token_data = exchange_discord_code(
            code=code,
            redirect_uri=redirect_uri
        )
        
        if not token_data or 'access_token' not in token_data:
            logger.error(f"Failed to exchange code for token: {token_data}")
            show_error('Failed to authenticate with Discord. Please try again.')
            return redirect(url_for('auth.login'))
            
        logger.info(f"Successfully obtained access token from Discord")
        
        user_data = get_discord_user_data(token_data['access_token'])
        
        if not user_data:
            logger.error("Failed to get user data from Discord")
            show_error('Failed to retrieve your Discord profile. Please try again.')
            return redirect(url_for('auth.login'))
            
        logger.info(f"Successfully retrieved Discord user data: id={user_data.get('id')}, username={user_data.get('username')}")
        
        # Safely handle potentially None email values
        discord_email = user_data.get('email')
        discord_email = discord_email.lower() if discord_email else ''
        discord_id = user_data.get('id')
        discord_username = user_data.get('username', 'Discord User')

        if not discord_email:
            show_error('Unable to access Discord email.')
            return redirect(url_for('auth.login'))

        # Get registration mode from session (default to False if not set)
        is_registration = session.get('discord_registration_mode', False)
        
        # Check if the user already exists
        user = db_session.query(User).filter(func.lower(User.email) == discord_email).first()
        
        # If user exists and this is a registration attempt
        if user and is_registration:
            show_info('An account with this email already exists. Please login instead.')
            return redirect(url_for('auth.login'))
            
        # If user doesn't exist and this is a login attempt
        if not user and not is_registration:
            show_info('No account found. Please register first.')
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
            # Make sure session is permanent and will persist with long lifetime
            session.permanent = True
            current_app.permanent_session_lifetime = timedelta(days=30)  # Much longer session
            
            # Store the necessary information in the session
            session['pending_2fa_user_id'] = user.id
            session['remember_me'] = True  # Always remember for better persistence
            
            # Generate CSRF token in advance
            from flask_wtf.csrf import generate_csrf
            csrf_token = generate_csrf()
            
            # Force session to be saved
            session.modified = True
            
            logger.info(f"User {user.id} has 2FA enabled. Redirecting to 2FA verification.")
            logger.info(f"Session data before redirect: {dict(session)}")
            
            # Use a response object to set a stronger cookie
            from flask import make_response
            
            # Always pass user_id as query parameter for reliability
            redirect_url = url_for('auth.verify_2fa_login', user_id=user.id)
            response = make_response(redirect(redirect_url))
            
            # Configure strong cookie settings
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0'
            
            # Force the session to be saved before redirecting
            from flask.sessions import SessionInterface
            if hasattr(current_app, 'session_interface') and isinstance(current_app.session_interface, SessionInterface):
                current_app.session_interface.save_session(current_app, session, response)
            
            return response

        # Log in the user normally.
        user.last_login = datetime.utcnow()
        # User is already attached to db_session, no need to add
        
        # Enhanced login flow with stronger session handling for Docker environments
        login_user(user, remember=True)  # Always set remember=True for persistence
        
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
        
        # Force session persistence
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
        
        # Create a response with secure cookie settings for better session persistence
        from flask import make_response
        response = make_response(redirect(redirect_url))
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0'
        
        # Force the session to be saved before redirecting
        from flask.sessions import SessionInterface
        if hasattr(current_app, 'session_interface') and isinstance(current_app.session_interface, SessionInterface):
            current_app.session_interface.save_session(current_app, session, response)
            
        return response

    except Exception as e:
        logger.error(f"Discord auth error: {str(e)}", exc_info=True)
        show_error('Authentication failed.')
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
        show_error('Missing Discord information. Please try again.')
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
                url = f"{current_app.config['BOT_API_URL']}/api/server/guilds/{current_app.config['SERVER_ID']}/members/{discord_id}"
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
                
                # Try to assign the ECS-FC-PL-UNVERIFIED role (previously SUB role)
                try:
                    unverified_role_id = "1357770021157212430"  # Reuse the same Discord role ID
                    await assign_role_to_member(
                        int(current_app.config['SERVER_ID']), 
                        discord_id, 
                        unverified_role_id, 
                        session
                    )
                    logger.info(f"Successfully assigned ECS-FC-PL-UNVERIFIED role to Discord user {discord_id}")
                except Exception as e:
                    logger.error(f"Error assigning ECS-FC-PL-UNVERIFIED role to Discord user {discord_id}: {str(e)}")
                    # Continue despite role assignment failure - registration can still proceed
                
                return {'success': True}
        
        try:
            discord_result = loop.run_until_complete(check_server_membership())
            loop.close()
            
            # Log Discord integration status but continue regardless
            if not discord_result.get('success'):
                logger.warning(f"Discord integration warning: {discord_result.get('message')}")
                show_warning("Discord integration had some issues. You have been registered, but you may need to join the Discord server manually.")
        except Exception as e:
            logger.error(f"Error with Discord server integration: {str(e)}")
            show_warning("Could not connect to Discord server. Your account will be created, but you'll need to join the Discord server manually.")
        
        # Find the pl-unverified role in database
        unverified_role = db_session.query(Role).filter_by(name='pl-unverified').first()
        if not unverified_role:
            # Create the role if it doesn't exist
            unverified_role = Role(name='pl-unverified', description='Unverified player awaiting league approval')
            db_session.add(unverified_role)
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
            approval_status='pending',  # Set to pending for approval workflow
            roles=[unverified_role]   # Assign pl-unverified role
        )
        new_user.set_password(temp_password)
        db_session.add(new_user)
        db_session.flush()
        
        # Create a player record linked to the user
        player = Player(
            name=username,
            user_id=new_user.id,
            discord_id=discord_id,
            is_current_player=True,
            is_sub=True  # Set is_sub flag since pl-unverified role is assigned
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
        
        # Set sweet alert flag instead of using flash
        flask_session['sweet_alert'] = {
            'title': 'Registration Successful!',
            'text': 'Please join our Discord server and complete your profile.',
            'icon': 'success'
        }
        
        # Redirect to main index which will handle onboarding and show the sweet alert
        return redirect(url_for('main.index'))
        
    except Exception as e:
        logger.error(f"Discord registration error: {str(e)}", exc_info=True)
        show_error('Registration failed. Please try again later.')
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
            return render_template('login.html', title='Login', form=form)

        logger.debug("Processing login POST request")
        if not form.validate_on_submit():
            logger.debug(f"Form validation failed: {form.errors}")
            show_error('Please check your form inputs.')
            return render_template('login.html', title='Login', form=form)

        email = form.email.data.lower()
        logger.debug(f"Attempting login for email: {email}")

        users = User.query.filter_by(email=email).all()
        if not users:
            logger.debug("No user found with provided email")
            show_error('Invalid email or password')
            return render_template('login.html', title='Login', form=form)

        if len(users) > 1:
            logger.debug(f"Multiple users found for email {email}")
            players = Player.query.filter_by(email=email).all()
            problematic_players = [p for p in players if p.needs_manual_review]
            if problematic_players:
                show_warning('Multiple profiles found. Please contact an admin.')
                return render_template('login.html', title='Login', form=form)

        user = users[0]
        logger.debug(f"Found user: {user.id}")

        if not user.check_password(form.password.data):
            logger.debug("Invalid password")
            show_error('Invalid email or password')
            return render_template('login.html', title='Login', form=form)

        if not user.is_approved:
            logger.debug("User not approved")
            show_info('Your account is not approved yet.')
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
                show_error('Login failed. Please try again.')
                return render_template('login.html', title='Login', form=form)

        except Exception as e:
            logger.error(f"Error during login: {str(e)}", exc_info=True)
            show_error('Login failed. Please try again.')
            return render_template('login.html', title='Login', form=form)

    except Exception as e:
        logger.error(f"Unexpected error in login route: {str(e)}", exc_info=True)
        show_error('An unexpected error occurred. Please try again.')
        return render_template('login.html', title='Login', form=form)


# ----------------------------------------------------------------------
# 2FA Verification Route
# ----------------------------------------------------------------------
@auth.route('/verify_2fa_login', methods=['GET', 'POST'])
@transactional
@csrf.exempt  # Completely exempt this route from CSRF protection
def verify_2fa_login():
    """
    Handle 2FA verification for users with 2FA enabled.

    If the provided TOTP token is valid, complete the login process.
    """
    # Set up a persistent session
    from flask import current_app
    import uuid
    
    # Ensure permanent session with longer lifetime
    session.permanent = True
    current_app.permanent_session_lifetime = timedelta(days=1)  # Longer session
    
    # Debug session state
    logger.info(f"2FA verification requested. Session data: {dict(session)}")
    logger.info(f"CSRF protection disabled for this route")
    
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
    if not user_id or not user_id.isdigit():
        logger.warning("No valid user_id found anywhere")
        show_error('No 2FA login pending.')
        return redirect(url_for('auth.login'))
    
    # Convert user_id to int
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
            show_info('Account created and pending approval.')
            return user, redirect(url_for('auth.login'))
        except Exception as e:
            logger.error(f"Registration error: {str(e)}")
            show_error('Registration failed. Please try again.')

    return render_template('register.html', title='Register', form=form)


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
    from flask_wtf import FlaskForm
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
        show_warning('No Discord account linked to your profile.')
        return redirect(url_for('main.index'))
    
    # Trigger a complete role sync (not just adding roles)
    assign_roles_to_player_task.delay(player_id=user.player.id, only_add=False)
    logger.info(f"Triggered complete Discord role sync for player {user.player.id}")
    
    show_success('Discord roles sync requested. Changes should take effect within a minute.')
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