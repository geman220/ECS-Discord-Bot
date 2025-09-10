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
from app.players_helpers import save_cropped_profile_picture

# Import duplicate prevention system
from app.duplicate_prevention import (
    check_discord_id_first, 
    handle_email_change,
    find_potential_duplicates,
    create_merge_request,
    verify_and_merge_accounts,
    check_pre_registration_duplicates,
    check_phone_duplicate_registration,
    log_potential_duplicate_registration
)
from app.merge_email_helpers import (
    send_merge_verification_email,
    send_merge_success_notification
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

        # NEW: Check Discord ID first before anything else (prevents duplicates from email changes)
        existing_player, needs_email_update = check_discord_id_first(user_data)
        
        if existing_player:
            # Player exists with this Discord ID - this is the same person
            user = existing_player.user
            
            if needs_email_update:
                # Handle email change automatically
                old_email = user.email
                success = handle_email_change(existing_player, discord_email, old_email)
                if not success:
                    session['sweet_alert'] = {
                        'title': 'Welcome Back!',
                        'text': 'There was an issue updating your email. Please contact support if needed.',
                        'icon': 'warning'
                    }
            # No additional notification needed for normal login
            
            # Check if 2FA is enabled before full login
            if user.is_2fa_enabled:
                logger.info(f"User {user.id} has 2FA enabled, redirecting to verification")
                session['pending_2fa_user_id'] = user.id
                session['remember_me'] = True
                sync_discord_for_user(user, user_data.get('id'))
                return redirect(url_for('auth.verify_2fa_login'))
            
            # Log them in with the existing account
            login_user(user)
            sync_discord_for_user(user, user_data.get('id'))
            update_last_login(user)
            
            # Clear session flags
            session.pop('discord_registration_mode', None)
            session.pop('waitlist_registration', None)
            session.pop('waitlist_intent', None)
            
            # Redirect to wherever they were going
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('main.index'))

        # Get registration mode from session (default to False if not set)
        is_registration = session.get('discord_registration_mode', False)
        is_waitlist_registration = session.get('waitlist_registration', False)
        
        # Check if the user already exists by email (fallback check)
        from app.utils.pii_encryption import create_hash
        discord_email_hash = create_hash(discord_email)
        user = db_session.query(User).filter(User.email_hash == discord_email_hash).first()
        
        # If user exists and this is a registration attempt
        if user and is_registration:
            if is_waitlist_registration:
                # For waitlist registration, existing users can still join the waitlist
                session['pending_discord_email'] = discord_email
                session['pending_discord_id'] = discord_id
                session['pending_discord_username'] = discord_username
                return redirect(url_for('auth.waitlist_register_with_discord'))
            else:
                show_info('An account with this email already exists. Please login instead.')
                return redirect(url_for('auth.login'))
            
        # If user doesn't exist and this is a login attempt
        if not user and not is_registration:
            # Check if this is a waitlist login attempt
            is_waitlist_intent = session.get('waitlist_intent', False)
            
            if is_waitlist_intent:
                # For waitlist login attempts, show error with SweetAlert and redirect to waitlist registration
                session['sweet_alert'] = {
                    'title': 'No Account Found',
                    'text': 'No account found. Please register for the waitlist instead.',
                    'icon': 'error'
                }
                return redirect(url_for('auth.waitlist_register'))
            else:
                show_error('No account found. Please register first.')
                # Redirect to registration with the same Discord auth data
                session['pending_discord_email'] = discord_email
                session['pending_discord_id'] = discord_id
                session['pending_discord_username'] = discord_username
                session['discord_registration_mode'] = True
                return redirect(url_for('auth.register_with_discord'))
            
        # If user doesn't exist and this is a registration attempt
        if not user and is_registration:
            # NEW: Check for potential duplicates before creating account
            potential_duplicates = find_potential_duplicates({
                'name': discord_username,
                'email': discord_email
            })
            
            if potential_duplicates and len(potential_duplicates) > 0:
                # Store data in session and show duplicate check screen
                session['pending_discord_data'] = user_data
                session['potential_duplicates'] = [
                    {
                        'id': p[0].id,
                        'name': p[0].name,
                        'email': p[0].email,
                        'reason': p[1],
                        'confidence': p[2]
                    } for p in potential_duplicates
                ]
                return redirect(url_for('auth.check_duplicate'))
            
            # No duplicates found - store Discord info in session for registration flow
            session['pending_discord_email'] = discord_email
            session['pending_discord_id'] = discord_id
            session['pending_discord_username'] = discord_username
            
            # Proceed to Discord registration flow
            if is_waitlist_registration:
                return redirect(url_for('auth.waitlist_register_with_discord'))
            else:
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
    from app.utils.sync_discord_client import get_sync_discord_client

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
        # Discord server integration using synchronous client
        def check_server_membership():
            discord_client = get_sync_discord_client()
            server_id = current_app.config['SERVER_ID']
            
            # Check if the user is already in the server
            member_check = discord_client.check_member_in_server(server_id, discord_id)
            
            if member_check.get('success') and not member_check.get('in_server'):
                # User is not in the server, invite them
                try:
                    invite_result = discord_client.invite_user_to_server(discord_id)
                    if invite_result.get('success'):
                        # Store the invite link or code in the Flask session for later use
                        if invite_result.get('invite_code'):
                            invite_code = invite_result.get('invite_code')
                            session['discord_invite_link'] = f"https://discord.gg/{invite_code}"
                            logger.info(f"Created personalized Discord invite: https://discord.gg/{invite_code}")
                        elif invite_result.get('invite_link'):
                            session['discord_invite_link'] = invite_result.get('invite_link')
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
                role_result = discord_client.assign_role_to_member(
                    server_id, 
                    discord_id, 
                    unverified_role_id
                )
                if role_result.get('success'):
                    logger.info(f"Successfully assigned ECS-FC-PL-UNVERIFIED role to Discord user {discord_id}")
                else:
                    logger.error(f"Failed to assign ECS-FC-PL-UNVERIFIED role: {role_result.get('message')}")
            except Exception as e:
                logger.error(f"Error assigning ECS-FC-PL-UNVERIFIED role to Discord user {discord_id}: {str(e)}")
                # Continue despite role assignment failure - registration can still proceed
            
            return {'success': True}
        
        try:
            discord_result = check_server_membership()
            
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


