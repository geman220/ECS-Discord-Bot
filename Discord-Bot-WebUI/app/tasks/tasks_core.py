# app/tasks/tasks_core.py

import logging
import asyncio
import aiohttp
from datetime import datetime, timedelta
from typing import Dict, Any

from app.extensions import db
from app.decorators import celery_task, async_task
from app.models import Match, ScheduledMessage

logger = logging.getLogger(__name__)

@celery_task(
    name='app.tasks.tasks_core.schedule_season_availability',
    retry_backoff=True
)
def schedule_season_availability(self):
    """Schedule availability messages for matches in the next week."""
    start_date = datetime.utcnow().date()
    end_date = start_date + timedelta(days=7)

    matches = Match.query.filter(
        Match.date.between(start_date, end_date)
    ).all()

    scheduled_count = 0
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
            scheduled_count += 1
            logger.info(f"Scheduled availability message for match {match.id} at {send_time}")
    
    result = {
        "message": f"Scheduled {scheduled_count} availability messages for the next week.",
        "scheduled_count": scheduled_count,
        "total_matches": len(matches),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat()
    }
    
    logger.info(f"Task completed: {result['message']}")
    return result

@async_task(name='app.tasks.tasks_core.async_send_availability_message_task')
async def async_send_availability_message_task(self, scheduled_message_id: int):
    """Celery task to send availability message asynchronously."""
    await _send_availability_message(scheduled_message_id)
    return "Availability message sent successfully"

@celery_task(name='app.tasks.tasks_core.retry_failed_task')
def retry_failed_task(self, task_name: str, *args, **kwargs):
    """
    Generic task to retry failed operations.
    
    Args:
        task_name: Name of the task to retry
        *args: Positional arguments for the task
        **kwargs: Keyword arguments for the task
    """
    from app import celery
    task = celery.tasks[task_name]
    return task.apply(args=args, kwargs=kwargs)

@celery_task(name='app.tasks.tasks_core.send_scheduled_messages')
def send_scheduled_messages(self):
    """Process and send all pending scheduled messages."""
    now = datetime.utcnow()
    messages_to_send = ScheduledMessage.query.filter(
        ScheduledMessage.status == 'PENDING',
        ScheduledMessage.scheduled_send_time <= now
    ).all()

    for scheduled_message in messages_to_send:
        try:
            async_send_availability_message_task.delay(scheduled_message.id)
            scheduled_message.status = 'QUEUED'
        except Exception as e:
            logger.error(f"Error queueing message {scheduled_message.id}: {str(e)}", exc_info=True)
            scheduled_message.status = 'FAILED'

    return f"Processed {len(messages_to_send)} scheduled messages."

# Helper Functions
async def _send_availability_message(scheduled_message_id: int):
    """Helper coroutine to send availability message."""
    bot_api_url = "http://discord-bot:5001/api/post_availability"
    
    scheduled_message = ScheduledMessage.query.get(scheduled_message_id)
    if not scheduled_message:
        raise ValueError(f"ScheduledMessage with ID {scheduled_message_id} not found")

    match = Match.query.get(scheduled_message.match_id)
    if not match:
        raise ValueError(f"Match with ID {scheduled_message.match_id} not found")

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

    async with aiohttp.ClientSession() as session:
        async with session.post(bot_api_url, json=payload, timeout=30) as response:
            if response.status != 200:
                error_text = await response.text()
                logger.error(f"Failed to send availability message. Status: {response.status}, Error: {error_text}")
                scheduled_message.status = 'FAILED'
                raise Exception(f"Failed to send message: {error_text}")

            result = await response.json()
            logger.info(f"Successfully sent availability message for match {match.id}")
            scheduled_message.status = 'SENT'