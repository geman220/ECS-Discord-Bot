# app/wallet_pass/generators/base.py

"""
Base Pass Generator

Abstract base class for wallet pass generators. Provides common functionality
for generating passes across different platforms (Apple, Google).
"""

import os
import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from io import BytesIO
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class BasePassGenerator(ABC):
    """
    Abstract base class for wallet pass generation.

    Provides common functionality for loading templates, preparing data,
    and generating passes. Platform-specific implementations (Apple, Google)
    extend this class.
    """

    def __init__(self, pass_type):
        """
        Initialize the generator with a pass type.

        Args:
            pass_type: WalletPassType model instance
        """
        self.pass_type = pass_type
        self.base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    @abstractmethod
    def generate(self, wallet_pass) -> Any:
        """
        Generate the pass file/URL.

        Args:
            wallet_pass: WalletPass model instance

        Returns:
            Platform-specific output (BytesIO for Apple, URL for Google)
        """
        pass

    @abstractmethod
    def get_platform_name(self) -> str:
        """Return the platform name (e.g., 'apple', 'google')"""
        pass

    def load_template(self, template_name: str) -> Dict[str, Any]:
        """
        Load a JSON template file.

        Args:
            template_name: Name of the template file (without .json)

        Returns:
            Parsed JSON template as dictionary
        """
        platform = self.get_platform_name()
        template_path = os.path.join(
            self.base_path, 'templates', platform, f'{template_name}.json'
        )

        if not os.path.exists(template_path):
            logger.error(f"Template not found: {template_path}")
            raise FileNotFoundError(f"Template not found: {template_path}")

        with open(template_path, 'r') as f:
            return json.load(f)

    def get_common_template_data(self, wallet_pass) -> Dict[str, Any]:
        """
        Get common template data used across all platforms.

        Args:
            wallet_pass: WalletPass model instance

        Returns:
            Dictionary of common template variables
        """
        # Get membership year or extract from valid_from
        membership_year = wallet_pass.membership_year or ''
        if not membership_year and wallet_pass.valid_from:
            membership_year = str(wallet_pass.valid_from.year)

        # Calculate member_since (use first year of membership if available in pass_data)
        member_since = ''
        if wallet_pass.pass_data and isinstance(wallet_pass.pass_data, dict):
            member_since = wallet_pass.pass_data.get('member_since', '')
        if not member_since and wallet_pass.created_at:
            member_since = str(wallet_pass.created_at.year)

        return {
            'serial_number': wallet_pass.serial_number,
            'member_name': wallet_pass.member_name,
            'member_email': wallet_pass.member_email or '',
            'team_name': wallet_pass.team_name or '',
            'barcode_data': wallet_pass.barcode_data,
            'valid_from': wallet_pass.valid_from.strftime('%Y-%m-%d'),
            'valid_until': wallet_pass.valid_until.strftime('%Y-%m-%d'),
            'valid_until_display': wallet_pass.valid_until.strftime('%b %d, %Y'),
            'display_validity': wallet_pass.display_validity,
            'membership_year': membership_year,
            'issue_date': datetime.utcnow().strftime('%Y-%m-%d'),
            'authentication_token': wallet_pass.authentication_token,
            'status': 'Active' if wallet_pass.is_valid else 'Expired',

            # Aliases for template field configs
            'validity': membership_year,  # Alias for {{validity}} in field templates
            'member_since': member_since,  # For "Supporting Since" field

            # Pass type info
            'pass_type_name': self.pass_type.name,
            'pass_type_code': self.pass_type.code,
            'background_color': self.pass_type.background_color,
            'foreground_color': self.pass_type.foreground_color,
            'label_color': self.pass_type.label_color,
            'logo_text': self.pass_type.logo_text,
            'suppress_barcode': self.pass_type.suppress_barcode or False,
        }

    def get_ecs_membership_data(self, wallet_pass) -> Dict[str, Any]:
        """
        Get ECS membership-specific template data.

        Args:
            wallet_pass: WalletPass model instance

        Returns:
            Dictionary with ECS membership specific data
        """
        common = self.get_common_template_data(wallet_pass)

        # Get subgroup from pass data (may be None)
        subgroup = None
        if wallet_pass.pass_data and isinstance(wallet_pass.pass_data, dict):
            subgroup = wallet_pass.pass_data.get('subgroup')

        common.update({
            'header_text': f'ECS Membership {wallet_pass.membership_year}',
            'description': f'ECS FC Membership Card {wallet_pass.membership_year}',
            'organization_name': 'ECS FC',
            'validity_label': 'Valid Through',
            'validity_value': f'December 31, {wallet_pass.membership_year}',
            'subgroup': subgroup,
            'has_subgroup': bool(subgroup),
        })
        return common

    def get_pub_league_data(self, wallet_pass) -> Dict[str, Any]:
        """
        Get Pub League-specific template data.

        Args:
            wallet_pass: WalletPass model instance

        Returns:
            Dictionary with Pub League specific data
        """
        common = self.get_common_template_data(wallet_pass)

        season_name = wallet_pass.season.name if wallet_pass.season else 'Current Season'

        common.update({
            'header_text': f'Pub League {season_name}',
            'description': f'ECS Pub League Membership - {season_name}',
            'organization_name': 'ECS Pub League',
            'season_name': season_name,
            'validity_label': 'Season',
            'validity_value': season_name,
        })
        return common

    def get_template_data(self, wallet_pass) -> Dict[str, Any]:
        """
        Get template data based on pass type.

        Args:
            wallet_pass: WalletPass model instance

        Returns:
            Dictionary of template variables
        """
        if self.pass_type.code == 'ecs_membership':
            return self.get_ecs_membership_data(wallet_pass)
        elif self.pass_type.code == 'pub_league':
            return self.get_pub_league_data(wallet_pass)
        else:
            return self.get_common_template_data(wallet_pass)

    def render_template(self, template: Dict, data: Dict) -> Dict:
        """
        Render a template by replacing placeholders with data.

        Args:
            template: Template dictionary
            data: Data dictionary for replacement

        Returns:
            Rendered template dictionary
        """
        template_str = json.dumps(template)

        for key, value in data.items():
            placeholder = f'{{{{{key}}}}}'
            template_str = template_str.replace(placeholder, str(value))

        return json.loads(template_str)

    def get_asset_path(self, asset_name: str, pass_type_specific: bool = True) -> Optional[str]:
        """
        Get the path to an asset file.

        Args:
            asset_name: Name of the asset file
            pass_type_specific: Whether to look in pass type-specific directory

        Returns:
            Path to asset file or None if not found
        """
        if pass_type_specific:
            # Look in pass type specific directory first
            specific_path = os.path.join(
                self.base_path, 'assets', self.pass_type.code, asset_name
            )
            if os.path.exists(specific_path):
                return specific_path

        # Fall back to common assets
        common_path = os.path.join(self.base_path, 'assets', asset_name)
        if os.path.exists(common_path):
            return common_path

        return None

    def validate_wallet_pass(self, wallet_pass) -> bool:
        """
        Validate that a wallet pass has all required data for generation.

        Args:
            wallet_pass: WalletPass model instance

        Returns:
            True if valid, raises ValueError if not
        """
        if not wallet_pass.member_name:
            raise ValueError("Wallet pass must have a member name")

        if not wallet_pass.barcode_data:
            raise ValueError("Wallet pass must have barcode data")

        if not wallet_pass.valid_from or not wallet_pass.valid_until:
            raise ValueError("Wallet pass must have validity dates")

        if not wallet_pass.authentication_token:
            raise ValueError("Wallet pass must have an authentication token")

        return True
