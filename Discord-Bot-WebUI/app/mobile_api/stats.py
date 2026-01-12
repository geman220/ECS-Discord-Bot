# app/mobile_api/stats.py

"""
Mobile API Statistics Endpoints

Provides league-separated statistics for mobile clients:
- Leaderboards (goals, assists) per league
- Player stats breakdown by league
- Career stats
- ECS FC stats (separate from Pub League)
"""

import logging
from flask import jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy.orm import joinedload

from app.mobile_api import mobile_api_v2
from app.core.session_manager import managed_session
from app.models import Player, Team, League, Season
from app.models.stats import PlayerSeasonStats, PlayerCareerStats
from app.models.ecs_fc import EcsFcPlayerEvent, EcsFcMatch

logger = logging.getLogger(__name__)


@mobile_api_v2.route('/stats/leaderboard', methods=['GET'])
@jwt_required()
def get_leaderboard():
    """
    Get leaderboard for goals and assists.

    Query Parameters:
        league_id: Filter by specific league (required for league-specific leaderboard)
        season_id: Season ID (defaults to current season)
        stat_type: 'goals' or 'assists' (default: 'goals')
        limit: Max results (default: 10, max: 50)

    Returns:
        JSON with leaderboard data
    """
    league_id = request.args.get('league_id', type=int)
    season_id = request.args.get('season_id', type=int)
    stat_type = request.args.get('stat_type', 'goals')
    limit = min(request.args.get('limit', 10, type=int), 50)

    if stat_type not in ['goals', 'assists']:
        return jsonify({"msg": "stat_type must be 'goals' or 'assists'"}), 400

    with managed_session() as session:
        # Get current season if not specified
        if not season_id:
            current_season = session.query(Season).filter(
                Season.is_current == True,
                Season.league_type == 'Pub League'
            ).first()
            if current_season:
                season_id = current_season.id
            else:
                return jsonify({"msg": "No current season found"}), 404

        # Get league info if specified
        league_info = None
        if league_id:
            league = session.query(League).get(league_id)
            if league:
                league_info = {"id": league.id, "name": league.name}

        # Build query based on stat type
        stat_column = PlayerSeasonStats.goals if stat_type == 'goals' else PlayerSeasonStats.assists

        query = session.query(
            Player.id,
            Player.name,
            Player.profile_picture_url,
            stat_column.label('stat_value')
        ).join(
            PlayerSeasonStats,
            Player.id == PlayerSeasonStats.player_id
        ).filter(
            PlayerSeasonStats.season_id == season_id,
            Player.is_current_player == True
        )

        # Filter by league if specified
        if league_id:
            query = query.filter(PlayerSeasonStats.league_id == league_id)

        query = query.order_by(stat_column.desc()).limit(limit)
        results = query.all()

        # Build leaderboard
        leaderboard = []
        for rank, (player_id, name, photo_url, stat_value) in enumerate(results, 1):
            if stat_value and stat_value > 0:
                leaderboard.append({
                    "rank": rank,
                    "player_id": player_id,
                    "player_name": name,
                    "profile_picture_url": photo_url,
                    "value": stat_value
                })

        return jsonify({
            "stat_type": stat_type,
            "season_id": season_id,
            "league": league_info,
            "leaderboard": leaderboard,
            "count": len(leaderboard)
        }), 200


@mobile_api_v2.route('/stats/player/<int:player_id>', methods=['GET'])
@jwt_required()
def get_player_stats(player_id: int):
    """
    Get comprehensive stats for a player, broken down by league.

    Query Parameters:
        season_id: Season ID (defaults to current season)
        include_career: Include career totals (default: true)
        include_ecs_fc: Include ECS FC stats (default: true)

    Returns:
        JSON with player stats per league and combined totals
    """
    season_id = request.args.get('season_id', type=int)
    include_career = request.args.get('include_career', 'true').lower() == 'true'
    include_ecs_fc = request.args.get('include_ecs_fc', 'true').lower() == 'true'

    with managed_session() as session:
        player = session.query(Player).options(
            joinedload(Player.season_stats).joinedload(PlayerSeasonStats.league),
            joinedload(Player.career_stats)
        ).get(player_id)

        if not player:
            return jsonify({"msg": "Player not found"}), 404

        # Get current season if not specified
        if not season_id:
            current_season = session.query(Season).filter(
                Season.is_current == True,
                Season.league_type == 'Pub League'
            ).first()
            if current_season:
                season_id = current_season.id

        # Get Pub League stats by league
        pub_league_stats = []
        combined_pub_league = {
            'goals': 0,
            'assists': 0,
            'yellow_cards': 0,
            'red_cards': 0
        }

        if season_id:
            for stats in player.season_stats:
                if stats.season_id == season_id:
                    league_data = {
                        'league_id': stats.league_id,
                        'league_name': stats.league.name if stats.league else 'Unknown',
                        'league_type': 'pub_league',
                        'goals': stats.goals or 0,
                        'assists': stats.assists or 0,
                        'yellow_cards': stats.yellow_cards or 0,
                        'red_cards': stats.red_cards or 0,
                    }
                    pub_league_stats.append(league_data)

                    combined_pub_league['goals'] += league_data['goals']
                    combined_pub_league['assists'] += league_data['assists']
                    combined_pub_league['yellow_cards'] += league_data['yellow_cards']
                    combined_pub_league['red_cards'] += league_data['red_cards']

        # Get ECS FC stats if requested
        ecs_fc_stats = None
        if include_ecs_fc:
            # Count events from ECS FC matches
            from sqlalchemy import func

            ecs_fc_events = session.query(
                EcsFcPlayerEvent.event_type,
                func.count(EcsFcPlayerEvent.id).label('count')
            ).filter(
                EcsFcPlayerEvent.player_id == player_id
            ).group_by(
                EcsFcPlayerEvent.event_type
            ).all()

            ecs_fc_stats = {
                'league_type': 'ecs_fc',
                'goals': 0,
                'assists': 0,
                'yellow_cards': 0,
                'red_cards': 0
            }

            for event_type, count in ecs_fc_events:
                if event_type == 'goal':
                    ecs_fc_stats['goals'] = count
                elif event_type == 'assist':
                    ecs_fc_stats['assists'] = count
                elif event_type == 'yellow_card':
                    ecs_fc_stats['yellow_cards'] = count
                elif event_type == 'red_card':
                    ecs_fc_stats['red_cards'] = count

        # Get career stats
        career_stats = None
        if include_career and player.career_stats:
            cs = player.career_stats[0] if player.career_stats else None
            if cs:
                career_stats = {
                    'goals': cs.goals or 0,
                    'assists': cs.assists or 0,
                    'yellow_cards': cs.yellow_cards or 0,
                    'red_cards': cs.red_cards or 0
                }

        return jsonify({
            "player_id": player_id,
            "player_name": player.name,
            "season_id": season_id,
            "pub_league": {
                "leagues": pub_league_stats,
                "combined": combined_pub_league
            },
            "ecs_fc": ecs_fc_stats,
            "career": career_stats
        }), 200


