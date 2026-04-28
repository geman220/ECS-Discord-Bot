# app/mobile_api/live_activity.py

"""
Live Activity (iOS ActivityKit) Push Token Endpoints

Mobile registers a per-Activity APNs push token here when starting an iOS
Live Activity for a match. Flask uses the token to push score / timer / event
updates to the lock-screen widget while the app is backgrounded.

Tokens are scoped (user_id, match_id, league_type) and idempotent — re-registering
the same token is a no-op.
"""

import logging
from datetime import datetime

from flask import jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.mobile_api import mobile_api_v2
from app.core.session_manager import managed_session
from app.models import LiveActivityToken

logger = logging.getLogger(__name__)


_VALID_LEAGUE_TYPES = ('pub', 'ecs_fc')


def _validate_payload(data: dict):
    """Returns (match_id_int, league_type, push_token, error_response_or_none)."""
    if not data:
        return None, None, None, (jsonify({"msg": "Missing request body"}), 400)
    match_id = data.get('match_id')
    league_type = (data.get('league_type') or 'pub').lower()
    push_token = (data.get('push_token') or '').strip()

    if not match_id:
        return None, None, None, (jsonify({"msg": "match_id is required"}), 400)
    try:
        match_id = int(match_id)
    except (TypeError, ValueError):
        return None, None, None, (jsonify({"msg": "match_id must be an integer"}), 400)

    if league_type not in _VALID_LEAGUE_TYPES:
        return None, None, None, (jsonify({"msg": f"league_type must be one of {_VALID_LEAGUE_TYPES}"}), 400)

    if not push_token:
        return None, None, None, (jsonify({"msg": "push_token is required"}), 400)
    # APNs Live Activity tokens are hex strings, typically 160 chars but Apple
    # has reserved up to 200 — reject anything implausibly long.
    if len(push_token) > 200:
        return None, None, None, (jsonify({"msg": "push_token too long"}), 400)

    return match_id, league_type, push_token, None


@mobile_api_v2.route('/live-activity/register', methods=['POST'])
@jwt_required()
def register_live_activity():
    """
    Register a Live Activity push token for the current user + match.

    Mobile calls this immediately after `Activity.request(...)` resolves on iOS
    and the per-activity push token becomes available.

    Body:
        match_id: int
        league_type: 'pub' | 'ecs_fc' (defaults to 'pub')
        push_token: hex-encoded APNs Live Activity token

    Returns 201 on first registration, 200 on idempotent re-registration.
    """
    data = request.get_json(silent=True) or {}
    match_id, league_type, push_token, err = _validate_payload(data)
    if err:
        return err

    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        existing = session.query(LiveActivityToken).filter_by(
            user_id=current_user_id,
            match_id=match_id,
            league_type=league_type,
            push_token=push_token,
        ).first()

        if existing:
            # Re-registration may mean the user re-opened the activity; clear
            # ended_at so we resume pushing.
            if existing.ended_at is not None:
                existing.ended_at = None
                existing.push_failure_count = 0
                existing.last_error = None
            session.commit()
            return jsonify({
                "success": True,
                "id": existing.id,
                "ended_at": None,
                "idempotent": True,
            }), 200

        token = LiveActivityToken(
            user_id=current_user_id,
            match_id=match_id,
            league_type=league_type,
            push_token=push_token,
            created_at=datetime.utcnow(),
        )
        session.add(token)
        session.commit()
        return jsonify({
            "success": True,
            "id": token.id,
            "idempotent": False,
        }), 201


@mobile_api_v2.route('/live-activity/unregister', methods=['POST'])
@jwt_required()
def unregister_live_activity():
    """
    Mark a Live Activity token as ended.

    Called when:
      - The user manually dismisses the activity from the lock screen.
      - The activity expires naturally (iOS gives Live Activities a max of ~12h).
      - The mobile app determines the activity is no longer needed.

    Body:
        match_id: int
        league_type: 'pub' | 'ecs_fc'
        push_token: the same token that was registered

    Returns 200 always (idempotent — safe to call on already-ended tokens).
    """
    data = request.get_json(silent=True) or {}
    match_id, league_type, push_token, err = _validate_payload(data)
    if err:
        return err

    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        token = session.query(LiveActivityToken).filter_by(
            user_id=current_user_id,
            match_id=match_id,
            league_type=league_type,
            push_token=push_token,
        ).first()
        if token and token.ended_at is None:
            token.ended_at = datetime.utcnow()
            session.commit()
        return jsonify({"success": True}), 200
