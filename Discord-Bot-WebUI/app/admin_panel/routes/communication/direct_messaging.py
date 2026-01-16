# app/admin_panel/routes/communication/direct_messaging.py

"""
Direct Messaging Routes

Routes for SMS and Discord DM messaging.
"""

import logging
from datetime import datetime

from flask import render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user

from app.admin_panel import admin_panel_bp
from app.core import db
from app.models.admin_config import AdminAuditLog
from app.models.core import User
from app.decorators import role_required

logger = logging.getLogger(__name__)


@admin_panel_bp.route('/communication/direct-messaging')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def direct_messaging():
    """Direct messaging dashboard for SMS and Discord DMs."""
    try:
        from app.models import Player

        # Get statistics
        stats = {
            'total_players': Player.query.count(),
            'players_with_phone': Player.query.filter(Player.phone != None, Player.phone != '').count(),
            'players_with_discord': Player.query.filter(Player.discord_id != None).count(),
            'sms_enabled_users': User.query.filter_by(sms_notifications=True).count(),
            'discord_enabled_users': User.query.filter_by(discord_notifications=True).count()
        }

        # Get recent players for quick messaging
        recent_players = Player.query.order_by(Player.id.desc()).limit(20).all()

        return render_template(
            'admin_panel/communication/direct_messaging_flowbite.html',
            stats=stats,
            recent_players=recent_players
        )
    except Exception as e:
        logger.error(f"Error loading direct messaging: {e}")
        flash('Direct messaging unavailable. Check database connectivity.', 'error')
        return redirect(url_for('admin_panel.communication_hub'))


@admin_panel_bp.route('/communication/send-sms', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'Pub League Coach'])
def send_sms():
    """Send an SMS message to a player."""
    try:
        from flask import g
        from app.models import Player
        from app.sms_helpers import send_sms as sms_send

        player_id = request.form.get('player_id')
        phone = request.form.get('phone')
        message = request.form.get('message')

        if not player_id or not phone or not message:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': 'Missing required fields'}), 400
            flash('Phone number and message are required.', 'error')
            return redirect(url_for('admin_panel.direct_messaging'))

        # Get player
        player = Player.query.get(player_id)
        if not player:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': 'Player not found'}), 404
            flash('Player not found.', 'error')
            return redirect(url_for('admin_panel.direct_messaging'))

        # Check SMS notifications enabled
        user = player.user
        if not user or not user.sms_notifications:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': 'SMS notifications are disabled for this user'}), 403
            flash('SMS notifications are disabled for this user.', 'error')
            return redirect(url_for('admin_panel.direct_messaging'))

        # CRITICAL: Check if phone is verified (legal compliance requirement)
        if not player.is_phone_verified:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': 'Phone not verified - cannot send SMS (legal compliance)'}), 403
            flash('Phone not verified - cannot send SMS for legal compliance reasons.', 'error')
            return redirect(url_for('admin_panel.direct_messaging'))

        # Check SMS consent was given
        if not player.sms_consent_given:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': 'User has not given SMS consent'}), 403
            flash('User has not given SMS consent.', 'error')
            return redirect(url_for('admin_panel.direct_messaging'))

        user_id = user.id

        # Send the SMS with audit logging parameters
        success, result = sms_send(
            phone, message, user_id=user_id,
            message_type='admin_direct',
            source='admin_panel',
            sent_by_user_id=current_user.id
        )

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='send_sms',
            resource_type='direct_messaging',
            resource_id=str(player_id),
            new_value=f'SMS sent to player {player.name}: {message[:50]}...',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        if success:
            logger.info(f"Admin {current_user.id} sent SMS to player {player_id}")
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': True, 'message': 'SMS sent successfully'})
            flash('SMS sent successfully.', 'success')
        else:
            logger.error(f"Failed to send SMS to player {player_id}: {result}")
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': f'Failed to send SMS: {result}'})
            flash(f'Failed to send SMS: {result}', 'error')

        return redirect(url_for('admin_panel.direct_messaging'))

    except Exception as e:
        logger.error(f"Error sending SMS: {e}")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': str(e)}), 500
        flash('Failed to send SMS.', 'error')
        return redirect(url_for('admin_panel.direct_messaging'))


