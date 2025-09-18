# app/db_utils.py

"""
Database Utilities Module

This module provides helper functions for managing MLS match data,
including insertion, update, deletion, and bulk updates. It also includes
functions for formatting match display data, safely committing database
transactions, and updating Discord-related information for players and teams.
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from sqlalchemy.orm import joinedload, Session
from sqlalchemy.exc import SQLAlchemyError

from app.models import MLSMatch, Player, Team
from app.core.helpers import get_match
from app.core.session_manager import managed_session

logger = logging.getLogger(__name__)


def format_match_display_data(matches: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Format match display data with proper date formatting.

    Args:
        matches (List[Dict[str, Any]]): A list of match dictionaries.

    Returns:
        List[Dict[str, Any]]: The list with an additional 'formatted_date' key.
    """
    formatted_matches = []
    for match in matches:
        match_copy = match.copy()
        if isinstance(match_copy.get('date'), str):
            try:
                dt_object = datetime.fromisoformat(match_copy['date'])
                match_copy['formatted_date'] = dt_object.strftime('%m/%d/%Y %I:%M %p')
            except Exception as e:
                logger.error(f"Error formatting date for match {match.get('match_id')}: {e}")
        formatted_matches.append(match_copy)
    return formatted_matches


def insert_mls_match(
    session: Session,
    match_id: str,
    opponent: str,
    date_time: datetime,
    is_home_game: bool,
    summary_link: str,
    stats_link: str,
    commentary_link: str,
    venue: str,
    competition: str,
    espn_match_id: str = None
) -> MLSMatch:
    """
    Insert a new MLS match into the database.

    Args:
        session (Session): The SQLAlchemy session.
        match_id (str): Unique match identifier.
        opponent (str): Opponent team name.
        date_time (datetime): Match datetime.
        is_home_game (bool): True if home game.
        summary_link (str): Link to match summary.
        stats_link (str): Link to match statistics.
        commentary_link (str): Link to match commentary.
        venue (str): Match venue.
        competition (str): Competition identifier.
        espn_match_id (str, optional): ESPN match ID for live reporting.

    Returns:
        MLSMatch: The newly created MLSMatch object.
    """
    new_match = MLSMatch(
        match_id=match_id,
        opponent=opponent,
        date_time=date_time,
        is_home_game=is_home_game,
        summary_link=summary_link,
        stats_link=stats_link,
        commentary_link=commentary_link,
        venue=venue,
        competition=competition,
        espn_match_id=espn_match_id,
        live_reporting_status='not_started',
        live_reporting_scheduled=False,
        live_reporting_started=False,
        thread_created=False
    )
    session.add(new_match)
    return new_match


def update_mls_match(session: Session, match_id: str, **kwargs) -> bool:
    """
    Update an existing MLS match with new data.

    Args:
        session (Session): The SQLAlchemy session.
        match_id (str): Unique match identifier.
        **kwargs: Key-value pairs to update on the match record.

    Returns:
        bool: True if the match was updated; False if not found.
    """
    match = get_match(session, match_id)
    if not match:
        logger.warning(f"MLS match {match_id} not found for update.")
        return False

    for key, value in kwargs.items():
        setattr(match, key, value)
    return True


def delete_mls_match(session: Session, match_id: str) -> bool:
    """
    Delete an MLS match from the database.

    Args:
        session (Session): The SQLAlchemy session.
        match_id (str): Unique match identifier.

    Returns:
        bool: True if deletion was successful; False if match not found.
    """
    match = get_match(session, match_id)
    if not match:
        logger.warning(f"MLS match {match_id} not found for deletion.")
        return False
    session.delete(match)
    return True


def get_upcoming_mls_matches(session: Session, hours_ahead: int = 24) -> List[MLSMatch]:
    """
    Retrieve upcoming MLS matches within a given timeframe.

    Args:
        session (Session): The SQLAlchemy session.
        hours_ahead (int): How many hours ahead to look (default: 24).

    Returns:
        List[MLSMatch]: List of upcoming MLSMatch objects.
    """
    now = datetime.utcnow()
    end_time = now + timedelta(hours=hours_ahead)
    return session.query(MLSMatch).filter(
        MLSMatch.date_time > now,
        MLSMatch.date_time <= end_time,
        MLSMatch.thread_created == False
    ).all()


def mark_mls_match_thread_created(session: Session, match_id: str, thread_id: str) -> bool:
    """
    Mark an MLS match as having its Discord thread created.

    Args:
        session (Session): The SQLAlchemy session.
        match_id (str): Unique match identifier.
        thread_id (str): The Discord thread ID.

    Returns:
        bool: True if the match was updated; False if match not found.
    """
    match = get_match(session, match_id)
    if not match:
        logger.warning(f"MLS match {match_id} not found for marking thread creation.")
        return False
    match.thread_created = True
    match.discord_thread_id = thread_id
    return True


def load_match_dates_from_db(session: Session) -> List[Dict[str, Any]]:
    """
    Load match dates from the database for display purposes.

    Args:
        session (Session): The SQLAlchemy session.

    Returns:
        List[Dict[str, Any]]: A list of dictionaries containing match details.
    """
    matches = session.query(MLSMatch).all()
    return [
        {
            'match_id': match.match_id,
            'opponent': match.opponent,
            'date': match.date_time.isoformat(),
            'venue': match.venue,
            'is_home_game': match.is_home_game,
            'summary_link': match.summary_link,
            'stats_link': match.stats_link,
            'commentary_link': match.commentary_link,
            'competition': match.competition
        }
        for match in matches
    ]


