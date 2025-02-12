# app/account.py

import qrcode
import base64
from io import BytesIO
from flask import send_file
from app import csrf
from app.core import db
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, jsonify, session, g
from flask_login import login_required, current_user
from app.forms import Verify2FAForm, NotificationSettingsForm, PasswordChangeForm, Enable2FAForm, Disable2FAForm
from app.models import Player, Team, Match, User, Notification
from app.sms_helpers import send_confirmation_sms, verify_sms_confirmation, user_is_blocked_in_textmagic, handle_incoming_text_command
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from app.utils.user_helpers import safe_current_user
from app.utils.db_utils import transactional
import aiohttp
import logging
import requests
import pyotp

logger = logging.getLogger(__name__)

account_bp = Blueprint('account', __name__)

DISCORD_OAUTH2_URL = 'https://discord.com/api/oauth2/authorize'
DISCORD_TOKEN_URL = 'https://discord.com/api/oauth2/token'
DISCORD_API_URL = 'https://discord.com/api/users/@me'


# --------------------
# Helper Functions
# --------------------

def get_player_notifications(user_id):
    return Notification.query.filter_by(user_id=user_id)\
        .order_by(Notification.created_at.desc())\
        .limit(10)\
        .all()

def get_player_with_team(user_id):
    return Player.query.options(db.joinedload(Player.team))\
        .filter_by(user_id=user_id)\
        .first()

