# app/auth/__init__.py

"""
Authentication Package

This package contains routes for authentication:
- Discord OAuth2 authentication
- Standard login/logout
- 2FA verification
- Password reset
- Waitlist registration
- Duplicate account prevention

Refactored from monolithic auth.py for better maintainability.

The legacy auth_legacy.py was removed but can be recovered from git history if needed.
"""

from flask import Blueprint

# Create the auth blueprint
auth = Blueprint('auth', __name__)


def register_auth_routes():
    """
    Register all authentication routes by importing route modules.

    This uses deferred imports to register routes with the auth blueprint.
    Each module contains related routes that were extracted from the original
    monolithic auth.py file.
    """
    # Import all route modules to register them with the blueprint
    from app.auth import (
        discord,
        login,
        two_factor,
        password,
        registration,
        waitlist,
        duplicates,
        roles,
    )


# Import the auth blueprint for external use
__all__ = ['auth', 'register_auth_routes']
