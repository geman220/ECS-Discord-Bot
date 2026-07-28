# app/models/discord_relink.py

"""
Discord Relink Request Model

Captures the dead-end that used to be a plain "contact an admin" message.

Discord OAuth is the only way into the portal, so a member who loses access
to their Discord account (hacked, deleted, locked out) cannot get back in on
their own. When they authenticate with a NEW Discord account, the identity
matcher in ``app.duplicate_prevention.find_user_for_discord_login`` refuses
the login on hijack/ambiguity grounds -- correctly, because "the email on
this Discord matches an account already linked to a different Discord ID" is
indistinguishable from an actual hijack attempt.

Refusing is right. Refusing SILENTLY is not: the member is stranded and no
admin learns about it unless the member happens to message someone. Every
refusal now writes a row here so it lands in a review queue an admin can
approve in one click (Admin Panel -> Discord -> Account Recovery).

Repeated attempts by the same Discord account collapse into ONE pending row
with an ``attempts`` counter -- a stranded member will retry, and the queue
should show one person needing help, not fifteen.

PII note: ``requested_discord_email`` is stored in the clear (unlike
``User.email``, which is encrypted). It is the whole point of the queue --
an admin verifies identity by seeing that the new Discord's email matches
the account being claimed. The queue is admin-only and rows should be
resolved, not left to accumulate.
"""

import json
import logging
from datetime import datetime

from app.core import db

logger = logging.getLogger(__name__)


class DiscordRelinkStatus:
    """Lifecycle of a relink request. Plain strings, not an Enum, to match the
    surrounding models (QuickProfile, approvals) which store status as text."""
    PENDING = 'pending'
    APPROVED = 'approved'
    REJECTED = 'rejected'

    ALL = (PENDING, APPROVED, REJECTED)


# Where the blocked login came from. Useful when triaging: a mobile block and
# a web block need different "here's what to tell them" instructions.
SOURCE_WEB_LOGIN = 'web_login'
SOURCE_WEB_REGISTER = 'web_register'
SOURCE_MOBILE = 'mobile'


