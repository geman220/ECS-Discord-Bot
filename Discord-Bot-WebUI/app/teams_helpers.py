# app/teams_helpers.py

"""
Teams Helpers Module

This module provides helper functions for populating team statistics,
updating league standings, and processing player events in match reports.
It also includes functions to update individual player statistics and
retrieve the current season ID.
"""

import logging
from flask import g
from sqlalchemy import func, or_
from app.models import (
    db, Player, PlayerSeasonStats, PlayerCareerStats, Season, Standings,
    Match, PlayerEvent, PlayerEventType, Team, League, player_teams
)

logger = logging.getLogger(__name__)


def populate_team_stats(team, season):
    """
    Calculate and return statistical data for a given team and season.
    Uses optimized cached team stats to avoid N+1 queries.
    """
    from app.team_performance_helpers import get_team_stats_cached
    
    # Get cached stats from our optimized helper
    cached_stats = get_team_stats_cached(team.id)
    
    # Parse the formatted strings to extract names and numbers
    top_scorer_text = cached_stats['top_scorer']
    top_assist_text = cached_stats['top_assist']
    
    # Extract top scorer info
    if top_scorer_text == "No data":
        top_scorer_name, top_scorer_goals = "No goals scored", 0
    else:
        # Parse "Player Name (X goals)" format
        import re
        match = re.match(r'(.+?) \((\d+) goals?\)', top_scorer_text)
        if match:
            top_scorer_name, top_scorer_goals = match.groups()
            top_scorer_goals = int(top_scorer_goals)
        else:
            top_scorer_name, top_scorer_goals = "No goals scored", 0
    
    # Extract top assister info
    if top_assist_text == "No data":
        top_assister_name, top_assister_assists = "No assists recorded", 0
    else:
        # Parse "Player Name (X assists)" format
        match = re.match(r'(.+?) \((\d+) assists?\)', top_assist_text)
        if match:
            top_assister_name, top_assister_assists = match.groups()
            top_assister_assists = int(top_assister_assists)
        else:
            top_assister_name, top_assister_assists = "No assists recorded", 0

    return {
        "top_scorer_name": top_scorer_name,
        "top_scorer_goals": top_scorer_goals,
        "top_assister_name": top_assister_name,
        "top_assister_assists": top_assister_assists,
        "recent_form": "N/A",  # Keep this simple for now
        "avg_goals_per_match": cached_stats['avg_goals_per_match']
    }


def update_standings(session, match, old_home_score=None, old_away_score=None):
    home_team = match.home_team
    away_team = match.away_team
    season = home_team.league.season

    def get_standing(team):
        standing = session.query(Standings).filter_by(team_id=team.id, season_id=season.id).first()
        if not standing:
            standing = Standings(team_id=team.id, season_id=season.id)
            # Set the team relationship so that standing.team is not None.
            standing.team = team
            session.add(standing)
            logger.info(f"Created new standings record for team_id={team.id}, season_id={season.id}")
        return standing

    home_standing = get_standing(home_team)
    away_standing = get_standing(away_team)

    # Revert old match result if previous scores are provided.
    if old_home_score is not None and old_away_score is not None:
        logger.info(f"Reverting old result for Match ID: {match.id}, old scores: {old_home_score}-{old_away_score}")
        adjust_standings(home_standing, away_standing, old_home_score, old_away_score, subtract=True)

    logger.info(f"Applying new result for Match ID: {match.id}, new scores: {match.home_team_score}-{match.away_team_score}")
    adjust_standings(home_standing, away_standing, match.home_team_score, match.away_team_score)
    
    session.commit()
    logger.info(f"Standings updated and committed for Match ID: {match.id}")


