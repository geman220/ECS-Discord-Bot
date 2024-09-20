import logging
from flask import Blueprint, render_template, redirect, url_for, flash, send_file, jsonify, request, session
from flask_login import login_required, current_user
from app.forms import Verify2FAForm
from app import db
from io import BytesIO
from werkzeug.security import generate_password_hash, check_password_hash
from .forms import (
    NotificationSettingsForm,
    PasswordChangeForm,
    Enable2FAForm,
    Disable2FAForm
)
import pyotp
import qrcode
import io

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

account_bp = Blueprint('account', __name__, template_folder='templates')

@account_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    print("Entered settings route")  # Debug statement
    print("Request Form Data:", request.form)  # Debug statement

    # Instantiate forms with unique prefixes
    notification_form = NotificationSettingsForm(prefix='notification')
    password_form = PasswordChangeForm(prefix='password')
    enable_2fa_form = Enable2FAForm(prefix='enable2fa')
    disable_2fa_form = Disable2FAForm(prefix='disable2fa')

    # Handle Notification Settings Form Submission
    if notification_form.submit_notifications.data and notification_form.validate_on_submit():
        print("Notification form submitted")  # Debug
        current_user.email_notifications = notification_form.email_notifications.data
        current_user.sms_notifications = notification_form.sms_notifications.data
        current_user.discord_notifications = notification_form.discord_notifications.data
        current_user.profile_visibility = notification_form.profile_visibility.data
        db.session.commit()
        flash('Notification settings updated successfully.', 'success')
        return redirect(url_for('account.settings'))

    # Handle Password Change Form Submission
    if password_form.submit_password.data:
        print("Password form submitted")  # Debug
        print("Password Submit Button Data:", password_form.submit_password.data)  # Debug
        if password_form.validate_on_submit():
            print("Password form validated")  # Debug
            if not current_user.check_password(password_form.current_password.data):
                flash('Current password is incorrect.', 'danger')
                print("Password validation failed")  # Debugging line
            else:
                # Update password
                current_user.password_hash = generate_password_hash(password_form.new_password.data)
                db.session.commit()
                flash('Password updated successfully.', 'success')
                print("Password updated successfully")  # Debugging line
            return redirect(url_for('account.settings'))
        else:
            flash('Please correct the errors below.', 'danger')
            print("Password form failed validation")  # Debugging line

    # Handle Enable 2FA Form Submission
    if enable_2fa_form.submit_enable_2fa.data and enable_2fa_form.validate_on_submit():
        print("Enable 2FA form submitted")  # Debug
        totp = pyotp.TOTP(current_user.totp_secret)
        if totp.verify(enable_2fa_form.totp_token.data):
            current_user.is_2fa_enabled = True
            db.session.commit()
            flash('Two-Factor Authentication enabled successfully.', 'success')
            print("Enable 2FA successful")  # Debugging line
            return redirect(url_for('account.settings'))
        else:
            print("Enable 2FA failed: Invalid token")  # Debugging line
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify(success=False, errors={'totp_token': 'Invalid 2FA token.'}), 400
            flash('Invalid 2FA token. Please try again.', 'danger')

    # Handle Disable 2FA Form Submission
    if disable_2fa_form.submit_disable_2fa.data and disable_2fa_form.validate_on_submit():
        print("Disable 2FA form submitted")  # Debug
        if current_user.is_2fa_enabled:
            current_user.is_2fa_enabled = False
            current_user.totp_secret = None  # Clear the TOTP secret
            db.session.commit()
            flash('Two-Factor Authentication has been disabled.', 'success')
            print("Disable 2FA successful")  # Debugging line
            return redirect(url_for('account.settings'))
        else:
            flash('Two-Factor Authentication is not enabled.', 'warning')
            print("Disable 2FA failed: 2FA not enabled")  # Debugging line

    # Populate forms with current user data on GET request
    if request.method == 'GET':
        # Populate Notification Settings
        notification_form.email_notifications.data = current_user.email_notifications
        notification_form.sms_notifications.data = current_user.sms_notifications
        notification_form.discord_notifications.data = current_user.discord_notifications
        notification_form.profile_visibility.data = current_user.profile_visibility

    return render_template('settings.html', 
                           notification_form=notification_form, 
                           password_form=password_form, 
                           enable_2fa_form=enable_2fa_form,
                           disable_2fa_form=disable_2fa_form,
                           is_2fa_enabled=current_user.is_2fa_enabled)

