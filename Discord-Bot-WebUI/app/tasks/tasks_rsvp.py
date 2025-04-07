# app/tasks/tasks_rsvp.py

"""
RSVP Tasks Module

This module defines several Celery tasks to manage RSVP updates and notifications.
Tasks include updating RSVP responses, sending availability messages to Discord,
processing scheduled RSVP messages, notifying the frontend of RSVP changes,
updating Discord RSVP status, notifying Discord of RSVP changes, cleaning up stale RSVPs,
and monitoring overall RSVP system health.
"""

import logging
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from app.core import socketio
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
    """
    Update RSVP response for a given match and player.

    This task:
      - Retrieves the Player record and current Availability for the match.
      - Updates or creates the Availability record based on the new response.
      - If a discord_id is provided or can be found in the player record, schedules a task to update the Discord RSVP.
      - Schedules a task to notify the frontend of the RSVP change.
      - Always triggers notify_discord_of_rsvp_change_task to update the Discord embed.

    Args:
        session: Database session.
        match_id: ID of the match.
        player_id: ID of the player.
        new_response: The new RSVP response.
        discord_id: (Optional) Discord ID of the player.

    Returns:
        A dictionary summarizing the update result and timestamp.

    Raises:
        Retries the task on database or general errors.
    """
    try:
        logger.info("Starting RSVP update", extra={
            "match_id": match_id,
            "player_id": player_id,
            "new_response": new_response,
            "discord_id": discord_id
        })

        player = session.query(Player).get(player_id)
        if not player:
            logger.warning("Player not found", extra={"player_id": player_id})
            return {'success': False, 'message': "Player not found"}

        # Retrieve current availability record for the player and match.
        availability = session.query(Availability).filter_by(
            match_id=match_id,
            player_id=player_id
        ).first()

        old_response = availability.response if availability else None

        # Update or create the availability record.
        if availability:
            if new_response == 'no_response':
                session.delete(availability)
            else:
                availability.response = new_response
                availability.responded_at = datetime.utcnow()
        else:
            if new_response != 'no_response':
                availability = Availability(
                    match_id=match_id,
                    player_id=player_id,
                    response=new_response,
                    discord_id=discord_id,
                    responded_at=datetime.utcnow()
                )
                session.add(availability)

        # Get the player's discord_id if not provided
        if not discord_id and player.discord_id:
            discord_id = player.discord_id
            logger.debug(f"Using player's discord_id: {discord_id}")

        # Schedule Discord RSVP update if discord_id is available
        if discord_id:
            update_discord_rsvp_task.apply_async(kwargs={
                "match_id": match_id,
                "discord_id": discord_id,
                "new_response": new_response,
                "old_response": old_response
            }, countdown=5)
        else:
            logger.info(f"No Discord ID available for player {player_id}, skipping Discord reaction update")

        # Always notify Discord to update the embed with the latest RSVPs
        notify_discord_of_rsvp_change_task.apply_async(kwargs={
            "match_id": match_id
        }, countdown=3)

        # Notify frontend of the RSVP change.
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
    """
    Send an availability message to Discord.

    This task creates a new event loop to run the asynchronous helper that sends the message.
    It then updates the ScheduledMessage record with the result (e.g., SENT or FAILED).

    Args:
        session: Database session.
        scheduled_message_id: ID of the scheduled message to send.

    Returns:
        A dictionary with the result of the send operation.

    Raises:
        Retries the task on database or general errors.
    """
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_send_availability_message_async(scheduled_message_id))
            
            # Update the ScheduledMessage record based on the result.
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
    """
    Process and send all pending scheduled RSVP messages.

    This task queries for ScheduledMessage records that are pending and due to be sent.
    It processes messages in batches, queues each message for sending, and updates their
    status to 'QUEUED' or 'FAILED' accordingly.

    Args:
        session: Database session.

    Returns:
        A dictionary summarizing the processing outcome, including counts and details.

    Raises:
        Retries the task on database or general errors.
    """
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
        
        # Process messages in batches with rate limiting
        # This staggered approach ensures we don't overload the Discord API
        batch_size = 4  # Only process 4 messages in each batch
        stagger_seconds = 30  # Wait 30 seconds between batches
        
        logger.info(f"Processing {len(messages_data)} messages with rate limiting: "
                    f"batch size {batch_size}, {stagger_seconds}s between batches")
        
        for i in range(0, len(messages_data), batch_size):
            batch = messages_data[i:i + batch_size]
            batch_num = i // batch_size
            
            logger.info(f"Processing batch {batch_num + 1} of {(len(messages_data) + batch_size - 1) // batch_size}")
            
            for j, message_data in enumerate(batch):
                try:
                    if not message_data['match_id']:
                        logger.warning(f"Skipping message {message_data['id']} - no match associated")
                        continue

                    # Add a small delay (5 seconds) between messages in the same batch
                    individual_delay = j * 5
                    # Add larger delay (30 seconds) between batches
                    batch_delay = batch_num * stagger_seconds
                    total_delay = batch_delay + individual_delay
                    
                    # Queue each message for sending with appropriate delay
                    send_availability_message.apply_async(
                        kwargs={'scheduled_message_id': message_data['id']},
                        countdown=total_delay,
                        expires=3600
                    )
                    
                    logger.info(
                        f"Queued message {message_data['id']} (batch {batch_num + 1}, position {j + 1}) "
                        f"with {total_delay}s delay"
                    )

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
    """
    Notify the frontend of an RSVP change via WebSocket.

    This task emits a socket.io event with the RSVP update details to update the frontend in real time.

    Args:
        session: Database session.
        match_id: ID of the match.
        player_id: ID of the player.
        response: The new RSVP response.

    Returns:
        A dictionary indicating whether the notification was sent successfully.
    """
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


