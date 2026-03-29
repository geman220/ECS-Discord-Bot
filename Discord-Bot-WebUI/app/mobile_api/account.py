# app/mobile_api/account.py

"""
Mobile API Account Management Endpoints

Provides account management functionality for mobile clients:
- Change password
- Manage 2FA (setup, enable, disable)
- Update profile settings
"""

import logging
import pyotp
import qrcode
import io
import base64
from flask import jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.mobile_api import mobile_api_v2
from app.core.session_manager import managed_session
from app.models import User, Player

logger = logging.getLogger(__name__)


@mobile_api_v2.route('/account/password', methods=['PUT'])
@jwt_required()
def change_password():
    """
    Change the current user's password.

    Expected JSON:
        current_password: Current password for verification
        new_password: New password to set

    Returns:
        JSON with success/error message
    """
    current_user_id = int(get_jwt_identity())

    data = request.get_json()
    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    current_password = data.get('current_password')
    new_password = data.get('new_password')

    if not current_password or not new_password:
        return jsonify({"msg": "current_password and new_password are required"}), 400

    if len(new_password) < 8:
        return jsonify({"msg": "New password must be at least 8 characters"}), 400

    with managed_session() as session:
        user = session.query(User).get(current_user_id)
        if not user:
            return jsonify({"msg": "User not found"}), 404

        # Verify current password
        if not user.check_password(current_password):
            return jsonify({"msg": "Current password is incorrect"}), 401

        # Set new password
        user.set_password(new_password)
        session.commit()

        logger.info(f"Password changed for user {user.username}")

        return jsonify({"msg": "Password changed successfully"}), 200


