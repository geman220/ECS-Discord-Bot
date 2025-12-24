"""
Navbar Notifications API
========================

REST API endpoints for the navbar notification dropdown.
Uses the existing Notification model from app/models/communication.py
"""

from datetime import datetime, timedelta
from flask import Blueprint, jsonify, request, current_app
from flask_login import login_required, current_user
from app.core import db
from app.models import Notification
import logging

logger = logging.getLogger(__name__)


def _get_limiter():
    """Get the rate limiter from the current app, if available."""
    return getattr(current_app, 'limiter', None)


navbar_notifications_bp = Blueprint('navbar_notifications', __name__, url_prefix='/api/notifications')


def register_rate_limit_exemptions(app):
    """
    Register rate limit exemptions for high-frequency presence endpoints.
    Call this after the blueprint is registered to the app.
    """
    limiter = getattr(app, 'limiter', None)
    if limiter:
        # Exempt presence endpoints - they poll frequently and shouldn't hit rate limits
        limiter.exempt(get_my_presence)
        limiter.exempt(get_user_presence)
        limiter.exempt(refresh_presence)
        limiter.exempt(get_online_users)
        limiter.exempt(check_batch_presence)
        logger.info("Rate limit exemptions registered for presence endpoints")


def _time_ago(dt):
    """Convert datetime to human-readable time ago string"""
    if not dt:
        return ''
    delta = datetime.utcnow() - dt

    if delta.days > 30:
        return dt.strftime('%b %d')
    elif delta.days > 0:
        return f'{delta.days}d ago'
    elif delta.seconds >= 3600:
        hours = delta.seconds // 3600
        return f'{hours}h ago'
    elif delta.seconds >= 60:
        minutes = delta.seconds // 60
        return f'{minutes}m ago'
    else:
        return 'Just now'


def _notification_to_dict(notification):
    """Serialize a notification for API response"""
    # Icon color mapping based on type
    color_map = {
        'match_result': 'success',
        'match_reminder': 'primary',
        'rsvp_reminder': 'warning',
        'team_update': 'info',
        'announcement': 'primary',
        'system': 'secondary',
        'success': 'success',
        'warning': 'warning',
        'error': 'danger',
        'info': 'info',
    }

    return {
        'id': notification.id,
        'type': notification.notification_type,
        'title': notification.notification_type.replace('_', ' ').title(),
        'message': notification.content,
        'icon': notification.icon_class(),
        'icon_color': color_map.get(notification.notification_type, 'primary'),
        'is_read': notification.read,
        'time_ago': _time_ago(notification.created_at),
        'created_at': notification.created_at.isoformat() if notification.created_at else None,
    }


@navbar_notifications_bp.route('', methods=['GET'])
@login_required
def get_notifications():
    """
    Get notifications for the current user

    Query params:
        limit: Number of notifications to return (default 10, max 50)
        include_read: Include read notifications (default false)
    """
    try:
        limit = min(int(request.args.get('limit', 10)), 50)
        include_read = request.args.get('include_read', 'false').lower() == 'true'

        query = Notification.query.filter_by(user_id=current_user.id)

        if not include_read:
            query = query.filter_by(read=False)

        notifications = query.order_by(Notification.created_at.desc()).limit(limit).all()

        unread_count = Notification.query.filter_by(
            user_id=current_user.id,
            read=False
        ).count()

        return jsonify({
            'success': True,
            'notifications': [_notification_to_dict(n) for n in notifications],
            'unread_count': unread_count,
            'has_more': len(notifications) >= limit
        })

    except Exception as e:
        logger.error(f"Error fetching notifications: {e}")
        return jsonify({
            'success': False,
            'error': 'Failed to fetch notifications'
        }), 500


@navbar_notifications_bp.route('/count', methods=['GET'])
@login_required
def get_notification_count():
    """Get unread notification count for badge display"""
    try:
        count = Notification.query.filter_by(
            user_id=current_user.id,
            read=False
        ).count()
        return jsonify({
            'success': True,
            'count': count
        })
    except Exception as e:
        logger.error(f"Error getting notification count: {e}")
        return jsonify({
            'success': False,
            'count': 0
        }), 500


@navbar_notifications_bp.route('/<int:notification_id>/read', methods=['POST'])
@login_required
def mark_notification_read(notification_id):
    """Mark a single notification as read"""
    try:
        notification = Notification.query.filter_by(
            id=notification_id,
            user_id=current_user.id
        ).first()

        if not notification:
            return jsonify({
                'success': False,
                'error': 'Notification not found'
            }), 404

        notification.read = True
        db.session.commit()

        unread_count = Notification.query.filter_by(
            user_id=current_user.id,
            read=False
        ).count()

        return jsonify({
            'success': True,
            'unread_count': unread_count
        })

    except Exception as e:
        logger.error(f"Error marking notification read: {e}")
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': 'Failed to mark notification as read'
        }), 500


