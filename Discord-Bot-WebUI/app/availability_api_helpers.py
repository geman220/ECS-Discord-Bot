# app/availability_api_helpers.py

"""
Availability API Helpers Module

This module contains utility functions for validating date/time inputs,
retrieving and processing availability data, storing message IDs, updating
RSVP data (both locally and via Discord), and fetching match request data.
"""

# Standard library imports
import re
import logging
from datetime import datetime
from typing import Optional

# Third-party imports
import aiohttp

# Local application imports
from flask import g
from app.models import Match, Availability, Player, ScheduledMessage
from app.tasks.tasks_rsvp import update_discord_rsvp_task

logger = logging.getLogger(__name__)


def validate_date(date_text):
    """
    Validate a date string in YYYY-MM-DD format.

    Args:
        date_text (str): The date string.

    Returns:
        bool: True if valid, False otherwise.
    """
    try:
        datetime.strptime(date_text, '%Y-%m-%d')
        return True
    except ValueError:
        return False


def validate_time(time_text):
    """
    Validate a time string in HH:MM or HH:MM:SS format.

    Args:
        time_text (str): The time string.

    Returns:
        bool: True if the time string matches the expected format, False otherwise.
    """
    return re.match(r"^\d{2}:\d{2}(:\d{2})?$", time_text) is not None


def get_availability_results(match_id, session=None):
    """
    Retrieve availability results for a given match.

    Args:
        match_id: The ID of the match.
        session: Optional database session; defaults to g.db_session.

    Returns:
        dict: Counts for 'yes', 'no', 'maybe' responses and a list of individual responses.
    """
    if session is None:
        session = g.db_session

    availability_list = session.query(Availability).filter_by(match_id=match_id).all()
    return {
        "yes": sum(1 for a in availability_list if a.response == 'yes'),
        "no": sum(1 for a in availability_list if a.response == 'no'),
        "maybe": sum(1 for a in availability_list if a.response == 'maybe'),
        "responses": [{
            "player_id": a.player_id,
            "response": a.response
        } for a in availability_list]
    }


def store_message_ids_for_match(match_id, home_channel_id, home_message_id, 
                                away_channel_id, away_message_id, session=None):
    """
    Store message IDs for scheduled messages associated with a match.

    Args:
        match_id (int): The match ID.
        home_channel_id: Home channel identifier.
        home_message_id: Home message identifier.
        away_channel_id: Away channel identifier.
        away_message_id: Away message identifier.
        session: Optional database session; defaults to g.db_session.

    Returns:
        tuple: (ScheduledMessage object or None, status message)
    """
    if session is None:
        session = g.db_session

    try:
        match = session.query(Match).get(match_id)
        if not match:
            logger.error(f"Match {match_id} not found")
            return None, "Match not found"

        scheduled_message = session.query(ScheduledMessage).filter_by(match_id=match_id).first()
        if not scheduled_message:
            scheduled_message = ScheduledMessage(match_id=match_id)
            session.add(scheduled_message)

        scheduled_message.home_channel_id = home_channel_id
        scheduled_message.home_message_id = home_message_id
        scheduled_message.away_channel_id = away_channel_id
        scheduled_message.away_message_id = away_message_id

        return scheduled_message, "Message IDs stored successfully"

    except Exception as e:
        logger.error(f"Error storing message IDs for match {match_id}: {str(e)}")
        return None, str(e)


def verify_availability_data(match_id: int, team_id: Optional[int] = None, session=None) -> None:
    """
    Log detailed availability data for a match, optionally filtering by team.

    Args:
        match_id (int): The match ID.
        team_id (Optional[int]): Team ID to filter availability data.
        session: Optional database session; defaults to g.db_session.
    """
    if session is None:
        session = g.db_session

    try:
        match = session.query(Match).get(match_id)
        if not match:
            logger.error(f"Match {match_id} not found!")
            return

        logger.debug(f"Found match: {match_id}")
        all_availabilities = session.query(Availability).filter(Availability.match_id == match_id).all()
        logger.debug(f"All availabilities for match {match_id}:")
        for avail in all_availabilities:
            player = session.query(Player).get(avail.player_id)
            if player:
                logger.debug(f"  Player {player.name} (ID: {player.id}, Team: {player.team_id}): {avail.response}")

        if team_id:
            team_players = session.query(Player).filter_by(team_id=team_id).all()
            logger.debug(f"Players on team {team_id}:")
            for player in team_players:
                logger.debug(f"  {player.name} (ID: {player.id})")

            team_availabilities = (session.query(Availability)
                                   .join(Player)
                                   .filter(Availability.match_id == match_id,
                                           Player.team_id == team_id)
                                   .all())
            logger.debug(f"Availabilities for team {team_id}:")
            for avail in team_availabilities:
                player = session.query(Player).get(avail.player_id)
                if player:
                    logger.debug(f"  Player {player.name}: {avail.response}")

    except Exception as e:
        logger.error(f"Error verifying data: {str(e)}", exc_info=True)


