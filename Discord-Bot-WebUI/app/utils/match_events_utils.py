# app/utils/match_events_utils.py

"""
Match Events Utilities Module

This module provides helper functions to generate unique keys for match events and
to identify new events compared to a list of previously processed event keys.
"""

import logging
from typing import Dict, List, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)


def event_key(event: Dict) -> str:
    """
    Generate a unique key for a given event.

    The key is constructed using the event's clock display value, event type text,
    the display name of the first athlete involved (if available), and the team ID.
    If any error occurs during key generation, a fallback timestamp-based key is returned.

    Args:
        event: A dictionary representing the event data.

    Returns:
        A unique key string for the event.
    """
    try:
        # Extract basic event details.
        event_time = event.get('clock', {}).get('displayValue', '')
        event_type = event.get('type', {}).get('text', '')
        
        # Extract player information if available.
        player_info = ''
        if 'athletesInvolved' in event and event['athletesInvolved']:
            player = event['athletesInvolved'][0]
            player_info = player.get('displayName', '')
            
        # Extract team identifier to further distinguish the event.
        team_id = event.get('team', {}).get('id', '')
        
        # Combine elements into a unique key.
        key_parts = [
            event_time,
            event_type,
            player_info,
            str(team_id)
        ]
        
        return '-'.join(filter(None, key_parts))
    except Exception as e:
        logger.error(f"Error generating event key: {str(e)}")
        # Fallback to a timestamp-based key if an error occurs.
        return f"event-{datetime.now().timestamp()}"


def get_new_events(events: List[Dict], last_event_keys: List[str]) -> Tuple[List[Dict], List[str]]:
    """
    Process a list of events and determine which ones are new.

    Compares each event's unique key to a list of previously processed keys.
    Returns a tuple containing:
      - A list of events that are not in the previous keys.
      - A list of the current keys from the provided events.

    Args:
        events: A list of event dictionaries.
        last_event_keys: A list of keys corresponding to events that have been processed before.

    Returns:
        A tuple with two elements:
          1. A list of new event dictionaries.
          2. A list of keys corresponding to all events in the current list.
    """
    new_events = []
    current_event_keys = []
    
    for event in events:
        key = event_key(event)
        current_event_keys.append(key)
        if key not in last_event_keys:
            new_events.append(event)
            
    return new_events, current_event_keys