@navbar_notifications_bp.route('/mark-all-read', methods=['POST'])
@login_required
def mark_all_notifications_read():
    """Mark all notifications as read for current user"""
    try:
        Notification.query.filter_by(
            user_id=current_user.id,
            read=False
        ).update({'read': True})
        db.session.commit()

        return jsonify({
            'success': True,
            'unread_count': 0
        })

    except Exception as e:
        logger.error(f"Error marking all notifications read: {e}")
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': 'Failed to mark notifications as read'
        }), 500


@navbar_notifications_bp.route('/<int:notification_id>', methods=['DELETE'])
@login_required
def delete_notification(notification_id):
    """Delete a single notification"""
    try:
        notification = Notification.query.filter_by(
            id=notification_id,
            user_id=current_user.id
        ).first()

        if not notification:
            return jsonify({
                'success': False,
                'error': 'Notification not found'
            }), 404

        db.session.delete(notification)
        db.session.commit()

        # Get updated count
        unread_count = Notification.query.filter_by(
            user_id=current_user.id,
            read=False
        ).count()

        return jsonify({
            'success': True,
            'unread_count': unread_count
        })

    except Exception as e:
        logger.error(f"Error deleting notification: {e}")
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': 'Failed to delete notification'
        }), 500


@navbar_notifications_bp.route('/clear-all', methods=['DELETE'])
@login_required
def clear_all_notifications():
    """Delete all notifications for current user"""
    try:
        deleted_count = Notification.query.filter_by(
            user_id=current_user.id
        ).delete()
        db.session.commit()

        return jsonify({
            'success': True,
            'deleted_count': deleted_count,
            'unread_count': 0
        })

    except Exception as e:
        logger.error(f"Error clearing all notifications: {e}")
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': 'Failed to clear notifications'
        }), 500


@navbar_notifications_bp.route('/<int:notification_id>', methods=['GET'])
@login_required
def get_notification_detail(notification_id):
    """Get full details for a single notification"""
    try:
        notification = Notification.query.filter_by(
            id=notification_id,
            user_id=current_user.id
        ).first()

        if not notification:
            return jsonify({
                'success': False,
                'error': 'Notification not found'
            }), 404

        return jsonify({
            'success': True,
            'notification': {
                **_notification_to_dict(notification),
                'full_content': notification.content,
                'created_at_formatted': notification.created_at.strftime('%B %d, %Y at %I:%M %p') if notification.created_at else None,
            }
        })

    except Exception as e:
        logger.error(f"Error getting notification detail: {e}")
        return jsonify({
            'success': False,
            'error': 'Failed to get notification'
        }), 500


# ============================================================================
# NOTIFICATION CREATION HELPERS (for use by other parts of the app)
# ============================================================================

def create_notification(user_id, content, notification_type='system', icon=None):
    """
    Create a notification for a user

    Args:
        user_id: Target user ID
        content: Notification message
        notification_type: Type (system, match_result, rsvp_reminder, etc.)
        icon: Optional icon class (defaults based on type)
    """
    notification = Notification(
        user_id=user_id,
        content=content,
        notification_type=notification_type,
        icon=icon,
        read=False
    )
    db.session.add(notification)
    return notification


def create_match_result_notification(user_id, opponent_name, won=True):
    """Create a match result notification"""
    if won:
        content = f"Your team won against {opponent_name}!"
        notification_type = 'success'
        icon = 'ti ti-trophy'
    else:
        content = f"Match against {opponent_name} has ended"
        notification_type = 'info'
        icon = 'ti ti-calendar-check'

    return create_notification(user_id, content, notification_type, icon)


def create_rsvp_reminder_notification(user_id, match_info):
    """Create an RSVP reminder notification"""
    content = f"Please RSVP for your upcoming match: {match_info}"
    return create_notification(user_id, content, 'warning', 'ti ti-clipboard-check')


def create_welcome_notification(user_id, username):
    """Create a welcome notification for new users"""
    content = f"Welcome to ECS Soccer, {username}! Your account is all set up."
    return create_notification(user_id, content, 'success', 'ti ti-confetti')


# ============================================================================
# PRESENCE / ONLINE STATUS API
# ============================================================================

@navbar_notifications_bp.route('/presence', methods=['GET'])
@login_required
def get_my_presence():
    """
    Get current user's online presence status.
    Used by navbar to show real online indicator.
    """
    try:
        from app.sockets.presence import PresenceManager

        is_online = PresenceManager.is_user_online(current_user.id)
        presence_data = PresenceManager.get_user_presence(current_user.id)

        return jsonify({
            'success': True,
            'online': is_online,
            'presence': presence_data,
            'user_id': current_user.id
        })

    except Exception as e:
        logger.error(f"Error getting presence: {e}")
        return jsonify({
            'success': False,
            'online': False,
            'error': 'Failed to check presence'
        }), 500


@navbar_notifications_bp.route('/presence/<int:user_id>', methods=['GET'])
@login_required
def get_user_presence(user_id):
    """
    Check if a specific user is online.
    Useful for profile pages, chat, etc.
    """
    try:
        from app.sockets.presence import PresenceManager

        is_online = PresenceManager.is_user_online(user_id)

        return jsonify({
            'success': True,
            'online': is_online,
            'user_id': user_id
        })

    except Exception as e:
        logger.error(f"Error checking user presence: {e}")
        return jsonify({
            'success': False,
            'online': False
        }), 500


