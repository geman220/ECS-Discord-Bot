#!/usr/bin/env python3
"""
ESPN Player Service

Fetches and caches player data including headshot images from ESPN API.
Provides scalable, maintainable player information for Discord embeds.
"""

import asyncio
import logging
import time
from typing import Dict, Optional, Any
import aiohttp
from app.services.redis_connection_service import get_redis_service

logger = logging.getLogger(__name__)


class ESPNPlayerService:
    """Service for fetching and caching ESPN player data."""

    def __init__(self):
        self.redis_service = get_redis_service()
        self.cache_ttl = 86400  # 24 hours
        self.base_url = "https://site.api.espn.com/apis/site/v2/sports/soccer/usa.1"

    async def get_player_image(self, player_name: str, team_name: str = "Seattle Sounders FC") -> Optional[str]:
        """
        Get player headshot image URL from ESPN API.

        Args:
            player_name: Player's full name
            team_name: Team name for context

        Returns:
            Player headshot URL or None if not found
        """
        try:
            # Check cache first
            cache_key = f"espn_player:{team_name}:{player_name.lower()}"
            cached_data = await self._get_from_cache(cache_key)

            if cached_data:
                return cached_data.get('headshot_url')

            # Fetch from ESPN API
            player_data = await self._fetch_player_from_espn(player_name, team_name)

            if player_data:
                # Cache the result
                await self._cache_player_data(cache_key, player_data)
                return player_data.get('headshot_url')

            return None

        except Exception as e:
            logger.warning(f"Error fetching player image for {player_name}: {e}")
            return None

    async def get_team_roster(self, team_name: str = "Seattle Sounders FC") -> Dict[str, Dict[str, Any]]:
        """
        Get full team roster with player data from ESPN.

        Args:
            team_name: Team name

        Returns:
            Dictionary mapping player names to player data
        """
        try:
            cache_key = f"espn_roster:{team_name.lower()}"
            cached_roster = await self._get_from_cache(cache_key)

            if cached_roster:
                return cached_roster

            # Fetch team roster from ESPN
            roster = await self._fetch_team_roster_from_espn(team_name)

            if roster:
                # Cache for 24 hours
                await self._cache_data(cache_key, roster, self.cache_ttl)

            return roster or {}

        except Exception as e:
            logger.error(f"Error fetching team roster for {team_name}: {e}")
            return {}

    async def _fetch_player_from_espn(self, player_name: str, team_name: str) -> Optional[Dict[str, Any]]:
        """Fetch individual player data from ESPN API."""
        try:
            # First get team roster to find player
            roster = await self.get_team_roster(team_name)

            # Search for player in roster
            player_key = self._normalize_player_name(player_name)

            for name, data in roster.items():
                if self._normalize_player_name(name) == player_key:
                    return data

            # If not found in roster, try direct search
            return await self._search_player_directly(player_name)

        except Exception as e:
            logger.error(f"Error fetching player {player_name} from ESPN: {e}")
            return None

    async def _fetch_team_roster_from_espn(self, team_name: str) -> Dict[str, Dict[str, Any]]:
        """Fetch team roster from ESPN API."""
        try:
            # Get Seattle Sounders team ID (MLS team ID: 9726)
            team_id = self._get_team_id(team_name)

            if not team_id:
                logger.warning(f"Team ID not found for {team_name}")
                return {}

            url = f"{self.base_url}/teams/{team_id}/roster"

            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status == 200:
                        data = await response.json()
                        return self._parse_roster_data(data)
                    else:
                        logger.warning(f"ESPN API returned status {response.status} for team roster")
                        return {}

        except Exception as e:
            logger.error(f"Error fetching team roster from ESPN: {e}")
            return {}

    async def _search_player_directly(self, player_name: str) -> Optional[Dict[str, Any]]:
        """Search for player directly in ESPN API."""
        try:
            # ESPN sometimes has search endpoints, but they're not always public
            # For now, return None and rely on roster data
            logger.info(f"Direct player search not implemented for {player_name}")
            return None

        except Exception as e:
            logger.error(f"Error in direct player search for {player_name}: {e}")
            return None

    def _get_team_id(self, team_name: str) -> Optional[str]:
        """Get ESPN team ID for team name."""
        team_ids = {
            "Seattle Sounders FC": "9726",
            "seattle sounders fc": "9726",
            "sounders": "9726",
            "seattle": "9726",
            # Add more teams as needed
            "Portland Timbers": "9725",
            "Vancouver Whitecaps": "9727",
            "Los Angeles FC": "9708",
            "LA Galaxy": "9698"
        }

        return team_ids.get(team_name.lower())

    def _parse_roster_data(self, espn_data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """Parse ESPN roster data into our format."""
        roster = {}

        try:
            athletes = espn_data.get('athletes', [])

            for athlete in athletes:
                player_data = self._extract_player_data(athlete)
                if player_data:
                    name = player_data['full_name']
                    roster[name] = player_data

        except Exception as e:
            logger.error(f"Error parsing ESPN roster data: {e}")

        return roster

    def _extract_player_data(self, athlete_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Extract relevant player data from ESPN athlete object."""
        try:
            player = {
                'full_name': athlete_data.get('fullName', ''),
                'display_name': athlete_data.get('displayName', ''),
                'short_name': athlete_data.get('shortName', ''),
                'jersey_number': athlete_data.get('jersey', ''),
                'position': self._get_position(athlete_data),
                'headshot_url': self._get_headshot_url(athlete_data),
                'age': athlete_data.get('age'),
                'height': athlete_data.get('height'),
                'weight': athlete_data.get('weight'),
                'birth_place': self._get_birth_place(athlete_data),
                'espn_id': athlete_data.get('id')
            }

            return player if player['full_name'] else None

        except Exception as e:
            logger.error(f"Error extracting player data: {e}")
            return None

    def _get_position(self, athlete_data: Dict[str, Any]) -> str:
        """Extract player position."""
        position = athlete_data.get('position', {})
        if isinstance(position, dict):
            return position.get('displayName', 'Unknown')
        return str(position) if position else 'Unknown'

    def _get_headshot_url(self, athlete_data: Dict[str, Any]) -> Optional[str]:
        """Extract player headshot URL."""
        headshot = athlete_data.get('headshot')
        if isinstance(headshot, dict):
            return headshot.get('href')
        elif isinstance(headshot, str):
            return headshot
        return None

    def _get_birth_place(self, athlete_data: Dict[str, Any]) -> Optional[str]:
        """Extract player birth place."""
        birth_place = athlete_data.get('birthPlace')
        if isinstance(birth_place, dict):
            city = birth_place.get('city', '')
            country = birth_place.get('country', '')
            return f"{city}, {country}".strip(', ') if city or country else None
        return None

    def _normalize_player_name(self, name: str) -> str:
        """Normalize player name for comparison."""
        return name.lower().strip().replace('.', '').replace('-', ' ')

    async def _get_from_cache(self, key: str) -> Optional[Dict[str, Any]]:
        """Get data from Redis cache."""
        try:
            if self.redis_service and hasattr(self.redis_service, 'client'):
                redis_client = getattr(self.redis_service, 'client', None)
                if redis_client:
                    cached = await redis_client.get(key)
                    if cached:
                        import json
                        return json.loads(cached)
        except Exception as e:
            logger.warning(f"Cache get error for {key}: {e}")
        return None

    async def _cache_data(self, key: str, data: Dict[str, Any], ttl: int):
        """Cache data in Redis."""
        try:
            if self.redis_service and hasattr(self.redis_service, 'client'):
                redis_client = getattr(self.redis_service, 'client', None)
                if redis_client:
                    import json
                    await redis_client.setex(
                        key, ttl, json.dumps(data, default=str)
                    )
        except Exception as e:
            logger.warning(f"Cache set error for {key}: {e}")

    async def _cache_player_data(self, key: str, player_data: Dict[str, Any]):
        """Cache player data."""
        await self._cache_data(key, player_data, self.cache_ttl)


# Global instance
_espn_player_service = None


def get_espn_player_service() -> ESPNPlayerService:
    """Get singleton ESPN player service instance."""
    global _espn_player_service
    if _espn_player_service is None:
        _espn_player_service = ESPNPlayerService()
    return _espn_player_service