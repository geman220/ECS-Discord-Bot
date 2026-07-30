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


@mobile_api_v2.route('/notifications/register-token', methods=['POST'])
@jwt_required()
def register_fcm_token():
    """
    Register an FCM token for push notifications.

    Expected JSON parameters:
        fcm_token: The Firebase Cloud Messaging token
        platform: 'ios' or 'android'

    Returns:
        JSON with registration result
    """
    current_user_id = int(get_jwt_identity())

    data = request.get_json(silent=True) or {}
    fcm_token = data.get('fcm_token')
    platform = data.get('platform', 'unknown')
    # The client sends this on every registration and it was dropped on the
    # floor here (only /notifications/register at :163 stored it), which is why
    # the admin version-distribution widget was always empty.
    app_version = data.get('app_version')

    if not fcm_token:
        return jsonify({"msg": "Missing fcm_token"}), 400

    # Reject debug/simulator tokens in non-debug environments
    if fcm_token.startswith('DEBUG_SIMULATOR_TOKEN_'):
        logger.debug(f"Ignoring debug simulator token for user {current_user_id}")
        return jsonify({"msg": "Token registered successfully"}), 200

    if platform not in ('ios', 'android', 'web', 'unknown'):
        platform = 'unknown'

    logger.info(f"Registering FCM token for user {current_user_id}: platform={platform}")

    with managed_session() as session_db:
        user = session_db.query(User).get(current_user_id)
        if not user:
            return jsonify({"msg": "User not found"}), 404

        try:
            existing = session_db.query(UserFCMToken).filter_by(
                fcm_token=fcm_token
            ).first()

            if existing:
                if existing.user_id != current_user_id:
                    existing.user_id = current_user_id
                existing.platform = platform
                existing.is_active = True
                if app_version:
                    existing.app_version = app_version
                existing.updated_at = datetime.utcnow()
                existing.last_used = datetime.utcnow()
            else:
                # Deactivate stale tokens for this user on the same platform
                # (device got a new token, old one is no longer valid)
                stale_count = session_db.query(UserFCMToken).filter(
                    UserFCMToken.user_id == current_user_id,
                    UserFCMToken.platform == platform,
                    UserFCMToken.is_active == True,
                    UserFCMToken.fcm_token != fcm_token
                ).update({
                    'is_active': False,
                    'deactivated_reason': 'replaced_by_new_token',
                    'updated_at': datetime.utcnow()
                }, synchronize_session=False)

                if stale_count:
                    logger.info(f"Deactivated {stale_count} old {platform} tokens for user {current_user_id}")

                new_token = UserFCMToken(
                    user_id=current_user_id,
                    fcm_token=fcm_token,
                    platform=platform,
                    app_version=app_version,
                    is_active=True,
                )
                session_db.add(new_token)

            session_db.commit()

            return jsonify({"msg": "Token registered successfully"}), 200

        except Exception as e:
            logger.exception(f"Error registering FCM token: {e}")
            session_db.rollback()
            return jsonify({"msg": "Failed to register token"}), 500


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

    data = request.get_json(silent=True) or {}
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

    DEPRECATED ALIAS of /account/notification-preferences, which is what the
    client actually uses. This route named the same underlying columns
    differently (`team_updates` / `league_updates` vs `team_notifications` /
    `league_announcements`) and was missing four keys entirely, so the two
    endpoints disagreed about the same user's settings.

    It now reads and writes BOTH spellings and carries the full key set, so
    whichever one a client calls it sees the same state. Prefer
    /account/notification-preferences for new work.

    Returns:
        JSON with preferences
    """
    current_user_id = int(get_jwt_identity())

    def _prefs(user):
        """Full preference payload in both naming conventions."""
        return {
            "email_notifications": getattr(user, 'email_notifications', True),
            "sms_notifications": getattr(user, 'sms_notifications', False),
            "discord_notifications": getattr(user, 'discord_notifications', True),
            "push_notifications": getattr(user, 'push_notifications', True),
            "dm_notifications": getattr(user, 'dm_notifications', True),
            "match_reminders": getattr(user, 'match_reminder_notifications', True),
            "rsvp_reminders": getattr(user, 'rsvp_reminder_notifications', True),
            # Both spellings of the same two columns.
            "team_updates": getattr(user, 'team_update_notifications', True),
            "team_notifications": getattr(user, 'team_update_notifications', True),
            "league_updates": getattr(user, 'announcement_notifications', True),
            "league_announcements": getattr(user, 'announcement_notifications', True),
            # Previously missing here entirely.
            "general_announcements": getattr(user, 'general_announcements', True),
            "feedback_updates": getattr(user, 'feedback_update_notifications', True),
            "feedback_alerts": getattr(user, 'feedback_alert_notifications', True),
            "draft_alerts": getattr(user, 'draft_alert_notifications', True),
        }

    with managed_session() as session_db:
        user = session_db.query(User).get(current_user_id)
        if not user:
            return jsonify({"msg": "User not found"}), 404

        player = session_db.query(Player).filter_by(user_id=current_user_id).first()

        if request.method == 'GET':
            return jsonify({"preferences": _prefs(user)}), 200

        else:  # PUT
            data = request.get_json(silent=True) or {}

            # Update user-level preferences
            if 'email_notifications' in data:
                user.email_notifications = data['email_notifications']
            if 'sms_notifications' in data:
                user.sms_notifications = data['sms_notifications']
            if 'discord_notifications' in data:
                user.discord_notifications = data['discord_notifications']
            if 'push_notifications' in data:
                user.push_notifications = bool(data['push_notifications'])
            if 'dm_notifications' in data:
                user.dm_notifications = bool(data['dm_notifications'])

            # Reminder / update toggles live on the USER (the reminder senders
            # read user.*_notifications). Writing Player.notify_* persisted nothing.
            if 'match_reminders' in data:
                user.match_reminder_notifications = bool(data['match_reminders'])
            if 'rsvp_reminders' in data:
                user.rsvp_reminder_notifications = bool(data['rsvp_reminders'])

            # Accept either spelling for the two aliased columns, so a client on
            # /account/notification-preferences naming and one on this route's
            # naming can both write successfully.
            for key in ('team_updates', 'team_notifications'):
                if key in data:
                    user.team_update_notifications = bool(data[key])
            for key in ('league_updates', 'league_announcements'):
                if key in data:
                    user.announcement_notifications = bool(data[key])

            if 'general_announcements' in data:
                user.general_announcements = bool(data['general_announcements'])
            if 'feedback_updates' in data:
                user.feedback_update_notifications = bool(data['feedback_updates'])
            if 'feedback_alerts' in data:
                user.feedback_alert_notifications = bool(data['feedback_alerts'])
            if 'draft_alerts' in data:
                user.draft_alert_notifications = bool(data['draft_alerts'])

            session_db.commit()

            return jsonify({
                "msg": "Preferences updated",
                "preferences": _prefs(user)
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

    data = request.get_json(silent=True) or {}
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
                        # send_test_notification returns a DICT — including on
                        # failure ({"success": False, ...}) — so a bare `if
                        # success:` was always true and counted every failed send
                        # as a device notified.
                        if isinstance(success, dict):
                            success = success.get('success', False)
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


# ============================================================================
# In-app notification store (the "bell")
#
# NotificationOrchestrator._create_in_app_notification writes a Notification row
# for EVERY user on EVERY send, and a full CRUD API already exists — but only at
# routes/navbar_notifications.py, which is Flask-Login (session cookie) auth and
# therefore unreachable from the app. The mobile Notification Center was
# consequently 100% device-local: a user who denied push, was offline past the
# FCM TTL, or picked up a second device saw an empty list while the server held
# their whole history, and the mobile bell could never agree with the web bell.
#
# These reuse the web serializer (_notification_to_dict) so the two surfaces
# cannot drift on shape or wording.
# ============================================================================


@mobile_api_v2.route('/notifications', methods=['GET'])
@jwt_required()
def list_notifications():
    """
    List the caller's in-app notifications, newest first.

    Query params:
        limit:       page size (default 20, max 50)
        offset:      page offset (default 0)
        unread_only: 'true' to exclude already-read rows (default false)

    Returns:
        {"notifications": [...], "unread_count": int, "total": int,
         "limit": int, "offset": int, "has_more": bool}
    """
    current_user_id = int(get_jwt_identity())
    limit = min(max(request.args.get('limit', 20, type=int), 1), 50)
    offset = max(request.args.get('offset', 0, type=int), 0)
    unread_only = (request.args.get('unread_only', 'false') or '').lower() == 'true'

    try:
        from app.models import Notification
        from app.routes.navbar_notifications import _notification_to_dict

        with managed_session() as session_db:
            query = session_db.query(Notification).filter_by(user_id=current_user_id)
            if unread_only:
                query = query.filter_by(read=False)

            total = query.count()
            rows = query.order_by(Notification.created_at.desc()) \
                .offset(offset).limit(limit).all()

            unread_count = session_db.query(Notification).filter_by(
                user_id=current_user_id, read=False
            ).count()

            return jsonify({
                "notifications": [_notification_to_dict(n) for n in rows],
                "unread_count": unread_count,
                "total": total,
                "limit": limit,
                "offset": offset,
                "has_more": (offset + len(rows)) < total,
            }), 200
    except Exception as e:
        logger.exception(f"Error listing notifications: {e}")
        return jsonify({"msg": "Failed to fetch notifications"}), 500


@mobile_api_v2.route('/notifications/count', methods=['GET'])
@jwt_required()
def notification_unread_count():
    """Unread count for the bell badge."""
    current_user_id = int(get_jwt_identity())
    try:
        from app.models import Notification
        with managed_session() as session_db:
            count = session_db.query(Notification).filter_by(
                user_id=current_user_id, read=False
            ).count()
            return jsonify({"count": count}), 200
    except Exception as e:
        logger.exception(f"Error getting notification count: {e}")
        # A failed badge must not look like "you have no notifications"
        # any louder than it has to — report the failure explicitly.
        return jsonify({"msg": "Failed to get count"}), 500


@mobile_api_v2.route('/notifications/<int:notification_id>/read', methods=['POST'])
@jwt_required()
def mark_notification_read_mobile(notification_id):
    """Mark one notification read. Scoped to the caller's own rows."""
    current_user_id = int(get_jwt_identity())
    try:
        from app.models import Notification
        with managed_session() as session_db:
            row = session_db.query(Notification).filter_by(
                id=notification_id, user_id=current_user_id
            ).first()
            if not row:
                return jsonify({"msg": "Notification not found"}), 404

            row.read = True
            session_db.commit()

            unread_count = session_db.query(Notification).filter_by(
                user_id=current_user_id, read=False
            ).count()
            return jsonify({
                "msg": "Notification marked as read",
                "notification_id": notification_id,
                "unread_count": unread_count,
            }), 200
    except Exception as e:
        logger.exception(f"Error marking notification {notification_id} read: {e}")
        return jsonify({"msg": "Failed to mark notification read"}), 500


@mobile_api_v2.route('/notifications/mark-all-read', methods=['POST'])
@jwt_required()
def mark_all_notifications_read_mobile():
    """Mark every unread notification for the caller as read."""
    current_user_id = int(get_jwt_identity())
    try:
        from app.models import Notification
        with managed_session() as session_db:
            updated = session_db.query(Notification).filter_by(
                user_id=current_user_id, read=False
            ).update({'read': True}, synchronize_session=False)
            session_db.commit()
            return jsonify({
                "msg": "All notifications marked as read",
                "updated": updated,
                "unread_count": 0,
            }), 200
    except Exception as e:
        logger.exception(f"Error marking all notifications read: {e}")
        return jsonify({"msg": "Failed to mark notifications read"}), 500