class DiscordRelinkRequest(db.Model):
    """A Discord login that was refused because it looked like it belonged to
    an existing account."""

    __tablename__ = 'discord_relink_request'

    id = db.Column(db.Integer, primary_key=True)

    # --- Who is asking (the NEW Discord account) ---
    requested_discord_id = db.Column(db.String(32), nullable=False, index=True)
    requested_discord_username = db.Column(db.String(100), nullable=True)
    requested_discord_email = db.Column(db.String(255), nullable=True)

    # --- Why we refused ---
    # 'email_in_use_by_other_discord' | 'email_history_ambiguous'
    blocked_reason = db.Column(db.String(50), nullable=False)
    source = db.Column(db.String(20), nullable=False, default=SOURCE_WEB_LOGIN)

    # --- Which existing account we think they are ---
    # SET NULL on delete: a resolved request must survive the player row being
    # merged away, or the audit trail vanishes exactly when it matters.
    candidate_user_id = db.Column(
        db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True
    )
    candidate_player_id = db.Column(
        db.Integer, db.ForeignKey('player.id', ondelete='SET NULL'), nullable=True, index=True
    )
    # Ambiguous case only: JSON array of player ids that all plausibly match.
    # No single candidate, so an admin must pick.
    candidate_player_ids = db.Column(db.Text, nullable=True)
    # The Discord ID currently on the candidate player -- i.e. the account
    # they lost. Snapshotted so the queue still reads correctly after relink.
    # Sized to match Player.discord_id (100), not to the 17-20 digits a real
    # snowflake has: this value comes from our own table, which has held
    # hand-entered junk before, and an overflow here would abort the queue
    # write on the one path that exists to unblock a locked-out member.
    existing_discord_id = db.Column(db.String(100), nullable=True)

    # --- Lifecycle ---
    status = db.Column(db.String(20), nullable=False, default=DiscordRelinkStatus.PENDING, index=True)
    attempts = db.Column(db.Integer, nullable=False, default=1)
    first_seen_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    last_seen_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    resolved_at = db.Column(db.DateTime, nullable=True)
    resolved_by_user_id = db.Column(
        db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True
    )
    resolution_note = db.Column(db.Text, nullable=True)

    # --- Request forensics (a hijack attempt looks identical up front) ---
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.Text, nullable=True)

    candidate_user = db.relationship('User', foreign_keys=[candidate_user_id])
    candidate_player = db.relationship('Player', foreign_keys=[candidate_player_id])
    resolved_by = db.relationship('User', foreign_keys=[resolved_by_user_id])

    __table_args__ = (
        db.Index('idx_discord_relink_status_seen', 'status', 'last_seen_at'),
        db.Index('idx_discord_relink_discord_status', 'requested_discord_id', 'status'),
    )

    def __repr__(self):
        return (
            f'<DiscordRelinkRequest {self.id} discord_id={self.requested_discord_id} '
            f'reason={self.blocked_reason} status={self.status}>'
        )

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    @property
    def candidate_player_id_list(self):
        """Parse ``candidate_player_ids`` into a list of ints (never raises)."""
        if not self.candidate_player_ids:
            return []
        try:
            parsed = json.loads(self.candidate_player_ids)
        except (json.JSONDecodeError, TypeError):
            return []
        return [int(pid) for pid in parsed if str(pid).isdigit()]

    @property
    def is_pending(self):
        return self.status == DiscordRelinkStatus.PENDING

    @classmethod
    def pending_count(cls, session):
        """COUNT of open requests. Feeds the nav badge -- must stay cheap."""
        return session.query(db.func.count(cls.id)).filter(
            cls.status == DiscordRelinkStatus.PENDING
        ).scalar() or 0

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    @classmethod
    def record(cls, session, *, discord_id, blocked_reason, source,
               discord_username=None, discord_email=None,
               candidate_user_id=None, candidate_player_id=None,
               candidate_player_ids=None, existing_discord_id=None,
               ip_address=None, user_agent=None):
        """Record a refused Discord login, collapsing retries into one row.

        Returns ``(request, is_new)``. ``is_new`` is False when an existing
        pending row was bumped instead -- callers use it to avoid re-pinging
        admins every time a stranded member hits the login button again.

        Flushes but does not commit; the caller's transaction owns the write.
        """
        if not discord_id:
            return None, False

        existing = session.query(cls).filter(
            cls.requested_discord_id == str(discord_id),
            cls.status == DiscordRelinkStatus.PENDING,
        ).first()

        now = datetime.utcnow()

        if existing:
            existing.attempts = (existing.attempts or 1) + 1
            existing.last_seen_at = now
            # Refresh the details -- the candidate may have changed since the
            # first attempt (e.g. an admin edited the account in between).
            existing.blocked_reason = blocked_reason
            existing.source = source
            if discord_username:
                existing.requested_discord_username = discord_username
            if discord_email:
                existing.requested_discord_email = discord_email
            if candidate_user_id:
                existing.candidate_user_id = candidate_user_id
            if candidate_player_id:
                existing.candidate_player_id = candidate_player_id
            if candidate_player_ids:
                existing.candidate_player_ids = json.dumps(candidate_player_ids)
            if existing_discord_id:
                existing.existing_discord_id = existing_discord_id
            if ip_address:
                existing.ip_address = ip_address
            if user_agent:
                existing.user_agent = user_agent
            session.flush()
            logger.info(
                f"Discord relink request {existing.id} bumped to "
                f"{existing.attempts} attempts (discord_id={discord_id})"
            )
            return existing, False

        request_row = cls(
            requested_discord_id=str(discord_id),
            requested_discord_username=discord_username,
            requested_discord_email=(discord_email or '').lower() or None,
            blocked_reason=blocked_reason,
            source=source,
            candidate_user_id=candidate_user_id,
            candidate_player_id=candidate_player_id,
            candidate_player_ids=json.dumps(candidate_player_ids) if candidate_player_ids else None,
            existing_discord_id=existing_discord_id,
            status=DiscordRelinkStatus.PENDING,
            attempts=1,
            first_seen_at=now,
            last_seen_at=now,
            ip_address=ip_address,
            user_agent=(user_agent or '')[:1000] or None,
        )
        session.add(request_row)
        session.flush()
        logger.info(
            f"Discord relink request {request_row.id} opened: reason={blocked_reason} "
            f"discord_id={discord_id} candidate_player_id={candidate_player_id}"
        )
        return request_row, True

    def resolve(self, status, admin_user_id, note=None):
        """Close the request. Does not commit."""
        self.status = status
        self.resolved_at = datetime.utcnow()
        self.resolved_by_user_id = admin_user_id
        self.resolution_note = note

    def to_dict(self):
        return {
            'id': self.id,
            'requested_discord_id': self.requested_discord_id,
            'requested_discord_username': self.requested_discord_username,
            'requested_discord_email': self.requested_discord_email,
            'blocked_reason': self.blocked_reason,
            'source': self.source,
            'candidate_user_id': self.candidate_user_id,
            'candidate_player_id': self.candidate_player_id,
            'candidate_player_ids': self.candidate_player_id_list,
            'existing_discord_id': self.existing_discord_id,
            'status': self.status,
            'attempts': self.attempts,
            'first_seen_at': self.first_seen_at.isoformat() if self.first_seen_at else None,
            'last_seen_at': self.last_seen_at.isoformat() if self.last_seen_at else None,
            'resolved_at': self.resolved_at.isoformat() if self.resolved_at else None,
            'resolved_by_user_id': self.resolved_by_user_id,
            'resolution_note': self.resolution_note,
        }
