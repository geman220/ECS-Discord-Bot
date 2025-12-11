# app/wallet_pass/generators/google.py

"""
Google Wallet Pass Generator

Generates Google Wallet passes using the GoogleWalletPassGenerator library.
Supports both ECS Membership and Pub League passes.
"""

import os
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional

from .base import BasePassGenerator

logger = logging.getLogger(__name__)

# Try to import Google Wallet libraries
try:
    from GoogleWalletPassGenerator.genericpass import GenericPassManager
    from GoogleWalletPassGenerator.types import (
        GenericClass, GenericClassId, GenericObject, GenericObjectId,
        Barcode, LocalizedString, TranslatedString, ImageUri, Image,
        TextModuleData, LinksModuleData, Uri
    )
    from GoogleWalletPassGenerator.enums import (
        ReviewStatus, State, BarcodeType, BarcodeRenderEncoding, MultipleDevicesAndHoldersAllowedStatus
    )
    from GoogleWalletPassGenerator.serializer import serialize_to_json
    GOOGLE_WALLET_AVAILABLE = True
except ImportError:
    GOOGLE_WALLET_AVAILABLE = False
    logger.warning("GoogleWalletPassGenerator not installed. Google Wallet passes will not be available.")


class GooglePassConfig:
    """Configuration for Google Wallet pass generation"""

    def __init__(self):
        self.issuer_id = os.getenv('GOOGLE_WALLET_ISSUER_ID')
        self.service_account_path = os.getenv(
            'GOOGLE_WALLET_SERVICE_ACCOUNT',
            'app/wallet_pass/certs/google-service-account.json'
        )

        if not self.issuer_id:
            raise ValueError("GOOGLE_WALLET_ISSUER_ID environment variable is required")

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


