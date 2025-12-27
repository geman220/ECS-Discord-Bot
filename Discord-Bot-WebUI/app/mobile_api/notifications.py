# app/mobile_api/notifications.py

"""
Notifications API Endpoints

Handles push notification operations including:
- Device registration
- Notification preferences
- Push token management
"""

import logging
from datetime import datetime

from flask import jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.mobile_api import mobile_api_v2
from app.core.session_manager import managed_session
from app.models import Player, User
from app.models.notifications import UserFCMToken

logger = logging.getLogger(__name__)


@mobile_api_v2.route('/notifications/register', methods=['POST'])
@jwt_required()
def register_device():
    """
    Register a device for push notifications.

    Expected JSON parameters:
        device_token: The FCM/APNs device token
        platform: 'ios' or 'android'
        device_id: Optional device identifier
        app_version: Optional app version string

    Returns:
        JSON with registration result
    """
    current_user_id = int(get_jwt_identity())

    data = request.json or {}
    device_token = data.get('device_token') or data.get('token')  # Support both formats
    platform = data.get('platform', 'unknown')
    device_id = data.get('device_id')
    app_version = data.get('app_version')

    if not device_token:
        return jsonify({"msg": "Missing device_token"}), 400

    # Validate platform
    if platform not in ('ios', 'android', 'web', 'unknown'):
        platform = 'unknown'

    logger.info(f"Registering device for user {current_user_id}: platform={platform}, token_prefix={device_token[:20]}...")

    with managed_session() as session_db:
        user = session_db.query(User).get(current_user_id)
        if not user:
            return jsonify({"msg": "User not found"}), 404

        player = session_db.query(Player).filter_by(user_id=current_user_id).first()

        try:
            # Check for existing token by fcm_token (unique)
            existing_by_token = session_db.query(UserFCMToken).filter_by(
                fcm_token=device_token
            ).first()

            if existing_by_token:
                # Token exists - update user_id if different (device changed hands)
                if existing_by_token.user_id != current_user_id:
                    existing_by_token.user_id = current_user_id
                existing_by_token.platform = platform
                existing_by_token.is_active = True
                existing_by_token.updated_at = datetime.utcnow()
                existing_by_token.last_used = datetime.utcnow()
                if app_version:
                    existing_by_token.app_version = app_version
                if device_id:
                    existing_by_token.device_info = device_id
                logger.info(f"Updated existing FCM token for user {current_user_id}")
            else:
                # Create new token
                new_token = UserFCMToken(
                    user_id=current_user_id,
                    fcm_token=device_token,
                    platform=platform,
                    is_active=True,
                    app_version=app_version,
                    device_info=device_id
                )
                session_db.add(new_token)
                logger.info(f"Created new FCM token for user {current_user_id}")

            session_db.commit()

            return jsonify({
                "msg": "Device registered successfully",
                "user_id": current_user_id,
                "player_id": player.id if player else None
            }), 200

        except Exception as e:
            logger.exception(f"Error registering device: {e}")
            session_db.rollback()
            return jsonify({"msg": "Failed to register device"}), 500


