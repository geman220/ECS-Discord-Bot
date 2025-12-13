# app/dto/calendar_dto.py

"""
Calendar Data Transfer Objects

Provides DTOs for calendar API responses including conversion functions
for Match and LeagueEvent models to FullCalendar-compatible format.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from .base import BaseDTO


# Color constants for calendar events
MATCH_COLORS = {
    'Premier': '#1976d2',      # Blue
    'Classic': '#388e3c',      # Green
    'ECS FC': '#7b1fa2',       # Purple
    'default': '#0288d1',      # Light Blue
}

LEAGUE_EVENT_COLORS = {
    'party': '#9c27b0',        # Purple
    'meeting': '#ff9800',      # Orange
    'social': '#e91e63',       # Pink
    'training': '#4caf50',     # Green
    'tournament': '#f44336',   # Red
    'other': '#607d8b',        # Blue-grey
}


@dataclass
class FullCalendarEvent(BaseDTO):
    """
    FullCalendar-compatible event format.

    This DTO maps to FullCalendar's event object specification.
    See: https://fullcalendar.io/docs/event-object
    """
    id: str
    title: str
    start: str  # ISO datetime string
    end: Optional[str] = None
    allDay: bool = False
    color: Optional[str] = None
    textColor: Optional[str] = None
    editable: bool = False
    url: Optional[str] = None
    extendedProps: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MatchExtendedProps(BaseDTO):
    """Extended properties for match events."""
    type: str = 'match'
    matchId: int = 0
    homeTeamId: int = 0
    homeTeamName: str = ''
    awayTeamId: int = 0
    awayTeamName: str = ''
    location: str = ''
    division: str = ''
    refId: Optional[int] = None
    refName: Optional[str] = None
    homeScore: Optional[int] = None
    awayScore: Optional[int] = None
    reported: bool = False
    weekType: str = 'REGULAR'


@dataclass
class LeagueEventExtendedProps(BaseDTO):
    """Extended properties for league events."""
    type: str = 'league_event'
    eventId: int = 0
    eventType: str = 'other'
    description: Optional[str] = None
    location: Optional[str] = None
    leagueId: Optional[int] = None
    seasonId: Optional[int] = None
    notifyDiscord: bool = False


def match_to_fullcalendar(match, editable: bool = False) -> Dict[str, Any]:
    """
    Convert a Match model to FullCalendar event format.

    Args:
        match: The Match model instance
        editable: Whether the event should be editable

    Returns:
        Dictionary in FullCalendar event format
    """
    # Build title
    home_team = match.home_team.name if match.home_team else 'TBD'
    away_team = match.away_team.name if match.away_team else 'TBD'
    title = f'{home_team} vs {away_team}'

    # Determine color based on division
    division = ''
    if match.home_team and hasattr(match.home_team, 'league') and match.home_team.league:
        division = match.home_team.league.name if hasattr(match.home_team.league, 'name') else ''

    color = MATCH_COLORS.get(division, MATCH_COLORS['default'])

    # Build start/end datetime
    start_dt = datetime.combine(match.date, match.time)
    end_dt = start_dt + timedelta(minutes=90)  # 90 minute match

    # Build extended props
    extended_props = {
        'type': 'match',
        'matchId': match.id,
        'homeTeamId': match.home_team_id,
        'homeTeamName': home_team,
        'awayTeamId': match.away_team_id,
        'awayTeamName': away_team,
        'location': match.location or '',
        'division': division,
        'refId': match.ref_id,
        'refName': match.ref.name if match.ref else None,
        'homeScore': match.home_team_score,
        'awayScore': match.away_team_score,
        'reported': match.reported if hasattr(match, 'reported') else False,
        'weekType': match.week_type or 'REGULAR',
    }

    return {
        'id': f'match-{match.id}',
        'title': title,
        'start': start_dt.isoformat(),
        'end': end_dt.isoformat(),
        'allDay': False,
        'color': color,
        'editable': False,  # Matches are never editable from calendar
        'extendedProps': extended_props,
    }


def league_event_to_fullcalendar(event, editable: bool = False) -> Dict[str, Any]:
    """
    Convert a LeagueEvent model to FullCalendar event format.

    Args:
        event: The LeagueEvent model instance
        editable: Whether the event should be editable

    Returns:
        Dictionary in FullCalendar event format
    """
    # Get color based on event type
    color = LEAGUE_EVENT_COLORS.get(event.event_type, LEAGUE_EVENT_COLORS['other'])

    # Build start/end datetime
    start = event.start_datetime.isoformat() if event.start_datetime else None

    end = None
    if event.end_datetime:
        end = event.end_datetime.isoformat()
    elif not event.is_all_day:
        # Default to 2 hours if no end time specified
        end = (event.start_datetime + timedelta(hours=2)).isoformat() if event.start_datetime else None

    # Build extended props
    extended_props = {
        'type': 'league_event',
        'eventId': event.id,
        'eventType': event.event_type,
        'description': event.description,
        'location': event.location,
        'leagueId': event.league_id,
        'seasonId': event.season_id,
        'notifyDiscord': event.notify_discord,
        'isActive': event.is_active,
    }

    return {
        'id': f'event-{event.id}',
        'title': event.title,
        'start': start,
        'end': end,
        'allDay': event.is_all_day,
        'color': color,
        'editable': editable,
        'extendedProps': extended_props,
    }


def events_to_fullcalendar(
    matches: List,
    league_events: List,
    matches_editable: bool = False,
    events_editable: bool = False
) -> List[Dict[str, Any]]:
    """
    Convert lists of matches and league events to FullCalendar format.

    Args:
        matches: List of Match model instances
        league_events: List of LeagueEvent model instances
        matches_editable: Whether matches should be editable
        events_editable: Whether league events should be editable

    Returns:
        Combined list of FullCalendar events
    """
    result = []

    for match in matches:
        result.append(match_to_fullcalendar(match, editable=matches_editable))

    for event in league_events:
        result.append(league_event_to_fullcalendar(event, editable=events_editable))

    # Sort by start date
    result.sort(key=lambda x: x.get('start', ''))

    return result
