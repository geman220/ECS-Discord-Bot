# app/models/substitutes.py

"""
Substitute Models Module

This module contains models for the substitute system:
- EcsFcSubRequest: ECS FC substitute requests
- EcsFcSubResponse: ECS FC substitute responses
- EcsFcSubAssignment: ECS FC substitute assignments
- EcsFcSubPool: ECS FC substitute pool
- SubstitutePool: General substitute pool
- SubstitutePoolHistory: History of substitute pool actions
- SubstituteRequest: General substitute requests
- SubstituteResponse: General substitute responses
- SubstituteAssignment: General substitute assignments
"""

from datetime import datetime
from sqlalchemy import JSON, DateTime, Boolean, Date, Time, String, Text, Integer, ForeignKey
from sqlalchemy.orm import relationship

from app.core import db


class EcsFcSubRequest(db.Model):
    """Model for ECS FC substitute requests."""
    __tablename__ = 'ecs_fc_sub_requests'
    
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('ecs_fc_matches.id'), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    requested_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    positions_needed = db.Column(db.String(255), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default='OPEN')
    substitutes_needed = db.Column(db.Integer, nullable=False, default=1)
    filled_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    match = db.relationship('EcsFcMatch', backref='sub_requests')
    team = db.relationship('Team', backref='ecs_fc_sub_requests')
    requester = db.relationship('User', foreign_keys=[requested_by], backref='ecs_fc_sub_requests')
    responses = db.relationship('EcsFcSubResponse', back_populates='request', cascade='all, delete-orphan')
    assignment = db.relationship('EcsFcSubAssignment', back_populates='request', uselist=False, cascade='all, delete-orphan')


class EcsFcSubResponse(db.Model):
    """Model for ECS FC substitute responses."""
    __tablename__ = 'ecs_fc_sub_responses'
    
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey('ecs_fc_sub_requests.id'), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False)
    is_available = db.Column(db.Boolean, nullable=False)
    response_method = db.Column(db.String(20), nullable=False)
    response_text = db.Column(db.Text, nullable=True)
    notification_sent_at = db.Column(db.DateTime, nullable=True)
    notification_methods = db.Column(db.String(100), nullable=True)
    responded_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    # Relationships
    request = db.relationship('EcsFcSubRequest', back_populates='responses')
    player = db.relationship('Player', backref='ecs_fc_sub_responses')
    
    __table_args__ = (
        db.UniqueConstraint('request_id', 'player_id', name='uq_ecs_fc_sub_response_request_player'),
    )


