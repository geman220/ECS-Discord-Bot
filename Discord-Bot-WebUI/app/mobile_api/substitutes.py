# app/mobile_api/substitutes.py

"""
Mobile API Substitute Management Endpoints

Provides substitute system functionality for mobile clients:
- Coaches: Create/view/update/cancel substitute requests for their teams
- Admins: View all requests, assign substitutes, manage pool
- Sub Pool Players: View available requests, respond, manage pool membership
"""

import logging
from datetime import datetime

from flask import jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy import and_, or_

from app.mobile_api import mobile_api_v2
from app.decorators import jwt_role_required
from app.core.session_manager import managed_session
from app.models import User, Player, Team, Match, player_teams
from app.models.substitutes import (
    SubstituteRequest, SubstituteResponse, SubstituteAssignment,
    SubstitutePool, SubstitutePoolHistory
)

logger = logging.getLogger(__name__)


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
    positions_needed = data.get('positions_needed', '')
    substitutes_needed = data.get('substitutes_needed', 1)
    gender_preference = data.get('gender_preference')
    notes = data.get('notes', '').strip()

    if not match_id or not team_id:
        return jsonify({"msg": "match_id and team_id are required"}), 400

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

        # Create the request
        sub_request = SubstituteRequest(
            match_id=match_id,
            team_id=team_id,
            requested_by=current_user_id,
            positions_needed=positions_needed,
            substitutes_needed=substitutes_needed,
            gender_preference=gender_preference,
            notes=notes,
            status='OPEN'
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

        # Build query
        query = session.query(SubstituteRequest).options(
            joinedload(SubstituteRequest.match),
            joinedload(SubstituteRequest.team),
            selectinload(SubstituteRequest.responses),
            selectinload(SubstituteRequest.assignments)
        ).filter(
            SubstituteRequest.team_id.in_(coach_team_ids)
        )

        if status_filter:
            query = query.filter(SubstituteRequest.status == status_filter.upper())

        query = query.order_by(SubstituteRequest.created_at.desc()).limit(limit)
        requests = query.all()

        # Build response
        requests_data = []
        for req in requests:
            requests_data.append({
                "id": req.id,
                "match": {
                    "id": req.match.id,
                    "date": req.match.date.isoformat() if req.match.date else None,
                    "time": req.match.time.isoformat() if req.match.time else None,
                    "home_team_id": req.match.home_team_id,
                    "away_team_id": req.match.away_team_id
                } if req.match else None,
                "team": {
                    "id": req.team.id,
                    "name": req.team.name
                } if req.team else None,
                "positions_needed": req.positions_needed,
                "substitutes_needed": req.substitutes_needed,
                "status": req.status,
                "response_count": len(req.responses),
                "assignment_count": len(req.assignments),
                "created_at": req.created_at.isoformat() if req.created_at else None
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
                    "position": resp.player.favorite_position
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

        requests_data = []
        for req in requests:
            requests_data.append({
                "id": req.id,
                "match": {
                    "id": req.match.id,
                    "date": req.match.date.isoformat() if req.match.date else None,
                    "time": req.match.time.isoformat() if req.match.time else None
                } if req.match else None,
                "team": {
                    "id": req.team.id,
                    "name": req.team.name
                } if req.team else None,
                "positions_needed": req.positions_needed,
                "substitutes_needed": req.substitutes_needed,
                "status": req.status,
                "response_count": len(req.responses),
                "assignment_count": len(req.assignments),
                "created_at": req.created_at.isoformat() if req.created_at else None
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
@jwt_role_required(['Global Admin', 'Pub League Admin'])
def assign_substitute(request_id: int):
    """
    Assign a substitute to a request (admin only).

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
    notes = data.get('notes', '').strip()
    send_notification = data.get('send_notification', True)

    if not player_id:
        return jsonify({"msg": "player_id is required"}), 400

    with managed_session() as session:
        sub_request = session.query(SubstituteRequest).get(request_id)
        if not sub_request:
            return jsonify({"msg": "Request not found"}), 404

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
                "player": {
                    "id": member.player.id,
                    "name": member.player.name,
                    "position": member.player.favorite_position
                } if member.player else None,
                "league_type": member.league_type,
                "is_active": member.is_active,
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

        session.commit()

        logger.info(f"Substitute response: player {player.id} responded to request {request_id}")

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
