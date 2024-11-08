# app/tasks/tasks_rsvp.py

import logging
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from app.extensions import db, socketio
from app.decorators import celery_task, db_operation, query_operation, session_context
from app.models import Match, Availability, Player, ScheduledMessage
from app.tasks.tasks_rsvp_helpers import (
    _send_availability_message_async,
    _update_discord_rsvp_async,
    _notify_discord_async
)

logger = logging.getLogger(__name__)

@celery_task(
    name='app.tasks.tasks_rsvp.update_rsvp',
    bind=True,
    max_retries=3,
    queue='discord'
)
def update_rsvp(self, match_id: int, player_id: int, new_response: str, 
                discord_id: Optional[str] = None) -> Dict[str, Any]:
    """Update RSVP status with proper context management and detailed logging."""
    try:
        # Log initial parameters
        logger.info("Starting RSVP update", extra={
            "match_id": match_id, 
            "player_id": player_id, 
            "new_response": new_response, 
            "discord_id": discord_id
        })

        with session_context():
            @query_operation
            def get_match_and_player():
                match = db.session.query(Match).get(match_id)
                player = db.session.query(Player).get(player_id)
                if not match:
                    logger.warning("Match not found", extra={"match_id": match_id})
                if not player:
                    logger.warning("Player not found", extra={"player_id": player_id})
                return match, player

            match, player = get_match_and_player()
            if not match or not player:
                return {
                    'success': False,
                    'message': "Match or Player not found"
                }

            # Log successful match and player retrieval
            logger.info("Match and Player retrieved successfully", extra={
                "match_id": match_id,
                "player_id": player_id
            })

            @query_operation
            def get_availability() -> Optional[Dict[str, Any]]:
                availability = db.session.query(Availability).filter_by(
                    match_id=match_id,
                    player_id=player_id
                ).first()
                if availability:
                    logger.info("Current availability found", extra={
                        "match_id": match_id, 
                        "player_id": player_id, 
                        "old_response": availability.response
                    })
                    return {
                        'id': availability.id,
                        'response': availability.response
                    }
                else:
                    logger.info("No existing availability, will create new if response is not 'no_response'", extra={
                        "match_id": match_id, 
                        "player_id": player_id
                    })
                return None

            availability_data = get_availability()
            old_response = availability_data['response'] if availability_data else None

            @db_operation
            def update_availability_and_player():
                if availability_data:
                    availability = db.session.query(Availability).get(availability_data['id'])
                    if new_response == 'no_response':
                        logger.info("Deleting existing RSVP", extra={"availability_id": availability.id})
                        db.session.delete(availability)
                    else:
                        logger.info("Updating existing RSVP", extra={
                            "availability_id": availability.id, 
                            "new_response": new_response
                        })
                        availability.response = new_response
                        availability.responded_at = datetime.utcnow()
                else:
                    if new_response != 'no_response':
                        logger.info("Creating new RSVP entry", extra={
                            "match_id": match_id, 
                            "player_id": player_id, 
                            "new_response": new_response
                        })
                        new_availability = Availability(
                            match_id=match_id,
                            player_id=player_id,
                            response=new_response,
                            discord_id=discord_id,
                            responded_at=datetime.utcnow()
                        )
                        db.session.add(new_availability)

                if discord_id:
                    player = db.session.query(Player).get(player_id)
                    if player:
                        player.discord_id = discord_id
                        logger.info("Player discord_id updated", extra={"player_id": player_id, "discord_id": discord_id})

            update_availability_and_player()

        # Trigger notifications after successful update - outside session context
        if discord_id:
            logger.info("Queueing Discord RSVP update", extra={
                "match_id": match_id,
                "discord_id": discord_id,
                "new_response": new_response,
                "old_response": old_response
            })
            update_discord_rsvp_task.delay({
                "match_id": match_id,
                "discord_id": discord_id,
                "new_response": new_response,
                "old_response": old_response
            })

        logger.info("Queueing frontend notification", extra={
            "match_id": match_id,
            "player_id": player_id,
            "new_response": new_response
        })
        notify_frontend_of_rsvp_change_task.delay(
            match_id,
            player_id,
            new_response
        )

        return {
            'success': True,
            'message': "RSVP updated successfully"
        }

    except Exception as e:
        logger.error(f"Error updating RSVP: {str(e)}", exc_info=True, extra={
            "match_id": match_id, 
            "player_id": player_id
        })
        raise self.retry(exc=e)

@celery_task(
    name='app.tasks.tasks_rsvp.send_availability_message',
    bind=True,
    max_retries=3,
    retry_backoff=True,
    queue='discord'
)
def send_availability_message(self, scheduled_message_id: int) -> Dict[str, Any]:
    """Send availability message to Discord."""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_send_availability_message_async(scheduled_message_id))
            return result
        finally:
            loop.close()
    except Exception as e:
        logger.error(f"Error sending availability message: {str(e)}", exc_info=True)
        raise self.retry(exc=e)

