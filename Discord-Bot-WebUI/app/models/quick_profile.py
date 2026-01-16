# app/models/quick_profile.py

"""
Quick Profile Model

Stores temporary profiles for tryout players who show up without an existing
account. Each profile gets a 6-character claim code that the player can use
during Discord registration to link their account.

Workflow:
1. Admin creates quick profile with name, photo, notes
2. System generates unique 6-char claim code (expires in 30 days)
3. Player enters code during Discord registration to claim profile
4. Profile data (name, photo, notes) is merged into their new account
"""

import secrets
import string
import logging
from datetime import datetime, timedelta
from enum import Enum

from app.core import db

logger = logging.getLogger(__name__)


class QuickProfileStatus(Enum):
    """Status of a quick profile"""
    PENDING = 'pending'      # Created, waiting to be claimed
    CLAIMED = 'claimed'      # Successfully claimed during registration
    LINKED = 'linked'        # Manually linked to existing player by admin
    EXPIRED = 'expired'      # Expired after 30 days


class QuickProfile(db.Model):
    """
    Model for temporary tryout player profiles.

    Created by admins for walk-in players who don't have an account yet.
    The player receives a claim code to link their account later.
    """
    __tablename__ = 'quick_profile'

    id = db.Column(db.Integer, primary_key=True)

    # Unique 6-character alphanumeric claim code (e.g., "A7X9K2")
    claim_code = db.Column(db.String(6), unique=True, nullable=False, index=True)

    # Profile data (required)
    player_name = db.Column(db.String(100), nullable=False)
    profile_picture_url = db.Column(db.String(255), nullable=True)

    # Profile data (optional)
    notes = db.Column(db.Text, nullable=True)
    jersey_number = db.Column(db.Integer, nullable=True)
    jersey_size = db.Column(db.String(10), nullable=True)  # S, M, L, XL, XXL
    pronouns = db.Column(db.String(50), nullable=True)

    # Contact info for sending claim code (optional)
    email = db.Column(db.String(255), nullable=True)
    phone_number = db.Column(db.String(20), nullable=True)

    # Status tracking
    status = db.Column(db.String(20), default=QuickProfileStatus.PENDING.value, nullable=False)

    # Admin who created this profile
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # If claimed - which player received the data
    claimed_by_player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=True)
    claimed_at = db.Column(db.DateTime, nullable=True)

    # If manually linked - which admin linked it
    linked_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    linked_at = db.Column(db.DateTime, nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)

    # Relationships
    created_by = db.relationship('User', foreign_keys=[created_by_user_id], backref='created_quick_profiles')
    claimed_by_player = db.relationship('Player', foreign_keys=[claimed_by_player_id])
    linked_by = db.relationship('User', foreign_keys=[linked_by_user_id])

    def __repr__(self):
        return f'<QuickProfile {self.id} code={self.claim_code} status={self.status}>'

    @classmethod
    def generate_claim_code(cls, length=6):
        """
        Generate a unique 6-character alphanumeric claim code.

        Uses uppercase letters and digits only for easy reading/typing.
        Codes are case-insensitive (stored as uppercase).

        Returns:
            str: A unique claim code (e.g., "A7X9K2")
        """
        alphabet = string.ascii_uppercase + string.digits
        while True:
            code = ''.join(secrets.choice(alphabet) for _ in range(length))
            # Ensure uniqueness
            if not cls.query.filter_by(claim_code=code).first():
                return code

    @classmethod
    def create(cls, player_name, profile_picture_url, created_by_user_id,
               notes=None, jersey_number=None, jersey_size=None, pronouns=None,
               email=None, phone_number=None, expiry_days=30):
        """
        Create a new quick profile with auto-generated claim code.

        Args:
            player_name: Full name of the player (required)
            profile_picture_url: URL to the saved profile picture (required)
            created_by_user_id: ID of the admin creating this profile (required)
            notes: Optional admin notes about the player
            jersey_number: Optional preferred jersey number
            jersey_size: Optional jersey size (S, M, L, XL, XXL)
            pronouns: Optional pronouns
            email: Optional email address for sending claim code
            phone_number: Optional phone number for SMS claim code
            expiry_days: Days until code expires (default 30)

        Returns:
            QuickProfile: The created profile instance
        """
        profile = cls(
            claim_code=cls.generate_claim_code(),
            player_name=player_name,
            profile_picture_url=profile_picture_url,
            notes=notes,
            jersey_number=jersey_number,
            jersey_size=jersey_size,
            pronouns=pronouns,
            email=email,
            phone_number=phone_number,
            created_by_user_id=created_by_user_id,
            expires_at=datetime.utcnow() + timedelta(days=expiry_days)
        )
        return profile

    @classmethod
    def find_by_code(cls, code):
        """
        Find a quick profile by claim code (case-insensitive).

        Args:
            code: The claim code to search for

        Returns:
            QuickProfile or None
        """
        if not code:
            return None
        return cls.query.filter_by(claim_code=code.upper().strip()).first()

    def is_valid(self):
        """
        Check if this quick profile can still be claimed.

        A profile is valid if:
        - Status is PENDING
        - Not expired (current time < expires_at)

        If expired, automatically updates status to EXPIRED.

        Returns:
            bool: True if profile can be claimed
        """
        if self.status != QuickProfileStatus.PENDING.value:
            return False
        if datetime.utcnow() > self.expires_at:
            self.status = QuickProfileStatus.EXPIRED.value
            return False
        return True

    def claim(self, player):
        """
        Mark this profile as claimed and associate with a player.

        This merges the quick profile data into the player's profile.

        Args:
            player: The Player model instance claiming this profile

        Raises:
            ValueError: If profile is not valid for claiming
        """
        if not self.is_valid():
            raise ValueError("Quick profile is no longer valid for claiming")

        # Update player with quick profile data
        player.name = self.player_name
        if self.profile_picture_url:
            player.profile_picture_url = self.profile_picture_url
        if self.notes:
            # Append to existing notes if any
            if player.notes:
                player.notes = f"{player.notes}\n\n[From tryout profile]: {self.notes}"
            else:
                player.notes = self.notes
        if self.jersey_number is not None:
            player.jersey_number = self.jersey_number
        if self.jersey_size:
            player.jersey_size = self.jersey_size
        if self.pronouns:
            player.pronouns = self.pronouns

        # Mark as claimed
        self.claimed_by_player_id = player.id
        self.claimed_at = datetime.utcnow()
        self.status = QuickProfileStatus.CLAIMED.value

        logger.info(f"Quick profile {self.id} (code={self.claim_code}) claimed by player {player.id}")

    def link_to_player(self, player, admin_user, overwrite_photo=False):
        """
        Manually link this profile to an existing player (admin action).

        Args:
            player: The existing Player to link to
            admin_user: The User (admin) performing the link
            overwrite_photo: If True, replace player's existing photo

        Raises:
            ValueError: If profile is not valid for linking
        """
        if self.status not in [QuickProfileStatus.PENDING.value]:
            raise ValueError(f"Cannot link profile with status {self.status}")

        # Update player with quick profile data
        if self.profile_picture_url and (overwrite_photo or not player.profile_picture_url):
            player.profile_picture_url = self.profile_picture_url

        if self.notes:
            if player.notes:
                player.notes = f"{player.notes}\n\n[Linked from tryout profile]: {self.notes}"
            else:
                player.notes = self.notes

        # Copy optional fields if not already set on player
        if self.jersey_number is not None and player.jersey_number is None:
            player.jersey_number = self.jersey_number
        if self.jersey_size and not player.jersey_size:
            player.jersey_size = self.jersey_size
        if self.pronouns and not player.pronouns:
            player.pronouns = self.pronouns

        # Mark as linked
        self.claimed_by_player_id = player.id
        self.linked_by_user_id = admin_user.id
        self.linked_at = datetime.utcnow()
        self.status = QuickProfileStatus.LINKED.value

        logger.info(f"Quick profile {self.id} linked to player {player.id} by admin {admin_user.id}")

    def to_dict(self, include_created_by=True):
        """
        Convert to dictionary for JSON serialization.

        Args:
            include_created_by: If True, include created_by user info

        Returns:
            dict: Profile data as dictionary
        """
        # Get linked player name if available
        linked_player_name = None
        if self.claimed_by_player:
            linked_player_name = self.claimed_by_player.name

        data = {
            'id': self.id,
            'claim_code': self.claim_code,
            # Include both field names for compatibility
            'name': self.player_name,  # Mobile app expects 'name'
            'player_name': self.player_name,  # Keep original for web
            'profile_picture_url': self.profile_picture_url,
            'notes': self.notes,
            'jersey_number': self.jersey_number,
            'jersey_size': self.jersey_size,
            'pronouns': self.pronouns,
            'email': self.email,
            # Include both field names for compatibility
            'phone': self.phone_number,  # Mobile app expects 'phone'
            'phone_number': self.phone_number,  # Keep original for web
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'claimed_at': self.claimed_at.isoformat() if self.claimed_at else None,
            'claimed_by_player_id': self.claimed_by_player_id,
            'linked_player_id': self.claimed_by_player_id,  # Alias for mobile
            'linked_player_name': linked_player_name,  # Mobile expects this
            'linked_at': self.linked_at.isoformat() if self.linked_at else None,
            'linked_by_user_id': self.linked_by_user_id,
        }

        if include_created_by and self.created_by:
            data['created_by'] = {
                'id': self.created_by.id,
                'name': self.created_by.username,  # Mobile expects 'name'
                'username': self.created_by.username  # Keep for web
            }

        return data
