import logging
import asyncio
import aiohttp
from datetime import datetime, timedelta
from typing import Dict, Any

from app.decorators import celery_task
from app.models import Match, ScheduledMessage, MLSMatch
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

@celery_task(
    name='app.tasks.tasks_core.schedule_season_availability',
    retry_backoff=True,
    bind=True
)
def schedule_season_availability(self, session) -> Dict[str, Any]:
    """Schedule availability messages for matches in the next week (Pub League example)."""
    try:
        start_date = datetime.utcnow().date()
        end_date = start_date + timedelta(days=7)

        matches = session.query(Match).options(
            joinedload(Match.scheduled_messages)
        ).filter(
            Match.date.between(start_date, end_date)
        ).all()

        matches_data = [{
            'id': match.id,
            'date': match.date,
            'has_message': any(msg for msg in match.scheduled_messages)
        } for match in matches]

        scheduled_count = 0
        for match_data in matches_data:
            if not match_data['has_message']:
                # Example logic: send at Monday 9AM of the match's week
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
            "message": f"Scheduled {scheduled_count} availability messages for the next week.",
            "scheduled_count": scheduled_count,
            "total_matches": len(matches_data),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat()
        }
        logger.info(result["message"])
        return result

    except Exception as e:
        logger.error(f"Error in schedule_season_availability: {str(e)}", exc_info=True)
        self.retry(exc=e, countdown=60, max_retries=3)
        return {"success": False, "message": str(e)}


@celery_task(
    name='app.tasks.tasks_core.send_availability_message_task',
    bind=True
)
def send_availability_message_task(self, session, scheduled_message_id: int) -> Dict[str, Any]:
    """Celery task to send availability message for either a Pub League Match or MLSMatch."""
    try:
        message = session.query(ScheduledMessage).options(
            # If it's a Pub League match, these loads will work; MLSMatch won't have these relationships
            joinedload(ScheduledMessage.match)
        ).get(scheduled_message_id)

        if not message or not message.match:
            raise ValueError(f"Message or match not found for ID {scheduled_message_id}")

        match = message.match

        # Determine if this is an MLSMatch or a Pub League Match
        if isinstance(match, MLSMatch):
            # MLS logic
            # We only have 'opponent', 'is_home_game', and 'date_time'
            local_team_name = "ECS FC"  # Your local MLS team name
            if match.is_home_game:
                home_team_name = local_team_name
                away_team_name = match.opponent
            else:
                home_team_name = match.opponent
                away_team_name = local_team_name

            # For MLS matches, if you previously relied on home_team/away_team channels, decide what to do now.
            # If you don't have channels for MLS matches, set them to None or skip them.
            home_channel_id = None
            away_channel_id = None

            match_date_str = match.date_time.strftime('%Y-%m-%d')
            match_time_str = match.date_time.strftime('%H:%M:%S')
        else:
            # Pub League logic (original)
            if not hasattr(match, 'home_team') or not hasattr(match, 'away_team'):
                # If somehow we have a normal Match but no relationships, handle error
                raise ValueError("Pub League match found but no home_team/away_team attributes.")

            home_channel_id = str(match.home_team.discord_channel_id)
            away_channel_id = str(match.away_team.discord_channel_id)
            match_date_str = match.date.strftime('%Y-%m-%d')
            match_time_str = match.time.strftime('%H:%M:%S')
            home_team_name = match.home_team.name
            away_team_name = match.away_team.name

        message_data = {
            "match_id": match.id,
            "home_channel_id": home_channel_id,
            "away_channel_id": away_channel_id,
            "match_date": match_date_str,
            "match_time": match_time_str,
            "home_team_name": home_team_name,
            "away_team_name": away_team_name
        }

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_send_availability_message(message_data))
        finally:
            loop.close()

        # Update status to SENT
        message = session.query(ScheduledMessage).get(scheduled_message_id)
        if message:
            message.status = 'SENT'
            # If result returned message IDs, store them if needed
            # message.home_discord_message_id = result.get('home_message_id')
            # message.away_discord_message_id = result.get('away_message_id')

        return {
            "success": True,
            "message": "Availability message sent successfully",
            "data": result
        }

    except Exception as e:
        # Mark failed if sending failed
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
    """Generic task to retry failed operations."""
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
    """Process and send all pending scheduled messages."""
    try:
        now = datetime.utcnow()
        messages = session.query(ScheduledMessage).filter(
            ScheduledMessage.status == 'PENDING',
            ScheduledMessage.scheduled_send_time <= now
        ).all()

        messages_to_send = [{'id': msg.id, 'match_id': msg.match_id} for msg in messages]

        processed_count = 0
        failed_count = 0

        from app.tasks.tasks_core import send_availability_message_task

        for msg_data in messages_to_send:
            try:
                # Queue the task to send the message
                send_availability_message_task.delay(msg_data['id'])

                # Mark status as QUEUED
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
    """Helper coroutine to send availability message - no DB operations."""
    bot_api_url = "http://discord-bot:5001/api/post_availability"

    try:
        async with aiohttp.ClientSession() as aiosession:
            async with aiosession.post(bot_api_url, json=message_data, timeout=30) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Failed to send availability message. Status: {response.status}, Error: {error_text}")
                    raise Exception(f"Failed to send message: {error_text}")

                result = await response.json()
                logger.info(f"Successfully sent availability message for match {message_data['match_id']}")
                return {
                    "match_id": message_data["match_id"],
                    "status": "sent",
                    # "home_message_id": result.get('home_message_id'),
                    # "away_message_id": result.get('away_message_id')
                    # Uncomment above lines if your API returns these fields
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
    """Clean up old scheduled messages that are SENT or FAILED and older than X days."""
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

        while True:
            messages_to_delete = session.query(ScheduledMessage).filter(
                ScheduledMessage.scheduled_send_time < cutoff_date,
                ScheduledMessage.status.in_(['SENT', 'FAILED'])
            ).limit(batch_size).all()

            if not messages_to_delete:
                break

            batch_details = [{
                'id': msg.id,
                'status': msg.status,
                'scheduled_time': msg.scheduled_send_time.isoformat(),
                'match_id': msg.match_id
            } for msg in messages_to_delete]
            cleanup_stats['deletion_details'].extend(batch_details)

            deleted_count = session.query(ScheduledMessage).filter(
                ScheduledMessage.id.in_([msg.id for msg in messages_to_delete])
            ).delete(synchronize_session=False)

            cleanup_stats['total_deleted'] += deleted_count
            cleanup_stats['batches_processed'] += 1
            session.flush()

            logger.info(
                f"Processed cleanup batch",
                extra={
                    'batch_number': cleanup_stats['batches_processed'],
                    'batch_size': len(messages_to_delete),
                    'total_deleted': cleanup_stats['total_deleted']
                }
            )

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
        logger.error(
            error_msg,
            extra={'days_old': days_old},
            exc_info=True
        )
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        error_msg = f"Error cleaning up old messages: {str(e)}"
        logger.error(
            error_msg,
            extra={'days_old': days_old},
            exc_info=True
        )
        raise self.retry(exc=e, countdown=30)
