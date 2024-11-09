# app/tasks/tasks_match_updates.py

import logging
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import SQLAlchemyError
from app.decorators import celery_task
from app.models import MLSMatch, ScheduledMessage, Match
from app.extensions import db
from app.db_management import db_manager
from app.tasks.tasks_match_updates_helpers import (
    _process_match_updates_async,
    get_team_id_from_message  # Updated to use renamed function
)

logger = logging.getLogger(__name__)

@celery_task(
    name='app.tasks.tasks_match_updates.process_match_updates',
    bind=True,
    queue='discord',
    max_retries=3,
    retry_backoff=True
)
def process_match_updates(self, match_id: str, match_data: Dict[str, Any]) -> Dict[str, Any]:
    """Process match updates and send to Discord."""
    try:
        # Validate input data
        if not match_data or 'competitions' not in match_data:
            return {
                'success': False,
                'message': 'Invalid match data format',
                'error_type': 'validation_error'
            }

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_process_match_updates_async(match_id, match_data))
            return result
        finally:
            loop.close()
            
    except SQLAlchemyError as e:
        logger.error(f"Database error processing match updates: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error processing match updates: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)

@celery_task(
    name='app.tasks.tasks_match_updates.fetch_match_and_team_id_task',
    bind=True,
    queue='discord',
    max_retries=3,
    retry_backoff=True
)
def fetch_match_and_team_id_task(self, message_id: str, channel_id: str) -> Dict[str, Any]:
    """Fetch match and team ID from message details."""
    logger.info(f"Processing message details", extra={
        'message_id': message_id,
        'channel_id': channel_id
    })
    
    try:
        with db_manager.session_scope(transaction_name='fetch_match_team_data') as session:
            # Query for message with related data
            message = session.query(ScheduledMessage).options(
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
                logger.error("No message found", extra={
                    'message_id': message_id,
                    'channel_id': channel_id
                })
                return {
                    'status': 'error',
                    'message': 'Message not found',
                    'error_type': 'message_not_found'
                }

            # Get team ID using helper function
            team_id = get_team_id_from_message(message, channel_id, message_id)
            if not team_id:
                logger.error("Could not determine team ID", extra={
                    'message_id': message_id,
                    'channel_id': channel_id
                })
                return {
                    'status': 'error',
                    'message': 'Team ID could not be determined',
                    'error_type': 'team_id_not_found'
                }

            # Prepare response data
            result_data = {
                'match_id': message.match_id,
                'team_id': team_id,
                'match_date': message.match.date.isoformat() if message.match else None,
                'team_name': (message.match.home_team.name 
                            if message.match and channel_id == message.home_channel_id 
                            else message.match.away_team.name if message.match 
                            else None),
                'fetched_at': datetime.utcnow().isoformat()
            }

            logger.info("Match and team data retrieved", extra=result_data)
            
            # Update message status
            message.last_fetch = datetime.utcnow()
            message.fetch_count = (message.fetch_count or 0) + 1
            session.flush()

            return {
                'status': 'success',
                'message': 'Match and team data retrieved successfully',
                'data': result_data
            }

    except SQLAlchemyError as e:
        logger.error(f"Database error fetching match and team ID: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error fetching match and team ID: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)

@celery_task(
    name='app.tasks.tasks_match_updates.update_match_details',
    bind=True,
    queue='discord',
    max_retries=3,
    retry_backoff=True
)
def update_match_details_task(self, match_id: str, update_info: Dict[str, Any]) -> Dict[str, Any]:
    """Update match details with proper session management."""
    try:
        # Validate update info
        required_fields = ['match_status', 'home_score', 'away_score', 'current_minute']
        if not all(field in update_info for field in required_fields):
            return {
                'success': False,
                'message': 'Missing required update fields',
                'required_fields': required_fields,
                'error_type': 'validation_error'
            }

        with db_manager.session_scope(transaction_name='update_match_details') as session:
            match = session.query(MLSMatch).get(match_id)
            if not match:
                return {
                    'success': False,
                    'message': f'Match {match_id} not found',
                    'error_type': 'match_not_found'
                }

            # Store previous state for change tracking
            previous_status = match.current_status
            previous_score = match.current_score

            # Update match details
            match.current_status = update_info['match_status']
            match.current_score = f"{update_info['home_score']}-{update_info['away_score']}"
            match.last_update_time = datetime.utcnow()
            match.current_minute = update_info['current_minute']
            match.update_count = (match.update_count or 0) + 1

            # Track significant changes
            if previous_status != match.current_status:
                match.previous_status = previous_status
                match.status_changed_at = datetime.utcnow()

            if previous_score != match.current_score:
                match.score_changed_at = datetime.utcnow()

            session.flush()

            result = {
                'id': match.id,
                'status': match.current_status,
                'score': match.current_score,
                'minute': match.current_minute,
                'update_count': match.update_count,
                'last_update': match.last_update_time.isoformat()
            }

            logger.info("Match details updated", extra=result)

            return {
                'success': True,
                'message': 'Match details updated successfully',
                'data': result
            }

    except SQLAlchemyError as e:
        logger.error(f"Database error updating match details: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error updating match details: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)

@celery_task(
    name='app.tasks.tasks_match_updates.get_active_matches',
    bind=True,
    queue='discord',
    max_retries=3
)
def get_active_matches_task(self) -> Dict[str, Any]:
    """Get all active matches that need updates."""
    try:
        with db_manager.session_scope(transaction_name='get_active_matches') as session:
            matches = session.query(MLSMatch).options(
                joinedload(MLSMatch.home_team),
                joinedload(MLSMatch.away_team)
            ).filter(
                MLSMatch.current_status.in_(['STATUS_IN_PROGRESS', 'STATUS_HALFTIME'])
            ).all()

            matches_data = [{
                'id': match.id,
                'match_id': match.match_id,
                'status': match.current_status,
                'score': match.current_score,
                'current_minute': match.current_minute,
                'last_update': match.last_update_time.isoformat() if match.last_update_time else None,
                'home_team': {
                    'name': match.home_team.name if match.home_team else None,
                    'id': match.home_team_id
                },
                'away_team': {
                    'name': match.away_team.name if match.away_team else None,
                    'id': match.away_team_id
                }
            } for match in matches]

            result = {
                'success': True,
                'message': f'Found {len(matches_data)} active matches',
                'data': matches_data,
                'timestamp': datetime.utcnow().isoformat()
            }

            logger.info("Retrieved active matches", extra={
                'match_count': len(matches_data),
                'status_counts': {
                    status: len([m for m in matches_data if m['status'] == status])
                    for status in set(m['status'] for m in matches_data)
                }
            })

            return result

    except SQLAlchemyError as e:
        logger.error(f"Database error getting active matches: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error getting active matches: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)