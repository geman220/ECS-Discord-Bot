# app/init/jwt.py

"""
JWT Initialization

Initialize Flask-JWT-Extended with custom error handlers.
"""

import logging
from flask import jsonify, current_app

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

    # Configure blocklist for token revocation (logout support)
    app.config['JWT_BLOCKLIST_ENABLED'] = True
    app.config['JWT_BLOCKLIST_TOKEN_CHECKS'] = ['access', 'refresh']

    @jwt.token_in_blocklist_loader
    def check_if_token_in_blocklist(jwt_header, jwt_payload):
        """Check if a token has been revoked."""
        jti = jwt_payload.get('jti')
        if not jti:
            return False
        try:
            redis_client = current_app.redis
            if redis_client:
                return redis_client.exists(f"jwt_blocklist:{jti}") > 0
        except Exception as e:
            logger.error(f"Error checking token blocklist: {e}")
        return False

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


def add_token_to_blocklist(jti: str, expires_in_seconds: int):
    """
    Add a token JTI to the blocklist.

    Args:
        jti: The unique identifier (JTI) of the token to blocklist
        expires_in_seconds: TTL for the blocklist entry (should match token expiry)

    Returns:
        True if successfully added, False otherwise
    """
    try:
        redis_client = current_app.redis
        if redis_client:
            redis_client.setex(f"jwt_blocklist:{jti}", expires_in_seconds, 'revoked')
            return True
    except Exception as e:
        logger.error(f"Error adding token to blocklist: {e}")
    return False
