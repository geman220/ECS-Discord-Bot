# app/models/external.py

"""
External Integration Models Module

This module contains models for external integrations:
- Token: Tokens for player operations
- MLSMatch: MLS match integration
- Progress: Task progress tracking
- HelpTopic: Help system topics
- Prediction: Match predictions
"""

import logging
from datetime import datetime, timedelta

from app.core import db

logger = logging.getLogger(__name__)

# Association table for many-to-many relationship between HelpTopic and Role
help_topic_roles = db.Table(
    'help_topic_roles',
    db.Column('help_topic_id', db.Integer, db.ForeignKey('help_topics.id'), primary_key=True),
    db.Column('role_id', db.Integer, db.ForeignKey('roles.id'), primary_key=True)
)


class Token(db.Model):
    """Model representing a token for player operations (e.g., password reset)."""
    __tablename__ = 'tokens'

    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id', ondelete='CASCADE'), nullable=False)
    token = db.Column(db.String(32), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False, nullable=False)

    player = db.relationship('Player', backref=db.backref('tokens', lazy=True))

    def __init__(self, player_id, token, expires_at=None):
        self.player_id = player_id
        self.token = token
        self.created_at = datetime.utcnow()
        self.expires_at = expires_at or (self.created_at + timedelta(hours=24))

    def __repr__(self):
        return f'<Token {self.token} for player {self.player_id}>'

    @property
    def is_expired(self):
        return datetime.utcnow() > self.expires_at

    @property
    def is_valid(self):
        return not self.is_expired and not self.used

    def invalidate(self):
        try:
            self.used = True
            logger.info(f"Token {self.token} for player {self.player_id} invalidated")
        except Exception as e:
            logger.error(f"Error invalidating token {self.token} for player {self.player_id}: {str(e)}")
            raise


class MLSMatch(db.Model):
    """Model representing an MLS match with additional details."""
    __tablename__ = 'mls_matches'

    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.String, unique=True, nullable=False)
    opponent = db.Column(db.String(100), nullable=False)
    date_time = db.Column(db.DateTime(timezone=True), nullable=False)
    is_home_game = db.Column(db.Boolean, nullable=False)
    summary_link = db.Column(db.String(200))
    stats_link = db.Column(db.String(200))
    commentary_link = db.Column(db.String(200))
    venue = db.Column(db.String(100))
    competition = db.Column(db.String(50))
    thread_creation_time = db.Column(db.DateTime(timezone=True))
    thread_created = db.Column(db.Boolean, default=False)
    discord_thread_id = db.Column(db.String)
    thread_creation_scheduled = db.Column(db.Boolean, default=False)
    thread_creation_task_id = db.Column(db.String(100))
    last_thread_scheduling_attempt = db.Column(db.DateTime)
    live_reporting_scheduled = db.Column(db.Boolean, default=False)
    live_reporting_started = db.Column(db.Boolean, default=False)
    live_reporting_status = db.Column(db.String(20), default='not_started')
    live_reporting_task_id = db.Column(db.String(50))
    espn_match_id = db.Column(db.String(50), nullable=True)  # ESPN match ID for live data
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.date_time and not self.thread_creation_time:
            self.thread_creation_time = self.date_time - timedelta(hours=24)

    def __repr__(self):
        return f'<MLSMatch {self.match_id}: {self.opponent} on {self.date_time}>'


class Progress(db.Model):
    """Model representing the progress of a task."""
    __tablename__ = 'progress'
    
    task_id = db.Column(db.String(50), primary_key=True)
    stage = db.Column(db.String(50), nullable=False)
    message = db.Column(db.String(255))
    progress = db.Column(db.Integer)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class HelpTopic(db.Model):
    """Model representing a help topic."""
    __tablename__ = 'help_topics'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    markdown_content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    allowed_roles = db.relationship('Role', secondary=help_topic_roles, backref=db.backref('help_topics', lazy='dynamic'))

    def __repr__(self):
        return f'<HelpTopic {self.title}>'


class Prediction(db.Model):
    """Model representing a user's prediction for a match."""
    __tablename__ = 'predictions'
    
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.String, nullable=False)
    discord_user_id = db.Column(db.String, nullable=False)
    home_score = db.Column(db.Integer, nullable=False)
    opponent_score = db.Column(db.Integer, nullable=False)
    is_correct = db.Column(db.Boolean, default=None)
    season_correct_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Prediction {self.match_id} by {self.discord_user_id}>"