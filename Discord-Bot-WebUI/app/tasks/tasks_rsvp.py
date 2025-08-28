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
from app.models_ecs import EcsFcMatch, EcsFcAvailability
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import SQLAlchemyError
# Old async helpers replaced with sync Discord client

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
                session.add(availability)
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

        # Note: Database changes are automatically committed by @celery_task decorator
        # This ensures proper transaction handling without holding locks during external calls
        
        # Emit WebSocket event for real-time updates to mobile/web clients
        try:
            from app.sockets.rsvp import emit_rsvp_update
            
            # Get match to determine team_id
            match = session.query(Match).get(match_id)
            team_id = None
            if match and player:
                if player in match.home_team.players:
                    team_id = match.home_team_id
                elif player in match.away_team.players:
                    team_id = match.away_team_id
            
            emit_rsvp_update(
                match_id=match_id,
                player_id=player_id,
                availability=new_response,
                source='system',  # This is from a background task
                player_name=player.name if player else None,
                team_id=team_id
            )
        except Exception as e:
            logger.error(f"Error emitting WebSocket event: {str(e)}")
            # Don't fail the task if WebSocket emission fails

        # Schedule Discord RSVP update if discord_id is available
        if discord_id:
            # Run reaction update with higher priority (lower countdown)
            # This ensures reactions are updated before the embed
            update_discord_rsvp_task.apply_async(kwargs={
                "match_id": match_id,
                "discord_id": discord_id,
                "new_response": new_response,
                "old_response": old_response
            }, countdown=1, priority=8)  # Higher priority value
            
            # Also try to update reaction directly via separate task for immediate response
            direct_discord_update_task.apply_async(kwargs={
                "match_id": match_id,
                "discord_id": discord_id,
                "new_response": new_response,
                "old_response": old_response
            }, countdown=0, priority=9)  # Immediate execution with highest priority
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

        # Update attendance statistics cache when RSVP changes
        try:
            from app.attendance_service import handle_availability_change
            from app.models import Match, Season
            
            # Get the season for this match to update season-specific stats
            match = session.query(Match).get(match_id)
            season_id = None
            if match and hasattr(match, 'schedule') and match.schedule:
                season_id = match.schedule.season_id
            
            # Update attendance stats asynchronously to avoid blocking main RSVP flow
            handle_availability_change(player_id, season_id)
            logger.debug(f"Updated attendance stats for player {player_id}")
            
        except Exception as e:
            # Don't fail the main RSVP update if attendance stats update fails
            logger.warning(f"Failed to update attendance stats for player {player_id}: {e}")

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
        # Fetch the scheduled message and related data
        message = session.query(ScheduledMessage).get(scheduled_message_id)
        if not message:
            logger.error(f"ScheduledMessage with id {scheduled_message_id} not found")
            return {
                'success': False,
                'message': f"ScheduledMessage with id {scheduled_message_id} not found",
                'error_type': 'not_found'
            }
        
        # Construct the message_data dictionary
        message_data = {
            'scheduled_message_id': scheduled_message_id,
            'match_id': message.match_id,
            'home_channel_id': message.home_channel_id,
            'away_channel_id': message.away_channel_id
        }
        
        # If match exists, add match details
        if message.match:
            message_data.update({
                'match_date': message.match.date.strftime('%Y-%m-%d') if message.match.date else '',
                'match_time': message.match.time.strftime('%H:%M') if message.match.time else '',
                'home_team_name': message.match.home_team.name if message.match.home_team else 'Home Team',
                'away_team_name': message.match.away_team.name if message.match.away_team else 'Away Team'
            })
        else:
            # Use metadata if available for ECS FC or other message types
            metadata = message.message_metadata or {}
            message_data.update({
                'match_date': metadata.get('match_date', ''),
                'match_time': metadata.get('match_time', ''),
                'home_team_name': metadata.get('home_team_name', 'Home Team'),
                'away_team_name': metadata.get('away_team_name', 'Away Team')
            })
        
        # Use synchronous Discord client to send availability message
        from app.utils.sync_discord_client import get_sync_discord_client
        discord_client = get_sync_discord_client()
        result = discord_client.send_rsvp_availability_message(message_data)
        
        # Update the ScheduledMessage record based on the result
        message.last_send_attempt = datetime.utcnow()
        if result['success']:
            message.status = 'SENT'
            message.sent_at = datetime.utcnow()
            message.send_error = None
        else:
            message.status = 'FAILED'
            message.send_error = result.get('message')
        session.add(message)
        return result
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
                    # Check message type - handle ECS FC messages separately
                    msg = session.query(ScheduledMessage).get(message_data['id'])
                    if msg and msg.message_type == 'ecs_fc_rsvp':
                        # Handle ECS FC message
                        from app.tasks.tasks_ecs_fc_scheduled import send_ecs_fc_availability_message
                        
                        # Add delays for rate limiting
                        individual_delay = j * 5
                        batch_delay = batch_num * stagger_seconds
                        total_delay = batch_delay + individual_delay
                        
                        send_ecs_fc_availability_message.apply_async(
                            kwargs={'scheduled_message_id': message_data['id']},
                            countdown=total_delay,
                            expires=3600
                        )
                        
                        logger.info(
                            f"Queued ECS FC message {message_data['id']} (batch {batch_num + 1}, position {j + 1}) "
                            f"with {total_delay}s delay"
                        )
                    else:
                        # Handle regular pub league message
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
    
    Includes reaction state checks to:
    1. Verify if the reaction change is needed before making the API call
    2. Avoid redundant reaction updates if the current state matches the desired state
    3. Check Discord's current reaction state when possible to ensure idempotency

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
            
        # Check 1: Skip update if removing a reaction that doesn't exist
        if old_response is None and new_response == 'no_response':
            logger.info(f"Skipping Discord RSVP update - no previous reaction to remove")
            return {
                'success': True,
                'message': 'No reaction change needed',
                'skipped': True,
                'sync_timestamp': datetime.utcnow().isoformat()
            }
            
        # Check 2: Skip update if the new response is the same as the old response
        if old_response == new_response and old_response is not None:
            logger.info(f"Skipping Discord RSVP update - reaction already matches desired state")
            
            # Update availability record to show it's synced
            availability = session.query(Availability).filter_by(match_id=match_id, discord_id=discord_id).first()
            if availability:
                availability.discord_sync_status = 'synced'
                availability.last_sync_attempt = datetime.utcnow()
                availability.sync_error = None
                
            return {
                'success': True,
                'message': 'Reaction already in desired state',
                'skipped': True,
                'sync_timestamp': datetime.utcnow().isoformat()
            }
            
        # Check 3: Verify current reaction state from Discord if we can
        if not self.request.retries:  # Only on first attempt to avoid API spam
            try:
                # Get the message IDs for this match from scheduled messages
                match = session.query(Match).get(match_id)
                if match:
                    # Get the Discord message IDs from the scheduled message
                    scheduled_message = session.query(ScheduledMessage).filter_by(match_id=match_id).first()
                    if scheduled_message and (scheduled_message.home_message_id or scheduled_message.away_message_id):
                        # Try both home and away message IDs (user might be on either team)
                        message_ids_to_check = []
                        if scheduled_message.home_message_id:
                            message_ids_to_check.append(scheduled_message.home_message_id)
                        if scheduled_message.away_message_id:
                            message_ids_to_check.append(scheduled_message.away_message_id)
                        
                        # Check reactions on the first available message
                        import requests
                        for msg_id in message_ids_to_check:
                            try:
                                discord_api_url = "http://discord-bot:5001/api/get_user_reaction"
                                params = {
                                    "message_id": msg_id,
                                    "discord_id": discord_id
                                }
                                
                                response = requests.get(discord_api_url, params=params, timeout=3)
                                if response.status_code == 200:
                                    current_reaction = response.json().get('current_reaction')
                                    
                                    # If current reaction matches desired state, skip update
                                    if current_reaction == new_response:
                                        logger.info(f"Skipping Discord RSVP update - verified reaction already matches")
                                        
                                        # Update availability record to show it's synced
                                        availability = session.query(Availability).filter_by(match_id=match_id, discord_id=discord_id).first()
                                        if availability:
                                            availability.discord_sync_status = 'synced'
                                            availability.last_sync_attempt = datetime.utcnow()
                                            availability.sync_error = None
                                            
                                        return {
                                            'success': True,
                                            'message': 'Discord reaction already matches, skipped update',
                                            'sync_status': 'verified_skip',
                                            'sync_timestamp': datetime.utcnow().isoformat()
                                        }
                                    break  # Found a working message, don't check others
                                else:
                                    logger.debug(f"Failed to check reaction on message {msg_id}: {response.status_code}")
                            except Exception as e:
                                logger.debug(f"Error checking reaction on message {msg_id}: {e}")
                                continue  # Try next message
            except Exception as e:
                # Just log the error and continue - this is just an optimization
                logger.warning(f"Error checking current reaction state: {str(e)}")
        
        # If we get here, we need to update the reaction
        from app.utils.sync_discord_client import get_sync_discord_client
        data = {
            'match_id': match_id,
            'discord_id': discord_id,
            'new_response': new_response,
            'old_response': old_response
        }
        
        logger.info(f"Sending Discord RSVP update for match {match_id}, user {discord_id}, response {new_response}")
        discord_client = get_sync_discord_client()
        result = discord_client.update_rsvp_response(data)
        
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
    
    Includes idempotency checks to:
    1. Prevent redundant notifications within a short time window
    2. Track the last notification to avoid spamming Discord
    3. Compare current RSVP status with the last notification state

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
            
        # Idempotency check #1: Rate limiting - prevent notifications too close together
        if match.last_discord_notification:
            now = datetime.utcnow()
            time_since_last_notification = now - match.last_discord_notification
            
            # Don't send notifications more than once per 10 seconds unless previous one failed
            if time_since_last_notification.total_seconds() < 10 and match.notification_status == 'success':
                logger.info(f"Skipping notification for match {match_id} - last notification was {time_since_last_notification.total_seconds()} seconds ago")
                return {
                    'success': True,
                    'message': 'Notification skipped - rate limited',
                    'skipped': True,
                    'notification_timestamp': datetime.utcnow().isoformat(),
                    'match_id': match_id
                }
                
        # Idempotency check #2: RSVP state check - get current RSVPs
        # OPTIMIZATION: Only process RSVPs for recent matches
        from app.utils.rsvp_filters import filter_availability_discord_relevant, should_sync_rsvp_to_discord
        
        # Check if we should still care about this match's RSVPs
        match = session.query(Match).get(match_id)
        if match and not should_sync_rsvp_to_discord(match.date):
            logger.debug(f"Skipping Discord sync for old match {match_id} on {match.date}")
            return {
                'success': True,
                'message': f'Match on {match.date} is outside Discord care window',
                'skipped': True,
                'match_date': match.date.isoformat()
            }
        
        # Get RSVPs with Discord relevance filtering
        current_rsvps_query = session.query(Availability).filter_by(match_id=match_id)
        current_rsvps = filter_availability_discord_relevant(current_rsvps_query).all()
        
        # Generate a hash of the current RSVP state to compare with the last notification
        import hashlib
        current_state = "|".join(sorted([
            f"{rsvp.player_id}:{rsvp.response}:{rsvp.responded_at.isoformat() if rsvp.responded_at else 'None'}"
            for rsvp in current_rsvps
        ]))
        current_state_hash = hashlib.md5(current_state.encode()).hexdigest()
        
        # Compare with last notification state (if available)
        if match.last_notification_state_hash == current_state_hash and match.notification_status == 'success':
            logger.info(f"Skipping notification for match {match_id} - RSVP state unchanged")
            return {
                'success': True,
                'message': 'Notification skipped - no changes',
                'skipped': True,
                'notification_timestamp': datetime.utcnow().isoformat(),
                'match_id': match_id
            }

        # Proceed with notification since we've passed the idempotency checks
        from app.utils.sync_discord_client import get_sync_discord_client
        discord_client = get_sync_discord_client()
        result = discord_client.notify_rsvp_changes(match_id)
        
        # Update match with notification result
        match = session.query(Match).get(match_id)
        if match:
            match.last_discord_notification = datetime.utcnow()
            match.notification_status = 'success' if result['success'] else 'failed'
            match.last_notification_error = None if result['success'] else result.get('message')
            
            # If successful, update the state hash to prevent redundant notifications
            if result['success']:
                match.last_notification_state_hash = current_state_hash
                
        return {
            'success': result['success'],
            'message': result['message'],
            'notification_timestamp': datetime.utcnow().isoformat(),
            'match_id': match_id,
            'state_hash': current_state_hash
        }
            
    except SQLAlchemyError as e:
        logger.error(f"Database error notifying Discord of RSVP change: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error notifying Discord of RSVP change: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)


@celery_task(name='app.tasks.tasks_rsvp.cleanup_stale_rsvps', max_retries=3, queue='discord')
def cleanup_stale_rsvps(self, session, days_old: int = 30) -> Dict[str, Any]:
    """
    Clean up stale RSVP records using batched processing with frequent commits.

    This task deletes Availability records for matches that occurred more than a specified
    number of days ago. It processes records in small batches with frequent commits to 
    prevent long-running transactions and connection timeouts.

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
        logger.info(f"Starting cleanup of RSVPs older than {cutoff_date}")
        
        # OPTIMIZED: Use efficient bulk delete with BulkOperationHelper
        from app.utils.query_optimizer import BulkOperationHelper
        from sqlalchemy import and_, exists
        
        # Get a sample of records to be deleted for logging (before deletion)
        sample_rsvps = session.query(Availability).join(
            Match, Match.id == Availability.match_id
        ).filter(
            Availability.responded_at < cutoff_date,
            Match.date < datetime.utcnow()
        ).limit(100).all()
        
        deletion_details = [{
            'id': rsvp.id,
            'match_id': rsvp.match_id,
            'player_id': rsvp.player_id,
            'responded_at': rsvp.responded_at.isoformat() if rsvp.responded_at else None
        } for rsvp in sample_rsvps[:50]]  # Limit details to prevent memory issues
        
        # Use bulk delete operation - much more efficient than loading records
        delete_conditions = [
            Availability.responded_at < cutoff_date,
            # Use EXISTS subquery for match date condition
            exists().where(
                and_(
                    Match.id == Availability.match_id,
                    Match.date < datetime.utcnow()
                )
            )
        ]
        
        total_deleted = BulkOperationHelper.bulk_delete_with_conditions(
            session, Availability, delete_conditions, batch_size=1000
        )
        
        logger.info(f"Bulk deleted {total_deleted} stale RSVPs efficiently")

        result = {
            'success': True,
            'message': f'Cleaned up {total_deleted} stale RSVPs using bulk operations',
            'deleted_count': total_deleted,
            'cutoff_date': cutoff_date.isoformat(),
            'cleanup_timestamp': datetime.utcnow().isoformat(),
            'optimization_used': 'bulk_delete_operations',
            'deletion_details': deletion_details,
            'details_truncated': len(deletion_details) >= 50
        }

        logger.info(f"Cleanup completed: {result['message']}")
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
        
        # Prepare data for each match, handling special weeks
        matches_data = []
        special_week_matches = {}  # Track special weeks to avoid duplicates
        
        for match in sunday_matches:
            # Check if this is a special week (home_team_id == away_team_id)
            if match.home_team_id == match.away_team_id:
                # Special week - only create one entry per week type
                week_type = getattr(match, 'week_type', 'SPECIAL')
                week_key = f"{match.date}_{week_type}"
                
                if week_key not in special_week_matches:
                    # Determine display name for special week
                    if week_type.upper() == 'FUN':
                        display_name = 'Fun Week!'
                    elif week_type.upper() == 'TST':
                        display_name = 'Soccer Tournament!'
                    elif week_type.upper() == 'BYE':
                        # Skip BYE weeks - no RSVP needed
                        continue
                    elif week_type.upper() == 'BONUS':
                        display_name = 'Bonus Week!'
                    else:
                        display_name = 'Special Week!'
                    
                    special_week_matches[week_key] = {
                        'id': match.id,
                        'date': match.date,
                        'home_team': display_name,
                        'away_team': display_name,
                        'is_special_week': True,
                        'week_type': week_type,
                        'has_message': any(msg for msg in match.scheduled_messages)
                    }
                    matches_data.append(special_week_matches[week_key])
            else:
                # Regular match
                matches_data.append({
                    'id': match.id,
                    'date': match.date,
                    'home_team': match.home_team.name if hasattr(match, 'home_team') else "Unknown",
                    'away_team': match.away_team.name if hasattr(match, 'away_team') else "Unknown",
                    'is_special_week': False,
                    'has_message': any(msg for msg in match.scheduled_messages)
                })
        
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
                
                # Create appropriate log message based on match type
                if match_data.get('is_special_week', False):
                    logger.info(
                        f"Scheduled RSVP for special event {match_data['id']} "
                        f"({match_data['home_team']}) "
                        f"at {send_time} (batch {batch_number+1})"
                    )
                else:
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
        # Only check health for RSVPs from matches within the last week
        week_ago = datetime.utcnow().date() - timedelta(days=7)
        yesterday = datetime.utcnow() - timedelta(hours=24)
        
        # OPTIMIZED: Use single aggregated query with EXISTS instead of IN with subquery
        from sqlalchemy import func, case, exists
        
        # Single query to get all availability counts using efficient EXISTS pattern
        availability_stats = session.query(
            func.count(Availability.id).label('total_avail'),
            func.sum(case(
                *[(Availability.discord_sync_status != 'synced', 1),
                  (Availability.discord_sync_status.is_(None), 1)],
                else_=0
            )).label('unsynced_count'),
            func.sum(case(
                *[(Availability.discord_sync_status == 'failed', 1)],
                else_=0
            )).label('failed_count'),
            func.sum(case(
                *[(Availability.responded_at >= yesterday, 1)],
                else_=0
            )).label('recent_responses')
        ).join(
            Match, Match.id == Availability.match_id
        ).filter(
            Match.date >= week_ago
        ).first()
        
        total_avail = availability_stats.total_avail or 0
        unsynced_count = availability_stats.unsynced_count or 0
        failed_count = availability_stats.failed_count or 0
        recent_responses = availability_stats.recent_responses or 0
        
        # Separate efficient queries for ScheduledMessage counts
        pending_count = session.query(func.count(ScheduledMessage.id)).filter(
            ScheduledMessage.status == 'PENDING'
        ).scalar()
        failed_messages_count = session.query(func.count(ScheduledMessage.id)).filter(
            ScheduledMessage.status == 'FAILED'
        ).scalar()

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

        # If health is degraded or unhealthy, trigger a Discord sync to fix issues
        if health_status != 'healthy' and failed_count > 3:
            logger.warning(f"RSVP health degraded (score: {health_score}) for recent matches. Triggering Discord sync.")
            try:
                # Trigger a Discord sync to fix issues
                force_discord_rsvp_sync.apply_async(countdown=10)
            except Exception as e:
                logger.error(f"Failed to schedule Discord sync after detecting unhealthy state: {str(e)}")

        result = {
            'success': True,
            'message': 'Health check completed',
            'metrics': metrics,
            'health_score': health_score,
            'health_status': health_status,
            'timestamp': datetime.utcnow().isoformat()
        }

        logger.info("RSVP health check completed (last 7 days only)", extra=result)
        return result

    except SQLAlchemyError as e:
        logger.error(f"Database error in health monitoring: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error in health monitoring: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)


def _extract_failed_rsvp_records(session):
    """Extract data for failed RSVP records from database (Phase 1)."""
    week_ago = datetime.utcnow().date() - timedelta(days=7)
    
    try:
        # FIXED: Use proper JOIN and handle potential empty results
        failed_record_ids = session.query(Availability.id).join(
            Match, Match.id == Availability.match_id
        ).filter(
            Availability.discord_sync_status == 'failed',
            Match.date >= week_ago
        ).limit(200).all()  # Process max 200 at a time
        
        # Extract just the ID values from the result tuples
        failed_ids = [record_id for (record_id,) in failed_record_ids] if failed_record_ids else []
        
        return {
            'failed_record_ids': failed_ids,
            'total_found': len(failed_ids)
        }
    except Exception as e:
        logger.error(f"Error extracting failed RSVP records: {str(e)}", exc_info=True)
        # Return empty results on error to prevent crash
        return {
            'failed_record_ids': [],
            'total_found': 0
        }


async def _execute_discord_sync_async(data):
    """Execute Discord API call without holding database session (Phase 2)."""
    import aiohttp
    import asyncio
    
    logger.info("Starting Discord RSVP sync API call")
    
    discord_bot_url = "http://discord-bot:5001/api/force_rsvp_sync"
    
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as client:
            async with client.post(discord_bot_url) as response:
                if response.status == 200:
                    result = await response.json()
                    logger.info(f"Discord RSVP sync triggered successfully: {result}")
                    return {
                        'success': True,
                        'message': 'Discord RSVP sync triggered successfully',
                        'discord_response': result,
                        'api_call_success': True
                    }
                else:
                    error_text = await response.text()
                    error_msg = f"Failed to trigger Discord RSVP sync: {response.status} - {error_text}"
                    logger.error(error_msg)
                    return {
                        'success': False,
                        'message': error_msg,
                        'api_call_success': False
                    }
                    
    except asyncio.TimeoutError:
        error_msg = "Discord API call timed out after 15 seconds"
        logger.error(error_msg)
        return {
            'success': False,
            'message': error_msg,
            'api_call_success': False,
            'timeout': True
        }
    except Exception as e:
        error_msg = f"Error connecting to Discord bot for RSVP sync: {str(e)}"
        logger.error(error_msg)
        return {
            'success': False,
            'message': error_msg,
            'api_call_success': False,
            'connection_error': True
        }


def _update_failed_records_after_sync(session, extract_result, api_result):
    """Update failed records after API call (Phase 3)."""
    failed_record_ids = extract_result.get('failed_record_ids', [])
    
    if not failed_record_ids:
        return {'updated_records': 0}
    
    # Process records in smaller batches to avoid long-running transactions
    batch_size = 50
    total_updated = 0
    
    for i in range(0, len(failed_record_ids), batch_size):
        batch_ids = failed_record_ids[i:i + batch_size]
        
        # Update this batch of records
        batch_records = session.query(Availability).filter(
            Availability.id.in_(batch_ids)
        ).all()
        
        for record in batch_records:
            record.discord_sync_status = None  # Mark as needing sync
            record.last_sync_attempt = None
            record.sync_error = None
            total_updated += 1
        
        # Commit this batch immediately to release locks
        session.commit()
        logger.debug(f"Updated batch of {len(batch_records)} records for resync")
    
    logger.info(f"Marked {total_updated} failed records for resync (last 7 days only)")
    return {'updated_records': total_updated}


@celery_task(name='app.tasks.tasks_rsvp.force_discord_rsvp_sync', max_retries=3, queue='discord')
def force_discord_rsvp_sync(self, session) -> Dict[str, Any]:
    """
    Force a full synchronization between Discord and Flask RSVP data using three-phase pattern.
    
    Phase 1: Extract failed record IDs from database (quick, minimal lock time)
    Phase 2: Call Discord API without holding database connection (async, no locks)
    Phase 3: Update records in small batches (quick, frequent commits)
    
    This approach prevents long-running transactions and connection timeouts.
    
    Args:
        session: Database session (used only in phases 1 and 3).
        
    Returns:
        A dictionary with the result of the sync operation.
        
    Raises:
        Retries the task on SQLAlchemy or general errors.
    """
    try:
        logger.info("Starting forced Discord RSVP synchronization (batched)")
        
        # Phase 1: Extract failed record data (quick DB operation)
        extract_result = _extract_failed_rsvp_records(session)
        
        # Commit phase 1 data extraction to release locks
        session.commit()
        
        # Phase 2: Call Discord API without holding database session (synchronous)
        from app.utils.sync_discord_client import get_sync_discord_client
        discord_client = get_sync_discord_client()
        api_result = discord_client.force_rsvp_sync()
        
        # Phase 3: Update records in batches with frequent commits
        update_result = _update_failed_records_after_sync(session, extract_result, api_result)
        
        # Combine results
        final_result = {
            'success': api_result.get('success', False),
            'message': api_result.get('message', 'Unknown result'),
            'discord_response': api_result.get('discord_response'),
            'updated_records': update_result.get('updated_records', 0),
            'total_found': extract_result.get('total_found', 0),
            'api_call_success': api_result.get('api_call_success', False),
            'timestamp': datetime.utcnow().isoformat()
        }
        
        # Add specific error details if available
        if api_result.get('timeout'):
            final_result['timeout'] = True
        if api_result.get('connection_error'):
            final_result['connection_error'] = True
            
        logger.info(f"Force Discord RSVP sync completed: {final_result['message']}")
        return final_result
        
    except SQLAlchemyError as e:
        logger.error(f"Database error during Discord RSVP sync: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error during Discord RSVP sync: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)


async def _execute_direct_discord_update_async(data):
    """Execute direct Discord reaction update without holding database session."""
    import aiohttp
    import asyncio
    
    discord_api_url = "http://discord-bot:5001/api/update_user_reaction"
    reaction_data = {
        "match_id": str(data['match_id']),
        "discord_id": str(data['discord_id']),
        "new_response": data['new_response'],
        "old_response": data['old_response']
    }
    
    logger.info(f"Sending direct reaction update to Discord: {reaction_data}")
    
    try:
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as client:
            async with client.post(discord_api_url, json=reaction_data) as response:
                if response.status == 200:
                    logger.info(f"Successfully sent direct reaction update for user {data['discord_id']}")
                    return {
                        'success': True,
                        'message': 'Discord reaction updated successfully',
                        'discord_id': data['discord_id'],
                        'match_id': data['match_id']
                    }
                else:
                    error_text = await response.text()
                    logger.warning(f"Direct reaction update failed: {response.status} - {error_text}")
                    return {
                        'success': False,
                        'message': f'Discord API returned {response.status}',
                        'discord_id': data['discord_id'],
                        'match_id': data['match_id'],
                        'api_error': error_text
                    }
                    
    except asyncio.TimeoutError:
        logger.warning(f"Direct reaction update timed out after 8 seconds for user {data['discord_id']}")
        return {
            'success': False,
            'message': 'Discord API request timed out',
            'discord_id': data['discord_id'],
            'match_id': data['match_id'],
            'timeout': True
        }
    except Exception as e:
        logger.warning(f"Could not send direct reaction update: {str(e)}")
        return {
            'success': False,
            'message': f'Network error: {str(e)}',
            'discord_id': data['discord_id'],
            'match_id': data['match_id'],
            'connection_error': True
        }


@celery_task(name='app.tasks.tasks_rsvp.direct_discord_update_task', max_retries=3, queue='discord')
def direct_discord_update_task(self, session, match_id: str, discord_id: str, new_response: str, old_response: str) -> Dict[str, Any]:
    """
    Directly update Discord reaction via async API call without holding database session.
    
    This task provides immediate Discord reaction updates using async HTTP calls
    to prevent blocking the database session during network requests.
    
    Args:
        session: Database session (not used for this task)
        match_id: ID of the match
        discord_id: Discord ID of the user
        new_response: New RSVP response
        old_response: Previous RSVP response
    
    Returns:
        Dictionary with success status and message
    """
    try:
        # Prepare data for async API call - no database session needed
        data = {
            'match_id': match_id,
            'discord_id': discord_id,
            'new_response': new_response,
            'old_response': old_response
        }
        
        # Execute Discord API call without holding database session (synchronous)
        from app.utils.sync_discord_client import get_sync_discord_client
        discord_client = get_sync_discord_client()
        result = discord_client.update_discord_reactions(data)
        
        # Retry on timeout or connection errors (but not on API errors)
        if not result.get('success'):
            if result.get('timeout') or result.get('connection_error'):
                if self.request.retries < self.max_retries - 1:
                    retry_delay = min(2 ** self.request.retries * 2, 30)  # Exponential backoff, max 30s
                    logger.info(f"Retrying direct Discord update after {retry_delay}s due to: {result['message']}")
                    raise self.retry(countdown=retry_delay)
        
        return result
        
    except Exception as e:
        logger.error(f"Unexpected error in direct Discord update: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=5)