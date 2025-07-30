# app/events/__init__.py

"""
Event-driven architecture for RSVP system.

This module provides enterprise-grade event handling with:
- Durable event streams via Redis
- Idempotent operations
- Circuit breaker patterns
- Dead letter queues
- Distributed tracing
"""

from .rsvp_events import RSVPEvent, RSVPEventType, RSVPSource, RSVPSyncEvent
from .event_publisher import EventPublisher, get_event_publisher

__all__ = [
    'RSVPEvent',
    'RSVPEventType',
    'RSVPSource',
    'RSVPSyncEvent',
    'EventPublisher',
    'get_event_publisher'
]