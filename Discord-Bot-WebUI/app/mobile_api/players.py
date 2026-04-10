# app/api/players.py

"""
Players API Endpoints

Handles player-related operations including:
- Player listing
- Player details
- Player profile pictures
- Player statistics (season and career)
- Team history
- Profile updates
"""

import logging

from flask import jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy.orm import joinedload, selectinload

from app.mobile_api import mobile_api_v2
from app.core.session_manager import managed_session
from app.models import Player, Season, User, Team
from app.models.players import PlayerTeamSeason, PlayerTeamHistory
from app.models.stats import PlayerSeasonStats, PlayerCareerStats
from app.app_api_helpers import (
    build_player_response,
    get_player_stats,
    build_player_season_stats_data,
    build_player_team_history_data,
)

logger = logging.getLogger(__name__)


@mobile_api_v2.route('/players', methods=['GET'])
@jwt_required()
def get_players():
    """
    Retrieve a list of players.

    Query parameters:
        search: Search by player name or team name (partial match, case-insensitive)
        team_id: Filter by team
        league_id: Filter by league
        current_only: If 'true', only return current players (default: true)
        limit: Maximum number of players (default: 50, max: 100)
        offset: Pagination offset

    Returns:
        JSON list of players
    """
    with managed_session() as session_db:
        from sqlalchemy import or_
        from app.models import Team, player_teams

        # Get pagination parameters first
        limit = min(request.args.get('limit', 50, type=int), 100)
        offset = request.args.get('offset', 0, type=int)

        # Get filter parameters
        search = request.args.get('search', '').strip()
        team_id = request.args.get('team_id', type=int)
        league_id = request.args.get('league_id', type=int)
        current_only = request.args.get('current_only', 'true').lower() == 'true'
        coaches_only = request.args.get('coaches_only', 'false').lower() == 'true'
        include_teams = request.args.get('include_teams', 'false').lower() == 'true'

        # Build a subquery to get distinct player IDs matching filters
        # Select both id and name so we can ORDER BY name with DISTINCT
        id_query = session_db.query(Player.id, Player.name)

        # Apply search filter - search player name or team name
        if search:
            id_query = id_query.outerjoin(player_teams).outerjoin(
                Team, Team.id == player_teams.c.team_id
            ).filter(
                or_(
                    Player.name.ilike(f'%{search}%'),
                    Team.name.ilike(f'%{search}%')
                )
            )

        # Filter by team
        if team_id:
            if not search:  # Only join if not already joined for search
                id_query = id_query.join(player_teams)
            id_query = id_query.filter(player_teams.c.team_id == team_id)

        # Filter by league
        if league_id:
            from app.models import player_league
            id_query = id_query.join(player_league).filter(player_league.c.league_id == league_id)

        # Filter current players only (default: true)
        if current_only:
            id_query = id_query.filter(Player.is_current_player == True)

        # Filter coaches only
        if coaches_only:
            id_query = id_query.filter(Player.is_coach == True)

        # Get distinct player IDs (name included for ORDER BY compatibility)
        id_query = id_query.distinct()

        # Get total count of filtered results (before pagination)
        total_count = id_query.count()

        # Get the player IDs for this page, ordered by name
        player_ids = [row[0] for row in id_query.order_by(Player.name).offset(offset).limit(limit).all()]

        # Fetch full player objects, preserving the order
        if player_ids:
            query = session_db.query(Player).filter(Player.id.in_(player_ids))
            if include_teams:
                from app.models import League
                query = query.options(
                    joinedload(Player.primary_team).joinedload(Team.league),
                    selectinload(Player.teams).joinedload(Team.league),
                )
            players = query.order_by(Player.name).all()
        else:
            players = []

        base_url = request.host_url.rstrip('/')
        players_data = []
        for player in players:
            player_data = {
                "id": player.id,
                "name": player.name,
                "jersey_number": player.jersey_number,
                "favorite_position": player.favorite_position,
                "is_current_player": player.is_current_player,
                "is_coach": player.is_coach,
                "profile_picture_url": (
                    player.profile_picture_url if player.profile_picture_url and player.profile_picture_url.startswith('http')
                    else f"{base_url}{player.profile_picture_url}" if player.profile_picture_url
                    else f"{base_url}/static/img/default_player.png"
                )
            }
            if include_teams:
                player_data["team_name"] = player.primary_team.name if player.primary_team else None
                player_data["league_name"] = (
                    player.primary_team.league.name
                    if player.primary_team and player.primary_team.league
                    else None
                )
                player_data["all_teams"] = []
                for team in player.teams:
                    team_assoc = session_db.query(player_teams).filter_by(
                        player_id=player.id, team_id=team.id
                    ).first()
                    player_data["all_teams"].append({
                        "id": team.id,
                        "name": team.name,
                        "league": team.league.name if team.league else None,
                        "is_coach": getattr(team_assoc, 'is_coach', False) if team_assoc else False,
                    })
            players_data.append(player_data)

        return jsonify({
            "players": players_data,
            "count": len(players_data),
            "total": total_count,
            "limit": limit,
            "offset": offset,
            "has_more": offset + len(players_data) < total_count
        }), 200


