# app/services/live_reporting/match_monitor.py

"""
Match Monitoring Service

Event-driven match monitoring with industry standard patterns:
- Service composition
- Dependency injection
- Event sourcing patterns
- Comprehensive error handling
- Health monitoring
"""

import logging
import asyncio
import time
from typing import List, Dict, Any, Optional, Set
from datetime import datetime, timedelta
from dataclasses import dataclass
import json

from .config import LiveReportingConfig, MatchEventContext, get_config
from .repositories import MatchRepository, LiveReportingRepository
from .espn_client import ESPNClient, MatchData
from .discord_client import DiscordClient
from .ai_client import AICommentaryClient
from .metrics import MetricsCollector, get_metrics
from .models import MatchEvent
from app.models import LiveReportingSession

logger = logging.getLogger(__name__)


# MatchEvent is imported from .models below


@dataclass
class MonitoringResult:
    """Result of monitoring a match."""
    success: bool
    match_id: str
    status: str
    score: str
    events_processed: int
    new_events: List[MatchEvent]
    error_message: Optional[str] = None
    match_ended: bool = False


class MatchMonitoringService:
    """
    Core service for monitoring live matches.
    
    This service orchestrates all components to provide live match reporting:
    - Fetches data from ESPN API
    - Processes new events
    - Generates AI commentary
    - Posts updates to Discord
    - Manages database state
    
    Uses dependency injection and composition for testability and maintainability.
    """
    
    def __init__(
        self,
        config: LiveReportingConfig,
        match_repo: MatchRepository,
        live_repo: LiveReportingRepository,
        espn_client: ESPNClient,
        discord_client: DiscordClient,
        ai_client: AICommentaryClient,
        metrics: MetricsCollector
    ):
        self.config = config
        self.match_repo = match_repo
        self.live_repo = live_repo
        self.espn_client = espn_client
        self.discord_client = discord_client
        self.ai_client = ai_client
        self.metrics = metrics
        
        # Event deduplication
        self._processed_events: Dict[str, Set[str]] = {}
    
    async def monitor_match(
        self,
        match_id: str,
        thread_id: Optional[str] = None,
        competition: str = "usa.1"
    ) -> MonitoringResult:
        """
        Monitor a single match for live updates.
        
        Args:
            match_id: ESPN match ID
            thread_id: Discord thread ID for posting updates
            competition: Competition identifier
            
        Returns:
            MonitoringResult with processing details
        """
        logger.info(f"Monitoring match {match_id}")
        
        try:
            # Get current session state
            session = await self.live_repo.get_session(match_id)
            if not session or not session.is_active:
                logger.warning(f"No active session for match {match_id}")
                return MonitoringResult(
                    success=False,
                    match_id=match_id,
                    status="NO_SESSION",
                    score="0-0",
                    events_processed=0,
                    new_events=[],
                    error_message="No active session found"
                )
            
            # Fetch match data from ESPN
            match_data = await self.espn_client.get_match_data(match_id, competition)
            if not match_data:
                logger.error(f"Failed to fetch match data for {match_id}")
                await self._handle_monitoring_error(session, "Failed to fetch ESPN data")
                return MonitoringResult(
                    success=False,
                    match_id=match_id,
                    status="FETCH_ERROR",
                    score=session.last_score or "0-0",
                    events_processed=0,
                    new_events=[],
                    error_message="Failed to fetch ESPN data"
                )
            
            # Handle pre-match state (5 minutes before kickoff)
            if match_data.status == 'STATUS_SCHEDULED':
                # Check if we should post pre-match hype
                if await self._should_post_pre_match(session, match_data):
                    logger.info(f"Posting pre-match hype for match {match_id}")
                    if thread_id and self.config.enable_discord_posting:
                        await self._post_pre_match_hype(match_data, thread_id)
                        # Update session to mark pre-match as posted
                        await self.live_repo.update_session(
                            match_id=match_id,
                            status='PRE_MATCH_POSTED'
                        )
                
                # Continue monitoring but don't process events yet
                return MonitoringResult(
                    success=True,
                    match_id=match_id,
                    status=match_data.status,
                    score="0-0",
                    events_processed=0,
                    new_events=[]
                )
            
            # Check if match has ended
            if self._is_match_ended(match_data.status):
                logger.info(f"Match {match_id} has ended with status {match_data.status}")
                await self.live_repo.deactivate_session(match_id, f"Match ended: {match_data.status}")
                
                # Post final update if configured
                if thread_id and self.config.enable_discord_posting:
                    await self._post_final_update(match_data, thread_id)
                
                return MonitoringResult(
                    success=True,
                    match_id=match_id,
                    status=match_data.status,
                    score=match_data.score,
                    events_processed=0,
                    new_events=[],
                    match_ended=True
                )
            
            # Check for status changes (match phases)
            status_events = await self._check_status_changes(match_data, session)
            
            # Process regular match events
            regular_events = await self._process_match_events(match_data, session)
            
            # Combine status events and regular events
            new_events = status_events + regular_events
            
            # Generate commentary and post updates if there are new events
            if new_events and thread_id and self.config.enable_discord_posting:
                await self._post_match_updates(match_data, new_events, thread_id)
            
            # Update session in database with accumulated event keys
            previous_keys = set(session.parsed_event_keys)
            new_event_keys = [event.to_key() for event in new_events] if new_events else []
            all_event_keys = list(previous_keys.union(set(new_event_keys)))
            
            await self.live_repo.update_session(
                match_id=match_id,
                status=match_data.status,
                score=match_data.score,
                event_keys=all_event_keys,
                increment_updates=True
            )
            
            # Update metrics
            self.metrics.record_match_event("match_monitored")
            for event in new_events:
                self.metrics.record_match_event(event.event_type.lower())
            
            logger.info(f"Successfully monitored match {match_id}: {len(new_events)} new events")
            
            return MonitoringResult(
                success=True,
                match_id=match_id,
                status=match_data.status,
                score=match_data.score,
                events_processed=len(new_events),
                new_events=new_events
            )
            
        except Exception as e:
            logger.error(f"Error monitoring match {match_id}: {e}", exc_info=True)
            if session:
                await self._handle_monitoring_error(session, str(e))
            
            return MonitoringResult(
                success=False,
                match_id=match_id,
                status="ERROR",
                score="0-0",
                events_processed=0,
                new_events=[],
                error_message=str(e)
            )
    
    async def _process_match_events(
        self,
        match_data: MatchData,
        session: LiveReportingSession
    ) -> List[MatchEvent]:
        """
        Process new match events from ESPN data.
        
        Args:
            match_data: Current match data
            session: Live reporting session
            
        Returns:
            List of new MatchEvent objects
        """
        # Get previously processed event keys
        previous_keys = set(session.parsed_event_keys)
        
        # Convert ESPN events to MatchEvent objects
        current_events = []
        for espn_event in match_data.events:
            # Extract basic event info
            event_id = espn_event.get('id', f"event_{len(current_events)}")
            event_type = espn_event.get('type', 'Unknown')
            description = espn_event.get('text', '')
            clock = espn_event.get('clock', '')
            team_id = espn_event.get('team_id', '')
            athlete_id = espn_event.get('athlete_id', '')
            athlete_name = espn_event.get('athlete_name', '')
            
            # Create match event
            match_event = MatchEvent(
                event_id=event_id,
                event_type=event_type,
                description=description,
                clock=clock,
                team_id=team_id,
                athlete_id=athlete_id,
                athlete_name=athlete_name,
                raw_data=espn_event
            )
            current_events.append(match_event)
        
        # Filter out already processed events
        new_events = []
        for event in current_events:
            event_key = event.to_key()
            if event_key not in previous_keys:
                new_events.append(event)
        
        # Update processed events cache
        if match_data.match_id not in self._processed_events:
            self._processed_events[match_data.match_id] = set()
        
        for event in new_events:
            self._processed_events[match_data.match_id].add(event.to_key())
        
        # Clean up old processed events (keep last 50)
        if len(self._processed_events[match_data.match_id]) > 50:
            sorted_events = sorted(self._processed_events[match_data.match_id])
            self._processed_events[match_data.match_id] = set(sorted_events[-50:])
        
        logger.debug(f"Processed {len(current_events)} total events, {len(new_events)} new events for match {match_data.match_id}")
        return new_events
    
    async def _post_match_updates(
        self,
        match_data: MatchData,
        new_events: List[MatchEvent],
        thread_id: str
    ):
        """
        Post individual match updates to Discord (one embed per event).
        
        Args:
            match_data: Current match data
            new_events: New events to post about
            thread_id: Discord thread ID
        """
        try:
            # Process each event individually for separate embeds
            for event in new_events:
                # Convert MatchEvent object to dict format for AI client
                event_dict = {
                    'id': event.event_id,
                    'type': event.event_type,
                    'text': event.description,
                    'clock': event.clock,
                    'team_id': event.team_id,
                    'athlete_id': event.athlete_id,
                    'athlete_name': event.athlete_name
                }
                
                # Generate AI commentary for this single event
                commentary = await self.ai_client.generate_commentary(
                    match_data=match_data,
                    single_event=event_dict
                )
                
                # Create Discord embed for this single event
                embed = self.discord_client.create_match_embed(match_data, commentary)
                
                # Post individual event to Discord
                message_id = await self.discord_client.post_message(
                    channel_id=thread_id,
                    embed=embed
                )
                
                if message_id:
                    logger.info(f"Posted individual event update {message_id} for {event.event_type} at {event.clock}")
                    self.metrics.record_match_update_posted("live_event")
                else:
                    logger.warning(f"Failed to post {event.event_type} event to Discord thread {thread_id}")
                
                # Minimal delay between posts for near real-time updates
                await asyncio.sleep(0.1)
                
        except Exception as e:
            logger.error(f"Error posting match updates: {e}", exc_info=True)
    
    async def _post_final_update(self, match_data: MatchData, thread_id: str):
        """Post final match result to Discord."""
        try:
            final_commentary = f"FINAL: {match_data.home_team['name']} {match_data.score} {match_data.away_team['name']}"
            embed = self.discord_client.create_match_embed(match_data, final_commentary)
            
            message_id = await self.discord_client.post_message(
                channel_id=thread_id,
                embed=embed
            )
            
            if message_id:
                logger.info(f"Posted final result {message_id} to Discord thread {thread_id}")
                self.metrics.record_match_update_posted("final_result")
                
        except Exception as e:
            logger.error(f"Error posting final update: {e}", exc_info=True)
    
    async def _check_status_changes(self, match_data: MatchData, session: 'LiveReportingSession') -> List['MatchEvent']:
        """
        Check for match status changes and generate events.
        
        Args:
            match_data: Current match data
            session: Live reporting session
            
        Returns:
            List of status change events
        """
        status_events = []
        current_status = match_data.status
        previous_status = session.last_status
        
        # Skip if status hasn't changed
        if current_status == previous_status:
            return status_events
        
        logger.info(f"Status change detected for match {match_data.match_id}: {previous_status} -> {current_status}")
        
        # MatchEvent is imported at the top of the file
        
        # Generate status change events
        event_text = ""
        event_type = "Status Change"
        
        if current_status == 'STATUS_IN_PROGRESS' and previous_status in [None, 'STATUS_SCHEDULED', 'STATUS_PRE']:
            event_text = "⚽ KICKOFF! The match has started!"
            event_type = "Match Start"
        elif current_status in ['STATUS_HALFTIME', 'STATUS_BREAK']:
            event_text = "🕐 HALFTIME - Teams head to the locker rooms"
            event_type = "Halftime"
        elif current_status == 'STATUS_SECOND_HALF' and previous_status in ['STATUS_HALFTIME', 'STATUS_BREAK']:
            event_text = "⚽ SECOND HALF UNDERWAY!"
            event_type = "Second Half Start"
        elif current_status in ['STATUS_FINAL', 'STATUS_FULL_TIME']:
            event_text = f"🏁 FULL TIME! Final score: {match_data.score}"
            event_type = "Full Time"
        elif current_status == 'STATUS_EXTRA_TIME':
            event_text = "⏰ EXTRA TIME! We're going to 30 minutes of additional play!"
            event_type = "Extra Time Start"
        elif current_status == 'STATUS_FINAL_ET':
            event_text = f"🏁 EXTRA TIME FINISHED! Final score: {match_data.score}"
            event_type = "Extra Time End"
        elif current_status == 'STATUS_PENALTY_SHOOTOUT':
            event_text = "🥅 PENALTY SHOOTOUT! This is it!"
            event_type = "Penalty Shootout Start"
        elif current_status == 'STATUS_FINAL_PEN':
            event_text = f"🏆 PENALTIES DECIDED IT! Final result: {match_data.score}"
            event_type = "Penalty Shootout End"
        
        # Create status event if we have text
        if event_text:
            status_event = MatchEvent(
                event_id=f"status_{current_status}_{int(time.time())}",
                event_type=event_type,
                description=event_text,
                clock="",  # Status changes don't have specific clock times
                team_id="",
                athlete_id="",
                athlete_name="",
                raw_data={"status_change": {"from": previous_status, "to": current_status}}
            )
            status_events.append(status_event)
            
        return status_events

    def _is_match_ended(self, status: str) -> bool:
        """Check if match has ended based on status."""
        ended_statuses = [
            'STATUS_FINAL', 'STATUS_FULL_TIME', 'STATUS_FINAL_PEN',
            'STATUS_FINAL_ET', 'STATUS_ABANDONED', 'STATUS_CANCELLED'
        ]
        return status in ended_statuses
    
    async def _should_post_pre_match(self, session: LiveReportingSession, match_data: MatchData) -> bool:
        """
        Check if we should post pre-match hype.
        Posts when match is scheduled and we haven't posted pre-match yet,
        and we're within 5 minutes of kickoff.
        """
        # Check if we've already posted pre-match
        if session.last_status == 'PRE_MATCH_POSTED':
            return False
        
        # Check if this is the first time monitoring (when live reporting starts 5 minutes before)
        # If session was just created, it means we're in the pre-match window
        if session.update_count == 0:
            logger.info(f"First monitoring cycle for match {session.match_id} - posting pre-match hype")
            return True
        
        return False
    
    async def _post_pre_match_hype(self, match_data: MatchData, thread_id: str):
        """Post pre-match hype message to Discord."""
        try:
            # Extract team forms from match data
            home_form = "N/A"
            away_form = "N/A"
            venue = "Unknown Venue"
            
            # Try to get form data from competitors
            if match_data.raw_data and 'competitions' in match_data.raw_data:
                competitions = match_data.raw_data['competitions']
                if competitions and len(competitions) > 0:
                    comp = competitions[0]
                    if 'competitors' in comp:
                        for competitor in comp['competitors']:
                            if competitor.get('homeAway') == 'home':
                                home_form = competitor.get('form', 'N/A')
                            elif competitor.get('homeAway') == 'away':
                                away_form = competitor.get('form', 'N/A')
                    if 'venue' in comp:
                        venue = comp['venue'].get('fullName', venue)
            
            # Create pre-match embed data
            pre_match_data = {
                'home_team': match_data.home_team,
                'away_team': match_data.away_team,
                'venue': venue,
                'home_form': home_form,
                'away_form': away_form
            }
            
            # Generate pre-match commentary
            is_home = match_data.home_team.get('id') == '9726'  # Seattle Sounders ID
            team_name = "Seattle Sounders FC"
            opponent_name = match_data.away_team['name'] if is_home else match_data.home_team['name']
            
            pre_match_message = f"🚨 **Pre-Match Hype: {match_data.home_team['name']} vs {match_data.away_team['name']}** 🚨\n\n"
            
            if is_home:
                pre_match_message += f"{team_name} is ready to dominate on home turf! Let's make Lumen Field rock! 🏟️💚\n\n"
            else:
                pre_match_message += f"{team_name} is ready for battle away from home—let's make it a statement! 🚀\n\n"
            
            pre_match_message += f"**🏟️ Venue:** {venue}\n"
            pre_match_message += f"**🏠 Home Form:** {home_form}\n"
            pre_match_message += f"**🛫 Away Form:** {away_form}\n\n"
            
            if is_home:
                pre_match_message += "**Home Fortress** 🏰\nTime to defend our turf and show them what Seattle is made of!"
            else:
                pre_match_message += "**Away Day Magic** ✈️\nWe're taking our A-game to their turf! Let's make our traveling fans proud!"
            
            # Post to Discord
            message_id = await self.discord_client.post_message(
                channel_id=thread_id,
                content=pre_match_message
            )
            
            if message_id:
                logger.info(f"Posted pre-match hype {message_id} to Discord thread {thread_id}")
                self.metrics.record_match_update_posted("pre_match_hype")
            
        except Exception as e:
            logger.error(f"Error posting pre-match hype: {e}", exc_info=True)
    
    async def _handle_monitoring_error(self, session: LiveReportingSession, error_message: str):
        """Handle monitoring errors and update session state."""
        try:
            await self.live_repo.update_session(
                match_id=session.match_id,
                error_message=error_message,
                increment_updates=False
            )
            
            # Deactivate session if too many errors
            if session.error_count + 1 >= self.config.max_error_count:
                await self.live_repo.deactivate_session(
                    session.match_id,
                    f"Too many errors: {session.error_count + 1}"
                )
                logger.error(f"Deactivated session for match {session.match_id} due to excessive errors")
            
            self.metrics.record_session_error("monitoring_error")
            
        except Exception as e:
            logger.error(f"Error handling monitoring error: {e}")
    
    async def get_health_status(self) -> Dict[str, Any]:
        """Get health status of all components."""
        health_status = {
            'overall': True,
            'timestamp': datetime.utcnow().isoformat(),
            'components': {}
        }
        
        # Check ESPN API health
        espn_healthy = await self.espn_client.health_check()
        health_status['components']['espn'] = espn_healthy
        self.metrics.update_health_status('espn', espn_healthy)
        
        # Check Discord API health
        discord_healthy = await self.discord_client.health_check()
        health_status['components']['discord'] = discord_healthy
        self.metrics.update_health_status('discord', discord_healthy)
        
        # Check AI service health
        ai_healthy = await self.ai_client.health_check()
        health_status['components']['ai'] = ai_healthy
        self.metrics.update_health_status('ai', ai_healthy)
        
        # Check database health
        db_healthy = await self.match_repo.health_check()
        health_status['components']['database'] = db_healthy
        self.metrics.update_health_status('database', db_healthy)
        
        # Overall health
        health_status['overall'] = all([
            espn_healthy, discord_healthy, db_healthy
            # AI is optional, don't fail overall health if it's down
        ])
        
        return health_status


