# app/cache_helpers.py

import json
import logging
from functools import wraps
from flask import current_app, g
from app.utils.redis_manager import get_redis_connection

# Note: We don't create a module-level Redis client to avoid connection leaks

logger = logging.getLogger(__name__)

def cache_db_result(key_prefix, ttl=300):
    """
    Decorator to cache database query results in Redis.
    
    Args:
        key_prefix: Prefix for the cache key
        ttl: Time to live in seconds (default 5 minutes)
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            # Generate cache key
            cache_key = f"{key_prefix}:{':'.join(map(str, args))}"
            
            try:
                # Get a fresh Redis connection for this operation
                redis_client = get_redis_connection()
                
                # Try to get from cache first
                cached_result = redis_client.get(cache_key)
                if cached_result:
                    logger.debug(f"Cache hit for key: {cache_key}")
                    return json.loads(cached_result)
                
                # Cache miss - execute function
                logger.debug(f"Cache miss for key: {cache_key}")
                result = f(*args, **kwargs)
                
                # Store in cache
                if result is not None:
                    redis_client.setex(cache_key, ttl, json.dumps(result, default=str))
                
                return result
                
            except Exception as e:
                logger.warning(f"Cache error for key {cache_key}: {e}")
                # Fallback to direct execution if cache fails
                return f(*args, **kwargs)
        
        return wrapper
    return decorator

@cache_db_result("message_info", ttl=600)  # Cache for 10 minutes
def get_cached_message_info(message_id):
    """
    Cached version of message info lookup.
    This reduces database connections for frequently requested messages.
    """
    from flask import g
    from app.models import ScheduledMessage
    
    session_db = g.db_session
    scheduled_msg = session_db.query(ScheduledMessage).filter(
        (ScheduledMessage.home_message_id == str(message_id)) | 
        (ScheduledMessage.away_message_id == str(message_id))
    ).first()
    
    if not scheduled_msg:
        return None
    
    # Determine message type
    is_home = scheduled_msg.home_message_id == str(message_id)
    message_type = 'home' if is_home else 'away'
    
    # Use the MLS match channel from environment
    import os
    channel_id = os.getenv('MATCH_CHANNEL_ID', '1194316942023077938')
    
    return {
        'channel_id': channel_id,
        'match_id': scheduled_msg.match_id,
        'team_id': os.getenv('TEAM_ID', '9726'),  # Seattle Sounders team ID
        'is_home': is_home,
        'message_type': message_type,
        'match_date': str(scheduled_msg.match.date) if scheduled_msg.match else None,
        'match_time': str(scheduled_msg.match.time) if scheduled_msg.match else None,
        'is_recent_match': False  # Calculate based on your logic
    }