# app/api/teams.py

"""
Teams API Endpoints

Handles team-related operations including:
- Team listing
- Team details
- Team rosters
- Team matches
- Team statistics
- My team(s) endpoints
"""

import hashlib
import logging
from datetime import datetime

from flask import jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import or_
from sqlalchemy.orm import joinedload, selectinload

from app.mobile_api import mobile_api_v2
from app.core.session_manager import managed_session
from app.models import Team, League, Season, Match, Player, player_teams
from app.models.ecs_fc import EcsFcMatch, EcsFcAvailability
from app.etag_utils import make_etag_response, CACHE_DURATIONS
from app.app_api_helpers import (
    build_match_response,
    get_team_players_availability,
    get_match_events,
    get_player_availability,
    get_team_upcoming_matches,
)

logger = logging.getLogger(__name__)


@mobile_api_v2.route('/teams', methods=['GET'])
@jwt_required()
def get_teams():
    """
    Retrieve a list of teams for the current season with associated league names.

    Returns:
        JSON list of teams with league information
    """
    with managed_session() as session_db:
        # Retrieve current seasons for Pub League and ECS FC
        current_pub_season = session_db.query(Season).filter_by(
            is_current=True, league_type='Pub League'
        ).first()
        current_ecs_season = session_db.query(Season).filter_by(
            is_current=True, league_type='ECS FC'
        ).first()

        # Build conditions based on which current seasons exist
        conditions = []
        if current_pub_season:
            conditions.append(League.season_id == current_pub_season.id)
        if current_ecs_season:
            conditions.append(League.season_id == current_ecs_season.id)

        # Query teams with eager loading to prevent N+1 queries
        teams_query = session_db.query(Team).join(
            League, Team.league_id == League.id
        ).options(joinedload(Team.league))

        if len(conditions) == 1:
            teams_query = teams_query.filter(conditions[0])
        elif len(conditions) == 2:
            teams_query = teams_query.filter(or_(*conditions))

        teams = teams_query.order_by(Team.name).all()

        # Check cache first
        from app.performance_cache import cache_match_results, set_match_results_cache

        cache_key_data = f"{request.args.get('league_id', 'all')}:{request.args.get('season_id', 'current')}"
        cache_hash = hashlib.md5(cache_key_data.encode()).hexdigest()

        cached_teams = cache_match_results(league_id=f"teams_{cache_hash}")

        if cached_teams:
            teams_data = cached_teams
        else:
            # Preload team stats to avoid N+1 queries
            from app.team_performance_helpers import preload_team_stats_for_request
            team_ids = [team.id for team in teams]
            preload_team_stats_for_request(team_ids)

            teams_data = [
                {
                    **team.to_dict(),
                    'league_name': team.league.name if team.league else "Unknown League"
                }
                for team in teams
            ]

            # Cache the results for 10 minutes
            set_match_results_cache(teams_data, league_id=f"teams_{cache_hash}", ttl=600)

        return make_etag_response(teams_data, 'team_list', CACHE_DURATIONS['team_list'])


@mobile_api_v2.route('/teams/<int:team_id>', methods=['GET'])
@jwt_required()
def get_team_details(team_id: int):
    """
    Retrieve details for a specific team.

    Query parameters:
        include_players: If 'true', include roster
        include_matches: If 'true', include upcoming matches

    Returns:
        JSON with team details
    """
    with managed_session() as session_db:
        team = session_db.query(Team).get(team_id)
        if not team:
            return jsonify({"msg": "Team not found"}), 404

        include_players = request.args.get('include_players', 'false').lower() == 'true'
        team_data = team.to_dict(include_players=include_players)

        base_url = request.host_url.rstrip('/')
        if team_data.get('logo_url') and not team_data['logo_url'].startswith('http'):
            team_data['logo_url'] = f"{base_url}{team_data['logo_url']}"

        if request.args.get('include_matches', 'false').lower() == 'true':
            team_data['upcoming_matches'] = get_team_upcoming_matches(team_id, session=session_db)

        return jsonify(team_data), 200