@mobile_api_v2.route('/account/2fa/setup', methods=['POST'])
@jwt_required()
def setup_2fa():
    """
    Begin 2FA setup - generates a secret and returns QR code data.

    Returns:
        JSON with 2FA setup data including QR code (base64)
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        user = session.query(User).get(current_user_id)
        if not user:
            return jsonify({"msg": "User not found"}), 404

        if user.is_2fa_enabled:
            return jsonify({"msg": "2FA is already enabled"}), 400

        # Generate new secret
        secret = pyotp.random_base32()

        # Store secret temporarily (not yet enabled)
        user.totp_secret = secret
        session.commit()

        # Generate provisioning URI for authenticator apps
        totp = pyotp.TOTP(secret)
        provisioning_uri = totp.provisioning_uri(
            name=user.email or user.username,
            issuer_name="ECS FC"
        )

        # Generate QR code
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(provisioning_uri)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        # Convert to base64
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        qr_base64 = base64.b64encode(buffer.getvalue()).decode()

        return jsonify({
            "success": True,
            "secret": secret,
            "provisioning_uri": provisioning_uri,
            "qr_code_base64": f"data:image/png;base64,{qr_base64}",
            "message": "Scan the QR code with your authenticator app, then verify with a code to enable 2FA"
        }), 200


@mobile_api_v2.route('/account/2fa/enable', methods=['POST'])
@jwt_required()
def enable_2fa():
    """
    Enable 2FA by verifying a code from the authenticator app.

    Expected JSON:
        token: 6-digit code from authenticator app

    Returns:
        JSON with success/error message
    """
    current_user_id = int(get_jwt_identity())

    data = request.get_json()
    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    token = data.get('token')
    if not token:
        return jsonify({"msg": "Verification token is required"}), 400

    with managed_session() as session:
        user = session.query(User).get(current_user_id)
        if not user:
            return jsonify({"msg": "User not found"}), 404

        if user.is_2fa_enabled:
            return jsonify({"msg": "2FA is already enabled"}), 400

        if not user.totp_secret:
            return jsonify({"msg": "2FA setup not started. Call /account/2fa/setup first"}), 400

        # Verify the token
        totp = pyotp.TOTP(user.totp_secret)
        if not totp.verify(token):
            return jsonify({"msg": "Invalid verification code"}), 400

        # Enable 2FA
        user.is_2fa_enabled = True
        session.commit()

        logger.info(f"2FA enabled for user {user.username}")

        return jsonify({"msg": "Two-factor authentication enabled successfully"}), 200


@mobile_api_v2.route('/account/2fa', methods=['DELETE'])
@jwt_required()
def disable_2fa():
    """
    Disable 2FA for the current user.

    Expected JSON:
        password: Current password for verification
        token: Current 2FA token (optional but recommended)

    Returns:
        JSON with success/error message
    """
    current_user_id = int(get_jwt_identity())

    data = request.get_json()
    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    password = data.get('password')
    token = data.get('token')

    if not password or not token:
        return jsonify({"msg": "Password and token are required to disable 2FA"}), 400

    with managed_session() as session:
        user = session.query(User).get(current_user_id)
        if not user:
            return jsonify({"msg": "User not found"}), 404

        if not user.is_2fa_enabled:
            return jsonify({"msg": "2FA is not enabled"}), 400

        # Verify password
        if not user.check_password(password):
            return jsonify({"msg": "Incorrect password"}), 401

        # Verify 2FA token
        if not user.totp_secret:
            return jsonify({"msg": "2FA secret not found"}), 400

        totp = pyotp.TOTP(user.totp_secret)
        if not totp.verify(token):
            return jsonify({"msg": "Invalid 2FA code"}), 401

        # Disable 2FA
        user.is_2fa_enabled = False
        user.totp_secret = None
        session.commit()

        logger.info(f"2FA disabled for user {user.username}")

        return jsonify({"msg": "Two-factor authentication disabled"}), 200


@mobile_api_v2.route('/account/profile', methods=['PUT'])
@jwt_required()
def update_profile():
    """
    Update the current user's profile settings.

    Expected JSON (all fields optional):
        phone: Phone number
        pronouns: Preferred pronouns
        favorite_position: Favorite playing position
        other_positions: Other positions (comma-separated or list)
        expected_weeks_available: Number of weeks expected to be available
        jersey_size: Jersey size
        jersey_number: Preferred jersey number
        willing_to_referee: Yes/No/Maybe
        frequency_play_goal: How often willing to play goal
        email_notifications: Boolean for email notifications
        sms_notifications: Boolean for SMS notifications
        discord_notifications: Boolean for Discord notifications

    Returns:
        JSON with updated profile data
    """
    current_user_id = int(get_jwt_identity())

    data = request.get_json()
    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    with managed_session() as session:
        user = session.query(User).get(current_user_id)
        if not user:
            return jsonify({"msg": "User not found"}), 404

        player = session.query(Player).filter_by(user_id=current_user_id).first()

        # Update user-level settings
        if 'email_notifications' in data:
            user.email_notifications = bool(data['email_notifications'])
        if 'sms_notifications' in data:
            user.sms_notifications = bool(data['sms_notifications'])
        if 'discord_notifications' in data:
            user.discord_notifications = bool(data['discord_notifications'])

        # Update player-level settings if player exists
        if player:
            if 'phone' in data:
                player.phone = data['phone']
            if 'pronouns' in data:
                player.pronouns = data['pronouns']
            if 'favorite_position' in data:
                player.favorite_position = data['favorite_position']
            if 'other_positions' in data:
                other = data['other_positions']
                if isinstance(other, list):
                    player.other_positions = ', '.join(other)
                else:
                    player.other_positions = other
            if 'expected_weeks_available' in data:
                try:
                    player.expected_weeks_available = int(data['expected_weeks_available'])
                except (ValueError, TypeError):
                    pass
            if 'jersey_size' in data:
                player.jersey_size = data['jersey_size']
            if 'jersey_number' in data:
                try:
                    player.jersey_number = int(data['jersey_number'])
                except (ValueError, TypeError):
                    pass
            if 'willing_to_referee' in data:
                player.willing_to_referee = data['willing_to_referee']
            if 'frequency_play_goal' in data:
                player.frequency_play_goal = data['frequency_play_goal']

        session.commit()

        logger.info(f"Profile updated for user {user.username}")

        # Build response
        response = {
            "success": True,
            "message": "Profile updated successfully",
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "email_notifications": user.email_notifications,
                "sms_notifications": user.sms_notifications,
                "discord_notifications": user.discord_notifications
            }
        }

        if player:
            response["player"] = {
                "id": player.id,
                "name": player.name,
                "phone": player.phone,
                "pronouns": player.pronouns,
                "favorite_position": player.favorite_position,
                "other_positions": player.other_positions,
                "expected_weeks_available": player.expected_weeks_available,
                "jersey_size": player.jersey_size,
                "jersey_number": player.jersey_number,
                "willing_to_referee": player.willing_to_referee,
                "frequency_play_goal": player.frequency_play_goal
            }

        return jsonify(response), 200


@mobile_api_v2.route('/account/notification-preferences', methods=['GET'])
@jwt_required()
def get_notification_preferences():
    """
    Get the current user's notification preferences.

    Returns:
        JSON with all notification preferences (web + mobile fields)
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        user = session.query(User).get(current_user_id)
        if not user:
            return jsonify({"msg": "User not found"}), 404

        return jsonify({
            "email_notifications": user.email_notifications,
            "sms_notifications": user.sms_notifications,
            "discord_notifications": user.discord_notifications,
            "profile_visibility": user.profile_visibility,
            "push_notifications": user.push_notifications,
            "match_reminders": user.match_reminder_notifications,
            "rsvp_reminders": user.rsvp_reminder_notifications,
            "team_notifications": user.team_update_notifications,
            "league_announcements": user.announcement_notifications,
            "general_announcements": user.general_announcements,
        }), 200


