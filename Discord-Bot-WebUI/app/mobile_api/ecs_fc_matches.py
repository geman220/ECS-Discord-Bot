# app/mobile_api/ecs_fc_matches.py

"""
Mobile API ECS FC Match Endpoints

Provides ECS FC match functionality for mobile clients:
- List ECS FC matches for user's teams
- Get single match details with user's availability
- Get match RSVP summary with player list
- Update user's RSVP for a match
"""

import logging
from datetime import datetime, date

from flask import jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy.orm import joinedload, selectinload

from app.mobile_api import mobile_api_v2
from app.core.session_manager import managed_session
from app.models import User, Player, Team
from app.models.ecs_fc import EcsFcMatch, EcsFcAvailability

logger = logging.getLogger(__name__)


def get_user_ecs_fc_team_ids(session, user_id: int) -> list:
    """
    Get all ECS FC team IDs for a user.

    Args:
        session: Database session
        user_id: User ID

    Returns:
        List of team IDs
    """
    player = session.query(Player).options(
        selectinload(Player.teams).joinedload(Team.league)
    ).filter_by(user_id=user_id).first()

    if not player:
        return []

    # Filter to only ECS FC teams
    ecs_fc_team_ids = []
    for team in player.teams:
        if team.league and 'ECS FC' in team.league.name:
            ecs_fc_team_ids.append(team.id)

    return ecs_fc_team_ids


def is_coach_for_team(session, user_id: int, team_id: int) -> bool:
    """Check if user is a coach for the specified team."""
    from app.models import player_teams
    from sqlalchemy import and_

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

    admin_roles = ['Global Admin', 'Pub League Admin', 'Admin', 'ECS FC Coach']
    return any(role.name in admin_roles for role in user.roles)


@mobile_api_v2.route('/ecs-fc-matches', methods=['GET'])
@jwt_required()
def get_ecs_fc_matches():
    """
    Get ECS FC matches for the current user's teams.

    Query Parameters:
        upcoming: If 'true', return only upcoming matches (default: true)
        team_id: Filter by specific team ID
        limit: Maximum number of matches (default: 20, max: 100)
        include_availability: If 'true', include user's availability

    Returns:
        JSON with list of ECS FC matches
    """
    current_user_id = int(get_jwt_identity())

    upcoming = request.args.get('upcoming', 'true').lower() == 'true'
    team_id = request.args.get('team_id', type=int)
    limit = min(request.args.get('limit', 20, type=int), 100)
    include_availability = request.args.get('include_availability', 'true').lower() == 'true'

    with managed_session() as session:
        # Get user's ECS FC teams
        user_team_ids = get_user_ecs_fc_team_ids(session, current_user_id)

        if not user_team_ids and not is_admin_user(session, current_user_id):
            return jsonify({
                "matches": [],
                "count": 0,
                "message": "You are not on any ECS FC teams"
            }), 200

        # Build query
        query = session.query(EcsFcMatch).options(
            joinedload(EcsFcMatch.team),
            selectinload(EcsFcMatch.availabilities)
        )

        # Filter by team
        if team_id:
            query = query.filter(EcsFcMatch.team_id == team_id)
        elif user_team_ids:
            query = query.filter(EcsFcMatch.team_id.in_(user_team_ids))

        # Filter by date
        if upcoming:
            query = query.filter(EcsFcMatch.match_date >= date.today())
            query = query.order_by(EcsFcMatch.match_date.asc(), EcsFcMatch.match_time.asc())
        else:
            query = query.order_by(EcsFcMatch.match_date.desc(), EcsFcMatch.match_time.desc())

        # Exclude cancelled matches
        query = query.filter(EcsFcMatch.status != 'CANCELLED')

        matches = query.limit(limit).all()

        # Get player for availability lookup
        player = session.query(Player).filter_by(user_id=current_user_id).first()

        # Build response
        matches_data = []
        for match in matches:
            match_data = {
                "id": match.id,
                "team": {
                    "id": match.team.id,
                    "name": match.team.name
                } if match.team else None,
                "opponent_name": match.opponent_name,
                "date": match.match_date.isoformat() if match.match_date else None,
                "time": match.match_time.isoformat() if match.match_time else None,
                "location": match.location,
                "field_name": match.field_name,
                "is_home_match": match.is_home_match,
                "status": match.status,
                "home_score": match.home_score,
                "away_score": match.away_score,
                "notes": match.notes,
                "rsvp_deadline": match.rsvp_deadline.isoformat() if match.rsvp_deadline else None,
                "rsvp_summary": match.get_rsvp_summary()
            }

            # Add user's availability
            if include_availability and player:
                user_availability = next(
                    (a for a in match.availability if a.player_id == player.id),
                    None
                )
                match_data["my_availability"] = user_availability.response if user_availability else None

            matches_data.append(match_data)

        return jsonify({
            "matches": matches_data,
            "count": len(matches_data)
        }), 200


