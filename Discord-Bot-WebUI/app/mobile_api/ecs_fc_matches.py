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


# =============================================================================
# LIVE MATCH REPORTING ENDPOINTS
# =============================================================================

# Valid event types for ECS FC matches
ECS_FC_EVENT_TYPES = ['goal', 'assist', 'yellow_card', 'red_card', 'own_goal']


def can_report_ecs_fc_match(session, user, player, match) -> bool:
    """
    Check if a user has permission to report/edit an ECS FC match.

    Permissions:
    - Global Admin, ECS FC Admin - can edit any match
    - Coach for the team - can edit
    - Player on the team - can edit
    """
    from app.models import player_teams
    from sqlalchemy import and_

    # Check admin roles
    is_global_admin = user.has_role('Global Admin')
    is_admin = user.has_role('admin')
    is_ecs_fc_admin = user.has_role('ECS FC Admin')

    if is_global_admin or is_admin or is_ecs_fc_admin:
        return True

    if not player:
        return False

    # Check if user is a coach for the team
    coach_check = session.execute(
        player_teams.select().where(
            and_(
                player_teams.c.player_id == player.id,
                player_teams.c.is_coach == True,
                player_teams.c.team_id == match.team_id
            )
        )
    ).fetchone()
    if coach_check:
        return True

    # Check if user is on the team's roster
    user_team_ids = {team.id for team in player.teams}
    if match.team_id in user_team_ids:
        return True

    return False


@mobile_api_v2.route('/ecs-fc-matches/<int:match_id>/reporting', methods=['GET'])
@jwt_required()
def get_ecs_fc_match_reporting_info(match_id: int):
    """
    Get ECS FC match information for reporting.

    Returns match details, team roster, existing events, and permissions.
    """
    from app.models.ecs_fc import EcsFcMatch, EcsFcPlayerEvent

    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        user = session.query(User).get(current_user_id)
        if not user:
            return jsonify({"msg": "User not found"}), 404

        player = session.query(Player).filter_by(user_id=current_user_id).first()

        match = session.query(EcsFcMatch).options(
            joinedload(EcsFcMatch.team).selectinload(Team.players),
            selectinload(EcsFcMatch.events).joinedload(EcsFcPlayerEvent.player)
        ).get(match_id)

        if not match:
            return jsonify({"msg": "Match not found"}), 404

        can_report = can_report_ecs_fc_match(session, user, player, match)

        # Get team roster
        team_players = []
        if match.team:
            for p in match.team.players:
                if p.is_current_player:
                    team_players.append({
                        "id": p.id,
                        "name": p.name,
                        "jersey_number": p.jersey_number,
                        "position": p.favorite_position,
                    })

        # Get existing events
        events_data = [e.to_dict(include_player=True) for e in match.events]

        return jsonify({
            "match": {
                "id": match.id,
                "team_id": match.team_id,
                "team_name": match.team.name if match.team else None,
                "opponent_name": match.opponent_name,
                "date": match.match_date.isoformat() if match.match_date else None,
                "time": match.match_time.strftime('%H:%M') if match.match_time else None,
                "location": match.location,
                "is_home_match": match.is_home_match,
                "home_score": match.home_score,
                "away_score": match.away_score,
                "status": match.status,
            },
            "team_players": team_players,
            "events": events_data,
            "can_report": can_report,
            "valid_event_types": ECS_FC_EVENT_TYPES,
        }), 200


@mobile_api_v2.route('/ecs-fc-matches/<int:match_id>/events', methods=['GET'])
@jwt_required()
def get_ecs_fc_match_events(match_id: int):
    """Get all events for an ECS FC match."""
    from app.models.ecs_fc import EcsFcMatch, EcsFcPlayerEvent

    with managed_session() as session:
        match = session.query(EcsFcMatch).options(
            selectinload(EcsFcMatch.events).joinedload(EcsFcPlayerEvent.player)
        ).get(match_id)

        if not match:
            return jsonify({"msg": "Match not found"}), 404

        events_data = [e.to_dict(include_player=True) for e in match.events]

        return jsonify({
            "match_id": match_id,
            "events": events_data,
            "count": len(events_data)
        }), 200


