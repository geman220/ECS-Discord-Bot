# app/mobile_api/draft.py

"""
Mobile API Draft Endpoints

Provides draft system functionality for mobile clients:
- View draft status and analytics
- Get available/drafted players
- Draft players to teams
- Remove players from teams
- Position analysis for teams
"""

import logging
from flask import jsonify, request, g
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.sql import exists, and_, or_
from sqlalchemy import func

from app.mobile_api import mobile_api_v2
from app.decorators import jwt_role_required
from app.core.session_manager import managed_session
from app.models import (
    User, Player, Team, League, Season,
    player_teams, player_league, DraftOrderHistory
)
from app.draft_enhanced import DraftService
from app.draft_cache_service import DraftCacheService
from app.db_utils import mark_player_for_discord_update
from app.models.ecs_fc import is_ecs_fc_league
from app.tasks.tasks_discord import assign_roles_to_player_task, remove_player_roles_task

logger = logging.getLogger(__name__)

# Valid leagues for drafting
VALID_LEAGUES = {
    'classic': 'Classic',
    'premier': 'Premier',
    'ecs_fc': 'ECS FC'
}


def get_db_league_name(league_name: str) -> str:
    """Convert URL league name to database league name."""
    return VALID_LEAGUES.get(league_name.lower())


@mobile_api_v2.route('/draft/leagues', methods=['GET'])
@jwt_required()
@jwt_role_required(['Pub League Coach', 'ECS FC Coach', 'Pub League Admin', 'Global Admin'])
def get_draft_leagues():
    """
    Get list of leagues available for drafting.

    Returns:
        JSON with list of leagues and their draft status
    """
    with managed_session() as session:
        # Get current season
        current_season = session.query(Season).filter_by(
            is_current=True,
            league_type='Pub League'
        ).first()

        if not current_season:
            return jsonify({
                "leagues": [],
                "message": "No current season found"
            }), 200

        # Get leagues for current season
        leagues = session.query(League).filter_by(
            season_id=current_season.id
        ).all()

        league_data = []
        for league in leagues:
            team_count = len([t for t in league.teams if t.name != "Practice"])

            # Count total players drafted
            total_drafted = 0
            for team in league.teams:
                if team.name != "Practice":
                    total_drafted += len([p for p in team.players if p.is_current_player])

            league_data.append({
                "id": league.id,
                "name": league.name,
                "url_name": league.name.lower().replace(' ', '_'),
                "season_id": league.season_id,
                "season_name": current_season.name,
                "team_count": team_count,
                "total_drafted": total_drafted
            })

        return jsonify({"leagues": league_data}), 200


@mobile_api_v2.route('/draft/<league_name>/status', methods=['GET'])
@jwt_required()
@jwt_role_required(['Pub League Coach', 'ECS FC Coach', 'Pub League Admin', 'Global Admin'])
def get_draft_status(league_name: str):
    """
    Get draft status and analytics for a league.

    Args:
        league_name: URL-friendly league name (classic, premier, ecs_fc)

    Returns:
        JSON with draft analytics and status
    """
    db_league_name = get_db_league_name(league_name)
    if not db_league_name:
        return jsonify({"msg": f"Invalid league name: {league_name}"}), 400

    with managed_session() as session:
        # Get current league
        current_league = (
            session.query(League)
            .join(League.season)
            .filter(League.name == db_league_name)
            .filter(Season.is_current == True)
            .first()
        )

        if not current_league:
            return jsonify({"msg": f"No current {db_league_name} league found"}), 404

        # Get teams (excluding Practice)
        teams = [t for t in current_league.teams if t.name != "Practice"]

        # Calculate analytics
        teams_data = []
        total_drafted = 0
        position_counts = {}

        for team in teams:
            team_players = [p for p in team.players if p.is_current_player]
            team_count = len(team_players)
            total_drafted += team_count

            # Count positions
            for player in team_players:
                pos = player.favorite_position or 'Unknown'
                position_counts[pos] = position_counts.get(pos, 0) + 1

            teams_data.append({
                "id": team.id,
                "name": team.name,
                "player_count": team_count
            })

        # Get available player count
        team_ids = [t.id for t in teams]
        all_leagues = session.query(League).filter(League.name == db_league_name).all()
        league_ids = [l.id for l in all_leagues]

        # Players belonging to this league
        belongs_to_league = or_(
            Player.primary_league_id.in_(league_ids),
            exists().where(
                and_(
                    player_league.c.player_id == Player.id,
                    player_league.c.league_id.in_(league_ids)
                )
            )
        )

        # Not on any current team
        not_drafted = ~exists().where(
            and_(
                player_teams.c.player_id == Player.id,
                player_teams.c.team_id.in_(team_ids)
            )
        )

        available_count = session.query(func.count(Player.id)).filter(
            belongs_to_league,
            not_drafted,
            Player.is_current_player == True
        ).scalar()

        # Get latest draft pick
        latest_pick = session.query(DraftOrderHistory).filter(
            DraftOrderHistory.league_id == current_league.id,
            DraftOrderHistory.season_id == current_league.season_id
        ).order_by(DraftOrderHistory.draft_position.desc()).first()

        return jsonify({
            "league_id": current_league.id,
            "league_name": db_league_name,
            "season_id": current_league.season_id,
            "teams": teams_data,
            "total_teams": len(teams),
            "total_drafted": total_drafted,
            "available_count": available_count,
            "avg_players_per_team": round(total_drafted / max(len(teams), 1), 1),
            "position_distribution": position_counts,
            "draft_progress": min(100, (total_drafted / (len(teams) * 15)) * 100),
            "latest_pick_position": latest_pick.draft_position if latest_pick else 0
        }), 200


