# app/account.py

"""
Account Module

This module defines the account-related routes for the application, including
settings, notification and password updates, SMS and two-factor authentication,
and Discord account linking. It leverages Flask-Login for user management,
Flask-WTF for forms, and custom helper functions for SMS, 2FA, and Discord integration.
"""

import qrcode
import base64
from io import BytesIO
from flask import send_file, Blueprint, render_template, redirect, url_for, request, current_app, jsonify, session, g
from app.alert_helpers import show_success, show_error, show_warning, show_info
from flask_login import login_required, current_user
from app import csrf
from app.core import db
from app.forms import NotificationSettingsForm, PasswordChangeForm, Enable2FAForm, Disable2FAForm
from app.models import Player, User, Notification
from app.sms_helpers import send_confirmation_sms, verify_sms_confirmation, user_is_blocked_in_textmagic, handle_incoming_text_command
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from app.utils.user_helpers import safe_current_user
from app.utils.db_utils import transactional
import aiohttp
import logging
import requests
import pyotp

# Set up logger
logger = logging.getLogger(__name__)

logger = logging.getLogger(__name__)

account_bp = Blueprint('account', __name__)

# Discord OAuth2 configuration constants.
DISCORD_OAUTH2_URL = 'https://discord.com/api/oauth2/authorize'
DISCORD_TOKEN_URL = 'https://discord.com/api/oauth2/token'
DISCORD_API_URL = 'https://discord.com/api/users/@me'

# --------------------
# Helper Functions
# --------------------

def get_player_notifications(user_id):
    """
    Retrieve the 10 most recent notifications for a given user.

    Args:
        user_id: The ID of the user.

    Returns:
        A list of Notification objects ordered by creation date (descending).
    """
    return Notification.query.filter_by(user_id=user_id)\
        .order_by(Notification.created_at.desc())\
        .limit(10)\
        .all()


def get_player_with_team(user_id):
    """
    Retrieve a Player along with their associated team information.

    Args:
        user_id: The ID of the user.

    Returns:
        A Player object with the team relationship eagerly loaded, or None if not found.
    """
    return Player.query.options(db.joinedload(Player.team))\
        .filter_by(user_id=user_id)\
        .first()


def create_or_update_player(session, user_id, phone_number):
    """
    Create or update a Player record with the provided phone number.

    This function uses the provided session (instead of the global db.session)
    to ensure transactional safety during user updates.

    Args:
        session: The database session to use.
        user_id: The ID of the user.
        phone_number: The phone number to set for the player.

    Returns:
        The created or updated Player object.
    """
    player = session.query(Player).filter_by(user_id=user_id).first()
    if not player:
        player = Player(user_id=user_id)
        session.add(player)
    player.phone = phone_number
    player.is_phone_verified = False
    player.sms_consent_given = True
    player.sms_consent_timestamp = datetime.utcnow()
    player.sms_opt_out_timestamp = None
    return player


def link_discord_account(code, discord_client_id, discord_client_secret, redirect_uri, player):
    """
    Link a Discord account to a player's profile.

    Exchanges an OAuth2 authorization code for an access token and retrieves
    the user's Discord ID. Updates the player's discord_id attribute accordingly.

    Args:
        code: The OAuth2 authorization code from Discord.
        discord_client_id: The Discord client ID.
        discord_client_secret: The Discord client secret.
        redirect_uri: The redirect URI used in the OAuth2 flow.
        player: The Player object to update.

    Returns:
        A tuple (success, error_message). If success is True, linking succeeded.
    """
    token_data = {
        'client_id': discord_client_id,
        'client_secret': discord_client_secret,
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': redirect_uri,
    }
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    token_response = requests.post(DISCORD_TOKEN_URL, data=token_data, headers=headers)
    token_json = token_response.json()
    
    if 'access_token' not in token_json:
        return False, "Failed to retrieve access token"
        
    headers = {'Authorization': f'Bearer {token_json["access_token"]}'}
    user_response = requests.get(DISCORD_API_URL, headers=headers)
    user_json = user_response.json()
    
    discord_id = user_json.get('id')
    if not discord_id:
        return False, "Failed to retrieve Discord ID"
        
    player.discord_id = discord_id
    return True, None

# --------------------
# Routes
# --------------------

