# app/tasks/tasks_match_updates_helpers.py

import logging
import aiohttp
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any, Tuple
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import SQLAlchemyError
from app.extensions import db
from app.db_management import db_manager
from app.models import MLSMatch, Match

logger = logging.getLogger(__name__)

async def _process_match_updates_async(match_id: str, match_data: Dict[str, Any]) -> Dict[str, Any]:
    """Async helper for processing match updates."""
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        def get_match_info_sync() -> Optional[Dict[str, Any]]:
            from app import create_app
            app = create_app()
            
            with app.app_context():
                with db_manager.session_scope(transaction_name='get_match_update_info') as session:
                    match = session.query(MLSMatch).options(
                        joinedload(MLSMatch.home_team),
                        joinedload(MLSMatch.away_team)
                    ).get(match_id)

                    if not match:
                        logger.error(f"Match {match_id} not found")
                        return None

                    return {
                        'id': match.id,
                        'discord_thread_id': match.discord_thread_id,
                        'home_team': match.home_team.name if match.home_team else None,
                        'away_team': match.away_team.name if match.away_team else None,
                        'current_status': match.current_status,
                        'current_score': match.current_score
                    }

        match_info = await asyncio.get_event_loop().run_in_executor(executor, get_match_info_sync)
        if not match_info:
            return {
                'success': False,
                'message': f"No match found with ID {match_id}",
                'error_type': 'match_not_found'
            }

        # Validate required match data
        if not match_data.get('competitions'):
            return {
                'success': False,
                'message': "Invalid match data format",
                'error_type': 'invalid_data'
            }

        try:
            competition = match_data['competitions'][0]
            home_comp = competition['competitors'][0]
            away_comp = competition['competitors'][1]

            update_info = {
                'home_team': home_comp['team']['displayName'],
                'away_team': away_comp['team']['displayName'],
                'home_score': home_comp['score'],
                'away_score': away_comp['score'],
                'match_status': competition['status']['type']['name'],
                'current_minute': competition['status']['displayClock']
            }

            update_type, update_data = create_match_update(**update_info)

            # Send update to Discord
            if match_info['discord_thread_id']:
                try:
                    await send_discord_update(
                        match_info['discord_thread_id'],
                        update_type,
                        update_data
                    )
                except aiohttp.ClientError as e:
                    logger.error(
                        "Discord API error sending update",
                        extra={
                            'match_id': match_id,
                            'error': str(e)
                        },
                        exc_info=True
                    )
                    raise

            # Update match status in database
            def update_match_status_sync():
                from app import create_app
                app = create_app()
                
                with app.app_context():
                    with db_manager.session_scope(transaction_name='update_match_status') as session:
                        match = session.query(MLSMatch).get(match_id)
                        if match:
                            match.last_update_time = datetime.utcnow()
                            match.last_update_type = update_type
                            match.current_status = update_info['match_status']
                            match.current_score = f"{update_info['home_score']}-{update_info['away_score']}"
                            match.current_minute = update_info['current_minute']
                            match.update_count = (match.update_count or 0) + 1
                            
                            # Track significant status changes
                            if match.current_status != match_info['current_status']:
                                match.last_status_change = datetime.utcnow()
                                match.previous_status = match_info['current_status']
                            
                            session.flush()

            await asyncio.get_event_loop().run_in_executor(executor, update_match_status_sync)

            return {
                'success': True,
                'message': "Match update processed successfully",
                'update_type': update_type,
                'match_status': update_info['match_status'],
                'score': f"{update_info['home_score']}-{update_info['away_score']}",
                'timestamp': datetime.utcnow().isoformat()
            }

        except KeyError as e:
            logger.error(
                "Invalid match data structure",
                extra={
                    'match_id': match_id,
                    'missing_key': str(e)
                },
                exc_info=True
            )
            return {
                'success': False,
                'message': f"Invalid match data: missing {str(e)}",
                'error_type': 'data_structure_error'
            }

    except SQLAlchemyError as e:
        logger.error(
            "Database error processing match update",
            extra={'match_id': match_id},
            exc_info=True
        )
        raise
    except Exception as e:
        logger.error(
            "Error processing match update",
            extra={'match_id': match_id},
            exc_info=True
        )
        raise
    finally:
        executor.shutdown()

