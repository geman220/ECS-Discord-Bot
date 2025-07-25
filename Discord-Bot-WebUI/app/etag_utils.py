"""
ETag utility functions for mobile API endpoints.
Provides efficient caching with 304 Not Modified responses.
"""

import hashlib
import json
from flask import request, jsonify, Response
from typing import Any, Dict, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


def generate_etag(data: Any) -> str:
    """
    Generate ETag hash from response data.
    
    Args:
        data: The data to hash (dict, list, or string)
        
    Returns:
        ETag hash string
    """
    if isinstance(data, (dict, list)):
        # Convert to JSON string with sorted keys for consistent hashing
        data_str = json.dumps(data, sort_keys=True, default=str)
    else:
        data_str = str(data)
    
    # Generate MD5 hash (sufficient for ETags)
    return hashlib.md5(data_str.encode()).hexdigest()


def check_etag_match(etag: str) -> bool:
    """
    Check if client's If-None-Match header matches the provided ETag.
    
    Args:
        etag: The current ETag to compare against
        
    Returns:
        True if ETags match (client has current version)
    """
    client_etag = request.headers.get('If-None-Match', '').strip('"')
    return client_etag == etag


def make_etag_response(data: Any, cache_type: str = 'default', 
                      max_age: int = 3600) -> Response:
    """
    Create response with ETag headers for mobile app caching.
    
    Args:
        data: The response data
        cache_type: Type of cache (match_schedule, team_stats, etc.)
        max_age: Cache duration in seconds
        
    Returns:
        Flask Response object with appropriate headers
    """
    # Generate ETag for the data
    etag = generate_etag(data)
    
    # Check if client has current version
    if check_etag_match(etag):
        # Return 304 Not Modified - no body needed
        response = Response(status=304)
        response.headers['ETag'] = f'"{etag}"'
        response.headers['Cache-Control'] = f'public, max-age={max_age}'
        logger.debug(f"ETag match for {cache_type} - returning 304")
        return response
    
    # Return full response with ETag headers
    response = jsonify(data)
    response.headers['ETag'] = f'"{etag}"'
    response.headers['Cache-Control'] = f'public, max-age={max_age}'
    response.headers['X-Cache-Type'] = cache_type
    
    logger.debug(f"New ETag generated for {cache_type}: {etag}")
    return response


def add_etag_headers(response: Response, data: Any = None, 
                    cache_type: str = 'default', max_age: int = 3600) -> Response:
    """
    Add ETag headers to existing response.
    
    Args:
        response: Flask Response object
        data: Optional data to generate ETag from (uses response data if None)
        cache_type: Type of cache
        max_age: Cache duration in seconds
        
    Returns:
        Response with ETag headers added
    """
    if data is None:
        # Use response data
        data = response.get_data(as_text=True)
    
    etag = generate_etag(data)
    response.headers['ETag'] = f'"{etag}"'
    response.headers['Cache-Control'] = f'public, max-age={max_age}'
    response.headers['X-Cache-Type'] = cache_type
    
    return response


# Cache duration constants (in seconds)
CACHE_DURATIONS = {
    'match_schedule': 604800,    # 7 days
    'match_list': 604800,        # 7 days
    'match_details': 86400,      # 1 day
    'team_roster': 259200,       # 3 days
    'team_stats': 86400,         # 1 day
    'team_list': 259200,         # 3 days
    'player_profile': 3600,      # 1 hour
    'player_stats': 86400,       # 1 day
    'user_profile': 3600,        # 1 hour
}


def get_cache_duration(cache_type: str) -> int:
    """Get appropriate cache duration for the given cache type."""
    return CACHE_DURATIONS.get(cache_type, 3600)  # Default 1 hour


def etag_cached_endpoint(cache_type: str):
    """
    Decorator to add ETag support to endpoints.
    
    Usage:
        @etag_cached_endpoint('match_schedule')
        def get_match_schedule():
            data = generate_schedule_data()
            return data
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            # Get the response data from the endpoint
            result = func(*args, **kwargs)
            
            # Handle different return types
            if isinstance(result, tuple):
                data, status_code = result
            else:
                data = result
                status_code = 200
            
            # Skip ETag for error responses
            if status_code >= 400:
                return jsonify(data), status_code
            
            # Create ETag response
            max_age = get_cache_duration(cache_type)
            return make_etag_response(data, cache_type, max_age)
        
        wrapper.__name__ = func.__name__
        return wrapper
    
    return decorator