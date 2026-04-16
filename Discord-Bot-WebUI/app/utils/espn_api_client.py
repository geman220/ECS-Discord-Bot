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

    Uses ESPN's /summary?event={match_id} endpoint exclusively. This endpoint
    is keyed directly on the match ID and is independent of ESPN's
    "current-day scoreboard" window, so it works for every supported league
    (MLS, Concacaf, Leagues Cup, etc.) without timezone/date heuristics.
    """

    BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer"
    TIMEOUT = 5
    MAX_RETRIES = 2

    # Cache TTLs
    LIVE_MATCH_CACHE_TTL = 15
    SCHEDULED_MATCH_CACHE_TTL = 300
    FINISHED_MATCH_CACHE_TTL = 3600

    # Circuit breaker settings
    FAILURE_THRESHOLD = 5
    RECOVERY_TIMEOUT = 60

    # ESPN status name → our normalized status
    STATUS_MAP = {
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
    ) -> Optional[Dict[str, Any]]:
        """
        Get real-time match data from ESPN's /summary endpoint.

        Returns None on any failure. Callers are expected to treat None as an
        error signal (increment error counters, retry next cycle). Never
        returns fabricated/mock data — silent fake data is how we missed live
        goals once before.

        Args:
            match_id: ESPN event id.
            competition: ESPN league code (e.g. ``usa.1`` / ``concacaf.champions``).
        """
        cache_key = f"espn:match:{competition}:{match_id}"
        cached_data = self._get_cached_data(cache_key)

        # Serve fresh cache hits
        if cached_data:
            status = cached_data.get('status', '')
            cache_age = time.time() - cached_data.get('cached_at', 0)
            ttl = self._cache_ttl_for_status(status)
            if ttl is not None and cache_age < ttl:
                logger.debug(f"Using cached data for {match_id} (status={status}, age={cache_age:.1f}s)")
                return cached_data

        # Circuit breaker shortcut
        if self._is_circuit_open(match_id):
            logger.warning(f"Circuit breaker open for {match_id}; skipping fetch")
            return cached_data  # may be None — caller handles as error

        # Rate limit: at most one live request per 3s per match
        last_request = self._last_request_time.get(match_id, 0)
        wait_time = 3 - (time.time() - last_request)
        if wait_time > 0:
            time.sleep(wait_time)

        data = self._fetch_from_api(match_id, competition)
        if data:
            self._cache_data(cache_key, data)
            self._last_request_time[match_id] = time.time()
            self._request_counts[match_id] = self._request_counts.get(match_id, 0) + 1
            self._record_success(match_id)
            return data

        # Real failure — surface it. Expired cache is not returned silently
        # because stale data masks problems during live matches.
        self._record_failure(match_id)
        return None

    def _cache_ttl_for_status(self, status: str) -> Optional[int]:
        if status in ('IN_PLAY', 'HALFTIME'):
            return self.LIVE_MATCH_CACHE_TTL
        if status in ('SCHEDULED', 'PRE_MATCH'):
            return self.SCHEDULED_MATCH_CACHE_TTL
        if status in ('FINAL', 'COMPLETED'):
            return self.FINISHED_MATCH_CACHE_TTL
        return None

    def _fetch_from_api(
        self,
        match_id: str,
        competition: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch match data from ESPN's /summary?event={match_id} endpoint.
        """
        url = f"{self.BASE_URL}/{competition}/summary?event={match_id}"
        try:
            response = self.session.get(url, timeout=self.TIMEOUT)
        except requests.Timeout:
            logger.warning(f"Timeout fetching {url}")
            return None
        except requests.RequestException as e:
            logger.warning(f"Request error fetching {url}: {e}")
            return None

        if response.status_code != 200:
            logger.warning(f"ESPN returned {response.status_code} for {url}")
            return None

        try:
            raw_data = response.json()
        except ValueError as e:
            logger.error(f"Invalid JSON from {url}: {e}")
            return None

        return self._process_summary_data(raw_data, match_id)

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
        Process ESPN /summary?event={id} response into our normalized schema.

        Sources used:
        - header.competitions[0]: status, competitors (team, score, logo, form, homeAway)
        - boxscore.teams[].statistics: live match statistics
        - keyEvents[]: goals, cards, substitutions (with participants → athletes)
        - rosters[].roster[]: athlete_id → jersey + headshot enrichment
        - gameInfo.venue.fullName: venue

        Output schema matches what downstream consumers expect (see
        realtime_reporting_service._extract_new_events / _build_event_embed):
        match_id, status, completed, minute, period, home_team, home_score,
        home_logo, home_form, away_team, away_score, away_logo, away_form,
        stats{home, away}, events[{type, minute, player, player_headshot,
        player_jersey, team, team_logo, detail_text, description, id}],
        venue, attendance, cached_at.
        """
        try:
            header = raw_data.get('header') or {}
            competitions = header.get('competitions') or []
            if not competitions:
                logger.error(f"No competitions in summary for {match_id}")
                return None

            comp = competitions[0]
            competitors = comp.get('competitors') or []
            if len(competitors) < 2:
                logger.error(f"Incomplete competitors in summary for {match_id}")
                return None

            # Pick home/away by explicit flag (ESPN order is not guaranteed)
            home = next((c for c in competitors if c.get('homeAway') == 'home'), competitors[0])
            away = next((c for c in competitors if c.get('homeAway') == 'away'), competitors[1])

            # Status
            status_detail = comp.get('status') or {}
            status_type = status_detail.get('type') or {}
            status = self._map_status(status_type)

            # Build team_id → {name, logo} so we can resolve events that
            # carry only team.id.
            team_lookup = {}
            for c in competitors:
                team_obj = c.get('team') or {}
                tid = str(team_obj.get('id') or c.get('id') or '')
                if tid:
                    team_lookup[tid] = {
                        'name': team_obj.get('displayName', 'Unknown'),
                        'logo': self._team_logo_url(team_obj),
                    }

            # Build athlete_id → {jersey, headshot} from rosters
            athlete_lookup = self._build_athlete_lookup(raw_data.get('rosters') or [])

            match_events = self._extract_events_from_summary(
                raw_data.get('keyEvents') or [],
                team_lookup,
                athlete_lookup,
            )

            # Boxscore stats
            home_stats = {}
            away_stats = {}
            for team_entry in (raw_data.get('boxscore') or {}).get('teams', []) or []:
                side = team_entry.get('homeAway')
                parsed = {
                    s.get('name', ''): s.get('displayValue', '0')
                    for s in (team_entry.get('statistics') or [])
                }
                if side == 'home':
                    home_stats = parsed
                elif side == 'away':
                    away_stats = parsed

            home_team_obj = home.get('team') or {}
            away_team_obj = away.get('team') or {}
            game_info = raw_data.get('gameInfo') or {}
            venue_name = (game_info.get('venue') or {}).get('fullName', '') or \
                         (comp.get('venue') or {}).get('fullName', '')

            return {
                'match_id': match_id,
                'status': status,
                'completed': status_type.get('completed', False),
                'minute': status_detail.get('displayClock', '0'),
                'period': status_detail.get('period', 0),
                'home_team': home_team_obj.get('displayName', 'Unknown'),
                'home_score': int(home.get('score', 0) or 0),
                'home_logo': self._team_logo_url(home_team_obj),
                'home_form': home_team_obj.get('form', '') or home.get('form', ''),
                'away_team': away_team_obj.get('displayName', 'Unknown'),
                'away_score': int(away.get('score', 0) or 0),
                'away_logo': self._team_logo_url(away_team_obj),
                'away_form': away_team_obj.get('form', '') or away.get('form', ''),
                'stats': {'home': home_stats, 'away': away_stats},
                'events': match_events,
                'venue': venue_name,
                'attendance': comp.get('attendance', 0) or game_info.get('attendance', 0) or 0,
                'cached_at': time.time(),
            }

        except Exception as e:
            logger.error(f"Error processing ESPN summary for {match_id}: {e}", exc_info=True)
            return None

    def _team_logo_url(self, team_obj: Dict[str, Any]) -> str:
        """Return logo URL from a team object (summary uses logos[], scoreboard uses logo)."""
        direct = team_obj.get('logo')
        if isinstance(direct, str) and direct:
            return direct
        logos = team_obj.get('logos') or []
        if logos and isinstance(logos, list):
            first = logos[0]
            if isinstance(first, dict):
                return first.get('href', '')
        return ''

    def _map_status(self, status_type: Dict[str, Any]) -> str:
        """Map ESPN status.type → our normalized status, with state fallback."""
        name = status_type.get('name', '')
        mapped = self.STATUS_MAP.get(name, '')
        if mapped:
            return mapped
        state = (status_type.get('state') or '').lower()
        if state == 'post':
            return 'FINAL'
        if state == 'in':
            return 'IN_PLAY'
        if state == 'pre':
            return 'SCHEDULED'
        logger.warning(f"Unmapped ESPN status: name={name}, state={state}")
        return 'UNKNOWN'

    def _build_athlete_lookup(self, rosters: List[Dict[str, Any]]) -> Dict[str, Dict[str, str]]:
        """
        Build athlete_id → {jersey, headshot_url, team_name} lookup.

        Summary rosters carry the jersey + headshot that keyEvents.participants
        don't include. Without this the event embeds would miss player photos.
        """
        lookup = {}
        for roster_entry in rosters:
            team_name = (roster_entry.get('team') or {}).get('displayName', '')
            for player in roster_entry.get('roster') or []:
                athlete = player.get('athlete') or {}
                aid = str(athlete.get('id') or '')
                if not aid:
                    continue
                headshot = athlete.get('headshot')
                if isinstance(headshot, dict):
                    headshot_url = headshot.get('href', '')
                elif isinstance(headshot, str):
                    headshot_url = headshot
                else:
                    headshot_url = ''
                lookup[aid] = {
                    'jersey': str(player.get('jersey') or athlete.get('jersey') or ''),
                    'headshot': headshot_url,
                    'team_name': team_name,
                }
        return lookup

    def _enrich_athlete(self, athlete_dict: Dict[str, Any],
                        athlete_lookup: Dict[str, Dict[str, str]]) -> Dict[str, str]:
        """Return {name, jersey, headshot} for a keyEvents.participants[].athlete."""
        if not athlete_dict:
            return {'name': '', 'jersey': '', 'headshot': ''}
        aid = str(athlete_dict.get('id') or '')
        enrich = athlete_lookup.get(aid, {})
        return {
            'name': athlete_dict.get('displayName', '') or '',
            'jersey': enrich.get('jersey', ''),
            'headshot': enrich.get('headshot', ''),
        }

    def _extract_events_from_summary(
        self,
        key_events: List[Dict[str, Any]],
        team_lookup: Dict[str, Dict[str, str]],
        athlete_lookup: Dict[str, Dict[str, str]],
    ) -> List[Dict[str, Any]]:
        """
        Extract goals, cards, and substitutions from /summary keyEvents[].
        """
        out = []
        for ke in key_events:
            type_text = (ke.get('type') or {}).get('text', '')
            clock_val = (ke.get('clock') or {}).get('displayValue', '')
            participants = ke.get('participants') or []
            ke_team = ke.get('team') or {}
            team_name = ke_team.get('displayName', '')
            if not team_name:
                tid = str(ke_team.get('id') or '')
                team_name = team_lookup.get(tid, {}).get('name', '')
            tid = str(ke_team.get('id') or '')
            team_logo = team_lookup.get(tid, {}).get('logo', '')

            is_scoring = ke.get('scoringPlay', False)
            event_id = str(ke.get('id') or '')

            # Goals: "Goal", "Goal - Header", "Goal - Free Kick", "Own Goal", "Penalty"
            if is_scoring or type_text.startswith('Goal') or 'Penalty' in type_text:
                is_own_goal = 'Own Goal' in type_text
                is_penalty = type_text == 'Penalty' or 'Penalty' in type_text
                goal_type = 'OWN_GOAL' if is_own_goal else 'PENALTY_GOAL' if is_penalty else 'GOAL'
                scorer = self._enrich_athlete(
                    (participants[0].get('athlete') if participants else {}) or {},
                    athlete_lookup,
                )
                # Fall back to parsing player from text when participants are empty
                if not scorer['name']:
                    scorer['name'] = self._player_from_goal_text(ke.get('text', ''))
                out.append({
                    'id': event_id,
                    'type': goal_type,
                    'minute': clock_val,
                    'player': scorer['name'],
                    'player_headshot': scorer['headshot'],
                    'player_jersey': scorer['jersey'],
                    'team': team_name,
                    'team_logo': team_logo,
                    'detail_text': type_text,
                    'description': ke.get('text', '') or f"{type_text}. {scorer['name']} ({team_name}). {clock_val}.",
                })

            elif 'Card' in type_text:
                card_type = 'RED_CARD' if 'Red' in type_text else 'YELLOW_CARD'
                carded = self._enrich_athlete(
                    (participants[0].get('athlete') if participants else {}) or {},
                    athlete_lookup,
                )
                out.append({
                    'id': event_id,
                    'type': card_type,
                    'minute': clock_val,
                    'player': carded['name'],
                    'player_headshot': carded['headshot'],
                    'player_jersey': carded['jersey'],
                    'team': team_name,
                    'team_logo': team_logo,
                    'detail_text': type_text,
                    'description': ke.get('text', '') or f"{type_text}. {carded['name']} ({team_name}). {clock_val}.",
                })

            elif type_text in ('Substitution', 'Sub'):
                # participants: [0]=on, [1]=off (verified against ESPN data)
                on = self._enrich_athlete(
                    (participants[0].get('athlete') if participants else {}) or {},
                    athlete_lookup,
                )
                off = self._enrich_athlete(
                    (participants[1].get('athlete') if len(participants) > 1 else {}) or {},
                    athlete_lookup,
                )
                sub_text = ke.get('text', '')
                if not on['name'] or not off['name']:
                    parsed_on, parsed_off = self._parse_substitution_text(sub_text)
                    on['name'] = on['name'] or parsed_on or 'Unknown'
                    off['name'] = off['name'] or parsed_off or 'Unknown'
                out.append({
                    'id': event_id,
                    'type': 'SUBSTITUTION',
                    'minute': clock_val,
                    'player': on['name'],
                    'player_on': on['name'],
                    'player_off': off['name'],
                    'player_headshot': on['headshot'],
                    'player_jersey': on['jersey'],
                    'team': team_name,
                    'team_logo': team_logo,
                    'detail_text': type_text,
                    'description': sub_text or f"{on['name']} replaces {off['name']}. {clock_val}.",
                })

        return out

    def _player_from_goal_text(self, text: str) -> str:
        """
        Parse scorer name from ESPN goal text when participants are empty.
        Example input: "Goal! Seattle Sounders FC 1, Tigres 0. Albert Rusnák
        (Seattle Sounders FC) left footed shot from the..."
        Returns "Albert Rusnák" or '' if it can't parse.
        """
        if not text:
            return ''
        try:
            # Strip "Goal! …. " prefix if present
            if '. ' in text:
                after_score = text.split('. ', 1)[1]
            else:
                after_score = text
            # Name ends at the " (TEAM)" parenthetical
            if ' (' in after_score:
                return after_score.split(' (', 1)[0].strip()
        except Exception:
            pass
        return ''

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