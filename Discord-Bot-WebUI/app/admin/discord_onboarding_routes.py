"""
Discord Onboarding Routes

API endpoints for Discord bot to communicate with Flask app regarding user onboarding.
Handles user join detection, league selection, and new player notifications.
"""

import logging
import requests
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from flask import Blueprint, request, jsonify, g, render_template, redirect, url_for
from sqlalchemy import and_, or_
from sqlalchemy.exc import SQLAlchemyError

from app.models import User, Player, db
from app.utils.db_utils import transactional
from app.decorators import role_required
from app.utils.user_helpers import safe_current_user
from app import csrf

logger = logging.getLogger(__name__)

# Create blueprint for Discord onboarding routes
discord_onboarding = Blueprint('discord_onboarding', __name__, url_prefix='/api/discord')


# =======================================================================
# Helper Functions
# =======================================================================

def log_discord_interaction(user_id: int, discord_id: str, interaction_type: str, 
                           message_content: str = None, success: bool = True, 
                           error_message: str = None, metadata: Dict = None):
    """Log Discord interaction to database."""
    try:
        from app.models import db
        
        # Use raw SQL to call the helper function we created
        db.session.execute(
            "SELECT log_discord_interaction(%s, %s, %s, %s, %s, %s, %s, %s)",
            (user_id, discord_id, interaction_type, message_content, None, 
             success, error_message, metadata)
        )
        db.session.commit()
        logger.info(f"Logged Discord interaction: {interaction_type} for user {user_id}")
    except Exception as e:
        logger.error(f"Failed to log Discord interaction: {e}")
        db.session.rollback()


def update_user_league_preference(user_id: int, league: str, method: str = 'bot_interaction') -> bool:
    """Update user's league preference using the database function."""
    try:
        result = db.session.execute(
            "SELECT update_user_league_preference(%s, %s, %s)",
            (user_id, league, method)
        ).fetchone()
        db.session.commit()
        return result[0] if result else False
    except Exception as e:
        logger.error(f"Failed to update user league preference: {e}")
        db.session.rollback()
        return False


# =======================================================================
# API Endpoints
# =======================================================================

@discord_onboarding.route('/user-joined/<discord_id>', methods=['POST'])
@csrf.exempt
@transactional
def user_joined_discord(discord_id: str):
    """
    Called by Discord bot when a user joins the server.
    Updates the user's discord_join_detected_at timestamp and returns onboarding status.
    """
    try:
        # Find user by Discord ID using the session from g
        player = g.db_session.query(Player).filter_by(discord_id=discord_id).first()
        if not player or not player.user:
            logger.warning(f"No user found for Discord ID: {discord_id}")
            return jsonify({
                'exists': False,
                'message': 'User not found in database'
            }), 404

        # Get fresh user instance from current session
        user = g.db_session.query(User).filter_by(id=player.user_id).first()
        if not user:
            logger.warning(f"User not found for player with Discord ID: {discord_id}")
            return jsonify({
                'exists': False,
                'message': 'User not found in database'
            }), 404
        
        # Update discord join detection timestamp
        user.discord_join_detected_at = datetime.utcnow()
        g.db_session.add(user)
        
        # Log the join detection
        log_discord_interaction(
            user.id, discord_id, 'join_detected',
            success=True, metadata={'username': user.username}
        )
        
        # Determine onboarding status
        needs_onboarding = not user.has_completed_onboarding
        needs_league_selection = user.preferred_league is None
        
        response_data = {
            'exists': True,
            'user_id': user.id,
            'username': user.username,
            'has_completed_onboarding': user.has_completed_onboarding,
            'preferred_league': user.preferred_league,
            'needs_onboarding': needs_onboarding,
            'needs_league_selection': needs_league_selection,
            'bot_interaction_status': user.bot_interaction_status,
            'should_contact': needs_onboarding or needs_league_selection,
            'discord_join_detected_at': user.discord_join_detected_at.isoformat()
        }
        
        logger.info(f"User join detected for {user.username} (Discord ID: {discord_id})")
        return jsonify(response_data), 200
        
    except Exception as e:
        logger.error(f"Error processing user join for Discord ID {discord_id}: {e}")
        return jsonify({
            'exists': False,
            'error': 'Internal server error'
        }), 500


