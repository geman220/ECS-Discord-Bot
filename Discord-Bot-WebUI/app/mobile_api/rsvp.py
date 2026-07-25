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
from app.models.players import player_teams
from app.events.rsvp_events import RSVPSource
from app.services.rsvp_service import create_rsvp_service_sync

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
    target_player_id = data.get('player_id')

    if not match_id or not availability_response:
        return jsonify({"msg": "Missing match_id or availability"}), 400

    valid_responses = ['yes', 'no', 'maybe', 'no_response']
    if availability_response not in valid_responses:
        return jsonify({"msg": f"Invalid availability. Must be one of: {valid_responses}"}), 400

    with managed_session() as session_db:
        # Handle Discord user lookup
        if isinstance(current_user_id, str) and not current_user_id.isdigit():
            # Discord user ID - find player by discord_id
            auth_player = session_db.query(Player).filter_by(discord_id=current_user_id).first()
        else:
            auth_player = session_db.query(Player).filter_by(user_id=int(current_user_id)).first()

        if not auth_player:
            return jsonify({"msg": "Player not found"}), 404

        # Determine which player's availability to update
        if target_player_id and target_player_id != auth_player.id:
            # Coach setting availability on behalf of a player
            if not auth_player.is_coach:
                return jsonify({"msg": "Only coaches can update availability for other players"}), 403

            target_player = session_db.query(Player).get(target_player_id)
            if not target_player:
                return jsonify({"msg": "Target player not found"}), 404

            # Verify the target player is on one of the coach's teams
            from sqlalchemy import and_
            coach_team_ids = session_db.query(player_teams.c.team_id).filter(
                player_teams.c.player_id == auth_player.id
            ).subquery()
            shared_team = session_db.query(player_teams.c.team_id).filter(
                and_(
                    player_teams.c.player_id == target_player_id,
                    player_teams.c.team_id.in_(coach_team_ids)
                )
            ).first()

            if not shared_team:
                return jsonify({"msg": "Target player is not on your team"}), 403

            player = target_player
        else:
            player = auth_player

        match = session_db.query(Match).get(match_id)
        if not match:
            return jsonify({"msg": "Match not found"}), 404

        # Commit through the canonical service so this path gets the same
        # validation, the same no_response semantics, and the same fan-out to
        # cache / websockets / Discord as the web, Discord and SMS paths.
        rsvp_service = create_rsvp_service_sync(session_db)
        success, message, _event = rsvp_service.update_rsvp_sync(
            match_id=match_id,
            player_id=player.id,
            new_response=availability_response,
            source=RSVPSource.MOBILE,
        )

        if not success:
            return jsonify({"msg": message}), 400

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

        # Same canonical path as /update_availability. This endpoint previously
        # did no response validation at all -- update_rsvp_sync rejects anything
        # outside yes/no/maybe/no_response.
        rsvp_service = create_rsvp_service_sync(session_db)
        success, message, _event = rsvp_service.update_rsvp_sync(
            match_id=match_id,
            player_id=player.id,
            new_response=availability_response,
            source=RSVPSource.MOBILE,
        )

        if not success:
            return jsonify({"success": False, "msg": message}), 400

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

        rsvp_service = create_rsvp_service_sync(session_db)
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
                # Previously wrote straight to the Availability row and notified
                # nothing at all -- a bulk RSVP from the app left Discord, the web
                # UI and the read cache stale until something else refreshed them.
                # Going through the service fans each match out individually.
                success, message, _event = rsvp_service.update_rsvp_sync(
                    match_id=match_id,
                    player_id=player.id,
                    new_response=availability_response,
                    source=RSVPSource.MOBILE,
                )
                results.append({
                    "match_id": match_id,
                    "success": success,
                    "availability": availability_response,
                    **({} if success else {"error": message}),
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