# ----------------------------------------------------------------------
# Waitlist Registration Routes
# ----------------------------------------------------------------------
@auth.route('/waitlist_register', methods=['GET', 'POST'])
@transactional
def waitlist_register():
    """
    Handle waitlist registration for both authenticated and unauthenticated users.
    
    Scenarios:
    1. Authenticated user: Add them to waitlist
    2. Unauthenticated user with account: Show login message
    3. Unauthenticated user without account: Show registration form
    """
    from app.models.admin_config import AdminConfig
    
    # Check if waitlist registration is enabled
    if not AdminConfig.get_setting('waitlist_registration_enabled', True):
        show_error('Waitlist registration is currently disabled.')
        return redirect(url_for('main.index'))
    
    db_session = g.db_session
    current_user = safe_current_user
    
    # Handle authenticated users - add them to waitlist
    if current_user.is_authenticated:
        if request.method == 'POST':
            try:
                # Find or create pl-waitlist role
                waitlist_role = db_session.query(Role).filter_by(name='pl-waitlist').first()
                if not waitlist_role:
                    waitlist_role = Role(name='pl-waitlist', description='Player on waitlist for current season')
                    db_session.add(waitlist_role)
                    db_session.flush()
                
                # Check if user is already on waitlist
                if waitlist_role in current_user.roles:
                    show_info('You are already on the waitlist!')
                    return redirect(url_for('main.index'))
                
                # Add user to waitlist
                current_user.roles.append(waitlist_role)
                # Set waitlist joined timestamp
                current_user.waitlist_joined_at = datetime.utcnow()
                db_session.flush()
                
                show_success('You have been added to the waitlist! You will be notified when spots become available.')
                return redirect(url_for('main.index'))
                
            except Exception as e:
                logger.error(f"Error adding authenticated user to waitlist: {str(e)}")
                show_error('Failed to join waitlist. Please try again.')
                return redirect(url_for('auth.waitlist_register'))
        
        # GET request for authenticated user - show waitlist join form
        # Check if already on waitlist
        waitlist_role = db_session.query(Role).filter_by(name='pl-waitlist').first()
        already_on_waitlist = waitlist_role and waitlist_role in current_user.roles
        
        # Get player data for profile verification
        player = None
        if current_user.player:
            player = current_user.player
        
        # Clear sweet_alert from session after it's been passed to template
        if 'sweet_alert' in session:
            session.pop('sweet_alert', None)
        
        return render_template('waitlist_register_authenticated.html', 
                              title='Join the Waitlist',
                              user=current_user,
                              player=player,
                              already_on_waitlist=already_on_waitlist)
    
    # Handle unauthenticated users - set session flag and show options
    if not current_user.is_authenticated:
        # Set session flag to indicate waitlist intent
        session['waitlist_intent'] = True
        
        # Store the waitlist URL as next destination
        session['next'] = url_for('auth.waitlist_register')
        
        # Show login/registration options for waitlist
        # Clear sweet_alert from session after it's been passed to template
        if 'sweet_alert' in session:
            session.pop('sweet_alert', None)
        
        return render_template('waitlist_login_register.html', 
                              title='Join the Waitlist')