@mobile_api_v2.route('/draft/<league_name>/available', methods=['GET'])
@jwt_required()
@jwt_role_required(['Pub League Coach', 'ECS FC Coach', 'Pub League Admin', 'Global Admin'])
def get_available_players(league_name: str):
    """
    Get available (undrafted) players for a league.

    Args:
        league_name: URL-friendly league name

    Query Parameters:
        search: Filter by player name (optional)
        position: Filter by position (optional)
        page: Page number for pagination (default: 1)
        per_page: Items per page (default: 50, max: 100)

    Returns:
        JSON with list of available players
    """
    db_league_name = get_db_league_name(league_name)
    if not db_league_name:
        return jsonify({"msg": f"Invalid league name: {league_name}"}), 400

    # Get query parameters
    search = request.args.get('search', '').strip()
    position = request.args.get('position', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 50, type=int), 100)

    with managed_session() as session:
        # Get current league and all historical leagues with same name
        current_league, all_leagues = DraftService.get_league_data(db_league_name)

        if not current_league:
            return jsonify({"msg": f"No current {db_league_name} league found"}), 404

        # Get team IDs for current league
        teams = [t for t in current_league.teams if t.name != "Practice"]
        team_ids = [t.id for t in teams]
        league_ids = [l.id for l in all_leagues]

        # Build query for available players
        belongs_to_league = or_(
            Player.primary_league_id.in_(league_ids),
            exists().where(
                and_(
                    player_league.c.player_id == Player.id,
                    player_league.c.league_id.in_(league_ids)
                )
            )
        )

        # Check if this is an ECS FC league
        is_ecs_fc = is_ecs_fc_league(current_league.id)

        query = (
            session.query(Player)
            .join(Player.user)  # Join to User to check approval status
            .filter(belongs_to_league)
            .filter(Player.is_current_player == True)
            .filter(User.is_approved == True)  # Only include approved users
            .options(
                joinedload(Player.career_stats),
                joinedload(Player.season_stats),
                selectinload(Player.teams),
                joinedload(Player.user)  # Eager load user for performance
            )
        )

        # For Pub League: exclude players already on a team
        # For ECS FC: include all players (multi-team allowed)
        if not is_ecs_fc:
            not_drafted = ~exists().where(
                and_(
                    player_teams.c.player_id == Player.id,
                    player_teams.c.team_id.in_(team_ids)
                )
            )
            query = query.filter(not_drafted)

        # Apply search filter
        if search:
            query = query.filter(Player.name.ilike(f'%{search}%'))

        # Apply position filter
        if position:
            query = query.filter(Player.favorite_position.ilike(f'%{position}%'))

        # Get total count before pagination
        total_count = query.count()

        # Apply pagination
        query = query.order_by(Player.name.asc())
        query = query.offset((page - 1) * per_page).limit(per_page)

        players_raw = query.all()

        # Get enhanced player data
        players = DraftService.get_enhanced_player_data(
            players_raw,
            current_league.season_id
        )

        # For ECS FC: add existing team information for multi-team support
        if is_ecs_fc:
            team_ids_set = set(team_ids)
            for i, player_data in enumerate(players):
                raw_player = players_raw[i]
                existing_teams = [
                    {"id": team.id, "name": team.name}
                    for team in raw_player.teams
                    if team.id in team_ids_set
                ]
                player_data['existing_ecs_fc_teams'] = existing_teams

        return jsonify({
            "players": players,
            "total": total_count,
            "page": page,
            "per_page": per_page,
            "total_pages": (total_count + per_page - 1) // per_page,
            "is_ecs_fc_league": is_ecs_fc
        }), 200


