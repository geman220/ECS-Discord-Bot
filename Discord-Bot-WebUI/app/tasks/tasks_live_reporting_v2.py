# app/tasks/tasks_live_reporting_v2.py

"""
Live Reporting Tasks V2 - Real-Time Match Updates

Optimized for real-time live match reporting with efficient ESPN API polling.
Checks every 10-30 seconds during live matches for near real-time updates.
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import time
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
    soft_time_limit=25,
    time_limit=30
)
def process_all_active_sessions_v2(self, session) -> Dict[str, Any]:
    """
    Process all active live reporting sessions (DEPRECATED - V2 LEGACY).

    ⚠️ DEPRECATION WARNING: This V2 Celery-based approach is deprecated!

    NEW ARCHITECTURE:
    - Celery handles scheduling (match threads, session start/stop)
    - Dedicated real-time service handles live updates
    - This task is kept for backward compatibility only

    The new hybrid approach:
    1. MatchSchedulerService creates threads 48hrs before
    2. MatchSchedulerService starts live sessions 5min before
    3. RealtimeReportingService handles actual live updates
    """
    task_id = self.request.id
    redis_service = get_redis_service()

    logger.error(
        f"*** DEPRECATED V2 TASK CALLED! *** "
        f"V2 Celery task {task_id} called when enterprise system is available. "
        f"CALLING LOCATION: {self.request.origin} "
        f"TIME: {datetime.utcnow().isoformat()} "
        f"MIGRATION REQUIRED: Remove calls to process_all_active_sessions_v2 and use MatchSchedulerService + RealtimeReportingService instead."
    )

    # Check if real-time service is running
    realtime_status = redis_service.get('realtime_service:status')
    if realtime_status == 'running':
        logger.info("Real-time service is active, skipping legacy V2 processing")
        return {
            'success': True,
            'message': 'Delegated to real-time service',
            'processed_count': 0,
            'error_count': 0,
            'results': [],
            'deprecated': True,
            'realtime_service_active': True
        }

    # Fallback processing if real-time service not available
    logger.error(
        f"*** V2 FALLBACK ACTIVATED! *** "
        f"Real-time service not available, using deprecated V2 processing for task {task_id}. "
        f"URGENT: Start RealtimeReportingService or investigate why it's offline. "
        f"This fallback should only be used temporarily."
    )
    return _process_sessions_legacy_fallback(session, redis_service, task_id)


def _process_sessions_legacy_fallback(session, redis_service, task_id) -> Dict[str, Any]:
    """
    Legacy fallback processing when real-time service is not available.

    This maintains the original V2 functionality as a safety net.
    """
    lock_key = 'live_reporting:v2:processing_lock'

    try:
        # Task deduplication - prevent multiple instances running simultaneously
        if not redis_service.execute_command('set', lock_key, task_id, nx=True, ex=40):
            existing_task = redis_service.execute_command('get', lock_key)
            logger.info(f"Another V2 task ({existing_task}) is already processing, skipping {task_id}")
            return {
                'success': True,
                'message': 'Skipped - another task already processing',
                'processed_count': 0,
                'error_count': 0,
                'results': []
            }

        logger.info(f"Processing live sessions (V2 Legacy Fallback) - Task {task_id}")

        # Process sessions with legacy real-time focus
        result = _process_sessions_realtime(session, redis_service, task_id)

        # Schedule next real-time update if there are live matches
        if result.get('live_matches', 0) > 0:
            delay = _calculate_next_update_delay(result)
            logger.info(f"Scheduling next legacy update in {delay} seconds")
            process_all_active_sessions_v2.apply_async(countdown=delay)

        logger.info(f"V2 legacy processing completed: {result}")
        return result

    except Exception as e:
        logger.error(f"Error in V2 legacy session processing: {e}", exc_info=True)
        raise self.retry(exc=e, countdown=15)
    finally:
        # Always release lock
        try:
            redis_service.execute_command('delete', lock_key)
        except Exception:
            pass


def _process_sessions_realtime(session, redis_service, task_id) -> Dict[str, Any]:
    """
    Process active sessions with real-time focus.

    REAL-TIME STRATEGY:
    - Only process sessions for matches that are LIVE or about to start
    - Skip scheduled matches that are hours away
    - Prioritize IN_PLAY matches for fastest updates
    """
    processed_count = 0
    error_count = 0
    live_matches = 0
    skipped_count = 0
    results = []

    try:
        # Get all active sessions
        active_sessions = session.query(LiveReportingSession).filter_by(is_active=True).all()

        if not active_sessions:
            logger.info("No active sessions to process")
            return {
                'success': True,
                'message': 'No active sessions',
                'processed_count': 0,
                'error_count': 0,
                'live_matches': 0,
                'results': []
            }

        # Filter sessions that need real-time updates
        realtime_sessions = []
        for session_obj in active_sessions:
            if _should_process_realtime(session_obj):
                realtime_sessions.append(session_obj)
            else:
                skipped_count += 1

        logger.info(f"Processing {len(realtime_sessions)} real-time sessions, skipped {skipped_count}")

        # Process each session
        for session_obj in realtime_sessions:
            try:
                result = _process_single_session_realtime(session, session_obj, redis_service)
                results.append(result)

                if result['success']:
                    processed_count += 1
                    if result.get('is_live', False):
                        live_matches += 1
                else:
                    error_count += 1

            except Exception as e:
                logger.error(f"Error processing session {session_obj.id}: {e}")
                error_count += 1
                results.append({
                    'session_id': session_obj.id,
                    'match_id': session_obj.match_id,
                    'success': False,
                    'error': str(e)
                })

        # Commit all changes
        session.commit()

        return {
            'success': True,
            'message': f'Processed {processed_count} sessions, {error_count} errors, {live_matches} live',
            'processed_count': processed_count,
            'error_count': error_count,
            'live_matches': live_matches,
            'skipped_count': skipped_count,
            'total_sessions': len(active_sessions),
            'task_id': task_id,
            'results': results
        }

    except Exception as e:
        logger.error(f"Critical error in real-time processing: {e}", exc_info=True)
        return {
            'success': False,
            'message': f'Critical error: {e}',
            'processed_count': processed_count,
            'error_count': error_count + 1,
            'live_matches': live_matches,
            'results': results
        }


def _should_process_realtime(session_obj: LiveReportingSession) -> bool:
    """
    Determine if a session needs real-time processing.

    REAL-TIME CRITERIA:
    - Match is currently IN_PLAY or HALFTIME
    - Match starts within next 30 minutes
    - Session hasn't been updated in last 20 seconds (rate limiting)
    """
    now = datetime.utcnow()

    # Always process if match is live
    if session_obj.last_status in ['IN_PLAY', 'HALFTIME']:
        # Rate limit: don't update same session more than every 10 seconds
        if session_obj.last_update_at:
            seconds_since_update = (now - session_obj.last_update_at).total_seconds()
            return seconds_since_update >= 10
        return True

    # Process if match starts soon (within 30 minutes)
    if hasattr(session_obj, 'match') and session_obj.match and session_obj.match.date:
        time_to_match = (session_obj.match.date - now).total_seconds()
        if 0 <= time_to_match <= 1800:  # 30 minutes
            # Less frequent updates for pre-match (every 5 minutes)
            if session_obj.last_update_at:
                seconds_since_update = (now - session_obj.last_update_at).total_seconds()
                return seconds_since_update >= 300
            return True

    # Skip matches that are far away or already finished
    if session_obj.last_status in ['FINAL', 'COMPLETED', 'CANCELLED', 'POSTPONED']:
        return False

    # Process scheduled matches at least every 15 minutes to check status
    if session_obj.last_update_at:
        seconds_since_update = (now - session_obj.last_update_at).total_seconds()
        return seconds_since_update >= 900  # 15 minutes

    return True  # Process if never updated


def _calculate_next_update_delay(result: Dict[str, Any]) -> int:
    """
    Calculate optimal delay for next real-time update.

    REAL-TIME SCHEDULING:
    - Live matches: 10-15 seconds
    - Pre-match (soon): 60 seconds
    - General monitoring: 5 minutes
    """
    live_matches = result.get('live_matches', 0)

    if live_matches > 0:
        # Real-time updates for live matches
        return 10 if live_matches > 3 else 15

    processed_count = result.get('processed_count', 0)
    if processed_count > 0:
        # Some sessions processed - check again in 1 minute
        return 60

    # No active sessions needing real-time updates - check every 5 minutes
    return 300


def _process_single_session_realtime(session, session_obj: LiveReportingSession, redis_service) -> Dict[str, Any]:
    """
    Process a single live reporting session with real-time ESPN API integration.

    REAL-TIME PROCESSING:
    - Fetches fresh data from ESPN API
    - Processes new events immediately
    - Posts to Discord in near real-time
    """
    try:
        from app.utils.espn_api_client import ESPNAPIClient
        from app.utils.discord_request_handler import send_to_discord_bot

        match_id = session_obj.match_id
        thread_id = session_obj.thread_id
        competition = session_obj.competition or 'eng.1'

        logger.info(f"Real-time processing session {session_obj.id} for match {match_id}")

        # Fetch fresh match data from ESPN API
        espn_client = ESPNAPIClient()
        match_data = espn_client.get_match_data(match_id, competition)

        if not match_data or match_data.get('status') == 'UNAVAILABLE':
            logger.warning(f"No match data available for {match_id}")
            # Increment error count but don't fail completely
            session_obj.error_count = (session_obj.error_count or 0) + 1
            session_obj.last_error = "ESPN API unavailable"
            return {
                'session_id': session_obj.id,
                'match_id': match_id,
                'success': False,
                'error': 'ESPN API unavailable',
                'is_live': False
            }

        current_status = match_data.get('status', 'UNKNOWN')
        is_live = current_status in ['IN_PLAY', 'HALFTIME']

        # Process new events
        events_processed = _process_match_events(session_obj, match_data, thread_id)

        # Send status updates if status changed
        if session_obj.last_status != current_status:
            _send_status_update(thread_id, session_obj.last_status, current_status, match_data)

        # Update session state
        session_obj.last_status = current_status
        session_obj.last_score = f"{match_data.get('home_score', 0)}-{match_data.get('away_score', 0)}"
        session_obj.update_count = (session_obj.update_count or 0) + 1
        session_obj.last_update_at = datetime.utcnow()
        session_obj.error_count = 0  # Reset error count on success
        session_obj.last_error = None

        # Check if match ended
        match_ended = current_status in ['FINAL', 'COMPLETED', 'CANCELLED', 'POSTPONED']
        if match_ended and session_obj.is_active:
            session_obj.is_active = False
            session_obj.ended_at = datetime.utcnow()
            logger.info(f"Match {match_id} ended with status {current_status}")

            # Send final message
            _send_final_message(thread_id, match_data)

        logger.info(f"Session {session_obj.id}: {events_processed} events, status={current_status}, live={is_live}")

        return {
            'session_id': session_obj.id,
            'match_id': match_id,
            'success': True,
            'status': current_status,
            'score': session_obj.last_score,
            'events_processed': events_processed,
            'is_live': is_live,
            'match_ended': match_ended
        }

    except Exception as e:
        # Update session error count
        session_obj.error_count = (session_obj.error_count or 0) + 1
        session_obj.last_error = str(e)[:500]

        # Deactivate session if too many errors
        if session_obj.error_count >= 5:
            session_obj.is_active = False
            session_obj.ended_at = datetime.utcnow()
            logger.error(f"Deactivating session {session_obj.id} after {session_obj.error_count} errors")

        logger.error(f"Error processing session {session_obj.id}: {e}")
        return {
            'session_id': session_obj.id,
            'match_id': session_obj.match_id,
            'success': False,
            'error': str(e),
            'is_live': False
        }


def _process_match_events(session_obj: LiveReportingSession, match_data: Dict[str, Any], thread_id: str) -> int:
    """
    Process and send new match events to Discord.

    Returns number of events processed.
    """
    events_processed = 0

    try:
        # Get previously processed events
        processed_event_keys = set(session_obj.parsed_event_keys or [])

        # Extract current events from match data
        current_events = match_data.get('events', [])

        for event in current_events:
            # Generate unique event key
            event_key = _generate_event_key(event)

            if event_key not in processed_event_keys:
                # Send event to Discord
                if _send_event_to_discord(thread_id, event, match_data):
                    processed_event_keys.add(event_key)
                    events_processed += 1
                    logger.info(f"Sent {event.get('type')} event for match {session_obj.match_id}")

        # Update processed events list
        session_obj.parsed_event_keys = list(processed_event_keys)

    except Exception as e:
        logger.error(f"Error processing match events: {e}")

    return events_processed


def _generate_event_key(event: Dict[str, Any]) -> str:
    """
    Generate unique key for an event to prevent duplicates.
    """
    event_type = event.get('type', 'unknown')
    minute = str(event.get('minute', '0'))
    player = event.get('player', '')
    team = event.get('team', '')

    # Create deterministic key
    return f"{event_type}:{minute}:{player}:{team}"


def _send_event_to_discord(thread_id: str, event: Dict[str, Any], match_data: Dict[str, Any]) -> bool:
    """
    Send match event to Discord thread.
    """
    try:
        from app.utils.discord_request_handler import send_to_discord_bot

        # Format event message based on type
        message = _format_event_message(event, match_data)

        payload = {
            'thread_id': thread_id,
            'content': message,
            'event_type': event.get('type'),
            'match_data': {
                'home_team': match_data.get('home_team'),
                'away_team': match_data.get('away_team'),
                'home_score': match_data.get('home_score'),
                'away_score': match_data.get('away_score'),
                'minute': match_data.get('minute'),
                'status': match_data.get('status')
            }
        }

        response = send_to_discord_bot('/api/live-reporting/event', payload)
        return response and response.get('success', False)

    except Exception as e:
        logger.error(f"Error sending event to Discord: {e}")
        return False


def _format_event_message(event: Dict[str, Any], match_data: Dict[str, Any]) -> str:
    """
    Format match event into Discord message.
    """
    event_type = event.get('type', '').upper()
    minute = event.get('minute', '0')
    player = event.get('player', 'Unknown')
    team = event.get('team', 'Unknown')

    # Get current score
    home_score = match_data.get('home_score', 0)
    away_score = match_data.get('away_score', 0)
    home_team = match_data.get('home_team', 'Home')
    away_team = match_data.get('away_team', 'Away')

    if event_type == 'GOAL':
        return f"⚽ **GOAL!** {minute}' - {player} ({team})\n\n**{home_team}** {home_score} - {away_score} **{away_team}**"

    elif event_type == 'YELLOW_CARD':
        return f"🟨 **Yellow Card** {minute}' - {player} ({team})"

    elif event_type == 'RED_CARD':
        return f"🟥 **Red Card** {minute}' - {player} ({team})"

    elif event_type == 'SUBSTITUTION':
        return f"🔄 **Substitution** {minute}' - {team}\n{event.get('description', player)}"

    else:
        return f"📝 **{minute}'** - {event.get('description', f'{event_type} by {player}')}"


def _send_status_update(thread_id: str, old_status: str, new_status: str, match_data: Dict[str, Any]):
    """
    Send match status change update to Discord.
    """
    try:
        from app.utils.discord_request_handler import send_to_discord_bot

        # Only send important status changes
        if new_status in ['IN_PLAY', 'HALFTIME', 'FINAL', 'COMPLETED']:
            message = _format_status_message(new_status, match_data)

            if message:
                payload = {
                    'thread_id': thread_id,
                    'content': message,
                    'event_type': 'status_change'
                }

                send_to_discord_bot('/api/live-reporting/status', payload)
                logger.info(f"Sent status update: {old_status} -> {new_status}")

    except Exception as e:
        logger.error(f"Error sending status update: {e}")


def _format_status_message(status: str, match_data: Dict[str, Any]) -> Optional[str]:
    """
    Format status change into Discord message.
    """
    home_team = match_data.get('home_team', 'Home')
    away_team = match_data.get('away_team', 'Away')

    if status == 'IN_PLAY':
        return f"🟢 **KICK-OFF!** {home_team} vs {away_team}"

    elif status == 'HALFTIME':
        home_score = match_data.get('home_score', 0)
        away_score = match_data.get('away_score', 0)
        return f"⏸️ **HALF-TIME**\n\n**{home_team}** {home_score} - {away_score} **{away_team}**"

    elif status in ['FINAL', 'COMPLETED']:
        home_score = match_data.get('home_score', 0)
        away_score = match_data.get('away_score', 0)
        return f"🏁 **FULL-TIME**\n\n**{home_team}** {home_score} - {away_score} **{away_team}**"

    return None


def _send_final_message(thread_id: str, match_data: Dict[str, Any]):
    """
    Send final match summary message.
    """
    try:
        from app.utils.discord_request_handler import send_to_discord_bot

        home_team = match_data.get('home_team', 'Home')
        away_team = match_data.get('away_team', 'Away')
        home_score = match_data.get('home_score', 0)
        away_score = match_data.get('away_score', 0)

        # Determine result
        if home_score > away_score:
            result = f"🏆 {home_team} wins!"
        elif away_score > home_score:
            result = f"🏆 {away_team} wins!"
        else:
            result = "🤝 It's a draw!"

        message = f"""
🏁 **MATCH FINISHED**

**{home_team}** {home_score} - {away_score} **{away_team}**

{result}

Thanks for following the live updates! 📺
"""

        payload = {
            'thread_id': thread_id,
            'content': message,
            'event_type': 'final'
        }

        send_to_discord_bot('/api/live-reporting/final', payload)
        logger.info(f"Sent final message for {home_team} vs {away_team}")

    except Exception as e:
        logger.error(f"Error sending final message: {e}")


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