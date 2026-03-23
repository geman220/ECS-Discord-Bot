# app/utils/live_reporting_helpers.py

"""
Live Reporting Session Helpers

Direct DB operations for creating/stopping LiveReportingSessions.
The RealtimeReportingService polls the DB for active sessions automatically,
so creating a session here is all that's needed to start live reporting.
"""

import json
import logging
from datetime import datetime
from typing import Dict, Any

from app.models import LiveReportingSession

logger = logging.getLogger(__name__)


def create_live_reporting_session(
    session,
    match_id: str,
    thread_id: str,
    competition: str = 'usa.1'
) -> Dict[str, Any]:
    """
    Create or reactivate a LiveReportingSession.

    The RealtimeReportingService polls the DB every 10-30s for active sessions
    and will automatically pick up this session for real-time processing.

    Args:
        session: SQLAlchemy database session
        match_id: ESPN match ID
        thread_id: Discord thread ID
        competition: Competition identifier (e.g., 'usa.1', 'MLS')

    Returns:
        Result dict with success status and session info
    """
    try:
        existing = session.query(LiveReportingSession).filter_by(
            match_id=match_id
        ).first()

        if existing:
            if existing.is_active:
                logger.info(f"Live reporting already active for match {match_id}")
                return {
                    'success': True,
                    'message': f'Live reporting already active for match {match_id}',
                    'match_id': match_id,
                    'session_id': existing.id,
                    'reactivated': False
                }
            else:
                existing.is_active = True
                existing.started_at = datetime.utcnow()
                existing.ended_at = None
                existing.thread_id = thread_id
                existing.competition = competition
                existing.error_count = 0
                existing.last_error = None
                existing.last_status = "STATUS_SCHEDULED"
                existing.last_score = "0-0"
                session.commit()
                logger.info(f"Reactivated session {existing.id} for match {match_id}")
                return {
                    'success': True,
                    'message': f'Reactivated live reporting for match {match_id}',
                    'match_id': match_id,
                    'session_id': existing.id,
                    'reactivated': True
                }
        else:
            new_session = LiveReportingSession(
                match_id=match_id,
                competition=competition,
                thread_id=thread_id,
                is_active=True,
                started_at=datetime.utcnow(),
                last_status="STATUS_SCHEDULED",
                last_score="0-0",
                last_event_keys=json.dumps([]),
                update_count=0,
                error_count=0
            )
            session.add(new_session)
            session.commit()
            logger.info(f"Created live reporting session {new_session.id} for match {match_id}")
            return {
                'success': True,
                'message': f'Started live reporting for match {match_id}',
                'match_id': match_id,
                'session_id': new_session.id,
                'reactivated': False
            }

    except Exception as e:
        logger.error(f"Error creating live reporting session for match {match_id}: {e}", exc_info=True)
        return {
            'success': False,
            'message': str(e),
            'match_id': match_id
        }


def stop_live_reporting_session(session, match_id: str) -> Dict[str, Any]:
    """
    Deactivate a live reporting session.

    The RealtimeReportingService will stop processing this session
    on its next polling cycle (within 10-30s).

    Args:
        session: SQLAlchemy database session
        match_id: ESPN match ID

    Returns:
        Result dict with success status
    """
    try:
        existing = session.query(LiveReportingSession).filter_by(
            match_id=match_id,
            is_active=True
        ).first()

        if existing:
            existing.is_active = False
            existing.ended_at = datetime.utcnow()
            existing.last_error = "Manual stop"
            session.commit()
            logger.info(f"Stopped live reporting session {existing.id} for match {match_id}")
            return {
                'success': True,
                'message': f'Stopped live reporting for match {match_id}',
                'match_id': match_id,
                'session_id': existing.id
            }
        else:
            logger.warning(f"No active session found for match {match_id}")
            return {
                'success': False,
                'message': f'No active session found for match {match_id}',
                'match_id': match_id
            }

    except Exception as e:
        logger.error(f"Error stopping live reporting for match {match_id}: {e}", exc_info=True)
        return {
            'success': False,
            'message': str(e),
            'match_id': match_id
        }