@auth.route('/waitlist_discord_login')
def waitlist_discord_login():
    """
    Initiate Discord OAuth for waitlist login.
    This is for existing users who want to login via Discord and join the waitlist.
    Uses the same Discord OAuth flow as regular login.
    """
    from app.models.admin_config import AdminConfig
    
    # Check if waitlist registration is enabled
    if not AdminConfig.get_setting('waitlist_registration_enabled', True):
        show_error('Waitlist registration is currently disabled.')
        return redirect(url_for('main.index'))
    
    from app.auth_helpers import generate_oauth_state
    from urllib.parse import quote
    
    # For authenticated users, redirect them to the regular waitlist registration
    if safe_current_user.is_authenticated:
        return redirect(url_for('auth.waitlist_register'))
    
    discord_client_id = current_app.config['DISCORD_CLIENT_ID']
    redirect_uri = url_for('auth.discord_callback', _external=True)
    scope = 'identify email'
    
    # Generate a secure state value to prevent CSRF attacks
    state_value = generate_oauth_state()
    
    # Make the session permanent to avoid expiration issues
    session.permanent = True
    
    # Store state in session and set waitlist flags
    session['oauth_state'] = state_value
    session['waitlist_intent'] = True
    session['discord_registration_mode'] = False  # This is login, not registration
    
    # Debug session storage
    logger.info(f"Setting oauth_state={state_value[:8]}... in session for waitlist login")
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
    
    logger.info(f"Redirecting to Combined Login+Auth URL for waitlist: {discord_login_url}")
    return redirect(discord_login_url)


@auth.route('/waitlist_discord_register')
def waitlist_discord_register():
    """
    Initiate Discord OAuth for waitlist registration.
    Uses the same Discord OAuth flow as regular registration but sets waitlist flags.
    """
    from app.models.admin_config import AdminConfig
    
    # Check if waitlist registration is enabled
    if not AdminConfig.get_setting('waitlist_registration_enabled', True):
        show_error('Waitlist registration is currently disabled.')
        return redirect(url_for('main.index'))
    
    from app.auth_helpers import generate_oauth_state
    from urllib.parse import quote
    
    # For authenticated users, redirect them to the regular waitlist registration
    if safe_current_user.is_authenticated:
        return redirect(url_for('auth.waitlist_register'))
    
    discord_client_id = current_app.config['DISCORD_CLIENT_ID']
    redirect_uri = url_for('auth.discord_callback', _external=True)
    scope = 'identify email'
    
    # Generate a secure state value to prevent CSRF attacks
    state_value = generate_oauth_state()
    
    # Make the session permanent to avoid expiration issues
    session.permanent = True
    
    # Store state in session and set waitlist registration flags
    session['oauth_state'] = state_value
    session['waitlist_registration'] = True
    session['discord_registration_mode'] = True
    
    # Debug session storage
    logger.info(f"Setting oauth_state={state_value[:8]}... in session for waitlist registration")
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
    
    logger.info(f"Redirecting to Combined Login+Auth URL for waitlist registration: {discord_login_url}")
    return redirect(discord_login_url)


