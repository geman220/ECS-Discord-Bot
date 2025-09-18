from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.models import User, UserFCMToken, Match
from app.services.notification_service import notification_service
from app.core import db
import logging

logger = logging.getLogger(__name__)

notifications_bp = Blueprint('notifications', __name__, url_prefix='/api/v1/notifications')

# Exempt this entire blueprint from CSRF protection for mobile API usage
from app import csrf
csrf.exempt(notifications_bp)

@notifications_bp.route('/register-token', methods=['POST'])
@jwt_required()
def register_fcm_token():
    """Register user's FCM token"""
    try:
        user_id = int(get_jwt_identity())
        data = request.get_json()
        
        fcm_token = data.get('fcm_token')
        platform = data.get('platform', 'unknown')
        
        if not fcm_token:
            return jsonify({'msg': 'FCM token is required'}), 400
        
        # Check if token already exists
        existing_token = UserFCMToken.query.filter_by(
            user_id=user_id, 
            fcm_token=fcm_token
        ).first()
        
        if not existing_token:
            # Create new token record
            user_token = UserFCMToken(
                user_id=user_id,
                fcm_token=fcm_token,
                platform=platform,
                is_active=True
            )
            db.session.add(user_token)
            db.session.commit()
            logger.info(f"Registered FCM token for user {user_id}")
        else:
            # Update existing token
            existing_token.is_active = True
            existing_token.platform = platform
            db.session.commit()
            logger.info(f"Updated FCM token for user {user_id}")
        
        return jsonify({'msg': 'FCM token registered successfully'}), 200
        
    except Exception as e:
        logger.error(f"Error registering FCM token: {e}")
        return jsonify({'msg': 'Internal server error'}), 500

@notifications_bp.route('/send-test', methods=['POST'])
@jwt_required()
def send_test_notification():
    """Send test notification to user (for debugging)"""
    try:
        user_id = int(get_jwt_identity())
        
        # Get user's FCM tokens
        user_tokens = UserFCMToken.query.filter_by(
            user_id=user_id, 
            is_active=True
        ).all()
        
        if not user_tokens:
            return jsonify({'msg': 'No FCM tokens found for user'}), 404
        
        tokens = [token.fcm_token for token in user_tokens]
        
        result = notification_service.send_general_notification(
            tokens,
            "🏆 ECS Soccer Test",
            "Test notification - your push notifications are working!"
        )
        
        return jsonify({
            'msg': 'Test notification sent',
            'result': result
        }), 200
        
    except Exception as e:
        logger.error(f"Error sending test notification: {e}")
        return jsonify({'msg': 'Internal server error'}), 500

@notifications_bp.route('/send-match-reminder/<int:match_id>', methods=['POST'])
@jwt_required()
def send_match_reminder(match_id):
    """Send match reminder to all players in the match"""
    try:
        match = Match.query.get_or_404(match_id)
        
        # Get all players from both teams
        home_team_players = match.home_team.players if match.home_team else []
        away_team_players = match.away_team.players if match.away_team else []
        all_players = list(home_team_players) + list(away_team_players)
        
        # Get FCM tokens for all players
        player_ids = [player.user_id for player in all_players if player.user_id]
        tokens_query = UserFCMToken.query.filter(
            UserFCMToken.user_id.in_(player_ids),
            UserFCMToken.is_active == True
        ).all()
        
        tokens = [token.fcm_token for token in tokens_query]
        
        if not tokens:
            return jsonify({'msg': 'No FCM tokens found for match players'}), 404
        
        # Prepare match data
        match_data = {
            'id': match.id,
            'opponent': match.away_team.name if match.home_team else match.home_team.name,
            'location': match.location,
            'date': match.date_time.strftime('%Y-%m-%d') if hasattr(match, 'date_time') else 'TBD',
            'time': match.date_time.strftime('%H:%M') if hasattr(match, 'date_time') else 'TBD'
        }
        
        result = notification_service.send_match_reminder(tokens, match_data)
        
        return jsonify({
            'msg': f'Match reminder sent to {len(tokens)} devices',
            'result': result
        }), 200
        
    except Exception as e:
        logger.error(f"Error sending match reminder: {e}")
        return jsonify({'msg': 'Internal server error'}), 500

