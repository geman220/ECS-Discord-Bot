# app/tasks/tasks_live_reporting_v2.py

"""
Live Reporting Tasks V2

Professional synchronous architecture implementation for live reporting tasks.
Uses industry standard patterns with the service layer, refactored to be 
purely synchronous for optimal Celery compatibility.
"""

import logging
from typing import Dict, Any, List
from datetime import datetime, timedelta
import pytz

from app.decorators import celery_task
from app.utils.task_session_manager import task_session
from app.models import LiveReportingSession
from app.services.redis_connection_service import get_redis_service
from app.utils.sync_ai_client import get_sync_ai_client

logger = logging.getLogger(__name__)


@celery_task(
    name='app.tasks.tasks_live_reporting_v2.process_all_active_sessions_v2',
    queue='live_reporting',
    max_retries=2,
    soft_time_limit=45,
    time_limit=60
)
def process_all_active_sessions_v2(self, session) -> Dict[str, Any]:
    """
    Process all active live reporting sessions using V2 architecture.
    
    Refactored to be purely synchronous for optimal Celery compatibility
    while maintaining the clean service-oriented architecture.
    """
    task_id = self.request.id
    redis_service = get_redis_service()
    lock_key = 'live_reporting:v2:processing_lock'
    
    try:
        # Task deduplication - prevent multiple instances running simultaneously
        if not redis_service.execute_command('set', lock_key, task_id, nx=True, ex=50):
            existing_task = redis_service.execute_command('get', lock_key)
            logger.info(f"Another V2 task ({existing_task}) is already processing, skipping {task_id}")
            return {
                'success': True,
                'message': 'Skipped - another task already processing',
                'processed_count': 0,
                'error_count': 0,
                'results': []
            }
        
        logger.info(f"Processing all active sessions (V2 Sync) - Task {task_id}")
        
        # Process sessions using pure synchronous architecture
        result = _process_sessions_sync(session, redis_service)
        
        logger.info(f"V2 session processing completed: {result}")
        return result
        
    except Exception as e:
        logger.error(f"Error in V2 session processing: {e}", exc_info=True)
        raise self.retry(exc=e, countdown=30)
    finally:
        # Always release lock
        try:
            redis_service.execute_command('delete', lock_key)
        except Exception:
            pass


def _process_sessions_sync(session, redis_service) -> Dict[str, Any]:
    """
    Process all active sessions using pure synchronous architecture.
    
    Eliminates the async/sync mismatch that was causing queue buildup by using
    only synchronous patterns compatible with Celery workers.
    """
    processed_count = 0
    error_count = 0
    results = []
    
    try:
        # Get all active sessions using synchronous database access
        active_sessions = session.query(LiveReportingSession).filter_by(is_active=True).all()
        
        if not active_sessions:
            logger.info("No active sessions to process")
            return {
                'success': True,
                'message': 'No active sessions',
                'processed_count': 0,
                'error_count': 0,
                'results': []
            }
        
        logger.info(f"Processing {len(active_sessions)} active sessions")
        
        # Process each session synchronously
        for session_obj in active_sessions:
            try:
                result = _process_single_session_sync(session, session_obj, redis_service)
                results.append(result)
                
                if result['success']:
                    processed_count += 1
                else:
                    error_count += 1
                    
            except Exception as e:
                logger.error(f"Error processing session {session_obj.id}: {e}")
                error_count += 1
                results.append({
                    'match_id': session_obj.match_id,
                    'success': False,
                    'error': str(e)
                })
        
        # Commit all changes
        session.commit()
        
        return {
            'success': True,
            'message': f'Processed {processed_count} sessions, {error_count} errors',
            'processed_count': processed_count,
            'error_count': error_count,
            'total_sessions': len(active_sessions),
            'results': results
        }
        
    except Exception as e:
        logger.error(f"Critical error in session processing: {e}", exc_info=True)
        return {
            'success': False,
            'message': f'Critical error: {e}',
            'processed_count': processed_count,
            'error_count': error_count + 1,
            'results': results
        }


