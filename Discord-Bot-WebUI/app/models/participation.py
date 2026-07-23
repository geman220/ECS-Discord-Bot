# app/models/participation.py

"""
Per-(player, season, league) participation rollup — the analytics spine.

Why this exists
---------------
``PlayerAttendanceStats`` (app/models/stats.py) has ``player_id`` UNIQUE: one row
per player, ever, carrying a single ``current_season_id`` that is overwritten at
rollover. So season history is destroyed rather than archived, and there is no
league dimension at all — every league filter in the reports actually matches on
``Player.primary_league_id``, which rollover repoints for every player.

This table adds the missing grain. It is a pure CACHE: every column is derivable
from ``matches`` + ``availability`` + ``match_attendance``, so it can always be
rebuilt with ``refresh_season_participation``. Nothing reads through it that
couldn't be recomputed.

The load-bearing distinction
----------------------------
``matches_played`` (the fixture date has passed) is the ONLY honest denominator
for a turnout percentage. ``matches_scheduled`` exists so the UI can say "9 of 14
played" — never so it can divide by it. Dividing by scheduled fixtures is exactly
the defect that made every player on the site read 0.0% during preseason.

``rsvp_yes`` and ``checked_in`` are deliberately separate columns. An RSVP is a
promise; a check-in is what happened. They are not the same measurement and the
UI must not present them as one.
"""

from datetime import datetime

from app.core import db


class PlayerSeasonParticipation(db.Model):
    __tablename__ = 'player_season_participation'

    id = db.Column(db.Integer, primary_key=True)

    player_id = db.Column(db.Integer, db.ForeignKey('player.id', ondelete='CASCADE'), nullable=False)
    season_id = db.Column(db.Integer, db.ForeignKey('season.id', ondelete='CASCADE'), nullable=False)
    league_id = db.Column(db.Integer, db.ForeignKey('league.id', ondelete='CASCADE'), nullable=False)

    # Their team in this league that season. NULL when rostered on more than one
    # team in the SAME league, in which case the counts are the union across them.
    team_id = db.Column(db.Integer, db.ForeignKey('team.id', ondelete='SET NULL'), nullable=True)
    team_count = db.Column(db.SmallInteger, nullable=False, default=1)

    matches_scheduled = db.Column(db.Integer, nullable=False, default=0)
    matches_played = db.Column(db.Integer, nullable=False, default=0)

    rsvp_yes = db.Column(db.Integer, nullable=False, default=0)
    rsvp_no = db.Column(db.Integer, nullable=False, default=0)
    rsvp_maybe = db.Column(db.Integer, nullable=False, default=0)
    rsvp_none = db.Column(db.Integer, nullable=False, default=0)

    # From match_attendance (QR / NFC / coach manual). 0 means "no check-ins
    # recorded", which is NOT "nobody turned up" — see `has_check_in_data`.
    checked_in = db.Column(db.Integer, nullable=False, default=0)

    was_coach = db.Column(db.Boolean, nullable=False, default=False)

    first_match_date = db.Column(db.Date, nullable=True)
    last_match_date = db.Column(db.Date, nullable=True)
    last_played_date = db.Column(db.Date, nullable=True)

    last_computed_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    player = db.relationship('Player', backref='season_participation')
    season = db.relationship('Season')
    league = db.relationship('League')
    team = db.relationship('Team')

    __table_args__ = (
        db.UniqueConstraint('player_id', 'season_id', 'league_id',
                            name='uq_psp_player_season_league'),
        db.Index('ix_psp_season_league', 'season_id', 'league_id'),
        db.Index('ix_psp_player', 'player_id'),
        db.Index('ix_psp_season_played', 'season_id', 'matches_played'),
    )

    # ---- derived, never stored -------------------------------------------
    # These are properties rather than columns so a formula change never
    # requires a backfill, and so there is exactly one definition of each rate.

    @property
    def turnout_pct(self):
        """% of PLAYED matches they RSVP'd yes to. None when nothing has been played.

        None, not 0.0 — "no matches yet" and "said no to everything" are different
        facts and must not render as the same number.
        """
        if not self.matches_played:
            return None
        return round(self.rsvp_yes / self.matches_played * 100, 1)

    @property
    def response_pct(self):
        """% of played matches they answered at all (yes/no/maybe)."""
        if not self.matches_played:
            return None
        answered = self.rsvp_yes + self.rsvp_no + self.rsvp_maybe
        return round(answered / self.matches_played * 100, 1)

    @property
    def has_check_in_data(self):
        """Whether check-in data exists at all for this row.

        Guard every "show rate" behind this. Check-in adoption is partial, so a
        0 would otherwise read as "never turned up" for a whole league that
        simply doesn't scan in.
        """
        return self.checked_in > 0

    @property
    def show_pct(self):
        """% of played matches they physically checked in for, or None."""
        if not self.matches_played or not self.has_check_in_data:
            return None
        return round(self.checked_in / self.matches_played * 100, 1)

    @property
    def reliability_gap(self):
        """Percentage points between saying yes and showing up. None if unknowable.

        Positive means they said yes more often than they appeared.
        """
        if self.turnout_pct is None or self.show_pct is None:
            return None
        return round(self.turnout_pct - self.show_pct, 1)

    def to_dict(self):
        return {
            'player_id': self.player_id,
            'season_id': self.season_id,
            'league_id': self.league_id,
            'team_id': self.team_id,
            'matches_scheduled': self.matches_scheduled,
            'matches_played': self.matches_played,
            'rsvp_yes': self.rsvp_yes,
            'rsvp_no': self.rsvp_no,
            'rsvp_maybe': self.rsvp_maybe,
            'rsvp_none': self.rsvp_none,
            'checked_in': self.checked_in,
            'was_coach': self.was_coach,
            'turnout_pct': self.turnout_pct,
            'response_pct': self.response_pct,
            'show_pct': self.show_pct,
            'first_match_date': self.first_match_date.isoformat() if self.first_match_date else None,
            'last_match_date': self.last_match_date.isoformat() if self.last_match_date else None,
            'last_computed_at': self.last_computed_at.isoformat() if self.last_computed_at else None,
        }

    def __repr__(self):
        return (f'<PlayerSeasonParticipation player={self.player_id} '
                f'season={self.season_id} league={self.league_id} '
                f'{self.rsvp_yes}/{self.matches_played}>')