@notifications_bp.route('/send-rsvp-reminder/<int:match_id>', methods=['POST'])
@jwt_required()
def send_rsvp_reminder(match_id):
    """Send RSVP reminder to all players in the match"""
    try:
        match = Match.query.get_or_404(match_id)
        
        # Get all players from both teams who haven't RSVP'd
        home_team_players = match.home_team.players if match.home_team else []
        away_team_players = match.away_team.players if match.away_team else []
        all_players = list(home_team_players) + list(away_team_players)
        
        # Filter players who haven't RSVP'd (you'll need to implement this logic)
        # For now, send to all players
        player_ids = [player.user_id for player in all_players if player.user_id]
        
        tokens_query = UserFCMToken.query.filter(
            UserFCMToken.user_id.in_(player_ids),
            UserFCMToken.is_active == True
        ).all()
        
        tokens = [token.fcm_token for token in tokens_query]
        
        if not tokens:
            return jsonify({'msg': 'No FCM tokens found for match players'}), 404
        
        # Prepare match data
        match_data = {
            'id': match.id,
            'opponent': match.away_team.name if match.home_team else match.home_team.name,
            'date': match.date_time.strftime('%B %d') if hasattr(match, 'date_time') else 'TBD',
        }
        
        result = notification_service.send_rsvp_reminder(tokens, match_data)
        
        return jsonify({
            'msg': f'RSVP reminder sent to {len(tokens)} devices',
            'result': result
        }), 200
        
    except Exception as e:
        logger.error(f"Error sending RSVP reminder: {e}")
        return jsonify({'msg': 'Internal server error'}), 500

@notifications_bp.route('/broadcast', methods=['POST'])
@jwt_required()
def broadcast_notification():
    """Send notification to all users (admin only)"""
    try:
        # Add admin check here
        current_user = User.query.get(int(get_jwt_identity()))
        if not current_user.has_role('Global Admin'):  # Using your existing has_role method
            return jsonify({'msg': 'Admin access required'}), 403
        
        data = request.get_json()
        title = data.get('title', 'ECS Soccer')
        message = data.get('message', '')
        
        if not message:
            return jsonify({'msg': 'Message is required'}), 400
        
        # Get all active FCM tokens
        all_tokens = UserFCMToken.query.filter_by(is_active=True).all()
        tokens = [token.fcm_token for token in all_tokens]
        
        if not tokens:
            return jsonify({'msg': 'No active FCM tokens found'}), 404
        
        result = notification_service.send_general_notification(tokens, title, message)
        
        return jsonify({
            'msg': f'Broadcast sent to {len(tokens)} devices',
            'result': result
        }), 200
        
    except Exception as e:
        logger.error(f"Error sending broadcast: {e}")
        return jsonify({'msg': 'Internal server error'}), 500

@notifications_bp.route('/settings', methods=['GET', 'PUT'])
@jwt_required()
def notification_settings():
    """Get or update user notification settings"""
    try:
        user_id = int(get_jwt_identity())
        user = User.query.get_or_404(user_id)
        
        if request.method == 'GET':
            return jsonify({
                'push_notifications': getattr(user, 'push_notifications', True),
                'match_reminders': getattr(user, 'match_reminders', True),
                'rsvp_reminders': getattr(user, 'rsvp_reminders', True),
                'general_notifications': getattr(user, 'general_notifications', True)
            }), 200
        
        elif request.method == 'PUT':
            data = request.get_json()
            
            # Update notification settings (you might need to add these columns to User model)
            if 'push_notifications' in data:
                setattr(user, 'push_notifications', data['push_notifications'])
            if 'match_reminders' in data:
                setattr(user, 'match_reminders', data['match_reminders'])
            if 'rsvp_reminders' in data:
                setattr(user, 'rsvp_reminders', data['rsvp_reminders'])
            if 'general_notifications' in data:
                setattr(user, 'general_notifications', data['general_notifications'])
            
            db.session.commit()
            
            return jsonify({'msg': 'Notification settings updated successfully'}), 200
        
    except Exception as e:
        logger.error(f"Error handling notification settings: {e}")
        return jsonify({'msg': 'Internal server error'}), 500

@notifications_bp.route('/status')
@jwt_required()
def notification_status():
    """Get notification system status (used by admin dashboard)"""
    try:
        # Check if Firebase is configured
        firebase_configured = notification_service._initialized
        
        # Get FCM token statistics
        total_tokens = UserFCMToken.query.filter_by(is_active=True).count()
        ios_tokens = UserFCMToken.query.filter_by(is_active=True, platform='ios').count()
        android_tokens = UserFCMToken.query.filter_by(is_active=True, platform='android').count()
        
        # TODO: Add actual notification count from logs/database
        notifications_sent_24h = 0
        
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

@notifications_bp.route('/recent-activity')
@jwt_required()
def recent_activity():
    """Get recent notification activity (used by admin dashboard)"""
    try:
        # TODO: Implement actual notification logging and retrieval
        # For now, return empty data
        return jsonify({
            'activities': []
        })
        
    except Exception as e:
        logger.error(f"Error getting recent activity: {e}")
        return jsonify({
            'activities': []
        }), 500