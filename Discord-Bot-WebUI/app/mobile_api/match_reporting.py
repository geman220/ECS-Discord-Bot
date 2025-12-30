# app/mobile_api/match_reporting.py

"""
Mobile API Match Reporting Endpoints

Provides match event reporting functionality for mobile clients:
- Get match info for reporting
- Add/update/delete match events (goals, cards, etc.)
- Update match scores
"""

import logging
from flask import jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy.orm import joinedload
from sqlalchemy import and_

from app.mobile_api import mobile_api_v2
from app.core.session_manager import managed_session
from app.models import User, Player, Team, Match, player_teams
from app.models.stats import PlayerEvent, PlayerEventType

logger = logging.getLogger(__name__)

# Valid event types
VALID_EVENT_TYPES = ['goal', 'assist', 'yellow_card', 'red_card', 'own_goal']


def is_coach_for_match(session, player_id: int, match: Match) -> bool:
    """Check if a player is a coach for either team in a match."""
    coach_check = session.execute(
        player_teams.select().where(
            and_(
                player_teams.c.player_id == player_id,
                player_teams.c.is_coach == True,
                player_teams.c.team_id.in_([match.home_team_id, match.away_team_id])
            )
        )
    ).fetchall()
    return len(coach_check) > 0


def get_coach_team_id(session, player_id: int, match: Match) -> int:
    """Get the team ID for which the player is a coach in this match."""
    coach_check = session.execute(
        player_teams.select().where(
            and_(
                player_teams.c.player_id == player_id,
                player_teams.c.is_coach == True,
                player_teams.c.team_id.in_([match.home_team_id, match.away_team_id])
            )
        )
    ).fetchone()
    return coach_check.team_id if coach_check else None


