from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required
from sqlalchemy import func
from app.models import User, UserFCMToken
from app.models.communication import Notification
from app.services.notification_service import notification_service
from app.core import db
from app.decorators import role_required
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

notification_admin_bp = Blueprint('notification_admin', __name__, url_prefix='/admin/notifications')

@notification_admin_bp.route('/')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def notification_dashboard():
    """Main notification management dashboard"""
    return render_template('admin/push_notifications.html')

@notification_admin_bp.route('/status')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def notification_status():
    """Get notification system status and statistics"""
    try:
        # Check if Firebase is configured
        firebase_configured = notification_service._initialized

        # Get FCM token statistics
        total_tokens = UserFCMToken.query.filter_by(is_active=True).count()
        ios_tokens = UserFCMToken.query.filter_by(is_active=True, platform='ios').count()
        android_tokens = UserFCMToken.query.filter_by(is_active=True, platform='android').count()

        # Count notifications sent in the last 24 hours
        cutoff_24h = datetime.utcnow() - timedelta(hours=24)
        notifications_sent_24h = Notification.query.filter(
            Notification.created_at >= cutoff_24h
        ).count()

        return jsonify({
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
            'firebase_configured': False,
            'stats': {
                'total_devices': 0,
                'ios_devices': 0,
                'android_devices': 0,
                'notifications_sent_24h': 0
            }
        }), 500

@notification_admin_bp.route('/recent-activity')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def recent_activity():
    """Get recent notification activity aggregated by type and time period"""
    try:
        # Get notification activity from the last 7 days
        cutoff_date = datetime.utcnow() - timedelta(days=7)

        # Query notifications grouped by type and approximate time period
        recent_notifications = db.session.query(
            Notification.notification_type,
            func.min(Notification.created_at).label('first_sent'),
            func.max(Notification.created_at).label('last_sent'),
            func.count(Notification.id).label('recipient_count')
        ).filter(
            Notification.created_at >= cutoff_date
        ).group_by(
            Notification.notification_type
        ).order_by(
            func.max(Notification.created_at).desc()
        ).limit(10).all()

        activities = []
        type_titles = {
            'match_reminder': 'Match Reminder',
            'rsvp_reminder': 'RSVP Reminder',
            'system': 'System Notification',
            'broadcast': 'Broadcast Message',
            'info': 'Information',
            'warning': 'Warning Alert',
            'success': 'Success Notification',
            'error': 'Error Alert'
        }

        for notif in recent_notifications:
            activities.append({
                'timestamp': notif.last_sent.isoformat() if notif.last_sent else None,
                'type': notif.notification_type,
                'title': type_titles.get(notif.notification_type, notif.notification_type.title()),
                'recipients': notif.recipient_count,
                'success_rate': 100,  # In-app notifications are always delivered
                'status': 'success'
            })

        # If no recent activity, return empty list (not mock data)
        return jsonify({
            'activities': activities
        })

    except Exception as e:
        logger.error(f"Error getting recent activity: {e}")
        return jsonify({
            'activities': []
        }), 500

@notification_admin_bp.route('/broadcast', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def admin_broadcast():
    """Send broadcast notification from admin panel"""
    try:
        data = request.get_json()
        title = data.get('title', 'ECS Soccer')
        message = data.get('message', '')
        target = data.get('target', 'all')
        
        if not message:
            return jsonify({'msg': 'Message is required'}), 400
        
        # Get target tokens based on selection
        query = UserFCMToken.query.filter_by(is_active=True)
        
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
            query = query.filter(UserFCMToken.user_id.in_(coach_ids))
        elif target == 'admins':
            # Get admin user IDs
            admin_users = User.query.join(User.roles).filter(
                db.or_(
                    db.text("roles.name = 'Global Admin'"),
                    db.text("roles.name = 'Pub League Admin'")
                )
            ).all()
            admin_ids = [u.id for u in admin_users]
            query = query.filter(UserFCMToken.user_id.in_(admin_ids))
        # 'all' - no additional filtering needed
        
        tokens_objs = query.all()
        tokens = [token.fcm_token for token in tokens_objs]
        
        if not tokens:
            return jsonify({'msg': 'No FCM tokens found for selected target'}), 404
        
        result = notification_service.send_general_notification(tokens, title, message)
        
        return jsonify({
            'msg': f'Broadcast sent to {len(tokens)} devices',
            'result': result
        }), 200
        
    except Exception as e:
        logger.error(f"Error sending admin broadcast: {e}")
        return jsonify({'msg': 'Internal server error'}), 500

@notification_admin_bp.route('/test-notification', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def admin_test_notification():
    """Send test notification to admin's devices"""
    try:
        from flask_login import current_user
        
        # Get current user's FCM tokens
        user_tokens = UserFCMToken.query.filter_by(
            user_id=current_user.id, 
            is_active=True
        ).all()
        
        if not user_tokens:
            return jsonify({'msg': 'No FCM tokens found for your account. Please register a device first.'}), 404
        
        tokens = [token.fcm_token for token in user_tokens]
        
        result = notification_service.send_general_notification(
            tokens,
            "🧪 ECS Soccer Admin Test",
            "Test notification from the admin panel - your push notifications are working perfectly!"
        )
        
        return jsonify({
            'msg': 'Test notification sent',
            'result': result
        }), 200
        
    except Exception as e:
        logger.error(f"Error sending admin test notification: {e}")
        return jsonify({'msg': 'Internal server error'}), 500

@notification_admin_bp.route('/cleanup-tokens', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def cleanup_invalid_tokens():
    """Clean up invalid/inactive FCM tokens"""
    try:
        # TODO: Implement token validation and cleanup
        # This would typically involve:
        # 1. Testing tokens against Firebase
        # 2. Removing invalid ones from database
        # 3. Marking inactive tokens
        
        # For now, just remove tokens that haven't been updated in 90 days
        cutoff_date = datetime.utcnow() - timedelta(days=90)
        old_tokens = UserFCMToken.query.filter(
            UserFCMToken.updated_at < cutoff_date
        ).all()
        
        count = len(old_tokens)
        for token in old_tokens:
            token.is_active = False
        
        db.session.commit()
        
        return jsonify({
            'msg': f'Cleaned up {count} old tokens',
            'count': count
        }), 200
        
    except Exception as e:
        logger.error(f"Error cleaning up tokens: {e}")
        return jsonify({'msg': 'Internal server error'}), 500

@notification_admin_bp.route('/tokens')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def list_tokens():
    """List all FCM tokens for management"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = 50
        
        tokens = UserFCMToken.query.join(User).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        token_data = []
        for token in tokens.items:
            token_data.append({
                'id': token.id,
                'user_id': token.user_id,
                'username': token.user.username,
                'platform': token.platform,
                'is_active': token.is_active,
                'created_at': token.created_at.isoformat(),
                'updated_at': token.updated_at.isoformat()
            })
        
        return jsonify({
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
        return jsonify({'msg': 'Internal server error'}), 500