@mobile_api_v2.route('/teams/<int:team_id>/players', methods=['GET'])
@jwt_required()
def get_team_players(team_id: int):
    """
    Retrieve roster details for a specific team.

    Returns:
        JSON with team info and list of players
    """
    with managed_session() as session_db:
        team = session_db.query(Team).get(team_id)
        if not team:
            return jsonify({"msg": "Team not found"}), 404

        # Fetch players with coach status in single query (prevents N+1)
        players_with_coach_status = (
            session_db.query(Player, player_teams.c.is_coach)
            .join(player_teams)
            .filter(player_teams.c.team_id == team_id)
            .order_by(Player.name)
            .all()
        )

        base_url = request.host_url.rstrip('/')
        default_image = f"{base_url}/static/img/default_player.png"

        detailed_players = []
        for player, is_coach in players_with_coach_status:
            profile_picture_url = player.profile_picture_url
            if profile_picture_url:
                full_profile_picture_url = (
                    profile_picture_url if profile_picture_url.startswith('http')
                    else f"{base_url}{profile_picture_url}"
                )
            else:
                full_profile_picture_url = default_image

            player_data = {
                "id": player.id,
                "name": player.name,
                "jersey_number": player.jersey_number,
                "is_coach": bool(is_coach),
                "is_ref": player.is_ref,
                "is_current_player": player.is_current_player,
                "favorite_position": player.favorite_position,
                "profile_picture_url": full_profile_picture_url,
                "discord_id": player.discord_id,
                "is_primary_team": (player.primary_team_id == team_id)
            }
            detailed_players.append(player_data)

        return jsonify({
            "team": {
                "id": team.id,
                "name": team.name,
                "logo_url": (
                    team.kit_url if team.kit_url and team.kit_url.startswith('http')
                    else f"{base_url}{team.kit_url}" if team.kit_url else None
                )
            },
            "players": detailed_players
        }), 200


@mobile_api_v2.route('/teams/<int:team_id>/matches', methods=['GET'])
@jwt_required()
def get_team_matches(team_id: int):
    """
    Retrieve matches for a specific team.

    Supports both Pub League teams and ECS FC teams.

    Query parameters:
        upcoming: If 'true', only return future matches
        completed: If 'true', only return past matches
        include_events: If 'true', include match events
        include_availability: If 'true', include RSVP data
        limit: Maximum number of matches to return

    Returns:
        JSON list of matches
    """
    current_user_id = int(get_jwt_identity())
    logger.info(f"get_team_matches called for team_id: {team_id}, user_id: {current_user_id}")

    with managed_session() as session_db:
        team = session_db.query(Team).options(
            joinedload(Team.league)
        ).get(team_id)
        if not team:
            return jsonify({"msg": "Team not found"}), 404

        # Get optional parameters
        upcoming = request.args.get('upcoming', 'false').lower() == 'true'
        completed = request.args.get('completed', 'false').lower() == 'true'
        include_events = request.args.get('include_events', 'false').lower() == 'true'
        include_availability = request.args.get('include_availability', 'false').lower() == 'true'
        limit = request.args.get('limit')
        if limit and limit.isdigit():
            limit = int(limit)
        else:
            limit = 50  # Default limit

        # Get player for availability data
        player = None
        if include_availability and current_user_id:
            player = session_db.query(Player).filter_by(user_id=current_user_id).first()

        matches_data = []

        # Check if this is an ECS FC team
        is_ecs_fc = team.league and 'ECS FC' in team.league.name

        if is_ecs_fc:
            # Query ECS FC matches
            query = session_db.query(EcsFcMatch).options(
                joinedload(EcsFcMatch.team).joinedload(Team.league),
                selectinload(EcsFcMatch.availabilities).joinedload(EcsFcAvailability.player)
            ).filter(
                EcsFcMatch.team_id == team_id,
                EcsFcMatch.status != 'CANCELLED'
            )

            # Apply upcoming/completed filters
            today = datetime.now().date()
            if upcoming:
                query = query.filter(EcsFcMatch.match_date >= today)
                query = query.order_by(EcsFcMatch.match_date.asc(), EcsFcMatch.match_time.asc())
            elif completed:
                query = query.filter(EcsFcMatch.match_date < today)
                query = query.order_by(EcsFcMatch.match_date.desc(), EcsFcMatch.match_time.desc())
            else:
                query = query.order_by(EcsFcMatch.match_date.desc(), EcsFcMatch.match_time.desc())

            if limit:
                query = query.limit(limit)

            ecs_matches = query.all()

            for match in ecs_matches:
                match_data = {
                    'id': match.id,
                    'match_type': 'ecs_fc',
                    'date': match.match_date.isoformat() if match.match_date else None,
                    'time': match.match_time.strftime('%H:%M') if match.match_time else None,
                    'location': match.location,
                    'field': match.field_name or match.location,
                    'status': match.status,
                    'notes': match.notes,
                    'opponent_name': match.opponent_name,
                    'is_home_match': match.is_home_match,
                    'home_shirt_color': match.home_shirt_color,
                    'away_shirt_color': match.away_shirt_color,
                    'home_score': match.home_score,
                    'away_score': match.away_score,
                    'home_team': {
                        'id': match.team.id,
                        'name': match.team.name if match.is_home_match else match.opponent_name,
                        'league_id': match.team.league_id
                    } if match.team else None,
                    'away_team': {
                        'id': None,
                        'name': match.opponent_name if match.is_home_match else match.team.name,
                        'league_id': None
                    } if match.team else None,
                    'team': {
                        'id': match.team.id,
                        'name': match.team.name,
                        'league_id': match.team.league_id
                    } if match.team else None,
                    'rsvp_deadline': match.rsvp_deadline.isoformat() if match.rsvp_deadline else None,
                    'rsvp_summary': match.get_rsvp_summary(),
                }

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
                        match_data['my_availability'] = user_availability.response
                    else:
                        match_data['availability'] = None
                        match_data['my_availability'] = None

                matches_data.append(match_data)
        else:
            # Query Pub League matches
            query = session_db.query(Match).options(
                joinedload(Match.home_team),
                joinedload(Match.away_team)
            ).filter(
                or_(Match.home_team_id == team_id, Match.away_team_id == team_id)
            )

            # Apply upcoming/completed filters
            if upcoming:
                query = query.filter(Match.date >= datetime.now().date())
            if completed:
                query = query.filter(Match.date < datetime.now().date())

            # Order by date
            query = query.order_by(Match.date.desc() if completed else Match.date.asc())

            if limit:
                query = query.limit(limit)

            matches = query.all()

            for match in matches:
                match_data = build_match_response(
                    match=match,
                    include_events=include_events,
                    include_teams=True,
                    include_players=False,
                    current_player=player,
                    session=session_db
                )
                match_data['match_type'] = 'pub_league'

                if include_availability and player:
                    match_data['my_availability'] = get_player_availability(
                        match, player, session=session_db
                    )
                    match_data['team_availability'] = get_team_players_availability(
                        match, team.players, session=session_db
                    )

                matches_data.append(match_data)

        return jsonify(matches_data), 200


