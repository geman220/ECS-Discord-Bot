# app/tasks/tasks_core.py

"""
Core tasks for scheduling match availability and player synchronization.

This module defines several Celery tasks that:
  - Schedule availability messages for upcoming matches.
  - Send availability messages to Discord via an asynchronous HTTP call.
  - Retry failed tasks generically.
  - Process and queue scheduled messages for sending.
  - Clean up old scheduled messages from the database.

Each task uses a provided database session and updates task state for progress reporting.
"""

import logging
import asyncio
import aiohttp
from datetime import datetime, timedelta
from typing import Dict, Any

from app.decorators import celery_task
from app.models import Match, ScheduledMessage, MLSMatch
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import SQLAlchemyError

from app.players_helpers import extract_player_info

logger = logging.getLogger(__name__)


@celery_task(
    name='app.tasks.tasks_core.schedule_season_availability',
    retry_backoff=True,
    bind=True
)
def schedule_season_availability(self, session) -> Dict[str, Any]:
    """
    Schedule availability messages for matches occurring in the next 90 days (entire season).

    The task:
      - Determines the current date range (today through 90 days ahead).
      - Retrieves matches scheduled in that date range.
      - For each match without a scheduled message, calculates a send time (9 AM on a computed date).
      - Creates a ScheduledMessage record in the database.
      - Updates Celery task state as progress.

    Returns:
        A dictionary summarizing the number of messages scheduled and match count.
    
    Raises:
        Exception: If no current Pub League season is found or other errors occur.
    """
    try:
        start_date = datetime.utcnow().date()
        # For "entire season", look at the next 90 days instead of just 7
        end_date = start_date + timedelta(days=90)

        # Query matches within the next 90 days along with any associated scheduled messages
        matches = session.query(Match).options(
            joinedload(Match.scheduled_messages)
        ).filter(
            Match.date.between(start_date, end_date)
        ).all()

        # Prepare data for each match
        matches_data = [{
            'id': match.id,
            'date': match.date,
            'has_message': any(msg for msg in match.scheduled_messages)
        } for match in matches]

        scheduled_count = 0
        # Process each match; schedule a message if not already present
        for match_data in matches_data:
            if not match_data['has_message']:
                # Calculate send date and time (9:00 AM on the computed day)
                send_date = match_data['date'] - timedelta(days=match_data['date'].weekday() + 1)
                send_time = datetime.combine(send_date, datetime.min.time()) + timedelta(hours=9)

                scheduled_message = ScheduledMessage(
                    match_id=match_data['id'],
                    scheduled_send_time=send_time,
                    status='PENDING'
                )
                session.add(scheduled_message)
                scheduled_count += 1
                logger.info(f"Scheduled availability message for match {match_data['id']} at {send_time}")

        result = {
            "message": f"Scheduled {scheduled_count} availability messages for matches in the next 90 days.",
            "scheduled_count": scheduled_count,
            "total_matches": len(matches_data),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat()
        }
        logger.info(result["message"])
        return result

    except Exception as e:
        logger.error(f"Error in schedule_season_availability: {str(e)}", exc_info=True)
        # Retry the task after 60 seconds with a maximum of 3 retries
        self.retry(exc=e, countdown=60, max_retries=3)
        return {"success": False, "message": str(e)}


