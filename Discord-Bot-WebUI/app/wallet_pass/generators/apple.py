# app/wallet_pass/generators/apple.py

"""
Apple Wallet Pass Generator

Generates .pkpass files for Apple Wallet using the wallet library.
Supports both ECS Membership and Pub League passes.

IMPORTANT: This generator reads field configurations from the database
(WalletPassFieldConfig, WalletBackField) to match what admins configure
in the Pass Studio UI.
"""

import os
import json
import logging
import requests
from io import BytesIO
from datetime import datetime
from typing import Dict, Any, Optional, List
from PIL import Image

from wallet.models import (
    Pass, Barcode, StoreCard, Generic, EventTicket, Field, Alignment,
    DateField, NumberField, CurrencyField, DateStyle, NumberStyle
)

from .base import BasePassGenerator

logger = logging.getLogger(__name__)


class ApplePassConfig:
    """Configuration for Apple Wallet pass generation"""

    def __init__(self):
        self.team_identifier = os.getenv('WALLET_TEAM_ID')
        if not self.team_identifier:
            raise ValueError("WALLET_TEAM_ID environment variable is required")

        self.certificate_path = os.getenv(
            'WALLET_CERT_PATH',
            'app/wallet_pass/certs/certificate.pem'
        )
        self.key_path = os.getenv(
            'WALLET_KEY_PATH',
            'app/wallet_pass/certs/key.pem'
        )
        self.wwdr_path = os.getenv(
            'WALLET_WWDR_PATH',
            'app/wallet_pass/certs/wwdr.pem'
        )
        self.key_password = os.getenv('WALLET_KEY_PASSWORD', '')
        self.web_service_url = os.getenv('WALLET_WEB_SERVICE_URL', '')

    def validate(self):
        """Validate that all required certificates exist"""
        missing = []
        for name, path in [
            ('Certificate', self.certificate_path),
            ('Private Key', self.key_path),
            ('WWDR Certificate', self.wwdr_path)
        ]:
            if not os.path.exists(path):
                missing.append(f"{name} not found at {path}")

        if len(self.team_identifier) != 10:
            missing.append(f"Team identifier must be 10 characters, got {len(self.team_identifier)}")

        if missing:
            raise ValueError(f"Apple Wallet configuration errors: {'; '.join(missing)}")

        return True


