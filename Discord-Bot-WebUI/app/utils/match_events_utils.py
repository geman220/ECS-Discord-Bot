# app/utils/match_events_utils.py

import logging
from typing import Dict, List
from datetime import datetime

logger = logging.getLogger(__name__)

def event_key(event: Dict) -> str:
    """Generate a unique key for an event."""
    try:
        # Get basic event info
        event_time = event.get('clock', {}).get('displayValue', '')
        event_type = event.get('type', {}).get('text', '')
        
        # Get player info if available
        player_info = ''
        if 'athletesInvolved' in event and event['athletesInvolved']:
            player = event['athletesInvolved'][0]
            player_info = player.get('displayName', '')
            
        # Add team info to make the key more unique
        team_id = event.get('team', {}).get('id', '')
        
        # Create a more unique key by combining all elements
        key_parts = [
            event_time,
            event_type,
            player_info,
            str(team_id)
        ]
        
        # Combine into unique key
        return '-'.join(filter(None, key_parts))
    except Exception as e:
        logger.error(f"Error generating event key: {str(e)}")
        # Fallback to a timestamp-based key if there's an error
        return f"event-{datetime.now().timestamp()}"

def get_new_events(events: List[Dict], last_event_keys: List[str]) -> tuple[List[Dict], List[str]]:
    """
    Process events and return new events and updated keys.
    
    Args:
        events: List of event dictionaries
        last_event_keys: List of previously processed event keys
        
    Returns:
        tuple: (new events list, current event keys list)
    """
    new_events = []
    current_event_keys = []
    
    for event in events:
        key = event_key(event)
        current_event_keys.append(key)
        if key not in last_event_keys:
            new_events.append(event)
            
    return new_events, current_event_keys
