# app/models/wallet.py

"""
Wallet Pass Models Module

This module contains models for managing digital wallet passes:
- WalletPassType: Defines membership types (ECS Annual, Pub League Seasonal)
- WalletPass: Individual issued passes with tracking
- WalletPassDevice: Device registrations for push updates
- WalletPassCheckin: Check-in/validation history
"""

import secrets
import logging
from datetime import datetime, timedelta
from enum import Enum

from app.core import db
from sqlalchemy import text

logger = logging.getLogger(__name__)


def ensure_wallet_columns():
    """
    Ensure all required columns exist in wallet tables.
    This handles schema migrations for new columns added after initial deployment.
    """
    try:
        # Check and add google_hero_image_url column if missing
        result = db.session.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'wallet_pass_type' AND column_name = 'google_hero_image_url'
        """))
        if not result.fetchone():
            logger.info("Adding google_hero_image_url column to wallet_pass_type")
            db.session.execute(text("""
                ALTER TABLE wallet_pass_type
                ADD COLUMN google_hero_image_url VARCHAR(500)
            """))
            db.session.commit()
            logger.info("Successfully added google_hero_image_url column")

        # Check and add google_logo_url column if missing
        result = db.session.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'wallet_pass_type' AND column_name = 'google_logo_url'
        """))
        if not result.fetchone():
            logger.info("Adding google_logo_url column to wallet_pass_type")
            db.session.execute(text("""
                ALTER TABLE wallet_pass_type
                ADD COLUMN google_logo_url VARCHAR(500)
            """))
            db.session.commit()
            logger.info("Successfully added google_logo_url column")

        # Check and add apple_pass_style column if missing
        result = db.session.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'wallet_pass_type' AND column_name = 'apple_pass_style'
        """))
        if not result.fetchone():
            logger.info("Adding apple_pass_style column to wallet_pass_type")
            db.session.execute(text("""
                ALTER TABLE wallet_pass_type
                ADD COLUMN apple_pass_style VARCHAR(20) DEFAULT 'generic'
            """))
            db.session.commit()
            logger.info("Successfully added apple_pass_style column")

        # Check and add show_logo column if missing
        result = db.session.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'wallet_pass_type' AND column_name = 'show_logo'
        """))
        if not result.fetchone():
            logger.info("Adding show_logo column to wallet_pass_type")
            db.session.execute(text("""
                ALTER TABLE wallet_pass_type
                ADD COLUMN show_logo BOOLEAN DEFAULT TRUE
            """))
            db.session.commit()
            logger.info("Successfully added show_logo column")

    except Exception as e:
        logger.error(f"Error ensuring wallet columns: {e}")
        db.session.rollback()
        raise


class PassValidityType(Enum):
    """Types of pass validity periods"""
    ANNUAL = 'annual'
    SEASONAL = 'seasonal'


class PassStatus(Enum):
    """Status of a wallet pass"""
    ACTIVE = 'active'
    VOIDED = 'voided'
    EXPIRED = 'expired'
    REPLACED = 'replaced'


class CheckInType(Enum):
    """Types of check-in methods"""
    QR_SCAN = 'qr_scan'
    NFC_TAP = 'nfc_tap'
    MANUAL = 'manual'


