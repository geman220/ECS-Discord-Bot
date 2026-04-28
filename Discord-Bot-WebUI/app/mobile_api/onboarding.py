# app/mobile_api/onboarding.py

"""
Mobile Onboarding API

Mirrors the web onboarding flow (app/main.py:/onboarding) for mobile sign-ups.
After a user authenticates via Discord OAuth on mobile, they land in the same
pl-unverified state as web sign-ups (handled in process_discord_user). This
module exposes the equivalent of the web onboarding form so mobile can collect
the rest of the profile and flip has_completed_onboarding=True without forcing
users through the web UI.
"""

import logging
import os
from datetime import datetime

import requests
from flask import jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.mobile_api import mobile_api_v2
from app.core.session_manager import managed_session
from app.models import User, Player

logger = logging.getLogger(__name__)


# Mirrors the web onboarding form's player fields. Notification preferences and
# preferred_league are handled separately because they live on User, not Player.
_PLAYER_FIELDS = (
    'name', 'phone', 'jersey_size', 'jersey_number', 'pronouns',
    'favorite_position', 'other_positions', 'positions_not_to_play',
    'frequency_play_goal', 'expected_weeks_available', 'unavailable_dates',
    'willing_to_referee', 'additional_info', 'player_notes', 'team_swap',
)


def _coerce_int(value):
    if value in (None, ''):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _serialize_list_field(value):
    """Web stores other_positions / positions_not_to_play as `{a,b,c}`. Mirror that."""
    if value is None or value == '':
        return None
    if isinstance(value, list):
        cleaned = [v.strip() for v in value if v and v.strip()]
        return '{' + ','.join(cleaned) + '}' if cleaned else None
    return value  # already a string in the right shape


@mobile_api_v2.route('/onboarding/status', methods=['GET'])
@jwt_required()
def onboarding_status():
    """
    Report whether the current user still needs onboarding.

    Returns:
        {
            "has_completed_onboarding": bool,
            "has_skipped_profile_creation": bool,
            "needs_onboarding": bool,    # convenience: not completed and not skipped
            "has_player_record": bool,   # whether a Player row already exists
            "preferred_league": str|null
        }
    """
    current_user_id = int(get_jwt_identity())
    with managed_session() as session:
        user = session.query(User).get(current_user_id)
        if not user:
            return jsonify({"msg": "User not found"}), 404
        player = session.query(Player).filter_by(user_id=current_user_id).first()
        completed = bool(user.has_completed_onboarding)
        skipped = bool(user.has_skipped_profile_creation)
        return jsonify({
            "has_completed_onboarding": completed,
            "has_skipped_profile_creation": skipped,
            "needs_onboarding": not (completed or skipped),
            "has_player_record": player is not None,
            "preferred_league": user.preferred_league,
        }), 200