@account_bp.route('/enable_2fa', methods=['POST'])
@login_required
def enable_2fa():
    # Generate TOTP secret if not already set
    if not current_user.totp_secret:
        current_user.generate_totp_secret()
        db.session.commit()

    # Generate TOTP URI for the user
    otp_uri = pyotp.TOTP(current_user.totp_secret).provisioning_uri(
        name=current_user.email, 
        issuer_name="ECS Web"
    )

    # Generate QR code
    qr = qrcode.make(otp_uri)
    buffer = BytesIO()
    qr.save(buffer)
    buffer.seek(0)

    # Serve the QR code image
    return send_file(buffer, mimetype='image/png')

@account_bp.route('/show_2fa_qr', methods=['GET'])
@login_required
def show_2fa_qr():
    try:
        # Generate TOTP secret (but do not save it to the database yet)
        totp_secret = pyotp.random_base32()
        logger.debug(f"TOTP Secret (not saved yet): {totp_secret}")

        # Generate TOTP URI for the user
        totp = pyotp.TOTP(totp_secret)
        otp_uri = totp.provisioning_uri(
            name=current_user.email, 
            issuer_name="ECS Web App"
        )

        logger.debug(f"OTP URI: {otp_uri}")

        # Create QR code
        img = qrcode.make(otp_uri)
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)

        # Store the generated TOTP secret in the session temporarily
        session['temp_totp_secret'] = totp_secret

        # Return the image as a response
        return send_file(buffer, mimetype='image/png')

    except Exception as e:
        logger.error(f"Error generating QR code: {str(e)}")
        return "Error generating QR code", 500

@account_bp.route('/verify_2fa', methods=['POST'])
@login_required
def verify_2fa():
    try:
        # Instantiate the form with the same prefix used in the template
        enable_2fa_form = Enable2FAForm(prefix='enable2fa')

        # Validate the form submission
        if enable_2fa_form.validate_on_submit():
            # Retrieve the token from the form
            token = enable_2fa_form.totp_token.data

            # Retrieve the temporary TOTP secret from the session
            totp_secret = session.get('temp_totp_secret')
            if not totp_secret:
                logger.error("No temporary TOTP secret found in session.")
                return jsonify({"success": False, "errors": {"general": "No 2FA setup found. Please try again."}}), 400

            # Initialize TOTP with the secret
            totp = pyotp.TOTP(totp_secret)

            # Verify the submitted token
            if totp.verify(token):
                # If valid, enable 2FA and save the secret to the database
                current_user.totp_secret = totp_secret
                current_user.is_2fa_enabled = True
                db.session.commit()

                # Remove the temporary secret from the session
                session.pop('temp_totp_secret', None)

                logger.info(f"2FA enabled for user {current_user.email}")
                return jsonify({"success": True}), 200
            else:
                logger.warning(f"Invalid 2FA token for user {current_user.email}")
                return jsonify({"success": False, "errors": {"totp_token": "Invalid 2FA token."}}), 400
        else:
            # If form validation fails, return errors
            errors = {field: error[0] for field, error in enable_2fa_form.errors.items()}
            logger.warning(f"Enable2FAForm validation failed: {errors}")
            return jsonify({"success": False, "errors": errors}), 400

    except Exception as e:
        logger.error(f"Error during 2FA verification: {str(e)}", exc_info=True)
        return jsonify({"success": False, "errors": {"general": "Internal server error."}}), 500