def adjust_standings(home_standing, away_standing, home_score, away_score, subtract=False):
    logger.info(f"Adjusting standings: home_score={home_score}, away_score={away_score}, subtract={subtract}")
    logger.info(f"Before adjustment: home_standing={home_standing.to_dict() if hasattr(home_standing, 'to_dict') else home_standing}, away_standing={away_standing.to_dict() if hasattr(away_standing, 'to_dict') else away_standing}")
    
    multiplier = -1 if subtract else 1

    def safe_update(obj, attr, delta):
        current = getattr(obj, attr) or 0
        setattr(obj, attr, current + delta)

    if home_score > away_score:
        safe_update(home_standing, 'wins', 1 * multiplier)
        safe_update(away_standing, 'losses', 1 * multiplier)
    elif home_score < away_score:
        safe_update(home_standing, 'losses', 1 * multiplier)
        safe_update(away_standing, 'wins', 1 * multiplier)
    else:
        safe_update(home_standing, 'draws', 1 * multiplier)
        safe_update(away_standing, 'draws', 1 * multiplier)

    safe_update(home_standing, 'goals_for', home_score * multiplier)
    safe_update(home_standing, 'goals_against', away_score * multiplier)
    safe_update(away_standing, 'goals_for', away_score * multiplier)
    safe_update(away_standing, 'goals_against', home_score * multiplier)

    # Recalculate goal difference and points using safe defaults.
    home_standing.goal_difference = (home_standing.goals_for or 0) - (home_standing.goals_against or 0)
    away_standing.goal_difference = (away_standing.goals_for or 0) - (away_standing.goals_against or 0)

    home_standing.points = (home_standing.wins or 0) * 3 + (home_standing.draws or 0)
    away_standing.points = (away_standing.wins or 0) * 3 + (away_standing.draws or 0)

    safe_update(home_standing, 'played', 1 * multiplier)
    safe_update(away_standing, 'played', 1 * multiplier)

    logger.info(f"After adjustment: home_standing={home_standing.to_dict() if hasattr(home_standing, 'to_dict') else home_standing}, away_standing={away_standing.to_dict() if hasattr(away_standing, 'to_dict') else away_standing}")


def process_own_goals(session, match, data, add_key, remove_key):
    """
    Process own goal events for a match: remove and add/update events.
    Own goals are team events, not player events.
    """
    logger.info(f"Processing OWN_GOAL events for Match ID {match.id}")
    events_to_add = data.get(add_key, [])
    events_to_remove = data.get(remove_key, [])

    logger.info(f"Own goals to add: {len(events_to_add)}, Own goals to remove: {len(events_to_remove)}")

    # Process removals first
    for event_data in events_to_remove:
        stat_id = event_data.get('stat_id')
        if stat_id:
            event = session.query(PlayerEvent).get(stat_id)
            if event:
                session.delete(event)
                logger.info(f"Removed OWN_GOAL: Stat ID {stat_id} for team_id={event.team_id}")
            else:
                logger.warning(f"Own goal event with Stat ID {stat_id} not found.")

    # Process additions or updates
    for event_data in events_to_add:
        team_id = int(event_data.get('team_id'))
        minute = event_data.get('minute')
        stat_id = event_data.get('stat_id')

        # Validate that team is part of this match
        if team_id not in [match.home_team_id, match.away_team_id]:
            logger.error(f"Team ID {team_id} not part of this match.")
            raise ValueError(f"Team ID {team_id} not part of this match.")

        if stat_id:
            # Update existing own goal
            event = session.query(PlayerEvent).get(stat_id)
            if event:
                event.team_id = team_id
                event.minute = minute
                logger.info(f"Updated OWN_GOAL: Stat ID {stat_id} for team_id={team_id}")
            else:
                logger.warning(f"Own goal event with Stat ID {stat_id} not found for update.")
        else:
            # Create new own goal event
            event = PlayerEvent(
                player_id=None,  # Own goals don't have a player
                team_id=team_id,
                match_id=match.id,
                minute=minute,
                event_type=PlayerEventType.OWN_GOAL
            )
            session.add(event)
            logger.info(f"Added new OWN_GOAL for team_id={team_id} at minute {minute}")