@mobile_api_v2.route('/account/notification-preferences', methods=['PUT'])
@jwt_required()
def update_notification_preferences():
    """
    Update the current user's notification preferences.

    Expected JSON (all fields optional):
        email_notifications: Boolean
        sms_notifications: Boolean
        discord_notifications: Boolean
        profile_visibility: String (public, private, team_only)
        push_notifications: Boolean (master push toggle)
        match_reminders: Boolean
        rsvp_reminders: Boolean
        team_notifications: Boolean
        league_announcements: Boolean
        general_announcements: Boolean

    Returns:
        JSON with updated preferences
    """
    current_user_id = int(get_jwt_identity())

    data = request.get_json()
    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    with managed_session() as session:
        user = session.query(User).get(current_user_id)
        if not user:
            return jsonify({"msg": "User not found"}), 404

        # Web notification channels
        if 'email_notifications' in data:
            user.email_notifications = bool(data['email_notifications'])
        if 'sms_notifications' in data:
            user.sms_notifications = bool(data['sms_notifications'])
        if 'discord_notifications' in data:
            user.discord_notifications = bool(data['discord_notifications'])
        if 'profile_visibility' in data:
            visibility = data['profile_visibility']
            if visibility in ['public', 'private', 'team_only']:
                user.profile_visibility = visibility

        # Mobile push notification preferences
        if 'push_notifications' in data:
            user.push_notifications = bool(data['push_notifications'])
        if 'match_reminders' in data:
            user.match_reminder_notifications = bool(data['match_reminders'])
        if 'rsvp_reminders' in data:
            user.rsvp_reminder_notifications = bool(data['rsvp_reminders'])
        if 'team_notifications' in data:
            user.team_update_notifications = bool(data['team_notifications'])
        if 'league_announcements' in data:
            user.announcement_notifications = bool(data['league_announcements'])
        if 'general_announcements' in data:
            user.general_announcements = bool(data['general_announcements'])

        session.commit()

        logger.info(f"Notification preferences updated for user {user.username}")

        return jsonify({
            "email_notifications": user.email_notifications,
            "sms_notifications": user.sms_notifications,
            "discord_notifications": user.discord_notifications,
            "profile_visibility": user.profile_visibility,
            "push_notifications": user.push_notifications,
            "match_reminders": user.match_reminder_notifications,
            "rsvp_reminders": user.rsvp_reminder_notifications,
            "team_notifications": user.team_update_notifications,
            "league_announcements": user.announcement_notifications,
            "general_announcements": user.general_announcements,
        }), 200


