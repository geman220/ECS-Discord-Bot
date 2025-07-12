# app/team_performance_helpers.py

"""
Team Performance Helpers

Optimized functions to bulk-load team statistics and avoid N+1 queries.
Instead of running separate queries for each team's stats, these functions
calculate all team statistics in a single query.
"""

from sqlalchemy import func, case, text, or_
from sqlalchemy.orm import Session
from flask import g
from app.models import Player, PlayerSeasonStats, Match, player_teams
from app.performance_cache import cache_team_stats, cache_standings_data, set_standings_cache
import logging

logger = logging.getLogger(__name__)


@cache_team_stats(ttl=600)  # Cache for 10 minutes
def bulk_load_team_stats(team_ids, session=None):
    """
    Load statistics for multiple teams using simplified queries to avoid N+1 problems.
    Includes Redis caching for improved performance.
    
    Args:
        team_ids: List of team IDs to load stats for
        session: Database session (uses g.db_session if not provided)
    
    Returns:
        Dictionary mapping team_id to stats dict with keys:
        - top_scorer: "Player Name (X goals)" or "No data"
        - top_assist: "Player Name (X assists)" or "No data" 
        - total_goals: Total goals scored by team
        - total_assists: Total assists by team
        - matches_played: Number of matches played
        - avg_goals_per_match: Average goals per match
    """
    if session is None:
        session = g.db_session
    
    if not team_ids:
        return {}
    
    # Initialize results for all teams
    team_stats = {}
    for team_id in team_ids:
        team_stats[team_id] = {
            'top_scorer': 'No data',
            'top_assist': 'No data', 
            'total_goals': 0,
            'total_assists': 0,
            'matches_played': 1,  # Avoid division by zero
            'avg_goals_per_match': 0.0
        }
    
    # Get goal statistics with a simpler query
    goal_query = session.query(
        player_teams.c.team_id,
        Player.name,
        PlayerSeasonStats.goals
    ).select_from(
        player_teams
    ).join(
        Player, Player.id == player_teams.c.player_id
    ).join(
        PlayerSeasonStats, PlayerSeasonStats.player_id == Player.id
    ).filter(
        player_teams.c.team_id.in_(team_ids),
        PlayerSeasonStats.goals > 0
    ).order_by(
        player_teams.c.team_id,
        PlayerSeasonStats.goals.desc()
    ).all()
    
    # Process goal statistics
    team_goal_totals = {}
    team_top_scorers = {}
    
    for team_id, player_name, goals in goal_query:
        # Track total goals per team
        if team_id not in team_goal_totals:
            team_goal_totals[team_id] = 0
        team_goal_totals[team_id] += goals
        
        # Track top scorer per team (first one due to ordering)
        if team_id not in team_top_scorers:
            team_top_scorers[team_id] = f"{player_name} ({goals} goals)"
    
    # Get assist statistics with a simpler query
    assist_query = session.query(
        player_teams.c.team_id,
        Player.name,
        PlayerSeasonStats.assists
    ).select_from(
        player_teams
    ).join(
        Player, Player.id == player_teams.c.player_id
    ).join(
        PlayerSeasonStats, PlayerSeasonStats.player_id == Player.id
    ).filter(
        player_teams.c.team_id.in_(team_ids),
        PlayerSeasonStats.assists > 0
    ).order_by(
        player_teams.c.team_id,
        PlayerSeasonStats.assists.desc()
    ).all()
    
    # Process assist statistics
    team_assist_totals = {}
    team_top_assisters = {}
    
    for team_id, player_name, assists in assist_query:
        # Track total assists per team
        if team_id not in team_assist_totals:
            team_assist_totals[team_id] = 0
        team_assist_totals[team_id] += assists
        
        # Track top assister per team (first one due to ordering)
        if team_id not in team_top_assisters:
            team_top_assisters[team_id] = f"{player_name} ({assists} assists)"
    
    # Get match counts (simplified)
    home_matches = session.query(
        Match.home_team_id.label('team_id'),
        func.count(Match.id).label('matches')
    ).filter(
        Match.home_team_id.in_(team_ids)
    ).group_by(Match.home_team_id).all()
    
    away_matches = session.query(
        Match.away_team_id.label('team_id'),
        func.count(Match.id).label('matches')
    ).filter(
        Match.away_team_id.in_(team_ids)
    ).group_by(Match.away_team_id).all()
    
    # Combine match counts
    team_match_counts = {}
    for team_id, matches in home_matches:
        team_match_counts[team_id] = team_match_counts.get(team_id, 0) + matches
    for team_id, matches in away_matches:
        team_match_counts[team_id] = team_match_counts.get(team_id, 0) + matches
    
    # Update team stats with calculated values
    for team_id in team_ids:
        if team_id in team_goal_totals:
            team_stats[team_id]['total_goals'] = team_goal_totals[team_id]
            team_stats[team_id]['top_scorer'] = team_top_scorers.get(team_id, 'No data')
        
        if team_id in team_assist_totals:
            team_stats[team_id]['total_assists'] = team_assist_totals[team_id]
            team_stats[team_id]['top_assist'] = team_top_assisters.get(team_id, 'No data')
        
        if team_id in team_match_counts:
            team_stats[team_id]['matches_played'] = max(team_match_counts[team_id], 1)
        
        # Calculate average goals per match
        stats = team_stats[team_id]
        stats['avg_goals_per_match'] = round(
            stats['total_goals'] / stats['matches_played'], 2
        )
    
    return team_stats


def get_team_stats_cached(team_id, session=None):
    """
    Get statistics for a single team. Uses bulk loading if multiple teams
    are being accessed to avoid N+1 queries.
    
    Args:
        team_id: ID of the team
        session: Database session (uses g.db_session if not provided)
    
    Returns:
        Dictionary with team statistics
    """
    # Check if we have cached bulk stats in the request context
    if hasattr(g, '_team_stats_cache'):
        if team_id in g._team_stats_cache:
            return g._team_stats_cache[team_id]
    
    # Load stats for this single team
    stats = bulk_load_team_stats([team_id], session)
    return stats.get(team_id, {
        'top_scorer': 'No data',
        'top_assist': 'No data',
        'total_goals': 0,
        'total_assists': 0,
        'matches_played': 1,
        'avg_goals_per_match': 0.0
    })


def preload_team_stats_for_request(team_ids, session=None):
    """
    Preload team statistics for multiple teams at the start of a request.
    This prevents N+1 queries when team properties are accessed later.
    
    Call this at the beginning of any view that will access team statistics.
    
    Args:
        team_ids: List of team IDs that will be accessed in this request
        session: Database session (uses g.db_session if not provided)
    """
    if session is None:
        session = g.db_session
    
    # Load all stats in bulk and cache in request context
    g._team_stats_cache = bulk_load_team_stats(team_ids, session)
    logger.debug(f"Preloaded stats for {len(team_ids)} teams in single query")