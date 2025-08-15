# app/services/__init__.py

"""
Business services layer for RSVP system and external integrations.

This package contains domain services that implement business logic
with enterprise patterns for reliability and maintainability.

New centralized services:
- ESPN Service: Centralized ESPN API access
- Discord Service: Discord bot API communication
"""

from .rsvp_service import RSVPService, create_rsvp_service
from .event_consumer import (
    EventConsumer, 
    WebSocketBroadcaster, 
    DiscordEmbedUpdater,
    initialize_default_consumers,
    start_all_consumers,
    stop_all_consumers,
    get_consumer_health
)
from .espn_service import get_espn_service, fetch_espn_data
from .discord_service import get_discord_service, create_match_thread_via_bot
from .enhanced_match_events import get_enhanced_events_service

__all__ = [
    'RSVPService',
    'create_rsvp_service',
    'EventConsumer', 
    'WebSocketBroadcaster',
    'DiscordEmbedUpdater',
    'initialize_default_consumers',
    'start_all_consumers', 
    'stop_all_consumers',
    'get_consumer_health',
    'get_espn_service',
    'fetch_espn_data',
    'get_discord_service',
    'create_match_thread_via_bot',
    'get_enhanced_events_service'
]