# app/models/wallet_config.py

"""
Wallet Pass Configuration Models

This module contains models for configuring wallet pass content:
- WalletLocation: Partner venues that trigger location-based notifications
- WalletSponsor: Sponsors whose info can be displayed on passes
- WalletPassField: Configurable fields for pass types
- WalletSubgroup: ECS supporter subgroups (Gorilla FC, North End Faithful, etc.)
"""

import logging
from datetime import datetime

from app.core import db

logger = logging.getLogger(__name__)


class WalletLocation(db.Model):
    """Partner venues for location-based pass notifications

    When a user with a pass approaches one of these locations,
    their phone can show a notification reminding them they have the pass.
    Apple allows up to 10 locations per pass.
    """
    __tablename__ = 'wallet_location'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)

    # Geographic coordinates
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)

    # The text shown in the notification when user is near this location
    relevant_text = db.Column(db.String(200), nullable=False)

    # Optional address for admin reference
    address = db.Column(db.String(255), nullable=True)
    city = db.Column(db.String(100), nullable=True)
    state = db.Column(db.String(50), nullable=True)

    # Which pass types this location applies to (null = all)
    # Can be 'ecs_membership', 'pub_league', or 'all'
    applies_to = db.Column(db.String(50), default='all')

    # Status and ordering
    is_active = db.Column(db.Boolean, default=True)
    display_order = db.Column(db.Integer, default=0)

    # Type of location (for filtering/display)
    location_type = db.Column(db.String(50), default='partner_bar')  # partner_bar, stadium, other

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<WalletLocation {self.name}>'

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'latitude': self.latitude,
            'longitude': self.longitude,
            'relevant_text': self.relevant_text,
            'address': self.address,
            'city': self.city,
            'applies_to': self.applies_to,
            'location_type': self.location_type,
            'is_active': self.is_active
        }

    def to_pass_dict(self):
        """Format for Apple/Google Wallet pass JSON"""
        return {
            'latitude': self.latitude,
            'longitude': self.longitude,
            'relevantText': self.relevant_text
        }

    @classmethod
    def get_for_pass_type(cls, pass_type_code, limit=10):
        """Get active locations for a specific pass type (max 10 for Apple Wallet)"""
        return cls.query.filter(
            cls.is_active == True,
            db.or_(cls.applies_to == 'all', cls.applies_to == pass_type_code)
        ).order_by(cls.display_order).limit(limit).all()


class WalletSponsor(db.Model):
    """Sponsors whose information can appear on wallet passes

    Sponsors can have their info displayed on the back of passes
    or mentioned in auxiliary fields.
    """
    __tablename__ = 'wallet_sponsor'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)

    # Display text for the pass
    display_name = db.Column(db.String(100), nullable=False)  # What shows on pass
    description = db.Column(db.Text, nullable=True)  # For back of pass

    # URLs
    website_url = db.Column(db.String(255), nullable=True)

    # Logo/branding (optional - for future use)
    logo_url = db.Column(db.String(255), nullable=True)

    # Which pass types this sponsor applies to
    applies_to = db.Column(db.String(50), default='all')  # ecs_membership, pub_league, all

    # Where to display on pass
    display_location = db.Column(db.String(50), default='back')  # back, auxiliary

    # Sponsorship type for grouping
    sponsor_type = db.Column(db.String(50), default='partner')  # partner, presenting, venue

    # Status and ordering
    is_active = db.Column(db.Boolean, default=True)
    display_order = db.Column(db.Integer, default=0)

    # Validity period (some sponsors may be seasonal)
    valid_from = db.Column(db.DateTime, nullable=True)
    valid_until = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<WalletSponsor {self.name}>'

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'display_name': self.display_name,
            'description': self.description,
            'website_url': self.website_url,
            'applies_to': self.applies_to,
            'display_location': self.display_location,
            'sponsor_type': self.sponsor_type,
            'is_active': self.is_active
        }

    @property
    def is_currently_valid(self):
        """Check if sponsor is within validity period"""
        now = datetime.utcnow()
        if self.valid_from and now < self.valid_from:
            return False
        if self.valid_until and now > self.valid_until:
            return False
        return True

    @classmethod
    def get_active_for_pass_type(cls, pass_type_code):
        """Get currently valid sponsors for a pass type"""
        now = datetime.utcnow()
        return cls.query.filter(
            cls.is_active == True,
            db.or_(cls.applies_to == 'all', cls.applies_to == pass_type_code),
            db.or_(cls.valid_from == None, cls.valid_from <= now),
            db.or_(cls.valid_until == None, cls.valid_until >= now)
        ).order_by(cls.display_order).all()


