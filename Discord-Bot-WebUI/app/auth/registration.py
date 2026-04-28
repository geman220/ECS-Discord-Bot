# app/auth/registration.py

"""
Registration Routes

Routes for standard registration and Discord-based registration.
"""

import logging
import secrets
import string
from datetime import datetime

from flask import (
    render_template, redirect, url_for, request,
    current_app, session, g
)
from flask_login import login_user

from app.auth import auth
from app.alert_helpers import show_error, show_warning, show_info
from app.models import User, Role, Player
from app.forms import RegistrationForm
from app.utils.db_utils import transactional
from app.utils.user_helpers import safe_current_user
from app.utils.log_sanitizer import mask_code

logger = logging.getLogger(__name__)


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

    from app.forms import EmptyForm
    return render_template('register_flowbite.html', title='Register', form=form, empty_form=EmptyForm())


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
        # Check for claim_code in session (from email/SMS link or URL param)
        pending_claim_code = session.get('pending_claim_code', '')
        return render_template('register_discord_flowbite.html',
                              title='Complete Registration',
                              discord_email=discord_email,
                              discord_username=discord_username,
                              claim_code=pending_claim_code)

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

        # Pre-insert duplicate detection. Without these checks an existing
        # account hits the DB unique constraints at commit time and raises a
        # 500 (see errors.log 2026-04-27 19:10:21). Each branch logs the user
        # in and gives explicit feedback so they're never left wondering what
        # happened.
        from app.utils.pii_encryption import create_hash
        from app.auth_helpers import update_last_login
        from flask import session as flask_session

        def _sign_in_existing(existing_user, alert_title, alert_text, banner_msg):
            login_user(existing_user, remember=True)
            update_last_login(existing_user)
            session.pop('pending_discord_email', None)
            session.pop('pending_discord_id', None)
            session.pop('pending_discord_username', None)
            session.pop('pending_claim_code', None)
            session.pop('discord_registration_mode', None)
            show_info(banner_msg)
            flask_session['sweet_alert'] = {
                'title': alert_title,
                'text': alert_text,
                'icon': 'info',
            }
            return redirect(url_for('main.index'))

        # 1. Email match — same person re-registering with a different entry path.
        existing_by_email = db_session.query(User).filter(
            User.email_hash == create_hash(discord_email)
        ).first()
        if existing_by_email:
            return _sign_in_existing(
                existing_by_email,
                'Account Already Exists',
                "You already have an account with this email. We've signed you in.",
                'Welcome back — we found your existing account and signed you in.',
            )

        # 2. Discord-ID match — Player.discord_id is unique and Player.user_id is
        # NOT NULL, so any matching Player has a linked User to sign in as.
        existing_player = db_session.query(Player).filter_by(discord_id=discord_id).first()
        if existing_player and existing_player.user_id:
            existing_user = db_session.query(User).get(existing_player.user_id)
            if existing_user:
                return _sign_in_existing(
                    existing_user,
                    'Discord Account Linked',
                    "Your Discord account is already linked to an existing user. We've signed you in.",
                    'This Discord account is already linked to an existing user — we\'ve signed you in.',
                )

        # Find the pl-unverified role in database
        unverified_role = db_session.query(Role).filter_by(name='pl-unverified').first()
        if not unverified_role:
            # Create the role if it doesn't exist
            unverified_role = Role(name='pl-unverified', description='Unverified player awaiting league approval')
            db_session.add(unverified_role)
            db_session.flush()

        # Create the user
        original_username = discord_username.split('#')[0] if '#' in discord_username else discord_username
        username = original_username
        username_was_adjusted = False

        # 3. Username collision — rare (different person already claimed this
        # exact handle via plain /auth/register). Try once with a short suffix;
        # if even that's taken, bail out cleanly rather than crash.
        if db_session.query(User.id).filter_by(username=username).first():
            username = f"{original_username}{secrets.token_hex(2)}"
            username_was_adjusted = True
            if db_session.query(User.id).filter_by(username=username).first():
                show_error(
                    "We couldn't automatically pick a username for your account. "
                    "Please try the standard registration form, or contact an admin."
                )
                flask_session['sweet_alert'] = {
                    'title': "Registration Couldn't Complete",
                    'text': 'We were unable to create your account automatically. Please contact an admin.',
                    'icon': 'error',
                }
                return redirect(url_for('auth.login'))

        # Generate a random password - user can reset it later
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

        # Check for and process quick profile claim code
        claim_code = request.form.get('claim_code', '').strip().upper()
        if claim_code:
            try:
                from app.models import QuickProfile
                quick_profile = QuickProfile.find_by_code(claim_code)
                if quick_profile and quick_profile.is_valid():
                    # Claim the profile - this merges data into the player
                    quick_profile.claim(player)
                    logger.info(f"Player {player.id} claimed quick profile {quick_profile.id} with code {mask_code(claim_code)}")
                else:
                    # Log invalid code but don't fail registration
                    logger.warning(f"Invalid or expired claim code '{mask_code(claim_code)}' during registration for player {player.id}")
            except Exception as claim_error:
                # Don't fail registration if claim code processing fails
                logger.error(f"Error processing claim code '{mask_code(claim_code)}': {str(claim_error)}")

        # Log in the user
        login_user(new_user)

        # Clear session variables
        session.pop('pending_discord_email', None)
        session.pop('pending_discord_id', None)
        session.pop('pending_discord_username', None)
        session.pop('pending_claim_code', None)

        # Ensure onboarding flags are properly set to trigger the onboarding modal
        new_user.has_completed_onboarding = False
        new_user.has_skipped_profile_creation = False
        new_user.has_completed_tour = False
        db_session.add(new_user)
        db_session.commit()  # Commit to ensure all flags are saved

        # Set session flag to ensure onboarding is shown
        flask_session['force_onboarding'] = True

        # Set Discord server invite information in the session
        default_invite_link = "https://discord.gg/weareecs"
        flask_session['discord_invite_link'] = default_invite_link
        flask_session['needs_discord_join'] = True

        # Set sweet alert flag instead of using flash. If we had to suffix the
        # username, surface that prominently so the user isn't confused later.
        if username_was_adjusted:
            adjusted_msg = (
                f"Your Discord username '{original_username}' was already taken, so "
                f"we created your account as '{username}'. You can change it later "
                f"in your profile settings."
            )
            show_warning(adjusted_msg)
            flask_session['sweet_alert'] = {
                'title': 'Username Adjusted',
                'text': adjusted_msg,
                'icon': 'warning',
            }
        else:
            flask_session['sweet_alert'] = {
                'title': 'Registration Successful!',
                'text': 'Please join our Discord server and complete your profile.',
                'icon': 'success',
            }

        # Redirect to main index which will handle onboarding and show the sweet alert
        return redirect(url_for('main.index'))

    except Exception as e:
        logger.error(f"Discord registration error: {str(e)}", exc_info=True)
        show_error('Registration failed. Please try again later.')
        from flask import session as flask_session
        flask_session['sweet_alert'] = {
            'title': 'Registration Failed',
            'text': 'We hit an unexpected error completing your registration. Please try again, or contact an admin if it keeps happening.',
            'icon': 'error',
        }
        return redirect(url_for('auth.login'))