@mobile_api_v2.route('/stats/my-stats', methods=['GET'])
@jwt_required()
def get_my_stats():
    """
    Get stats for the current authenticated user.

    Same as /stats/player/{id} but for the current user.
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        player = session.query(Player).filter_by(user_id=current_user_id).first()
        if not player:
            return jsonify({"msg": "Player profile not found"}), 404

    # Redirect to player stats endpoint
    return get_player_stats(player.id)


@mobile_api_v2.route('/stats/leagues', methods=['GET'])
@jwt_required()
def get_leagues_for_stats():
    """
    Get list of leagues for filtering stats.

    Query Parameters:
        season_id: Filter by season (defaults to current)
        include_ecs_fc: Include ECS FC leagues (default: false)

    Returns:
        JSON with league list for dropdown/filter selection
    """
    season_id = request.args.get('season_id', type=int)
    include_ecs_fc = request.args.get('include_ecs_fc', 'false').lower() == 'true'

    with managed_session() as session:
        # Get current season if not specified
        if not season_id:
            current_season = session.query(Season).filter(
                Season.is_current == True,
                Season.league_type == 'Pub League'
            ).first()
            if current_season:
                season_id = current_season.id

        query = session.query(League).filter(League.season_id == season_id)

        if not include_ecs_fc:
            query = query.filter(~League.name.ilike('%ECS FC%'))

        leagues = query.order_by(League.name).all()

        leagues_data = []
        for league in leagues:
            leagues_data.append({
                "id": league.id,
                "name": league.name,
                "is_ecs_fc": 'ECS FC' in league.name
            })

        return jsonify({
            "season_id": season_id,
            "leagues": leagues_data,
            "count": len(leagues_data)
        }), 200


@mobile_api_v2.route('/stats/ecs-fc/leaderboard', methods=['GET'])
@jwt_required()
def get_ecs_fc_leaderboard():
    """
    Get ECS FC-specific leaderboard.

    Query Parameters:
        team_id: Filter by specific ECS FC team (optional)
        stat_type: 'goals' or 'assists' (default: 'goals')
        limit: Max results (default: 10, max: 50)

    Returns:
        JSON with ECS FC leaderboard
    """
    from sqlalchemy import func

    team_id = request.args.get('team_id', type=int)
    stat_type = request.args.get('stat_type', 'goals')
    limit = min(request.args.get('limit', 10, type=int), 50)

    if stat_type not in ['goals', 'assists']:
        return jsonify({"msg": "stat_type must be 'goals' or 'assists'"}), 400

    event_type = 'goal' if stat_type == 'goals' else 'assist'

    with managed_session() as session:
        query = session.query(
            Player.id,
            Player.name,
            Player.profile_picture_url,
            func.count(EcsFcPlayerEvent.id).label('stat_value')
        ).join(
            EcsFcPlayerEvent,
            Player.id == EcsFcPlayerEvent.player_id
        ).filter(
            EcsFcPlayerEvent.event_type == event_type
        )

        # Filter by team if specified
        if team_id:
            query = query.join(
                EcsFcMatch,
                EcsFcPlayerEvent.ecs_fc_match_id == EcsFcMatch.id
            ).filter(EcsFcMatch.team_id == team_id)

        query = query.group_by(
            Player.id, Player.name, Player.profile_picture_url
        ).order_by(
            func.count(EcsFcPlayerEvent.id).desc()
        ).limit(limit)

        results = query.all()

        # Build leaderboard
        leaderboard = []
        for rank, (player_id, name, photo_url, stat_value) in enumerate(results, 1):
            if stat_value and stat_value > 0:
                leaderboard.append({
                    "rank": rank,
                    "player_id": player_id,
                    "player_name": name,
                    "profile_picture_url": photo_url,
                    "value": stat_value
                })

        # Get team info if filtered
        team_info = None
        if team_id:
            team = session.query(Team).get(team_id)
            if team:
                team_info = {"id": team.id, "name": team.name}

        return jsonify({
            "stat_type": stat_type,
            "league_type": "ecs_fc",
            "team": team_info,
            "leaderboard": leaderboard,
            "count": len(leaderboard)
        }), 200
