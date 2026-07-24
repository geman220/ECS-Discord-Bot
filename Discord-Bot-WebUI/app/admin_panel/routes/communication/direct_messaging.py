# app/admin_panel/routes/communication/direct_messaging.py

"""
Direct Messaging Routes

Routes for one-to-one SMS, Discord DM and email messaging.
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
        from sqlalchemy.orm import joinedload
        from app.models import Player

        # Get statistics
        stats = {
            'total_players': Player.query.count(),
            'players_with_phone': Player.query.filter(Player.phone != None, Player.phone != '').count(),
            'players_with_discord': Player.query.filter(Player.discord_id != None).count(),
            # Emails are encrypted, so reachability is counted off the search
            # hash column rather than the ciphertext.
            'players_with_email': Player.query.join(User, Player.user_id == User.id).filter(
                User.email_hash.isnot(None)).count(),
            'sms_enabled_users': User.query.filter_by(sms_notifications=True).count(),
            'discord_enabled_users': User.query.filter_by(discord_notifications=True).count(),
            'email_enabled_users': User.query.filter(
                User.email_hash.isnot(None),
                User.email_notifications.isnot(False)).count(),
        }

        # Get recent players for quick messaging. The template reads notification
        # flags off player.user for every row, so eager-load it.
        recent_players = Player.query.options(
            joinedload(Player.user)
        ).order_by(Player.id.desc()).limit(20).all()

        # The email preview only claims the ECS header/footer when a default
        # layout actually exists to wrap the body in.
        from app.models.email_templates import EmailTemplate
        has_email_layout = EmailTemplate.query.filter_by(
            is_default=True, is_deleted=False).count() > 0

        return render_template(
            'admin_panel/communication/direct_messaging_flowbite.html',
            stats=stats,
            recent_players=recent_players,
            has_email_layout=has_email_layout
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

        # Add opt-out language for TCPA compliance
        full_message = f"{message}\n\nReply STOP to opt out."

        # Send the SMS with audit logging parameters
        success, result = sms_send(
            phone, full_message, user_id=user_id,
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
            return jsonify({'success': False, 'message': 'Internal Server Error'}), 500
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
                return jsonify({'success': False, 'message': 'Internal Server Error'})
            flash('Internal Server Error')

        return redirect(url_for('admin_panel.direct_messaging'))

    except Exception as e:
        logger.error(f"Error sending Discord DM: {e}")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Internal Server Error'}), 500
        flash('Failed to send Discord DM.', 'error')
        return redirect(url_for('admin_panel.direct_messaging'))


@admin_panel_bp.route('/communication/send-direct-email', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'Pub League Coach'])
def send_direct_email():
    """Send a one-off email to a single player.

    Queued to Celery rather than sent inline: send_email() blocks on the Gmail
    API, and holding a PgBouncer transaction slot across that round trip is what
    "slow queries" on this app actually are.
    """
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    def _fail(message, status=400):
        if is_ajax:
            return jsonify({'success': False, 'message': message}), status
        flash(message, 'error')
        return redirect(url_for('admin_panel.direct_messaging'))

    try:
        from app.models import Player

        player_id = request.form.get('player_id')
        subject = (request.form.get('subject') or '').strip()
        message = (request.form.get('message') or '').strip()

        if not player_id or not subject or not message:
            return _fail('A recipient, subject and message are all required.')
        if len(subject) > 200:
            return _fail('Subject must be 200 characters or fewer.')
        try:
            player_id = int(player_id)
        except (TypeError, ValueError):
            # A non-numeric id would reach the DB and raise a DataError.
            return _fail('Player not found.', 404)

        player = Player.query.get(player_id)
        if not player:
            return _fail('Player not found.', 404)

        user = player.user
        if not user or not user.email:
            return _fail('This player has no email address on file.', 403)
        # Unlike SMS there is no legal verification gate, but the member's own
        # email preference is still honored.
        if user.email_notifications is False:
            return _fail('Email notifications are turned off for this member.', 403)

        # Plain-text composer -> minimal HTML. Escaped first so a message
        # containing < or & can't inject markup into the email body.
        from markupsafe import escape
        body_html = '<p>' + '</p><p>'.join(
            str(escape(p)).replace('\n', '<br>')
            for p in message.split('\n\n') if p.strip()
        ) + '</p>'

        from app.tasks.tasks_email_broadcast import send_direct_admin_email
        try:
            send_direct_admin_email.delay(user.id, subject, body_html, current_user.id)
        except Exception as enqueue_err:
            logger.error(f"Could not queue direct email to player {player_id}: {enqueue_err}")
            return _fail('The email could not be queued for delivery. Check the task queue and retry.', 502)

        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='send_direct_email',
            resource_type='direct_messaging',
            resource_id=str(player_id),
            new_value=f'Email queued to player {player.name}: {subject[:80]}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        logger.info(f"Admin {current_user.id} queued a direct email to player {player_id}")
        ok = 'Email queued — it sends in the background within a few seconds.'
        if is_ajax:
            return jsonify({'success': True, 'message': ok})
        flash(ok, 'success')
        return redirect(url_for('admin_panel.direct_messaging'))

    except Exception as e:
        logger.error(f"Error sending direct email: {e}")
        if is_ajax:
            return jsonify({'success': False, 'message': 'Internal Server Error'}), 500
        flash('Failed to send the email.', 'error')
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
        return jsonify({'error': 'Internal Server Error'}), 500


@admin_panel_bp.route('/communication/player-search')
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'Pub League Coach'])
def player_search():
    """Search for players by name for direct messaging."""
    try:
        from flask import g
        from sqlalchemy.orm import joinedload
        from app.models import Player

        query = request.args.get('q', '').strip()
        if len(query) < 2:
            return jsonify({'players': []})

        # Search players by name — request session (not Model.query/db.session,
        # which pins a second pooled connection), user eager-loaded since the
        # serializer reads notification flags off it for every row.
        players = g.db_session.query(Player).options(
            joinedload(Player.user)
        ).filter(
            Player.name.ilike(f'%{query}%')
        ).limit(20).all()

        # This endpoint is also open to coaches. They may still send a direct
        # email, but only admins get to see the actual address back — knowing a
        # channel is available is not the same as being handed everyone's email.
        show_email = current_user.has_role('Global Admin') or current_user.has_role('Pub League Admin')

        results = []
        for player in players:
            user = player.user
            # Decrypting per row is cheap here (max 20) and the address is what
            # makes the email channel verifiable before an admin hits send.
            email = (user.email if user else None) or ''
            results.append({
                'id': player.id,
                'name': player.name,
                'phone': player.phone or '',
                'discord_id': player.discord_id or '',
                'email': email if show_email else '',
                'has_phone': bool(player.phone),
                'has_discord': bool(player.discord_id),
                'has_email': bool(email),
                'sms_enabled': user.sms_notifications if user else False,
                'discord_enabled': user.discord_notifications if user else False,
                # email_notifications defaults to True; only an explicit False
                # is an opt-out.
                'email_enabled': (user.email_notifications is not False) if user else False,
                'email_eligible': bool(email and user and user.email_notifications is not False),
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
        return jsonify({'error': 'Internal Server Error', 'players': []}), 500