@navbar_notifications_bp.route('/presence/refresh', methods=['POST'])
@login_required
def refresh_presence():
    """
    Refresh current user's presence TTL.
    Call periodically to keep user shown as online.
    """
    try:
        from app.sockets.presence import PresenceManager

        PresenceManager.refresh_presence(current_user.id)

        return jsonify({
            'success': True,
            'message': 'Presence refreshed'
        })

    except Exception as e:
        logger.error(f"Error refreshing presence: {e}")
        return jsonify({
            'success': False,
            'error': 'Failed to refresh presence'
        }), 500


@navbar_notifications_bp.route('/presence/online-users', methods=['GET'])
@login_required
def get_online_users():
    """
    Get list of currently online users that the current user can message.
    Used by the messenger widget to show messageable online users.
    Returns up to 100 online users with optional player info.

    Query params:
        details: Include full user details (default: false)
        limit: Max users to return (default: 50, max: 100)
        filter_messageable: Only show users current user can message (default: true)
    """
    try:
        from app.sockets.presence import PresenceManager
        from app.models import User, Player, MessagingPermission, MessagingSettings, Role

        include_details = request.args.get('details', 'false').lower() == 'true'
        limit = min(int(request.args.get('limit', 50)), 100)
        filter_messageable = request.args.get('filter_messageable', 'true').lower() == 'true'

        online_user_ids = PresenceManager.get_online_users(limit=limit * 2)  # Get more to account for filtering

        if not include_details:
            return jsonify({
                'success': True,
                'online_user_ids': list(online_user_ids)[:limit],
                'count': len(online_user_ids)
            })

        # Get user details for online users
        from app.core import db
        online_users = db.session.query(User).filter(
            User.id.in_(list(online_user_ids)),
            User.id != current_user.id  # Exclude self
        ).options(
            db.joinedload(User.player),
            db.joinedload(User.roles)
        ).all()

        # Get current user's role IDs for permission checking
        current_user_role_ids = []
        for role in current_user.roles:
            if hasattr(role, 'id'):
                current_user_role_ids.append(role.id)
            elif isinstance(role, str):
                role_obj = Role.query.filter_by(name=role).first()
                if role_obj:
                    current_user_role_ids.append(role_obj.id)

        # Check if messaging is enabled
        settings = MessagingSettings.get_settings()
        messaging_enabled = settings.enabled

        users_data = []
        for user in online_users:
            # Filter by messaging permissions if requested
            if filter_messageable and messaging_enabled:
                # Get recipient's role IDs
                recipient_role_ids = []
                for role in user.roles:
                    if hasattr(role, 'id'):
                        recipient_role_ids.append(role.id)
                    elif isinstance(role, str):
                        role_obj = Role.query.filter_by(name=role).first()
                        if role_obj:
                            recipient_role_ids.append(role_obj.id)

                # Check if current user can message this user
                if not current_user_role_ids or not recipient_role_ids:
                    continue
                if not MessagingPermission.can_message(current_user_role_ids, recipient_role_ids):
                    continue

            user_data = {
                'id': user.id,
                'username': user.username,
                'name': user.player.name if user.player else user.username,
                'profile_url': f'/players/profile/{user.player.id}' if user.player else None,
                'avatar_url': user.player.profile_picture_url if user.player else None
            }
            users_data.append(user_data)

            # Stop if we've reached the limit
            if len(users_data) >= limit:
                break

        return jsonify({
            'success': True,
            'online_users': users_data,
            'online_user_ids': [u['id'] for u in users_data],
            'count': len(users_data)
        })

    except Exception as e:
        logger.error(f"Error getting online users: {e}")
        return jsonify({
            'success': False,
            'online_user_ids': [],
            'count': 0,
            'error': 'Failed to get online users'
        }), 500


@navbar_notifications_bp.route('/presence/check-batch', methods=['POST'])
@login_required
def check_batch_presence():
    """
    Check online status for a batch of user IDs.
    More efficient than checking one at a time.

    Request body: { "user_ids": [1, 2, 3, ...] }
    """
    try:
        from app.sockets.presence import PresenceManager

        data = request.get_json() or {}
        user_ids = data.get('user_ids', [])

        if not user_ids:
            return jsonify({
                'success': True,
                'online_status': {}
            })

        # Limit to 100 users per request
        user_ids = user_ids[:100]

        online_status = {}
        for user_id in user_ids:
            try:
                online_status[str(user_id)] = PresenceManager.is_user_online(user_id)
            except Exception:
                online_status[str(user_id)] = False

        return jsonify({
            'success': True,
            'online_status': online_status
        })

    except Exception as e:
        logger.error(f"Error checking batch presence: {e}")
        return jsonify({
            'success': False,
            'online_status': {},
            'error': 'Failed to check presence'
        }), 500
