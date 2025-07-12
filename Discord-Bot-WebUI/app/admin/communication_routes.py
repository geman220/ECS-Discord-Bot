# app/admin/communication_routes.py

"""
Communication Routes

This module contains routes for SMS messaging, Discord DMs,
and communication status monitoring.
"""

import time
import logging
import requests
from datetime import datetime
from flask import Blueprint, request, jsonify, redirect, url_for, g, current_app
from flask_login import login_required

from app.decorators import role_required
from app.alert_helpers import show_error, show_success
from app.admin_helpers import send_sms_message
from app.models import Player, User
from app.utils.user_helpers import safe_current_user

logger = logging.getLogger(__name__)

# Import the shared admin blueprint
from app.admin.blueprint import admin_bp


# -----------------------------------------------------------
# SMS Messaging
# -----------------------------------------------------------

@admin_bp.route('/admin/send_sms', endpoint='send_sms', methods=['POST'])
@login_required
@role_required('Global Admin')
def send_sms():
    """
    Send an SMS message using provided phone number and message body.
    """
    to_phone = request.form.get('to_phone_number')
    message = request.form.get('message_body')

    if not to_phone or not message:
        show_error("Phone number and message body are required.")
        return redirect(url_for('admin.admin_dashboard'))

    success = send_sms_message(to_phone, message)
    if not success:
        show_error("Failed to send SMS.")
    return redirect(url_for('admin.admin_dashboard'))


@admin_bp.route('/admin/send_custom_sms', methods=['POST'], endpoint='send_custom_sms')
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'Pub League Coach'])
def send_custom_sms():
    """
    Send a custom SMS message to a player.
    
    Expects:
    - player_id: ID of the player to message
    - phone: Phone number to send to
    - message: The message content
    - match_id: Optional - ID of the match for context
    """
    session = g.db_session
    player_id = request.form.get('player_id')
    phone = request.form.get('phone')
    message = request.form.get('message')
    match_id = request.form.get('match_id')
    
    if not player_id or not phone or not message:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Missing required fields'}), 400
        show_error('Phone number and message are required.')
        if match_id:
            return redirect(url_for('admin.rsvp_status', match_id=match_id))
        return redirect(url_for('admin.admin_dashboard'))
    
    player = session.query(Player).get(player_id)
    if not player:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Player not found'}), 404
        show_error('Player not found.')
        if match_id:
            return redirect(url_for('admin.rsvp_status', match_id=match_id))
        return redirect(url_for('admin.admin_dashboard'))
    
    # Check if user has SMS notifications enabled
    user = player.user
    if not user or not user.sms_notifications:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'SMS notifications are disabled for this user'}), 403
        show_error('SMS notifications are disabled for this user.')
        if match_id:
            return redirect(url_for('admin.rsvp_status', match_id=match_id))
        return redirect(url_for('admin.admin_dashboard'))
    
    # Extract user_id before committing session
    user_id = user.id
    
    # Commit the session before making the external SMS API call to avoid
    # holding the database transaction open during the external call
    session.commit()
    
    # Send the SMS
    from app.sms_helpers import send_sms
    success, result = send_sms(phone, message, user_id=user_id)
    
    if success:
        # Log the SMS
        logger.info(f"Admin {safe_current_user.id} sent SMS to player {player_id}")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'message': 'SMS sent successfully'})
        show_success('SMS sent successfully.')
    else:
        logger.error(f"Failed to send SMS to player {player_id}: {result}")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': f'Failed to send SMS: {result}'})
        show_error(f'Failed to send SMS: {result}')
    
    if match_id:
        return redirect(url_for('admin.rsvp_status', match_id=match_id))
    return redirect(url_for('admin.admin_dashboard'))


