# app/models/league_features.py

"""
League Features Models Module

This module contains models for various league features:
- LeaguePoll: League-wide polls
- LeaguePollResponse: Poll responses
- LeaguePollDiscordMessage: Discord messages for polls
- DraftOrderHistory: Draft order tracking
- MessageCategory: Message categories
- MessageTemplate: Message templates
- LeagueSetting: Configurable league-specific settings

Note: SubRequest (sub_requests table) has been unified into SubstituteRequest
(substitute_requests table) in app/models/substitutes.py.
"""

import logging
from datetime import datetime
from flask import g
from sqlalchemy import JSON, func

from app.core import db
from app.models.players import player_teams, Team, Player

logger = logging.getLogger(__name__)


class LeaguePoll(db.Model):
    """Model representing a league-wide poll sent to all team channels."""
    __tablename__ = 'league_polls'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    question = db.Column(db.Text, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    status = db.Column(db.String(20), default='ACTIVE')  # ACTIVE, CLOSED, DELETED
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    closed_at = db.Column(db.DateTime, nullable=True)
    
    # Relationships
    creator = db.relationship('User', backref=db.backref('created_polls', lazy='dynamic'))
    responses = db.relationship('LeaguePollResponse', back_populates='poll', cascade='all, delete-orphan')
    discord_messages = db.relationship('LeaguePollDiscordMessage', back_populates='poll', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f"<LeaguePoll {self.id}: {self.title}>"
    
    def get_response_counts(self):
        """Get counts of responses by type."""
        from sqlalchemy import func
        response_counts = g.db_session.query(
            LeaguePollResponse.response,
            func.count(LeaguePollResponse.id).label('count')
        ).filter(
            LeaguePollResponse.poll_id == self.id
        ).group_by(LeaguePollResponse.response).all()
        
        counts = {'yes': 0, 'no': 0, 'maybe': 0}
        for response, count in response_counts:
            counts[response] = count
        return counts
    
    def get_team_breakdown(self):
        """Get response breakdown by team."""
        from sqlalchemy import func
        team_breakdown = g.db_session.query(
            Team.name,
            Team.id,
            LeaguePollResponse.response,
            func.count(LeaguePollResponse.id).label('count')
        ).join(
            Player, Player.id == LeaguePollResponse.player_id
        ).join(
            player_teams, player_teams.c.player_id == Player.id
        ).join(
            Team, Team.id == player_teams.c.team_id
        ).filter(
            LeaguePollResponse.poll_id == self.id
        ).group_by(
            Team.name, Team.id, LeaguePollResponse.response
        ).order_by(Team.name, LeaguePollResponse.response).all()
        
        return team_breakdown


class LeaguePollResponse(db.Model):
    """Model representing a response to a league poll."""
    __tablename__ = 'league_poll_responses'
    
    id = db.Column(db.Integer, primary_key=True)
    poll_id = db.Column(db.Integer, db.ForeignKey('league_polls.id', ondelete='CASCADE'), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id', ondelete='CASCADE'), nullable=False)
    discord_id = db.Column(db.String(20), nullable=False)  # For tracking Discord user
    response = db.Column(db.String(10), nullable=False)  # 'yes', 'no', 'maybe'
    responded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships - passive_deletes=True trusts DB's ON DELETE CASCADE
    poll = db.relationship('LeaguePoll', back_populates='responses', passive_deletes=True)
    player = db.relationship('Player', backref=db.backref('poll_responses', lazy='dynamic', passive_deletes=True), passive_deletes=True)
    
    __table_args__ = (
        db.UniqueConstraint('poll_id', 'player_id', name='uq_poll_player_response'),
        db.Index('idx_league_poll_responses_player_id', 'player_id'),
    )
    
    def __repr__(self):
        return f"<LeaguePollResponse: Poll {self.poll_id}, Player {self.player_id}, Response: {self.response}>"


class LeaguePollDiscordMessage(db.Model):
    """Model representing Discord messages sent for a league poll."""
    __tablename__ = 'league_poll_discord_messages'
    __table_args__ = (
        db.Index('idx_league_poll_discord_messages_poll_id', 'poll_id'),
    )

    id = db.Column(db.Integer, primary_key=True)
    poll_id = db.Column(db.Integer, db.ForeignKey('league_polls.id', ondelete='CASCADE'), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id', ondelete='CASCADE'), nullable=False)
    channel_id = db.Column(db.String(20), nullable=False)  # Discord channel ID
    message_id = db.Column(db.String(20), nullable=True)   # Discord message ID (set after sending)
    sent_at = db.Column(db.DateTime, nullable=True)
    send_error = db.Column(db.Text, nullable=True)
    
    # Relationships - passive_deletes=True trusts DB's ON DELETE CASCADE
    poll = db.relationship('LeaguePoll', back_populates='discord_messages', passive_deletes=True)
    team = db.relationship('Team', backref=db.backref('poll_messages', lazy='dynamic', passive_deletes=True), passive_deletes=True)
    
    def __repr__(self):
        return f"<LeaguePollDiscordMessage: Poll {self.poll_id}, Team {self.team_id}, Channel {self.channel_id}>"


class DraftOrderHistory(db.Model):
    """Model representing the historical draft order of players."""
    __tablename__ = 'draft_order_history'
    
    id = db.Column(db.Integer, primary_key=True)
    season_id = db.Column(db.Integer, db.ForeignKey('season.id', ondelete='CASCADE'), nullable=False)
    league_id = db.Column(db.Integer, db.ForeignKey('league.id', ondelete='CASCADE'), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id', ondelete='CASCADE'), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id', ondelete='CASCADE'), nullable=False)
    draft_position = db.Column(db.Integer, nullable=False)  # 1, 2, 3, etc.
    drafted_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    drafted_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships - passive_deletes=True trusts DB's ON DELETE CASCADE
    season = db.relationship('Season', backref=db.backref('draft_orders', lazy='dynamic', passive_deletes=True), passive_deletes=True)
    league = db.relationship('League', backref=db.backref('draft_orders', lazy='dynamic', passive_deletes=True), passive_deletes=True)
    player = db.relationship('Player', backref=db.backref('draft_history', lazy='dynamic', passive_deletes=True), passive_deletes=True)
    team = db.relationship('Team', backref=db.backref('draft_picks', lazy='dynamic', passive_deletes=True), passive_deletes=True)
    drafter = db.relationship('User', backref=db.backref('draft_picks_made', lazy='dynamic'))
    
    __table_args__ = (
        db.UniqueConstraint('season_id', 'league_id', 'player_id', name='uq_draft_order_player_season_league'),
        db.UniqueConstraint('season_id', 'league_id', 'draft_position', name='uq_draft_order_position_season_league'),
        db.Index('idx_draft_order_history_player_id', 'player_id'),
    )
    
    def __repr__(self):
        return f"<DraftOrderHistory: #{self.draft_position} {self.player_id} to {self.team_id} in S{self.season_id}>"


class DraftSession(db.Model):
    """Live 'on the clock' draft state for one (season, league).

    Additive to the existing free-form draft: when a row exists and status is
    'active', picks must respect the team pick order (see DraftPickSlot) and the
    clock advances after each pick. When no row exists, the draft behaves exactly
    as before (any player -> any team, no turns).
    """
    __tablename__ = 'draft_session'

    id = db.Column(db.Integer, primary_key=True)
    season_id = db.Column(db.Integer, db.ForeignKey('season.id', ondelete='CASCADE'), nullable=False)
    league_id = db.Column(db.Integer, db.ForeignKey('league.id', ondelete='CASCADE'), nullable=False)

    # format / rules
    format = db.Column(db.String(10), nullable=False, default='snake')      # 'snake' | 'linear' | 'rotating'
    seconds_per_pick = db.Column(db.Integer, nullable=False, default=90)     # 0 = untimed; adjustable live
    timeout_action = db.Column(db.String(10), nullable=False, default='alert')  # alert | skip | pause
    lock_to_clock = db.Column(db.Boolean, nullable=False, default=True)      # only current team may be assigned
    rounds = db.Column(db.Integer, nullable=False, default=0)                # roster-size target (picks per team)
    # Roster-composition requirements (soft — shown as live counters/warnings, never blocks a
    # pick; admins can always exceed/override). 'new' = players with no prior team history;
    # 'admin' = players who hold a Pub League Admin / Global Admin role.
    min_new_players = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    min_admins = db.Column(db.Integer, nullable=False, default=0, server_default='0')

    # live state
    status = db.Column(db.String(12), nullable=False, default='setup')      # setup|active|paused|complete
    current_overall_pick = db.Column(db.Integer, nullable=True)             # 1..(teams*rounds)
    current_round = db.Column(db.Integer, nullable=True)
    current_team_id = db.Column(db.Integer, db.ForeignKey('team.id', ondelete='SET NULL'), nullable=True)
    pick_deadline = db.Column(db.DateTime, nullable=True)                   # server-authoritative clock
    pause_remaining_seconds = db.Column(db.Integer, nullable=True)         # set while paused
    alerts_sent = db.Column(db.Integer, nullable=False, default=0)          # escalation counter for the current pick

    started_at = db.Column(db.DateTime, nullable=True)
    started_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    season = db.relationship('Season', backref=db.backref('draft_sessions', lazy='dynamic', passive_deletes=True), passive_deletes=True)
    league = db.relationship('League', backref=db.backref('draft_sessions', lazy='dynamic', passive_deletes=True), passive_deletes=True)
    current_team = db.relationship('Team', foreign_keys=[current_team_id])
    slots = db.relationship('DraftPickSlot', backref='draft_session', cascade='all, delete-orphan',
                            order_by='DraftPickSlot.slot', passive_deletes=True)

    __table_args__ = (
        db.UniqueConstraint('season_id', 'league_id', name='uq_draft_session_season_league'),
    )

    def __repr__(self):
        return f"<DraftSession S{self.season_id}/L{self.league_id} {self.status} pick={self.current_overall_pick}>"


class DraftPickSlot(db.Model):
    """One team's position in the draft pick order (round-1 order; snake derives later rounds)."""
    __tablename__ = 'draft_pick_slot'

    id = db.Column(db.Integer, primary_key=True)
    draft_session_id = db.Column(db.Integer, db.ForeignKey('draft_session.id', ondelete='CASCADE'), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id', ondelete='CASCADE'), nullable=False)
    slot = db.Column(db.Integer, nullable=False)  # 1..N

    team = db.relationship('Team')

    __table_args__ = (
        db.UniqueConstraint('draft_session_id', 'team_id', name='uq_draft_slot_session_team'),
        db.UniqueConstraint('draft_session_id', 'slot', name='uq_draft_slot_session_slot'),
    )

    def __repr__(self):
        return f"<DraftPickSlot session={self.draft_session_id} slot={self.slot} team={self.team_id}>"


class MessageCategory(db.Model):
    """Model representing categories for configurable messages."""
    __tablename__ = 'message_categories'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    templates = db.relationship('MessageTemplate', back_populates='category', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f"<MessageCategory: {self.name}>"


class MessageTemplate(db.Model):
    """Model representing configurable message templates."""
    __tablename__ = 'message_templates'

    # Channel type constants
    CHANNEL_DISCORD_DM = 'discord_dm'
    CHANNEL_DISCORD_POST = 'discord_channel'
    CHANNEL_SMS = 'sms'
    CHANNEL_EMAIL = 'email'
    CHANNEL_ANNOUNCEMENT = 'announcement'

    CHANNEL_TYPES = [
        (CHANNEL_DISCORD_DM, 'Discord DM'),
        (CHANNEL_DISCORD_POST, 'Discord Channel Post'),
        (CHANNEL_SMS, 'SMS Message'),
        (CHANNEL_EMAIL, 'Email'),
        (CHANNEL_ANNOUNCEMENT, 'System Announcement'),
    ]

    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey('message_categories.id', ondelete='CASCADE'), nullable=False)
    key = db.Column(db.String(100), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    message_content = db.Column(db.Text, nullable=False)
    variables = db.Column(JSON, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    # New fields for better UX
    channel_type = db.Column(db.String(50), nullable=True)  # discord_dm, sms, email, etc.
    usage_context = db.Column(db.Text, nullable=True)  # Human-readable description of when/where used
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    updated_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    
    # Relationships - passive_deletes=True trusts DB's ON DELETE CASCADE
    category = db.relationship('MessageCategory', back_populates='templates', passive_deletes=True)
    creator = db.relationship('User', foreign_keys=[created_by], backref='created_message_templates')
    updater = db.relationship('User', foreign_keys=[updated_by], backref='updated_message_templates')
    
    __table_args__ = (
        db.UniqueConstraint('category_id', 'key', name='uq_message_template_category_key'),
    )
    
    def format_message(self, **kwargs):
        """Format the message content with provided variables."""
        try:
            return self.message_content.format(**kwargs)
        except KeyError as e:
            logger.warning(f"Missing variable for message template {self.key}: {e}")
            return self.message_content
        except Exception as e:
            logger.error(f"Error formatting message template {self.key}: {e}")
            return self.message_content
    
    @classmethod
    def get_by_key(cls, category_name: str, template_key: str):
        """Get a message template by category name and key."""
        return cls.query.join(MessageCategory).filter(
            MessageCategory.name == category_name,
            cls.key == template_key,
            cls.is_active == True
        ).first()

    def get_channel_type_display(self):
        """Get human-readable channel type name."""
        for value, display in self.CHANNEL_TYPES:
            if value == self.channel_type:
                return display
        return self.channel_type or 'Not Specified'

    def __repr__(self):
        return f"<MessageTemplate: {self.category.name}.{self.key}>"


class LeagueSetting(db.Model):
    """Model for configurable league-specific information.

    Stores league welcome messages, contact info, and display names
    that can be edited by admins in the UI instead of being hardcoded
    in the Discord bot.
    """
    __tablename__ = 'league_settings'

    id = db.Column(db.Integer, primary_key=True)
    league_key = db.Column(db.String(50), unique=True, nullable=False)  # pub_league_classic, pub_league_premier, ecs_fc
    display_name = db.Column(db.String(100), nullable=False)  # Human-readable name
    welcome_message = db.Column(db.Text, nullable=False)  # Message sent to new users
    contact_info = db.Column(db.Text, nullable=False)  # How to get help
    emoji = db.Column(db.String(10), nullable=True)  # Optional emoji for display
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)  # For display ordering
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def to_dict(self):
        """Convert to dictionary for API responses."""
        return {
            'id': self.id,
            'league_key': self.league_key,
            'display_name': self.display_name,
            'welcome_message': self.welcome_message,
            'contact_info': self.contact_info,
            'emoji': self.emoji,
            'is_active': self.is_active,
        }

    @classmethod
    def get_by_key(cls, league_key: str):
        """Get league setting by key."""
        return cls.query.filter_by(league_key=league_key, is_active=True).first()

    @classmethod
    def get_all_active(cls):
        """Get all active league settings ordered by sort_order."""
        return cls.query.filter_by(is_active=True).order_by(cls.sort_order).all()

    def __repr__(self):
        return f"<LeagueSetting: {self.league_key}>"