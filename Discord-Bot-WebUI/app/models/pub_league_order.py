# app/models/pub_league_order.py

"""
Pub League Order Models

These models track Pub League WooCommerce order linking, pass assignment,
and claim links for the order linking wizard flow.

Tables:
- pub_league_order: Main order tracking
- pub_league_order_line_item: Individual passes (quantity expansion)
- pub_league_order_claim: Claim links for unassigned passes
"""

import secrets
from datetime import datetime, timedelta
from enum import Enum

from app.core import db


class PubLeagueOrderStatus(Enum):
    """Status of a Pub League order"""
    NOT_STARTED = 'not_started'  # Order created from webhook, link not clicked yet
    PENDING = 'pending'  # Link clicked, no passes assigned yet
    PARTIALLY_LINKED = 'partially_linked'
    FULLY_LINKED = 'fully_linked'
    CANCELLED = 'cancelled'


class PubLeagueLineItemStatus(Enum):
    """Status of an individual line item/pass"""
    UNASSIGNED = 'unassigned'
    ASSIGNED = 'assigned'
    CLAIMED = 'claimed'
    PASS_CREATED = 'pass_created'


class PubLeagueClaimStatus(Enum):
    """Status of a claim link"""
    PENDING = 'pending'
    CLAIMED = 'claimed'
    EXPIRED = 'expired'
    CANCELLED = 'cancelled'


class PubLeagueOrder(db.Model):
    """
    Tracks Pub League order processing state.

    Created when a user lands on the linking wizard from WooCommerce.
    Stores order data and tracks how many passes have been linked.
    """
    __tablename__ = 'pub_league_order'

    id = db.Column(db.Integer, primary_key=True)
    woo_order_id = db.Column(db.Integer, unique=True, nullable=False, index=True)

    # Security token for order verification (HMAC-SHA256 from WooCommerce plugin)
    verification_token = db.Column(db.String(64), unique=True, nullable=False, index=True)

    # Customer info from WooCommerce billing
    customer_email = db.Column(db.String(255), nullable=True)
    customer_name = db.Column(db.String(100), nullable=True)

    # Season tracking
    season_name = db.Column(db.String(50), nullable=True)  # e.g., "2025 Fall"
    season_id = db.Column(db.Integer, db.ForeignKey('season.id'), nullable=True)

    # Processing state
    status = db.Column(db.String(30), default=PubLeagueOrderStatus.PENDING.value, nullable=False)
    total_passes = db.Column(db.Integer, default=0, nullable=False)
    linked_passes = db.Column(db.Integer, default=0, nullable=False)

    # Primary user who initiated the linking (first claimant)
    primary_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    # Cached order data from WooCommerce (JSON blob)
    woo_order_data = db.Column(db.JSON, nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=True)  # Token expiration

    # Relationships
    line_items = db.relationship(
        'PubLeagueOrderLineItem',
        back_populates='order',
        cascade='all, delete-orphan',
        lazy='dynamic'
    )
    season = db.relationship('Season', backref='pub_league_orders')
    primary_user = db.relationship('User', foreign_keys=[primary_user_id])

    def __repr__(self):
        return f'<PubLeagueOrder {self.id} woo_order={self.woo_order_id} status={self.status}>'

    @classmethod
    def generate_verification_token(cls):
        """Generate a secure 64-character verification token."""
        return secrets.token_hex(32)

    @classmethod
    def find_by_woo_order_id(cls, woo_order_id):
        """Find order by WooCommerce order ID."""
        return cls.query.filter_by(woo_order_id=woo_order_id).first()

    @classmethod
    def find_by_verification_token(cls, token):
        """Find order by verification token."""
        return cls.query.filter_by(verification_token=token).first()

    def is_fully_linked(self):
        """Check if all passes have been linked."""
        return self.linked_passes >= self.total_passes

    def update_status(self):
        """Update status based on linked passes count."""
        # Don't change NOT_STARTED status here - that's handled when link is clicked
        if self.status == PubLeagueOrderStatus.NOT_STARTED.value:
            return
        if self.linked_passes == 0:
            self.status = PubLeagueOrderStatus.PENDING.value
        elif self.linked_passes < self.total_passes:
            self.status = PubLeagueOrderStatus.PARTIALLY_LINKED.value
        else:
            self.status = PubLeagueOrderStatus.FULLY_LINKED.value

    def mark_link_clicked(self):
        """Transition from NOT_STARTED to PENDING when link is clicked."""
        if self.status == PubLeagueOrderStatus.NOT_STARTED.value:
            self.status = PubLeagueOrderStatus.PENDING.value

    def get_unassigned_line_items(self):
        """Get all line items that haven't been assigned yet."""
        return self.line_items.filter_by(status=PubLeagueLineItemStatus.UNASSIGNED.value).all()

    def to_dict(self):
        """Convert to dictionary for JSON serialization."""
        return {
            'id': self.id,
            'woo_order_id': self.woo_order_id,
            'customer_email': self.customer_email,
            'customer_name': self.customer_name,
            'season_name': self.season_name,
            'status': self.status,
            'total_passes': self.total_passes,
            'linked_passes': self.linked_passes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'line_items': [item.to_dict() for item in self.line_items.all()]
        }


