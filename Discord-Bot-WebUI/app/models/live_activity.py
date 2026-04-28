"""
Live Activity Push Tokens

Per-activity APNs push tokens registered by mobile when starting an iOS
Live Activity for a match. Used by the live-reporting socket layer to fan
out lock-screen / dynamic-island updates as score / timer / events change.
"""

from datetime import datetime

from app.core import db


class LiveActivityToken(db.Model):
    """One Live Activity push token per (user, match, token)."""
    __tablename__ = 'live_activity_tokens'

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    match_id = db.Column(db.Integer, nullable=False)
    league_type = db.Column(db.String(16), nullable=False)        # 'pub' | 'ecs_fc'

    push_token = db.Column(db.String(200), nullable=False)        # per-activity token (hex)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    last_pushed_at = db.Column(db.DateTime, nullable=True)
    ended_at = db.Column(db.DateTime, nullable=True)              # set when activity closes

    push_failure_count = db.Column(db.Integer, nullable=False, default=0)
    last_error = db.Column(db.String(500), nullable=True)

    user = db.relationship('User', backref=db.backref('live_activity_tokens', lazy='dynamic'))

    __table_args__ = (
        db.UniqueConstraint('user_id', 'match_id', 'league_type', 'push_token',
                            name='idx_live_activity_tokens_unique'),
        db.Index('idx_live_activity_tokens_active',
                 'match_id', 'league_type', 'ended_at'),
    )

    def __repr__(self):
        return (
            f'<LiveActivityToken id={self.id} match={self.league_type}:{self.match_id} '
            f'user={self.user_id} ended={self.ended_at is not None}>'
        )