def get_match_rsvp_data(match_id, team_id=None, session=None):
    """
    Retrieve RSVP data for a match, optionally filtered by team.

    Args:
        match_id (int): The match ID.
        team_id (Optional[int]): Team ID to filter results.
        session: Optional database session; defaults to g.db_session.

    Returns:
        dict: RSVP data categorized by response ('yes', 'no', 'maybe').
    """
    if session is None:
        session = g.db_session

    try:
        base_count = session.query(Availability).filter(Availability.match_id == match_id).count()
        logger.debug(f"Total availability records for match {match_id}: {base_count}")

        query = session.query(Availability, Player).join(Player).filter(Availability.match_id == match_id)
        all_avail = query.with_entities(
            Availability.response, 
            Player.name,
            Player.id,
            Player.team_id
        ).all()
        logger.debug(f"All availabilities before team filter: {all_avail}")

        if team_id:
            query = query.filter(Player.team_id == team_id)
            filtered_avail = query.with_entities(
                Availability.response, 
                Player.name,
                Player.id,
                Player.team_id
            ).all()
            logger.debug(f"Filtered availabilities for team {team_id}: {filtered_avail}")

        availability_records = query.with_entities(
            Availability.response, 
            Player.name,
            Player.id
        ).all()
        logger.debug(f"Final availability records: {availability_records}")

        rsvp_data = {'yes': [], 'no': [], 'maybe': []}
        for response, player_name, player_id in availability_records:
            logger.debug(f"Processing record: response={response}, player={player_name}, id={player_id}")
            if response in rsvp_data:
                rsvp_data[response].append({
                    'player_name': player_name,
                    'player_id': player_id
                })
                logger.debug(f"Added player {player_name} to {response} list")
        
        logger.debug(f"Final RSVP data for match {match_id}, team {team_id}: {rsvp_data}")
        return rsvp_data

    except Exception as e:
        logger.error(f"Error getting RSVP data for match {match_id}, team {team_id}: {str(e)}", exc_info=True)
        return {'yes': [], 'no': [], 'maybe': []}


async def update_discord_rsvp(match, player, new_response, old_response, session=None):
    """
    Asynchronously trigger a Discord RSVP update task.

    Args:
        match: The match instance.
        player: The player instance.
        new_response: The new RSVP response.
        old_response: The previous RSVP response.
        session: Optional database session; defaults to g.db_session.

    Returns:
        dict: Status message indicating if the task was queued.
    """
    if session is None:
        session = g.db_session

    scheduled_message = session.query(ScheduledMessage).filter_by(match_id=match.id).first()
    if not scheduled_message:
        logger.debug(f"No scheduled message found for match {match.id}")
        return {"status": "success", "message": "RSVP recorded; no Discord messages yet"}

    message_ids = []
    if scheduled_message.home_message_id and scheduled_message.home_channel_id:
        message_ids.append(f"{scheduled_message.home_channel_id}-{scheduled_message.home_message_id}")
    if scheduled_message.away_message_id and scheduled_message.away_channel_id:
        message_ids.append(f"{scheduled_message.away_channel_id}-{scheduled_message.away_message_id}")

    if not message_ids:
        logger.debug(f"No Discord messages to update for match {match.id}")
        return {"status": "success", "message": "RSVP recorded; no message IDs"}

    data = {
        "match_id": match.id,
        "discord_id": player.discord_id,
        "new_response": new_response,
        "old_response": old_response,
        "message_ids": message_ids
    }

    update_discord_rsvp_task.delay(data)
    return {"status": "success", "message": "RSVP update task queued"}


