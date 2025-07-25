# app/external_api/stats_utils.py

"""
Statistics calculation utilities with proper season vs career handling.
"""

import logging
from datetime import datetime
from sqlalchemy import func, desc, and_, or_

from app.core import db
from app.models import (
    Player, Team, Match, League, Season, 
    PlayerSeasonStats, PlayerCareerStats, PlayerEvent
)

logger = logging.getLogger(__name__)


def get_current_season():
    """Get the current active Pub League season."""
    return Season.query.filter(
        and_(
            Season.is_current == True,
            Season.league_type == 'Pub League'
        )
    ).first()


def get_season_goal_leaders(season_id=None, limit=10):
    """
    Get goal leaders for a specific season or current season.
    Falls back to calculating from PlayerEvent data if PlayerSeasonStats is empty.
    
    Args:
        season_id: Specific season ID, or None for current season
        limit: Number of top scorers to return
        
    Returns:
        List of (player_id, player_name, goals) tuples
    """
    # Default to current season if none specified
    if season_id is None:
        current_season = get_current_season()
        if current_season:
            season_id = current_season.id
        else:
            logger.warning("No current season found and no season_id provided")
            return []
    
    # First try PlayerSeasonStats
    stats_query = g.db_session.query(
        Player.id,
        Player.name,
        func.coalesce(func.sum(PlayerSeasonStats.goals), 0).label('season_goals')
    ).outerjoin(
        PlayerSeasonStats,
        and_(
            Player.id == PlayerSeasonStats.player_id,
            PlayerSeasonStats.season_id == season_id
        )
    ).filter(
        Player.is_current_player == True
    ).group_by(
        Player.id, Player.name
    ).order_by(
        desc('season_goals')
    ).limit(limit)
    
    results = stats_query.all()
    
    # Check if we have any non-zero goals from PlayerSeasonStats
    has_stats_data = any(result.season_goals > 0 for result in results)
    
    if not has_stats_data:
        # Fall back to calculating from PlayerEvent data
        logger.info(f"No PlayerSeasonStats data found for season {season_id}, calculating from PlayerEvent data")
        
        # Get teams for this season
        teams_in_season = Team.query.filter(Team.league.has(League.season_id == season_id)).all()
        team_ids = [team.id for team in teams_in_season]
        
        if team_ids:
            # Calculate goals from PlayerEvent records for matches involving teams in this season
            events_query = g.db_session.query(
                Player.id,
                Player.name,
                func.count(PlayerEvent.id).label('season_goals')
            ).join(
                PlayerEvent, Player.id == PlayerEvent.player_id
            ).join(
                Match, PlayerEvent.match_id == Match.id
            ).filter(
                and_(
                    PlayerEvent.event_type == 'GOAL',
                    or_(
                        Match.home_team_id.in_(team_ids),
                        Match.away_team_id.in_(team_ids)
                    ),
                    Player.is_current_player == True
                )
            ).group_by(
                Player.id, Player.name
            ).order_by(
                desc('season_goals')
            ).limit(limit)
            
            return events_query.all()
    
    return results


def get_career_goal_leaders(limit=10):
    """
    Get career goal leaders across all seasons.
    
    Args:
        limit: Number of top scorers to return
        
    Returns:
        List of (player_id, player_name, career_goals) tuples
    """
    query = g.db_session.query(
        Player.id,
        Player.name,
        func.coalesce(PlayerCareerStats.goals, 0).label('career_goals')
    ).outerjoin(
        PlayerCareerStats,
        Player.id == PlayerCareerStats.player_id
    ).filter(
        Player.is_current_player == True
    ).order_by(
        desc('career_goals')
    ).limit(limit)
    
    return query.all()


