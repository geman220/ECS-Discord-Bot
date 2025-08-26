# app/services/live_reporting/ai_client.py

"""
AI Commentary Client

Industry standard async OpenAI client for generating match commentary.
"""

import logging
import asyncio
import json
from typing import Optional, List, Dict, Any
from datetime import datetime
import aiohttp
from aiohttp import ClientTimeout, ClientSession
from tenacity import (
    retry, stop_after_attempt, wait_exponential,
    retry_if_exception_type, before_sleep_log
)

from .config import LiveReportingConfig, MatchEventContext
from .circuit_breaker import CircuitBreaker, CircuitBreakerError
from .metrics import MetricsCollector
from .espn_client import MatchData

logger = logging.getLogger(__name__)


class AICommentaryError(Exception):
    """Custom exception for AI commentary errors."""
    pass


class AICommentaryClient:
    """
    Async OpenAI client for generating match commentary.
    
    Features:
    - Circuit breaker for fault tolerance
    - Exponential backoff retry logic
    - Context-aware commentary generation
    - Fallback to template-based commentary
    - Rate limiting and cost tracking
    """
    
    def __init__(self, config: LiveReportingConfig, metrics: Optional[MetricsCollector] = None):
        self.config = config
        self.metrics = metrics
        self.base_url = "https://api.openai.com/v1"
        self._session: Optional[ClientSession] = None
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=3,
            recovery_timeout=60,
            expected_exception=AICommentaryError
        )
        
        # Match context storage for continuity
        self._match_contexts: Dict[str, List[Dict]] = {}
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self._setup_session()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
    
    async def _setup_session(self):
        """Setup HTTP session with authentication."""
        if not self.config.openai_api_key:
            logger.warning("OpenAI API key not configured, AI commentary disabled")
            return
        
        timeout = ClientTimeout(
            total=self.config.openai_timeout,
            connect=10,
            sock_read=self.config.openai_timeout
        )
        
        connector = aiohttp.TCPConnector(
            limit=50,
            limit_per_host=10,
            ttl_dns_cache=300,
            use_dns_cache=True,
            keepalive_timeout=30,
            enable_cleanup_closed=True
        )
        
        self._session = ClientSession(
            connector=connector,
            timeout=timeout,
            headers={
                'Authorization': f'Bearer {self.config.openai_api_key}',
                'Content-Type': 'application/json',
                'User-Agent': 'ECS-Discord-Bot/1.0'
            }
        )
    
    async def _get_dynamic_prompt_config(
        self,
        prompt_type: str,
        competition: str = None,
        team: str = None
    ) -> Optional[Dict]:
        """
        Fetch dynamic prompt configuration from database.
        
        Args:
            prompt_type: Type of prompt (match_commentary, goal, card, etc.)
            competition: Competition identifier
            team: Team name for team-specific prompts
            
        Returns:
            Prompt configuration dict or None if using defaults
        """
        try:
            # Import here to avoid circular dependency
            import aiohttp
            
            # Build API URL
            base_url = "http://localhost:5000/ai-prompts/active"
            params = {'competition': competition} if competition else {}
            if team:
                params['team'] = team
            
            # Fetch active prompt configuration
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{base_url}/{prompt_type}", params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data['success'] and data['prompt']:
                            logger.info(f"Using dynamic prompt config: {data['prompt']['name']} v{data['prompt']['version']}")
                            return data['prompt']
                    
            logger.debug(f"No dynamic prompt found for {prompt_type}, using defaults")
            return None
            
        except Exception as e:
            logger.error(f"Error fetching dynamic prompt config: {e}")
            return None
    
    async def close(self):
        """Clean up resources."""
        if self._session:
            await self._session.close()
    
    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError)),
        before_sleep=before_sleep_log(logger, logging.WARNING)
    )
    async def _make_request(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Make request to OpenAI API.
        
        Args:
            data: Request payload
            
        Returns:
            API response or None
        """
        if not self._session or not self.config.openai_api_key:
            logger.warning("OpenAI not configured, skipping request")
            return None
        
        try:
            # Record metrics
            if self.metrics:
                self.metrics.ai_requests_total.inc()
            
            start_time = asyncio.get_event_loop().time()
            
            async with self._session.post(f"{self.base_url}/chat/completions", json=data) as response:
                # Record timing
                if self.metrics:
                    duration = asyncio.get_event_loop().time() - start_time
                    self.metrics.ai_request_duration.observe(duration)
                
                if response.status == 429:  # Rate limited
                    retry_after = int(response.headers.get('Retry-After', 60))
                    logger.warning(f"OpenAI API rate limited, waiting {retry_after}s")
                    await asyncio.sleep(retry_after)
                    raise AICommentaryError("Rate limited")
                
                if response.status >= 400:
                    error_text = await response.text()
                    logger.error(f"OpenAI API error {response.status}: {error_text}")
                    if self.metrics:
                        self.metrics.ai_requests_failed.labels(
                            error_type=str(response.status)
                        ).inc()
                    raise AICommentaryError(f"HTTP {response.status}: {error_text}")
                
                return await response.json()
                
        except aiohttp.ClientError as e:
            logger.error(f"OpenAI API request failed: {e}")
            if self.metrics:
                self.metrics.ai_requests_failed.labels(error_type='client_error').inc()
            raise AICommentaryError(f"HTTP request failed: {e}") from e
        except asyncio.TimeoutError as e:
            logger.error(f"OpenAI API timeout: {e}")
            if self.metrics:
                self.metrics.ai_requests_failed.labels(error_type='timeout').inc()
            raise AICommentaryError(f"Request timeout: {e}") from e
    
    def _build_system_prompt(self) -> str:
        """Build the system prompt for AI commentary."""
        return """You are a passionate Seattle Sounders FC supporter providing live match commentary for the ECS (Emerald City Supporters). Your commentary should be:

PERSONALITY:
- Enthusiastic and passionate about the Sounders
- Use authentic soccer fan language - swearing is perfectly fine and encouraged
- Show clear bias toward Seattle Sounders
- Be critical of current opponents, but save extra hostility for actual rivalry matches
- Use casual, conversational tone like you're talking to fellow supporters

CONTENT GUIDELINES:
- Keep responses under 200 characters for Discord
- Focus on the specific event that just happened
- Reference previous events in the match when relevant
- Never use hashtags, em dashes, or overly corporate language
- Avoid phrases like "Let's go" or generic cheering
- Be specific about what happened, not just emotional reactions

RIVAL AWARENESS:
- Only reference Portland/Vancouver when we're actually playing them
- When facing Portland Timbers: Be extra hostile and critical (biggest rival)
- When facing Vancouver Whitecaps: Show strong dislike (Cascadia rival)
- Against other teams: Occasional light trash talk, focus on supporting Sounders
- Always favor Sounders players and decisions

MATCH CONTEXT:
- React to goals, cards, substitutions, and key plays
- Build on previous events in the match
- Show frustration with bad calls or poor play
- Celebrate Sounders successes with genuine excitement

Remember: You're a real fan in the stands, not a neutral commentator."""
    
    def _build_match_context(self, match_data: MatchData, recent_events: List[Dict]) -> str:
        """Build match context for the AI."""
        # Detect rivalry matches
        home_team = match_data.home_team['name'].lower()
        away_team = match_data.away_team['name'].lower()
        
        rival_status = ""
        if 'portland' in home_team or 'portland' in away_team or 'timbers' in home_team or 'timbers' in away_team:
            rival_status = "⚠️ CASCADIA RIVALRY MATCH vs PORTLAND TIMBERS - Maximum hostility authorized!"
        elif 'vancouver' in home_team or 'vancouver' in away_team or 'whitecaps' in home_team or 'whitecaps' in away_team:
            rival_status = "⚠️ CASCADIA RIVALRY MATCH vs VANCOUVER WHITECAPS - Strong dislike authorized!"
        else:
            rival_status = "Regular match - Keep rivalry comments minimal and rare"
            
        context_parts = [
            f"MATCH: {match_data.home_team['name']} vs {match_data.away_team['name']}",
            f"SCORE: {match_data.score}",
            f"STATUS: {match_data.status}",
            f"VENUE: {match_data.venue or 'Unknown'}",
            f"RIVALRY STATUS: {rival_status}"
        ]
        
        if recent_events:
            context_parts.append("RECENT EVENTS:")
            for event in recent_events[-5:]:  # Last 5 events for context
                context_parts.append(f"- {event.get('text', 'Unknown event')}")
        
        return "\n".join(context_parts)
    
    def _get_match_context(self, match_id: str) -> List[Dict]:
        """Get stored context for a match."""
        return self._match_contexts.get(match_id, [])
    
    def _update_match_context(self, match_id: str, event: Dict):
        """Update stored context for a match."""
        if match_id not in self._match_contexts:
            self._match_contexts[match_id] = []
        
        self._match_contexts[match_id].append({
            'timestamp': datetime.utcnow().isoformat(),
            'event': event
        })
        
        # Keep only last 20 events to manage memory
        if len(self._match_contexts[match_id]) > 20:
            self._match_contexts[match_id] = self._match_contexts[match_id][-20:]
    
    async def _get_prompt_config(self, prompt_type: str, competition: str) -> Optional[Dict]:
        """
        Fetch AI prompt configuration from the API.
        
        Args:
            prompt_type: Type of prompt (goal, opponent_goal, card, etc.)
            competition: Competition identifier (e.g., 'usa.1')
            
        Returns:
            Prompt configuration dict or None if not found
        """
        try:
            api_url = f"http://host.docker.internal:5000/ai-prompts/active/{prompt_type}"
            params = {'competition': competition} if competition else {}
            
            timeout = ClientTimeout(total=5)  # Short timeout for quick response
            async with ClientSession(timeout=timeout) as session:
                async with session.get(api_url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get('success') and data.get('prompt'):
                            logger.info(f"Retrieved AI prompt config for {prompt_type}")
                            return data['prompt']
                        else:
                            logger.info(f"No active prompt config found for {prompt_type}")
                            return None
                    else:
                        logger.warning(f"Failed to fetch prompt config: HTTP {response.status}")
                        return None
                        
        except Exception as e:
            logger.error(f"Error fetching prompt config for {prompt_type}: {e}")
            return None
    
    async def generate_commentary(
        self,
        match_data: MatchData,
        single_event: Dict,
        context: Optional[MatchEventContext] = None
    ) -> str:
        """
        Generate AI commentary for a single match event.
        
        Args:
            match_data: Current match data
            single_event: Single event to comment on
            context: Optional match context
            
        Returns:
            Generated commentary string
        """
        if not self.config.enable_ai_commentary:
            logger.info("AI commentary disabled, using fallback")
            if self.metrics:
                self.metrics.ai_fallback_used.labels(reason='disabled').inc()
            return self._generate_fallback_commentary(match_data, [single_event])
        
        try:
            # Check circuit breaker
            if not self._circuit_breaker.can_execute():
                logger.warning("AI commentary circuit breaker is open")
                if self.metrics:
                    self.metrics.ai_fallback_used.labels(reason='circuit_breaker').inc()
                return self._generate_fallback_commentary(match_data, [single_event])
            
            # Get match context for continuity (AI memory)
            match_context = self._get_match_context(match_data.match_id)
            recent_events = [ctx['event'] for ctx in match_context[-5:]]  # Last 5 events for AI context
            
            # Determine event type and team for prompt selection
            event_type = single_event.get('type', 'Unknown').lower()
            team_id = single_event.get('team_id', '')
            # ALWAYS check for Seattle Sounders, regardless of home/away status
            sounders_team_id = '9726'  # Seattle Sounders FC
            is_sounders_event = (team_id == sounders_team_id)
            
            # Determine prompt type based on event and team
            if 'goal' in event_type or ('penalty' in event_type and 'scored' in event_type):
                prompt_type = 'goal' if is_sounders_event else 'opponent_goal'
            elif 'penalty' in event_type and ('missed' in event_type or 'saved' in event_type):
                # Penalty miss/save: celebrate if opponent misses, frustrated if we miss
                prompt_type = 'opponent_penalty_miss' if not is_sounders_event else 'sounders_penalty_miss'
            elif 'red card' in event_type or event_type == 'red card':
                # Red cards get dramatic responses
                prompt_type = 'sounders_red_card' if is_sounders_event else 'opponent_red_card'
            elif 'card' in event_type or 'yellow card' in event_type:
                # Yellow cards and generic cards
                prompt_type = 'yellow_card' if is_sounders_event else 'opponent_yellow_card'
            elif 'substitution' in event_type:
                prompt_type = 'substitution' if is_sounders_event else 'opponent_substitution'
            else:
                prompt_type = 'match_commentary'
            
            # Fetch AI prompt configuration from API
            prompt_config = await self._get_prompt_config(prompt_type, match_data.competition)
            
            if not prompt_config:
                logger.warning(f"No AI prompt config found for {prompt_type}, using fallback")
                if self.metrics:
                    self.metrics.ai_fallback_used.labels(reason='no_prompt_config').inc()
                return self._generate_fallback_commentary(match_data, [single_event])
            
            # Build match context string for AI
            match_context_str = self._build_match_context(match_data, recent_events)
            
            # Use the configured template or build basic prompt
            user_prompt_template = prompt_config.get('user_prompt_template')
            system_prompt = prompt_config.get('system_prompt', self._build_system_prompt())
            
            if user_prompt_template:
                # Use template with variable substitution
                event_desc = single_event.get('text', 'Unknown event')
                user_prompt = user_prompt_template.format(
                    match_context=match_context_str,
                    event_description=event_desc,
                    score=match_data.score,
                    clock=single_event.get('clock', 'Unknown time'),
                    event_type=single_event.get('type', 'Unknown'),
                    athlete_name=single_event.get('athlete_name', 'Unknown player')
                )
            else:
                # Fallback prompt construction
                event_desc = single_event.get('text', 'Unknown event')
                user_prompt = f"""MATCH CONTEXT:
{match_context_str}

EVENT TO COMMENT ON:
{single_event.get('clock', 'Unknown time')}: {event_desc}

Provide commentary on this event. Current score: {match_data.score}"""
            
            # Make API request with prompt configuration
            request_data = {
                "model": self.config.openai_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "max_tokens": prompt_config.get('max_tokens', 100),
                "temperature": prompt_config.get('temperature', 0.8),
                "presence_penalty": 0.1,
                "frequency_penalty": 0.1
            }
            
            response = await self._make_request(request_data)
            
            if response and 'choices' in response and response['choices']:
                commentary = response['choices'][0]['message']['content'].strip()
                
                # Update match context with the single event
                self._update_match_context(match_data.match_id, single_event)
                
                # Record success
                await self._circuit_breaker.record_success()
                
                logger.info(f"Generated AI commentary for match {match_data.match_id}: {commentary}")
                return commentary
            else:
                logger.warning("No valid response from OpenAI API")
                if self.metrics:
                    self.metrics.ai_fallback_used.labels(reason='no_response').inc()
                return self._generate_fallback_commentary(match_data, [single_event])
            
        except (AICommentaryError, CircuitBreakerError) as e:
            await self._circuit_breaker.record_failure()
            logger.error(f"AI commentary generation failed: {e}")
            if self.metrics:
                self.metrics.ai_fallback_used.labels(reason='api_error').inc()
            return self._generate_fallback_commentary(match_data, [single_event])
        except Exception as e:
            await self._circuit_breaker.record_failure()
            logger.error(f"Unexpected error in AI commentary: {e}")
            if self.metrics:
                self.metrics.ai_fallback_used.labels(reason='unexpected_error').inc()
            return self._generate_fallback_commentary(match_data, [single_event])
    
    def _generate_fallback_commentary(self, match_data: MatchData, new_events: List[Dict]) -> str:
        """Generate fallback commentary when AI is unavailable."""
        if not new_events:
            return f"Live updates for {match_data.home_team['short_name']} vs {match_data.away_team['short_name']} ({match_data.score})"
        
        # Simple template-based commentary
        event = new_events[0]  # Focus on first new event
        event_type = event.get('type', '').lower()
        clock = event.get('clock', '')
        athlete_name = event.get('athlete_name', 'Player')
        
        templates = {
            'goal': [
                f"GOAL! {athlete_name} finds the net! {clock}",
                f"{athlete_name} scores! What a strike! {clock}",
                f"It's in the back of the net! {athlete_name} with the goal {clock}"
            ],
            'penalty': [
                f"PENALTY GOAL! {athlete_name} converts from the spot! {clock}",
                f"{athlete_name} scores from the penalty spot! {clock}",
                f"PENALTY! {athlete_name} makes no mistake from 12 yards {clock}"
            ],
            'penalty - scored': [
                f"PENALTY GOAL! {athlete_name} converts from the spot! {clock}",
                f"{athlete_name} scores from the penalty spot! {clock}",
                f"PENALTY! {athlete_name} makes no mistake from 12 yards {clock}"
            ],
            'penalty - missed': [
                f"PENALTY MISS! {athlete_name} sends it wide! {clock}",
                f"{athlete_name} misses from the spot! {clock}",
                f"PENALTY SAVED! Great keeping to deny {athlete_name} {clock}"
            ],
            'penalty - saved': [
                f"PENALTY SAVED! Keeper denies {athlete_name}! {clock}",
                f"BRILLIANT SAVE! {athlete_name} denied from the spot {clock}",
                f"PENALTY MISS! {athlete_name} can't convert {clock}"
            ],
            'yellow card': [
                f"Yellow card for {athlete_name} at {clock}",
                f"{athlete_name} picks up a booking {clock}",
                f"Caution shown to {athlete_name} {clock}"
            ],
            'red card': [
                f"RED CARD! {athlete_name} is off! {clock}",
                f"{athlete_name} sees red at {clock}",
                f"Sending off! {athlete_name} gets the red card {clock}"
            ],
            'substitution': [
                f"Substitution: {athlete_name} comes on {clock}",
                f"Change made: {athlete_name} enters the game {clock}",
                f"Fresh legs: {athlete_name} is on {clock}"
            ]
        }
        
        # Find matching template
        template_key = None
        for key in templates.keys():
            if key in event_type:
                template_key = key
                break
        
        if template_key:
            import random
            return random.choice(templates[template_key])
        else:
            return f"Match update: {event.get('text', 'Event')} at {clock}"
    
    async def health_check(self) -> bool:
        """Check AI service health."""
        if not self.config.openai_api_key:
            return False
        
        try:
            # Make a simple request to check connectivity
            data = {
                "model": self.config.openai_model,
                "messages": [{"role": "user", "content": "Test"}],
                "max_tokens": 5
            }
            response = await self._make_request(data)
            return response is not None
        except Exception as e:
            logger.error(f"AI service health check failed: {e}")
            return False