@account_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    """
    Render the account settings page.

    Displays forms for updating notification settings, password changes, and enabling/disabling 2FA.
    """
    notification_form = NotificationSettingsForm(prefix='notification', obj=safe_current_user)
    password_form = PasswordChangeForm(prefix='password')
    enable_2fa_form = Enable2FAForm(prefix='enable2fa')
    disable_2fa_form = Disable2FAForm(prefix='disable2fa')

    return render_template('settings.html', 
                           notification_form=notification_form, 
                           password_form=password_form, 
                           enable_2fa_form=enable_2fa_form,
                           disable_2fa_form=disable_2fa_form,
                           is_2fa_enabled=safe_current_user.is_2fa_enabled)


@account_bp.route('/update_notifications', methods=['POST'])
@login_required
@transactional
def update_notifications():
    """
    Update user notification settings.

    Processes the NotificationSettingsForm submission and updates the user's email, Discord
    notifications, and profile visibility.
    """
    session = g.db_session
    user = session.query(User).get(current_user.id)

    form = NotificationSettingsForm(prefix='notification')
    if form.validate_on_submit():
        user.email_notifications = form.email_notifications.data
        user.discord_notifications = form.discord_notifications.data
        user.profile_visibility = form.profile_visibility.data
        show_success('Notification settings updated successfully.')
    else:
        show_error('Error updating notification settings.')
    return redirect(url_for('account.settings'))


@account_bp.route('/change_password', methods=['POST'])
@login_required
@transactional
def change_password():
    """
    Change the user's password.

    Validates the current password and updates it to the new password using secure hashing.
    """
    session = g.db_session
    user = session.query(User).get(current_user.id)

    form = PasswordChangeForm(prefix='password')
    if form.validate_on_submit():
        if check_password_hash(user.password_hash, form.current_password.data):
            user.password_hash = generate_password_hash(form.new_password.data)
            show_success('Your password has been updated successfully.')
        else:
            show_error('Current password is incorrect.')
    else:
        for field, errors in form.errors.items():
            for error in errors:
                show_error(f"{field.capitalize()}: {error}")
    return redirect(url_for('account.settings'))


@account_bp.route('/update_account_info', methods=['POST'])
@login_required
@transactional
def update_account_info():
    """
    Update account information.

    Updates the user's email and, if a player profile exists, the player's name and phone.
    """
    session = g.db_session
    user = session.query(User).get(current_user.id)

    form = request.form
    user.email = form.get('email')
    if user.player:
        user.player.name = form.get('name')
        user.player.phone = form.get('phone')
    show_success('Account information updated successfully')
    return redirect(url_for('account.settings'))


@account_bp.route('/initiate-sms-opt-in', methods=['POST'])
@login_required
@transactional
def initiate_sms_opt_in():
    """
    Initiate SMS opt-in process.

    Validates the phone number and consent, creates or updates the player's record, checks
    for blocked numbers, and sends a confirmation SMS.
    """
    session = g.db_session
    user = session.query(User).get(current_user.id)

    phone_number = request.json.get('phone_number')
    consent_given = request.json.get('consent_given')
    
    if not phone_number or not consent_given:
        return jsonify(success=False, message="Phone number and consent are required."), 400
    
    # Validate and normalize the phone number
    phone_number = phone_number.strip()
    # Remove any non-digit characters
    phone_number = ''.join(filter(str.isdigit, phone_number))
    
    # Check if this is a valid US number (10 digits)
    if len(phone_number) != 10:
        return jsonify(success=False, message="Please enter a valid 10-digit US phone number."), 400

    # Create or update the player record with the normalized phone number
    player = create_or_update_player(session, user.id, phone_number)
    
    try:
        # Check if the user's phone is blocked
        if user_is_blocked_in_textmagic(phone_number):
            return jsonify(success=False, message="You previously un-subscribed. Please text 'START' to re-subscribe"), 400
    except Exception as e:
        logger.error(f"Error checking if phone is blocked: {e}")
        # Continue even if the blocked check fails
    
    # Enable SMS notifications and send confirmation code
    user.sms_notifications = True
    success, message = send_confirmation_sms(user)
    
    if success:
        return jsonify(success=True, message="Verification code sent. Please check your phone.")
    else:
        logger.error(f'Failed to send SMS to user {user.id}. Error: {message}')
        # Include more details for the user if there's an authentication issue
        if "Authenticate" in str(message):
            return jsonify(success=False, message="SMS service is currently unavailable. Please try again later or contact support."), 500
        return jsonify(success=False, message="Failed to send verification code. Please try again."), 500


