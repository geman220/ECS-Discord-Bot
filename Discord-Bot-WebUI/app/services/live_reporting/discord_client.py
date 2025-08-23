# app/services/live_reporting/discord_client.py

"""
Discord API Client

Industry standard async Discord client with:
- Rate limit handling
- Retry logic with exponential backoff
- Proper connection management
- Structured logging and metrics
- Type safety
"""

import logging
import asyncio
import json
from typing import Optional, Dict, Any, List
from datetime import datetime
from dataclasses import dataclass
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


@dataclass(frozen=True)
class DiscordEmbed:
    """Discord embed structure."""
    title: str
    description: str
    color: int = 0x00ff00  # Green by default
    thumbnail: Optional[str] = None
    image: Optional[str] = None
    fields: Optional[List[Dict[str, Any]]] = None
    footer: Optional[Dict[str, str]] = None
    timestamp: Optional[str] = None


class DiscordAPIError(Exception):
    """Custom exception for Discord API errors."""
    pass


class RateLimitError(DiscordAPIError):
    """Rate limit specific error."""
    def __init__(self, retry_after: float, *args):
        super().__init__(*args)
        self.retry_after = retry_after


class DiscordClient:
    """
    Async Discord API client with industry standard patterns.
    
    Features:
    - Automatic rate limit handling
    - Circuit breaker for fault tolerance
    - Exponential backoff retry logic
    - Connection pooling
    - Structured logging and metrics
    - Type-safe message building
    """
    
    def __init__(self, config: LiveReportingConfig, metrics: Optional[MetricsCollector] = None):
        self.config = config
        self.metrics = metrics
        self.base_url = "https://discord.com/api/v10"
        self._session: Optional[ClientSession] = None
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=3,
            recovery_timeout=30,
            expected_exception=DiscordAPIError
        )
        
        # Rate limiting state
        self._rate_limits: Dict[str, Dict] = {}
        self._global_rate_limit_reset = 0
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self._setup_session()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
    
    async def _setup_session(self):
        """Setup HTTP session with authentication."""
        if not self.config.discord_token:
            logger.warning("Discord token not configured, Discord posting disabled")
            return
        
        timeout = ClientTimeout(
            total=self.config.discord_timeout,
            connect=10,
            sock_read=self.config.discord_timeout
        )
        
        connector = aiohttp.TCPConnector(
            limit=100,
            limit_per_host=10,  # Discord rate limits per endpoint
            ttl_dns_cache=300,
            use_dns_cache=True,
            keepalive_timeout=30,
            enable_cleanup_closed=True
        )
        
        self._session = ClientSession(
            connector=connector,
            timeout=timeout,
            headers={
                'Authorization': f'Bot {self.config.discord_token}',
                'User-Agent': 'ECS-Discord-Bot/1.0',
                'Content-Type': 'application/json'
            }
        )
    
    async def close(self):
        """Clean up resources."""
        if self._session:
            await self._session.close()
    
    def _get_rate_limit_key(self, method: str, endpoint: str) -> str:
        """Generate rate limit key for endpoint."""
        # Simplified rate limit bucketing - in production you'd want more sophisticated logic
        return f"{method}:{endpoint}"
    
    async def _handle_rate_limit(self, rate_limit_key: str, retry_after: float):
        """Handle rate limiting."""
        self._rate_limits[rate_limit_key] = {
            'reset_time': asyncio.get_event_loop().time() + retry_after
        }
        
        if self.metrics:
            self.metrics.discord_rate_limit_hits.inc()
        
        logger.warning(f"Discord rate limited for {rate_limit_key}, waiting {retry_after}s")
        await asyncio.sleep(retry_after)
    
    async def _check_rate_limit(self, rate_limit_key: str) -> bool:
        """Check if we're currently rate limited."""
        if rate_limit_key in self._rate_limits:
            reset_time = self._rate_limits[rate_limit_key]['reset_time']
            current_time = asyncio.get_event_loop().time()
            
            if current_time < reset_time:
                wait_time = reset_time - current_time
                await asyncio.sleep(wait_time)
                return True
            else:
                # Rate limit expired
                del self._rate_limits[rate_limit_key]
        
        return False
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=4, max=30),
        retry=retry_if_exception_type((aiohttp.ClientError, RateLimitError)),
        before_sleep=before_sleep_log(logger, logging.WARNING)
    )
    async def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Make HTTP request to Discord API with rate limiting and retry logic.
        
        Args:
            method: HTTP method
            endpoint: API endpoint
            data: Request body data
            params: Query parameters
            
        Returns:
            JSON response data or None
            
        Raises:
            DiscordAPIError: On API errors
        """
        if not self._session:
            await self._setup_session()
        
        if not self._session or not self.config.discord_token:
            logger.warning("Discord not configured, skipping request")
            return None
        
        rate_limit_key = self._get_rate_limit_key(method, endpoint)
        await self._check_rate_limit(rate_limit_key)
        
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        try:
            # Record metrics
            if self.metrics:
                action = endpoint.split('/')[0] if '/' in endpoint else endpoint
                self.metrics.discord_requests_total.labels(action=action).inc()
            
            start_time = asyncio.get_event_loop().time()
            
            request_kwargs = {'params': params} if params else {}
            if data:
                request_kwargs['json'] = data
            
            async with self._session.request(method, url, **request_kwargs) as response:
                # Handle rate limiting
                if response.status == 429:
                    retry_after = float(response.headers.get('Retry-After', 60))
                    await self._handle_rate_limit(rate_limit_key, retry_after)
                    raise RateLimitError(retry_after, "Rate limited")
                
                # Record timing
                if self.metrics:
                    duration = asyncio.get_event_loop().time() - start_time
                    action = endpoint.split('/')[0] if '/' in endpoint else endpoint
                    self.metrics.discord_request_duration.labels(action=action).observe(duration)
                
                if response.status == 204:  # No content
                    return None
                
                if response.status >= 400:
                    error_text = await response.text()
                    logger.error(f"Discord API error {response.status}: {error_text}")
                    if self.metrics:
                        action = endpoint.split('/')[0] if '/' in endpoint else endpoint
                        self.metrics.discord_requests_failed.labels(
                            action=action,
                            error_type=str(response.status)
                        ).inc()
                    raise DiscordAPIError(f"HTTP {response.status}: {error_text}")
                
                return await response.json() if response.content_type == 'application/json' else None
                
        except aiohttp.ClientError as e:
            logger.error(f"Discord API request failed: {e}")
            if self.metrics:
                action = endpoint.split('/')[0] if '/' in endpoint else endpoint
                self.metrics.discord_requests_failed.labels(
                    action=action,
                    error_type='client_error'
                ).inc()
            raise DiscordAPIError(f"HTTP request failed: {e}") from e
        except asyncio.TimeoutError as e:
            logger.error(f"Discord API timeout: {e}")
            if self.metrics:
                action = endpoint.split('/')[0] if '/' in endpoint else endpoint
                self.metrics.discord_requests_failed.labels(
                    action=action,
                    error_type='timeout'
                ).inc()
            raise DiscordAPIError(f"Request timeout: {e}") from e
    
    async def post_message(
        self,
        channel_id: str,
        content: Optional[str] = None,
        embed: Optional[DiscordEmbed] = None
    ) -> Optional[str]:
        """
        Post a message to Discord channel.
        
        Args:
            channel_id: Discord channel ID
            content: Message content
            embed: Discord embed
            
        Returns:
            Message ID if successful, None otherwise
        """
        if not channel_id:
            logger.warning("No channel ID provided for Discord message")
            return None
        
        try:
            # Check circuit breaker
            if not self._circuit_breaker.can_execute():
                logger.warning("Discord API circuit breaker is open")
                if self.metrics:
                    self.metrics.circuit_breaker_requests_blocked.labels(
                        service='discord'
                    ).inc()
                return None
            
            data = {}
            if content:
                data['content'] = content
            if embed:
                data['embeds'] = [self._embed_to_dict(embed)]
            
            if not data:
                logger.warning("No content or embed provided for Discord message")
                return None
            
            response = await self._make_request(
                'POST',
                f'channels/{channel_id}/messages',
                data=data
            )
            
            # Record success in circuit breaker
            await self._circuit_breaker.record_success()
            
            if response and 'id' in response:
                logger.info(f"Posted Discord message {response['id']} to channel {channel_id}")
                if self.metrics:
                    self.metrics.record_match_update_posted('discord_message')
                return response['id']
            
            return None
            
        except (DiscordAPIError, CircuitBreakerError) as e:
            await self._circuit_breaker.record_failure()
            logger.error(f"Failed to post Discord message: {e}")
            return None
    
    async def create_thread(
        self,
        channel_id: str,
        name: str,
        message_content: Optional[str] = None
    ) -> Optional[str]:
        """
        Create a thread in Discord channel.
        
        Args:
            channel_id: Parent channel ID
            name: Thread name
            message_content: Initial message content
            
        Returns:
            Thread ID if successful, None otherwise
        """
        try:
            if not self._circuit_breaker.can_execute():
                logger.warning("Discord API circuit breaker is open")
                return None
            
            data = {'name': name, 'type': 11}  # 11 = public thread
            if message_content:
                data['message'] = {'content': message_content}
            
            response = await self._make_request(
                'POST',
                f'channels/{channel_id}/threads',
                data=data
            )
            
            await self._circuit_breaker.record_success()
            
            if response and 'id' in response:
                thread_id = response['id']
                logger.info(f"Created Discord thread {thread_id}: {name}")
                return thread_id
            
            return None
            
        except (DiscordAPIError, CircuitBreakerError) as e:
            await self._circuit_breaker.record_failure()
            logger.error(f"Failed to create Discord thread: {e}")
            return None
    
    def _embed_to_dict(self, embed: DiscordEmbed) -> Dict[str, Any]:
        """Convert DiscordEmbed to dictionary."""
        embed_dict = {
            'title': embed.title,
            'description': embed.description,
            'color': embed.color
        }
        
        if embed.thumbnail:
            embed_dict['thumbnail'] = {'url': embed.thumbnail}
        if embed.image:
            embed_dict['image'] = {'url': embed.image}
        if embed.fields:
            embed_dict['fields'] = embed.fields
        if embed.footer:
            embed_dict['footer'] = embed.footer
        if embed.timestamp:
            embed_dict['timestamp'] = embed.timestamp
        
        return embed_dict
    
    def create_match_embed(self, match_data: MatchData, commentary: str) -> DiscordEmbed:
        """
        Create Discord embed for match update.
        
        Args:
            match_data: Match data from ESPN
            commentary: AI-generated commentary
            
        Returns:
            DiscordEmbed for the match update
        """
        # Determine embed color based on match status
        color = 0x00ff00  # Green for active
        if match_data.status in ['STATUS_FINAL', 'STATUS_FULL_TIME']:
            color = 0x0099ff  # Blue for completed
        elif match_data.status in ['STATUS_HALFTIME', 'STATUS_BREAK']:
            color = 0xffaa00  # Orange for break
        
        # Create title
        title = f"{match_data.home_team['short_name']} vs {match_data.away_team['short_name']}"
        if match_data.score != "0-0":
            title += f" ({match_data.score})"
        
        # Create description with commentary
        description = commentary
        
        # Add fields for match details
        fields = [
            {
                'name': 'Status',
                'value': match_data.status.replace('STATUS_', '').replace('_', ' ').title(),
                'inline': True
            },
            {
                'name': 'Score',
                'value': match_data.score,
                'inline': True
            }
        ]
        
        if match_data.venue:
            fields.append({
                'name': 'Venue',
                'value': match_data.venue,
                'inline': True
            })
        
        return DiscordEmbed(
            title=title,
            description=description,
            color=color,
            fields=fields,
            footer={'text': 'ECS Live Reporting'},
            timestamp=datetime.utcnow().isoformat()
        )
    
    async def health_check(self) -> bool:
        """
        Check Discord API health.
        
        Returns:
            bool: True if API is healthy
        """
        if not self.config.discord_token:
            return False
        
        try:
            # Make a simple request to check connectivity
            response = await self._make_request('GET', 'users/@me')
            return response is not None
        except Exception as e:
            logger.error(f"Discord API health check failed: {e}")
            return False