from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
import logging
import aiohttp
import asyncio

from app.extensions import db, socketio
from app.decorators import celery_task, async_task
from app.models import Match, ScheduledMessage, Availability, Player
from app.db_utils import safe_commit
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
        match = Match.query.get_or_404(match_id)
        player = Player.query.get_or_404(player_id)
        availability = Availability.query.filter_by(
            match_id=match_id,
            player_id=player_id
        ).first()

        old_response = availability.response if availability else None

        if availability:
            if new_response == 'no_response':
                db.session.delete(availability)
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
                db.session.add(availability)

        if discord_id:
            player.discord_id = discord_id

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
async def send_availability_message(self, scheduled_message_id: int):
    """Send availability message to Discord."""
    try:
        scheduled_message = ScheduledMessage.query.get(scheduled_message_id)
        if not scheduled_message:
            return f"Scheduled message {scheduled_message_id} not found"

        match = scheduled_message.match
        home_channel_id = match.home_team.discord_channel_id
        away_channel_id = match.away_team.discord_channel_id

        payload = {
            "match_id": match.id,
            "home_team_id": match.home_team_id,
            "away_team_id": match.away_team_id,
            "home_channel_id": str(home_channel_id),
            "away_channel_id": str(away_channel_id),
            "match_date": match.date.strftime('%Y-%m-%d'),
            "match_time": match.time.strftime('%H:%M:%S'),
            "home_team_name": match.home_team.name,
            "away_team_name": match.away_team.name
        }

        result = await post_availability_message(payload)
        if result:
            home_message_id, away_message_id = result
            scheduled_message.home_discord_message_id = home_message_id
            scheduled_message.away_discord_message_id = away_message_id
            scheduled_message.status = 'SENT'
            return "Availability message sent successfully"
        
        scheduled_message.status = 'FAILED'
        return "Failed to send availability message"

    except Exception as e:
        logger.error(f"Error sending availability message {scheduled_message_id}: {str(e)}", exc_info=True)
        raise

@celery_task(name='app.tasks.tasks_rsvp.process_scheduled_messages')
def process_scheduled_messages(self):
    """Process and send all pending scheduled messages."""
    try:
        now = datetime.utcnow()
        messages = ScheduledMessage.query.filter(
            ScheduledMessage.status == 'PENDING',
            ScheduledMessage.scheduled_send_time <= now
        ).all()

        for message in messages:
            try:
                send_availability_message.delay(message.id)
                message.status = 'QUEUED'
            except Exception as e:
                logger.error(f"Error queueing message {message.id}: {str(e)}", exc_info=True)
                message.status = 'FAILED'

        return f"Processed {len(messages)} scheduled messages"

    except Exception as e:
        logger.error(f"Error processing scheduled messages: {str(e)}", exc_info=True)
        raise

@celery_task(name='app.tasks.tasks_rsvp.notify_frontend_of_rsvp_change')
def notify_frontend_of_rsvp_change_task(self, match_id: int, player_id: int, response: str):
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
async def update_discord_rsvp_task(self, data: Dict[str, Any]):
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
        return result

    except Exception as e:
        logger.error(f"Error updating Discord RSVP: {str(e)}", exc_info=True)
        raise

@async_task(name='app.tasks.tasks_rsvp.notify_discord_of_rsvp_change')
async def notify_discord_of_rsvp_change_task(self, match_id: int):
    """Notify Discord of RSVP changes."""
    try:
        await update_availability_embed(match_id)
        return True
    except Exception as e:
        logger.error(f"Error notifying Discord of RSVP change for match {match_id}: {str(e)}", exc_info=True)
        raise

@celery_task(name='app.tasks.tasks_rsvp.process_discord_role_updates')
def process_discord_role_updates(self):
    """Process Discord role updates for all marked players."""
    try:
        players = Player.query.filter(
            (Player.discord_needs_update == True) |
            (Player.discord_last_verified == None) |
            (Player.discord_last_verified < datetime.utcnow() - timedelta(days=90))
        ).all()

        if not players:
            logger.info("No players need Discord role updates")
            return True

        logger.info(f"Processing Discord role updates for {len(players)} players")
        asyncio.run(process_role_updates(players))
        return True

    except Exception as e:
        logger.error(f"Error processing Discord role updates: {str(e)}", exc_info=True)
        raise

# Helper Functions

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