class PubLeagueOrderLineItem(db.Model):
    """
    Individual passes from a Pub League order (quantity expansion).

    Each line item represents one pass that can be assigned to a player.
    For example, if someone orders 2 Premier passes, this creates 2 line items.
    """
    __tablename__ = 'pub_league_order_line_item'

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(
        db.Integer,
        db.ForeignKey('pub_league_order.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )

    # Original WooCommerce line item reference
    woo_line_item_id = db.Column(db.Integer, nullable=True)

    # Product details extracted from WooCommerce
    product_name = db.Column(db.String(255), nullable=False)
    division = db.Column(db.String(50), nullable=True)  # 'Classic' or 'Premier'
    jersey_size = db.Column(db.String(10), nullable=True)  # Extracted from variation

    # Assignment - who this pass is for
    assigned_player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=True)
    assigned_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    # Status tracking
    status = db.Column(db.String(30), default=PubLeagueLineItemStatus.UNASSIGNED.value)

    # Generated wallet pass (after assignment and pass creation)
    wallet_pass_id = db.Column(db.Integer, db.ForeignKey('wallet_pass.id'), nullable=True)

    # Claim link reference (if sent to someone else)
    claim_id = db.Column(db.Integer, db.ForeignKey('pub_league_order_claim.id'), nullable=True)

    # Timestamps
    assigned_at = db.Column(db.DateTime, nullable=True)
    pass_created_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    order = db.relationship('PubLeagueOrder', back_populates='line_items')
    assigned_player = db.relationship('Player', foreign_keys=[assigned_player_id])
    assigned_user = db.relationship('User', foreign_keys=[assigned_user_id])
    wallet_pass = db.relationship('WalletPass')
    # Note: claim relationship uses claim_id FK - separate from PubLeagueOrderClaim.line_item_id
    claim = db.relationship('PubLeagueOrderClaim', foreign_keys=[claim_id], uselist=False)

    def __repr__(self):
        return f'<PubLeagueOrderLineItem {self.id} order={self.order_id} division={self.division} status={self.status}>'

    def assign_to_player(self, player, user=None):
        """
        Assign this line item to a player.

        Args:
            player: Player model instance
            user: Optional User model instance
        """
        self.assigned_player_id = player.id
        self.assigned_user_id = user.id if user else (player.user_id if player.user_id else None)
        self.status = PubLeagueLineItemStatus.ASSIGNED.value
        self.assigned_at = datetime.utcnow()

        # Update parent order's linked count
        if self.order:
            self.order.linked_passes += 1
            self.order.update_status()

    def mark_pass_created(self, wallet_pass):
        """Mark that the wallet pass has been generated."""
        self.wallet_pass_id = wallet_pass.id
        self.status = PubLeagueLineItemStatus.PASS_CREATED.value
        self.pass_created_at = datetime.utcnow()

    def is_assigned(self):
        """Check if this line item has been assigned."""
        return self.status in [
            PubLeagueLineItemStatus.ASSIGNED.value,
            PubLeagueLineItemStatus.CLAIMED.value,
            PubLeagueLineItemStatus.PASS_CREATED.value
        ]

    def to_dict(self):
        """Convert to dictionary for JSON serialization."""
        return {
            'id': self.id,
            'product_name': self.product_name,
            'division': self.division,
            'jersey_size': self.jersey_size,
            'status': self.status,
            'assigned_player_id': self.assigned_player_id,
            'assigned_user_id': self.assigned_user_id,
            'wallet_pass_id': self.wallet_pass_id,
            'claim_id': self.claim_id,
            'assigned_at': self.assigned_at.isoformat() if self.assigned_at else None
        }


class PubLeagueOrderClaim(db.Model):
    """
    Claim links for unassigned Pub League passes.

    Created when the purchaser wants to assign a pass to someone else
    who may not have an account yet. The claim link is sent via email
    and expires after 7 days.
    """
    __tablename__ = 'pub_league_order_claim'

    id = db.Column(db.Integer, primary_key=True)

    # Secure claim token (64 characters)
    claim_token = db.Column(db.String(64), unique=True, nullable=False, index=True)

    # Source order and line item
    order_id = db.Column(
        db.Integer,
        db.ForeignKey('pub_league_order.id', ondelete='CASCADE'),
        nullable=False
    )
    line_item_id = db.Column(
        db.Integer,
        db.ForeignKey('pub_league_order_line_item.id'),
        nullable=True
    )

    # Optional recipient info (for notification email)
    recipient_email = db.Column(db.String(255), nullable=True)
    recipient_name = db.Column(db.String(100), nullable=True)

    # Who created this claim link
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    # Claim status
    status = db.Column(db.String(30), default=PubLeagueClaimStatus.PENDING.value)

    # Who claimed it (populated when claim is processed)
    claimed_by_player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=True)
    claimed_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    claimed_at = db.Column(db.DateTime, nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)

    # Notification tracking
    email_sent_at = db.Column(db.DateTime, nullable=True)
    reminder_sent_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    order = db.relationship('PubLeagueOrder')
    line_item = db.relationship(
        'PubLeagueOrderLineItem',
        foreign_keys=[line_item_id],
        uselist=False
    )
    created_by = db.relationship('User', foreign_keys=[created_by_user_id])
    claimed_by_player = db.relationship('Player', foreign_keys=[claimed_by_player_id])
    claimed_by_user = db.relationship('User', foreign_keys=[claimed_by_user_id])

    def __repr__(self):
        return f'<PubLeagueOrderClaim {self.id} token={self.claim_token[:8]}... status={self.status}>'

    @classmethod
    def generate_claim_token(cls):
        """Generate a secure 64-character claim token."""
        return secrets.token_hex(32)

    @classmethod
    def create_claim(cls, order, line_item, created_by_user=None, recipient_email=None, recipient_name=None, expiry_days=7):
        """
        Create a new claim link for a line item.

        Args:
            order: PubLeagueOrder instance
            line_item: PubLeagueOrderLineItem instance
            created_by_user: User who created this claim
            recipient_email: Optional email to send claim link to
            recipient_name: Optional name of recipient
            expiry_days: Number of days until claim expires (default 7)

        Returns:
            PubLeagueOrderClaim instance
        """
        claim = cls(
            claim_token=cls.generate_claim_token(),
            order_id=order.id,
            line_item_id=line_item.id,
            recipient_email=recipient_email,
            recipient_name=recipient_name,
            created_by_user_id=created_by_user.id if created_by_user else None,
            expires_at=datetime.utcnow() + timedelta(days=expiry_days)
        )

        # Link claim to line item
        line_item.claim_id = claim.id

        return claim

    @classmethod
    def find_by_token(cls, token):
        """Find claim by token."""
        return cls.query.filter_by(claim_token=token).first()

    def is_valid(self):
        """Check if claim is still valid (not expired, not already claimed)."""
        if self.status != PubLeagueClaimStatus.PENDING.value:
            return False
        if datetime.utcnow() > self.expires_at:
            self.status = PubLeagueClaimStatus.EXPIRED.value
            return False
        return True

    def process_claim(self, player, user):
        """
        Process a claim - assign the pass to the claiming player.

        Args:
            player: Player model instance who is claiming
            user: User model instance who is claiming
        """
        if not self.is_valid():
            raise ValueError("Claim is no longer valid")

        # Update claim record
        self.claimed_by_player_id = player.id
        self.claimed_by_user_id = user.id
        self.claimed_at = datetime.utcnow()
        self.status = PubLeagueClaimStatus.CLAIMED.value

        # Assign line item to player
        if self.line_item:
            self.line_item.assign_to_player(player, user)
            self.line_item.status = PubLeagueLineItemStatus.CLAIMED.value

    def to_dict(self):
        """Convert to dictionary for JSON serialization."""
        return {
            'id': self.id,
            'claim_token': self.claim_token,
            'order_id': self.order_id,
            'line_item_id': self.line_item_id,
            'recipient_email': self.recipient_email,
            'recipient_name': self.recipient_name,
            'status': self.status,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'claimed_at': self.claimed_at.isoformat() if self.claimed_at else None,
            'is_valid': self.is_valid()
        }
