# app/models/match_lineup.py

"""
Match Lineup Model

This module contains the model for per-match lineup assignments:
- MatchLineup: Position assignments for players in a specific match

Supports:
- Multiple players per position (for rotation)
- RSVP integration via Match.availability
- Real-time collaboration between coaches
- Optimistic locking for concurrent edits
"""

import logging
from datetime import datetime

from sqlalchemy.dialects.postgresql import JSONB

from app.core import db

logger = logging.getLogger(__name__)


class MatchLineup(db.Model):
    """
    Model representing per-match lineup assignments for a team.

    Stores position assignments as JSONB allowing multiple players per position
    for rotation purposes. Each position entry includes player_id, position code,
    and order (for priority within position).

    Position codes: gk, lb, cb, rb, lwb, rwb, cdm, cm, cam, lw, rw, st, bench

    Example positions structure:
    [
        {"player_id": 1, "position": "gk", "order": 0},
        {"player_id": 2, "position": "lw", "order": 0},
        {"player_id": 3, "position": "lw", "order": 1},
        {"player_id": 4, "position": "lw", "order": 2},
        {"player_id": 5, "position": "bench", "order": 0}
    ]
    """
    __tablename__ = 'match_lineups'

    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(
        db.Integer,
        db.ForeignKey('matches.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    team_id = db.Column(
        db.Integer,
        db.ForeignKey('team.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )

    # JSONB array of position assignments
    # Format: [{"player_id": int, "position": str, "order": int}, ...]
    positions = db.Column(JSONB, default=list, nullable=False)

    # Metadata
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by = db.Column(
        db.Integer,
        db.ForeignKey('users.id'),
        nullable=False
    )
    last_updated_by = db.Column(
        db.Integer,
        db.ForeignKey('users.id'),
        nullable=True
    )

    # Optimistic locking for concurrent edit protection
    version = db.Column(db.Integer, default=1, nullable=False)

    # Relationships
    match = db.relationship(
        'Match',
        backref=db.backref('lineups', lazy='dynamic', cascade='all, delete-orphan')
    )
    team = db.relationship(
        'Team',
        backref=db.backref('match_lineups', lazy='dynamic')
    )
    creator = db.relationship(
        'User',
        foreign_keys=[created_by],
        backref=db.backref('created_lineups', lazy='dynamic')
    )
    last_editor = db.relationship(
        'User',
        foreign_keys=[last_updated_by],
        backref=db.backref('edited_lineups', lazy='dynamic')
    )

    # Constraints
    __table_args__ = (
        db.UniqueConstraint('match_id', 'team_id', name='uq_match_lineup_team'),
        db.Index('idx_match_lineup_positions', 'positions', postgresql_using='gin'),
    )

    # Valid position codes
    VALID_POSITIONS = {
        'gk', 'lb', 'cb', 'rb', 'lwb', 'rwb',
        'cdm', 'cm', 'cam', 'lw', 'rw', 'st', 'bench'
    }

    def to_dict(self, include_meta=True):
        """Convert lineup to dictionary for API responses."""
        data = {
            'id': self.id,
            'match_id': self.match_id,
            'team_id': self.team_id,
            'positions': self.positions or [],
            'notes': self.notes,
            'version': self.version
        }

        if include_meta:
            data.update({
                'created_at': self.created_at.isoformat() if self.created_at else None,
                'updated_at': self.updated_at.isoformat() if self.updated_at else None,
                'created_by': self.created_by,
                'last_updated_by': self.last_updated_by
            })

        return data

    def get_players_at_position(self, position):
        """Get all player IDs assigned to a specific position, ordered by priority."""
        if not self.positions:
            return []

        players = [
            p for p in self.positions
            if p.get('position') == position
        ]
        return sorted(players, key=lambda x: x.get('order', 0))

    def get_player_position(self, player_id):
        """Get the position for a specific player, or None if not in lineup."""
        if not self.positions:
            return None

        for p in self.positions:
            if p.get('player_id') == player_id:
                return p.get('position')
        return None

    def add_player(self, player_id, position, order=None):
        """
        Add a player to a position in the lineup.

        Args:
            player_id: The player's ID
            position: Position code (e.g., 'gk', 'lw', 'bench')
            order: Priority order within position (auto-calculated if None)

        Returns:
            The position entry that was added
        """
        if position not in self.VALID_POSITIONS:
            raise ValueError(f"Invalid position: {position}")

        # Remove player from any existing position first
        self.remove_player(player_id)

        # Auto-calculate order if not provided
        if order is None:
            existing = self.get_players_at_position(position)
            order = len(existing)

        entry = {
            'player_id': player_id,
            'position': position,
            'order': order
        }

        if self.positions is None:
            self.positions = []

        self.positions.append(entry)
        return entry

    def remove_player(self, player_id):
        """
        Remove a player from the lineup.

        Args:
            player_id: The player's ID

        Returns:
            The removed position entry, or None if player wasn't in lineup
        """
        if not self.positions:
            return None

        for i, p in enumerate(self.positions):
            if p.get('player_id') == player_id:
                removed = self.positions.pop(i)
                return removed

        return None

    def move_player(self, player_id, new_position, new_order=None):
        """
        Move a player to a new position.

        Args:
            player_id: The player's ID
            new_position: New position code
            new_order: New priority order (auto-calculated if None)

        Returns:
            The updated position entry
        """
        return self.add_player(player_id, new_position, new_order)

    def get_position_counts(self):
        """Get counts of players at each position."""
        counts = {pos: 0 for pos in self.VALID_POSITIONS}

        if self.positions:
            for p in self.positions:
                pos = p.get('position')
                if pos in counts:
                    counts[pos] += 1

        return counts

    def increment_version(self):
        """Increment version for optimistic locking."""
        self.version = (self.version or 0) + 1
        return self.version

    def __repr__(self):
        return f"<MatchLineup match_id={self.match_id} team_id={self.team_id} players={len(self.positions or [])}>"