def get_season_assist_leaders(season_id=None, limit=10):
    """
    Get assist leaders for a specific season or current season.
    Falls back to calculating from PlayerEvent data if PlayerSeasonStats is empty.
    
    Args:
        season_id: Specific season ID, or None for current season
        limit: Number of top assist providers to return
        
    Returns:
        List of (player_id, player_name, assists) tuples
    """
    # Default to current season if none specified
    if season_id is None:
        current_season = get_current_season()
        if current_season:
            season_id = current_season.id
        else:
            logger.warning("No current season found and no season_id provided")
            return []
    
    # First try PlayerSeasonStats
    stats_query = g.db_session.query(
        Player.id,
        Player.name,
        func.coalesce(func.sum(PlayerSeasonStats.assists), 0).label('season_assists')
    ).outerjoin(
        PlayerSeasonStats,
        and_(
            Player.id == PlayerSeasonStats.player_id,
            PlayerSeasonStats.season_id == season_id
        )
    ).filter(
        Player.is_current_player == True
    ).group_by(
        Player.id, Player.name
    ).order_by(
        desc('season_assists')
    ).limit(limit)
    
    results = stats_query.all()
    
    # Check if we have any non-zero assists from PlayerSeasonStats
    has_stats_data = any(result.season_assists > 0 for result in results)
    
    if not has_stats_data:
        # Fall back to calculating from PlayerEvent data
        logger.info(f"No PlayerSeasonStats data found for season {season_id}, calculating from PlayerEvent data")
        
        # Get teams for this season
        teams_in_season = Team.query.filter(Team.league.has(League.season_id == season_id)).all()
        team_ids = [team.id for team in teams_in_season]
        
        if team_ids:
            # Calculate assists from PlayerEvent records for matches involving teams in this season
            events_query = g.db_session.query(
                Player.id,
                Player.name,
                func.count(PlayerEvent.id).label('season_assists')
            ).join(
                PlayerEvent, Player.id == PlayerEvent.player_id
            ).join(
                Match, PlayerEvent.match_id == Match.id
            ).filter(
                and_(
                    PlayerEvent.event_type == 'ASSIST',
                    or_(
                        Match.home_team_id.in_(team_ids),
                        Match.away_team_id.in_(team_ids)
                    ),
                    Player.is_current_player == True
                )
            ).group_by(
                Player.id, Player.name
            ).order_by(
                desc('season_assists')
            ).limit(limit)
            
            return events_query.all()
    
    return results


def get_player_season_stats(player_id, season_id=None):
    """
    Get comprehensive season stats for a specific player.
    
    Args:
        player_id: Player ID
        season_id: Season ID, or None for current season
        
    Returns:
        Dictionary with season stats or None
    """
    # Default to current season if none specified
    if season_id is None:
        current_season = get_current_season()
        if current_season:
            season_id = current_season.id
        else:
            return None
    
    stats = PlayerSeasonStats.query.filter(
        and_(
            PlayerSeasonStats.player_id == player_id,
            PlayerSeasonStats.season_id == season_id
        )
    ).first()
    
    if stats:
        return {
            'player_id': stats.player_id,
            'season_id': stats.season_id,
            'goals': stats.goals or 0,
            'assists': stats.assists or 0,
            'yellow_cards': stats.yellow_cards or 0,
            'red_cards': stats.red_cards or 0,
            'matches_played': stats.matches_played or 0
        }
    
    return {
        'player_id': player_id,
        'season_id': season_id,
        'goals': 0,
        'assists': 0,
        'yellow_cards': 0,
        'red_cards': 0,
        'matches_played': 0
    }


def get_season_matches_count(team_ids, season_id=None):
    """
    Get count of completed matches for teams in a specific season.
    
    Args:
        team_ids: List of team IDs
        season_id: Season ID, or None for current season
        
    Returns:
        Number of completed matches
    """
    if not team_ids:
        return 0
    
    # Default to current season if none specified
    if season_id is None:
        current_season = get_current_season()
        if current_season:
            season_id = current_season.id
        else:
            return 0
    
    match_filter = [
        or_(
            Match.home_team_id.in_(team_ids),
            Match.away_team_id.in_(team_ids)
        ),
        Match.home_team_score.isnot(None)  # Only completed matches
    ]
    
    # Filter by season through team's league
    if season_id:
        match_filter.append(
            or_(
                Match.home_team.has(Team.league.has(League.season_id == season_id)),
                Match.away_team.has(Team.league.has(League.season_id == season_id))
            )
        )
    
    return Match.query.filter(and_(*match_filter)).count()


def calculate_expected_attendance(available_count, maybe_count, maybe_factor=0.5):
    """
    Standardized attendance calculation used across all endpoints.
    
    Args:
        available_count: Number of players confirmed available
        maybe_count: Number of players marked as maybe
        maybe_factor: Weight given to maybe responses (default 0.5)
    
    Returns:
        Expected number of attendees
    """
    return available_count + (maybe_count * maybe_factor)


def get_substitution_urgency(expected_attendance, roster_size, min_players=8, ideal_players=13):
    """
    Standardized substitution urgency calculation for 8v8 format.
    
    Args:
        expected_attendance: Expected number of players
        roster_size: Total roster size
        min_players: Minimum players needed (default 8 for 8v8)
        ideal_players: Ideal number for balanced rotation (default 13 - allows 2 double shifts per shift)
    
    Returns:
        urgency level: 'critical', 'high', 'medium', 'low', 'none'
    """
    if expected_attendance < min_players:
        return 'critical'  # Cannot field a team
    elif expected_attendance < min_players + 2:
        return 'high'      # Can barely field team, no subs
    elif expected_attendance < min_players + 4:
        return 'medium'    # Limited substitution options (10-11 players)
    elif expected_attendance < ideal_players:
        return 'low'       # Some substitution depth but not optimal (12 players)
    else:
        return 'none'      # Ideal state - 13+ players allows balanced rotation