@mobile_api_v2.route('/onboarding/submit', methods=['POST'])
@jwt_required()
def onboarding_submit():
    """
    Submit the onboarding profile (mobile equivalent of web /onboarding POST).

    Creates the Player record if missing, fills in profile fields, sets
    notification preferences on User, optionally records preferred_league, and
    flips has_completed_onboarding=True.

    Body fields (all optional unless noted; same shape as web onboarding form):
        name, phone, jersey_size, jersey_number (int), pronouns,
        favorite_position, other_positions (list[str] | str),
        positions_not_to_play (list[str] | str),
        frequency_play_goal, expected_weeks_available, unavailable_dates,
        willing_to_referee, additional_info, player_notes, team_swap,
        date_of_birth (YYYY-MM-DD or null),
        ispy_opt_out (bool),
        email_notifications (bool),
        sms_notifications (bool),
        discord_notifications (bool),
        profile_visibility (str),
        preferred_league (str: 'classic' | 'premier' | 'ecs_fc' | 'not_sure'),
        skip (bool) — if true, set has_skipped_profile_creation=True instead of
            has_completed_onboarding (mirrors the web "skip for now" path)
    """
    data = request.get_json(silent=True) or {}
    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        user = session.query(User).get(current_user_id)
        if not user:
            return jsonify({"msg": "User not found"}), 404

        # Skip path — defer profile completion. Matches the web "skip for now" flow.
        if data.get('skip') is True:
            user.has_skipped_profile_creation = True
            session.commit()
            return jsonify({
                "success": True,
                "skipped": True,
                "has_completed_onboarding": False,
                "has_skipped_profile_creation": True,
            }), 200

        player = session.query(Player).filter_by(user_id=current_user_id).first()

        # Player should usually already exist (created by process_discord_user
        # at sign-up), but we recreate defensively for accounts that pre-date
        # that change.
        if not player:
            player = Player(
                user_id=current_user_id,
                name=data.get('name') or user.username,
                is_current_player=True,
                is_sub=True,
            )
            session.add(player)
            session.flush()

        # Apply Player fields — direct setattr is safe because _PLAYER_FIELDS
        # is a fixed whitelist.
        for field in _PLAYER_FIELDS:
            if field not in data:
                continue
            value = data[field]
            if field == 'jersey_number':
                value = _coerce_int(value)
            elif field in ('other_positions', 'positions_not_to_play'):
                value = _serialize_list_field(value)
            setattr(player, field, value)

        # date_of_birth (separate parsing).
        if 'date_of_birth' in data:
            raw_dob = data['date_of_birth']
            if raw_dob in (None, ''):
                player.date_of_birth = None
            else:
                from datetime import date as _date
                try:
                    player.date_of_birth = _date.fromisoformat(raw_dob)
                except (ValueError, TypeError):
                    return jsonify({"msg": "Invalid date_of_birth (expected YYYY-MM-DD)"}), 400

        # ispy_opt_out (bool).
        if 'ispy_opt_out' in data:
            player.ispy_opt_out = bool(data['ispy_opt_out'])

        # User-level fields: notification prefs + visibility + preferred_league.
        if 'email_notifications' in data:
            user.email_notifications = bool(data['email_notifications'])
        if 'sms_notifications' in data:
            user.sms_notifications = bool(data['sms_notifications'])
        if 'discord_notifications' in data:
            user.discord_notifications = bool(data['discord_notifications'])
        if 'profile_visibility' in data:
            user.profile_visibility = data['profile_visibility']

        preferred_league = data.get('preferred_league')
        if preferred_league == 'not_sure':
            preferred_league = None
        if preferred_league:
            user.preferred_league = preferred_league
            user.league_selection_method = 'onboarding_mobile'

        # Mark onboarding complete.
        user.has_completed_onboarding = True
        user.has_skipped_profile_creation = False
        player.profile_last_updated = datetime.utcnow()

        session.commit()

        # Best-effort Discord new-player notification (matches web behavior).
        # Failures here must not roll back onboarding — fire-and-log only.
        if player.discord_id:
            try:
                bot_url = os.getenv('BOT_API_URL', 'http://discord-bot:5001')
                requests.post(
                    f"{bot_url}/onboarding/notify-new-player",
                    json={'discord_id': player.discord_id},
                    timeout=5,
                )
            except Exception as exc:
                logger.warning(f"Failed to trigger new-player notification for {player.discord_id}: {exc}")

        logger.info(f"Mobile onboarding completed for user {user.id} (player {player.id})")

        return jsonify({
            "success": True,
            "skipped": False,
            "has_completed_onboarding": True,
            "has_skipped_profile_creation": False,
            "player": {
                "id": player.id,
                "name": player.name,
                "phone": player.phone,
                "jersey_size": player.jersey_size,
                "jersey_number": player.jersey_number,
                "pronouns": player.pronouns,
                "date_of_birth": player.date_of_birth.isoformat() if player.date_of_birth else None,
                "ispy_opt_out": player.ispy_opt_out,
                "favorite_position": player.favorite_position,
                "other_positions": player.other_positions,
                "positions_not_to_play": player.positions_not_to_play,
                "frequency_play_goal": player.frequency_play_goal,
                "expected_weeks_available": player.expected_weeks_available,
                "unavailable_dates": player.unavailable_dates,
                "willing_to_referee": player.willing_to_referee,
                "additional_info": player.additional_info,
                "player_notes": player.player_notes,
                "team_swap": player.team_swap,
                "is_current_player": player.is_current_player,
            },
            "user": {
                "id": user.id,
                "username": user.username,
                "preferred_league": user.preferred_league,
                "email_notifications": user.email_notifications,
                "sms_notifications": user.sms_notifications,
                "discord_notifications": user.discord_notifications,
                "profile_visibility": user.profile_visibility,
            },
        }), 200
