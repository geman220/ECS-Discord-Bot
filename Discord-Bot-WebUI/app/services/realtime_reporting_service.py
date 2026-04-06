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
from concurrent.futures import ThreadPoolExecutor
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

    # Maximum time a session can stay active before forced deactivation (4 hours)
    SESSION_MAX_DURATION_SECONDS = 4 * 3600
    # Number of consecutive UNKNOWN status polls before forcing deactivation
    UNKNOWN_STATUS_THRESHOLD = 20  # ~200 seconds at 10s polling

    def __init__(self):
        self.redis_service = get_redis_service()
        self.espn_client = ESPNAPIClient()
        self.ai_client = get_sync_ai_client()  # Enhanced AI for commentary
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix='espn-poll')
        self.is_running = False
        self.active_sessions: Dict[int, Dict[str, Any]] = {}
        self.last_events: Dict[int, Set[str]] = {}  # Track processed events by session
        self.match_history: Dict[int, List[Dict[str, Any]]] = {}  # Track match history per session
        self._catchup_sessions: Set[int] = set()  # Sessions needing silent catch-up on first poll
        self._last_statuses: Dict[int, str] = {}  # Track previous status per session for transition detection
        self._unknown_status_counts: Dict[int, int] = {}  # Consecutive UNKNOWN status polls per session

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
                        home_team = "Seattle Sounders FC" if match.is_home_game else match.opponent
                        away_team = match.opponent if match.is_home_game else "Seattle Sounders FC"

                        # espn_match_id may not be populated separately - match_id IS the ESPN ID
                        espn_id = match.espn_match_id or match.match_id

                        session_data.update({
                            'home_team': home_team,
                            'away_team': away_team,
                            'match_date': match.date_time,
                            'opponent': match.opponent,
                            'is_home_game': match.is_home_game,
                            'venue': match.venue or 'TBD',
                            'competition': match.competition or 'MLS',
                            'espn_match_id': espn_id
                        })

                    current_sessions[live_session.id] = session_data

                    # Initialize event tracking - load persisted keys from DB to survive restarts
                    if live_session.id not in self.last_events:
                        persisted_keys = live_session.parsed_event_keys
                        self.last_events[live_session.id] = set(persisted_keys) if persisted_keys else set()
                        if persisted_keys:
                            logger.info(f"Loaded {len(persisted_keys)} persisted event keys for session {live_session.id}")
                        else:
                            # No persisted keys but session has been active — need silent catch-up
                            # to avoid replaying all past events after a restart/first-run
                            age = (datetime.utcnow() - live_session.started_at).total_seconds() if live_session.started_at else 0
                            if age > 120:  # Session older than 2 minutes
                                self._catchup_sessions.add(live_session.id)
                                logger.info(f"Session {live_session.id} needs catch-up (age={age:.0f}s, no persisted events)")

                        # Restore last known status from DB for transition detection
                        if live_session.last_status:
                            self._last_statuses[live_session.id] = live_session.last_status
                            logger.info(f"Restored last status '{live_session.last_status}' for session {live_session.id}")

                        # Seed Redis score key from DB to prevent false score-change on restart
                        if live_session.last_score:
                            score_key = f"last_score_{live_session.id}"
                            try:
                                self.redis_service.execute_command('setex', score_key, 3600, live_session.last_score)
                                logger.info(f"Restored last score '{live_session.last_score}' for session {live_session.id}")
                            except Exception:
                                pass

                # Clean up old sessions from our cache
                old_session_ids = set(self.active_sessions.keys()) - set(current_sessions.keys())
                for old_id in old_session_ids:
                    if old_id in self.last_events:
                        del self.last_events[old_id]

                self.active_sessions = current_sessions

                if self.active_sessions:
                    session_ids = list(self.active_sessions.keys())
                    logger.info(f"Found {len(self.active_sessions)} active live session(s): {session_ids}")
                else:
                    logger.info("No active live reporting sessions found")

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
                logger.warning(f"No ESPN match ID for session {session_id}, skipping")
                return

            # Map competition name to ESPN league code
            competition = session_data.get('competition', 'usa.1')
            competition_map = {
                'MLS': 'usa.1',
                'US Open Cup': 'usa.open',
                'Leagues Cup': 'usa.leagues_cup',
                'CONCACAF Champions League': 'concacaf.champions',
            }
            league_code = competition_map.get(competition, competition)

            logger.info(f"Polling ESPN for session {session_id} (match={espn_match_id}, league={league_code})")
            # Run sync ESPN client in executor to avoid blocking the async event loop
            loop = asyncio.get_running_loop()
            match_data = await loop.run_in_executor(
                self._executor, self.espn_client.get_match_data, espn_match_id, league_code
            )
            if not match_data:
                await self._handle_session_error(session_id, "Failed to fetch match data")
                return

            status = match_data.get('status', 'UNKNOWN')
            score = f"{match_data.get('home_score', 0)}-{match_data.get('away_score', 0)}"
            logger.info(f"Session {session_id}: ESPN status={status}, score={score}, mock={match_data.get('mock_data', False)}")

            # Detect status transitions for lifecycle messages
            previous_status = self._last_statuses.get(session_id)
            is_catchup = session_id in self._catchup_sessions

            # Check absolute session timeout — no match lasts forever
            started_at = session_data.get('started_at')
            if started_at:
                age = (datetime.utcnow() - started_at).total_seconds()
                if age > self.SESSION_MAX_DURATION_SECONDS:
                    logger.warning(f"Session {session_id}: Exceeded max duration ({age:.0f}s), force-deactivating")
                    await self._deactivate_session(session_id, session_data, f"Session timeout after {age:.0f}s")
                    self._unknown_status_counts.pop(session_id, None)
                    self._catchup_sessions.discard(session_id)
                    return

            # Check match state
            if self._is_match_ended(match_data):
                if not is_catchup:
                    # Send proper fulltime message before deactivating
                    await self._send_lifecycle_event(session_id, session_data, 'fulltime', match_data)
                logger.info(f"Session {session_id}: Match ended (status={status}), deactivating")
                await self._deactivate_session(session_id, session_data, f"Match ended (status: {status})")
                self._unknown_status_counts.pop(session_id, None)
                self._catchup_sessions.discard(session_id)
                return

            if not self._is_match_live(match_data):
                # Track consecutive UNKNOWN polls — if the match was previously live
                # and we keep getting UNKNOWN, ESPN likely dropped it (match ended)
                if status == 'UNKNOWN' and previous_status in ('IN_PLAY', 'HALFTIME'):
                    count = self._unknown_status_counts.get(session_id, 0) + 1
                    self._unknown_status_counts[session_id] = count
                    logger.warning(
                        f"Session {session_id}: UNKNOWN status after {previous_status} "
                        f"({count}/{self.UNKNOWN_STATUS_THRESHOLD})"
                    )
                    if count >= self.UNKNOWN_STATUS_THRESHOLD:
                        logger.warning(f"Session {session_id}: Too many UNKNOWN polls, assuming match ended")
                        if not is_catchup:
                            await self._send_lifecycle_event(session_id, session_data, 'fulltime', match_data)
                        await self._deactivate_session(
                            session_id, session_data,
                            f"Match presumed ended (UNKNOWN status x{count} after {previous_status})"
                        )
                        self._unknown_status_counts.pop(session_id, None)
                        self._catchup_sessions.discard(session_id)
                        return
                else:
                    # Reset counter if we get a known non-live status (SCHEDULED, etc.)
                    self._unknown_status_counts.pop(session_id, None)

                # Match not started yet or unknown status — wait, don't deactivate
                logger.info(f"Session {session_id}: Match not live yet (status={status}), waiting...")
                self._last_statuses[session_id] = status
                return

            # Status is live — reset unknown counter
            self._unknown_status_counts.pop(session_id, None)

            # Detect and send lifecycle messages on status transitions
            if previous_status and previous_status != status and not is_catchup:
                await self._send_lifecycle_event(session_id, session_data,
                                                 self._get_transition_type(previous_status, status),
                                                 match_data)

            # Process any new discrete events (goals, cards, subs)
            new_events = await self._extract_new_events(session_id, match_data)

            # On first poll after restart with no persisted keys, silently catch up
            if is_catchup:
                if new_events:
                    logger.info(f"Session {session_id}: Catch-up mode - absorbed {len(new_events)} existing event(s) without sending")
                self._catchup_sessions.discard(session_id)
            elif new_events:
                logger.info(f"Session {session_id}: Processing {len(new_events)} new event(s)")
                # Inject live score from ESPN into session_data so AI context has current score
                session_data['home_score'] = match_data.get('home_score', 0)
                session_data['away_score'] = match_data.get('away_score', 0)
                await self._send_events_to_discord(session_id, session_data, new_events)

            # Update status tracking and persist state
            self._last_statuses[session_id] = status
            await self._update_session_stats(session_id, status, score)

        except Exception as e:
            logger.error(f"Error processing session {session_id}: {e}")
            await self._handle_session_error(session_id, str(e))

    def _get_match_status(self, match_data: Dict[str, Any]) -> str:
        """Extract match status string from match data."""
        if isinstance(match_data.get('status'), str):
            return match_data.get('status', '').upper()
        else:
            return match_data.get('status', {}).get('type', {}).get('name', '').upper()

    def _is_match_live(self, match_data: Dict[str, Any]) -> bool:
        """Check if match is currently live."""
        status = self._get_match_status(match_data)
        return status in ['IN_PLAY', 'HALFTIME']

    def _is_match_ended(self, match_data: Dict[str, Any]) -> bool:
        """Check if match has ended (should deactivate session)."""
        status = self._get_match_status(match_data)
        if status in ['FINAL', 'COMPLETED', 'POSTPONED', 'CANCELLED']:
            return True
        # Secondary check: ESPN 'completed' flag from status.type
        if match_data.get('completed'):
            return True
        return False

    def _get_transition_type(self, previous_status: str, current_status: str) -> Optional[str]:
        """Determine the lifecycle event type for a status transition."""
        prev = previous_status.upper() if previous_status else ''
        curr = current_status.upper() if current_status else ''

        if curr == 'IN_PLAY' and prev in ('SCHEDULED', 'PRE_MATCH', ''):
            return 'kickoff'
        elif curr == 'HALFTIME' and prev == 'IN_PLAY':
            return 'halftime'
        elif curr == 'IN_PLAY' and prev == 'HALFTIME':
            return 'second_half_start'
        elif curr in ('FINAL', 'COMPLETED'):
            return 'fulltime'
        return None

    def _build_stats_fields(self, match_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Build embed fields from ESPN match statistics."""
        fields = []
        stats = match_data.get('stats', {})
        home_stats = stats.get('home', {})
        away_stats = stats.get('away', {})

        if not home_stats and not away_stats:
            return fields

        # Possession
        home_poss = home_stats.get('possessionPct', '')
        away_poss = away_stats.get('possessionPct', '')
        if home_poss or away_poss:
            fields.append({
                'name': 'Possession',
                'value': f"{home_poss}% - {away_poss}%",
                'inline': True
            })

        # Shots (total + on target)
        home_shots = home_stats.get('totalShots', '')
        away_shots = away_stats.get('totalShots', '')
        home_sot = home_stats.get('shotsOnTarget', '')
        away_sot = away_stats.get('shotsOnTarget', '')
        if home_shots or away_shots:
            shot_text = f"{home_shots} - {away_shots}"
            if home_sot or away_sot:
                shot_text += f" ({home_sot} - {away_sot} on target)"
            fields.append({
                'name': 'Shots',
                'value': shot_text,
                'inline': True
            })

        # Corners
        home_corners = home_stats.get('wonCorners', '')
        away_corners = away_stats.get('wonCorners', '')
        if home_corners or away_corners:
            fields.append({
                'name': 'Corners',
                'value': f"{home_corners} - {away_corners}",
                'inline': True
            })

        # Fouls
        home_fouls = home_stats.get('foulsCommitted', '')
        away_fouls = away_stats.get('foulsCommitted', '')
        if home_fouls or away_fouls:
            fields.append({
                'name': 'Fouls',
                'value': f"{home_fouls} - {away_fouls}",
                'inline': True
            })

        return fields

    async def _send_lifecycle_event(self, session_id: int, session_data: Dict[str, Any],
                                     event_type: Optional[str], match_data: Dict[str, Any]):
        """Send a match lifecycle message (kickoff, halftime, second half, fulltime)."""
        if not event_type:
            return

        thread_id = session_data.get('thread_id')
        if not thread_id:
            return

        home_team = session_data.get('home_team', 'Home')
        away_team = session_data.get('away_team', 'Away')
        home_score = match_data.get('home_score', 0)
        away_score = match_data.get('away_score', 0)

        logger.info(f"Session {session_id}: Sending lifecycle event '{event_type}'")

        # Try AI-generated message first, fall back to static
        message = None

        if event_type == 'kickoff':
            venue = match_data.get('venue', '')
            if venue:
                message = f"Kickoff. {home_team} vs {away_team} at {venue}."
            else:
                message = f"Kickoff. {home_team} vs {away_team}."

        elif event_type == 'halftime':
            try:
                context = {
                    'home_team': {'displayName': home_team},
                    'away_team': {'displayName': away_team},
                    'home_score': str(home_score),
                    'away_score': str(away_score),
                    'competition': session_data.get('competition', 'MLS')
                }
                ai_msg = self.ai_client.generate_half_time_message(context)
                if ai_msg:
                    message = ai_msg
            except Exception as e:
                logger.warning(f"AI halftime message failed: {e}")
            if not message:
                message = f"Halftime. {home_team} {home_score}-{away_score} {away_team}."

        elif event_type == 'second_half_start':
            message = f"Second half underway. {home_team} {home_score}-{away_score} {away_team}."

        elif event_type == 'fulltime':
            try:
                context = {
                    'home_team': {'displayName': home_team},
                    'away_team': {'displayName': away_team},
                    'home_score': str(home_score),
                    'away_score': str(away_score),
                    'competition': session_data.get('competition', 'MLS')
                }
                ai_msg = self.ai_client.generate_full_time_message(context)
                if ai_msg:
                    message = ai_msg
            except Exception as e:
                logger.warning(f"AI fulltime message failed: {e}")
            if not message:
                message = f"Full time. {home_team} {home_score}-{away_score} {away_team}."

        if message:
            try:
                # Build a rich embed for lifecycle events
                lifecycle_colors = {
                    'kickoff': 0x00FF00,
                    'halftime': 0xFFA500,
                    'second_half_start': 0x00FF00,
                    'fulltime': 0x005F4F,
                }
                embed = {
                    'title': event_type.replace('_', ' ').title(),
                    'description': message,
                    'color': lifecycle_colors.get(event_type, 0x005F4F),
                    'timestamp': datetime.utcnow().isoformat(),
                    'footer': {
                        'text': f'{home_team} {home_score}-{away_score} {away_team}',
                    },
                    'fields': [],
                }

                # Add match stats for halftime and fulltime
                if event_type in ('halftime', 'fulltime'):
                    stats_fields = self._build_stats_fields(match_data)
                    embed['fields'].extend(stats_fields)

                    # Add attendance for fulltime
                    attendance = match_data.get('attendance', 0)
                    if attendance and event_type == 'fulltime':
                        embed['fields'].append({
                            'name': 'Attendance',
                            'value': f"{attendance:,}",
                            'inline': True
                        })

                request_data = {
                    'thread_id': thread_id,
                    'event_type': event_type,
                    'content': message,
                    'embed': embed,
                    'match_data': {
                        'session_id': session_id,
                        'match_id': session_data.get('match_id')
                    }
                }
                response = send_to_discord_bot('/api/live-reporting/event', request_data)
                if response and response.get('success'):
                    logger.info(f"Sent {event_type} lifecycle message for session {session_id}")
                else:
                    error_msg = response.get('error', 'Unknown') if response else 'No response'
                    logger.error(f"Failed to send {event_type} message: {error_msg}")
            except Exception as e:
                logger.error(f"Error sending lifecycle event: {e}")

    async def _extract_new_events(self, session_id: int, match_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract new events that haven't been processed yet."""
        new_events = []

        try:
            # Get current events from match data
            events = match_data.get('events', [])

            # Track processed events for this session
            processed_events = self.last_events.get(session_id, set())

            for event in events:
                # Build a robust dedup key from all available fields.
                # ESPN events via _process_event_data() lack an 'id' field, so we
                # combine type + minute + player + team to avoid collisions.
                parts = [
                    event.get('id', ''),
                    event.get('type', 'unknown'),
                    str(event.get('minute', '0')),
                    event.get('player', event.get('athlete_name', '')),
                    event.get('team', event.get('team_id', '')),
                ]
                event_id = '_'.join(p for p in parts if p)

                if event_id not in processed_events:
                    new_events.append(event)
                    processed_events.add(event_id)

            # Update processed events cache
            self.last_events[session_id] = processed_events

            # Also check for score changes (skip during halftime — score can't change)
            status = self._get_match_status(match_data)
            if status != 'HALFTIME':
                current_score = self._get_current_score(match_data)
                last_score_key = f"last_score_{session_id}"
                last_score = self.redis_service.execute_command('get', last_score_key)

                # Ensure consistent string comparison
                if last_score is not None:
                    last_score = str(last_score)

                if last_score != current_score:
                    # Only emit score_update if no goal event was already detected this cycle
                    # (goals naturally change the score, so posting both would be a double-post)
                    has_goal_event = any(
                        e.get('type', '').upper() in ('GOAL', 'OWN GOAL', 'PENALTY')
                        for e in new_events
                    )
                    if last_score is not None and not has_goal_event:
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
        """Extract current score from processed ESPN match data."""
        return f"{match_data.get('home_score', 0)}-{match_data.get('away_score', 0)}"

    # Embed color mapping by event type
    EVENT_COLORS = {
        'goal': 0x005F4F,        # Sounders green
        'own_goal': 0x005F4F,
        'penalty_goal': 0x005F4F,
        'yellow_card': 0xFFD700,  # Gold
        'red_card': 0xFF0000,     # Red
        'substitution': 0x0099FF, # Blue
        'score_update': 0x005F4F,
    }

    def _build_event_embed(self, event: Dict[str, Any], session_data: Dict[str, Any],
                           commentary: str) -> Optional[Dict[str, Any]]:
        """Build a rich Discord embed dict for a match event."""
        event_type = event.get('type', '').lower()
        minute = event.get('minute', '')
        player = event.get('player', '')
        team = event.get('team', '')
        player_headshot = event.get('player_headshot', '')
        team_logo = event.get('team_logo', '')
        home_team = session_data.get('home_team', 'Home')
        away_team = session_data.get('away_team', 'Away')
        home_score = session_data.get('home_score', 0)
        away_score = session_data.get('away_score', 0)

        # Title by event type
        title_map = {
            'goal': 'Goal',
            'own_goal': 'Own Goal',
            'penalty_goal': 'Penalty Goal',
            'yellow_card': 'Yellow Card',
            'red_card': 'Red Card',
            'substitution': 'Substitution',
            'score_update': 'Score Update',
        }
        title = title_map.get(event_type, 'Match Update')

        color = self.EVENT_COLORS.get(event_type, 0x005F4F)

        embed = {
            'title': title,
            'description': commentary,
            'color': color,
            'timestamp': datetime.utcnow().isoformat(),
            'footer': {
                'text': f'{home_team} {home_score}-{away_score} {away_team}',
            },
            'fields': [],
        }

        # Add time field
        if minute:
            embed['fields'].append({'name': 'Time', 'value': str(minute), 'inline': True})

        # Add player field for non-sub events
        if player and event_type != 'substitution':
            jersey = event.get('player_jersey', '')
            player_display = f"{player} #{jersey}" if jersey else player
            embed['fields'].append({'name': 'Player', 'value': player_display, 'inline': True})

        # Substitution: show both players
        if event_type == 'substitution':
            player_on = event.get('player_on', '')
            player_off = event.get('player_off', '')
            if player_on:
                embed['fields'].append({'name': 'On', 'value': player_on, 'inline': True})
            if player_off:
                embed['fields'].append({'name': 'Off', 'value': player_off, 'inline': True})

        # Player headshot as thumbnail
        if player_headshot:
            embed['thumbnail'] = {'url': player_headshot}

        # Team logo as author icon
        if team:
            author = {'name': team}
            if team_logo:
                author['icon_url'] = team_logo
            embed['author'] = author

        return embed

    async def _send_events_to_discord(self, session_id: int, session_data: Dict[str, Any], events: List[Dict[str, Any]]):
        """Send new events to Discord via bot API with rich embeds."""
        thread_id = session_data.get('thread_id')
        if not thread_id:
            logger.warning(f"No thread ID for session {session_id}")
            return

        for event in events:
            try:
                # Generate AI commentary text
                message_content = self._format_event_message(event, session_data)
                if not message_content:
                    continue

                # Build rich embed for the bot API
                embed = self._build_event_embed(event, session_data, message_content)

                # Sanitize event data for JSON serialization
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

                # Include embed if we built one
                if embed:
                    request_data['embed'] = embed

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

            # Also match goal variants from ESPN
            if ai_event_type in ['goal', 'own_goal', 'penalty_goal', 'yellow_card', 'red_card', 'substitution']:
                # Normalize goal variants for AI
                if ai_event_type in ('own_goal', 'penalty_goal'):
                    ai_event_type = 'goal'

                # Use the actual ESPN description when available, fall back to structured text
                espn_description = event.get('description', '')
                if not espn_description:
                    espn_description = f"{event.get('detail_text', ai_event_type.replace('_', ' ').title())}. {player} ({team}). {minute}."

                # Build AI context with real event data
                ai_context = {
                    'match_id': session_data.get('match_id', ''),
                    'home_team': {'displayName': home_team},
                    'away_team': {'displayName': away_team},
                    'event_type': ai_event_type,
                    'player': player,
                    'minute': minute,
                    'home_score': session_data.get('home_score', 0),
                    'away_score': session_data.get('away_score', 0),
                    'description': espn_description
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

            # Fallback to static messages for other events
            if event_type == 'score_update':
                current_score = event.get('current_score', '0-0')
                return f"{home_team} {current_score} {away_team}"

            elif event_type == 'halftime':
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
                except Exception as e:
                    logger.warning(f"AI halftime message failed in formatter: {e}")
                return f"Halftime. {home_team} vs {away_team}."

            elif event_type == 'fulltime':
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
                except Exception as e:
                    logger.warning(f"AI fulltime message failed in formatter: {e}")
                return f"Full time. {home_team} vs {away_team}."

            elif event_type in ['period_start', 'period_end']:
                description = event.get('description', event_type.replace('_', ' ').title())
                return description

            # Fallback for unknown events
            return f"{event_type.replace('_', ' ').title()}. {minute}' {player}."

        except Exception as e:
            logger.error(f"Error formatting event message with AI: {e}")
            player = event.get('player', event.get('participant', {}).get('displayName', '')) if isinstance(event, dict) else ''
            minute = event.get('minute', '') if isinstance(event, dict) else ''
            event_type_str = event.get('type', 'Unknown') if isinstance(event, dict) else 'Unknown'
            parts = [event_type_str]
            if minute:
                parts.append(f"{minute}'")
            if player:
                parts.append(f"- {player}")
            return " ".join(parts)

    async def _update_session_stats(self, session_id: int, status: str = None, score: str = None):
        """Update session statistics and persist event keys to database."""
        try:
            with task_session() as session:
                live_session = session.query(LiveReportingSession).filter_by(id=session_id).first()
                if live_session:
                    live_session.last_update = datetime.utcnow()
                    live_session.update_count += 1

                    if status:
                        live_session.last_status = status
                    if score:
                        live_session.last_score = score

                    # Persist processed event keys to survive restarts
                    current_keys = self.last_events.get(session_id, set())
                    if current_keys:
                        live_session.last_event_keys = json.dumps(list(current_keys))

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
                    live_session.last_update = datetime.utcnow()
                    live_session.last_error = error_msg

                    # Deactivate session if too many errors
                    if live_session.error_count >= 5:
                        session.commit()
                        session_data = self.active_sessions.get(session_id, {})
                        await self._deactivate_session(
                            session_id, session_data, f"Too many errors: {error_msg}"
                        )
                        return

                    session.commit()
        except Exception as e:
            logger.error(f"Error handling session error: {e}")

    async def _deactivate_session(self, session_id: int, session_data: Dict[str, Any], reason: str):
        """Deactivate a live reporting session and clean up related records."""
        try:
            from app.models.scheduled_task import ScheduledTask, TaskType, TaskState
            from app.models.match_status import MatchStatus

            with task_session() as session:
                live_session = session.query(LiveReportingSession).filter_by(id=session_id).first()
                if live_session and live_session.is_active:
                    live_session.is_active = False
                    live_session.ended_at = datetime.utcnow()

                    # Persist final event keys
                    current_keys = self.last_events.get(session_id, set())
                    if current_keys:
                        live_session.last_event_keys = json.dumps(list(current_keys))

                    # Update MLSMatch status to completed
                    match = session.query(MLSMatch).filter_by(match_id=live_session.match_id).first()
                    if match:
                        match.live_reporting_status = MatchStatus.COMPLETED
                        match.live_reporting_started = True
                        logger.info(f"Updated MLSMatch {match.id} live_reporting_status to COMPLETED")

                        # Update ScheduledTask to COMPLETED
                        scheduled_task = session.query(ScheduledTask).filter_by(
                            match_id=match.id,
                            task_type=TaskType.LIVE_REPORTING_START
                        ).filter(
                            ScheduledTask.state.in_([TaskState.SCHEDULED, TaskState.RUNNING])
                        ).first()
                        if scheduled_task:
                            scheduled_task.state = TaskState.COMPLETED
                            scheduled_task.execution_time = datetime.utcnow()
                            logger.info(f"Updated ScheduledTask {scheduled_task.id} to COMPLETED")

                    session.commit()
                    logger.info(f"Deactivated session {session_id}: {reason}")

                    # Archive thread on match end (no extra message - fulltime was already posted)
                    is_match_end = 'ended' in reason.lower() or 'FINAL' in reason or 'COMPLETED' in reason
                    if is_match_end:
                        # Just archive the thread silently - fulltime lifecycle message was already sent
                        await self._archive_thread(live_session.thread_id)
                    else:
                        # Non-match-end deactivation (errors, timeout) - post explanation
                        await self._send_session_end_message(
                            live_session.thread_id, reason, close_thread=False
                        )

                    # Clean up in-memory tracking
                    self.last_events.pop(session_id, None)
                    self._last_statuses.pop(session_id, None)
                    self.match_history.pop(session_id, None)
                    self._unknown_status_counts.pop(session_id, None)

        except Exception as e:
            logger.error(f"Error deactivating session {session_id}: {e}")

    async def _archive_thread(self, thread_id: str):
        """Archive thread without posting a message (used after fulltime was already sent)."""
        try:
            request_data = {
                'thread_id': thread_id,
                'content': '',  # No message needed
                'close_thread': True
            }
            send_to_discord_bot('/api/live-reporting/final', request_data)
        except Exception as e:
            logger.error(f"Error archiving thread: {e}")

    async def _send_session_end_message(self, thread_id: str, reason: str, close_thread: bool = False):
        """Send message when session ends for non-match-end reasons (errors, timeouts)."""
        try:
            request_data = {
                'thread_id': thread_id,
                'content': f"Live reporting stopped: {reason}",
                'close_thread': close_thread
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