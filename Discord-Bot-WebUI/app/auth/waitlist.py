# app/auth/waitlist.py

"""
Waitlist Registration Routes

Routes for waitlist registration, Discord integration, and confirmation.
"""

import logging
import secrets
import string
from datetime import datetime

from flask import (
    render_template, redirect, url_for, request,
    current_app, session, g
)
from flask_login import login_user, login_required, current_user as flask_current_user

from app.auth import auth
from app.alert_helpers import show_error, show_warning, show_success, show_info
from app.models import User, Role, Player
from app.utils.db_utils import transactional
from app.utils.user_helpers import safe_current_user
from app.utils.log_sanitizer import get_safe_session_keys
from app.auth_helpers import update_last_login
from app.players_helpers import save_cropped_profile_picture
from app.duplicate_prevention import (
    check_pre_registration_duplicates,
    check_phone_duplicate_registration,
    log_potential_duplicate_registration
)

logger = logging.getLogger(__name__)


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
        # If already on waitlist, redirect to status page
        if current_user.waitlist_joined_at:
            return redirect(url_for('auth.waitlist_status'))

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

        return render_template('waitlist_register_authenticated_flowbite.html',
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

        return render_template('waitlist_login_register_flowbite.html',
                              title='Join the Waitlist')


@auth.route('/waitlist_status')
@login_required
def waitlist_status():
    """
    Display waitlist status for authenticated users.

    Shows different messaging based on user type:
    - New users (not approved): "Application Under Review"
    - Returning approved players: "Waiting for Spot"
    """
    db_session = g.db_session
    user = flask_current_user

    # Check if user is on waitlist
    if not user.waitlist_joined_at:
        return redirect(url_for('auth.waitlist_register'))

    # Get player data
    player = user.player

    # Determine waitlist type
    # is_approved=True means they're an approved player waiting for a spot (league full)
    # is_approved=False means they're a new user under review
    is_returning_player = user.is_approved

    # Get Discord server info
    discord_server_url = current_app.config.get('DISCORD_SERVER_URL', 'https://discord.gg/weareecs')

    return render_template('waitlist_status_flowbite.html',
        title='Waitlist Status',
        user=user,
        player=player,
        waitlist_date=user.waitlist_joined_at,
        approval_status=user.approval_status,
        approval_league=user.approval_league,
        is_returning_player=is_returning_player,
        discord_server_url=discord_server_url
    )


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

    # Debug session storage (sanitized - no sensitive values)
    logger.debug(f"OAuth state set in session for waitlist login")
    logger.debug(f"Session keys: {get_safe_session_keys(session)}")

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

    logger.debug(f"Redirecting to Discord OAuth for waitlist login")
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

    # Capture claim_code from URL if present (for quick profile linking)
    claim_code = request.args.get('claim_code', '').strip().upper()
    if claim_code:
        session['pending_claim_code'] = claim_code
        logger.debug(f"Stored claim_code in session for waitlist registration")

    # Debug session storage (sanitized - no sensitive values)
    logger.debug(f"OAuth state set in session for waitlist registration")
    logger.debug(f"Session keys: {get_safe_session_keys(session)}")

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

    logger.debug(f"Redirecting to Discord OAuth for waitlist registration")
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

        # Check for claim_code in session (from email/SMS link or URL param)
        pending_claim_code = session.get('pending_claim_code', '')

        # Use the new carousel template
        return render_template('waitlist_register_discord_carousel_flowbite.html',
                              title='Complete Waitlist Registration',
                              discord_email=discord_email,
                              discord_username=discord_username,
                              potential_duplicates=potential_duplicates,
                              claim_code=pending_claim_code)

    try:
        # Check if user already exists
        existing_user = db_session.query(User).filter_by(email=discord_email).first()

        if existing_user:
            # Handle existing user - add to waitlist
            return _handle_existing_user_waitlist(db_session, existing_user, discord_id, discord_email, discord_username)

        # New user registration - continue with Discord integration
        return _handle_new_user_waitlist(db_session, discord_email, discord_id, discord_username)

    except Exception as e:
        logger.error(f"Waitlist Discord registration error: {str(e)}", exc_info=True)
        show_error('Waitlist registration failed. Please try again.')
        return redirect(url_for('auth.waitlist_register'))


def _handle_existing_user_waitlist(db_session, existing_user, discord_id, discord_email, discord_username):
    """Handle waitlist registration for existing users."""
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
    _update_player_profile(db_session, existing_user, discord_id, discord_email, discord_username, is_new_user=False)

    # Log the user in
    login_user(existing_user, remember=True)
    update_last_login(existing_user)

    # Clear session data
    _clear_waitlist_session()

    # Set success message for SweetAlert
    session['sweet_alert'] = {
        'title': 'Thanks for Registering!',
        'text': 'You have been successfully added to the waitlist. We will notify you when spots become available.',
        'icon': 'success'
    }

    return redirect(url_for('auth.waitlist_confirmation'))


def _handle_new_user_waitlist(db_session, discord_email, discord_id, discord_username):
    """Handle waitlist registration for new users."""
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
    if preferred_league == 'not_sure':
        preferred_league = None

    name = request.form.get('name', discord_username).strip()
    username = name

    # Generate a random password
    temp_password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))

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

    # Create player profile
    _update_player_profile(db_session, new_user, discord_id, discord_email, discord_username, is_new_user=True)

    # Log the user in
    login_user(new_user, remember=True)
    update_last_login(new_user)

    # Clear session data
    _clear_waitlist_session()

    # Set success message for SweetAlert
    session['sweet_alert'] = {
        'title': 'Thanks for Registering!',
        'text': 'You have been successfully added to the waitlist. We will notify you when spots become available.',
        'icon': 'success'
    }

    return redirect(url_for('auth.waitlist_confirmation'))


