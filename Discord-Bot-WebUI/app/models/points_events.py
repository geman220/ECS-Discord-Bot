# app/models/points_events.py

"""
Points Events Models

- PointsEventType: admin-defined event categories that carry a default point
  value (e.g. "Field Setup Help — 5 pts", "Match Attendance — 10 pts"). Soft-
  deleted via is_archived so historical award rows stay queryable.
- PointsEventAward: per-player award row, the audit trail. Multiple awards of
  the same type to the same player over time are valid; duplicate-scan
  debounce within 30s is enforced at the service layer (Redis), not in the
  schema.

Names intentionally avoid "LeagueEventType" to prevent a collision with the
existing calendar Enum at app/models/calendar.py:21.
"""

from datetime import datetime
from typing import Optional

from app.core import db


class PointsEventType(db.Model):
    __tablename__ = 'points_event_type'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(60), nullable=False)
    description = db.Column(db.Text, nullable=True)
    default_points = db.Column(db.Integer, nullable=False)
    is_archived = db.Column(db.Boolean, nullable=False, default=False)
    created_by_user_id = db.Column(
        db.Integer, db.ForeignKey('users.id'), nullable=False
    )
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False,
        default=datetime.utcnow, onupdate=datetime.utcnow
    )

    created_by = db.relationship('User', foreign_keys=[created_by_user_id])
    awards = db.relationship(
        'PointsEventAward', back_populates='event_type', lazy='dynamic'
    )

    __table_args__ = (
        db.CheckConstraint(
            'default_points BETWEEN 1 AND 10000',
            name='ck_points_event_type_default_points_range'
        ),
        db.Index('idx_points_event_type_active', 'is_archived'),
        # Partial unique index uq_points_event_type_name_active is defined in
        # the SQL migration (Postgres-specific WHERE clause not portable via
        # plain SQLAlchemy column args).
    )

    def __repr__(self):
        return f'<PointsEventType {self.id}: {self.name}>'

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'default_points': self.default_points,
            'is_archived': self.is_archived,
            'created_by_user_id': self.created_by_user_id,
            'created_at': self.created_at.isoformat() + 'Z' if self.created_at else None,
            'updated_at': self.updated_at.isoformat() + 'Z' if self.updated_at else None,
        }


class PointsEventAward(db.Model):
    __tablename__ = 'points_event_award'

    id = db.Column(db.Integer, primary_key=True)
    event_type_id = db.Column(
        db.Integer, db.ForeignKey('points_event_type.id'), nullable=False
    )
    player_id = db.Column(
        db.Integer, db.ForeignKey('player.id', ondelete='CASCADE'), nullable=False
    )
    points_awarded = db.Column(db.Integer, nullable=False)
    recorded_by_user_id = db.Column(
        db.Integer, db.ForeignKey('users.id'), nullable=False
    )
    recorded_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    note = db.Column(db.String(255), nullable=True)

    event_type = db.relationship('PointsEventType', back_populates='awards')
    player = db.relationship('Player', backref='points_awards')
    recorded_by = db.relationship('User', foreign_keys=[recorded_by_user_id])

    __table_args__ = (
        db.CheckConstraint(
            'points_awarded > 0',
            name='ck_points_event_award_points_positive'
        ),
        db.Index('idx_points_event_award_player', 'player_id', 'recorded_at'),
        db.Index('idx_points_event_award_type', 'event_type_id', 'recorded_at'),
    )

    def __repr__(self):
        return (
            f'<PointsEventAward player={self.player_id} '
            f'type={self.event_type_id} pts={self.points_awarded}>'
        )

    @classmethod
    def total_for_player(cls, session, player_id: int) -> int:
        """Sum of points_awarded for a player. Returns 0 if no awards."""
        from sqlalchemy import func
        result = session.query(func.coalesce(func.sum(cls.points_awarded), 0)).filter(
            cls.player_id == player_id
        ).scalar()
        return int(result or 0)

    @classmethod
    def latest_for_player(cls, session, player_id: int) -> Optional['PointsEventAward']:
        """Most recent award for a player, or None."""
        return (
            session.query(cls)
            .filter(cls.player_id == player_id)
            .order_by(cls.recorded_at.desc())
            .first()
        )

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'event_type_id': self.event_type_id,
            'player_id': self.player_id,
            'points_awarded': self.points_awarded,
            'recorded_by_user_id': self.recorded_by_user_id,
            'recorded_at': self.recorded_at.isoformat() + 'Z' if self.recorded_at else None,
            'note': self.note,
        }