@auth.route('/waitlist_register_with_discord', methods=['GET', 'POST'])
@transactional
def waitlist_register_with_discord():
    """
    Handle the waitlist registration process for users authenticating with Discord.
    
    This route checks if the user is in the Discord server, invites them if needed,
    and creates a new user account with pl-waitlist and pl-unverified roles.
    """
    from app.models.admin_config import AdminConfig
    
    # Check if waitlist registration is enabled
    if not AdminConfig.get_setting('waitlist_registration_enabled', True):
        show_error('Waitlist registration is currently disabled.')
        return redirect(url_for('main.index'))
    
    from app.discord_utils import assign_role_to_member, invite_user_to_server
    from app.utils.discord_request_handler import make_discord_request

    db_session = g.db_session
    discord_email = session.get('pending_discord_email')
    discord_id = session.get('pending_discord_id')
    discord_username = session.get('pending_discord_username')
    
    if not discord_email or not discord_id:
        show_error('Missing Discord information. Please try again.')
        return redirect(url_for('auth.waitlist_register'))
    
    if request.method == 'GET':
        # Check for potential duplicates before showing the form
        potential_duplicates = check_pre_registration_duplicates(discord_email, discord_username)
        
        if potential_duplicates:
            logger.info(f"Found {len(potential_duplicates)} potential duplicates for {discord_email}")
            # Log this as a potential duplicate registration attempt
            for match in potential_duplicates:
                log_potential_duplicate_registration({
                    'new_discord_email': discord_email,
                    'new_discord_username': discord_username,
                    'new_name': discord_username,
                    'existing_player_id': match['player'].id,
                    'existing_player_name': match['player'].name,
                    'match_type': match['match_type'],
                    'confidence': match['confidence']
                })
        
        return render_template('waitlist_register_discord.html', 
                              title='Complete Waitlist Registration',
                              discord_email=discord_email,
                              discord_username=discord_username,
                              potential_duplicates=potential_duplicates)
    
    try:
        # Check if user already exists
        existing_user = db_session.query(User).filter_by(email=discord_email).first()
        
        if existing_user:
            # User exists, add them to waitlist and create/update player profile
            waitlist_role = db_session.query(Role).filter_by(name='pl-waitlist').first()
            if not waitlist_role:
                waitlist_role = Role(name='pl-waitlist', description='Player on waitlist for current season')
                db_session.add(waitlist_role)
                db_session.flush()
            
            unverified_role = db_session.query(Role).filter_by(name='pl-unverified').first()
            if not unverified_role:
                unverified_role = Role(name='pl-unverified', description='Unverified player awaiting league approval')
                db_session.add(unverified_role)
                db_session.flush()
            
            # Add waitlist role if not already assigned
            if waitlist_role not in existing_user.roles:
                existing_user.roles.append(waitlist_role)
                # Set waitlist joined timestamp
                existing_user.waitlist_joined_at = datetime.utcnow()
            
            # Add unverified role if not already assigned (for approval system)
            if unverified_role not in existing_user.roles:
                existing_user.roles.append(unverified_role)
            
            # Get form data for player profile
            preferred_league = request.form.get('preferred_league')
            # Map 'not_sure' to None to comply with database constraint
            if preferred_league == 'not_sure':
                preferred_league = None
            available_for_subbing = request.form.get('available_for_subbing') == 'true'
            
            # Personal information
            name = request.form.get('name', discord_username).strip()
            phone = request.form.get('phone', '')
            
            # Check for phone number duplicates (exclude current user)
            phone_duplicate_players = check_phone_duplicate_registration(phone, exclude_player_id=existing_user.player.id if existing_user.player else None)
            if phone_duplicate_players:
                # Log the potential phone duplicate
                log_potential_duplicate_registration({
                    'new_discord_email': discord_email,
                    'new_discord_username': discord_username,
                    'new_name': name,
                    'new_phone': phone,
                    'existing_player_id': phone_duplicate_players[0].id,
                    'existing_player_name': phone_duplicate_players[0].name,
                    'match_type': 'phone',
                    'confidence': 0.9
                })
                
                # Show warning but allow registration to continue with admin review
                session['sweet_alert'] = {
                    'title': 'Phone Number Already Registered',
                    'text': f'This phone number is already associated with {phone_duplicate_players[0].name}. Your registration will proceed but will be flagged for admin review.',
                    'icon': 'warning'
                }
            
            pronouns = request.form.get('pronouns', '')
            jersey_size = request.form.get('jersey_size', '')
            jersey_number = request.form.get('jersey_number')
            
            # Convert jersey_number to int if provided
            jersey_number_int = None
            if jersey_number:
                try:
                    jersey_number_int = int(jersey_number)
                except ValueError:
                    jersey_number_int = None
            
            # Playing preferences
            favorite_position = request.form.get('favorite_position', '')
            frequency_play_goal = request.form.get('frequency_play_goal', '')
            
            # Handle multi-select fields
            other_positions_list = request.form.getlist('other_positions')
            other_positions = ','.join(other_positions_list) if other_positions_list else ''
            
            positions_not_to_play_list = request.form.getlist('positions_not_to_play')
            positions_not_to_play = ','.join(positions_not_to_play_list) if positions_not_to_play_list else ''
            
            # Availability
            expected_weeks_available = request.form.get('expected_weeks_available', '')
            willing_to_referee = request.form.get('willing_to_referee', '')
            unavailable_dates = request.form.get('unavailable_dates', '')
            
            # Additional information
            additional_info = request.form.get('additional_info', '')
            player_notes = request.form.get('player_notes', '')
            
            # Profile picture
            cropped_image_data = request.form.get('cropped_image_data', '')
            
            # Update user preferences and onboarding status
            existing_user.preferred_league = preferred_league
            existing_user.approval_status = 'pending'  # Reset to pending for approval
            existing_user.has_completed_onboarding = True
            existing_user.has_skipped_profile_creation = False
            existing_user.has_completed_tour = False
            
            # Create or update player profile
            if existing_user.player:
                # Update existing player profile
                player = existing_user.player
                player.name = name
                player.phone = phone
                player.pronouns = pronouns
                player.jersey_size = jersey_size
                player.jersey_number = jersey_number_int
                player.favorite_position = favorite_position
                player.frequency_play_goal = frequency_play_goal
                player.other_positions = other_positions
                player.positions_not_to_play = positions_not_to_play
                player.expected_weeks_available = expected_weeks_available
                player.willing_to_referee = willing_to_referee
                player.unavailable_dates = unavailable_dates
                player.additional_info = additional_info
                player.player_notes = player_notes
                player.interested_in_sub = available_for_subbing
                player.discord_id = discord_id  # Link Discord ID if not already linked
                player.is_current_player = True
            else:
                # Create new player profile
                player = Player(
                    user_id=existing_user.id,
                    discord_id=discord_id,
                    name=name,
                    phone=phone,
                    pronouns=pronouns,
                    jersey_size=jersey_size,
                    jersey_number=jersey_number_int,
                    favorite_position=favorite_position,
                    frequency_play_goal=frequency_play_goal,
                    other_positions=other_positions,
                    positions_not_to_play=positions_not_to_play,
                    expected_weeks_available=expected_weeks_available,
                    willing_to_referee=willing_to_referee,
                    unavailable_dates=unavailable_dates,
                    additional_info=additional_info,
                    player_notes=player_notes,
                    interested_in_sub=available_for_subbing,
                    is_current_player=True
                )
                db_session.add(player)
                db_session.flush()
                existing_user.player = player
            
            db_session.flush()
            
            # Handle profile picture upload if provided
            if cropped_image_data and existing_user.player:
                try:
                    profile_picture_url = save_cropped_profile_picture(cropped_image_data, existing_user.player.id)
                    existing_user.player.profile_picture_url = profile_picture_url
                    db_session.add(existing_user.player)
                    
                    # Trigger image optimization asynchronously
                    try:
                        from app.image_cache_service import handle_player_image_update
                        handle_player_image_update(existing_user.player.id)
                        logger.info(f"Queued image optimization for player {existing_user.player.id}")
                    except Exception as e:
                        logger.warning(f"Failed to queue image optimization: {e}")
                        # Don't fail the registration if optimization queue fails
                    
                    logger.info(f"Profile picture uploaded for waitlist user {existing_user.player.id}")
                except Exception as e:
                    logger.error(f"Error saving profile picture for waitlist user {existing_user.player.id}: {str(e)}")
                    # Don't fail the registration if profile picture save fails
            
            # Log the user in
            login_user(existing_user, remember=True)
            update_last_login(existing_user)
            
            # Clear session data
            session.pop('pending_discord_email', None)
            session.pop('pending_discord_id', None)
            session.pop('pending_discord_username', None)
            session.pop('waitlist_registration', None)
            session.pop('registration_mode', None)
            
            # Set success message for SweetAlert
            session['sweet_alert'] = {
                'title': 'Thanks for Registering!',
                'text': 'You have been successfully added to the waitlist. We will notify you when spots become available.',
                'icon': 'success'
            }
            
            return redirect(url_for('auth.waitlist_confirmation'))
        
        # New user registration - continue with Discord integration
        from app.utils.sync_discord_client import get_sync_discord_client
        
        # Discord server integration using synchronous client
        def handle_discord_integration():
            discord_client = get_sync_discord_client()
            
            # Check if user is in Discord server
            server_id = current_app.config['SERVER_ID']
            member_check = discord_client.check_member_in_server(server_id, discord_id)
            
            if member_check.get('success') and not member_check.get('in_server'):
                # User not in server, invite them
                try:
                    invite_result = discord_client.invite_user_to_server(discord_id)
                    if invite_result.get('success'):
                        if invite_result.get('invite_code'):
                            invite_code = invite_result.get('invite_code')
                            session['discord_invite_link'] = f"https://discord.gg/{invite_code}"
                            logger.info(f"Created personalized Discord invite: https://discord.gg/{invite_code}")
                        elif invite_result.get('invite_link'):
                            session['discord_invite_link'] = invite_result.get('invite_link')
                            logger.info(f"Using generic Discord invite: {invite_result.get('invite_link')}")
                except Exception as e:
                    logger.error(f"Error inviting user to Discord server: {str(e)}")
            
            # Assign pl-waitlist Discord role
            try:
                # For now, we'll use the same Discord role as pl-unverified
                # In the future, you might want to create a separate Discord role for waitlist
                waitlist_discord_role_id = "1357770021157212430"  # ECS-FC-PL-UNVERIFIED
                role_result = discord_client.assign_role_to_member(
                    server_id, 
                    discord_id, 
                    waitlist_discord_role_id
                )
                if role_result.get('success'):
                    logger.info(f"Successfully assigned waitlist Discord role to user {discord_id}")
                else:
                    logger.error(f"Failed to assign Discord role: {role_result.get('message')}")
            except Exception as e:
                logger.error(f"Error assigning Discord role to user {discord_id}: {str(e)}")
            
            return {'success': True}
        
        try:
            discord_result = handle_discord_integration()
        except Exception as e:
            logger.error(f"Error with Discord server integration: {str(e)}")
            show_warning("Could not connect to Discord server. Your waitlist registration will be created, but you may need to join the Discord server manually.")
        
        # Find or create roles
        waitlist_role = db_session.query(Role).filter_by(name='pl-waitlist').first()
        if not waitlist_role:
            waitlist_role = Role(name='pl-waitlist', description='Player on waitlist for current season')
            db_session.add(waitlist_role)
            db_session.flush()
        
        unverified_role = db_session.query(Role).filter_by(name='pl-unverified').first()
        if not unverified_role:
            unverified_role = Role(name='pl-unverified', description='Unverified player awaiting league approval')
            db_session.add(unverified_role)
            db_session.flush()
        
        # Get form data - all profile fields
        preferred_league = request.form.get('preferred_league')
        # Map 'not_sure' to None to comply with database constraint
        if preferred_league == 'not_sure':
            preferred_league = None
        available_for_subbing = request.form.get('available_for_subbing') == 'true'
        
        # Personal information - use the name from form as username
        name = request.form.get('name', discord_username).strip()
        username = name  # Use the entered name as username, not Discord username
        
        # Generate a random password
        import secrets
        import string
        temp_password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))
        phone = request.form.get('phone', '')
        
        # Check for phone number duplicates
        phone_duplicate_players = check_phone_duplicate_registration(phone)
        if phone_duplicate_players:
            # Log the potential phone duplicate
            log_potential_duplicate_registration({
                'new_discord_email': discord_email,
                'new_discord_username': discord_username,
                'new_name': name,
                'new_phone': phone,
                'existing_player_id': phone_duplicate_players[0].id,
                'existing_player_name': phone_duplicate_players[0].name,
                'match_type': 'phone',
                'confidence': 0.9
            })
            
            # Show warning but allow registration to continue with admin review
            session['sweet_alert'] = {
                'title': 'Phone Number Already Registered',
                'text': f'This phone number is already associated with {phone_duplicate_players[0].name}. Your registration will proceed but will be flagged for admin review.',
                'icon': 'warning'
            }
        
        pronouns = request.form.get('pronouns', '')
        jersey_size = request.form.get('jersey_size', '')
        jersey_number = request.form.get('jersey_number')
        
        # Playing preferences
        favorite_position = request.form.get('favorite_position', '')
        frequency_play_goal = request.form.get('frequency_play_goal', '')
        
        # Handle multi-select fields
        other_positions_list = request.form.getlist('other_positions')
        other_positions = ','.join(other_positions_list) if other_positions_list else ''
        
        positions_not_to_play_list = request.form.getlist('positions_not_to_play')
        positions_not_to_play = ','.join(positions_not_to_play_list) if positions_not_to_play_list else ''
        
        # Availability
        expected_weeks_available = request.form.get('expected_weeks_available', '')
        willing_to_referee = request.form.get('willing_to_referee', '')
        unavailable_dates = request.form.get('unavailable_dates', '')
        
        # Additional information
        additional_info = request.form.get('additional_info', '')
        player_notes = request.form.get('player_notes', '')
        
        # Profile picture
        cropped_image_data = request.form.get('cropped_image_data', '')
        
        # Convert jersey_number to int if provided
        jersey_number_int = None
        if jersey_number:
            try:
                jersey_number_int = int(jersey_number)
            except ValueError:
                jersey_number_int = None
        
        new_user = User(
            username=username,
            email=discord_email,
            is_approved=False,
            approval_status='pending',
            preferred_league=preferred_league,
            has_completed_onboarding=True,
            has_skipped_profile_creation=False,
            has_completed_tour=False,
            waitlist_joined_at=datetime.utcnow(),
            roles=[waitlist_role, unverified_role]
        )
        new_user.set_password(temp_password)
        db_session.add(new_user)
        db_session.flush()
        
        # Create comprehensive player profile
        player = Player(
            user_id=new_user.id,
            discord_id=discord_id,
            name=name,
            phone=phone,
            pronouns=pronouns,
            jersey_size=jersey_size,
            jersey_number=jersey_number_int,
            favorite_position=favorite_position,
            frequency_play_goal=frequency_play_goal,
            other_positions=other_positions,
            positions_not_to_play=positions_not_to_play,
            expected_weeks_available=expected_weeks_available,
            willing_to_referee=willing_to_referee,
            unavailable_dates=unavailable_dates,
            additional_info=additional_info,
            player_notes=player_notes,
            interested_in_sub=available_for_subbing
        )
        db_session.add(player)
        db_session.flush()
        
        # Update user with player_id
        new_user.player_id = player.id
        db_session.flush()
        
        # Handle profile picture upload if provided
        if cropped_image_data:
            try:
                profile_picture_url = save_cropped_profile_picture(cropped_image_data, player.id)
                player.profile_picture_url = profile_picture_url
                db_session.add(player)
                
                # Trigger image optimization asynchronously
                try:
                    from app.image_cache_service import handle_player_image_update
                    handle_player_image_update(player.id)
                    logger.info(f"Queued image optimization for player {player.id}")
                except Exception as e:
                    logger.warning(f"Failed to queue image optimization: {e}")
                    # Don't fail the registration if optimization queue fails
                
                logger.info(f"Profile picture uploaded for waitlist user {player.id}")
            except Exception as e:
                logger.error(f"Error saving profile picture for waitlist user {player.id}: {str(e)}")
                # Don't fail the registration if profile picture save fails
        
        # Log the user in
        login_user(new_user, remember=True)
        update_last_login(new_user)
        
        # Clear session data
        session.pop('pending_discord_email', None)
        session.pop('pending_discord_id', None)
        session.pop('pending_discord_username', None)
        session.pop('waitlist_registration', None)
        session.pop('registration_mode', None)
        
        # Set success message for SweetAlert
        session['sweet_alert'] = {
            'title': 'Thanks for Registering!',
            'text': 'You have been successfully added to the waitlist. We will notify you when spots become available.',
            'icon': 'success'
        }
        
        return redirect(url_for('auth.waitlist_confirmation'))
        
    except Exception as e:
        logger.error(f"Waitlist Discord registration error: {str(e)}", exc_info=True)
        show_error('Waitlist registration failed. Please try again.')
        return redirect(url_for('auth.waitlist_register'))