def safe_commit(session: Session) -> bool:
    """
    Safely commit changes to the database, rolling back on error.

    Args:
        session (Session): The SQLAlchemy session.

    Returns:
        bool: True if commit was successful; False otherwise.
    """
    try:
        session.commit()
        return True
    except SQLAlchemyError as e:
        session.rollback()
        logger.error(f"Error committing: {e}")
        return False


def bulk_update_matches(session: Session, updates: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Perform a bulk update of matches.

    Args:
        session (Session): The SQLAlchemy session.
        updates (List[Dict[str, Any]]): List of dictionaries containing updates.
            Each dictionary must include 'match_id' and key-value pairs to update.

    Returns:
        dict: Summary of the bulk update, including counts of updated and failed match IDs.
    """
    try:
        success_count = 0
        failed_ids = []
        for update in updates:
            match_id = update.pop('match_id', None)
            if not match_id:
                continue
            match = get_match(session, match_id)
            if match:
                for key, value in update.items():
                    setattr(match, key, value)
                success_count += 1
            else:
                failed_ids.append(match_id)
        return {
            'success': True,
            'updated_count': success_count,
            'failed_ids': failed_ids
        }
    except Exception as e:
        logger.error(f"Error in bulk update: {e}")
        return {
            'success': False,
            'error': str(e)
        }


def get_match_by_id(session: Session, match_id: str) -> Optional[MLSMatch]:
    """
    Retrieve a single MLS match by its match_id.

    Args:
        session (Session): The SQLAlchemy session.
        match_id (str): The unique match identifier.

    Returns:
        Optional[MLSMatch]: The matching MLSMatch object, or None if not found.
    """
    return session.query(MLSMatch).filter_by(match_id=match_id).first()


def update_player_discord_info(
    session: Session, player_id: int, current_roles: List[str], verified_time: datetime
) -> bool:
    """
    Update a player's Discord role information.

    Args:
        session (Session): The SQLAlchemy session.
        player_id (int): The player's ID.
        current_roles (List[str]): List of current Discord roles.
        verified_time (datetime): The timestamp when roles were verified.

    Returns:
        bool: True if updated successfully; False otherwise.
    """
    try:
        player = session.query(Player).get(player_id)
        if player:
            player.discord_roles = current_roles
            player.discord_last_verified = verified_time
            player.discord_needs_update = False
            return True
        return False
    except Exception as e:
        logger.error(f"Error updating Discord info for player {player_id}: {str(e)}")
        return False


def mark_player_for_discord_update(session: Session, player_id: int) -> bool:
    """
    Mark a player for Discord role update.

    Args:
        session (Session): The SQLAlchemy session.
        player_id (int): The player's ID.

    Returns:
        bool: True if marked successfully; False otherwise.
    """
    try:
        player = session.query(Player).get(player_id)
        if player:
            player.discord_needs_update = True
            return True
        return False
    except Exception as e:
        logger.error(f"Error marking player {player_id} for Discord update: {str(e)}")
        return False


def update_discord_channel_id(session: Session, team_id: int, channel_id: str) -> bool:
    """
    Update a team's Discord channel ID.

    Args:
        session (Session): The SQLAlchemy session.
        team_id (int): The team's ID.
        channel_id (str): The new Discord channel ID.

    Returns:
        bool: True if updated; False otherwise.
    """
    try:
        team = session.query(Team).get(team_id)
        if team:
            team.discord_channel_id = channel_id
            return True
        return False
    except Exception as e:
        logger.error(f"Error updating Discord channel ID for team {team_id}: {str(e)}")
        return False


def update_discord_role_ids(
    session: Session, team_id: int, coach_role_id: str = None, player_role_id: str = None
) -> bool:
    """
    Update a team's Discord role IDs.

    Args:
        session (Session): The SQLAlchemy session.
        team_id (int): The team's ID.
        coach_role_id (str, optional): The coach role ID.
        player_role_id (str, optional): The player role ID.

    Returns:
        bool: True if updated; False otherwise.
    """
    try:
        team = session.query(Team).get(team_id)
        if team:
            if coach_role_id is not None:
                team.discord_coach_role_id = coach_role_id
            if player_role_id is not None:
                team.discord_player_role_id = player_role_id
            return True
        return False
    except Exception as e:
        logger.error(f"Error updating Discord role IDs for team {team_id}: {str(e)}")
        return False


def get_players_needing_discord_update(session: Session) -> List[Player]:
    """
    Retrieve all players that require a Discord role update.

    A player needs an update if:
      - They have a Discord ID, AND
      - Their roles need updating OR they have never been verified OR their last verification is older than 90 days.

    Args:
        session (Session): The SQLAlchemy session.

    Returns:
        List[Player]: List of players needing a Discord update.
    """
    threshold_date = datetime.utcnow() - timedelta(days=90)
    return (session.query(Player)
            .filter(
                (Player.discord_id.isnot(None)) &
                (
                    (Player.discord_needs_update == True) |
                    (Player.discord_last_verified.is_(None)) |
                    (Player.discord_last_verified < threshold_date)
                )
            )
            .options(
                joinedload(Player.teams),  # multi-team support
                joinedload(Player.teams).joinedload(Team.league)
            )
            .all())