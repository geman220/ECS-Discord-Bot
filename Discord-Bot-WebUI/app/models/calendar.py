# app/models/calendar.py

"""
Calendar Models Module

This module contains models for the enhanced calendar system:
- LeagueEvent: Non-match events (parties, meetings, etc.)
- CalendarSubscription: User iCal subscription tokens
"""

import secrets
import logging
from datetime import datetime
from enum import Enum

from app.core import db

logger = logging.getLogger(__name__)


class LeagueEventType(Enum):
    """Enum for league event types."""
    PARTY = 'party'
    MEETING = 'meeting'
    SOCIAL = 'social'
    PLOP = 'plop'  # Replaced 'training'
    TOURNAMENT = 'tournament'
    FUNDRAISER = 'fundraiser'
    OTHER = 'other'


class LeagueEvent(db.Model):
    """
    Model representing a non-match league event.

    Examples: Pre-season party, league meeting, training session, etc.
    These appear on the calendar alongside matches but are managed separately.
    """
    __tablename__ = 'league_events'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    event_type = db.Column(db.String(50), default='other', nullable=False)
    location = db.Column(db.String(255), nullable=True)

    # Timing
    start_datetime = db.Column(db.DateTime, nullable=False)
    end_datetime = db.Column(db.DateTime, nullable=True)
    is_all_day = db.Column(db.Boolean, default=False, nullable=False)

    # Scope - null values mean "all" (league-wide)
    season_id = db.Column(db.Integer, db.ForeignKey('season.id'), nullable=True)
    league_id = db.Column(db.Integer, db.ForeignKey('league.id'), nullable=True)

    # Discord notification
    notify_discord = db.Column(db.Boolean, default=False, nullable=False)
    discord_message_id = db.Column(db.String(100), nullable=True)
    discord_channel_id = db.Column(db.String(100), nullable=True)

    # Metadata
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    # Relationships
    season = db.relationship('Season', backref=db.backref('league_events', lazy='dynamic'))
    league = db.relationship('League', backref=db.backref('league_events', lazy='dynamic'))
    creator = db.relationship('User', backref=db.backref('created_league_events', lazy='dynamic'))

    def to_dict(self, include_creator=False):
        """Convert to dictionary for API responses."""
        data = {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'event_type': self.event_type,
            'location': self.location,
            'start_datetime': self.start_datetime.isoformat() if self.start_datetime else None,
            'end_datetime': self.end_datetime.isoformat() if self.end_datetime else None,
            'is_all_day': self.is_all_day,
            'season_id': self.season_id,
            'league_id': self.league_id,
            'notify_discord': self.notify_discord,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_creator and self.creator:
            data['created_by'] = {
                'id': self.creator.id,
                'username': self.creator.username
            }
        return data

    def to_fullcalendar_event(self):
        """
        Convert to FullCalendar event format.

        Returns a dict compatible with FullCalendar's event source format.
        """
        # Color mapping by event type
        color_map = {
            'party': '#9c27b0',       # Purple
            'meeting': '#2196f3',     # Blue
            'social': '#e91e63',      # Pink
            'plop': '#4caf50',        # Green
            'tournament': '#ffc107',  # Yellow/Gold
            'fundraiser': '#ff5722',  # Deep Orange
            'other': '#607d8b',       # Blue-grey
        }

        return {
            'id': f'event-{self.id}',
            'title': self.title,
            'start': self.start_datetime.isoformat() if self.start_datetime else None,
            'end': self.end_datetime.isoformat() if self.end_datetime else None,
            'allDay': self.is_all_day,
            'color': color_map.get(self.event_type, '#607d8b'),
            'editable': True,  # Will be filtered by role on frontend
            'extendedProps': {
                'type': 'league_event',
                'eventType': self.event_type,
                'description': self.description,
                'location': self.location,
                'leagueId': self.league_id,
                'seasonId': self.season_id,
            }
        }

    def __repr__(self):
        return f'<LeagueEvent {self.id}: {self.title}>'


class CalendarSubscription(db.Model):
    """
    Model representing a user's calendar subscription token.

    Each user can have one subscription that provides a personalized
    iCal feed URL for syncing with external calendar applications.
    """
    __tablename__ = 'calendar_subscriptions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
        unique=True
    )
    token = db.Column(db.String(64), unique=True, nullable=False, index=True)

    # Subscription preferences
    include_team_matches = db.Column(db.Boolean, default=True, nullable=False)
    include_league_events = db.Column(db.Boolean, default=True, nullable=False)
    include_ref_assignments = db.Column(db.Boolean, default=True, nullable=False)

    # Status and tracking
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    regenerated_at = db.Column(db.DateTime, nullable=True)
    last_accessed = db.Column(db.DateTime, nullable=True)
    access_count = db.Column(db.Integer, default=0, nullable=False)

    # Relationships
    user = db.relationship(
        'User',
        backref=db.backref('calendar_subscription', uselist=False, cascade='all, delete-orphan')
    )

    @classmethod
    def generate_token(cls) -> str:
        """
        Generate a cryptographically secure subscription token.

        Uses secrets.token_urlsafe for URL-safe tokens that can be
        used directly in iCal subscription URLs.
        """
        return secrets.token_urlsafe(48)  # Results in ~64 character token

    @classmethod
    def create_for_user(cls, user_id: int) -> 'CalendarSubscription':
        """
        Create a new subscription for a user.

        Args:
            user_id: The user's ID

        Returns:
            A new CalendarSubscription instance (not yet committed)
        """
        return cls(
            user_id=user_id,
            token=cls.generate_token()
        )

    def regenerate_token(self) -> str:
        """
        Regenerate the subscription token.

        This invalidates the old token and creates a new one.
        Users will need to update their calendar subscriptions.

        Returns:
            The new token
        """
        self.token = self.generate_token()
        self.regenerated_at = datetime.utcnow()
        return self.token

    def record_access(self) -> None:
        """Record an access to this subscription feed."""
        self.last_accessed = datetime.utcnow()
        self.access_count += 1

    def to_dict(self):
        """Convert to dictionary for API responses."""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'include_team_matches': self.include_team_matches,
            'include_league_events': self.include_league_events,
            'include_ref_assignments': self.include_ref_assignments,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_accessed': self.last_accessed.isoformat() if self.last_accessed else None,
            'access_count': self.access_count,
        }

    def __repr__(self):
        return f'<CalendarSubscription {self.id} for User {self.user_id}>'
