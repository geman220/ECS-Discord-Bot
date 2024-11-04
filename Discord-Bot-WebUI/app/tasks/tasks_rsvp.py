from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple, List
import logging
import aiohttp
import asyncio

from app.extensions import db, socketio
from app.decorators import celery_task, async_task, db_operation, query_operation, session_context
from app.models import Match, ScheduledMessage, Availability, Player
from app.discord_utils import (
    process_single_player_update,
    get_expected_roles,
    fetch_user_roles,
    process_role_updates
)

logger = logging.getLogger(__name__)

@celery_task(name='app.tasks.tasks_rsvp.update_rsvp')
def update_rsvp(
    self,
    match_id: int,
    player_id: int,
    new_response: str,
    discord_id: Optional[str] = None
) -> Tuple[bool, str]:
    """Update RSVP status and handle notifications."""
    try:
        @query_operation
        def get_match_and_player() -> Tuple[Optional[Match], Optional[Player]]:
            return (
                Match.query.get(match_id),
                Player.query.get(player_id)
            )

        match, player = get_match_and_player()
        if not match or not player:
            return False, "Match or Player not found"

        @query_operation
        def get_availability() -> Optional[Availability]:
            return Availability.query.filter_by(
                match_id=match_id,
                player_id=player_id
            ).first()

        availability = get_availability()
        old_response = availability.response if availability else None

        @db_operation
        def update_availability_and_player():
            if availability:
                if new_response == 'no_response':
                    db.session.delete(availability)
                else:
                    availability.response = new_response
                    availability.responded_at = datetime.utcnow()
            else:
                if new_response != 'no_response':
                    new_availability = Availability(
                        match_id=match_id,
                        player_id=player_id,
                        response=new_response,
                        discord_id=discord_id,
                        responded_at=datetime.utcnow()
                    )
                    db.session.add(new_availability)

            if discord_id:
                player = Player.query.get(player_id)
                if player:
                    player.discord_id = discord_id

        update_availability_and_player()

        # Trigger notifications after successful update
        if player.discord_id:
            update_discord_rsvp_task.delay({
                "match_id": match_id,
                "discord_id": player.discord_id,
                "new_response": new_response,
                "old_response": old_response
            })

        notify_frontend_of_rsvp_change_task.delay(
            match_id,
            player_id,
            new_response
        )

        return True, "RSVP updated successfully"

    except Exception as e:
        logger.error(f"Error updating RSVP: {str(e)}", exc_info=True)
        raise

