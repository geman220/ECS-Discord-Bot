# app/wallet_pass/generators/google.py

"""
Google Wallet Pass Generator

Generates Google Wallet passes natively using JWT (JSON Web Token).
This gives full control over pass content including hero images,
fields, barcodes, and member data.

Architecture:
  1. Ensure Google Wallet Class exists (create/update if needed)
  2. Build genericObject JSON with all pass data
  3. Sign as JWT using Google service account credentials
  4. Return "Add to Google Wallet" URL with embedded JWT
"""

import os
import json
import logging
import time
from io import BytesIO
from typing import Optional, Tuple, Dict, Any, List
from datetime import datetime

from google.oauth2 import service_account
from google.auth.transport.requests import AuthorizedSession
import jwt  # PyJWT library

from .base import BasePassGenerator

logger = logging.getLogger(__name__)

# Google Wallet API base URL
WALLET_API_BASE = "https://walletobjects.googleapis.com/walletobjects/v1"


def _check_google_wallet_config() -> Tuple[bool, str]:
    """
    Check if Google Wallet is properly configured for native JWT generation.

    Returns:
        Tuple of (is_available, reason)
    """
    issuer_id = os.getenv('GOOGLE_WALLET_ISSUER_ID')
    if not issuer_id:
        return False, "GOOGLE_WALLET_ISSUER_ID not set"

    service_account_path = os.getenv(
        'GOOGLE_WALLET_SERVICE_ACCOUNT',
        'app/wallet_pass/certs/google-service-account.json'
    )
    if not os.path.exists(service_account_path):
        return False, f"Service account not found at {service_account_path}"

    # Verify service account file is valid JSON with required fields
    try:
        with open(service_account_path, 'r') as f:
            sa_data = json.load(f)
            if 'client_email' not in sa_data or 'private_key' not in sa_data:
                return False, "Service account missing client_email or private_key"
    except (json.JSONDecodeError, IOError) as e:
        return False, f"Invalid service account file: {e}"

    return True, "OK"


# Check configuration at module load
_config_available, _config_reason = _check_google_wallet_config()
GOOGLE_WALLET_AVAILABLE = _config_available

if not GOOGLE_WALLET_AVAILABLE:
    logger.info(f"Google Wallet not available: {_config_reason}")
else:
    logger.info("Google Wallet configuration validated")


class GooglePassConfig:
    """Configuration for Google Wallet pass generation using native JWT"""

    def __init__(self):
        self.issuer_id = os.getenv('GOOGLE_WALLET_ISSUER_ID')
        self.service_account_path = os.getenv(
            'GOOGLE_WALLET_SERVICE_ACCOUNT',
            'app/wallet_pass/certs/google-service-account.json'
        )
        self._service_account_data = None

    def validate(self):
        """Validate that all required configuration exists"""
        missing = []

        if not self.issuer_id:
            missing.append("GOOGLE_WALLET_ISSUER_ID not set")

        if not os.path.exists(self.service_account_path):
            missing.append(f"Service account file not found at {self.service_account_path}")

        if missing:
            raise ValueError(f"Google Wallet configuration errors: {'; '.join(missing)}")

        return True

    @property
    def service_account_data(self) -> dict:
        """Load and cache service account data"""
        if self._service_account_data is None:
            with open(self.service_account_path, 'r') as f:
                self._service_account_data = json.load(f)
        return self._service_account_data

    @property
    def service_account_email(self) -> str:
        """Get service account email for JWT signing"""
        return self.service_account_data.get('client_email')

    @property
    def private_key(self) -> str:
        """Get private key for JWT signing"""
        return self.service_account_data.get('private_key')

    def get_authorized_session(self) -> AuthorizedSession:
        """Get an authorized session for Google Wallet API calls."""
        credentials = service_account.Credentials.from_service_account_file(
            self.service_account_path,
            scopes=['https://www.googleapis.com/auth/wallet_object.issuer']
        )
        return AuthorizedSession(credentials)


def _get_class_id(issuer_id: str, apple_pass_type_id: str) -> str:
    """
    Generate the Google Wallet class ID from issuer ID and Apple pass type ID.

    Format: {issuer_id}.{apple_pass_type_id}
    Example: 3388000000022958274.pass.com.ecsfc.membership
    """
    return f"{issuer_id}.{apple_pass_type_id}"


