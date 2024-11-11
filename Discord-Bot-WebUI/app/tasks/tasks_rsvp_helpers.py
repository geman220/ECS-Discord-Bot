# app/tasks/tasks_rsvp_helpers.py

import logging
import aiohttp
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any, Tuple
from concurrent.futures import ThreadPoolExecutor
from flask import current_app
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import SQLAlchemyError
from app.db_management import db_manager
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
                    logger.error(
                        f"Failed to update Discord embed",
                        extra={
                            'match_id': match_id,
                            'status': response.status,
                            'error': error_text
                        }
                    )
                    return {
                        'success': False,
                        'message': error_text,
                        'status_code': response.status
                    }
                
                logger.info(
                    f"Successfully updated Discord embed",
                    extra={'match_id': match_id}
                )
                return {
                    'success': True,
                    'message': "Discord embed updated successfully",
                    'timestamp': datetime.utcnow().isoformat()
                }
                
    except aiohttp.ClientError as e:
        logger.error(
            f"Discord API error updating embed",
            extra={
                'match_id': match_id,
                'error': str(e)
            },
            exc_info=True
        )
        return {
            'success': False,
            'message': str(e),
            'error_type': 'discord_api_error'
        }
    except Exception as e:
        logger.error(
            f"Unexpected error updating Discord embed",
            extra={'match_id': match_id},
            exc_info=True
        )
        return {
            'success': False,
            'message': str(e),
            'error_type': 'unexpected_error'
        }

async def _send_availability_message_async(scheduled_message_id: int) -> Dict[str, Any]:
    """Async helper for send_availability_message task."""
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        def get_message_data_sync() -> Optional[Dict[str, Any]]:
            from app import create_app
            app = create_app()
            
            with app.app_context():
                with db_manager.session_scope(transaction_name='get_availability_message_data') as session:
                    message = session.query(ScheduledMessage).options(
                        joinedload(ScheduledMessage.match),
                        joinedload(ScheduledMessage.match).joinedload(Match.home_team),
                        joinedload(ScheduledMessage.match).joinedload(Match.away_team)
                    ).get(scheduled_message_id)
                    
                    if not message:
                        return None
                        
                    match = message.match
                    if not match:
                        logger.error(f"No match found for scheduled message {scheduled_message_id}")
                        return None

                    return {
                        'scheduled_message_id': message.id,
                        'match_id': match.id,
                        'home_channel_id': str(match.home_team.discord_channel_id) if match.home_team else None,
                        'away_channel_id': str(match.away_team.discord_channel_id) if match.away_team else None,
                        'match_date': match.date.strftime('%Y-%m-%d'),
                        'match_time': match.time.strftime('%H:%M:%S'),
                        'home_team_name': match.home_team.name if match.home_team else None,
                        'away_team_name': match.away_team.name if match.away_team else None
                    }

        message_data = await asyncio.get_event_loop().run_in_executor(executor, get_message_data_sync)
        if not message_data:
            logger.error(f"Failed to get message data for ID {scheduled_message_id}")
            return {
                'success': False,
                'message': f"Scheduled message {scheduled_message_id} not found or invalid",
                'error_type': 'data_not_found'
            }

        # Validate required data
        if not (message_data['home_channel_id'] and message_data['away_channel_id']):
            logger.error("Missing channel IDs", extra={'message_data': message_data})
            return {
                'success': False,
                'message': "Missing Discord channel IDs",
                'error_type': 'missing_channel_ids'
            }

        # Post message to Discord
        message_ids = await post_availability_message(message_data)
        if not message_ids:
            def mark_failed_sync():
                from app import create_app
                app = create_app()
                
                with app.app_context():
                    with db_manager.session_scope(transaction_name='mark_message_failed') as session:
                        message = session.query(ScheduledMessage).get(scheduled_message_id)
                        if message:
                            message.status = 'FAILED'
                            message.last_error = "Failed to send Discord message"
                            message.error_timestamp = datetime.utcnow()
                            session.flush()

            await asyncio.get_event_loop().run_in_executor(executor, mark_failed_sync)
            return {
                'success': False,
                'message': "Failed to send availability message",
                'error_type': 'discord_send_failed'
            }

        home_message_id, away_message_id = message_ids

        def mark_sent_sync():
            from app import create_app
            app = create_app()
            
            with app.app_context():
                with db_manager.session_scope(transaction_name='mark_message_sent') as session:
                    message = session.query(ScheduledMessage).get(scheduled_message_id)
                    if message:
                        message.status = 'SENT'
                        message.home_discord_message_id = home_message_id
                        message.away_discord_message_id = away_message_id
                        message.sent_at = datetime.utcnow()
                        message.last_error = None
                        session.flush()

        await asyncio.get_event_loop().run_in_executor(executor, mark_sent_sync)
        
        logger.info(
            "Availability message sent successfully",
            extra={
                'scheduled_message_id': scheduled_message_id,
                'home_message_id': home_message_id,
                'away_message_id': away_message_id
            }
        )
        
        return {
            'success': True,
            'message': "Availability message sent successfully",
            'home_message_id': home_message_id,
            'away_message_id': away_message_id,
            'sent_at': datetime.utcnow().isoformat()
        }

    except SQLAlchemyError as e:
        logger.error(
            "Database error sending availability message",
            extra={'scheduled_message_id': scheduled_message_id},
            exc_info=True
        )
        raise
    except Exception as e:
        logger.error(
            "Error sending availability message",
            extra={'scheduled_message_id': scheduled_message_id},
            exc_info=True
        )
        raise
    finally:
        executor.shutdown()

