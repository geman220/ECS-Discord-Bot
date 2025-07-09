"""
Unified Substitute Pool System Models

This module contains the models for the unified substitute pool system
that supports ECS FC, Classic, and Premier leagues.
"""

import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

from sqlalchemy import Column, Integer, String, Boolean, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship, backref
from sqlalchemy.ext.hybrid import hybrid_property

from app.core import db

logger = logging.getLogger(__name__)


class SubstitutePool(db.Model):
    """
    Unified substitute pool for all league types.
    
    This model replaces the ECS FC specific pool and supports
    Classic, Premier, and ECS FC substitute management.
    """
    __tablename__ = 'substitute_pools'
    
    id = Column(Integer, primary_key=True)
    player_id = Column(Integer, ForeignKey('player.id', ondelete='CASCADE'), nullable=False)
    league_type = Column(String(50), nullable=False)  # 'ECS FC', 'Classic', 'Premier'
    is_active = Column(Boolean, nullable=False, default=True)
    preferred_positions = Column(Text)
    max_matches_per_week = Column(Integer, default=3)
    notes = Column(Text)
    
    # Notification preferences
    sms_for_sub_requests = Column(Boolean, nullable=False, default=True)
    discord_for_sub_requests = Column(Boolean, nullable=False, default=True)
    email_for_sub_requests = Column(Boolean, nullable=False, default=True)
    
    # Statistics
    requests_received = Column(Integer, nullable=False, default=0)
    requests_accepted = Column(Integer, nullable=False, default=0)
    matches_played = Column(Integer, nullable=False, default=0)
    
    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_active_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    
    # Admin tracking
    approved_by = Column(Integer, ForeignKey('users.id'), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    
    # Relationships
    player = relationship('Player', backref=backref('substitute_pools', lazy='dynamic'))
    approver = relationship('User', foreign_keys=[approved_by])
    
    __table_args__ = (
        db.UniqueConstraint('player_id', 'league_type'),
    )
    
    @hybrid_property
    def acceptance_rate(self) -> float:
        """Calculate the acceptance rate for this substitute."""
        if self.requests_received == 0:
            return 0.0
        return (self.requests_accepted / self.requests_received) * 100
    
    @hybrid_property
    def is_eligible(self) -> bool:
        """Check if player is eligible for this league type based on roles."""
        if not self.player or not self.player.user:
            return False
        
        role_mapping = {
            'ECS FC': 'ECS FC Sub',
            'Classic': 'Classic Sub',
            'Premier': 'Premier Sub'
        }
        
        required_role = role_mapping.get(self.league_type)
        if not required_role:
            return False
        
        return any(role.name == required_role for role in self.player.user.roles)
    
    def to_dict(self, include_stats: bool = False) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        result = {
            'id': self.id,
            'player_id': self.player_id,
            'player_name': self.player.name if self.player else None,
            'league_type': self.league_type,
            'is_active': self.is_active,
            'preferred_positions': self.preferred_positions,
            'max_matches_per_week': self.max_matches_per_week,
            'notes': self.notes,
            'sms_for_sub_requests': self.sms_for_sub_requests,
            'discord_for_sub_requests': self.discord_for_sub_requests,
            'email_for_sub_requests': self.email_for_sub_requests,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_active_at': self.last_active_at.isoformat() if self.last_active_at else None,
            'approved_by': self.approved_by,
            'approved_at': self.approved_at.isoformat() if self.approved_at else None,
            'is_eligible': self.is_eligible
        }
        
        if include_stats:
            result.update({
                'requests_received': self.requests_received,
                'requests_accepted': self.requests_accepted,
                'matches_played': self.matches_played,
                'acceptance_rate': self.acceptance_rate
            })
        
        return result
    
    def activate(self, approved_by_user_id: int) -> None:
        """Activate this substitute in the pool."""
        self.is_active = True
        self.approved_by = approved_by_user_id
        self.approved_at = datetime.utcnow()
        self.last_active_at = datetime.utcnow()
    
    def deactivate(self) -> None:
        """Deactivate this substitute from the pool."""
        self.is_active = False
        self.last_active_at = datetime.utcnow()
    
    def __repr__(self):
        return f'<SubstitutePool {self.player.name if self.player else "Unknown"} - {self.league_type}>'


class SubstitutePoolHistory(db.Model):
    """
    Audit trail for substitute pool changes.
    """
    __tablename__ = 'substitute_pool_history'
    
    id = Column(Integer, primary_key=True)
    pool_id = Column(Integer, ForeignKey('substitute_pools.id', ondelete='CASCADE'), nullable=False)
    action = Column(String(50), nullable=False)  # 'ADDED', 'REMOVED', 'ACTIVATED', 'DEACTIVATED', 'UPDATED'
    previous_status = Column(JSON)
    new_status = Column(JSON)
    performed_by = Column(Integer, ForeignKey('users.id'), nullable=False)
    performed_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    notes = Column(Text)
    
    # Relationships
    pool = relationship('SubstitutePool', backref=backref('history', lazy='dynamic'))
    performer = relationship('User', foreign_keys=[performed_by])
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            'id': self.id,
            'pool_id': self.pool_id,
            'action': self.action,
            'previous_status': self.previous_status,
            'new_status': self.new_status,
            'performed_by': self.performed_by,
            'performed_at': self.performed_at.isoformat() if self.performed_at else None,
            'notes': self.notes,
            'performer_name': self.performer.username if self.performer else None
        }
    
    def __repr__(self):
        return f'<SubstitutePoolHistory {self.action} - {self.performed_at}>'


