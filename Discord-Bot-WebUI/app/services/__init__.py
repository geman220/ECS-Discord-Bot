# app/services/__init__.py

"""
Business services layer for RSVP system.

This package contains domain services that implement business logic
with enterprise patterns for reliability and maintainability.
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

__all__ = [
    'RSVPService',
    'create_rsvp_service',
    'EventConsumer', 
    'WebSocketBroadcaster',
    'DiscordEmbedUpdater',
    'initialize_default_consumers',
    'start_all_consumers', 
    'stop_all_consumers',
    'get_consumer_health'
]