# app/database/cache.py

from functools import lru_cache
from sqlalchemy import text
from datetime import timedelta
from flask_caching import Cache
from flask import current_app
from app.models import Season

cache = Cache()

def init_cache(app):
    cache_config = {
        'CACHE_TYPE': 'redis',  # Use Redis for caching
        'CACHE_REDIS_URL': app.config['REDIS_URL'],
        'CACHE_DEFAULT_TIMEOUT': 600,
        'CACHE_KEY_PREFIX': 'ecs_',
        'CACHE_OPTIONS': {
            'CONNECTION_POOL': {
                'max_connections': 20
            }
        }
    }
    cache.init_app(app, config=cache_config)

def cache_static_file(timeout=86400):  # 24 hours
    def decorator(f):
        @cache.memoize(timeout=timeout)
        def decorated_function(*args, **kwargs):
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def generate_cache_key(*args, **kwargs):
    """Generate consistent cache keys"""
    key_parts = [str(arg) for arg in args]
    key_parts.extend(f"{k}:{v}" for k, v in sorted(kwargs.items()))
    return ":".join(key_parts)

def invalidate_static_cache(pattern=None):
    """Invalidate static file cache entries"""
    if pattern:
        cache.delete_pattern(f"static:{pattern}:*")
    else:
        cache.delete_pattern("static:*")

@cache.memoize(timeout=300)
def get_current_seasons():
    """Cache current season data with timeout"""
    app = current_app._get_current_object()
    session = app.SessionLocal()
    try:
        pub_league = session.query(Season).filter_by(
            league_type='Pub League',
            is_current=True
        ).first()

        ecs_fc = session.query(Season).filter_by(
            league_type='ECS FC',
            is_current=True
        ).first()

        return {
            'Pub League': pub_league,
            'ECS FC': ecs_fc
        }
    finally:
        session.close()

def clear_season_cache():
    """Clear season cache on updates"""
    cache.delete_memoized(get_current_seasons)
