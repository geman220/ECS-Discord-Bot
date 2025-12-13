# app/admin_panel/routes/communication/push_admin.py

"""
Push Notification Admin Routes

Admin operations for push notifications including broadcast, test, token management, and status.
"""

import logging
from datetime import datetime, timedelta

from flask import request, jsonify
from flask_login import login_required, current_user

from app.admin_panel import admin_panel_bp
from app.core import db
from app.models.admin_config import AdminAuditLog
from app.models.communication import DeviceToken, Notification
from app.models.core import User
from app.decorators import role_required

logger = logging.getLogger(__name__)


@admin_panel_bp.route('/communication/push-notifications/broadcast', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def push_notification_broadcast():
    """Send broadcast notification from admin panel."""
    try:
        from app.services.notification_service import notification_service

        # Try to use UserFCMToken if available, fall back to DeviceToken
        try:
            from app.models import UserFCMToken
            token_model = UserFCMToken
        except ImportError:
            token_model = DeviceToken

        data = request.get_json()
        title = data.get('title', 'ECS Soccer')
        message = data.get('message', '')
        target = data.get('target', 'all')

        if not message:
            return jsonify({'success': False, 'message': 'Message is required'}), 400

        # Get target tokens based on selection
        query = token_model.query.filter_by(is_active=True)

        if target == 'ios':
            query = query.filter_by(platform='ios')
        elif target == 'android':
            query = query.filter_by(platform='android')
        elif target == 'coaches':
            # Get coach user IDs
            coach_users = User.query.join(User.roles).filter(
                db.or_(
                    db.text("roles.name = 'Pub League Coach'"),
                    db.text("roles.name = 'ECS FC Coach'")
                )
            ).all()
            coach_ids = [u.id for u in coach_users]
            query = query.filter(token_model.user_id.in_(coach_ids))
        elif target == 'admins':
            # Get admin user IDs
            admin_users = User.query.join(User.roles).filter(
                db.or_(
                    db.text("roles.name = 'Global Admin'"),
                    db.text("roles.name = 'Pub League Admin'")
                )
            ).all()
            admin_ids = [u.id for u in admin_users]
            query = query.filter(token_model.user_id.in_(admin_ids))

        tokens_objs = query.all()
        token_attr = 'fcm_token' if hasattr(token_model, 'fcm_token') else 'token'
        tokens = [getattr(token, token_attr) for token in tokens_objs]

        if not tokens:
            return jsonify({'success': False, 'message': 'No devices found for selected target'}), 404

        result = notification_service.send_general_notification(tokens, title, message)

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='push_notification_broadcast',
            resource_type='communication',
            resource_id='broadcast',
            new_value=f'Sent to {len(tokens)} devices: {title}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({
            'success': True,
            'message': f'Broadcast sent to {len(tokens)} devices',
            'result': result
        })

    except Exception as e:
        logger.error(f"Error sending push broadcast: {e}")
        return jsonify({'success': False, 'message': 'Internal server error'}), 500


