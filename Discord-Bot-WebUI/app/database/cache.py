# app/database/cache.py
from functools import lru_cache
from sqlalchemy import text
from datetime import timedelta
from flask_caching import Cache
from flask import current_app

cache = Cache()

def init_cache(app):
    """Initialize caching with app config"""
    cache_config = {
        'CACHE_TYPE': 'simple',
        'CACHE_DEFAULT_TIMEOUT': 300,
        'CACHE_KEY_PREFIX': 'ecs_',
        'CACHE_THRESHOLD': 1000  # Maximum number of items
    }
    cache.init_app(app, config=cache_config)

# Template variable caching
@cache.memoize(timeout=300)
def get_current_seasons():
    """Cache current season data with timeout"""
    from app.models import Season
    with current_app.app_context():
        pub_league = Season.query.filter_by(
            league_type='Pub League', 
            is_current=True
        ).first()
        ecs_fc = Season.query.filter_by(
            league_type='ECS FC', 
            is_current=True
        ).first()
        return {
            'Pub League': pub_league,
            'ECS FC': ecs_fc
        }

def clear_season_cache():
    """Clear season cache on updates"""
    cache.delete_memoized(get_current_seasons)