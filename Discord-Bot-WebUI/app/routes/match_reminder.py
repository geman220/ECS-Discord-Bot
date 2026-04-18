# app/routes/match_reminder.py

"""
Match Reminder Opt-Out API

Endpoints that flip `User.match_reminder_notifications`. Used by:
- The Discord bot (via discord_id) when a player taps "Don't remind me anymore"
- The web UI (via session auth) as backup for users who arrive via settings
"""

import logging

from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user

from app import csrf
from app.core.session_manager import managed_session
from app.models import User, Player

logger = logging.getLogger(__name__)

match_reminder_bp = Blueprint('match_reminder', __name__, url_prefix='/api/match-reminder')
csrf.exempt(match_reminder_bp)


@match_reminder_bp.route('/opt-out', methods=['POST'])
def opt_out():
    """Turn off match reminder notifications for a user.

    Accepts either `discord_id` (bot callback) or `user_id`/`player_id`
    (web UI). Idempotent — a second opt-out is a no-op.
    """
    data = request.get_json() or {}

    with managed_session() as session_db:
        user = _resolve_user(session_db, data)
        if not user:
            return jsonify({'success': False, 'error': 'User not found'}), 404

        already_off = not user.match_reminder_notifications
        user.match_reminder_notifications = False
        session_db.commit()

        logger.info(
            f"Match reminders opted OUT for user_id={user.id} "
            f"(already_off={already_off}, source={data.get('source', 'unknown')})"
        )
        return jsonify({
            'success': True,
            'user_id': user.id,
            'match_reminder_notifications': False,
            'already_off': already_off,
        })


@match_reminder_bp.route('/opt-in', methods=['POST'])
def opt_in():
    """Turn match reminder notifications back on."""
    data = request.get_json() or {}

    with managed_session() as session_db:
        user = _resolve_user(session_db, data)
        if not user:
            return jsonify({'success': False, 'error': 'User not found'}), 404

        user.match_reminder_notifications = True
        session_db.commit()

        logger.info(f"Match reminders opted IN for user_id={user.id}")
        return jsonify({
            'success': True,
            'user_id': user.id,
            'match_reminder_notifications': True,
        })


@match_reminder_bp.route('/status/<int:user_id>', methods=['GET'])
@login_required
def status(user_id):
    """Return the current match-reminder preference for a user."""
    if current_user.id != user_id and not current_user.is_admin:
        return jsonify({'error': 'Not authorized'}), 403

    with managed_session() as session_db:
        user = session_db.query(User).get(user_id)
        if not user:
            return jsonify({'error': 'User not found'}), 404
        return jsonify({
            'user_id': user.id,
            'match_reminder_notifications': user.match_reminder_notifications,
        })


def _resolve_user(session_db, data):
    """Resolve User from discord_id, user_id, or player_id in request data."""
    discord_id = data.get('discord_id')
    user_id = data.get('user_id')
    player_id = data.get('player_id')

    if discord_id:
        player = session_db.query(Player).filter_by(discord_id=str(discord_id)).first()
        return player.user if player and player.user else None
    if user_id:
        return session_db.query(User).get(user_id)
    if player_id:
        player = session_db.query(Player).get(player_id)
        return player.user if player and player.user else None
    return None
