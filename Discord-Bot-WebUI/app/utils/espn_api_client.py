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
    TIMEOUT = 3  # Reduced from 5 to 3 seconds for faster failure detection
    MAX_RETRIES = 2  # Maximum retries per request

    # Cache TTLs
    LIVE_MATCH_CACHE_TTL = 15  # Increased from 10 to 15 seconds to reduce API load
    SCHEDULED_MATCH_CACHE_TTL = 300  # 5 minutes for scheduled matches
    FINISHED_MATCH_CACHE_TTL = 3600  # 1 hour for finished matches

    # Circuit breaker settings
    FAILURE_THRESHOLD = 5  # Number of failures before circuit opens
    RECOVERY_TIMEOUT = 60  # Seconds to wait before trying again

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'ECS-Discord-Bot/2.0',
            'Accept': 'application/json',
            'Accept-Encoding': 'gzip, deflate'
        })
        # Configure connection pool and retry settings
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=10,
            pool_maxsize=10,
            max_retries=requests.adapters.Retry(
                total=self.MAX_RETRIES,
                backoff_factor=0.3,
                status_forcelist=[500, 502, 503, 504]
            )
        )
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)

        self.redis_service = get_redis_service()
        self._last_request_time = {}
        self._request_counts = {}
        self._failure_counts = {}  # Track failures for circuit breaker
        self._circuit_open_until = {}  # Track when circuit can close

    def get_match_data(
        self,
        match_id: str,
        competition: str = 'eng.1',
        match_date: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Get real-time match data from ESPN API.

        Optimized for live matches with smart caching and rate limiting.

        Args:
            match_id: ESPN event id.
            competition: ESPN league code (e.g. ``usa.1`` / ``concacaf.champions``).
            match_date: Optional ``YYYYMMDD`` date hint. ESPN's default
                scoreboard only returns today's matches; passing the match's
                scheduled date scopes the query so the event is always
                included even near UTC day boundaries.
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

            # Check circuit breaker
            if self._is_circuit_open(match_id):
                logger.warning(f"Circuit breaker open for {match_id}, using cached data or returning None")
                return cached_data if cached_data else None

            # Rate limiting - minimum 3 seconds between requests for same match (increased from 2)
            last_request = self._last_request_time.get(match_id, 0)
            time_since_last = time.time() - last_request
            if time_since_last < 3:
                wait_time = 3 - time_since_last
                logger.debug(f"Rate limiting: waiting {wait_time:.1f}s for {match_id}")
                time.sleep(wait_time)

            # Make API request
            data = self._fetch_from_api(match_id, competition, match_date)

            if data:
                # Cache with appropriate TTL
                self._cache_data(cache_key, data)
                self._last_request_time[match_id] = time.time()

                # Track request count for monitoring
                self._request_counts[match_id] = self._request_counts.get(match_id, 0) + 1

                # Record success for circuit breaker
                self._record_success(match_id)

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

    def _fetch_from_api(
        self,
        match_id: str,
        competition: str,
        match_date: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch match data from ESPN API.
        """
        try:
            # The scoreboard endpoint is the only reliable ESPN API for MLS.
            # It returns all current-day matches including recently finished ones.
            # The /summary endpoint returns 404 for MLS (usa.1).
            base = f"{self.BASE_URL}/sports/soccer/{competition}/scoreboard"
            # If we have a match date, try that first (handles UTC-midnight
            # rollovers during live games), then fall back to the default
            # scoreboard window.
            endpoints = []
            if match_date:
                endpoints.append(f"{base}?dates={match_date}")
            endpoints.append(base)

            for url in endpoints:
                try:
                    response = self.session.get(url, timeout=self.TIMEOUT)

                    if response.status_code == 200:
                        raw_data = response.json()

                        # Scoreboard endpoint: search for this match among all events
                        if '/scoreboard' in url and 'events' in raw_data:
                            for event in raw_data['events']:
                                if str(event.get('id')) == str(match_id):
                                    return self._process_event_data(event)
                            # Match not in scoreboard — try next endpoint
                            logger.debug(f"Match {match_id} not found in scoreboard ({len(raw_data['events'])} events)")
                            continue

                        # Summary endpoint: has a different structure with header/boxscore
                        if '/summary' in url and 'header' in raw_data:
                            return self._process_summary_data(raw_data, match_id)

                        # Generic fallback processing
                        return self._process_espn_data(raw_data, match_id)
                    elif response.status_code in (400, 404):
                        logger.debug(f"ESPN returned {response.status_code} for {url}")
                        continue  # Try next endpoint
                    else:
                        logger.warning(f"ESPN API returned {response.status_code} for {url}")

                except requests.Timeout:
                    logger.warning(f"Timeout fetching from {url}")
                    self._record_failure(match_id)
                    continue
                except requests.RequestException as e:
                    logger.warning(f"Request error fetching from {url}: {e}")
                    self._record_failure(match_id)
                    continue
                except Exception as e:
                    logger.error(f"Unexpected error fetching from {url}: {e}")
                    self._record_failure(match_id)
                    continue

            # All endpoints failed
            self._record_failure(match_id)
            return None

        except Exception as e:
            logger.error(f"Error fetching from ESPN API: {e}")
            self._record_failure(match_id)
            return None

    def _is_circuit_open(self, match_id: str) -> bool:
        """Check if circuit breaker is open for this match."""
        open_until = self._circuit_open_until.get(match_id, 0)
        if time.time() < open_until:
            return True
        # Reset failure count if circuit was closed
        if match_id in self._failure_counts:
            self._failure_counts[match_id] = 0
        return False

    def _record_failure(self, match_id: str):
        """Record a failure and potentially open circuit breaker."""
        self._failure_counts[match_id] = self._failure_counts.get(match_id, 0) + 1

        if self._failure_counts[match_id] >= self.FAILURE_THRESHOLD:
            self._circuit_open_until[match_id] = time.time() + self.RECOVERY_TIMEOUT
            logger.error(
                f"Circuit breaker opened for {match_id} after {self._failure_counts[match_id]} failures. "
                f"Will retry after {self.RECOVERY_TIMEOUT} seconds."
            )

    def _record_success(self, match_id: str):
        """Record a successful request and reset failure count."""
        self._failure_counts[match_id] = 0
        if match_id in self._circuit_open_until:
            del self._circuit_open_until[match_id]
            logger.info(f"Circuit breaker closed for {match_id} after successful request")

    def _parse_substitution_text(self, text: str) -> tuple:
        """
        Parse substitution text to extract player on and player off.

        Examples:
        - "Jackson Ragen replaces Yeimar Gómez" -> ("Jackson Ragen", "Yeimar Gómez")
        - "Albert Rusnák (replaces Paul Rothrock)" -> ("Albert Rusnák", "Paul Rothrock")
        """
        try:
            if " replaces " in text:
                # Format: "Player On replaces Player Off"
                parts = text.split(" replaces ")
                if len(parts) == 2:
                    player_on = parts[0].strip().rstrip("(")
                    player_off = parts[1].strip().rstrip(")")
                    return (player_on, player_off)
            elif " for " in text:
                # Format: "Player On for Player Off"
                parts = text.split(" for ")
                if len(parts) == 2:
                    player_on = parts[0].strip()
                    player_off = parts[1].strip()
                    return (player_on, player_off)
        except Exception:
            pass
        return (None, None)

    def _process_summary_data(self, raw_data: Dict[str, Any], match_id: str) -> Optional[Dict[str, Any]]:
        """
        Process ESPN summary endpoint response.

        The summary endpoint (/summary?event=ID) has a different structure:
        - header.competitions[0] contains status and competitors
        - boxscore.teams contains scores
        - keyEvents or plays may contain match events
        """
        try:
            header = raw_data.get('header', {})
            competitions = header.get('competitions', [{}])
            if not competitions:
                return None

            competition_data = competitions[0]
            competitors = competition_data.get('competitors', [])

            if len(competitors) < 2:
                return None

            home_comp = competitors[0]
            away_comp = competitors[1]

            # Status from header
            status_detail = competition_data.get('status', {})
            status_type = status_detail.get('type', {})

            # Reuse the same status mapping
            status_map = {
                'STATUS_SCHEDULED': 'SCHEDULED',
                'STATUS_PRE_EVENT': 'PRE_MATCH',
                'STATUS_IN_PROGRESS': 'IN_PLAY',
                'STATUS_FIRST_HALF': 'IN_PLAY',
                'STATUS_SECOND_HALF': 'IN_PLAY',
                'STATUS_HALFTIME': 'HALFTIME',
                'STATUS_FINAL': 'FINAL',
                'STATUS_FULL_TIME': 'FINAL',
                'STATUS_FINAL_AET': 'FINAL',
                'STATUS_FINAL_PEN': 'FINAL',
                'STATUS_END_OF_REGULATION': 'IN_PLAY',
                'STATUS_EXTRA_TIME': 'IN_PLAY',
                'STATUS_PENALTIES': 'IN_PLAY',
                'STATUS_POSTPONED': 'POSTPONED',
                'STATUS_CANCELED': 'CANCELLED',
                'STATUS_SUSPENDED': 'POSTPONED',
                'STATUS_ABANDONED': 'CANCELLED',
                'STATUS_DELAYED': 'SCHEDULED',
            }

            espn_status_name = status_type.get('name', '')
            status = status_map.get(espn_status_name, '')
            if not status:
                espn_state = status_type.get('state', '').lower()
                if espn_state == 'post':
                    status = 'FINAL'
                elif espn_state == 'in':
                    status = 'IN_PLAY'
                elif espn_state == 'pre':
                    status = 'SCHEDULED'
                else:
                    status = 'UNKNOWN'

            # Extract events from keyEvents or roster/details
            match_events = []
            for ke in raw_data.get('keyEvents', []):
                ke_type_text = ke.get('type', {}).get('text', '')
                athletes = ke.get('athletesInvolved', [])
                clock_val = ke.get('clock', {}).get('displayValue', '')
                team_name = ke.get('team', {}).get('displayName', '')
                player_name = athletes[0].get('displayName', '') if athletes else ''

                if ke_type_text in ('Goal', 'Own Goal', 'Penalty'):
                    match_events.append({
                        'type': 'GOAL', 'minute': clock_val,
                        'player': player_name, 'team': team_name,
                        'description': ke.get('text', '')
                    })
                elif 'Card' in ke_type_text:
                    card_type = 'YELLOW_CARD' if 'Yellow' in ke_type_text else 'RED_CARD'
                    match_events.append({
                        'type': card_type, 'minute': clock_val,
                        'player': player_name, 'team': team_name,
                        'description': ke.get('text', '')
                    })
                elif ke_type_text in ('Substitution', 'Sub'):
                    sub_text = ke.get('text', '')
                    player_on, player_off = self._parse_substitution_text(sub_text)
                    if not player_on and athletes:
                        player_on = athletes[0].get('displayName', 'Unknown')
                    if not player_off and len(athletes) > 1:
                        player_off = athletes[1].get('displayName', 'Unknown')
                    match_events.append({
                        'type': 'SUBSTITUTION', 'minute': clock_val,
                        'player': player_on or 'Unknown',
                        'player_on': player_on or 'Unknown',
                        'player_off': player_off or 'Unknown',
                        'team': team_name,
                        'description': sub_text
                    })

            return {
                'match_id': match_id,
                'status': status,
                'completed': status_type.get('completed', False),
                'minute': status_detail.get('displayClock', '0'),
                'period': status_detail.get('period', 0),
                'home_team': home_comp.get('team', {}).get('displayName', 'Unknown'),
                'home_score': int(home_comp.get('score', '0')),
                'away_team': away_comp.get('team', {}).get('displayName', 'Unknown'),
                'away_score': int(away_comp.get('score', '0')),
                'events': match_events,
                'venue': header.get('venue', {}).get('fullName', ''),
                'cached_at': time.time()
            }

        except Exception as e:
            logger.error(f"Error processing ESPN summary data for {match_id}: {e}")
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

            elif 'header' in raw_data:
                return self._process_summary_data(raw_data, match_id)

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
            'STATUS_PRE_EVENT': 'PRE_MATCH',
            'STATUS_IN_PROGRESS': 'IN_PLAY',
            'STATUS_FIRST_HALF': 'IN_PLAY',
            'STATUS_SECOND_HALF': 'IN_PLAY',
            'STATUS_HALFTIME': 'HALFTIME',
            'STATUS_FINAL': 'FINAL',
            'STATUS_FULL_TIME': 'FINAL',
            'STATUS_FINAL_AET': 'FINAL',
            'STATUS_FINAL_PEN': 'FINAL',
            'STATUS_END_OF_REGULATION': 'IN_PLAY',
            'STATUS_EXTRA_TIME': 'IN_PLAY',
            'STATUS_PENALTIES': 'IN_PLAY',
            'STATUS_POSTPONED': 'POSTPONED',
            'STATUS_CANCELED': 'CANCELLED',
            'STATUS_SUSPENDED': 'POSTPONED',
            'STATUS_ABANDONED': 'CANCELLED',
            'STATUS_DELAYED': 'SCHEDULED',
        }

        espn_status_name = status_type.get('name', '')
        status = status_map.get(espn_status_name, '')

        # Fallback: use the ESPN 'state' field if the name didn't match our map
        if not status:
            espn_state = status_type.get('state', '').lower()
            if espn_state == 'post':
                status = 'FINAL'
            elif espn_state == 'in':
                status = 'IN_PLAY'
            elif espn_state == 'pre':
                status = 'SCHEDULED'
            else:
                status = 'UNKNOWN'
                logger.warning(f"Unmapped ESPN status: name={espn_status_name}, state={espn_state}")

        # Build team_id → team_name lookup from competitors.
        # ESPN details only have team.id, NOT team.displayName.
        team_lookup = {}
        for comp in competitors:
            tid = comp.get('team', {}).get('id', comp.get('id', ''))
            tname = comp.get('team', {}).get('displayName', 'Unknown')
            tlogo = comp.get('team', {}).get('logo', '')
            if tid:
                team_lookup[str(tid)] = {'name': tname, 'logo': tlogo}

        home_display = home_team.get('team', {}).get('displayName', 'Unknown')
        away_display = away_team.get('team', {}).get('displayName', 'Unknown')

        # Extract events (goals, cards, subs) in a single pass
        match_events = []
        for detail in competitions.get('details', []):
            detail_type_text = detail.get('type', {}).get('text', '')
            clock_val = detail.get('clock', {}).get('displayValue', '')
            athletes = detail.get('athletesInvolved', [])
            player_name = athletes[0].get('displayName', '') if athletes else ''
            player_headshot = ''
            if athletes:
                hs = athletes[0].get('headshot', '')
                player_headshot = hs if isinstance(hs, str) else hs.get('href', '') if isinstance(hs, dict) else ''
            player_jersey = athletes[0].get('jersey', '') if athletes else ''

            # Resolve team name from ID
            detail_team_id = str(detail.get('team', {}).get('id', ''))
            team_info = team_lookup.get(detail_team_id, {})
            team_name = team_info.get('name', '')
            team_logo = team_info.get('logo', '')

            # Use ESPN's boolean flags for reliable event type detection
            is_scoring = detail.get('scoringPlay', False)
            is_yellow = detail.get('yellowCard', False)
            is_red = detail.get('redCard', False)
            is_own_goal = detail.get('ownGoal', False)
            is_penalty = detail.get('penaltyKick', False)

            if is_scoring or 'Goal' in detail_type_text:
                # Goal variants: "Goal", "Goal - Header", "Goal - Free-kick",
                # "Goal - Volley", "Own Goal", "Penalty - Scored", etc.
                goal_type = 'OWN_GOAL' if is_own_goal else 'PENALTY_GOAL' if is_penalty else 'GOAL'
                match_events.append({
                    'type': goal_type,
                    'minute': clock_val,
                    'player': player_name,
                    'player_headshot': player_headshot,
                    'player_jersey': player_jersey,
                    'team': team_name,
                    'team_logo': team_logo,
                    'detail_text': detail_type_text,
                    'description': f"{detail_type_text}. {player_name} ({team_name}). {clock_val}."
                })

            elif is_yellow or is_red or 'Card' in detail_type_text:
                card_type = 'RED_CARD' if is_red else 'YELLOW_CARD'
                match_events.append({
                    'type': card_type,
                    'minute': clock_val,
                    'player': player_name,
                    'player_headshot': player_headshot,
                    'player_jersey': player_jersey,
                    'team': team_name,
                    'team_logo': team_logo,
                    'detail_text': detail_type_text,
                    'description': f"{detail_type_text}. {player_name} ({team_name}). {clock_val}."
                })

            elif detail_type_text in ('Substitution', 'Sub') or 'substitution' in detail_type_text.lower():
                sub_text = detail.get('text', '')
                player_on, player_off = self._parse_substitution_text(sub_text)
                if not player_on and athletes:
                    player_on = athletes[0].get('displayName', 'Unknown')
                if not player_off and len(athletes) > 1:
                    player_off = athletes[1].get('displayName', 'Unknown')

                # Headshot for the player coming on
                on_headshot = ''
                if athletes:
                    hs = athletes[0].get('headshot', '')
                    on_headshot = hs if isinstance(hs, str) else hs.get('href', '') if isinstance(hs, dict) else ''

                match_events.append({
                    'type': 'SUBSTITUTION',
                    'minute': clock_val,
                    'player': player_on or 'Unknown',
                    'player_on': player_on or 'Unknown',
                    'player_off': player_off or 'Unknown',
                    'player_headshot': on_headshot,
                    'team': team_name,
                    'team_logo': team_logo,
                    'detail_text': detail_type_text,
                    'description': sub_text or f"{player_on} replaces {player_off}. {clock_val}."
                })

        # Extract match statistics from both competitors
        def _parse_stats(competitor: Dict) -> Dict[str, str]:
            stats = {}
            for stat in competitor.get('statistics', []):
                stats[stat.get('name', '')] = stat.get('displayValue', '0')
            return stats

        home_stats = _parse_stats(home_team)
        away_stats = _parse_stats(away_team)

        return {
            'match_id': event.get('id'),
            'status': status,
            'completed': status_type.get('completed', False),
            'minute': status_detail.get('displayClock', '0'),
            'period': status_detail.get('period', 0),
            'home_team': home_display,
            'home_score': int(home_team.get('score', 0)),
            'home_logo': home_team.get('team', {}).get('logo', ''),
            'home_form': home_team.get('form', ''),
            'away_team': away_display,
            'away_score': int(away_team.get('score', 0)),
            'away_logo': away_team.get('team', {}).get('logo', ''),
            'away_form': away_team.get('form', ''),
            'stats': {
                'home': home_stats,
                'away': away_stats,
            },
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
        """Return minimal mock data when API is unavailable."""
        logger.warning(f"All ESPN API endpoints failed for match {match_id}, using mock data")
        return {
            'match_id': match_id,
            'status': 'UNKNOWN',
            'minute': '0',
            'period': 0,
            'home_team': 'Unknown',
            'home_score': 0,
            'away_team': 'Unknown',
            'away_score': 0,
            'events': [],
            'venue': 'Unknown Venue',
            'attendance': 0,
            'cached_at': time.time(),
            'mock_data': True,
            'error': 'ESPN API unavailable'
        }

    def get_match_lineups(self, match_id: str, competition: str = 'usa.1') -> Optional[Dict[str, Any]]:
        """
        Fetch match lineups from ESPN summary endpoint.

        The summary API (site.web.api.espn.com) includes rosters with
        starter flag, position, jersey, and formation placement.

        Returns dict with 'home' and 'away' keys, each containing:
        - team: team name
        - logo: team logo URL
        - starters: list of {name, jersey, position, formation_place}
        - subs: list of {name, jersey, position}

        Returns None if lineups aren't available yet.
        """
        try:
            url = f"https://site.web.api.espn.com/apis/site/v2/sports/soccer/{competition}/summary?event={match_id}"
            response = self.session.get(url, timeout=self.TIMEOUT)

            if response.status_code != 200:
                logger.info(f"ESPN summary returned {response.status_code} for lineups (match {match_id})")
                return None

            data = response.json()
            rosters = data.get('rosters', [])
            if not rosters:
                logger.info(f"No roster data in ESPN summary for match {match_id}")
                return None

            result = {}
            for roster_entry in rosters:
                side = roster_entry.get('homeAway', 'home')
                team_data = roster_entry.get('team', {})
                players = roster_entry.get('roster', [])

                if not players:
                    continue

                starters = []
                subs = []
                for player in players:
                    player_info = {
                        'name': player.get('athlete', {}).get('displayName', 'Unknown'),
                        'jersey': player.get('jersey', ''),
                        'position': player.get('position', {}).get('abbreviation', ''),
                        'position_name': player.get('position', {}).get('name', ''),
                    }

                    if player.get('starter', False):
                        player_info['formation_place'] = player.get('formationPlace', '')
                        starters.append(player_info)
                    else:
                        subs.append(player_info)

                # Sort starters by formation place (GK first, then defense → attack)
                starters.sort(key=lambda p: int(p.get('formation_place', '99') or '99'))

                logos = team_data.get('logos', [])
                logo_url = logos[0].get('href', '') if logos else ''

                result[side] = {
                    'team': team_data.get('displayName', 'Unknown'),
                    'logo': logo_url,
                    'starters': starters,
                    'subs': subs,
                }

            if not result:
                return None

            return result

        except Exception as e:
            logger.error(f"Error fetching lineups for match {match_id}: {e}")
            return None