@mobile_api_v2.route('/draft/<league_name>/teams', methods=['GET'])
@jwt_required()
@jwt_role_required(['Pub League Coach', 'ECS FC Coach', 'Pub League Admin', 'Global Admin'])
def get_draft_teams(league_name: str):
    """
    Get teams for a league with roster counts.

    Args:
        league_name: URL-friendly league name

    Returns:
        JSON with list of teams and their rosters
    """
    db_league_name = get_db_league_name(league_name)
    if not db_league_name:
        return jsonify({"msg": f"Invalid league name: {league_name}"}), 400

    with managed_session() as session:
        current_league, _ = DraftService.get_league_data(db_league_name)

        if not current_league:
            return jsonify({"msg": f"No current {db_league_name} league found"}), 404

        teams = [t for t in current_league.teams if t.name != "Practice"]

        teams_data = []
        for team in teams:
            team_players = [p for p in team.players if p.is_current_player]

            # Count positions on team
            position_counts = {}
            for player in team_players:
                pos = player.favorite_position or 'Unknown'
                position_counts[pos] = position_counts.get(pos, 0) + 1

            teams_data.append({
                "id": team.id,
                "name": team.name,
                "player_count": len(team_players),
                "position_breakdown": position_counts
            })

        return jsonify({"teams": teams_data}), 200


@mobile_api_v2.route('/draft/<league_name>/team/<int:team_id>/roster', methods=['GET'])
@jwt_required()
@jwt_role_required(['Pub League Coach', 'ECS FC Coach', 'Pub League Admin', 'Global Admin'])
def get_team_roster(league_name: str, team_id: int):
    """
    Get detailed roster for a specific team.

    Args:
        league_name: URL-friendly league name
        team_id: Team ID

    Returns:
        JSON with team roster and player details
    """
    db_league_name = get_db_league_name(league_name)
    if not db_league_name:
        return jsonify({"msg": f"Invalid league name: {league_name}"}), 400

    with managed_session() as session:
        current_league, _ = DraftService.get_league_data(db_league_name)

        if not current_league:
            return jsonify({"msg": f"No current {db_league_name} league found"}), 404

        # Get team
        team = session.query(Team).filter(
            Team.id == team_id,
            Team.league_id == current_league.id
        ).first()

        if not team:
            return jsonify({"msg": f"Team not found in {db_league_name}"}), 404

        # Get team players with enhanced data
        team_players = [p for p in team.players if p.is_current_player]
        players = DraftService.get_enhanced_player_data(
            team_players,
            current_league.season_id
        )

        return jsonify({
            "team_id": team.id,
            "team_name": team.name,
            "player_count": len(players),
            "players": players
        }), 200