class ApplePassGenerator(BasePassGenerator):
    """
    Generates Apple Wallet .pkpass files.

    Supports ECS Membership and Pub League passes with different
    styling and templates for each type.
    """

    def __init__(self, pass_type, config: ApplePassConfig = None):
        """
        Initialize Apple pass generator.

        Args:
            pass_type: WalletPassType model instance
            config: ApplePassConfig instance (optional)
        """
        super().__init__(pass_type)
        self.config = config or ApplePassConfig()

    def get_platform_name(self) -> str:
        return 'apple'

    def generate(self, wallet_pass) -> BytesIO:
        """
        Generate an Apple Wallet .pkpass file.

        Args:
            wallet_pass: WalletPass model instance

        Returns:
            BytesIO containing the .pkpass file
        """
        try:
            # Validate wallet pass data
            self.validate_wallet_pass(wallet_pass)

            # Validate Apple config
            self.config.validate()

            # Get template data
            template_data = self.get_template_data(wallet_pass)

            # Create the pass object
            pass_obj = self._create_pass_object(wallet_pass, template_data)

            # Add assets
            self._add_assets(pass_obj, wallet_pass)

            # Sign and create the pass
            pass_file = self._sign_pass(pass_obj)

            logger.info(
                f"Generated Apple Wallet pass for {wallet_pass.member_name} "
                f"(type: {self.pass_type.code})"
            )
            return pass_file

        except Exception as e:
            logger.error(f"Error generating Apple Wallet pass: {e}")
            raise

    def _create_pass_object(self, wallet_pass, template_data: Dict) -> Pass:
        """
        Create the Apple Wallet Pass object.

        Reads field configurations from the database to match what admins
        have configured in the Pass Studio UI.

        Args:
            wallet_pass: WalletPass model instance
            template_data: Template data dictionary

        Returns:
            wallet.models.Pass object
        """
        # Import models here to avoid circular imports
        from app.models.wallet_config import (
            WalletPassFieldConfig, WalletBackField, WalletLocation
        )

        # Get pass style from database (defaults to 'generic' for clean separated fields)
        pass_style = self.pass_type.apple_pass_style or 'generic'
        logger.info(f"Creating Apple Wallet pass with style: {pass_style}")

        # Create the appropriate card type based on pass style
        # - generic: Thumbnail with clean separated fields (best for memberships)
        # - storeCard: Strip image with primary field overlaid
        # - eventTicket: Strip image with primary overlaid + notch at top
        if pass_style == 'generic':
            card_info = Generic()
        elif pass_style == 'eventTicket':
            card_info = EventTicket()
        else:  # Default to storeCard for backwards compatibility
            card_info = StoreCard()

        # Get field configurations from database
        field_configs = WalletPassFieldConfig.query.filter(
            WalletPassFieldConfig.pass_type_id == self.pass_type.id,
            WalletPassFieldConfig.is_visible == True
        ).order_by(WalletPassFieldConfig.display_order).all()

        logger.info(f"Found {len(field_configs)} visible field configs for pass type {self.pass_type.id}")
        for fc in field_configs:
            logger.debug(f"  Field: {fc.field_key} | Location: {fc.field_location} | Label: {fc.label} | Template: {fc.value_template}")

        # Group fields by location
        fields_by_location = {
            'header': [],
            'primary': [],
            'secondary': [],
            'auxiliary': []
        }

        for field in field_configs:
            if field.field_location in fields_by_location:
                fields_by_location[field.field_location].append(field)

        # Add header fields
        for field in fields_by_location['header']:
            pass_field = self._create_pass_field(field, template_data)
            card_info.headerFields.append(pass_field)

        # Add primary fields
        # NOTE: For eventTicket, we skip primary fields to keep the strip image clean
        # Primary fields on eventTicket would overlay on the strip, so we use secondary/auxiliary instead
        if pass_style != 'eventTicket':
            for field in fields_by_location['primary']:
                pass_field = self._create_pass_field(field, template_data)
                card_info.primaryFields.append(pass_field)
        else:
            # For eventTicket, move any primary fields to secondary to display below strip
            if fields_by_location['primary']:
                logger.info(f"EventTicket: Moving {len(fields_by_location['primary'])} primary field(s) to secondary")
            for field in fields_by_location['primary']:
                pass_field = self._create_pass_field(field, template_data)
                card_info.secondaryFields.append(pass_field)

        # Add secondary fields
        for field in fields_by_location['secondary']:
            pass_field = self._create_pass_field(field, template_data)
            card_info.secondaryFields.append(pass_field)

        # Add auxiliary fields
        for field in fields_by_location['auxiliary']:
            pass_field = self._create_pass_field(field, template_data)
            card_info.auxiliaryFields.append(pass_field)

        # If no fields configured in database, use defaults
        if not field_configs:
            logger.warning(f"No field configs found for pass type {self.pass_type.id}, using defaults")
            # For eventTicket, put member name in secondary (not primary) to avoid strip overlay
            if pass_style == 'eventTicket':
                card_info.addSecondaryField('name', template_data['member_name'], 'MEMBER')
            else:
                card_info.addPrimaryField('name', template_data['member_name'], 'MEMBER')
            if self.pass_type.code == 'ecs_membership':
                card_info.addSecondaryField('year', str(template_data['membership_year']), 'YEAR')
            else:
                card_info.addSecondaryField('team', template_data.get('team_name', 'TBD'), 'TEAM')

        # Get back fields from database
        back_fields = WalletBackField.query.filter(
            WalletBackField.pass_type_id == self.pass_type.id,
            WalletBackField.is_visible == True
        ).order_by(WalletBackField.display_order).all()

        for field in back_fields:
            # Back field values might also have templates
            value = field.value
            for key, val in template_data.items():
                value = value.replace('{{' + key + '}}', str(val) if val else '')
            card_info.addBackField(field.field_key, value, field.label)

        # If no back fields configured, add defaults
        if not back_fields:
            card_info.addBackField('organization', template_data['organization_name'], 'Organization')
            card_info.addBackField('issued', template_data['issue_date'], 'Issued')

        # Create the pass
        pass_type_id = self.pass_type.apple_pass_type_id or 'pass.com.weareecs.membership'

        pass_obj = Pass(
            card_info,
            passTypeIdentifier=pass_type_id,
            organizationName=template_data['organization_name'],
            teamIdentifier=self.config.team_identifier
        )

        # Set pass properties
        pass_obj.serialNumber = f"ecsfc-{self.pass_type.code}-{wallet_pass.serial_number}"
        pass_obj.description = template_data['description']

        # Add barcode (unless suppressed in pass type settings)
        if not template_data.get('suppress_barcode', False):
            pass_obj.barcode = Barcode(
                message=wallet_pass.barcode_data,
                format='PKBarcodeFormatQR'
            )
        else:
            logger.debug(f"Barcode suppressed for pass type {self.pass_type.code}")

        # Set colors from pass type (read from database via template_data)
        logger.info(f"Setting pass colors - BG: {template_data['background_color']}, FG: {template_data['foreground_color']}, Label: {template_data['label_color']}")
        pass_obj.backgroundColor = template_data['background_color']
        pass_obj.foregroundColor = template_data['foreground_color']
        pass_obj.labelColor = template_data['label_color']

        # Set logo text
        logger.info(f"Setting logo text: {template_data['logo_text']}")
        pass_obj.logoText = template_data['logo_text']

        # Add locations for location-based notifications
        locations = WalletLocation.get_for_pass_type(self.pass_type.code, limit=10)
        if locations:
            pass_obj.locations = [loc.to_pass_dict() for loc in locations]
            logger.debug(f"Added {len(locations)} locations to pass")

        # Web service configuration for push updates
        if self.config.web_service_url:
            pass_obj.webServiceURL = self.config.web_service_url
            pass_obj.authenticationToken = wallet_pass.authentication_token
            logger.info(f"Set webServiceURL: {self.config.web_service_url}, authToken: {wallet_pass.authentication_token[:8]}...")
        else:
            logger.warning("No web_service_url configured - push updates will not work")

        return pass_obj

    def _resolve_field_value(self, field, template_data: Dict) -> str:
        """
        Resolve the value for a field configuration.

        Uses value_template if set, falls back to default_value,
        and replaces {{variable}} placeholders with template data.

        Args:
            field: WalletPassFieldConfig instance
            template_data: Dictionary of template variables

        Returns:
            Resolved string value
        """
        # Start with value_template if set, otherwise default_value
        value = field.value_template or field.default_value or ''

        # Replace template variables
        for key, val in template_data.items():
            placeholder = '{{' + key + '}}'
            if placeholder in value:
                value = value.replace(placeholder, str(val) if val else '')

        return value

    def _create_pass_field(self, field, template_data: Dict) -> Field:
        """
        Create the appropriate Field object based on field type.

        Uses DateField for dates, NumberField for numbers, CurrencyField for currency,
        and standard Field for text. Applies alignment and formatting options.

        Args:
            field: WalletPassFieldConfig instance
            template_data: Dictionary of template variables

        Returns:
            Configured Field instance (or subclass)
        """
        value = self._resolve_field_value(field, template_data)
        alignment = self._get_alignment(field.text_alignment)
        field_type = field.field_type or 'text'

        logger.info(
            f"Creating {field_type} field: key={field.field_key}, label={field.label}, "
            f"value={value}, align={field.text_alignment}"
        )

        # Create appropriate field type based on field_type
        if field_type == 'date':
            pass_field = DateField(field.field_key, value, field.label)
            if field.date_style:
                pass_field.dateStyle = self._get_date_style(field.date_style)
            if field.time_style:
                pass_field.timeStyle = self._get_date_style(field.time_style)
        elif field_type == 'currency':
            # Currency fields use CurrencyField with currencyCode
            # Note: currencyCode and numberStyle are mutually exclusive in Apple Wallet
            pass_field = CurrencyField(
                field.field_key, value, field.label,
                currencyCode=field.currency_code or 'USD'
            )
        elif field_type == 'number':
            pass_field = NumberField(field.field_key, value, field.label)
            if field.number_style:
                pass_field.numberStyle = self._get_number_style(field.number_style)
        else:
            # Default text field
            pass_field = Field(field.field_key, value, field.label)

        # Apply text alignment to all field types
        pass_field.textAlignment = alignment

        return pass_field

    def _get_alignment(self, alignment_str: str) -> str:
        """
        Convert alignment string from database to Apple Wallet alignment constant.

        Args:
            alignment_str: Alignment value ('natural', 'left', 'center', 'right')

        Returns:
            Apple Wallet alignment constant (e.g., 'PKTextAlignmentLeft')
        """
        alignment_map = {
            'natural': Alignment.NATURAL,
            'left': Alignment.LEFT,
            'center': Alignment.CENTER,
            'right': Alignment.RIGHT,
        }
        return alignment_map.get(alignment_str or 'natural', Alignment.NATURAL)

    def _get_date_style(self, style_str: str) -> str:
        """
        Convert date/time style string from database to Apple Wallet constant.

        Args:
            style_str: Style value ('none', 'short', 'medium', 'long', 'full')

        Returns:
            Apple Wallet date style constant (e.g., 'PKDateStyleShort')
        """
        style_map = {
            'none': DateStyle.NONE,
            'short': DateStyle.SHORT,
            'medium': DateStyle.MEDIUM,
            'long': DateStyle.LONG,
            'full': DateStyle.FULL,
        }
        return style_map.get(style_str or 'short', DateStyle.SHORT)

    def _get_number_style(self, style_str: str) -> str:
        """
        Convert number style string from database to Apple Wallet constant.

        Args:
            style_str: Style value ('decimal', 'percent', 'scientific', 'spellOut')

        Returns:
            Apple Wallet number style constant (e.g., 'PKNumberStyleDecimal')
        """
        style_map = {
            'decimal': NumberStyle.DECIMAL,
            'percent': NumberStyle.PERCENT,
            'scientific': NumberStyle.SCIENTIFIC,
            'spellOut': NumberStyle.SPELLOUT,
        }
        return style_map.get(style_str or 'decimal', NumberStyle.DECIMAL)

    def _add_assets(self, pass_obj: Pass, wallet_pass) -> None:
        """
        Add image assets to the pass from database-tracked WalletAsset records.

        This reads assets that were uploaded through the Pass Studio UI,
        stored in the WalletAsset table with file paths to the actual files.

        Different pass styles support different assets:
        - generic: icon, logo, thumbnail (NO strip)
        - storeCard: icon, logo, strip (NO thumbnail)
        - eventTicket: icon, logo, strip, thumbnail, background (strip OR background, not both)

        Args:
            pass_obj: wallet.models.Pass object
            wallet_pass: WalletPass model instance
        """
        from app.models.wallet_asset import WalletAsset

        # Get all assets for this pass type from the database
        db_assets = WalletAsset.get_assets_by_pass_type(self.pass_type.id)
        assets_by_type = {asset.asset_type: asset for asset in db_assets}

        # Get pass style to determine which assets to include
        pass_style = self.pass_type.apple_pass_style or 'generic'
        logger.info(f"Found {len(db_assets)} assets in database for pass type {self.pass_type.id} (style: {pass_style}): {list(assets_by_type.keys())}")

        # Asset mappings per pass style
        # Reference: https://developer.apple.com/library/archive/documentation/UserExperience/Conceptual/PassKit_PG/Creating.html
        if pass_style == 'generic':
            # Generic pass: uses thumbnail (not strip)
            asset_mapping = {
                'icon': 'icon.png',
                'icon2x': 'icon@2x.png',
                'logo': 'logo.png',
                'logo2x': 'logo@2x.png',
                'thumbnail': 'thumbnail.png',
                'thumbnail2x': 'thumbnail@2x.png',
            }
        elif pass_style == 'eventTicket':
            # EventTicket: can use strip OR (thumbnail + background), but not both
            # We'll prefer strip if available, otherwise use thumbnail
            has_strip = 'strip' in assets_by_type or 'strip2x' in assets_by_type
            if has_strip:
                asset_mapping = {
                    'icon': 'icon.png',
                    'icon2x': 'icon@2x.png',
                    'logo': 'logo.png',
                    'logo2x': 'logo@2x.png',
                    'strip': 'strip.png',
                    'strip2x': 'strip@2x.png',
                }
            else:
                # Fall back to thumbnail + background for eventTicket
                asset_mapping = {
                    'icon': 'icon.png',
                    'icon2x': 'icon@2x.png',
                    'logo': 'logo.png',
                    'logo2x': 'logo@2x.png',
                    'thumbnail': 'thumbnail.png',
                    'thumbnail2x': 'thumbnail@2x.png',
                    'background': 'background.png',
                    'background2x': 'background@2x.png',
                }
        else:
            # storeCard: uses strip (not thumbnail)
            asset_mapping = {
                'icon': 'icon.png',
                'icon2x': 'icon@2x.png',
                'logo': 'logo.png',
                'logo2x': 'logo@2x.png',
                'strip': 'strip.png',
                'strip2x': 'strip@2x.png',
            }

        # Required assets - warn if missing
        # Note: Only icon is truly required. Logo is optional.
        required_types = ['icon']

        # Check if logo should be hidden
        show_logo = self.pass_type.show_logo if hasattr(self.pass_type, 'show_logo') and self.pass_type.show_logo is not None else True
        if not show_logo:
            # Remove logo from asset mapping if show_logo is False
            asset_mapping = {k: v for k, v in asset_mapping.items() if k not in ('logo', 'logo2x')}
            logger.info("Logo hidden per pass type settings (show_logo=False)")

        # Add all database-tracked assets to the pass
        for asset_type, apple_filename in asset_mapping.items():
            if asset_type in assets_by_type:
                asset = assets_by_type[asset_type]
                if asset.file_path and os.path.exists(asset.file_path):
                    with open(asset.file_path, 'rb') as f:
                        pass_obj.addFile(apple_filename, f)
                    logger.debug(f"Added asset from database: {asset_type} -> {apple_filename} (path: {asset.file_path})")
                else:
                    logger.warning(f"Asset file not found on disk: {asset.file_path}")
            elif asset_type in required_types:
                logger.warning(f"Required asset '{asset_type}' not configured in Pass Studio for pass type {self.pass_type.code}")

        # Try to add player profile image if available (for Pub League)
        # This overrides strip/thumbnail if a player has a profile image
        if wallet_pass.player:
            self._add_profile_image(pass_obj, wallet_pass.player, pass_style)

    def _add_profile_image(self, pass_obj: Pass, player, pass_style: str = 'generic') -> bool:
        """
        Add player profile image to the pass.

        For generic passes, adds as thumbnail (90x90).
        For storeCard/eventTicket, adds as strip (320x84).

        Args:
            pass_obj: wallet.models.Pass object
            player: Player model instance
            pass_style: Pass style ('generic', 'storeCard', 'eventTicket')

        Returns:
            True if image was added, False otherwise
        """
        if not player or not player.profile_picture_url:
            return False

        try:
            image_data = self._get_image_data(player.profile_picture_url)
            if not image_data:
                return False

            # Process for appropriate size based on pass style
            if pass_style == 'generic':
                # Generic uses thumbnail (90x90 for 1x, 180x180 for 2x)
                processed = self._process_image_for_wallet(image_data, target_size=(90, 90))
                if not processed:
                    return False
                pass_obj.addFile('thumbnail.png', processed)
                # Process again at 2x for retina
                image_data.seek(0)
                processed_2x = self._process_image_for_wallet(image_data, target_size=(180, 180))
                if processed_2x:
                    pass_obj.addFile('thumbnail@2x.png', processed_2x)
                logger.info(f"Added profile image as thumbnail for {player.name}")
            else:
                # storeCard/eventTicket use strip (320x84)
                processed = self._process_image_for_wallet(image_data, target_size=(320, 84))
                if not processed:
                    return False
                pass_obj.addFile('strip.png', processed)
                processed.seek(0)
                pass_obj.addFile('strip@2x.png', processed)
                logger.info(f"Added profile image as strip for {player.name}")

            return True

        except Exception as e:
            logger.warning(f"Error adding profile image: {e}")
            return False

    def _get_image_data(self, image_url: str) -> Optional[BytesIO]:
        """
        Download or load an image.

        Args:
            image_url: URL or local path to image

        Returns:
            BytesIO containing image data or None
        """
        try:
            if image_url.startswith('/static/'):
                local_path = os.path.join('app', image_url.lstrip('/'))
                if os.path.exists(local_path):
                    with open(local_path, 'rb') as f:
                        return BytesIO(f.read())
            elif image_url.startswith('http'):
                response = requests.get(image_url, timeout=10)
                if response.status_code == 200:
                    return BytesIO(response.content)
            return None
        except Exception as e:
            logger.warning(f"Error fetching image from {image_url}: {e}")
            return None

    def _process_image_for_wallet(self, image_data: BytesIO, target_size: tuple = (320, 84)) -> Optional[BytesIO]:
        """
        Process image for Apple Wallet specifications.

        Args:
            image_data: BytesIO containing image data
            target_size: Tuple of (width, height) for the output image
                        - Strip: (320, 84) for storeCard/eventTicket
                        - Thumbnail: (90, 90) for generic, (180, 180) for 2x

        Returns:
            BytesIO containing processed PNG image
        """
        try:
            img = Image.open(image_data)

            # Convert to RGB if needed
            if img.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                if img.mode == 'RGBA':
                    background.paste(img, mask=img.split()[-1])
                else:
                    background.paste(img)
                img = background

            # Resize to target size
            img = img.resize(target_size, Image.Resampling.LANCZOS)

            output = BytesIO()
            img.save(output, format='PNG', optimize=True)
            output.seek(0)

            return output

        except Exception as e:
            logger.warning(f"Error processing image: {e}")
            return None

    def _sign_pass(self, pass_obj: Pass) -> BytesIO:
        """
        Sign and create the final .pkpass file.

        Args:
            pass_obj: wallet.models.Pass object

        Returns:
            BytesIO containing the signed .pkpass file
        """
        pass_buffer = BytesIO()

        pass_obj.create(
            self.config.certificate_path,
            self.config.key_path,
            self.config.wwdr_path,
            self.config.key_password,
            pass_buffer
        )

        pass_buffer.seek(0)
        return pass_buffer


def validate_apple_config():
    """
    Validate Apple Wallet configuration.

    Returns:
        dict with 'configured' boolean and 'issues' list
    """
    issues = []

    try:
        config = ApplePassConfig()
        config.validate()
    except ValueError as e:
        issues.append(str(e))
    except Exception as e:
        issues.append(f"Configuration error: {e}")

    # Check for templates
    template_path = 'app/wallet_pass/templates/apple'
    if not os.path.exists(template_path):
        issues.append(f"Template directory not found: {template_path}")

    # Check for assets
    asset_path = 'app/wallet_pass/assets'
    required_assets = ['icon.png', 'logo.png']
    for asset in required_assets:
        if not os.path.exists(os.path.join(asset_path, asset)):
            issues.append(f"Required asset not found: {asset}")

    return {
        'configured': len(issues) == 0,
        'issues': issues
    }
