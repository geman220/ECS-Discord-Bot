# app/mobile_api/referees.py

"""
Mobile API Referee Management Endpoints

Provides referee management functionality for mobile clients:
- Get available referees for a match
- Assign referee to a match
- Remove referee from a match
- View referee's own assignments
"""

import logging
from datetime import datetime, timedelta
from flask import jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy.orm import joinedload, aliased

from app.mobile_api import mobile_api_v2
from app.decorators import jwt_role_required
from app.core.session_manager import managed_session
from app.models import User, Player, Match, Team, Season, player_teams

logger = logging.getLogger(__name__)


@mobile_api_v2.route('/matches/<int:match_id>/available-refs', methods=['GET'])
@jwt_required()
@jwt_role_required(['Pub League Admin', 'Global Admin'])
def get_available_refs_for_match(match_id: int):
    """
    Get available referees for a specific match.
    Filters out refs who:
    - Are on one of the teams playing
    - Are already assigned to another match at the same time
    - Are playing in another match at the same time

    Args:
        match_id: Match ID

    Returns:
        JSON with list of available referees
    """
    with managed_session() as session:
        # Get the match
        match = session.query(Match).options(
            joinedload(Match.home_team),
            joinedload(Match.away_team)
        ).get(match_id)

        if not match:
            return jsonify({"msg": "Match not found"}), 404

        # Get all available refs
        refs = session.query(Player).filter_by(
            is_ref=True,
            is_available_for_ref=True
        ).all()

        available_refs = []
        for ref in refs:
            # Check if ref is on one of the teams
            ref_team_ids = {team.id for team in ref.teams}
            if match.home_team_id in ref_team_ids or match.away_team_id in ref_team_ids:
                continue

            # Check if ref is already assigned to another match at same time
            conflicting_assignment = session.query(Match).filter(
                Match.ref_id == ref.id,
                Match.date == match.date,
                Match.time == match.time,
                Match.id != match_id
            ).first()

            if conflicting_assignment:
                continue

            # Check if ref is playing in another match at same time
            conflicting_player_match = session.query(Match).join(
                player_teams,
                (Match.home_team_id == player_teams.c.team_id) |
                (Match.away_team_id == player_teams.c.team_id)
            ).filter(
                player_teams.c.player_id == ref.id,
                Match.date == match.date,
                Match.time == match.time,
                Match.id != match_id
            ).first()

            if conflicting_player_match:
                continue

            # Count matches assigned in current week
            week_start = match.date - timedelta(days=match.date.weekday()) if match.date else None
            week_end = week_start + timedelta(days=6) if week_start else None

            matches_this_week = 0
            if week_start and week_end:
                matches_this_week = session.query(Match).filter(
                    Match.ref_id == ref.id,
                    Match.date >= week_start,
                    Match.date <= week_end
                ).count()

            total_matches = session.query(Match).filter_by(ref_id=ref.id).count()

            available_refs.append({
                "id": ref.id,
                "name": ref.name,
                "matches_this_week": matches_this_week,
                "total_matches_assigned": total_matches
            })

        # Also include current ref if one is assigned
        current_ref = None
        if match.ref_id:
            ref = session.query(Player).get(match.ref_id)
            if ref:
                current_ref = {
                    "id": ref.id,
                    "name": ref.name
                }

        return jsonify({
            "match_id": match_id,
            "match_date": match.date.isoformat() if match.date else None,
            "match_time": match.time.isoformat() if match.time else None,
            "home_team": match.home_team.name,
            "away_team": match.away_team.name,
            "current_ref": current_ref,
            "available_refs": available_refs
        }), 200


@mobile_api_v2.route('/matches/<int:match_id>/ref', methods=['POST'])
@jwt_required()
@jwt_role_required(['Pub League Admin', 'Global Admin'])
def assign_ref_to_match(match_id: int):
    """
    Assign a referee to a match.

    Args:
        match_id: Match ID

    Expected JSON:
        ref_id: ID of the referee to assign

    Returns:
        JSON with success message
    """
    data = request.get_json()
    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    ref_id = data.get('ref_id')
    if not ref_id:
        return jsonify({"msg": "ref_id is required"}), 400

    with managed_session() as session:
        # Get the match
        match = session.query(Match).get(match_id)
        if not match:
            return jsonify({"msg": "Match not found"}), 404

        # Get the referee
        ref = session.query(Player).get(ref_id)
        if not ref or not ref.is_ref:
            return jsonify({"msg": "Invalid referee"}), 400

        # Check if ref is on one of the teams
        ref_team_ids = {team.id for team in ref.teams}
        if match.home_team_id in ref_team_ids or match.away_team_id in ref_team_ids:
            return jsonify({"msg": "Referee is on one of the teams in this match"}), 400

        # Check for conflicting assignment
        conflicting_match = session.query(Match).filter(
            Match.ref_id == ref_id,
            Match.date == match.date,
            Match.time == match.time,
            Match.id != match_id
        ).first()

        if conflicting_match:
            return jsonify({"msg": "Referee is already assigned to another match at this time"}), 400

        # Check if ref is playing in another match at same time
        conflicting_player_match = session.query(Match).join(
            player_teams,
            (Match.home_team_id == player_teams.c.team_id) |
            (Match.away_team_id == player_teams.c.team_id)
        ).filter(
            player_teams.c.player_id == ref.id,
            Match.date == match.date,
            Match.time == match.time,
            Match.id != match_id
        ).first()

        if conflicting_player_match:
            return jsonify({"msg": "Referee is playing in another match at this time"}), 400

        # Assign referee
        match.ref_id = ref_id
        session.commit()

        logger.info(f"Referee {ref.name} assigned to match {match_id}")

        return jsonify({
            "success": True,
            "message": f"Referee {ref.name} assigned successfully",
            "match_id": match_id,
            "ref": {
                "id": ref.id,
                "name": ref.name
            }
        }), 200