@mobile_api_v2.route('/ecs-fc-matches/<int:match_id>', methods=['GET'])
@jwt_required()
def get_ecs_fc_match_details(match_id: int):
    """
    Get detailed information for a specific ECS FC match.

    Args:
        match_id: ECS FC match ID

    Query Parameters:
        include_availability: If 'true', include user's availability (default: true)

    Returns:
        JSON with full match details including user's availability
    """
    current_user_id = int(get_jwt_identity())
    include_availability = request.args.get('include_availability', 'true').lower() == 'true'

    with managed_session() as session:
        match = session.query(EcsFcMatch).options(
            joinedload(EcsFcMatch.team).selectinload(Team.players),
            selectinload(EcsFcMatch.availabilities).joinedload(EcsFcAvailability.player)
        ).get(match_id)

        if not match:
            return jsonify({"msg": "Match not found"}), 404

        # Get player for availability lookup
        player = session.query(Player).filter_by(user_id=current_user_id).first()

        # Build response
        match_data = {
            "id": match.id,
            "team": {
                "id": match.team.id,
                "name": match.team.name,
                "league_id": match.team.league_id
            } if match.team else None,
            "opponent_name": match.opponent_name,
            "date": match.match_date.isoformat() if match.match_date else None,
            "time": match.match_time.isoformat() if match.match_time else None,
            "location": match.location,
            "field_name": match.field_name,
            "is_home_match": match.is_home_match,
            "home_shirt_color": match.home_shirt_color,
            "away_shirt_color": match.away_shirt_color,
            "status": match.status,
            "home_score": match.home_score,
            "away_score": match.away_score,
            "notes": match.notes,
            "rsvp_deadline": match.rsvp_deadline.isoformat() if match.rsvp_deadline else None,
            "rsvp_reminder_sent": match.rsvp_reminder_sent,
            "created_at": match.created_at.isoformat() if match.created_at else None,
            "updated_at": match.updated_at.isoformat() if match.updated_at else None,
            "rsvp_summary": match.get_rsvp_summary()
        }

        # Add user's availability
        if include_availability and player:
            user_availability = next(
                (a for a in match.availability if a.player_id == player.id),
                None
            )
            match_data["my_availability"] = user_availability.response if user_availability else None
            match_data["my_availability_updated_at"] = (
                user_availability.responded_at.isoformat()
                if user_availability and user_availability.responded_at else None
            )

        return jsonify(match_data), 200