@celery_task(
    name='app.tasks.tasks_core.send_availability_message_task',
    bind=True
)
def send_availability_message_task(self, session, scheduled_message_id: int) -> Dict[str, Any]:
    """
    Send an availability message for a match (handles Pub League, MLSMatch, and ECS FC matches).

    The task:
      - Retrieves the ScheduledMessage and routes to appropriate handler based on message type.
      - For ECS FC messages: Routes to dedicated ECS FC handler.
      - For regular matches: Extracts and formats match details based on match type.
      - Invokes appropriate helper to send the message via Discord API.
      - Updates the ScheduledMessage status to 'SENT' upon success.

    Returns:
        A dictionary indicating success, with details of the sent message.
    
    Raises:
        Exception: If the message or match is not found or if sending fails.
    """
    try:
        # Fetch scheduled message along with its associated match
        message = session.query(ScheduledMessage).options(
            joinedload(ScheduledMessage.match)
        ).get(scheduled_message_id)

        if not message:
            raise ValueError(f"Message not found for ID {scheduled_message_id}")

        # Check if this is an ECS FC message
        if message.message_type == 'ecs_fc_rsvp' or (message.message_metadata and message.message_metadata.get('ecs_fc_match_id')):
            # Route to ECS FC handler by queueing the dedicated task
            from app.tasks.tasks_ecs_fc_scheduled import send_ecs_fc_availability_message
            # Queue the ECS FC task and return immediately
            task_result = send_ecs_fc_availability_message.delay(scheduled_message_id)
            return {
                'success': True,
                'message': 'ECS FC availability message queued',
                'task_id': task_result.id,
                'routed_to': 'ecs_fc_handler'
            }

        # For regular pub league and MLS matches
        if not message.match:
            raise ValueError(f"Regular match not found for scheduled message ID {scheduled_message_id}")

        match = message.match

        # Process match details based on match type (MLSMatch or Pub League match)
        if isinstance(match, MLSMatch):
            local_team_name = "ECS FC"
            if match.is_home_game:
                home_team_name = local_team_name
                away_team_name = match.opponent
            else:
                home_team_name = match.opponent
                away_team_name = local_team_name

            home_channel_id = None
            away_channel_id = None

            match_date_str = match.date_time.strftime('%Y-%m-%d')
            match_time_str = match.date_time.strftime('%H:%M:%S')
        else:
            if not hasattr(match, 'home_team') or not hasattr(match, 'away_team'):
                raise ValueError("Pub League match found but missing home_team/away_team attributes.")

            home_channel_id = str(match.home_team.discord_channel_id)
            away_channel_id = str(match.away_team.discord_channel_id)
            match_date_str = match.date.strftime('%Y-%m-%d')
            match_time_str = match.time.strftime('%H:%M:%S')
            home_team_name = match.home_team.name
            away_team_name = match.away_team.name

        # Extract team IDs
        if hasattr(match, 'home_team') and hasattr(match, 'away_team'):
            home_team_id = match.home_team.id
            away_team_id = match.away_team.id
        else:
            # For MLS matches, we need to handle differently
            # Default to None if not available
            home_team_id = getattr(match, 'home_team_id', None)
            away_team_id = getattr(match, 'away_team_id', None)

        message_data = {
            "match_id": match.id,
            "home_team_id": home_team_id,
            "away_team_id": away_team_id,
            "home_channel_id": home_channel_id,
            "away_channel_id": away_channel_id,
            "match_date": match_date_str,
            "match_time": match_time_str,
            "home_team_name": home_team_name,
            "away_team_name": away_team_name
        }

        # Use synchronous Discord client to send availability message
        from app.utils.sync_discord_client import get_sync_discord_client
        discord_client = get_sync_discord_client()
        result = discord_client.send_availability_message(message_data)

        # Update the scheduled message status to SENT
        message = session.query(ScheduledMessage).get(scheduled_message_id)
        if message:
            message.status = 'SENT'

        return {
            "success": True,
            "message": "Availability message sent successfully",
            "data": result
        }

    except Exception as e:
        # Mark the message as FAILED if an error occurs
        msg = session.query(ScheduledMessage).get(scheduled_message_id)
        if msg:
            msg.status = 'FAILED'
        logger.error(f"Error sending availability message: {str(e)}", exc_info=True)
        raise self.retry(exc=e)


@celery_task(
    name='app.tasks.tasks_core.retry_failed_task',
    bind=True
)
def retry_failed_task(self, session, task_name: str, *args, **kwargs) -> Any:
    """
    Generic task to retry failed operations.

    This task attempts to locate and re-run a specified task using its name and parameters.

    Returns:
        The result of the retried task.
    
    Raises:
        Exception: If the retried task fails.
    """
    from app import celery
    try:
        task = celery.tasks[task_name]
        return task.apply(args=args, kwargs=kwargs)
    except Exception as e:
        logger.error(f"Error retrying task {task_name}: {str(e)}", exc_info=True)
        raise self.retry(exc=e)


@celery_task(
    name='app.tasks.tasks_core.send_scheduled_messages',
    bind=True
)
def send_scheduled_messages(self, session) -> Dict[str, Any]:
    """
    Process and send all pending scheduled messages.

    This task:
      - Queries for all pending scheduled messages whose send time is due.
      - For each message, queues the sending task and updates its status to 'QUEUED'.
      - Tracks the number of processed and failed messages.

    Returns:
        A summary dictionary of the processing outcome.
    """
    try:
        now = datetime.utcnow()
        messages = session.query(ScheduledMessage).filter(
            ScheduledMessage.status == 'PENDING',
            ScheduledMessage.scheduled_send_time <= now
        ).all()

        messages_to_send = [{'id': msg.id, 'match_id': msg.match_id} for msg in messages]

        processed_count = 0
        failed_count = 0

        # Import the send task to queue messages
        from app.tasks.tasks_core import send_availability_message_task

        for msg_data in messages_to_send:
            try:
                send_availability_message_task.delay(msg_data['id'])
                # Update status to QUEUED after successfully queueing the task
                message = session.query(ScheduledMessage).get(msg_data['id'])
                if message:
                    message.status = 'QUEUED'
                processed_count += 1
            except Exception as e:
                logger.error(f"Error queueing message {msg_data['id']}: {str(e)}", exc_info=True)
                message = session.query(ScheduledMessage).get(msg_data['id'])
                if message:
                    message.status = 'FAILED'
                failed_count += 1

        return {
            "success": True,
            "message": f"Processed {len(messages_to_send)} scheduled messages",
            "processed_count": processed_count,
            "failed_count": failed_count
        }

    except Exception as e:
        logger.error(f"Error processing scheduled messages: {str(e)}", exc_info=True)
        return {
            "success": False,
            "message": str(e)
        }


