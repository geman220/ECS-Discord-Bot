# app/mobile_api/substitutes.py

"""
Mobile API Substitute Management Endpoints

Provides substitute system functionality for mobile clients:
- Coaches: Create/view/update/cancel substitute requests for their teams
- Admins: View all requests, assign substitutes, manage pool
- Sub Pool Players: View available requests, respond, manage pool membership
"""

import logging
import os
import json
from datetime import datetime

import requests
from flask import jsonify, request, g
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError

from web_config import Config
from app.mobile_api import mobile_api_v2
from app.constants.positions import label_for
from app.decorators import jwt_role_required
from app.utils.mobile_auth import api_key_required
from app.core.session_manager import managed_session
from app.models import User, Player, Team, Match, player_teams
from app.models.core import Role
from app.models.admin_config import AdminAuditLog
from app.models.discord_polls import DiscordPoll, DiscordPollVote
from app.models.substitutes import (
    SubstituteRequest, SubstituteResponse, SubstituteAssignment,
    SubstitutePool, SubstitutePoolHistory
)
from app.utils.pacific_time import pacific_today, pacific_now, pacific_datetime

logger = logging.getLogger(__name__)


# Channel registry for /substitutes/discord/availability-poll.
# Maps channel_key -> env var holding the Discord channel ID and the role names
# to ping when posting. Easily extensible for future channels (e.g. ecs_fc_subs).
DISCORD_POLL_CHANNELS = {
    'pl_subs': {
        'channel_env_var': 'DISCORD_PL_SUBS_CHANNEL_ID',
        'channel_id_default': '1420461752344117300',  # #pl-subs
        'tag_role_names': ['ECS-FC-PL-CLASSIC-SUB', 'ECS-FC-PL-PREMIER-SUB'],
    },
}


# ============================================================================
# Authorization Helpers
# ============================================================================

def is_coach_for_team(session, user_id: int, team_id: int) -> bool:
    """Check if user is a coach for the specified team."""
    player = session.query(Player).filter_by(user_id=user_id).first()
    if not player:
        return False

    coach_check = session.execute(
        player_teams.select().where(
            and_(
                player_teams.c.player_id == player.id,
                player_teams.c.team_id == team_id,
                player_teams.c.is_coach == True
            )
        )
    ).fetchone()

    return coach_check is not None


def is_admin_user(session, user_id: int) -> bool:
    """Check if user has admin role."""
    user = session.query(User).options(
        joinedload(User.roles)
    ).filter(User.id == user_id).first()

    if not user or not user.roles:
        return False

    admin_roles = ['Global Admin', 'Pub League Admin', 'Admin']
    return any(role.name in admin_roles for role in user.roles)


def get_user_coach_teams(session, user_id: int) -> list:
    """Get list of team IDs where user is a coach."""
    player = session.query(Player).filter_by(user_id=user_id).first()
    if not player:
        return []

    coach_teams = session.execute(
        player_teams.select().where(
            and_(
                player_teams.c.player_id == player.id,
                player_teams.c.is_coach == True
            )
        )
    ).fetchall()

    return [row.team_id for row in coach_teams]


def is_in_substitute_pool(session, player_id: int, league_type: str = None) -> bool:
    """Check if player is in the substitute pool."""
    query = session.query(SubstitutePool).filter(
        SubstitutePool.player_id == player_id,
        SubstitutePool.is_active == True
    )

    if league_type:
        query = query.filter(SubstitutePool.league_type == league_type)

    return query.first() is not None


def get_player_from_user(session, user_id: int) -> Player:
    """Get Player object for a user."""
    return session.query(Player).filter_by(user_id=user_id).first()


def _resolve_profile_picture_url(player) -> str:
    """
    Resolve a Player's profile_picture_url to an absolute URL, matching the
    shape used by /players/search and /teams/{id}/players. Falls back to the
    default avatar when the player has no picture set.
    """
    base_url = request.host_url.rstrip('/')
    if not player or not getattr(player, 'profile_picture_url', None):
        return f"{base_url}/static/img/default_player.png"
    pic = player.profile_picture_url
    if pic.startswith('http'):
        return pic
    return f"{base_url}{pic}"


# ============================================================================
# Coach Endpoints - Manage Substitute Requests for Their Teams
# ============================================================================

@mobile_api_v2.route('/substitutes/requests', methods=['POST'])
@jwt_required()
def create_substitute_request():
    """
    Create a substitute request for a team's match.

    Expected JSON:
        match_id: ID of the match
        team_id: ID of the team needing substitutes
        positions_needed: Comma-separated positions (e.g., "GK, DEF")
        substitutes_needed: Number of substitutes needed (default: 1)
        gender_preference: "male", "female", or null (optional)
        notes: Additional notes (optional)

    Returns:
        JSON with created request details
    """
    current_user_id = int(get_jwt_identity())

    data = request.get_json()
    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    match_id = data.get('match_id')
    team_id = data.get('team_id')
    league_type = data.get('league_type', '')
    positions_needed = data.get('positions_needed', '')
    substitutes_needed = data.get('substitutes_needed', 1)
    gender_preference = data.get('gender_preference')
    notes = (data.get('notes') or '').strip()

    if not match_id or not team_id:
        return jsonify({"msg": "match_id and team_id are required"}), 400

    try:
        match_id = int(match_id)
        team_id = int(team_id)
    except (ValueError, TypeError):
        return jsonify({"msg": "match_id and team_id must be valid integers"}), 400

    try:
        substitutes_needed = int(substitutes_needed)
        if substitutes_needed < 1:
            substitutes_needed = 1
    except (ValueError, TypeError):
        substitutes_needed = 1

    with managed_session() as session:
        # Check authorization - must be coach for this team or admin
        if not is_coach_for_team(session, current_user_id, team_id) and not is_admin_user(session, current_user_id):
            return jsonify({"msg": "You are not authorized to create requests for this team"}), 403

        # Verify match exists
        match = session.query(Match).get(match_id)
        if not match:
            return jsonify({"msg": "Match not found"}), 404

        # Verify team is in this match
        if match.home_team_id != team_id and match.away_team_id != team_id:
            return jsonify({"msg": "Team is not participating in this match"}), 400

        # Check for existing open request
        existing = session.query(SubstituteRequest).filter(
            SubstituteRequest.match_id == match_id,
            SubstituteRequest.team_id == team_id,
            SubstituteRequest.status.in_(['OPEN', 'PENDING'])
        ).first()

        if existing:
            return jsonify({
                "msg": "An open substitute request already exists for this match/team",
                "existing_request_id": existing.id
            }), 400

        # Resolve league_type from team if not provided by client
        if not league_type:
            team_obj = session.query(Team).options(
                joinedload(Team.league)
            ).get(team_id)
            league_type = team_obj.league.name if team_obj and team_obj.league else 'Premier'

        # Create the request
        sub_request = SubstituteRequest(
            match_id=match_id,
            team_id=team_id,
            requested_by=current_user_id,
            league_type=league_type,
            positions_needed=positions_needed,
            substitutes_needed=substitutes_needed,
            gender_preference=gender_preference,
            notes=notes,
            status='OPEN',
            source='mobile'
        )

        session.add(sub_request)
        session.commit()

        logger.info(f"Substitute request created: {sub_request.id} by user {current_user_id}")

        return jsonify({
            "success": True,
            "message": "Substitute request created",
            "request": {
                "id": sub_request.id,
                "match_id": sub_request.match_id,
                "team_id": sub_request.team_id,
                "positions_needed": sub_request.positions_needed,
                "substitutes_needed": sub_request.substitutes_needed,
                "status": sub_request.status,
                "created_at": sub_request.created_at.isoformat() if sub_request.created_at else None
            }
        }), 201


@mobile_api_v2.route('/substitutes/requests/my-team', methods=['GET'])
@jwt_required()
def get_my_team_requests():
    """
    Get all substitute requests for teams where the user is a coach.

    Query Parameters:
        status: Filter by status (OPEN, PENDING, FILLED, CANCELLED)
        limit: Maximum number of requests (default: 20)

    Returns:
        JSON with list of substitute requests
    """
    current_user_id = int(get_jwt_identity())
    status_filter = request.args.get('status')
    limit = min(request.args.get('limit', 20, type=int), 100)

    with managed_session() as session:
        # Get teams where user is coach
        coach_team_ids = get_user_coach_teams(session, current_user_id)

        if not coach_team_ids:
            return jsonify({
                "requests": [],
                "count": 0,
                "message": "You are not a coach for any team"
            }), 200

        # Build query with eager loading for requester, assignments, and match teams
        query = session.query(SubstituteRequest).options(
            joinedload(SubstituteRequest.match).joinedload(Match.home_team),
            joinedload(SubstituteRequest.match).joinedload(Match.away_team),
            joinedload(SubstituteRequest.team),
            joinedload(SubstituteRequest.requester).joinedload(User.player),
            selectinload(SubstituteRequest.responses),
            selectinload(SubstituteRequest.assignments).joinedload(SubstituteAssignment.player)
        ).filter(
            SubstituteRequest.team_id.in_(coach_team_ids)
        )

        if status_filter:
            query = query.filter(SubstituteRequest.status == status_filter.upper())

        query = query.order_by(SubstituteRequest.created_at.desc()).limit(limit)
        requests = query.all()

        # Build response matching Flutter SubstituteRequest model
        requests_data = []
        for req in requests:
            requests_data.append({
                "id": req.id,
                "league_type": req.league_type or "",
                "match_id": req.match_id,
                "team_id": req.team_id,
                "requested_by": req.requested_by,
                "status": req.status,
                "substitutes_needed": req.substitutes_needed or 1,
                "positions_needed": req.positions_needed,
                "notes": req.notes,
                "created_at": req.created_at.isoformat() if req.created_at else None,
                "response_count": len(req.responses),
                "assignment_count": len(req.assignments),
                "match": {
                    "id": req.match.id,
                    "date": req.match.date.isoformat() if req.match.date else "",
                    "time": req.match.time.isoformat() if req.match.time else "",
                    "location": req.match.location or "",
                    "home_team_id": req.match.home_team_id,
                    "away_team_id": req.match.away_team_id,
                    "home_team_name": req.match.home_team.name if req.match.home_team else None,
                    "away_team_name": req.match.away_team.name if req.match.away_team else None,
                } if req.match else None,
                "team": {
                    "id": req.team.id,
                    "name": req.team.name
                } if req.team else None,
                "requester": {
                    "id": req.requester.id,
                    "username": req.requester.username,
                    "display_name": req.requester.player.name if req.requester.player else req.requester.username,
                } if req.requester else None,
                "assignments": [
                    {
                        "id": a.id,
                        "player_name": a.player.name if a.player else "Unknown",
                        "player_phone": a.player.phone if a.player else None,
                        "position_assigned": a.position_assigned,
                        "assigned_at": a.assigned_at.isoformat() if a.assigned_at else None,
                    } for a in req.assignments
                ],
            })

        return jsonify({
            "requests": requests_data,
            "count": len(requests_data)
        }), 200