@mobile_api_v2.route('/draft/<league_name>/pick', methods=['POST'])
@jwt_required()
@jwt_role_required(['Pub League Coach', 'ECS FC Coach', 'Pub League Admin', 'Global Admin'])
def draft_player(league_name: str):
    """
    Draft a player to a team.

    Args:
        league_name: URL-friendly league name

    Expected JSON:
        player_id: ID of player to draft
        team_id: ID of team to draft player to

    Returns:
        JSON with draft result
    """
    db_league_name = get_db_league_name(league_name)
    if not db_league_name:
        return jsonify({"msg": f"Invalid league name: {league_name}"}), 400

    data = request.get_json()
    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    player_id = data.get('player_id')
    team_id = data.get('team_id')

    if not player_id or not team_id:
        return jsonify({"msg": "Missing player_id or team_id"}), 400

    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        # Get current user
        user = session.query(User).get(current_user_id)
        if not user:
            return jsonify({"msg": "User not found"}), 404

        # Get league from current season
        league = session.query(League).join(Season).filter(
            League.name == db_league_name,
            Season.is_current == True
        ).first()

        if not league:
            return jsonify({"msg": "League not found"}), 404

        # Get player and team
        player = session.query(Player).get(player_id)
        team = session.query(Team).filter(
            Team.id == team_id,
            Team.league_id == league.id
        ).first()

        if not player:
            return jsonify({"msg": "Player not found"}), 404
        if not team:
            return jsonify({"msg": "Team not found in this league"}), 404

        # Check if player is already on a team in this league
        existing = session.query(player_teams).filter(
            player_teams.c.player_id == player_id,
            player_teams.c.team_id.in_(
                session.query(Team.id).filter(Team.league_id == league.id)
            )
        ).first()

        # ECS FC allows multi-team membership, skip check for ECS FC leagues
        if existing and not is_ecs_fc_league(league.id):
            return jsonify({"msg": "Player is already on a team in this league"}), 400

        # Add player to team
        team.players.append(player)
        player.primary_team_id = team_id

        # Record draft pick
        try:
            draft_position = DraftService.record_draft_pick(
                session=session,
                player_id=player_id,
                team_id=team_id,
                league_id=league.id,
                season_id=league.season_id,
                drafted_by_user_id=current_user_id,
                notes=f"Drafted via mobile API by {user.username}"
            )
        except Exception as e:
            logger.error(f"Failed to record draft pick: {e}")
            draft_position = 0

        session.commit()

        # Mark player for Discord update
        mark_player_for_discord_update(session, player_id)

        # Queue Discord role assignment
        assign_roles_to_player_task.delay(player_id=player_id, only_add=True)

        # Invalidate cache
        DraftCacheService.invalidate_league_cache(db_league_name)

        return jsonify({
            "success": True,
            "message": f"{player.name} drafted to {team.name}",
            "player": {
                "id": player.id,
                "name": player.name,
                "position": player.favorite_position
            },
            "team": {
                "id": team.id,
                "name": team.name
            },
            "draft_position": draft_position
        }), 200


@mobile_api_v2.route('/draft/<league_name>/pick/<int:player_id>', methods=['DELETE'])
@jwt_required()
@jwt_role_required(['Pub League Coach', 'ECS FC Coach', 'Pub League Admin', 'Global Admin'])
def remove_player_from_team(league_name: str, player_id: int):
    """
    Remove a player from their team (return to available pool).

    Args:
        league_name: URL-friendly league name
        player_id: ID of player to remove

    Returns:
        JSON with removal result
    """
    db_league_name = get_db_league_name(league_name)
    if not db_league_name:
        return jsonify({"msg": f"Invalid league name: {league_name}"}), 400

    with managed_session() as session:
        # Get league from current season
        league = session.query(League).join(Season).filter(
            League.name == db_league_name,
            Season.is_current == True
        ).first()

        if not league:
            return jsonify({"msg": "League not found"}), 404

        # Get player
        player = session.query(Player).options(
            selectinload(Player.teams)
        ).get(player_id)

        if not player:
            return jsonify({"msg": "Player not found"}), 404

        # Find which team the player is on in this league
        team = None
        for t in player.teams:
            if t.league_id == league.id:
                team = t
                break

        if not team:
            return jsonify({"msg": "Player is not on a team in this league"}), 400

        team_name = team.name

        # Remove player from team
        team.players.remove(player)

        # Clear primary team if it was this team
        if player.primary_team_id == team.id:
            player.primary_team_id = None

        # Remove from draft history
        try:
            DraftService.remove_draft_pick(
                session=session,
                player_id=player_id,
                season_id=league.season_id,
                league_id=league.id
            )
        except Exception as e:
            logger.error(f"Failed to remove draft pick record: {e}")

        session.commit()

        # Mark player for Discord update and remove roles
        mark_player_for_discord_update(session, player_id)
        remove_player_roles_task.delay(player_id=player_id)

        # Invalidate cache
        DraftCacheService.invalidate_league_cache(db_league_name)

        return jsonify({
            "success": True,
            "message": f"{player.name} removed from {team_name}",
            "player_id": player_id,
            "player_name": player.name
        }), 200


