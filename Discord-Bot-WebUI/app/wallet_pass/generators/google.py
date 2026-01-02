# app/wallet_pass/generators/google.py

"""
Google Wallet Pass Generator

Converts Apple Wallet passes to Google Wallet format using Google's
official pass-converter service. This approach ensures consistent
pass designs across both platforms from a single source of truth.

Architecture:
  1. Generate Apple .pkpass file (using existing ApplePassGenerator)
  2. POST the .pkpass to pass-converter service
  3. pass-converter returns a Google Wallet "Add to Wallet" URL
"""

import os
import logging
import requests
from io import BytesIO
from typing import Optional, Tuple

from .base import BasePassGenerator

logger = logging.getLogger(__name__)


def _check_google_wallet_config() -> Tuple[bool, str]:
    """
    Check if Google Wallet is properly configured.

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

    converter_url = os.getenv('PASS_CONVERTER_URL', 'http://pass-converter:3000')
    if not converter_url:
        return False, "PASS_CONVERTER_URL not configured"

    return True, "OK"


# Check configuration at module load
_config_available, _config_reason = _check_google_wallet_config()
GOOGLE_WALLET_AVAILABLE = _config_available

if not GOOGLE_WALLET_AVAILABLE:
    logger.info(f"Google Wallet not available: {_config_reason}")
else:
    logger.info("Google Wallet configuration validated")


class GooglePassConfig:
    """Configuration for Google Wallet pass generation via pass-converter"""

    def __init__(self):
        self.issuer_id = os.getenv('GOOGLE_WALLET_ISSUER_ID')
        self.service_account_path = os.getenv(
            'GOOGLE_WALLET_SERVICE_ACCOUNT',
            'app/wallet_pass/certs/google-service-account.json'
        )
        self.converter_url = os.getenv('PASS_CONVERTER_URL', 'http://pass-converter:3000')

    def validate(self):
        """Validate that all required configuration exists"""
        missing = []

        if not self.issuer_id:
            missing.append("GOOGLE_WALLET_ISSUER_ID not set")

        if not os.path.exists(self.service_account_path):
            missing.append(f"Service account file not found at {self.service_account_path}")

        if not self.converter_url:
            missing.append("PASS_CONVERTER_URL not configured")

        if missing:
            raise ValueError(f"Google Wallet configuration errors: {'; '.join(missing)}")

        return True


class GooglePassGenerator(BasePassGenerator):
    """
    Generates Google Wallet passes by converting Apple passes.

    Uses Google's official pass-converter service to convert .pkpass
    files to Google Wallet format. This ensures consistent pass designs
    across both platforms.
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
        Generate a Google Wallet pass by converting an Apple pass.

        Args:
            wallet_pass: WalletPass model instance
            apple_pass_bytes: Optional pre-generated Apple .pkpass bytes.
                              If not provided, will generate using ApplePassGenerator.

        Returns:
            URL to add the pass to Google Wallet
        """
        try:
            # Validate configuration
            self.config.validate()

            # Generate Apple pass if not provided
            if apple_pass_bytes is None:
                from .apple import ApplePassGenerator
                apple_generator = ApplePassGenerator(self.pass_type)
                apple_pass_file = apple_generator.generate(wallet_pass)
                apple_pass_bytes = apple_pass_file.getvalue()
                logger.debug(f"Generated Apple pass for conversion ({len(apple_pass_bytes)} bytes)")

            # Convert to Google Wallet via pass-converter service
            google_wallet_url = self._convert_to_google(apple_pass_bytes, wallet_pass)

            logger.info(
                f"Generated Google Wallet pass for {wallet_pass.member_name} "
                f"(type: {self.pass_type.code})"
            )

            # Store the URL on the wallet pass for future reference
            wallet_pass.google_pass_url = google_wallet_url
            wallet_pass.google_pass_generated = True
            from datetime import datetime
            wallet_pass.google_pass_generated_at = datetime.utcnow()

            return google_wallet_url

        except Exception as e:
            logger.error(f"Error generating Google Wallet pass: {e}")
            raise

    def _convert_to_google(self, apple_pass_bytes: bytes, wallet_pass) -> str:
        """
        Convert Apple .pkpass to Google Wallet URL via pass-converter.

        Args:
            apple_pass_bytes: The .pkpass file as bytes
            wallet_pass: WalletPass model instance (for logging)

        Returns:
            Google Wallet "Add to Wallet" URL
        """
        convert_url = f"{self.config.converter_url}/convert/"

        try:
            response = requests.post(
                convert_url,
                files={
                    'pass': (
                        f'{wallet_pass.serial_number}.pkpass',
                        apple_pass_bytes,
                        'application/vnd.apple.pkpass'
                    )
                },
                allow_redirects=False,
                timeout=30
            )

            # pass-converter returns 302 redirect with Google Wallet URL
            if response.status_code == 302:
                google_url = response.headers.get('Location')
                if google_url:
                    logger.debug(f"Got Google Wallet URL: {google_url[:50]}...")
                    return google_url
                else:
                    raise ValueError("pass-converter returned 302 but no Location header")

            # Handle other response codes
            elif response.status_code == 200:
                # Some versions might return URL in body
                data = response.json() if response.headers.get('content-type', '').startswith('application/json') else {}
                if 'url' in data:
                    return data['url']
                elif 'saveUrl' in data:
                    return data['saveUrl']
                raise ValueError(f"pass-converter returned 200 but no URL found in response")

            else:
                error_msg = response.text[:200] if response.text else "No error message"
                raise ValueError(
                    f"pass-converter returned {response.status_code}: {error_msg}"
                )

        except requests.exceptions.ConnectionError as e:
            logger.error(f"Cannot connect to pass-converter at {convert_url}: {e}")
            raise ConnectionError(
                f"pass-converter service unavailable at {self.config.converter_url}. "
                "Ensure the pass-converter container is running."
            )
        except requests.exceptions.Timeout:
            logger.error(f"Timeout connecting to pass-converter")
            raise TimeoutError("pass-converter request timed out after 30 seconds")


def validate_google_config() -> tuple:
    """
    Validate Google Wallet configuration.

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

    converter_url = os.getenv('PASS_CONVERTER_URL', 'http://pass-converter:3000')
    if not converter_url:
        errors.append("PASS_CONVERTER_URL not configured")

    # Try to reach pass-converter (optional - don't fail validation if down)
    if not errors:
        try:
            response = requests.get(f"{converter_url}/", timeout=5)
            if response.status_code >= 500:
                errors.append(f"pass-converter service returned error: {response.status_code}")
        except requests.exceptions.RequestException as e:
            # Don't add as error - service might not be up during config validation
            logger.warning(f"Could not reach pass-converter at {converter_url}: {e}")

    return len(errors) == 0, errors