async def _update_discord_rsvp_async(data: Dict[str, Any]) -> Dict[str, Any]:
    """Async helper for update_discord_rsvp task."""
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        # Validate required fields
        required_fields = ['match_id', 'discord_id', 'new_response']
        if not all(key in data for key in required_fields):
            return {
                'success': False,
                'message': "Missing required fields",
                'required_fields': required_fields,
                'error_type': 'validation_error'
            }

        request_data = {
            "match_id": str(data.get("match_id")),
            "discord_id": str(data.get("discord_id")),
            "new_response": data.get("new_response"),
            "old_response": data.get("old_response")
        }

        result = await update_user_reaction(request_data)

        if result['success']:
            def update_rsvp_status_sync():
                from app import create_app
                app = create_app()
                
                with app.app_context():
                    with db_manager.session_scope(transaction_name='update_rsvp_sync_status') as session:
                        availability = session.query(Availability).filter_by(
                            match_id=int(data['match_id']),
                            discord_id=data['discord_id']
                        ).first()
                        if availability:
                            availability.discord_sync_status = 'synced'
                            availability.last_sync_time = datetime.utcnow()
                            availability.sync_error = None
                            availability.sync_attempts = (availability.sync_attempts or 0) + 1
                            session.flush()

            await asyncio.get_event_loop().run_in_executor(executor, update_rsvp_status_sync)
            
            logger.info(
                "RSVP sync completed successfully",
                extra={
                    'match_id': data['match_id'],
                    'discord_id': data['discord_id']
                }
            )

        return {
            'success': result['success'],
            'message': result['message'],
            'timestamp': datetime.utcnow().isoformat(),
            'sync_status': 'synced' if result['success'] else 'failed'
        }
        
    except SQLAlchemyError as e:
        logger.error(
            "Database error updating RSVP sync status",
            extra={'data': data},
            exc_info=True
        )
        raise
    except Exception as e:
        logger.error(
            "Error updating Discord RSVP",
            extra={'data': data},
            exc_info=True
        )
        raise
    finally:
        executor.shutdown()

