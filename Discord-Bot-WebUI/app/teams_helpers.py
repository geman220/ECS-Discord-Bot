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
    Match, PlayerEvent, PlayerEventType, Team, League, player_teams, Schedule
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
    """Recompute standings from all match results for both teams involved."""
    home_team = match.home_team
    away_team = match.away_team
    season = home_team.league.season

    for team in (home_team, away_team):
        recompute_team_standings(session, team, season)

    session.commit()
    logger.info(f"Standings recomputed and committed for Match ID: {match.id}")


def recompute_team_standings(session, team, season):
    """Recompute a single team's standings from all reported matches in the season."""
    standing = session.query(Standings).filter_by(team_id=team.id, season_id=season.id).first()
    if not standing:
        standing = Standings(team_id=team.id, season_id=season.id)
        standing.team = team
        session.add(standing)
        logger.info(f"Created new standings record for team_id={team.id}, season_id={season.id}")

    # Query all reported matches for this team in this season
    matches = (
        session.query(Match)
        .join(Schedule, Match.schedule_id == Schedule.id)
        .filter(
            Schedule.season_id == season.id,
            or_(Match.home_team_id == team.id, Match.away_team_id == team.id),
            Match.home_team_score.isnot(None),
            Match.away_team_score.isnot(None),
        )
        .all()
    )

    wins = draws = losses = gf = ga = 0
    for m in matches:
        is_home = m.home_team_id == team.id
        team_goals = m.home_team_score if is_home else m.away_team_score
        opp_goals = m.away_team_score if is_home else m.home_team_score
        gf += team_goals
        ga += opp_goals
        if team_goals > opp_goals:
            wins += 1
        elif team_goals == opp_goals:
            draws += 1
        else:
            losses += 1

    standing.played = len(matches)
    standing.wins = wins
    standing.draws = draws
    standing.losses = losses
    standing.goals_for = gf
    standing.goals_against = ga
    standing.goal_difference = gf - ga
    standing.points = (wins * 3) + draws

    logger.info(f"Recomputed standings for team_id={team.id}: P={standing.played} W={wins} D={draws} L={losses} GF={gf} GA={ga} Pts={standing.points}")



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
                update_player_stats(session, event.player_id, event_type.value, match, increment=False, is_sub_event=event.is_sub_event)
                session.delete(event)
                logger.info(f"Removed {event_type.name}: Stat ID {stat_id} for player_id={event.player_id}")
            else:
                logger.warning(f"Event with Stat ID {stat_id} not found.")

    # Process additions or updates
    for event_data in events_to_add:
        player_id = int(event_data.get('player_id'))
        minute = event_data.get('minute')
        stat_id = event_data.get('stat_id')

        # Check if player is on one of the match teams (roster or temp sub)
        player = session.query(Player).filter(
            Player.id == player_id,
            or_(
                Player.primary_team_id.in_([match.home_team_id, match.away_team_id]),
                Player.teams.any(Team.id.in_([match.home_team_id, match.away_team_id]))
            )
        ).first()

        # Also accept temp subs assigned to this match
        from app.utils.substitute_helpers import is_player_temp_sub_for_match
        is_sub = False
        if not player:
            is_sub = is_player_temp_sub_for_match(player_id, match.id, session=session)
            if is_sub:
                player = session.query(Player).get(player_id)

        if not player:
            logger.error(f"Player ID {player_id} not part of this match.")
            raise ValueError(f"Player ID {player_id} not part of this match.")

        if not is_sub:
            is_sub = is_player_temp_sub_for_match(player_id, match.id, session=session)

        if stat_id:
            event = session.query(PlayerEvent).get(stat_id)
            if event:
                if event.player_id != player_id:
                    # If player changed, update stats for both old and new player
                    old_is_sub = event.is_sub_event
                    update_player_stats(session, event.player_id, event_type.value, match, increment=False, is_sub_event=old_is_sub)
                    update_player_stats(session, player_id, event_type.value, match, increment=True, is_sub_event=is_sub)
                    event.player_id = player_id
                    event.is_sub_event = is_sub
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
                event_type=event_type,
                is_sub_event=is_sub
            )
            session.add(new_event)
            logger.info(f"Calling update_player_stats for player_id={player_id}, event_type={event_type.value}, is_sub={is_sub}")
            update_player_stats(session, player_id, event_type.value, match, is_sub_event=is_sub)
            logger.info("Finished updating player stats")
            logger.info(f"Added {event_type.name}: Player ID {player_id}")

    # Commit changes to persist events and stats using the passed session
    session.commit()
    logger.info(f"Events processed and committed for Match ID {match.id}")


def update_player_stats(session, player_id, event_type, match, increment=True, is_sub_event=False):
    """
    Update the player's season and career statistics based on an event.

    Stats are now separated by league to ensure proper attribution:
    - A player on both Premier and Classic has separate stat records per league
    - Golden Boot is calculated per-league, not combined across leagues
    - Career stats continue to aggregate across all leagues
    - Sub events only update career stats (subs are excluded from season awards)
    """
    logger.info(f"Updating stats for player_id={player_id}, event_type={event_type}, increment={increment}, is_sub_event={is_sub_event}")

    # Get league and season from the match's team
    league = match.home_team.league
    if not league:
        logger.error("No league found from the match's home team. Cannot update player stats.")
        return

    season = league.season
    if not season:
        logger.error("No season found from the match's league. Cannot update player stats.")
        return

    season_id = season.id
    league_id = league.id
    adjustment = 1 if increment else -1

    # Sub events skip season stats — subs should not be eligible for golden/silver boot
    if not is_sub_event:
        season_stats = session.query(PlayerSeasonStats).filter_by(
            player_id=player_id, season_id=season_id, league_id=league_id
        ).first()
        if not season_stats:
            # No exact (player, season, league) match. Before creating a new row,
            # check for a legacy NULL-league_id row for this (player, season) and
            # upgrade it in place if it's still empty. Prevents recreating the
            # same NULL-vs-league_id duplicate that this fix is closing.
            legacy = session.query(PlayerSeasonStats).filter_by(
                player_id=player_id, season_id=season_id, league_id=None
            ).first()
            if legacy and legacy.goals == 0 and legacy.assists == 0 \
                    and legacy.yellow_cards == 0 and legacy.red_cards == 0:
                legacy.league_id = league_id
                season_stats = legacy
            else:
                logger.info(f"Creating new season stats record for player_id={player_id}, season_id={season_id}, league_id={league_id}")
                season_stats = PlayerSeasonStats(
                    player_id=player_id,
                    season_id=season_id,
                    league_id=league_id,
                    goals=0,
                    assists=0,
                    yellow_cards=0,
                    red_cards=0
                )
                session.add(season_stats)
    else:
        season_stats = None
        logger.info(f"Skipping season stats for sub event: player_id={player_id}")

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
        if season_stats is not None:
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