@discord_onboarding.route('/onboarding-status/<discord_id>', methods=['GET'])
@csrf.exempt
@transactional
def get_onboarding_status(discord_id: str):
    """
    Get detailed onboarding status for a Discord user.
    Used by bot to determine appropriate messaging.
    """
    try:
        player = Player.query.filter_by(discord_id=discord_id).first()
        if not player or not player.user:
            return jsonify({
                'exists': False,
                'message': 'User not found'
            }), 404

        user = player.user
        
        # Calculate time since registration
        time_since_registration = datetime.utcnow() - user.created_at
        
        # Determine recommended action
        if user.has_completed_onboarding and user.preferred_league:
            recommended_action = 'send_welcome'
        elif user.has_completed_onboarding and not user.preferred_league:
            recommended_action = 'ask_league_only'
        elif not user.has_completed_onboarding and user.preferred_league:
            recommended_action = 'encourage_onboarding'
        else:
            recommended_action = 'ask_league_and_onboarding'
        
        response_data = {
            'exists': True,
            'user_id': user.id,
            'player_id': player.id,
            'username': user.username,
            'email': user.email,
            'has_completed_onboarding': user.has_completed_onboarding,
            'preferred_league': user.preferred_league,
            'league_selection_method': user.league_selection_method,
            'bot_interaction_status': user.bot_interaction_status,
            'bot_interaction_attempts': user.bot_interaction_attempts,
            'last_bot_contact_at': user.last_bot_contact_at.isoformat() if user.last_bot_contact_at else None,
            'discord_join_detected_at': user.discord_join_detected_at.isoformat() if user.discord_join_detected_at else None,
            'time_since_registration_hours': int(time_since_registration.total_seconds() / 3600),
            'recommended_action': recommended_action,
            'approval_status': user.approval_status,
            'is_approved': user.is_approved
        }
        
        return jsonify(response_data), 200
        
    except Exception as e:
        logger.error(f"Error getting onboarding status for Discord ID {discord_id}: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@discord_onboarding.route('/league-selection', methods=['POST'])
@csrf.exempt
@transactional
def receive_league_selection():
    """
    Receive league selection from Discord bot.
    Updates user's preferred league and interaction status.
    """
    try:
        data = request.get_json()
        discord_id = data.get('discord_id')
        league_selection = data.get('league_selection')  # 'pub_league_classic', 'pub_league_premier', 'ecs_fc'
        raw_message = data.get('raw_message', '')
        
        if not discord_id or not league_selection:
            return jsonify({'error': 'Missing required fields'}), 400
        
        # Validate league selection
        valid_leagues = ['pub_league_classic', 'pub_league_premier', 'ecs_fc']
        if league_selection not in valid_leagues:
            return jsonify({'error': 'Invalid league selection'}), 400
        
        # Find user
        player = Player.query.filter_by(discord_id=discord_id).first()
        if not player or not player.user:
            return jsonify({'error': 'User not found'}), 404
        
        user = player.user
        
        # Update user's league preference
        success = update_user_league_preference(user.id, league_selection, 'bot_interaction')
        if not success:
            return jsonify({'error': 'Failed to update league preference'}), 500
        
        # Update bot interaction status
        user.bot_interaction_status = 'completed'
        user.bot_response_received_at = datetime.utcnow()
        g.db_session.add(user)
        
        # Log the interaction
        log_discord_interaction(
            user.id, discord_id, 'league_selected',
            message_content=raw_message, success=True,
            metadata={
                'league_selected': league_selection,
                'method': 'bot_interaction'
            }
        )
        
        # Check if we should trigger new player notification
        should_notify = not user.is_approved and user.approval_status == 'pending'
        
        response_data = {
            'success': True,
            'user_id': user.id,
            'league_selected': league_selection,
            'should_trigger_notification': should_notify,
            'message': f'League preference updated to {league_selection}'
        }
        
        logger.info(f"League selection received for {user.username}: {league_selection}")
        return jsonify(response_data), 200
        
    except Exception as e:
        logger.error(f"Error processing league selection: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@discord_onboarding.route('/update-interaction-status', methods=['POST'])
@csrf.exempt
@transactional
def update_interaction_status():
    """
    Update bot interaction status (e.g., when DM is sent, failed, etc.)
    """
    try:
        data = request.get_json()
        discord_id = data.get('discord_id')
        status = data.get('status')  # 'contacted', 'failed', etc.
        error_message = data.get('error_message')
        bot_message_id = data.get('bot_message_id')
        
        if not discord_id or not status:
            return jsonify({'error': 'Missing required fields'}), 400
        
        player = Player.query.filter_by(discord_id=discord_id).first()
        if not player or not player.user:
            return jsonify({'error': 'User not found'}), 404
        
        user = player.user
        
        # Update interaction status
        user.bot_interaction_status = status
        user.last_bot_contact_at = datetime.utcnow()
        if status == 'contacted':
            user.bot_interaction_attempts = (user.bot_interaction_attempts or 0) + 1
        
        g.db_session.add(user)
        
        # Log the interaction
        log_discord_interaction(
            user.id, discord_id, f'status_update_{status}',
            success=(status != 'failed'), error_message=error_message,
            metadata={'bot_message_id': bot_message_id}
        )
        
        logger.info(f"Updated interaction status for {user.username}: {status}")
        return jsonify({'success': True}), 200
        
    except Exception as e:
        logger.error(f"Error updating interaction status: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@discord_onboarding.route('/new-player-notification', methods=['POST'])
@csrf.exempt
@transactional
def create_new_player_notification():
    """
    Create/update new player notification record for #pl-new-players channel.
    """
    try:
        data = request.get_json()
        discord_id = data.get('discord_id')
        discord_username = data.get('discord_username')
        discord_display_name = data.get('discord_display_name')
        notification_sent = data.get('notification_sent', False)
        discord_message_id = data.get('discord_message_id')
        error_message = data.get('error_message')
        
        if not discord_id:
            return jsonify({'error': 'Discord ID required'}), 400
        
        player = Player.query.filter_by(discord_id=discord_id).first()
        if not player or not player.user:
            return jsonify({'error': 'User not found'}), 404
        
        user = player.user
        
        # Insert new player notification record using raw SQL
        try:
            from sqlalchemy import text
            db.session.execute(text("""
                INSERT INTO new_player_notifications 
                (user_id, discord_id, discord_username, discord_display_name, 
                 preferred_league, notification_sent, notification_sent_at, 
                 discord_message_id, error_message)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    discord_username = EXCLUDED.discord_username,
                    discord_display_name = EXCLUDED.discord_display_name,
                    notification_sent = EXCLUDED.notification_sent,
                    notification_sent_at = EXCLUDED.notification_sent_at,
                    discord_message_id = EXCLUDED.discord_message_id,
                    error_message = EXCLUDED.error_message,
                    updated_at = NOW()
            """), (
                user.id, discord_id, discord_username, discord_display_name,
                user.preferred_league, notification_sent,
                datetime.utcnow() if notification_sent else None,
                discord_message_id, error_message
            ))
            db.session.commit()
        except Exception as db_error:
            logger.error(f"Database error creating notification record: {db_error}")
            return jsonify({'error': 'Database error'}), 500
        
        # Log the notification attempt
        log_discord_interaction(
            user.id, discord_id, 'new_player_notification',
            success=notification_sent, error_message=error_message,
            metadata={
                'discord_username': discord_username,
                'discord_message_id': discord_message_id
            }
        )
        
        response_data = {
            'success': True,
            'user_id': user.id,
            'notification_created': True
        }
        
        logger.info(f"New player notification record created for {user.username}")
        return jsonify(response_data), 200
        
    except Exception as e:
        logger.error(f"Error creating new player notification: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@discord_onboarding.route('/pending-contacts', methods=['GET'])
@transactional
def get_pending_contacts():
    """
    Get list of users who need to be contacted by the bot.
    Used for batch processing and retry mechanisms.
    """
    try:
        # Get users who need bot contact
        query = db.session.query(User, Player).join(Player).filter(
            and_(
                User.is_approved == False,
                User.approval_status == 'pending',
                or_(
                    User.has_completed_onboarding == False,
                    User.preferred_league.is_(None)
                ),
                User.bot_interaction_status.in_(['not_contacted', 'failed']),
                User.discord_join_detected_at.isnot(None),
                # Don't retry too frequently
                or_(
                    User.last_bot_contact_at.is_(None),
                    User.last_bot_contact_at < datetime.utcnow() - timedelta(hours=1)
                )
            )
        )
        
        users_to_contact = []
        for user, player in query.all():
            time_since_join = None
            if user.discord_join_detected_at:
                time_since_join = int((datetime.utcnow() - user.discord_join_detected_at).total_seconds() / 60)
            
            users_to_contact.append({
                'user_id': user.id,
                'discord_id': player.discord_id,
                'username': user.username,
                'has_completed_onboarding': user.has_completed_onboarding,
                'preferred_league': user.preferred_league,
                'bot_interaction_attempts': user.bot_interaction_attempts or 0,
                'time_since_join_minutes': time_since_join,
                'priority': 'high' if time_since_join and time_since_join > 30 else 'normal'
            })
        
        return jsonify({
            'users_to_contact': users_to_contact,
            'total_count': len(users_to_contact)
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting pending contacts: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# =======================================================================
# Admin Endpoints (require admin role)
# =======================================================================

@discord_onboarding.route('/admin/onboarding-overview', methods=['GET'])
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def admin_onboarding_overview():
    """
    Admin endpoint to get overview of onboarding status.
    """
    try:
        # Use the view we created in the database
        from sqlalchemy import text
        result = db.session.execute(text("SELECT * FROM onboarding_status_overview ORDER BY id DESC LIMIT 50"))
        
        overview_data = []
        for row in result:
            overview_data.append({
                'id': row.id,
                'username': row.username,
                'email': row.email,
                'has_completed_onboarding': row.has_completed_onboarding,
                'preferred_league': row.preferred_league,
                'league_selection_method': row.league_selection_method,
                'bot_interaction_status': row.bot_interaction_status,
                'bot_interaction_attempts': row.bot_interaction_attempts,
                'last_bot_contact_at': row.last_bot_contact_at.isoformat() if row.last_bot_contact_at else None,
                'discord_join_detected_at': row.discord_join_detected_at.isoformat() if row.discord_join_detected_at else None,
                'discord_id': row.discord_id,
                'player_name': row.player_name,
                'overall_status': row.overall_status
            })
        
        return jsonify({
            'overview': overview_data,
            'total_count': len(overview_data)
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting admin onboarding overview: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@discord_onboarding.route('/admin/retry-contact/<int:user_id>', methods=['POST'])
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def admin_retry_contact(user_id: int):
    """
    Admin endpoint to manually trigger bot contact retry.
    """
    try:
        user = User.query.get(user_id)
        if not user or not user.player:
            return jsonify({'error': 'User not found'}), 404
        
        # Reset bot interaction status to allow retry
        user.bot_interaction_status = 'not_contacted'
        user.last_bot_contact_at = None
        g.db_session.add(user)
        
        # Log the manual retry
        log_discord_interaction(
            user.id, user.player.discord_id, 'admin_retry_requested',
            success=True, metadata={'admin_user': safe_current_user.username}
        )
        
        return jsonify({
            'success': True,
            'message': f'Contact retry enabled for {user.username}'
        }), 200
        
    except Exception as e:
        logger.error(f"Error enabling contact retry: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@discord_onboarding.route('/admin/test-onboarding', methods=['GET', 'POST'])
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def admin_test_onboarding():
    """
    Admin interface to test the onboarding flow step by step.
    """
    # Get current user's Discord ID safely
    current_user = safe_current_user
    user_discord_id = None
    if current_user and current_user.player:
        # Query the player to get fresh data from the session
        player = g.db_session.query(Player).filter_by(user_id=current_user.id).first()
        if player:
            user_discord_id = player.discord_id
    
    if request.method == 'POST':
        action = request.form.get('action')
        discord_id = request.form.get('discord_id', str(user_discord_id) if user_discord_id else '')
        
        results = []
        
        if action == 'test_user_join':
            # Simulate user joining Discord
            try:
                response = requests.post(f"http://webui:5000/api/discord/user-joined/{discord_id}", timeout=10)
                results.append(f"User join notification: {response.status_code} - {response.text}")
            except Exception as e:
                results.append(f"Error: {e}")
                
        elif action == 'test_contextual_welcome':
            # Test contextual welcome message
            try:
                response = requests.post(
                    "http://discord-bot:5001/onboarding/send-contextual-welcome",
                    json={"discord_id": discord_id},
                    timeout=30
                )
                results.append(f"Contextual welcome: {response.status_code} - {response.text}")
            except Exception as e:
                results.append(f"Error: {e}")
                
        elif action == 'test_league_selection':
            # Test league selection processing
            message = request.form.get('test_message', 'I think premier')
            try:
                response = requests.post(
                    "http://discord-bot:5001/onboarding/process-user-message",
                    json={
                        "discord_id": discord_id,
                        "message_content": message
                    },
                    timeout=30
                )
                results.append(f"League selection processing: {response.status_code} - {response.text}")
            except Exception as e:
                results.append(f"Error: {e}")
                
        elif action == 'test_new_player_notification':
            # Test new player notification
            try:
                response = requests.post(
                    "http://discord-bot:5001/onboarding/notify-new-player",
                    json={
                        "discord_id": discord_id,
                        "discord_username": "test_user",
                        "discord_display_name": "Test User"
                    },
                    timeout=30
                )
                results.append(f"New player notification: {response.status_code} - {response.text}")
            except Exception as e:
                results.append(f"Error: {e}")
                
        elif action == 'reset_user_state':
            # Reset user for fresh testing
            try:
                user = User.query.join(Player).filter(Player.discord_id == discord_id).first()
                if user:
                    user.has_completed_onboarding = False
                    user.preferred_league = None
                    user.league_selection_method = None
                    user.bot_interaction_status = 'not_contacted'
                    user.bot_interaction_attempts = 0
                    user.last_bot_contact_at = None
                    user.discord_join_detected_at = None
                    g.db_session.add(user)
                    g.db_session.commit()
                    results.append(f"Reset user state for Discord ID: {discord_id}")
                else:
                    results.append(f"User not found for Discord ID: {discord_id}")
            except Exception as e:
                results.append(f"Error: {e}")
                
        elif action == 'apply_scenario_flags':
            # Apply scenario flags to modify user state
            try:
                scenario_flags = request.form.getlist('scenario_flags')
                user = User.query.join(Player).filter(Player.discord_id == discord_id).first()
                if user:
                    # Apply flags
                    if 'no_onboarding' in scenario_flags:
                        user.has_completed_onboarding = False
                        results.append("✓ Set onboarding as incomplete")
                    
                    if 'no_league' in scenario_flags:
                        user.preferred_league = None
                        user.league_selection_method = None
                        results.append("✓ Cleared league selection")
                    
                    if 'different_league' in scenario_flags:
                        user.preferred_league = 'pub_league_classic'
                        user.league_selection_method = 'admin_assignment'
                        results.append("✓ Set league to Classic")
                    
                    if 'unapproved' in scenario_flags:
                        user.is_approved = False
                        user.approval_status = 'pending'
                        results.append("✓ Set user as unapproved")
                    
                    g.db_session.add(user)
                    g.db_session.commit()
                    results.append(f"Applied {len(scenario_flags)} scenario flags")
                else:
                    results.append(f"User not found for Discord ID: {discord_id}")
            except Exception as e:
                results.append(f"Error: {e}")
                
        elif action == 'show_current_state':
            # Show current user state
            try:
                user = User.query.join(Player).filter(Player.discord_id == discord_id).first()
                if user:
                    results.append("=== CURRENT USER STATE ===")
                    results.append(f"Username: {user.username}")
                    results.append(f"Has completed onboarding: {user.has_completed_onboarding}")
                    results.append(f"Preferred league: {user.preferred_league or 'None'}")
                    results.append(f"League selection method: {user.league_selection_method or 'None'}")
                    results.append(f"Bot interaction status: {user.bot_interaction_status}")
                    results.append(f"Bot interaction attempts: {user.bot_interaction_attempts}")
                    results.append(f"Is approved: {user.is_approved}")
                    results.append(f"Approval status: {user.approval_status}")
                    results.append(f"Discord join detected: {user.discord_join_detected_at or 'None'}")
                    results.append(f"Last bot contact: {user.last_bot_contact_at or 'None'}")
                else:
                    results.append(f"User not found for Discord ID: {discord_id}")
            except Exception as e:
                results.append(f"Error: {e}")
                
        elif action == 'manage_messages':
            # Redirect to message management
            return redirect(url_for('admin.message_config.list_categories'))
        
        # Quick league selection tests
        elif action in ['test_league_classic', 'test_league_premier', 'test_league_ecs_fc', 'test_league_unclear']:
            test_messages = {
                'test_league_classic': 'I want to join classic division',
                'test_league_premier': 'Put me in premier please',
                'test_league_ecs_fc': 'I want ECS FC',
                'test_league_unclear': 'I dont know maybe something good'
            }
            message = test_messages[action]
            try:
                response = requests.post(
                    "http://discord-bot:5001/onboarding/process-user-message",
                    json={
                        "discord_id": discord_id,
                        "message_content": message
                    },
                    timeout=30
                )
                results.append(f"League test '{message}': {response.status_code} - {response.text}")
            except Exception as e:
                results.append(f"Error: {e}")
        
        return render_template('admin/test_onboarding.html', results=results, user_discord_id=user_discord_id)
    
    return render_template('admin/test_onboarding.html', user_discord_id=user_discord_id)


@discord_onboarding.route('/message-template/<category>/<key>', methods=['GET'])
@csrf.exempt
@transactional
def get_message_template_by_key(category: str, key: str):
    """
    API endpoint to get a message template by category and key.
    Used by Discord bot to fetch configurable messages.
    """
    try:
        from app.models import MessageTemplate, MessageCategory
        
        template = MessageTemplate.query.join(MessageCategory).filter(
            MessageCategory.name == category,
            MessageTemplate.key == key,
            MessageTemplate.is_active == True
        ).first()
        
        if not template:
            return jsonify({'error': 'Template not found'}), 404
        
        return jsonify({
            'id': template.id,
            'key': template.key,
            'name': template.name,
            'message_content': template.message_content,
            'variables': template.variables,
            'category': category
        }), 200
        
    except Exception as e:
        logger.error(f"Error fetching message template {category}/{key}: {e}")
        return jsonify({'error': 'Internal server error'}), 500