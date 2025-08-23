# app/tasks/tasks_robust_live_reporting.py

"""
Robust Live Reporting Tasks

This module implements a persistent live reporting system that survives
container restarts by storing session state in the database and using
Celery Beat periodic tasks instead of self-scheduling task chains.
"""

import logging
import json
import asyncio
import concurrent.futures
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from sqlalchemy.exc import SQLAlchemyError
from app.core.session_manager import managed_session
from app.core.helpers import get_match
from app.decorators import celery_task
from app.models import MLSMatch, LiveReportingSession
from app.match_api import process_live_match_updates
from app.services import fetch_espn_data

logger = logging.getLogger(__name__)


@celery_task(
    name='app.tasks.tasks_robust_live_reporting.process_all_active_sessions',
    bind=True,
    queue='live_reporting',
    max_retries=3
)
def process_all_active_sessions(self, session):
    """
    Periodic task that processes all active live reporting sessions.
    
    This task is called by Celery Beat every 30 seconds and checks
    all active sessions for updates. This replaces the old self-scheduling
    chain system with a robust periodic approach.
    """
    try:
        # Get all active sessions
        active_sessions = LiveReportingSession.get_active_sessions(session)
        
        if not active_sessions:
            logger.debug("No active live reporting sessions found")
            return {
                'success': True,
                'message': 'No active sessions',
                'processed_count': 0
            }
        
        logger.info(f"Processing {len(active_sessions)} active live reporting sessions")
        
        processed_count = 0
        failed_count = 0
        
        # Process each session independently with fresh database connections
        session_updates = []
        
        for session_obj in active_sessions:
            try:
                # Store session data we need
                session_data = {
                    'id': session_obj.id,
                    'match_id': session_obj.match_id,
                    'thread_id': session_obj.thread_id,
                    'competition': session_obj.competition,
                    'last_status': session_obj.last_status,
                    'last_score': session_obj.last_score,
                    'last_event_keys': json.loads(session_obj.last_event_keys) if session_obj.last_event_keys else None,
                    'error_count': session_obj.error_count
                }
                
                # Process session without holding database connection
                result = process_single_session_sync(
                    session_data['match_id'],
                    session_data['thread_id'],
                    session_data['competition'],
                    session_data['last_status'],
                    session_data['last_score'],
                    session_data['last_event_keys']
                )
                
                # Queue update for later
                session_updates.append({
                    'session_id': session_data['id'],
                    'match_id': session_data['match_id'],
                    'result': result,
                    'error_count': session_data['error_count']
                })
                
            except Exception as e:
                logger.error(f"Error processing session {session_obj.match_id}: {e}", exc_info=True)
                session_updates.append({
                    'session_id': session_obj.id,
                    'match_id': session_obj.match_id,
                    'result': {'success': False, 'message': str(e)},
                    'error_count': session_obj.error_count
                })
        
        # Now update all sessions with fresh transactions
        for update in session_updates:
            try:
                with managed_session() as fresh_session:
                    session_obj = fresh_session.query(LiveReportingSession).filter_by(id=update['session_id']).first()
                    if not session_obj:
                        continue
                        
                    result = update['result']
                    if result['success']:
                        session_obj.update_state(
                            fresh_session,
                            status=result.get('match_status'),
                            score=result.get('score'),
                            event_keys=result.get('event_keys')
                        )
                        
                        # Check if match ended
                        if result.get('match_status') in ['STATUS_FULL_TIME', 'STATUS_FINAL']:
                            session_obj.deactivate(fresh_session, "Match ended")
                            logger.info(f"Deactivated session for match {update['match_id']} - match ended")
                        
                        processed_count += 1
                    else:
                        # Handle failure
                        session_obj.update_state(fresh_session, error=result.get('message'))
                        failed_count += 1
                        
                        # Deactivate if too many errors
                        if session_obj.error_count >= 10:
                            session_obj.deactivate(fresh_session, f"Too many errors: {session_obj.error_count}")
                            logger.warning(f"Deactivated session for match {update['match_id']} - too many errors")
                    
                    # Commit happens automatically with managed_session
                    
            except Exception as db_error:
                logger.error(f"Database error updating session {update['match_id']}: {db_error}")
                failed_count += 1
        
        return {
            'success': True,
            'message': f'Processed {processed_count} sessions, {failed_count} failed',
            'processed_count': processed_count,
            'failed_count': failed_count,
            'total_sessions': len(active_sessions)
        }
        
    except Exception as e:
        logger.error(f"Error in process_all_active_sessions: {e}", exc_info=True)
        return {
            'success': False,
            'message': str(e),
            'processed_count': 0
        }