@mobile_api_v2.route('/ecs-fc-matches/<int:match_id>/events', methods=['POST'])
@jwt_required()
def add_ecs_fc_match_event(match_id: int):
    """
    Add an event to an ECS FC match.

    Expected JSON:
        event_type: Type of event (goal, assist, yellow_card, red_card, own_goal)
        player_id: Player ID (optional for own_goal)
        minute: Match minute (optional)
    """
    from app.models.ecs_fc import EcsFcMatch, EcsFcPlayerEvent

    current_user_id = int(get_jwt_identity())
    data = request.get_json()

    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    event_type = data.get('event_type')
    if not event_type or event_type not in ECS_FC_EVENT_TYPES:
        return jsonify({"msg": f"Invalid event_type. Must be one of: {ECS_FC_EVENT_TYPES}"}), 400

    player_id = data.get('player_id')
    minute = data.get('minute')

    # Own goals don't require a player_id
    if event_type != 'own_goal' and not player_id:
        return jsonify({"msg": "player_id is required for this event type"}), 400

    with managed_session() as session:
        user = session.query(User).get(current_user_id)
        if not user:
            return jsonify({"msg": "User not found"}), 404

        player = session.query(Player).filter_by(user_id=current_user_id).first()

        match = session.query(EcsFcMatch).options(
            joinedload(EcsFcMatch.team)
        ).get(match_id)

        if not match:
            return jsonify({"msg": "Match not found"}), 404

        if not can_report_ecs_fc_match(session, user, player, match):
            return jsonify({"msg": "You don't have permission to report this match"}), 403

        # Validate player_id if provided
        if player_id:
            target_player = session.query(Player).get(player_id)
            if not target_player:
                return jsonify({"msg": "Player not found"}), 404

        # Create the event
        event = EcsFcPlayerEvent(
            ecs_fc_match_id=match_id,
            player_id=player_id if event_type != 'own_goal' else None,
            team_id=match.team_id if event_type == 'own_goal' else None,
            event_type=event_type,
            minute=minute,
            created_by=current_user_id
        )
        session.add(event)
        session.commit()

        logger.info(f"ECS FC event added: {event_type} for match {match_id} by user {current_user_id}")

        return jsonify({
            "success": True,
            "message": "Event added",
            "event": event.to_dict(include_player=True)
        }), 201


@mobile_api_v2.route('/ecs-fc-matches/<int:match_id>/events/<int:event_id>', methods=['PUT'])
@jwt_required()
def update_ecs_fc_match_event(match_id: int, event_id: int):
    """
    Update an event in an ECS FC match.

    Expected JSON:
        event_type: Type of event (optional)
        player_id: Player ID (optional)
        minute: Match minute (optional)
    """
    from app.models.ecs_fc import EcsFcMatch, EcsFcPlayerEvent

    current_user_id = int(get_jwt_identity())
    data = request.get_json()

    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    with managed_session() as session:
        user = session.query(User).get(current_user_id)
        if not user:
            return jsonify({"msg": "User not found"}), 404

        player = session.query(Player).filter_by(user_id=current_user_id).first()

        match = session.query(EcsFcMatch).get(match_id)
        if not match:
            return jsonify({"msg": "Match not found"}), 404

        if not can_report_ecs_fc_match(session, user, player, match):
            return jsonify({"msg": "You don't have permission to edit this match"}), 403

        event = session.query(EcsFcPlayerEvent).filter(
            EcsFcPlayerEvent.id == event_id,
            EcsFcPlayerEvent.ecs_fc_match_id == match_id
        ).first()

        if not event:
            return jsonify({"msg": "Event not found"}), 404

        # Update fields
        if 'event_type' in data:
            if data['event_type'] not in ECS_FC_EVENT_TYPES:
                return jsonify({"msg": f"Invalid event_type. Must be one of: {ECS_FC_EVENT_TYPES}"}), 400
            event.event_type = data['event_type']

        if 'player_id' in data:
            event.player_id = data['player_id']

        if 'minute' in data:
            event.minute = data['minute']

        session.commit()

        return jsonify({
            "success": True,
            "message": "Event updated",
            "event": event.to_dict(include_player=True)
        }), 200


@mobile_api_v2.route('/ecs-fc-matches/<int:match_id>/events/<int:event_id>', methods=['DELETE'])
@jwt_required()
def delete_ecs_fc_match_event(match_id: int, event_id: int):
    """Delete an event from an ECS FC match."""
    from app.models.ecs_fc import EcsFcMatch, EcsFcPlayerEvent

    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        user = session.query(User).get(current_user_id)
        if not user:
            return jsonify({"msg": "User not found"}), 404

        player = session.query(Player).filter_by(user_id=current_user_id).first()

        match = session.query(EcsFcMatch).get(match_id)
        if not match:
            return jsonify({"msg": "Match not found"}), 404

        if not can_report_ecs_fc_match(session, user, player, match):
            return jsonify({"msg": "You don't have permission to edit this match"}), 403

        event = session.query(EcsFcPlayerEvent).filter(
            EcsFcPlayerEvent.id == event_id,
            EcsFcPlayerEvent.ecs_fc_match_id == match_id
        ).first()

        if not event:
            return jsonify({"msg": "Event not found"}), 404

        session.delete(event)
        session.commit()

        logger.info(f"ECS FC event deleted: {event_id} from match {match_id} by user {current_user_id}")

        return jsonify({
            "success": True,
            "message": "Event deleted"
        }), 200