@celery_task(name='app.tasks.tasks_rsvp.update_discord_rsvp', max_retries=5, retry_backoff=True, queue='discord')
def update_discord_rsvp_task(self, session, match_id: int, discord_id: str, new_response: str, old_response: Optional[str] = None) -> Dict[str, Any]:
    """
    Update Discord RSVP status by communicating with the Discord API.

    This task runs an asynchronous helper to update the RSVP on Discord and then updates the corresponding
    Availability record with the sync status and timestamp.

    Args:
        session: Database session.
        match_id: ID of the match.
        discord_id: Discord user ID.
        new_response: New RSVP response.
        old_response: (Optional) Previous RSVP response.

    Returns:
        A dictionary with the update result and sync timestamp.

    Raises:
        Retries the task on SQLAlchemy or general errors.
    """
    try:
        # Ensure discord_id is a string
        if discord_id is not None and not isinstance(discord_id, str):
            discord_id = str(discord_id)
            logger.debug(f"Converted discord_id to string: {discord_id}")
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            data = {
                'match_id': match_id,
                'discord_id': discord_id,
                'new_response': new_response,
                'old_response': old_response
            }
            
            logger.info(f"Sending Discord RSVP update for match {match_id}, user {discord_id}, response {new_response}")
            result = loop.run_until_complete(_update_discord_rsvp_async(data))
            
            # Update availability record with sync status
            availability = session.query(Availability).filter_by(match_id=match_id, discord_id=discord_id).first()
            if availability:
                availability.discord_sync_status = 'synced' if result['success'] else 'failed'
                availability.last_sync_attempt = datetime.utcnow()
                availability.sync_error = None if result['success'] else result.get('message')
                logger.info(f"Updated sync status for availability record: {availability.discord_sync_status}")

            # If update failed and we're not on the last retry, try again
            if not result['success'] and self.request.retries < self.max_retries - 1:
                logger.warning(f"Discord RSVP update failed, will retry: {result.get('message', 'Unknown error')}")
                raise self.retry(countdown=min(2 ** self.request.retries * 10, 300))  # Exponential backoff with max 5 minutes

            # After updating reaction, also make sure embed is updated
            if not result['success']:
                logger.warning(f"Discord reaction update failed, will trigger embed update to ensure consistency")
                # Trigger embed update, but don't wait for it
                notify_discord_of_rsvp_change_task.delay(match_id)

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
    """
    Notify Discord of RSVP changes for a match.

    This task fetches a Match record, calls an asynchronous helper to notify Discord,
    and then updates the Match record with the notification status and timestamp.

    Args:
        session: Database session.
        match_id: ID of the match.

    Returns:
        A dictionary with the notification result and timestamp.

    Raises:
        Retries the task on SQLAlchemy or general errors.
    """
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
    """
    Clean up stale RSVP records.

    This task deletes Availability records for matches that occurred more than a specified
    number of days ago. It processes records in batches and returns details about the cleanup.

    Args:
        session: Database session.
        days_old: Age threshold (in days) for stale RSVPs (default: 30).

    Returns:
        A dictionary summarizing the cleanup process.
    
    Raises:
        Retries the task on SQLAlchemy or general errors.
    """
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days_old)
        
        # Get past matches via a subquery.
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