async def _notify_discord_async(match_id: int) -> Dict[str, Any]:
    """Async helper for notify_discord_of_rsvp_change task."""
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        # Verify match exists
        def verify_match_exists():
            from app import create_app
            app = create_app()
            
            with app.app_context():
                with db_manager.session_scope(transaction_name='verify_match_exists') as session:
                    match = session.query(Match).get(match_id)
                    return bool(match)

        match_exists = await asyncio.get_event_loop().run_in_executor(executor, verify_match_exists)
        if not match_exists:
            return {
                'success': False,
                'message': f"Match {match_id} not found",
                'error_type': 'match_not_found'
            }

        result = await update_availability_embed(match_id)
        
        if result['success']:
            def update_match_notification_sync():
                from app import create_app
                app = create_app()
                
                with app.app_context():
                    with db_manager.session_scope(transaction_name='update_match_notification') as session:
                        match = session.query(Match).get(match_id)
                        if match:
                            match.last_discord_notification = datetime.utcnow()
                            match.notification_status = 'success'
                            match.notification_error = None
                            session.flush()

            await asyncio.get_event_loop().run_in_executor(executor, update_match_notification_sync)
            
            logger.info(
                "Discord notification completed successfully",
                extra={'match_id': match_id}
            )
            
        return {
            'success': result['success'],
            'message': result['message'],
            'notification_time': datetime.utcnow().isoformat()
        }
        
    except SQLAlchemyError as e:
        logger.error(
            "Database error updating notification status",
            extra={'match_id': match_id},
            exc_info=True
        )
        raise
    except Exception as e:
        logger.error(
            "Error notifying Discord",
            extra={'match_id': match_id},
            exc_info=True
        )
        raise
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
                    logger.error(
                        "Failed to post availability message",
                        extra={
                            'status': response.status,
                            'error': error_text,
                            'message_data': {k: v for k, v in message_data.items() if k != 'auth_token'}
                        }
                    )
                    return None
                
                result = await response.json()
                
                logger.info(
                    "Posted availability message successfully",
                    extra={
                        'message_data': {k: v for k, v in message_data.items() if k != 'auth_token'},
                        'message_ids': {
                            'home': result.get('home_message_id'),
                            'away': result.get('away_message_id')
                        }
                    }
                )
                
                return result.get('home_message_id'), result.get('away_message_id')
                
    except aiohttp.ClientError as e:
        logger.error(
            "Discord API error posting availability message",
            extra={'message_data': {k: v for k, v in message_data.items() if k != 'auth_token'}},
            exc_info=True
        )
        return None
    except Exception as e:
        logger.error(
            "Error posting availability message",
            extra={'message_data': {k: v for k, v in message_data.items() if k != 'auth_token'}},
            exc_info=True
        )
        return None