async def _send_availability_message(message_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Asynchronous helper coroutine to send an availability message via HTTP.

    This function makes a POST request to the Discord bot API with the provided message data.
    
    Args:
        message_data: A dictionary containing match and channel details.

    Returns:
        A dictionary with the message send result.
    
    Raises:
        Exception: If the HTTP request fails or returns a non-200 status code.
    """
    bot_api_url = "http://discord-bot:5001/api/post_availability"

    try:
        async with aiohttp.ClientSession() as aiosession:
            async with aiosession.post(bot_api_url, json=message_data, timeout=30) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(
                        f"Failed to send availability message. Status: {response.status}, Error: {error_text}"
                    )
                    raise Exception(f"Failed to send message: {error_text}")

                result = await response.json()
                logger.info(f"Successfully sent availability message for match {message_data['match_id']}")
                return {
                    "match_id": message_data["match_id"],
                    "status": "sent",
                }

    except Exception as e:
        logger.error(f"Error in _send_availability_message: {str(e)}", exc_info=True)
        raise


@celery_task(
    name='app.tasks.tasks_core.cleanup_old_messages',
    bind=True,
    max_retries=3,
    retry_backoff=True
)
def cleanup_old_messages(self, session, days_old: int = 30) -> Dict[str, Any]:
    """
    Clean up old scheduled messages that are either SENT or FAILED and older than a specified number of days.

    The task:
      - Computes a cutoff date based on the provided days_old parameter.
      - Processes messages in batches (default size 1000) to delete eligible messages.
      - Logs deletion details and statistics for each batch.

    Returns:
        A dictionary summarizing the cleanup process, including total deletions and batch statistics.
    
    Raises:
        SQLAlchemyError: If a database error occurs during deletion, with a retry.
        Exception: For any other errors, with a retry.
    """
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days_old)
        batch_size = 1000
        cleanup_stats = {
            'total_deleted': 0,
            'batches_processed': 0,
            'deletion_details': []
        }

        total_messages = session.query(ScheduledMessage).filter(
            ScheduledMessage.scheduled_send_time < cutoff_date,
            ScheduledMessage.status.in_(['SENT', 'FAILED'])
        ).count()

        logger.info(
            f"Starting message cleanup for messages older than {days_old} days",
            extra={'cutoff_date': cutoff_date.isoformat(), 'total_messages': total_messages, 'batch_size': batch_size}
        )

        # OPTIMIZED: Use bulk delete operations instead of loading records
        from app.utils.query_optimizer import BulkOperationHelper
        
        # Get sample for logging before deletion
        sample_messages = session.query(ScheduledMessage).filter(
            ScheduledMessage.scheduled_send_time < cutoff_date,
            ScheduledMessage.status.in_(['SENT', 'FAILED'])
        ).limit(50).all()
        
        cleanup_stats['deletion_details'] = [{
            'id': msg.id,
            'status': msg.status,
            'scheduled_time': msg.scheduled_send_time.isoformat(),
            'match_id': msg.match_id
        } for msg in sample_messages]
        
        # Use bulk delete for efficiency
        delete_conditions = [
            ScheduledMessage.scheduled_send_time < cutoff_date,
            ScheduledMessage.status.in_(['SENT', 'FAILED'])
        ]
        
        total_deleted = BulkOperationHelper.bulk_delete_with_conditions(
            session, ScheduledMessage, delete_conditions, batch_size=1000
        )
        
        cleanup_stats['total_deleted'] = total_deleted
        cleanup_stats['batches_processed'] = 1  # Single bulk operation
        cleanup_stats['optimization_used'] = 'bulk_delete_operations'
        
        logger.info(f"Bulk deleted {total_deleted} old messages using optimized operations")

        result = {
            'success': True,
            'message': f"Cleaned up {cleanup_stats['total_deleted']} old messages",
            'stats': {
                'deleted_count': cleanup_stats['total_deleted'],
                'batches_processed': cleanup_stats['batches_processed'],
                'total_eligible': total_messages,
                'cutoff_date': cutoff_date.isoformat()
            },
            'deletion_details': cleanup_stats['deletion_details'],
            'cleanup_time': datetime.utcnow().isoformat()
        }

        logger.info(
            "Message cleanup completed successfully",
            extra={
                'deleted_count': cleanup_stats['total_deleted'],
                'batches_processed': cleanup_stats['batches_processed']
            }
        )

        return result

    except SQLAlchemyError as e:
        error_msg = f"Database error cleaning up old messages: {str(e)}"
        logger.error(error_msg, extra={'days_old': days_old}, exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        error_msg = f"Error cleaning up old messages: {str(e)}"
        logger.error(error_msg, extra={'days_old': days_old}, exc_info=True)
        raise self.retry(exc=e, countdown=30)