@mobile_api_v2.route('/matches/<int:match_id>/reporting', methods=['GET'])
@jwt_required()
def get_match_reporting_info(match_id: int):
    """
    Get match information for reporting.
    Returns match details, team rosters, and whether user can edit.

    Args:
        match_id: Match ID

    Returns:
        JSON with match info, rosters, and permissions
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        # Get user and player
        user = session.query(User).get(current_user_id)
        if not user:
            return jsonify({"msg": "User not found"}), 404

        player = session.query(Player).filter_by(user_id=current_user_id).first()
        if not player:
            return jsonify({"msg": "Player profile not found"}), 404

        # Get match with teams
        match = session.query(Match).options(
            joinedload(Match.home_team),
            joinedload(Match.away_team),
            joinedload(Match.events)
        ).get(match_id)

        if not match:
            return jsonify({"msg": "Match not found"}), 404

        # Check if user can report for this match
        can_report = is_coach_for_match(session, player.id, match)
        coach_team_id = get_coach_team_id(session, player.id, match) if can_report else None

        # Get home team roster
        home_players = []
        for p in match.home_team.players:
            if p.is_current_player:
                home_players.append({
                    "id": p.id,
                    "name": p.name,
                    "jersey_number": p.jersey_number,
                    "position": p.favorite_position
                })

        # Get away team roster
        away_players = []
        for p in match.away_team.players:
            if p.is_current_player:
                away_players.append({
                    "id": p.id,
                    "name": p.name,
                    "jersey_number": p.jersey_number,
                    "position": p.favorite_position
                })

        # Get existing events
        events = []
        for event in match.events:
            events.append({
                "id": event.id,
                "event_type": event.event_type.value,
                "player_id": event.player_id,
                "player_name": event.player.name if event.player else None,
                "team_id": event.team_id,
                "minute": event.minute
            })

        return jsonify({
            "match": {
                "id": match.id,
                "date": match.date.isoformat() if match.date else None,
                "time": match.time.isoformat() if match.time else None,
                "home_team": {
                    "id": match.home_team.id,
                    "name": match.home_team.name
                },
                "away_team": {
                    "id": match.away_team.id,
                    "name": match.away_team.name
                },
                "home_team_score": match.home_team_score,
                "away_team_score": match.away_team_score
            },
            "home_roster": home_players,
            "away_roster": away_players,
            "events": events,
            "can_report": can_report,
            "coach_team_id": coach_team_id
        }), 200


@mobile_api_v2.route('/matches/<int:match_id>/events', methods=['GET'])
@jwt_required()
def get_match_events(match_id: int):
    """
    Get all events for a match.

    Args:
        match_id: Match ID

    Returns:
        JSON with list of match events
    """
    with managed_session() as session:
        match = session.query(Match).options(
            joinedload(Match.events).joinedload(PlayerEvent.player)
        ).get(match_id)

        if not match:
            return jsonify({"msg": "Match not found"}), 404

        events = []
        for event in match.events:
            events.append({
                "id": event.id,
                "event_type": event.event_type.value,
                "player_id": event.player_id,
                "player_name": event.player.name if event.player else None,
                "team_id": event.team_id,
                "minute": event.minute
            })

        return jsonify({
            "match_id": match_id,
            "events": events,
            "home_team_score": match.home_team_score,
            "away_team_score": match.away_team_score
        }), 200


@mobile_api_v2.route('/matches/<int:match_id>/events', methods=['POST'])
@jwt_required()
def add_match_event(match_id: int):
    """
    Add a match event (goal, card, etc.).

    Args:
        match_id: Match ID

    Expected JSON:
        event_type: Type of event (goal, assist, yellow_card, red_card, own_goal)
        player_id: ID of player (required except for own_goal)
        team_id: ID of team (required for own_goal)
        minute: Match minute when event occurred (optional)

    Returns:
        JSON with created event
    """
    current_user_id = int(get_jwt_identity())

    data = request.get_json()
    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    event_type = data.get('event_type')
    player_id = data.get('player_id')
    team_id = data.get('team_id')
    minute = data.get('minute')

    # Validate event type
    if not event_type or event_type not in VALID_EVENT_TYPES:
        return jsonify({"msg": f"Invalid event type. Must be one of: {', '.join(VALID_EVENT_TYPES)}"}), 400

    # Validate required fields
    if event_type == 'own_goal':
        if not team_id:
            return jsonify({"msg": "team_id is required for own_goal events"}), 400
    else:
        if not player_id:
            return jsonify({"msg": "player_id is required for this event type"}), 400

    with managed_session() as session:
        # Get current user's player profile
        player = session.query(Player).filter_by(user_id=current_user_id).first()
        if not player:
            return jsonify({"msg": "Player profile not found"}), 404

        # Get match
        match = session.query(Match).get(match_id)
        if not match:
            return jsonify({"msg": "Match not found"}), 404

        # Check authorization
        if not is_coach_for_match(session, player.id, match):
            return jsonify({"msg": "You are not authorized to report events for this match"}), 403

        # Validate player/team belongs to match
        if player_id:
            event_player = session.query(Player).get(player_id)
            if not event_player:
                return jsonify({"msg": "Player not found"}), 404

            # Check player is on one of the match teams
            player_team_ids = {t.id for t in event_player.teams}
            if match.home_team_id not in player_team_ids and match.away_team_id not in player_team_ids:
                return jsonify({"msg": "Player is not on either team in this match"}), 400

        if team_id:
            if team_id not in [match.home_team_id, match.away_team_id]:
                return jsonify({"msg": "Team is not in this match"}), 400

        # Create the event
        event = PlayerEvent(
            match_id=match_id,
            event_type=PlayerEventType(event_type),
            minute=str(minute) if minute else None
        )

        if event_type == 'own_goal':
            event.team_id = team_id
        else:
            event.player_id = player_id

        session.add(event)
        session.commit()

        # Get player name for response
        event_player_name = None
        if event.player_id:
            event_player = session.query(Player).get(event.player_id)
            event_player_name = event_player.name if event_player else None

        return jsonify({
            "success": True,
            "event": {
                "id": event.id,
                "event_type": event.event_type.value,
                "player_id": event.player_id,
                "player_name": event_player_name,
                "team_id": event.team_id,
                "minute": event.minute
            }
        }), 201


@mobile_api_v2.route('/matches/<int:match_id>/events/<int:event_id>', methods=['PUT'])
@jwt_required()
def update_match_event(match_id: int, event_id: int):
    """
    Update a match event.

    Args:
        match_id: Match ID
        event_id: Event ID

    Expected JSON:
        player_id: New player ID (optional)
        team_id: New team ID (optional, for own_goal)
        minute: New minute (optional)

    Returns:
        JSON with updated event
    """
    current_user_id = int(get_jwt_identity())

    data = request.get_json()
    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    with managed_session() as session:
        # Get current user's player profile
        player = session.query(Player).filter_by(user_id=current_user_id).first()
        if not player:
            return jsonify({"msg": "Player profile not found"}), 404

        # Get event
        event = session.query(PlayerEvent).filter_by(
            id=event_id,
            match_id=match_id
        ).first()

        if not event:
            return jsonify({"msg": "Event not found"}), 404

        # Get match
        match = session.query(Match).get(match_id)
        if not match:
            return jsonify({"msg": "Match not found"}), 404

        # Check authorization
        if not is_coach_for_match(session, player.id, match):
            return jsonify({"msg": "You are not authorized to update events for this match"}), 403

        # Update fields
        if 'player_id' in data:
            new_player_id = data['player_id']
            if new_player_id:
                event_player = session.query(Player).get(new_player_id)
                if not event_player:
                    return jsonify({"msg": "Player not found"}), 404
                event.player_id = new_player_id
            else:
                event.player_id = None

        if 'team_id' in data:
            event.team_id = data['team_id']

        if 'minute' in data:
            event.minute = str(data['minute']) if data['minute'] else None

        session.commit()

        # Get player name for response
        event_player_name = None
        if event.player_id:
            event_player = session.query(Player).get(event.player_id)
            event_player_name = event_player.name if event_player else None

        return jsonify({
            "success": True,
            "event": {
                "id": event.id,
                "event_type": event.event_type.value,
                "player_id": event.player_id,
                "player_name": event_player_name,
                "team_id": event.team_id,
                "minute": event.minute
            }
        }), 200


@mobile_api_v2.route('/matches/<int:match_id>/events/<int:event_id>', methods=['DELETE'])
@jwt_required()
def delete_match_event(match_id: int, event_id: int):
    """
    Delete a match event.

    Args:
        match_id: Match ID
        event_id: Event ID

    Returns:
        JSON with success message
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        # Get current user's player profile
        player = session.query(Player).filter_by(user_id=current_user_id).first()
        if not player:
            return jsonify({"msg": "Player profile not found"}), 404

        # Get event
        event = session.query(PlayerEvent).filter_by(
            id=event_id,
            match_id=match_id
        ).first()

        if not event:
            return jsonify({"msg": "Event not found"}), 404

        # Get match
        match = session.query(Match).get(match_id)
        if not match:
            return jsonify({"msg": "Match not found"}), 404

        # Check authorization
        if not is_coach_for_match(session, player.id, match):
            return jsonify({"msg": "You are not authorized to delete events for this match"}), 403

        event_type = event.event_type.value
        session.delete(event)
        session.commit()

        return jsonify({
            "success": True,
            "message": f"Event ({event_type}) deleted successfully"
        }), 200