@admin_panel_bp.route('/communication/send-discord-dm', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'Pub League Coach'])
def send_discord_dm():
    """Send a Discord DM to a player."""
    try:
        import requests as http_requests
        from flask import current_app
        from app.models import Player

        player_id = request.form.get('player_id')
        message = request.form.get('message')

        if not player_id or not message:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': 'Missing required fields'}), 400
            flash('Player ID and message are required.', 'error')
            return redirect(url_for('admin_panel.direct_messaging'))

        # Get player
        player = Player.query.get(player_id)
        if not player or not player.discord_id:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': 'Player not found or no Discord ID'}), 404
            flash('Player not found or has no Discord ID.', 'error')
            return redirect(url_for('admin_panel.direct_messaging'))

        # Check Discord notifications enabled
        user = player.user
        if not user or not user.discord_notifications:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': 'Discord notifications are disabled for this user'}), 403
            flash('Discord notifications are disabled for this user.', 'error')
            return redirect(url_for('admin_panel.direct_messaging'))

        discord_id = player.discord_id

        # Send the Discord DM using the bot API
        payload = {
            "message": message,
            "discord_id": discord_id
        }

        bot_api_url = current_app.config.get('BOT_API_URL', 'http://localhost:5001') + '/send_discord_dm'

        try:
            response = http_requests.post(bot_api_url, json=payload, timeout=10)

            # Log the action
            AdminAuditLog.log_action(
                user_id=current_user.id,
                action='send_discord_dm',
                resource_type='direct_messaging',
                resource_id=str(player_id),
                new_value=f'Discord DM sent to player {player.name}: {message[:50]}...',
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )

            if response.status_code == 200:
                logger.info(f"Admin {current_user.id} sent Discord DM to player {player_id}")
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'success': True, 'message': 'Discord DM sent successfully'})
                flash('Discord DM sent successfully.', 'success')
            else:
                logger.error(f"Failed to send Discord DM to player {player_id}: {response.text}")
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'success': False, 'message': 'Failed to send Discord DM'})
                flash('Failed to send Discord DM.', 'error')

        except http_requests.exceptions.RequestException as e:
            logger.error(f"Error contacting Discord bot: {str(e)}")
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': f'Error contacting Discord bot: {str(e)}'})
            flash(f'Error contacting Discord bot: {str(e)}', 'error')

        return redirect(url_for('admin_panel.direct_messaging'))

    except Exception as e:
        logger.error(f"Error sending Discord DM: {e}")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': str(e)}), 500
        flash('Failed to send Discord DM.', 'error')
        return redirect(url_for('admin_panel.direct_messaging'))


@admin_panel_bp.route('/communication/sms-status')
@login_required
@role_required(['Global Admin'])
def sms_status():
    """Check SMS usage and rate limiting status."""
    try:
        import time
        from app.sms_helpers import (
            sms_user_cache, sms_system_counter,
            SMS_RATE_LIMIT_PER_USER, SMS_SYSTEM_RATE_LIMIT, SMS_RATE_LIMIT_WINDOW
        )

        current_time = time.time()
        cutoff_time = current_time - SMS_RATE_LIMIT_WINDOW

        # Clean up expired timestamps
        cleaned_system_counter = [t for t in sms_system_counter if t > cutoff_time]

        # Prepare per-user data
        user_data = {}
        for user_id, timestamps in sms_user_cache.items():
            valid_timestamps = [t for t in timestamps if t > cutoff_time]
            if valid_timestamps:
                user = User.query.get(user_id)
                username = user.username if user else "Unknown"

                user_data[user_id] = {
                    'username': username,
                    'count': len(valid_timestamps),
                    'remaining': SMS_RATE_LIMIT_PER_USER - len(valid_timestamps),
                    'last_send': datetime.fromtimestamp(max(valid_timestamps)).strftime('%Y-%m-%d %H:%M:%S'),
                    'reset': datetime.fromtimestamp(min(valid_timestamps) + SMS_RATE_LIMIT_WINDOW).strftime('%Y-%m-%d %H:%M:%S')
                }

        # Calculate system-wide reset time
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

    except ImportError:
        # SMS helpers may not be configured
        return jsonify({
            'error': 'SMS system not configured',
            'system': {'total_count': 0, 'limit': 0, 'remaining': 0},
            'users': {},
            'config': {}
        })
    except Exception as e:
        logger.error(f"Error getting SMS status: {e}")
        return jsonify({'error': str(e)}), 500


@admin_panel_bp.route('/communication/player-search')
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'Pub League Coach'])
def player_search():
    """Search for players by name for direct messaging."""
    try:
        from app.models import Player

        query = request.args.get('q', '').strip()
        if len(query) < 2:
            return jsonify({'players': []})

        # Search players by name
        players = Player.query.filter(
            Player.name.ilike(f'%{query}%')
        ).limit(20).all()

        results = []
        for player in players:
            user = player.user
            results.append({
                'id': player.id,
                'name': player.name,
                'phone': player.phone or '',
                'discord_id': player.discord_id or '',
                'has_phone': bool(player.phone),
                'has_discord': bool(player.discord_id),
                'sms_enabled': user.sms_notifications if user else False,
                'discord_enabled': user.discord_notifications if user else False,
                # SMS verification status for UI feedback
                'is_phone_verified': player.is_phone_verified if player else False,
                'sms_consent_given': player.sms_consent_given if player else False,
                'sms_eligible': bool(
                    player.phone and
                    player.is_phone_verified and
                    player.sms_consent_given and
                    (user.sms_notifications if user else False)
                )
            })

        return jsonify({'players': results})

    except Exception as e:
        logger.error(f"Error searching players: {e}")
        return jsonify({'error': str(e), 'players': []}), 500