@celery_task(
    name='app.tasks.tasks_rsvp.process_scheduled_messages',
    bind=True,
    queue='discord'
)
def process_scheduled_messages(self) -> Dict[str, Any]:
    """Process and send all pending scheduled messages."""
    try:
        with session_context():
            @query_operation
            def get_pending_messages() -> List[Dict[str, Any]]:
                now = datetime.utcnow()
                messages = db.session.query(ScheduledMessage).filter(
                    ScheduledMessage.status == 'PENDING',
                    ScheduledMessage.scheduled_send_time <= now
                ).all()
                return [{'id': msg.id} for msg in messages]

            messages_data = get_pending_messages()

        processed_count = 0
        failed_count = 0
        
        for message_data in messages_data:
            message_id = message_data['id']
            try:
                send_availability_message.delay(message_id)

                with session_context():
                    @db_operation
                    def update_message_status():
                        message = db.session.query(ScheduledMessage).get(message_id)
                        if message:
                            message.status = 'QUEUED'

                    update_message_status()
                processed_count += 1
                
            except Exception as e:
                logger.error(f"Error queueing message {message_id}: {str(e)}", exc_info=True)

                with session_context():
                    @db_operation
                    def mark_message_failed():
                        message = db.session.query(ScheduledMessage).get(message_id)
                        if message:
                            message.status = 'FAILED'

                    mark_message_failed()
                failed_count += 1

        return {
            'success': True,
            'message': f"Processed {len(messages_data)} scheduled messages",
            'processed_count': processed_count,
            'failed_count': failed_count
        }

    except Exception as e:
        logger.error(f"Error processing scheduled messages: {str(e)}", exc_info=True)
        raise self.retry(exc=e)

@celery_task(
    name='app.tasks.tasks_rsvp.notify_frontend_of_rsvp_change',
    bind=True,
    queue='discord'
)
def notify_frontend_of_rsvp_change_task(self, match_id: int, player_id: int, 
                                      response: str) -> Dict[str, Any]:
    """Notify frontend of RSVP changes via WebSocket."""
    try:
        socketio.emit(
            'rsvp_update',
            {
                'match_id': match_id,
                'player_id': player_id,
                'response': response
            },
            namespace='/availability'
        )
        logger.info(f"Frontend notified of RSVP change for match {match_id}")
        return {
            'success': True,
            'message': 'Frontend notification sent successfully'
        }
    except Exception as e:
        logger.error(f"Error notifying frontend: {str(e)}", exc_info=True)
        return {
            'success': False,
            'message': str(e)
        }

@celery_task(
    name='app.tasks.tasks_rsvp.update_discord_rsvp',
    bind=True,
    max_retries=3,
    retry_backoff=True,
    queue='discord'
)
def update_discord_rsvp_task(self, data: Dict[str, Any]) -> Dict[str, Any]:
    """Update Discord RSVP status."""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_update_discord_rsvp_async(data))
            return result
        finally:
            loop.close()
    except Exception as e:
        logger.error(f"Error updating Discord RSVP: {str(e)}", exc_info=True)
        raise self.retry(exc=e)

@celery_task(
    name='app.tasks.tasks_rsvp.notify_discord_of_rsvp_change',
    bind=True,
    queue='discord'
)
def notify_discord_of_rsvp_change_task(self, match_id: int) -> Dict[str, Any]:
    """Notify Discord of RSVP changes."""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_notify_discord_async(match_id))
            return result
        finally:
            loop.close()
    except Exception as e:
        logger.error(f"Error notifying Discord of RSVP change: {str(e)}", exc_info=True)
        raise self.retry(exc=e)

@celery_task(
    name='app.tasks.tasks_rsvp.cleanup_stale_rsvps',
    bind=True,
    queue='discord'
)
def cleanup_stale_rsvps(self, days_old: int = 30) -> Dict[str, Any]:
    """Clean up stale RSVPs."""
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days_old)

        with session_context():
            @db_operation
            def delete_old_rsvps() -> int:
                subquery = db.session.query(Match.id).filter(Match.date < datetime.utcnow())
                deleted_count = db.session.query(Availability).filter(
                    Availability.responded_at < cutoff_date,
                    Availability.match_id.in_(subquery)
                ).delete(synchronize_session='fetch')
                return deleted_count

            deleted_count = delete_old_rsvps()

        return {
            'success': True,
            'message': f'Cleaned up {deleted_count} stale RSVPs',
            'deleted_count': deleted_count
        }

    except Exception as e:
        logger.error(f"Error cleaning up stale RSVPs: {str(e)}", exc_info=True)
        raise self.retry(exc=e)

@celery_task(
    name='app.tasks.tasks_rsvp.monitor_rsvp_health',
    bind=True,
    queue='discord'
)
def monitor_rsvp_health(self) -> Dict[str, Any]:
    """Monitor overall RSVP system health."""
    try:
        with session_context():
            @query_operation
            def get_health_metrics() -> Dict[str, int]:
                total_availabilities = db.session.query(Availability).count()
                unsynced_count = db.session.query(Availability).filter(
                    (Availability.discord_sync_status != 'synced') |
                    (Availability.discord_sync_status.is_(None))
                ).count()
                failed_count = db.session.query(Availability).filter(
                    Availability.discord_sync_status == 'failed'
                ).count()

                return {
                    'total_availabilities': total_availabilities,
                    'unsynced_count': unsynced_count,
                    'failed_count': failed_count
                }

            metrics = get_health_metrics()

        return {
            'success': True,
            'message': 'Health check completed',
            'metrics': metrics,
            'health_status': 'healthy' if metrics['failed_count'] < 5 else 'degraded'
        }

    except Exception as e:
        logger.error(f"Error in health monitoring: {str(e)}", exc_info=True)
        raise self.retry(exc=e)