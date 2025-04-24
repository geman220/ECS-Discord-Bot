﻿# app/tasks/tasks_match_updates.py

"""
Match Updates Tasks Module

This module defines Celery tasks related to match updates for live reporting,
including processing match updates and fetching match and team IDs based on
Discord message details. The tasks leverage async operations to send updates
to Discord and update match records in the database.
"""

import logging
import asyncio
from datetime import datetime
from typing import Dict, Any, Tuple
from sqlalchemy.exc import SQLAlchemyError

from app.decorators import celery_task
from app.models import MLSMatch, ScheduledMessage
from app.utils.discord_helpers import send_discord_update
from app.utils.db_connection_monitor import ensure_connections_cleanup

logger = logging.getLogger(__name__)


@celery_task(
    name='app.tasks.tasks_match_updates.process_match_updates',
    bind=True,
    queue='discord',
    max_retries=3
)
def process_match_updates(self, session, match_id: str, match_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process match updates and send them to Discord.

    This task validates the provided match data, retrieves the match record from the
    database, constructs an update message based on the current match status and score,
    and sends the update to Discord via an asynchronous helper.

    Args:
        session: The database session.
        match_id: The ID of the match to update.
        match_data: Dictionary containing live match data (must include 'competitions').

    Returns:
        A dictionary containing success status, message, update type, and match status.

    Raises:
        Retries the task after 60 seconds on SQLAlchemyError and after 30 seconds on general errors.
    """
    try:
        # Validate incoming match data format.
        if not match_data or 'competitions' not in match_data:
            return {'success': False, 'message': 'Invalid match data format'}

        match = get_match(session, match_id)
        if not match:
            logger.error(f"Match {match_id} not found")
            return {'success': False, 'message': f'No match found with ID {match_id}'}

        # Extract information from the ESPN data.
        competition = match_data['competitions'][0]
        home_comp = competition['competitors'][0]
        away_comp = competition['competitors'][1]

        home_team = home_comp['team']['displayName']
        away_team = away_comp['team']['displayName']
        home_score = home_comp['score']
        away_score = away_comp['score']
        match_status = competition['status']['type']['name']
        current_minute = competition['status'].get('displayClock', 'N/A')

        # Build update message based on match status.
        update_type, update_message = create_match_update(
            match_status,
            home_team,
            away_team,
            home_score,
            away_score,
            current_minute
        )

        # Update match record.
        match.current_status = match_status
        match.current_score = f"{home_score}-{away_score}"
        match.current_minute = current_minute
        match.last_update_time = datetime.utcnow()

        # Create a new event loop for async operations.
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(send_discord_update(
                match.discord_thread_id,
                update_type,
                update_message
            ))
        finally:
            loop.close()
            # Ensure connections are properly cleaned up after asyncio operations
            ensure_connections_cleanup()

        logger.info(f"Match update sent successfully for match {match_id}")
        return {
            'success': True,
            'message': 'Match update sent successfully',
            'update_type': update_type,
            'match_status': match_status
        }

    except SQLAlchemyError as e:
        logger.error(f"Database error processing match updates: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error processing match updates: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)


@celery_task(
    name='app.tasks.tasks_match_updates.fetch_match_and_team_id_task',
    bind=True,
    queue='discord',
    max_retries=3
)
def fetch_match_and_team_id_task(self, session, message_id: str, channel_id: str) -> Dict[str, Any]:
    """
    Fetch match and team ID based on Discord message details.

    This task locates a ScheduledMessage record by matching the provided channel and message IDs.
    Depending on which channel (home or away) the message came from, it returns the corresponding team ID.

    Args:
        session: The database session.
        message_id: The ID of the Discord message.
        channel_id: The ID of the Discord channel.

    Returns:
        A dictionary with success status, match_id, and team_id if found.
    
    Raises:
        Retries the task on SQLAlchemy or general errors.
    """
    try:
        scheduled_message = session.query(ScheduledMessage).filter(
            ((ScheduledMessage.home_channel_id == channel_id) & (ScheduledMessage.home_message_id == message_id)) |
            ((ScheduledMessage.away_channel_id == channel_id) & (ScheduledMessage.away_message_id == message_id))
        ).first()

        if not scheduled_message:
            logger.error(f"No scheduled message found for message_id: {message_id}")
            return {'success': False, 'message': 'Message ID not found'}

        # Determine the team ID based on the channel the message was sent in.
        if scheduled_message.home_channel_id == channel_id and scheduled_message.home_message_id == message_id:
            team_id = scheduled_message.match.home_team_id
        elif scheduled_message.away_channel_id == channel_id and scheduled_message.away_message_id == message_id:
            team_id = scheduled_message.match.away_team_id
        else:
            logger.error(f"Team ID not found for message: {message_id}")
            return {'success': False, 'message': 'Team ID not found'}

        # Update the last fetch timestamp.
        scheduled_message.last_fetch = datetime.utcnow()

        logger.info(f"Found match_id: {scheduled_message.match_id}, team_id: {team_id}")
        return {
            'success': True,
            'match_id': scheduled_message.match_id,
            'team_id': team_id
        }

    except SQLAlchemyError as e:
        logger.error(f"Database error fetching match and team ID: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error fetching match and team ID: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)


def create_match_update(
    status: str,
    home_team: str,
    away_team: str,
    home_score: str,
    away_score: str,
    current_minute: str
) -> Tuple[str, str]:
    """
    Create an update message based on the match status.

    Args:
        status: The current match status.
        home_team: Home team name.
        away_team: Away team name.
        home_score: Home team score.
        away_score: Away team score.
        current_minute: Current minute or clock display.

    Returns:
        A tuple (update_type, update_message) appropriate for the match status.
    """
    if status == 'STATUS_SCHEDULED':
        return (
            "pre_match_info",
            f"🚨 Match Alert: {home_team} vs {away_team} is about to start!"
        )
    elif status in ['STATUS_IN_PROGRESS', 'STATUS_HALFTIME']:
        return (
            "score_update",
            f"⚽ {home_team} {home_score} - {away_score} {away_team} ({current_minute})"
        )
    elif status == 'STATUS_FINAL':
        return (
            "match_end",
            f"🏁 Full Time: {home_team} {home_score} - {away_score} {away_team}"
        )
    else:
        return (
            "status_update",
            f"Match Status: {status}"
        )


@celery_task(
    name='app.tasks.tasks_match_updates.get_active_matches',
    bind=True,
    queue='discord',
    max_retries=3
)
def get_active_matches_task(self, session) -> Dict[str, Any]:
    """
    Retrieve all active matches that require updates.

    This task queries for matches with a current status of 'STATUS_IN_PROGRESS' or 'STATUS_HALFTIME'
    and returns summary data for each match.

    Args:
        session: The database session.

    Returns:
        A dictionary containing a success flag, a message, and a list of active match summaries.

    Raises:
        Retries the task on SQLAlchemy or general errors.
    """
    try:
        matches = session.query(MLSMatch).filter(
            MLSMatch.current_status.in_(['STATUS_IN_PROGRESS', 'STATUS_HALFTIME'])
        ).all()

        matches_data = [{
            'id': match.id,
            'match_id': match.match_id,
            'status': match.current_status,
            'score': match.current_score,
            'current_minute': match.current_minute,
            'last_update': match.last_update_time.isoformat() if match.last_update_time else None
        } for match in matches]

        return {
            'success': True,
            'message': f'Found {len(matches_data)} active matches',
            'matches': matches_data
        }

    except SQLAlchemyError as e:
        logger.error(f"Database error getting active matches: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error getting active matches: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)


# Helper function for retrieving match
def get_match(session, match_id: str) -> MLSMatch:
    """
    Retrieve a match by its ID.
    
    Args:
        session: The database session.
        match_id: The ID of the match to retrieve.
        
    Returns:
        The MLSMatch object if found, None otherwise.
    """
    return session.query(MLSMatch).filter(MLSMatch.match_id == match_id).first()