def process_single_session_sync(match_id: str, thread_id: str, competition: str,
                                last_status: Optional[str] = None,
                                last_score: Optional[str] = None,
                                last_event_keys: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Synchronous wrapper for process_single_session.
    Handles async operations without holding database connections.
    Preserves Flask app context for async execution.
    """
    try:
        # Import Flask context utilities
        from flask import has_app_context, copy_current_request_context
        from app.core import celery
        
        # Get the Flask app from Celery
        app = celery.flask_app
        
        def run_with_context():
            """Run async function with Flask app context."""
            with app.app_context():
                return asyncio.run(
                    process_single_session(
                        match_id, thread_id, competition,
                        last_status, last_score, last_event_keys
                    )
                )
        
        # Always use ThreadPoolExecutor to avoid event loop conflicts in Celery
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(run_with_context)
            return future.result(timeout=30)
    except Exception as e:
        logger.error(f"Error in process_single_session_sync: {e}", exc_info=True)
        return {
            'success': False,
            'message': str(e),
            'match_status': last_status,
            'score': last_score
        }


async def process_single_session(match_id: str, thread_id: str, competition: str,
                                last_status: Optional[str] = None,
                                last_score: Optional[str] = None,
                                last_event_keys: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Process a single live reporting session.
    
    This is the core logic extracted from the old task chain system,
    now used by the periodic task processor.
    """
    try:
        logger.debug(f"Processing session for match {match_id}")
        
        # Fetch ESPN data
        match_data = await fetch_espn_data(f"sports/soccer/{competition}/scoreboard/{match_id}")
        
        if not match_data or 'competitions' not in match_data:
            return {
                'success': False,
                'message': f'No ESPN data found for match {match_id}',
                'match_status': last_status,
                'score': last_score
            }
            
        # Extract match status and score
        competition_data = match_data["competitions"][0]
        new_status = competition_data["status"]["type"]["name"]
        
        home_score = competition_data['competitors'][0]['score']
        away_score = competition_data['competitors'][1]['score']
        new_score = f"{home_score}-{away_score}"
        
        # Check if match ended
        if new_status in ['STATUS_FULL_TIME', 'STATUS_FINAL']:
            logger.info(f"Match {match_id} ended with status {new_status}")
            
            # Process final update
            match_ended, current_event_keys = await process_live_match_updates(
                match_id, thread_id, match_data,
                session=None, last_status=last_status, last_score=last_score, last_event_keys=last_event_keys or []
            )
            
            return {
                'success': True,
                'message': 'Match ended',
                'match_status': new_status,
                'score': new_score,
                'event_keys': current_event_keys,
                'match_ended': match_ended
            }
        
        # Process live updates
        match_ended, current_event_keys = await process_live_match_updates(
            match_id, thread_id, match_data,
            session=None, last_status=last_status, last_score=last_score, last_event_keys=last_event_keys or []
        )
        
        return {
            'success': True,
            'message': 'Update processed',
            'match_status': new_status,
            'score': new_score,
            'event_keys': current_event_keys,
            'match_ended': match_ended
        }
        
    except Exception as e:
        logger.error(f"Error processing session for match {match_id}: {e}", exc_info=True)
        return {
            'success': False,
            'message': str(e),
            'match_status': last_status,
            'score': last_score
        }


@celery_task(
    name='app.tasks.tasks_robust_live_reporting.start_robust_live_reporting',
    bind=True,
    queue='live_reporting',
    max_retries=3
)
def start_robust_live_reporting(self, session, match_id: str, thread_id: str, competition: str) -> Dict[str, Any]:
    """
    Start robust live reporting for a match.
    
    Creates or reactivates a LiveReportingSession in the database.
    Auto-creates match record if it doesn't exist.
    The periodic task will automatically pick this up and start processing.
    """
    try:
        match_id_str = str(match_id)
        thread_id_str = str(thread_id)
        
        logger.info(f"Starting robust live reporting for match {match_id_str} ({competition})")
        
        # Auto-create match record if it doesn't exist
        from app.models import MLSMatch
        match = session.query(MLSMatch).filter_by(match_id=match_id_str).first()
        
        if not match:
            # Fetch match data from ESPN to create record
            from app.services.espn_service import get_espn_service
            from app.api_utils import async_to_sync
            
            logger.info(f"Match {match_id_str} not in database, fetching from ESPN...")
            espn_service = get_espn_service()
            match_data = async_to_sync(espn_service.get_match_data(match_id_str, competition))
            
            if match_data:
                # Extract match details
                competition_data = match_data.get('competitions', [{}])[0]
                competitors = competition_data.get('competitors', [])
                venue = competition_data.get('venue', {})
                date_str = match_data.get('date', '')
                
                home_team = competitors[0] if len(competitors) > 0 else {}
                away_team = competitors[1] if len(competitors) > 1 else {}
                
                # Parse date
                match_date = None
                if date_str:
                    try:
                        match_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                    except:
                        match_date = datetime.utcnow()
                
                # Create match record
                match = MLSMatch(
                    match_id=match_id_str,
                    competition=competition,
                    opponent=f"{home_team.get('team', {}).get('displayName', 'Unknown')} vs {away_team.get('team', {}).get('displayName', 'Unknown')}",
                    date_time=match_date or datetime.utcnow(),
                    is_home_game=False,  # Generic test match
                    venue=venue.get('fullName', 'Unknown Venue'),
                    discord_thread_id=thread_id_str,
                    thread_created=True,
                    live_reporting_scheduled=False,
                    live_reporting_started=False,
                    live_reporting_status='idle'
                )
                session.add(match)
                session.commit()
                logger.info(f"Auto-created match record for {match_id_str}")
            else:
                logger.warning(f"Could not fetch match data from ESPN for {match_id_str}, creating minimal record")
                # Create minimal match record
                from datetime import datetime
                match = MLSMatch(
                    match_id=match_id_str,
                    competition=competition,
                    opponent='Test Match',
                    date_time=datetime.utcnow(),
                    is_home_game=False,
                    venue='Test Venue',
                    discord_thread_id=thread_id_str,
                    thread_created=True,
                    live_reporting_scheduled=False,
                    live_reporting_started=False,
                    live_reporting_status='idle'
                )
                session.add(match)
                session.commit()
        else:
            # Update thread ID if provided and different
            if thread_id_str and match.discord_thread_id != thread_id_str:
                match.discord_thread_id = thread_id_str
                match.thread_created = True
                session.commit()
                logger.info(f"Updated thread ID for match {match_id_str}")
        
        # Check if session already exists
        existing_session = LiveReportingSession.get_session_by_match_id(session, match_id_str)
        
        if existing_session:
            if existing_session.is_active:
                logger.info(f"Live reporting already active for match {match_id_str}")
                return {
                    'success': True,
                    'message': f'Live reporting already active for match {match_id_str}',
                    'session_id': existing_session.id,
                    'reactivated': False
                }
            else:
                # Reactivate existing session
                existing_session.is_active = True
                existing_session.started_at = datetime.utcnow()
                existing_session.ended_at = None
                existing_session.thread_id = thread_id_str
                existing_session.error_count = 0
                existing_session.last_error = None
                session.add(existing_session)
                session.commit()
                
                logger.info(f"Reactivated live reporting session for match {match_id_str}")
                return {
                    'success': True,
                    'message': f'Reactivated live reporting for match {match_id_str}',
                    'session_id': existing_session.id,
                    'reactivated': True
                }
        
        # Create new session
        new_session = LiveReportingSession(
            match_id=match_id_str,
            competition=competition,
            thread_id=thread_id_str,
            is_active=True
        )
        
        session.add(new_session)
        session.commit()
        
        logger.info(f"Created new live reporting session for match {match_id_str} (session_id: {new_session.id})")
        
        return {
            'success': True,
            'message': f'Started robust live reporting for match {match_id_str}',
            'session_id': new_session.id,
            'reactivated': False
        }
        
    except Exception as e:
        logger.error(f"Error starting robust live reporting for match {match_id}: {e}", exc_info=True)
        return {
            'success': False,
            'message': str(e)
        }


@celery_task(
    name='app.tasks.tasks_robust_live_reporting.stop_robust_live_reporting',
    bind=True,
    queue='live_reporting',
    max_retries=3
)
def stop_robust_live_reporting(self, session, match_id: str, reason: str = "Manual stop") -> Dict[str, Any]:
    """
    Stop robust live reporting for a match.
    
    Deactivates the LiveReportingSession in the database.
    """
    try:
        match_id_str = str(match_id)
        
        logger.info(f"Stopping robust live reporting for match {match_id_str}: {reason}")
        
        # Find the session
        session_obj = LiveReportingSession.get_session_by_match_id(session, match_id_str)
        
        if not session_obj:
            logger.warning(f"No live reporting session found for match {match_id_str}")
            return {
                'success': False,
                'message': f'No live reporting session found for match {match_id_str}'
            }
        
        if not session_obj.is_active:
            logger.info(f"Live reporting session for match {match_id_str} already inactive")
            return {
                'success': True,
                'message': f'Live reporting for match {match_id_str} already stopped'
            }
        
        # Deactivate session
        session_obj.deactivate(session, reason)
        session.commit()
        
        logger.info(f"Stopped live reporting session for match {match_id_str}")
        
        return {
            'success': True,
            'message': f'Stopped live reporting for match {match_id_str}',
            'session_id': session_obj.id
        }
        
    except Exception as e:
        logger.error(f"Error stopping robust live reporting for match {match_id}: {e}", exc_info=True)
        return {
            'success': False,
            'message': str(e)
        }


@celery_task(
    name='app.tasks.tasks_robust_live_reporting.cleanup_old_sessions',
    bind=True,
    queue='live_reporting',
    max_retries=3
)
def cleanup_old_sessions(self, session) -> Dict[str, Any]:
    """
    Clean up old inactive sessions to prevent database bloat.
    
    Removes sessions that ended more than 7 days ago.
    """
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=7)
        
        old_sessions = session.query(LiveReportingSession).filter(
            LiveReportingSession.is_active == False,
            LiveReportingSession.ended_at < cutoff_date
        ).all()
        
        if not old_sessions:
            logger.debug("No old sessions to clean up")
            return {
                'success': True,
                'message': 'No old sessions to clean up',
                'cleaned_count': 0
            }
        
        logger.info(f"Cleaning up {len(old_sessions)} old live reporting sessions")
        
        for old_session in old_sessions:
            session.delete(old_session)
        
        session.commit()
        
        return {
            'success': True,
            'message': f'Cleaned up {len(old_sessions)} old sessions',
            'cleaned_count': len(old_sessions)
        }
        
    except Exception as e:
        logger.error(f"Error cleaning up old sessions: {e}", exc_info=True)
        return {
            'success': False,
            'message': str(e),
            'cleaned_count': 0
        }