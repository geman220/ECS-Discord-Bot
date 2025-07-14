# app/models/league_features.py

"""
League Features Models Module

This module contains models for various league features:
- SubRequest: Substitute requests from coaches
- LeaguePoll: League-wide polls
- LeaguePollResponse: Poll responses
- LeaguePollDiscordMessage: Discord messages for polls
- DraftOrderHistory: Draft order tracking
- MessageCategory: Message categories
- MessageTemplate: Message templates
"""

import logging
from datetime import datetime
from flask import g
from sqlalchemy import JSON, func

from app.core import db
from app.models.players import player_teams

logger = logging.getLogger(__name__)


class SubRequest(db.Model):
    """Model representing a substitute request from a coach."""
    __tablename__ = 'sub_requests'
    
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('matches.id', ondelete='CASCADE'), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id', ondelete='CASCADE'), nullable=False)
    requested_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    status = db.Column(db.String(20), default='PENDING')  # PENDING, APPROVED, DECLINED, FULFILLED
    substitutes_needed = db.Column(db.Integer, default=1, nullable=False)  # Number of substitutes needed
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    fulfilled_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    
    # Define relationships
    match = db.relationship('Match', backref=db.backref('sub_requests', lazy='dynamic'))
    team = db.relationship('Team', backref=db.backref('sub_requests', lazy='dynamic'))
    requester = db.relationship('User', foreign_keys=[requested_by], backref=db.backref('requested_subs', lazy='dynamic'))
    fulfiller = db.relationship('User', foreign_keys=[fulfilled_by], backref=db.backref('fulfilled_sub_requests', lazy='dynamic'))
    
    __table_args__ = (
        db.UniqueConstraint('match_id', 'team_id', name='uq_sub_req_match_team'),
    )
    
    def __repr__(self):
        return f"<SubRequest: {self.team_id} in match {self.match_id}, status: {self.status}>"


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
    
    # Relationships
    poll = db.relationship('LeaguePoll', back_populates='responses')
    player = db.relationship('Player', backref=db.backref('poll_responses', lazy='dynamic'))
    
    __table_args__ = (
        db.UniqueConstraint('poll_id', 'player_id', name='uq_poll_player_response'),
    )
    
    def __repr__(self):
        return f"<LeaguePollResponse: Poll {self.poll_id}, Player {self.player_id}, Response: {self.response}>"


class LeaguePollDiscordMessage(db.Model):
    """Model representing Discord messages sent for a league poll."""
    __tablename__ = 'league_poll_discord_messages'
    
    id = db.Column(db.Integer, primary_key=True)
    poll_id = db.Column(db.Integer, db.ForeignKey('league_polls.id', ondelete='CASCADE'), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id', ondelete='CASCADE'), nullable=False)
    channel_id = db.Column(db.String(20), nullable=False)  # Discord channel ID
    message_id = db.Column(db.String(20), nullable=True)   # Discord message ID (set after sending)
    sent_at = db.Column(db.DateTime, nullable=True)
    send_error = db.Column(db.Text, nullable=True)
    
    # Relationships
    poll = db.relationship('LeaguePoll', back_populates='discord_messages')
    team = db.relationship('Team', backref=db.backref('poll_messages', lazy='dynamic'))
    
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
    
    # Relationships
    season = db.relationship('Season', backref=db.backref('draft_orders', lazy='dynamic'))
    league = db.relationship('League', backref=db.backref('draft_orders', lazy='dynamic'))
    player = db.relationship('Player', backref=db.backref('draft_history', lazy='dynamic'))
    team = db.relationship('Team', backref=db.backref('draft_picks', lazy='dynamic'))
    drafter = db.relationship('User', backref=db.backref('draft_picks_made', lazy='dynamic'))
    
    __table_args__ = (
        db.UniqueConstraint('season_id', 'league_id', 'player_id', name='uq_draft_order_player_season_league'),
        db.UniqueConstraint('season_id', 'league_id', 'draft_position', name='uq_draft_order_position_season_league'),
    )
    
    def __repr__(self):
        return f"<DraftOrderHistory: #{self.draft_position} {self.player_id} to {self.team_id} in S{self.season_id}>"


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
    
    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey('message_categories.id', ondelete='CASCADE'), nullable=False)
    key = db.Column(db.String(100), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    message_content = db.Column(db.Text, nullable=False)
    variables = db.Column(JSON, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    updated_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    
    # Relationships
    category = db.relationship('MessageCategory', back_populates='templates')
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
    
    def __repr__(self):
        return f"<MessageTemplate: {self.category.name}.{self.key}>"