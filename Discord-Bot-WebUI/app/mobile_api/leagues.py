# app/mobile_api/leagues.py

"""
Mobile API Season and League Endpoints

Provides season and league information for mobile clients:
- Get list of seasons
- Get current season info
- Get leagues for a season
- Get league details
"""

import logging
from flask import jsonify, request
from flask_jwt_extended import jwt_required
from sqlalchemy.orm import joinedload

from app.mobile_api import mobile_api_v2
from app.core.session_manager import managed_session
from app.models import Season, League, Team

logger = logging.getLogger(__name__)


@mobile_api_v2.route('/seasons', methods=['GET'])
@jwt_required()
def get_seasons():
    """
    Get list of all seasons.

    Query Parameters:
        league_type: Filter by league type (e.g., 'Pub League', 'ECS FC')
        is_current: Filter by current status ('true' or 'false')

    Returns:
        JSON with list of seasons
    """
    league_type = request.args.get('league_type', '').strip()
    is_current_param = request.args.get('is_current', '').strip().lower()

    with managed_session() as session:
        query = session.query(Season)

        if league_type:
            query = query.filter(Season.league_type == league_type)

        if is_current_param == 'true':
            query = query.filter(Season.is_current == True)
        elif is_current_param == 'false':
            query = query.filter(Season.is_current == False)

        query = query.order_by(Season.start_date.desc())
        seasons = query.all()

        seasons_data = []
        for s in seasons:
            seasons_data.append({
                "id": s.id,
                "name": s.name,
                "league_type": s.league_type,
                "start_date": s.start_date.isoformat() if s.start_date else None,
                "end_date": s.end_date.isoformat() if s.end_date else None,
                "is_current": s.is_current,
                "league_count": len(s.leagues) if s.leagues else 0
            })

        return jsonify({
            "seasons": seasons_data,
            "total": len(seasons_data)
        }), 200


@mobile_api_v2.route('/seasons/current', methods=['GET'])
@jwt_required()
def get_current_season():
    """
    Get the current season(s) information.

    Query Parameters:
        league_type: Filter by league type (e.g., 'Pub League')

    Returns:
        JSON with current season info
    """
    league_type = request.args.get('league_type', '').strip()

    with managed_session() as session:
        query = session.query(Season).options(
            joinedload(Season.leagues)
        ).filter(Season.is_current == True)

        if league_type:
            query = query.filter(Season.league_type == league_type)

        seasons = query.all()

        if not seasons:
            return jsonify({
                "current_seasons": [],
                "message": "No current season found"
            }), 200

        seasons_data = []
        for s in seasons:
            leagues_data = []
            for league in s.leagues:
                team_count = len([t for t in league.teams if t.name != "Practice"])
                leagues_data.append({
                    "id": league.id,
                    "name": league.name,
                    "team_count": team_count
                })

            seasons_data.append({
                "id": s.id,
                "name": s.name,
                "league_type": s.league_type,
                "start_date": s.start_date.isoformat() if s.start_date else None,
                "end_date": s.end_date.isoformat() if s.end_date else None,
                "is_current": s.is_current,
                "leagues": leagues_data
            })

        return jsonify({
            "current_seasons": seasons_data
        }), 200


@mobile_api_v2.route('/leagues', methods=['GET'])
@jwt_required()
def get_leagues():
    """
    Get list of leagues, optionally filtered by season.

    Query Parameters:
        season_id: Filter by season ID
        current_only: If 'true', only return leagues from current seasons

    Returns:
        JSON with list of leagues
    """
    season_id = request.args.get('season_id', type=int)
    current_only = request.args.get('current_only', 'true').lower() == 'true'

    with managed_session() as session:
        query = session.query(League).options(
            joinedload(League.season),
            joinedload(League.teams)
        )

        if season_id:
            query = query.filter(League.season_id == season_id)
        elif current_only:
            query = query.join(Season).filter(Season.is_current == True)

        query = query.order_by(League.name)
        leagues = query.all()

        leagues_data = []
        for league in leagues:
            teams = [t for t in league.teams if t.name != "Practice"]

            # Count total players
            total_players = 0
            for team in teams:
                total_players += len([p for p in team.players if p.is_current_player])

            leagues_data.append({
                "id": league.id,
                "name": league.name,
                "season_id": league.season_id,
                "season_name": league.season.name if league.season else None,
                "team_count": len(teams),
                "total_players": total_players
            })

        return jsonify({
            "leagues": leagues_data,
            "total": len(leagues_data)
        }), 200


@mobile_api_v2.route('/leagues/<int:league_id>', methods=['GET'])
@jwt_required()
def get_league_detail(league_id: int):
    """
    Get details for a specific league.

    Args:
        league_id: League ID

    Returns:
        JSON with league details including teams
    """
    with managed_session() as session:
        league = session.query(League).options(
            joinedload(League.season),
            joinedload(League.teams)
        ).get(league_id)

        if not league:
            return jsonify({"msg": "League not found"}), 404

        teams = [t for t in league.teams if t.name != "Practice"]

        teams_data = []
        for team in teams:
            players = [p for p in team.players if p.is_current_player]
            teams_data.append({
                "id": team.id,
                "name": team.name,
                "player_count": len(players)
            })

        return jsonify({
            "league": {
                "id": league.id,
                "name": league.name,
                "season": {
                    "id": league.season.id,
                    "name": league.season.name,
                    "league_type": league.season.league_type,
                    "is_current": league.season.is_current
                } if league.season else None,
                "teams": teams_data,
                "team_count": len(teams_data)
            }
        }), 200


@mobile_api_v2.route('/leagues/<int:league_id>/standings', methods=['GET'])
@jwt_required()
def get_league_standings(league_id: int):
    """
    Get standings for a specific league.

    Args:
        league_id: League ID

    Returns:
        JSON with league standings
    """
    with managed_session() as session:
        from app.models import Standings

        league = session.query(League).get(league_id)
        if not league:
            return jsonify({"msg": "League not found"}), 404

        # Get standings for teams in this league
        teams = [t for t in league.teams if t.name != "Practice"]
        team_ids = [t.id for t in teams]

        standings = session.query(Standings).filter(
            Standings.team_id.in_(team_ids)
        ).order_by(
            Standings.points.desc(),
            Standings.goal_difference.desc(),
            Standings.goals_for.desc()
        ).all()

        standings_data = []
        for i, standing in enumerate(standings, 1):
            team = next((t for t in teams if t.id == standing.team_id), None)
            standings_data.append({
                "position": i,
                "team_id": standing.team_id,
                "team_name": team.name if team else "Unknown",
                "played": standing.played,
                "won": standing.wins,
                "drawn": standing.draws,
                "lost": standing.losses,
                "goals_for": standing.goals_for,
                "goals_against": standing.goals_against,
                "goal_difference": standing.goal_difference,
                "points": standing.points
            })

        return jsonify({
            "league_id": league_id,
            "league_name": league.name,
            "standings": standings_data
        }), 200
