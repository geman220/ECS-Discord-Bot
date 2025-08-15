# app/services/espn_service.py

"""
ESPN API Service

Centralized service for all ESPN API interactions.
This replaces duplicate ESPN fetching logic across the codebase.
"""

import asyncio
import logging
from typing import Optional, Dict, Any, Union
from datetime import datetime, timedelta
import aiohttp
from app.utils.safe_redis import get_safe_redis
import json

logger = logging.getLogger(__name__)


class ESPNService:
    """
    Centralized service for ESPN API operations.
    Provides caching, retry logic, and standardized error handling.
    """
    
    BASE_URL = "https://site.api.espn.com/apis/site/v2"
    CACHE_TTL = 300  # 5 minutes
    MAX_RETRIES = 3
    
    def __init__(self):
        self._redis = None
        self._session = None
    
    @property
    def redis(self):
        """Get Redis client for caching."""
        if self._redis is None:
            self._redis = get_safe_redis()
        return self._redis
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session.
        
        Creates a new session for each call to avoid event loop issues
        when called from different threads/contexts.
        """
        # Always create a new session to avoid event loop conflicts
        # This is especially important when called via async_to_sync from Flask
        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        return aiohttp.ClientSession(timeout=timeout)
    
    def _get_cache_key(self, endpoint: str) -> str:
        """Generate cache key for endpoint."""
        return f"espn_api:{endpoint.replace('/', ':')}"
    
    async def _fetch_from_cache(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """Fetch data from Redis cache."""
        try:
            cached_data = self.redis.get(cache_key)
            if cached_data:
                return json.loads(cached_data.decode('utf-8'))
        except Exception as e:
            logger.warning(f"Cache fetch failed for {cache_key}: {e}")
        return None
    
    async def _store_in_cache(self, cache_key: str, data: Dict[str, Any]) -> None:
        """Store data in Redis cache."""
        try:
            serialized_data = json.dumps(data, default=str)
            self.redis.setex(cache_key, self.CACHE_TTL, serialized_data)
        except Exception as e:
            logger.warning(f"Cache store failed for {cache_key}: {e}")
    
    async def fetch_data(self, endpoint: str = None, full_url: str = None, use_cache: bool = True) -> Optional[Dict[str, Any]]:
        """
        Fetch data from ESPN API with caching and retry logic.
        
        Args:
            endpoint: ESPN API endpoint (e.g., 'sports/soccer/usa.1/scoreboard')
            full_url: Complete URL if not using base URL
            use_cache: Whether to use Redis caching
            
        Returns:
            API response data or None if failed
        """
        # Determine URL
        if full_url:
            url = full_url
            cache_endpoint = full_url.replace(self.BASE_URL, '').lstrip('/')
        elif endpoint:
            url = f"{self.BASE_URL}/{endpoint}"
            cache_endpoint = endpoint
        else:
            raise ValueError("Either endpoint or full_url must be provided")
        
        # Check cache first
        cache_key = self._get_cache_key(cache_endpoint) if use_cache else None
        if cache_key:
            cached_data = await self._fetch_from_cache(cache_key)
            if cached_data:
                logger.debug(f"Cache hit for ESPN endpoint: {cache_endpoint}")
                return cached_data
        
        # Fetch from API with retry logic
        for attempt in range(self.MAX_RETRIES):
            try:
                logger.info(f"Fetching from ESPN API (attempt {attempt + 1}): {url}")
                
                async with await self._get_session() as session:
                    async with session.get(url) as response:
                        if response.status == 200:
                            data = await response.json()
                            logger.info(f"Successfully fetched ESPN data from: {url}")
                            
                            # Cache successful response
                            if cache_key:
                                await self._store_in_cache(cache_key, data)
                            
                            return data
                        
                        elif response.status == 429:  # Rate limited
                            retry_after = int(response.headers.get('Retry-After', 30))
                            logger.warning(f"ESPN API rate limited. Retry after {retry_after}s")
                            if attempt < self.MAX_RETRIES - 1:
                                await asyncio.sleep(retry_after)
                                continue
                        
                        else:
                            logger.error(f"ESPN API error {response.status}: {await response.text()}")
                        
            except asyncio.TimeoutError:
                logger.warning(f"ESPN API timeout (attempt {attempt + 1})")
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
                    continue
                    
            except aiohttp.ClientError as e:
                logger.error(f"ESPN API client error (attempt {attempt + 1}): {e}")
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                    
            except Exception as e:
                logger.error(f"Unexpected ESPN API error: {e}", exc_info=True)
                break
        
        logger.error(f"Failed to fetch ESPN data after {self.MAX_RETRIES} attempts: {url}")
        return None
    
    async def get_team_record(self, team_id: str) -> tuple[Union[Dict[str, Any], str], Optional[str]]:
        """
        Get team record and logo URL.
        
        Args:
            team_id: ESPN team ID
            
        Returns:
            Tuple of (record_info, logo_url)
        """
        data = await self.fetch_data(f"sports/soccer/usa.1/teams/{team_id}")
        
        if not data or "team" not in data:
            return "Record not available", None
        
        team_data = data["team"]
        record_data = team_data.get("record", {}).get("items", [])
        logo_url = None
        
        if team_data.get("logos"):
            logo_url = team_data["logos"][0].get("href")
        
        if record_data:
            stats = record_data[0].get("stats", [])
            record_info = {stat["name"]: stat["value"] for stat in stats}
            return record_info, logo_url
        
        return "Record not available", logo_url
    
    async def get_match_data(self, match_id: str, competition: str = "usa.1") -> Optional[Dict[str, Any]]:
        """
        Get live match data for a specific match.
        
        Args:
            match_id: ESPN match ID
            competition: Competition identifier (default: usa.1 for MLS)
            
        Returns:
            Match data or None if not found
        """
        endpoint = f"sports/soccer/{competition}/scoreboard/{match_id}"
        return await self.fetch_data(endpoint)
    
    async def get_scoreboard(self, competition: str = "usa.1", date: str = None) -> Optional[Dict[str, Any]]:
        """
        Get scoreboard for a competition on a specific date.
        
        Args:
            competition: Competition identifier
            date: Date in YYYYMMDD format (default: today)
            
        Returns:
            Scoreboard data or None if failed
        """
        endpoint = f"sports/soccer/{competition}/scoreboard"
        if date:
            endpoint += f"?dates={date}"
        
        return await self.fetch_data(endpoint)
    
    async def close(self):
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()


# Global service instance
_espn_service = None

def get_espn_service() -> ESPNService:
    """Get the global ESPN service instance."""
    global _espn_service
    if _espn_service is None:
        _espn_service = ESPNService()
    return _espn_service

# Convenience functions for backward compatibility
async def fetch_espn_data(endpoint: str = None, full_url: str = None) -> Optional[Dict[str, Any]]:
    """
    Backward compatibility function for existing code.
    """
    service = get_espn_service()
    return await service.fetch_data(endpoint=endpoint, full_url=full_url)