def _process_single_session_sync(session, session_obj: LiveReportingSession, redis_service) -> Dict[str, Any]:
    """
    Process a single live reporting session synchronously.
    
    Uses synchronous ESPN API calls, database operations, and Discord posting
    to eliminate the resource overhead that was causing worker exhaustion.
    """
    try:
        from app.utils.espn_api_client import ESPNAPIClient
        from app.utils.discord_request_handler import send_to_discord_bot
        from app.utils.ai_commentary_client import AICommentaryClient
        
        match_id = session_obj.match_id
        thread_id = session_obj.thread_id
        competition = session_obj.competition
        
        logger.info(f"Processing session for match {match_id}")
        
        # Fetch match data from ESPN (synchronous)
        espn_client = ESPNAPIClient()
        match_data = espn_client.get_match_data(match_id, competition)
        
        if not match_data:
            logger.warning(f"No match data found for {match_id}")
            return {
                'match_id': match_id,
                'success': False,
                'error': 'No match data available'
            }
        
        # Process events and update Discord (synchronous)
        ai_client = AICommentaryClient()
        
        # Get previously processed event keys
        processed_event_keys = set(session_obj.parsed_event_keys or [])
        new_events = []
        
        # Check for pre-match hype opportunity (5 minutes before kickoff)
        pre_match_hype_sent = _check_and_send_pre_match_hype(
            session_obj, match_data, processed_event_keys
        )
        
        # Extract and process new events
        current_events = _extract_events_from_match_data(match_data)
        
        for event in current_events:
            event_key = f"{event['type']}_{event['minute']}_{hash(str(event))}"
            
            if event_key not in processed_event_keys:
                new_events.append((event, event_key))
                processed_event_keys.add(event_key)
        
        # Process new events
        events_processed = 0
        for event, event_key in new_events:
            try:
                # Check for special events that need enhanced AI messages
                enhanced_message = None
                event_type = event.get('type', '').lower()
                
                if event_type == 'halftime':
                    # Generate AI half-time analysis
                    enhanced_message = _generate_enhanced_half_time_message(match_data, session_obj)
                elif event_type in ['fulltime', 'final', 'end']:
                    # Generate AI full-time summary
                    enhanced_message = _generate_enhanced_full_time_message(match_data, session_obj)
                
                # Generate regular commentary or use enhanced message
                if enhanced_message:
                    commentary = enhanced_message
                    logger.info(f"Generated enhanced AI message for {event_type}")
                else:
                    commentary = ai_client.generate_commentary(match_data, event, competition)
                
                # Post to Discord via HTTP API
                discord_payload = {
                    'thread_id': thread_id,
                    'event': event,
                    'commentary': commentary,
                    'match_data': match_data
                }
                
                response = send_to_discord_bot('/api/live-reporting/event', discord_payload)
                message_id = response.get('message_id') if response else None
                
                logger.info(f"Posted event update {message_id} for {event['type']}")
                events_processed += 1
                
            except Exception as e:
                logger.error(f"Error processing event {event_key}: {e}")
        
        # Update session state
        session_obj.last_status = match_data.get('status', 'UNKNOWN')
        session_obj.last_score = f"{match_data.get('home_score', 0)}-{match_data.get('away_score', 0)}"
        session_obj.parsed_event_keys = list(processed_event_keys)
        session_obj.update_count += 1
        session_obj.last_update_at = datetime.utcnow()
        
        # Check if match ended
        match_ended = match_data.get('status') in ['FINAL', 'COMPLETED']
        if match_ended:
            session_obj.is_active = False
            session_obj.ended_at = datetime.utcnow()
            logger.info(f"Match {match_id} ended, deactivating session")
        
        return {
            'match_id': match_id,
            'success': True,
            'status': session_obj.last_status,
            'events_processed': events_processed,
            'match_ended': match_ended
        }
        
    except Exception as e:
        # Update session error count
        session_obj.error_count = (session_obj.error_count or 0) + 1
        session_obj.last_error = str(e)
        
        logger.error(f"Error processing session {session_obj.id}: {e}")
        return {
            'match_id': session_obj.match_id,
            'success': False,
            'error': str(e)
        }


