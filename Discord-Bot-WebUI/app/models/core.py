# app/models/core.py

"""
Core Models Module

This module contains the fundamental models for the application:
- User: User accounts and authentication
- Role: User roles for authorization  
- Permission: Granular permissions system
- League: League entity
- Season: Season entity
"""

import logging
import pyotp
from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.ext.hybrid import hybrid_property

from app.core import db
from app.models.players import player_teams, player_league

# Set up the module logger
logger = logging.getLogger(__name__)

# Association table for the many-to-many relationship between User and Role
user_roles = db.Table(
    'user_roles',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id'), primary_key=True),
    db.Column('role_id', db.Integer, db.ForeignKey('roles.id'), primary_key=True)
)

# Association table for many-to-many relationship between Role and Permission
role_permissions = db.Table(
    'role_permissions',
    db.Column('role_id', db.Integer, db.ForeignKey('roles.id')),
    db.Column('permission_id', db.Integer, db.ForeignKey('permissions.id'))
)


class League(db.Model):
    """Model representing a league."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    season_id = db.Column(db.Integer, db.ForeignKey('season.id'), nullable=False)
    season = db.relationship('Season', back_populates='leagues')
    teams = db.relationship('Team', back_populates='league', lazy='joined')
    players = db.relationship(
        'Player',
        secondary=player_teams,
        primaryjoin='League.id==Team.league_id',
        secondaryjoin='and_(Team.id==player_teams.c.team_id, Player.id==player_teams.c.player_id)',
        overlaps="teams,players",
        viewonly=True,
        backref=db.backref('associated_leagues', viewonly=True)
    )
    primary_players = db.relationship('Player', back_populates='primary_league', foreign_keys='Player.primary_league_id')
    other_players = db.relationship('Player', secondary=player_league, back_populates='other_leagues')
    users = db.relationship('User', back_populates='league')

    def to_dict(self, session=None):
        return {
            'id': self.id,
            'name': self.name,
            'season_id': self.season_id,
        }

    def __repr__(self):
        return f'<League {self.name}>'


class User(UserMixin, db.Model):
    """Model representing a user in the system."""
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    
    # Encrypted PII fields
    encrypted_email = db.Column(db.Text, nullable=True)
    email_hash = db.Column(db.String(64), nullable=True, index=True)  # For searching encrypted emails
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp(), nullable=False)
    updated_at = db.Column(db.DateTime, default=db.func.current_timestamp(), onupdate=db.func.current_timestamp(), nullable=False)
    is_approved = db.Column(db.Boolean, default=False, nullable=False)
    email_notifications = db.Column(db.Boolean, default=True)
    sms_notifications = db.Column(db.Boolean, default=True)
    sms_confirmation_code = db.Column(db.String(6), nullable=True)
    discord_notifications = db.Column(db.Boolean, default=True)
    profile_visibility = db.Column(db.String(20), default='everyone')
    notifications = db.relationship('Notification', back_populates='user', lazy='select')
    has_completed_onboarding = db.Column(db.Boolean, default=False)
    has_completed_tour = db.Column(db.Boolean, default=False)
    has_skipped_profile_creation = db.Column(db.Boolean, default=False)
    league_id = db.Column(db.Integer, db.ForeignKey('league.id'), nullable=True)
    league = db.relationship('League', back_populates='users')
    is_2fa_enabled = db.Column(db.Boolean, default=False)
    totp_secret = db.Column(db.String(32), nullable=True)
    roles = db.relationship('Role', secondary=user_roles, back_populates='users')
    player = db.relationship('Player', back_populates='user', uselist=False)
    stat_change_logs = db.relationship('StatChangeLog', back_populates='user', cascade='all, delete-orphan')
    stat_audits = db.relationship('PlayerStatAudit', back_populates='user', cascade='all, delete-orphan')
    feedbacks = db.relationship('Feedback', back_populates='user', lazy='dynamic')
    notes = db.relationship('Note', back_populates='author', lazy=True)
    last_login = db.Column(db.DateTime, default=datetime.utcnow)
    feedback_replies = db.relationship('FeedbackReply', back_populates='user', lazy=True)
    device_tokens = db.relationship('DeviceToken', back_populates='user', lazy=True)
    
    # User approval fields
    approval_status = db.Column(db.String(20), nullable=False, default='pending')
    approval_league = db.Column(db.String(50), nullable=True)
    approved_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    approval_notes = db.Column(db.Text, nullable=True)
    
    # Discord onboarding fields
    preferred_league = db.Column(db.String(50), nullable=True)
    discord_join_detected_at = db.Column(db.DateTime, nullable=True)
    bot_interaction_status = db.Column(db.String(20), nullable=True, default='not_contacted')
    league_selection_method = db.Column(db.String(20), nullable=True)
    bot_interaction_attempts = db.Column(db.Integer, nullable=True, default=0)
    last_bot_contact_at = db.Column(db.DateTime, nullable=True)
    bot_response_received_at = db.Column(db.DateTime, nullable=True)
    
    # Waitlist tracking
    waitlist_joined_at = db.Column(db.DateTime, nullable=True)
    
    # Approval relationships
    approved_by_user = db.relationship('User', remote_side=[id], backref='approved_users')

    @hybrid_property
    def email(self):
        """Get decrypted email."""
        if self.encrypted_email:
            from app.utils.pii_encryption import decrypt_value
            return decrypt_value(self.encrypted_email)
        return None

    @email.setter
    def email(self, value):
        """Set encrypted email."""
        if value:
            from app.utils.pii_encryption import encrypt_value, create_hash
            self.encrypted_email = encrypt_value(value)
            self.email_hash = create_hash(value)
        else:
            self.encrypted_email = None
            self.email_hash = None

    def generate_totp_secret(self):
        """Generate a TOTP secret for 2FA."""
        self.totp_secret = pyotp.random_base32()

    def verify_totp(self, token):
        """Verify a provided 2FA token."""
        totp = pyotp.TOTP(self.totp_secret)
        return totp.verify(token)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def has_role(self, role_name):
        return any(role.name == role_name for role in self.roles or [])

    def has_permission(self, permission_name):
        return any(
            perm.name == permission_name
            for role in self.roles or []
            for perm in role.permissions or []
        )

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'is_approved': self.is_approved,
            'roles': [role.name for role in self.roles],
            'has_completed_onboarding': self.has_completed_onboarding,
            'league_id': self.league_id
        }


class Role(db.Model):
    """Model representing a user role."""
    __tablename__ = 'roles'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.String(255), nullable=True)

    users = db.relationship('User', secondary=user_roles, back_populates='roles')
    permissions = db.relationship('Permission', secondary=role_permissions, back_populates='roles')

    def __repr__(self):
        return f'<Role {self.name}>'


class Permission(db.Model):
    """Model representing a permission."""
    __tablename__ = 'permissions'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.String(255), nullable=True)
    roles = db.relationship('Role', secondary=role_permissions, back_populates='permissions')

    def __repr__(self):
        return f'<Permission {self.name}>'


class Season(db.Model):
    """Model representing a season."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    league_type = db.Column(db.String(50), nullable=False)
    is_current = db.Column(db.Boolean, default=False, nullable=False)
    leagues = db.relationship('League', back_populates='season', lazy=True)
    player_stats = db.relationship('PlayerSeasonStats', back_populates='season', lazy=True, cascade="all, delete-orphan")
    stat_change_logs = db.relationship('StatChangeLog', back_populates='season', cascade='all, delete-orphan')
    stat_audits = db.relationship('PlayerStatAudit', back_populates='season', cascade='all, delete-orphan')
    player_assignments = db.relationship(
        'PlayerTeamSeason',
        back_populates='season',
        cascade='all, delete-orphan'
    )

    def to_dict(self, session=None):
        return {
            'id': self.id,
            'name': self.name,
            'league_type': self.league_type,
            'is_current': self.is_current,
        }

    def __repr__(self):
        return f'<Season {self.name} ({self.league_type})>'


