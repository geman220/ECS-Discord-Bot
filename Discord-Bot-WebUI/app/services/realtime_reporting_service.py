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
import os

from app.models import LiveReportingSession, MLSMatch
from app.services.live_reporting_event_log import record_event as log_event
from app.services.redis_connection_service import get_redis_service
from app.utils.competition_mappings import resolve_league_code
from app.utils.espn_api_client import ESPNAPIClient
from app.utils.discord_request_handler import send_to_discord_bot
from app.utils.task_session_manager import task_session
from app.utils.sync_ai_client import get_sync_ai_client
from app.utils.template_commentary import get_template_engine, detect_rivalry
from app.utils.commentary_validator import generate_with_validation, CommentaryType

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
        self.template_engine = get_template_engine()  # Deterministic mad-lib commentary
        # Template-first ("mad-lib") commentary is the default — deterministic,
        # human-authored lines filled from real ESPN data, undetectable as AI.
        # Set LIVE_REPORTING_TEMPLATE_COMMENTARY=0 to fall back to LLM-first.
        self._template_first = os.getenv('LIVE_REPORTING_TEMPLATE_COMMENTARY', '1').lower() not in ('0', 'false', 'no')
        # LLM commentary is opt-in "spice" — off by default. When on, the LLM is
        # tried after the template engine (and before the ESPN-text fallback).
        self._ai_spice = os.getenv('LIVE_REPORTING_AI_SPICE', '0').lower() in ('1', 'true', 'yes')
        # Standalone "Score Update" embeds are OFF by default — a score change with
        # no goal keyEvent advances the score silently (the goal keyEvent announces
        # it, and the score is in every event footer). Set =1 to re-enable.
        self._post_score_updates = os.getenv('LIVE_REPORTING_POST_SCORE_UPDATES', '0').lower() in ('1', 'true', 'yes')
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix='espn-poll')
        self.is_running = False
        self.active_sessions: Dict[int, Dict[str, Any]] = {}
        self.last_events: Dict[int, Set[str]] = {}  # Track processed events by session
        self.match_history: Dict[int, List[Dict[str, Any]]] = {}  # Track match history per session
        self._catchup_sessions: Set[int] = set()  # Sessions needing silent catch-up on first poll
        self._last_statuses: Dict[int, str] = {}  # Track previous status per session for transition detection
        self._unknown_status_counts: Dict[int, int] = {}  # Consecutive UNKNOWN status polls per session
        self._pending_score: Dict[int, tuple] = {}  # Per-session (new_score, carrier) awaiting a confirmed post
        self._pending_correction: Dict[int, str] = {}  # Per-session lower score awaiting debounce confirmation
        self._overrides_refreshed_at = None  # Last time admin mad-lib overrides were loaded
        self._session_goals: Dict[int, List[Dict[str, Any]]] = {}  # Goals accumulated per session for the FT recap

    async def start_service(self):
        """Start the real-time reporting service."""
        if self.is_running:
            logger.warning("Real-time service already running")
            return

        self.is_running = True
        logger.info("Starting real-time live reporting service")

        # Seed status + heartbeat immediately so the container healthcheck
        # (which polls realtime_service:heartbeat) doesn't flap during the
        # first 60 seconds before the main loop's periodic refresh kicks in.
        now_iso = datetime.utcnow().isoformat()
        self.redis_service.execute_command('setex', 'realtime_service:status', 300, 'running')
        self.redis_service.execute_command('setex', 'realtime_service:heartbeat', 120, now_iso)

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
                if (now - last_heartbeat).total_seconds() >= 60:
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

    def _refresh_template_overrides(self):
        """
        Load admin-edited mad-lib lines (AIPromptConfig.template_lines) into the
        template engine, throttled to once every 5 min so edits propagate without
        a restart but we don't query every cycle. Best-effort — on failure the
        engine keeps its current (or code-default) lines.
        """
        now = datetime.utcnow()
        if (self._overrides_refreshed_at is not None
                and (now - self._overrides_refreshed_at).total_seconds() < 300):
            return
        self._overrides_refreshed_at = now
        try:
            from app.models.ai_prompt_config import AIPromptConfig
            overrides: Dict[str, List[str]] = {}
            with task_session() as db:
                rows = db.query(
                    AIPromptConfig.prompt_type, AIPromptConfig.template_lines
                ).filter(
                    AIPromptConfig.is_active == True,
                    AIPromptConfig.template_lines.isnot(None),
                ).all()
            for prompt_type, lines_text in rows:
                lines = [ln.strip() for ln in (lines_text or '').splitlines() if ln.strip()]
                if lines:
                    overrides[prompt_type] = lines
            self.template_engine.set_overrides(overrides)
            if overrides:
                logger.info(f"Loaded mad-lib overrides for {len(overrides)} prompt type(s): {sorted(overrides)}")
        except Exception as e:
            logger.warning(f"Could not refresh template overrides: {e}")

    async def _refresh_active_sessions(self):
        """Load active live reporting sessions from database."""
        try:
            # Refresh admin mad-lib line overrides (throttled internally)
            self._refresh_template_overrides()

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

                    # Log new sessions to the admin UI ring buffer
                    if live_session.id not in self.active_sessions:
                        log_event(
                            stage="session", outcome="info",
                            session_id=live_session.id,
                            match_id=str(live_session.match_id),
                            message=f"Session active: {session_data.get('home_team', '?')} vs {session_data.get('away_team', '?')}",
                            context={
                                "competition": session_data.get('competition'),
                                "thread_id": session_data.get('thread_id'),
                            },
                        )

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
                                self.redis_service.setex(score_key, 3600, str(live_session.last_score))
                                logger.info(f"Restored last score '{live_session.last_score}' for session {live_session.id}")
                            except Exception:
                                pass

                # Clean up old sessions from our cache
                old_session_ids = set(self.active_sessions.keys()) - set(current_sessions.keys())
                for old_id in old_session_ids:
                    self.last_events.pop(old_id, None)
                    self._session_goals.pop(old_id, None)
                    self._pending_score.pop(old_id, None)
                    self._pending_correction.pop(old_id, None)

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

            # Resolve the ESPN league code from the session's competition
            # (accepts display names like "Concacaf Champions Cup" and ESPN
            # codes like "concacaf.champions" transparently).
            competition = session_data.get('competition')
            league_code = resolve_league_code(competition)

            logger.info(
                f"Polling ESPN for session {session_id} "
                f"(match={espn_match_id}, league={league_code})"
            )
            # Run sync ESPN client in executor to avoid blocking the async event loop
            loop = asyncio.get_running_loop()
            match_data = await loop.run_in_executor(
                self._executor,
                self.espn_client.get_match_data,
                espn_match_id, league_code,
            )
            if not match_data:
                # If ESPN returned nothing after the match was previously live,
                # it has likely dropped off the live scoreboard because it
                # ended. Feed this into the UNKNOWN-after-live counter so
                # _is_match_ended can short-circuit instead of waiting for the
                # 4h absolute timeout.
                previous_status = self._last_statuses.get(session_id)
                if previous_status in ('IN_PLAY', 'HALFTIME'):
                    count = self._unknown_status_counts.get(session_id, 0) + 1
                    self._unknown_status_counts[session_id] = count
                    logger.warning(
                        f"Session {session_id}: ESPN returned no data after {previous_status} "
                        f"({count}/{self.UNKNOWN_STATUS_THRESHOLD})"
                    )
                    if count >= self.UNKNOWN_STATUS_THRESHOLD:
                        logger.warning(f"Session {session_id}: ESPN data gone, treating as match end")
                        if session_id not in self._catchup_sessions:
                            await self._send_lifecycle_event(
                                session_id, session_data, 'fulltime', {'status': previous_status}
                            )
                        await self._deactivate_session(
                            session_id, session_data,
                            f"Match presumed ended (no ESPN data x{count} after {previous_status})"
                        )
                        self._unknown_status_counts.pop(session_id, None)
                        self._catchup_sessions.discard(session_id)
                        return
                await self._handle_session_error(session_id, "Failed to fetch match data")
                return

            status = match_data.get('status', 'UNKNOWN')
            score = f"{match_data.get('home_score', 0)}-{match_data.get('away_score', 0)}"
            logger.info(f"Session {session_id}: ESPN status={status}, score={score}")

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
                    # Absorb pre-existing events as already-processed without posting
                    self.last_events.setdefault(session_id, set()).update(
                        e['_dedup_key'] for e in new_events
                        if e.get('_dedup_key') and not str(e['_dedup_key']).startswith('score_')
                    )
                    logger.info(f"Session {session_id}: Catch-up mode - absorbed {len(new_events)} existing event(s) without sending")
                self._commit_pending_score(session_id)  # seed score silently
                self._catchup_sessions.discard(session_id)
            elif new_events:
                logger.info(f"Session {session_id}: Processing {len(new_events)} new event(s)")
                # Inject live score from ESPN into session_data so AI context has current score
                session_data['home_score'] = match_data.get('home_score', 0)
                session_data['away_score'] = match_data.get('away_score', 0)
                posted_keys = await self._send_events_to_discord(session_id, session_data, new_events)
                # Commit dedup keys ONLY for events that actually posted, so a failed
                # post is retried next cycle instead of being silently dropped. (Score
                # keys are tracked via Redis, not last_events.)
                if posted_keys:
                    self.last_events.setdefault(session_id, set()).update(
                        k for k in posted_keys if not str(k).startswith('score_')
                    )
                # Advance the scoreline only if its carrying event posted.
                self._commit_pending_score(session_id, new_events, posted_keys or set())
            else:
                # No events to post, but a first-cycle score seed may be pending.
                self._commit_pending_score(session_id)

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

    def _build_fulltime_recap_fields(self, session_id: int, match_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Build full-time recap fields: a goalscorer timeline (accumulated live,
        since ESPN strips keyEvents from the payload at FT), plus venue & referee.
        """
        fields = []
        goals = self._session_goals.get(session_id, [])
        if goals:
            lines = []
            for g in goals:
                minute = str(g.get('minute', '')).strip()
                tick = f"{minute} " if minute else ""
                player = g.get('player') or 'Unknown'
                gtype = g.get('type', '')
                if gtype == 'OWN_GOAL':
                    suffix = ' (OG)'
                elif gtype == 'PENALTY_GOAL':
                    suffix = ' (pen)'
                elif g.get('assist'):
                    suffix = f" ({g['assist']})"
                else:
                    suffix = ''
                lines.append(f"⚽ {tick}{player}{suffix}".strip())
            value = "\n".join(lines)
            if len(value) > 1024:
                value = value[:1021] + "..."
            fields.append({'name': 'Goals', 'value': value, 'inline': False})

        venue = match_data.get('venue', '')
        if venue:
            fields.append({'name': 'Venue', 'value': str(venue)[:1024], 'inline': True})
        referee = match_data.get('referee', '')
        if referee:
            fields.append({'name': 'Referee', 'value': str(referee)[:1024], 'inline': True})
        return fields

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

        # Saves
        home_saves = home_stats.get('saves', '')
        away_saves = away_stats.get('saves', '')
        if home_saves or away_saves:
            fields.append({'name': 'Saves', 'value': f"{home_saves} - {away_saves}", 'inline': True})

        # Offsides
        home_off = home_stats.get('offsides', '')
        away_off = away_stats.get('offsides', '')
        if home_off or away_off:
            fields.append({'name': 'Offsides', 'value': f"{home_off} - {away_off}", 'inline': True})

        # Passing accuracy (computed from accurate/total passes)
        home_pp = self._pass_pct(home_stats)
        away_pp = self._pass_pct(away_stats)
        if home_pp or away_pp:
            fields.append({'name': 'Passing', 'value': f"{home_pp}% - {away_pp}%", 'inline': True})

        # Cards (only when at least one card has been shown)
        hy = str(home_stats.get('yellowCards', '0') or '0'); hr = str(home_stats.get('redCards', '0') or '0')
        ay = str(away_stats.get('yellowCards', '0') or '0'); ar = str(away_stats.get('redCards', '0') or '0')
        if any(v not in ('', '0') for v in (hy, hr, ay, ar)):
            fields.append({'name': 'Cards', 'value': f"{hy}Y {hr}R - {ay}Y {ar}R", 'inline': True})

        return fields

    @staticmethod
    def _pass_pct(team_stats: Dict[str, Any]) -> str:
        """Pass-accuracy percentage from accurate/total passes; '' if unavailable."""
        try:
            acc = float(team_stats.get('accuratePasses') or 0)
            tot = float(team_stats.get('totalPasses') or 0)
            return str(round(acc / tot * 100)) if tot else ''
        except (ValueError, TypeError, ZeroDivisionError):
            return ''

    def _format_stats_for_ai(self, match_data: Dict[str, Any]) -> str:
        """Format match stats into a concise string for AI prompts."""
        stats = match_data.get('stats', {})
        home_stats = stats.get('home', {})
        away_stats = stats.get('away', {})
        if not home_stats and not away_stats:
            return ''

        parts = []
        home_poss = home_stats.get('possessionPct', '')
        away_poss = away_stats.get('possessionPct', '')
        if home_poss and away_poss:
            parts.append(f"Possession: {home_poss}%-{away_poss}%")

        home_shots = home_stats.get('totalShots', '')
        away_shots = away_stats.get('totalShots', '')
        if home_shots and away_shots:
            home_sot = home_stats.get('shotsOnTarget', '')
            away_sot = away_stats.get('shotsOnTarget', '')
            if home_sot and away_sot:
                parts.append(f"Shots: {home_shots}-{away_shots} ({home_sot}-{away_sot} on target)")
            else:
                parts.append(f"Shots: {home_shots}-{away_shots}")

        home_corners = home_stats.get('wonCorners', '')
        away_corners = away_stats.get('wonCorners', '')
        if home_corners and away_corners:
            parts.append(f"Corners: {home_corners}-{away_corners}")

        return ". ".join(parts)

    @staticmethod
    def _event_sort_key(event: Dict[str, Any]):
        """
        Chronological sort key from ESPN's displayClock minute string. Handles
        "23'", "45'+2" (stoppage), and "67:30" (mm:ss). Events with no minute
        (synthetic score_update/score_correction) sort to the end.
        """
        m = str(event.get('minute', '')).strip().replace("'", "")
        if not m:
            return (10 ** 6, 0)
        added = 0
        if '+' in m:
            base, _, extra = m.partition('+')
            added = int(''.join(c for c in extra if c.isdigit()) or 0)
            m = base
        if ':' in m:
            base, _, sec = m.partition(':')
            return (int(''.join(c for c in base if c.isdigit()) or 0),
                    int(''.join(c for c in sec if c.isdigit()) or 0))
        digits = ''.join(c for c in m if c.isdigit())
        return (int(digits) if digits else 10 ** 6, added)

    async def _post_to_bot(self, path: str, request_data: Dict[str, Any]):
        """
        Send to the bot HTTP API OFF the event loop. send_to_discord_bot is a
        blocking requests call (30s timeout); running it inline would stall every
        session's polling AND the Redis heartbeat for up to 30s, which can get the
        container marked unhealthy and killed mid-match. Offloading to the thread
        pool keeps the loop (and heartbeat) responsive while a bot POST is slow.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, send_to_discord_bot, path, request_data)

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
                stats_str = self._format_stats_for_ai(match_data)
                context = {
                    'home_team': {'displayName': home_team},
                    'away_team': {'displayName': away_team},
                    'home_score': str(home_score),
                    'away_score': str(away_score),
                    'competition': session_data.get('competition', 'MLS'),
                    'match_context': f"{home_team} {home_score}-{away_score} {away_team}",
                    'score': f"{home_score}-{away_score}",
                    'stats': stats_str,
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
                stats_str = self._format_stats_for_ai(match_data)
                context = {
                    'home_team': {'displayName': home_team},
                    'away_team': {'displayName': away_team},
                    'home_score': str(home_score),
                    'away_score': str(away_score),
                    'competition': session_data.get('competition', 'MLS'),
                    'match_context': f"{home_team} {home_score}-{away_score} {away_team}",
                    'score': f"{home_score}-{away_score}",
                    'stats': stats_str,
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
                    # Full-time leads with the scorer recap; venue/referee trail the stats
                    ft_goals, ft_meta = [], []
                    if event_type == 'fulltime':
                        recap = self._build_fulltime_recap_fields(session_id, match_data)
                        ft_goals = [f for f in recap if f['name'] == 'Goals']
                        ft_meta = [f for f in recap if f['name'] != 'Goals']

                    embed['fields'].extend(ft_goals)
                    embed['fields'].extend(self._build_stats_fields(match_data))

                    # Add attendance for fulltime
                    attendance = match_data.get('attendance', 0)
                    if attendance and event_type == 'fulltime':
                        embed['fields'].append({
                            'name': 'Attendance',
                            'value': f"{attendance:,}",
                            'inline': True
                        })

                    embed['fields'].extend(ft_meta)

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
                response = await self._post_to_bot('/api/live-reporting/event', request_data)
                if response and response.get('success'):
                    logger.info(f"Sent {event_type} lifecycle message for session {session_id}")
                else:
                    error_msg = response.get('error', 'Unknown') if response else 'No response'
                    logger.error(f"Failed to send {event_type} message: {error_msg}")
            except Exception as e:
                logger.error(f"Error sending lifecycle event: {e}")

    async def _extract_new_events(self, session_id: int, match_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Return events not yet posted for this session.

        This does NOT mark events as processed. A dedup key is committed to
        self.last_events only AFTER its Discord post is confirmed (see
        _process_session_realtime), so a transient/failed post is retried on the
        next poll instead of being silently dropped. Each returned event carries a
        stable '_dedup_key' used both for that commit and as the bot idempotency id.
        """
        new_events = []

        try:
            # Get current events from match data
            events = match_data.get('events', [])

            # Already-posted keys (committed only after confirmed posts)
            processed_events = self.last_events.get(session_id, set())
            batch_seen = set()  # avoid returning the same event twice within one poll

            for event in events:
                # Build a robust dedup key from all available fields. ESPN
                # keyEvents carry a unique 'id' but we include type/minute/
                # player/team so dedup survives even if id is missing.
                parts = [
                    event.get('id', ''),
                    event.get('type', 'unknown'),
                    str(event.get('minute', '0')),
                    event.get('player', event.get('athlete_name', '')),
                    event.get('team', event.get('team_id', '')),
                ]
                event_id = '_'.join(p for p in parts if p)

                if event_id not in processed_events and event_id not in batch_seen:
                    batch_seen.add(event_id)
                    event['_dedup_key'] = event_id
                    new_events.append(event)

            # Score-change detection (skip during halftime — score can't change).
            # The Redis/DB score is NOT advanced here; it is committed only after
            # the score-carrying event posts successfully (_commit_pending_score),
            # so a dropped goal post can't silently desync the scoreline.
            self._pending_score.pop(session_id, None)
            status = self._get_match_status(match_data)
            if status != 'HALFTIME':
                current_score = self._get_current_score(match_data)
                last_score_key = f"last_score_{session_id}"
                last_score_raw = self.redis_service.get(last_score_key)
                if isinstance(last_score_raw, bytes):
                    last_score_raw = last_score_raw.decode('utf-8')
                last_score = str(last_score_raw) if last_score_raw is not None else None

                # A score DECREASE means a goal was rolled back (VAR/correction).
                decreased = last_score is not None and self._score_decreased(last_score, current_score)
                if not decreased:
                    self._pending_correction.pop(session_id, None)

                if last_score != current_score:
                    if decreased:
                        # Debounce: only announce a SUSTAINED decrease (ESPN scores
                        # can briefly flicker). First sighting is remembered without
                        # advancing the score or posting, so a flicker self-heals.
                        if self._pending_correction.get(session_id) == current_score:
                            self._pending_correction.pop(session_id, None)
                            self._pending_score[session_id] = (current_score, 'score_correction')
                            new_events.append({
                                'type': 'score_correction',
                                'current_score': current_score,
                                'previous_score': last_score,
                                '_dedup_key': f"scorecorr_{last_score}_{current_score}",
                            })
                        else:
                            self._pending_correction[session_id] = current_score
                    else:
                        has_goal_event = any(
                            e.get('type', '').upper() in ('GOAL', 'OWN GOAL', 'PENALTY', 'OWN_GOAL', 'PENALTY_GOAL')
                            for e in new_events
                        )
                        if last_score is None:
                            # First observation — seed the score silently, nothing to post.
                            self._pending_score[session_id] = (current_score, 'seed')
                        elif has_goal_event:
                            # A goal carries the score change; advance only if it posts.
                            self._pending_score[session_id] = (current_score, 'goal')
                        elif self._post_score_updates:
                            # Score moved with no goal event — emit a standalone update.
                            self._pending_score[session_id] = (current_score, 'score_update')
                            new_events.append({
                                'type': 'score_update',
                                'current_score': current_score,
                                'previous_score': last_score,
                                '_dedup_key': f"score_{current_score}",
                            })
                        else:
                            # Routine score change, no goal keyEvent and score-updates
                            # disabled — advance the score silently (no spam embed).
                            self._pending_score[session_id] = (current_score, 'score_silent')

        except Exception as e:
            logger.error(f"Error extracting events for session {session_id}: {e}")

        return new_events

    def _commit_pending_score(self, session_id: int, new_events: Optional[List[Dict[str, Any]]] = None,
                              posted_keys: Optional[Set[str]] = None):
        """
        Advance the Redis last_score for a session, but only if the event that
        carried the score change actually posted (so a dropped goal post doesn't
        desync the scoreline). posted_keys=None commits unconditionally — used for
        the silent first-cycle seed and for catch-up after a restart.
        """
        pending = self._pending_score.pop(session_id, None)
        if not pending:
            return
        current_score, carrier = pending

        if posted_keys is None or carrier in ('seed', 'score_silent'):
            commit = True
        elif carrier == 'goal':
            goal_types = ('GOAL', 'OWN GOAL', 'PENALTY', 'OWN_GOAL', 'PENALTY_GOAL')
            commit = any(
                e.get('type', '').upper() in goal_types and e.get('_dedup_key') in posted_keys
                for e in (new_events or [])
            )
        elif carrier in ('score_update', 'score_correction'):
            commit = any(
                e.get('type') == carrier and e.get('_dedup_key') in posted_keys
                for e in (new_events or [])
            )
        else:
            commit = False

        if commit:
            try:
                self.redis_service.setex(f"last_score_{session_id}", 3600, str(current_score))
            except Exception as e:
                logger.error(f"Error committing score for session {session_id}: {e}")

    @staticmethod
    def _score_decreased(last_score: str, current_score: str) -> bool:
        """True if either side's goal count dropped (a goal was rolled back)."""
        try:
            lh, la = (int(x) for x in str(last_score).split('-'))
            ch, ca = (int(x) for x in str(current_score).split('-'))
            return ch < lh or ca < la
        except (ValueError, AttributeError):
            return False

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
        'penalty_missed': 0x9CA3AF,  # Grey — non-scoring penalty
        'penalty_saved': 0x9CA3AF,
        'score_correction': 0xD97706,  # Amber — goal rolled back (VAR/correction)
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
            'penalty_missed': 'Penalty Missed',
            'penalty_saved': 'Penalty Saved',
            'score_correction': 'Goal Disallowed',
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

        # Assist (open-play goals only)
        assist = event.get('assist', '')
        if assist and event_type == 'goal':
            embed['fields'].append({'name': 'Assist', 'value': assist, 'inline': True})

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

        # Team logo as author icon — only for our side, not the opponent
        if team:
            author = {'name': team}
            opponent_name = session_data.get('opponent', '')
            if team_logo and team != opponent_name:
                author['icon_url'] = team_logo
            embed['author'] = author

        return embed

    async def _send_events_to_discord(self, session_id: int, session_data: Dict[str, Any],
                                      events: List[Dict[str, Any]]) -> Set[str]:
        """
        Send new events to Discord via bot API with rich embeds.

        Returns the set of '_dedup_key's that posted successfully, so the caller
        commits only those (failed events stay un-deduped and retry next cycle).
        """
        posted_keys: Set[str] = set()
        thread_id = session_data.get('thread_id')
        match_id_str = str(session_data.get('match_id', ''))
        if not thread_id:
            logger.warning(f"Session {session_id}: No thread ID — cannot post {len(events)} events")
            log_event(
                stage="post", outcome="error", session_id=session_id,
                match_id=match_id_str,
                message=f"No thread_id; dropped {len(events)} events",
            )
            return posted_keys

        logger.info(f"Session {session_id}: Posting {len(events)} event(s) to thread {thread_id}")
        posted = 0
        skipped = 0
        failed = 0

        # Post in match-clock order (ESPN keyEvents aren't guaranteed chronological,
        # and synthetic score events carry no minute — they sort last).
        events = sorted(events, key=self._event_sort_key)

        for event in events:
            event_type = event.get('type', 'unknown')
            event_player = event.get('player', 'Unknown')
            event_minute = event.get('minute', '?')
            try:
                # Generate AI-or-ESPN-fallback commentary text
                message_content = self._format_event_message(event, session_data)
                if not message_content:
                    skipped += 1
                    logger.warning(
                        f"Session {session_id}: Skipping {event_type} event "
                        f"({event_player}, {event_minute}') — no message content produced"
                    )
                    log_event(
                        stage="post", outcome="error", session_id=session_id,
                        match_id=match_id_str,
                        message=f"Skipped {event_type} — no message content",
                        context={"event_type": event_type, "player": event_player, "minute": event_minute},
                    )
                    continue

                # Build rich embed for the bot API
                embed = self._build_event_embed(event, session_data, message_content)

                # Sanitize event data for JSON serialization
                clean_event = {
                    'type': str(event_type),
                    'player': str(event_player),
                    'minute': str(event_minute),
                    'team': str(event.get('team', 'Unknown')),
                    'description': str(event.get('description', ''))
                }

                request_data = {
                    'thread_id': thread_id,
                    'event_type': event_type,
                    'content': message_content,
                    # Stable idempotency id so a retry (e.g. after a timeout the bot
                    # actually delivered) can't double-post the same event.
                    'idempotency_key': event.get('_dedup_key'),
                    'match_data': {
                        'session_id': session_id,
                        'match_id': session_data.get('match_id'),
                        'event': clean_event
                    }
                }

                # Include embed if we built one
                if embed:
                    request_data['embed'] = embed

                response = await self._post_to_bot('/api/live-reporting/event', request_data)

                if response and response.get('success'):
                    posted += 1
                    if event.get('_dedup_key'):
                        posted_keys.add(event['_dedup_key'])
                    # Accumulate goals for the full-time recap (keyEvents are
                    # stripped from ESPN's payload at FT, so we must collect live).
                    if event_type.upper() in ('GOAL', 'OWN_GOAL', 'PENALTY_GOAL'):
                        self._session_goals.setdefault(session_id, []).append({
                            'minute': event.get('minute', ''),
                            'player': event.get('player', ''),
                            'team': event.get('team', ''),
                            'type': event_type.upper(),
                            'assist': event.get('assist', ''),
                        })
                    logger.info(
                        f"Session {session_id}: Posted {event_type} event "
                        f"({event_player}, {event_minute}') to Discord"
                    )
                    log_event(
                        stage="post", outcome="ok", session_id=session_id,
                        match_id=match_id_str,
                        message=f"Posted {event_type}: {event_player} {event_minute}'",
                        context={
                            "event_type": event_type, "player": event_player,
                            "minute": event_minute, "team": event.get('team'),
                            "content": message_content[:200],
                        },
                    )
                else:
                    failed += 1
                    error_msg = response.get('error', 'Unknown error') if response else 'No response'
                    logger.error(
                        f"Session {session_id}: Bot rejected {event_type} event "
                        f"({event_player}, {event_minute}'): {error_msg}"
                    )
                    log_event(
                        stage="post", outcome="error", session_id=session_id,
                        match_id=match_id_str,
                        message=f"Bot rejected {event_type} ({event_player}, {event_minute}'): {error_msg}",
                        context={"event_type": event_type, "error": error_msg},
                    )

            except Exception as e:
                failed += 1
                logger.error(
                    f"Session {session_id}: Exception posting {event_type} event "
                    f"({event_player}, {event_minute}'): {e}",
                    exc_info=True,
                )
                log_event(
                    stage="post", outcome="error", session_id=session_id,
                    match_id=match_id_str,
                    message=f"Exception posting {event_type}: {e}",
                    context={"event_type": event_type, "player": event_player},
                )

        logger.info(
            f"Session {session_id}: Event batch complete — "
            f"posted={posted}, skipped={skipped}, failed={failed}"
        )
        log_event(
            stage="post", outcome="info", session_id=session_id,
            match_id=match_id_str,
            message=f"Batch: posted={posted}, skipped={skipped}, failed={failed}",
            context={"posted": posted, "skipped": skipped, "failed": failed},
        )

        return posted_keys

    def _record_event_history(self, session_id, event_type, minute, player, team, home_team):
        """Append an event to the per-session history used for AI context."""
        self.match_history.setdefault(session_id, []).append({
            'event_type': event_type,
            'minute': minute,
            'player': player,
            'team': 'home' if team == home_team else 'away',
        })

    def _build_template_ctx(self, event: Dict[str, Any], session_data: Dict[str, Any],
                            event_type: str, player: str, team: str, minute) -> Dict[str, Any]:
        """
        Build the Sounders-perspective context for the template engine.

        'opponent' (set on the session for logo suppression) identifies the
        NON-Sounders side, so the Sounders side is whichever of home/away isn't
        the opponent. Score is rendered us-them. is_our_event drives for/against
        line selection (own goals are neutral, so the value is ignored there).
        """
        home_team = session_data.get('home_team', '') or ''
        away_team = session_data.get('away_team', '') or ''
        opponent = session_data.get('opponent', '') or ''
        home_score = session_data.get('home_score', 0) or 0
        away_score = session_data.get('away_score', 0) or 0

        # Sounders is home unless the opponent IS the home team.
        sounders_is_home = True if not opponent else (home_team != opponent)
        if sounders_is_home:
            sounders_team, sounders_score, opp_score = home_team, home_score, away_score
        else:
            sounders_team, sounders_score, opp_score = away_team, away_score, home_score

        if event_type == 'own_goal':
            is_our = False  # neutral templates; value unused
        elif sounders_team:
            is_our = (team == sounders_team)
        else:
            is_our = bool(opponent) and (team != opponent)

        if sounders_score > opp_score:
            score_state = 'us_ahead'
        elif sounders_score < opp_score:
            score_state = 'behind'
        else:
            score_state = 'level'

        return {
            'event_type': event_type,
            'is_our_event': is_our,
            'player': player,
            'team': team,
            'minute': minute,
            'assist': event.get('assist', ''),
            'player_on': event.get('player_on', ''),
            'player_off': event.get('player_off', ''),
            'score': f"{sounders_score}-{opp_score}",
            'score_state': score_state,
            'rivalry': detect_rivalry(opponent),
            'match_id': str(session_data.get('match_id', '')),
        }

    def _format_event_message(self, event: Dict[str, Any], session_data: Dict[str, Any]) -> Optional[str]:
        """Format an event into a Discord message (template-first, then optional AI, then ESPN text)."""
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

            event_type = event_type.lower()
            match_id_str = str(session_data.get('match_id', ''))
            match_id_arg = match_id_str or None

            discrete_types = ['goal', 'own_goal', 'penalty_goal', 'penalty_missed',
                              'penalty_saved', 'yellow_card', 'red_card', 'substitution']
            if event_type in discrete_types:
                # The real ESPN description is the factual floor / final fallback.
                espn_description = event.get('description', '')
                if not espn_description:
                    espn_description = f"{event.get('detail_text', event_type.replace('_', ' ').title())}. {player} ({team}). {minute}."

                # 1) Template-first ("mad-lib"): deterministic, human-authored lines
                #    filled from real ESPN data — undetectable as AI. Refuses (None)
                #    on missing data so we fall through to the ESPN text, never a
                #    hollow line.
                if self._template_first:
                    tmpl_ctx = self._build_template_ctx(event, session_data, event_type, player, team, minute)
                    tmpl_text = generate_with_validation(
                        generate_fn=lambda: self.template_engine.render(tmpl_ctx),
                        fallback_fn=lambda: None,
                        commentary_type=CommentaryType.MATCH_EVENT,
                        match_id=match_id_arg,
                        max_attempts=3,
                        strict=False,  # curated human lines — the AI-ism gate is moot
                    )
                    if tmpl_text:
                        self._record_event_history(session_id, event_type, minute, player, team, home_team)
                        logger.info(f"Session {session_id}: Template commentary for {event_type} ({player}, {minute}')")
                        log_event(
                            stage="ai", outcome="template", session_id=session_id,
                            match_id=match_id_str,
                            message=f"Template: {tmpl_text[:160]}",
                            context={"event_type": event_type, "player": player, "minute": minute, "team": team},
                        )
                        return tmpl_text

                # 2) LLM commentary — only when template-first is off, or AI 'spice'
                #    is explicitly enabled.
                if (not self._template_first) or self._ai_spice:
                    norm_type = 'goal' if event_type in ('own_goal', 'penalty_goal') else event_type
                    ai_context = {
                        'match_id': session_data.get('match_id', ''),
                        'home_team': {'displayName': home_team},
                        'away_team': {'displayName': away_team},
                        'event_type': norm_type,
                        'player': player,
                        'minute': minute,
                        'home_score': session_data.get('home_score', 0),
                        'away_score': session_data.get('away_score', 0),
                        'assist': event.get('assist', ''),
                        'description': espn_description,
                    }
                    if norm_type == 'goal':
                        ai_context['scoring_team'] = team
                    if event_type in ('yellow_card', 'red_card', 'substitution'):
                        ai_context['team'] = team
                    if event_type == 'substitution':
                        ai_context['player_on'] = event.get('player_on', player)
                        ai_context['player_off'] = event.get('player_off', 'Unknown Player')

                    match_history = self.match_history.get(session_id, [])
                    ai_commentary = self.ai_client.generate_match_event_commentary(ai_context, match_history)
                    if ai_commentary:
                        self._record_event_history(session_id, event_type, minute, player, team, home_team)
                        logger.info(f"Session {session_id}: AI commentary for {event_type} ({player}, {minute}')")
                        log_event(
                            stage="ai", outcome="ok", session_id=session_id,
                            match_id=match_id_str,
                            message=f"AI ok: {ai_commentary[:160]}",
                            context={"event_type": event_type, "player": player, "minute": minute, "team": team},
                        )
                        return ai_commentary

                # 3) ESPN description fallback — real factual content, always safe.
                fallback_text = espn_description or (
                    f"{event_type.replace('_', ' ').title()}. {player} ({team}). {minute}."
                )
                self._record_event_history(session_id, event_type, minute, player, team, home_team)
                log_event(
                    stage="ai", outcome="fallback", session_id=session_id,
                    match_id=match_id_str,
                    message=f"ESPN fallback: {fallback_text[:160]}",
                    context={"event_type": event_type, "player": player, "minute": minute, "team": team},
                )
                return fallback_text

            # Fallback to static messages for other events
            if event_type == 'score_update':
                current_score = event.get('current_score', '0-0')
                return f"{home_team} {current_score} {away_team}"

            elif event_type == 'score_correction':
                current_score = event.get('current_score', '0-0')
                return f"Goal ruled out. Back to {home_team} {current_score} {away_team}."

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
                    is_match_end = (
                        'ended' in reason.lower()
                        or 'FINAL' in reason
                        or 'COMPLETED' in reason
                    )
                    log_event(
                        stage="session",
                        outcome="ok" if is_match_end else "info",
                        session_id=session_id,
                        match_id=str(live_session.match_id),
                        message=f"Session deactivated: {reason}",
                    )

                    # Always archive the thread silently — users don't need a
                    # Discord embed announcing timeouts or errors. The reason
                    # is preserved in server logs (see logger.info above) and
                    # in the LiveReportingSession DB record for diagnostics.
                    await self._archive_thread(live_session.thread_id)

                    # Clean up in-memory tracking
                    self.last_events.pop(session_id, None)
                    self._last_statuses.pop(session_id, None)
                    self.match_history.pop(session_id, None)
                    self._unknown_status_counts.pop(session_id, None)
                    self._session_goals.pop(session_id, None)
                    self._pending_score.pop(session_id, None)
                    self._pending_correction.pop(session_id, None)

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
            await self._post_to_bot('/api/live-reporting/final', request_data)
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

            await self._post_to_bot('/api/live-reporting/final', request_data)
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