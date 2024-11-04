# app/tasks/tasks_core.py

import logging
import asyncio
import aiohttp
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from app.extensions import db
from app.decorators import celery_task, async_task, db_operation, query_operation, session_context
from app.models import Match, ScheduledMessage

logger = logging.getLogger(__name__)

@celery_task(
    name='app.tasks.tasks_core.schedule_season_availability',
    retry_backoff=True
)
def schedule_season_availability(self) -> Dict[str, Any]:
    """Schedule availability messages for matches in the next week."""
    try:
        start_date = datetime.utcnow().date()
        end_date = start_date + timedelta(days=7)

        @query_operation
        def get_upcoming_matches() -> List[Match]:
            return Match.query.filter(
                Match.date.between(start_date, end_date)
            ).all()

        matches = get_upcoming_matches()
        scheduled_count = 0

        @db_operation
        def create_scheduled_messages(matches: List[Match]) -> int:
            count = 0
            for match in matches:
                # Calculate message send time (Tuesday 9am for weekend matches)
                send_date = match.date - timedelta(days=match.date.weekday() + 1)
                send_time = datetime.combine(send_date, datetime.min.time()) + timedelta(hours=9)

                # Check for existing message
                existing_message = ScheduledMessage.query.filter_by(match_id=match.id).first()
                
                if not existing_message:
                    scheduled_message = ScheduledMessage(
                        match_id=match.id,
                        scheduled_send_time=send_time,
                        status='PENDING'
                    )
                    db.session.add(scheduled_message)
                    count += 1
                    logger.info(f"Scheduled availability message for match {match.id} at {send_time}")
            return count

        scheduled_count = create_scheduled_messages(matches)
        
        result = {
            "message": f"Scheduled {scheduled_count} availability messages for the next week.",
            "scheduled_count": scheduled_count,
            "total_matches": len(matches),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat()
        }
        
        logger.info(f"Task completed: {result['message']}")
        return result

    except Exception as e:
        logger.error(f"Error in schedule_season_availability: {str(e)}", exc_info=True)
        return {
            "success": False,
            "message": str(e)
        }

@async_task(name='app.tasks.tasks_core.async_send_availability_message_task')
async def async_send_availability_message_task(self, scheduled_message_id: int) -> str:
    """Celery task to send availability message asynchronously."""
    try:
        await _send_availability_message(scheduled_message_id)
        return "Availability message sent successfully"
    except Exception as e:
        logger.error(f"Error sending availability message: {str(e)}", exc_info=True)
        raise

@celery_task(name='app.tasks.tasks_core.retry_failed_task')
def retry_failed_task(self, task_name: str, *args, **kwargs) -> Any:
    """Generic task to retry failed operations."""
    from app import celery
    try:
        task = celery.tasks[task_name]
        return task.apply(args=args, kwargs=kwargs)
    except Exception as e:
        logger.error(f"Error retrying task {task_name}: {str(e)}", exc_info=True)
        raise

@celery_task(name='app.tasks.tasks_core.send_scheduled_messages')
def send_scheduled_messages(self) -> str:
    """Process and send all pending scheduled messages."""
    try:
        @query_operation
        def get_pending_messages() -> List[ScheduledMessage]:
            now = datetime.utcnow()
            return ScheduledMessage.query.filter(
                ScheduledMessage.status == 'PENDING',
                ScheduledMessage.scheduled_send_time <= now
            ).all()

        messages_to_send = get_pending_messages()

        @db_operation
        def update_message_status(message_id: int, status: str) -> None:
            message = ScheduledMessage.query.get(message_id)
            if message:
                message.status = status

        for scheduled_message in messages_to_send:
            try:
                async_send_availability_message_task.delay(scheduled_message.id)
                update_message_status(scheduled_message.id, 'QUEUED')
            except Exception as e:
                logger.error(f"Error queueing message {scheduled_message.id}: {str(e)}", exc_info=True)
                update_message_status(scheduled_message.id, 'FAILED')

        return f"Processed {len(messages_to_send)} scheduled messages."

    except Exception as e:
        logger.error(f"Error processing scheduled messages: {str(e)}", exc_info=True)
        return f"Error processing scheduled messages: {str(e)}"

async def _send_availability_message(scheduled_message_id: int) -> None:
    """Helper coroutine to send availability message."""
    bot_api_url = "http://discord-bot:5001/api/post_availability"
    
    @query_operation
    def get_message_and_match() -> Optional[tuple]:
        scheduled_message = ScheduledMessage.query.get(scheduled_message_id)
        if not scheduled_message:
            raise ValueError(f"ScheduledMessage with ID {scheduled_message_id} not found")

        match = Match.query.get(scheduled_message.match_id)
        if not match:
            raise ValueError(f"Match with ID {scheduled_message.match_id} not found")
            
        return scheduled_message, match

    message_data = get_message_and_match()
    if not message_data:
        return None

    scheduled_message, match = message_data

    payload = {
        "match_id": match.id,
        "home_team_id": match.home_team_id,
        "away_team_id": match.away_team_id,
        "home_channel_id": str(match.home_team.discord_channel_id),
        "away_channel_id": str(match.away_team.discord_channel_id),
        "match_date": match.date.strftime('%Y-%m-%d'),
        "match_time": match.time.strftime('%H:%M:%S'),
        "home_team_name": match.home_team.name,
        "away_team_name": match.away_team.name
    }

    logger.debug(f"Sending availability message with payload: {payload}")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(bot_api_url, json=payload, timeout=30) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Failed to send availability message. Status: {response.status}, Error: {error_text}")
                    
                    @db_operation
                    def mark_failed():
                        message = ScheduledMessage.query.get(scheduled_message_id)
                        if message:
                            message.status = 'FAILED'
                    
                    mark_failed()
                    raise Exception(f"Failed to send message: {error_text}")

                result = await response.json()
                logger.info(f"Successfully sent availability message for match {match.id}")
                
                @db_operation
                def mark_sent():
                    message = ScheduledMessage.query.get(scheduled_message_id)
                    if message:
                        message.status = 'SENT'
                
                mark_sent()

    except Exception as e:
        logger.error(f"Error in _send_availability_message: {str(e)}", exc_info=True)
        raise

# Additional utility functions for monitoring and cleanup
@celery_task(name='app.tasks.tasks_core.cleanup_old_messages')
def cleanup_old_messages(self, days_old: int = 30) -> Dict[str, Any]:
    """Clean up old scheduled messages."""
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days_old)
        
        @db_operation
        def delete_old_messages() -> int:
            deleted = ScheduledMessage.query.filter(
                ScheduledMessage.scheduled_send_time < cutoff_date,
                ScheduledMessage.status.in_(['SENT', 'FAILED'])
            ).delete(synchronize_session=False)
            return deleted

        deleted_count = delete_old_messages()
        
        return {
            "success": True,
            "message": f"Cleaned up {deleted_count} old messages",
            "deleted_count": deleted_count
        }
    except Exception as e:
        logger.error(f"Error cleaning up old messages: {str(e)}", exc_info=True)
        return {
            "success": False,
            "message": str(e)
        }