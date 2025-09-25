# app/utils/mobile_auth.py

"""
Mobile API Authentication Utilities

Provides authentication decorators and utilities specifically for mobile API endpoints
including API key validation, rate limiting, and JWT verification.
"""

import functools
import time
from collections import defaultdict
from datetime import datetime, timedelta
from flask import request, jsonify, current_app, g
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity
import logging

logger = logging.getLogger(__name__)

# Simple in-memory rate limiting (in production, use Redis)
rate_limit_store = defaultdict(list)

# Mobile API configuration
MOBILE_API_KEYS = {
    'ecs-soccer-mobile-key': {
        'name': 'ECS Soccer Mobile App',
        'permissions': ['analytics', 'logging'],
        'rate_limit': 100  # requests per minute
    }
}


def validate_mobile_api_key(api_key):
    """
    Validate mobile API key.
    
    Args:
        api_key (str): API key from X-API-Key header
        
    Returns:
        dict: API key info if valid, None if invalid
    """
    return MOBILE_API_KEYS.get(api_key)


def check_rate_limit(identifier, limit=100, window=60):
    """
    Check if request is within rate limit.
    
    Args:
        identifier (str): Unique identifier (user_id, IP, etc.)
        limit (int): Maximum requests per window
        window (int): Time window in seconds
        
    Returns:
        tuple: (is_allowed: bool, requests_made: int, reset_time: int)
    """
    now = time.time()
    window_start = now - window
    
    # Clean old entries
    rate_limit_store[identifier] = [
        timestamp for timestamp in rate_limit_store[identifier]
        if timestamp > window_start
    ]
    
    requests_made = len(rate_limit_store[identifier])
    
    if requests_made < limit:
        rate_limit_store[identifier].append(now)
        return True, requests_made + 1, int(now + window)
    else:
        return False, requests_made, int(now + window)


def api_key_required(f):
    """
    Simple decorator that only validates the mobile API key.
    Use this when JWT validation is handled separately with @jwt_required().
    """
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            # Validate API Key
            api_key = request.headers.get('X-API-Key')
            if not api_key:
                logger.warning(f"Missing API key for mobile endpoint: {request.endpoint}")
                return jsonify({
                    'error': 'Missing API key',
                    'code': 'MISSING_API_KEY'
                }), 401

            api_key_info = validate_mobile_api_key(api_key)
            if not api_key_info:
                logger.warning(f"Invalid API key for mobile endpoint: {request.endpoint}")
                return jsonify({
                    'error': 'Invalid API key',
                    'code': 'INVALID_API_KEY'
                }), 401

            # Store API key info for use in endpoint
            g.mobile_api_key_info = api_key_info

            return f(*args, **kwargs)

        except Exception as e:
            logger.error(f"API key validation error: {str(e)}", exc_info=True)
            return jsonify({
                'error': 'API key validation error',
                'code': 'API_KEY_ERROR'
            }), 500

    return decorated_function


def mobile_api_auth_required(require_permissions=None):
    """
    Decorator for mobile API endpoints requiring authentication.
    
    Validates:
    1. JWT token for user authentication
    2. Mobile API key for app authentication
    3. Rate limiting per user
    
    Args:
        require_permissions (list): Required permissions for this endpoint
    """
    def decorator(f):
        @functools.wraps(f)
        def decorated_function(*args, **kwargs):
            try:
                # 1. Validate API Key
                api_key = request.headers.get('X-API-Key')
                if not api_key:
                    logger.warning(f"Missing API key for mobile endpoint: {request.endpoint}")
                    return jsonify({
                        'error': 'Missing API key',
                        'code': 'MISSING_API_KEY'
                    }), 401
                
                api_key_info = validate_mobile_api_key(api_key)
                if not api_key_info:
                    logger.warning(f"Invalid API key for mobile endpoint: {request.endpoint}")
                    return jsonify({
                        'error': 'Invalid API key',
                        'code': 'INVALID_API_KEY'
                    }), 401
                
                # Store API key info for use in endpoint
                g.mobile_api_key_info = api_key_info
                
                # 2. Validate JWT Token
                try:
                    verify_jwt_in_request()
                    user_id = int(get_jwt_identity())
                    g.current_user_id = user_id
                except Exception as e:
                    logger.warning(f"JWT validation failed for mobile endpoint: {str(e)}")
                    return jsonify({
                        'error': 'Invalid or expired token',
                        'code': 'INVALID_TOKEN'
                    }), 401
                
                # 3. Check Permissions
                if require_permissions:
                    api_permissions = api_key_info.get('permissions', [])
                    missing_permissions = set(require_permissions) - set(api_permissions)
                    if missing_permissions:
                        logger.warning(f"Insufficient permissions for mobile endpoint: missing {missing_permissions}")
                        return jsonify({
                            'error': f'Insufficient permissions: {", ".join(missing_permissions)}',
                            'code': 'INSUFFICIENT_PERMISSIONS'
                        }), 403
                
                # 4. Rate Limiting
                rate_limit = api_key_info.get('rate_limit', 100)
                identifier = f"mobile_{api_key}_{user_id}"
                is_allowed, requests_made, reset_time = check_rate_limit(identifier, rate_limit)
                
                if not is_allowed:
                    logger.warning(f"Rate limit exceeded for user {user_id}: {requests_made}/{rate_limit}")
                    return jsonify({
                        'error': 'Rate limit exceeded',
                        'code': 'RATE_LIMIT_EXCEEDED',
                        'limit': rate_limit,
                        'requests_made': requests_made,
                        'reset_time': reset_time
                    }), 429
                
                # Add rate limit info to response headers
                @functools.wraps(f)
                def add_rate_limit_headers(response):
                    if hasattr(response, 'headers'):
                        response.headers['X-RateLimit-Limit'] = str(rate_limit)
                        response.headers['X-RateLimit-Remaining'] = str(rate_limit - requests_made)
                        response.headers['X-RateLimit-Reset'] = str(reset_time)
                    return response
                
                # Execute the endpoint
                result = f(*args, **kwargs)
                
                # Add headers if result is a Flask response
                if hasattr(result, 'headers'):
                    result.headers['X-RateLimit-Limit'] = str(rate_limit)
                    result.headers['X-RateLimit-Remaining'] = str(rate_limit - requests_made)
                    result.headers['X-RateLimit-Reset'] = str(reset_time)
                
                return result
                
            except Exception as e:
                logger.error(f"Mobile API auth error: {str(e)}", exc_info=True)
                return jsonify({
                    'error': 'Authentication service error',
                    'code': 'AUTH_SERVICE_ERROR'
                }), 500
        
        return decorated_function
    return decorator


def log_mobile_api_request():
    """
    Log mobile API request for monitoring and debugging.
    Call this at the beginning of mobile API endpoints.
    """
    try:
        api_key = request.headers.get('X-API-Key', 'unknown')
        user_id = getattr(g, 'current_user_id', 'unknown')
        endpoint = request.endpoint
        method = request.method
        
        logger.info(f"Mobile API request: {method} {endpoint} | User: {user_id} | API Key: {api_key[:10]}...")
        
    except Exception as e:
        logger.error(f"Failed to log mobile API request: {str(e)}")


def get_request_context():
    """
    Get request context for logging and analytics.
    
    Returns:
        dict: Request context information
    """
    return {
        'ip_address': request.remote_addr,
        'user_agent': request.headers.get('User-Agent'),
        'endpoint': request.endpoint,
        'method': request.method,
        'timestamp': datetime.utcnow().isoformat(),
        'api_key_name': getattr(g, 'mobile_api_key_info', {}).get('name'),
        'user_id': getattr(g, 'current_user_id')
    }