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
        
        # Get pool stats if available
        pool_stats = {}
        if hasattr(db.engine.pool, 'size'):
            pool_stats['pool_size'] = db.engine.pool.size()
            pool_stats['checked_in'] = db.engine.pool.checkedin()
            pool_stats['checked_out'] = db.engine.pool.checkedout()
            pool_stats['overflow'] = getattr(db.engine.pool, 'overflow', 0)
        
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