class WalletPassType(db.Model):
    """Defines types of wallet passes (ECS Membership, Pub League)"""
    __tablename__ = 'wallet_pass_type'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)

    # Pass design
    template_name = db.Column(db.String(100), nullable=False)
    background_color = db.Column(db.String(7), default='#213e96')
    foreground_color = db.Column(db.String(7), default='#ffffff')
    label_color = db.Column(db.String(7), default='#c8c8c8')
    logo_text = db.Column(db.String(50), default='ECS')

    # Validity settings
    validity_type = db.Column(db.String(20), nullable=False)
    validity_duration_days = db.Column(db.Integer)
    grace_period_days = db.Column(db.Integer, default=30)

    # WooCommerce product pattern matching (JSON array of regex patterns)
    woo_product_patterns = db.Column(db.Text)

    # Apple Wallet settings
    apple_pass_type_id = db.Column(db.String(100))
    # Pass style: 'storeCard', 'generic', or 'eventTicket'
    # - storeCard: Strip image with primary field overlaid (default)
    # - generic: Thumbnail with clean separated fields (recommended for memberships)
    # - eventTicket: Strip image with primary overlaid, has notch at top
    apple_pass_style = db.Column(db.String(20), default='generic')

    # Google Wallet settings
    google_issuer_id = db.Column(db.String(50))
    google_class_id = db.Column(db.String(100))
    google_hero_image_url = db.Column(db.String(500), nullable=True)
    google_logo_url = db.Column(db.String(500), nullable=True)

    # Barcode settings
    suppress_barcode = db.Column(db.Boolean, default=False)  # If True, barcode won't be shown on pass

    # Logo visibility settings
    show_logo = db.Column(db.Boolean, default=True)  # If False, logo won't be shown even if uploaded

    # Status
    is_active = db.Column(db.Boolean, default=True)
    display_order = db.Column(db.Integer, default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    passes = db.relationship('WalletPass', back_populates='pass_type', lazy='dynamic')

    def __repr__(self):
        return f'<WalletPassType {self.code}: {self.name}>'

    def to_dict(self):
        return {
            'id': self.id,
            'code': self.code,
            'name': self.name,
            'description': self.description,
            'validity_type': self.validity_type,
            'background_color': self.background_color,
            'foreground_color': self.foreground_color,
            'label_color': self.label_color,
            'logo_text': self.logo_text,
            'apple_pass_style': self.apple_pass_style or 'generic',
            'google_hero_image_url': self.google_hero_image_url,
            'google_logo_url': self.google_logo_url,
            'suppress_barcode': self.suppress_barcode or False,
            'show_logo': self.show_logo if self.show_logo is not None else True,
            'is_active': self.is_active
        }

    @classmethod
    def get_by_code(cls, code):
        return cls.query.filter_by(code=code, is_active=True).first()

    @classmethod
    def get_ecs_membership(cls):
        return cls.get_by_code('ecs_membership')

    @classmethod
    def get_pub_league(cls):
        return cls.get_by_code('pub_league')


class WalletPass(db.Model):
    """Tracks all issued wallet passes"""
    __tablename__ = 'wallet_pass'

    id = db.Column(db.Integer, primary_key=True)
    serial_number = db.Column(db.String(100), unique=True, nullable=False)

    pass_type_id = db.Column(db.Integer, db.ForeignKey('wallet_pass_type.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=True)

    member_name = db.Column(db.String(100), nullable=False)
    member_email = db.Column(db.String(255), nullable=True)
    team_name = db.Column(db.String(100), nullable=True)

    # WooCommerce integration
    woo_order_id = db.Column(db.Integer, nullable=True, index=True)
    download_token = db.Column(db.String(64), unique=True, nullable=False, index=True)

    # Validity
    season_id = db.Column(db.Integer, db.ForeignKey('season.id'), nullable=True)
    membership_year = db.Column(db.Integer, nullable=True)
    valid_from = db.Column(db.DateTime, nullable=False)
    valid_until = db.Column(db.DateTime, nullable=False)

    # Status
    status = db.Column(db.String(20), default='active', index=True)
    voided_at = db.Column(db.DateTime, nullable=True)
    voided_reason = db.Column(db.String(200), nullable=True)
    voided_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    # Wallet authentication
    authentication_token = db.Column(db.String(64), nullable=False)
    barcode_data = db.Column(db.String(200), nullable=False)

    # Generation tracking
    apple_pass_generated = db.Column(db.Boolean, default=False)
    apple_pass_generated_at = db.Column(db.DateTime, nullable=True)
    google_pass_generated = db.Column(db.Boolean, default=False)
    google_pass_generated_at = db.Column(db.DateTime, nullable=True)
    google_pass_url = db.Column(db.Text, nullable=True)  # JWT URLs can be 1000+ chars

    # Download tracking
    download_count = db.Column(db.Integer, default=0)
    last_downloaded_at = db.Column(db.DateTime, nullable=True)
    last_downloaded_platform = db.Column(db.String(20), nullable=True)

    # Additional pass data (JSON field for subgroup, etc.)
    pass_data = db.Column(db.JSON, nullable=True)

    version = db.Column(db.Integer, default=1)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    pass_type = db.relationship('WalletPassType', back_populates='passes')
    user = db.relationship('User', foreign_keys=[user_id], backref='owned_wallet_passes')
    voided_by = db.relationship('User', foreign_keys=[voided_by_user_id])
    player = db.relationship('Player', backref='owned_wallet_passes')
    season = db.relationship('Season', backref='issued_wallet_passes')
    device_registrations = db.relationship('WalletPassDevice', back_populates='wallet_pass',
                                           cascade='all, delete-orphan')
    checkins = db.relationship('WalletPassCheckin', back_populates='wallet_pass',
                               cascade='all, delete-orphan',
                               order_by='WalletPassCheckin.checked_in_at.desc()')

    def __repr__(self):
        return f'<WalletPass {self.serial_number[:8]}... - {self.member_name}>'

    @staticmethod
    def generate_serial_number():
        import uuid
        return str(uuid.uuid4())

    @staticmethod
    def generate_token():
        return secrets.token_urlsafe(48)

    @staticmethod
    def generate_download_token():
        return secrets.token_urlsafe(32)

    def generate_barcode_data(self):
        """Generate barcode data: ECSFC-{TYPE}-{SHORT_SERIAL}"""
        type_code = self.pass_type.code.upper()[:3] if self.pass_type else 'UNK'
        short_serial = self.serial_number.replace('-', '')[:12].upper()
        return f"ECSFC-{type_code}-{short_serial}"

    @property
    def is_valid(self):
        """Check if pass is valid (active and not expired).

        Note: Passes are considered valid even before their valid_from date
        (e.g., buying a 2026 membership in December 2025). They remain valid
        until they expire (valid_until + grace period).
        """
        now = datetime.utcnow()
        return (
            self.status == PassStatus.ACTIVE.value and
            now <= self.valid_until
        )

    @property
    def is_expired(self):
        return datetime.utcnow() > self.valid_until

    @property
    def days_until_expiry(self):
        delta = self.valid_until - datetime.utcnow()
        return delta.days

    @property
    def display_validity(self):
        if self.membership_year:
            return f"{self.membership_year}"
        elif self.season:
            return self.season.name
        return f"{self.valid_from.strftime('%b %Y')} - {self.valid_until.strftime('%b %Y')}"

    def void(self, reason=None, voided_by_user_id=None):
        self.status = PassStatus.VOIDED.value
        self.voided_at = datetime.utcnow()
        self.voided_reason = reason
        self.voided_by_user_id = voided_by_user_id
        self.version += 1

    def record_download(self, platform='apple'):
        self.download_count += 1
        self.last_downloaded_at = datetime.utcnow()
        self.last_downloaded_platform = platform
        if platform == 'apple':
            self.apple_pass_generated = True
            self.apple_pass_generated_at = datetime.utcnow()
        elif platform == 'google':
            self.google_pass_generated = True
            self.google_pass_generated_at = datetime.utcnow()

    def to_dict(self, include_checkins=False):
        data = {
            'id': self.id,
            'serial_number': self.serial_number,
            'pass_type': self.pass_type.to_dict() if self.pass_type else None,
            'member_name': self.member_name,
            'member_email': self.member_email,
            'team_name': self.team_name,
            'woo_order_id': self.woo_order_id,
            'membership_year': self.membership_year,
            'valid_from': self.valid_from.isoformat() if self.valid_from else None,
            'valid_until': self.valid_until.isoformat() if self.valid_until else None,
            'display_validity': self.display_validity,
            'status': self.status,
            'is_valid': self.is_valid,
            'days_until_expiry': self.days_until_expiry,
            'download_count': self.download_count,
            'last_downloaded_at': self.last_downloaded_at.isoformat() if self.last_downloaded_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
        if include_checkins:
            data['checkins'] = [c.to_dict() for c in self.checkins[:10]]
            data['total_checkins'] = len(self.checkins)
        return data

    @classmethod
    def find_by_download_token(cls, token):
        return cls.query.filter_by(download_token=token).first()

    @classmethod
    def find_by_barcode(cls, barcode_data):
        return cls.query.filter_by(barcode_data=barcode_data).first()

    @classmethod
    def find_active_for_user(cls, user_id, pass_type_code=None):
        query = cls.query.filter_by(user_id=user_id, status=PassStatus.ACTIVE.value)
        if pass_type_code:
            query = query.join(WalletPassType).filter(WalletPassType.code == pass_type_code)
        return query.all()

    @classmethod
    def find_by_woo_order(cls, order_id):
        return cls.query.filter_by(woo_order_id=order_id).all()


class WalletPassDevice(db.Model):
    """Tracks devices registered for pass updates (Apple/Google push)"""
    __tablename__ = 'wallet_pass_device'

    id = db.Column(db.Integer, primary_key=True)
    wallet_pass_id = db.Column(db.Integer, db.ForeignKey('wallet_pass.id', ondelete='CASCADE'),
                               nullable=False, index=True)
    device_library_id = db.Column(db.String(100), nullable=False, index=True)
    push_token = db.Column(db.String(200), nullable=False)
    platform = db.Column(db.String(20), default='apple')

    registered_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    wallet_pass = db.relationship('WalletPass', back_populates='device_registrations')

    __table_args__ = (
        db.UniqueConstraint('wallet_pass_id', 'device_library_id', name='uq_pass_device'),
    )

    def __repr__(self):
        return f'<WalletPassDevice {self.device_library_id[:8]}...>'

    @classmethod
    def find_or_create(cls, wallet_pass_id, device_library_id, push_token, platform='apple'):
        existing = cls.query.filter_by(
            wallet_pass_id=wallet_pass_id,
            device_library_id=device_library_id
        ).first()
        if existing:
            existing.push_token = push_token
            existing.last_updated_at = datetime.utcnow()
            return existing
        return cls(
            wallet_pass_id=wallet_pass_id,
            device_library_id=device_library_id,
            push_token=push_token,
            platform=platform
        )


class WalletPassCheckin(db.Model):
    """Tracks pass validations and check-ins"""
    __tablename__ = 'wallet_pass_checkin'

    id = db.Column(db.Integer, primary_key=True)
    wallet_pass_id = db.Column(db.Integer, db.ForeignKey('wallet_pass.id', ondelete='CASCADE'),
                               nullable=False, index=True)

    checked_in_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    check_in_type = db.Column(db.String(20), default='qr_scan')
    location = db.Column(db.String(100), nullable=True)
    event_name = db.Column(db.String(200), nullable=True)
    checked_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    was_valid = db.Column(db.Boolean, default=True)
    validation_message = db.Column(db.String(200), nullable=True)
    notes = db.Column(db.Text, nullable=True)

    wallet_pass = db.relationship('WalletPass', back_populates='checkins')
    checked_by = db.relationship('User')

    def __repr__(self):
        return f'<WalletPassCheckin {self.id} at {self.checked_in_at}>'

    def to_dict(self):
        return {
            'id': self.id,
            'checked_in_at': self.checked_in_at.isoformat() if self.checked_in_at else None,
            'check_in_type': self.check_in_type,
            'location': self.location,
            'event_name': self.event_name,
            'was_valid': self.was_valid,
            'validation_message': self.validation_message,
            'checked_by': self.checked_by.username if self.checked_by else None
        }

    @classmethod
    def record_checkin(cls, wallet_pass, check_in_type='qr_scan', location=None,
                       event_name=None, checked_by_user_id=None, was_valid=True,
                       validation_message=None, notes=None):
        checkin = cls(
            wallet_pass_id=wallet_pass.id,
            check_in_type=check_in_type,
            location=location,
            event_name=event_name,
            checked_by_user_id=checked_by_user_id,
            was_valid=was_valid,
            validation_message=validation_message,
            notes=notes
        )
        db.session.add(checkin)
        return checkin


def create_ecs_membership_pass(member_name, member_email, year, woo_order_id=None, user_id=None, subgroup=None):
    """Create a new ECS membership pass

    Args:
        member_name: Member's display name
        member_email: Member's email address
        year: Membership year (e.g., 2025)
        woo_order_id: WooCommerce order ID (optional)
        user_id: Portal user ID (optional)
        subgroup: Supporter subgroup name (optional, e.g., 'Gorilla FC', 'North End Faithful')

    Returns:
        WalletPass instance
    """
    pass_type = WalletPassType.get_ecs_membership()
    if not pass_type:
        raise ValueError("ECS Membership pass type not configured")

    valid_from = datetime(year, 1, 1)
    valid_until = datetime(year, 12, 31, 23, 59, 59)
    valid_until = valid_until + timedelta(days=pass_type.grace_period_days)

    # Build pass_data with optional fields
    pass_data = {}
    if subgroup:
        pass_data['subgroup'] = subgroup

    wallet_pass = WalletPass(
        serial_number=WalletPass.generate_serial_number(),
        pass_type_id=pass_type.id,
        user_id=user_id,
        member_name=member_name,
        member_email=member_email,
        woo_order_id=woo_order_id,
        download_token=WalletPass.generate_download_token(),
        membership_year=year,
        valid_from=valid_from,
        valid_until=valid_until,
        status=PassStatus.ACTIVE.value,
        authentication_token=WalletPass.generate_token(),
        barcode_data='',
        pass_data=pass_data if pass_data else None
    )
    wallet_pass.barcode_data = wallet_pass.generate_barcode_data()
    return wallet_pass


def create_pub_league_pass(player, season, woo_order_id=None):
    """Create a new Pub League pass for a player"""
    pass_type = WalletPassType.get_pub_league()
    if not pass_type:
        raise ValueError("Pub League pass type not configured")

    valid_from = season.start_date if season.start_date else datetime.utcnow()
    valid_until = season.end_date if season.end_date else (datetime.utcnow() + timedelta(days=120))
    valid_until = valid_until + timedelta(days=pass_type.grace_period_days)

    team_name = None
    if player.primary_team:
        team_name = player.primary_team.name
    elif player.teams and len(player.teams) > 0:
        team_name = player.teams[0].name

    wallet_pass = WalletPass(
        serial_number=WalletPass.generate_serial_number(),
        pass_type_id=pass_type.id,
        user_id=player.user_id,
        player_id=player.id,
        member_name=player.name,
        member_email=player.user.email if player.user else None,
        team_name=team_name,
        woo_order_id=woo_order_id,
        download_token=WalletPass.generate_download_token(),
        season_id=season.id,
        valid_from=valid_from,
        valid_until=valid_until,
        status=PassStatus.ACTIVE.value,
        authentication_token=WalletPass.generate_token(),
        barcode_data=''
    )
    wallet_pass.barcode_data = wallet_pass.generate_barcode_data()
    return wallet_pass


def create_pub_league_pass_manual(
    member_name,
    member_email,
    team_name,
    season_name,
    woo_order_id=None,
    user_id=None,
    player_id=None
):
    """
    Create a new Pub League pass with manual field input.

    This is used for admin-created passes where we don't have
    Player and Season model objects.
    """
    pass_type = WalletPassType.get_pub_league()
    if not pass_type:
        raise ValueError("Pub League pass type not configured")

    # Default validity period (6 months / 182 days from now)
    valid_from = datetime.utcnow()
    valid_until = valid_from + timedelta(days=pass_type.validity_days)
    valid_until = valid_until + timedelta(days=pass_type.grace_period_days)

    wallet_pass = WalletPass(
        serial_number=WalletPass.generate_serial_number(),
        pass_type_id=pass_type.id,
        user_id=user_id,
        player_id=player_id,
        member_name=member_name,
        member_email=member_email,
        team_name=team_name,
        woo_order_id=woo_order_id,
        download_token=WalletPass.generate_download_token(),
        valid_from=valid_from,
        valid_until=valid_until,
        status=PassStatus.ACTIVE.value,
        authentication_token=WalletPass.generate_token(),
        barcode_data='',
        pass_data={'season_name': season_name} if season_name else None
    )
    wallet_pass.barcode_data = wallet_pass.generate_barcode_data()
    return wallet_pass