@mobile_api_v2.route('/ecs-fc-matches/<int:match_id>/availability', methods=['GET'])
@jwt_required()
def get_ecs_fc_match_availability(match_id: int):
    """
    Get RSVP/availability summary for an ECS FC match.

    Returns the RSVP summary counts and detailed player list.
    Coaches and admins see all player details.
    Regular players see summary counts only.

    Args:
        match_id: ECS FC match ID

    Returns:
        JSON with RSVP summary and player availability details
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        match = session.query(EcsFcMatch).options(
            joinedload(EcsFcMatch.team).selectinload(Team.players),
            selectinload(EcsFcMatch.availabilities).joinedload(EcsFcAvailability.player)
        ).get(match_id)

        if not match:
            return jsonify({"msg": "Match not found"}), 404

        # Check if user can see detailed player list
        is_coach = is_coach_for_team(session, current_user_id, match.team_id)
        is_admin = is_admin_user(session, current_user_id)
        can_see_details = is_coach or is_admin

        # Get player for user's own availability
        player = session.query(Player).filter_by(user_id=current_user_id).first()

        # Build RSVP summary
        rsvp_summary = match.get_rsvp_summary()

        # Build availability map from responses
        availability_map = {a.player_id: a for a in match.availability if a.player_id}

        # Get base URL for profile pictures
        base_url = request.host_url.rstrip('/')

        # Build player list (only for coaches/admins)
        players_data = []
        if can_see_details and match.team:
            team_players = [p for p in match.team.players if p.is_current_player]

            for team_player in team_players:
                av = availability_map.get(team_player.id)

                profile_picture_url = None
                if team_player.profile_picture_url:
                    profile_picture_url = (
                        team_player.profile_picture_url
                        if team_player.profile_picture_url.startswith('http')
                        else f"{base_url}{team_player.profile_picture_url}"
                    )
                else:
                    profile_picture_url = f"{base_url}/static/img/default_player.png"

                players_data.append({
                    "id": team_player.id,
                    "name": team_player.name,
                    "jersey_number": team_player.jersey_number,
                    "position": team_player.favorite_position,
                    "response": av.response if av else None,
                    "responded_at": av.responded_at.isoformat() if av and av.responded_at else None,
                    "profile_picture_url": profile_picture_url
                })

            # Sort: yes first, then maybe, then no_response, then no
            response_order = {'yes': 0, 'maybe': 1, None: 2, 'no_response': 2, 'no': 3}
            players_data.sort(key=lambda p: (response_order.get(p['response'], 2), p['name']))

        # Build response
        response_data = {
            "match_id": match_id,
            "match": {
                "id": match.id,
                "date": match.match_date.isoformat() if match.match_date else None,
                "time": match.match_time.isoformat() if match.match_time else None,
                "opponent_name": match.opponent_name,
                "location": match.location,
                "is_home_match": match.is_home_match
            },
            "team": {
                "id": match.team.id,
                "name": match.team.name
            } if match.team else None,
            "rsvp_summary": rsvp_summary,
            "has_enough_players": rsvp_summary['yes'] >= 11  # Full team for ECS FC
        }

        # Add detailed player list for coaches/admins
        if can_see_details:
            response_data["players"] = players_data
            response_data["total_players"] = len(players_data)

        # Add user's own availability
        if player:
            user_availability = availability_map.get(player.id)
            response_data["my_availability"] = user_availability.response if user_availability else None

        return jsonify(response_data), 200


@mobile_api_v2.route('/ecs-fc-matches/<int:match_id>/rsvp', methods=['POST'])
@jwt_required()
def update_ecs_fc_match_rsvp(match_id: int):
    """
    Update the current user's RSVP for an ECS FC match.

    Args:
        match_id: ECS FC match ID

    Expected JSON:
        response: RSVP response ('yes', 'no', 'maybe')

    Returns:
        JSON with updated availability
    """
    current_user_id = int(get_jwt_identity())

    data = request.get_json()
    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    response_value = data.get('response')
    if not response_value:
        return jsonify({"msg": "response is required"}), 400

    valid_responses = ['yes', 'no', 'maybe', 'no_response']
    if response_value not in valid_responses:
        return jsonify({"msg": f"Invalid response. Must be one of: {valid_responses}"}), 400

    with managed_session() as session:
        # Get match
        match = session.query(EcsFcMatch).get(match_id)
        if not match:
            return jsonify({"msg": "Match not found"}), 404

        # Get player
        player = session.query(Player).filter_by(user_id=current_user_id).first()
        if not player:
            return jsonify({"msg": "Player profile not found"}), 404

        # Check/create availability record
        availability = session.query(EcsFcAvailability).filter(
            EcsFcAvailability.ecs_fc_match_id == match_id,
            EcsFcAvailability.player_id == player.id
        ).first()

        if availability:
            # Update existing
            availability.response = response_value
            availability.responded_at = datetime.utcnow()
        else:
            # Create new
            availability = EcsFcAvailability(
                ecs_fc_match_id=match_id,
                player_id=player.id,
                discord_id=player.discord_id or '',
                response=response_value,
                responded_at=datetime.utcnow()
            )
            session.add(availability)

        session.commit()

        logger.info(f"ECS FC RSVP updated: player {player.id} -> {response_value} for match {match_id}")

        return jsonify({
            "success": True,
            "message": "RSVP updated",
            "match_id": match_id,
            "response": response_value,
            "responded_at": availability.responded_at.isoformat()
        }), 200


@mobile_api_v2.route('/ecs-fc-matches/<int:match_id>/rsvp/bulk', methods=['POST'])
@jwt_required()
def bulk_update_ecs_fc_rsvp(match_id: int):
    """
    Update RSVP for multiple players (coach/admin only).

    Args:
        match_id: ECS FC match ID

    Expected JSON:
        updates: List of {player_id, response} objects

    Returns:
        JSON with results for each update
    """
    current_user_id = int(get_jwt_identity())

    data = request.get_json()
    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    updates = data.get('updates', [])
    if not updates:
        return jsonify({"msg": "No updates provided"}), 400

    with managed_session() as session:
        # Get match
        match = session.query(EcsFcMatch).get(match_id)
        if not match:
            return jsonify({"msg": "Match not found"}), 404

        # Check authorization
        if not is_coach_for_team(session, current_user_id, match.team_id) and not is_admin_user(session, current_user_id):
            return jsonify({"msg": "You are not authorized to update RSVPs for this team"}), 403

        valid_responses = ['yes', 'no', 'maybe', 'no_response']
        results = []

        for update in updates:
            player_id = update.get('player_id')
            response_value = update.get('response')

            if not player_id or not response_value:
                results.append({
                    "player_id": player_id,
                    "success": False,
                    "error": "Missing player_id or response"
                })
                continue

            if response_value not in valid_responses:
                results.append({
                    "player_id": player_id,
                    "success": False,
                    "error": f"Invalid response: {response_value}"
                })
                continue

            # Get player
            player = session.query(Player).get(player_id)
            if not player:
                results.append({
                    "player_id": player_id,
                    "success": False,
                    "error": "Player not found"
                })
                continue

            # Update/create availability
            availability = session.query(EcsFcAvailability).filter(
                EcsFcAvailability.ecs_fc_match_id == match_id,
                EcsFcAvailability.player_id == player_id
            ).first()

            if availability:
                availability.response = response_value
                availability.responded_at = datetime.utcnow()
            else:
                availability = EcsFcAvailability(
                    ecs_fc_match_id=match_id,
                    player_id=player_id,
                    discord_id=player.discord_id or '',
                    response=response_value,
                    responded_at=datetime.utcnow()
                )
                session.add(availability)

            results.append({
                "player_id": player_id,
                "success": True,
                "response": response_value
            })

        session.commit()

        return jsonify({
            "success": True,
            "message": "Bulk update completed",
            "results": results,
            "successful": sum(1 for r in results if r.get('success')),
            "failed": sum(1 for r in results if not r.get('success'))
        }), 200