def ensure_google_wallet_class_exists(
    config: 'GooglePassConfig',
    pass_type,
    force_update: bool = False
) -> str:
    """
    Ensure the Google Wallet class exists, creating it if needed.

    Google Wallet requires a "class" to be created before objects (passes)
    can be created. This function checks if the class exists and creates
    it if not.

    Args:
        config: GooglePassConfig instance
        pass_type: WalletPassType model instance
        force_update: If True, update the class even if it exists

    Returns:
        The class ID
    """
    class_id = _get_class_id(config.issuer_id, pass_type.apple_pass_type_id)

    session = config.get_authorized_session()

    # Check if class exists (using genericClass for membership cards)
    check_url = f"{WALLET_API_BASE}/genericClass/{class_id}"
    response = session.get(check_url)

    if response.status_code == 200 and not force_update:
        logger.debug(f"Google Wallet class {class_id} already exists")
        return class_id

    # Class doesn't exist (404) or we're forcing update - create/update it
    class_definition = _build_class_definition(config.issuer_id, pass_type)

    if response.status_code == 200:
        # Update existing class
        update_url = f"{WALLET_API_BASE}/genericClass/{class_id}"
        response = session.put(update_url, json=class_definition)
        action = "updated"
    else:
        # Create new class
        create_url = f"{WALLET_API_BASE}/genericClass"
        response = session.post(create_url, json=class_definition)
        action = "created"

    if response.status_code in (200, 201):
        logger.info(f"Google Wallet class {class_id} {action} successfully")
        return class_id
    elif response.status_code == 409:
        # Class already exists (race condition) - that's fine
        logger.debug(f"Google Wallet class {class_id} already exists (409)")
        return class_id
    else:
        error_detail = response.text[:500] if response.text else "No details"
        raise ValueError(
            f"Failed to create Google Wallet class {class_id}: "
            f"{response.status_code} - {error_detail}"
        )


def _get_hero_image_url(pass_type) -> Optional[str]:
    """
    Get hero image URL, auto-generating from strip.png if not configured.

    Args:
        pass_type: WalletPassType model instance

    Returns:
        URL to hero image, or None if not available
    """
    # If explicitly configured, use that
    if pass_type.google_hero_image_url:
        return pass_type.google_hero_image_url

    # Try to use the strip image from wallet assets as hero
    # The strip image is used for Apple passes and can serve as hero for Google
    base_url = os.getenv('WEBUI_BASE_URL', 'https://portal.ecsfc.com')

    # Check if strip asset exists for this pass type
    try:
        from app.models.wallet_asset import WalletAsset
        strip_asset = WalletAsset.query.filter_by(
            pass_type_id=pass_type.id,
            asset_type='strip'
        ).first()

        if strip_asset:
            # Serve the strip as hero image through our public asset route
            return f"{base_url}/membership/wallet/assets/{pass_type.code}/strip.png"
    except Exception as e:
        logger.debug(f"Could not check for strip asset: {e}")

    return None


def _build_class_definition(issuer_id: str, pass_type) -> dict:
    """
    Build the Google Wallet genericClass definition from pass type.

    Uses genericClass instead of eventTicketClass because membership cards
    need flexible field layouts with custom text modules, headers, and
    subheaders that genericClass provides.

    Args:
        issuer_id: Google Wallet Issuer ID
        pass_type: WalletPassType model instance

    Returns:
        Dict suitable for Google Wallet API

    WalletPassType attributes used:
        - apple_pass_type_id: Used to generate class ID
        - name: Pass type name (e.g., "ECS Membership")
        - logo_text: Organization name (e.g., "ECS")
        - background_color: Hex color (e.g., "#213e96")
        - google_logo_url: Public URL to logo image
        - google_hero_image_url: Public URL to hero/banner image
    """
    class_id = _get_class_id(issuer_id, pass_type.apple_pass_type_id)

    # Get colors directly from pass_type model
    # Default to ECS blue instead of black
    background_color = pass_type.background_color or '#213e96'

    # Build the genericClass definition
    class_def = {
        "id": class_id,
        "issuerName": pass_type.logo_text or "ECS FC",
        # Card title shown at top of pass
        "cardTitle": {
            "defaultValue": {
                "language": "en",
                "value": pass_type.name or "Membership"
            }
        },
        # Subheader provides context (e.g., "Member")
        "subheader": {
            "defaultValue": {
                "language": "en",
                "value": "Member"
            }
        },
        # Header will be set per-object (member name)
        "header": {
            "defaultValue": {
                "language": "en",
                "value": ""
            }
        },
        "reviewStatus": "UNDER_REVIEW",  # Required for new classes
        "hexBackgroundColor": background_color,
        # Allow multiple users to save the same object
        "multipleDevicesAndHoldersAllowedStatus": "ONE_USER_ALL_DEVICES",
    }

    # Add logo if configured
    # This must be a publicly accessible URL that Google's servers can fetch
    if pass_type.google_logo_url:
        class_def["logo"] = {
            "sourceUri": {
                "uri": pass_type.google_logo_url
            }
        }
        logger.debug(f"Using logo URL for class: {pass_type.google_logo_url}")

    # Add hero/wide image - try configured URL first, then auto-generate from strip
    hero_url = _get_hero_image_url(pass_type)
    if hero_url:
        class_def["heroImage"] = {
            "sourceUri": {
                "uri": hero_url
            }
        }
        logger.debug(f"Using hero image URL for class: {hero_url}")

    logger.debug(f"Built genericClass definition for {class_id}: {json.dumps(class_def, indent=2)}")
    return class_def


