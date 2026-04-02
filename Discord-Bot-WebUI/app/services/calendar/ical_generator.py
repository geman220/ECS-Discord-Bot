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
from app.models.ecs_fc import EcsFcMatch

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

            if getattr(subscription, 'include_ecs_fc_matches', True):
                self._add_ecs_fc_matches(cal, user, start_date, end_date)

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

        # Timezone (keep X-WR-TIMEZONE for backward compatibility)
        cal.add('x-wr-timezone', TIMEZONE)

        # Add VTIMEZONE component for RFC 5545 compliance
        cal.add_component(self._create_vtimezone())

        # Refresh interval (RFC 7986)
        # Format: PT{minutes}M for duration
        cal.add('refresh-interval;value=duration', f'PT{REFRESH_INTERVAL_MINUTES}M')

        # Color hint for calendar apps
        cal.add('x-apple-calendar-color', '#1E88E5')

        return cal

    @staticmethod
    def _create_vtimezone() -> 'Timezone':
        """
        Create a VTIMEZONE component for America/Los_Angeles.

        Includes both STANDARD (PST, UTC-8) and DAYLIGHT (PDT, UTC-7)
        sub-components with US DST transition rules.
        """
        from icalendar import Timezone, TimezoneDaylight, TimezoneStandard

        tz = Timezone()
        tz.add('tzid', TIMEZONE)

        # Daylight saving time (PDT): 2nd Sunday in March at 2:00 AM
        daylight = TimezoneDaylight()
        daylight.add('dtstart', datetime(1970, 3, 8, 2, 0, 0))
        daylight.add('rrule', {'freq': 'yearly', 'bymonth': 3, 'byday': '2SU'})
        daylight.add('tzoffsetfrom', timedelta(hours=-8))
        daylight.add('tzoffsetto', timedelta(hours=-7))
        daylight.add('tzname', 'PDT')
        tz.add_component(daylight)

        # Standard time (PST): 1st Sunday in November at 2:00 AM
        standard = TimezoneStandard()
        standard.add('dtstart', datetime(1970, 11, 1, 2, 0, 0))
        standard.add('rrule', {'freq': 'yearly', 'bymonth': 11, 'byday': '1SU'})
        standard.add('tzoffsetfrom', timedelta(hours=-7))
        standard.add('tzoffsetto', timedelta(hours=-8))
        standard.add('tzname', 'PST')
        tz.add_component(standard)

        return tz

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

    def _add_ecs_fc_matches(
        self,
        cal: 'Calendar',
        user: User,
        start_date: datetime,
        end_date: datetime
    ) -> None:
        """
        Add ECS FC matches to the calendar.

        Args:
            cal: The calendar to add events to
            user: The user
            start_date: Start of date range
            end_date: End of date range
        """
        player = user.player if hasattr(user, 'player') else None
        if not player or not player.teams:
            return

        team_ids = [team.id for team in player.teams]

        matches = self.session.query(EcsFcMatch).options(
            joinedload(EcsFcMatch.team)
        ).filter(
            EcsFcMatch.match_date >= start_date.date(),
            EcsFcMatch.match_date <= end_date.date(),
            EcsFcMatch.team_id.in_(team_ids),
            EcsFcMatch.status != 'CANCELLED'
        ).order_by(EcsFcMatch.match_date, EcsFcMatch.match_time).all()

        for match in matches:
            event = self._ecs_fc_match_to_event(match)
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

        # Reminders: 1 day before and 2 hours before
        self._add_alarms(event, [timedelta(days=1), timedelta(hours=2)])

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
            'plop': ['PLOP', 'Training'],
            'tournament': ['Tournament', 'Match'],
            'fundraiser': ['Fundraiser', 'Social'],
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

        # Reminders: use model fields if set, otherwise default 1 day before
        if league_event.send_reminder and league_event.reminder_days_before:
            self._add_alarms(event, [timedelta(days=league_event.reminder_days_before)])
        else:
            self._add_alarms(event, [timedelta(days=1)])

        return event

    def generate_single_event(self, event_type: str, event_id: int) -> Optional[str]:
        """
        Generate an iCal file containing a single event.

        Args:
            event_type: 'match', 'league_event', or 'ecs_fc_match'
            event_id: The event's database ID

        Returns:
            iCalendar formatted string, or None if event not found
        """
        try:
            from icalendar import Calendar

            cal = Calendar()
            cal.add('prodid', '-//ECS FC//Pub League Calendar//EN')
            cal.add('version', '2.0')
            cal.add('calscale', 'GREGORIAN')
            cal.add('method', 'PUBLISH')
            cal.add('x-wr-timezone', TIMEZONE)

            if event_type == 'match':
                match = self.session.query(Match).options(
                    joinedload(Match.home_team),
                    joinedload(Match.away_team),
                    joinedload(Match.ref)
                ).get(event_id)
                if not match:
                    return None
                event = self._match_to_event(match, player=None, is_ref_assignment=False)
                cal.add_component(event)

            elif event_type == 'league_event':
                league_event = self.session.query(LeagueEvent).get(event_id)
                if not league_event:
                    return None
                event = self._league_event_to_event(league_event)
                cal.add_component(event)

            elif event_type == 'ecs_fc_match':
                ecs_match = self.session.query(EcsFcMatch).options(
                    joinedload(EcsFcMatch.team)
                ).get(event_id)
                if not ecs_match:
                    return None
                event = self._ecs_fc_match_to_event(ecs_match)
                cal.add_component(event)

            else:
                return None

            return cal.to_ical().decode('utf-8')

        except ImportError:
            logger.error("icalendar package not installed")
            return None
        except Exception as e:
            logger.error(f"Error generating single event iCal: {e}", exc_info=True)
            return None

    def _ecs_fc_match_to_event(self, match: EcsFcMatch) -> 'Event':
        """
        Convert an EcsFcMatch to an iCal Event.

        Args:
            match: The ECS FC match to convert

        Returns:
            icalendar.Event object
        """
        from icalendar import Event

        event = Event()

        team_name = match.team.name if match.team else 'Unknown'
        opponent = match.opponent_name or 'TBD'

        event.add('uid', f'ecs-fc-match-{match.id}@ecsfc.com')

        if match.status == 'BYE':
            event.add('summary', f'{team_name} - Bye Week')
        else:
            event.add('summary', f'{team_name} vs {opponent}')

        # Date/time
        start_dt = datetime.combine(match.match_date, match.match_time)
        event.add('dtstart', start_dt)
        event.add('dtend', start_dt + timedelta(minutes=90))

        # Location
        location_parts = []
        if match.location:
            location_parts.append(match.location)
        if match.field_name:
            location_parts.append(match.field_name)
        if location_parts:
            event.add('location', ', '.join(location_parts))

        # Description
        description_parts = [f'ECS FC Match: {team_name} vs {opponent}']
        if match.is_home_match is not None:
            description_parts.append(f'{"Home" if match.is_home_match else "Away"} match')
        if match.location:
            description_parts.append(f'Location: {match.location}')
        if match.field_name:
            description_parts.append(f'Field: {match.field_name}')
        if match.notes:
            description_parts.append(f'Notes: {match.notes}')
        if match.home_shirt_color or match.away_shirt_color:
            description_parts.append(f'Kit: Home {match.home_shirt_color or "TBD"} / Away {match.away_shirt_color or "TBD"}')

        event.add('description', '\n'.join(description_parts))

        # Categories
        event.add('categories', ['ECS FC', 'Match'])

        # Status mapping
        status_map = {
            'SCHEDULED': 'TENTATIVE',
            'IN_PROGRESS': 'CONFIRMED',
            'COMPLETED': 'CONFIRMED',
            'CANCELLED': 'CANCELLED',
            'POSTPONED': 'TENTATIVE',
            'BYE': 'CONFIRMED',
        }
        event.add('status', status_map.get(match.status, 'TENTATIVE'))

        # Timestamps
        event.add('dtstamp', datetime.utcnow())
        if match.updated_at:
            event.add('last-modified', match.updated_at)

        # Reminders: 1 day before and 2 hours before
        self._add_alarms(event, [timedelta(days=1), timedelta(hours=2)])

        return event

    def _add_alarms(self, event: 'Event', triggers: List[timedelta]) -> None:
        """
        Add VALARM reminder components to an event.

        Args:
            event: The iCal event to add alarms to
            triggers: List of timedelta values for how long before the event to trigger
        """
        from icalendar import Alarm

        for trigger in triggers:
            alarm = Alarm()
            alarm.add('action', 'DISPLAY')
            alarm.add('trigger', -trigger)
            alarm.add('description', event.get('summary', 'Event reminder'))
            event.add_component(alarm)

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
