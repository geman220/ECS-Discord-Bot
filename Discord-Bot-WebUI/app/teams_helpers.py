# app/teams_helpers.py

"""
Teams Helpers Module

This module provides helper functions for populating team statistics,
updating league standings, and processing player events in match reports.
It also includes functions to update individual player statistics and
retrieve the current season ID.
"""

import logging
from sqlalchemy import func
from app.models import (
    db, Player, PlayerSeasonStats, PlayerCareerStats, Season, Standings,
    Match, PlayerEvent, PlayerEventType, Team, League
)

logger = logging.getLogger(__name__)


def populate_team_stats(team, season):
    """
    Calculate and return statistical data for a given team and season.

    This function computes:
      - Top scorer and top assister for the team.
      - Recent match form (last 5 matches) as a sequence of 'W', 'D', or 'L'.
      - Average goals per match.

    Args:
        team (Team): The team for which to calculate stats.
        season (Season): The season to consider.

    Returns:
        dict: A dictionary containing team stats including:
            - top_scorer_name
            - top_scorer_goals
            - top_assister_name
            - top_assister_assists
            - recent_form
            - avg_goals_per_match
    """
    # Calculate top scorer.
    top_scorer = db.session.query(Player.name, PlayerSeasonStats.goals).join(
        PlayerSeasonStats, Player.id == PlayerSeasonStats.player_id
    ).filter(
        PlayerSeasonStats.season_id == season.id,
        Player.team_id == team.id
    ).order_by(PlayerSeasonStats.goals.desc()).first()

    top_scorer_name, top_scorer_goals = (
        top_scorer if top_scorer and top_scorer[1] > 0 else ("No goals scored", 0)
    )

    # Calculate top assister.
    top_assister = db.session.query(Player.name, PlayerSeasonStats.assists).join(
        PlayerSeasonStats, Player.id == PlayerSeasonStats.player_id
    ).filter(
        PlayerSeasonStats.season_id == season.id,
        Player.team_id == team.id
    ).order_by(PlayerSeasonStats.assists.desc()).first()

    top_assister_name, top_assister_assists = (
        top_assister if top_assister and top_assister[1] > 0 else ("No assists recorded", 0)
    )

    # Fetch the last 5 matches to determine recent form.
    matches = Match.query.join(
        Team, ((Match.home_team_id == Team.id) | (Match.away_team_id == Team.id))
    ).join(
        League, Team.league_id == League.id
    ).filter(
        ((Match.home_team_id == team.id) | (Match.away_team_id == team.id)),
        League.season_id == season.id,
        Match.home_team_score.isnot(None),
        Match.away_team_score.isnot(None)
    ).order_by(Match.date.desc()).limit(5).all()

    recent_form_list = []
    for match in matches:
        if match.home_team_id == team.id:
            result = 'W' if match.home_team_score > match.away_team_score else 'D' if match.home_team_score == match.away_team_score else 'L'
        else:
            result = 'W' if match.away_team_score > match.home_team_score else 'D' if match.away_team_score == match.home_team_score else 'L'
        recent_form_list.append(result)

    recent_form = ' '.join(recent_form_list) if recent_form_list else "N/A"

    # Calculate average goals per match.
    total_goals = db.session.query(func.sum(PlayerSeasonStats.goals)).join(
        Player, PlayerSeasonStats.player_id == Player.id
    ).filter(
        PlayerSeasonStats.season_id == season.id,
        Player.team_id == team.id
    ).scalar() or 0

    matches_played = db.session.query(func.count(Match.id)).join(
        Team, ((Match.home_team_id == Team.id) | (Match.away_team_id == Team.id))
    ).join(
        League, Team.league_id == League.id
    ).filter(
        ((Match.home_team_id == team.id) | (Match.away_team_id == team.id)),
        League.season_id == season.id,
        Match.home_team_score.isnot(None),
        Match.away_team_score.isnot(None)
    ).scalar() or 0

    avg_goals_per_match = round(total_goals / matches_played, 2) if matches_played else 0

    return {
        "top_scorer_name": top_scorer_name,
        "top_scorer_goals": top_scorer_goals,
        "top_assister_name": top_assister_name,
        "top_assister_assists": top_assister_assists,
        "recent_form": recent_form,
        "avg_goals_per_match": avg_goals_per_match
    }


def update_standings(match, old_home_score=None, old_away_score=None):
    """
    Update league standings based on a match's outcome.

    Retrieves or creates standings for both home and away teams, then:
      - If previous scores exist, reverts the old result.
      - Applies the new match result to update wins, losses, draws, goals, goal difference, and points.

    Args:
        match (Match): The match object.
        old_home_score (int, optional): Previous home team score.
        old_away_score (int, optional): Previous away team score.
    """
    home_team = match.home_team
    away_team = match.away_team
    season = home_team.league.season

    # Helper function to fetch or create a team's standing for the season.
    def get_standing(team):
        standing = Standings.query.filter_by(team_id=team.id, season_id=season.id).first()
        if not standing:
            standing = Standings(team_id=team.id, season_id=season.id)
            db.session.add(standing)
        return standing

    home_standing = get_standing(home_team)
    away_standing = get_standing(away_team)

    # Revert old match result if previous scores are provided.
    if old_home_score is not None and old_away_score is not None:
        logger.info(f"Reverting old result for Match ID: {match.id}")
        adjust_standings(home_standing, away_standing, old_home_score, old_away_score, subtract=True)

    # Apply the new match result.
    adjust_standings(home_standing, away_standing, match.home_team_score, match.away_team_score)