class GooglePassGenerator(BasePassGenerator):
    """
    Generates Google Wallet passes natively using JWT.

    Creates passes with full control over content: hero images, fields,
    barcodes, and member data. No external converter service needed.
    """

    def __init__(self, pass_type, config: GooglePassConfig = None):
        """
        Initialize Google pass generator.

        Args:
            pass_type: WalletPassType model instance
            config: GooglePassConfig instance (optional)
        """
        super().__init__(pass_type)
        self.config = config or GooglePassConfig()

    def get_platform_name(self) -> str:
        return 'google'

    def generate(self, wallet_pass, apple_pass_bytes: Optional[bytes] = None) -> str:
        """
        Generate a Google Wallet pass using native JWT.

        Args:
            wallet_pass: WalletPass model instance
            apple_pass_bytes: Ignored (kept for API compatibility)

        Returns:
            URL to add the pass to Google Wallet
        """
        try:
            # Validate configuration
            self.config.validate()

            # Ensure Google Wallet class exists before creating objects
            class_id = ensure_google_wallet_class_exists(self.config, self.pass_type)
            logger.debug(f"Google Wallet class ready: {class_id}")

            # Build the pass object
            pass_object = self._build_pass_object(wallet_pass, class_id)

            # Generate JWT and save URL
            google_wallet_url = self._generate_save_url(pass_object)

            logger.info(
                f"Generated Google Wallet pass for {wallet_pass.member_name} "
                f"(type: {self.pass_type.code})"
            )

            # Store the URL on the wallet pass for future reference
            wallet_pass.google_pass_url = google_wallet_url
            wallet_pass.google_pass_generated = True
            wallet_pass.google_pass_generated_at = datetime.utcnow()

            return google_wallet_url

        except Exception as e:
            logger.error(f"Error generating Google Wallet pass: {e}")
            raise

    def _build_pass_object(self, wallet_pass, class_id: str) -> Dict[str, Any]:
        """
        Build the Google Wallet genericObject for this pass.

        Reads field configurations from the database (same as Apple) for full parity.

        Args:
            wallet_pass: WalletPass model instance
            class_id: The class ID this object belongs to

        Returns:
            Dict representing the genericObject
        """
        issuer_id = self.config.issuer_id
        object_id = f"{issuer_id}.{self.pass_type.code}_{wallet_pass.serial_number}"

        # Get template data (shared with Apple generator)
        template_data = self.get_template_data(wallet_pass)

        # Get colors from pass type
        background_color = self.pass_type.background_color or '#213e96'

        # Build the object
        pass_object = {
            "id": object_id,
            "classId": class_id,
            "genericType": "GENERIC_TYPE_UNSPECIFIED",
            "hexBackgroundColor": background_color,
            "cardTitle": {
                "defaultValue": {
                    "language": "en",
                    "value": self.pass_type.name or "Membership"
                }
            },
            "subheader": {
                "defaultValue": {
                    "language": "en",
                    "value": "Member"
                }
            },
            "header": {
                "defaultValue": {
                    "language": "en",
                    "value": wallet_pass.member_name or "Member"
                }
            },
            "state": "ACTIVE"
        }

        # Add logo if configured
        logo_url = self.pass_type.google_logo_url or self._get_default_logo_url()
        if logo_url:
            pass_object["logo"] = {
                "sourceUri": {"uri": logo_url},
                "contentDescription": {
                    "defaultValue": {"language": "en", "value": "Logo"}
                }
            }

        # Add hero image
        hero_url = _get_hero_image_url(self.pass_type)
        if hero_url:
            pass_object["heroImage"] = {
                "sourceUri": {"uri": hero_url},
                "contentDescription": {
                    "defaultValue": {"language": "en", "value": self.pass_type.name}
                }
            }

        # Build text modules from database field configurations (same source as Apple)
        text_modules = self._build_text_modules_from_config(wallet_pass, template_data)
        if text_modules:
            pass_object["textModulesData"] = text_modules

        # Add barcode (unless suppressed)
        if not self.pass_type.suppress_barcode:
            barcode_data = wallet_pass.barcode_data or wallet_pass.serial_number
            pass_object["barcode"] = {
                "type": "QR_CODE",
                "value": barcode_data,
                "alternateText": barcode_data
            }

        logger.debug(f"Built pass object: {json.dumps(pass_object, indent=2, default=str)}")
        return pass_object

    def _build_text_modules_from_config(self, wallet_pass, template_data: Dict) -> List[Dict]:
        """
        Build Google Wallet textModulesData from database field configurations.

        This reads from the same WalletPassFieldConfig table as Apple passes,
        ensuring field parity between platforms.

        Args:
            wallet_pass: WalletPass model instance
            template_data: Template data dictionary

        Returns:
            List of textModulesData dictionaries
        """
        from app.models.wallet_config import WalletPassFieldConfig

        text_modules = []

        # Get field configurations from database (same query as Apple)
        field_configs = WalletPassFieldConfig.query.filter(
            WalletPassFieldConfig.pass_type_id == self.pass_type.id,
            WalletPassFieldConfig.is_visible == True
        ).order_by(WalletPassFieldConfig.display_order).all()

        logger.debug(f"Found {len(field_configs)} field configs for Google pass")

        for field in field_configs:
            # Render the value template with pass data
            value = field.value_template or ''
            for key, val in template_data.items():
                value = value.replace('{{' + key + '}}', str(val) if val is not None else '')

            # Skip empty values
            if not value.strip():
                continue

            text_modules.append({
                "id": field.field_key,
                "header": field.label or field.field_key.replace('_', ' ').title(),
                "body": value
            })

        # If no field configs found, use defaults (same fallback as Apple)
        if not field_configs:
            logger.warning(f"No field configs found for {self.pass_type.code}, using defaults")

            # Membership year
            if wallet_pass.membership_year:
                text_modules.append({
                    "id": "membership_year",
                    "header": "Membership Year",
                    "body": str(wallet_pass.membership_year)
                })

            # Valid until
            if wallet_pass.valid_until:
                valid_str = wallet_pass.valid_until.strftime('%B %d, %Y') if hasattr(wallet_pass.valid_until, 'strftime') else str(wallet_pass.valid_until)
                text_modules.append({
                    "id": "valid_until",
                    "header": "Valid Until",
                    "body": valid_str
                })

            # Status
            text_modules.append({
                "id": "status",
                "header": "Status",
                "body": wallet_pass.status.capitalize() if wallet_pass.status else "Active"
            })

        return text_modules

    def _get_default_logo_url(self) -> Optional[str]:
        """Get default logo URL from assets"""
        base_url = os.getenv('WEBUI_BASE_URL', 'https://portal.ecsfc.com')
        try:
            from app.models.wallet_asset import WalletAsset
            logo_asset = WalletAsset.query.filter_by(
                pass_type_id=self.pass_type.id,
                asset_type='logo'
            ).first()
            if logo_asset:
                return f"{base_url}/membership/wallet/assets/{self.pass_type.code}/logo.png"
        except Exception as e:
            logger.debug(f"Could not get logo asset: {e}")
        return None

    def _generate_save_url(self, pass_object: Dict[str, Any]) -> str:
        """
        Generate a Google Wallet "Add to Wallet" URL with signed JWT.

        Args:
            pass_object: The genericObject dict

        Returns:
            URL that opens Google Wallet add dialog
        """
        # Build the JWT claims
        claims = {
            "iss": self.config.service_account_email,
            "aud": "google",
            "typ": "savetowallet",
            "iat": int(time.time()),
            "payload": {
                "genericObjects": [pass_object]
            },
            "origins": [os.getenv('WEBUI_BASE_URL', 'https://portal.ecsfc.com')]
        }

        # Sign the JWT
        token = jwt.encode(
            claims,
            self.config.private_key,
            algorithm="RS256"
        )

        # Build the save URL
        save_url = f"https://pay.google.com/gp/v/save/{token}"

        logger.debug(f"Generated save URL (length: {len(save_url)})")
        return save_url


def validate_google_config() -> tuple:
    """
    Validate Google Wallet configuration for native JWT generation.

    Returns:
        Tuple of (is_valid: bool, errors: list)
    """
    errors = []

    issuer_id = os.getenv('GOOGLE_WALLET_ISSUER_ID')
    if not issuer_id:
        errors.append("GOOGLE_WALLET_ISSUER_ID environment variable not set")

    service_account_path = os.getenv(
        'GOOGLE_WALLET_SERVICE_ACCOUNT',
        'app/wallet_pass/certs/google-service-account.json'
    )
    if not os.path.exists(service_account_path):
        errors.append(f"Google service account file not found at {service_account_path}")
    else:
        # Verify service account file is valid
        try:
            with open(service_account_path, 'r') as f:
                sa_data = json.load(f)
                if 'client_email' not in sa_data:
                    errors.append("Service account missing client_email")
                if 'private_key' not in sa_data:
                    errors.append("Service account missing private_key")
        except (json.JSONDecodeError, IOError) as e:
            errors.append(f"Invalid service account file: {e}")

    return len(errors) == 0, errors