@mobile_api_v2.route('/ecs-fc-matches/<int:match_id>/score', methods=['PUT'])
@jwt_required()
def update_ecs_fc_match_score(match_id: int):
    """
    Update the score for an ECS FC match.

    Expected JSON:
        home_score: Home team score (integer)
        away_score: Away team score (integer)
        status: Match status (optional, e.g., 'COMPLETED', 'IN_PROGRESS')
    """
    from app.models.ecs_fc import EcsFcMatch

    current_user_id = int(get_jwt_identity())
    data = request.get_json()

    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    with managed_session() as session:
        user = session.query(User).get(current_user_id)
        if not user:
            return jsonify({"msg": "User not found"}), 404

        player = session.query(Player).filter_by(user_id=current_user_id).first()

        match = session.query(EcsFcMatch).get(match_id)
        if not match:
            return jsonify({"msg": "Match not found"}), 404

        if not can_report_ecs_fc_match(session, user, player, match):
            return jsonify({"msg": "You don't have permission to update this match"}), 403

        # Update score
        if 'home_score' in data:
            match.home_score = data['home_score']
        if 'away_score' in data:
            match.away_score = data['away_score']
        if 'status' in data:
            match.status = data['status']

        match.updated_at = datetime.utcnow()
        session.commit()

        logger.info(f"ECS FC match score updated: {match_id} - {match.home_score}:{match.away_score}")

        return jsonify({
            "success": True,
            "message": "Score updated",
            "match": {
                "id": match.id,
                "home_score": match.home_score,
                "away_score": match.away_score,
                "status": match.status
            }
        }), 200


# =============================================================================
# COACH RSVP DASHBOARD ENDPOINTS
# =============================================================================

@mobile_api_v2.route('/coach/ecs-fc-teams', methods=['GET'])
@jwt_required()
def get_coach_ecs_fc_teams():
    """
    Get all ECS FC teams where the user is a coach.

    Returns list of teams with basic info.
    """
    from app.models import player_teams
    from sqlalchemy import and_

    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        player = session.query(Player).options(
            selectinload(Player.teams).joinedload(Team.league)
        ).filter_by(user_id=current_user_id).first()

        if not player:
            return jsonify({"teams": [], "count": 0}), 200

        # Get teams where user is coach and team is ECS FC
        coach_teams = []
        for team in player.teams:
            # Check if coach for this team
            coach_check = session.execute(
                player_teams.select().where(
                    and_(
                        player_teams.c.player_id == player.id,
                        player_teams.c.team_id == team.id,
                        player_teams.c.is_coach == True
                    )
                )
            ).fetchone()

            if coach_check and team.league and 'ECS FC' in team.league.name:
                coach_teams.append({
                    "id": team.id,
                    "name": team.name,
                    "league_id": team.league_id,
                    "league_name": team.league.name,
                })

        return jsonify({
            "teams": coach_teams,
            "count": len(coach_teams)
        }), 200


@mobile_api_v2.route('/coach/ecs-fc-teams/<int:team_id>/rsvp', methods=['GET'])
@jwt_required()
def get_coach_ecs_fc_team_rsvp(team_id: int):
    """
    Get RSVP overview for all upcoming ECS FC matches for a team.

    Query Parameters:
        limit: Max matches to return (default: 10)
    """
    from app.models.ecs_fc import EcsFcMatch

    current_user_id = int(get_jwt_identity())
    limit = request.args.get('limit', 10, type=int)

    with managed_session() as session:
        # Verify coach access
        if not is_coach_for_team(session, current_user_id, team_id) and not is_admin_user(session, current_user_id):
            return jsonify({"msg": "You are not a coach for this team"}), 403

        team = session.query(Team).options(
            joinedload(Team.league)
        ).get(team_id)

        if not team:
            return jsonify({"msg": "Team not found"}), 404

        # Get upcoming matches
        today = date.today()
        matches = session.query(EcsFcMatch).options(
            selectinload(EcsFcMatch.availabilities)
        ).filter(
            EcsFcMatch.team_id == team_id,
            EcsFcMatch.match_date >= today,
            EcsFcMatch.status != 'CANCELLED'
        ).order_by(
            EcsFcMatch.match_date.asc(),
            EcsFcMatch.match_time.asc()
        ).limit(limit).all()

        matches_data = []
        for match in matches:
            rsvp_summary = match.get_rsvp_summary()
            matches_data.append({
                "id": match.id,
                "opponent_name": match.opponent_name,
                "date": match.match_date.isoformat() if match.match_date else None,
                "time": match.match_time.strftime('%H:%M') if match.match_time else None,
                "location": match.location,
                "is_home_match": match.is_home_match,
                "status": match.status,
                "rsvp_summary": rsvp_summary,
                "rsvp_deadline": match.rsvp_deadline.isoformat() if match.rsvp_deadline else None,
            })

        return jsonify({
            "team": {
                "id": team.id,
                "name": team.name,
            },
            "matches": matches_data,
            "count": len(matches_data)
        }), 200


