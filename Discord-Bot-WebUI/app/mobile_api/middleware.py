# app/api/middleware.py

"""
API Middleware

Common middleware functions for the mobile API including:
- API key validation
- IP restriction
- Request logging
- Authentication helpers
"""

import logging
import ipaddress
from functools import wraps

from flask import request, current_app, jsonify, g, Blueprint
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity

logger = logging.getLogger(__name__)


def register_api_middleware(blueprint: Blueprint):
    """
    Register middleware functions with the API blueprint.

    Args:
        blueprint: The Flask blueprint to register middleware with
    """

    @blueprint.before_request
    def validate_api_access():
        """
        Restrict API access to allowed hosts and mobile devices.

        Allows access from:
        1. Mobile devices with valid API key (from any IP)
        2. Specific development hosts
        3. IP ranges using CIDR notation (from config)
        """
        # Check for API key in headers (for mobile app)
        api_key = request.headers.get('X-API-Key')
        expected_key = current_app.config.get('MOBILE_API_KEY', 'ecs-soccer-mobile-key')
        if api_key and api_key == expected_key:
            return None

        # Development hosts that are always allowed
        allowed_dev_hosts = [
            '127.0.0.1:5000',
            'localhost:5000',
            'webui:5000',
            '192.168.1.112:5000',
            '10.0.2.2:5000',  # Android emulator default
            'portal.ecsfc.com',  # Production domain
        ]

        # Check if host is in the allowed development hosts list
        if request.host in allowed_dev_hosts:
            return None

        # Get allowed networks from configuration
        allowed_networks_str = current_app.config.get('MOBILE_APP_ALLOWED_NETWORKS', '')
        allowed_networks = [net.strip() for net in allowed_networks_str.split(',') if net.strip()]

        # Check IP ranges (CIDR notation)
        if allowed_networks:
            client_ip = request.host.split(':')[0]  # Remove port if present
            for network_cidr in allowed_networks:
                try:
                    network = ipaddress.ip_network(network_cidr)
                    if ipaddress.ip_address(client_ip) in network:
                        return None
                except (ValueError, ipaddress.AddressValueError):
                    logger.warning(f"Invalid network CIDR in config: {network_cidr}")
                    continue

        # Access denied
        logger.warning(f"API access denied for host: {request.host}")
        return jsonify({'error': 'Access Denied'}), 403


def jwt_or_discord_auth_required(f):
    """
    Decorator that allows either JWT authentication or Discord bot authentication.

    For Discord bot requests, expects X-Discord-User header with Discord user ID.
    For regular requests, requires valid JWT token.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check for Discord bot authentication first
        discord_user_id = request.headers.get('X-Discord-User')
        if discord_user_id:
            try:
                g.current_user_id = discord_user_id
                g.auth_source = 'discord'
                return f(*args, **kwargs)
            except Exception as e:
                logger.error(f"Error in Discord bot authentication: {str(e)}")
                return jsonify({'error': 'Authentication error'}), 401
        else:
            # Use standard JWT authentication
            try:
                verify_jwt_in_request()
                g.current_user_id = int(get_jwt_identity())
                g.auth_source = 'jwt'
                return f(*args, **kwargs)
            except Exception as e:
                logger.error(f"JWT authentication failed: {str(e)}")
                return jsonify({'error': 'Authentication required'}), 401

    return decorated_function


def get_current_user_id() -> int:
    """
    Get the current authenticated user ID from the request context.

    Returns:
        int: The user ID if authenticated, None otherwise
    """
    return getattr(g, 'current_user_id', None)
