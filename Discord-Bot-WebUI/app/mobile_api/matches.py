# app/api/matches.py

"""
Matches API Endpoints

Handles Pub League match-related operations including:
- Match listing (Pub League only — ECS FC matches are served by /api/v1/ecs-fc-matches)
- Match details (with single-id fallthrough to EcsFcMatch for backward compatibility)
- Match events
- Match availability
- Match live updates
"""

import hashlib
import logging
from datetime import datetime, date

from app.utils.pacific_time import pacific_today
from collections import defaultdict

from flask import jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import and_, or_
from sqlalchemy.orm import joinedload, selectinload

from app.mobile_api import mobile_api_v2
from app.core.session_manager import managed_session
from app.models import Match, Player, User, Team
from app.models.ecs_fc import EcsFcMatch, EcsFcAvailability
from app.etag_utils import make_etag_response, CACHE_DURATIONS
from app.app_api_helpers import (
    build_match_response,
    get_match_events,
    get_player_availability,
    get_team_players_availability,
    compute_rsvp_summary,
    build_matches_query,
    process_matches_data,
)

logger = logging.getLogger(__name__)


def normalize_ecs_fc_match(match: EcsFcMatch, player: Player = None,
                           include_availability: bool = False) -> dict:
    """
    Normalize an ECS FC match to the same format as Pub League matches.

    Args:
        match: EcsFcMatch instance
        player: Player instance for availability lookup
        include_availability: Whether to include availability data

    Returns:
        Dict in the same format as Pub League match data
    """
    # Build normalized match data matching Pub League Match.to_dict() field names
    # so the Flutter app can parse both types uniformly
    is_completed = match.status == 'COMPLETED'

    match_data = {
        'id': match.id,
        'match_type': 'ecs_fc',  # Flag to distinguish from pub league
        'date': match.match_date.isoformat() if match.match_date else None,
        'time': match.match_time.isoformat() if match.match_time else None,
        'location': match.location,
        'latitude': match.latitude or 0.0,
        'longitude': match.longitude or 0.0,
        'field': match.field_name or match.location,
        'status': match.status,
        'is_completed': is_completed,
        'notes': match.notes,
        # ECS FC specific fields
        'opponent_name': match.opponent_name,
        'is_home_match': match.is_home_match,
        'home_shirt_color': match.home_shirt_color,
        'away_shirt_color': match.away_shirt_color,
        # Scores - return null when no score entered (not 0)
        'home_score': match.home_score,
        'away_score': match.away_score,
        'home_team_score': match.home_score,
        'away_team_score': match.away_score,
        # Pub league compat fields (Flutter requires non-null team IDs; use 0 for external opponent)
        'home_team_id': match.team_id if match.is_home_match else 0,
        'away_team_id': match.team_id if not match.is_home_match else 0,
        'reported': is_completed,
        'home_team_verified': is_completed,
        'away_team_verified': is_completed,
        'fully_verified': is_completed,
        'schedule_id': None,
        'ref_id': None,
        'week_type': 'REGULAR',
        'is_special_week': False,
        'is_playoff_game': False,
        'playoff_round': None,
        'version': 1,
        'updated_at': None,
        # Team info (ECS FC matches have single team + opponent; use 0 for external opponent ID)
        'home_team': {
            'id': match.team.id if match.is_home_match else 0,
            'name': match.team.name if match.is_home_match else match.opponent_name,
            'league_id': match.team.league_id if match.is_home_match else None
        } if match.team else None,
        'away_team': {
            'id': match.team.id if not match.is_home_match else 0,
            'name': match.opponent_name if match.is_home_match else match.team.name,
            'league_id': match.team.league_id if not match.is_home_match else None
        } if match.team else None,
        # For display purposes
        'team': {
            'id': match.team.id,
            'name': match.team.name,
            'league_id': match.team.league_id
        } if match.team else None,
        # RSVP info
        'rsvp_deadline': match.rsvp_deadline.isoformat() if match.rsvp_deadline else None,
        'rsvp_summary': match.get_rsvp_summary(),
    }

    # Add availability if requested
    if include_availability and player:
        user_availability = next(
            (a for a in match.availabilities if a.player_id == player.id),
            None
        )
        if user_availability:
            match_data['availability'] = {
                'id': user_availability.id,
                'response': user_availability.response,
                'responded_at': user_availability.responded_at.isoformat() if user_availability.responded_at else None
            }
        else:
            match_data['availability'] = None

    return match_data