class LiveReportingOrchestrator:
    """
    Main orchestrator for live reporting system.
    
    Manages the lifecycle of match monitoring and provides
    a clean interface for external systems.
    """
    
    def __init__(self, config: Optional[LiveReportingConfig] = None):
        self.config = config or get_config()
        self.metrics = get_metrics()
        self._services_initialized = False
        
        # Service instances (initialized lazily)
        self._match_repo: Optional[MatchRepository] = None
        self._live_repo: Optional[LiveReportingRepository] = None
        self._espn_client: Optional[ESPNClient] = None
        self._discord_client: Optional[DiscordClient] = None
        self._ai_client: Optional[AICommentaryClient] = None
        self._monitor_service: Optional[MatchMonitoringService] = None
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self._initialize_services()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self._cleanup_services()
    
    async def _initialize_services(self):
        """Initialize all service dependencies."""
        if self._services_initialized:
            return
        
        logger.info("Initializing live reporting services")
        
        # Initialize repositories
        self._match_repo = MatchRepository(self.config)
        self._live_repo = LiveReportingRepository(self.config)
        
        # Initialize clients
        self._espn_client = ESPNClient(self.config, self.metrics)
        await self._espn_client.__aenter__()
        
        self._discord_client = DiscordClient(self.config, self.metrics)
        await self._discord_client.__aenter__()
        
        self._ai_client = AICommentaryClient(self.config, self.metrics)
        await self._ai_client.__aenter__()
        
        # Initialize monitoring service
        self._monitor_service = MatchMonitoringService(
            config=self.config,
            match_repo=self._match_repo,
            live_repo=self._live_repo,
            espn_client=self._espn_client,
            discord_client=self._discord_client,
            ai_client=self._ai_client,
            metrics=self.metrics
        )
        
        self._services_initialized = True
        logger.info("Live reporting services initialized successfully")
    
    async def _cleanup_services(self):
        """Cleanup service resources."""
        if not self._services_initialized:
            return
        
        logger.info("Cleaning up live reporting services")
        
        try:
            if self._espn_client:
                await self._espn_client.__aexit__(None, None, None)
            if self._discord_client:
                await self._discord_client.__aexit__(None, None, None)
            if self._ai_client:
                await self._ai_client.__aexit__(None, None, None)
            if self._match_repo:
                await self._match_repo.close()
            if self._live_repo:
                await self._live_repo.close()
                
        except Exception as e:
            logger.error(f"Error during service cleanup: {e}")
        
        self._services_initialized = False
        logger.info("Live reporting services cleaned up")
    
    async def monitor_match(
        self,
        match_id: str,
        thread_id: Optional[str] = None,
        competition: str = "usa.1"
    ) -> MonitoringResult:
        """
        Monitor a match for live updates.
        
        Args:
            match_id: ESPN match ID
            thread_id: Discord thread ID
            competition: Competition identifier
            
        Returns:
            MonitoringResult
        """
        if not self._services_initialized:
            await self._initialize_services()
        
        return await self._monitor_service.monitor_match(match_id, thread_id, competition)
    
    async def get_health_status(self) -> Dict[str, Any]:
        """Get system health status."""
        if not self._services_initialized:
            await self._initialize_services()
        
        return await self._monitor_service.get_health_status()
    
    async def get_active_sessions(self) -> List[LiveReportingSession]:
        """Get all active live reporting sessions."""
        if not self._services_initialized:
            await self._initialize_services()
        
        return await self._live_repo.get_active_sessions()