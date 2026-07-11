# app/models/match_check_in.py

"""
Match Check-In Models

- MatchCheckInToken: opaque per-match venue token (encoded in printed QR /
  NFC sticker at the pitch). One active token per match.
- MatchAttendance: idempotent record that a specific player was checked in
  to a specific match. UNIQUE on (league_type, match_id, player_id).

No FK on match_id — pub_league `Match` and `EcsFcMatch` share an integer
ID space across tables, so enforcement lives at the app layer.
"""

import secrets
from datetime import datetime
from typing import Optional, Tuple

from flask import g, has_request_context

from app.core import db


LEAGUE_TYPES = ('pub_league', 'ecs_fc')
CHECK_IN_SOURCES = ('self', 'coach', 'coach_manual', 'admin')


def _resolve_session(session=None):
    """The session to read and write through.

    These methods used to hardcode `cls.query` (which binds to Flask-SQLAlchemy's
    `db.session`) for reads and `db.session.add()` for writes, while their callers
    committed `g.db_session` — a DIFFERENT session. Nothing commits `db.session`
    and teardown calls `db.session.remove()` (a rollback), so every attendance row
    written through a `managed_session()` caller was silently discarded: the API
    reported success and `match_attendance` stayed empty.

    Callers that already hold a session (the check-in service, the Celery token
    task) now pass it in explicitly. Everyone else gets the per-request session,
    which is the one `managed_session()` and `@transactional` both commit.
    """
    if session is not None:
        return session
    if has_request_context() and getattr(g, 'db_session', None) is not None:
        return g.db_session
    return db.session