class EcsFcSubAssignment(db.Model):
    """Model for ECS FC substitute assignments."""
    __tablename__ = 'ecs_fc_sub_assignments'
    
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey('ecs_fc_sub_requests.id'), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False)
    assigned_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    position_assigned = db.Column(db.String(100), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    notification_sent = db.Column(db.Boolean, nullable=False, default=False)
    notification_sent_at = db.Column(db.DateTime, nullable=True)
    notification_methods = db.Column(db.String(100), nullable=True)
    assigned_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    # Relationships
    request = db.relationship('EcsFcSubRequest', back_populates='assignment')
    player = db.relationship('Player', backref='ecs_fc_sub_assignments')
    assigner = db.relationship('User', foreign_keys=[assigned_by], backref='ecs_fc_sub_assignments')
    
    __table_args__ = (
        db.UniqueConstraint('request_id', 'player_id', name='uq_ecs_fc_sub_assignment_request_player'),
    )


class EcsFcSubPool(db.Model):
    """Model for ECS FC substitute pool."""
    __tablename__ = 'ecs_fc_sub_pool'
    
    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False, unique=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    preferred_positions = db.Column(db.String(255), nullable=True)
    max_matches_per_week = db.Column(db.Integer, nullable=True)
    preferred_locations = db.Column(db.Text, nullable=True)
    max_travel_distance = db.Column(db.Integer, nullable=True)
    sms_for_sub_requests = db.Column(db.Boolean, nullable=False, default=True)
    discord_for_sub_requests = db.Column(db.Boolean, nullable=False, default=True)
    email_for_sub_requests = db.Column(db.Boolean, nullable=False, default=True)
    requests_received = db.Column(db.Integer, nullable=False, default=0)
    requests_accepted = db.Column(db.Integer, nullable=False, default=0)
    matches_played = db.Column(db.Integer, nullable=False, default=0)
    joined_pool_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    last_active_at = db.Column(db.DateTime, nullable=True)
    
    # Relationships
    player = db.relationship('Player', backref='ecs_fc_sub_pool')


class SubstitutePool(db.Model):
    """Model for general substitute pool."""
    __tablename__ = 'substitute_pools'
    
    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False, unique=True)
    league_type = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    preferred_positions = db.Column(db.Text, nullable=True)
    max_matches_per_week = db.Column(db.Integer, nullable=True, default=3)
    notes = db.Column(db.Text, nullable=True)
    preferred_locations = db.Column(db.Text, nullable=True)
    max_travel_distance = db.Column(db.Integer, nullable=True)
    sms_for_sub_requests = db.Column(db.Boolean, nullable=False, default=True)
    discord_for_sub_requests = db.Column(db.Boolean, nullable=False, default=True)
    email_for_sub_requests = db.Column(db.Boolean, nullable=False, default=True)
    requests_received = db.Column(db.Integer, nullable=False, default=0)
    requests_accepted = db.Column(db.Integer, nullable=False, default=0)
    matches_played = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    last_active_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    approved_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    league_id = db.Column(db.Integer, db.ForeignKey('league.id'), nullable=True)
    joined_pool_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow)
    
    # Relationships
    player = db.relationship('Player', backref='substitute_pools')
    league = db.relationship('League', backref='substitute_pools')
    approver = db.relationship('User', foreign_keys=[approved_by])


class SubstitutePoolHistory(db.Model):
    """Model for substitute pool history."""
    __tablename__ = 'substitute_pool_history'
    
    id = db.Column(db.Integer, primary_key=True)
    pool_id = db.Column(db.Integer, db.ForeignKey('substitute_pools.id'), nullable=False)
    action = db.Column(db.String(50), nullable=False)
    previous_status = db.Column(db.JSON, nullable=True)
    new_status = db.Column(db.JSON, nullable=True)
    performed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    performed_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    notes = db.Column(db.Text, nullable=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=True)
    league_id = db.Column(db.Integer, db.ForeignKey('league.id'), nullable=True)
    
    # Relationships
    player = db.relationship('Player', backref='substitute_pool_history')
    league = db.relationship('League', backref='substitute_pool_history')
    pool = db.relationship('SubstitutePool', backref='history')
    performer = db.relationship('User', backref='substitute_pool_history')
    
    def to_dict(self):
        return {
            'id': self.id,
            'pool_id': self.pool_id,
            'action': self.action,
            'previous_status': self.previous_status,
            'new_status': self.new_status,
            'performed_by': self.performed_by,
            'performed_at': self.performed_at.isoformat() if self.performed_at else None,
            'notes': self.notes,
            'player_id': self.player_id,
            'league_id': self.league_id,
            'player_name': self.player.name if self.player else None,
            'performer_name': self.performer.username if self.performer else None
        }


class SubstituteRequest(db.Model):
    """Model for general substitute requests."""
    __tablename__ = 'substitute_requests'
    
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('matches.id'), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    requested_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    positions_needed = db.Column(db.String(255), nullable=True)
    gender_preference = db.Column(db.String(20), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default='OPEN')
    substitutes_needed = db.Column(db.Integer, nullable=False, default=1)
    filled_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    match = db.relationship('Match', backref='substitute_requests')
    team = db.relationship('Team', backref='substitute_requests')
    requester = db.relationship('User', foreign_keys=[requested_by], backref='substitute_requests')
    responses = db.relationship('SubstituteResponse', back_populates='request', cascade='all, delete-orphan')
    assignments = db.relationship('SubstituteAssignment', back_populates='request', cascade='all, delete-orphan')