def process_events(session, match, data, event_type, add_key, remove_key):
    """
    Process player events for a match: remove and add/update events.
    """
    logger.info(f"Processing {event_type.name} events for Match ID {match.id}")
    events_to_add = data.get(add_key, [])
    events_to_remove = data.get(remove_key, [])

    logger.info(f"Events to add: {len(events_to_add)}, Events to remove: {len(events_to_remove)}")

    # Process removals first
    for event_data in events_to_remove:
        stat_id = event_data.get('stat_id')
        if stat_id:
            event = session.query(PlayerEvent).get(stat_id)
            if event:
                # Update player stats BEFORE deleting the event; pass match to update_player_stats
                update_player_stats(session, event.player_id, event_type.value, match, increment=False)
                session.delete(event)
                logger.info(f"Removed {event_type.name}: Stat ID {stat_id} for player_id={event.player_id}")
            else:
                logger.warning(f"Event with Stat ID {stat_id} not found.")

    # Process additions or updates
    for event_data in events_to_add:
        player_id = int(event_data.get('player_id'))
        minute = event_data.get('minute')
        stat_id = event_data.get('stat_id')

        player = session.query(Player).filter(
            Player.id == player_id,
            or_(
                Player.primary_team_id.in_([match.home_team_id, match.away_team_id]),
                Player.teams.any(Team.id.in_([match.home_team_id, match.away_team_id]))
            )
        ).first()

        if not player:
            logger.error(f"Player ID {player_id} not part of this match.")
            raise ValueError(f"Player ID {player_id} not part of this match.")

        if stat_id:
            event = session.query(PlayerEvent).get(stat_id)
            if event:
                if event.player_id != player_id:
                    # If player changed, update stats for both old and new player
                    update_player_stats(session, event.player_id, event_type.value, match, increment=False)
                    update_player_stats(session, player_id, event_type.value, match, increment=True)
                    event.player_id = player_id
                event.minute = minute
                logger.info(f"Updated {event_type.name}: Stat ID {stat_id}")
            else:
                logger.warning(f"Event with Stat ID {stat_id} not found.")
        else:
            # Create new event and update player stats
            new_event = PlayerEvent(
                player_id=player_id,
                match_id=match.id,
                minute=minute,
                event_type=event_type
            )
            session.add(new_event)
            logger.info(f"Calling update_player_stats for player_id={player_id}, event_type={event_type.value}")
            update_player_stats(session, player_id, event_type.value, match)
            logger.info("Finished updating player stats")
            logger.info(f"Added {event_type.name}: Player ID {player_id}")

    # Commit changes to persist events and stats using the passed session
    session.commit()
    logger.info(f"Events processed and committed for Match ID {match.id}")


def update_player_stats(session, player_id, event_type, match, increment=True):
    """
    Update the player's season and career statistics based on an event.
    """
    logger.info(f"Updating stats for player_id={player_id}, event_type={event_type}, increment={increment}")

    # Use the season from the match's league instead of a global current season.
    season = match.home_team.league.season
    if not season:
        logger.error("No season found from the match's league. Cannot update player stats.")
        return
    season_id = season.id
    adjustment = 1 if increment else -1

    # Retrieve the season stats record for this season.
    season_stats = session.query(PlayerSeasonStats).filter_by(
        player_id=player_id, season_id=season_id
    ).first()
    if not season_stats:
        logger.info(f"Creating new season stats record for player_id={player_id}, season_id={season_id}")
        season_stats = PlayerSeasonStats(
            player_id=player_id,
            season_id=season_id,
            goals=0,
            assists=0,
            yellow_cards=0,
            red_cards=0
        )
        session.add(season_stats)

    # Retrieve the career stats record.
    career_stats = session.query(PlayerCareerStats).filter_by(player_id=player_id).first()
    if not career_stats:
        logger.info(f"Creating new career stats record for player_id={player_id}")
        career_stats = PlayerCareerStats(
            player_id=player_id,
            goals=0,
            assists=0,
            yellow_cards=0,
            red_cards=0
        )
        session.add(career_stats)

    def update_stat(stat_name):
        current_season_value = getattr(season_stats, stat_name) or 0
        new_season_value = max(current_season_value + adjustment, 0)
        setattr(season_stats, stat_name, new_season_value)
        logger.info(f"Updated season {stat_name} for player_id={player_id}: {current_season_value} → {new_season_value}")

        current_career_value = getattr(career_stats, stat_name) or 0
        new_career_value = max(current_career_value + adjustment, 0)
        setattr(career_stats, stat_name, new_career_value)
        logger.info(f"Updated career {stat_name} for player_id={player_id}: {current_career_value} → {new_career_value}")

    if event_type == PlayerEventType.GOAL.value:
        update_stat('goals')
    elif event_type == PlayerEventType.ASSIST.value:
        update_stat('assists')
    elif event_type == PlayerEventType.YELLOW_CARD.value:
        update_stat('yellow_cards')
    elif event_type == PlayerEventType.RED_CARD.value:
        update_stat('red_cards')

    session.commit()
    logger.info(f"Stats update committed for player_id={player_id}, event_type={event_type}")


def current_season_id(session):
    current_season = session.query(Season).filter_by(is_current=True).first()
    logger.info(f"Current season: {current_season.id if current_season else None}")
    return current_season.id if current_season else None