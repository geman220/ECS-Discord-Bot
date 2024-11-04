from datetime import datetime, timedelta
import logging
from typing import Dict, Any, Tuple, Optional, List
from app.extensions import db
from app.decorators import celery_task, async_task, db_operation, query_operation, session_context
from app.models import MLSMatch, ScheduledMessage
from app.utils.discord_helpers import send_discord_update
from app.api_utils import fetch_espn_data

logger = logging.getLogger(__name__)

@async_task(name='app.tasks.tasks_match_updates.process_match_updates')
async def process_match_updates(self, match_id: str, match_data: Dict[str, Any]) -> str:
    """Process match updates and send to Discord."""
    try:
        @query_operation
        def get_match() -> Optional[MLSMatch]:
            return MLSMatch.query.get(match_id)

        match = get_match()
        if not match:
            logger.error(f"Match {match_id} not found")
            return f"No match found with ID {match_id}"

        # Extract match data
        competition = match_data['competitions'][0]
        home_comp = competition['competitors'][0]
        away_comp = competition['competitors'][1]

        update_info = {
            'home_team': home_comp['team']['displayName'],
            'away_team': away_comp['team']['displayName'],
            'home_score': home_comp['score'],
            'away_score': away_comp['score'],
            'match_status': match_data['status']['type']['name'],
            'current_minute': match_data['status']['displayClock']
        }

        # Create update message
        update_type, update_data = create_match_update(
            status=update_info['match_status'],
            home_team=update_info['home_team'],
            away_team=update_info['away_team'],
            home_score=update_info['home_score'],
            away_score=update_info['away_score'],
            current_minute=update_info['current_minute']
        )

        # Send update to Discord
        await send_discord_update(
            match.discord_thread_id,
            update_type,
            update_data
        )

        @db_operation
        def update_match_status():
            match = MLSMatch.query.get(match_id)
            if match:
                match.last_update_time = datetime.utcnow()
                match.last_update_type = update_type
                match.current_status = update_info['match_status']
                match.current_score = f"{update_info['home_score']}-{update_info['away_score']}"
            return match

        updated_match = update_match_status()
        
        logger.info(f"Match update sent successfully for match {match_id}")
        return "Match update sent successfully"

    except Exception as e:
        logger.error(f"Error processing match updates: {str(e)}", exc_info=True)
        raise

@celery_task(name='app.tasks.tasks_match_updates.fetch_match_and_team_id_task')
def fetch_match_and_team_id_task(self, message_id: str, channel_id: str) -> Dict[str, Any]:
    """Fetch match and team ID from message details."""
    try:
        @query_operation
        def get_scheduled_message() -> Optional[ScheduledMessage]:
            return ScheduledMessage.query.filter(
                ((ScheduledMessage.home_channel_id == channel_id) &
                 (ScheduledMessage.home_message_id == message_id)) |
                ((ScheduledMessage.away_channel_id == channel_id) &
                 (ScheduledMessage.away_message_id == message_id))
            ).first()

        scheduled_message = get_scheduled_message()
        if not scheduled_message:
            logger.error(f"No scheduled message found for message_id: {message_id}")
            return {'error': 'Message ID not found'}

        # Determine team ID based on channel
        team_id = get_team_id_from_message(scheduled_message, channel_id, message_id)
        if not team_id:
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

def get_team_id_from_message(message: ScheduledMessage, channel_id: str, message_id: str) -> Optional[int]:
    """Helper function to determine team ID from message details."""
    if message.home_channel_id == channel_id and message.home_message_id == message_id:
        return message.match.home_team_id
    elif message.away_channel_id == channel_id and message.away_message_id == message_id:
        return message.match.away_team_id
    return None

def create_match_update(
    status: str,
    home_team: str,
    away_team: str,
    home_score: str,
    away_score: str,
    current_minute: str
) -> Tuple[str, str]:
    """Create appropriate update message based on match status."""
    update_types = {
        'STATUS_SCHEDULED': (
            "pre_match_info",
            f"🚨 Match Alert: {home_team} vs {away_team} is about to start!"
        ),
        'STATUS_IN_PROGRESS': (
            "score_update",
            f"⚽ {home_team} {home_score} - {away_score} {away_team} ({current_minute})"
        ),
        'STATUS_HALFTIME': (
            "score_update",
            f"⚽ {home_team} {home_score} - {away_score} {away_team} ({current_minute})"
        ),
        'STATUS_FINAL': (
            "match_end",
            f"🏁 Full Time: {home_team} {home_score} - {away_score} {away_team}"
        )
    }
    
    return update_types.get(status, ("status_update", f"Match Status: {status}"))

# Additional utility functions for match status management
@db_operation
def update_match_details(match_id: str, update_info: Dict[str, Any]) -> Optional[MLSMatch]:
    """Update match details with proper session management."""
    match = MLSMatch.query.get(match_id)
    if match:
        match.current_status = update_info.get('match_status')
        match.current_score = f"{update_info.get('home_score')}-{update_info.get('away_score')}"
        match.last_update_time = datetime.utcnow()
        match.current_minute = update_info.get('current_minute')
    return match

@query_operation
def get_active_matches() -> List[MLSMatch]:
    """Get all active matches that need updates."""
    return MLSMatch.query.filter(
        MLSMatch.current_status.in_(['STATUS_IN_PROGRESS', 'STATUS_HALFTIME'])
    ).all()

@celery_task(name='app.tasks.tasks_match_updates.cleanup_old_updates')
def cleanup_old_updates(self, days_old: int = 7) -> Dict[str, Any]:
    """Clean up old match updates."""
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days_old)
        
        @db_operation
        def cleanup_matches() -> int:
            return MLSMatch.query.filter(
                MLSMatch.current_status == 'STATUS_FINAL',
                MLSMatch.last_update_time < cutoff_date
            ).update({
                'current_status': None,
                'current_score': None,
                'current_minute': None
            }, synchronize_session=False)

        cleaned_count = cleanup_matches()
        
        return {
            'success': True,
            'message': f'Cleaned up {cleaned_count} old match updates',
            'cleaned_count': cleaned_count
        }
    except Exception as e:
        logger.error(f"Error cleaning up old updates: {str(e)}", exc_info=True)
        return {
            'success': False,
            'message': str(e)
        }