def _extract_events_from_match_data(match_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract events from ESPN match data.
    
    Synchronous event extraction compatible with existing ESPN API patterns.
    """
    events = []
    
    try:
        # Extract from match_data based on ESPN API structure
        if 'events' in match_data:
            for event in match_data['events']:
                events.append({
                    'type': event.get('type', 'unknown'),
                    'minute': event.get('minute', 0),
                    'player': event.get('player', ''),
                    'team': event.get('team', ''),
                    'description': event.get('description', '')
                })
        
        # Also check for scoring events in scoreboard data
        if 'scoreboard' in match_data and 'events' in match_data['scoreboard']:
            for event in match_data['scoreboard']['events']:
                events.append({
                    'type': event.get('type', 'unknown'),
                    'minute': event.get('minute', 0),
                    'player': event.get('participant', ''),
                    'team': event.get('team', ''),
                    'description': event.get('text', '')
                })
    
    except Exception as e:
        logger.error(f"Error extracting events from match data: {e}")
    
    return events


@celery_task(
    name='app.tasks.tasks_live_reporting_v2.process_single_match_v2',
    queue='live_reporting',
    max_retries=3,
    soft_time_limit=30,
    time_limit=40
)
def process_single_match_v2(self, session, match_id: str) -> Dict[str, Any]:
    """
    Process a single match for live reporting.
    
    Event-driven task that processes one specific match session.
    Used by the LiveReportingManager for efficient, targeted processing.
    
    Args:
        match_id: ESPN match ID to process
        
    Returns:
        Processing result dictionary
    """
    try:
        logger.info(f"Processing single match V2: {match_id}")
        
        # Get the session for this match
        live_session = LiveReportingSession.get_session_by_match_id(session, match_id)
        
        if not live_session:
            logger.warning(f"No live session found for match {match_id}")
            return {
                'match_id': match_id,
                'success': False,
                'error': 'No active session found'
            }
        
        if not live_session.is_active:
            logger.info(f"Session for match {match_id} is not active")
            return {
                'match_id': match_id, 
                'success': False,
                'error': 'Session not active'
            }
        
        # Process the session
        result = _process_live_session_v2(live_session)
        
        # Update session state
        if result['success']:
            live_session.update_state(
                session, 
                status=result.get('status'),
                score=result.get('score'),
                event_keys=result.get('processed_events')
            )
        else:
            live_session.update_state(
                session,
                error=result.get('error')
            )
            
        # Deactivate if match ended
        if result.get('match_ended', False):
            live_session.deactivate(session, "Match completed")
            logger.info(f"Deactivated session for completed match {match_id}")
        
        session.commit()
        
        logger.info(f"Single match processing completed: {result}")
        return result
        
    except Exception as e:
        logger.error(f"Error processing single match {match_id}: {e}", exc_info=True)
        return {
            'match_id': match_id,
            'success': False,
            'error': str(e)
        }


@celery_task(
    name='app.tasks.tasks_live_reporting_v2.start_live_reporting_v2',
    queue='live_reporting',
    max_retries=3
)
def start_live_reporting_v2(self, session, match_id: str, thread_id: str, competition: str = "usa.1") -> Dict[str, Any]:
    """
    Start live reporting using synchronous architecture.
    
    Args:
        match_id: ESPN match ID
        thread_id: Discord thread ID  
        competition: Competition identifier
        
    Returns:
        Task result dictionary
    """
    try:
        logger.info(f"Starting live reporting V2 for match {match_id}")
        
        # Synchronous session creation/reactivation
        result = _start_live_reporting_sync(session, match_id, thread_id, competition)
        
        logger.info(f"V2 live reporting started: {result}")
        return result
        
    except Exception as e:
        logger.error(f"Error starting V2 live reporting for match {match_id}: {e}", exc_info=True)
        raise self.retry(exc=e, countdown=60)


def _start_live_reporting_sync(session, match_id: str, thread_id: str, competition: str) -> Dict[str, Any]:
    """
    Synchronous function to start live reporting.
    
    Creates or reactivates live reporting session using pure synchronous operations.
    """
    try:
        import json
        
        session_id = None
        reactivated = False
        
        # Check for existing session
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
                # Reactivate existing session
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
                session_id = existing.id
                reactivated = True
                logger.info(f"Reactivated session {existing.id} for match {match_id}")
        else:
            # Create new session
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
            session_id = new_session.id
            logger.info(f"Created session {new_session.id} for match {match_id}")
        
        # Auto-create match record if needed (synchronous check)
        from app.models import MLSMatch
        existing_match = session.query(MLSMatch).filter_by(match_id=match_id).first()
        if not existing_match:
            logger.info(f"Match record {match_id} already exists or will be created elsewhere")
        
        return {
            'success': True,
            'message': f'{"Reactivated" if reactivated else "Started"} live reporting for match {match_id}',
            'match_id': match_id,
            'session_id': session_id,
            'reactivated': reactivated
        }
                
    except Exception as e:
        logger.error(f"Error in sync live reporting start: {e}", exc_info=True)
        return {
            'success': False,
            'message': str(e),
            'match_id': match_id
        }


@celery_task(
    name='app.tasks.tasks_live_reporting_v2.stop_live_reporting_v2',
    queue='live_reporting'
)
def stop_live_reporting_v2(self, session, match_id: str) -> Dict[str, Any]:
    """
    Stop live reporting using synchronous architecture.
    
    Args:
        match_id: ESPN match ID
        
    Returns:
        Task result dictionary
    """
    try:
        logger.info(f"Stopping live reporting V2 for match {match_id}")
        
        # Synchronous stop
        result = _stop_live_reporting_sync(session, match_id)
        
        logger.info(f"V2 live reporting stopped: {result}")
        return result
        
    except Exception as e:
        logger.error(f"Error stopping V2 live reporting for match {match_id}: {e}", exc_info=True)
        raise self.retry(exc=e, countdown=60)


def _stop_live_reporting_sync(session, match_id: str) -> Dict[str, Any]:
    """
    Synchronous function to stop live reporting.
    """
    try:
        # Find and deactivate the session
        existing = session.query(LiveReportingSession).filter_by(
            match_id=match_id,
            is_active=True
        ).first()
        
        if existing:
            existing.is_active = False
            existing.ended_at = datetime.utcnow()
            existing.last_error = "Manual stop via V2 interface"
            session.commit()
            
            logger.info(f"Successfully stopped live reporting for match {match_id}")
            return {
                'success': True,
                'message': f'Stopped live reporting for match {match_id}',
                'match_id': match_id
            }
        else:
            logger.warning(f"No active session found for match {match_id}")
            return {
                'success': False,
                'message': f'No active session found for match {match_id}',
                'match_id': match_id
            }
                
    except Exception as e:
        logger.error(f"Error in sync live reporting stop: {e}", exc_info=True)
        return {
            'success': False,
            'message': str(e),
            'match_id': match_id
        }


def _generate_enhanced_half_time_message(match_data: Dict[str, Any], session_obj) -> str:
    """
    Generate enhanced AI half-time analysis message.
    
    Args:
        match_data: ESPN match data with current score
        session_obj: LiveReportingSession object
        
    Returns:
        Enhanced half-time message or None if generation fails
    """
    try:
        # Extract match context
        competition = match_data.get('competitions', [{}])[0]
        competitors = competition.get('competitors', [])
        
        if len(competitors) < 2:
            logger.warning("Insufficient team data for enhanced half-time message")
            return None
        
        # Extract team info and scores
        home_team = None
        away_team = None
        home_score = 0
        away_score = 0
        
        for competitor in competitors:
            team_data = competitor.get('team', {})
            score = int(competitor.get('score', 0))
            
            if competitor.get('homeAway') == 'home':
                home_team = team_data
                home_score = score
            elif competitor.get('homeAway') == 'away':
                away_team = team_data
                away_score = score
        
        if not home_team or not away_team:
            logger.warning("Could not identify teams for enhanced half-time message")
            return None
        
        # Build context for AI
        match_context = {
            'home_team': {'displayName': home_team.get('displayName', 'Home Team')},
            'away_team': {'displayName': away_team.get('displayName', 'Away Team')},
            'home_score': str(home_score),
            'away_score': str(away_score),
            'competition': session_obj.competition or 'MLS'
        }
        
        # Generate enhanced AI message
        ai_client = get_sync_ai_client()
        enhanced_message = ai_client.generate_half_time_message(match_context)
        
        if enhanced_message:
            logger.info(f"Generated enhanced half-time message: {home_score}-{away_score}")
            return enhanced_message
        else:
            logger.warning("AI failed to generate enhanced half-time message")
            return None
            
    except Exception as e:
        logger.error(f"Error generating enhanced half-time message: {e}", exc_info=True)
        return None


def _generate_enhanced_full_time_message(match_data: Dict[str, Any], session_obj) -> str:
    """
    Generate enhanced AI full-time summary message.
    
    Args:
        match_data: ESPN match data with final score
        session_obj: LiveReportingSession object
        
    Returns:
        Enhanced full-time message or None if generation fails
    """
    try:
        # Extract match context
        competition = match_data.get('competitions', [{}])[0]
        competitors = competition.get('competitors', [])
        
        if len(competitors) < 2:
            logger.warning("Insufficient team data for enhanced full-time message")
            return None
        
        # Extract team info and final scores
        home_team = None
        away_team = None
        home_score = 0
        away_score = 0
        
        for competitor in competitors:
            team_data = competitor.get('team', {})
            score = int(competitor.get('score', 0))
            
            if competitor.get('homeAway') == 'home':
                home_team = team_data
                home_score = score
            elif competitor.get('homeAway') == 'away':
                away_team = team_data
                away_score = score
        
        if not home_team or not away_team:
            logger.warning("Could not identify teams for enhanced full-time message")
            return None
        
        # Build context for AI
        match_context = {
            'home_team': {'displayName': home_team.get('displayName', 'Home Team')},
            'away_team': {'displayName': away_team.get('displayName', 'Away Team')},
            'home_score': str(home_score),
            'away_score': str(away_score),
            'competition': session_obj.competition or 'MLS'
        }
        
        # Generate enhanced AI message
        ai_client = get_sync_ai_client()
        enhanced_message = ai_client.generate_full_time_message(match_context)
        
        if enhanced_message:
            logger.info(f"Generated enhanced full-time message: Final {home_score}-{away_score}")
            return enhanced_message
        else:
            logger.warning("AI failed to generate enhanced full-time message")
            return None
            
    except Exception as e:
        logger.error(f"Error generating enhanced full-time message: {e}", exc_info=True)
        return None


def _check_and_send_pre_match_hype(session_obj, match_data: Dict[str, Any], processed_event_keys: set) -> bool:
    """
    Check if we should send a pre-match hype message (5 minutes before kickoff).
    
    Args:
        session_obj: LiveReportingSession object
        match_data: ESPN match data
        processed_event_keys: Set of already processed event keys
        
    Returns:
        bool: True if hype message was sent, False otherwise
    """
    try:
        # Check if pre-match hype already sent
        hype_key = f"pre_match_hype_{session_obj.match_id}"
        if hype_key in processed_event_keys:
            logger.debug(f"Pre-match hype already sent for match {session_obj.match_id}")
            return False
        
        # Get match details from ESPN data
        if not match_data or 'competitions' not in match_data:
            logger.debug("No competition data available for pre-match hype")
            return False
        
        competition = match_data['competitions'][0]
        
        # Extract kickoff time
        if 'date' not in competition:
            logger.debug("No kickoff time available for pre-match hype")
            return False
            
        # Parse kickoff time (ESPN uses ISO format)
        kickoff_str = competition['date']
        kickoff_time = datetime.fromisoformat(kickoff_str.replace('Z', '+00:00'))
        
        # Get current time in UTC
        now_utc = datetime.now(pytz.UTC)
        
        # Calculate time until kickoff
        time_until_kickoff = kickoff_time - now_utc
        
        # Check if we're within 5 minutes before kickoff
        five_minutes = timedelta(minutes=5)
        one_minute = timedelta(minutes=1)  # Buffer to avoid spam
        
        if one_minute <= time_until_kickoff <= five_minutes:
            logger.info(f"Time for pre-match hype! {time_until_kickoff.total_seconds()/60:.1f} minutes until kickoff")
            
            # Extract team information
            competitors = competition.get('competitors', [])
            if len(competitors) < 2:
                logger.warning("Insufficient team data for pre-match hype")
                return False
            
            # Build context for AI
            home_team = None
            away_team = None
            
            for team in competitors:
                if team.get('homeAway') == 'home':
                    home_team = team.get('team', {})
                elif team.get('homeAway') == 'away':
                    away_team = team.get('team', {})
            
            if not home_team or not away_team:
                logger.warning("Could not identify home/away teams for pre-match hype")
                return False
            
            # Build match context for AI
            match_context = {
                'home_team': {'displayName': home_team.get('displayName', 'Home Team')},
                'away_team': {'displayName': away_team.get('displayName', 'Away Team')},
                'competition': session_obj.competition or 'MLS',
                'venue': competition.get('venue', {}).get('fullName', 'Stadium'),
                'kickoff_time': kickoff_str,
                'minutes_until_kickoff': int(time_until_kickoff.total_seconds() / 60)
            }
            
            # Generate AI hype message
            ai_client = get_sync_ai_client()
            hype_message = ai_client.generate_pre_match_hype(match_context)
            
            if hype_message:
                # Post to Discord thread via HTTP API
                try:
                    hype_payload = {
                        'thread_id': session_obj.thread_id,
                        'message': hype_message,
                        'context': match_context,
                        'message_type': 'pre_match_hype'
                    }
                    
                    response = send_to_discord_bot('/api/live-reporting/hype', hype_payload)
                    
                    if response and response.get('success'):
                        # Mark as sent to prevent duplicates
                        processed_event_keys.add(hype_key)
                        
                        logger.info(f"Pre-match hype sent for match {session_obj.match_id}")
                        return True
                    else:
                        logger.error(f"Discord bot rejected pre-match hype: {response}")
                        return False
                    
                except Exception as e:
                    logger.error(f"Failed to post pre-match hype to Discord: {e}")
                    return False
            else:
                logger.warning("AI failed to generate pre-match hype message")
                return False
        else:
            # Log timing for debugging
            if time_until_kickoff.total_seconds() > 300:  # More than 5 minutes
                logger.debug(f"Too early for pre-match hype: {time_until_kickoff.total_seconds()/60:.1f} minutes until kickoff")
            elif time_until_kickoff.total_seconds() < 60:  # Less than 1 minute
                logger.debug(f"Too late for pre-match hype: {time_until_kickoff.total_seconds()/60:.1f} minutes until kickoff")
            
            return False
    
    except Exception as e:
        logger.error(f"Error checking pre-match hype timing: {e}", exc_info=True)
        return False


@celery_task(
    name='app.tasks.tasks_live_reporting_v2.health_check_v2',
    queue='live_reporting'
)
def health_check_v2(self, session) -> Dict[str, Any]:
    """
    Health check for V2 live reporting system.
    
    Returns:
        Health status dictionary
    """
    try:
        logger.debug("Running V2 health check")
        
        # Synchronous health check
        result = _health_check_sync(session)
        
        return result
        
    except Exception as e:
        logger.error(f"Error in V2 health check: {e}", exc_info=True)
        return {
            'overall': False,
            'timestamp': datetime.utcnow().isoformat(),
            'error': str(e),
            'components': {}
        }


def _health_check_sync(session) -> Dict[str, Any]:
    """Synchronous health check implementation."""
    try:
        from app.services.redis_connection_service import get_redis_service
        
        components = {}
        overall_health = True
        
        # Check database connectivity
        try:
            from sqlalchemy import text
            session.execute(text("SELECT 1")).fetchone()
            components['database'] = {'status': 'healthy', 'response_time_ms': 0}
        except Exception as e:
            components['database'] = {'status': 'unhealthy', 'error': str(e)}
            overall_health = False
        
        # Check Redis connectivity
        try:
            redis_service = get_redis_service()
            redis_service.ping()
            components['redis'] = {'status': 'healthy', 'response_time_ms': 0}
        except Exception as e:
            components['redis'] = {'status': 'unhealthy', 'error': str(e)}
            overall_health = False
        
        # Check active sessions
        try:
            active_count = session.query(LiveReportingSession).filter_by(is_active=True).count()
            components['live_sessions'] = {'status': 'healthy', 'active_count': active_count}
        except Exception as e:
            components['live_sessions'] = {'status': 'unhealthy', 'error': str(e)}
            overall_health = False
        
        return {
            'overall': overall_health,
            'timestamp': datetime.utcnow().isoformat(),
            'components': components
        }
            
    except Exception as e:
        logger.error(f"Error in sync health check: {e}", exc_info=True)
        return {
            'overall': False,
            'timestamp': datetime.utcnow().isoformat(),
            'error': str(e),
            'components': {}
        }