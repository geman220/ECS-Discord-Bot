# app/wallet_pass/generators/__init__.py

"""
Wallet Pass Generators

This package contains generators for different wallet platforms:
- Apple Wallet (.pkpass files)
- Google Wallet (via pass-converter, converts Apple passes to Google Wallet format)
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
