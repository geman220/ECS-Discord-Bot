# app/services/calendar/league_event_service.py

"""
League Event Service

Handles CRUD operations for league events (non-match calendar events).
"""

import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

from sqlalchemy.orm import Session

from app.services.base_service import BaseService, ServiceResult, ValidationError, NotFoundError
from app.models import LeagueEvent, User

logger = logging.getLogger(__name__)


class LeagueEventService(BaseService):
    """
    Service for managing league events.

    Provides CRUD operations for non-match calendar events
    such as parties, meetings, training sessions, etc.
    """

    # Valid event types
    VALID_EVENT_TYPES = {'party', 'meeting', 'social', 'training', 'tournament', 'other'}

    def __init__(self, session: Session):
        """
        Initialize the league event service.

        Args:
            session: SQLAlchemy database session
        """
        super().__init__(session)

    def create_event(
        self,
        title: str,
        start_datetime: datetime,
        created_by: int,
        description: Optional[str] = None,
        event_type: str = 'other',
        location: Optional[str] = None,
        end_datetime: Optional[datetime] = None,
        is_all_day: bool = False,
        season_id: Optional[int] = None,
        league_id: Optional[int] = None,
        notify_discord: bool = False
    ) -> ServiceResult[LeagueEvent]:
        """
        Create a new league event.

        Args:
            title: Event title (required)
            start_datetime: Event start date/time (required)
            created_by: User ID of the creator (required)
            description: Optional event description
            event_type: Type of event (party, meeting, etc.)
            location: Optional event location
            end_datetime: Optional event end date/time
            is_all_day: Whether this is an all-day event
            season_id: Optional season association
            league_id: Optional league association (null = all leagues)
            notify_discord: Whether to announce in Discord

        Returns:
            ServiceResult containing the created LeagueEvent
        """
        self._log_operation_start('create_event', title=title)

        try:
            # Validate required fields
            self._validate_required(title, 'title')

            if not start_datetime:
                raise ValidationError('start_datetime is required', 'MISSING_START_DATETIME')

            # Validate event type
            if event_type not in self.VALID_EVENT_TYPES:
                raise ValidationError(
                    f'Invalid event_type. Must be one of: {", ".join(self.VALID_EVENT_TYPES)}',
                    'INVALID_EVENT_TYPE'
                )

            # Validate end_datetime is after start_datetime
            if end_datetime and end_datetime < start_datetime:
                raise ValidationError(
                    'end_datetime must be after start_datetime',
                    'INVALID_DATE_RANGE'
                )

            # Create the event
            event = LeagueEvent(
                title=title.strip(),
                description=description.strip() if description else None,
                event_type=event_type,
                location=location.strip() if location else None,
                start_datetime=start_datetime,
                end_datetime=end_datetime,
                is_all_day=is_all_day,
                season_id=season_id,
                league_id=league_id,
                notify_discord=notify_discord,
                created_by=created_by,
                is_active=True
            )

            self.session.add(event)
            self._commit()

            self._log_operation_success('create_event', event_id=event.id)
            return ServiceResult.ok(event, 'Event created successfully')

        except ValidationError as e:
            self._log_operation_error('create_event', e)
            return ServiceResult.fail(e.message, e.error_code)
        except Exception as e:
            self._log_operation_error('create_event', e)
            self._rollback()
            return ServiceResult.fail(str(e), 'CREATE_EVENT_ERROR')

    def get_event(self, event_id: int) -> ServiceResult[LeagueEvent]:
        """
        Get a league event by ID.

        Args:
            event_id: The event ID

        Returns:
            ServiceResult containing the LeagueEvent
        """
        try:
            event = self.session.query(LeagueEvent).get(event_id)

            if not event:
                return ServiceResult.fail('Event not found', 'EVENT_NOT_FOUND')

            return ServiceResult.ok(event)

        except Exception as e:
            logger.error(f"Error getting event {event_id}: {e}")
            return ServiceResult.fail(str(e), 'GET_EVENT_ERROR')

    def update_event(
        self,
        event_id: int,
        **updates
    ) -> ServiceResult[LeagueEvent]:
        """
        Update a league event.

        Args:
            event_id: The event ID to update
            **updates: Fields to update

        Returns:
            ServiceResult containing the updated LeagueEvent
        """
        self._log_operation_start('update_event', event_id=event_id)

        try:
            event = self.session.query(LeagueEvent).get(event_id)

            if not event:
                raise NotFoundError('Event not found', 'EVENT_NOT_FOUND')

            # Allowed fields to update
            allowed_fields = {
                'title', 'description', 'event_type', 'location',
                'start_datetime', 'end_datetime', 'is_all_day',
                'season_id', 'league_id', 'notify_discord', 'is_active'
            }

            for field, value in updates.items():
                if field not in allowed_fields:
                    continue

                # Validate event_type if being updated
                if field == 'event_type' and value not in self.VALID_EVENT_TYPES:
                    raise ValidationError(
                        f'Invalid event_type. Must be one of: {", ".join(self.VALID_EVENT_TYPES)}',
                        'INVALID_EVENT_TYPE'
                    )

                # Strip strings
                if isinstance(value, str):
                    value = value.strip() if value else None

                setattr(event, field, value)

            # Validate date range after updates
            if event.end_datetime and event.end_datetime < event.start_datetime:
                raise ValidationError(
                    'end_datetime must be after start_datetime',
                    'INVALID_DATE_RANGE'
                )

            event.updated_at = datetime.utcnow()
            self._commit()

            self._log_operation_success('update_event', event_id=event_id)
            return ServiceResult.ok(event, 'Event updated successfully')

        except (ValidationError, NotFoundError) as e:
            self._log_operation_error('update_event', e)
            return ServiceResult.fail(e.message, e.error_code)
        except Exception as e:
            self._log_operation_error('update_event', e)
            self._rollback()
            return ServiceResult.fail(str(e), 'UPDATE_EVENT_ERROR')

    def delete_event(self, event_id: int, soft_delete: bool = True) -> ServiceResult[bool]:
        """
        Delete a league event.

        Args:
            event_id: The event ID to delete
            soft_delete: If True, set is_active=False instead of deleting

        Returns:
            ServiceResult with success status
        """
        self._log_operation_start('delete_event', event_id=event_id)

        try:
            event = self.session.query(LeagueEvent).get(event_id)

            if not event:
                raise NotFoundError('Event not found', 'EVENT_NOT_FOUND')

            if soft_delete:
                event.is_active = False
                event.updated_at = datetime.utcnow()
            else:
                self.session.delete(event)

            self._commit()

            self._log_operation_success('delete_event', event_id=event_id)
            return ServiceResult.ok(True, 'Event deleted successfully')

        except NotFoundError as e:
            return ServiceResult.fail(e.message, e.error_code)
        except Exception as e:
            self._log_operation_error('delete_event', e)
            self._rollback()
            return ServiceResult.fail(str(e), 'DELETE_EVENT_ERROR')

    def list_events(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        event_type: Optional[str] = None,
        league_id: Optional[int] = None,
        include_inactive: bool = False
    ) -> ServiceResult[List[LeagueEvent]]:
        """
        List league events with optional filters.

        Args:
            start_date: Filter events on or after this date
            end_date: Filter events on or before this date
            event_type: Filter by event type
            league_id: Filter by league (None = all)
            include_inactive: Whether to include soft-deleted events

        Returns:
            ServiceResult containing list of LeagueEvents
        """
        try:
            query = self.session.query(LeagueEvent)

            if not include_inactive:
                query = query.filter(LeagueEvent.is_active == True)

            if start_date:
                query = query.filter(LeagueEvent.start_datetime >= start_date)

            if end_date:
                query = query.filter(LeagueEvent.start_datetime <= end_date)

            if event_type:
                query = query.filter(LeagueEvent.event_type == event_type)

            if league_id is not None:
                query = query.filter(LeagueEvent.league_id == league_id)

            events = query.order_by(LeagueEvent.start_datetime).all()
            return ServiceResult.ok(events)

        except Exception as e:
            logger.error(f"Error listing events: {e}")
            return ServiceResult.fail(str(e), 'LIST_EVENTS_ERROR')

    def get_upcoming_events(
        self,
        days: int = 30,
        league_id: Optional[int] = None
    ) -> ServiceResult[List[LeagueEvent]]:
        """
        Get upcoming league events.

        Args:
            days: Number of days to look ahead
            league_id: Filter by league (None = all)

        Returns:
            ServiceResult containing list of upcoming LeagueEvents
        """
        from datetime import timedelta

        start = datetime.utcnow()
        end = start + timedelta(days=days)

        return self.list_events(
            start_date=start,
            end_date=end,
            league_id=league_id
        )


def create_league_event_service(session: Session) -> LeagueEventService:
    """
    Factory function to create a LeagueEventService instance.

    Args:
        session: SQLAlchemy database session

    Returns:
        Configured LeagueEventService instance
    """
    return LeagueEventService(session)