@account_bp.route('/confirm-sms-opt-in', methods=['POST'])
@login_required
@transactional
def confirm_sms_opt_in():
    """
    Confirm SMS opt-in.

    Validates the SMS confirmation code and updates the user's SMS notification settings.
    """
    session = g.db_session
    user = session.query(User).get(current_user.id)

    confirmation_code = request.json.get('confirmation_code')
    if not confirmation_code:
        return jsonify(success=False, message="Verification code is required."), 400
    
    if verify_sms_confirmation(user, confirmation_code):
        user.sms_notifications = True
        if user.player:
            user.player.is_phone_verified = True
        show_success('SMS notifications enabled successfully.')
        return jsonify(success=True, message="SMS notifications enabled successfully.")
    else:
        return jsonify(success=False, message="Invalid verification code."), 400


@account_bp.route('/opt_out_sms', methods=['POST'])
@login_required
@transactional
def opt_out_sms():
    """
    Opt out of SMS notifications.

    Disables SMS notifications for the user and records the opt-out timestamp.
    """
    session = g.db_session
    user = session.query(User).get(current_user.id)

    user.sms_notifications = False
    if user.player:
        user.player.sms_opt_out_timestamp = datetime.utcnow()
    show_success('SMS notifications disabled successfully.')
    return jsonify(success=True, message="You have successfully opted-out of SMS notifications.")


@account_bp.route('/sms-verification-status', methods=['GET'])
@login_required
def sms_verification_status():
    """
    Check SMS verification status.

    Returns a JSON response indicating whether the player's phone has been verified and the associated phone number.
    """
    session = g.db_session
    user = session.query(User).get(current_user.id)

    is_verified = False
    phone_number = None
    if user.player:
        is_verified = user.player.is_phone_verified
        phone_number = user.player.phone
    return jsonify({'is_verified': is_verified, 'phone_number': phone_number})


@account_bp.route('/enable_2fa', methods=['GET', 'POST'])
@login_required
def enable_2fa():
    """
    Enable two-factor authentication (2FA) for the current user.

    On GET requests, generates a new TOTP secret, creates a QR code for setup, and returns it as a JSON response.
    On POST requests, verifies the provided TOTP code and enables 2FA if valid.
    """
    # GET: Generate TOTP secret and QR code.
    if request.method == 'GET':
        if not current_user.totp_secret:
            current_user.generate_totp_secret()
        totp = pyotp.TOTP(current_user.totp_secret)
        otp_uri = totp.provisioning_uri(name=current_user.email, issuer_name="ECS Web")
        img = qrcode.make(otp_uri)
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        buffered.seek(0)
        session['temp_totp_secret'] = current_user.totp_secret
        return jsonify({
            'qr_code': base64.b64encode(buffered.getvalue()).decode(),
            'secret': current_user.totp_secret
        })
    
    # POST: Verify the TOTP code and enable 2FA.
    elif request.method == 'POST':
        code = request.json.get('code')
        totp = pyotp.TOTP(current_user.totp_secret)
        if totp.verify(code):
            current_user.is_2fa_enabled = True
            show_success('2FA enabled successfully.')
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'message': 'Invalid verification code'}), 400


@account_bp.route('/disable_2fa', methods=['POST'])
@login_required
@transactional
def disable_2fa():
    """
    Disable two-factor authentication (2FA) for the current user.

    If the user has 2FA enabled, it will be disabled and the TOTP secret cleared.
    """
    session = g.db_session
    user = session.query(User).get(current_user.id)

    form = Disable2FAForm(prefix='disable2fa')
    if form.validate_on_submit():
        if user.is_2fa_enabled:
            user.is_2fa_enabled = False
            user.totp_secret = None
            show_success('Two-Factor Authentication has been disabled.')
        else:
            show_warning('Two-Factor Authentication is not currently enabled.')
    return redirect(url_for('account.settings'))


@account_bp.route('/link-discord')
@login_required
def link_discord():
    """
    Redirect the user to Discord for OAuth2 linking.

    Constructs the Discord OAuth2 URL with required parameters and redirects the user.
    """
    discord_client_id = current_app.config['DISCORD_CLIENT_ID']
    redirect_uri = url_for('account.discord_callback', _external=True)
    scope = 'identify email'
    discord_login_url = f"{DISCORD_OAUTH2_URL}?client_id={discord_client_id}&redirect_uri={redirect_uri}&response_type=code&scope={scope}"
    return redirect(discord_login_url)