def create_match_update(
    match_status: str,
    home_team: str,
    away_team: str,
    home_score: str,
    away_score: str,
    current_minute: str
) -> Tuple[str, str]:
    """Create appropriate update message based on match status."""
    try:
        update_types = {
            'STATUS_SCHEDULED': (
                "pre_match_info",
                f"🏆 Match Alert: {home_team} vs {away_team} is about to start!"
            ),
            'STATUS_IN_PROGRESS': (
                "score_update",
                f"⚽ {home_team} {home_score} - {away_score} {away_team} ({current_minute})"
            ),
            'STATUS_HALFTIME': (
                "halftime_update",
                f"🔄 Halftime: {home_team} {home_score} - {away_score} {away_team}"
            ),
            'STATUS_FINAL': (
                "match_end",
                f"🔚 Full Time: {home_team} {home_score} - {away_score} {away_team}"
            ),
            'STATUS_POSTPONED': (
                "match_postponed",
                f"⚠️ Match Postponed: {home_team} vs {away_team}"
            ),
            'STATUS_CANCELLED': (
                "match_cancelled",
                f"❌ Match Cancelled: {home_team} vs {away_team}"
            ),
            'STATUS_DELAYED': (
                "match_delayed",
                f"⏳ Match Delayed: {home_team} vs {away_team}"
            )
        }

        return update_types.get(
            match_status, 
            ("status_update", f"ℹ️ Match Status: {match_status} - {home_team} vs {away_team}")
        )

    except Exception as e:
        logger.error(
            "Error creating match update",
            extra={
                'match_status': match_status,
                'teams': f"{home_team} vs {away_team}"
            },
            exc_info=True
        )
        return ("error", f"Error creating update: {str(e)}")

def get_team_id_from_message(message: Match, channel_id: str, message_id: str) -> Optional[int]:
    """Helper function to determine team ID from message details."""
    try:
        if not message or not message.match:
            logger.error("Invalid message or missing match reference")
            return None

        if message.home_channel_id == channel_id and message.home_message_id == message_id:
            return message.match.home_team_id
        elif message.away_channel_id == channel_id and message.away_message_id == message_id:
            return message.match.away_team_id
            
        logger.warning(
            "No matching channel/message combination found",
            extra={
                'channel_id': channel_id,
                'message_id': message_id,
                'home_channel': message.home_channel_id,
                'away_channel': message.away_channel_id
            }
        )
        return None

    except Exception as e:
        logger.error(
            "Error determining team ID",
            extra={
                'channel_id': channel_id,
                'message_id': message_id
            },
            exc_info=True
        )
        return None

async def send_discord_update(thread_id: str, update_type: str, update_data: str) -> Dict[str, Any]:
    """Send update to Discord thread."""
    bot_api_url = f"http://discord-bot:5001/api/thread/{thread_id}/update"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                bot_api_url,
                json={
                    'type': update_type,
                    'content': update_data
                },
                timeout=30
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(
                        "Failed to send Discord update",
                        extra={
                            'thread_id': thread_id,
                            'status': response.status,
                            'error': error_text
                        }
                    )
                    return {
                        'success': False,
                        'message': f"Discord API error: {error_text}",
                        'status_code': response.status
                    }
                
                return {
                    'success': True,
                    'message': "Update sent successfully",
                    'timestamp': datetime.utcnow().isoformat()
                }

    except aiohttp.ClientError as e:
        logger.error(
            "Discord API error",
            extra={
                'thread_id': thread_id,
                'error': str(e)
            },
            exc_info=True
        )
        raise
    except Exception as e:
        logger.error(
            "Error sending Discord update",
            extra={'thread_id': thread_id},
            exc_info=True
        )
        raise