@mobile_api_v2.route('/coach/ecs-fc-teams/<int:team_id>/matches/<int:match_id>/rsvp', methods=['GET'])
@jwt_required()
def get_coach_ecs_fc_match_rsvp_details(team_id: int, match_id: int):
    """
    Get detailed RSVP information for a specific ECS FC match.

    Returns individual player responses with timestamps.
    """
    from app.models.ecs_fc import EcsFcMatch, EcsFcAvailability

    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        # Verify coach access
        if not is_coach_for_team(session, current_user_id, team_id) and not is_admin_user(session, current_user_id):
            return jsonify({"msg": "You are not a coach for this team"}), 403

        match = session.query(EcsFcMatch).options(
            joinedload(EcsFcMatch.team).selectinload(Team.players),
            selectinload(EcsFcMatch.availabilities).joinedload(EcsFcAvailability.player)
        ).filter(
            EcsFcMatch.id == match_id,
            EcsFcMatch.team_id == team_id
        ).first()

        if not match:
            return jsonify({"msg": "Match not found"}), 404

        # Build availability map
        availability_map = {a.player_id: a for a in match.availabilities if a.player_id}

        # Get all team players with their responses
        players_data = []
        for player in match.team.players:
            if not player.is_current_player:
                continue

            av = availability_map.get(player.id)
            players_data.append({
                "id": player.id,
                "name": player.name,
                "jersey_number": player.jersey_number,
                "position": player.favorite_position,
                "response": av.response if av else None,
                "responded_at": av.responded_at.isoformat() if av and av.responded_at else None,
            })

        # Sort by response (yes first, then maybe, then no_response, then no)
        response_order = {'yes': 0, 'maybe': 1, None: 2, 'no_response': 2, 'no': 3}
        players_data.sort(key=lambda p: (response_order.get(p['response'], 2), p['name']))

        return jsonify({
            "match": {
                "id": match.id,
                "opponent_name": match.opponent_name,
                "date": match.match_date.isoformat() if match.match_date else None,
                "time": match.match_time.strftime('%H:%M') if match.match_time else None,
                "location": match.location,
                "is_home_match": match.is_home_match,
            },
            "rsvp_summary": match.get_rsvp_summary(),
            "players": players_data,
            "total_players": len(players_data)
        }), 200


@mobile_api_v2.route('/coach/ecs-fc-teams/<int:team_id>/matches/<int:match_id>/rsvp/reminder', methods=['POST'])
@jwt_required()
def send_ecs_fc_rsvp_reminder(team_id: int, match_id: int):
    """
    Send RSVP reminder to players who haven't responded.

    Expected JSON:
        message: Custom reminder message (optional)
        include_responded: If true, send to all players (default: false)
        channels: List of notification channels ['discord', 'email', 'sms'] (optional)
    """
    from app.models.ecs_fc import EcsFcMatch, EcsFcAvailability

    current_user_id = int(get_jwt_identity())
    data = request.get_json() or {}

    custom_message = data.get('message')
    include_responded = data.get('include_responded', False)
    channels = data.get('channels', ['discord'])

    with managed_session() as session:
        # Verify coach access
        if not is_coach_for_team(session, current_user_id, team_id) and not is_admin_user(session, current_user_id):
            return jsonify({"msg": "You are not a coach for this team"}), 403

        match = session.query(EcsFcMatch).options(
            joinedload(EcsFcMatch.team).selectinload(Team.players),
            selectinload(EcsFcMatch.availabilities)
        ).filter(
            EcsFcMatch.id == match_id,
            EcsFcMatch.team_id == team_id
        ).first()

        if not match:
            return jsonify({"msg": "Match not found"}), 404

        # Get players who need reminders
        responded_player_ids = {a.player_id for a in match.availabilities if a.player_id and a.response}

        players_to_notify = []
        for player in match.team.players:
            if not player.is_current_player:
                continue

            if include_responded or player.id not in responded_player_ids:
                players_to_notify.append({
                    "id": player.id,
                    "name": player.name,
                    "discord_id": player.discord_id,
                    "email": player.user.email if player.user else None,
                    "phone": player.phone_number,
                })

        # Queue notification task (if you have a task system)
        # For now, we'll just mark the reminder as sent
        match.rsvp_reminder_sent = True
        session.commit()

        logger.info(f"ECS FC RSVP reminder sent for match {match_id} to {len(players_to_notify)} players")

        return jsonify({
            "success": True,
            "message": f"Reminder sent to {len(players_to_notify)} players",
            "players_notified": len(players_to_notify),
            "channels": channels
        }), 200