@admin_bp.route('/admin/send_discord_dm', methods=['POST'], endpoint='send_discord_dm')
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'Pub League Coach'])
def send_discord_dm():
    """
    Send a Discord DM to a player using the bot.
    
    Expects:
    - player_id: ID of the player to message
    - message: The message content
    - match_id: Optional - ID of the match for context
    """
    session = g.db_session
    player_id = request.form.get('player_id')
    message = request.form.get('message')
    match_id = request.form.get('match_id')
    
    if not player_id or not message:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Missing required fields'}), 400
        show_error('Player ID and message are required.')
        if match_id:
            return redirect(url_for('admin.rsvp_status', match_id=match_id))
        return redirect(url_for('admin.admin_dashboard'))
    
    player = session.query(Player).get(player_id)
    if not player or not player.discord_id:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Player not found or no Discord ID'}), 404
        show_error('Player not found or has no Discord ID.')
        if match_id:
            return redirect(url_for('admin.rsvp_status', match_id=match_id))
        return redirect(url_for('admin.admin_dashboard'))
    
    # Check if user has Discord notifications enabled
    user = player.user
    if not user or not user.discord_notifications:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Discord notifications are disabled for this user'}), 403
        show_error('Discord notifications are disabled for this user.')
        if match_id:
            return redirect(url_for('admin.rsvp_status', match_id=match_id))
        return redirect(url_for('admin.admin_dashboard'))
    
    # Extract discord_id before committing session
    discord_id = player.discord_id
    
    # Commit the session before making the external API call to avoid
    # holding the database transaction open during the 10-second timeout
    session.commit()
    
    # Send the Discord DM using the bot API
    payload = {
        "message": message,
        "discord_id": discord_id
    }
    
    bot_api_url = current_app.config.get('BOT_API_URL', 'http://localhost:5001') + '/send_discord_dm'
    
    try:
        response = requests.post(bot_api_url, json=payload, timeout=10)
        if response.status_code == 200:
            logger.info(f"Admin {safe_current_user.id} sent Discord DM to player {player_id}")
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': True, 'message': 'Discord DM sent successfully'})
            show_success('Discord DM sent successfully.')
        else:
            logger.error(f"Failed to send Discord DM to player {player_id}: {response.text}")
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': 'Failed to send Discord DM'})
            show_error('Failed to send Discord DM.')
    except Exception as e:
        logger.error(f"Error contacting Discord bot: {str(e)}")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': f'Error contacting Discord bot: {str(e)}'})
        show_error(f'Error contacting Discord bot: {str(e)}')
    
    if match_id:
        return redirect(url_for('admin.rsvp_status', match_id=match_id))
    return redirect(url_for('admin.admin_dashboard'))


@admin_bp.route('/admin/sms_status', methods=['GET'])
@login_required
@role_required('Global Admin')
def sms_rate_limit_status():
    """
    Check SMS usage and rate limiting status.
    
    This endpoint provides information about:
    - System-wide SMS usage
    - Per-user SMS usage
    - Rate limit configuration
    """
    from app.sms_helpers import sms_user_cache, sms_system_counter, SMS_RATE_LIMIT_PER_USER, SMS_SYSTEM_RATE_LIMIT, SMS_RATE_LIMIT_WINDOW
    
    current_time = time.time()
    cutoff_time = current_time - SMS_RATE_LIMIT_WINDOW
    
    # Clean up expired timestamps
    cleaned_system_counter = [t for t in sms_system_counter if t > cutoff_time]
    
    # Prepare per-user data
    user_data = {}
    for user_id, timestamps in sms_user_cache.items():
        valid_timestamps = [t for t in timestamps if t > cutoff_time]
        if valid_timestamps:
            # Get user information if available
            session = g.db_session
            user = session.query(User).get(user_id)
            username = user.username if user else "Unknown"
            
            user_data[user_id] = {
                'username': username,
                'count': len(valid_timestamps),
                'remaining': SMS_RATE_LIMIT_PER_USER - len(valid_timestamps),
                'last_send': datetime.fromtimestamp(max(valid_timestamps)).strftime('%Y-%m-%d %H:%M:%S'),
                'reset': datetime.fromtimestamp(min(valid_timestamps) + SMS_RATE_LIMIT_WINDOW).strftime('%Y-%m-%d %H:%M:%S')
            }
    
    # Calculate system-wide reset time if any messages have been sent
    system_reset = None
    if cleaned_system_counter:
        system_reset = datetime.fromtimestamp(min(cleaned_system_counter) + SMS_RATE_LIMIT_WINDOW).strftime('%Y-%m-%d %H:%M:%S')
    
    return jsonify({
        'system': {
            'total_count': len(cleaned_system_counter),
            'limit': SMS_SYSTEM_RATE_LIMIT,
            'remaining': SMS_SYSTEM_RATE_LIMIT - len(cleaned_system_counter),
            'window_seconds': SMS_RATE_LIMIT_WINDOW,
            'window_hours': SMS_RATE_LIMIT_WINDOW / 3600,
            'reset_time': system_reset
        },
        'users': user_data,
        'config': {
            'per_user_limit': SMS_RATE_LIMIT_PER_USER,
            'system_limit': SMS_SYSTEM_RATE_LIMIT,
            'window_seconds': SMS_RATE_LIMIT_WINDOW
        }
    })