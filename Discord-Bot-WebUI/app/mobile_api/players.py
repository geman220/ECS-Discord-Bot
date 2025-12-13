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

        # Get distinct player IDs (name included for ORDER BY compatibility)
        id_query = id_query.distinct()

        # Get total count of filtered results (before pagination)
        total_count = id_query.count()

        # Get the player IDs for this page, ordered by name
        player_ids = [row[0] for row in id_query.order_by(Player.name).offset(offset).limit(limit).all()]

        # Fetch full player objects, preserving the order
        if player_ids:
            players = session_db.query(Player).filter(Player.id.in_(player_ids)).order_by(Player.name).all()
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
                "profile_picture_url": (
                    player.profile_picture_url if player.profile_picture_url and player.profile_picture_url.startswith('http')
                    else f"{base_url}{player.profile_picture_url}" if player.profile_picture_url
                    else f"{base_url}/static/img/default_player.png"
                )
            }
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
            return jsonify({"msg": f"Error updating profile: {str(e)}"}), 500


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

        # Get all season stats for this player
        stats_query = session.query(PlayerSeasonStats).filter(
            PlayerSeasonStats.player_id == player_id
        ).options(
            joinedload(PlayerSeasonStats.season)
        )

        if season_id_filter:
            stats_query = stats_query.filter(PlayerSeasonStats.season_id == season_id_filter)

        season_stats = stats_query.all()

        # Get career stats
        career_stats = session.query(PlayerCareerStats).filter(
            PlayerCareerStats.player_id == player_id
        ).first()

        # Build response
        season_stats_data = []
        for stat in season_stats:
            season_stats_data.append({
                "id": stat.id,
                "season_id": stat.season_id,
                "season_name": stat.season.name if stat.season else None,
                "is_current_season": stat.season.is_current if stat.season else False,
                "goals": stat.goals,
                "assists": stat.assists,
                "yellow_cards": stat.yellow_cards,
                "red_cards": stat.red_cards
            })

        # Sort by season (current first, then by name descending)
        season_stats_data.sort(key=lambda x: (not x['is_current_season'], x['season_name'] or ''), reverse=False)

        career_stats_data = None
        if career_stats:
            career_stats_data = {
                "id": career_stats.id,
                "goals": career_stats.goals,
                "assists": career_stats.assists,
                "yellow_cards": career_stats.yellow_cards,
                "red_cards": career_stats.red_cards
            }

        return jsonify({
            "player_id": player_id,
            "player_name": player.name,
            "season_stats": season_stats_data,
            "career_stats": career_stats_data,
            "total_seasons": len(season_stats_data)
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

        base_url = request.host_url.rstrip('/')

        # Get season-based team assignments
        season_assignments = session.query(PlayerTeamSeason).filter(
            PlayerTeamSeason.player_id == player_id
        ).options(
            joinedload(PlayerTeamSeason.team).joinedload(Team.league),
            joinedload(PlayerTeamSeason.season)
        ).all()

        # Build season history
        seasons_data = []
        for assignment in season_assignments:
            team = assignment.team
            season = assignment.season

            team_data = {
                "season_id": season.id if season else None,
                "season_name": season.name if season else None,
                "is_current_season": season.is_current if season else False,
                "team": {
                    "id": team.id if team else None,
                    "name": team.name if team else None,
                    "league_id": team.league_id if team else None,
                    "league_name": team.league.name if team and team.league else None,
                    "logo_url": (
                        team.kit_url if team and team.kit_url and team.kit_url.startswith('http')
                        else f"{base_url}{team.kit_url}" if team and team.kit_url else None
                    )
                }
            }

            # Optionally include roster
            if include_roster and team:
                # Get players who were on this team in this season
                team_roster = session.query(PlayerTeamSeason).filter(
                    PlayerTeamSeason.team_id == team.id,
                    PlayerTeamSeason.season_id == season.id if season else None
                ).options(
                    joinedload(PlayerTeamSeason.player)
                ).all()

                roster_data = []
                for roster_entry in team_roster:
                    p = roster_entry.player
                    if p:
                        roster_data.append({
                            "id": p.id,
                            "name": p.name,
                            "jersey_number": p.jersey_number
                        })

                team_data["roster"] = roster_data
                team_data["roster_count"] = len(roster_data)

            seasons_data.append(team_data)

        # Sort by season (current first, then by name descending for chronological order)
        seasons_data.sort(key=lambda x: (not x['is_current_season'], x['season_name'] or ''), reverse=False)

        # Get historical tracking records (join/leave dates)
        history_records = session.query(PlayerTeamHistory).filter(
            PlayerTeamHistory.player_id == player_id
        ).options(
            joinedload(PlayerTeamHistory.team)
        ).order_by(PlayerTeamHistory.joined_date.desc()).all()

        history_data = []
        for record in history_records:
            history_data.append({
                "id": record.id,
                "team_id": record.team_id,
                "team_name": record.team.name if record.team else None,
                "joined_date": record.joined_date.isoformat() if record.joined_date else None,
                "left_date": record.left_date.isoformat() if record.left_date else None,
                "is_coach": record.is_coach,
                "is_current": record.left_date is None
            })

        # Get current teams
        current_teams = []
        from app.models.players import player_teams
        current_team_records = session.execute(
            player_teams.select().where(player_teams.c.player_id == player_id)
        ).fetchall()

        for record in current_team_records:
            team = session.query(Team).options(
                joinedload(Team.league)
            ).get(record.team_id)
            if team:
                current_teams.append({
                    "id": team.id,
                    "name": team.name,
                    "league_id": team.league_id,
                    "league_name": team.league.name if team.league else None,
                    "is_coach": record.is_coach,
                    "position": record.position
                })

        return jsonify({
            "player_id": player_id,
            "player_name": player.name,
            "current_teams": current_teams,
            "season_history": seasons_data,
            "detailed_history": history_data,
            "total_teams_played": len(set(
                [s['team']['id'] for s in seasons_data if s['team']['id']] +
                [h['team_id'] for h in history_data if h['team_id']]
            ))
        }), 200
