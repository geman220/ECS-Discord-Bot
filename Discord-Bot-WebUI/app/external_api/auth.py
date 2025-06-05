# app/external_api/auth.py

"""
Authentication utilities for external API endpoints.
"""

import logging
from functools import wraps

from flask import request, jsonify, current_app

logger = logging.getLogger(__name__)


def api_key_required(f):
    """Decorator to require API key authentication for external endpoints."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key') or request.args.get('api_key')
        
        if not api_key:
            return jsonify({
                'error': 'API key required',
                'message': 'Please provide an API key in X-API-Key header or api_key parameter'
            }), 401
        
        # Get valid API keys from config
        valid_keys = current_app.config.get('EXTERNAL_API_KEYS', [])
        
        if api_key not in valid_keys:
            logger.warning(f"Invalid API key attempted: {api_key[:8]}...")
            return jsonify({
                'error': 'Invalid API key',
                'message': 'The provided API key is not valid'
            }), 401
        
        return f(*args, **kwargs)
    
    return decorated_function