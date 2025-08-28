"""
Synchronous ESPN API client.

Pure synchronous implementation to replace async ESPN calls in Celery tasks.
Eliminates ThreadPoolExecutor usage that causes queue buildup.
"""

import logging
import requests
from typing import Dict, Any, Optional, List
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


class SyncESPNClient:
    """
    Synchronous ESPN API client for Celery tasks.
    
    Replaces async ESPN service calls with synchronous requests library
    to prevent ThreadPoolExecutor resource exhaustion.
    """
    
    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self.session = self._create_session()
        self.base_url = "https://site.api.espn.com/apis/site/v2/sports/soccer"
    
    def _create_session(self) -> requests.Session:
        """Create a requests session with retry logic."""
        session = requests.Session()
        
        # Configure retries for network errors
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[502, 503, 504],
            allowed_methods=["GET", "POST"]
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        return session
    
    def get_match_data(self, match_id: str, competition: str = "usa.1") -> Optional[Dict[str, Any]]:
        """
        Get match data from ESPN API using synchronous HTTP call.
        
        Args:
            match_id: ESPN match ID
            competition: Competition identifier (default: usa.1 for MLS)
            
        Returns:
            Dictionary with match data or None if not found.
        """
        try:
            # Construct ESPN API URL
            url = f"{self.base_url}/{competition}/scoreboard/{match_id}"
            
            logger.info(f"Fetching ESPN match data for {match_id} (synchronous)")
            
            response = self.session.get(url, timeout=self.timeout)
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"ESPN match data retrieved successfully for {match_id}")
                
                # Extract relevant match data
                return self._parse_match_data(data)
            else:
                logger.warning(f"ESPN API returned {response.status_code} for match {match_id}")
                return None
                
        except requests.Timeout:
            logger.error(f"ESPN API call timed out after {self.timeout} seconds")
            return None
        except Exception as e:
            logger.error(f"Error fetching ESPN match data: {str(e)}")
            return None
    
    def _parse_match_data(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse ESPN API response into standardized match data format.
        
        Args:
            raw_data: Raw ESPN API response
            
        Returns:
            Parsed match data dictionary.
        """
        try:
            # This is a simplified parser - adjust based on actual ESPN API structure
            event = raw_data.get('event', raw_data.get('events', [{}])[0] if 'events' in raw_data else {})
            competition = event.get('competition', {})
            competitors = competition.get('competitors', [])
            
            home_team = competitors[0] if len(competitors) > 0 else {}
            away_team = competitors[1] if len(competitors) > 1 else {}
            
            return {
                'match_id': event.get('id'),
                'status': event.get('status', {}).get('type', {}).get('name', 'UNKNOWN'),
                'home_team': home_team.get('team', {}).get('displayName', 'Unknown'),
                'away_team': away_team.get('team', {}).get('displayName', 'Unknown'),
                'home_score': home_team.get('score', 0),
                'away_score': away_team.get('score', 0),
                'venue': event.get('venue', {}).get('fullName', 'Unknown Venue'),
                'date_time': event.get('date'),
                'competition': competition.get('name', 'Unknown Competition'),
                'events': self._extract_events(event)
            }
        except Exception as e:
            logger.error(f"Error parsing ESPN match data: {e}")
            return {
                'match_id': raw_data.get('id', 'unknown'),
                'status': 'PARSE_ERROR',
                'error': str(e)
            }
    
    def _extract_events(self, event_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Extract match events (goals, cards, etc.) from ESPN data.
        
        Args:
            event_data: ESPN event data
            
        Returns:
            List of parsed events.
        """
        events = []
        
        try:
            # Extract from plays or timeline
            plays = event_data.get('plays', [])
            for play in plays:
                event = {
                    'type': play.get('type', {}).get('text', 'unknown'),
                    'minute': play.get('clock', {}).get('displayValue', '0'),
                    'team': play.get('team', {}).get('displayName', ''),
                    'player': play.get('participants', [{}])[0].get('athlete', {}).get('displayName', '') if play.get('participants') else '',
                    'description': play.get('text', '')
                }
                events.append(event)
        except Exception as e:
            logger.error(f"Error extracting events: {e}")
        
        return events
    
    def close(self):
        """Close the session."""
        if self.session:
            self.session.close()


# Global client instance for reuse
_espn_client: Optional[SyncESPNClient] = None


def get_sync_espn_client() -> SyncESPNClient:
    """
    Get or create a global synchronous ESPN client.
    
    Returns:
        SyncESPNClient instance.
    """
    global _espn_client
    if _espn_client is None:
        _espn_client = SyncESPNClient()
    return _espn_client


def process_live_match_updates_sync(
    match_id: str,
    thread_id: str,
    competition: str,
    last_event_keys: List[str] = None
) -> tuple[bool, List[str]]:
    """
    Synchronous version of process_live_match_updates.
    
    Args:
        match_id: ESPN match ID
        thread_id: Discord thread ID
        competition: Competition identifier
        last_event_keys: Previously processed event keys
        
    Returns:
        Tuple of (match_ended, current_event_keys)
    """
    try:
        from app.utils.sync_discord_client import get_sync_discord_client
        
        espn_client = get_sync_espn_client()
        discord_client = get_sync_discord_client()
        
        # Get match data
        match_data = espn_client.get_match_data(match_id, competition)
        if not match_data:
            logger.warning(f"No match data found for {match_id}")
            return False, last_event_keys or []
        
        # Check if match ended
        match_ended = match_data.get('status') in ['FINAL', 'COMPLETED', 'FINISHED']
        
        # Process new events
        current_event_keys = []
        events = match_data.get('events', [])
        
        for event in events:
            # Create unique event key
            event_key = f"{event.get('type')}_{event.get('minute')}_{hash(str(event))}"
            current_event_keys.append(event_key)
            
            # Check if this is a new event
            if last_event_keys and event_key not in last_event_keys:
                # Post update to Discord (simplified)
                logger.info(f"New event detected: {event_key}")
                # discord_client.post_match_update(thread_id, event)
        
        return match_ended, current_event_keys
        
    except Exception as e:
        logger.error(f"Error processing live match updates: {e}")
        return False, last_event_keys or []