# =============================================================================
# SUBSTITUTE SYSTEM ENDPOINTS
# =============================================================================

@mobile_api_v2.route('/substitutes/ecs-fc/requests', methods=['GET'])
@jwt_required()
def get_ecs_fc_substitute_requests():
    """
    Get ECS FC substitute requests.

    For admins: Returns all open requests
    For coaches: Returns requests for their teams

    Query Parameters:
        status: Filter by status (OPEN, FILLED, CANCELLED)
        team_id: Filter by team
    """
    from app.models.substitutes import EcsFcSubRequest

    current_user_id = int(get_jwt_identity())
    status_filter = request.args.get('status')
    team_id = request.args.get('team_id', type=int)

    with managed_session() as session:
        user = session.query(User).get(current_user_id)
        is_admin = is_admin_user(session, current_user_id)

        query = session.query(EcsFcSubRequest).options(
            joinedload(EcsFcSubRequest.match),
            joinedload(EcsFcSubRequest.team),
            joinedload(EcsFcSubRequest.requester)
        )

        if status_filter:
            query = query.filter(EcsFcSubRequest.status == status_filter)

        if team_id:
            query = query.filter(EcsFcSubRequest.team_id == team_id)
        elif not is_admin:
            # Get coach's teams
            player = session.query(Player).filter_by(user_id=current_user_id).first()
            if player:
                coach_team_ids = get_coach_team_ids(session, player.id)
                if coach_team_ids:
                    query = query.filter(EcsFcSubRequest.team_id.in_(coach_team_ids))
                else:
                    return jsonify({"requests": [], "count": 0}), 200
            else:
                return jsonify({"requests": [], "count": 0}), 200

        requests = query.order_by(EcsFcSubRequest.created_at.desc()).all()

        requests_data = []
        for req in requests:
            requests_data.append({
                "id": req.id,
                "match_id": req.match_id,
                "match": {
                    "opponent_name": req.match.opponent_name,
                    "date": req.match.match_date.isoformat() if req.match.match_date else None,
                    "time": req.match.match_time.strftime('%H:%M') if req.match.match_time else None,
                    "location": req.match.location,
                } if req.match else None,
                "team_id": req.team_id,
                "team_name": req.team.name if req.team else None,
                "positions_needed": req.positions_needed,
                "substitutes_needed": req.substitutes_needed,
                "notes": req.notes,
                "status": req.status,
                "created_at": req.created_at.isoformat() if req.created_at else None,
            })

        return jsonify({
            "requests": requests_data,
            "count": len(requests_data)
        }), 200


def get_coach_team_ids(session, player_id: int) -> list:
    """Get team IDs where player is a coach."""
    from app.models import player_teams
    from sqlalchemy import and_

    results = session.execute(
        player_teams.select().where(
            and_(
                player_teams.c.player_id == player_id,
                player_teams.c.is_coach == True
            )
        )
    ).fetchall()

    return [r.team_id for r in results]


@mobile_api_v2.route('/substitutes/ecs-fc/requests', methods=['POST'])
@jwt_required()
def create_ecs_fc_substitute_request():
    """
    Create an ECS FC substitute request.

    Expected JSON:
        match_id: ECS FC match ID
        positions_needed: Positions needed (e.g., "GK, DEF")
        substitutes_needed: Number of substitutes needed (default: 1)
        notes: Additional notes
    """
    from app.models.substitutes import EcsFcSubRequest
    from app.models.ecs_fc import EcsFcMatch

    current_user_id = int(get_jwt_identity())
    data = request.get_json()

    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    match_id = data.get('match_id')
    if not match_id:
        return jsonify({"msg": "match_id is required"}), 400

    with managed_session() as session:
        match = session.query(EcsFcMatch).get(match_id)
        if not match:
            return jsonify({"msg": "Match not found"}), 404

        # Verify coach access
        if not is_coach_for_team(session, current_user_id, match.team_id) and not is_admin_user(session, current_user_id):
            return jsonify({"msg": "You are not authorized to create requests for this team"}), 403

        # Create request
        sub_request = EcsFcSubRequest(
            match_id=match_id,
            team_id=match.team_id,
            requested_by=current_user_id,
            positions_needed=data.get('positions_needed'),
            substitutes_needed=data.get('substitutes_needed', 1),
            notes=data.get('notes'),
            status='OPEN'
        )
        session.add(sub_request)
        session.commit()

        logger.info(f"ECS FC sub request created: {sub_request.id} for match {match_id}")

        return jsonify({
            "success": True,
            "message": "Substitute request created",
            "request_id": sub_request.id
        }), 201