class WalletSubgroup(db.Model):
    """ECS Supporter subgroups

    These are optional affiliations that can be shown on ECS passes.
    Examples: Gorilla FC, North End Faithful, Eastside Supporters, etc.
    """
    __tablename__ = 'wallet_subgroup'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)  # e.g., 'gorilla_fc'
    name = db.Column(db.String(100), nullable=False)  # e.g., 'Gorilla FC'

    # Optional logo/image path (stored in wallet assets)
    logo_asset_id = db.Column(db.Integer, db.ForeignKey('wallet_asset.id'), nullable=True)

    # Description for admin reference
    description = db.Column(db.Text, nullable=True)

    # Status
    is_active = db.Column(db.Boolean, default=True)
    display_order = db.Column(db.Integer, default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship to logo asset
    logo_asset = db.relationship('WalletAsset', foreign_keys=[logo_asset_id])

    def __repr__(self):
        return f'<WalletSubgroup {self.name}>'

    def to_dict(self):
        return {
            'id': self.id,
            'code': self.code,
            'name': self.name,
            'is_active': self.is_active,
            'has_logo': self.logo_asset_id is not None
        }

    @classmethod
    def get_active(cls):
        """Get all active subgroups"""
        return cls.query.filter_by(is_active=True).order_by(cls.display_order).all()


class WalletPassFieldConfig(db.Model):
    """Configurable fields for each pass type

    Allows admins to customize what fields appear on passes
    without editing JSON templates directly.
    """
    __tablename__ = 'wallet_pass_field_config'

    id = db.Column(db.Integer, primary_key=True)

    # Which pass type this config belongs to
    pass_type_id = db.Column(db.Integer, db.ForeignKey('wallet_pass_type.id'), nullable=False)

    # Field identification
    field_key = db.Column(db.String(50), nullable=False)  # e.g., 'member', 'validity', 'team'

    # Field placement
    field_location = db.Column(db.String(50), nullable=False)  # primary, secondary, auxiliary, header, back

    # Display settings
    label = db.Column(db.String(50), nullable=False)  # e.g., 'MEMBER', 'VALID FOR'
    default_value = db.Column(db.String(200), nullable=True)  # Static value or template variable
    value_template = db.Column(db.String(200), nullable=True)  # e.g., '{{member_name}}', '{{team_name}}'

    # Behavior
    is_required = db.Column(db.Boolean, default=True)
    is_visible = db.Column(db.Boolean, default=True)
    display_order = db.Column(db.Integer, default=0)

    # Field type hints for the UI
    field_type = db.Column(db.String(50), default='text')  # text, date, url, phone

    # Apple Wallet formatting options
    text_alignment = db.Column(db.String(20), default='natural')  # natural, left, center, right
    date_style = db.Column(db.String(20), nullable=True)  # none, short, medium, long, full
    time_style = db.Column(db.String(20), nullable=True)  # none, short, medium, long, full
    number_style = db.Column(db.String(20), nullable=True)  # decimal, percent, scientific, spellOut
    currency_code = db.Column(db.String(3), nullable=True)  # ISO 4217: USD, EUR, GBP, etc. (mutually exclusive with numberStyle)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship
    pass_type = db.relationship('WalletPassType', backref='field_configs')

    __table_args__ = (
        db.UniqueConstraint('pass_type_id', 'field_key', name='uq_pass_field_key'),
    )

    def __repr__(self):
        return f'<WalletPassFieldConfig {self.field_key} for pass_type {self.pass_type_id}>'

    def to_dict(self):
        return {
            'id': self.id,
            'pass_type_id': self.pass_type_id,
            'field_key': self.field_key,
            'field_location': self.field_location,
            'label': self.label,
            'default_value': self.default_value,
            'value_template': self.value_template,
            'is_required': self.is_required,
            'is_visible': self.is_visible,
            'display_order': self.display_order,
            'field_type': self.field_type,
            'text_alignment': self.text_alignment or 'natural',
            'date_style': self.date_style,
            'time_style': self.time_style,
            'number_style': self.number_style,
            'currency_code': self.currency_code
        }

    def to_pass_field_dict(self, data=None):
        """Generate the field dictionary for pass JSON

        Args:
            data: dict with values for template variables
        """
        value = self.default_value or ''

        # Replace template variables if data provided
        if self.value_template and data:
            value = self.value_template
            for key, val in data.items():
                value = value.replace('{{' + key + '}}', str(val) if val else '')

        return {
            'key': self.field_key,
            'label': self.label,
            'value': value
        }


class WalletBackField(db.Model):
    """Configurable back-of-pass content

    The back of the pass can contain multiple fields with
    longer content like terms, contact info, links, etc.
    """
    __tablename__ = 'wallet_back_field'

    id = db.Column(db.Integer, primary_key=True)
    pass_type_id = db.Column(db.Integer, db.ForeignKey('wallet_pass_type.id'), nullable=False)

    field_key = db.Column(db.String(50), nullable=False)
    label = db.Column(db.String(100), nullable=False)
    value = db.Column(db.Text, nullable=False)  # Can be longer content

    # Field type for rendering
    field_type = db.Column(db.String(50), default='text')  # text, url, phone, email

    is_visible = db.Column(db.Boolean, default=True)
    display_order = db.Column(db.Integer, default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    pass_type = db.relationship('WalletPassType', backref='back_fields')

    def __repr__(self):
        return f'<WalletBackField {self.field_key}>'

    def to_dict(self):
        return {
            'id': self.id,
            'field_key': self.field_key,
            'label': self.label,
            'value': self.value,
            'field_type': self.field_type,
            'is_visible': self.is_visible,
            'display_order': self.display_order
        }

    def to_pass_field_dict(self):
        return {
            'key': self.field_key,
            'label': self.label,
            'value': self.value
        }


# Default field configurations for each pass type
DEFAULT_ECS_FIELDS = [
    {'field_key': 'member', 'field_location': 'primary', 'label': 'MEMBER',
     'value_template': '{{member_name}}', 'is_required': True, 'display_order': 1},
    {'field_key': 'validity', 'field_location': 'secondary', 'label': 'VALID FOR',
     'value_template': '{{validity}}', 'is_required': True, 'display_order': 2},
    {'field_key': 'since', 'field_location': 'auxiliary', 'label': 'SUPPORTING SINCE',
     'value_template': '{{member_since}}', 'is_required': False, 'display_order': 3},
]

DEFAULT_ECS_BACK_FIELDS = [
    {'field_key': 'terms', 'label': 'TERMS & CONDITIONS',
     'value': 'This pass identifies the holder as a member of the Emerald City Supporters. Membership is non-transferable.'},
    {'field_key': 'website', 'label': 'WEBSITE', 'value': 'https://www.weareecs.com', 'field_type': 'url'},
    {'field_key': 'discord', 'label': 'DISCORD', 'value': 'https://discord.gg/weareecs', 'field_type': 'url'},
]

DEFAULT_PUB_LEAGUE_FIELDS = [
    {'field_key': 'player', 'field_location': 'primary', 'label': 'PLAYER',
     'value_template': '{{member_name}}', 'is_required': True, 'display_order': 1},
    {'field_key': 'team', 'field_location': 'secondary', 'label': 'TEAM',
     'value_template': '{{team_name}}', 'is_required': True, 'display_order': 2},
    {'field_key': 'season', 'field_location': 'auxiliary', 'label': 'SEASON',
     'value_template': '{{validity}}', 'is_required': True, 'display_order': 3},
]

DEFAULT_PUB_LEAGUE_BACK_FIELDS = [
    {'field_key': 'terms', 'label': 'RULES & CONDUCT',
     'value': 'All players must adhere to the ECS Pub League code of conduct. Passes are non-transferable.'},
    {'field_key': 'website', 'label': 'WEBSITE', 'value': 'https://www.weareecs.com/pub-league', 'field_type': 'url'},
]

# Default locations
DEFAULT_LOCATIONS = [
    {'name': 'Hellbent Brewing', 'latitude': 47.7240, 'longitude': -122.2958,
     'relevant_text': 'Hellbent Brewing', 'city': 'Seattle', 'state': 'WA', 'location_type': 'partner_bar'},
    {'name': "Shawn O'Donnell's - Fremont", 'latitude': 47.6513, 'longitude': -122.3500,
     'relevant_text': "Shawn O'Donnell's - Fremont", 'city': 'Seattle', 'state': 'WA', 'location_type': 'partner_bar'},
    {'name': 'Rough & Tumble Pub', 'latitude': 47.6669, 'longitude': -122.3875,
     'relevant_text': 'Rough & Tumble Pub', 'city': 'Seattle', 'state': 'WA', 'location_type': 'partner_bar'},
    {'name': 'Temple Billiards', 'latitude': 47.5993, 'longitude': -122.3358,
     'relevant_text': 'Temple Billiards', 'city': 'Seattle', 'state': 'WA', 'location_type': 'partner_bar'},
    {'name': 'Atlantic Crossing', 'latitude': 47.6784, 'longitude': -122.3234,
     'relevant_text': 'Atlantic Crossing', 'city': 'Seattle', 'state': 'WA', 'location_type': 'partner_bar'},
    {'name': 'The Press Box', 'latitude': 47.5896, 'longitude': -122.3363,
     'relevant_text': 'The Press Box', 'city': 'Seattle', 'state': 'WA', 'location_type': 'partner_bar'},
    {'name': 'Golden Rooster', 'latitude': 47.6012, 'longitude': -122.3357,
     'relevant_text': 'Golden Rooster', 'city': 'Seattle', 'state': 'WA', 'location_type': 'partner_bar'},
    {'name': 'Mission Cantina', 'latitude': 47.5822, 'longitude': -122.3894,
     'relevant_text': 'Mission Cantina', 'city': 'Seattle', 'state': 'WA', 'location_type': 'partner_bar'},
    {'name': "Purdy's Public House - Sumner", 'latitude': 47.1982, 'longitude': -122.2157,
     'relevant_text': "Purdy's Public House - Sumner", 'city': 'Sumner', 'state': 'WA', 'location_type': 'partner_bar'},
    {'name': 'Bar Palmina - Philadelphia', 'latitude': 39.9707, 'longitude': -75.1386,
     'relevant_text': 'Bar Palmina - Philadelphia', 'city': 'Philadelphia', 'state': 'PA', 'location_type': 'partner_bar'},
]

# Default subgroups
DEFAULT_SUBGROUPS = [
    {'code': 'gorilla_fc', 'name': 'Gorilla FC'},
    {'code': 'north_end_faithful', 'name': 'North End Faithful'},
    {'code': 'eastside_supporters', 'name': 'Eastside Supporters'},
    {'code': 'south_sound_supporters', 'name': 'South Sound Supporters'},
]


def initialize_wallet_config_defaults():
    """Initialize default configuration data

    Call this during app setup or migration to populate defaults.
    """
    from app.models.wallet import WalletPassType

    # Create default locations
    existing_locations = WalletLocation.query.count()
    if existing_locations == 0:
        for loc_data in DEFAULT_LOCATIONS:
            location = WalletLocation(**loc_data)
            db.session.add(location)
        logger.info(f"Created {len(DEFAULT_LOCATIONS)} default locations")

    # Create default subgroups
    existing_subgroups = WalletSubgroup.query.count()
    if existing_subgroups == 0:
        for sg_data in DEFAULT_SUBGROUPS:
            subgroup = WalletSubgroup(**sg_data)
            db.session.add(subgroup)
        logger.info(f"Created {len(DEFAULT_SUBGROUPS)} default subgroups")

    # Create default field configs for ECS
    ecs_type = WalletPassType.get_ecs_membership()
    if ecs_type:
        existing = WalletPassFieldConfig.query.filter_by(pass_type_id=ecs_type.id).count()
        if existing == 0:
            for field_data in DEFAULT_ECS_FIELDS:
                field = WalletPassFieldConfig(pass_type_id=ecs_type.id, **field_data)
                db.session.add(field)
            for back_data in DEFAULT_ECS_BACK_FIELDS:
                back_field = WalletBackField(pass_type_id=ecs_type.id, display_order=len(DEFAULT_ECS_BACK_FIELDS), **back_data)
                db.session.add(back_field)
            logger.info("Created default ECS field configs")

    # Create default field configs for Pub League
    pl_type = WalletPassType.get_pub_league()
    if pl_type:
        existing = WalletPassFieldConfig.query.filter_by(pass_type_id=pl_type.id).count()
        if existing == 0:
            for field_data in DEFAULT_PUB_LEAGUE_FIELDS:
                field = WalletPassFieldConfig(pass_type_id=pl_type.id, **field_data)
                db.session.add(field)
            for back_data in DEFAULT_PUB_LEAGUE_BACK_FIELDS:
                back_field = WalletBackField(pass_type_id=pl_type.id, display_order=len(DEFAULT_PUB_LEAGUE_BACK_FIELDS), **back_data)
                db.session.add(back_field)
            logger.info("Created default Pub League field configs")

    db.session.commit()