@mobile_api_v2.route('/report_match/<int:match_id>', methods=['POST'])
@jwt_required()
def report_match(match_id: int):
    """
    Submit a complete match report with score and events.

    This is the final submission endpoint that marks the match as reported.

    Args:
        match_id: Match ID

    Expected JSON:
        home_team_score: Final home team score (required)
        away_team_score: Final away team score (required)
        notes: Optional match notes
        events: Optional list of events to add
            Each event: { player_id, event_type, minute, team_id (for own_goal) }

    Returns:
        JSON with reported match details
    """
    current_user_id = int(get_jwt_identity())

    data = request.get_json()
    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    home_score = data.get('home_team_score')
    away_score = data.get('away_team_score')

    if home_score is None or away_score is None:
        return jsonify({"msg": "Both home_team_score and away_team_score are required"}), 400

    try:
        home_score = int(home_score)
        away_score = int(away_score)
    except (ValueError, TypeError):
        return jsonify({"msg": "Scores must be integers"}), 400

    if home_score < 0 or away_score < 0:
        return jsonify({"msg": "Scores cannot be negative"}), 400

    with managed_session() as session:
        # Get current user's player profile
        player = session.query(Player).filter_by(user_id=current_user_id).first()
        if not player:
            return jsonify({"msg": "Player profile not found"}), 404

        # Get match with teams
        match = session.query(Match).options(
            joinedload(Match.home_team),
            joinedload(Match.away_team)
        ).get(match_id)

        if not match:
            return jsonify({"msg": "Match not found"}), 404

        # Check authorization
        if not is_coach_for_match(session, player.id, match):
            return jsonify({"msg": "You are not authorized to report this match"}), 403

        # Update scores
        match.home_team_score = home_score
        match.away_team_score = away_score
        match.reported = True

        # Add notes if provided
        notes = data.get('notes')
        if notes:
            match.notes = notes

        # Add events if provided
        events_data = data.get('events', [])
        created_events = []

        for event_data in events_data:
            event_type = event_data.get('event_type')
            if not event_type or event_type not in VALID_EVENT_TYPES:
                continue  # Skip invalid events

            event = PlayerEvent(
                match_id=match_id,
                event_type=PlayerEventType(event_type),
                minute=str(event_data.get('minute')) if event_data.get('minute') else None
            )

            if event_type == 'own_goal':
                event.team_id = event_data.get('team_id')
            else:
                event.player_id = event_data.get('player_id')

            session.add(event)
            created_events.append({
                "event_type": event_type,
                "player_id": event.player_id,
                "team_id": event.team_id,
                "minute": event.minute
            })

        session.commit()

        logger.info(f"Match {match_id} reported by user {current_user_id}: {home_score}-{away_score}")

        return jsonify({
            "success": True,
            "msg": "Match reported successfully",
            "match": {
                "id": match.id,
                "date": match.date.isoformat() if match.date else None,
                "home_team": {
                    "id": match.home_team.id,
                    "name": match.home_team.name
                },
                "away_team": {
                    "id": match.away_team.id,
                    "name": match.away_team.name
                },
                "home_team_score": match.home_team_score,
                "away_team_score": match.away_team_score,
                "reported": match.reported,
                "notes": match.notes
            },
            "events_created": len(created_events)
        }), 200