class SubstituteRequest(db.Model):
    """
    Unified substitute request for all league types.
    """
    __tablename__ = 'substitute_requests'
    
    id = Column(Integer, primary_key=True)
    league_type = Column(String(50), nullable=False)  # 'ECS FC', 'Classic', 'Premier'
    match_id = Column(Integer, nullable=True)  # Can be null for generic requests
    team_id = Column(Integer, ForeignKey('team.id'), nullable=False)
    requested_by = Column(Integer, ForeignKey('users.id'), nullable=False)
    positions_needed = Column(Text)
    substitutes_needed = Column(Integer, nullable=False, default=1)  # Number of substitutes needed
    gender_preference = Column(String(20), nullable=True)  # 'male', 'female', or None for any
    notes = Column(Text)
    status = Column(String(20), nullable=False, default='OPEN')  # 'OPEN', 'FILLED', 'CANCELLED'
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    filled_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
    
    # Relationships
    team = relationship('Team', backref=backref('substitute_requests', lazy='dynamic'))
    requester = relationship('User', foreign_keys=[requested_by])
    
    def to_dict(self, include_responses: bool = False) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        assigned_count = len(self.assignments) if self.assignments else 0
        result = {
            'id': self.id,
            'league_type': self.league_type,
            'match_id': self.match_id,
            'team_id': self.team_id,
            'team_name': self.team.name if self.team else None,
            'requested_by': self.requested_by,
            'requester_name': self.requester.username if self.requester else None,
            'positions_needed': self.positions_needed,
            'substitutes_needed': self.substitutes_needed,
            'notes': self.notes,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'filled_at': self.filled_at.isoformat() if self.filled_at else None,
            'cancelled_at': self.cancelled_at.isoformat() if self.cancelled_at else None,
            'assigned_count': assigned_count,
            'assignments_remaining': self.substitutes_needed - assigned_count
        }
        
        if include_responses:
            result['responses'] = [r.to_dict() for r in self.responses]
            result['assignments'] = [a.to_dict() for a in self.assignments]
        
        return result
    
    def __repr__(self):
        return f'<SubstituteRequest {self.league_type} - {self.status}>'


class SubstituteResponse(db.Model):
    """
    Player response to a substitute request.
    """
    __tablename__ = 'substitute_responses'
    
    id = Column(Integer, primary_key=True)
    request_id = Column(Integer, ForeignKey('substitute_requests.id', ondelete='CASCADE'), nullable=False)
    player_id = Column(Integer, ForeignKey('player.id', ondelete='CASCADE'), nullable=False)
    is_available = Column(Boolean, nullable=False, default=False)
    response_text = Column(Text)
    response_method = Column(String(20), nullable=False, default='UNKNOWN')  # 'SMS', 'DISCORD', 'EMAIL', 'WEB'
    notification_sent_at = Column(DateTime, nullable=True)
    responded_at = Column(DateTime, nullable=True)
    notification_methods = Column(Text)
    
    # Relationships
    request = relationship('SubstituteRequest', backref=backref('responses', lazy='select'))
    player = relationship('Player', backref=backref('substitute_responses', lazy='dynamic'))
    
    __table_args__ = (
        db.UniqueConstraint('request_id', 'player_id'),
    )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            'id': self.id,
            'request_id': self.request_id,
            'player_id': self.player_id,
            'player_name': self.player.name if self.player else None,
            'is_available': self.is_available,
            'response_text': self.response_text,
            'response_method': self.response_method,
            'notification_sent_at': self.notification_sent_at.isoformat() if self.notification_sent_at else None,
            'responded_at': self.responded_at.isoformat() if self.responded_at else None,
            'notification_methods': self.notification_methods
        }
    
    def __repr__(self):
        return f'<SubstituteResponse {self.player.name if self.player else "Unknown"} - {"Available" if self.is_available else "Not Available"}>'


