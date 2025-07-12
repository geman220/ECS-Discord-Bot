# app/cache_admin_routes.py

"""
Cache Administration Routes

Provides admin interface for monitoring and managing Redis cache performance.
Includes cache statistics, manual cache warming, and cache invalidation controls.
"""

from flask import Blueprint, render_template, jsonify, request, flash, redirect, url_for
from flask_login import login_required
from app.decorators import role_required
from app.performance_cache import get_cache_stats, warm_critical_caches, invalidate_team_cache, invalidate_player_cache
from app.utils.redis_manager import get_redis_connection
import logging

logger = logging.getLogger(__name__)

cache_admin_bp = Blueprint('cache_admin', __name__, url_prefix='/admin/cache')

@cache_admin_bp.route('/stats')
@login_required
@role_required(['Global Admin'])
def cache_stats():
    """Display cache statistics and performance metrics."""
    try:
        stats = get_cache_stats()
        return render_template('admin/cache_stats.html', 
                             title='Cache Statistics',
                             stats=stats)
    except Exception as e:
        logger.error(f"Error getting cache stats: {e}")
        flash('Error retrieving cache statistics', 'error')
        return redirect(url_for('cache_admin.cache_stats'))

@cache_admin_bp.route('/stats/api')
@login_required
@role_required(['Global Admin'])
def cache_stats_api():
    """API endpoint for cache statistics (for AJAX updates)."""
    try:
        stats = get_cache_stats()
        return jsonify(stats)
    except Exception as e:
        logger.error(f"Error getting cache stats: {e}")
        return jsonify({'error': str(e)}), 500

@cache_admin_bp.route('/warm')
@login_required
@role_required(['Global Admin'])
def warm_cache():
    """Manually trigger cache warming for critical data."""
    try:
        warm_critical_caches()
        flash('Cache warming initiated successfully', 'success')
    except Exception as e:
        logger.error(f"Error warming cache: {e}")
        flash(f'Cache warming failed: {str(e)}', 'error')
    
    return redirect(url_for('cache_admin.cache_stats'))

@cache_admin_bp.route('/invalidate/team/<int:team_id>')
@login_required
@role_required(['Global Admin'])
def invalidate_team(team_id):
    """Invalidate cache entries for a specific team."""
    try:
        invalidate_team_cache(team_id)
        flash(f'Cache invalidated for team {team_id}', 'success')
    except Exception as e:
        logger.error(f"Error invalidating team cache: {e}")
        flash(f'Cache invalidation failed: {str(e)}', 'error')
    
    return redirect(url_for('cache_admin.cache_stats'))

@cache_admin_bp.route('/invalidate/player/<int:player_id>')
@login_required
@role_required(['Global Admin'])
def invalidate_player(player_id):
    """Invalidate cache entries for a specific player."""
    try:
        invalidate_player_cache(player_id)
        flash(f'Cache invalidated for player {player_id}', 'success')
    except Exception as e:
        logger.error(f"Error invalidating player cache: {e}")
        flash(f'Cache invalidation failed: {str(e)}', 'error')
    
    return redirect(url_for('cache_admin.cache_stats'))

@cache_admin_bp.route('/clear/all')
@login_required
@role_required(['Global Admin'])
def clear_all_cache():
    """Clear all cache entries (use with caution)."""
    try:
        cache_client = get_redis_connection()
        if cache_client:
            # Only clear our application cache keys, not all Redis data
            patterns = ['team_stats:*', 'standings:*', 'player_stats:*', 'matches:*']
            total_deleted = 0
            
            for pattern in patterns:
                keys = cache_client.keys(pattern)
                if keys:
                    cache_client.delete(*keys)
                    total_deleted += len(keys)
            
            flash(f'Cleared {total_deleted} cache entries', 'success')
        else:
            flash('Redis connection not available', 'error')
    
    except Exception as e:
        logger.error(f"Error clearing cache: {e}")
        flash(f'Cache clearing failed: {str(e)}', 'error')
    
    return redirect(url_for('cache_admin.cache_stats'))

@cache_admin_bp.route('/test')
@login_required
@role_required(['Global Admin'])
def test_cache():
    """Test cache functionality with a simple operation."""
    try:
        cache_client = get_redis_connection()
        if not cache_client:
            return jsonify({'error': 'Redis not available'}), 500
        
        # Test set/get operation
        test_key = 'cache_test:admin'
        test_value = 'Cache is working!'
        
        cache_client.setex(test_key, 30, test_value)  # 30 second TTL
        retrieved = cache_client.get(test_key)
        
        if retrieved and retrieved.decode() == test_value:
            cache_client.delete(test_key)  # Clean up
            return jsonify({
                'status': 'success',
                'message': 'Cache is functioning correctly'
            })
        else:
            return jsonify({
                'status': 'error', 
                'message': 'Cache test failed'
            }), 500
    
    except Exception as e:
        logger.error(f"Cache test error: {e}")
        return jsonify({'error': str(e)}), 500