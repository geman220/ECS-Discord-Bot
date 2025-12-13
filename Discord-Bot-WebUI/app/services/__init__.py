# app/services/__init__.py

"""
Business services layer for the application.

This package contains domain services that implement business logic
with enterprise patterns for reliability and maintainability.

Centralized services:
- Base Service: Foundation class for all services
- ESPN Service: Centralized ESPN API access
- Discord Service: Discord bot API communication
- RSVP Service: RSVP domain logic
- Mobile Services: Mobile API business logic
"""

from .base_service import (
    BaseService,
    ServiceResult,
    ServiceError,
    ValidationError,
    NotFoundError,
    AuthorizationError,
    ConflictError,
)
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
from .ai_commentary import get_ai_commentary_service, generate_ai_commentary

# Calendar services
from .calendar import (
    VisibilityService,
    create_visibility_service,
    LeagueEventService,
    create_league_event_service,
    SubscriptionService,
    create_subscription_service,
    ICalGenerator,
    create_ical_generator,
)

__all__ = [
    # Base service classes
    'BaseService',
    'ServiceResult',
    'ServiceError',
    'ValidationError',
    'NotFoundError',
    'AuthorizationError',
    'ConflictError',
    # RSVP
    'RSVPService',
    'create_rsvp_service',
    # Event consumers
    'EventConsumer',
    'WebSocketBroadcaster',
    'DiscordEmbedUpdater',
    'initialize_default_consumers',
    'start_all_consumers',
    'stop_all_consumers',
    'get_consumer_health',
    # ESPN
    'get_espn_service',
    'fetch_espn_data',
    # Discord
    'get_discord_service',
    'create_match_thread_via_bot',
    # Enhanced events
    'get_enhanced_events_service',
    # AI
    'get_ai_commentary_service',
    'generate_ai_commentary',
    # Calendar
    'VisibilityService',
    'create_visibility_service',
    'LeagueEventService',
    'create_league_event_service',
    'SubscriptionService',
    'create_subscription_service',
    'ICalGenerator',
    'create_ical_generator',
]