@mobile_api_v2.route('/players/<int:player_id>', methods=['GET'])
@jwt_required()
def get_player(player_id: int):
    """
    Retrieve details for a specific player.

    Query parameters:
        include_stats: If 'true', include player statistics
        include_preferences: If 'true', include position preferences
            (favorite_position, other_positions, positions_not_to_play, frequency_play_goal)

    Returns:
        JSON with player details
    """
    include_stats = request.args.get('include_stats', 'false').lower() == 'true'
    include_preferences = request.args.get('include_preferences', 'false').lower() == 'true'

    with managed_session() as session_db:
        player = session_db.query(Player).get(player_id)
        if not player:
            return jsonify({"msg": "Player not found"}), 404

        response_data = build_player_response(player)

        if include_preferences:
            response_data.update({
                "favorite_position": player.favorite_position,
                "other_positions": player.other_positions,
                "positions_not_to_play": player.positions_not_to_play,
                "frequency_play_goal": player.frequency_play_goal,
            })

        if include_stats:
            current_season = session_db.query(Season).filter_by(is_current=True).first()
            response_data.update(get_player_stats(player, current_season, session=session_db))

        return jsonify(response_data), 200


@mobile_api_v2.route('/players/<int:player_id>/profile_picture', methods=['GET'])
@jwt_required()
def get_player_profile_picture(player_id: int):
    """
    Get the profile picture URL for a player.

    Returns:
        JSON with profile picture URL
    """
    with managed_session() as session_db:
        player = session_db.query(Player).get(player_id)
        if not player:
            return jsonify({"msg": "Player not found"}), 404

        base_url = request.host_url.rstrip('/')
        if player.profile_picture_url:
            url = (
                player.profile_picture_url if player.profile_picture_url.startswith('http')
                else f"{base_url}{player.profile_picture_url}"
            )
        else:
            url = f"{base_url}/static/img/default_player.png"

        return jsonify({"player_id": player_id, "profile_picture_url": url}), 200


@mobile_api_v2.route('/player/update', methods=['PUT'])
@jwt_required()
def update_player_profile():
    """
    Update the authenticated user's player profile.

    Expected JSON parameters:
        name, phone, jersey_size, jersey_number, pronouns,
        favorite_position, other_positions, positions_not_to_play,
        frequency_play_goal, expected_weeks_available, unavailable_dates,
        willing_to_referee, additional_info

    Returns:
        JSON with updated player data
    """
    with managed_session() as session_db:
        current_user_id = int(get_jwt_identity())
        player = session_db.query(Player).filter_by(user_id=current_user_id).first()
        if not player:
            return jsonify({"msg": "Player not found"}), 404

        data = request.json
        allowed_fields = [
            'name', 'phone', 'jersey_size', 'jersey_number', 'pronouns',
            'favorite_position', 'other_positions', 'positions_not_to_play',
            'frequency_play_goal', 'expected_weeks_available', 'unavailable_dates',
            'willing_to_referee', 'additional_info'
        ]

        try:
            for field in allowed_fields:
                if field in data:
                    setattr(player, field, data[field])
            return jsonify({
                "msg": "Profile updated successfully",
                "player": player.to_dict()
            }), 200
        except Exception as e:
            logger.error(f"Error updating player profile: {str(e)}")
            return jsonify({"msg": "Error updating profile: Internal Server Error"}), 500


@mobile_api_v2.route('/players/<int:player_id>/stats', methods=['GET'])
@jwt_required()
def get_player_all_stats(player_id: int):
    """
    Get all season statistics and career statistics for a player.

    Unlike the basic stats in GET /players/<id>?include_stats=true which only
    returns current season, this endpoint returns stats for ALL seasons.

    Query parameters:
        season_id: Filter to a specific season (optional)

    Returns:
        JSON with season_stats array (all seasons) and career_stats
    """
    season_id_filter = request.args.get('season_id', type=int)

    with managed_session() as session:
        player = session.query(Player).get(player_id)
        if not player:
            return jsonify({"msg": "Player not found"}), 404

        result = build_player_season_stats_data(
            player_id, season_id_filter=season_id_filter, session=session
        )

        return jsonify({
            "player_id": player_id,
            "player_name": player.name,
            **result
        }), 200


@mobile_api_v2.route('/players/<int:player_id>/team-history', methods=['GET'])
@jwt_required()
def get_player_team_history(player_id: int):
    """
    Get the complete team history for a player across all seasons.

    Returns both:
    - Season-based assignments (PlayerTeamSeason): Which team they were on each season
    - Historical tracking (PlayerTeamHistory): Join/leave dates

    Query parameters:
        include_roster: If 'true', include basic roster info for each team (default: false)

    Returns:
        JSON with team history organized by season
    """
    include_roster = request.args.get('include_roster', 'false').lower() == 'true'

    with managed_session() as session:
        player = session.query(Player).get(player_id)
        if not player:
            return jsonify({"msg": "Player not found"}), 404

        result = build_player_team_history_data(
            player_id, include_roster=include_roster, session=session
        )

        return jsonify({
            "player_id": player_id,
            "player_name": player.name,
            **result
        }), 200