@mobile_api_v2.route('/teams/<int:team_id>/stats', methods=['GET'])
@jwt_required()
def get_team_stats(team_id: int):
    """
    Retrieve detailed statistics for a specific team, including standings.

    Returns:
        JSON with team statistics
    """
    from sqlalchemy import func
    from app.models import Standings, PlayerSeasonStats

    with managed_session() as session_db:
        team = session_db.query(Team).get(team_id)
        if not team:
            return jsonify({"msg": "Team not found"}), 404

        # Find current season - first check team's league's season
        current_season = None
        if team.league and team.league.season:
            current_season = team.league.season

        # If not found through team's league, find any current season
        if not current_season:
            current_season = session_db.query(Season).filter_by(is_current=True).first()

        # Get standings data
        standings = session_db.query(Standings).filter_by(
            team_id=team_id,
            season_id=current_season.id if current_season else None
        ).first()

        # Preload team stats to avoid N+1 queries
        from app.team_performance_helpers import preload_team_stats_for_request
        preload_team_stats_for_request([team.id])

        # Get team stats from model properties
        stats = {
            "name": team.name,
            "league": team.league.name if team.league else None,
            "season": current_season.name if current_season else None,
            "top_scorer": team.top_scorer,
            "top_assist": team.top_assist,
            "avg_goals_per_match": team.avg_goals_per_match,
        }

        # Add recent form information
        recent_matches = session_db.query(Match).filter(
            or_(Match.home_team_id == team_id, Match.away_team_id == team_id),
            Match.home_team_score.isnot(None),
            Match.away_team_score.isnot(None)
        ).order_by(Match.date.desc()).limit(5).all()

        form = []
        for match in recent_matches:
            if match.home_team_id == team_id:
                if match.home_team_score > match.away_team_score:
                    form.append("W")
                elif match.home_team_score < match.away_team_score:
                    form.append("L")
                else:
                    form.append("D")
            else:  # Away team
                if match.away_team_score > match.home_team_score:
                    form.append("W")
                elif match.away_team_score < match.home_team_score:
                    form.append("L")
                else:
                    form.append("D")

        stats["recent_form"] = form

        # Add standings data if available
        if standings:
            stats.update({
                "standings": {
                    "played": standings.played,
                    "wins": standings.wins,
                    "draws": standings.draws,
                    "losses": standings.losses,
                    "goals_for": standings.goals_for,
                    "goals_against": standings.goals_against,
                    "goal_difference": standings.goal_difference,
                    "points": standings.points,
                }
            })
        else:
            stats["standings"] = None

        # Get total goals scored by team's players
        total_goals = session_db.query(func.sum(PlayerSeasonStats.goals)).join(
            player_teams, PlayerSeasonStats.player_id == player_teams.c.player_id
        ).filter(
            player_teams.c.team_id == team_id,
            PlayerSeasonStats.season_id == current_season.id if current_season else None
        ).scalar() or 0

        stats["total_goals"] = total_goals

        # Get player statistics for this team (bulk load to prevent N+1)
        players_stats = []
        if current_season:
            # Single query to get all player stats for the team
            player_stats_query = session_db.query(Player, PlayerSeasonStats).join(
                player_teams, Player.id == player_teams.c.player_id
            ).outerjoin(
                PlayerSeasonStats,
                (PlayerSeasonStats.player_id == Player.id) &
                (PlayerSeasonStats.season_id == current_season.id)
            ).filter(
                player_teams.c.team_id == team_id
            ).all()

            for player, player_stats in player_stats_query:
                if player_stats and (player_stats.goals > 0 or player_stats.assists > 0):
                    players_stats.append({
                        "id": player.id,
                        "name": player.name,
                        "goals": player_stats.goals,
                        "assists": player_stats.assists,
                        "yellow_cards": player_stats.yellow_cards,
                        "red_cards": player_stats.red_cards
                    })

        # Sort by goals, then assists
        players_stats.sort(key=lambda x: (x.get("goals", 0), x.get("assists", 0)), reverse=True)
        stats["players_stats"] = players_stats

        # Return with ETag support for mobile app caching
        return make_etag_response(stats, 'team_stats', CACHE_DURATIONS['team_stats'])