@mobile_api_v2.route('/matches/<int:match_id>/score', methods=['PUT'])
@jwt_required()
def update_match_score(match_id: int):
    """
    Update the final score for a match.

    Args:
        match_id: Match ID

    Expected JSON:
        home_team_score: Home team score
        away_team_score: Away team score

    Returns:
        JSON with updated match
    """
    current_user_id = int(get_jwt_identity())

    data = request.get_json()
    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    home_score = data.get('home_team_score')
    away_score = data.get('away_team_score')

    if home_score is None or away_score is None:
        return jsonify({"msg": "Both home_team_score and away_team_score are required"}), 400

    try:
        home_score = int(home_score)
        away_score = int(away_score)
    except (ValueError, TypeError):
        return jsonify({"msg": "Scores must be integers"}), 400

    if home_score < 0 or away_score < 0:
        return jsonify({"msg": "Scores cannot be negative"}), 400

    with managed_session() as session:
        # Get current user's player profile
        player = session.query(Player).filter_by(user_id=current_user_id).first()
        if not player:
            return jsonify({"msg": "Player profile not found"}), 404

        # Get match
        match = session.query(Match).options(
            joinedload(Match.home_team),
            joinedload(Match.away_team)
        ).get(match_id)

        if not match:
            return jsonify({"msg": "Match not found"}), 404

        # Check authorization
        if not is_coach_for_match(session, player.id, match):
            return jsonify({"msg": "You are not authorized to update scores for this match"}), 403

        # Update scores
        match.home_team_score = home_score
        match.away_team_score = away_score
        session.commit()

        return jsonify({
            "success": True,
            "match": {
                "id": match.id,
                "home_team": {
                    "id": match.home_team.id,
                    "name": match.home_team.name
                },
                "away_team": {
                    "id": match.away_team.id,
                    "name": match.away_team.name
                },
                "home_team_score": match.home_team_score,
                "away_team_score": match.away_team_score
            }
        }), 200
