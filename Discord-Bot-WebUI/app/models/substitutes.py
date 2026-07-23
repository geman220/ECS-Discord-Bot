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

from datetime import datetime, timedelta
import secrets
from sqlalchemy import JSON, DateTime, Boolean, Date, Time, String, Text, Integer, ForeignKey
from sqlalchemy.orm import relationship

from app.core import db


class EcsFcSubRequest(db.Model):
    """Model for ECS FC substitute requests."""
    __tablename__ = 'ecs_fc_sub_requests'
    __table_args__ = (
        db.Index('idx_ecs_fc_sub_requests_match_id_status', 'match_id', 'status'),
        db.Index('idx_ecs_fc_sub_requests_status_created_at', 'status', 'created_at'),
        db.Index('idx_ecs_fc_sub_requests_team_id_status', 'team_id', 'status'),
    )

    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('ecs_fc_matches.id'), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    requested_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    positions_needed = db.Column(db.String(255), nullable=True)
    # 'male' | 'female' | None. Parity with SubstituteRequest.gender_preference so
    # ECS FC coach/admin requests can carry an M/F preference into the pool filter.
    gender_preference = db.Column(db.String(255), nullable=True)
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
    assignments = db.relationship('EcsFcSubAssignment', back_populates='request', cascade='all, delete-orphan')