@mobile_api_v2.route('/draft/<league_name>/team/<int:team_id>/analysis', methods=['GET'])
@jwt_required()
@jwt_role_required(['Pub League Coach', 'ECS FC Coach', 'Pub League Admin', 'Global Admin'])
def get_team_position_analysis(league_name: str, team_id: int):
    """
    Get position analysis for a team showing needs and recommended players.

    Args:
        league_name: URL-friendly league name
        team_id: Team ID

    Returns:
        JSON with position needs and player recommendations
    """
    db_league_name = get_db_league_name(league_name)
    if not db_league_name:
        return jsonify({"msg": f"Invalid league name: {league_name}"}), 400

    with managed_session() as session:
        try:
            from app.draft_position_analyzer import PositionAnalyzer
        except ImportError:
            return jsonify({"msg": "Position analyzer not available"}), 500

        # Get league from current season
        league = session.query(League).join(Season).filter(
            League.name == db_league_name,
            Season.is_current == True
        ).first()

        if not league:
            return jsonify({"msg": "League not found"}), 404

        # Get team
        team = session.query(Team).filter(
            Team.id == team_id,
            Team.league_id == league.id
        ).first()

        if not team:
            return jsonify({"msg": "Team not found in this league"}), 404

        # Get current team players
        team_players = [p for p in team.players if p.is_current_player]

        # Calculate team needs
        team_needs = PositionAnalyzer.calculate_team_needs(team_players)

        # Get available players
        all_teams = session.query(Team).filter(Team.league_id == league.id).all()
        drafted_player_ids = set()
        for t in all_teams:
            drafted_player_ids.update([p.id for p in t.players])

        available_players = session.query(Player).filter(
            Player.is_current_player == True,
            ~Player.id.in_(drafted_player_ids)
        ).limit(50).all()  # Limit for performance

        # Calculate fit scores
        player_recommendations = []
        for player in available_players:
            fit_score = PositionAnalyzer.calculate_fit_score(player, team_needs)
            if fit_score > 0:
                player_recommendations.append({
                    "player_id": player.id,
                    "player_name": player.name,
                    "position": player.favorite_position,
                    "fit_score": fit_score,
                    "fit_category": PositionAnalyzer.get_fit_category(fit_score)
                })

        # Sort by fit score descending
        player_recommendations.sort(key=lambda x: x['fit_score'], reverse=True)

        return jsonify({
            "team_id": team.id,
            "team_name": team.name,
            "current_roster_size": len(team_players),
            "position_needs": team_needs,
            "recommended_players": player_recommendations[:20]  # Top 20
        }), 200


@mobile_api_v2.route('/draft/<league_name>/history', methods=['GET'])
@jwt_required()
@jwt_role_required(['Pub League Coach', 'ECS FC Coach', 'Pub League Admin', 'Global Admin'])
def get_draft_history(league_name: str):
    """
    Get draft order history for a league.

    Args:
        league_name: URL-friendly league name

    Query Parameters:
        page: Page number (default: 1)
        per_page: Items per page (default: 50, max: 100)

    Returns:
        JSON with draft history
    """
    db_league_name = get_db_league_name(league_name)
    if not db_league_name:
        return jsonify({"msg": f"Invalid league name: {league_name}"}), 400

    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 50, type=int), 100)

    with managed_session() as session:
        # Get league from current season
        league = session.query(League).join(Season).filter(
            League.name == db_league_name,
            Season.is_current == True
        ).first()

        if not league:
            return jsonify({"msg": "League not found"}), 404

        # Get draft history
        query = session.query(DraftOrderHistory).options(
            joinedload(DraftOrderHistory.player),
            joinedload(DraftOrderHistory.team),
            joinedload(DraftOrderHistory.drafter)
        ).filter(
            DraftOrderHistory.league_id == league.id,
            DraftOrderHistory.season_id == league.season_id
        ).order_by(DraftOrderHistory.draft_position.asc())

        total_count = query.count()

        query = query.offset((page - 1) * per_page).limit(per_page)
        picks = query.all()

        history = []
        for pick in picks:
            history.append({
                "position": pick.draft_position,
                "player": {
                    "id": pick.player.id,
                    "name": pick.player.name
                } if pick.player else None,
                "team": {
                    "id": pick.team.id,
                    "name": pick.team.name
                } if pick.team else None,
                "drafted_by": pick.drafter.username if pick.drafter else None,
                "drafted_at": pick.created_at.isoformat() if pick.created_at else None
            })

        return jsonify({
            "history": history,
            "total": total_count,
            "page": page,
            "per_page": per_page,
            "total_pages": (total_count + per_page - 1) // per_page
        }), 200