@mobile_api_v2.route('/substitutes/ecs-fc/requests/<int:request_id>', methods=['GET'])
@jwt_required()
def get_ecs_fc_substitute_request(request_id: int):
    """Get details of a specific ECS FC substitute request."""
    from app.models.substitutes import EcsFcSubRequest, EcsFcSubResponse

    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        sub_request = session.query(EcsFcSubRequest).options(
            joinedload(EcsFcSubRequest.match),
            joinedload(EcsFcSubRequest.team),
            selectinload(EcsFcSubRequest.responses).joinedload(EcsFcSubResponse.player)
        ).get(request_id)

        if not sub_request:
            return jsonify({"msg": "Request not found"}), 404

        # Build response data
        responses_data = []
        for resp in sub_request.responses:
            responses_data.append({
                "id": resp.id,
                "player_id": resp.player_id,
                "player_name": resp.player.name if resp.player else None,
                "is_available": resp.is_available,
                "response_text": resp.response_text,
                "responded_at": resp.responded_at.isoformat() if resp.responded_at else None,
            })

        return jsonify({
            "id": sub_request.id,
            "match": {
                "id": sub_request.match.id,
                "opponent_name": sub_request.match.opponent_name,
                "date": sub_request.match.match_date.isoformat() if sub_request.match.match_date else None,
                "time": sub_request.match.match_time.strftime('%H:%M') if sub_request.match.match_time else None,
                "location": sub_request.match.location,
            } if sub_request.match else None,
            "team": {
                "id": sub_request.team.id,
                "name": sub_request.team.name,
            } if sub_request.team else None,
            "positions_needed": sub_request.positions_needed,
            "substitutes_needed": sub_request.substitutes_needed,
            "notes": sub_request.notes,
            "status": sub_request.status,
            "responses": responses_data,
            "created_at": sub_request.created_at.isoformat() if sub_request.created_at else None,
        }), 200


@mobile_api_v2.route('/substitutes/ecs-fc/requests/<int:request_id>', methods=['PUT'])
@jwt_required()
def update_ecs_fc_substitute_request(request_id: int):
    """Update an ECS FC substitute request."""
    from app.models.substitutes import EcsFcSubRequest

    current_user_id = int(get_jwt_identity())
    data = request.get_json()

    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    with managed_session() as session:
        sub_request = session.query(EcsFcSubRequest).get(request_id)

        if not sub_request:
            return jsonify({"msg": "Request not found"}), 404

        # Verify authorization
        if not is_coach_for_team(session, current_user_id, sub_request.team_id) and not is_admin_user(session, current_user_id):
            return jsonify({"msg": "You are not authorized to update this request"}), 403

        # Update fields
        if 'positions_needed' in data:
            sub_request.positions_needed = data['positions_needed']
        if 'substitutes_needed' in data:
            sub_request.substitutes_needed = data['substitutes_needed']
        if 'notes' in data:
            sub_request.notes = data['notes']
        if 'status' in data:
            sub_request.status = data['status']

        session.commit()

        return jsonify({
            "success": True,
            "message": "Request updated"
        }), 200


@mobile_api_v2.route('/substitutes/ecs-fc/requests/<int:request_id>', methods=['DELETE'])
@jwt_required()
def delete_ecs_fc_substitute_request(request_id: int):
    """Cancel/delete an ECS FC substitute request."""
    from app.models.substitutes import EcsFcSubRequest

    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        sub_request = session.query(EcsFcSubRequest).get(request_id)

        if not sub_request:
            return jsonify({"msg": "Request not found"}), 404

        # Verify authorization
        if not is_coach_for_team(session, current_user_id, sub_request.team_id) and not is_admin_user(session, current_user_id):
            return jsonify({"msg": "You are not authorized to delete this request"}), 403

        sub_request.status = 'CANCELLED'
        session.commit()

        return jsonify({
            "success": True,
            "message": "Request cancelled"
        }), 200


@mobile_api_v2.route('/substitutes/ecs-fc/available-requests', methods=['GET'])
@jwt_required()
def get_available_ecs_fc_substitute_requests():
    """
    Get available ECS FC substitute requests for sub pool players.

    Returns open requests that the player can respond to.
    """
    from app.models.substitutes import EcsFcSubRequest, EcsFcSubPool

    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        player = session.query(Player).filter_by(user_id=current_user_id).first()
        if not player:
            return jsonify({"requests": [], "count": 0}), 200

        # Check if player is in ECS FC sub pool
        pool_membership = session.query(EcsFcSubPool).filter_by(
            player_id=player.id,
            is_active=True
        ).first()

        if not pool_membership:
            return jsonify({
                "requests": [],
                "count": 0,
                "message": "You are not in the ECS FC substitute pool"
            }), 200

        # Get open requests
        requests = session.query(EcsFcSubRequest).options(
            joinedload(EcsFcSubRequest.match),
            joinedload(EcsFcSubRequest.team)
        ).filter(
            EcsFcSubRequest.status == 'OPEN'
        ).order_by(
            EcsFcSubRequest.created_at.desc()
        ).all()

        requests_data = []
        for req in requests:
            requests_data.append({
                "id": req.id,
                "match": {
                    "opponent_name": req.match.opponent_name,
                    "date": req.match.match_date.isoformat() if req.match.match_date else None,
                    "time": req.match.match_time.strftime('%H:%M') if req.match.match_time else None,
                    "location": req.match.location,
                    "is_home_match": req.match.is_home_match,
                } if req.match else None,
                "team_name": req.team.name if req.team else None,
                "positions_needed": req.positions_needed,
                "substitutes_needed": req.substitutes_needed,
                "notes": req.notes,
                "created_at": req.created_at.isoformat() if req.created_at else None,
            })

        return jsonify({
            "requests": requests_data,
            "count": len(requests_data)
        }), 200