@mobile_api_v2.route('/substitutes/requests/<int:request_id>', methods=['GET'])
@jwt_required()
def get_substitute_request(request_id: int):
    """
    Get details for a specific substitute request.

    Args:
        request_id: Substitute request ID

    Returns:
        JSON with full request details including responses
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        sub_request = session.query(SubstituteRequest).options(
            joinedload(SubstituteRequest.match).joinedload(Match.home_team),
            joinedload(SubstituteRequest.match).joinedload(Match.away_team),
            joinedload(SubstituteRequest.team),
            joinedload(SubstituteRequest.requester),
            selectinload(SubstituteRequest.responses).joinedload(SubstituteResponse.player),
            selectinload(SubstituteRequest.assignments).joinedload(SubstituteAssignment.player)
        ).get(request_id)

        if not sub_request:
            return jsonify({"msg": "Request not found"}), 404

        # Check authorization - must be coach for this team, admin, or in sub pool
        player = get_player_from_user(session, current_user_id)
        is_coach = is_coach_for_team(session, current_user_id, sub_request.team_id)
        is_admin = is_admin_user(session, current_user_id)
        in_pool = player and is_in_substitute_pool(session, player.id)

        if not (is_coach or is_admin or in_pool):
            return jsonify({"msg": "You are not authorized to view this request"}), 403

        # Build responses list (only for coach/admin)
        responses_data = []
        if is_coach or is_admin:
            for resp in sub_request.responses:
                responses_data.append({
                    "id": resp.id,
                    "player": {
                        "id": resp.player.id,
                        "name": resp.player.name
                    } if resp.player else None,
                    "is_available": resp.is_available,
                    "response_text": resp.response_text,
                    "responded_at": resp.responded_at.isoformat() if resp.responded_at else None
                })

        # Build assignments list
        assignments_data = []
        for assign in sub_request.assignments:
            assignments_data.append({
                "id": assign.id,
                "player": {
                    "id": assign.player.id,
                    "name": assign.player.name
                } if assign.player else None,
                "position_assigned": assign.position_assigned,
                "assigned_at": assign.assigned_at.isoformat() if assign.assigned_at else None
            })

        return jsonify({
            "request": {
                "id": sub_request.id,
                "match": {
                    "id": sub_request.match.id,
                    "date": sub_request.match.date.isoformat() if sub_request.match.date else None,
                    "time": sub_request.match.time.isoformat() if sub_request.match.time else None,
                    "location": sub_request.match.location,
                    "home_team": {
                        "id": sub_request.match.home_team.id,
                        "name": sub_request.match.home_team.name
                    } if sub_request.match.home_team else None,
                    "away_team": {
                        "id": sub_request.match.away_team.id,
                        "name": sub_request.match.away_team.name
                    } if sub_request.match.away_team else None
                } if sub_request.match else None,
                "team": {
                    "id": sub_request.team.id,
                    "name": sub_request.team.name
                } if sub_request.team else None,
                "requested_by": sub_request.requester.username if sub_request.requester else None,
                "positions_needed": sub_request.positions_needed,
                "substitutes_needed": sub_request.substitutes_needed,
                "gender_preference": sub_request.gender_preference,
                "notes": sub_request.notes,
                "status": sub_request.status,
                "created_at": sub_request.created_at.isoformat() if sub_request.created_at else None,
                "updated_at": sub_request.updated_at.isoformat() if sub_request.updated_at else None
            },
            "responses": responses_data,
            "assignments": assignments_data
        }), 200


@mobile_api_v2.route('/substitutes/requests/<int:request_id>', methods=['PUT'])
@jwt_required()
def update_substitute_request(request_id: int):
    """
    Update a substitute request.

    Args:
        request_id: Substitute request ID

    Expected JSON (all optional):
        positions_needed: Updated positions
        substitutes_needed: Updated count
        notes: Updated notes

    Returns:
        JSON with updated request details
    """
    current_user_id = int(get_jwt_identity())

    data = request.get_json()
    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    with managed_session() as session:
        sub_request = session.query(SubstituteRequest).get(request_id)

        if not sub_request:
            return jsonify({"msg": "Request not found"}), 404

        # Check authorization
        if not is_coach_for_team(session, current_user_id, sub_request.team_id) and not is_admin_user(session, current_user_id):
            return jsonify({"msg": "You are not authorized to update this request"}), 403

        # Can only update open/pending requests
        if sub_request.status not in ['OPEN', 'PENDING']:
            return jsonify({"msg": f"Cannot update request with status: {sub_request.status}"}), 400

        # Update fields
        if 'positions_needed' in data:
            sub_request.positions_needed = data['positions_needed']
        if 'substitutes_needed' in data:
            try:
                sub_request.substitutes_needed = max(1, int(data['substitutes_needed']))
            except (ValueError, TypeError):
                pass
        if 'notes' in data:
            sub_request.notes = data['notes'].strip()
        if 'gender_preference' in data:
            sub_request.gender_preference = data['gender_preference']

        session.commit()

        return jsonify({
            "success": True,
            "message": "Request updated",
            "request": {
                "id": sub_request.id,
                "positions_needed": sub_request.positions_needed,
                "substitutes_needed": sub_request.substitutes_needed,
                "notes": sub_request.notes,
                "status": sub_request.status
            }
        }), 200


@mobile_api_v2.route('/substitutes/requests/<int:request_id>', methods=['DELETE'])
@jwt_required()
def cancel_substitute_request(request_id: int):
    """
    Cancel a substitute request.

    Args:
        request_id: Substitute request ID

    Returns:
        JSON with success message
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        sub_request = session.query(SubstituteRequest).get(request_id)

        if not sub_request:
            return jsonify({"msg": "Request not found"}), 404

        # Check authorization
        if not is_coach_for_team(session, current_user_id, sub_request.team_id) and not is_admin_user(session, current_user_id):
            return jsonify({"msg": "You are not authorized to cancel this request"}), 403

        # Can only cancel open/pending requests
        if sub_request.status not in ['OPEN', 'PENDING']:
            return jsonify({"msg": f"Cannot cancel request with status: {sub_request.status}"}), 400

        sub_request.status = 'CANCELLED'
        session.commit()

        logger.info(f"Substitute request {request_id} cancelled by user {current_user_id}")

        return jsonify({
            "success": True,
            "message": "Request cancelled"
        }), 200


@mobile_api_v2.route('/substitutes/requests/<int:request_id>/responses', methods=['GET'])
@jwt_required()
def get_request_responses(request_id: int):
    """
    Get all responses for a substitute request.

    Args:
        request_id: Substitute request ID

    Returns:
        JSON with list of responses
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        sub_request = session.query(SubstituteRequest).get(request_id)

        if not sub_request:
            return jsonify({"msg": "Request not found"}), 404

        # Check authorization
        if not is_coach_for_team(session, current_user_id, sub_request.team_id) and not is_admin_user(session, current_user_id):
            return jsonify({"msg": "You are not authorized to view responses for this request"}), 403

        responses = session.query(SubstituteResponse).options(
            joinedload(SubstituteResponse.player)
        ).filter(
            SubstituteResponse.request_id == request_id
        ).order_by(SubstituteResponse.responded_at.desc()).all()

        responses_data = []
        for resp in responses:
            responses_data.append({
                "id": resp.id,
                "player": {
                    "id": resp.player.id,
                    "name": resp.player.name,
                    "position": label_for(resp.player.favorite_position)
                } if resp.player else None,
                "is_available": resp.is_available,
                "response_text": resp.response_text,
                "response_method": resp.response_method,
                "responded_at": resp.responded_at.isoformat() if resp.responded_at else None
            })

        return jsonify({
            "request_id": request_id,
            "responses": responses_data,
            "count": len(responses_data),
            "available_count": sum(1 for r in responses_data if r['is_available']),
            "unavailable_count": sum(1 for r in responses_data if not r['is_available'])
        }), 200


# ============================================================================
# Admin Endpoints - View All Requests, Assign Substitutes
# ============================================================================

@mobile_api_v2.route('/substitutes/requests', methods=['GET'])
@jwt_required()
@jwt_role_required(['Global Admin', 'Pub League Admin'])
def get_all_substitute_requests():
    """
    Get all substitute requests (admin only).

    Query Parameters:
        status: Filter by status (OPEN, FILLED, CANCELLED)
        match_id: Filter by match
        team_id: Filter by team
        limit: Maximum number of requests (default: 50)
        page: Page number (default: 1)

    Returns:
        JSON with list of all substitute requests
    """
    status_filter = request.args.get('status')
    match_id = request.args.get('match_id', type=int)
    team_id = request.args.get('team_id', type=int)
    limit = min(request.args.get('limit', 50, type=int), 100)
    page = request.args.get('page', 1, type=int)

    with managed_session() as session:
        query = session.query(SubstituteRequest).options(
            joinedload(SubstituteRequest.match),
            joinedload(SubstituteRequest.team),
            selectinload(SubstituteRequest.responses),
            selectinload(SubstituteRequest.assignments)
        )

        if status_filter:
            query = query.filter(SubstituteRequest.status == status_filter.upper())

        if match_id:
            query = query.filter(SubstituteRequest.match_id == match_id)

        if team_id:
            query = query.filter(SubstituteRequest.team_id == team_id)

        total = query.count()

        query = query.order_by(SubstituteRequest.created_at.desc())
        query = query.offset((page - 1) * limit).limit(limit)
        requests = query.all()

        # Response shape mirrors GET /substitutes/requests/my-team so Flutter
        # can deserialize both endpoints into the same SubstituteRequest model
        # without optional-field gymnastics.
        requests_data = []
        for req in requests:
            requests_data.append({
                "id": req.id,
                "league_type": req.league_type or "",
                "match_id": req.match_id,
                "team_id": req.team_id,
                "requested_by": req.requested_by,
                "status": req.status,
                "substitutes_needed": req.substitutes_needed or 1,
                "positions_needed": req.positions_needed,
                "gender_preference": req.gender_preference,
                "notes": req.notes,
                "filled_at": req.filled_at.isoformat() if req.filled_at else None,
                "cancelled_at": req.cancelled_at.isoformat() if req.cancelled_at else None,
                "created_at": req.created_at.isoformat() if req.created_at else None,
                "updated_at": req.updated_at.isoformat() if req.updated_at else None,
                "match": {
                    "id": req.match.id,
                    "date": req.match.date.isoformat() if req.match.date else None,
                    "time": req.match.time.isoformat() if req.match.time else None,
                } if req.match else None,
                "team": {
                    "id": req.team.id,
                    "name": req.team.name,
                } if req.team else None,
                "response_count": len(req.responses),
                "assignment_count": len(req.assignments),
            })

        return jsonify({
            "requests": requests_data,
            "total": total,
            "page": page,
            "per_page": limit,
            "total_pages": (total + limit - 1) // limit
        }), 200


@mobile_api_v2.route('/substitutes/requests/<int:request_id>/assign', methods=['POST'])
@jwt_required()
@jwt_role_required(['Global Admin', 'Pub League Admin', 'Pub League Coach'])
def assign_substitute(request_id: int):
    """
    Assign a substitute to a request. Admins can assign for any team;
    Pub League Coaches can assign only for their own team's requests.

    Args:
        request_id: Substitute request ID

    Expected JSON:
        player_id: ID of player to assign
        position_assigned: Position for the player (optional)
        notes: Assignment notes (optional)
        send_notification: Whether to send notification (default: true)

    Returns:
        JSON with assignment details
    """
    current_user_id = int(get_jwt_identity())

    data = request.get_json()
    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    player_id = data.get('player_id')
    position_assigned = data.get('position_assigned', '')
    notes = (data.get('notes') or '').strip()
    send_notification = data.get('send_notification', True)

    if not player_id:
        return jsonify({"msg": "player_id is required"}), 400

    with managed_session() as session:
        sub_request = session.query(SubstituteRequest).get(request_id)
        if not sub_request:
            return jsonify({"msg": "Request not found"}), 404

        if not (is_admin_user(session, current_user_id)
                or is_coach_for_team(session, current_user_id, sub_request.team_id)):
            return jsonify({"msg": "You can only assign subs for teams you coach"}), 403

        if sub_request.status not in ['OPEN', 'PENDING']:
            return jsonify({"msg": f"Cannot assign to request with status: {sub_request.status}"}), 400

        player = session.query(Player).get(player_id)
        if not player:
            return jsonify({"msg": "Player not found"}), 404

        # Check if player already assigned
        existing = session.query(SubstituteAssignment).filter(
            SubstituteAssignment.request_id == request_id,
            SubstituteAssignment.player_id == player_id
        ).first()

        if existing:
            return jsonify({"msg": "Player is already assigned to this request"}), 400

        # Create assignment
        assignment = SubstituteAssignment(
            request_id=request_id,
            player_id=player_id,
            assigned_by=current_user_id,
            position_assigned=position_assigned,
            notes=notes
        )

        session.add(assignment)

        # Check if request is now filled
        current_assignments = session.query(SubstituteAssignment).filter(
            SubstituteAssignment.request_id == request_id
        ).count()

        if current_assignments + 1 >= sub_request.substitutes_needed:
            sub_request.status = 'FILLED'
            sub_request.filled_at = datetime.utcnow()

        session.commit()

        logger.info(f"Substitute assigned: player {player_id} to request {request_id}")

        # Send notification to assigned sub if requested
        if send_notification:
            try:
                from app.services.substitute_notification_service import SubstituteNotificationService
                notification_service = SubstituteNotificationService()
                notification_service.send_confirmation(assignment.id)
            except Exception as e:
                logger.error(f"Failed to send assignment notification: {e}")

        return jsonify({
            "success": True,
            "message": f"{player.name} assigned as substitute",
            "assignment": {
                "id": assignment.id,
                "player_id": player_id,
                "player_name": player.name,
                "position_assigned": position_assigned,
                "assigned_at": assignment.assigned_at.isoformat() if assignment.assigned_at else None
            },
            "request_status": sub_request.status
        }), 201


@mobile_api_v2.route('/substitutes/assignments/<int:assignment_id>', methods=['DELETE'])
@jwt_required()
@jwt_role_required(['Global Admin', 'Pub League Admin'])
def remove_assignment(assignment_id: int):
    """
    Remove a substitute assignment (admin only).

    Args:
        assignment_id: Assignment ID

    Returns:
        JSON with success message
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        assignment = session.query(SubstituteAssignment).options(
            joinedload(SubstituteAssignment.request)
        ).get(assignment_id)

        if not assignment:
            return jsonify({"msg": "Assignment not found"}), 404

        request_id = assignment.request_id
        sub_request = assignment.request

        session.delete(assignment)

        # Reopen request if it was filled
        if sub_request and sub_request.status == 'FILLED':
            sub_request.status = 'OPEN'
            sub_request.filled_at = None

        session.commit()

        logger.info(f"Substitute assignment {assignment_id} removed by user {current_user_id}")

        return jsonify({
            "success": True,
            "message": "Assignment removed"
        }), 200


