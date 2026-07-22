# app/models/league_membership.py

"""
League Membership Model

The unified spine for a person's participation. One row per
(player, season, league_type, role) — multiple rows per person per season is the
point: the same person can be a free `sub` in ECS FC and a paid `player` in
Premier in the same season.

This SUPERSEDES the smeared model (Player.is_sub / is_current_player booleans,
SubstitutePool/EcsFcSubPool tables, the pl-waitlist role + waitlist_league column)
by giving role + status a single per-league-per-season home.

Design + rollout plan: ~/.claude/plans/registration-lifecycle-overhaul.md
Phase 0: this model maps the already-created + backfilled `league_membership`
table. Reads still run off the old columns until Phase 2; existing write paths
dual-write here (behavior-neutral) until the read cutover.
"""

from datetime import datetime

from app.core import db


class LeagueMembership(db.Model):
    """A person's role + status in one league_type for one season."""
    __tablename__ = 'league_membership'
    __table_args__ = (
        db.UniqueConstraint(
            'player_id', 'season_id', 'league_type', 'role',
            name='uq_league_membership_person_lane_role'
        ),
        db.Index('ix_league_membership_scan', 'season_id', 'league_type', 'role', 'status'),
        db.Index('ix_league_membership_player', 'player_id'),
        db.Index('ix_league_membership_team', 'team_id'),
    )

    # --- vocab (enforced in the app layer, not the DB, to stay flexible) ---
    LEAGUE_TYPES = ('classic', 'premier', 'ecs_fc')
    ROLES = ('waitlist', 'sub', 'player', 'coach')
    SOURCES = ('self_signup', 'quick_profile', 'paid_registration', 'admin', 'draft', 'backfill')
    STATUSES = {
        'waitlist': ('waiting', 'offered', 'converted', 'removed'),
        'sub':      ('pending', 'active', 'resting', 'retired'),
        'player':   ('unrostered', 'rostered', 'inactive'),
        'coach':    ('active', 'inactive'),
    }

    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id', ondelete='CASCADE'), nullable=False)
    season_id = db.Column(db.Integer, db.ForeignKey('season.id', ondelete='CASCADE'), nullable=False)

    league_type = db.Column(db.String(16), nullable=False)   # classic | premier | ecs_fc
    role = db.Column(db.String(16), nullable=False)          # waitlist | sub | player | coach
    status = db.Column(db.String(24), nullable=False)        # role-specific (see STATUSES)

    team_id = db.Column(db.Integer, db.ForeignKey('team.id', ondelete='SET NULL'), nullable=True)
    source = db.Column(db.String(24), nullable=True)

    # player role only; NULL for ECS FC players (approval-activated) and all subs (subs never pay).
    paid_at = db.Column(db.DateTime, nullable=True)
    activated_at = db.Column(db.DateTime, nullable=True)     # entered the active/contactable set
    rested_at = db.Column(db.DateTime, nullable=True)        # sub moved to resting
    last_engaged_at = db.Column(db.DateTime, nullable=True)  # last accepted request / match played
    needs_reconfirm = db.Column(db.Boolean, nullable=False, default=False)

    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    player = db.relationship(
        'Player',
        backref=db.backref('league_memberships', cascade='all, delete-orphan', passive_deletes=True)
    )
    season = db.relationship('Season')
    team = db.relationship('Team')

    @property
    def is_active_sub(self):
        """True only for a sub currently in the contact rotation."""
        return self.role == 'sub' and self.status == 'active'

    @property
    def is_playing(self):
        """True for a rostered player (the 'active paying player' signal, minus payment)."""
        return self.role == 'player' and self.status == 'rostered'

    def to_dict(self):
        return {
            'id': self.id,
            'player_id': self.player_id,
            'season_id': self.season_id,
            'league_type': self.league_type,
            'role': self.role,
            'status': self.status,
            'team_id': self.team_id,
            'source': self.source,
            'paid_at': self.paid_at.isoformat() if self.paid_at else None,
            'activated_at': self.activated_at.isoformat() if self.activated_at else None,
            'rested_at': self.rested_at.isoformat() if self.rested_at else None,
            'last_engaged_at': self.last_engaged_at.isoformat() if self.last_engaged_at else None,
            'needs_reconfirm': self.needs_reconfirm,
            'notes': self.notes,
        }

    def __repr__(self):
        return (f'<LeagueMembership player={self.player_id} '
                f'{self.league_type}/{self.role}={self.status} season={self.season_id}>')