def process_availability_update(match_id, discord_id, response, responded_at=None, session=None):
    """
    Process an availability update for a player.

    Args:
        match_id (int): The match ID.
        discord_id (str): The player's Discord ID.
        response (str): The new availability response.
        responded_at (datetime, optional): The time of response.
        session: Optional database session; defaults to g.db_session.

    Returns:
        tuple: (player_id or None, dict with status and message)
    """
    if session is None:
        session = g.db_session

    try:
        result = {'status': 'success', 'message': None}
        player = session.query(Player).filter_by(discord_id=str(discord_id)).first()
        if not player:
            return None, {'status': 'error', 'message': 'Player not found'}

        availability = session.query(Availability).filter_by(match_id=match_id, player_id=player.id).first()

        if response == 'no_response':
            if availability:
                session.delete(availability)
                result['message'] = 'Availability removed'
            else:
                result['message'] = 'No availability to remove'
            return player.id, result

        if not availability:
            availability = Availability(
                match_id=match_id,
                player_id=player.id,
                discord_id=discord_id,
                response=response,
                responded_at=responded_at or datetime.utcnow()
            )
            session.add(availability)
            result['message'] = 'Availability created'
        else:
            availability.response = response
            availability.responded_at = responded_at or datetime.utcnow()
            result['message'] = 'Availability updated'

        return player.id, result

    except Exception as e:
        logger.error(f"Error in process_availability_update: {str(e)}", exc_info=True)
        return None, {'status': 'error', 'message': str(e)}


def get_message_data(match_id, session=None):
    """
    Retrieve message data for a match.

    Args:
        match_id (int): The match ID.
        session: Optional database session; defaults to g.db_session.

    Returns:
        dict or None: Message data if available; otherwise None.
    """
    if session is None:
        session = g.db_session

    try:
        scheduled_message = (session.query(ScheduledMessage)
                             .join(Match)
                             .filter(ScheduledMessage.match_id == match_id)
                             .first())
        if not scheduled_message:
            logger.debug(f"No scheduled message found for match_id {match_id}")
            return None

        logger.debug(f"Found scheduled_message for match_id {match_id}: {scheduled_message}")

        if not (scheduled_message.match and scheduled_message.match.home_team_id and scheduled_message.match.away_team_id):
            logger.error(f"Incomplete match data for match_id {match_id}")
            return None

        data = {
            'home_message_id': scheduled_message.home_message_id,
            'home_channel_id': scheduled_message.home_channel_id,
            'home_team_id': scheduled_message.match.home_team_id,
            'away_message_id': scheduled_message.away_message_id,
            'away_channel_id': scheduled_message.away_channel_id,
            'away_team_id': scheduled_message.match.away_team_id
        }
        logger.debug(f"Message data for match_id {match_id}: {data}")

        if not all(data.values()):
            logger.error(f"Missing required message data for match_id {match_id}: {data}")
            return None

        return data

    except Exception as e:
        logger.exception(f"Error getting message data for match_id {match_id}")
        return None


def get_match_request_data(match_id, session=None):
    """
    Retrieve match request data for a given match.

    Args:
        match_id (int): The match ID.
        session: Optional database session; defaults to g.db_session.

    Returns:
        dict or None: Dictionary containing match request details, or None if not found.
    """
    if session is None:
        session = g.db_session

    try:
        match = session.query(Match).get(match_id)
        if not match:
            logger.error(f"Match {match_id} not found")
            return None

        if not (match.home_team and match.away_team):
            logger.error(f"Missing team data for match {match_id}")
            return None

        return {
            'match_id': match.id,
            'home_team_name': match.home_team.name,
            'away_team_name': match.away_team.name,
            'match_date': match.date.strftime('%Y-%m-%d') if match.date else None,
            'match_time': match.time.strftime('%H:%M:%S') if match.time else None,
            'home_team_id': match.home_team_id,
            'away_team_id': match.away_team_id
        }

    except Exception as e:
        logger.error(f"Error getting match request data for match {match_id}: {str(e)}")
        return None