@account_bp.route('/discord-callback')
@login_required
@transactional
def discord_callback():
    """
    Handle the Discord OAuth2 callback.

    Retrieves the authorization code from Discord, links the Discord account to the user's profile,
    and provides appropriate feedback.
    """
    session = g.db_session
    user = session.query(User).get(current_user.id)
    code = request.args.get('code')
    if not code:
        show_error('Discord linking failed. Please try again.')
        return redirect(url_for('account.settings'))

    if not user.player:
        show_error('Unable to link Discord account. Player profile not found.')
        return redirect(url_for('account.settings'))

    success, error = link_discord_account(
        code=code,
        discord_client_id=current_app.config['DISCORD_CLIENT_ID'],
        discord_client_secret=current_app.config['DISCORD_CLIENT_SECRET'],
        redirect_uri=url_for('account.discord_callback', _external=True),
        player=user.player
    )

    if success:
        show_success('Your Discord account has been successfully linked.')
    else:
        show_error(f'Failed to link Discord account: {error}')
    return redirect(url_for('account.settings'))


@account_bp.route('/unlink-discord', methods=['POST'])
@login_required
@transactional
def unlink_discord():
    """
    Unlink the user's Discord account.

    Clears the discord_id from the player's profile and provides user feedback.
    """
    session = g.db_session
    user = session.query(User).get(current_user.id)

    if user.player and user.player.discord_id:
        user.player.discord_id = None
        show_success('Your Discord account has been unlinked successfully.')
    else:
        show_info('No Discord account is currently linked.')
    return redirect(url_for('account.settings'))


@csrf.exempt
@account_bp.route('/webhook/incoming-sms', methods=['POST'])
@transactional
def incoming_sms_webhook():
    """
    Webhook endpoint for processing incoming SMS commands.

    Retrieves the sender's phone number and message body, and passes the command
    to a helper function for processing. Maintains the original phone number format
    to ensure consistent handling throughout the application.
    """
    session = g.db_session
    sender_number = request.form.get('From', '').strip()
    message_text = request.form.get('Body', '').strip()

    # Log FULL request data for debugging SMS issues
    logger.info(f"Incoming SMS webhook received from: {sender_number}, message: {message_text}")
    logger.info(f"Full SMS request data: {request.form}")
    
    # Make sure command works regardless of case
    if message_text.lower() == 'schedule':
        logger.info(f"Processing 'schedule' command for {sender_number}")
    
    return handle_incoming_text_command(sender_number, message_text)


@account_bp.route('/show_2fa_qr', methods=['GET'])
@login_required
def show_2fa_qr():
    """
    Generate and display a QR code for setting up two-factor authentication (2FA).

    Generates a temporary TOTP secret, creates an OTP URI, and renders a QR code image.
    The QR code is returned as an image/png file.
    """
    try:
        totp_secret = pyotp.random_base32()
        logger.debug(f"TOTP Secret (not saved yet): {totp_secret}")

        totp = pyotp.TOTP(totp_secret)
        otp_uri = totp.provisioning_uri(
            name=safe_current_user.email, 
            issuer_name="ECS Web App"
        )

        logger.debug(f"OTP URI: {otp_uri}")

        img = qrcode.make(otp_uri)
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)

        session['temp_totp_secret'] = totp_secret

        return send_file(buffer, mimetype='image/png')
    except Exception as e:
        logger.error(f"Error generating QR code: {str(e)}")
        return "Error generating QR code", 500


@account_bp.route('/api/sms/config', methods=['GET'])
@login_required
def check_sms_configuration():
    """
    Check the SMS configuration status.
    
    This endpoint is available to administrators for diagnosing SMS-related issues.
    """
    from app.sms_helpers import check_sms_config
    import os
    
    # Only allow administrators to access this endpoint
    if not current_user.is_admin:
        return jsonify({"error": "Unauthorized"}), 403
        
    config_status = check_sms_config()
    
    # Add environment variable debug info for admins
    config_status['env_vars'] = {
        k: "<exists>" for k, v in os.environ.items() 
        if 'TWILIO' in k or 'TEXTMAGIC' in k
    }
    
    # Add current configured values (with hidden secrets)
    config_status['configured_values'] = {
        'TWILIO_SID': current_app.config.get('TWILIO_SID', 'missing'),
        'TWILIO_ACCOUNT_SID': current_app.config.get('TWILIO_ACCOUNT_SID', 'missing'),
        'TWILIO_AUTH_TOKEN': '***hidden***' if current_app.config.get('TWILIO_AUTH_TOKEN') else 'missing',
        'TWILIO_PHONE_NUMBER': current_app.config.get('TWILIO_PHONE_NUMBER', 'missing'),
        'TEXTMAGIC_USERNAME': current_app.config.get('TEXTMAGIC_USERNAME', 'missing'),
        'TEXTMAGIC_API_KEY': '***hidden***' if current_app.config.get('TEXTMAGIC_API_KEY') else 'missing'
    }
    
    return jsonify(config_status)