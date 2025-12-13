# app/auth/discord.py

"""
Discord OAuth2 Authentication Routes

Routes for Discord OAuth2 login, registration, and callback handling.
"""

import logging
from datetime import datetime, timedelta

from flask import (
    render_template, redirect, url_for, request,
    current_app, session, g, make_response
)
from flask_login import login_user
from flask_wtf.csrf import generate_csrf

from app.auth import auth
from app.alert_helpers import show_success, show_error, show_warning, show_info
from app.models import User, Role, Player
from app.utils.db_utils import transactional
from app.auth_helpers import (
    get_discord_user_data,
    exchange_discord_code,
    update_last_login,
)
from app.auth.helpers import sync_discord_for_user
from app.duplicate_prevention import (
    check_discord_id_first,
    handle_email_change,
    find_potential_duplicates,
)

logger = logging.getLogger(__name__)


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
    session.permanent = True
    current_app.permanent_session_lifetime = timedelta(days=30)  # Even longer lifetime

    # First, generate a CSRF token manually to ensure the session exists
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
            csrf_token = generate_csrf()

            # Force session to be saved
            session.modified = True

            logger.info(f"User {user.id} has 2FA enabled. Redirecting to 2FA verification.")
            logger.info(f"Session data before redirect: {dict(session)}")

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
