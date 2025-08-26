# app/services/live_reporting/espn_client.py

"""
ESPN API Client

Industry standard async HTTP client with:
- Circuit breaker pattern
- Retry logic with exponential backoff
- Proper connection pooling
- Structured logging and metrics
- Type safety
"""

import logging
import json
import asyncio
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from dataclasses import dataclass
import aiohttp
import aioredis
from aiohttp import ClientTimeout, ClientSession
from tenacity import (
    retry, stop_after_attempt, wait_exponential,
    retry_if_exception_type, before_sleep_log
)

from .config import LiveReportingConfig, MatchEventContext
from .circuit_breaker import CircuitBreaker, CircuitBreakerError
from .metrics import MetricsCollector

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MatchData:
    """Structured match data from ESPN API."""
    match_id: str
    status: str
    home_team: Dict[str, Any]
    away_team: Dict[str, Any]
    score: str
    events: List[Dict[str, Any]]
    competition: str
    venue: Optional[str] = None
    date: Optional[str] = None
    raw_data: Optional[Dict[str, Any]] = None


class ESPNAPIError(Exception):
    """Custom exception for ESPN API errors."""
    pass


class ESPNClient:
    """
    Async ESPN API client with industry standard patterns.
    
    Features:
    - Connection pooling
    - Circuit breaker for fault tolerance
    - Exponential backoff retry logic
    - Response caching with Redis
    - Structured logging and metrics
    - Type-safe responses
    """
    
    def __init__(self, config: LiveReportingConfig, metrics: Optional[MetricsCollector] = None):
        self.config = config
        self.metrics = metrics
        self.base_url = config.espn_api_base
        self._session: Optional[ClientSession] = None
        self._redis: Optional[aioredis.Redis] = None
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=60,
            expected_exception=ESPNAPIError
        )
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self._setup_session()
        if self.config.enable_caching:
            await self._setup_redis()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
    
    async def _setup_session(self):
        """Setup HTTP session with connection pooling."""
        timeout = ClientTimeout(
            total=self.config.espn_timeout,
            connect=10,
            sock_read=self.config.espn_timeout
        )
        
        connector = aiohttp.TCPConnector(
            limit=100,  # Total connection pool size
            limit_per_host=30,  # Per-host connection limit
            ttl_dns_cache=300,  # DNS cache TTL
            use_dns_cache=True,
            keepalive_timeout=30,
            enable_cleanup_closed=True
        )
        
        self._session = ClientSession(
            connector=connector,
            timeout=timeout,
            headers={
                'User-Agent': 'ECS-Discord-Bot/1.0',
                'Accept': 'application/json',
                'Accept-Encoding': 'gzip, deflate'
            }
        )
    
    async def _setup_redis(self):
        """Setup Redis for caching (compatible with aioredis 1.3.x)."""
        try:
            # Parse Redis URL for aioredis 1.3.x compatibility
            import urllib.parse
            parsed = urllib.parse.urlparse(self.config.redis_url)
            host = parsed.hostname or 'localhost'
            port = parsed.port or 6379
            db = int(parsed.path.lstrip('/')) if parsed.path and parsed.path != '/' else 0
            
            self._redis = await aioredis.create_redis_pool(
                f"redis://{host}:{port}",
                db=db,
                encoding='utf-8'
            )
            # Test connection
            await self._redis.ping()
        except Exception as e:
            logger.warning(f"Redis setup failed, caching disabled: {e}")
            self._redis = None
    
    async def close(self):
        """Clean up resources."""
        if self._session:
            await self._session.close()
        if self._redis:
            # aioredis 1.3.x uses wait_closed() after close()
            self._redis.close()
            await self._redis.wait_closed()
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError)),
        before_sleep=before_sleep_log(logger, logging.WARNING)
    )
    async def _make_request(self, endpoint: str) -> Dict[str, Any]:
        """
        Make HTTP request with retry logic.
        
        Args:
            endpoint: API endpoint path
            
        Returns:
            JSON response data
            
        Raises:
            ESPNAPIError: On API errors
        """
        if not self._session:
            await self._setup_session()
        
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        try:
            # Record metrics with proper labels
            if self.metrics:
                self.metrics.espn_requests_total.labels(endpoint=endpoint).inc()
            
            start_time = asyncio.get_event_loop().time()
            
            async with self._session.get(url) as response:
                # Record response metrics
                if self.metrics:
                    self.metrics.espn_response_status.labels(
                        status=str(response.status)
                    ).inc()
                
                if response.status == 429:  # Rate limited
                    retry_after = int(response.headers.get('Retry-After', 60))
                    logger.warning(f"ESPN API rate limited, waiting {retry_after}s")
                    await asyncio.sleep(retry_after)
                    raise ESPNAPIError("Rate limited")
                
                response.raise_for_status()
                data = await response.json()
                
                # Record timing with proper labels
                if self.metrics:
                    duration = asyncio.get_event_loop().time() - start_time
                    self.metrics.espn_request_duration.labels(endpoint=endpoint).observe(duration)
                
                return data
                
        except aiohttp.ClientError as e:
            logger.error(f"ESPN API request failed: {e}")
            if self.metrics:
                self.metrics.espn_requests_failed.labels(
                    endpoint=endpoint, 
                    error_type='client_error'
                ).inc()
            raise ESPNAPIError(f"HTTP request failed: {e}") from e
        except asyncio.TimeoutError as e:
            logger.error(f"ESPN API timeout: {e}")
            if self.metrics:
                self.metrics.espn_requests_timeout.labels(endpoint=endpoint).inc()
            raise ESPNAPIError(f"Request timeout: {e}") from e
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON response from ESPN: {e}")
            if self.metrics:
                self.metrics.espn_requests_failed.labels(
                    endpoint=endpoint, 
                    error_type='json_decode_error'
                ).inc()
            raise ESPNAPIError(f"Invalid JSON response: {e}") from e
    
    async def _get_cached_data(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """Get data from Redis cache."""
        if not self._redis or not self.config.enable_caching:
            return None
        
        try:
            data = await self._redis.get(cache_key)
            if data:
                if self.metrics:
                    self.metrics.cache_hits.labels(type='espn').inc()
                return json.loads(data)
        except Exception as e:
            logger.warning(f"Cache read error: {e}")
        
        if self.metrics:
            self.metrics.cache_misses.labels(type='espn').inc()
        return None
    
    async def _cache_data(self, cache_key: str, data: Dict[str, Any], ttl: int = None):
        """Cache data in Redis."""
        if not self._redis or not self.config.enable_caching:
            return
        
        try:
            ttl = ttl or self.config.espn_cache_ttl
            await self._redis.setex(
                cache_key,
                ttl,
                json.dumps(data, default=str)
            )
        except Exception as e:
            logger.warning(f"Cache write error: {e}")
    
    async def get_match_data(self, match_id: str, competition: str) -> Optional[MatchData]:
        """
        Get match data from ESPN API.
        
        Args:
            match_id: ESPN match ID
            competition: Competition ID (e.g., 'usa.1')
            
        Returns:
            MatchData object or None if not found
        """
        endpoint = f"sports/soccer/{competition}/scoreboard/{match_id}"
        cache_key = f"espn:match:{match_id}:{competition}"
        
        try:
            # Check circuit breaker
            if not self._circuit_breaker.can_execute():
                logger.warning("ESPN API circuit breaker is open")
                if self.metrics:
                    self.metrics.circuit_breaker_state.labels(
                        service='espn', state='open'
                    ).inc()
                raise CircuitBreakerError("ESPN API circuit breaker is open")
            
            # Try cache first
            cached_data = await self._get_cached_data(cache_key)
            if cached_data:
                logger.debug(f"Cache hit for match {match_id}")
                return self._parse_match_data(match_id, competition, cached_data)
            
            # Make API request
            logger.info(f"Fetching match data for {match_id} from ESPN API")
            raw_data = await self._make_request(endpoint)
            
            # Cache the response
            await self._cache_data(cache_key, raw_data)
            
            # Parse and return
            match_data = self._parse_match_data(match_id, competition, raw_data)
            
            # Record success in circuit breaker
            await self._circuit_breaker.record_success()
            
            return match_data
            
        except (ESPNAPIError, CircuitBreakerError) as e:
            # Record failure in circuit breaker
            await self._circuit_breaker.record_failure()
            logger.error(f"Failed to get match data for {match_id}: {e}")
            return None
        except Exception as e:
            await self._circuit_breaker.record_failure()
            logger.error(f"Unexpected error getting match data for {match_id}: {e}")
            return None
    
    def _parse_match_data(self, match_id: str, competition: str, raw_data: Dict[str, Any]) -> Optional[MatchData]:
        """
        Parse ESPN API response into structured MatchData.
        
        Args:
            match_id: ESPN match ID
            competition: Competition ID
            raw_data: Raw ESPN API response
            
        Returns:
            MatchData object or None if parsing fails
        """
        try:
            if not raw_data or 'competitions' not in raw_data:
                logger.warning(f"Invalid ESPN data structure for match {match_id}")
                return None
            
            competition_data = raw_data['competitions'][0]
            status = competition_data.get('status', {})
            competitors = competition_data.get('competitors', [])
            
            if len(competitors) < 2:
                logger.warning(f"Insufficient competitor data for match {match_id}")
                return None
            
            home_competitor = competitors[0]
            away_competitor = competitors[1]
            
            # Extract team data
            home_team = {
                'id': home_competitor.get('id', ''),
                'name': home_competitor.get('team', {}).get('displayName', 'Unknown'),
                'short_name': home_competitor.get('team', {}).get('abbreviation', 'UNK'),
                'score': home_competitor.get('score', '0'),
                'logo': home_competitor.get('team', {}).get('logo', ''),
                'is_home': home_competitor.get('homeAway', '') == 'home'
            }
            
            away_team = {
                'id': away_competitor.get('id', ''),
                'name': away_competitor.get('team', {}).get('displayName', 'Unknown'),
                'short_name': away_competitor.get('team', {}).get('abbreviation', 'UNK'),
                'score': away_competitor.get('score', '0'),
                'logo': away_competitor.get('team', {}).get('logo', ''),
                'is_home': away_competitor.get('homeAway', '') == 'home'
            }
            
            # Create score string
            score = f"{home_team['score']}-{away_team['score']}"
            
            # Extract events with enhanced substitution and player info
            events = []
            for event_idx, event in enumerate(competition_data.get('details', [])):
                event_type = event.get('type', {}).get('text', '')
                event_text = event.get('text', '')
                athletes_involved = event.get('athletesInvolved', [])
                clock_value = event.get('clock', {}).get('displayValue', '')
                team_id = event.get('team', {}).get('id', '')
                
                # Generate unique event ID using multiple data points
                # Format: matchId_teamId_eventType_clockValue_athleteId
                primary_athlete_id = athletes_involved[0].get('id', '') if athletes_involved else ''
                unique_id = f"{match_id}_{team_id}_{event_type.replace(' ', '')}_{clock_value}_{primary_athlete_id}_{event_idx}"
                
                # Basic event info
                event_data = {
                    'id': unique_id,
                    'type': event_type,
                    'text': event_text,
                    'clock': clock_value,
                    'team_id': team_id,
                }
                
                # Enhanced player information
                if athletes_involved:
                    # Primary player (first in list)
                    primary_athlete = athletes_involved[0]
                    event_data.update({
                        'athlete_id': primary_athlete.get('id', ''),
                        'athlete_name': primary_athlete.get('displayName', ''),
                        'athlete_short_name': primary_athlete.get('shortName', ''),
                        'athlete_photo': primary_athlete.get('headshot', {}).get('href', '') if isinstance(primary_athlete.get('headshot'), dict) else '',
                        'athlete_position': primary_athlete.get('position', {}).get('abbreviation', '') if isinstance(primary_athlete.get('position'), dict) else '',
                        'athlete_jersey': primary_athlete.get('jersey', ''),
                    })
                    
                    # Handle substitutions specifically (usually have 2 players)
                    if event_type.lower() in ['substitution', 'sub', 'substitution-in', 'substitution-out'] or 'substitution' in event_text.lower():
                        event_data['is_substitution'] = True
                        event_data['is_card'] = False
                        if len(athletes_involved) >= 2:
                            # Player coming in
                            player_in = athletes_involved[0] if 'in' in event_text.lower() else athletes_involved[1]
                            # Player going out  
                            player_out = athletes_involved[1] if 'in' in event_text.lower() else athletes_involved[0]
                            
                            event_data.update({
                                'sub_player_in_id': player_in.get('id', ''),
                                'sub_player_in_name': player_in.get('displayName', ''),
                                'sub_player_in_photo': player_in.get('headshot', {}).get('href', '') if isinstance(player_in.get('headshot'), dict) else '',
                                'sub_player_in_jersey': player_in.get('jersey', ''),
                                'sub_player_out_id': player_out.get('id', ''),
                                'sub_player_out_name': player_out.get('displayName', ''),
                                'sub_player_out_photo': player_out.get('headshot', {}).get('href', '') if isinstance(player_out.get('headshot'), dict) else '',
                                'sub_player_out_jersey': player_out.get('jersey', ''),
                            })
                    # Handle cards specifically
                    elif event_type.lower() in ['yellow card', 'red card', 'booking', 'card'] or any(card in event_text.lower() for card in ['yellow', 'red', 'card', 'booking']):
                        event_data['is_substitution'] = False
                        event_data['is_card'] = True
                        
                        # Determine card type
                        if 'red' in event_type.lower() or 'red' in event_text.lower():
                            event_data['card_type'] = 'red'
                            event_data['card_emoji'] = '🟥'
                        elif 'yellow' in event_type.lower() or 'yellow' in event_text.lower():
                            event_data['card_type'] = 'yellow'  
                            event_data['card_emoji'] = '🟨'
                        else:
                            event_data['card_type'] = 'unknown'
                            event_data['card_emoji'] = '📋'
                            
                        # Check for second yellow = red
                        if 'second yellow' in event_text.lower() or '2nd yellow' in event_text.lower():
                            event_data['card_type'] = 'second_yellow_red'
                            event_data['card_emoji'] = '🟨🟥'
                    # Handle goals
                    elif event_type.lower() in ['goal', 'own goal', 'penalty goal'] or 'goal' in event_text.lower():
                        event_data['is_substitution'] = False
                        event_data['is_card'] = False
                        event_data['is_goal'] = True
                        
                        # Get scorer info
                        scorer_name = event_data.get('athlete_name', 'Unknown')
                        scorer_jersey = event_data.get('athlete_jersey', '')
                        jersey_text = f" #{scorer_jersey}" if scorer_jersey else ""
                        
                        if 'penalty' in event_text.lower() or 'penalty' in event_type.lower():
                            event_data['goal_type'] = 'penalty'
                            event_data['goal_emoji'] = '⚽🥅'
                            event_data['text'] = f"GOAL! {scorer_name}{jersey_text} scores from the penalty spot! {clock_value}"
                        elif 'own goal' in event_text.lower() or 'own goal' in event_type.lower():
                            event_data['goal_type'] = 'own_goal' 
                            event_data['goal_emoji'] = '🤦'
                            event_data['text'] = f"Own Goal by {scorer_name}{jersey_text} {clock_value}"
                        else:
                            event_data['goal_type'] = 'regular'
                            event_data['goal_emoji'] = '⚽'
                            event_data['text'] = f"GOAL! {scorer_name}{jersey_text} finds the net! {clock_value}"
                    else:
                        event_data['is_substitution'] = False
                        event_data['is_card'] = False
                        event_data['is_goal'] = False
                else:
                    # No athletes involved
                    event_data.update({
                        'athlete_id': '',
                        'athlete_name': '',
                        'athlete_short_name': '',
                        'athlete_photo': '',
                        'athlete_position': '',
                        'athlete_jersey': '',
                        'is_substitution': False,
                        'is_card': False,
                        'is_goal': False
                    })
                
                events.append(event_data)
            
            return MatchData(
                match_id=match_id,
                status=status.get('type', {}).get('name', 'UNKNOWN'),
                home_team=home_team,
                away_team=away_team,
                score=score,
                events=events,
                competition=competition,
                venue=competition_data.get('venue', {}).get('fullName', 'Unknown Venue'),
                date=raw_data.get('date'),
                raw_data=raw_data
            )
            
        except (KeyError, IndexError, TypeError) as e:
            logger.error(f"Error parsing ESPN data for match {match_id}: {e}")
            return None
    
    async def health_check(self) -> bool:
        """
        Check ESPN API health.
        
        Returns:
            bool: True if API is healthy
        """
        try:
            # Make a simple request to check connectivity - bypass metrics for health check
            url = f"{self.config.espn_api_base}/sports/soccer/usa.1/scoreboard"
            async with self._session.get(url) as response:
                if response.status == 200:
                    return True
                return False
        except Exception as e:
            logger.warning(f"ESPN API health check failed: {e}")
            return False