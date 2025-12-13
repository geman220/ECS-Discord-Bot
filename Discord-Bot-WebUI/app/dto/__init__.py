# app/dto/__init__.py

"""
Data Transfer Objects (DTOs) for the application.

DTOs provide a clean interface for data transfer between layers,
with built-in serialization and validation support.
"""

from app.dto.base import BaseDTO, APIResponse, PaginatedResponse, ErrorResponse
from app.dto.calendar_dto import (
    FullCalendarEvent,
    MatchExtendedProps,
    LeagueEventExtendedProps,
    match_to_fullcalendar,
    league_event_to_fullcalendar,
    events_to_fullcalendar,
    MATCH_COLORS,
    LEAGUE_EVENT_COLORS,
)

__all__ = [
    'BaseDTO',
    'APIResponse',
    'PaginatedResponse',
    'ErrorResponse',
    # Calendar DTOs
    'FullCalendarEvent',
    'MatchExtendedProps',
    'LeagueEventExtendedProps',
    'match_to_fullcalendar',
    'league_event_to_fullcalendar',
    'events_to_fullcalendar',
    'MATCH_COLORS',
    'LEAGUE_EVENT_COLORS',
]