@mobile_api_v2.route('/matches/<int:match_id>/ref', methods=['DELETE'])
@jwt_required()
@jwt_role_required(['Pub League Admin', 'Global Admin'])
def remove_ref_from_match(match_id: int):
    """
    Remove the referee assignment from a match.

    Args:
        match_id: Match ID

    Returns:
        JSON with success message
    """
    with managed_session() as session:
        # Get the match
        match = session.query(Match).get(match_id)
        if not match:
            return jsonify({"msg": "Match not found"}), 404

        if not match.ref_id:
            return jsonify({"msg": "No referee assigned to this match"}), 400

        # Get ref name for response
        ref = session.query(Player).get(match.ref_id)
        ref_name = ref.name if ref else "Unknown"

        # Remove referee
        match.ref_id = None
        session.commit()

        logger.info(f"Referee {ref_name} removed from match {match_id}")

        return jsonify({
            "success": True,
            "message": f"Referee {ref_name} removed from match"
        }), 200


@mobile_api_v2.route('/referees/my-assignments', methods=['GET'])
@jwt_required()
@jwt_role_required(['Pub League Ref', 'Pub League Admin', 'Global Admin'])
def get_my_ref_assignments():
    """
    Get the current user's referee assignments.

    Query Parameters:
        upcoming_only: If 'true', only return upcoming matches (default: true)

    Returns:
        JSON with list of assigned matches
    """
    current_user_id = int(get_jwt_identity())
    upcoming_only = request.args.get('upcoming_only', 'true').lower() == 'true'

    with managed_session() as session:
        # Get user's player record
        player = session.query(Player).filter_by(
            user_id=current_user_id,
            is_ref=True
        ).first()

        if not player:
            return jsonify({"msg": "User is not a referee"}), 404

        # Get current season leagues
        seasons = session.query(Season).options(
            joinedload(Season.leagues)
        ).filter_by(is_current=True).all()

        if not seasons:
            return jsonify({
                "assignments": [],
                "total": 0,
                "message": "No current season found"
            }), 200

        league_ids = [league.id for season in seasons for league in season.leagues]

        # Query for assigned matches
        home_team = aliased(Team)
        away_team = aliased(Team)

        query = session.query(Match).join(
            home_team, Match.home_team_id == home_team.id
        ).join(
            away_team, Match.away_team_id == away_team.id
        ).filter(
            Match.ref_id == player.id,
            home_team.league_id.in_(league_ids)
        )

        if upcoming_only:
            query = query.filter(Match.date >= datetime.now().date())

        query = query.order_by(Match.date.asc(), Match.time.asc())
        matches = query.all()

        assignments = []
        for match in matches:
            assignments.append({
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
                "away_team_score": match.away_team_score,
                "location": match.location if hasattr(match, 'location') else None
            })

        return jsonify({
            "assignments": assignments,
            "total": len(assignments),
            "ref_id": player.id,
            "ref_name": player.name
        }), 200


@mobile_api_v2.route('/referees/availability', methods=['GET'])
@jwt_required()
@jwt_role_required(['Pub League Ref', 'Pub League Admin', 'Global Admin'])
def get_ref_availability():
    """
    Get the current user's referee availability status.

    Returns:
        JSON with availability status
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        player = session.query(Player).filter_by(
            user_id=current_user_id,
            is_ref=True
        ).first()

        if not player:
            return jsonify({"msg": "User is not a referee"}), 404

        return jsonify({
            "ref_id": player.id,
            "ref_name": player.name,
            "is_available_for_ref": player.is_available_for_ref
        }), 200


@mobile_api_v2.route('/referees/availability', methods=['PUT'])
@jwt_required()
@jwt_role_required(['Pub League Ref', 'Pub League Admin', 'Global Admin'])
def update_ref_availability():
    """
    Update the current user's referee availability status.

    Expected JSON:
        is_available: Boolean indicating availability

    Returns:
        JSON with updated availability status
    """
    current_user_id = int(get_jwt_identity())

    data = request.get_json()
    if not data or 'is_available' not in data:
        return jsonify({"msg": "is_available field is required"}), 400

    is_available = bool(data['is_available'])

    with managed_session() as session:
        player = session.query(Player).filter_by(
            user_id=current_user_id,
            is_ref=True
        ).first()

        if not player:
            return jsonify({"msg": "User is not a referee"}), 404

        player.is_available_for_ref = is_available
        session.commit()

        logger.info(f"Referee {player.name} availability updated to {is_available}")

        return jsonify({
            "success": True,
            "ref_id": player.id,
            "ref_name": player.name,
            "is_available_for_ref": player.is_available_for_ref
        }), 200
