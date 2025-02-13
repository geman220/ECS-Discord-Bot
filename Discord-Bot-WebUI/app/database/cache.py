# app/database/cache.py

"""
Caching utilities for the application.

This module provides helper functions to initialize caching (using Redis via Flask-Caching),
decorate functions for static file caching, generate cache keys, and manage cached season data.
"""

from flask_caching import Cache
from flask import current_app
from app.models import Season

cache = Cache()


def init_cache(app):
    """
    Initialize the cache for the Flask app using Redis as the backend.

    :param app: The Flask application instance.
    """
    cache_config = {
        'CACHE_TYPE': 'redis',
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


def cache_static_file(timeout=86400):
    """
    Decorator for caching static file responses.

    :param timeout: Cache timeout in seconds (default: 24 hours).
    :return: Decorated function with caching enabled.
    """
    def decorator(f):
        @cache.memoize(timeout=timeout)
        def decorated_function(*args, **kwargs):
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def generate_cache_key(*args, **kwargs):
    """
    Generate a consistent cache key from positional and keyword arguments.

    :return: A string key created by joining the string representations of args and sorted kwargs.
    """
    key_parts = [str(arg) for arg in args]
    key_parts.extend(f"{k}:{v}" for k, v in sorted(kwargs.items()))
    return ":".join(key_parts)


def invalidate_static_cache(pattern=None):
    """
    Invalidate cache entries for static files.

    :param pattern: If provided, only keys matching "static:{pattern}:*" are invalidated;
                    otherwise, all static cache keys are removed.
    """
    if pattern:
        cache.delete_pattern(f"static:{pattern}:*")
    else:
        cache.delete_pattern("static:*")


@cache.memoize(timeout=300)
def get_current_seasons():
    """
    Retrieve and cache current season data.

    Queries the database for the current 'Pub League' and 'ECS FC' seasons,
    caching the result for 5 minutes.

    :return: A dictionary with keys 'Pub League' and 'ECS FC' mapping to the current Season instances.
    """
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
    """
    Clear the cached season data.

    This function deletes the memoized result of get_current_seasons.
    """
    cache.delete_memoized(get_current_seasons)