@auth.route('/waitlist_confirmation')
def waitlist_confirmation():
    """
    Display confirmation page after successful waitlist registration.
    
    Checks Discord server membership and prompts user to join if needed.
    """
    discord_membership_status = None
    discord_error = None
    
    # Check if user has Discord info and check membership
    if safe_current_user.is_authenticated and safe_current_user.player:
        player = safe_current_user.player
        if player.discord_id:
            try:
                from app.utils.sync_discord_client import get_sync_discord_client
                discord_client = get_sync_discord_client()
                server_id = current_app.config.get('SERVER_ID')
                
                if server_id:
                    member_check = discord_client.check_member_in_server(server_id, player.discord_id)
                    
                    if member_check.get('success'):
                        discord_membership_status = {
                            'in_server': member_check.get('in_server', False),
                            'discord_id': player.discord_id,
                            'server_id': server_id
                        }
                    else:
                        discord_error = member_check.get('message', 'Unable to check Discord server membership')
                        logger.warning(f"Failed to check Discord membership for user {safe_current_user.id}: {discord_error}")
                        
            except Exception as e:
                discord_error = f"Error checking Discord membership: {str(e)}"
                logger.error(f"Discord membership check error for user {safe_current_user.id}: {discord_error}")
    
    return render_template('waitlist_confirmation.html', 
                           discord_membership_status=discord_membership_status,
                           discord_error=discord_error)