class EcsFcSubResponse(db.Model):
    """Model for ECS FC substitute responses."""
    __tablename__ = 'ecs_fc_sub_responses'

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey('ecs_fc_sub_requests.id'), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False)
    is_available = db.Column(db.Boolean, nullable=True)  # None = not yet responded
    response_method = db.Column(db.String(20), nullable=True)  # Nullable until they respond
    response_text = db.Column(db.Text, nullable=True)
    notification_sent_at = db.Column(db.DateTime, nullable=True)
    notification_methods = db.Column(db.String(100), nullable=True)
    responded_at = db.Column(db.DateTime, nullable=True)  # Nullable until they respond

    # RSVP token fields for secure response links
    rsvp_token = db.Column(db.String(64), unique=True, nullable=True, index=True)
    token_expires_at = db.Column(db.DateTime, nullable=True)
    token_used_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    request = db.relationship('EcsFcSubRequest', back_populates='responses')
    player = db.relationship('Player', backref='ecs_fc_sub_responses')

    __table_args__ = (
        db.UniqueConstraint('request_id', 'player_id', name='uq_ecs_fc_sub_response_request_player'),
        db.Index('idx_ecs_fc_sub_responses_player_id', 'player_id'),
    )

    def generate_token(self, expiry_hours=48):
        """Generate a secure RSVP token."""
        self.rsvp_token = secrets.token_urlsafe(32)
        self.token_expires_at = datetime.utcnow() + timedelta(hours=expiry_hours)
        return self.rsvp_token

    def is_token_valid(self):
        """Check if the token is still valid."""
        if not self.rsvp_token or not self.token_expires_at:
            return False
        return datetime.utcnow() < self.token_expires_at and self.token_used_at is None

    def mark_token_used(self):
        """Mark the token as used."""
        self.token_used_at = datetime.utcnow()


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
    # Track which methods were used for initial outreach (for confirmation routing)
    outreach_methods = db.Column(db.String(100), nullable=True)
    assigned_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    request = db.relationship('EcsFcSubRequest', back_populates='assignments')
    player = db.relationship('Player', backref='ecs_fc_sub_assignments')
    assigner = db.relationship('User', foreign_keys=[assigned_by], backref='ecs_fc_sub_assignments')

    __table_args__ = (
        db.UniqueConstraint('request_id', 'player_id', name='uq_ecs_fc_sub_assignment_request_player'),
        db.Index('idx_ecs_fc_sub_assignments_player_id', 'player_id'),
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
    push_for_sub_requests = db.Column(db.Boolean, nullable=False, default=True)
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
    
    @property
    def acceptance_rate(self):
        """Calculate acceptance rate as percentage."""
        if self.requests_received == 0:
            return 0.0
        return (self.requests_accepted / self.requests_received) * 100


class SubstitutePoolHistory(db.Model):
    """Model for substitute pool history."""
    __tablename__ = 'substitute_pool_history'
    __table_args__ = (
        db.Index('idx_substitute_pool_history_pool_id', 'pool_id'),
        db.Index('idx_substitute_pool_history_league_id', 'league_id'),
    )

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
    __table_args__ = (
        db.Index('idx_substitute_requests_match_id_team_id_status', 'match_id', 'team_id', 'status'),
        db.Index('idx_substitute_requests_team_id_status_created_at', 'team_id', 'status', 'created_at'),
        db.Index('idx_substitute_requests_status_created_at', 'status', 'created_at'),
    )

    id = db.Column(db.Integer, primary_key=True)
    league_type = db.Column(db.String(255), nullable=False)
    match_id = db.Column(db.Integer, db.ForeignKey('matches.id'), nullable=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    requested_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    positions_needed = db.Column(db.Text, nullable=True)
    gender_preference = db.Column(db.String(255), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default='OPEN')
    substitutes_needed = db.Column(db.Integer, nullable=False, default=1)
    filled_at = db.Column(db.DateTime, nullable=True)
    cancelled_at = db.Column(db.DateTime, nullable=True)
    assignments_count = db.Column(db.Integer, nullable=True, default=0)
    fulfilled_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    # Provenance: which front-end created this request and (for Discord) where.
    # 'web' = admin/coach via WebUI, 'mobile' = Flutter app, 'discord' = /subs bot command.
    source = db.Column(db.String(20), nullable=True, default='web')
    discord_channel_id = db.Column(db.String(20), nullable=True)
    discord_message_id = db.Column(db.String(20), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    match = db.relationship('Match', backref=db.backref('substitute_requests', lazy='dynamic', passive_deletes=True), passive_deletes=True)
    team = db.relationship('Team', backref=db.backref('substitute_requests', lazy='dynamic', passive_deletes=True), passive_deletes=True)
    requester = db.relationship('User', foreign_keys=[requested_by], backref='substitute_requests')
    fulfiller = db.relationship('User', foreign_keys=[fulfilled_by], backref='fulfilled_substitute_requests')
    responses = db.relationship('SubstituteResponse', back_populates='request', cascade='all, delete-orphan')
    assignments = db.relationship('SubstituteAssignment', back_populates='request', cascade='all, delete-orphan')


class SubstituteResponse(db.Model):
    """Model for general substitute responses."""
    __tablename__ = 'substitute_responses'

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey('substitute_requests.id'), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False)
    is_available = db.Column(db.Boolean, nullable=True)  # None = not yet responded
    response_method = db.Column(db.String(20), nullable=True)  # Nullable until they respond
    response_text = db.Column(db.Text, nullable=True)
    notification_sent_at = db.Column(db.DateTime, nullable=True)
    notification_methods = db.Column(db.String(100), nullable=True)
    responded_at = db.Column(db.DateTime, nullable=True)  # Nullable until they respond

    # RSVP token fields for secure response links
    rsvp_token = db.Column(db.String(64), unique=True, nullable=True, index=True)
    token_expires_at = db.Column(db.DateTime, nullable=True)
    token_used_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    request = db.relationship('SubstituteRequest', back_populates='responses')
    player = db.relationship('Player', backref='substitute_responses')

    __table_args__ = (
        db.UniqueConstraint('request_id', 'player_id', name='uq_substitute_response_request_player'),
        db.Index('idx_substitute_responses_player_id_notification_sent_at', 'player_id', db.text('notification_sent_at DESC')),
    )

    def generate_token(self, expiry_hours=48):
        """Generate a secure RSVP token."""
        self.rsvp_token = secrets.token_urlsafe(32)
        self.token_expires_at = datetime.utcnow() + timedelta(hours=expiry_hours)
        return self.rsvp_token

    def is_token_valid(self):
        """Check if the token is still valid."""
        if not self.rsvp_token or not self.token_expires_at:
            return False
        return datetime.utcnow() < self.token_expires_at and self.token_used_at is None

    def mark_token_used(self):
        """Mark the token as used."""
        self.token_used_at = datetime.utcnow()


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
    # Track which methods were used for initial outreach (for confirmation routing)
    outreach_methods = db.Column(db.String(100), nullable=True)
    assigned_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    request = db.relationship('SubstituteRequest', back_populates='assignments')
    player = db.relationship('Player', backref='substitute_assignments')
    assigner = db.relationship('User', foreign_keys=[assigned_by], backref='substitute_assignments')

    __table_args__ = (
        db.UniqueConstraint('request_id', 'player_id', name='uq_substitute_assignment_request_player'),
    )


class SubstituteAvailability(db.Model):
    """Canonical weekly substitute availability surface (Pub League: Classic/Premier).

    ONE row per (player, match_date, league_type). This is the single assignable
    "who can sub this week" pool. It is fed by BOTH:
      - Discord availability poll votes (source='discord_poll'), recomputed from the
        player's current active DiscordPollVote rows for that poll, and
      - Admin reach-out responses (source='reachout_push'/'reachout_dm'/'reachout_web'),
        whether a general "can anyone sub at these times?" blast or a targeted
        "can you sub for this specific time?" ask (the team is never revealed to the sub).

    It is time-slot scoped, NOT tied to one SubstituteRequest or team, so admins can
    assign any available sub to any matching OPEN request and keep teams balanced.
    Classic subs only ever populate Classic rows; Premier only Premier (a dual-role
    sub can have one row per league_type on the same date).
    """
    __tablename__ = 'substitute_availability'
    __table_args__ = (
        # Segregated by source bucket ('discord_poll' vs 'reachout') so the two
        # independent doors never clobber each other's slots; reads aggregate the
        # (<=2) rows per player/date/league.
        db.UniqueConstraint('player_id', 'match_date', 'league_type', 'source',
                            name='uq_sub_availability_player_date_league_source'),
        db.Index('idx_sub_availability_date_league', 'match_date', 'league_type'),
        db.Index('idx_sub_availability_season', 'season_id'),
    )

    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False)
    season_id = db.Column(db.Integer, db.ForeignKey('season.id'), nullable=True)
    # The Sunday (match day) this availability is for.
    match_date = db.Column(db.Date, nullable=False)
    # 'Classic' | 'Premier' (canonical human strings, matching SubstitutePool.league_type).
    league_type = db.Column(db.String(20), nullable=False)
    # True = can sub, False = explicitly declined (keeps a record so we don't re-ask).
    is_available = db.Column(db.Boolean, nullable=False, default=True)
    # Union of time-slot strings the player said yes to, e.g. ["08:20", "09:30"].
    time_slots = db.Column(db.JSON, nullable=True)
    # Resolved match ids for those slots (exact join to SubstituteRequest.match_id).
    match_ids = db.Column(db.JSON, nullable=True)
    # 'discord_poll' | 'reachout_push' | 'reachout_dm' | 'reachout_web' | 'mobile' | 'web'
    source = db.Column(db.String(20), nullable=False, default='discord_poll')
    # Provenance back to the originating availability poll (for discord_poll source).
    poll_id = db.Column(db.Integer, db.ForeignKey('discord_polls.id', ondelete='SET NULL'), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    responded_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    player = db.relationship('Player', backref='substitute_availability')
    season = db.relationship('Season')
    poll = db.relationship('DiscordPoll')


class SubstituteReachout(db.Model):
    """An admin ad-hoc reach-out asking subs if they can play — beyond the weekly poll.

    Two kinds:
      - kind='general'  : "can anyone sub at these times?" blasted to a whole league pool.
      - kind='targeted' : "can you (this person / this group) sub for THIS specific time?"
        The originating request/team is NEVER disclosed to the contacted subs.

    Recipients respond via push (mobile), Discord DM buttons, or a secure web link; every
    yes upserts a SubstituteAvailability row via substitute_availability_service, so the
    reach-out feeds the same assignable pool as the poll. Optionally anchored to a
    SubstituteRequest (request_id) for coordinator context, but a 'yes' is pool-wide.
    """
    __tablename__ = 'substitute_reachouts'
    __table_args__ = (
        db.Index('idx_sub_reachout_date_league', 'match_date', 'league_type'),
    )

    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(20), nullable=False, default='general')  # 'general' | 'targeted'
    league_type = db.Column(db.String(20), nullable=False)  # 'Classic' | 'Premier'
    match_date = db.Column(db.Date, nullable=False)
    season_id = db.Column(db.Integer, db.ForeignKey('season.id'), nullable=True)
    # Time slots the reach-out asks about, e.g. ["08:20", "09:30"] (subset for targeted).
    time_slots = db.Column(db.JSON, nullable=True)
    match_ids = db.Column(db.JSON, nullable=True)
    # Optional coordinator context; never shown to recipients.
    request_id = db.Column(db.Integer, db.ForeignKey('substitute_requests.id', ondelete='SET NULL'), nullable=True)
    message = db.Column(db.Text, nullable=True)
    channels = db.Column(db.String(100), nullable=True)  # e.g. "push,discord"
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    recipients_count = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    creator = db.relationship('User')
    recipients = db.relationship('SubstituteReachoutRecipient', back_populates='reachout',
                                 cascade='all, delete-orphan')


class SubstituteReachoutRecipient(db.Model):
    """One contacted sub for a SubstituteReachout, with their response state.

    Lets targeted asks track "did we hear back from this specific person/group" and
    lets a secure web/push response be tied to a recipient without revealing the team.
    """
    __tablename__ = 'substitute_reachout_recipients'
    __table_args__ = (
        db.UniqueConstraint('reachout_id', 'player_id', name='uq_sub_reachout_recipient'),
        db.Index('idx_sub_reachout_recipient_player', 'player_id'),
        db.Index('idx_sub_reachout_recipient_token', 'response_token'),
    )

    id = db.Column(db.Integer, primary_key=True)
    reachout_id = db.Column(db.Integer, db.ForeignKey('substitute_reachouts.id'), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False)
    is_available = db.Column(db.Boolean, nullable=True)  # None = not yet responded
    responded_at = db.Column(db.DateTime, nullable=True)
    response_method = db.Column(db.String(20), nullable=True)
    channels_sent = db.Column(db.String(100), nullable=True)
    notification_sent_at = db.Column(db.DateTime, nullable=True)
    response_token = db.Column(db.String(64), unique=True, nullable=True, index=True)
    token_expires_at = db.Column(db.DateTime, nullable=True)

    reachout = db.relationship('SubstituteReachout', back_populates='recipients')
    player = db.relationship('Player', backref='substitute_reachout_recipients')

    def generate_token(self, expiry_hours=72):
        self.response_token = secrets.token_urlsafe(32)
        self.token_expires_at = datetime.utcnow() + timedelta(hours=expiry_hours)
        return self.response_token

    def is_token_valid(self):
        if not self.response_token or not self.token_expires_at:
            return False
        return datetime.utcnow() < self.token_expires_at


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
    
    # Find all eligible players with the required role
    # Must be: active (is_current_player), approved, and have the sub role
    from app.models import Player, User, Role
    from sqlalchemy.orm import joinedload

    players_with_role = session.query(Player).options(
        joinedload(Player.user).joinedload(User.roles)
    ).join(User).join(User.roles).filter(
        Role.name == required_role,
        Player.is_current_player == True,  # Must be an active player
        User.is_approved == True  # Must be approved
    ).all()

    # Apply gender filter via the ONE shared inclusive matcher (they/them + blank
    # always included; 'she/her' never matches a 'male' preference). The old
    # `gender in pronouns` substring test had the 'he' in 'she/her' false-positive.
    if gender:
        from app.services.substitute_notification_service import player_matches_gender_preference
        players_with_role = [
            p for p in players_with_role
            if player_matches_gender_preference(p.pronouns, gender)
        ]

    return players_with_role


def get_active_substitutes(league_type, session=None, gender_filter=None):
    """Get all active substitutes for a league type.

    Parallel-run (registration-lifecycle overhaul): by DEFAULT this runs the PROVEN LEGACY
    pool query (flag `cutover_subs_read_from_spine` defaults FALSE during burn-in — see
    cutover_flags.subs_read_from_spine for why). When the flag is turned ON, the ACTIVE SET
    (who is contactable) is instead confirmed against the new `league_membership` spine
    (role='sub', status='active'), while the returned rows stay `SubstitutePool` objects so
    callers keep their contact prefs / channel opt-outs. Both stay in sync via the dual-write,
    so the two paths return the same people while everything is healthy; flip the flag once
    you've confirmed that.
    """
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

    from app.models import Player, User, Role
    from sqlalchemy.orm import joinedload

    # Base legacy query: "Active in Pool" tri-state members (is_active + approved_at),
    # who are current + approved and hold the league sub role.
    existing_pools = session.query(SubstitutePool).options(
        joinedload(SubstitutePool.player).joinedload(Player.user).joinedload(User.roles)
    ).join(Player).join(User).join(User.roles).filter(
        Role.name == required_role,
        SubstitutePool.is_active == True,
        SubstitutePool.approved_at.isnot(None),
        Player.is_current_player == True,
        User.is_approved == True
    )

    # NEW SYSTEM (default): let the spine decide the active set. We keep returning
    # SubstitutePool rows (for contact prefs) but restrict to players the spine marks
    # as active subs in this lane for the current season. Failback: flag off -> skip.
    import logging
    _log = logging.getLogger(__name__)
    try:
        from app.services.cutover_flags import subs_read_from_spine
        if subs_read_from_spine():
            from app.models import LeagueMembership, Season
            lane = {'ECS FC': 'ecs_fc', 'Classic': 'classic', 'Premier': 'premier'}.get(league_type)
            program = 'ECS FC' if lane == 'ecs_fc' else 'Pub League'
            # order_by so a duplicate is_current picks deterministically (highest id =
            # newest), matching league_membership_sync._current_season_ids.
            season_row = session.query(Season.id).filter(
                Season.is_current == True, Season.league_type == program
            ).order_by(Season.id.desc()).first()
            if lane and season_row:
                active_pids = [pid for (pid,) in session.query(LeagueMembership.player_id).filter(
                    LeagueMembership.season_id == season_row[0],
                    LeagueMembership.league_type == lane,
                    LeagueMembership.role == 'sub',
                    LeagueMembership.status == 'active',
                ).all()]
                if active_pids:
                    # Spine is authoritative for membership; the pool row still supplies prefs.
                    existing_pools = existing_pools.filter(SubstitutePool.player_id.in_(active_pids))
                else:
                    # No active subs in the spine for this lane/season. Could be legitimate
                    # (all resting) OR an un-synced gap. Fall back to the legacy pool set
                    # rather than muting ALL sub requests: when it's legitimately empty the
                    # legacy set is empty too (dual-write keeps is_active in sync), so this is
                    # safe both ways and never silently contacts nobody due to a spine gap.
                    _log.info("Spine active-sub set empty for %s; using legacy pool set", league_type)
    except Exception:
        # Any spine hiccup -> fall back to the pure legacy query. Roll back first so a
        # DB-level spine error can't leave the transaction poisoned for the legacy read.
        try:
            session.rollback()
        except Exception:
            pass
        _log.warning("Sub active-set spine read failed; using legacy pool query", exc_info=True)

    # Apply gender filter via the ONE shared inclusive matcher. The old
    # `pronouns ILIKE '%male%'` matched ZERO rows (pronouns are stored 'he/him' /
    # 'she/her' / 'they/them'), silently muting gender-filtered pool broadcasts.
    if gender_filter:
        from app.services.substitute_notification_service import player_matches_gender_preference
        return [
            pe for pe in existing_pools.all()
            if player_matches_gender_preference(pe.player.pronouns if pe.player else None, gender_filter)
        ]

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