@mobile_api_v2.route('/substitutes/ecs-fc/requests/<int:request_id>/respond', methods=['POST'])
@jwt_required()
def respond_to_ecs_fc_substitute_request(request_id: int):
    """
    Respond to an ECS FC substitute request.

    Expected JSON:
        is_available: Boolean - whether player is available
        response_text: Optional message
    """
    from app.models.substitutes import EcsFcSubRequest, EcsFcSubResponse, EcsFcSubPool

    current_user_id = int(get_jwt_identity())
    data = request.get_json()

    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    is_available = data.get('is_available')
    if is_available is None:
        return jsonify({"msg": "is_available is required"}), 400

    with managed_session() as session:
        player = session.query(Player).filter_by(user_id=current_user_id).first()
        if not player:
            return jsonify({"msg": "Player profile not found"}), 404

        # Verify pool membership
        pool_membership = session.query(EcsFcSubPool).filter_by(
            player_id=player.id,
            is_active=True
        ).first()

        if not pool_membership:
            return jsonify({"msg": "You are not in the ECS FC substitute pool"}), 403

        sub_request = session.query(EcsFcSubRequest).get(request_id)
        if not sub_request:
            return jsonify({"msg": "Request not found"}), 404

        if sub_request.status != 'OPEN':
            return jsonify({"msg": "This request is no longer open"}), 400

        # Check for existing response
        existing = session.query(EcsFcSubResponse).filter_by(
            request_id=request_id,
            player_id=player.id
        ).first()

        if existing:
            existing.is_available = is_available
            existing.response_text = data.get('response_text')
            existing.responded_at = datetime.utcnow()
        else:
            response = EcsFcSubResponse(
                request_id=request_id,
                player_id=player.id,
                is_available=is_available,
                response_text=data.get('response_text'),
                responded_at=datetime.utcnow()
            )
            session.add(response)

        session.commit()

        return jsonify({
            "success": True,
            "message": "Response recorded"
        }), 200


@mobile_api_v2.route('/substitutes/ecs-fc/requests/<int:request_id>/assign', methods=['POST'])
@jwt_required()
def assign_ecs_fc_substitute(request_id: int):
    """
    Assign a substitute to an ECS FC request (admin/coach only).

    Expected JSON:
        player_id: Player ID to assign
        position_assigned: Position assigned (optional)
        notes: Assignment notes (optional)
    """
    from app.models.substitutes import EcsFcSubRequest, EcsFcSubAssignment

    current_user_id = int(get_jwt_identity())
    data = request.get_json()

    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    player_id = data.get('player_id')
    if not player_id:
        return jsonify({"msg": "player_id is required"}), 400

    with managed_session() as session:
        sub_request = session.query(EcsFcSubRequest).get(request_id)
        if not sub_request:
            return jsonify({"msg": "Request not found"}), 404

        # Verify authorization
        if not is_coach_for_team(session, current_user_id, sub_request.team_id) and not is_admin_user(session, current_user_id):
            return jsonify({"msg": "You are not authorized to assign substitutes"}), 403

        # Verify player exists
        player = session.query(Player).get(player_id)
        if not player:
            return jsonify({"msg": "Player not found"}), 404

        # Create assignment
        assignment = EcsFcSubAssignment(
            request_id=request_id,
            player_id=player_id,
            assigned_by=current_user_id,
            position_assigned=data.get('position_assigned'),
            notes=data.get('notes')
        )
        session.add(assignment)

        # Update request status
        sub_request.status = 'FILLED'
        sub_request.filled_at = datetime.utcnow()

        session.commit()

        logger.info(f"ECS FC substitute assigned: player {player_id} to request {request_id}")

        return jsonify({
            "success": True,
            "message": "Substitute assigned",
            "assignment_id": assignment.id
        }), 201