@mobile_api_v2.route('/teams/my_team', methods=['GET'])
@jwt_required()
def get_my_team():
    """
    Retrieve the primary team for the authenticated user.

    Returns:
        JSON with team details or message if no team found
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session_db:
        player = session_db.query(Player).filter_by(user_id=current_user_id).first()
        if not player:
            return jsonify({"msg": "Player profile not found"}), 404

        # Get primary team or first team
        if player.primary_team_id:
            team = session_db.query(Team).get(player.primary_team_id)
        elif player.teams:
            team = player.teams[0]
        else:
            return jsonify({"msg": "No team found for player"}), 404

        team_data = team.to_dict(include_players=True)
        team_data['upcoming_matches'] = get_team_upcoming_matches(team.id, session=session_db)

        return jsonify(team_data), 200


@mobile_api_v2.route('/teams/my_teams', methods=['GET'])
@jwt_required()
def get_my_teams():
    """
    Retrieve all teams the currently authenticated player is associated with.

    Returns:
        JSON list of teams the user belongs to
    """
    with managed_session() as session_db:
        current_user_id = int(get_jwt_identity())
        player = session_db.query(Player).filter_by(user_id=current_user_id).first()

        if not player:
            return jsonify({"msg": "Player not found"}), 404

        # Query all teams for this player using the player_teams association table
        teams_query = session_db.query(Team).join(player_teams).filter(
            player_teams.c.player_id == player.id
        )

        teams = teams_query.all()

        if not teams:
            return jsonify({"msg": "No teams found for this player"}), 404

        # Preload team stats to avoid N+1 queries
        from app.team_performance_helpers import preload_team_stats_for_request
        team_ids = [team.id for team in teams]
        preload_team_stats_for_request(team_ids)

        base_url = request.host_url.rstrip('/')
        teams_data = []

        for team in teams:
            team_data = team.to_dict()

            # Add is_primary flag
            team_data['is_primary'] = (team.id == player.primary_team_id)

            # Add is_coach flag
            is_coach = session_db.query(player_teams.c.is_coach).filter(
                player_teams.c.player_id == player.id,
                player_teams.c.team_id == team.id
            ).scalar()
            team_data['is_coach'] = bool(is_coach)

            # Handle team logo URLs
            if team_data.get('logo_url') and not team_data['logo_url'].startswith('http'):
                team_data['logo_url'] = f"{base_url}{team_data['logo_url']}"

            teams_data.append(team_data)

        # Sort teams with primary team first, then alphabetically
        teams_data.sort(key=lambda t: (not t['is_primary'], t['name'].lower()))

        return jsonify(teams_data), 200
