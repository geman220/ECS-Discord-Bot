# app/api/matches.py

"""
Matches API Endpoints

Handles match-related operations including:
- Match listing
- Match details
- Match events
- Match availability
- Match live updates
"""

import hashlib
import logging
from datetime import datetime
from collections import defaultdict

from flask import jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy.orm import joinedload

from app.mobile_api import mobile_api_v2
from app.core.session_manager import managed_session
from app.models import Match, Player, User
from app.etag_utils import make_etag_response, CACHE_DURATIONS
from app.app_api_helpers import (
    build_match_response,
    get_match_events,
    get_player_availability,
    get_team_players_availability,
    build_matches_query,
    process_matches_data,
)

logger = logging.getLogger(__name__)


@mobile_api_v2.route('/matches', methods=['GET'])
@jwt_required()
def get_all_matches():
    """
    Retrieve a list of matches based on query parameters.

    Query parameters:
        upcoming: If 'true', return future matches only
        completed: If 'true', return past matches only
        team_id: Filter by specific team
        all_teams: If 'true', include all user's teams
        include_events: If 'true', include match events
        include_availability: If 'true', include RSVP data
        limit: Maximum number of matches

    Returns:
        JSON list of matches
    """
    current_user_id = int(get_jwt_identity())
    logger.info(f"get_all_matches called for user_id: {current_user_id}")

    with managed_session() as session_db:
        # Get user with roles for access level determination
        user = session_db.query(User).options(
            joinedload(User.roles)
        ).filter(User.id == current_user_id).first()

        player = session_db.query(Player).options(
            joinedload(Player.primary_team),
            joinedload(Player.league)
        ).filter_by(user_id=current_user_id).first()

        # Get query parameters
        upcoming = request.args.get('upcoming', 'false').lower() == 'true'
        completed = request.args.get('completed', 'false').lower() == 'true'
        team_id = request.args.get('team_id', type=int)

        # Smart default for all_teams
        all_teams_param = request.args.get('all_teams')
        if all_teams_param is None:
            all_teams = player and len(player.teams) > 1
        else:
            all_teams = all_teams_param.lower() == 'true'

        # Determine user access level for smart limits
        user_roles = [r.name for r in user.roles] if user.roles else []
        is_admin = any(r in ['Global Admin', 'Admin'] for r in user_roles)
        is_league_admin = any('admin' in r.lower() for r in user_roles)
        is_coach = 'Coach' in user_roles or (player and player.is_coach)

        # Set reasonable default limits based on role
        limit = request.args.get('limit')
        if limit and limit.isdigit():
            limit = min(int(limit), 200 if is_admin else 100)
        else:
            if team_id:
                limit = 50
            elif is_admin:
                limit = 45 if not (completed or upcoming or all_teams) else 60
            elif is_league_admin or is_coach:
                limit = 25 if not (completed or upcoming or all_teams) else 35
            else:
                limit = 15 if not (completed or upcoming or all_teams) else 20

        query = build_matches_query(
            team_id=request.args.get('team_id'),
            player=player,
            upcoming=upcoming,
            completed=completed,
            all_teams=all_teams,
            limit=limit,
            session=session_db
        )

        matches = query.all()
        logger.info(f"Found {len(matches)} matches")

        include_events = request.args.get('include_events', 'false').lower() == 'true'
        include_availability = request.args.get('include_availability', 'false').lower() == 'true'

        matches_data = process_matches_data(
            matches=matches,
            player=player,
            include_events=include_events,
            include_availability=include_availability,
            session=session_db
        )

        cache_duration = CACHE_DURATIONS['match_list'] if not include_availability else 3600
        return make_etag_response(matches_data, 'match_list', cache_duration)


@mobile_api_v2.route('/matches/schedule', methods=['GET'])
@jwt_required()
def get_match_schedule():
    """
    Retrieve the schedule of upcoming matches, grouped by date.

    Query parameters:
        team_id: Filter by specific team
        limit: Maximum number of matches
        include_availability: If 'true', include RSVP data

    Returns:
        JSON object with matches grouped by date
    """
    current_user_id = int(get_jwt_identity())
    logger.info(f"get_match_schedule called for user_id: {current_user_id}")

    with managed_session() as session_db:
        user = session_db.query(User).options(
            joinedload(User.roles)
        ).filter(User.id == current_user_id).first()

        player = session_db.query(Player).options(
            joinedload(Player.primary_team),
            joinedload(Player.league)
        ).filter_by(user_id=current_user_id).first()

        # Determine user access level
        user_roles = [r.name for r in user.roles] if user.roles else []
        is_admin = any(r in ['Global Admin', 'Admin'] for r in user_roles)
        is_league_admin = any('admin' in r.lower() for r in user_roles)
        is_coach = 'Coach' in user_roles or (player and player.is_coach)

        team_id = request.args.get('team_id', type=int)
        requested_limit = request.args.get('limit', type=int)

        # Set limits based on role
        if requested_limit:
            limit = min(requested_limit, 200 if is_admin else 100)
        elif team_id:
            limit = 50
        elif is_admin:
            limit = 75
        elif is_league_admin or is_coach:
            limit = 50
        else:
            limit = 25

        # Check cache for non-personalized queries
        include_availability = request.args.get('include_availability', 'true').lower() == 'true'
        if not (player and include_availability):
            from app.performance_cache import cache_match_results
            cache_params = f"schedule_{team_id or 'all'}_{limit}"
            cache_key = hashlib.md5(cache_params.encode()).hexdigest()
            cached_matches = cache_match_results(league_id=f"schedule_{cache_key}")

            if cached_matches:
                return jsonify(cached_matches), 200

        # Build query for upcoming matches
        query = build_matches_query(
            team_id=team_id,
            player=player,
            upcoming=True,
            session=session_db
        )

        query = query.order_by(Match.date.asc()).limit(limit)
        matches = query.all()

        # Group matches by date
        matches_by_date = defaultdict(list)
        for match in matches:
            match_data = build_match_response(
                match=match,
                include_events=False,
                include_teams=True,
                include_players=False,
                current_player=player if include_availability else None,
                session=session_db
            )
            if include_availability and player:
                match_data['my_availability'] = get_player_availability(
                    match, player, session=session_db
                )
            date_key = match.date.isoformat() if match.date else 'unknown'
            matches_by_date[date_key].append(match_data)

        # Convert to list format
        schedule = [
            {"date": date, "matches": matches_list}
            for date, matches_list in sorted(matches_by_date.items())
        ]

        return jsonify({"schedule": schedule}), 200


