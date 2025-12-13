# app/init/jwt.py

"""
JWT Initialization

Initialize Flask-JWT-Extended with custom error handlers.
"""

import logging
from flask import jsonify

logger = logging.getLogger(__name__)


def init_jwt(app):
    """
    Initialize JWT for API authentication.

    Args:
        app: The Flask application instance.

    Returns:
        The JWTManager instance.
    """
    from flask_jwt_extended import JWTManager

    jwt = JWTManager(app)

    # Configure JWT error handlers to return proper JSON responses instead of 422
    @jwt.expired_token_loader
    def expired_token_callback(jwt_header, jwt_payload):
        """Handle expired JWT tokens."""
        logger.warning(f"JWT token expired for user: {jwt_payload.get('sub', 'unknown')}")
        return jsonify({
            'error': 'Token has expired',
            'code': 'TOKEN_EXPIRED'
        }), 401

    @jwt.invalid_token_loader
    def invalid_token_callback(error):
        """Handle invalid JWT tokens."""
        logger.warning(f"Invalid JWT token: {error}")
        return jsonify({
            'error': 'Invalid token',
            'code': 'INVALID_TOKEN'
        }), 401

    @jwt.unauthorized_loader
    def missing_token_callback(error):
        """Handle missing JWT tokens."""
        logger.warning(f"Missing JWT token: {error}")
        return jsonify({
            'error': 'Authorization required',
            'code': 'MISSING_TOKEN'
        }), 401

    @jwt.revoked_token_loader
    def revoked_token_callback(jwt_header, jwt_payload):
        """Handle revoked JWT tokens."""
        logger.warning(f"Revoked JWT token for user: {jwt_payload.get('sub', 'unknown')}")
        return jsonify({
            'error': 'Token has been revoked',
            'code': 'TOKEN_REVOKED'
        }), 401

    @jwt.needs_fresh_token_loader
    def token_not_fresh_callback(jwt_header, jwt_payload):
        """Handle tokens that need to be refreshed."""
        return jsonify({
            'error': 'Fresh token required',
            'code': 'FRESH_TOKEN_REQUIRED'
        }), 401

    return jwt
