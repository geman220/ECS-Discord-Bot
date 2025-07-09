"""
ECS FC Substitute System Models

This module defines SQLAlchemy ORM models for the ECS FC substitute request
and assignment system, separate from the pub league substitute system.
"""

import logging
from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.core import db

logger = logging.getLogger(__name__)


class EcsFcSubRequest(db.Model):
    """
    Model representing an ECS FC substitute request.
    
    When an ECS FC coach needs a substitute, they create a request which
    notifies all players with the 'ECS FC Sub' role.
    """
    __tablename__ = 'ecs_fc_sub_requests'
    
    id = Column(Integer, primary_key=True)
    match_id = Column(Integer, ForeignKey('ecs_fc_matches.id'), nullable=False)
    team_id = Column(Integer, ForeignKey('team.id'), nullable=False)
    requested_by = Column(Integer, ForeignKey('users.id'), nullable=False)
    
    # Request details
    positions_needed = Column(String(255), nullable=True)  # e.g., "Forward, Midfield"
    substitutes_needed = Column(Integer, nullable=False, default=1)  # Number of substitutes needed
    notes = Column(Text, nullable=True)
    
    # Status tracking
    status = Column(String(20), nullable=False, default='OPEN')  # OPEN, FILLED, CANCELLED
    filled_at = Column(DateTime, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    match = relationship('EcsFcMatch', backref='sub_requests')
    team = relationship('Team', backref='ecs_fc_sub_requests')
    requester = relationship('User', backref='ecs_fc_sub_requests_made')
    responses = relationship('EcsFcSubResponse', back_populates='request', cascade='all, delete-orphan')
    assignments = relationship('EcsFcSubAssignment', back_populates='request', cascade='all, delete-orphan')
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert request to dictionary format."""
        assigned_count = len(self.assignments) if self.assignments else 0
        return {
            'id': self.id,
            'match_id': self.match_id,
            'team_id': self.team_id,
            'team_name': self.team.name if self.team else None,
            'requested_by': self.requested_by,
            'requester_name': self.requester.username if self.requester else None,
            'positions_needed': self.positions_needed,
            'substitutes_needed': self.substitutes_needed,
            'notes': self.notes,
            'status': self.status,
            'filled_at': self.filled_at.isoformat() if self.filled_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'match_details': self.match.to_dict() if self.match else None,
            'available_subs_count': len([r for r in self.responses if r.is_available]),
            'assigned_count': assigned_count,
            'assignments_remaining': self.substitutes_needed - assigned_count
        }


class EcsFcSubResponse(db.Model):
    """
    Model tracking responses from potential substitutes.
    
    When notified about a sub request, players can respond via SMS or Discord
    to indicate their availability.
    """
    __tablename__ = 'ecs_fc_sub_responses'
    
    id = Column(Integer, primary_key=True)
    request_id = Column(Integer, ForeignKey('ecs_fc_sub_requests.id'), nullable=False)
    player_id = Column(Integer, ForeignKey('player.id'), nullable=False)
    
    # Response details
    is_available = Column(Boolean, nullable=False)
    response_method = Column(String(20), nullable=False)  # SMS, DISCORD, WEB
    response_text = Column(Text, nullable=True)
    
    # Notification tracking
    notification_sent_at = Column(DateTime, nullable=True)
    notification_methods = Column(String(100), nullable=True)  # Comma-separated: SMS,DISCORD,EMAIL
    
    # Timestamps
    responded_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    
    # Ensure one response per player per request
    __table_args__ = (
        UniqueConstraint('request_id', 'player_id', name='uq_ecs_fc_sub_response_request_player'),
    )
    
    # Relationships
    request = relationship('EcsFcSubRequest', back_populates='responses')
    player = relationship('Player', backref='ecs_fc_sub_responses')
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert response to dictionary format."""
        return {
            'id': self.id,
            'request_id': self.request_id,
            'player_id': self.player_id,
            'player_name': self.player.name if self.player else None,
            'is_available': self.is_available,
            'response_method': self.response_method,
            'response_text': self.response_text,
            'responded_at': self.responded_at.isoformat() if self.responded_at else None
        }


class EcsFcSubAssignment(db.Model):
    """
    Model representing the assignment of a substitute to an ECS FC match.
    
    After receiving responses, the coach can select and assign a substitute
    from the available pool.
    """
    __tablename__ = 'ecs_fc_sub_assignments'
    
    id = Column(Integer, primary_key=True)
    request_id = Column(Integer, ForeignKey('ecs_fc_sub_requests.id'), nullable=False)
    player_id = Column(Integer, ForeignKey('player.id'), nullable=False)
    assigned_by = Column(Integer, ForeignKey('users.id'), nullable=False)
    
    # Assignment details
    position_assigned = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)
    
    # Notification tracking
    notification_sent = Column(Boolean, nullable=False, default=False)
    notification_sent_at = Column(DateTime, nullable=True)
    notification_methods = Column(String(100), nullable=True)  # Comma-separated
    
    # Timestamps
    assigned_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    
    # Ensure one assignment per player per request (but allow multiple players per request)
    __table_args__ = (
        UniqueConstraint('request_id', 'player_id', name='uq_ecs_fc_sub_assignment_request_player'),
    )
    
    # Relationships
    request = relationship('EcsFcSubRequest', back_populates='assignments')
    player = relationship('Player', backref='ecs_fc_sub_assignments')
    assigner = relationship('User', backref='ecs_fc_sub_assignments_made')
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert assignment to dictionary format."""
        return {
            'id': self.id,
            'request_id': self.request_id,
            'player_id': self.player_id,
            'player_name': self.player.name if self.player else None,
            'assigned_by': self.assigned_by,
            'assigner_name': self.assigner.username if self.assigner else None,
            'position_assigned': self.position_assigned,
            'notes': self.notes,
            'notification_sent': self.notification_sent,
            'assigned_at': self.assigned_at.isoformat() if self.assigned_at else None
        }


class EcsFcSubPool(db.Model):
    """
    Model tracking players who are in the ECS FC substitute pool.
    
    This is separate from roles to allow for more granular control
    and preferences specific to substitute availability.
    """
    __tablename__ = 'ecs_fc_sub_pool'
    
    id = Column(Integer, primary_key=True)
    player_id = Column(Integer, ForeignKey('player.id'), nullable=False, unique=True)
    
    # Availability preferences
    is_active = Column(Boolean, nullable=False, default=True)
    preferred_positions = Column(String(255), nullable=True)
    max_matches_per_week = Column(Integer, nullable=True)
    
    # Location preferences
    preferred_locations = Column(Text, nullable=True)  # JSON array of locations
    max_travel_distance = Column(Integer, nullable=True)  # in miles
    
    # Notification preferences specific to sub requests
    sms_for_sub_requests = Column(Boolean, nullable=False, default=True)
    discord_for_sub_requests = Column(Boolean, nullable=False, default=True)
    email_for_sub_requests = Column(Boolean, nullable=False, default=True)
    
    # Stats tracking
    requests_received = Column(Integer, nullable=False, default=0)
    requests_accepted = Column(Integer, nullable=False, default=0)
    matches_played = Column(Integer, nullable=False, default=0)
    
    # Timestamps
    joined_pool_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_active_at = Column(DateTime, nullable=True)
    
    # Relationships
    player = relationship('Player', backref='ecs_fc_sub_pool_membership', uselist=False)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format."""
        return {
            'id': self.id,
            'player_id': self.player_id,
            'player_name': self.player.name if self.player else None,
            'is_active': self.is_active,
            'preferred_positions': self.preferred_positions,
            'notification_preferences': {
                'sms': self.sms_for_sub_requests,
                'discord': self.discord_for_sub_requests,
                'email': self.email_for_sub_requests
            },
            'stats': {
                'requests_received': self.requests_received,
                'requests_accepted': self.requests_accepted,
                'matches_played': self.matches_played
            }
        }