@mobile_api_v2.route('/notifications/preferences', methods=['GET', 'PUT'])
@jwt_required()
def notification_preferences():
    """
    Get or update notification preferences.

    For GET:
        Returns current notification preferences

    For PUT:
        Expected JSON parameters:
            match_reminders: bool
            rsvp_reminders: bool
            team_updates: bool
            league_updates: bool

    Returns:
        JSON with preferences
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session_db:
        user = session_db.query(User).get(current_user_id)
        if not user:
            return jsonify({"msg": "User not found"}), 404

        player = session_db.query(Player).filter_by(user_id=current_user_id).first()

        if request.method == 'GET':
            # Build preferences response from user settings
            preferences = {
                "email_notifications": getattr(user, 'email_notifications', True),
                "sms_notifications": getattr(user, 'sms_notifications', False),
                "discord_notifications": getattr(user, 'discord_notifications', True),
            }

            # Add player-specific preferences if available
            if player:
                preferences.update({
                    "match_reminders": getattr(player, 'notify_match_reminders', True),
                    "rsvp_reminders": getattr(player, 'notify_rsvp_reminders', True),
                    "team_updates": getattr(player, 'notify_team_updates', True),
                    "league_updates": getattr(player, 'notify_league_updates', False),
                })
            else:
                # Default preferences if no player profile
                preferences.update({
                    "match_reminders": True,
                    "rsvp_reminders": True,
                    "team_updates": True,
                    "league_updates": False,
                })

            return jsonify({"preferences": preferences}), 200

        else:  # PUT
            data = request.json or {}

            # Update user-level preferences
            if 'email_notifications' in data:
                user.email_notifications = data['email_notifications']
            if 'sms_notifications' in data:
                user.sms_notifications = data['sms_notifications']
            if 'discord_notifications' in data:
                user.discord_notifications = data['discord_notifications']

            # Update player-level preferences if available
            if player:
                if 'match_reminders' in data:
                    player.notify_match_reminders = data['match_reminders']
                if 'rsvp_reminders' in data:
                    player.notify_rsvp_reminders = data['rsvp_reminders']
                if 'team_updates' in data:
                    player.notify_team_updates = data['team_updates']
                if 'league_updates' in data:
                    player.notify_league_updates = data['league_updates']

            session_db.commit()

            # Return updated preferences
            preferences = {
                "email_notifications": getattr(user, 'email_notifications', True),
                "sms_notifications": getattr(user, 'sms_notifications', False),
                "discord_notifications": getattr(user, 'discord_notifications', True),
            }

            if player:
                preferences.update({
                    "match_reminders": getattr(player, 'notify_match_reminders', True),
                    "rsvp_reminders": getattr(player, 'notify_rsvp_reminders', True),
                    "team_updates": getattr(player, 'notify_team_updates', True),
                    "league_updates": getattr(player, 'notify_league_updates', False),
                })

            return jsonify({
                "msg": "Preferences updated",
                "preferences": preferences
            }), 200


@mobile_api_v2.route('/notifications/unregister', methods=['POST'])
@jwt_required()
def unregister_device():
    """
    Unregister a device from push notifications.

    Expected JSON parameters:
        device_token: The device token to unregister (optional - if not provided, deactivates all)
        platform: 'ios' or 'android' (optional)

    Returns:
        JSON with result
    """
    current_user_id = int(get_jwt_identity())

    data = request.json or {}
    device_token = data.get('device_token')
    platform = data.get('platform')

    logger.info(f"Unregistering device for user {current_user_id}")

    with managed_session() as session_db:
        user = session_db.query(User).get(current_user_id)
        if not user:
            return jsonify({"msg": "User not found"}), 404

        try:
            query = session_db.query(UserFCMToken).filter_by(user_id=current_user_id)

            if device_token:
                query = query.filter_by(fcm_token=device_token)
            if platform:
                query = query.filter_by(platform=platform)

            # Deactivate tokens instead of deleting (for audit trail)
            tokens = query.all()
            deactivated_count = 0
            for token in tokens:
                token.is_active = False
                token.deactivated_reason = 'User requested unregister'
                token.updated_at = datetime.utcnow()
                deactivated_count += 1

            session_db.commit()

            logger.info(f"Deactivated {deactivated_count} FCM tokens for user {current_user_id}")

            return jsonify({
                "msg": "Device unregistered successfully",
                "tokens_removed": deactivated_count
            }), 200

        except Exception as e:
            logger.exception(f"Error unregistering device: {e}")
            session_db.rollback()
            return jsonify({"msg": "Failed to unregister device"}), 500


@mobile_api_v2.route('/notifications/test', methods=['POST'])
@jwt_required()
def send_test_notification():
    """
    Send a test push notification to the current user's registered devices.

    Returns:
        JSON with result
    """
    current_user_id = int(get_jwt_identity())

    logger.info(f"Sending test notification to user {current_user_id}")

    with managed_session() as session_db:
        user = session_db.query(User).get(current_user_id)
        if not user:
            return jsonify({"msg": "User not found"}), 404

        try:
            # Get all active FCM tokens for this user
            tokens = session_db.query(UserFCMToken).filter_by(
                user_id=current_user_id,
                is_active=True
            ).all()

            if not tokens:
                return jsonify({
                    "msg": "No registered devices found",
                    "devices_notified": 0
                }), 200

            # Try to send notification via notification service
            notified_count = 0
            try:
                from app.services.notification_service import notification_service

                for token in tokens:
                    try:
                        success = notification_service.send_test_notification(token.fcm_token)
                        if success:
                            token.mark_as_used()
                            notified_count += 1
                            logger.info(f"Sent test notification to {token.platform} device")
                        else:
                            logger.warning(f"Failed to send to {token.platform} device")
                    except Exception as e:
                        logger.error(f"Failed to send to device: {e}")

                session_db.commit()

            except ImportError:
                # Notification service not available - just log
                for token in tokens:
                    logger.info(f"Would send test notification to {token.platform} device: {token.token_preview}")
                    notified_count += 1

            return jsonify({
                "msg": "Test notification sent",
                "devices_notified": notified_count
            }), 200

        except Exception as e:
            logger.exception(f"Error sending test notification: {e}")
            return jsonify({"msg": "Failed to send test notification"}), 500
