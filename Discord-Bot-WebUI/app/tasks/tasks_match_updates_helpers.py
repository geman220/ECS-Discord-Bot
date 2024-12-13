# app/tasks/tasks_match_updates_helpers.py

import logging
import aiohttp
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any, Tuple
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy.exc import SQLAlchemyError
from app.models import MLSMatch, Match
from app.core import celery

logger = logging.getLogger(__name__)

async def _process_match_updates_async(match_id: str, match_data: Dict[str, Any]) -> Dict[str, Any]:
    """Async helper for processing match updates."""
    executor = ThreadPoolExecutor(max_workers=1)
    app = celery.flask_app

    try:
        def get_match_info_sync() -> Optional[Dict[str, Any]]:
            with app.app_context():
                session = app.SessionLocal()
                try:
                    match = session.query(MLSMatch).get(match_id)
                    if not match:
                        return None
                    return {
                        'id': match.id,
                        'discord_thread_id': match.discord_thread_id,
                        'home_team': match.home_team.name if match.home_team else None,
                        'away_team': match.away_team.name if match.away_team else None,
                        'current_status': match.current_status
                    }
                except Exception as e:
                    logger.error(f"Error fetching match info: {e}", exc_info=True)
                    raise
                finally:
                    session.close()

        match_info = await asyncio.get_event_loop().run_in_executor(executor, get_match_info_sync)
        if not match_info:
            return {
                'success': False,
                'message': f"No match found with ID {match_id}"
            }

        competition = match_data['competitions'][0]
        home_comp = competition['competitors'][0]
        away_comp = competition['competitors'][1]

        update_info = {
            'match_status': competition['status']['type']['name'],
            'home_team': home_comp['team']['displayName'],
            'away_team': away_comp['team']['displayName'],
            'home_score': home_comp['score'],
            'away_score': away_comp['score'],
            'current_minute': competition['status'].get('displayClock', 'N/A')
        }

        update_type, update_data = create_match_update(**update_info)

        # Send update to Discord
        await send_discord_update(
            match_info['discord_thread_id'],
            update_type,
            update_data
        )

        def update_match_status_sync():
            with app.app_context():
                session = app.SessionLocal()
                try:
                    match = session.query(MLSMatch).get(match_id)
                    if match:
                        match.last_update_time = datetime.utcnow()
                        match.last_update_type = update_type
                        match.current_status = update_info['match_status']
                        match.current_score = f"{update_info['home_score']}-{update_info['away_score']}"
                        match.current_minute = update_info['current_minute']
                        session.commit()
                except Exception as e:
                    session.rollback()
                    logger.error(f"Error updating match status: {e}", exc_info=True)
                    raise
                finally:
                    session.close()

        await asyncio.get_event_loop().run_in_executor(executor, update_match_status_sync)

        return {
            'success': True,
            'message': "Match update sent successfully",
            'update_type': update_type,
            'match_status': update_info['match_status']
        }

    except SQLAlchemyError as e:
        logger.error(f"Database error processing match updates: {str(e)}", exc_info=True)
        raise
    except Exception as e:
        logger.error(f"Error processing match updates: {str(e)}", exc_info=True)
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
    update_types = {
        'STATUS_SCHEDULED': (
            "pre_match_info",
            f"🚨 Match Alert: {home_team} vs {away_team} is about to start!"
        ),
        'STATUS_IN_PROGRESS': (
            "score_update",
            f"⚽ {home_team} {home_score} - {away_score} {away_team} ({current_minute})"
        ),
        'STATUS_HALFTIME': (
            "halftime_update",
            f"⏸ Halftime: {home_team} {home_score} - {away_score} {away_team}"
        ),
        'STATUS_FINAL': (
            "match_end",
            f"🏁 Full Time: {home_team} {home_score} - {away_score} {away_team}"
        )
    }

    return update_types.get(
        match_status,
        ("status_update", f"Match Status: {match_status}")
    )

def get_team_id_from_message(message: Match, channel_id: str, message_id: str) -> Optional[int]:
    """Helper function to determine team ID from message details."""
    try:
        if message.home_channel_id == channel_id and message.home_message_id == message_id:
            return message.match.home_team_id
        elif message.away_channel_id == channel_id and message.away_message_id == message_id:
            return message.match.away_team_id
        return None
    except Exception as e:
        logger.error(f"Error determining team ID: {str(e)}")
        return None

async def send_discord_update(thread_id: str, update_type: str, update_data: str) -> Dict[str, Any]:
    """Send update to Discord thread."""
    bot_api_url = f"http://discord-bot:5001/api/thread/{thread_id}/update"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                bot_api_url,
                json={'type': update_type, 'content': update_data},
                timeout=30
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Failed to send Discord update: {error_text}")
                    raise Exception(f"Discord API error: {error_text}")

                return {
                    'success': True,
                    'message': "Update sent successfully"
                }

    except aiohttp.ClientError as e:
        logger.error(f"Discord API error: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Error sending Discord update: {str(e)}")
        raise
