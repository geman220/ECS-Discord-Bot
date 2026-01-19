# app/admin_panel/routes/match_operations/substitute_contact.py

"""
Substitute Contact Routes

Admin routes for contacting substitutes:
- Contact all subs in a pool
- Contact individual subs
- View availability status
- Compose messages with auto-filled match details
"""

import logging
from datetime import datetime

from flask import request, jsonify, render_template
from flask_login import login_required, current_user

from app.admin_panel import admin_panel_bp
from app.core import db
from app.decorators import role_required
from app.models.admin_config import AdminAuditLog
from app.services.substitute_notification_service import get_notification_service
from app.services.substitute_rsvp_service import get_rsvp_service

logger = logging.getLogger(__name__)


@admin_panel_bp.route('/substitute-contact/notify-pool', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'Pub League Coach'])
def notify_substitute_pool():
    """
    Contact substitutes in a pool for a specific request.
    Supports filtering by recipient_type, gender, positions, or specific players.

    Expected JSON payload:
    {
        "request_id": int,
        "league_type": str,  # "Premier", "Classic"
        "custom_message": str,
        "channels": ["EMAIL", "SMS", "DISCORD"],  # optional, defaults to all
        "recipient_type": str,  # "all", "gender", "position", "specific"
        "gender_filter": str,  # optional, for gender filtering
        "position_filters": [],  # optional, list of positions
        "player_ids": [],  # optional, specific player IDs
        "subs_needed": int  # optional, how many subs are needed
    }
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400

        request_id = data.get('request_id')
        league_type = data.get('league_type')
        custom_message = data.get('custom_message', '')
        channels = data.get('channels')
        recipient_type = data.get('recipient_type', 'all')
        gender_filter = data.get('gender_filter')
        position_filters = data.get('position_filters', [])
        player_ids = data.get('player_ids', [])
        subs_needed = data.get('subs_needed', 1)

        if not request_id or not league_type:
            return jsonify({
                'success': False,
                'error': 'Missing required fields: request_id and league_type'
            }), 400

        # Get notification service
        notification_service = get_notification_service()

        # Send notifications with filtering
        result = notification_service.notify_pool(
            request_id=request_id,
            league_type=league_type,
            custom_message=custom_message,
            channels=channels,
            gender_filter=gender_filter if recipient_type == 'gender' else None,
            position_filters=position_filters if recipient_type == 'position' else None,
            player_ids=player_ids if recipient_type == 'specific' else None,
            subs_needed=subs_needed
        )

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='notify_substitute_pool',
            resource_type='substitute_request',
            resource_id=str(request_id),
            new_value=f'Contacted {result.get("notifications_sent", 0)} subs for {league_type}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify(result)

    except Exception as e:
        logger.exception(f"Error notifying substitute pool: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/substitute-contact/notify-individual', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'Pub League Coach'])
def notify_individual_substitute():
    """
    Contact a single substitute for a request.

    Expected JSON payload:
    {
        "player_id": int,
        "request_id": int,
        "custom_message": str,
        "channels": ["EMAIL", "SMS", "DISCORD"]  # optional
    }
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400

        player_id = data.get('player_id')
        request_id = data.get('request_id')
        custom_message = data.get('custom_message', '')
        channels = data.get('channels')

        if not player_id or not request_id:
            return jsonify({
                'success': False,
                'error': 'Missing required fields: player_id and request_id'
            }), 400

        # Get notification service
        notification_service = get_notification_service()

        # Send notification
        result = notification_service.notify_individual(
            player_id=player_id,
            request_id=request_id,
            custom_message=custom_message,
            channels=channels
        )

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='notify_individual_substitute',
            resource_type='substitute_request',
            resource_id=str(request_id),
            new_value=f'Contacted player {player_id} via {", ".join(result.get("channels_used", []))}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify(result)

    except Exception as e:
        logger.exception(f"Error notifying individual substitute: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/substitute-contact/<int:request_id>/availability')
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'Pub League Coach'])
def get_request_availability(request_id):
    """
    Get availability status for all contacted subs for a request.
    Returns color-coded status for display.
    """
    try:
        league_type = request.args.get('league_type', 'pub_league')

        rsvp_service = get_rsvp_service()
        status = rsvp_service.get_request_availability_status(request_id, league_type)

        return jsonify({
            'success': True,
            **status
        })

    except Exception as e:
        logger.exception(f"Error getting availability status: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/substitute-contact/compose-message')
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'Pub League Coach'])
def compose_sub_message():
    """
    Get auto-filled message template with match details.

    Query params:
    - request_id: SubstituteRequest ID
    """
    try:
        from app.models.substitutes import SubstituteRequest

        request_id = request.args.get('request_id', type=int)

        if not request_id:
            return jsonify({'success': False, 'error': 'request_id required'}), 400

        sub_request = db.session.query(SubstituteRequest).get(request_id)

        if not sub_request:
            return jsonify({'success': False, 'error': 'Request not found'}), 404

        match = sub_request.match
        team = sub_request.team

        # Build default message template
        template = f"""Hi! We're looking for a substitute player.

Team: {team.name}
Match: {match.home_team.name} vs {match.away_team.name}
Date: {match.date.strftime('%A, %B %d, %Y') if match.date else 'TBD'}
Time: {match.time.strftime('%I:%M %p') if match.time else 'TBD'}
Location: {match.location or 'TBD'}"""

        if sub_request.positions_needed:
            template += f"\nPosition(s) needed: {sub_request.positions_needed}"

        if sub_request.notes:
            template += f"\n\nAdditional info: {sub_request.notes}"

        template += "\n\nPlease click the link below to let us know if you're available."

        return jsonify({
            'success': True,
            'template': template,
            'match_details': {
                'id': match.id,
                'home_team': match.home_team.name,
                'away_team': match.away_team.name,
                'date': match.date.isoformat() if match.date else None,
                'time': match.time.strftime('%H:%M') if match.time else None,
                'location': match.location
            },
            'team': {
                'id': team.id,
                'name': team.name
            },
            'request': {
                'id': sub_request.id,
                'positions_needed': sub_request.positions_needed,
                'substitutes_needed': sub_request.substitutes_needed,
                'notes': sub_request.notes
            }
        })

    except Exception as e:
        logger.exception(f"Error composing message: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/substitute-contact/available-subs')
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'Pub League Coach'])
def get_available_subs():
    """
    Get list of available substitutes for a league type.

    Query params:
    - league_type: "Premier", "Classic", or "ECS FC"
    - gender_filter: optional gender filter
    """
    try:
        from app.models.substitutes import get_active_substitutes

        league_type = request.args.get('league_type')
        gender_filter = request.args.get('gender_filter')

        if not league_type:
            return jsonify({'success': False, 'error': 'league_type required'}), 400

        active_subs = get_active_substitutes(league_type, db.session, gender_filter)

        notification_service = get_notification_service()

        subs_data = []
        for pool_entry in active_subs:
            player = pool_entry.player
            channels = notification_service.get_player_channels(player, pool_entry)

            subs_data.append({
                'pool_id': pool_entry.id,
                'player_id': player.id,
                'name': player.name,
                'pronouns': player.pronouns,
                'preferred_positions': pool_entry.preferred_positions,
                'acceptance_rate': pool_entry.acceptance_rate,
                'matches_played': pool_entry.matches_played,
                'channels': {
                    'email': channels.get('EMAIL', False),
                    'sms': channels.get('SMS', False),
                    'discord': channels.get('DISCORD', False)
                }
            })

        return jsonify({
            'success': True,
            'league_type': league_type,
            'total': len(subs_data),
            'subs': subs_data
        })

    except Exception as e:
        logger.exception(f"Error getting available subs: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/substitute-contact/send-confirmation', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def send_assignment_confirmation():
    """
    Send confirmation notification to an assigned substitute.

    Expected JSON payload:
    {
        "assignment_id": int,
        "league_type": str  # optional, defaults to "pub_league"
    }
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400

        assignment_id = data.get('assignment_id')
        league_type = data.get('league_type', 'pub_league')

        if not assignment_id:
            return jsonify({'success': False, 'error': 'assignment_id required'}), 400

        notification_service = get_notification_service()

        result = notification_service.send_confirmation(
            assignment_id=assignment_id,
            league_type=league_type
        )

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='send_sub_confirmation',
            resource_type='substitute_assignment',
            resource_id=str(assignment_id),
            new_value=f'Sent confirmation via {", ".join(result.get("channels_used", []))}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify(result)

    except Exception as e:
        logger.exception(f"Error sending confirmation: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
