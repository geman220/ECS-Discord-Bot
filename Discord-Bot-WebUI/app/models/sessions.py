# app/models/sessions.py

"""
Session Models Module

Tracks active user sessions for the mobile API.
Each login creates a session record with a unique ID that is embedded
in the JWT claims (as 'sid'). This enables per-session revocation
and the ability to list/manage active sessions.
"""

import uuid
from datetime import datetime
from app.core import db


class UserSession(db.Model):
    """Model for tracking active user sessions."""
    __tablename__ = 'user_sessions'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    device_name = db.Column(db.String(200), nullable=True)
    device_type = db.Column(db.String(20), nullable=True)  # 'ios', 'android', 'web'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_activity = db.Column(db.DateTime, default=datetime.utcnow)
    ip_address = db.Column(db.String(45), nullable=True)  # Supports IPv6
    is_active = db.Column(db.Boolean, default=True)

    user = db.relationship('User', backref='sessions')

    def to_dict(self, is_current=False):
        return {
            'session_id': self.id,
            'device_name': self.device_name or 'Unknown Device',
            'device_type': self.device_type or 'unknown',
            'created_at': self.created_at.isoformat() + 'Z' if self.created_at else None,
            'last_activity': self.last_activity.isoformat() + 'Z' if self.last_activity else None,
            'ip_address': self.ip_address,
            'is_current': is_current,
        }

    def __repr__(self):
        return f'<UserSession {self.id} user={self.user_id}>'
