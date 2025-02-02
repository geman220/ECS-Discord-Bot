from flask import current_app, g
from app.models import Player, PlayerSeasonStats, PlayerEventType
from app.teams_helpers import current_season_id
import logging

# Get the logger for this module
logger = logging.getLogger(__name__)

def decrement_player_stats(player_id, event_type):
    """Decrement player stats with proper session management."""
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

        log_current_stats(season_stats, career_stats)

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
    """Helper function to decrement a stat safely"""
    # Decrement season stat
    season_stat_value = getattr(season_stats, stat_attr)
    if season_stat_value > 0:
        setattr(season_stats, stat_attr, season_stat_value - 1)
        current_app.logger.info(f"{log_msg} for Player ID: {player_id} in season stats")

    # Decrement career stat
    career_stat_value = getattr(career_stats, stat_attr)
    if career_stat_value > 0:
        setattr(career_stats, stat_attr, career_stat_value - 1)
        current_app.logger.info(f"{log_msg} for Player ID: {player_id} in career stats")

def log_current_stats(season_stats, career_stats):
    """Log current stats before decrementing"""
    current_app.logger.info(
        f"Current Season Stats: Goals: {season_stats.goals}, Assists: {season_stats.assists}, "
        f"Yellow Cards: {season_stats.yellow_cards}, Red Cards: {season_stats.red_cards}"
    )
    current_app.logger.info(
        f"Current Career Stats: Goals: {career_stats.goals}, Assists: {career_stats.assists}, "
        f"Yellow Cards: {career_stats.yellow_cards}, Red Cards: {career_stats.red_cards}"
    )
