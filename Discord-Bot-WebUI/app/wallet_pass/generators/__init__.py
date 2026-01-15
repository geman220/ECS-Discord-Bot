# app/wallet_pass/generators/__init__.py

"""
Wallet Pass Generators

This package contains generators for different wallet platforms:
- Apple Wallet (.pkpass files with PKCS#7 signature)
- Google Wallet (native JWT generation with service account signing)

Both platforms share the same source of truth (WalletPass database model
and WalletPassFieldConfig), ensuring 1:1 parity in pass content.
"""

from .base import BasePassGenerator
from .apple import ApplePassGenerator, validate_apple_config
from .google import GooglePassGenerator, validate_google_config, GOOGLE_WALLET_AVAILABLE

__all__ = [
    'BasePassGenerator',
    'ApplePassGenerator',
    'GooglePassGenerator',
    'validate_apple_config',
    'validate_google_config',
    'GOOGLE_WALLET_AVAILABLE',
]
