# app/services/calendar/ical_generator.py

"""
iCal Generator Service

Generates RFC 5545 compliant iCalendar feeds for calendar subscriptions.
"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy.orm import Session, joinedload

from app.models import (
    User, Player, Match, LeagueEvent, CalendarSubscription
)

logger = logging.getLogger(__name__)

# Pacific timezone offset (standard/daylight saving handled by client)
TIMEZONE = 'America/Los_Angeles'

# Refresh interval in minutes (how often clients should check for updates)
REFRESH_INTERVAL_MINUTES = 60


class ICalGenerator:
    """
    Service for generating iCal feeds.

    Creates RFC 5545 compliant calendars with matches and league events
    personalized for each user based on their subscription preferences.
    """

    def __init__(self, session: Session):
        """
        Initialize the iCal generator.

        Args:
            session: SQLAlchemy database session
        """
        self.session = session

    def generate_feed(
        self,
        subscription: CalendarSubscription,
        days_back: int = 7,
        days_forward: int = 180
    ) -> str:
        """
        Generate a complete iCal feed for a subscription.

        Args:
            subscription: The calendar subscription
            days_back: Number of days in the past to include
            days_forward: Number of days in the future to include

        Returns:
            iCalendar formatted string
        """
        try:
            # Import icalendar here to handle optional dependency gracefully
            from icalendar import Calendar, Event, vText

            # Get user and their player record
            user = self.session.query(User).options(
                joinedload(User.player).joinedload(Player.teams)
            ).get(subscription.user_id)

            if not user:
                logger.error(f"User {subscription.user_id} not found for subscription")
                return self._create_error_feed("User not found")

            # Create calendar
            cal = self._create_calendar_header(user)

            # Calculate date range
            now = datetime.utcnow()
            start_date = now - timedelta(days=days_back)
            end_date = now + timedelta(days=days_forward)

            # Add events based on preferences
            if subscription.include_team_matches:
                self._add_team_matches(cal, user, start_date, end_date)

            if subscription.include_ref_assignments:
                self._add_ref_assignments(cal, user, start_date, end_date)

            if subscription.include_league_events:
                self._add_league_events(cal, user, start_date, end_date)

            return cal.to_ical().decode('utf-8')

        except ImportError:
            logger.error("icalendar package not installed")
            return self._create_error_feed("Calendar generation unavailable")
        except Exception as e:
            logger.error(f"Error generating iCal feed: {e}", exc_info=True)
            return self._create_error_feed("Error generating calendar")

    def _create_calendar_header(self, user: User) -> 'Calendar':
        """
        Create the calendar with proper headers.

        Args:
            user: The user the calendar is for

        Returns:
            icalendar.Calendar object
        """
        from icalendar import Calendar

        cal = Calendar()

        # Required iCalendar properties (RFC 5545)
        cal.add('prodid', '-//ECS FC//Pub League Calendar//EN')
        cal.add('version', '2.0')
        cal.add('calscale', 'GREGORIAN')
        cal.add('method', 'PUBLISH')

        # Calendar name and description
        cal.add('x-wr-calname', f'ECS FC - {user.username}')
        cal.add('x-wr-caldesc', 'Your personalized ECS FC schedule')

        # Timezone
        cal.add('x-wr-timezone', TIMEZONE)

        # Refresh interval (RFC 7986)
        # Format: PT{minutes}M for duration
        cal.add('refresh-interval;value=duration', f'PT{REFRESH_INTERVAL_MINUTES}M')

        # Color hint for calendar apps
        cal.add('x-apple-calendar-color', '#1E88E5')

        return cal

    def _add_team_matches(
        self,
        cal: 'Calendar',
        user: User,
        start_date: datetime,
        end_date: datetime
    ) -> None:
        """
        Add user's team matches to the calendar.

        Args:
            cal: The calendar to add events to
            user: The user
            start_date: Start of date range
            end_date: End of date range
        """
        from icalendar import Event

        player = user.player if hasattr(user, 'player') else None
        if not player or not player.teams:
            return

        team_ids = [team.id for team in player.teams]

        matches = self.session.query(Match).options(
            joinedload(Match.home_team),
            joinedload(Match.away_team),
            joinedload(Match.ref)
        ).filter(
            Match.date >= start_date.date(),
            Match.date <= end_date.date(),
            (Match.home_team_id.in_(team_ids)) | (Match.away_team_id.in_(team_ids))
        ).order_by(Match.date, Match.time).all()

        for match in matches:
            event = self._match_to_event(match, player, is_ref_assignment=False)
            cal.add_component(event)

    def _add_ref_assignments(
        self,
        cal: 'Calendar',
        user: User,
        start_date: datetime,
        end_date: datetime
    ) -> None:
        """
        Add referee assignments to the calendar.

        Args:
            cal: The calendar to add events to
            user: The user (must be a referee)
            start_date: Start of date range
            end_date: End of date range
        """
        from icalendar import Event

        player = user.player if hasattr(user, 'player') else None
        if not player or not player.is_ref:
            return

        # Get matches where user is assigned as ref
        # Exclude matches where user is on one of the teams (already added)
        team_ids = [team.id for team in player.teams] if player.teams else []

        query = self.session.query(Match).options(
            joinedload(Match.home_team),
            joinedload(Match.away_team)
        ).filter(
            Match.date >= start_date.date(),
            Match.date <= end_date.date(),
            Match.ref_id == player.id
        )

        # Exclude team matches (already included via include_team_matches)
        if team_ids:
            query = query.filter(
                ~Match.home_team_id.in_(team_ids),
                ~Match.away_team_id.in_(team_ids)
            )

        matches = query.order_by(Match.date, Match.time).all()

        for match in matches:
            event = self._match_to_event(match, player, is_ref_assignment=True)
            cal.add_component(event)

    def _add_league_events(
        self,
        cal: 'Calendar',
        user: User,
        start_date: datetime,
        end_date: datetime
    ) -> None:
        """
        Add league events to the calendar.

        Args:
            cal: The calendar to add events to
            user: The user
            start_date: Start of date range
            end_date: End of date range
        """
        from icalendar import Event

        player = user.player if hasattr(user, 'player') else None
        league_ids = []
        if player and player.teams:
            league_ids = list(set(
                team.league_id for team in player.teams
                if team.league_id is not None
            ))

        # Query events - league-wide (league_id IS NULL) or user's leagues
        query = self.session.query(LeagueEvent).filter(
            LeagueEvent.is_active == True,
            LeagueEvent.start_datetime >= start_date,
            LeagueEvent.start_datetime <= end_date
        )

        if league_ids:
            query = query.filter(
                (LeagueEvent.league_id.is_(None)) |
                (LeagueEvent.league_id.in_(league_ids))
            )
        else:
            query = query.filter(LeagueEvent.league_id.is_(None))

        events = query.order_by(LeagueEvent.start_datetime).all()

        for league_event in events:
            event = self._league_event_to_event(league_event)
            cal.add_component(event)

    def _match_to_event(
        self,
        match: Match,
        player: Player,
        is_ref_assignment: bool = False
    ) -> 'Event':
        """
        Convert a Match to an iCal Event.

        Args:
            match: The match to convert
            player: The user's player record
            is_ref_assignment: Whether this is a ref assignment

        Returns:
            icalendar.Event object
        """
        from icalendar import Event

        event = Event()

        home_team = match.home_team.name if match.home_team else 'TBD'
        away_team = match.away_team.name if match.away_team else 'TBD'

        # Unique ID
        prefix = 'ref-' if is_ref_assignment else 'match-'
        event.add('uid', f'{prefix}{match.id}@ecsfc.com')

        # Title
        if is_ref_assignment:
            event.add('summary', f'[REF] {home_team} vs {away_team}')
        else:
            event.add('summary', f'{home_team} vs {away_team}')

        # Date/time
        start_dt = datetime.combine(match.date, match.time)
        if is_ref_assignment:
            # Refs should arrive early
            start_dt = start_dt - timedelta(minutes=15)
            event.add('dtstart', start_dt)
            event.add('dtend', start_dt + timedelta(minutes=105))
        else:
            event.add('dtstart', start_dt)
            event.add('dtend', start_dt + timedelta(minutes=90))

        # Location
        if match.location:
            event.add('location', match.location)

        # Description
        description_parts = []
        if is_ref_assignment:
            description_parts.append('REFEREE ASSIGNMENT')
            description_parts.append('Please arrive 15 minutes early.')
            description_parts.append('')

        description_parts.append(f'Match: {home_team} vs {away_team}')

        if match.location:
            description_parts.append(f'Location: {match.location}')

        if match.ref and not is_ref_assignment:
            description_parts.append(f'Referee: {match.ref.name}')

        if match.home_team_score is not None and match.away_team_score is not None:
            description_parts.append(f'Score: {match.home_team_score} - {match.away_team_score}')

        event.add('description', '\n'.join(description_parts))

        # Categories
        categories = ['Match', 'ECS FC']
        if is_ref_assignment:
            categories.insert(0, 'Referee')
        event.add('categories', categories)

        # Status
        if match.reported:
            event.add('status', 'CONFIRMED')
        else:
            event.add('status', 'TENTATIVE')

        # Timestamps
        event.add('dtstamp', datetime.utcnow())
        if match.updated_at:
            event.add('last-modified', match.updated_at)

        return event

    def _league_event_to_event(self, league_event: LeagueEvent) -> 'Event':
        """
        Convert a LeagueEvent to an iCal Event.

        Args:
            league_event: The league event to convert

        Returns:
            icalendar.Event object
        """
        from icalendar import Event

        event = Event()

        event.add('uid', f'event-{league_event.id}@ecsfc.com')
        event.add('summary', league_event.title)

        # Date/time
        if league_event.is_all_day:
            event.add('dtstart', league_event.start_datetime.date())
            if league_event.end_datetime:
                event.add('dtend', league_event.end_datetime.date())
        else:
            event.add('dtstart', league_event.start_datetime)
            if league_event.end_datetime:
                event.add('dtend', league_event.end_datetime)
            else:
                # Default to 2 hour event
                event.add('dtend', league_event.start_datetime + timedelta(hours=2))

        # Location
        if league_event.location:
            event.add('location', league_event.location)

        # Description
        if league_event.description:
            event.add('description', league_event.description)

        # Categories based on event type
        type_categories = {
            'party': ['Social', 'Party'],
            'meeting': ['Meeting'],
            'social': ['Social'],
            'training': ['Training'],
            'tournament': ['Tournament', 'Match'],
            'other': ['Event'],
        }
        categories = type_categories.get(league_event.event_type, ['Event'])
        categories.append('ECS FC')
        event.add('categories', categories)

        # Status
        event.add('status', 'CONFIRMED')

        # Timestamps
        event.add('dtstamp', datetime.utcnow())
        if league_event.updated_at:
            event.add('last-modified', league_event.updated_at)

        return event

    def _create_error_feed(self, message: str) -> str:
        """
        Create an error calendar with a single error event.

        Args:
            message: Error message to display

        Returns:
            iCalendar formatted string
        """
        try:
            from icalendar import Calendar, Event

            cal = Calendar()
            cal.add('prodid', '-//ECS FC//Error//EN')
            cal.add('version', '2.0')
            cal.add('x-wr-calname', 'ECS FC - Error')

            event = Event()
            event.add('uid', f'error-{datetime.utcnow().timestamp()}@ecsfc.com')
            event.add('summary', f'Calendar Error: {message}')
            event.add('dtstart', datetime.utcnow())
            event.add('dtend', datetime.utcnow() + timedelta(hours=1))
            event.add('description', 'There was an error generating your calendar. Please try again later or contact support.')
            event.add('dtstamp', datetime.utcnow())

            cal.add_component(event)
            return cal.to_ical().decode('utf-8')

        except ImportError:
            # Fallback if icalendar is not available
            return f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//ECS FC//Error//EN
X-WR-CALNAME:ECS FC - Error
BEGIN:VEVENT
UID:error@ecsfc.com
SUMMARY:Calendar Error: {message}
DTSTART:{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}
DTEND:{(datetime.utcnow() + timedelta(hours=1)).strftime('%Y%m%dT%H%M%SZ')}
DESCRIPTION:There was an error generating your calendar.
END:VEVENT
END:VCALENDAR"""


def create_ical_generator(session: Session) -> ICalGenerator:
    """
    Factory function to create an ICalGenerator instance.

    Args:
        session: SQLAlchemy database session

    Returns:
        Configured ICalGenerator instance
    """
    return ICalGenerator(session)
