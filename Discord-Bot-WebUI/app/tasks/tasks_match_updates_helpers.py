# app/tasks/tasks_match_updates_helpers.py

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
                with session_context():
                    match = db.session.query(MLSMatch).options(
                        joinedload(MLSMatch.home_team),
                        joinedload(MLSMatch.away_team)
                    ).get(match_id)

                    if not match:
                        return None

                    return {
                        'id': match.id,
                        'discord_thread_id': match.discord_thread_id,
                        'home_team': match.home_team.name,
                        'away_team': match.away_team.name
                    }

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
            'home_team': home_comp['team']['displayName'],
            'away_team': away_comp['team']['displayName'],
            'home_score': home_comp['score'],
            'away_score': away_comp['score'],
            'match_status': competition['status']['type']['name'],
            'current_minute': competition['status']['displayClock']
        }

        update_type, update_data = _create_match_update(**update_info)

        # Send update to Discord
        await send_discord_update(
            match_info['discord_thread_id'],
            update_type,
            update_data
        )

        def update_match_status_sync():
            from app import create_app
            app = create_app()
            
            with app.app_context():
                with session_context():
                    match = db.session.query(MLSMatch).get(match_id)
                    if match:
                        match.last_update_time = datetime.utcnow()
                        match.last_update_type = update_type
                        match.current_status = update_info['match_status']
                        match.current_score = f"{update_info['home_score']}-{update_info['away_score']}"

        await asyncio.get_event_loop().run_in_executor(executor, update_match_status_sync)

        return {
            'success': True,
            'message': "Match update sent successfully",
            'update_type': update_type,
            'match_status': update_info['match_status']
        }

    except Exception as e:
        logger.error(f"Error processing match updates: {str(e)}", exc_info=True)
        return {
            'success': False,
            'message': str(e)
        }
    finally:
        executor.shutdown()

def _create_match_update(
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

    return update_types.get(match_status, ("status_update", f"Match Status: {match_status}"))

def _get_team_id_from_message(message: Match, channel_id: str, message_id: str) -> Optional[int]:
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