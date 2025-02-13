# app/stat_helpers.py

"""
Stat Helpers Module

This module provides helper functions for updating player statistics,
specifically for decrementing stats (such as goals, assists, yellow cards, and red cards)
when a player event is reversed. It logs current stats before making changes and
ensures proper session management.
"""

from flask import current_app, g
from app.models import Player, PlayerSeasonStats, PlayerEventType
from app.teams_helpers import current_season_id
import logging

logger = logging.getLogger(__name__)


def decrement_player_stats(player_id, event_type):
    """
    Decrement the player's season and career statistics based on the event type.

    Retrieves the player and their corresponding season and career stats.
    Logs the current stats before decrementing. If the specified stat is above 0,
    it decrements the stat value for both season and career stats.

    Args:
        player_id (int): The ID of the player.
        event_type (PlayerEventType): The type of event (e.g., GOAL, ASSIST, YELLOW_CARD, RED_CARD).

    Raises:
        Exception: Propagates any exceptions that occur during processing.
    """
    session = g.db_session
    try:
        player = session.query(Player).get(player_id)
        if not player:
            logger.error(f"Player {player_id} not found")
            return

        season_id = current_season_id()
        season_stats = session.query(PlayerSeasonStats).filter_by(
            player_id=player_id,
            season_id=season_id
        ).first()

        career_stats = player.career_stats[0] if player.career_stats else None

        if not season_stats or not career_stats:
            logger.error(f"Stats not found for Player {player_id}")
            return

        # Log current stats before decrementing.
        log_current_stats(season_stats, career_stats)

        # Map event types to the corresponding stat attribute and log message.
        event_stats_map = {
            PlayerEventType.GOAL: ('goals', 'Decremented goals'),
            PlayerEventType.ASSIST: ('assists', 'Decremented assists'),
            PlayerEventType.YELLOW_CARD: ('yellow_cards', 'Decremented yellow cards'),
            PlayerEventType.RED_CARD: ('red_cards', 'Decremented red cards')
        }

        if event_type in event_stats_map:
            stat_attr, log_msg = event_stats_map[event_type]
            decrement_stat(season_stats, career_stats, stat_attr, player_id, log_msg)
        else:
            logger.error(f"Unknown event type: {event_type}")

    except Exception as e:
        logger.error(f"Error decrementing stats: {str(e)}", exc_info=True)
        raise


def decrement_stat(season_stats, career_stats, stat_attr, player_id, log_msg):
    """
    Helper function to decrement a given stat safely for both season and career stats.

    Args:
        season_stats: The season statistics object.
        career_stats: The career statistics object.
        stat_attr (str): The name of the stat attribute to decrement.
        player_id (int): The ID of the player.
        log_msg (str): Log message to indicate the operation.
    """
    # Decrement season stat if greater than zero.
    season_stat_value = getattr(season_stats, stat_attr)
    if season_stat_value > 0:
        setattr(season_stats, stat_attr, season_stat_value - 1)
        current_app.logger.info(f"{log_msg} for Player ID: {player_id} in season stats")

    # Decrement career stat if greater than zero.
    career_stat_value = getattr(career_stats, stat_attr)
    if career_stat_value > 0:
        setattr(career_stats, stat_attr, career_stat_value - 1)
        current_app.logger.info(f"{log_msg} for Player ID: {player_id} in career stats")


def log_current_stats(season_stats, career_stats):
    """
    Log the current season and career statistics for a player before making changes.

    Args:
        season_stats: The season statistics object.
        career_stats: The career statistics object.
    """
    current_app.logger.info(
        f"Current Season Stats: Goals: {season_stats.goals}, Assists: {season_stats.assists}, "
        f"Yellow Cards: {season_stats.yellow_cards}, Red Cards: {season_stats.red_cards}"
    )
    current_app.logger.info(
        f"Current Career Stats: Goals: {career_stats.goals}, Assists: {career_stats.assists}, "
        f"Yellow Cards: {career_stats.yellow_cards}, Red Cards: {career_stats.red_cards}"
    )