class SubstituteResponse(db.Model):
    """Model for general substitute responses."""
    __tablename__ = 'substitute_responses'
    
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey('substitute_requests.id'), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False)
    is_available = db.Column(db.Boolean, nullable=False)
    response_method = db.Column(db.String(20), nullable=False)
    response_text = db.Column(db.Text, nullable=True)
    notification_sent_at = db.Column(db.DateTime, nullable=True)
    notification_methods = db.Column(db.String(100), nullable=True)
    responded_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    # Relationships
    request = db.relationship('SubstituteRequest', back_populates='responses')
    player = db.relationship('Player', backref='substitute_responses')
    
    __table_args__ = (
        db.UniqueConstraint('request_id', 'player_id', name='uq_substitute_response_request_player'),
    )


class SubstituteAssignment(db.Model):
    """Model for general substitute assignments."""
    __tablename__ = 'substitute_assignments'
    
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey('substitute_requests.id'), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False)
    assigned_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    position_assigned = db.Column(db.String(100), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    notification_sent = db.Column(db.Boolean, nullable=False, default=False)
    notification_sent_at = db.Column(db.DateTime, nullable=True)
    notification_methods = db.Column(db.String(100), nullable=True)
    assigned_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    # Relationships
    request = db.relationship('SubstituteRequest', back_populates='assignments')
    player = db.relationship('Player', backref='substitute_assignments')
    assigner = db.relationship('User', foreign_keys=[assigned_by], backref='substitute_assignments')
    
    __table_args__ = (
        db.UniqueConstraint('request_id', 'player_id', name='uq_substitute_assignment_request_player'),
    )


def get_eligible_players(league_type, positions=None, gender=None, session=None):
    """Get eligible players for substitute requests by league type."""
    if session is None:
        session = db.session
    
    # Map league types to role names
    role_mapping = {
        'ECS FC': 'ECS FC Sub',
        'Classic': 'Classic Sub', 
        'Premier': 'Premier Sub'
    }
    
    required_role = role_mapping.get(league_type)
    if not required_role:
        return []
    
    # Find all players with the required role
    from app.models import Player, User, Role
    from sqlalchemy.orm import joinedload
    
    players_with_role = session.query(Player).options(
        joinedload(Player.user).joinedload(User.roles)
    ).join(User).join(User.roles).filter(
        Role.name == required_role
    ).all()
    
    # Apply gender filter if specified
    if gender:
        players_with_role = [
            p for p in players_with_role 
            if p.pronouns and gender.lower() in p.pronouns.lower()
        ]
    
    return players_with_role


def get_active_substitutes(league_type, session=None, gender_filter=None):
    """Get all active substitutes for a league type."""
    if session is None:
        session = db.session
    
    # Map league types to role names
    role_mapping = {
        'ECS FC': 'ECS FC Sub',
        'Classic': 'Classic Sub', 
        'Premier': 'Premier Sub'
    }
    
    required_role = role_mapping.get(league_type)
    if not required_role:
        return []
    
    # Find all active substitute pool entries for players with the required role
    from app.models import Player, User, Role
    from sqlalchemy.orm import joinedload
    
    # First, try to get existing SubstitutePool entries
    existing_pools = session.query(SubstitutePool).options(
        joinedload(SubstitutePool.player).joinedload(Player.user).joinedload(User.roles)
    ).join(Player).join(User).join(User.roles).filter(
        Role.name == required_role,
        SubstitutePool.is_active == True
    )
    
    # Apply gender filter if specified
    if gender_filter:
        existing_pools = existing_pools.filter(
            Player.pronouns.ilike(f'%{gender_filter}%')
        )
    
    return existing_pools.all()


def log_pool_action(player_id, league_id, action, notes=None, performed_by=None, pool_id=None, session=None):
    """Log an action in the substitute pool history."""
    if session is None:
        session = db.session
    
    history_entry = SubstitutePoolHistory(
        player_id=player_id,
        league_id=league_id,
        pool_id=pool_id,
        action=action,
        notes=notes,
        performed_by=performed_by
    )
    session.add(history_entry)
    # Don't commit here - let the calling code handle the transaction
    return history_entry