@async_task(name='app.tasks.tasks_rsvp.send_availability_message')
async def send_availability_message(self, scheduled_message_id: int) -> str:
    """Send availability message to Discord."""
    try:
        @query_operation
        def get_message_data() -> Optional[Dict[str, Any]]:
            message = ScheduledMessage.query.get(scheduled_message_id)
            if not message:
                return None
                
            match = message.match
            return {
                'scheduled_message': message,
                'match': match,
                'home_channel_id': match.home_team.discord_channel_id,
                'away_channel_id': match.away_team.discord_channel_id,
                'payload': {
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
            }

        message_data = get_message_data()
        if not message_data:
            return f"Scheduled message {scheduled_message_id} not found"

        result = await post_availability_message(message_data['payload'])
        if result:
            home_message_id, away_message_id = result
            
            @db_operation
            def update_message_status():
                message = ScheduledMessage.query.get(scheduled_message_id)
                if message:
                    message.home_discord_message_id = home_message_id
                    message.away_discord_message_id = away_message_id
                    message.status = 'SENT'

            update_message_status()
            return "Availability message sent successfully"
        
        @db_operation
        def mark_message_failed():
            message = ScheduledMessage.query.get(scheduled_message_id)
            if message:
                message.status = 'FAILED'

        mark_message_failed()
        return "Failed to send availability message"

    except Exception as e:
        logger.error(f"Error sending availability message {scheduled_message_id}: {str(e)}", exc_info=True)
        raise

@celery_task(name='app.tasks.tasks_rsvp.process_scheduled_messages')
def process_scheduled_messages(self) -> str:
    """Process and send all pending scheduled messages."""
    try:
        @query_operation
        def get_pending_messages() -> List[ScheduledMessage]:
            now = datetime.utcnow()
            return ScheduledMessage.query.filter(
                ScheduledMessage.status == 'PENDING',
                ScheduledMessage.scheduled_send_time <= now
            ).all()

        messages = get_pending_messages()

        for message in messages:
            try:
                send_availability_message.delay(message.id)
                
                @db_operation
                def update_message_status(message_id: int):
                    message = ScheduledMessage.query.get(message_id)
                    if message:
                        message.status = 'QUEUED'

                update_message_status(message.id)
            except Exception as e:
                logger.error(f"Error queueing message {message.id}: {str(e)}", exc_info=True)
                
                @db_operation
                def mark_message_failed(message_id: int):
                    message = ScheduledMessage.query.get(message_id)
                    if message:
                        message.status = 'FAILED'

                mark_message_failed(message.id)

        return f"Processed {len(messages)} scheduled messages"

    except Exception as e:
        logger.error(f"Error processing scheduled messages: {str(e)}", exc_info=True)
        raise

@celery_task(name='app.tasks.tasks_rsvp.notify_frontend_of_rsvp_change')
def notify_frontend_of_rsvp_change_task(self, match_id: int, player_id: int, response: str) -> bool:
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
        return True
    except Exception as e:
        logger.error(f"Error notifying frontend: {str(e)}", exc_info=True)
        raise

@async_task(name='app.tasks.tasks_rsvp.update_discord_rsvp')
async def update_discord_rsvp_task(self, data: Dict[str, Any]) -> Dict[str, Any]:
    """Update Discord RSVP status."""
    try:
        if not all(key in data for key in ['match_id', 'discord_id']):
            raise ValueError("Missing required fields: match_id and discord_id are required")

        request_data = {
            "match_id": str(data.get("match_id")),
            "discord_id": str(data.get("discord_id")),
            "new_response": data.get("new_response"),
            "old_response": data.get("old_response")
        }

        result = await update_user_reaction(request_data)
        
        if result['status'] == 'success':
            @db_operation
            def update_rsvp_status():
                availability = Availability.query.filter_by(
                    match_id=int(data['match_id']),
                    discord_id=data['discord_id']
                ).first()
                if availability:
                    availability.discord_sync_status = 'synced'
                    availability.last_sync_time = datetime.utcnow()

            update_rsvp_status()

        return result

    except Exception as e:
        logger.error(f"Error updating Discord RSVP: {str(e)}", exc_info=True)
        raise

@async_task(name='app.tasks.tasks_rsvp.notify_discord_of_rsvp_change')
async def notify_discord_of_rsvp_change_task(self, match_id: int) -> bool:
    """Notify Discord of RSVP changes."""
    try:
        success = await update_availability_embed(match_id)
        
        if success:
            @db_operation
            def update_notification_status():
                match = Match.query.get(match_id)
                if match:
                    match.last_discord_notification = datetime.utcnow()

            update_notification_status()
            
        return success
    except Exception as e:
        logger.error(f"Error notifying Discord of RSVP change for match {match_id}: {str(e)}", exc_info=True)
        raise

@celery_task(name='app.tasks.tasks_rsvp.process_discord_role_updates')
def process_discord_role_updates(self) -> bool:
    """Process Discord role updates for all marked players."""
    try:
        @query_operation
        def get_players_needing_updates() -> List[Player]:
            return Player.query.filter(
                (Player.discord_needs_update == True) |
                (Player.discord_last_verified == None) |
                (Player.discord_last_verified < datetime.utcnow() - timedelta(days=90))
            ).all()

        players = get_players_needing_updates()

        if not players:
            logger.info("No players need Discord role updates")
            return True

        logger.info(f"Processing Discord role updates for {len(players)} players")
        asyncio.run(process_role_updates(players))

        @db_operation
        def update_player_statuses():
            for player in players:
                db_player = Player.query.get(player.id)
                if db_player:
                    db_player.discord_needs_update = False
                    db_player.discord_last_verified = datetime.utcnow()

        update_player_statuses()
        return True

    except Exception as e:
        logger.error(f"Error processing Discord role updates: {str(e)}", exc_info=True)
        raise

# Enhanced helper functions with proper error handling and logging
async def post_availability_message(payload: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """Post availability message to Discord bot."""
    url = "http://discord-bot:5001/api/post_availability"
    logger.debug(f"Sending availability message with payload: {payload}")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    return result.get('home_message_id'), result.get('away_message_id')
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to post availability. Status: {response.status}, Error: {error_text}")
                    return None
    except Exception as e:
        logger.error(f"Error posting availability message: {str(e)}")
        return None

async def update_user_reaction(request_data: Dict[str, Any]) -> Dict[str, Any]:
    """Update user reaction in Discord."""
    bot_api_url = "http://discord-bot:5001/api/update_user_reaction"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(bot_api_url, json=request_data) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Failed to update Discord RSVP. Status: {response.status}, Response: {error_text}")
                    return {
                        "status": "error",
                        "message": f"Failed to update Discord RSVP: {error_text}"
                    }
                
                logger.info("Discord RSVP update successful")
                return {
                    "status": "success",
                    "message": "Discord RSVP updated successfully"
                }
    except Exception as e:
        error_msg = f"Error updating Discord RSVP: {str(e)}"
        logger.error(error_msg)
        return {
            "status": "error",
            "message": error_msg
        }

async def update_availability_embed(match_id: int) -> bool:
    """Update availability embed in Discord."""
    bot_api_url = f"http://discord-bot:5001/api/update_availability_embed/{match_id}"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(bot_api_url, timeout=10) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Failed to update Discord embed. Status: {response.status}, Response: {error_text}")
                    return False
                logger.info(f"Successfully updated Discord embed for match {match_id}")
                return True
    except Exception as e:
        logger.error(f"Error updating Discord embed for match {match_id}: {str(e)}")
        return False

@celery_task(name='app.tasks.tasks_rsvp.cleanup_stale_rsvps')
def cleanup_stale_rsvps(self, days_old: int = 30) -> Dict[str, Any]:
    """Clean up stale RSVPs."""
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days_old)
        
        @db_operation
        def delete_old_rsvps() -> int:
            return Availability.query.filter(
                Availability.responded_at < cutoff_date,
                Match.date < datetime.utcnow()
            ).join(Match).delete(synchronize_session='fetch')

        deleted_count = delete_old_rsvps()
        
        return {
            'success': True,
            'message': f'Cleaned up {deleted_count} stale RSVPs',
            'deleted_count': deleted_count
        }

    except Exception as e:
        logger.error(f"Error cleaning up stale RSVPs: {str(e)}", exc_info=True)
        return {
            'success': False,
            'message': str(e)
        }

@celery_task(name='app.tasks.tasks_rsvp.cleanup_orphaned_availabilities')
def cleanup_orphaned_availabilities(self) -> Dict[str, Any]:
    """Clean up availability records that don't have associated matches."""
    try:
        @db_operation
        def delete_orphaned_records() -> int:
            subquery = db.session.query(Match.id)
            return Availability.query.filter(
                ~Availability.match_id.in_(subquery)
            ).delete(synchronize_session='fetch')

        deleted_count = delete_orphaned_records()
        
        return {
            'success': True,
            'message': f'Cleaned up {deleted_count} orphaned availability records',
            'deleted_count': deleted_count
        }

    except Exception as e:
        logger.error(f"Error cleaning up orphaned availabilities: {str(e)}", exc_info=True)
        return {
            'success': False,
            'message': str(e)
        }

@celery_task(name='app.tasks.tasks_rsvp.sync_discord_rsvps')
def sync_discord_rsvps(self) -> Dict[str, Any]:
    """Synchronize RSVPs with Discord for any out-of-sync records."""
    try:
        @query_operation
        def get_unsynced_availabilities() -> List[Availability]:
            return Availability.query.filter(
                (Availability.discord_sync_status != 'synced') |
                (Availability.discord_sync_status.is_(None))
            ).all()

        unsynced = get_unsynced_availabilities()
        synced_count = 0
        failed_count = 0

        for availability in unsynced:
            try:
                update_discord_rsvp_task.delay({
                    "match_id": availability.match_id,
                    "discord_id": availability.discord_id,
                    "new_response": availability.response,
                    "old_response": None
                })
                synced_count += 1
            except Exception as e:
                logger.error(f"Error syncing availability {availability.id}: {str(e)}")
                failed_count += 1

        return {
            'success': True,
            'message': f'Synchronized {synced_count} RSVPs, {failed_count} failed',
            'synced_count': synced_count,
            'failed_count': failed_count
        }

    except Exception as e:
        logger.error(f"Error in RSVP sync: {str(e)}", exc_info=True)
        return {
            'success': False,
            'message': str(e)
        }

@celery_task(name='app.tasks.tasks_rsvp.retry_failed_rsvp_updates')
def retry_failed_rsvp_updates(self) -> Dict[str, Any]:
    """Retry failed RSVP updates."""
    try:
        @query_operation
        def get_failed_updates() -> List[Availability]:
            return Availability.query.filter(
                Availability.discord_sync_status == 'failed'
            ).all()

        failed_updates = get_failed_updates()
        retried_count = 0
        success_count = 0

        for availability in failed_updates:
            try:
                result = update_discord_rsvp_task.delay({
                    "match_id": availability.match_id,
                    "discord_id": availability.discord_id,
                    "new_response": availability.response,
                    "old_response": None
                })
                retried_count += 1
                
                if result.get('status') == 'success':
                    success_count += 1
                    
                    @db_operation
                    def update_sync_status(availability_id: int):
                        availability = Availability.query.get(availability_id)
                        if availability:
                            availability.discord_sync_status = 'synced'
                            availability.last_sync_attempt = datetime.utcnow()
                    
                    update_sync_status(availability.id)

            except Exception as e:
                logger.error(f"Error retrying availability {availability.id}: {str(e)}")

        return {
            'success': True,
            'message': f'Retried {retried_count} updates, {success_count} succeeded',
            'retried_count': retried_count,
            'success_count': success_count
        }

    except Exception as e:
        logger.error(f"Error in retry process: {str(e)}", exc_info=True)
        return {
            'success': False,
            'message': str(e)
        }

@celery_task(name='app.tasks.tasks_rsvp.monitor_rsvp_health')
def monitor_rsvp_health(self) -> Dict[str, Any]:
    """Monitor overall RSVP system health."""
    try:
        @query_operation
        def get_health_metrics() -> Dict[str, int]:
            total_availabilities = Availability.query.count()
            unsynced_count = Availability.query.filter(
                (Availability.discord_sync_status != 'synced') |
                (Availability.discord_sync_status.is_(None))
            ).count()
            failed_count = Availability.query.filter(
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
        return {
            'success': False,
            'message': str(e)
        }