@celery_task(name='app.tasks.tasks_rsvp.schedule_weekly_match_availability', max_retries=3, queue='discord')
def schedule_weekly_match_availability(self, session) -> Dict[str, Any]:
    """
    Schedule availability messages for matches occurring in the next week on Sundays.
    
    This task runs every Monday to:
      - Find all Sunday matches for the upcoming week
      - Schedule RSVP messages for each match without existing scheduled messages
      - Set send time to 9 AM on Monday for maximum visibility
      - Create ScheduledMessage records in the database
      - Schedules messages with varying countdown times to prevent rate limiting
      
    Returns:
        A dictionary summarizing the number of messages scheduled and match count.
        
    Raises:
        Retries the task on errors with exponential backoff.
    """
    try:
        # Get today (should be Monday when scheduled) and next Sunday
        today = datetime.utcnow().date()
        days_until_sunday = (6 - today.weekday()) % 7  # 6 is Sunday's weekday number
        next_sunday = today + timedelta(days=days_until_sunday)
        
        logger.info(f"Scheduling for Sunday matches on {next_sunday}")
        
        # Find all matches scheduled for next Sunday
        sunday_matches = session.query(Match).options(
            joinedload(Match.scheduled_messages)
        ).filter(
            Match.date == next_sunday
        ).all()
        
        logger.info(f"Found {len(sunday_matches)} matches scheduled for next Sunday")
        
        # Prepare data for each match
        matches_data = [{
            'id': match.id,
            'date': match.date,
            'home_team': match.home_team.name if hasattr(match, 'home_team') else "Unknown",
            'away_team': match.away_team.name if hasattr(match, 'away_team') else "Unknown",
            'has_message': any(msg for msg in match.scheduled_messages)
        } for match in sunday_matches]
        
        # Schedule messages for matches without existing scheduled messages
        scheduled_count = 0
        
        # Batch size for sending to avoid overloading Discord API
        # This staggered approach ensures no more than 4 messages are sent per minute
        batch_size = 4
        stagger_minutes = 1
        
        for i, match_data in enumerate(matches_data):
            if not match_data['has_message']:
                # Calculate staggered send time
                # Base time is 9:00 AM, then stagger by batch
                batch_number = i // batch_size
                batch_minutes_offset = batch_number * stagger_minutes
                
                # Set initial timestamp as 9:00 AM
                base_send_time = datetime.combine(today, datetime.min.time()) + timedelta(hours=9)
                
                # Add the batch offset for staggered sending
                send_time = base_send_time + timedelta(minutes=batch_minutes_offset)
                
                scheduled_message = ScheduledMessage(
                    match_id=match_data['id'],
                    scheduled_send_time=send_time,
                    status='PENDING'
                )
                session.add(scheduled_message)
                scheduled_count += 1
                logger.info(
                    f"Scheduled availability message for match {match_data['id']} "
                    f"({match_data['home_team']} vs {match_data['away_team']}) "
                    f"at {send_time} (batch {batch_number+1})"
                )
        
        result = {
            "success": True,
            "message": f"Scheduled {scheduled_count} availability messages for Sunday matches",
            "scheduled_count": scheduled_count,
            "total_matches": len(matches_data),
            "sunday_date": next_sunday.isoformat(),
            "batches": (scheduled_count + batch_size - 1) // batch_size
        }
        logger.info(f"{result['message']} in {result['batches']} batches")
        return result
        
    except SQLAlchemyError as e:
        logger.error(f"Database error scheduling weekly match availability: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error scheduling weekly match availability: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)


@celery_task(name='app.tasks.tasks_rsvp.monitor_rsvp_health', max_retries=3, queue='discord')
def monitor_rsvp_health(self, session) -> Dict[str, Any]:
    """
    Monitor the overall health of the RSVP system.

    This task gathers various metrics from Availability and ScheduledMessage records,
    computes a health score based on unsynced and failed counts, and returns a health status.

    Args:
        session: Database session.

    Returns:
        A dictionary containing health metrics, score, status, and a timestamp.

    Raises:
        Retries the task on SQLAlchemy or general errors.
    """
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
        if total_avail > 0:
            unsynced_percentage = (unsynced_count / total_avail) * 100
            failed_percentage = (failed_count / total_avail) * 100

            if unsynced_percentage > 10:
                health_score -= 20
            if failed_percentage > 5:
                health_score -= 30
            if failed_messages_count > 10:
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