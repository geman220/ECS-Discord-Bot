from datetime import datetime, timedelta
import logging
from typing import Dict, Any, Tuple

from app.extensions import db
from app.decorators import celery_task, async_task
from app.models import MLSMatch, ScheduledMessage
from app.utils.discord_helpers import send_discord_update
from app.api_utils import fetch_espn_data

logger = logging.getLogger(__name__)

@async_task(name='app.tasks.tasks_match_updates.process_match_updates')
async def process_match_updates(self, match_id: str, match_data: Dict[str, Any]):
    """Process match updates and send to Discord."""
    try:
        match = MLSMatch.query.get(match_id)
        if not match:
            logger.error(f"Match {match_id} not found")
            return f"No match found with ID {match_id}"

        # Extract match data
        competition = match_data['competitions'][0]
        home_comp = competition['competitors'][0]
        away_comp = competition['competitors'][1]

        home_team = home_comp['team']['displayName']
        away_team = away_comp['team']['displayName']
        home_score = home_comp['score']
        away_score = away_comp['score']
        match_status = match_data['status']['type']['name']
        current_minute = match_data['status']['displayClock']

        # Create update message
        update_type, update_data = create_match_update(
            match_status,
            home_team,
            away_team,
            home_score,
            away_score,
            current_minute
        )

        # Send update to Discord
        await send_discord_update(
            match.discord_thread_id,
            update_type,
            update_data
        )
        
        logger.info(f"Match update sent successfully for match {match_id}")
        return "Match update sent successfully"

    except Exception as e:
        logger.error(f"Error processing match updates: {str(e)}", exc_info=True)
        raise

@celery_task(name='app.tasks.tasks_match_updates.fetch_match_and_team_id_task')
def fetch_match_and_team_id_task(self, message_id: str, channel_id: str) -> Dict[str, Any]:
    """Fetch match and team ID from message details."""
    try:
        scheduled_message = ScheduledMessage.query.filter(
            ((ScheduledMessage.home_channel_id == channel_id) &
             (ScheduledMessage.home_message_id == message_id)) |
            ((ScheduledMessage.away_channel_id == channel_id) &
             (ScheduledMessage.away_message_id == message_id))
        ).first()

        if not scheduled_message:
            logger.error(f"No scheduled message found for message_id: {message_id}")
            return {'error': 'Message ID not found'}

        # Determine team ID based on channel
        if scheduled_message.home_channel_id == channel_id and scheduled_message.home_message_id == message_id:
            team_id = scheduled_message.match.home_team_id
        elif scheduled_message.away_channel_id == channel_id and scheduled_message.away_message_id == message_id:
            team_id = scheduled_message.match.away_team_id
        else:
            logger.error(f"Team ID not found for message: {message_id}")
            return {'error': 'Team ID not found'}

        logger.info(f"Found match_id: {scheduled_message.match_id}, team_id: {team_id}")
        return {
            'match_id': scheduled_message.match_id,
            'team_id': team_id
        }

    except Exception as e:
        logger.error(f"Error fetching match and team ID: {str(e)}", exc_info=True)
        raise

def create_match_update(
    status: str,
    home_team: str,
    away_team: str,
    home_score: str,
    away_score: str,
    current_minute: str
) -> Tuple[str, str]:
    """
    Create appropriate update message based on match status.
    
    Args:
        status: Current match status
        home_team: Name of home team
        away_team: Name of away team
        home_score: Home team's score
        away_score: Away team's score
        current_minute: Current minute of the match
        
    Returns:
        Tuple containing update type and formatted message
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