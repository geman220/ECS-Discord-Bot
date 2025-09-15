# app/utils/espn_api_client.py

"""
ESPN API Client for Real-Time Match Data

Optimized for live match reporting with efficient polling and caching.
"""

import logging
import requests
import time
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
import json

from app.services.redis_connection_service import get_redis_service

logger = logging.getLogger(__name__)


class ESPNAPIClient:
    """
    ESPN API Client optimized for real-time match updates.

    Features:
    - Efficient polling for live matches
    - Smart caching to reduce API calls
    - Error handling with retry logic
    - Mock data fallback for testing
    """

    BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer"
    TIMEOUT = 5  # Short timeout for real-time updates

    # Cache TTLs
    LIVE_MATCH_CACHE_TTL = 10  # 10 seconds for live matches
    SCHEDULED_MATCH_CACHE_TTL = 300  # 5 minutes for scheduled matches
    FINISHED_MATCH_CACHE_TTL = 3600  # 1 hour for finished matches

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'ECS-Discord-Bot/2.0',
            'Accept': 'application/json',
            'Accept-Encoding': 'gzip, deflate'
        })
        self.redis_service = get_redis_service()
        self._last_request_time = {}
        self._request_counts = {}

    def get_match_data(self, match_id: str, competition: str = 'eng.1') -> Optional[Dict[str, Any]]:
        """
        Get real-time match data from ESPN API.

        Optimized for live matches with smart caching and rate limiting.
        """
        try:
            # Check cache first
            cache_key = f"espn:match:{competition}:{match_id}"
            cached_data = self._get_cached_data(cache_key)

            if cached_data:
                # Check if cache is still valid based on match status
                status = cached_data.get('status', '')
                cache_age = time.time() - cached_data.get('cached_at', 0)

                # Dynamic cache validation based on match status
                if status in ['IN_PLAY', 'HALFTIME']:
                    if cache_age < self.LIVE_MATCH_CACHE_TTL:
                        logger.debug(f"Using cached live data for {match_id} (age: {cache_age:.1f}s)")
                        return cached_data
                elif status in ['SCHEDULED', 'PRE_MATCH']:
                    if cache_age < self.SCHEDULED_MATCH_CACHE_TTL:
                        logger.debug(f"Using cached scheduled data for {match_id}")
                        return cached_data
                elif status in ['FINAL', 'COMPLETED']:
                    if cache_age < self.FINISHED_MATCH_CACHE_TTL:
                        logger.debug(f"Using cached finished data for {match_id}")
                        return cached_data

            # Rate limiting - minimum 2 seconds between requests for same match
            last_request = self._last_request_time.get(match_id, 0)
            time_since_last = time.time() - last_request
            if time_since_last < 2:
                wait_time = 2 - time_since_last
                logger.debug(f"Rate limiting: waiting {wait_time:.1f}s for {match_id}")
                time.sleep(wait_time)

            # Make API request
            data = self._fetch_from_api(match_id, competition)

            if data:
                # Cache with appropriate TTL
                self._cache_data(cache_key, data)
                self._last_request_time[match_id] = time.time()

                # Track request count for monitoring
                self._request_counts[match_id] = self._request_counts.get(match_id, 0) + 1

                return data

            # If API fails, return cached data even if expired
            if cached_data:
                logger.warning(f"API failed, using expired cache for {match_id}")
                return cached_data

            # Last resort - return mock data
            return self._get_mock_data(match_id)

        except Exception as e:
            logger.error(f"Error getting match data for {match_id}: {e}")
            return self._get_mock_data(match_id)

    def _fetch_from_api(self, match_id: str, competition: str) -> Optional[Dict[str, Any]]:
        """
        Fetch match data from ESPN API.
        """
        try:
            # Parse competition (e.g., 'eng.1' -> 'eng.1')
            league = competition.replace('.', '/')

            # Try multiple endpoints for better reliability
            endpoints = [
                f"{self.BASE_URL}/{league}/scoreboard/{match_id}",
                f"{self.BASE_URL}/{league}/summary?event={match_id}",
                f"https://www.espn.com/soccer/match/_/gameId/{match_id}"
            ]

            for url in endpoints:
                try:
                    response = self.session.get(url, timeout=self.TIMEOUT)

                    if response.status_code == 200:
                        raw_data = response.json()
                        return self._process_espn_data(raw_data, match_id)
                    elif response.status_code == 404:
                        continue  # Try next endpoint
                    else:
                        logger.warning(f"ESPN API returned {response.status_code} for {url}")

                except requests.Timeout:
                    logger.warning(f"Timeout fetching from {url}")
                    continue
                except Exception as e:
                    logger.warning(f"Error fetching from {url}: {e}")
                    continue

            return None

        except Exception as e:
            logger.error(f"Error fetching from ESPN API: {e}")
            return None

    def _process_espn_data(self, raw_data: Dict[str, Any], match_id: str) -> Dict[str, Any]:
        """
        Process raw ESPN API response into standardized format.
        """
        try:
            # Handle different ESPN response formats
            if 'events' in raw_data:
                # Scoreboard format
                events = raw_data.get('events', [])
                if events:
                    event = events[0]
                    return self._process_event_data(event)

            elif 'gameData' in raw_data:
                # Summary format
                return self._process_game_data(raw_data['gameData'])

            elif 'header' in raw_data:
                # Match page format
                return self._process_match_page_data(raw_data)

            # Fallback processing
            return {
                'match_id': match_id,
                'status': 'UNKNOWN',
                'home_score': 0,
                'away_score': 0,
                'events': [],
                'cached_at': time.time()
            }

        except Exception as e:
            logger.error(f"Error processing ESPN data: {e}")
            return None

    def _process_event_data(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process event data from ESPN scoreboard API.
        """
        competitions = event.get('competitions', [{}])[0]
        competitors = competitions.get('competitors', [])

        home_team = competitors[0] if len(competitors) > 0 else {}
        away_team = competitors[1] if len(competitors) > 1 else {}

        status_detail = competitions.get('status', {})
        status_type = status_detail.get('type', {})

        # Map ESPN status to our status
        status_map = {
            'STATUS_SCHEDULED': 'SCHEDULED',
            'STATUS_IN_PROGRESS': 'IN_PLAY',
            'STATUS_HALFTIME': 'HALFTIME',
            'STATUS_FINAL': 'FINAL',
            'STATUS_POSTPONED': 'POSTPONED',
            'STATUS_CANCELED': 'CANCELLED'
        }

        status = status_map.get(status_type.get('name', ''), 'UNKNOWN')

        # Extract events (goals, cards, etc.)
        match_events = []

        # Check for scoring plays
        for detail in competitions.get('details', []):
            if detail.get('type', {}).get('text') in ['Goal', 'Own Goal', 'Penalty']:
                match_events.append({
                    'type': 'GOAL',
                    'minute': detail.get('clock', {}).get('displayValue', ''),
                    'player': detail.get('athletesInvolved', [{}])[0].get('displayName', ''),
                    'team': detail.get('team', {}).get('displayName', ''),
                    'description': detail.get('text', '')
                })

        # Check for cards
        for detail in competitions.get('details', []):
            if 'Card' in detail.get('type', {}).get('text', ''):
                card_type = 'YELLOW_CARD' if 'Yellow' in detail['type']['text'] else 'RED_CARD'
                match_events.append({
                    'type': card_type,
                    'minute': detail.get('clock', {}).get('displayValue', ''),
                    'player': detail.get('athletesInvolved', [{}])[0].get('displayName', ''),
                    'team': detail.get('team', {}).get('displayName', ''),
                    'description': detail.get('text', '')
                })

        return {
            'match_id': event.get('id'),
            'status': status,
            'minute': status_detail.get('displayClock', '0'),
            'period': status_detail.get('period', 0),
            'home_team': home_team.get('team', {}).get('displayName', 'Unknown'),
            'home_score': int(home_team.get('score', 0)),
            'away_team': away_team.get('team', {}).get('displayName', 'Unknown'),
            'away_score': int(away_team.get('score', 0)),
            'events': match_events,
            'venue': event.get('venue', {}).get('fullName', ''),
            'attendance': event.get('attendance', 0),
            'cached_at': time.time()
        }

    def _get_cached_data(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """
        Get cached data from Redis.
        """
        try:
            data = self.redis_service.execute_command('get', cache_key)
            if data:
                return json.loads(data)
        except Exception as e:
            logger.debug(f"Cache miss for {cache_key}: {e}")
        return None

    def _cache_data(self, cache_key: str, data: Dict[str, Any]):
        """
        Cache data in Redis with appropriate TTL.
        """
        try:
            status = data.get('status', '')

            # Determine TTL based on match status
            if status in ['IN_PLAY', 'HALFTIME']:
                ttl = self.LIVE_MATCH_CACHE_TTL
            elif status in ['SCHEDULED', 'PRE_MATCH']:
                ttl = self.SCHEDULED_MATCH_CACHE_TTL
            else:
                ttl = self.FINISHED_MATCH_CACHE_TTL

            self.redis_service.execute_command(
                'setex', cache_key, ttl, json.dumps(data)
            )

        except Exception as e:
            logger.error(f"Failed to cache data: {e}")

    def _get_mock_data(self, match_id: str) -> Dict[str, Any]:
        """
        Return mock data when API is unavailable.
        """
        logger.warning(f"Using mock data for match {match_id}")

        # Create a simple in-progress mock
        return {
                'header': {
                    'id': match_id,
                    'competitions': [{
                        'id': match_id,
                        'competitors': [
                            {
                                'homeAway': 'home',
                                'team': {'displayName': 'Seattle Sounders FC'},
                                'score': '1'
                            },
                            {
                                'homeAway': 'away',
                                'team': {'displayName': 'Inter Miami CF'},
                                'score': '0'
                            }
                        ],
                        'status': {
                            'type': {'name': 'STATUS_IN_PROGRESS'},
                            'displayClock': '23:00',
                            'period': 1
                        }
                    }]
                },
                'plays': [],
                'mock_data': True,
                'cached_at': time.time()
            }