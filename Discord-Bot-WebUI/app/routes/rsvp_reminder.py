# app/routes/rsvp_reminder.py

"""
RSVP Reminder API Routes

Endpoints for managing RSVP reminder snooze/break preferences.
Used by both the Discord bot (via discord_id) and the web UI (via session auth).
"""

import logging
from datetime import date

from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user

from app import csrf
from app.core import db
from app.core.session_manager import managed_session
from app.models import Player
from app.services import rsvp_snooze_service

logger = logging.getLogger(__name__)

rsvp_reminder_bp = Blueprint('rsvp_reminder', __name__, url_prefix='/api/rsvp-reminder')
csrf.exempt(rsvp_reminder_bp)


@rsvp_reminder_bp.route('/snooze', methods=['POST'])
def set_snooze():
    """
    Set RSVP reminder snooze for a player.

    Accepts either discord_id (from bot) or player_id (from web UI).

    Request Body:
        {
            "discord_id": "string",       // OR "player_id": int
            "duration_weeks": int|null,    // null = rest of season
            "reason": "dm_button|web_ui|admin"  // optional, default 'web_ui'
        }
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Request body required'}), 400

    duration_weeks = data.get('duration_weeks')
    reason = data.get('reason', 'web_ui')

    # Validate duration
    if duration_weeks is not None:
        if not isinstance(duration_weeks, int) or duration_weeks < 1 or duration_weeks > 52:
            return jsonify({'error': 'duration_weeks must be between 1 and 52, or null for rest of season'}), 400

    with managed_session() as session_db:
        # Resolve player
        player = _resolve_player(session_db, data)
        if not player:
            return jsonify({'error': 'Player not found'}), 404

        created_by = None
        if reason == 'admin' and current_user and current_user.is_authenticated:
            created_by = current_user.id

        snooze = rsvp_snooze_service.set_snooze(
            player_id=player.id,
            duration_weeks=duration_weeks,
            reason=reason,
            created_by=created_by
        )

        return jsonify({
            'success': True,
            'player_id': player.id,
            'snooze_until': snooze.snooze_until.isoformat(),
            'duration_weeks': snooze.duration_weeks
        })


@rsvp_reminder_bp.route('/snooze/<int:player_id>', methods=['GET'])
@login_required
def get_snooze(player_id):
    """Get current snooze status for a player."""
    snooze = rsvp_snooze_service.get_snooze(player_id)
    if not snooze:
        return jsonify({'snoozed': False})

    return jsonify({
        'snoozed': True,
        'snooze_until': snooze.snooze_until.isoformat(),
        'duration_weeks': snooze.duration_weeks,
        'reason': snooze.reason,
        'created_at': snooze.created_at.isoformat() if snooze.created_at else None
    })


@rsvp_reminder_bp.route('/snooze/<int:player_id>', methods=['DELETE'])
@login_required
def clear_snooze(player_id):
    """Clear snooze for a player. Requires admin or self."""
    # Allow self-service (player clearing their own) or admin
    if current_user.player and current_user.player.id == player_id:
        pass  # Self-service allowed
    elif current_user.is_admin:
        pass  # Admin allowed
    else:
        return jsonify({'error': 'Not authorized'}), 403

    cleared = rsvp_snooze_service.clear_snooze(player_id)
    return jsonify({'success': True, 'was_snoozed': cleared})


@rsvp_reminder_bp.route('/snoozed-players', methods=['GET'])
@login_required
def list_snoozed_players():
    """List all currently snoozed players (admin only)."""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403

    snoozes = rsvp_snooze_service.get_all_snoozed_players()
    return jsonify({
        'snoozed_players': [
            {
                'player_id': s.player_id,
                'player_name': s.player.name if s.player else 'Unknown',
                'snooze_until': s.snooze_until.isoformat(),
                'duration_weeks': s.duration_weeks,
                'reason': s.reason,
                'created_at': s.created_at.isoformat() if s.created_at else None
            }
            for s in snoozes
        ]
    })


def _resolve_player(session_db, data):
    """Resolve player from discord_id or player_id in request data."""
    discord_id = data.get('discord_id')
    player_id = data.get('player_id')

    if discord_id:
        return session_db.query(Player).filter_by(discord_id=str(discord_id)).first()
    elif player_id:
        return session_db.query(Player).get(player_id)
    return None
