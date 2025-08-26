# app/models/live_reporting_session.py

"""
Live Reporting Session Model

Tracks active live reporting sessions to enable persistent reporting
across container restarts. Each session represents a match that should
be monitored for live updates.
"""

import json
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Boolean, Integer, Text
from app.core import db


class LiveReportingSession(db.Model):
    """
    Model to track active live reporting sessions.
    
    This ensures live reporting persists across container restarts
    by storing session state in the database rather than relying
    on task chains that get lost during restarts.
    """
    __tablename__ = 'live_reporting_sessions'
    
    # Primary key
    id = db.Column(db.Integer, primary_key=True)
    
    # Match identification
    match_id = db.Column(db.String(50), unique=True, nullable=False, index=True)
    competition = db.Column(db.String(100), nullable=False)
    thread_id = db.Column(db.String(50), nullable=False)
    
    # Session state
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    started_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_update = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    ended_at = db.Column(db.DateTime, nullable=True)
    
    # Match state tracking
    last_status = db.Column(db.String(50), nullable=True)
    last_score = db.Column(db.String(20), nullable=True)
    last_event_keys = db.Column(db.Text, nullable=True)  # JSON string of processed event fingerprints
    
    # Operational data
    update_count = db.Column(db.Integer, default=0, nullable=False)
    error_count = db.Column(db.Integer, default=0, nullable=False)
    last_error = db.Column(db.Text, nullable=True)
    
    @property
    def parsed_event_keys(self):
        """Parse last_event_keys from JSON string to list."""
        if not self.last_event_keys:
            return []
        try:
            # Handle JSON format (from repository)
            parsed = json.loads(self.last_event_keys)
            if isinstance(parsed, list):
                return parsed
            # Handle Python string format (from old model method)
            elif isinstance(parsed, str):
                return [parsed]
            else:
                return []
        except (json.JSONDecodeError, TypeError):
            # Fallback for malformed data
            return []
    
    def __repr__(self):
        return f'<LiveReportingSession {self.match_id} ({self.competition}) - {"Active" if self.is_active else "Inactive"}>'
    
    def to_dict(self):
        """Convert session to dictionary for API responses."""
        return {
            'id': self.id,
            'match_id': self.match_id,
            'competition': self.competition,
            'thread_id': self.thread_id,
            'is_active': self.is_active,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'last_update': self.last_update.isoformat() if self.last_update else None,
            'ended_at': self.ended_at.isoformat() if self.ended_at else None,
            'last_status': self.last_status,
            'last_score': self.last_score,
            'update_count': self.update_count,
            'error_count': self.error_count,
            'last_error': self.last_error
        }
    
    @classmethod
    def get_active_sessions(cls, session_db):
        """Get all currently active live reporting sessions."""
        return session_db.query(cls).filter_by(is_active=True).all()
    
    @classmethod
    def get_session_by_match_id(cls, session_db, match_id):
        """Get session by match ID."""
        return session_db.query(cls).filter_by(match_id=str(match_id)).first()
    
    def deactivate(self, session_db, reason=None):
        """Deactivate the session."""
        self.is_active = False
        self.ended_at = datetime.utcnow()
        if reason:
            self.last_error = reason
        session_db.add(self)
    
    def update_state(self, session_db, status=None, score=None, event_keys=None, error=None):
        """Update session state."""
        self.last_update = datetime.utcnow()
        self.update_count += 1
        
        if status:
            self.last_status = status
        if score:
            self.last_score = score
        if event_keys:
            self.last_event_keys = str(event_keys)
        if error:
            self.error_count += 1
            self.last_error = error
            
        session_db.add(self)