@admin_panel_bp.route('/communication/push-notifications/test', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def push_notification_test():
    """Send test notification to admin's devices."""
    try:
        from app.services.notification_service import notification_service

        # Try to use UserFCMToken if available, fall back to DeviceToken
        try:
            from app.models import UserFCMToken
            token_model = UserFCMToken
        except ImportError:
            token_model = DeviceToken

        # Get current user's tokens
        user_tokens = token_model.query.filter_by(
            user_id=current_user.id,
            is_active=True
        ).all()

        if not user_tokens:
            return jsonify({
                'success': False,
                'message': 'No devices registered for your account. Please register a device first.'
            }), 404

        token_attr = 'fcm_token' if hasattr(token_model, 'fcm_token') else 'token'
        tokens = [getattr(token, token_attr) for token in user_tokens]

        result = notification_service.send_general_notification(
            tokens,
            "ECS Soccer Admin Test",
            "Test notification from the admin panel - your push notifications are working!"
        )

        return jsonify({
            'success': True,
            'message': 'Test notification sent',
            'result': result
        })

    except Exception as e:
        logger.error(f"Error sending test notification: {e}")
        return jsonify({'success': False, 'message': 'Internal server error'}), 500


@admin_panel_bp.route('/communication/push-notifications/cleanup-tokens', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def push_notification_cleanup_tokens():
    """Clean up invalid/inactive FCM tokens."""
    try:
        # Try to use UserFCMToken if available, fall back to DeviceToken
        try:
            from app.models import UserFCMToken
            token_model = UserFCMToken
        except ImportError:
            token_model = DeviceToken

        # Remove tokens that haven't been updated in 90 days
        cutoff_date = datetime.utcnow() - timedelta(days=90)
        old_tokens = token_model.query.filter(
            token_model.updated_at < cutoff_date
        ).all()

        count = len(old_tokens)
        for token in old_tokens:
            token.is_active = False

        db.session.commit()

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='push_notification_token_cleanup',
            resource_type='communication',
            resource_id='tokens',
            new_value=f'Cleaned up {count} old tokens',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({
            'success': True,
            'message': f'Cleaned up {count} old tokens',
            'count': count
        })

    except Exception as e:
        logger.error(f"Error cleaning up tokens: {e}")
        return jsonify({'success': False, 'message': 'Internal server error'}), 500


@admin_panel_bp.route('/communication/push-notifications/tokens')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def push_notification_tokens():
    """List all FCM tokens for management."""
    try:
        # Try to use UserFCMToken if available, fall back to DeviceToken
        try:
            from app.models import UserFCMToken
            token_model = UserFCMToken
        except ImportError:
            token_model = DeviceToken

        page = request.args.get('page', 1, type=int)
        per_page = 50

        tokens = token_model.query.join(User).paginate(
            page=page, per_page=per_page, error_out=False
        )

        token_data = []
        for token in tokens.items:
            token_data.append({
                'id': token.id,
                'user_id': token.user_id,
                'username': token.user.username if hasattr(token, 'user') and token.user else 'Unknown',
                'platform': getattr(token, 'platform', 'unknown'),
                'is_active': token.is_active,
                'created_at': token.created_at.isoformat() if token.created_at else None,
                'updated_at': token.updated_at.isoformat() if token.updated_at else None
            })

        return jsonify({
            'success': True,
            'tokens': token_data,
            'pagination': {
                'page': tokens.page,
                'pages': tokens.pages,
                'per_page': tokens.per_page,
                'total': tokens.total
            }
        })

    except Exception as e:
        logger.error(f"Error listing tokens: {e}")
        return jsonify({'success': False, 'message': 'Internal server error'}), 500


@admin_panel_bp.route('/communication/push-notifications/status')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def push_notification_status():
    """Get notification system status and statistics."""
    try:
        # Check if notification service is initialized
        try:
            from app.services.notification_service import notification_service
            firebase_configured = getattr(notification_service, '_initialized', False)
        except ImportError:
            firebase_configured = False

        # Try to use UserFCMToken if available, fall back to DeviceToken
        try:
            from app.models import UserFCMToken
            token_model = UserFCMToken
        except ImportError:
            token_model = DeviceToken

        # Get FCM token statistics
        total_tokens = token_model.query.filter_by(is_active=True).count()
        ios_tokens = token_model.query.filter_by(is_active=True, platform='ios').count() if hasattr(token_model, 'platform') else 0
        android_tokens = token_model.query.filter_by(is_active=True, platform='android').count() if hasattr(token_model, 'platform') else 0

        # Get notifications sent in last 24 hours
        yesterday = datetime.utcnow() - timedelta(days=1)
        notifications_sent_24h = Notification.query.filter(
            Notification.notification_type == 'push',
            Notification.created_at >= yesterday
        ).count()

        return jsonify({
            'success': True,
            'firebase_configured': firebase_configured,
            'stats': {
                'total_devices': total_tokens,
                'ios_devices': ios_tokens,
                'android_devices': android_tokens,
                'notifications_sent_24h': notifications_sent_24h
            }
        })

    except Exception as e:
        logger.error(f"Error getting notification status: {e}")
        return jsonify({
            'success': False,
            'firebase_configured': False,
            'stats': {
                'total_devices': 0,
                'ios_devices': 0,
                'android_devices': 0,
                'notifications_sent_24h': 0
            }
        }), 500