@mobile_api_v2.route('/account/profile-picture', methods=['POST'])
@jwt_required()
def upload_profile_picture():
    """
    Upload a profile picture for the authenticated user.

    Supports two formats:
    1. Base64 JSON: {"cropped_image_data": "data:image/png;base64,..."}
    2. Multipart form data with 'file' field

    Returns:
        JSON with profile picture URL
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        # Get player profile
        player = session.query(Player).filter_by(user_id=current_user_id).first()
        if not player:
            return jsonify({"msg": "Player profile not found"}), 404

        try:
            # Check content type to determine format
            content_type = request.content_type or ''

            if 'multipart/form-data' in content_type:
                # Handle file upload
                if 'file' not in request.files:
                    return jsonify({"msg": "No file provided"}), 400

                file = request.files['file']
                if file.filename == '':
                    return jsonify({"msg": "No file selected"}), 400

                # Validate file type
                allowed_extensions = {'png', 'jpg', 'jpeg', 'webp'}
                file_ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
                if file_ext not in allowed_extensions:
                    return jsonify({
                        "msg": f"Invalid file type. Allowed: {', '.join(allowed_extensions)}"
                    }), 400

                # Read file data and convert to base64 for processing
                import base64
                file_data = file.read()

                # Check file size (5MB limit)
                max_size = 5 * 1024 * 1024
                if len(file_data) > max_size:
                    return jsonify({
                        "msg": f"File too large. Maximum size: 5MB"
                    }), 400

                # Convert to base64 format expected by helper
                mime_type = file.content_type or f'image/{file_ext}'
                base64_data = base64.b64encode(file_data).decode('utf-8')
                cropped_image_data = f"data:{mime_type};base64,{base64_data}"

            else:
                # Handle JSON with base64 data
                data = request.get_json()
                if not data:
                    return jsonify({"msg": "Missing request data"}), 400

                cropped_image_data = data.get('cropped_image_data')
                if not cropped_image_data:
                    return jsonify({"msg": "Missing cropped_image_data"}), 400

            # Use existing helper to save the image
            from app.players_helpers import save_cropped_profile_picture

            new_profile_picture_path = save_cropped_profile_picture(
                cropped_image_data,
                player.id
            )

            # Update player profile
            player.profile_picture_url = new_profile_picture_path
            session.commit()

            # Build full URL for response
            base_url = request.host_url.rstrip('/')
            full_url = (
                new_profile_picture_path if new_profile_picture_path.startswith('http')
                else f"{base_url}{new_profile_picture_path}"
            )

            logger.info(f"Profile picture updated for player {player.id}")

            return jsonify({
                "success": True,
                "message": "Profile picture updated successfully",
                "profile_picture_url": full_url
            }), 200

        except ValueError as e:
            logger.warning(f"Profile picture validation error: {e}")
            return jsonify({"msg": "Internal Server Error"}), 400
        except Exception as e:
            logger.error(f"Error uploading profile picture: {e}")
            return jsonify({"msg": "Failed to upload profile picture"}), 500


@mobile_api_v2.route('/account/profile-picture', methods=['DELETE'])
@jwt_required()
def delete_profile_picture():
    """
    Remove the profile picture for the authenticated user.

    Returns:
        JSON with success message
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        # Get player profile
        player = session.query(Player).filter_by(user_id=current_user_id).first()
        if not player:
            return jsonify({"msg": "Player profile not found"}), 404

        if not player.profile_picture_url:
            return jsonify({"msg": "No profile picture to remove"}), 400

        try:
            import os
            from flask import current_app

            # Get the file path
            old_path = player.profile_picture_url
            if old_path and not old_path.startswith('http'):
                # It's a local file, try to delete it
                full_path = os.path.join(current_app.root_path, old_path.lstrip('/'))
                if os.path.exists(full_path):
                    os.remove(full_path)

            # Clear the profile picture URL
            player.profile_picture_url = None
            session.commit()

            logger.info(f"Profile picture removed for player {player.id}")

            base_url = request.host_url.rstrip('/')
            return jsonify({
                "success": True,
                "message": "Profile picture removed",
                "profile_picture_url": f"{base_url}/static/img/default_player.png"
            }), 200

        except Exception as e:
            logger.error(f"Error removing profile picture: {e}")
            return jsonify({"msg": "Failed to remove profile picture"}), 500


# ---------------------------------------------------------------------------
# Change Email (Spec H)
# ---------------------------------------------------------------------------

@mobile_api_v2.route('/account/change-email', methods=['POST'])
@jwt_required()
def change_email():
    """
    Change the current user's email address.

    Expected JSON:
        new_email: The new email address
        password: Current password for verification

    Returns:
        JSON with success message
    """
    current_user_id = int(get_jwt_identity())

    data = request.get_json()
    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    new_email = data.get('new_email')
    password = data.get('password')

    if not new_email or not password:
        return jsonify({"msg": "new_email and password are required"}), 400

    # Validate email format
    import re
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_pattern, new_email):
        return jsonify({"msg": "Invalid email format"}), 400

    with managed_session() as session:
        user = session.query(User).get(current_user_id)
        if not user:
            return jsonify({"msg": "User not found"}), 404

        if not user.check_password(password):
            return jsonify({"msg": "Incorrect password"}), 401

        # Check uniqueness via email hash
        from app.utils.pii_encryption import create_hash
        new_hash = create_hash(new_email.lower())
        existing = session.query(User).filter(
            User.email_hash == new_hash,
            User.id != current_user_id,
        ).first()
        if existing:
            return jsonify({"msg": "Email already in use"}), 409

        # Update email (setter handles encryption + hash)
        user.email = new_email.lower()
        session.commit()

        logger.info(f"Email changed for user {user.username}")

        return jsonify({"msg": "Email updated successfully"}), 200