class SubstituteAssignment(db.Model):
    """
    Assignment of a substitute to a request.
    """
    __tablename__ = 'substitute_assignments'
    
    id = Column(Integer, primary_key=True)
    request_id = Column(Integer, ForeignKey('substitute_requests.id', ondelete='CASCADE'), nullable=False)
    player_id = Column(Integer, ForeignKey('player.id', ondelete='CASCADE'), nullable=False)
    assigned_by = Column(Integer, ForeignKey('users.id'), nullable=False)
    position_assigned = Column(Text)
    notes = Column(Text)
    notification_sent = Column(Boolean, nullable=False, default=False)
    notification_sent_at = Column(DateTime, nullable=True)
    notification_methods = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    
    # Relationships
    request = relationship('SubstituteRequest', backref=backref('assignments', lazy='select'))
    player = relationship('Player', backref=backref('substitute_assignments', lazy='dynamic'))
    assigner = relationship('User', foreign_keys=[assigned_by])
    
    __table_args__ = (
        db.UniqueConstraint('request_id', 'player_id'),
    )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
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
            'notification_sent_at': self.notification_sent_at.isoformat() if self.notification_sent_at else None,
            'notification_methods': self.notification_methods,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
    
    def __repr__(self):
        return f'<SubstituteAssignment {self.player.name if self.player else "Unknown"} - {self.position_assigned or "No Position"}>'


# Helper functions for common queries
def get_eligible_players(league_type: str, session=None) -> List[Any]:
    """
    Get players eligible for a specific league type based on their roles.
    
    Args:
        league_type: The league type ('ECS FC', 'Classic', 'Premier')
        session: Database session (optional)
        
    Returns:
        List of Player objects with the appropriate substitute role
    """
    if session is None:
        session = db.session
    
    from app.models import Player, User, Role
    
    role_mapping = {
        'ECS FC': 'ECS FC Sub',
        'Classic': 'Classic Sub',
        'Premier': 'Premier Sub'
    }
    
    required_role = role_mapping.get(league_type)
    if not required_role:
        return []
    
    return session.query(Player).join(
        User, Player.user_id == User.id
    ).join(
        User.roles
    ).filter(
        Role.name == required_role
    ).all()


def get_active_substitutes(league_type: str, session=None, gender_filter: str = None) -> List[SubstitutePool]:
    """
    Get all active substitutes for a specific league type, optionally filtered by gender.
    
    Args:
        league_type: The league type ('ECS FC', 'Classic', 'Premier')
        session: Database session (optional)
        gender_filter: Gender filter ('male', 'female', or None for all)
        
    Returns:
        List of active SubstitutePool objects
    """
    if session is None:
        session = db.session
    
    from app.models import Player
    
    query = session.query(SubstitutePool).join(Player).filter(
        SubstitutePool.league_type == league_type,
        SubstitutePool.is_active == True
    )
    
    if gender_filter:
        if gender_filter.lower() == 'male':
            # Only include he/him pronouns for male-specific spots
            query = query.filter(
                Player.pronouns.ilike('%he/him%')
            )
        elif gender_filter.lower() == 'female':
            # Only include she/her pronouns for female-specific spots
            query = query.filter(
                Player.pronouns.ilike('%she/her%')
            )
        # Note: they/them and null pronouns get both male and female notifications
        # but are not included in gender-specific filters
    
    return query.all()


def log_pool_action(pool_id: int, action: str, performed_by: int, notes: str = None, 
                   previous_status: Dict = None, new_status: Dict = None, session=None) -> None:
    """
    Log an action in the substitute pool history.
    
    Args:
        pool_id: ID of the substitute pool
        action: The action performed
        performed_by: User ID who performed the action
        notes: Optional notes about the action
        previous_status: Previous status (for updates)
        new_status: New status (for updates)
        session: Database session (optional)
    """
    if session is None:
        session = db.session
    
    history_entry = SubstitutePoolHistory(
        pool_id=pool_id,
        action=action,
        performed_by=performed_by,
        notes=notes,
        previous_status=previous_status,
        new_status=new_status
    )
    
    session.add(history_entry)
    logger.info(f"Logged substitute pool action: {action} for pool {pool_id} by user {performed_by}")