class MatchCheckInToken(db.Model):
    __tablename__ = 'match_check_in_token'

    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(32), unique=True, nullable=False)
    match_id = db.Column(db.Integer, nullable=False)
    league_type = db.Column(db.String(16), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    revoked_at = db.Column(db.DateTime, nullable=True)
    # Hard expiry — set at creation to kickoff + a window. Once this passes the
    # token stops resolving on the public landing (and anywhere is_valid is
    # checked), so the "Codes expire after the match window closes" copy is true.
    expires_at = db.Column(db.DateTime, nullable=True)

    created_by = db.relationship('User', foreign_keys=[created_by_user_id])

    __table_args__ = (
        db.Index('idx_match_check_in_token_match', 'league_type', 'match_id'),
    )

    def __repr__(self):
        return f'<MatchCheckInToken {self.token[:8]}... {self.league_type}/{self.match_id}>'

    @staticmethod
    def generate_token() -> str:
        # 16 bytes → ~22 url-safe chars; well under the 32-char column limit.
        return secrets.token_urlsafe(16)

    @property
    def is_expired(self) -> bool:
        """True once we're past expires_at. Tokens with no expiry never expire."""
        if self.expires_at is None:
            return False
        return datetime.utcnow() >= self.expires_at

    @property
    def is_active(self) -> bool:
        """Active == not revoked AND not expired."""
        return self.revoked_at is None and not self.is_expired

    @property
    def is_valid(self) -> bool:
        """Alias for is_active — the public landing / scan paths check this."""
        return self.is_active

    @classmethod
    def find_active_by_token(cls, token: str, session=None) -> Optional['MatchCheckInToken']:
        """Resolve a token, treating revoked OR expired tokens as not found.

        The expiry filter is applied in Python (not SQL) so a NULL expires_at
        is always treated as non-expiring regardless of DB NULL semantics.
        """
        if not token:
            return None
        db_session = _resolve_session(session)
        ct = db_session.query(cls).filter_by(token=token, revoked_at=None).first()
        if ct is None or ct.is_expired:
            return None
        return ct

    @classmethod
    def find_active_for_match(
        cls, league_type: str, match_id: int, session=None
    ) -> Optional['MatchCheckInToken']:
        """Return the live (non-revoked, non-expired) token for this match.

        There can be at most one non-revoked row per match; if it's expired we
        treat it as gone so callers regenerate rather than reuse a dead code.
        """
        db_session = _resolve_session(session)
        ct = db_session.query(cls).filter_by(
            league_type=league_type,
            match_id=match_id,
            revoked_at=None
        ).first()
        if ct is None or ct.is_expired:
            return None
        return ct

    @classmethod
    def get_or_create_for_match(
        cls, league_type: str, match_id: int, user_id: Optional[int] = None,
        expires_at: Optional[datetime] = None, session=None,
    ) -> 'MatchCheckInToken':
        """Return the active token for this match, creating one if none exists.

        Caller must commit — and must commit THE SAME session it passed here
        (or the per-request one, if it passed none). See _resolve_session.
        Idempotent. `expires_at` applies only to a newly created token.
        """
        db_session = _resolve_session(session)
        existing = cls.find_active_for_match(league_type, match_id, session=db_session)
        if existing:
            return existing
        ct = cls(
            token=cls.generate_token(),
            match_id=match_id,
            league_type=league_type,
            created_by_user_id=user_id,
            expires_at=expires_at,
        )
        db_session.add(ct)
        return ct

    def revoke(self):
        if self.revoked_at is None:
            self.revoked_at = datetime.utcnow()


class MatchAttendance(db.Model):
    __tablename__ = 'match_attendance'

    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, nullable=False)
    league_type = db.Column(db.String(16), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id', ondelete='CASCADE'), nullable=False)
    checked_in_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    checked_in_by = db.Column(db.String(16), nullable=False)
    recorded_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    venue_token_id = db.Column(db.Integer, db.ForeignKey('match_check_in_token.id', ondelete='SET NULL'), nullable=True)
    notes = db.Column(db.Text, nullable=True)

    player = db.relationship('Player', backref='match_attendance_records')
    recorded_by = db.relationship('User', foreign_keys=[recorded_by_user_id])
    venue_token = db.relationship('MatchCheckInToken')

    __table_args__ = (
        db.UniqueConstraint('league_type', 'match_id', 'player_id', name='uq_match_attendance_match_player'),
        db.Index('idx_match_attendance_match', 'league_type', 'match_id'),
        db.Index('idx_match_attendance_player', 'player_id'),
    )

    def __repr__(self):
        return f'<MatchAttendance player={self.player_id} match={self.league_type}/{self.match_id} by={self.checked_in_by}>'

    @classmethod
    def find_for_match_player(
        cls, league_type: str, match_id: int, player_id: int, session=None
    ) -> Optional['MatchAttendance']:
        db_session = _resolve_session(session)
        return db_session.query(cls).filter_by(
            league_type=league_type,
            match_id=match_id,
            player_id=player_id,
        ).first()

    @classmethod
    def list_for_match(cls, league_type: str, match_id: int, session=None):
        db_session = _resolve_session(session)
        return db_session.query(cls).filter_by(
            league_type=league_type, match_id=match_id
        ).all()

    @classmethod
    def record(
        cls,
        league_type: str,
        match_id: int,
        player_id: int,
        source: str,
        recorded_by_user_id: Optional[int] = None,
        venue_token_id: Optional[int] = None,
        notes: Optional[str] = None,
        session=None,
    ) -> Tuple['MatchAttendance', bool]:
        """Idempotent attendance record.

        Returns (row, created) where `created=False` if the player was already
        checked in for this match. Caller commits — THE SAME session it passed
        here. This used to add unconditionally to db.session while callers
        committed g.db_session, so the row never landed and `created` came back
        True on every re-scan.
        """
        db_session = _resolve_session(session)
        existing = cls.find_for_match_player(
            league_type, match_id, player_id, session=db_session
        )
        if existing:
            return existing, False

        row = cls(
            match_id=match_id,
            league_type=league_type,
            player_id=player_id,
            checked_in_by=source,
            recorded_by_user_id=recorded_by_user_id,
            venue_token_id=venue_token_id,
            notes=notes,
        )
        db_session.add(row)
        return row, True

    def to_dict(self):
        return {
            'id': self.id,
            'match_id': self.match_id,
            'league_type': self.league_type,
            'player_id': self.player_id,
            'checked_in_at': self.checked_in_at.isoformat() + 'Z' if self.checked_in_at else None,
            'checked_in_by': self.checked_in_by,
            'recorded_by_user_id': self.recorded_by_user_id,
        }