def create_or_update_player(session, user_id, phone_number):
    """
    Updated to use session passed in rather than db.session
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
    session = g.db_session
    user = session.query(User).get(current_user.id)

    form = NotificationSettingsForm(prefix='notification')
    if form.validate_on_submit():
        user.email_notifications = form.email_notifications.data
        user.discord_notifications = form.discord_notifications.data
        user.profile_visibility = form.profile_visibility.data
        flash('Notification settings updated successfully.', 'success')
    else:
        flash('Error updating notification settings.', 'danger')
    return redirect(url_for('account.settings'))


@account_bp.route('/change_password', methods=['POST'])
@login_required
@transactional
def change_password():
    session = g.db_session
    user = session.query(User).get(current_user.id)

    form = PasswordChangeForm(prefix='password')
    if form.validate_on_submit():
        if check_password_hash(user.password_hash, form.current_password.data):
            user.password_hash = generate_password_hash(form.new_password.data)
            flash('Your password has been updated successfully.', 'success')
        else:
            flash('Current password is incorrect.', 'danger')
    else:
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"{field.capitalize()}: {error}", 'danger')
    return redirect(url_for('account.settings'))


@account_bp.route('/update_account_info', methods=['POST'])
@login_required
@transactional
def update_account_info():
    session = g.db_session
    user = session.query(User).get(current_user.id)

    form = request.form
    user.email = form.get('email')
    if user.player:
        user.player.name = form.get('name')
        user.player.phone = form.get('phone')
    flash('Account information updated successfully', 'success')
    return redirect(url_for('account.settings'))


@account_bp.route('/initiate-sms-opt-in', methods=['POST'])
@login_required
@transactional
def initiate_sms_opt_in():
    session = g.db_session
    user = session.query(User).get(current_user.id)

    phone_number = request.json.get('phone_number')
    consent_given = request.json.get('consent_given')
    
    if not phone_number or not consent_given:
        return jsonify(success=False, message="Phone number and consent are required."), 400

    player = create_or_update_player(session, user.id, phone_number)
    
    if user_is_blocked_in_textmagic(phone_number):
        return jsonify(success=False, message="You previously un-subscribed. Please text 'START' to re-subscribe"), 400

    user.sms_notifications = True
    success, message = send_confirmation_sms(user)
    
    if success:
        return jsonify(success=True, message="Verification code sent. Please check your phone.")
    else:
        logger.error(f'Failed to send SMS to user {user.id}. Error: {message}')
        return jsonify(success=False, message="Failed to send verification code. Please try again."), 500


@account_bp.route('/confirm-sms-opt-in', methods=['POST'])
@login_required
@transactional
def confirm_sms_opt_in():
    session = g.db_session
    user = session.query(User).get(current_user.id)

    confirmation_code = request.json.get('confirmation_code')
    if not confirmation_code:
        return jsonify(success=False, message="Verification code is required."), 400
    
    if verify_sms_confirmation(user, confirmation_code):
        user.sms_notifications = True
        if user.player:
            user.player.is_phone_verified = True
        flash('SMS notifications enabled successfully.', 'success')
        return jsonify(success=True, message="SMS notifications enabled successfully.")
    else:
        return jsonify(success=False, message="Invalid verification code."), 400


@account_bp.route('/opt_out_sms', methods=['POST'])
@login_required
@transactional
def opt_out_sms():
    session = g.db_session
    user = session.query(User).get(current_user.id)

    user.sms_notifications = False
    if user.player:
        user.player.sms_opt_out_timestamp = datetime.utcnow()
    flash('SMS notifications disabled successfully.', 'success')
    return jsonify(success=True, message="You have successfully opted-out of SMS notifications.")


@account_bp.route('/sms-verification-status', methods=['GET'])
@login_required
def sms_verification_status():
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
@transactional
def enable_2fa():
    session = g.db_session
    user = session.query(User).get(current_user.id)

    if request.method == 'GET':
        if not user.totp_secret:
            user.generate_totp_secret()
        totp = pyotp.TOTP(user.totp_secret)
        otp_uri = totp.provisioning_uri(name=user.email, issuer_name="ECS Web")
        img = qrcode.make(otp_uri)
        buffered = BytesIO()
        img.save(buffered)
        qr_code = base64.b64encode(buffered.getvalue()).decode()
        return jsonify({'qr_code': qr_code, 'secret': user.totp_secret})
    
    elif request.method == 'POST':
        code = request.json.get('code')
        totp = pyotp.TOTP(user.totp_secret)
        
        if totp.verify(code):
            user.is_2fa_enabled = True
            flash('2FA enabled successfully.', 'success')
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'message': 'Invalid verification code'}), 400


@account_bp.route('/disable_2fa', methods=['POST'])
@login_required
@transactional
def disable_2fa():
    session = g.db_session
    user = session.query(User).get(current_user.id)

    form = Disable2FAForm(prefix='disable2fa')
    if form.validate_on_submit():
        if user.is_2fa_enabled:
            user.is_2fa_enabled = False
            user.totp_secret = None
            flash('Two-Factor Authentication has been disabled.', 'success')
        else:
            flash('Two-Factor Authentication is not currently enabled.', 'warning')
    return redirect(url_for('account.settings'))


@account_bp.route('/link-discord')
@login_required
def link_discord():
    discord_client_id = current_app.config['DISCORD_CLIENT_ID']
    redirect_uri = url_for('account.discord_callback', _external=True)
    scope = 'identify email'
    
    discord_login_url = f"{DISCORD_OAUTH2_URL}?client_id={discord_client_id}&redirect_uri={redirect_uri}&response_type=code&scope={scope}"
    return redirect(discord_login_url)


@account_bp.route('/discord-callback')
@login_required
@transactional
def discord_callback():
    session = g.db_session
    user = session.query(User).get(current_user.id)

    code = request.args.get('code')
    if not code:
        flash('Discord linking failed. Please try again.', 'danger')
        return redirect(url_for('account.settings'))

    if not user.player:
        flash('Unable to link Discord account. Player profile not found.', 'danger')
        return redirect(url_for('account.settings'))

    success, error = link_discord_account(
        code=code,
        discord_client_id=current_app.config['DISCORD_CLIENT_ID'],
        discord_client_secret=current_app.config['DISCORD_CLIENT_SECRET'],
        redirect_uri=url_for('account.discord_callback', _external=True),
        player=user.player
    )

    if success:
        flash('Your Discord account has been successfully linked.', 'success')
    else:
        flash(f'Failed to link Discord account: {error}', 'danger')

    return redirect(url_for('account.settings'))


@account_bp.route('/unlink-discord', methods=['POST'])
@login_required
@transactional
def unlink_discord():
    session = g.db_session
    user = session.query(User).get(current_user.id)

    if user.player and user.player.discord_id:
        user.player.discord_id = None
        flash('Your Discord account has been unlinked successfully.', 'success')
    else:
        flash('No Discord account is currently linked.', 'info')
    return redirect(url_for('account.settings'))


@csrf.exempt
@account_bp.route('/webhook/incoming-sms', methods=['POST'])
@transactional
def incoming_sms_webhook():
    session = g.db_session

    sender_number = request.form.get('From', '').strip()
    message_text = request.form.get('Body', '').strip()

    if sender_number.startswith('+1'):
        sender_number = sender_number[2:]

    return handle_incoming_text_command(sender_number, message_text)

@account_bp.route('/show_2fa_qr', methods=['GET'])
@login_required
def show_2fa_qr():
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