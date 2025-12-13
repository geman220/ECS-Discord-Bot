# app/api/rsvp.py

"""
RSVP API Endpoints

Handles availability and RSVP operations including:
- Update availability
- Bulk availability updates
- Debug endpoints for RSVP testing
"""

import logging
from datetime import datetime

from flask import jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.mobile_api import mobile_api_v2
from app.mobile_api.middleware import jwt_or_discord_auth_required
from app.core.session_manager import managed_session
from app.models import Player, Match, Availability
from app.app_api_helpers import (
    update_player_availability,
    update_player_match_availability,
    notify_availability_update,
)

logger = logging.getLogger(__name__)


@mobile_api_v2.route('/update_availability', methods=['POST'])
@jwt_or_discord_auth_required
def update_availability():
    """
    Update availability for a specific match.

    Expected JSON parameters:
        match_id: The match ID
        availability: The availability response ('yes', 'no', 'maybe')

    Returns:
        JSON with update result
    """
    from flask import g
    current_user_id = g.current_user_id

    data = request.json or {}
    match_id = data.get('match_id')
    availability_response = data.get('availability')

    if not match_id or not availability_response:
        return jsonify({"msg": "Missing match_id or availability"}), 400

    valid_responses = ['yes', 'no', 'maybe', 'no_response']
    if availability_response not in valid_responses:
        return jsonify({"msg": f"Invalid availability. Must be one of: {valid_responses}"}), 400

    with managed_session() as session_db:
        # Handle Discord user lookup
        if isinstance(current_user_id, str) and not current_user_id.isdigit():
            # Discord user ID - find player by discord_id
            player = session_db.query(Player).filter_by(discord_id=current_user_id).first()
        else:
            player = session_db.query(Player).filter_by(user_id=int(current_user_id)).first()

        if not player:
            return jsonify({"msg": "Player not found"}), 404

        match = session_db.query(Match).get(match_id)
        if not match:
            return jsonify({"msg": "Match not found"}), 404

        # Update or create availability record
        result = update_player_match_availability(
            session=session_db,
            match_id=match_id,
            player_id=player.id,
            response=availability_response
        )

        # Notify other systems of the update
        notify_availability_update(match_id, player.id, availability_response)

        return jsonify({
            "msg": "Availability updated",
            "match_id": match_id,
            "player_id": player.id,
            "availability": availability_response
        }), 200


@mobile_api_v2.route('/update_availability_web', methods=['POST'])
@jwt_required()
def update_availability_web():
    """
    Update availability from web interface.
    Similar to update_availability but expects different parameter format.

    Expected JSON parameters:
        match_id: The match ID
        response: The availability response

    Returns:
        JSON with update result
    """
    current_user_id = int(get_jwt_identity())

    data = request.json or {}
    match_id = data.get('match_id')
    availability_response = data.get('response')

    if not match_id or not availability_response:
        return jsonify({"msg": "Missing match_id or response"}), 400

    with managed_session() as session_db:
        player = session_db.query(Player).filter_by(user_id=current_user_id).first()
        if not player:
            return jsonify({"msg": "Player not found"}), 404

        result = update_player_match_availability(
            session=session_db,
            match_id=match_id,
            player_id=player.id,
            response=availability_response
        )

        notify_availability_update(match_id, player.id, availability_response)

        return jsonify({
            "success": True,
            "msg": "Availability updated",
            "match_id": match_id,
            "availability": availability_response
        }), 200


@mobile_api_v2.route('/matches/availability/bulk', methods=['POST'])
@jwt_required()
def bulk_availability_update():
    """
    Update availability for multiple matches at once.

    Expected JSON parameters:
        updates: List of {match_id, availability} objects

    Returns:
        JSON with results for each update
    """
    current_user_id = int(get_jwt_identity())

    data = request.json or {}
    updates = data.get('updates', [])

    if not updates:
        return jsonify({"msg": "No updates provided"}), 400

    with managed_session() as session_db:
        player = session_db.query(Player).filter_by(user_id=current_user_id).first()
        if not player:
            return jsonify({"msg": "Player not found"}), 404

        results = []
        for update in updates:
            match_id = update.get('match_id')
            availability_response = update.get('availability')

            if not match_id or not availability_response:
                results.append({
                    "match_id": match_id,
                    "success": False,
                    "error": "Missing match_id or availability"
                })
                continue

            match = session_db.query(Match).get(match_id)
            if not match:
                results.append({
                    "match_id": match_id,
                    "success": False,
                    "error": "Match not found"
                })
                continue

            try:
                update_player_match_availability(
                    session=session_db,
                    match_id=match_id,
                    player_id=player.id,
                    response=availability_response
                )
                results.append({
                    "match_id": match_id,
                    "success": True,
                    "availability": availability_response
                })
            except Exception as e:
                results.append({
                    "match_id": match_id,
                    "success": False,
                    "error": str(e)
                })

        return jsonify({
            "msg": "Bulk update completed",
            "results": results,
            "successful": sum(1 for r in results if r.get('success')),
            "failed": sum(1 for r in results if not r.get('success'))
        }), 200


@mobile_api_v2.route('/debug/availability', methods=['GET'])
@jwt_required()
def debug_availability():
    """
    Debug endpoint to view availability data.
    Only for testing purposes.

    Returns:
        JSON with availability debug info
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session_db:
        player = session_db.query(Player).filter_by(user_id=current_user_id).first()
        if not player:
            return jsonify({"msg": "Player not found"}), 404

        # Get recent availability records
        availabilities = session_db.query(Availability).filter_by(
            player_id=player.id
        ).order_by(Availability.id.desc()).limit(10).all()

        data = []
        for av in availabilities:
            data.append({
                "id": av.id,
                "match_id": av.match_id,
                "response": av.response,
                "updated_at": av.updated_at.isoformat() if hasattr(av, 'updated_at') and av.updated_at else None
            })

        return jsonify({
            "player_id": player.id,
            "player_name": player.name,
            "recent_availability": data
        }), 200