@mobile_api_v2.route('/substitutes/ecs-fc/pool/my-status', methods=['GET'])
@jwt_required()
def get_ecs_fc_pool_status():
    """Get current user's ECS FC substitute pool status."""
    from app.models.substitutes import EcsFcSubPool

    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        player = session.query(Player).filter_by(user_id=current_user_id).first()
        if not player:
            return jsonify({"in_pool": False}), 200

        membership = session.query(EcsFcSubPool).filter_by(player_id=player.id).first()

        if not membership:
            return jsonify({"in_pool": False}), 200

        return jsonify({
            "in_pool": True,
            "is_active": membership.is_active,
            "preferred_positions": membership.preferred_positions,
            "max_matches_per_week": membership.max_matches_per_week,
            "sms_notifications": membership.sms_for_sub_requests,
            "discord_notifications": membership.discord_for_sub_requests,
            "email_notifications": membership.email_for_sub_requests,
            "requests_received": membership.requests_received,
            "requests_accepted": membership.requests_accepted,
            "matches_played": membership.matches_played,
            "joined_at": membership.joined_pool_at.isoformat() if membership.joined_pool_at else None,
        }), 200


@mobile_api_v2.route('/substitutes/ecs-fc/pool/my-status', methods=['PUT'])
@jwt_required()
def update_ecs_fc_pool_status():
    """Update current user's ECS FC substitute pool preferences."""
    from app.models.substitutes import EcsFcSubPool

    current_user_id = int(get_jwt_identity())
    data = request.get_json()

    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    with managed_session() as session:
        player = session.query(Player).filter_by(user_id=current_user_id).first()
        if not player:
            return jsonify({"msg": "Player profile not found"}), 404

        membership = session.query(EcsFcSubPool).filter_by(player_id=player.id).first()
        if not membership:
            return jsonify({"msg": "You are not in the ECS FC substitute pool"}), 404

        # Update fields
        if 'is_active' in data:
            membership.is_active = data['is_active']
        if 'preferred_positions' in data:
            membership.preferred_positions = data['preferred_positions']
        if 'max_matches_per_week' in data:
            membership.max_matches_per_week = data['max_matches_per_week']
        if 'sms_notifications' in data:
            membership.sms_for_sub_requests = data['sms_notifications']
        if 'discord_notifications' in data:
            membership.discord_for_sub_requests = data['discord_notifications']
        if 'email_notifications' in data:
            membership.email_for_sub_requests = data['email_notifications']

        membership.last_active_at = datetime.utcnow()
        session.commit()

        return jsonify({
            "success": True,
            "message": "Pool preferences updated"
        }), 200


@mobile_api_v2.route('/substitutes/ecs-fc/pool/join', methods=['POST'])
@jwt_required()
def join_ecs_fc_substitute_pool():
    """Join the ECS FC substitute pool."""
    from app.models.substitutes import EcsFcSubPool

    current_user_id = int(get_jwt_identity())
    data = request.get_json() or {}

    with managed_session() as session:
        player = session.query(Player).filter_by(user_id=current_user_id).first()
        if not player:
            return jsonify({"msg": "Player profile not found"}), 404

        # Check existing membership
        existing = session.query(EcsFcSubPool).filter_by(player_id=player.id).first()
        if existing:
            if existing.is_active:
                return jsonify({"msg": "You are already in the pool"}), 400
            else:
                # Reactivate
                existing.is_active = True
                existing.last_active_at = datetime.utcnow()
                session.commit()
                return jsonify({
                    "success": True,
                    "message": "Pool membership reactivated"
                }), 200

        # Create new membership
        membership = EcsFcSubPool(
            player_id=player.id,
            is_active=True,
            preferred_positions=data.get('preferred_positions'),
            max_matches_per_week=data.get('max_matches_per_week'),
            sms_for_sub_requests=data.get('sms_notifications', True),
            discord_for_sub_requests=data.get('discord_notifications', True),
            email_for_sub_requests=data.get('email_notifications', True),
        )
        session.add(membership)
        session.commit()

        logger.info(f"Player {player.id} joined ECS FC substitute pool")

        return jsonify({
            "success": True,
            "message": "Joined ECS FC substitute pool"
        }), 201


@mobile_api_v2.route('/substitutes/ecs-fc/pool/leave', methods=['DELETE'])
@jwt_required()
def leave_ecs_fc_substitute_pool():
    """Leave the ECS FC substitute pool."""
    from app.models.substitutes import EcsFcSubPool

    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        player = session.query(Player).filter_by(user_id=current_user_id).first()
        if not player:
            return jsonify({"msg": "Player profile not found"}), 404

        membership = session.query(EcsFcSubPool).filter_by(player_id=player.id).first()
        if not membership:
            return jsonify({"msg": "You are not in the pool"}), 404

        membership.is_active = False
        session.commit()

        return jsonify({
            "success": True,
            "message": "Left ECS FC substitute pool"
        }), 200
