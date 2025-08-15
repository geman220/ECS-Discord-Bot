# app/utils/match_events_utils.py

"""
Match Events Utilities Module

This module provides helper functions to generate unique keys for match events and
to identify new events compared to a list of previously processed event keys.
"""

import logging
from typing import Dict, List, Tuple, Set
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

def event_fingerprint(event: Dict) -> str:
    """
    Generate a stable fingerprint for event deduplication.
    
    This fingerprint is designed to remain the same even when ESPN updates
    event details (like changing "Goal" to "Header Goal" or adding assists).
    It focuses on the core event identity rather than detailed descriptions.
    
    Args:
        event: A dictionary representing the event data.
        
    Returns:
        A stable fingerprint string for deduplication.
    """
    try:
        # Extract basic event timing and location
        event_time = event.get('clock', {}).get('displayValue', '')
        # Normalize event time (remove extra characters that might change)
        event_time = event_time.replace('+', '').replace("'", '').strip()
        
        # Normalize event type to core categories to handle ESPN updates
        # "Goal", "Header Goal", "Penalty Goal" all become "Goal"
        raw_event_type = event.get('type', {}).get('text', '')
        event_type = normalize_event_type(raw_event_type)
        
        # Extract primary player (scorer, card recipient, etc.)
        primary_player = ''
        if 'athletesInvolved' in event and event['athletesInvolved']:
            player = event['athletesInvolved'][0]
            primary_player = player.get('displayName', '')
            
        # Extract team identifier
        team_id = event.get('team', {}).get('id', '')
        
        # Create fingerprint using core elements that don't change
        fingerprint_parts = [
            event_time,
            event_type,
            primary_player,
            str(team_id)
        ]
        
        fingerprint = '-'.join(filter(None, fingerprint_parts))
        logger.debug(f"Generated fingerprint: {fingerprint} for event: {raw_event_type} at {event_time}")
        return fingerprint
        
    except Exception as e:
        logger.error(f"Error generating event fingerprint: {str(e)}")
        # Fallback to timestamp if error occurs
        return f"fingerprint-{datetime.now().timestamp()}"

def normalize_event_type(event_type: str) -> str:
    """
    Normalize event types to core categories for deduplication.
    
    This prevents spam when ESPN updates event details like:
    - "Goal" -> "Header Goal" -> "Goal - Header"
    - "Substitution" -> "Tactical Substitution"
    - "Yellow Card" -> "Caution"
    
    Args:
        event_type: Raw event type from ESPN
        
    Returns:
        Normalized event type for deduplication
    """
    event_type = event_type.lower().strip()
    
    # Goal variations
    if any(goal_type in event_type for goal_type in ['goal', 'header', 'penalty', 'free kick goal']):
        return 'Goal'
    
    # Card variations  
    if any(card_type in event_type for card_type in ['yellow', 'caution']):
        return 'Yellow Card'
    if any(card_type in event_type for card_type in ['red', 'sending off', 'dismissal']):
        return 'Red Card'
        
    # Substitution variations
    if 'substitution' in event_type or 'sub' in event_type:
        return 'Substitution'
    
    # Save variations
    if 'save' in event_type or 'stop' in event_type:
        return 'Save'
        
    # VAR variations
    if any(var_type in event_type for var_type in ['var', 'video', 'review']):
        return 'VAR Review'
        
    # Added time variations
    if any(time_type in event_type for time_type in ['added time', 'stoppage', 'additional']):
        return 'Added Time'
    
    # Return original if no normalization needed
    return event_type.title()


def get_new_events(events: List[Dict], last_event_keys: List[str]) -> Tuple[List[Dict], List[str]]:
    """
    Process a list of events and determine which ones are new with enhanced deduplication.

    Uses both traditional event keys and fingerprints to prevent spam from ESPN API updates.
    The fingerprint system prevents duplicate reports when ESPN updates event details
    (like changing "Goal" to "Header Goal" or adding assist information).

    Args:
        events: A list of event dictionaries.
        last_event_keys: A list of keys corresponding to events that have been processed before.

    Returns:
        A tuple with two elements:
          1. A list of new event dictionaries (deduplicated).
          2. A list of keys corresponding to all events in the current list.
    """
    new_events = []
    current_event_keys = []
    seen_fingerprints = set()
    
    # Extract fingerprints from last_event_keys for deduplication
    last_fingerprints = set()
    for key in last_event_keys:
        # Check if this key contains a fingerprint (new format: key|fingerprint)
        if '|' in key:
            _, fingerprint = key.split('|', 1)
            last_fingerprints.add(fingerprint)
    
    for event in events:
        key = event_key(event)
        fingerprint = event_fingerprint(event)
        
        # Create combined key with fingerprint for future tracking
        combined_key = f"{key}|{fingerprint}"
        current_event_keys.append(combined_key)
        
        # Check for duplicates using fingerprint logic
        is_duplicate = (
            fingerprint in last_fingerprints or 
            fingerprint in seen_fingerprints or
            key in last_event_keys  # Backward compatibility
        )
        
        if not is_duplicate:
            new_events.append(event)
            seen_fingerprints.add(fingerprint)
            logger.debug(f"New event detected: {event.get('type', {}).get('text', 'Unknown')} at {event.get('clock', {}).get('displayValue', 'N/A')} (fingerprint: {fingerprint})")
        else:
            logger.debug(f"Duplicate event filtered: {event.get('type', {}).get('text', 'Unknown')} at {event.get('clock', {}).get('displayValue', 'N/A')} (fingerprint: {fingerprint})")
            
    logger.info(f"Event processing: {len(events)} total, {len(new_events)} new, {len(events) - len(new_events)} duplicates filtered")
    return new_events, current_event_keys