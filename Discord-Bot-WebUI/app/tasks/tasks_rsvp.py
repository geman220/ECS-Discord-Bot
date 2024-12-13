# app/tasks/tasks_rsvp.py

import logging
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from app.core import socketio, celery
from app.decorators import celery_task
from app.models import Match, Availability, Player, ScheduledMessage
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import SQLAlchemyError
from app.tasks.tasks_rsvp_helpers import (
    _send_availability_message_async,
    _update_discord_rsvp_async,
    _notify_discord_async
)

logger = logging.getLogger(__name__)

@celery_task(name='app.tasks.tasks_rsvp.update_rsvp', max_retries=3, queue='discord')
def update_rsvp(self, session, match_id: int, player_id: int, new_response: str,
                discord_id: Optional[str] = None) -> Dict[str, Any]:
    """Update RSVP status with detailed logging."""
    try:
        logger.info("Starting RSVP update", extra={
            "match_id": match_id,
            "player_id": player_id,
            "new_response": new_response,
            "discord_id": discord_id
        })

        # Fetch match and player
        match = session.query(Match).get(match_id)
        player = session.query(Player).get(player_id)

        if not match:
            logger.warning("Match not found", extra={"match_id": match_id})
            return {'success': False, 'message': "Match not found", 'error_type': 'match_not_found'}

        if not player:
            logger.warning("Player not found", extra={"player_id": player_id})
            return {'success': False, 'message': "Player not found", 'error_type': 'player_not_found'}

        availability = session.query(Availability).filter_by(match_id=match_id, player_id=player_id).first()
        old_response = availability.response if availability else None
        logger.info("Current state retrieved", extra={
            "match_id": match_id,
            "player_id": player_id,
            "has_existing_rsvp": availability is not None,
            "old_response": old_response
        })

        # Update or delete availability
        if availability:
            if new_response == 'no_response':
                logger.info("Deleting existing RSVP", extra={"availability_id": availability.id})
                session.delete(availability)
            else:
                logger.info("Updating existing RSVP", extra={"availability_id": availability.id, "new_response": new_response})
                availability.response = new_response
                availability.responded_at = datetime.utcnow()
                availability.last_update = datetime.utcnow()
                availability.update_count = (availability.update_count or 0) + 1
        else:
            if new_response != 'no_response':
                logger.info("Creating new RSVP entry", extra={"match_id": match_id, "player_id": player_id, "new_response": new_response})
                new_availability = Availability(
                    match_id=match_id,
                    player_id=player_id,
                    response=new_response,
                    discord_id=discord_id,
                    responded_at=datetime.utcnow(),
                    last_update=datetime.utcnow(),
                    update_count=1
                )
                session.add(new_availability)

        # Update player's Discord ID if provided
        if discord_id and player.discord_id != discord_id:
            logger.info("Updating player discord_id", extra={"player_id": player_id, "old_discord_id": player.discord_id, "new_discord_id": discord_id})
            player.discord_id = discord_id
            player.discord_id_updated_at = datetime.utcnow()

        # Outside of DB transaction logic: queue notifications
        if discord_id:
            logger.info("Queueing Discord RSVP update", extra={"match_id": match_id, "discord_id": discord_id, "new_response": new_response, "old_response": old_response})
            update_discord_rsvp_task.apply_async(kwargs={
                "match_id": match_id,
                "discord_id": discord_id,
                "new_response": new_response,
                "old_response": old_response
            }, countdown=5)

        logger.info("Queueing frontend notification", extra={"match_id": match_id, "player_id": player_id, "new_response": new_response})
        notify_frontend_of_rsvp_change_task.apply_async(kwargs={
            "match_id": match_id,
            "player_id": player_id,
            "response": new_response
        }, countdown=2)

        return {
            'success': True,
            'message': "RSVP updated successfully",
            'match_id': match_id,
            'player_id': player_id,
            'new_response': new_response,
            'timestamp': datetime.utcnow().isoformat()
        }

    except SQLAlchemyError as e:
        logger.error(f"Database error updating RSVP: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error updating RSVP: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)

@celery_task(name='app.tasks.tasks_rsvp.send_availability_message', max_retries=3, retry_backoff=True, queue='discord')
def send_availability_message(self, session, scheduled_message_id: int) -> Dict[str, Any]:
    """Send availability message to Discord."""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_send_availability_message_async(scheduled_message_id))
            
            message = session.query(ScheduledMessage).get(scheduled_message_id)
            if message:
                message.last_send_attempt = datetime.utcnow()
                if result['success']:
                    message.status = 'SENT'
                    message.sent_at = datetime.utcnow()
                    message.send_error = None
                else:
                    message.status = 'FAILED'
                    message.send_error = result.get('message')

            return result
        finally:
            loop.close()
    except SQLAlchemyError as e:
        logger.error(f"Database error sending availability message: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error sending availability message: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)

@celery_task(name='app.tasks.tasks_rsvp.process_scheduled_messages', max_retries=3, queue='discord')
def process_scheduled_messages(self, session) -> Dict[str, Any]:
    """Process and send all pending scheduled messages."""
    try:
        now = datetime.utcnow()
        messages = session.query(ScheduledMessage).filter(
            ScheduledMessage.status == 'PENDING',
            ScheduledMessage.scheduled_send_time <= now
        ).options(joinedload(ScheduledMessage.match)).all()

        messages_data = [{
            'id': msg.id,
            'match_id': msg.match_id if msg.match else None,
            'scheduled_time': msg.scheduled_send_time
        } for msg in messages]

        processed_count = 0
        failed_count = 0
        results = []
        
        batch_size = 50
        for i in range(0, len(messages_data), batch_size):
            batch = messages_data[i:i + batch_size]
            
            for message_data in batch:
                try:
                    if not message_data['match_id']:
                        logger.warning(f"Skipping message {message_data['id']} - no match associated")
                        continue

                    send_availability_message.apply_async(
                        kwargs={'scheduled_message_id': message_data['id']},
                        countdown=5 * (i // batch_size),
                        expires=3600
                    )

                    # Update message status to QUEUED
                    msg = session.query(ScheduledMessage).get(message_data['id'])
                    if msg:
                        msg.status = 'QUEUED'
                        msg.queued_at = datetime.utcnow()

                    processed_count += 1
                    results.append({
                        'message_id': message_data['id'],
                        'match_id': message_data['match_id'],
                        'status': 'queued',
                        'queued_at': datetime.utcnow().isoformat()
                    })
                    
                except Exception as e:
                    logger.error(f"Error processing message {message_data['id']}: {str(e)}", exc_info=True)
                    msg = session.query(ScheduledMessage).get(message_data['id'])
                    if msg:
                        msg.status = 'FAILED'
                        msg.last_error = str(e)
                        msg.error_timestamp = datetime.utcnow()

                    failed_count += 1
                    results.append({
                        'message_id': message_data['id'],
                        'match_id': message_data['match_id'],
                        'status': 'failed',
                        'error': str(e)
                    })

        return {
            'success': True,
            'message': f"Processed {len(messages_data)} scheduled messages",
            'processed_count': processed_count,
            'failed_count': failed_count,
            'results': results,
            'processed_at': datetime.utcnow().isoformat()
        }

    except SQLAlchemyError as e:
        logger.error(f"Database error processing scheduled messages: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error processing scheduled messages: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)

@celery_task(name='app.tasks.tasks_rsvp.notify_frontend_of_rsvp_change', max_retries=2, queue='discord')
def notify_frontend_of_rsvp_change_task(self, session, match_id: int, player_id: int, response: str) -> Dict[str, Any]:
    """Notify frontend of RSVP changes via WebSocket."""
    try:
        notification_data = {
            'match_id': match_id,
            'player_id': player_id,
            'response': response,
            'timestamp': datetime.utcnow().isoformat()
        }

        socketio.emit('rsvp_update', notification_data, namespace='/availability')
        
        logger.info("Frontend notified of RSVP change", extra=notification_data)
        
        return {
            'success': True,
            'message': 'Frontend notification sent successfully',
            'notification': notification_data
        }
        
    except Exception as e:
        logger.error(f"Error notifying frontend: {str(e)}", exc_info=True)
        return {
            'success': False,
            'message': str(e),
            'error_type': 'socket_error'
        }

@celery_task(name='app.tasks.tasks_rsvp.update_discord_rsvp', max_retries=3, retry_backoff=True, queue='discord')
def update_discord_rsvp_task(self, session, match_id: int, discord_id: str, new_response: str, old_response: Optional[str] = None) -> Dict[str, Any]:
    """Update Discord RSVP status."""
    try:
        required_fields = ['match_id', 'discord_id', 'new_response']
        # Already have all arguments as separate parameters

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            data = {
                'match_id': match_id,
                'discord_id': discord_id,
                'new_response': new_response,
                'old_response': old_response
            }
            result = loop.run_until_complete(_update_discord_rsvp_async(data))
            
            availability = session.query(Availability).filter_by(match_id=match_id, discord_id=discord_id).first()
            if availability:
                availability.discord_sync_status = 'synced' if result['success'] else 'failed'
                availability.last_sync_attempt = datetime.utcnow()
                availability.sync_error = None if result['success'] else result.get('message')

            return {
                'success': result['success'],
                'message': result['message'],
                'sync_timestamp': datetime.utcnow().isoformat(),
                'data': data
            }
        finally:
            loop.close()
            
    except SQLAlchemyError as e:
        logger.error(f"Database error updating Discord RSVP: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error updating Discord RSVP: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)

@celery_task(name='app.tasks.tasks_rsvp.notify_discord_of_rsvp_change', max_retries=3, retry_backoff=True, queue='discord')
def notify_discord_of_rsvp_change_task(self, session, match_id: int) -> Dict[str, Any]:
    """Notify Discord of RSVP changes."""
    try:
        match = session.query(Match).get(match_id)
        if not match:
            return {'success': False, 'message': f'Match {match_id} not found'}

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_notify_discord_async(match_id))
            
            match = session.query(Match).get(match_id)
            if match:
                match.last_discord_notification = datetime.utcnow()
                match.notification_status = 'success' if result['success'] else 'failed'
                match.last_notification_error = None if result['success'] else result.get('message')

            return {
                'success': result['success'],
                'message': result['message'],
                'notification_timestamp': datetime.utcnow().isoformat(),
                'match_id': match_id
            }
        finally:
            loop.close()
            
    except SQLAlchemyError as e:
        logger.error(f"Database error notifying Discord of RSVP change: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error notifying Discord of RSVP change: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)

@celery_task(name='app.tasks.tasks_rsvp.cleanup_stale_rsvps', max_retries=3, queue='discord')
def cleanup_stale_rsvps(self, session, days_old: int = 30) -> Dict[str, Any]:
    """Clean up stale RSVPs."""
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days_old)
        
        # Get past matches
        past_match_ids = session.query(Match.id).filter(Match.date < datetime.utcnow()).subquery()

        total_deleted = 0
        deletion_details = []
        batch_size = 1000

        while True:
            stale_rsvps = session.query(Availability).filter(
                Availability.responded_at < cutoff_date,
                Availability.match_id.in_(past_match_ids)
            ).limit(batch_size).all()

            if not stale_rsvps:
                break

            batch_details = [{
                'id': rsvp.id,
                'match_id': rsvp.match_id,
                'player_id': rsvp.player_id,
                'responded_at': rsvp.responded_at.isoformat() if rsvp.responded_at else None
            } for rsvp in stale_rsvps]
            deletion_details.extend(batch_details)

            deleted_count = session.query(Availability).filter(
                Availability.id.in_([rsvp.id for rsvp in stale_rsvps])
            ).delete(synchronize_session=False)
            total_deleted += deleted_count

        result = {
            'success': True,
            'message': f'Cleaned up {total_deleted} stale RSVPs',
            'deleted_count': total_deleted,
            'cutoff_date': cutoff_date.isoformat(),
            'cleanup_timestamp': datetime.utcnow().isoformat(),
            'deletion_details': deletion_details
        }

        logger.info("Cleanup completed", extra=result)
        return result

    except SQLAlchemyError as e:
        logger.error(f"Database error cleaning up stale RSVPs: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error cleaning up stale RSVPs: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)

@celery_task(name='app.tasks.tasks_rsvp.monitor_rsvp_health', max_retries=3, queue='discord')
def monitor_rsvp_health(self, session) -> Dict[str, Any]:
    """Monitor overall RSVP system health."""
    try:
        total_avail = session.query(Availability).count()
        unsynced_count = session.query(Availability).filter(
            (Availability.discord_sync_status != 'synced') |
            (Availability.discord_sync_status.is_(None))
        ).count()
        failed_count = session.query(Availability).filter(
            Availability.discord_sync_status == 'failed'
        ).count()
        pending_count = session.query(ScheduledMessage).filter(
            ScheduledMessage.status == 'PENDING'
        ).count()
        failed_messages_count = session.query(ScheduledMessage).filter(
            ScheduledMessage.status == 'FAILED'
        ).count()
        recent_responses = session.query(Availability).filter(
            Availability.responded_at >= datetime.utcnow() - timedelta(hours=24)
        ).count()

        metrics = {
            'total_availabilities': total_avail,
            'unsynced_count': unsynced_count,
            'failed_count': failed_count,
            'pending_count': pending_count,
            'failed_messages_count': failed_messages_count,
            'recent_responses': recent_responses
        }

        health_score = 100
        if metrics['total_availabilities'] > 0:
            unsynced_percentage = (unsynced_count / metrics['total_availabilities']) * 100
            failed_percentage = (failed_count / metrics['total_availabilities']) * 100

            if unsynced_percentage > 10:
                health_score -= 20
            if failed_percentage > 5:
                health_score -= 30
            if metrics['failed_messages_count'] > 10:
                health_score -= 20

        health_status = 'healthy' if health_score >= 80 else 'degraded' if health_score >= 50 else 'unhealthy'

        result = {
            'success': True,
            'message': 'Health check completed',
            'metrics': metrics,
            'health_score': health_score,
            'health_status': health_status,
            'timestamp': datetime.utcnow().isoformat()
        }

        logger.info("RSVP health check completed", extra=result)
        return result

    except SQLAlchemyError as e:
        logger.error(f"Database error in health monitoring: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error in health monitoring: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)