def adjust_standings(home_standing, away_standing, home_score, away_score, subtract=False):
    """
    Adjust the standings for both home and away teams based on match scores.

    Args:
        home_standing: Standing object for the home team.
        away_standing: Standing object for the away team.
        home_score (int): Home team score.
        away_score (int): Away team score.
        subtract (bool, optional): If True, subtracts the result (used for reverting). Defaults to False.
    """
    multiplier = -1 if subtract else 1
    if home_score > away_score:
        home_standing.wins += 1 * multiplier
        away_standing.losses += 1 * multiplier
    elif home_score < away_score:
        home_standing.losses += 1 * multiplier
        away_standing.wins += 1 * multiplier
    else:
        home_standing.draws += 1 * multiplier
        away_standing.draws += 1 * multiplier

    home_standing.goals_for += home_score * multiplier
    home_standing.goals_against += away_score * multiplier
    away_standing.goals_for += away_score * multiplier
    away_standing.goals_against += home_score * multiplier

    home_standing.goal_difference = home_standing.goals_for - home_standing.goals_against
    away_standing.goal_difference = away_standing.goals_for - away_standing.goals_against

    home_standing.points = home_standing.wins * 3 + home_standing.draws
    away_standing.points = away_standing.wins * 3 + away_standing.draws

    home_standing.played += 1 * multiplier
    away_standing.played += 1 * multiplier


def process_events(match, data, event_type, add_key, remove_key):
    """
    Process player events for a match: remove and add/update events.

    Args:
        match (Match): The match object.
        data (dict): Data containing events to add and remove.
        event_type (PlayerEventType): The type of event to process.
        add_key (str): Key in data for events to add.
        remove_key (str): Key in data for events to remove.
    """
    logger.info(f"Processing {event_type.name} events for Match ID {match.id}")
    events_to_add = data.get(add_key, [])
    events_to_remove = data.get(remove_key, [])

    # Process removals.
    for event_data in events_to_remove:
        stat_id = event_data.get('stat_id')
        if stat_id:
            event = PlayerEvent.query.get(stat_id)
            if event:
                update_player_stats(event.player_id, event.event_type.value, increment=False)
                db.session.delete(event)
                logger.info(f"Removed {event_type.name}: Stat ID {stat_id}")
            else:
                logger.warning(f"Event with Stat ID {stat_id} not found.")

    # Process additions or updates.
    for event_data in events_to_add:
        player_id = int(event_data.get('player_id'))
        minute = event_data.get('minute')
        stat_id = event_data.get('stat_id')

        player = Player.query.filter(
            Player.id == player_id,
            Player.team_id.in_([match.home_team_id, match.away_team_id])
        ).first()

        if not player:
            raise ValueError(f"Player ID {player_id} not part of this match.")

        if stat_id:
            event = PlayerEvent.query.get(stat_id)
            if event:
                if event.player_id != player_id:
                    update_player_stats(event.player_id, event_type.value, increment=False)
                    update_player_stats(player_id, event_type.value, increment=True)
                    event.player_id = player_id
                event.minute = minute
                logger.info(f"Updated {event_type.name}: Stat ID {stat_id}")
            else:
                logger.warning(f"Event with Stat ID {stat_id} not found.")
        else:
            new_event = PlayerEvent(
                player_id=player_id,
                match_id=match.id,
                minute=minute,
                event_type=event_type
            )
            db.session.add(new_event)
            update_player_stats(player_id, event_type.value)
            logger.info(f"Added {event_type.name}: Player ID {player_id}")


def update_player_stats(player_id, event_type, increment=True):
    """
    Update the player's season and career statistics based on an event.

    Args:
        player_id (int): The ID of the player.
        event_type (str): The event type value (e.g., 'goal', 'assist', etc.).
        increment (bool, optional): If True, increments stats; if False, decrements. Defaults to True.
    """
    logger.info(f"Updating stats for player_id={player_id}, event_type={event_type}, increment={increment}")
    season_id = current_season_id()
    adjustment = 1 if increment else -1

    season_stats = PlayerSeasonStats.query.filter_by(player_id=player_id, season_id=season_id).first()
    if not season_stats:
        season_stats = PlayerSeasonStats(player_id=player_id, season_id=season_id)
        db.session.add(season_stats)

    career_stats = PlayerCareerStats.query.filter_by(player_id=player_id).first()
    if not career_stats:
        career_stats = PlayerCareerStats(player_id=player_id)
        db.session.add(career_stats)

    def update_stat(stat_name):
        current_value = getattr(season_stats, stat_name) or 0
        setattr(season_stats, stat_name, max(current_value + adjustment, 0))
        current_value_career = getattr(career_stats, stat_name) or 0
        setattr(career_stats, stat_name, max(current_value_career + adjustment, 0))

    if event_type == PlayerEventType.GOAL.value:
        update_stat('goals')
    elif event_type == PlayerEventType.ASSIST.value:
        update_stat('assists')
    elif event_type == PlayerEventType.YELLOW_CARD.value:
        update_stat('yellow_cards')
    elif event_type == PlayerEventType.RED_CARD.value:
        update_stat('red_cards')


def current_season_id():
    """
    Retrieve the current season's ID.

    Returns:
        int: The current season ID, or None if no current season is found.
    """
    current_season = Season.query.filter_by(is_current=True).first()
    return current_season.id if current_season else None