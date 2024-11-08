# app/tasks/tasks_core.py

import logging
import asyncio
import traceback
import threading
import aiohttp
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Union
from app.extensions import db
from app.celery_utils import async_task_with_context
from app.decorators import celery_task, async_task, db_operation, query_operation, session_context
from app.models import Match, ScheduledMessage, User
from sqlalchemy.orm import joinedload
from flask import has_app_context, current_app
from app.decorators import log_context_state

logger = logging.getLogger(__name__)

@celery_task(
    name='app.tasks.tasks_core.schedule_season_availability',
    retry_backoff=True,
    bind=True
)
def schedule_season_availability(self) -> Dict[str, Any]:
    """Schedule availability messages for matches in the next week."""
    try:
        start_date = datetime.utcnow().date()
        end_date = start_date + timedelta(days=7)
        with session_context():
            @query_operation
            def get_matches_data() -> List[Dict[str, Any]]:
                matches = Match.query.options(
                    joinedload(Match.scheduled_messages)
                ).filter(
                    Match.date.between(start_date, end_date)
                ).all()
                
                return [{
                    'id': match.id,
                    'date': match.date,
                    'has_message': any(msg for msg in match.scheduled_messages)
                } for match in matches]

            matches_data = get_matches_data()

            @db_operation
            def create_scheduled_messages() -> int:
                count = 0
                for match_data in matches_data:
                    if not match_data['has_message']:
                        send_date = match_data['date'] - timedelta(days=match_data['date'].weekday() + 1)
                        send_time = datetime.combine(send_date, datetime.min.time()) + timedelta(hours=9)
                        
                        scheduled_message = ScheduledMessage(
                            match_id=match_data['id'],
                            scheduled_send_time=send_time,
                            status='PENDING'
                        )
                        db.session.add(scheduled_message)
                        count += 1
                        logger.info(f"Scheduled availability message for match {match_data['id']} at {send_time}")
                return count

            scheduled_count = create_scheduled_messages()

        result = {
            "message": f"Scheduled {scheduled_count} availability messages for the next week.",
            "scheduled_count": scheduled_count,
            "total_matches": len(matches_data),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat()
        }
        logger.info(f"Task completed: {result['message']}")
        return result

    except Exception as e:
        logger.error(f"Error in schedule_season_availability: {str(e)}", exc_info=True)
        # Use the bound task's retry method if needed
        self.retry(exc=e, countdown=60, max_retries=3)
        return {
            "success": False,
            "message": str(e)
        }

@celery_task(
    name='app.tasks.tasks_core.send_availability_message_task',
    bind=True
)
def send_availability_message_task(self, scheduled_message_id: int) -> Dict[str, Any]:
    """Celery task to send availability message."""
    try:
        # Get all needed data in one session at the start
        message_data = None
        with session_context() as session:
            message = session.query(ScheduledMessage).options(
                joinedload(ScheduledMessage.match),
                joinedload(ScheduledMessage.match).joinedload(Match.home_team),
                joinedload(ScheduledMessage.match).joinedload(Match.away_team)
            ).get(scheduled_message_id)

            if not message or not message.match:
                raise ValueError(f"Message or match not found for ID {scheduled_message_id}")

            # Create detached data copy
            message_data = {
                "match_id": message.match.id,
                "home_team_id": message.match.home_team_id,
                "away_team_id": message.match.away_team_id,
                "home_channel_id": str(message.match.home_team.discord_channel_id),
                "away_channel_id": str(message.match.away_team.discord_channel_id),
                "match_date": message.match.date.strftime('%Y-%m-%d'),
                "match_time": message.match.time.strftime('%H:%M:%S'),
                "home_team_name": message.match.home_team.name,
                "away_team_name": message.match.away_team.name
            }

        # Now run the async operation with just the data
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_send_availability_message(message_data))
            
            # Update status in a new session after successful send
            with session_context() as session:
                message = session.query(ScheduledMessage).get(scheduled_message_id)
                if message:
                    message.status = 'SENT'
                    message.home_discord_message_id = result.get('home_message_id')
                    message.away_discord_message_id = result.get('away_message_id')

            return {
                "success": True,
                "message": "Availability message sent successfully",
                "data": result
            }
        except Exception as e:
            # Update status in a new session after failure
            with session_context() as session:
                message = session.query(ScheduledMessage).get(scheduled_message_id)
                if message:
                    message.status = 'FAILED'
            raise
        finally:
            loop.close()

    except Exception as e:
        logger.error(f"Error sending availability message: {str(e)}", exc_info=True)
        raise self.retry(exc=e)

@celery_task(
    name='app.tasks.tasks_core.retry_failed_task',
    bind=True
)
def retry_failed_task(self, task_name: str, *args, **kwargs) -> Any:
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
def send_scheduled_messages(self) -> Dict[str, Any]:
    """Process and send all pending scheduled messages."""
    try:
        with session_context():
            @query_operation
            def get_pending_messages() -> List[Dict[str, Any]]:
                now = datetime.utcnow()
                messages = ScheduledMessage.query.filter(
                    ScheduledMessage.status == 'PENDING',
                    ScheduledMessage.scheduled_send_time <= now
                ).options(
                    joinedload(ScheduledMessage.match)
                ).all()
                
                return [{
                    'id': msg.id,
                    'match_id': msg.match_id
                } for msg in messages]

            messages_to_send = get_pending_messages()

        processed_count = 0
        failed_count = 0

        for message_data in messages_to_send:
            try:
                send_availability_message_task.delay(message_data['id'])
                
                with session_context():
                    @db_operation
                    def update_message_status():
                        message = ScheduledMessage.query.get(message_data['id'])
                        if message:
                            message.status = 'QUEUED'
                    
                    update_message_status()
                processed_count += 1
                
            except Exception as e:
                logger.error(f"Error queueing message {message_data['id']}: {str(e)}", exc_info=True)
                
                with session_context():
                    @db_operation
                    def mark_message_failed():
                        message = ScheduledMessage.query.get(message_data['id'])
                        if message:
                            message.status = 'FAILED'
                    
                    mark_message_failed()
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
        async with aiohttp.ClientSession() as session:
            async with session.post(bot_api_url, json=message_data, timeout=30) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Failed to send availability message. Status: {response.status}, Error: {error_text}")
                    raise Exception(f"Failed to send message: {error_text}")

                result = await response.json()
                logger.info(f"Successfully sent availability message for match {message_data['match_id']}")
                return {
                    "match_id": message_data["match_id"],
                    "status": "sent",
                    "home_message_id": result.get('home_message_id'),
                    "away_message_id": result.get('away_message_id')
                }

    except Exception as e:
        logger.error(f"Error in _send_availability_message: {str(e)}", exc_info=True)
        raise

@celery_task(
    name='app.tasks.tasks_core.cleanup_old_messages',
    bind=True
)
def cleanup_old_messages(self, days_old: int = 30) -> Dict[str, Any]:
    """Clean up old scheduled messages."""
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days_old)

        with session_context():
            @db_operation
            def delete_old_messages() -> int:
                batch_size = 1000
                total_deleted = 0

                while True:
                    deleted = ScheduledMessage.query.filter(
                        ScheduledMessage.scheduled_send_time < cutoff_date,
                        ScheduledMessage.status.in_(['SENT', 'FAILED'])
                    ).limit(batch_size).delete(synchronize_session=False)

                    if not deleted:
                        break

                    total_deleted += deleted
                    db.session.commit()

                return total_deleted

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