# ---------------------------------------------------------------------------
# Active Sessions (Spec F)
# ---------------------------------------------------------------------------

@mobile_api_v2.route('/account/sessions', methods=['GET'])
@jwt_required()
def get_sessions():
    """
    List active sessions for the current user.

    Returns:
        JSON with sessions list, each including is_current flag
    """
    from flask_jwt_extended import get_jwt
    from app.models.sessions import UserSession

    current_user_id = int(get_jwt_identity())
    current_sid = get_jwt().get('sid')

    with managed_session() as session:
        sessions = session.query(UserSession).filter_by(
            user_id=current_user_id,
            is_active=True,
        ).order_by(UserSession.last_activity.desc()).all()

        return jsonify({
            "sessions": [
                s.to_dict(is_current=(s.id == current_sid))
                for s in sessions
            ]
        }), 200


# ---------------------------------------------------------------------------
# Revoke Session (Spec G)
# ---------------------------------------------------------------------------

@mobile_api_v2.route('/account/sessions/<session_id>', methods=['DELETE'])
@jwt_required()
def revoke_session(session_id):
    """
    Revoke an active session.

    Path parameter:
        session_id: The session ID to revoke

    Returns:
        JSON with success message
    """
    from app.models.sessions import UserSession
    from app.utils.session_utils import revoke_user_session

    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        user_session = session.query(UserSession).filter_by(
            id=session_id,
            user_id=current_user_id,
            is_active=True,
        ).first()

        if not user_session:
            return jsonify({"msg": "Session not found"}), 404

        # Revoke in Redis so JWTs with this sid are immediately rejected
        revoke_user_session(session_id)

        user_session.is_active = False
        session.commit()

        logger.info(f"Session {session_id[:8]}... revoked for user {current_user_id}")

        return jsonify({"msg": "Session revoked successfully"}), 200


# ---------------------------------------------------------------------------
# Deactivate Account (Spec J)
# ---------------------------------------------------------------------------

@mobile_api_v2.route('/account/deactivate', methods=['POST'])
@jwt_required()
def deactivate_account():
    """
    Temporarily deactivate the current user's account.

    Expected JSON:
        password: Current password for verification
        reason: Optional reason for deactivation

    Returns:
        JSON with success message
    """
    from app.models.sessions import UserSession
    from app.models.notifications import UserFCMToken
    from app.utils.session_utils import revoke_user_session

    current_user_id = int(get_jwt_identity())

    data = request.get_json()
    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    password = data.get('password')
    reason = data.get('reason')
    if not password:
        return jsonify({"msg": "Password is required"}), 400

    with managed_session() as session:
        user = session.query(User).get(current_user_id)
        if not user:
            return jsonify({"msg": "User not found"}), 404

        if not user.check_password(password):
            return jsonify({"msg": "Incorrect password"}), 401

        # Deactivate account
        user.is_active = False

        # Revoke all active sessions
        active_sessions = session.query(UserSession).filter_by(
            user_id=current_user_id, is_active=True,
        ).all()
        for s in active_sessions:
            revoke_user_session(s.id)
            s.is_active = False

        # Deactivate all FCM tokens
        session.query(UserFCMToken).filter_by(
            user_id=current_user_id, is_active=True,
        ).update({
            'is_active': False,
            'deactivated_reason': 'account_deactivated',
        })

        session.commit()

        logger.info(f"Account deactivated for user {user.username}" +
                     (f", reason: {reason}" if reason else ""))

        return jsonify({"msg": "Account deactivated successfully"}), 200


# ---------------------------------------------------------------------------
# Delete Account (Spec K)
# ---------------------------------------------------------------------------