class GooglePassGenerator(BasePassGenerator):
    """
    Generates Google Wallet passes.

    Creates generic passes for ECS Membership and Pub League with
    styling and templates matching the Apple Wallet versions.
    """

    def __init__(self, pass_type, config: GooglePassConfig = None):
        """
        Initialize Google pass generator.

        Args:
            pass_type: WalletPassType model instance
            config: GooglePassConfig instance (optional)
        """
        super().__init__(pass_type)

        if not GOOGLE_WALLET_AVAILABLE:
            raise ImportError("GoogleWalletPassGenerator is not installed")

        self.config = config or GooglePassConfig()
        self._manager = None

    @property
    def manager(self):
        """Lazy-load the GenericPassManager"""
        if self._manager is None:
            self._manager = GenericPassManager(self.config.service_account_path)
        return self._manager

    def get_platform_name(self) -> str:
        return 'google'

    def generate(self, wallet_pass) -> str:
        """
        Generate a Google Wallet pass.

        Args:
            wallet_pass: WalletPass model instance

        Returns:
            URL to add the pass to Google Wallet
        """
        try:
            # Validate wallet pass data
            self.validate_wallet_pass(wallet_pass)

            # Validate Google config
            self.config.validate()

            # Get template data
            template_data = self.get_template_data(wallet_pass)

            # Create or get the class
            class_id = self._ensure_class_exists(template_data)

            # Create the pass object
            pass_url = self._create_pass_object(wallet_pass, template_data, class_id)

            logger.info(
                f"Generated Google Wallet pass for {wallet_pass.member_name} "
                f"(type: {self.pass_type.code})"
            )
            return pass_url

        except Exception as e:
            logger.error(f"Error generating Google Wallet pass: {e}")
            raise

    def _get_class_id(self) -> str:
        """Get the unique class ID for this pass type"""
        return f"{self.pass_type.code.replace('_', '-')}-class"

    def _get_object_id(self, wallet_pass) -> str:
        """Get the unique object ID for a specific pass"""
        return f"{self.pass_type.code.replace('_', '-')}-{wallet_pass.serial_number}"

    def _ensure_class_exists(self, template_data: Dict) -> str:
        """
        Ensure the pass class exists, creating it if necessary.

        Args:
            template_data: Template data dictionary

        Returns:
            The class ID
        """
        class_id = self._get_class_id()

        try:
            # Try to get existing class
            self.manager.get_class(self.config.issuer_id, class_id)
            logger.debug(f"Using existing Google Wallet class: {class_id}")
        except Exception:
            # Class doesn't exist, create it
            logger.info(f"Creating new Google Wallet class: {class_id}")
            self._create_class(template_data)

        return class_id

    def _create_class(self, template_data: Dict):
        """
        Create a new pass class in Google Wallet.

        Args:
            template_data: Template data dictionary
        """
        is_ecs = self.pass_type.code == 'ecs_membership'

        class_data = serialize_to_json(
            GenericClass(
                id=GenericClassId(
                    issuerId=self.config.issuer_id,
                    uniqueId=self._get_class_id()
                ),
                issuerName=template_data['organization_name'],
                reviewStatus=ReviewStatus.UNDER_REVIEW,
                multipleDevicesAndHoldersAllowedStatus=MultipleDevicesAndHoldersAllowedStatus.MULTIPLE_HOLDERS,
            )
        )

        self.manager.create_class(class_data)

    def _create_pass_object(self, wallet_pass, template_data: Dict, class_id: str) -> str:
        """
        Create a pass object and return the add-to-wallet URL.

        Args:
            wallet_pass: WalletPass model instance
            template_data: Template data dictionary
            class_id: The class ID to use

        Returns:
            URL to add the pass to Google Wallet
        """
        is_ecs = self.pass_type.code == 'ecs_membership'

        # Build text modules for pass content
        text_modules = []

        if is_ecs:
            text_modules.append(
                TextModuleData(
                    header="Membership Year",
                    body=str(template_data.get('membership_year', ''))
                )
            )
            text_modules.append(
                TextModuleData(
                    header="Valid Through",
                    body=template_data.get('valid_until_display', '')
                )
            )
            if template_data.get('subgroup'):
                text_modules.append(
                    TextModuleData(
                        header="Subgroup",
                        body=template_data.get('subgroup', '')
                    )
                )
        else:
            # Pub League
            text_modules.append(
                TextModuleData(
                    header="Team",
                    body=template_data.get('team_name', 'TBD')
                )
            )
            text_modules.append(
                TextModuleData(
                    header="Season",
                    body=template_data.get('season_name', '')
                )
            )

        text_modules.append(
            TextModuleData(
                header="Status",
                body=template_data.get('status', 'Active')
            )
        )

        # Build object kwargs (barcode is optional based on suppress_barcode setting)
        object_kwargs = {
            'id': GenericObjectId(
                issuerId=self.config.issuer_id,
                uniqueId=self._get_object_id(wallet_pass)
            ),
            'classId': GenericClassId(
                issuerId=self.config.issuer_id,
                uniqueId=class_id
            ),
            'state': State.ACTIVE if wallet_pass.is_valid else State.EXPIRED,
            'header': LocalizedString(
                defaultValue=TranslatedString("en-US", template_data['member_name'])
            ),
            'subheader': LocalizedString(
                defaultValue=TranslatedString("en-US", template_data['description'])
            ),
            'hexBackgroundColor': self.pass_type.background_color,
            'textModulesData': text_modules,
            'linksModuleData': LinksModuleData(
                uris=[
                    Uri(
                        uri="https://weareecs.com" if is_ecs else "https://portal.ecsfc.com",
                        description="Website"
                    )
                ]
            )
        }

        # Add barcode unless suppressed in pass type settings
        if not template_data.get('suppress_barcode', False):
            object_kwargs['barcode'] = Barcode(
                type=BarcodeType.QR_CODE,
                value=wallet_pass.barcode_data,
                renderEncoding=BarcodeRenderEncoding.UTF_8
            )
        else:
            logger.debug(f"Barcode suppressed for Google pass type {self.pass_type.code}")

        # Create the object
        object_data = serialize_to_json(GenericObject(**object_kwargs))

        # Create the object and get the save URL
        try:
            self.manager.create_object(object_data)
        except Exception as e:
            # Object might already exist, try to update
            if "already exists" in str(e).lower():
                logger.debug(f"Object already exists, updating: {self._get_object_id(wallet_pass)}")
                self.manager.update_object(object_data)
            else:
                raise

        # Generate the "Add to Wallet" URL
        save_url = self.manager.create_jwt_save_url(
            self.config.issuer_id,
            self._get_class_id(),
            self._get_object_id(wallet_pass)
        )

        return save_url


def validate_google_config() -> tuple:
    """
    Validate Google Wallet configuration.

    Returns:
        Tuple of (is_valid: bool, errors: list)
    """
    errors = []

    if not GOOGLE_WALLET_AVAILABLE:
        errors.append("GoogleWalletPassGenerator library not installed")
        return False, errors

    issuer_id = os.getenv('GOOGLE_WALLET_ISSUER_ID')
    if not issuer_id:
        errors.append("GOOGLE_WALLET_ISSUER_ID environment variable not set")

    service_account_path = os.getenv(
        'GOOGLE_WALLET_SERVICE_ACCOUNT',
        'app/wallet_pass/certs/google-service-account.json'
    )
    if not os.path.exists(service_account_path):
        errors.append(f"Google service account file not found at {service_account_path}")

    return len(errors) == 0, errors
