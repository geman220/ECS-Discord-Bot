# app/tasks/tasks_rsvp_helpers.py

import logging
import aiohttp
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any, Tuple
from concurrent.futures import ThreadPoolExecutor
from flask import current_app
from sqlalchemy.orm import joinedload
from app.extensions import db
from app.decorators import db_operation, query_operation, session_context
from app.models import Match, Availability, ScheduledMessage

logger = logging.getLogger(__name__)

# Discord API Helpers
async def update_availability_embed(match_id: int) -> Dict[str, Any]:
    """Update availability embed in Discord."""
    bot_api_url = f"http://discord-bot:5001/api/update_availability_embed/{match_id}"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(bot_api_url, timeout=10) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Failed to update Discord embed. Status: {response.status}, Response: {error_text}")
                    return {
                        'success': False,
                        'message': error_text
                    }
                logger.info(f"Successfully updated Discord embed for match {match_id}")
                return {
                    'success': True,
                    'message': "Discord embed updated successfully"
                }
    except Exception as e:
        logger.error(f"Error updating Discord embed for match {match_id}: {str(e)}")
        return {
            'success': False,
            'message': str(e)
        }

async def _send_availability_message_async(scheduled_message_id: int) -> Dict[str, Any]:
    """Async helper for send_availability_message task."""
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        def get_message_data_sync() -> Optional[Dict[str, Any]]:
            from app import create_app
            app = create_app()
            
            with app.app_context():
                with session_context():
                    message = db.session.query(ScheduledMessage).options(
                        joinedload(ScheduledMessage.match),
                        joinedload(ScheduledMessage.match).joinedload(Match.home_team),
                        joinedload(ScheduledMessage.match).joinedload(Match.away_team)
                    ).get(scheduled_message_id)
                    
                    if not message:
                        return None
                        
                    match = message.match
                    return {
                        'scheduled_message_id': message.id,
                        'match_id': match.id,
                        'home_channel_id': str(match.home_team.discord_channel_id),
                        'away_channel_id': str(match.away_team.discord_channel_id),
                        'match_date': match.date.strftime('%Y-%m-%d'),
                        'match_time': match.time.strftime('%H:%M:%S'),
                        'home_team_name': match.home_team.name,
                        'away_team_name': match.away_team.name
                    }

        message_data = await asyncio.get_event_loop().run_in_executor(executor, get_message_data_sync)
        if not message_data:
            return {
                'success': False,
                'message': f"Scheduled message {scheduled_message_id} not found"
            }

        # Post message to Discord
        message_ids = await post_availability_message(message_data)
        if not message_ids:
            def mark_failed_sync():
                from app import create_app
                app = create_app()
                
                with app.app_context():
                    with session_context():
                        message = db.session.query(ScheduledMessage).get(scheduled_message_id)
                        if message:
                            message.status = 'FAILED'

            await asyncio.get_event_loop().run_in_executor(executor, mark_failed_sync)
            return {
                'success': False,
                'message': "Failed to send availability message"
            }

        home_message_id, away_message_id = message_ids

        def mark_sent_sync():
            from app import create_app
            app = create_app()
            
            with app.app_context():
                with session_context():
                    message = db.session.query(ScheduledMessage).get(scheduled_message_id)
                    if message:
                        message.status = 'SENT'
                        message.home_discord_message_id = home_message_id
                        message.away_discord_message_id = away_message_id

        await asyncio.get_event_loop().run_in_executor(executor, mark_sent_sync)
        
        return {
            'success': True,
            'message': "Availability message sent successfully",
            'home_message_id': home_message_id,
            'away_message_id': away_message_id
        }

    finally:
        executor.shutdown()

async def _update_discord_rsvp_async(data: Dict[str, Any]) -> Dict[str, Any]:
    """Async helper for update_discord_rsvp task."""
    executor = ThreadPoolExecutor(max_workers=1)
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
            def update_rsvp_status_sync():
                from app import create_app
                app = create_app()
                
                with app.app_context():
                    with session_context():
                        availability = db.session.query(Availability).filter_by(
                            match_id=int(data['match_id']),
                            discord_id=data['discord_id']
                        ).first()
                        if availability:
                            availability.discord_sync_status = 'synced'
                            availability.last_sync_time = datetime.utcnow()

            await asyncio.get_event_loop().run_in_executor(executor, update_rsvp_status_sync)

        return result
    finally:
        executor.shutdown()

async def _notify_discord_async(match_id: int) -> Dict[str, Any]:
    """Async helper for notify_discord_of_rsvp_change task."""
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        result = await update_availability_embed(match_id)
        
        if result['success']:
            def update_match_notification_sync():
                from app import create_app
                app = create_app()
                
                with app.app_context():
                    with session_context():
                        match = db.session.query(Match).get(match_id)
                        if match:
                            match.last_discord_notification = datetime.utcnow()
                            logger.debug(f"Updated notification status for match {match_id}")

            await asyncio.get_event_loop().run_in_executor(executor, update_match_notification_sync)
            
        return result
    finally:
        executor.shutdown()

async def post_availability_message(message_data: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """Post availability message to Discord and return message IDs."""
    bot_api_url = "http://discord-bot:5001/api/post_availability"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(bot_api_url, json=message_data, timeout=30) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Failed to post availability message. Status: {response.status}, Error: {error_text}")
                    return None
                
                result = await response.json()
                return result.get('home_message_id'), result.get('away_message_id')
                
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
