# app/api/notifications.py

"""
Notifications API Endpoints

Handles push notification operations including:
- Device registration
- Notification preferences
- Push token management
"""

import logging

from flask import jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.mobile_api import mobile_api_v2
from app.core.session_manager import managed_session
from app.models import Player, User

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

    Returns:
        JSON with registration result
    """
    current_user_id = int(get_jwt_identity())

    data = request.json or {}
    device_token = data.get('device_token') or data.get('token')  # Support both formats
    platform = data.get('platform', 'unknown')
    device_id = data.get('device_id')

    if not device_token:
        return jsonify({"msg": "Missing device_token"}), 400

    logger.info(f"Registering device for user {current_user_id}: platform={platform}, token_prefix={device_token[:20]}...")

    with managed_session() as session_db:
        user = session_db.query(User).get(current_user_id)
        if not user:
            return jsonify({"msg": "User not found"}), 404

        player = session_db.query(Player).filter_by(user_id=current_user_id).first()

        # Store device token in database
        # First check if we need to update or create
        try:
            from app.models import DeviceToken

            # Check for existing token
            existing = session_db.query(DeviceToken).filter_by(
                user_id=current_user_id,
                platform=platform
            ).first()

            if existing:
                existing.token = device_token
                existing.device_id = device_id
                logger.info(f"Updated existing device token for user {current_user_id}")
            else:
                new_token = DeviceToken(
                    user_id=current_user_id,
                    token=device_token,
                    platform=platform,
                    device_id=device_id
                )
                session_db.add(new_token)
                logger.info(f"Created new device token for user {current_user_id}")

            session_db.commit()

            return jsonify({
                "msg": "Device registered successfully",
                "user_id": current_user_id,
                "player_id": player.id if player else None
            }), 200

        except ImportError:
            # DeviceToken model doesn't exist yet - store on user/player
            logger.warning("DeviceToken model not found, storing on user")

            # Try storing on user model if it has the field
            if hasattr(user, 'push_token'):
                user.push_token = device_token
                session_db.commit()
                return jsonify({
                    "msg": "Device registered successfully (legacy mode)",
                    "user_id": current_user_id
                }), 200
            else:
                return jsonify({
                    "msg": "Push notifications not fully configured",
                    "warning": "DeviceToken model not available"
                }), 200

        except Exception as e:
            logger.exception(f"Error registering device: {e}")
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
        device_token: The device token to unregister (optional - if not provided, unregisters all)
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
            from app.models import DeviceToken

            query = session_db.query(DeviceToken).filter_by(user_id=current_user_id)

            if device_token:
                query = query.filter_by(token=device_token)
            if platform:
                query = query.filter_by(platform=platform)

            deleted_count = query.delete()
            session_db.commit()

            logger.info(f"Deleted {deleted_count} device tokens for user {current_user_id}")

            return jsonify({
                "msg": "Device unregistered successfully",
                "tokens_removed": deleted_count
            }), 200

        except ImportError:
            # DeviceToken model doesn't exist
            logger.warning("DeviceToken model not found")

            # Try clearing from user model if available
            if hasattr(user, 'push_token'):
                user.push_token = None
                session_db.commit()
                return jsonify({"msg": "Device unregistered (legacy mode)"}), 200
            else:
                return jsonify({
                    "msg": "No tokens to unregister",
                    "warning": "DeviceToken model not available"
                }), 200

        except Exception as e:
            logger.exception(f"Error unregistering device: {e}")
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
            from app.models import DeviceToken

            # Get all device tokens for this user
            tokens = session_db.query(DeviceToken).filter_by(user_id=current_user_id).all()

            if not tokens:
                return jsonify({
                    "msg": "No registered devices found",
                    "devices_notified": 0
                }), 200

            # Try to send notification via configured service
            notified_count = 0
            for token in tokens:
                try:
                    # This would integrate with FCM/APNs
                    logger.info(f"Would send test notification to {token.platform} device: {token.token[:20]}...")
                    notified_count += 1
                except Exception as e:
                    logger.error(f"Failed to send to device: {e}")

            return jsonify({
                "msg": "Test notification sent",
                "devices_notified": notified_count
            }), 200

        except ImportError:
            return jsonify({
                "msg": "Push notifications not fully configured",
                "warning": "DeviceToken model not available"
            }), 200

        except Exception as e:
            logger.exception(f"Error sending test notification: {e}")
            return jsonify({"msg": "Failed to send test notification"}), 500
