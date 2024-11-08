# app/tasks/tasks_match_updates.py

import logging
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional, List
from app.decorators import celery_task, db_operation, query_operation, session_context
from app.models import MLSMatch, ScheduledMessage, Match
from sqlalchemy.orm import joinedload
from app.extensions import db
from app.tasks.tasks_match_updates_helpers import (
    _process_match_updates_async,
    _get_team_id_from_message
)

logger = logging.getLogger(__name__)

@celery_task(
    name='app.tasks.tasks_match_updates.process_match_updates',
    bind=True,
    queue='discord'
)
def process_match_updates(self, match_id: str, match_data: Dict[str, Any]) -> Dict[str, Any]:
    """Process match updates and send to Discord."""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_process_match_updates_async(match_id, match_data))
            return result
        finally:
            loop.close()
    except Exception as e:
        logger.error(f"Error processing match updates: {str(e)}", exc_info=True)
        raise self.retry(exc=e)

@celery_task(
    name='app.tasks.tasks_match_updates.fetch_match_and_team_id_task',
    bind=True,
    queue='discord'
)
def fetch_match_and_team_id_task(self, message_id: str, channel_id: str) -> Dict[str, Any]:
    """Fetch match and team ID from message details."""
    logger.info(f"Processing message_id: {message_id}, channel_id: {channel_id}")
    
    try:
        with session_context():
            @query_operation
            def get_message_data() -> Optional[Dict[str, Any]]:
                message = ScheduledMessage.query.options(
                    joinedload(ScheduledMessage.match),
                    joinedload(ScheduledMessage.match).joinedload(Match.home_team),
                    joinedload(ScheduledMessage.match).joinedload(Match.away_team)
                ).filter(
                    ((ScheduledMessage.home_channel_id == channel_id) &
                     (ScheduledMessage.home_message_id == message_id)) |
                    ((ScheduledMessage.away_channel_id == channel_id) &
                     (ScheduledMessage.away_message_id == message_id))
                ).first()

                if not message:
                    logger.error(f"No message found for message_id: {message_id}, channel_id: {channel_id}")
                    return None

                team_id = _get_team_id_from_message(message, channel_id, message_id)
                if not team_id:
                    logger.error(f"Could not determine team_id for message: {message_id}")
                    return None

                return {
                    'match_id': message.match_id,
                    'team_id': team_id,
                    'match_date': message.match.date.isoformat() if message.match else None,
                    'team_name': (message.match.home_team.name 
                                if message.match and channel_id == message.home_channel_id 
                                else message.match.away_team.name if message.match 
                                else None)
                }

            message_data = get_message_data()
            if not message_data:
                return {
                    'status': 'error',  # Changed from success: False to status: 'error'
                    'message': 'Message or team ID not found'
                }

            logger.info(f"Found match_id: {message_data['match_id']}, team_id: {message_data['team_id']}")
            return {
                'status': 'success',  # Changed from success: True to status: 'success'
                'message': 'Match and team data retrieved successfully',
                'data': message_data
            }

    except Exception as e:
        logger.error(f"Error fetching match and team ID: {str(e)}", exc_info=True)
        raise self.retry(exc=e)

@celery_task(
    name='app.tasks.tasks_match_updates.update_match_details',
    bind=True,
    queue='discord'
)
def update_match_details_task(self, match_id: str, update_info: Dict[str, Any]) -> Dict[str, Any]:
    """Update match details with proper session management."""
    try:
        with session_context():
            @db_operation
            def _update_match():
                match = db.session.query(MLSMatch).get(match_id)
                if match:
                    match.current_status = update_info.get('match_status')
                    match.current_score = f"{update_info.get('home_score')}-{update_info.get('away_score')}"
                    match.last_update_time = datetime.utcnow()
                    match.current_minute = update_info.get('current_minute')
                    return {
                        'id': match.id,
                        'status': match.current_status,
                        'score': match.current_score,
                        'minute': match.current_minute
                    }
                return None

            result = _update_match()
            if not result:
                return {
                    'success': False,
                    'message': f'Match {match_id} not found'
                }

            return {
                'success': True,
                'message': 'Match details updated successfully',
                'data': result
            }

    except Exception as e:
        logger.error(f"Error updating match details: {str(e)}")
        raise self.retry(exc=e)

@celery_task(
    name='app.tasks.tasks_match_updates.get_active_matches',
    bind=True,
    queue='discord'
)
def get_active_matches_task(self) -> Dict[str, Any]:
    """Get all active matches that need updates."""
    try:
        with session_context():
            @query_operation
            def _get_matches():
                matches = db.session.query(MLSMatch).options(
                    joinedload(MLSMatch.home_team),
                    joinedload(MLSMatch.away_team)
                ).filter(
                    MLSMatch.current_status.in_(['STATUS_IN_PROGRESS', 'STATUS_HALFTIME'])
                ).all()

                return [{
                    'id': match.id,
                    'match_id': match.match_id,
                    'status': match.current_status,
                    'score': match.current_score,
                    'home_team': {
                        'name': match.home_team.name,
                        'id': match.home_team_id
                    },
                    'away_team': {
                        'name': match.away_team.name,
                        'id': match.away_team_id
                    }
                } for match in matches]

            matches = _get_matches()
            return {
                'success': True,
                'message': f'Found {len(matches)} active matches',
                'data': matches
            }

    except Exception as e:
        logger.error(f"Error getting active matches: {str(e)}")
        raise self.retry(exc=e)