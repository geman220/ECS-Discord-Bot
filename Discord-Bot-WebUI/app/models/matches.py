# app/models/matches.py

"""
Match and Schedule Models Module

This module contains models related to matches and scheduling:
- Schedule: Schedule entity for matches
- Match: Match entity between teams
- Availability: Player availability for matches
- TemporarySubAssignment: Temporary substitute assignments
- AutoScheduleConfig: Auto schedule generation configuration
- ScheduleTemplate: Schedule templates
- WeekConfiguration: Week configuration for scheduling
"""

import logging
from datetime import datetime, time
from sqlalchemy import event

from app.core import db

logger = logging.getLogger(__name__)



class Schedule(db.Model):
    """Model representing a schedule for matches."""
    id = db.Column(db.Integer, primary_key=True)
    week = db.Column(db.String(10), nullable=False)
    date = db.Column(db.Date, nullable=False)
    time = db.Column(db.Time, nullable=False)
    opponent = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    location = db.Column(db.String(100), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    season_id = db.Column(db.Integer, db.ForeignKey('season.id'))

    team = db.relationship('Team', foreign_keys=[team_id], back_populates='schedules', overlaps='matches')
    opponent_team = db.relationship('Team', foreign_keys=[opponent], back_populates='opponent_schedules', post_update=True)
    matches = db.relationship('Match', back_populates='schedule', lazy=True)
    season = db.relationship('Season')


class Match(db.Model):
    """Model representing a match between two teams."""
    __tablename__ = 'matches'
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    time = db.Column(db.Time, nullable=False)
    location = db.Column(db.String(100), nullable=False)
    home_team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    away_team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    home_team_message_id = db.Column(db.String(100), nullable=True)
    away_team_message_id = db.Column(db.String(100), nullable=True)
    home_team_channel_id = db.Column(db.String(100), nullable=True)
    away_team_channel_id = db.Column(db.String(100), nullable=True)
    home_team_score = db.Column(db.Integer, nullable=True)
    away_team_score = db.Column(db.Integer, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    schedule_id = db.Column(db.Integer, db.ForeignKey('schedule.id'), nullable=False)
    events = db.relationship('PlayerEvent', back_populates='match', lazy=True, cascade="all, delete-orphan")
    # Relationship with temporary sub assignments defined in TemporarySubAssignment model

    # Team verification fields
    home_team_verified = db.Column(db.Boolean, default=False)
    home_team_verified_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    home_team_verified_at = db.Column(db.DateTime, nullable=True)
    away_team_verified = db.Column(db.Boolean, default=False)
    away_team_verified_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    away_team_verified_at = db.Column(db.DateTime, nullable=True)
    
    # Optimistic locking for concurrent edit protection
    version = db.Column(db.Integer, default=1, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    home_team = db.relationship('Team', foreign_keys=[home_team_id], backref='home_matches')
    away_team = db.relationship('Team', foreign_keys=[away_team_id], backref='away_matches')
    schedule = db.relationship('Schedule', back_populates='matches')
    availability = db.relationship('Availability', back_populates='match', lazy=True, cascade="all, delete-orphan")
    ref_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=True)
    ref = db.relationship('Player', backref='assigned_matches')
    scheduled_messages = db.relationship('ScheduledMessage', back_populates='match')
    home_verifier = db.relationship('User', foreign_keys=[home_team_verified_by], backref=db.backref('home_verified_matches', lazy='dynamic'))
    away_verifier = db.relationship('User', foreign_keys=[away_team_verified_by], backref=db.backref('away_verified_matches', lazy='dynamic'))
    
    # Discord notification tracking
    last_discord_notification = db.Column(db.DateTime, nullable=True)
    notification_status = db.Column(db.String(50), nullable=True)
    last_notification_state_hash = db.Column(db.String(64), nullable=True)
    
    # Special week tracking
    week_type = db.Column(db.String(20), default='REGULAR', nullable=False)  # REGULAR, FUN, TST, BYE, PLAYOFF, PRACTICE, BONUS
    is_special_week = db.Column(db.Boolean, default=False)  # True for FUN/TST/BYE weeks
    is_playoff_game = db.Column(db.Boolean, default=False)  # True if this is a playoff game
    playoff_round = db.Column(db.Integer, nullable=True)  # Playoff round number (1, 2, etc.)

    def to_dict(self, include_teams=False, include_events=False):
        data = {
            'id': self.id,
            'date': self.date.isoformat() if self.date else None,
            'time': self.time.isoformat() if self.time else None,
            'location': self.location,
            'home_team_id': self.home_team_id,
            'away_team_id': self.away_team_id,
            'home_team_score': self.home_team_score,
            'away_team_score': self.away_team_score,
            'notes': self.notes,
            'schedule_id': self.schedule_id,
            'ref_id': self.ref_id,
            'reported': self.reported,
            'home_team_verified': self.home_team_verified,
            'away_team_verified': self.away_team_verified,
            'fully_verified': self.fully_verified,
            'week_type': self.week_type,
            'is_special_week': self.is_special_week,
            'is_playoff_game': self.is_playoff_game,
            'playoff_round': self.playoff_round,
            'version': self.version,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_teams:
            data['home_team'] = self.home_team.to_dict()
            data['away_team'] = self.away_team.to_dict()
        if include_events:
            data['events'] = [event.to_dict() for event in self.events]
        return data

    @property
    def reported(self):
        """Determine if the match has been reported based on scores."""
        return (
            self.home_team_score is not None and
            self.away_team_score is not None
        )
        
    @property
    def fully_verified(self):
        """Determine if the match has been verified by both teams."""
        return self.home_team_verified and self.away_team_verified
        
    def get_verification_status(self):
        """Get a detailed verification status for the match."""
        return {
            'reported': self.reported,
            'home_team_verified': self.home_team_verified,
            'away_team_verified': self.away_team_verified,
            'fully_verified': self.fully_verified,
            'home_verifier': self.home_verifier.username if self.home_verifier else None,
            'away_verifier': self.away_verifier.username if self.away_verifier else None,
            'home_verified_at': self.home_team_verified_at.isoformat() if self.home_team_verified_at else None,
            'away_verified_at': self.away_team_verified_at.isoformat() if self.away_team_verified_at else None,
        }

    def get_opponent_name(self, player):
        player_team_ids = [team.id for team in player.teams]
        if self.home_team_id in player_team_ids:
            return self.away_team.name
        elif self.away_team_id in player_team_ids:
            return self.home_team.name
        return None


class Availability(db.Model):
    """Model representing a player's availability for a match."""
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('matches.id'), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id', ondelete='CASCADE'), nullable=True)
    discord_id = db.Column(db.String(100), nullable=False)
    response = db.Column(db.String(20), nullable=False)
    responded_at = db.Column(db.DateTime, default=datetime.utcnow)
    discord_sync_status = db.Column(db.String(20), nullable=True)
    last_sync_attempt = db.Column(db.DateTime, nullable=True)
    sync_error = db.Column(db.String(255), nullable=True)
    match = db.relationship('Match', back_populates='availability')
    player = db.relationship('Player', back_populates='availability')

    def to_dict(self, session=None):
        return {
            'id': self.id,
            'match_id': self.match_id,
            'player_id': self.player_id,
            'discord_id': self.discord_id,
            'response': self.response,
            'responded_at': self.responded_at.isoformat() if self.responded_at else None,
            'discord_sync_status': self.discord_sync_status,
            'last_sync_attempt': self.last_sync_attempt.isoformat() if self.last_sync_attempt else None,
            'sync_error': self.sync_error,
        }


class TemporarySubAssignment(db.Model):
    """Model representing a temporary substitute assignment for a match."""
    __tablename__ = 'temporary_sub_assignments'
    
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('matches.id', ondelete='CASCADE'), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id', ondelete='CASCADE'), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id', ondelete='CASCADE'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    assigned_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Define relationships
    match = db.relationship('Match', backref=db.backref('temp_sub_assignments', lazy='dynamic'))
    player = db.relationship('Player', backref=db.backref('temp_sub_assignments', lazy='dynamic'))
    team = db.relationship('Team', backref=db.backref('temp_sub_assignments', lazy='dynamic'))
    assigner = db.relationship('User', backref=db.backref('assigned_subs', lazy='dynamic'))
    
    __table_args__ = (
        db.UniqueConstraint('match_id', 'player_id', name='uq_temp_sub_match_player'),
    )
    
    def __repr__(self):
        return f"<TemporarySubAssignment: {self.player_id} for {self.team_id} in match {self.match_id}>"


class AutoScheduleConfig(db.Model):
    """Model for storing automatic schedule generation configuration."""
    __tablename__ = 'auto_schedule_configs'
    
    id = db.Column(db.Integer, primary_key=True)
    league_id = db.Column(db.Integer, db.ForeignKey('league.id'), nullable=False)
    
    # Legacy single start time (for backward compatibility)
    start_time = db.Column(db.Time, nullable=True)  # e.g., 8:00 AM
    
    # Enhanced time configuration
    premier_start_time = db.Column(db.Time, default=time(8, 20), nullable=False)  # Premier division start time
    classic_start_time = db.Column(db.Time, default=time(13, 10), nullable=False)  # Classic division start time
    enable_time_rotation = db.Column(db.Boolean, default=True, nullable=False)  # Enable time slot balancing
    break_duration_minutes = db.Column(db.Integer, default=10, nullable=False)  # Break between back-to-back matches
    
    # Match and season configuration
    match_duration_minutes = db.Column(db.Integer, default=70, nullable=False)
    weeks_count = db.Column(db.Integer, default=7, nullable=False)
    
    # Field configuration (enhanced)
    fields = db.Column(db.String(255), default='North,South', nullable=False)  # Comma-separated field names
    field_config = db.Column(db.JSON, nullable=True)  # JSON: [{"name": "North", "capacity": 20}, ...]
    
    # Practice session configuration
    enable_practice_weeks = db.Column(db.Boolean, default=False, nullable=False)
    practice_weeks = db.Column(db.String(50), nullable=True)  # Comma-separated week numbers (e.g., "1,3")
    
    # Metadata
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    league = db.relationship('League', backref=db.backref('auto_schedule_configs', lazy='dynamic'))
    creator = db.relationship('User', backref=db.backref('created_schedule_configs', lazy='dynamic'))
    
    def get_start_time_for_division(self, division_name):
        """Get the appropriate start time for a specific division."""
        if division_name == 'Premier':
            return self.premier_start_time
        elif division_name == 'Classic':
            return self.classic_start_time
        else:
            # Fallback to legacy start_time or Premier time
            return self.start_time or self.premier_start_time
    
    def get_field_list(self):
        """Get list of field names."""
        if self.field_config:
            return [field['name'] for field in self.field_config]
        else:
            return [name.strip() for name in self.fields.split(',') if name.strip()]
    
    def get_field_capacity(self, field_name):
        """Get capacity for a specific field."""
        if self.field_config:
            for field in self.field_config:
                if field['name'] == field_name:
                    return field.get('capacity', 20)
        return 20  # Default capacity
    
    def get_practice_weeks_list(self):
        """Get list of practice week numbers."""
        if self.practice_weeks:
            return [int(week.strip()) for week in self.practice_weeks.split(',') if week.strip().isdigit()]
        return []
    
    def __repr__(self):
        return f'<AutoScheduleConfig {self.league_id} Premier:{self.premier_start_time} Classic:{self.classic_start_time}>'


class ScheduleTemplate(db.Model):
    """Model for storing generated schedule templates before committing to actual schedule."""
    __tablename__ = 'schedule_templates'
    
    id = db.Column(db.Integer, primary_key=True)
    league_id = db.Column(db.Integer, db.ForeignKey('league.id'), nullable=False)
    week_number = db.Column(db.Integer, nullable=False)
    home_team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    away_team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    scheduled_date = db.Column(db.Date, nullable=False)
    scheduled_time = db.Column(db.Time, nullable=False)
    field_name = db.Column(db.String(50), nullable=False)  # North, South, etc.
    match_order = db.Column(db.Integer, nullable=False)  # 1st or 2nd match for teams that day
    week_type = db.Column(db.String(20), default='REGULAR', nullable=False)  # REGULAR, FUN, TST, BYE, PLAYOFF, PRACTICE, BONUS
    is_special_week = db.Column(db.Boolean, default=False)  # True for FUN/TST/BYE weeks
    is_practice_game = db.Column(db.Boolean, default=False)  # True if this is a practice game
    is_playoff_game = db.Column(db.Boolean, default=False)  # True if this is a playoff game
    playoff_round = db.Column(db.Integer, nullable=True)  # Playoff round number (1, 2, etc.)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_committed = db.Column(db.Boolean, default=False)  # Whether this template has been converted to actual schedule
    
    league = db.relationship('League', backref=db.backref('schedule_templates', lazy='dynamic'))
    home_team = db.relationship('Team', foreign_keys=[home_team_id], backref=db.backref('home_schedule_templates', lazy='dynamic'))
    away_team = db.relationship('Team', foreign_keys=[away_team_id], backref=db.backref('away_schedule_templates', lazy='dynamic'))
    
    def __repr__(self):
        return f'<ScheduleTemplate W{self.week_number}: {self.home_team_id} vs {self.away_team_id} ({self.week_type})>'


class WeekConfiguration(db.Model):
    """Model for configuring special weeks in a season schedule."""
    __tablename__ = 'week_configurations'
    
    id = db.Column(db.Integer, primary_key=True)
    league_id = db.Column(db.Integer, db.ForeignKey('league.id'), nullable=False)
    week_date = db.Column(db.Date, nullable=False)
    week_type = db.Column(db.String(20), nullable=False)  # REGULAR, FUN, TST, BYE, PLAYOFF, PRACTICE, BONUS
    week_order = db.Column(db.Integer, nullable=False)  # Order in the season (1, 2, 3, etc.)
    description = db.Column(db.String(255), nullable=True)  # Optional description
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # New fields for enhanced playoff and practice handling
    is_playoff_week = db.Column(db.Boolean, default=False)  # True for playoff weeks
    playoff_round = db.Column(db.Integer, nullable=True)  # 1 for first round, 2 for second round, etc.
    has_practice_session = db.Column(db.Boolean, default=False)  # True if week has practice sessions
    practice_game_number = db.Column(db.Integer, nullable=True)  # Which game number is practice (1 or 2)
    
    league = db.relationship('League', backref=db.backref('week_configurations', lazy='dynamic'))
    
    def __repr__(self):
        return f'<WeekConfiguration {self.week_type} on {self.week_date}>'


class SeasonConfiguration(db.Model):
    """Model for storing season-specific configuration options."""
    __tablename__ = 'season_configurations'
    
    id = db.Column(db.Integer, primary_key=True)
    league_id = db.Column(db.Integer, db.ForeignKey('league.id'), nullable=False)
    
    # Season structure configuration
    regular_season_weeks = db.Column(db.Integer, default=7)  # Number of regular season weeks
    playoff_weeks = db.Column(db.Integer, default=2)  # Number of playoff weeks
    has_fun_week = db.Column(db.Boolean, default=True)  # Whether season has fun week
    has_tst_week = db.Column(db.Boolean, default=True)  # Whether season has TST week
    has_bonus_week = db.Column(db.Boolean, default=False)  # Whether season has bonus week
    
    # Practice session configuration
    has_practice_sessions = db.Column(db.Boolean, default=False)  # Whether league has practice sessions
    practice_weeks = db.Column(db.String(50), nullable=True)  # Comma-separated week numbers with practice (e.g., "1,3")
    practice_game_number = db.Column(db.Integer, default=1)  # Which game number is practice (1 or 2)
    
    # League type specific settings
    league_type = db.Column(db.String(20), nullable=False)  # PREMIER, CLASSIC, ECS_FC
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    league = db.relationship('League', backref=db.backref('season_configuration', uselist=False))
    
    def get_practice_weeks_list(self):
        """Get practice weeks as a list of integers."""
        if not self.practice_weeks:
            return []
        return [int(week.strip()) for week in self.practice_weeks.split(',') if week.strip()]
    
    def set_practice_weeks_list(self, weeks_list):
        """Set practice weeks from a list of integers."""
        if weeks_list:
            self.practice_weeks = ','.join(str(week) for week in weeks_list)
        else:
            self.practice_weeks = None
    
    def __repr__(self):
        return f'<SeasonConfiguration {self.league_type} - {self.regular_season_weeks} weeks + {self.playoff_weeks} playoffs>'