@mobile_api_v2.route('/substitutes/requests/<int:request_id>/notify-pool', methods=['POST'])
@mobile_api_v2.route('/substitutes/requests/<int:request_id>/contact', methods=['POST'])
@jwt_required()
@jwt_role_required(['Global Admin', 'Pub League Admin', 'Pub League Coach'])
def notify_substitute_pool(request_id: int):
    """
    Contact substitute pool members for a request. Admins can contact for
    any team; Pub League Coaches can only contact for their own team's
    requests.

    Reachable at both /notify-pool (legacy) and /contact (Flutter spec).
    Both paths share the same handler and identical body shape.

    Args:
        request_id: Substitute request ID

    Expected JSON:
        custom_message: Message to send to subs (required)
        channels: List of notification channels (optional, defaults to all)
                  Valid: "EMAIL", "SMS", "DISCORD", "PUSH"
        gender_filter: Filter by gender (optional, e.g. "male", "female")
        position_filters: Filter by positions (optional, e.g. ["GK", "DEF"])
        player_ids: Contact only specific players (optional, list of player IDs)
        subs_needed: Override number of subs needed (optional)

    Returns:
        JSON with notification results
    """
    current_user_id = int(get_jwt_identity())
    data = request.get_json()
    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    custom_message = (data.get('custom_message') or data.get('message') or '').strip()
    if not custom_message:
        return jsonify({"msg": "custom_message is required"}), 400

    with managed_session() as session:
        sub_request = session.query(SubstituteRequest).get(request_id)
        if not sub_request:
            return jsonify({"msg": "Request not found"}), 404

        if not (is_admin_user(session, current_user_id)
                or is_coach_for_team(session, current_user_id, sub_request.team_id)):
            return jsonify({"msg": "You can only contact subs for teams you coach"}), 403

        if sub_request.status not in ['OPEN', 'PENDING']:
            return jsonify({"msg": f"Cannot notify for request with status: {sub_request.status}"}), 400

    from app.services.substitute_notification_service import SubstituteNotificationService
    notification_service = SubstituteNotificationService()

    league_type = data.get('league_type', 'Premier')
    # subs_needed must default to None (not 1) — the service mutates
    # sub_request.substitutes_needed when this is truthy, so a missing
    # key shouldn't silently overwrite the request's stored count.
    result = notification_service.notify_pool(
        request_id=request_id,
        league_type=league_type,
        custom_message=custom_message,
        channels=data.get('channels'),
        gender_filter=data.get('gender_filter'),
        position_filters=data.get('position_filters'),
        player_ids=data.get('player_ids'),
        subs_needed=data.get('subs_needed')
    )

    status_code = 200 if result['success'] else 400
    return jsonify({
        "success": result['success'],
        "total_subs_in_pool": result['total_subs'],
        "notifications_sent": result['notifications_sent'],
        "responses_created": result['responses_created'],
        "errors": result['errors']
    }), status_code


@mobile_api_v2.route('/substitutes/requests/<int:request_id>/notify-individual', methods=['POST'])
@jwt_required()
@jwt_role_required(['Global Admin', 'Pub League Admin', 'Pub League Coach'])
def notify_individual_substitute(request_id: int):
    """
    Contact a specific substitute for a request. Admins can contact for any
    team; Pub League Coaches can only contact for their own team's requests.

    Args:
        request_id: Substitute request ID

    Expected JSON:
        player_id: Player ID to contact (required)
        custom_message: Message to send (required)
        channels: List of notification channels (optional, defaults to all)
                  Valid: "EMAIL", "SMS", "DISCORD", "PUSH"

    Returns:
        JSON with notification results
    """
    current_user_id = int(get_jwt_identity())
    data = request.get_json()
    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    player_id = data.get('player_id')
    custom_message = (data.get('custom_message') or data.get('message') or '').strip()

    if not player_id:
        return jsonify({"msg": "player_id is required"}), 400
    if not custom_message:
        return jsonify({"msg": "custom_message is required"}), 400

    with managed_session() as session:
        sub_request = session.query(SubstituteRequest).get(request_id)
        if not sub_request:
            return jsonify({"msg": "Request not found"}), 404

        if not (is_admin_user(session, current_user_id)
                or is_coach_for_team(session, current_user_id, sub_request.team_id)):
            return jsonify({"msg": "You can only contact subs for teams you coach"}), 403

        if sub_request.status not in ['OPEN', 'PENDING']:
            return jsonify({"msg": f"Cannot notify for request with status: {sub_request.status}"}), 400

    from app.services.substitute_notification_service import SubstituteNotificationService
    notification_service = SubstituteNotificationService()

    result = notification_service.notify_individual(
        player_id=player_id,
        request_id=request_id,
        custom_message=custom_message,
        channels=data.get('channels')
    )

    status_code = 200 if result['success'] else 400
    return jsonify({
        "success": result['success'],
        "channels_used": result['channels_used'],
        "response_id": result['response_id'],
        "errors": result['errors']
    }), status_code


@mobile_api_v2.route('/substitutes/pool', methods=['GET'])
@jwt_required()
@jwt_role_required(['Global Admin', 'Pub League Admin'])
def get_substitute_pool():
    """
    Get all players in the substitute pool (admin only).

    Query Parameters:
        league_type: Filter by league type
        active_only: If true, only return active members (default: true)

    Returns:
        JSON with list of pool members
    """
    league_type = request.args.get('league_type')
    active_only = request.args.get('active_only', 'true').lower() == 'true'

    with managed_session() as session:
        query = session.query(SubstitutePool).options(
            joinedload(SubstitutePool.player)
        )

        if league_type:
            query = query.filter(SubstitutePool.league_type == league_type)
        if active_only:
            query = query.filter(SubstitutePool.is_active == True)

        pool_members = query.order_by(SubstitutePool.joined_pool_at.desc()).all()

        members_data = []
        for member in pool_members:
            members_data.append({
                "id": member.id,
                "player_id": member.player.id if member.player else None,
                "player": {
                    "id": member.player.id,
                    "name": member.player.name,
                    "favorite_position": label_for(member.player.favorite_position),
                    "position": label_for(member.player.favorite_position),  # legacy alias
                    "profile_picture_url": _resolve_profile_picture_url(member.player),
                } if member.player else None,
                "league_type": member.league_type,
                "is_active": member.is_active,
                "is_approved": member.approved_at is not None,
                "approved_at": member.approved_at.isoformat() if member.approved_at else None,
                "preferred_positions": member.preferred_positions,
                "requests_received": member.requests_received,
                "requests_accepted": member.requests_accepted,
                "matches_played": member.matches_played,
                "joined_pool_at": member.joined_pool_at.isoformat() if member.joined_pool_at else None
            })

        return jsonify({
            "pool_members": members_data,
            "count": len(members_data)
        }), 200


# ============================================================================
# Admin Endpoints - Discord Native Poll Posting
# ============================================================================

def _validate_emoji(value):
    """
    Return (ok, normalized_or_None). An emoji is valid if it is None/empty
    (treated as no emoji) or exactly one Unicode codepoint after stripping
    the variation selector-16 (U+FE0F) that often follows emoji in JSON.
    """
    if value is None or value == "":
        return True, None
    if not isinstance(value, str):
        return False, None
    stripped = value.replace("️", "")
    if len(stripped) == 1:
        return True, stripped
    return False, None


