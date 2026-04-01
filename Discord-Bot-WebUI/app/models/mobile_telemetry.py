# app/models/mobile_telemetry.py

"""
Mobile Telemetry Models

Tracks mobile app sessions, screen views, and feature usage.
Data is reported by the Flutter app via /api/v1/telemetry/ endpoints.
"""

from datetime import datetime
from app.core import db


class MobileSession(db.Model):
    """Tracks individual mobile app sessions."""
    __tablename__ = 'mobile_sessions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    session_id = db.Column(db.String(100), unique=True, nullable=False, index=True)
    platform = db.Column(db.String(20), nullable=True)  # 'ios' or 'android'
    app_version = db.Column(db.String(50), nullable=True)
    started_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    ended_at = db.Column(db.DateTime, nullable=True)
    duration_seconds = db.Column(db.Integer, nullable=True)
    screens_viewed = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship('User', foreign_keys=[user_id])

    def to_dict(self):
        return {
            'id': self.id,
            'session_id': self.session_id,
            'user_id': self.user_id,
            'platform': self.platform,
            'app_version': self.app_version,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'ended_at': self.ended_at.isoformat() if self.ended_at else None,
            'duration_seconds': self.duration_seconds,
            'screens_viewed': self.screens_viewed,
        }


class MobileScreenView(db.Model):
    """Tracks individual screen/page views within a session."""
    __tablename__ = 'mobile_screen_views'

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(100), db.ForeignKey('mobile_sessions.session_id', ondelete='CASCADE'),
                          nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    screen_name = db.Column(db.String(100), nullable=False, index=True)
    entered_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    exited_at = db.Column(db.DateTime, nullable=True)
    duration_seconds = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    session = db.relationship('MobileSession', foreign_keys=[session_id],
                             primaryjoin="MobileScreenView.session_id == MobileSession.session_id")


class MobileFeatureUsage(db.Model):
    """Tracks feature usage events from the mobile app."""
    __tablename__ = 'mobile_feature_usage'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    feature_name = db.Column(db.String(100), nullable=False, index=True)
    platform = db.Column(db.String(20), nullable=True)
    app_version = db.Column(db.String(50), nullable=True)
    used_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
