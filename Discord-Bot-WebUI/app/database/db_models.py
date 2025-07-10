# app/database/db_models.py

"""
Database Models for Monitoring and Live Reporting

This module defines models for:
1. Database monitoring snapshots
2. Live match reporting data structures including active reporters, match state, and events
"""

from datetime import datetime
from app.core import db
from sqlalchemy import JSON, TypeDecorator, String
import json


class FlexibleJSON(TypeDecorator):
    """
    JSON column type that works with both PostgreSQL and SQLite.
    Uses JSONB for PostgreSQL, JSON for others.
    """
    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            from sqlalchemy.dialects.postgresql import JSONB
            return dialect.type_descriptor(JSONB())
        else:
            return dialect.type_descriptor(JSON())

class DBMonitoringSnapshot(db.Model):
    """
    Represents a snapshot of database monitoring metrics.

    This model captures various details such as connection pool statistics,
    active connections, long-running transactions, recent events, and session
    monitoring data, all stored in JSONB format for flexibility.
    """
    __tablename__ = 'db_monitoring_snapshots'

    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, nullable=False, index=True)  # Snapshot creation time
    pool_stats = db.Column(FlexibleJSON())             # Database connection pool statistics
    active_connections = db.Column(FlexibleJSON())     # Data on current active connections
    long_running_transactions = db.Column(FlexibleJSON())  # Information about long-running transactions
    recent_events = db.Column(FlexibleJSON())          # Recent events or errors recorded
    session_monitor = db.Column(FlexibleJSON())        # Additional session monitoring metrics

class ActiveMatchReporter(db.Model):
    """
    Tracks users actively reporting on a match.
    
    This allows multiple coaches to report on the same match simultaneously,
    with each being associated with a specific team.
    """
    __tablename__ = 'active_match_reporters'
    
    match_id = db.Column(db.Integer, db.ForeignKey('matches.id'), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_active = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    match = db.relationship('Match', backref=db.backref('active_reporters', lazy='dynamic'))
    user = db.relationship('User', backref=db.backref('reporting_matches', lazy='dynamic'))
    team = db.relationship('Team', backref=db.backref('active_reporters', lazy='dynamic'))



class LiveMatch(db.Model):
    """
    Represents the current state of a live match being reported.
    
    Tracks score, time, status and other real-time information that
    should be synchronized across all reporters.
    """
    __tablename__ = 'live_matches'
    
    match_id = db.Column(db.Integer, db.ForeignKey('matches.id'), primary_key=True)
    status = db.Column(db.String(20), default='in_progress', nullable=False)
    current_period = db.Column(db.String(20))
    elapsed_seconds = db.Column(db.Integer, default=0)
    home_score = db.Column(db.Integer, default=0)
    away_score = db.Column(db.Integer, default=0)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    timer_running = db.Column(db.Boolean, default=False)
    report_submitted = db.Column(db.Boolean, default=False)
    report_submitted_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    
    match = db.relationship('Match', backref=db.backref('live_state', uselist=False))
    submitter = db.relationship('User', backref=db.backref('submitted_reports', lazy='dynamic'))
    events = db.relationship('MatchEvent', backref='live_match', lazy='dynamic', cascade='all, delete-orphan')

class MatchEvent(db.Model):
    """
    Represents events that occur during a match (goals, cards, etc.).
    
    These events are synchronized across all reporters and stored
    for generating the final match report.
    """
    __tablename__ = 'match_events'
    
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('live_matches.match_id'), nullable=False)
    event_type = db.Column(db.String(20), nullable=False)  # GOAL, YELLOW_CARD, RED_CARD, SUBSTITUTION, etc.
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'))
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'))
    minute = db.Column(db.Integer)
    period = db.Column(db.String(20))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    reported_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    additional_data = db.Column(FlexibleJSON())  # For flexible storage of event-specific details
    
    team = db.relationship('Team', backref=db.backref('match_events', lazy='dynamic'))
    player = db.relationship('Player', backref=db.backref('match_events', lazy='dynamic'))
    reporter = db.relationship('User', backref=db.backref('reported_events', lazy='dynamic'))

class PlayerShift(db.Model):
    """
    Tracks player shifts during a match.
    
    This is team-specific and not synchronized between teams.
    Each coach manages their own team's player shifts.
    """
    __tablename__ = 'player_shifts'
    
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('matches.id'), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False)
    is_active = db.Column(db.Boolean, default=False)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    
    match = db.relationship('Match', backref=db.backref('player_shifts', lazy='dynamic'))
    team = db.relationship('Team', backref=db.backref('player_shifts', lazy='dynamic'))
    player = db.relationship('Player', backref=db.backref('shifts', lazy='dynamic'))
    updater = db.relationship('User', backref=db.backref('updated_shifts', lazy='dynamic'))