# app/services/calendar/__init__.py

"""
Calendar Services Package

This package provides services for the enhanced calendar system:
- VisibilityService: Role-based event filtering
- LeagueEventService: League event CRUD operations
- SubscriptionService: iCal subscription token management
- ICalGenerator: RFC 5545 iCal feed generation
"""

from .visibility_service import VisibilityService, create_visibility_service
from .league_event_service import LeagueEventService, create_league_event_service
from .subscription_service import SubscriptionService, create_subscription_service
from .ical_generator import ICalGenerator, create_ical_generator

__all__ = [
    'VisibilityService',
    'create_visibility_service',
    'LeagueEventService',
    'create_league_event_service',
    'SubscriptionService',
    'create_subscription_service',
    'ICalGenerator',
    'create_ical_generator',
]