def query_ecs_fc_matches(session, team_ids: list, upcoming: bool = False,
                         completed: bool = False, limit: int = 50) -> list:
    """
    Query ECS FC matches for given team IDs.

    Args:
        session: Database session
        team_ids: List of team IDs to query
        upcoming: If True, only future matches
        completed: If True, only past matches
        limit: Max matches to return

    Returns:
        List of EcsFcMatch instances
    """
    if not team_ids:
        return []

    query = session.query(EcsFcMatch).options(
        joinedload(EcsFcMatch.team).joinedload(Team.league),
        selectinload(EcsFcMatch.availabilities)
    ).filter(
        EcsFcMatch.team_id.in_(team_ids),
        EcsFcMatch.status != 'CANCELLED'
    )

    today = pacific_today()

    if upcoming:
        query = query.filter(EcsFcMatch.match_date >= today)
        query = query.order_by(EcsFcMatch.match_date.asc(), EcsFcMatch.match_time.asc())
    elif completed:
        query = query.filter(
            or_(
                EcsFcMatch.match_date < today,
                and_(EcsFcMatch.match_date == today, EcsFcMatch.home_score.isnot(None), EcsFcMatch.away_score.isnot(None))
            )
        )
        query = query.order_by(EcsFcMatch.match_date.desc(), EcsFcMatch.match_time.desc())
    else:
        query = query.order_by(EcsFcMatch.match_date.desc(), EcsFcMatch.match_time.desc())

    return query.limit(limit).all()


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
            joinedload(Player.league),
            joinedload(Player.teams).joinedload(Team.league)
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

        include_events = request.args.get('include_events', 'false').lower() == 'true'
        include_availability = request.args.get('include_availability', 'false').lower() == 'true'

        # Query Pub League matches only.
        # ECS FC fixtures are served by /api/v1/ecs-fc-matches; this endpoint
        # used to UNION both tables, which caused multi-league players to see
        # every ECS FC fixture twice (once here, once via /ecs-fc-matches).
        query = build_matches_query(
            team_id=team_id,
            player=player,
            upcoming=upcoming,
            completed=completed,
            all_teams=all_teams,
            limit=limit,
            session=session_db
        )

        pub_matches = query.all()
        logger.info(f"Found {len(pub_matches)} Pub League matches")

        all_matches_data = process_matches_data(
            matches=pub_matches,
            player=player,
            include_events=include_events,
            include_availability=include_availability,
            session=session_db
        )

        # Tag pub league matches so clients can branch on match_type uniformly
        for m in all_matches_data:
            m['match_type'] = 'pub_league'

        # Sort results by date
        def get_sort_key(m):
            date_str = m.get('date')
            time_str = m.get('time', '00:00')
            if date_str:
                try:
                    return datetime.fromisoformat(f"{date_str}T{time_str or '00:00'}")
                except (ValueError, TypeError):
                    return datetime.min
            return datetime.min

        if upcoming:
            all_matches_data.sort(key=get_sort_key)
        else:
            all_matches_data.sort(key=get_sort_key, reverse=True)

        # Apply limit to combined results
        all_matches_data = all_matches_data[:limit]

        logger.info(f"Returning {len(all_matches_data)} Pub League matches")

        cache_duration = CACHE_DURATIONS['match_list'] if not include_availability else 3600
        return make_etag_response(all_matches_data, 'match_list', cache_duration)


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
            joinedload(Player.league),
            joinedload(Player.teams).joinedload(Team.league)
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
            joinedload(Match.away_team),
            joinedload(Match.ref),
        ).get(match_id)

        if not match:
            # Fall through to ECS FC
            ecs_match = session_db.query(EcsFcMatch).options(
                joinedload(EcsFcMatch.team)
            ).get(match_id)
            if not ecs_match:
                return jsonify({"msg": "Match not found"}), 404

            player = session_db.query(Player).filter_by(user_id=current_user_id).first()
            include_availability = request.args.get('include_availability', 'false').lower() == 'true'
            match_data = normalize_ecs_fc_match(
                ecs_match, player=player, include_availability=include_availability
            )
            return jsonify(match_data), 200

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
            if match.home_team:
                match_data['home_team_availability'] = get_team_players_availability(
                    match, match.home_team.players, session=session_db
                )
            if match.away_team:
                match_data['away_team_availability'] = get_team_players_availability(
                    match, match.away_team.players, session=session_db
                )

        include_all_availability = request.args.get('include_all_availability', 'false').lower() == 'true'
        if include_all_availability:
            if match.home_team:
                if 'home_team_availability' in match_data:
                    match_data['home_team_availability_summary'] = compute_rsvp_summary(
                        match_data['home_team_availability']
                    )
                else:
                    home_avail = get_team_players_availability(
                        match, match.home_team.players, session=session_db
                    )
                    match_data['home_team_availability_summary'] = compute_rsvp_summary(home_avail)
            if match.away_team:
                if 'away_team_availability' in match_data:
                    match_data['away_team_availability_summary'] = compute_rsvp_summary(
                        match_data['away_team_availability']
                    )
                else:
                    away_avail = get_team_players_availability(
                        match, match.away_team.players, session=session_db
                    )
                    match_data['away_team_availability_summary'] = compute_rsvp_summary(away_avail)
            if player and 'my_availability' not in match_data:
                match_data['my_availability'] = get_player_availability(
                    match, player, session=session_db
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
            # Fall through to ECS FC
            ecs_match = session_db.query(EcsFcMatch).options(
                joinedload(EcsFcMatch.team),
                joinedload(EcsFcMatch.availabilities)
            ).get(match_id)
            if not ecs_match:
                return jsonify({"msg": "Match not found"}), 404

            player = session_db.query(Player).filter_by(user_id=current_user_id).first()
            team = ecs_match.team

            # Build availability from EcsFcAvailability
            avail_list = []
            if team:
                rsvp_map = {a.player_id: a for a in ecs_match.availabilities}
                for p in team.players:
                    avail = rsvp_map.get(p.id)
                    avail_list.append({
                        'player_id': p.id,
                        'name': p.name,
                        'response': avail.response if avail else None,
                        'responded_at': avail.responded_at.isoformat() if avail and avail.responded_at else None,
                    })

            # ECS FC team as home or away based on is_home_match
            ecs_team_data = {
                'id': team.id if team else 0,
                'name': team.name if team else 'Unknown',
                'availability': avail_list,
            }
            opponent_data = {
                'id': 0,
                'name': ecs_match.opponent_name,
                'availability': [],
            }

            response_data = {
                'match_id': match_id,
                'match_type': 'ecs_fc',
                'home_team': ecs_team_data if ecs_match.is_home_match else opponent_data,
                'away_team': opponent_data if ecs_match.is_home_match else ecs_team_data,
            }

            if player:
                user_avail = next(
                    (a for a in ecs_match.availabilities if a.player_id == player.id),
                    None
                )
                response_data['my_availability'] = {
                    'response': user_avail.response if user_avail else None,
                    'responded_at': user_avail.responded_at.isoformat() if user_avail and user_avail.responded_at else None,
                } if user_avail else None

            return jsonify(response_data), 200

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