@mobile_api_v2.route('/matches/<int:match_id>', methods=['GET'])
@jwt_required()
def get_single_match_details(match_id: int):
    """
    Retrieve details for a specific match.

    Query parameters:
        include_events: If 'true', include match events
        include_availability: If 'true', include RSVP data

    Returns:
        JSON with match details
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session_db:
        match = session_db.query(Match).options(
            joinedload(Match.home_team),
            joinedload(Match.away_team)
        ).get(match_id)

        if not match:
            return jsonify({"msg": "Match not found"}), 404

        include_events = request.args.get('include_events', 'false').lower() == 'true'
        include_teams = request.args.get('include_teams', 'true').lower() == 'true'
        include_players = request.args.get('include_players', 'false').lower() == 'true'
        include_availability = request.args.get('include_availability', 'false').lower() == 'true'

        player = session_db.query(Player).filter_by(user_id=current_user_id).first()

        match_data = build_match_response(
            match=match,
            include_events=include_events,
            include_teams=include_teams,
            include_players=include_players,
            current_player=player,
            session=session_db
        )

        if include_availability and player:
            match_data['my_availability'] = get_player_availability(
                match, player, session=session_db
            )
            # Get both teams' availability
            if match.home_team:
                match_data['home_team_availability'] = get_team_players_availability(
                    match, match.home_team.players, session=session_db
                )
            if match.away_team:
                match_data['away_team_availability'] = get_team_players_availability(
                    match, match.away_team.players, session=session_db
                )

        return jsonify(match_data), 200


@mobile_api_v2.route('/matches/<int:match_id>/events', methods=['GET'])
@jwt_required()
def get_match_events_endpoint(match_id: int):
    """
    Retrieve events for a specific match.

    Returns:
        JSON list of match events
    """
    with managed_session() as session_db:
        match = session_db.query(Match).options(
            joinedload(Match.events)
        ).get(match_id)
        if not match:
            return jsonify({"msg": "Match not found"}), 404

        events_data = get_match_events(match)
        return jsonify({"match_id": match_id, **events_data}), 200


@mobile_api_v2.route('/matches/<int:match_id>/availability', methods=['GET'])
@jwt_required()
def get_match_availability(match_id: int):
    """
    Retrieve availability/RSVP status for a match.

    Returns:
        JSON with player availability and team summaries
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session_db:
        match = session_db.query(Match).options(
            joinedload(Match.home_team),
            joinedload(Match.away_team)
        ).get(match_id)

        if not match:
            return jsonify({"msg": "Match not found"}), 404

        player = session_db.query(Player).filter_by(user_id=current_user_id).first()

        response_data = {
            "match_id": match_id,
            "home_team": {
                "id": match.home_team_id,
                "name": match.home_team.name if match.home_team else None,
                "availability": get_team_players_availability(
                    match, match.home_team.players if match.home_team else [], session=session_db
                )
            },
            "away_team": {
                "id": match.away_team_id,
                "name": match.away_team.name if match.away_team else None,
                "availability": get_team_players_availability(
                    match, match.away_team.players if match.away_team else [], session=session_db
                )
            }
        }

        if player:
            response_data['my_availability'] = get_player_availability(
                match, player, session=session_db
            )

        return jsonify(response_data), 200


@mobile_api_v2.route('/matches/<int:match_id>/live_updates', methods=['GET'])
@jwt_required()
def get_match_live_updates(match_id: int):
    """
    Retrieve live updates for a match (for real-time reporting).

    Returns:
        JSON with match status and recent events
    """
    with managed_session() as session_db:
        match = session_db.query(Match).options(
            joinedload(Match.events)
        ).get(match_id)
        if not match:
            return jsonify({"msg": "Match not found"}), 404

        # Get recent events
        events_data = get_match_events(match)
        events_list = events_data.get('events', [])

        return jsonify({
            "match_id": match_id,
            "status": match.status if hasattr(match, 'status') else None,
            "home_score": match.home_team_score,
            "away_score": match.away_team_score,
            "events": events_list[-10:] if events_list else [],  # Last 10 events
            "last_updated": datetime.utcnow().isoformat()
        }), 200