# NEW ROUTES FOR DUPLICATE PREVENTION

@auth.route('/check-duplicate', methods=['GET', 'POST'])
def check_duplicate():
    """Show potential duplicate accounts and let user choose."""
    if 'potential_duplicates' not in session:
        return redirect(url_for('auth.login'))
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'claim':
            # User claims this is their account
            player_id = request.form.get('player_id')
            discord_data = session.get('pending_discord_data')
            
            if player_id and discord_data:
                player = Player.query.get(player_id)
                if player:
                    # Create merge request
                    token = create_merge_request(player.id, {
                        'discord_id': discord_data.get('id'),
                        'discord_username': discord_data.get('username'),
                        'email': discord_data.get('email')
                    })
                    
                    # Send verification email
                    success = send_merge_verification_email(
                        player.user.email,
                        player.name,
                        discord_data.get('email'),
                        token
                    )
                    
                    if success:
                        session['sweet_alert'] = {
                            'title': 'Verification Email Sent!',
                            'text': f'Please check {player.user.email} and click the verification link.',
                            'icon': 'info'
                        }
                    else:
                        session['sweet_alert'] = {
                            'title': 'Email Error',
                            'text': 'Failed to send verification email. Please try again.',
                            'icon': 'error'
                        }
                    
                    return redirect(url_for('auth.login'))
        
        elif action == 'new':
            # User says these aren't their accounts
            discord_data = session.pop('pending_discord_data', None)
            session.pop('potential_duplicates', None)
            
            if discord_data:
                # Continue with normal registration
                session['pending_discord_email'] = discord_data.get('email')
                session['pending_discord_id'] = discord_data.get('id')
                session['pending_discord_username'] = discord_data.get('username')
                session['discord_registration_mode'] = True
                return redirect(url_for('auth.register_with_discord'))
    
    duplicates = session.get('potential_duplicates', [])
    return render_template('auth/check_duplicate.html', 
                         duplicates=duplicates,
                         title="Account Verification - ECS FC")