def _update_player_profile(db_session, user, discord_id, discord_email, discord_username, is_new_user=False):
    """Update or create player profile from form data."""
    # Get form data
    preferred_league = request.form.get('preferred_league')
    if preferred_league == 'not_sure':
        preferred_league = None
    available_for_subbing = request.form.get('available_for_subbing') == 'true'

    # Get claim code from form (may override session value)
    claim_code = request.form.get('claim_code', '').strip().upper()
    # Fall back to session if not in form
    if not claim_code:
        claim_code = session.get('pending_claim_code', '').strip().upper()

    name = request.form.get('name', discord_username).strip()
    phone = request.form.get('phone', '')

    # Check for phone number duplicates
    exclude_player_id = user.player.id if user.player else None
    phone_duplicate_players = check_phone_duplicate_registration(phone, exclude_player_id=exclude_player_id)
    if phone_duplicate_players:
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
        session['sweet_alert'] = {
            'title': 'Phone Number Already Registered',
            'text': f'This phone number is already associated with {phone_duplicate_players[0].name}. Your registration will proceed but will be flagged for admin review.',
            'icon': 'warning'
        }

    pronouns = request.form.get('pronouns', '')
    jersey_size = request.form.get('jersey_size', '')
    jersey_number = request.form.get('jersey_number')

    jersey_number_int = None
    if jersey_number:
        try:
            jersey_number_int = int(jersey_number)
        except ValueError:
            jersey_number_int = None

    favorite_position = request.form.get('favorite_position', '')
    frequency_play_goal = request.form.get('frequency_play_goal', '')

    other_positions_list = request.form.getlist('other_positions')
    other_positions = ','.join(other_positions_list) if other_positions_list else ''

    positions_not_to_play_list = request.form.getlist('positions_not_to_play')
    positions_not_to_play = ','.join(positions_not_to_play_list) if positions_not_to_play_list else ''

    expected_weeks_available = request.form.get('expected_weeks_available', '')
    willing_to_referee = request.form.get('willing_to_referee', '')
    unavailable_dates = request.form.get('unavailable_dates', '')
    additional_info = request.form.get('additional_info', '')
    player_notes = request.form.get('player_notes', '')
    cropped_image_data = request.form.get('cropped_image_data', '')

    # Update user preferences
    user.preferred_league = preferred_league
    user.approval_status = 'pending'
    user.has_completed_onboarding = True
    user.has_skipped_profile_creation = False
    user.has_completed_tour = False

    if is_new_user or not user.player:
        # Create new player profile
        player = Player(
            user_id=user.id,
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
        user.player_id = player.id
    else:
        # Update existing player profile
        player = user.player
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
        player.discord_id = discord_id
        player.is_current_player = True

    db_session.flush()

    # Handle profile picture upload
    if cropped_image_data:
        try:
            profile_picture_url = save_cropped_profile_picture(cropped_image_data, player.id)
            player.profile_picture_url = profile_picture_url
            db_session.add(player)

            try:
                from app.image_cache_service import handle_player_image_update
                handle_player_image_update(player.id)
                logger.info(f"Queued image optimization for player {player.id}")
            except Exception as e:
                logger.warning(f"Failed to queue image optimization: {e}")

            logger.info(f"Profile picture uploaded for waitlist user {player.id}")
        except Exception as e:
            logger.error(f"Error saving profile picture for waitlist user {player.id}: {str(e)}")

    # Process quick profile claim code if provided
    if claim_code:
        try:
            from app.models import QuickProfile
            quick_profile = QuickProfile.find_by_code(claim_code)
            if quick_profile and quick_profile.is_valid():
                # Claim the profile - this merges data into the player
                quick_profile.claim(player)
                logger.info(f"Player {player.id} claimed quick profile {quick_profile.id} with code {claim_code}")
                # Clear the claim code from session
                session.pop('pending_claim_code', None)
            else:
                # Log invalid code but don't fail registration
                logger.warning(f"Invalid or expired claim code '{claim_code}' during waitlist registration for player {player.id}")
        except Exception as claim_error:
            # Don't fail registration if claim code processing fails
            logger.error(f"Error processing claim code '{claim_code}': {str(claim_error)}")


def _clear_waitlist_session():
    """Clear waitlist-related session data."""
    session.pop('pending_discord_email', None)
    session.pop('pending_discord_id', None)
    session.pop('pending_discord_username', None)
    session.pop('waitlist_registration', None)
    session.pop('registration_mode', None)
    session.pop('pending_claim_code', None)


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

    return render_template('waitlist_confirmation_flowbite.html',
                           discord_membership_status=discord_membership_status,
                           discord_error=discord_error)