class DuplicateRegistrationAlert(db.Model):
    """Model for tracking potential duplicate registrations for admin review."""
    __tablename__ = 'duplicate_registration_alerts'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # New registration information
    new_discord_email = db.Column(db.String(255), nullable=False)
    
    # New encrypted fields for verification emails
    encrypted_discord_email = db.Column(db.Text, nullable=True)  # Will replace new_discord_email
    new_discord_username = db.Column(db.String(100), nullable=True)
    new_name = db.Column(db.String(255), nullable=True)
    new_phone = db.Column(db.String(20), nullable=True)
    
    # New encrypted fields for phone numbers
    encrypted_phone = db.Column(db.Text, nullable=True)  # Will replace new_phone
    phone_hash = db.Column(db.String(64), nullable=True, index=True)  # For searching encrypted phones
    
    # Existing player information
    existing_player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False)
    existing_player_name = db.Column(db.String(255), nullable=True)
    
    # Match details
    match_type = db.Column(db.String(50), nullable=False)  # 'phone', 'name', 'email_domain_name'
    confidence_score = db.Column(db.Float, nullable=False, default=0.0)
    details = db.Column(db.Text, nullable=True)  # JSON string with additional details
    
    # Status and timestamps
    status = db.Column(db.String(20), nullable=False, default='pending')  # 'pending', 'resolved', 'ignored'
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    resolved_at = db.Column(db.DateTime, nullable=True)
    resolved_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    resolution_action = db.Column(db.String(50), nullable=True)  # 'merged', 'allowed', 'blocked'
    resolution_notes = db.Column(db.Text, nullable=True)
    
    # Relationships
    existing_player = db.relationship('Player', foreign_keys=[existing_player_id], backref='duplicate_alerts')
    resolved_by = db.relationship('User', foreign_keys=[resolved_by_user_id])
    
    def to_dict(self):
        return {
            'id': self.id,
            'new_discord_email': self.new_discord_email,
            'new_discord_username': self.new_discord_username,
            'new_name': self.new_name,
            'new_phone': self.new_phone,
            'existing_player_id': self.existing_player_id,
            'existing_player_name': self.existing_player_name,
            'match_type': self.match_type,
            'confidence_score': self.confidence_score,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'resolved_at': self.resolved_at.isoformat() if self.resolved_at else None,
            'resolution_action': self.resolution_action,
            'resolution_notes': self.resolution_notes
        }
    
    def __repr__(self):
        return f'<DuplicateRegistrationAlert {self.id}: {self.new_name} -> Player {self.existing_player_id}>'


class DiscordBotStatus(db.Model):
    """Model for tracking Discord bot online status for smart sync."""
    __tablename__ = 'discord_bot_status'
    
    id = db.Column(db.Integer, primary_key=True)
    instance_type = db.Column(db.String(50), nullable=False, unique=True)  # 'main', 'backup', etc.
    instance_id = db.Column(db.String(100), nullable=False)  # Unique instance identifier
    last_online = db.Column(db.DateTime, nullable=False)  # When bot was last known online
    last_updated = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)  # When this record was updated
    
    def to_dict(self):
        return {
            'id': self.id,
            'instance_type': self.instance_type,
            'instance_id': self.instance_id,
            'last_online': self.last_online.isoformat() if self.last_online else None,
            'last_updated': self.last_updated.isoformat() if self.last_updated else None
        }
    
    def __repr__(self):
        return f'<DiscordBotStatus {self.instance_type}: {self.instance_id}>'