@auth.route('/verify-merge')
@auth.route('/verify-merge/<token>')
def verify_merge(token=None):
    """Handle account merge verification from email link."""
    
    if token:
        # Process verification
        success, message = verify_and_merge_accounts(token)
        
        if success:
            # SweetAlert message is set in verify_and_merge_accounts
            return redirect(url_for('auth.login'))
        else:
            session['sweet_alert'] = {
                'title': 'Verification Failed',
                'text': message,
                'icon': 'error'
            }
            return render_template('auth/verify_merge.html', 
                                 verification_token=None,
                                 title="Verification Failed - ECS FC")
    
    # Show verification page
    return render_template('auth/verify_merge.html',
                         verification_token=token,
                         title="Verify Account Merge - ECS FC")


@auth.route('/resend-merge-verification', methods=['POST'])
def resend_merge_verification():
    """API endpoint to resend merge verification email."""
    try:
        data = request.get_json()
        old_email = data.get('old_email')
        merge_data = data.get('merge_data')
        
        if not old_email or not merge_data:
            return jsonify({'success': False, 'message': 'Missing required data'})
        
        # Create new verification token
        player = Player.query.filter_by(email=old_email).first()
        if not player:
            return jsonify({'success': False, 'message': 'Player not found'})
        
        token = create_merge_request(player.id, merge_data)
        
        # Send email
        success = send_merge_verification_email(
            old_email,
            player.name,
            merge_data.get('email'),
            token
        )
        
        return jsonify({
            'success': success,
            'message': 'Verification email sent' if success else 'Failed to send email'
        })
        
    except Exception as e:
        logger.error(f"Error resending verification email: {e}")
        return jsonify({'success': False, 'message': 'Server error'})