async def update_user_reaction(request_data: Dict[str, Any]) -> Dict[str, Any]:
    """Update user reaction in Discord."""
    bot_api_url = "http://discord-bot:5001/api/update_user_reaction"
    
    try:
        # Validate required fields
        required_fields = ['match_id', 'discord_id', 'new_response']
        if not all(key in request_data for key in required_fields):
            return {
                'success': False,
                'message': "Missing required fields",
                'required_fields': required_fields,
                'error_type': 'validation_error'
            }

        start_time = datetime.utcnow()
        async with aiohttp.ClientSession() as session:
            async with session.post(
                bot_api_url,
                json=request_data,
                timeout=30
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(
                        "Failed to update Discord RSVP",
                        extra={
                            'status': response.status,
                            'error': error_text,
                            'match_id': request_data.get('match_id'),
                            'discord_id': request_data.get('discord_id')
                        }
                    )
                    return {
                        'success': False,
                        'message': f"Failed to update Discord RSVP: {error_text}",
                        'error_type': 'discord_api_error',
                        'status_code': response.status
                    }

                duration = (datetime.utcnow() - start_time).total_seconds()
                logger.info(
                    "Discord RSVP update successful",
                    extra={
                        'match_id': request_data.get('match_id'),
                        'discord_id': request_data.get('discord_id'),
                        'duration': duration,
                        'new_response': request_data.get('new_response')
                    }
                )
                
                # Update database with success status
                def update_discord_status():
                    from app import create_app
                    app = create_app()
                    
                    with app.app_context():
                        with db_manager.session_scope(transaction_name='update_discord_reaction_status') as session:
                            availability = session.query(Availability).filter_by(
                                match_id=request_data.get('match_id'),
                                discord_id=request_data.get('discord_id')
                            ).first()
                            
                            if availability:
                                availability.discord_update_time = datetime.utcnow()
                                availability.discord_update_status = 'success'
                                availability.last_update_duration = duration
                                session.flush()

                await asyncio.get_event_loop().run_in_executor(
                    ThreadPoolExecutor(max_workers=1),
                    update_discord_status
                )
                
                return {
                    'success': True,
                    'message': "Discord RSVP updated successfully",
                    'timestamp': datetime.utcnow().isoformat(),
                    'duration': duration
                }

    except aiohttp.ClientError as e:
        error_msg = f"Discord API error: {str(e)}"
        logger.error(
            "Discord API error updating RSVP",
            extra={
                'match_id': request_data.get('match_id'),
                'discord_id': request_data.get('discord_id'),
                'error': str(e)
            },
            exc_info=True
        )
        
        # Update database with error status
        def update_error_status():
            from app import create_app
            app = create_app()
            
            with app.app_context():
                with db_manager.session_scope(transaction_name='update_discord_reaction_error') as session:
                    availability = session.query(Availability).filter_by(
                        match_id=request_data.get('match_id'),
                        discord_id=request_data.get('discord_id')
                    ).first()
                    
                    if availability:
                        availability.discord_update_time = datetime.utcnow()
                        availability.discord_update_status = 'error'
                        availability.last_error = str(e)
                        availability.error_count = (availability.error_count or 0) + 1
                        session.flush()

        await asyncio.get_event_loop().run_in_executor(
            ThreadPoolExecutor(max_workers=1),
            update_error_status
        )
        
        return {
            'success': False,
            'message': error_msg,
            'error_type': 'discord_api_error'
        }
        
    except Exception as e:
        error_msg = f"Error updating Discord RSVP: {str(e)}"
        logger.error(
            "Unexpected error updating RSVP",
            extra={
                'match_id': request_data.get('match_id'),
                'discord_id': request_data.get('discord_id')
            },
            exc_info=True
        )
        return {
            'success': False,
            'message': error_msg,
            'error_type': 'unexpected_error'
        }

# Additional helper functions for tracking and monitoring
async def check_discord_connection() -> Dict[str, Any]:
    """Check Discord bot API connection health."""
    bot_api_url = "http://discord-bot:5001/api/health"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(bot_api_url, timeout=5) as response:
                if response.status != 200:
                    return {
                        'success': False,
                        'message': "Discord bot API health check failed",
                        'status_code': response.status
                    }
                return {
                    'success': True,
                    'message': "Discord bot API connection healthy",
                    'timestamp': datetime.utcnow().isoformat()
                }
    except Exception as e:
        return {
            'success': False,
            'message': f"Discord bot API connection error: {str(e)}",
            'error_type': 'connection_error'
        }

def handle_discord_error(e: Exception, context: Dict[str, Any]) -> Dict[str, Any]:
    """Handle Discord-related errors with proper logging and status updates."""
    error_msg = str(e)
    error_type = 'discord_api_error' if isinstance(e, aiohttp.ClientError) else 'unexpected_error'
    
    logger.error(
        f"Discord operation error: {error_msg}",
        extra={
            'error_type': error_type,
            'context': context
        },
        exc_info=True
    )
    
    return {
        'success': False,
        'message': error_msg,
        'error_type': error_type,
        'context': context,
        'timestamp': datetime.utcnow().isoformat()
    }