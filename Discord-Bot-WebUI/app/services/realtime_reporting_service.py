# app/services/realtime_reporting_service.py

"""
Dedicated Real-Time Live Reporting Service

A standalone service that handles real-time match updates during live games.
This service runs independently of Celery and focuses solely on:
- Polling ESPN API every 10-15 seconds for live matches
- Processing match events and score changes
- Sending updates to Discord via bot API
- Managing session lifecycles

Designed to work with the MatchSchedulerService for complete automation.
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional, Set
from datetime import datetime, timedelta
import json

from app.models import LiveReportingSession, MLSMatch
from app.services.redis_connection_service import get_redis_service
from app.utils.espn_api_client import ESPNAPIClient
from app.utils.discord_request_handler import send_to_discord_bot
from app.utils.task_session_manager import task_session
from app.utils.sync_ai_client import get_sync_ai_client

logger = logging.getLogger(__name__)


class RealtimeReportingService:
    """
    Dedicated real-time live reporting service.

    This service runs as a separate process/thread and handles:
    1. Continuous monitoring of active live sessions
    2. Real-time ESPN API polling (10-15s intervals)
    3. Event processing and Discord updates
    4. Session state management and cleanup
    """

    def __init__(self):
        self.redis_service = get_redis_service()
        self.espn_client = ESPNAPIClient()
        self.ai_client = get_sync_ai_client()  # Enhanced AI for commentary
        self.is_running = False
        self.active_sessions: Dict[int, Dict[str, Any]] = {}
        self.last_events: Dict[int, Set[str]] = {}  # Track processed events by session
        self.match_history: Dict[int, List[Dict[str, Any]]] = {}  # Track match history per session

    async def start_service(self):
        """Start the real-time reporting service."""
        if self.is_running:
            logger.warning("Real-time service already running")
            return

        self.is_running = True
        logger.info("Starting real-time live reporting service")

        # Set status in Redis to coordinate with Celery tasks
        self.redis_service.execute_command('setex', 'realtime_service:status', 300, 'running')

        try:
            await self._main_loop()
        except Exception as e:
            logger.error(f"Fatal error in real-time service: {e}")
        finally:
            self.is_running = False
            # Clear status in Redis using execute_command
            self.redis_service.execute_command('del', 'realtime_service:status')

    async def stop_service(self):
        """Stop the real-time reporting service."""
        logger.info("Stopping real-time live reporting service")
        self.is_running = False

    async def _main_loop(self):
        """Main service loop - runs continuously while service is active."""
        last_heartbeat = datetime.utcnow()

        while self.is_running:
            try:
                # Maintain heartbeat in Redis every 60 seconds
                now = datetime.utcnow()
                if (now - last_heartbeat).seconds >= 60:
                    self.redis_service.execute_command('setex', 'realtime_service:status', 300, 'running')
                    self.redis_service.execute_command('setex', 'realtime_service:heartbeat', 120, now.isoformat())
                    last_heartbeat = now

                # Load active sessions from database
                await self._refresh_active_sessions()

                if not self.active_sessions:
                    # No active sessions, check less frequently
                    await asyncio.sleep(30)
                    continue

                # Process all active sessions
                await self._process_active_sessions()

                # Determine next check interval based on active matches
                sleep_interval = self._get_next_interval()
                await asyncio.sleep(sleep_interval)

            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                await asyncio.sleep(10)  # Brief pause on error

    async def _refresh_active_sessions(self):
        """Load active live reporting sessions from database."""
        try:
            with task_session() as session:
                active_sessions = session.query(LiveReportingSession).filter_by(
                    is_active=True
                ).all()

                # Update our local cache
                current_sessions = {}
                for live_session in active_sessions:
                    session_data = {
                        'id': live_session.id,
                        'match_id': live_session.match_id,
                        'thread_id': live_session.thread_id,
                        'competition': live_session.competition,
                        'started_at': live_session.started_at,
                        'last_update': live_session.last_update,
                        'update_count': getattr(live_session, 'update_count', 0),
                        'error_count': getattr(live_session, 'error_count', 0)
                    }

                    # Get match details - handle both match_id (ESPN ID) and id (database primary key)
                    match = session.query(MLSMatch).filter_by(match_id=live_session.match_id).first()
                    if not match:
                        # Try looking up by database ID if match_id didn't work
                        try:
                            match = session.query(MLSMatch).filter_by(id=int(live_session.match_id)).first()
                        except (ValueError, TypeError):
                            pass

                    if match:
                        # For MLSMatch, we have opponent and is_home_game
                        home_team = "LAFC" if match.is_home_game else match.opponent
                        away_team = match.opponent if match.is_home_game else "LAFC"

                        session_data.update({
                            'home_team': home_team,
                            'away_team': away_team,
                            'match_date': match.date_time,
                            'opponent': match.opponent,
                            'is_home_game': match.is_home_game,
                            'venue': match.venue or 'TBD',
                            'competition': match.competition or 'MLS',
                            'espn_match_id': match.espn_match_id
                        })

                    current_sessions[live_session.id] = session_data

                    # Initialize event tracking if new session
                    if live_session.id not in self.last_events:
                        self.last_events[live_session.id] = set()

                # Clean up old sessions from our cache
                old_session_ids = set(self.active_sessions.keys()) - set(current_sessions.keys())
                for old_id in old_session_ids:
                    if old_id in self.last_events:
                        del self.last_events[old_id]

                self.active_sessions = current_sessions

                if self.active_sessions:
                    logger.debug(f"Monitoring {len(self.active_sessions)} active live sessions")

        except Exception as e:
            logger.error(f"Error refreshing active sessions: {e}")

    async def _process_active_sessions(self):
        """Process all active sessions for real-time updates."""
        tasks = []

        for session_id, session_data in self.active_sessions.items():
            if session_data.get('espn_match_id'):
                task = asyncio.create_task(
                    self._process_session_realtime(session_id, session_data)
                )
                tasks.append(task)

        if tasks:
            # Process all sessions concurrently
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _process_session_realtime(self, session_id: int, session_data: Dict[str, Any]):
        """Process a single live session for real-time updates."""
        try:
            espn_match_id = session_data.get('espn_match_id')
            if not espn_match_id:
                logger.warning(f"No ESPN match ID for session {session_id}")
                return

            # Get match data from ESPN with correct competition
            competition = session_data.get('competition', 'usa.1')  # Default to MLS if not specified
            match_data = self.espn_client.get_match_data(espn_match_id, competition)
            if not match_data:
                await self._handle_session_error(session_id, "Failed to fetch match data")
                return

            # Check if match is actually live
            if not self._is_match_live(match_data):
                # Match ended or not started, deactivate session
                await self._deactivate_session(session_id, "Match no longer live")
                return

            # Process any new events
            new_events = await self._extract_new_events(session_id, match_data)
            if new_events:
                await self._send_events_to_discord(session_id, session_data, new_events)

            # Update session stats
            await self._update_session_stats(session_id)

        except Exception as e:
            logger.error(f"Error processing session {session_id}: {e}")
            await self._handle_session_error(session_id, str(e))

    def _is_match_live(self, match_data: Dict[str, Any]) -> bool:
        """Check if match is currently live."""
        # Handle different data structures
        if isinstance(match_data.get('status'), str):
            # Our mock data format
            status = match_data.get('status', '')
        else:
            # ESPN API format
            status = match_data.get('status', {}).get('type', {}).get('name', '')

        return status.upper() in ['IN_PLAY', 'HALFTIME', 'SECOND_HALF']

    async def _extract_new_events(self, session_id: int, match_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract new events that haven't been processed yet."""
        new_events = []

        try:
            # Get current events from match data
            events = match_data.get('events', [])

            # Track processed events for this session
            processed_events = self.last_events.get(session_id, set())

            for event in events:
                # Create unique event ID
                event_id = f"{event.get('id', 'unknown')}_{event.get('minute', 0)}"

                if event_id not in processed_events:
                    new_events.append(event)
                    processed_events.add(event_id)

            # Update processed events cache
            self.last_events[session_id] = processed_events

            # Also check for score changes
            current_score = self._get_current_score(match_data)
            last_score_key = f"last_score_{session_id}"
            last_score = self.redis_service.execute_command('get', last_score_key)

            if last_score != current_score:
                # Score changed, add score update event
                if last_score is not None:  # Don't send on first check
                    new_events.append({
                        'type': 'score_update',
                        'current_score': current_score,
                        'previous_score': last_score
                    })

                self.redis_service.execute_command('setex', last_score_key, 3600, current_score)

        except Exception as e:
            logger.error(f"Error extracting events for session {session_id}: {e}")

        return new_events

    def _get_current_score(self, match_data: Dict[str, Any]) -> str:
        """Extract current score from match data."""
        try:
            competitors = match_data.get('competitions', [{}])[0].get('competitors', [])
            if len(competitors) >= 2:
                home_score = competitors[0].get('score', '0')
                away_score = competitors[1].get('score', '0')
                return f"{home_score}-{away_score}"
        except:
            pass
        return "0-0"

    async def _send_events_to_discord(self, session_id: int, session_data: Dict[str, Any], events: List[Dict[str, Any]]):
        """Send new events to Discord via bot API."""
        thread_id = session_data.get('thread_id')
        if not thread_id:
            logger.warning(f"No thread ID for session {session_id}")
            return

        for event in events:
            try:
                # Format event message
                message_content = self._format_event_message(event, session_data)
                if not message_content:
                    continue

                # Send to Discord bot API - sanitize event data for JSON serialization
                clean_event = {
                    'type': str(event.get('type', 'unknown')),
                    'player': str(event.get('player', 'Unknown')),
                    'minute': str(event.get('minute', '0')),
                    'team': str(event.get('team', 'Unknown')),
                    'description': str(event.get('description', ''))
                }

                request_data = {
                    'thread_id': thread_id,
                    'event_type': event.get('type', 'unknown'),
                    'content': message_content,
                    'match_data': {
                        'session_id': session_id,
                        'match_id': session_data.get('match_id'),
                        'event': clean_event
                    }
                }

                response = send_to_discord_bot('/api/live-reporting/event', request_data)

                if response and response.get('success'):
                    logger.debug(f"Sent {event.get('type')} event to Discord for session {session_id}")
                else:
                    error_msg = response.get('error', 'Unknown error') if response else 'No response'
                    logger.error(f"Failed to send event to Discord: {error_msg}")

            except Exception as e:
                logger.error(f"Error sending event to Discord: {e}")

    def _format_event_message(self, event: Dict[str, Any], session_data: Dict[str, Any]) -> Optional[str]:
        """Format an event into a Discord message using enhanced AI commentary."""
        try:
            event_type = event.get('type', '').lower()
            session_id = session_data.get('id')

            # Extract event details (handle both ESPN and mock data formats)
            if isinstance(event.get('participant'), dict):
                # ESPN API format
                player = event.get('participant', {}).get('displayName', 'Unknown Player')
            else:
                # Mock data format
                player = event.get('player', 'Unknown Player')

            minute = event.get('minute', 0)

            if isinstance(event.get('team'), dict):
                # ESPN API format
                team = event.get('team', {}).get('displayName', 'Unknown Team')
            else:
                # Mock data format
                team = event.get('team', 'Unknown Team')

            # Get match context
            home_team = session_data.get('home_team', 'Home Team')
            away_team = session_data.get('away_team', 'Away Team')

            # Convert event type to lowercase for AI matching
            ai_event_type = event_type.lower()

            # Use AI for goals, cards, and substitutions
            if ai_event_type in ['goal', 'yellow_card', 'red_card', 'substitution']:
                # Build AI context
                ai_context = {
                    'home_team': {'displayName': home_team},
                    'away_team': {'displayName': away_team},
                    'event_type': ai_event_type,
                    'player': player,
                    'minute': minute,
                    'home_score': session_data.get('home_score', 0),
                    'away_score': session_data.get('away_score', 0)
                }

                # Set scoring team for goals
                if ai_event_type == 'goal':
                    ai_context['scoring_team'] = team

                # Set team for cards/subs
                if ai_event_type in ['yellow_card', 'red_card', 'substitution']:
                    ai_context['team'] = team

                # Add substitution-specific data
                if ai_event_type == 'substitution':
                    ai_context['player_on'] = event.get('player_on', player)
                    ai_context['player_off'] = event.get('player_off', 'Unknown Player')

                # Get match history for this session
                match_history = self.match_history.get(session_id, [])

                # Generate enhanced AI commentary
                ai_commentary = self.ai_client.generate_match_event_commentary(ai_context, match_history)

                if ai_commentary:
                    # Add event to match history
                    if session_id not in self.match_history:
                        self.match_history[session_id] = []

                    self.match_history[session_id].append({
                        'event_type': event_type,
                        'minute': minute,
                        'player': player,
                        'team': 'home' if team == home_team else 'away'
                    })

                    return ai_commentary

            # Fallback to enhanced static messages for other events
            if event_type == 'score_update':
                current_score = event.get('current_score', '0-0')
                return f"📊 **Score Update:** {home_team} {current_score} {away_team}"

            elif event_type == 'halftime':
                # Use AI for halftime if possible
                try:
                    halftime_context = {
                        'home_team': {'displayName': home_team},
                        'away_team': {'displayName': away_team},
                        'home_score': str(session_data.get('home_score', 0)),
                        'away_score': str(session_data.get('away_score', 0)),
                        'competition': session_data.get('competition', 'Match')
                    }
                    halftime_message = self.ai_client.generate_half_time_message(halftime_context)
                    if halftime_message:
                        return halftime_message
                except:
                    pass
                return f"⏸️ **HALFTIME** - {home_team} vs {away_team}"

            elif event_type == 'fulltime':
                # Use AI for fulltime if possible
                try:
                    fulltime_context = {
                        'home_team': {'displayName': home_team},
                        'away_team': {'displayName': away_team},
                        'home_score': str(session_data.get('home_score', 0)),
                        'away_score': str(session_data.get('away_score', 0)),
                        'competition': session_data.get('competition', 'Match')
                    }
                    fulltime_message = self.ai_client.generate_full_time_message(fulltime_context)
                    if fulltime_message:
                        return fulltime_message
                except:
                    pass
                return f"🏁 **FULL TIME** - {home_team} vs {away_team}"

            elif event_type in ['period_start', 'period_end']:
                description = event.get('description', event_type.replace('_', ' ').title())
                return f"🕐 **{description}**"

            # Fallback for unknown events
            return f"📋 **{event_type.replace('_', ' ').title()}** - {minute}' {player}"

        except Exception as e:
            logger.error(f"Error formatting event message with AI: {e}")
            # Ultimate fallback
            return f"📋 Match event: {event.get('type', 'Unknown')}"

    async def _update_session_stats(self, session_id: int):
        """Update session statistics in database."""
        try:
            with task_session() as session:
                live_session = session.query(LiveReportingSession).filter_by(id=session_id).first()
                if live_session:
                    live_session.last_update_at = datetime.utcnow()
                    live_session.update_count += 1
                    session.commit()
        except Exception as e:
            logger.error(f"Error updating session stats for {session_id}: {e}")

    async def _handle_session_error(self, session_id: int, error_msg: str):
        """Handle errors for a specific session."""
        try:
            with task_session() as session:
                live_session = session.query(LiveReportingSession).filter_by(id=session_id).first()
                if live_session:
                    live_session.error_count += 1
                    live_session.last_update_at = datetime.utcnow()

                    # Deactivate session if too many errors
                    if live_session.error_count >= 5:
                        live_session.is_active = False
                        live_session.ended_at = datetime.utcnow()
                        logger.warning(f"Deactivated session {session_id} due to excessive errors")

                    session.commit()
        except Exception as e:
            logger.error(f"Error handling session error: {e}")

    async def _deactivate_session(self, session_id: int, reason: str):
        """Deactivate a live reporting session."""
        try:
            with task_session() as session:
                live_session = session.query(LiveReportingSession).filter_by(id=session_id).first()
                if live_session and live_session.is_active:
                    live_session.is_active = False
                    live_session.ended_at = datetime.utcnow()
                    session.commit()

                    logger.info(f"Deactivated session {session_id}: {reason}")

                    # Send final message to Discord
                    await self._send_session_end_message(live_session.thread_id, reason)

        except Exception as e:
            logger.error(f"Error deactivating session {session_id}: {e}")

    async def _send_session_end_message(self, thread_id: int, reason: str):
        """Send final message when session ends."""
        try:
            request_data = {
                'thread_id': thread_id,
                'content': f"📺 Live reporting ended: {reason}",
                'close_thread': False
            }

            send_to_discord_bot('/api/live-reporting/final', request_data)
        except Exception as e:
            logger.error(f"Error sending session end message: {e}")

    def _get_next_interval(self) -> float:
        """Determine the next check interval based on active sessions."""
        if not self.active_sessions:
            return 30.0  # No active sessions

        # If we have active sessions, check frequently
        return 10.0  # Real-time updates every 10 seconds

    async def get_service_status(self) -> Dict[str, Any]:
        """Get current service status for monitoring."""
        return {
            'is_running': self.is_running,
            'active_sessions_count': len(self.active_sessions),
            'active_session_ids': list(self.active_sessions.keys()),
            'service_uptime': 'running' if self.is_running else 'stopped',
            'last_check': datetime.utcnow().isoformat()
        }


# Singleton service instance
realtime_service = RealtimeReportingService()


async def start_realtime_service():
    """Start the real-time service (called from main application)."""
    await realtime_service.start_service()


async def stop_realtime_service():
    """Stop the real-time service."""
    await realtime_service.stop_service()


async def get_realtime_service_status():
    """Get service status."""
    return await realtime_service.get_service_status()