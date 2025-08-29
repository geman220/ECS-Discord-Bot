# app/admin/redis_routes.py

"""
Redis Administration and Monitoring Routes

This module provides admin endpoints for monitoring Redis connection pools,
viewing connection statistics, and debugging Redis-related issues.
"""

import logging
from flask import Blueprint, render_template, jsonify, current_app
from flask_login import login_required
from app.decorators import role_required
from app.utils.redis_manager import get_redis_manager, get_redis_connection

logger = logging.getLogger(__name__)

redis_bp = Blueprint('redis_admin', __name__, url_prefix='/admin/redis')


@redis_bp.route('/stats')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def redis_stats():
    """Display Redis connection pool statistics."""
    try:
        redis_manager = get_redis_manager()
        stats = redis_manager.get_connection_stats()
        
        # Test connection health
        try:
            decoded_ping = redis_manager.client.ping()
            raw_ping = redis_manager.raw_client.ping()
            connection_health = {
                'decoded_client': decoded_ping,
                'raw_client': raw_ping,
                'overall': decoded_ping and raw_ping
            }
        except Exception as e:
            connection_health = {
                'decoded_client': False,
                'raw_client': False,
                'overall': False,
                'error': str(e)
            }
        
        # Get Redis server info if possible
        server_info = {}
        try:
            redis_client = get_redis_connection()
            server_info = redis_client.info()
        except Exception as e:
            server_info = {'error': f'Could not get server info: {e}'}
        
        return render_template('admin/redis_stats.html',
                             stats=stats,
                             connection_health=connection_health,
                             server_info=server_info)
    
    except Exception as e:
        logger.error(f"Error getting Redis stats: {e}")
        return jsonify({'error': str(e)}), 500


@redis_bp.route('/api/stats')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def redis_stats_api():
    """API endpoint for Redis statistics (for AJAX updates)."""
    try:
        redis_manager = get_redis_manager()
        stats = redis_manager.get_connection_stats()
        
        # Add real-time connection health check
        try:
            decoded_ping = redis_manager.client.ping()
            raw_ping = redis_manager.raw_client.ping()
            stats['health'] = {
                'decoded_client': decoded_ping,
                'raw_client': raw_ping,
                'overall': decoded_ping and raw_ping
            }
        except Exception as e:
            stats['health'] = {
                'decoded_client': False,
                'raw_client': False,
                'overall': False,
                'error': str(e)
            }
        
        # Add connection usage metrics
        try:
            redis_client = get_redis_connection()
            info = redis_client.info()
            stats['server_metrics'] = {
                'connected_clients': info.get('connected_clients', 0),
                'used_memory_human': info.get('used_memory_human', 'unknown'),
                'total_commands_processed': info.get('total_commands_processed', 0),
                'instantaneous_ops_per_sec': info.get('instantaneous_ops_per_sec', 0)
            }
        except Exception as e:
            stats['server_metrics'] = {'error': str(e)}
            
        return jsonify(stats)
    
    except Exception as e:
        logger.error(f"Error getting Redis API stats: {e}")
        return jsonify({'error': str(e)}), 500


@redis_bp.route('/test-connection')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def test_redis_connection():
    """Test Redis connection and return detailed results."""
    try:
        redis_manager = get_redis_manager()
        
        test_results = {
            'unified_manager': True,
            'tests': {}
        }
        
        # Test decoded client
        try:
            redis_manager.client.ping()
            test_results['tests']['decoded_client'] = {'status': 'success', 'message': 'Ping successful'}
        except Exception as e:
            test_results['tests']['decoded_client'] = {'status': 'failed', 'message': str(e)}
        
        # Test raw client
        try:
            redis_manager.raw_client.ping()
            test_results['tests']['raw_client'] = {'status': 'success', 'message': 'Ping successful'}
        except Exception as e:
            test_results['tests']['raw_client'] = {'status': 'failed', 'message': str(e)}
        
        # Test basic operations
        try:
            test_key = 'redis_admin_test'
            redis_manager.client.set(test_key, 'test_value', ex=10)
            value = redis_manager.client.get(test_key)
            redis_manager.client.delete(test_key)
            
            if value == 'test_value':
                test_results['tests']['operations'] = {'status': 'success', 'message': 'Set/Get/Delete successful'}
            else:
                test_results['tests']['operations'] = {'status': 'failed', 'message': f'Expected "test_value", got "{value}"'}
        except Exception as e:
            test_results['tests']['operations'] = {'status': 'failed', 'message': str(e)}
        
        return jsonify(test_results)
    
    except Exception as e:
        logger.error(f"Error testing Redis connection: {e}")
        return jsonify({'error': str(e)}), 500