@mobile_api_v2.route('/account', methods=['DELETE'])
@jwt_required()
def delete_account():
    """
    Permanently delete the current user's account.
    Clears all PII, revokes sessions, and deactivates the account.

    Expected JSON:
        password: Current password for verification
        confirmation: Must be exactly "DELETE MY ACCOUNT"

    Returns:
        JSON with success message
    """
    from app.models.sessions import UserSession
    from app.models.notifications import UserFCMToken
    from app.utils.session_utils import revoke_user_session

    current_user_id = int(get_jwt_identity())

    data = request.get_json()
    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    password = data.get('password')
    confirmation = data.get('confirmation')

    if not password:
        return jsonify({"msg": "Password is required"}), 400

    if confirmation != "DELETE MY ACCOUNT":
        return jsonify({"msg": "Invalid confirmation string"}), 400

    with managed_session() as session:
        user = session.query(User).get(current_user_id)
        if not user:
            return jsonify({"msg": "User not found"}), 404

        if not user.check_password(password):
            return jsonify({"msg": "Incorrect password"}), 401

        username = user.username  # capture for logging before clearing

        # Revoke all sessions
        active_sessions = session.query(UserSession).filter_by(
            user_id=current_user_id, is_active=True,
        ).all()
        for s in active_sessions:
            revoke_user_session(s.id)
            s.is_active = False

        # Deactivate all FCM tokens
        session.query(UserFCMToken).filter_by(
            user_id=current_user_id,
        ).update({
            'is_active': False,
            'deactivated_reason': 'account_deleted',
        })

        # Clear PII and deactivate
        user.encrypted_email = None
        user.email_hash = None
        user.password_hash = 'DELETED'
        user.is_active = False
        user.is_2fa_enabled = False
        user.totp_secret = None
        user.username = f'deleted_user_{user.id}'

        session.commit()

        logger.info(f"Account permanently deleted for former user {username} (id={current_user_id})")

        return jsonify({"msg": "Account deleted successfully"}), 200


# ---------------------------------------------------------------------------
# Export Data (Download My Data)
# ---------------------------------------------------------------------------

@mobile_api_v2.route('/account/export-data', methods=['POST'])
@jwt_required()
def request_data_export():
    """
    Request a data export. Queues a background job to collect the user's data
    and email a download link. Rate limited to 1 export per 24 hours.

    Returns:
        JSON with success message, or 429 if rate limited
    """
    from flask import current_app

    current_user_id = int(get_jwt_identity())

    # Rate limit: 1 export per 24 hours via Redis
    try:
        redis_client = current_app.redis
        rate_key = f"data_export:{current_user_id}"
        if redis_client and redis_client.exists(rate_key):
            return jsonify({"msg": "You can only request one data export per day"}), 429
    except Exception as e:
        logger.warning(f"Redis rate-limit check failed: {e}")

    with managed_session() as session:
        user = session.query(User).get(current_user_id)
        if not user:
            return jsonify({"msg": "User not found"}), 404

        if not user.email:
            return jsonify({"msg": "No email address on file. Add an email first."}), 400

    # Set rate limit (24 hours)
    try:
        redis_client = current_app.redis
        if redis_client:
            redis_client.setex(rate_key, 24 * 60 * 60, '1')
    except Exception as e:
        logger.warning(f"Redis rate-limit set failed: {e}")

    # Queue the Celery task
    from app.tasks.tasks_data_export import export_user_data
    export_user_data.delay(current_user_id)

    logger.info(f"Data export requested by user {current_user_id}")

    return jsonify({
        "msg": "Data export requested. You will receive an email with a download link."
    }), 200


@mobile_api_v2.route('/account/export-data/download/<token>', methods=['GET'])
def download_data_export(token):
    """
    Download a previously exported data file using a signed token.
    Token expires after 48 hours. No JWT required (link from email).

    Path parameter:
        token: Signed download token from the email link

    Returns:
        JSON file download, or error
    """
    import os
    from flask import current_app, send_file
    from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature

    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])

    try:
        # 48-hour expiry
        data = serializer.loads(token, salt='data-export', max_age=48 * 60 * 60)
    except SignatureExpired:
        return jsonify({"msg": "Download link has expired"}), 410
    except BadSignature:
        return jsonify({"msg": "Invalid download link"}), 400

    filename = data.get('filename')
    if not filename:
        return jsonify({"msg": "Invalid download link"}), 400

    # Validate filename to prevent path traversal
    if '/' in filename or '\\' in filename or '..' in filename:
        return jsonify({"msg": "Invalid download link"}), 400

    filepath = os.path.join(current_app.root_path, 'exports', filename)
    if not os.path.exists(filepath):
        return jsonify({"msg": "Export file not found. It may have been cleaned up."}), 404

    return send_file(
        filepath,
        mimetype='application/json',
        as_attachment=True,
        download_name=f"ecsfc_data_export.json",
    )
