# app/health.py
"""
Health check endpoints for monitoring connection status
"""

from flask import Blueprint, jsonify, g
from sqlalchemy import text
import time
import logging

logger = logging.getLogger(__name__)

health_bp = Blueprint('health', __name__)

@health_bp.route('/health/db')
def database_health():
    """Check database connectivity and basic stats."""
    try:
        session = g.db_session
        start_time = time.time()
        
        # Simple query to test connectivity
        result = session.execute(text("SELECT 1")).scalar()
        query_time = time.time() - start_time
        
        # Get connection count if possible
        try:
            conn_result = session.execute(text("""
                SELECT count(*) as total_connections,
                       count(*) filter (where state = 'active') as active_connections,
                       count(*) filter (where state = 'idle') as idle_connections
                FROM pg_stat_activity 
                WHERE datname = current_database()
            """)).fetchone()
            
            connection_stats = {
                'total': conn_result[0],
                'active': conn_result[1], 
                'idle': conn_result[2]
            }
        except:
            connection_stats = None
        
        return jsonify({
            'status': 'healthy',
            'query_time_ms': round(query_time * 1000, 2),
            'connection_stats': connection_stats,
            'timestamp': time.time()
        })
        
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return jsonify({
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': time.time()
        }), 503

@health_bp.route('/health/pool')
def pool_health():
    """Check connection pool status."""
    try:
        from app.core import db
        
        # Get basic pool info safely
        pool_stats = {}
        pool = db.engine.pool
        
        # Try to get pool statistics safely
        try:
            pool_stats['pool_class'] = pool.__class__.__name__
            
            # These are properties/methods on SQLAlchemy pools
            if hasattr(pool, 'size'):
                size_attr = getattr(pool, 'size')
                pool_stats['pool_size'] = size_attr() if callable(size_attr) else int(size_attr)
            
            if hasattr(pool, 'checkedin'):
                checkedin_attr = getattr(pool, 'checkedin')
                pool_stats['checked_in'] = checkedin_attr() if callable(checkedin_attr) else int(checkedin_attr)
                
            if hasattr(pool, 'checkedout'):
                checkedout_attr = getattr(pool, 'checkedout')  
                pool_stats['checked_out'] = checkedout_attr() if callable(checkedout_attr) else int(checkedout_attr)
                
        except Exception as stats_error:
            pool_stats['stats_error'] = str(stats_error)
        
        return jsonify({
            'status': 'healthy',
            'pool_stats': pool_stats,
            'timestamp': time.time()
        })
        
    except Exception as e:
        logger.error(f"Pool health check failed: {e}")
        return jsonify({
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': time.time()
        }), 503

@health_bp.route('/health')
def overall_health():
    """Quick overall health check."""
    try:
        session = g.db_session
        session.execute(text("SELECT 1"))
        
        return jsonify({
            'status': 'healthy',
            'services': {
                'database': 'up',
                'application': 'up'
            },
            'timestamp': time.time()
        })
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': time.time()
        }), 503