@mobile_api_v2.route('/substitutes/discord/availability-poll', methods=['POST'])
@jwt_required()
@api_key_required
@jwt_role_required(['Global Admin', 'Pub League Admin'])
def post_discord_availability_poll():
    """
    Post a native Discord poll to a configured channel and ping the
    associated substitute roles. Pub League Admin / Global Admin only.
    """
    current_user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}

    # --- Validation ---
    channel_key = data.get('channel_key')
    if channel_key not in DISCORD_POLL_CHANNELS:
        allowed = ', '.join(sorted(DISCORD_POLL_CHANNELS.keys()))
        return jsonify({"msg": f"channel_key must be one of: {allowed}"}), 400

    match_date_raw = data.get('match_date')
    if not isinstance(match_date_raw, str):
        return jsonify({"msg": "match_date must be ISO format YYYY-MM-DD"}), 400
    try:
        match_date_dt = datetime.strptime(match_date_raw, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({"msg": "match_date must be ISO format YYYY-MM-DD"}), 400
    today_local = datetime.now(Config.TIMEZONE).date()
    if match_date_dt < today_local:
        return jsonify({"msg": "match_date must be today or later"}), 400

    title = data.get('title')
    if not isinstance(title, str) or not title.strip():
        return jsonify({"msg": "title is required"}), 400
    title = title.strip()
    if len(title) > 300:
        return jsonify({"msg": "title must be 1-300 characters"}), 400

    options = data.get('options')
    if not isinstance(options, list) or len(options) < 2 or len(options) > 10:
        return jsonify({"msg": "options must contain 2-10 entries"}), 400

    normalized_options = []
    for i, opt in enumerate(options):
        if not isinstance(opt, dict):
            return jsonify({"msg": f"option[{i}].text must be 1-55 characters"}), 400
        opt_text = opt.get('text')
        if not isinstance(opt_text, str):
            return jsonify({"msg": f"option[{i}].text must be 1-55 characters"}), 400
        opt_text = opt_text.strip()
        if len(opt_text) < 1 or len(opt_text) > 55:
            return jsonify({"msg": f"option[{i}].text must be 1-55 characters"}), 400
        ok, normalized_emoji = _validate_emoji(opt.get('emoji'))
        if not ok:
            return jsonify({"msg": f"option[{i}].emoji must be a single character"}), 400
        normalized_options.append({"text": opt_text, "emoji": normalized_emoji})

    duration_hours = data.get('duration_hours')
    if not isinstance(duration_hours, int) or isinstance(duration_hours, bool) \
            or duration_hours < 1 or duration_hours > 168:
        return jsonify({"msg": "duration_hours must be an integer 1-168"}), 400

    allow_multiselect = data.get('allow_multiselect')
    if not isinstance(allow_multiselect, bool):
        return jsonify({"msg": "allow_multiselect must be boolean"}), 400

    # --- Resolve channel ID (env override, otherwise hardcoded default) ---
    cfg = DISCORD_POLL_CHANNELS[channel_key]
    channel_id = os.getenv(cfg['channel_env_var']) or cfg.get('channel_id_default')
    if not channel_id:
        logger.error(
            "No channel ID for %s (env %s unset and no default)",
            channel_key, cfg['channel_env_var'],
        )
        return jsonify({"msg": "Discord channel not configured"}), 500

    # --- Resolve role mention IDs from DB ---
    session = getattr(g, 'db_session', None)
    tag_role_ids = []
    try:
        if session is None:
            logger.error("No DB session available for role lookup")
            return jsonify({"msg": "Internal error posting poll"}), 500
        role_rows = session.query(Role).filter(
            Role.name.in_(cfg['tag_role_names'])
        ).all()
        found_names = {r.name for r in role_rows}
        for r in role_rows:
            if r.discord_role_id:
                tag_role_ids.append(str(r.discord_role_id))
        missing = [n for n in cfg['tag_role_names'] if n not in found_names]
        without_id = [r.name for r in role_rows if not r.discord_role_id]
        if missing:
            logger.warning("Mention roles missing from DB: %s", missing)
        if without_id:
            logger.warning("Mention roles without discord_role_id: %s", without_id)
        if not tag_role_ids:
            return jsonify({"msg": "No mention roles configured"}), 500
    except Exception:
        logger.exception("Error resolving mention role IDs")
        return jsonify({"msg": "Internal error posting poll"}), 500

    # --- Call bot ---
    bot_payload = {
        "channel_id": str(channel_id),
        "tag_role_ids": tag_role_ids,
        "question": title,
        "answers": normalized_options,
        "duration_hours": duration_hours,
        "allow_multiselect": allow_multiselect,
    }

    bot_url = f"{Config.BOT_API_URL.rstrip('/')}/api/discord/post-poll"
    try:
        resp = requests.post(bot_url, json=bot_payload, timeout=15)
    except (requests.ConnectionError, requests.Timeout):
        logger.exception("Discord bot unreachable at %s", bot_url)
        return jsonify({"msg": "Discord bot unreachable"}), 502
    except requests.RequestException:
        logger.exception("Error calling Discord bot at %s", bot_url)
        return jsonify({"msg": "Discord bot unreachable"}), 502

    if resp.status_code >= 400:
        try:
            err_body = resp.json()
            detail = err_body.get('detail') or err_body.get('msg') or resp.text[:200]
        except ValueError:
            detail = resp.text[:200] if resp.text else f"status {resp.status_code}"
        logger.warning("Bot rejected poll (status=%s): %s", resp.status_code, detail)
        return jsonify({"msg": f"Discord rejected poll: {detail}"}), 502

    try:
        bot_resp = resp.json()
    except ValueError:
        logger.error("Bot returned non-JSON success body: %s", resp.text[:200])
        return jsonify({"msg": "Internal error posting poll"}), 500

    if not bot_resp.get('success'):
        detail = bot_resp.get('detail') or bot_resp.get('msg') or 'unknown error'
        return jsonify({"msg": f"Discord rejected poll: {detail}"}), 502

    discord_message_id = str(bot_resp.get('message_id', ''))
    bot_channel_id = str(bot_resp.get('channel_id', channel_id))
    channel_name = bot_resp.get('channel_name', '')
    guild_id = bot_resp.get('guild_id') or None
    expires_at = bot_resp.get('expires_at', '')
    message_url = bot_resp.get('message_url', '')
    bot_answers = bot_resp.get('answers') or [
        {"answer_id": i + 1, "text": o['text'], "emoji": o.get('emoji')}
        for i, o in enumerate(normalized_options)
    ]

    # --- Persist DiscordPoll row so we can later track votes ---
    try:
        expires_dt = None
        if expires_at:
            try:
                expires_dt = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                if expires_dt.tzinfo is not None:
                    expires_dt = expires_dt.astimezone(tz=None).replace(tzinfo=None)
            except (ValueError, TypeError):
                expires_dt = None
        if expires_dt is None:
            from datetime import timedelta as _td
            expires_dt = datetime.utcnow() + _td(hours=duration_hours)

        poll_row = DiscordPoll(
            discord_message_id=discord_message_id,
            channel_id=bot_channel_id,
            channel_key=channel_key,
            guild_id=guild_id,
            title=title,
            match_date=match_date_dt,
            options=bot_answers,
            duration_hours=duration_hours,
            allow_multiselect=allow_multiselect,
            created_by_user_id=current_user_id,
            expires_at=expires_dt,
            discord_message_url=message_url,
        )
        session.add(poll_row)
        session.flush()
    except Exception:
        logger.exception("Failed to persist DiscordPoll row")
        # Don't fail the whole request — the poll is already live in Discord.
        # Vote tracking just won't work for this poll until manually backfilled.

    # --- Audit log ---
    try:
        AdminAuditLog.log_action(
            user_id=current_user_id,
            action='discord_poll_posted',
            resource_type='discord_poll',
            resource_id=discord_message_id,
            new_value=json.dumps({
                'channel_key': channel_key,
                'channel_id': bot_channel_id,
                'title': title,
                'options_count': len(normalized_options),
                'duration_hours': duration_hours,
                'allow_multiselect': allow_multiselect,
                'expires_at': expires_at,
                'discord_message_url': message_url,
            }),
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent'),
            deferred=True,
        )
    except Exception:
        logger.exception("Failed to write discord_poll_posted audit log")

    return jsonify({
        "success": True,
        "discord_message_id": discord_message_id,
        "channel_id": bot_channel_id,
        "channel_name": channel_name,
        "expires_at": expires_at,
        "discord_message_url": message_url,
    }), 200


# ============================================================================
# Internal Endpoints - Discord /subs bot command (X-Bot-Token trust boundary)
#
# These mirror the existing /internal/discord-poll-vote pattern: the bot
# authenticates with the shared FLASK_TOKEN secret (X-Bot-Token header), and
# every authorization decision is re-run server-side against the resolved human
# coach. The bot never holds a per-user JWT; Flask stays the single source of
# truth. Phase 1 is Pub League only (Premier/Classic) — ECS FC is deferred
# until its backend converges, so coach resolution filters to the current
# 'Pub League' season.
# ============================================================================

def _bot_token_ok() -> bool:
    """True if the request carries the shared bot secret (FLASK_TOKEN)."""
    expected = os.getenv('FLASK_TOKEN')
    token = request.headers.get('X-Bot-Token', '')
    return bool(expected) and bool(token) and token == expected


def _board_url():
    """Public URL of the substitute board (admin-gated; non-admins are denied)."""
    base = (getattr(Config, 'WEBUI_BASE_URL', '') or '').rstrip('/')
    return f"{base}/admin-panel/substitute-management" if base else None


def _current_pub_league_coach_teams(session, player):
    """
    Teams the player coaches THIS season in Pub League only.

    get_coach_teams() is season-agnostic (player_teams has no season), so we
    filter to teams whose league belongs to the current 'Pub League' season.
    This drops stale prior-season coaching rows and excludes ECS FC.
    """
    from app.mobile_api.coach_rsvp import get_coach_teams
    teams = get_coach_teams(session, player.user_id)
    scoped = []
    for team in teams:
        league = getattr(team, 'league', None)
        season = getattr(league, 'season', None) if league else None
        if not season or not season.is_current:
            continue
        if season.league_type != 'Pub League':
            continue
        scoped.append(team)
    return scoped


@mobile_api_v2.route('/internal/subs/coach-context', methods=['GET'])
def internal_subs_coach_context():
    """
    Resolve a Discord user to the Pub League teams they coach this season.

    Auth: X-Bot-Token == FLASK_TOKEN.
    Query: discord_id
    Returns: {linked: bool, teams: [{team_id, team_name, league_name}]}
        linked=False means no Player is linked to that Discord account, so the
        bot should tell the user to link their portal account rather than fail
        silently.
    """
    if not _bot_token_ok():
        return jsonify({"msg": "unauthorized"}), 401

    discord_id = str(request.args.get('discord_id') or '').strip()
    if not discord_id:
        return jsonify({"msg": "discord_id required"}), 400

    with managed_session() as session:
        player = session.query(Player).filter_by(discord_id=discord_id).first()
        if not player:
            return jsonify({"linked": False, "teams": []}), 200

        teams = _current_pub_league_coach_teams(session, player)
        return jsonify({
            "linked": True,
            "user_id": player.user_id,
            "player_name": player.name,
            "teams": [
                {
                    "team_id": t.id,
                    "team_name": t.name,
                    "league_name": t.league.name if t.league else None,
                }
                for t in teams
            ],
        }), 200


@mobile_api_v2.route('/internal/subs/upcoming', methods=['GET'])
def internal_subs_upcoming():
    """
    Upcoming matches for a team (for the /subs match picker).

    Auth: X-Bot-Token == FLASK_TOKEN.
    Query: team_id
    Returns: {matches: [{match_id, date, time, opponent_name, is_home, location}]}
    """
    if not _bot_token_ok():
        return jsonify({"msg": "unauthorized"}), 401

    try:
        team_id = int(request.args.get('team_id'))
    except (TypeError, ValueError):
        return jsonify({"msg": "team_id must be a valid integer"}), 400

    with managed_session() as session:
        matches = session.query(Match).filter(
            ((Match.home_team_id == team_id) | (Match.away_team_id == team_id)) &
            (Match.date >= pacific_today()) &
            (Match.week_type == 'REGULAR') &
            (Match.home_team_id != Match.away_team_id)  # exclude BYE/special self-match rows
        ).order_by(Match.date, Match.time).limit(10).all()

        # Resolve opponent names in one pass
        opponent_ids = {
            (m.away_team_id if m.home_team_id == team_id else m.home_team_id)
            for m in matches
        }
        name_by_id = {}
        if opponent_ids:
            for t in session.query(Team).filter(Team.id.in_(opponent_ids)).all():
                name_by_id[t.id] = t.name

        out = []
        for m in matches:
            is_home = (m.home_team_id == team_id)
            opp_id = m.away_team_id if is_home else m.home_team_id
            out.append({
                "match_id": m.id,
                "date": m.date.isoformat() if m.date else None,
                "time": m.time.strftime('%H:%M') if m.time else None,
                "opponent_name": name_by_id.get(opp_id, 'TBD'),
                "is_home": is_home,
                "location": m.location,
            })

        return jsonify({"matches": out}), 200


@mobile_api_v2.route('/internal/subs/requests', methods=['POST'])
def internal_create_subs_request():
    """
    Create a substitute request on behalf of a coach from the Discord bot.

    Auth: X-Bot-Token == FLASK_TOKEN. Authorization is re-run here:
    acting_coach_user_id MUST be a coach for team_id (we do NOT accept admins
    on this path — the point is honest attribution of the human coach).

    Body: {
        acting_coach_user_id, team_id, match_id,
        substitutes_needed?, positions_needed?, notes?, gender_preference?,
        discord_channel_id?, discord_message_id?
    }

    Idempotent: an existing OPEN/PENDING request for the same (match, team)
    returns 200 with duplicate=True so the bot reports "already logged" on a
    retry instead of surfacing an error.
    """
    if not _bot_token_ok():
        return jsonify({"msg": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    try:
        acting_user_id = int(data.get('acting_coach_user_id'))
        team_id = int(data.get('team_id'))
        match_id = int(data.get('match_id'))
    except (TypeError, ValueError):
        return jsonify({"msg": "acting_coach_user_id, team_id and match_id are required integers"}), 400

    try:
        # Clamp to a sane range — the Discord modal is free text, so "99" is
        # possible input but never a real ask (a full side is ~11).
        substitutes_needed = max(1, min(int(data.get('substitutes_needed', 1)), 10))
    except (TypeError, ValueError):
        substitutes_needed = 1

    positions_needed = (data.get('positions_needed') or '').strip()
    notes = (data.get('notes') or '').strip()
    gender_preference = data.get('gender_preference')
    discord_channel_id = (str(data.get('discord_channel_id') or '').strip() or None)
    discord_message_id = (str(data.get('discord_message_id') or '').strip() or None)

    with managed_session() as session:
        # Re-run authorization server-side against the resolved coach.
        if not is_coach_for_team(session, acting_user_id, team_id):
            return jsonify({"msg": "Acting user is not a coach for this team"}), 403

        match = session.query(Match).get(match_id)
        if not match:
            return jsonify({"msg": "Match not found"}), 404
        if match.home_team_id != team_id and match.away_team_id != team_id:
            return jsonify({"msg": "Team is not participating in this match"}), 400

        existing = session.query(SubstituteRequest).filter(
            SubstituteRequest.match_id == match_id,
            SubstituteRequest.team_id == team_id,
            SubstituteRequest.status.in_(['OPEN', 'PENDING'])
        ).first()
        if existing:
            return jsonify({
                "success": True,
                "duplicate": True,
                "message": "An open request already exists for this match/team",
                "request": {"id": existing.id, "status": existing.status},
                "board_url": _board_url(),
            }), 200

        team_obj = session.query(Team).options(joinedload(Team.league)).get(team_id)
        league_type = team_obj.league.name if team_obj and team_obj.league else 'Premier'

        sub_request = SubstituteRequest(
            match_id=match_id,
            team_id=team_id,
            requested_by=acting_user_id,
            league_type=league_type,
            positions_needed=positions_needed,
            substitutes_needed=substitutes_needed,
            gender_preference=gender_preference,
            notes=notes,
            status='OPEN',
            source='discord',
            discord_channel_id=discord_channel_id,
            discord_message_id=discord_message_id,
        )
        session.add(sub_request)
        try:
            session.commit()
        except IntegrityError:
            # Two near-simultaneous submissions raced past the existence check
            # (e.g. coach double-submits the modal). Treat the loser like the
            # normal duplicate path instead of surfacing a 500.
            session.rollback()
            existing = session.query(SubstituteRequest).filter(
                SubstituteRequest.match_id == match_id,
                SubstituteRequest.team_id == team_id,
                SubstituteRequest.status.in_(['OPEN', 'PENDING'])
            ).first()
            return jsonify({
                "success": True,
                "duplicate": True,
                "message": "An open request already exists for this match/team",
                "request": {"id": existing.id, "status": existing.status} if existing else None,
                "board_url": _board_url(),
            }), 200

        logger.info(
            f"Substitute request created via Discord: {sub_request.id} "
            f"(team={team_id}, match={match_id}, coach_user={acting_user_id})"
        )

        return jsonify({
            "success": True,
            "duplicate": False,
            "message": "Substitute request created",
            "request": {
                "id": sub_request.id,
                "match_id": sub_request.match_id,
                "team_id": sub_request.team_id,
                "league_type": sub_request.league_type,
                "substitutes_needed": sub_request.substitutes_needed,
                "status": sub_request.status,
            },
            "board_url": _board_url(),
        }), 201


def _format_slot_label(t) -> str:
    """A time object -> '8:20am'."""
    h = t.hour
    ampm = 'am' if h < 12 else 'pm'
    h12 = h % 12 or 12
    return f"{h12}:{t.minute:02d}{ampm}"


def _upcoming_sunday(today):
    """The next Sunday on/after `today` (today if it is already Sunday)."""
    from datetime import timedelta
    return today + timedelta(days=(6 - today.weekday()) % 7)


def _build_availability_buckets(session, target_date):
    """
    Group the current-season Pub League matches on `target_date` into
    availability buckets — one option per league, split into early/late halves
    when a league has more than two distinct kickoff times.

    Returns (buckets, season). Each bucket is:
        {label, league_type, slots: ['HH:MM', ...], match_ids: [int, ...]}
    Because each bucket carries the real match_ids, reconciliation later is an
    exact join (no time-string tolerance matching needed).
    """
    from collections import defaultdict
    from app.models.core import Season

    season = session.query(Season).filter_by(
        league_type='Pub League', is_current=True
    ).first()

    matches = session.query(Match).filter(
        Match.date == target_date,
        Match.week_type == 'REGULAR',
        Match.home_team_id != Match.away_team_id,  # exclude BYE/special self-match rows
    ).all()
    by_league = defaultdict(list)
    for m in matches:
        home = m.home_team
        league = home.league if home else None
        if not league or not league.season:
            continue
        if league.season.league_type != 'Pub League' or not league.season.is_current:
            continue
        if m.time is None:
            continue
        by_league[league.name].append(m)

    buckets = []
    for league_name in sorted(by_league.keys()):
        ms = by_league[league_name]
        times = sorted({m.time for m in ms})
        if len(times) <= 2:
            groups = [times]
        else:
            mid = len(times) // 2
            groups = [times[:mid], times[mid:]]
        multi = len(groups) > 1
        for gi, group in enumerate(groups):
            tset = set(group)
            match_ids = sorted(m.id for m in ms if m.time in tset)
            slots = [t.strftime('%H:%M') for t in group]
            human = ' & '.join(_format_slot_label(t) for t in group)
            if multi:
                label = f"{league_name} {'early' if gi == 0 else 'late'} ({human})"
            else:
                label = f"{league_name} ({human})"
            buckets.append({
                'label': label[:55],
                'league_type': league_name,
                'slots': slots,
                'match_ids': match_ids,
            })
    return buckets, season


@mobile_api_v2.route('/internal/subs/poll', methods=['POST'])
def internal_create_subs_poll():
    """
    Post a schedule-generated availability poll to #pl-subs from the bot.

    Auth: X-Bot-Token. The acting user is resolved from discord_id and must
    hold an admin role server-side (same gate as the WebUI poll endpoint).
    The poll options are BUILT FROM the schedule for the target Sunday, so each
    answer maps to real match_ids (persisted in DiscordPoll.slot_map), making
    the later reconcile step an exact join instead of fuzzy time matching.

    Body: {discord_id, match_date?, channel_key?='pl_subs', duration_hours?}
    """
    if not _bot_token_ok():
        return jsonify({"msg": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    discord_id = str(data.get('discord_id') or '').strip()
    if not discord_id:
        return jsonify({"msg": "discord_id required"}), 400

    channel_key = data.get('channel_key', 'pl_subs')
    if channel_key not in DISCORD_POLL_CHANNELS:
        allowed = ', '.join(sorted(DISCORD_POLL_CHANNELS.keys()))
        return jsonify({"msg": f"channel_key must be one of: {allowed}"}), 400

    with managed_session() as session:
        player = session.query(Player).filter_by(discord_id=discord_id).first()
        if not player:
            return jsonify({"success": False, "reason": "not_linked"}), 200
        user_id = player.user_id
        if not is_admin_user(session, user_id):
            return jsonify({"success": False, "reason": "not_authorized"}), 200

        # Resolve target date (default: the upcoming Sunday)
        match_date_raw = data.get('match_date')
        if match_date_raw:
            try:
                target_date = datetime.strptime(str(match_date_raw), '%Y-%m-%d').date()
            except ValueError:
                return jsonify({"msg": "match_date must be ISO format YYYY-MM-DD"}), 400
        else:
            target_date = _upcoming_sunday(pacific_today())

        # Idempotency: one live availability poll per Sunday. A retry after a
        # timed-out first attempt (or two admins racing) must not post a second
        # real poll to #pl-subs. Expired polls don't block a re-post.
        existing_poll = session.query(DiscordPoll).filter(
            DiscordPoll.poll_kind == 'availability',
            DiscordPoll.match_date == target_date,
            DiscordPoll.expires_at > datetime.utcnow(),
        ).order_by(DiscordPoll.created_at.desc()).first()
        if existing_poll:
            return jsonify({
                "success": False,
                "reason": "duplicate",
                "match_date": target_date.isoformat(),
                "discord_message_url": existing_poll.discord_message_url,
            }), 200

        buckets, season = _build_availability_buckets(session, target_date)
        if not buckets:
            return jsonify({
                "success": False,
                "reason": "no_matches",
                "match_date": target_date.isoformat(),
            }), 200
        buckets = buckets[:10]  # Discord poll cap

        normalized_options = [{"text": b['label'], "emoji": None} for b in buckets]
        title = (
            f"Sub availability for Sunday {target_date.strftime('%b %d')} — "
            f"which slot(s) can you play?"
        )[:300]

        # Duration: from now through end of the target day, clamped 1..168h.
        # Both sides Pacific-aware — naive datetime.now() is UTC in the
        # containers, which would close the poll hours before Sunday ends.
        from datetime import timedelta as _td
        hours_until = int((pacific_datetime(target_date, datetime.max.time())
                           - pacific_now()).total_seconds() // 3600)
        duration_hours = data.get('duration_hours')
        if not isinstance(duration_hours, int) or isinstance(duration_hours, bool):
            duration_hours = hours_until
        duration_hours = max(1, min(duration_hours, 168))

        # --- Resolve channel + mention roles (same registry as the web path) ---
        cfg = DISCORD_POLL_CHANNELS[channel_key]
        channel_id = os.getenv(cfg['channel_env_var']) or cfg.get('channel_id_default')
        if not channel_id:
            return jsonify({"msg": "Discord channel not configured"}), 500
        role_rows = session.query(Role).filter(Role.name.in_(cfg['tag_role_names'])).all()
        tag_role_ids = [str(r.discord_role_id) for r in role_rows if r.discord_role_id]
        if not tag_role_ids:
            found_names = {r.name for r in role_rows if r.discord_role_id}
            missing = [n for n in cfg['tag_role_names'] if n not in found_names]
            return jsonify({
                "msg": f"Mention roles missing or lacking a discord_role_id: {', '.join(missing)}"
            }), 500

        # --- Call the bot to post the native poll ---
        bot_payload = {
            "channel_id": str(channel_id),
            "tag_role_ids": tag_role_ids,
            "question": title,
            "answers": normalized_options,
            "duration_hours": duration_hours,
            "allow_multiselect": True,
        }
        bot_url = f"{Config.BOT_API_URL.rstrip('/')}/api/discord/post-poll"
        try:
            resp = requests.post(bot_url, json=bot_payload, timeout=15)
        except requests.RequestException:
            logger.exception("Discord bot unreachable at %s", bot_url)
            return jsonify({"msg": "Discord bot unreachable"}), 502
        if resp.status_code >= 400:
            try:
                detail = resp.json().get('detail') or resp.text[:200]
            except ValueError:
                detail = resp.text[:200] if resp.text else f"status {resp.status_code}"
            return jsonify({"msg": f"Discord rejected poll: {detail}"}), 502
        try:
            bot_resp = resp.json()
        except ValueError:
            return jsonify({"msg": "Internal error posting poll"}), 500
        if not bot_resp.get('success'):
            return jsonify({"msg": "Discord rejected poll"}), 502

        discord_message_id = str(bot_resp.get('message_id', ''))
        bot_channel_id = str(bot_resp.get('channel_id', channel_id))
        guild_id = bot_resp.get('guild_id') or None
        message_url = bot_resp.get('message_url', '')
        bot_answers = bot_resp.get('answers') or [
            {"answer_id": i + 1, "text": o['text'], "emoji": o.get('emoji')}
            for i, o in enumerate(normalized_options)
        ]

        # slot_map: answer_id (as STRING key) -> bucket meaning. Bot assigns
        # answer_ids in option order starting at 1, so bucket index = id - 1.
        slot_map = {}
        for ans in bot_answers:
            aid = int(ans['answer_id'])
            if 1 <= aid <= len(buckets):
                slot_map[str(aid)] = buckets[aid - 1]

        expires_dt = bot_resp.get('expires_at', '')
        try:
            expires_parsed = datetime.fromisoformat(expires_dt.replace('Z', '+00:00')) if expires_dt else None
            if expires_parsed is not None and expires_parsed.tzinfo is not None:
                expires_parsed = expires_parsed.astimezone(tz=None).replace(tzinfo=None)
        except (ValueError, TypeError, AttributeError):
            expires_parsed = None
        if expires_parsed is None:
            expires_parsed = datetime.utcnow() + _td(hours=duration_hours)

        try:
            poll_row = DiscordPoll(
                discord_message_id=discord_message_id,
                channel_id=bot_channel_id,
                channel_key=channel_key,
                guild_id=guild_id,
                title=title,
                match_date=target_date,
                options=bot_answers,
                poll_kind='availability',
                season_id=season.id if season else None,
                slot_map=slot_map,
                duration_hours=duration_hours,
                allow_multiselect=True,
                created_by_user_id=user_id,
                expires_at=expires_parsed,
                discord_message_url=message_url,
            )
            session.add(poll_row)
            session.commit()
        except Exception:
            logger.exception("Failed to persist availability DiscordPoll row")

        try:
            AdminAuditLog.log_action(
                user_id=user_id,
                action='discord_poll_posted',
                resource_type='discord_poll',
                resource_id=discord_message_id,
                new_value=json.dumps({
                    'channel_key': channel_key,
                    'poll_kind': 'availability',
                    'match_date': target_date.isoformat(),
                    'buckets': [b['label'] for b in buckets],
                    'source': 'discord_subs_command',
                }),
                deferred=True,
            )
        except Exception:
            logger.exception("Failed to write discord_poll_posted audit log")

        return jsonify({
            "success": True,
            "discord_message_id": discord_message_id,
            "discord_message_url": message_url,
            "match_date": target_date.isoformat(),
            "buckets": [b['label'] for b in buckets],
        }), 200


# ============================================================================
# Internal Endpoint - Bot pushes poll vote events here
# ============================================================================

@mobile_api_v2.route('/internal/discord-poll-vote', methods=['POST'])
def receive_discord_poll_vote():
    """
    Receive a poll vote add/remove event from the Discord bot.

    Auth: shared secret in X-Bot-Token header (must match FLASK_TOKEN env var,
    which is the same value the bot reads from its own .env).

    Body: {
        discord_message_id, discord_user_id, answer_id,
        action: "add"|"remove", channel_id?, guild_id?
    }

    Polls not previously persisted (i.e. polls created outside this system)
    are silently ignored — the bot fires events for every poll in the guild.
    """
    expected = os.getenv('FLASK_TOKEN')
    token = request.headers.get('X-Bot-Token', '')
    if not expected or not token or token != expected:
        return jsonify({"msg": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    discord_message_id = str(data.get('discord_message_id') or '').strip()
    discord_user_id = str(data.get('discord_user_id') or '').strip()
    answer_id_raw = data.get('answer_id')
    action = data.get('action')

    if not discord_message_id or not discord_user_id:
        return jsonify({"msg": "discord_message_id and discord_user_id required"}), 400
    try:
        answer_id = int(answer_id_raw)
    except (TypeError, ValueError):
        return jsonify({"msg": "answer_id must be an integer"}), 400
    if action not in ('add', 'remove'):
        return jsonify({"msg": "action must be 'add' or 'remove'"}), 400

    session = getattr(g, 'db_session', None)
    if session is None:
        return jsonify({"msg": "Database session not available"}), 500

    poll = session.query(DiscordPoll).filter_by(
        discord_message_id=discord_message_id
    ).first()
    if poll is None:
        # Untracked poll — ignore silently. Bot fires for every poll.
        return jsonify({"success": True, "tracked": False}), 200

    if action == 'add':
        existing = session.query(DiscordPollVote).filter(
            DiscordPollVote.poll_id == poll.id,
            DiscordPollVote.discord_user_id == discord_user_id,
            DiscordPollVote.answer_id == answer_id,
            DiscordPollVote.removed_at.is_(None),
        ).first()
        if existing:
            return jsonify({"success": True, "tracked": True, "noop": True}), 200
        vote = DiscordPollVote(
            poll_id=poll.id,
            discord_user_id=discord_user_id,
            answer_id=answer_id,
            voted_at=datetime.utcnow(),
        )
        session.add(vote)
    else:  # remove
        existing = session.query(DiscordPollVote).filter(
            DiscordPollVote.poll_id == poll.id,
            DiscordPollVote.discord_user_id == discord_user_id,
            DiscordPollVote.answer_id == answer_id,
            DiscordPollVote.removed_at.is_(None),
        ).order_by(DiscordPollVote.voted_at.desc()).first()
        if existing:
            existing.removed_at = datetime.utcnow()

    return jsonify({"success": True, "tracked": True}), 200


# ============================================================================
# Read Endpoints - View poll responses (admin only)
# ============================================================================

def _build_options_lookup(options):
    """Return {answer_id: {text, emoji}} from a poll's options jsonb."""
    out = {}
    for o in (options or []):
        try:
            out[int(o['answer_id'])] = {
                'text': o.get('text', ''),
                'emoji': o.get('emoji'),
            }
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _serialize_poll_summary(poll, vote_count_by_answer):
    """Serialize a DiscordPoll with per-answer tallies (no responders)."""
    options_out = []
    for o in (poll.options or []):
        ans_id = o.get('answer_id')
        options_out.append({
            'answer_id': ans_id,
            'text': o.get('text', ''),
            'emoji': o.get('emoji'),
            'vote_count': vote_count_by_answer.get(ans_id, 0),
        })
    total_voters = sum(vote_count_by_answer.values()) if vote_count_by_answer else 0
    return {
        'discord_message_id': poll.discord_message_id,
        'channel_id': poll.channel_id,
        'channel_key': poll.channel_key,
        'guild_id': poll.guild_id,
        'title': poll.title,
        'match_date': poll.match_date.isoformat() if poll.match_date else None,
        'options': options_out,
        'duration_hours': poll.duration_hours,
        'allow_multiselect': poll.allow_multiselect,
        'created_by_user_id': poll.created_by_user_id,
        'created_at': poll.created_at.isoformat() if poll.created_at else None,
        'expires_at': poll.expires_at.isoformat() if poll.expires_at else None,
        'is_closed': bool(poll.expires_at and poll.expires_at <= datetime.utcnow()),
        'discord_message_url': poll.discord_message_url,
        'total_votes': total_voters,
    }


@mobile_api_v2.route('/substitutes/discord/availability-poll/recent', methods=['GET'])
@jwt_required()
@api_key_required
@jwt_role_required(['Global Admin', 'Pub League Admin'])
def list_recent_discord_polls():
    """
    List recent Discord availability polls with per-answer tallies.

    Query params:
      - channel_key (optional): filter by channel_key (e.g. "pl_subs")
      - limit (optional, default 10, max 50)
    """
    session = getattr(g, 'db_session', None)
    if session is None:
        return jsonify({"msg": "Database session not available"}), 500

    channel_key = request.args.get('channel_key')
    try:
        limit = int(request.args.get('limit', 10))
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(limit, 50))

    q = session.query(DiscordPoll).order_by(DiscordPoll.created_at.desc())
    if channel_key:
        q = q.filter(DiscordPoll.channel_key == channel_key)
    polls = q.limit(limit).all()

    if not polls:
        return jsonify({"polls": []}), 200

    poll_ids = [p.id for p in polls]
    from sqlalchemy import func
    tally_rows = session.query(
        DiscordPollVote.poll_id,
        DiscordPollVote.answer_id,
        func.count(DiscordPollVote.id).label('cnt'),
    ).filter(
        DiscordPollVote.poll_id.in_(poll_ids),
        DiscordPollVote.removed_at.is_(None),
    ).group_by(
        DiscordPollVote.poll_id, DiscordPollVote.answer_id
    ).all()

    tallies_by_poll = {}
    for poll_id, answer_id, cnt in tally_rows:
        tallies_by_poll.setdefault(poll_id, {})[answer_id] = cnt

    polls_out = [
        _serialize_poll_summary(p, tallies_by_poll.get(p.id, {}))
        for p in polls
    ]
    return jsonify({"polls": polls_out}), 200


@mobile_api_v2.route(
    '/substitutes/discord/availability-poll/<string:discord_message_id>',
    methods=['GET'],
)
@jwt_required()
@api_key_required
@jwt_role_required(['Global Admin', 'Pub League Admin'])
def get_discord_poll_detail(discord_message_id: str):
    """
    Get full details of a Discord availability poll: per-answer tally plus
    the responders mapped to ECS player_id and player_name where possible.
    """
    session = getattr(g, 'db_session', None)
    if session is None:
        return jsonify({"msg": "Database session not available"}), 500

    poll = session.query(DiscordPoll).filter_by(
        discord_message_id=discord_message_id
    ).first()
    if poll is None:
        return jsonify({"msg": "Poll not found"}), 404

    active_votes = session.query(DiscordPollVote).filter(
        DiscordPollVote.poll_id == poll.id,
        DiscordPollVote.removed_at.is_(None),
    ).order_by(DiscordPollVote.voted_at.asc()).all()

    discord_ids = list({v.discord_user_id for v in active_votes})
    players_by_discord_id = {}
    if discord_ids:
        rows = session.query(Player).options(
            selectinload(Player.teams)
        ).filter(
            Player.discord_id.in_(discord_ids)
        ).all()
        players_by_discord_id = {p.discord_id: p for p in rows}

    options_lookup = _build_options_lookup(poll.options)

    responders_map = {}  # discord_user_id -> {player info, [selected]}
    tally = {}
    for v in active_votes:
        tally[v.answer_id] = tally.get(v.answer_id, 0) + 1
        entry = responders_map.get(v.discord_user_id)
        if entry is None:
            player = players_by_discord_id.get(v.discord_user_id)
            entry = {
                'discord_user_id': v.discord_user_id,
                'player_id': player.id if player else None,
                'player_name': player.name if player else None,
                'team_ids': (
                    [t.id for t in player.teams] if player and getattr(player, 'teams', None)
                    else []
                ),
                'selected_answers': [],
                'first_voted_at': v.voted_at.isoformat() if v.voted_at else None,
                'last_voted_at': v.voted_at.isoformat() if v.voted_at else None,
            }
            responders_map[v.discord_user_id] = entry
        opt = options_lookup.get(v.answer_id, {})
        entry['selected_answers'].append({
            'answer_id': v.answer_id,
            'text': opt.get('text', ''),
            'emoji': opt.get('emoji'),
            'voted_at': v.voted_at.isoformat() if v.voted_at else None,
        })
        if v.voted_at and (not entry['last_voted_at'] or v.voted_at.isoformat() > entry['last_voted_at']):
            entry['last_voted_at'] = v.voted_at.isoformat()

    # Sort responders: mapped players first (by name), then unmapped by discord_user_id
    def _sort_key(r):
        name = (r['player_name'] or '').lower()
        return (0 if r['player_id'] else 1, name, r['discord_user_id'])
    responders = sorted(responders_map.values(), key=_sort_key)

    poll_payload = _serialize_poll_summary(poll, tally)

    mapped_count = sum(1 for r in responders if r['player_id'])
    unmapped_count = len(responders) - mapped_count

    return jsonify({
        'poll': poll_payload,
        'responders': responders,
        'summary': {
            'unique_responders': len(responders),
            'mapped_to_player': mapped_count,
            'unmapped_discord_users': unmapped_count,
        },
    }), 200


# ============================================================================
# Sub Pool Player Endpoints - Respond to Requests
# ============================================================================

@mobile_api_v2.route('/substitutes/available-requests', methods=['GET'])
@jwt_required()
def get_available_requests():
    """
    Get substitute requests available to the current user.

    Returns only open requests that the user can respond to.

    Returns:
        JSON with list of available requests
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        player = get_player_from_user(session, current_user_id)
        if not player:
            return jsonify({"msg": "Player profile not found"}), 404

        # Check if user is in substitute pool
        pool_membership = session.query(SubstitutePool).filter(
            SubstitutePool.player_id == player.id,
            SubstitutePool.is_active == True
        ).first()

        if not pool_membership:
            return jsonify({
                "requests": [],
                "count": 0,
                "message": "You are not in the substitute pool"
            }), 200

        # Get open requests
        requests = session.query(SubstituteRequest).options(
            joinedload(SubstituteRequest.match).joinedload(Match.home_team),
            joinedload(SubstituteRequest.match).joinedload(Match.away_team),
            joinedload(SubstituteRequest.team)
        ).filter(
            SubstituteRequest.status == 'OPEN'
        ).order_by(SubstituteRequest.created_at.desc()).limit(50).all()

        # Filter out requests the user has already responded to
        responded_request_ids = set(
            r.request_id for r in session.query(SubstituteResponse).filter(
                SubstituteResponse.player_id == player.id
            ).all()
        )

        requests_data = []
        for req in requests:
            if req.id in responded_request_ids:
                continue

            requests_data.append({
                "id": req.id,
                "match": {
                    "id": req.match.id,
                    "date": req.match.date.isoformat() if req.match.date else None,
                    "time": req.match.time.isoformat() if req.match.time else None,
                    "location": req.match.location,
                    "home_team": req.match.home_team.name if req.match.home_team else None,
                    "away_team": req.match.away_team.name if req.match.away_team else None
                } if req.match else None,
                "team": {
                    "id": req.team.id,
                    "name": req.team.name
                } if req.team else None,
                "positions_needed": req.positions_needed,
                "substitutes_needed": req.substitutes_needed,
                "notes": req.notes,
                "created_at": req.created_at.isoformat() if req.created_at else None
            })

        return jsonify({
            "requests": requests_data,
            "count": len(requests_data)
        }), 200


@mobile_api_v2.route('/substitutes/requests/<int:request_id>/respond', methods=['POST'])
@jwt_required()
def respond_to_request(request_id: int):
    """
    Respond to a substitute request.

    Args:
        request_id: Substitute request ID

    Expected JSON:
        is_available: Boolean indicating availability
        response_text: Optional message (optional)

    Returns:
        JSON with response details
    """
    current_user_id = int(get_jwt_identity())

    data = request.get_json()
    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    is_available = data.get('is_available')
    response_text = data.get('response_text', '').strip()

    if is_available is None:
        return jsonify({"msg": "is_available is required"}), 400

    with managed_session() as session:
        player = get_player_from_user(session, current_user_id)
        if not player:
            return jsonify({"msg": "Player profile not found"}), 404

        # Verify request exists and is open
        sub_request = session.query(SubstituteRequest).get(request_id)
        if not sub_request:
            return jsonify({"msg": "Request not found"}), 404

        if sub_request.status != 'OPEN':
            return jsonify({"msg": f"Cannot respond to request with status: {sub_request.status}"}), 400

        # Check for existing response
        existing = session.query(SubstituteResponse).filter(
            SubstituteResponse.request_id == request_id,
            SubstituteResponse.player_id == player.id
        ).first()

        if existing:
            return jsonify({"msg": "You have already responded to this request"}), 400

        # Create response
        response = SubstituteResponse(
            request_id=request_id,
            player_id=player.id,
            is_available=bool(is_available),
            response_method='mobile_api',
            response_text=response_text
        )

        session.add(response)

        # Update pool stats
        pool_membership = session.query(SubstitutePool).filter(
            SubstitutePool.player_id == player.id
        ).first()

        if pool_membership:
            pool_membership.requests_received = (pool_membership.requests_received or 0) + 1
            if is_available:
                pool_membership.requests_accepted = (pool_membership.requests_accepted or 0) + 1
            pool_membership.last_active_at = datetime.utcnow()

        # Capture data for admin notification before commit
        player_name = player.name
        team_name = sub_request.team.name if sub_request.team else 'Unknown Team'
        match_date_str = None
        if sub_request.match and sub_request.match.date:
            match_date_str = sub_request.match.date.strftime('%A, %B %d')

        session.commit()

        logger.info(f"Substitute response: player {player.id} responded to request {request_id}")

        # Notify admins (Pub League admins manage subs, not the coach)
        try:
            from app.models.core import Role
            from app.services.notification_orchestrator import (
                orchestrator, NotificationType, NotificationPayload
            )

            # Get all Pub League Admin and Global Admin user IDs
            admin_roles = session.query(Role).filter(
                Role.name.in_(['Global Admin', 'Pub League Admin'])
            ).all()
            admin_user_ids = []
            for role in admin_roles:
                admin_user_ids.extend([u.id for u in role.users])
            admin_user_ids = list(set(admin_user_ids))

            if admin_user_ids:
                availability_text = "is available" if is_available else "is NOT available"
                match_text = f" for {team_name} on {match_date_str}" if match_date_str else f" for {team_name}"

                orchestrator.send(NotificationPayload(
                    notification_type=NotificationType.SUB_REQUEST,
                    title="Sub Response Received",
                    message=f"{player_name} {availability_text}{match_text}",
                    user_ids=admin_user_ids,
                    data={
                        'type': 'sub_response',
                        'request_id': str(request_id),
                        'player_name': player_name,
                        'is_available': str(is_available).lower(),
                        'league_type': 'pub_league',
                        'click_action': 'FLUTTER_NOTIFICATION_CLICK',
                    },
                ))
                logger.info(f"Notified {len(admin_user_ids)} admins of sub response from {player_name}")
        except Exception as e:
            logger.error(f"Failed to notify admins of sub response: {e}")

        return jsonify({
            "success": True,
            "message": "Response recorded",
            "response": {
                "id": response.id,
                "request_id": request_id,
                "is_available": response.is_available,
                "responded_at": response.responded_at.isoformat() if response.responded_at else None
            }
        }), 201


@mobile_api_v2.route('/substitutes/my-targeted-requests', methods=['GET'])
@jwt_required()
def get_my_targeted_requests():
    """
    Get substitute requests where the current user was specifically contacted.

    Returns requests where a SubstituteResponse exists for the user with
    notification_sent_at populated (indicating they were directly contacted).

    Query Parameters:
        status: Filter by request status (OPEN, FILLED, CANCELLED)
        pending_only: If 'true', only show requests user hasn't responded to yet

    Returns:
        JSON with list of targeted requests
    """
    current_user_id = int(get_jwt_identity())
    status_filter = request.args.get('status')
    pending_only = request.args.get('pending_only', 'false').lower() == 'true'

    with managed_session() as session:
        player = get_player_from_user(session, current_user_id)
        if not player:
            return jsonify({"msg": "Player profile not found"}), 404

        # Find responses where user was specifically contacted (notification_sent_at is set)
        query = session.query(SubstituteResponse).options(
            joinedload(SubstituteResponse.request).joinedload(SubstituteRequest.match).joinedload(Match.home_team),
            joinedload(SubstituteResponse.request).joinedload(SubstituteRequest.match).joinedload(Match.away_team),
            joinedload(SubstituteResponse.request).joinedload(SubstituteRequest.team)
        ).filter(
            SubstituteResponse.player_id == player.id,
            SubstituteResponse.notification_sent_at.isnot(None)  # Was specifically contacted
        )

        # Filter by pending (not yet responded)
        if pending_only:
            query = query.filter(SubstituteResponse.responded_at.is_(None))

        query = query.order_by(SubstituteResponse.notification_sent_at.desc())
        targeted_responses = query.all()

        # Filter by request status if specified
        requests_data = []
        for resp in targeted_responses:
            if not resp.request:
                continue

            if status_filter and resp.request.status != status_filter.upper():
                continue

            match_data = None
            if resp.request.match:
                match = resp.request.match
                match_data = {
                    "id": match.id,
                    "date": match.date.isoformat() if match.date else None,
                    "time": match.time.isoformat() if match.time else None,
                    "location": match.location,
                    "home_team": match.home_team.name if match.home_team else None,
                    "away_team": match.away_team.name if match.away_team else None
                }

            requests_data.append({
                "request_id": resp.request.id,
                "response_id": resp.id,
                "match": match_data,
                "team": {
                    "id": resp.request.team.id,
                    "name": resp.request.team.name
                } if resp.request.team else None,
                "positions_needed": resp.request.positions_needed,
                "substitutes_needed": resp.request.substitutes_needed,
                "notes": resp.request.notes,
                "request_status": resp.request.status,
                "contacted_at": resp.notification_sent_at.isoformat() if resp.notification_sent_at else None,
                "notification_methods": resp.notification_methods,
                "has_responded": resp.responded_at is not None,
                "my_response": {
                    "is_available": resp.is_available,
                    "response_text": resp.response_text,
                    "responded_at": resp.responded_at.isoformat() if resp.responded_at else None
                } if resp.responded_at else None,
                "created_at": resp.request.created_at.isoformat() if resp.request.created_at else None
            })

        return jsonify({
            "requests": requests_data,
            "count": len(requests_data),
            "pending_count": sum(1 for r in requests_data if not r['has_responded'])
        }), 200


@mobile_api_v2.route('/substitutes/my-responses', methods=['GET'])
@jwt_required()
def get_my_responses():
    """
    Get the current user's substitute response history.

    Returns:
        JSON with list of user's responses
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        player = get_player_from_user(session, current_user_id)
        if not player:
            return jsonify({"msg": "Player profile not found"}), 404

        responses = session.query(SubstituteResponse).options(
            joinedload(SubstituteResponse.request).joinedload(SubstituteRequest.match),
            joinedload(SubstituteResponse.request).joinedload(SubstituteRequest.team)
        ).filter(
            SubstituteResponse.player_id == player.id
        ).order_by(SubstituteResponse.responded_at.desc()).limit(50).all()

        responses_data = []
        for resp in responses:
            responses_data.append({
                "id": resp.id,
                "request": {
                    "id": resp.request.id,
                    "match_date": resp.request.match.date.isoformat() if resp.request.match and resp.request.match.date else None,
                    "team_name": resp.request.team.name if resp.request.team else None,
                    "status": resp.request.status
                } if resp.request else None,
                "is_available": resp.is_available,
                "response_text": resp.response_text,
                "responded_at": resp.responded_at.isoformat() if resp.responded_at else None
            })

        return jsonify({
            "responses": responses_data,
            "count": len(responses_data)
        }), 200


@mobile_api_v2.route('/substitutes/my-assignments', methods=['GET'])
@jwt_required()
def get_my_assignments():
    """
    Get the current user's substitute assignments.

    Returns:
        JSON with list of user's assignments
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        player = get_player_from_user(session, current_user_id)
        if not player:
            return jsonify({"msg": "Player profile not found"}), 404

        assignments = session.query(SubstituteAssignment).options(
            joinedload(SubstituteAssignment.request).joinedload(SubstituteRequest.match),
            joinedload(SubstituteAssignment.request).joinedload(SubstituteRequest.team)
        ).filter(
            SubstituteAssignment.player_id == player.id
        ).order_by(SubstituteAssignment.assigned_at.desc()).limit(50).all()

        assignments_data = []
        for assign in assignments:
            assignments_data.append({
                "id": assign.id,
                "request": {
                    "id": assign.request.id,
                    "match": {
                        "id": assign.request.match.id,
                        "date": assign.request.match.date.isoformat() if assign.request.match.date else None,
                        "time": assign.request.match.time.isoformat() if assign.request.match.time else None,
                        "location": assign.request.match.location
                    } if assign.request.match else None,
                    "team_name": assign.request.team.name if assign.request.team else None
                } if assign.request else None,
                "position_assigned": assign.position_assigned,
                "notes": assign.notes,
                "assigned_at": assign.assigned_at.isoformat() if assign.assigned_at else None
            })

        return jsonify({
            "assignments": assignments_data,
            "count": len(assignments_data)
        }), 200


# ============================================================================
# Pool Management Endpoints - Join/Leave/Update Pool Status
# ============================================================================

@mobile_api_v2.route('/substitutes/pool/my-status', methods=['GET'])
@jwt_required()
def get_my_pool_status():
    """
    Get the current user's substitute pool membership status.

    Returns:
        JSON with pool membership details
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        player = get_player_from_user(session, current_user_id)
        if not player:
            return jsonify({"msg": "Player profile not found"}), 404

        pool_membership = session.query(SubstitutePool).filter(
            SubstitutePool.player_id == player.id
        ).first()

        if not pool_membership:
            return jsonify({
                "in_pool": False,
                "membership": None
            }), 200

        return jsonify({
            "in_pool": True,
            "membership": {
                "id": pool_membership.id,
                "league_type": pool_membership.league_type,
                "is_active": pool_membership.is_active,
                "preferred_positions": pool_membership.preferred_positions,
                "max_matches_per_week": pool_membership.max_matches_per_week,
                "sms_for_sub_requests": pool_membership.sms_for_sub_requests,
                "discord_for_sub_requests": pool_membership.discord_for_sub_requests,
                "email_for_sub_requests": pool_membership.email_for_sub_requests,
                "requests_received": pool_membership.requests_received,
                "requests_accepted": pool_membership.requests_accepted,
                "matches_played": pool_membership.matches_played,
                "joined_pool_at": pool_membership.joined_pool_at.isoformat() if pool_membership.joined_pool_at else None
            }
        }), 200


@mobile_api_v2.route('/substitutes/pool/my-status', methods=['PUT'])
@jwt_required()
def update_my_pool_status():
    """
    Update the current user's substitute pool preferences.

    Expected JSON (all optional):
        preferred_positions: Comma-separated positions
        max_matches_per_week: Maximum matches per week
        sms_for_sub_requests: Enable SMS notifications
        discord_for_sub_requests: Enable Discord notifications
        email_for_sub_requests: Enable email notifications
        is_active: Active status

    Returns:
        JSON with updated membership details
    """
    current_user_id = int(get_jwt_identity())

    data = request.get_json()
    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    with managed_session() as session:
        player = get_player_from_user(session, current_user_id)
        if not player:
            return jsonify({"msg": "Player profile not found"}), 404

        pool_membership = session.query(SubstitutePool).filter(
            SubstitutePool.player_id == player.id
        ).first()

        if not pool_membership:
            return jsonify({"msg": "You are not in the substitute pool"}), 404

        # Update fields
        if 'preferred_positions' in data:
            pool_membership.preferred_positions = data['preferred_positions']
        if 'max_matches_per_week' in data:
            try:
                pool_membership.max_matches_per_week = int(data['max_matches_per_week'])
            except (ValueError, TypeError):
                pass
        if 'sms_for_sub_requests' in data:
            pool_membership.sms_for_sub_requests = bool(data['sms_for_sub_requests'])
        if 'discord_for_sub_requests' in data:
            pool_membership.discord_for_sub_requests = bool(data['discord_for_sub_requests'])
        if 'email_for_sub_requests' in data:
            pool_membership.email_for_sub_requests = bool(data['email_for_sub_requests'])
        if 'is_active' in data:
            pool_membership.is_active = bool(data['is_active'])

        pool_membership.last_active_at = datetime.utcnow()
        session.commit()

        return jsonify({
            "success": True,
            "message": "Pool preferences updated",
            "membership": {
                "is_active": pool_membership.is_active,
                "preferred_positions": pool_membership.preferred_positions,
                "max_matches_per_week": pool_membership.max_matches_per_week,
                "sms_for_sub_requests": pool_membership.sms_for_sub_requests,
                "discord_for_sub_requests": pool_membership.discord_for_sub_requests,
                "email_for_sub_requests": pool_membership.email_for_sub_requests
            }
        }), 200


@mobile_api_v2.route('/substitutes/pool/join', methods=['POST'])
@jwt_required()
@jwt_role_required(['Global Admin', 'Pub League Admin'])
def join_substitute_pool():
    """
    Request to join the substitute pool.

    Expected JSON:
        league_type: League type (e.g., "Pub League", "Classic", "Premier")
        preferred_positions: Comma-separated positions (optional)

    Returns:
        JSON with membership details
    """
    current_user_id = int(get_jwt_identity())

    data = request.get_json()
    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    league_type = data.get('league_type', 'Pub League')
    preferred_positions = data.get('preferred_positions', '')

    with managed_session() as session:
        player = get_player_from_user(session, current_user_id)
        if not player:
            return jsonify({"msg": "Player profile not found"}), 404

        # Check if already in pool
        existing = session.query(SubstitutePool).filter(
            SubstitutePool.player_id == player.id
        ).first()

        if existing:
            if existing.is_active:
                return jsonify({"msg": "You are already in the substitute pool"}), 400
            else:
                # Reactivate
                existing.is_active = True
                existing.last_active_at = datetime.utcnow()
                session.commit()
                return jsonify({
                    "success": True,
                    "message": "Pool membership reactivated",
                    "membership_id": existing.id
                }), 200

        # Create new membership
        membership = SubstitutePool(
            player_id=player.id,
            league_type=league_type,
            preferred_positions=preferred_positions,
            is_active=True
        )

        session.add(membership)
        session.commit()

        logger.info(f"Player {player.id} joined substitute pool")

        return jsonify({
            "success": True,
            "message": "Joined substitute pool",
            "membership_id": membership.id
        }), 201


@mobile_api_v2.route('/substitutes/pool/leave', methods=['DELETE'])
@jwt_required()
@jwt_role_required(['Global Admin', 'Pub League Admin'])
def leave_substitute_pool():
    """
    Leave the substitute pool.

    Returns:
        JSON with success message
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        player = get_player_from_user(session, current_user_id)
        if not player:
            return jsonify({"msg": "Player profile not found"}), 404

        membership = session.query(SubstitutePool).filter(
            SubstitutePool.player_id == player.id
        ).first()

        if not membership:
            return jsonify({"msg": "You are not in the substitute pool"}), 404

        # Deactivate rather than delete to preserve history
        membership.is_active = False
        session.commit()

        logger.info(f"Player {player.id} left substitute pool")

        return jsonify({
            "success": True,
            "message": "Left substitute pool"
        }), 200