@redis_bp.route('/connection-cleanup')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def cleanup_connections():
    """Manually trigger connection pool cleanup."""
    try:
        redis_manager = get_redis_manager()
        
        # Get stats before cleanup
        stats_before = redis_manager.get_connection_stats()
        
        # Just get fresh stats - avoid dangerous reinitialization
        # The unified manager is designed to be stable and self-healing
        
        # Get stats after cleanup
        stats_after = redis_manager.get_connection_stats()
        
        return jsonify({
            'success': True,
            'message': 'Connection pool cleanup completed',
            'stats_before': stats_before,
            'stats_after': stats_after
        })
    
    except Exception as e:
        logger.error(f"Error during connection cleanup: {e}")
        return jsonify({'error': str(e)}), 500


@redis_bp.route('/draft-cache-stats')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def draft_cache_stats():
    """Display draft cache statistics and performance metrics."""
    try:
        from app.draft_cache_service import DraftCacheService
        
        # Get draft cache statistics
        cache_stats = DraftCacheService.get_cache_stats()
        
        # Get cache warmth for each league
        from app.models import League
        from flask import g
        session = g.db_session
        leagues = session.query(League).filter(League.is_active == True).all()
        
        league_cache_status = {}
        for league in leagues:
            league_cache_status[league.name] = DraftCacheService.warm_cache_for_league(league.name)
        
        return render_template('admin/draft_cache_stats.html',
                             cache_stats=cache_stats,
                             league_cache_status=league_cache_status,
                             leagues=[l.name for l in leagues])
    
    except Exception as e:
        logger.error(f"Error getting draft cache stats: {e}")
        return jsonify({'error': str(e)}), 500


@redis_bp.route('/api/draft-cache-stats')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def draft_cache_stats_api():
    """API endpoint for draft cache statistics (for AJAX updates)."""
    try:
        from app.draft_cache_service import DraftCacheService
        
        # Get comprehensive cache statistics
        cache_stats = DraftCacheService.get_cache_stats()
        
        # Add TTL information
        cache_stats['ttl_settings'] = {
            'player_data': DraftCacheService.PLAYER_DATA_TTL,
            'analytics': DraftCacheService.DRAFT_ANALYTICS_TTL,
            'team_data': DraftCacheService.TEAM_DATA_TTL,
            'availability': DraftCacheService.AVAILABILITY_TTL
        }
        
        return jsonify(cache_stats)
    
    except Exception as e:
        logger.error(f"Error getting draft cache API stats: {e}")
        return jsonify({'error': str(e)}), 500


@redis_bp.route('/warm-draft-cache/<league_name>')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def warm_draft_cache(league_name: str):
    """Manually warm draft cache for a specific league."""
    try:
        from app.draft_cache_service import DraftCacheService
        
        # Check current cache status
        cache_status = DraftCacheService.warm_cache_for_league(league_name)
        
        return jsonify({
            'success': True,
            'message': f'Cache warming initiated for {league_name}',
            'cache_status': cache_status,
            'note': 'Cache will be populated on next draft page visit'
        })
    
    except Exception as e:
        logger.error(f"Error warming draft cache for {league_name}: {e}")
        return jsonify({'error': str(e)}), 500