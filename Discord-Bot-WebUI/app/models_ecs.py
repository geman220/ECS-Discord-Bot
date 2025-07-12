"""
ECS FC Specific Models Module

This module defines SQLAlchemy ORM models specifically for ECS FC scheduling functionality.
These models are separate from the main pub league system to maintain clean separation
of concerns while leveraging existing infrastructure.
"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from flask import g
from sqlalchemy import event, func, Enum, JSON, DateTime, Boolean, Column, Integer, ForeignKey, or_, desc, String, Text, Date, Time
from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_property

from app.core import db

# Set up the module logger
logger = logging.getLogger(__name__)


class EcsFcMatch(db.Model):
    """
    Model representing an ECS FC match.
    
    ECS FC matches are independent of the traditional season/league structure
    and allow teams to schedule matches against external opponents.
    """
    __tablename__ = 'ecs_fc_matches'
    
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    opponent_name = db.Column(db.String(255), nullable=False)
    match_date = db.Column(db.Date, nullable=False)
    match_time = db.Column(db.Time, nullable=False)
    location = db.Column(db.String(500), nullable=False)
    field_name = db.Column(db.String(255), nullable=True)
    is_home_match = db.Column(db.Boolean, nullable=False, default=True)
    notes = db.Column(db.Text, nullable=True)
    
    # Match status and results
    status = db.Column(db.String(20), nullable=False, default='SCHEDULED')  # SCHEDULED, COMPLETED, CANCELLED
    home_score = db.Column(db.Integer, nullable=True)
    away_score = db.Column(db.Integer, nullable=True)
    
    # Metadata and tracking
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # RSVP related
    rsvp_deadline = db.Column(db.DateTime, nullable=True)
    rsvp_reminder_sent = db.Column(db.Boolean, nullable=False, default=False)
    
    # Relationships
    team = db.relationship('Team', backref='ecs_fc_matches')
    creator = db.relationship('User', backref='created_ecs_fc_matches')
    availabilities = db.relationship('EcsFcAvailability', backref='ecs_fc_match', cascade='all, delete-orphan')
    
    def to_dict(self, include_rsvp=False) -> Dict[str, Any]:
        """Convert match to dictionary format."""
        result = {
            'id': self.id,
            'team_id': self.team_id,
            'team_name': self.team.name if self.team else None,
            'opponent_name': self.opponent_name,
            'match_date': self.match_date.isoformat() if self.match_date else None,
            'match_time': self.match_time.strftime('%H:%M') if self.match_time else None,
            'location': self.location,
            'field_name': self.field_name,
            'is_home_match': self.is_home_match,
            'notes': self.notes,
            'status': self.status,
            'home_score': self.home_score,
            'away_score': self.away_score,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'rsvp_deadline': self.rsvp_deadline.isoformat() if self.rsvp_deadline else None,
            'rsvp_reminder_sent': self.rsvp_reminder_sent
        }
        
        if include_rsvp:
            result['rsvp_summary'] = self.get_rsvp_summary()
            
        return result
    
    def get_rsvp_summary(self) -> Dict[str, int]:
        """Get RSVP summary for this match."""
        summary = {'yes': 0, 'no': 0, 'maybe': 0, 'no_response': 0}
        
        # Get all team players
        team_players = self.team.players if self.team else []
        
        # Count responses
        for availability in self.availabilities:
            if availability.response:
                summary[availability.response] += 1
        
        # Count players who haven't responded
        responded_players = {av.player_id for av in self.availabilities if av.response}
        all_players = {p.id for p in team_players}
        summary['no_response'] = len(all_players - responded_players)
        
        return summary
    
    @hybrid_property
    def datetime_combined(self):
        """Get combined datetime for sorting/filtering."""
        if self.match_date and self.match_time:
            return datetime.combine(self.match_date, self.match_time)
        return None
    
    @hybrid_property
    def is_upcoming(self):
        """Check if match is in the future."""
        if self.datetime_combined:
            return self.datetime_combined > datetime.now()
        return False
    
    @hybrid_property
    def is_past(self):
        """Check if match is in the past."""
        if self.datetime_combined:
            return self.datetime_combined < datetime.now()
        return False
    
    def can_edit(self, user) -> bool:
        """Check if user can edit this match."""
        if not user:
            return False
            
        # Admin can edit any match
        if (user.has_role('Global Admin') or user.has_role('Pub League Admin')):
            return True
            
        # Team coaches can edit their team's matches
        if self.team and user.player:
            from app.models import player_teams
            from app.core import db
            is_coach = g.db_session.query(player_teams.c.is_coach).filter(
                player_teams.c.player_id == user.player.id,
                player_teams.c.team_id == self.team.id,
                player_teams.c.is_coach == True
            ).first()
            if is_coach:
                return True
            
        # Creator can edit their own matches
        if self.created_by == user.id:
            return True
            
        return False
    
    def __repr__(self):
        return f'<EcsFcMatch {self.team.name if self.team else "Unknown"} vs {self.opponent_name} on {self.match_date}>'


class EcsFcAvailability(db.Model):
    """
    Model representing player availability for ECS FC matches.
    
    Similar to the existing Availability model but specific to ECS FC matches.
    """
    __tablename__ = 'ecs_fc_availability'
    
    id = db.Column(db.Integer, primary_key=True)
    ecs_fc_match_id = db.Column(db.Integer, db.ForeignKey('ecs_fc_matches.id'), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    discord_id = db.Column(db.String(50), nullable=True)
    
    # RSVP response
    response = db.Column(db.String(10), nullable=True)  # 'yes', 'no', 'maybe'
    response_time = db.Column(db.DateTime, nullable=True)
    
    # Additional info
    notes = db.Column(db.Text, nullable=True)
    
    # Tracking
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    player = db.relationship('Player', backref='ecs_fc_availabilities')
    user = db.relationship('User', backref='ecs_fc_availabilities')
    
    # Unique constraint to prevent duplicate responses
    __table_args__ = (
        db.UniqueConstraint('ecs_fc_match_id', 'player_id', name='uq_ecs_fc_availability_match_player'),
    )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert availability to dictionary format."""
        return {
            'id': self.id,
            'ecs_fc_match_id': self.ecs_fc_match_id,
            'player_id': self.player_id,
            'player_name': self.player.player_name if self.player else None,
            'user_id': self.user_id,
            'discord_id': self.discord_id,
            'response': self.response,
            'response_time': self.response_time.isoformat() if self.response_time else None,
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
    
    def __repr__(self):
        return f'<EcsFcAvailability Player:{self.player_id} Match:{self.ecs_fc_match_id} Response:{self.response}>'


class EcsFcScheduleTemplate(db.Model):
    """
    Model for storing ECS FC schedule templates.
    
    This allows coaches to create reusable schedule templates
    for recurring matches or tournament schedules.
    """
    __tablename__ = 'ecs_fc_schedule_templates'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    description = db.Column(db.Text, nullable=True)
    
    # Template data stored as JSON
    template_data = db.Column(db.JSON, nullable=False)
    
    # Metadata
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    
    # Relationships
    team = db.relationship('Team', backref='ecs_fc_schedule_templates')
    creator = db.relationship('User', backref='created_ecs_fc_schedule_templates')
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert template to dictionary format."""
        return {
            'id': self.id,
            'name': self.name,
            'team_id': self.team_id,
            'team_name': self.team.name if self.team else None,
            'description': self.description,
            'template_data': self.template_data,
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'is_active': self.is_active
        }
    
    def __repr__(self):
        return f'<EcsFcScheduleTemplate {self.name} for {self.team.name if self.team else "Unknown"}>'


# Event listeners for automatic timestamp updates
@event.listens_for(EcsFcMatch, 'before_update')
def update_ecs_fc_match_timestamp(mapper, connection, target):
    """Update the updated_at timestamp before updating ECS FC match."""
    target.updated_at = datetime.utcnow()


@event.listens_for(EcsFcAvailability, 'before_update')
def update_ecs_fc_availability_timestamp(mapper, connection, target):
    """Update the updated_at timestamp before updating ECS FC availability."""
    target.updated_at = datetime.utcnow()


@event.listens_for(EcsFcScheduleTemplate, 'before_update')
def update_ecs_fc_template_timestamp(mapper, connection, target):
    """Update the updated_at timestamp before updating ECS FC template."""
    target.updated_at = datetime.utcnow()


# Utility functions for ECS FC operations
def get_ecs_fc_teams():
    """Get all ECS FC teams."""
    from app.models import Team, League
    
    return g.db_session.query(Team).join(League).filter(
        League.name == 'ECS FC'
    ).all()


def is_ecs_fc_team(team_id: int) -> bool:
    """Check if a team is an ECS FC team."""
    from app.models import Team, League
    
    team = g.db_session.query(Team).join(League).filter(
        Team.id == team_id,
        League.name == 'ECS FC'
    ).first()
    
    return team is not None


def get_ecs_fc_matches_for_team(team_id: int, upcoming_only: bool = False) -> List[EcsFcMatch]:
    """Get ECS FC matches for a specific team."""
    query = g.db_session.query(EcsFcMatch).filter(EcsFcMatch.team_id == team_id)
    
    if upcoming_only:
        query = query.filter(EcsFcMatch.match_date >= datetime.now().date())
    
    return query.order_by(EcsFcMatch.match_date.asc(), EcsFcMatch.match_time.asc()).all()


def get_ecs_fc_matches_for_date_range(team_id: int, start_date: datetime, end_date: datetime) -> List[EcsFcMatch]:
    """Get ECS FC matches for a team within a date range."""
    return g.db_session.query(EcsFcMatch).filter(
        EcsFcMatch.team_id == team_id,
        EcsFcMatch.match_date >= start_date.date(),
        EcsFcMatch.match_date <= end_date.date()
    ).order_by(EcsFcMatch.match_date.asc(), EcsFcMatch.match_time.asc()).all()