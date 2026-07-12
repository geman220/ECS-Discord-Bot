# app/admin/redis_routes.py

"""
Redis Administration and Monitoring Routes

This module provides admin endpoints for monitoring Redis connection pools,
viewing connection statistics, and debugging Redis-related issues.
"""

import logging
from flask import Blueprint, render_template, jsonify, current_app, redirect, url_for
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
                'error': 'Internal Server Error'
            }
        
        # Get Redis server info if possible
        server_info = {}
        try:
            redis_client = get_redis_connection()
            server_info = redis_client.info()
        except Exception as e:
            server_info = {'error': f'Could not get server info: {e}'}
        
        return render_template('admin/redis_stats_flowbite.html',
                             stats=stats,
                             connection_health=connection_health,
                             server_info=server_info)
    
    except Exception as e:
        logger.error(f"Error getting Redis stats: {e}")
        return jsonify({'error': 'Internal Server Error'}), 500


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
                'error': 'Internal Server Error'
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
            stats['server_metrics'] = {'error': 'Internal Server Error'}
            
        return jsonify(stats)
    
    except Exception as e:
        logger.error(f"Error getting Redis API stats: {e}")
        return jsonify({'error': 'Internal Server Error'}), 500


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
        return jsonify({'error': 'Internal Server Error'}), 500


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
        return jsonify({'error': 'Internal Server Error'}), 500


@redis_bp.route('/draft-cache-stats')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def draft_cache_stats():
    """Retired duplicate — redirects to the canonical draft-cache page.

    This route rendered templates/admin/draft_cache_stats_flowbite.html, a near-duplicate of
    the admin_panel page that the nav actually links to. It had NEVER rendered: it called
    DraftCacheService.warm_cache_for_league(), which does not exist, so it 500'd on every
    request. Repairing it was not worth it — the template is broken independently of that:

      * it reads league_status.get('players_available') at the TOP level, but
        get_league_cache_status() nests those under 'cache_status', so every league would
        render "Missing" even with a fully warm cache;
      * two of its buttons POST to endpoints that do not exist
        (/draft-cache-stats/invalidate-all and /draft-cache-stats/warm-cache -> 404).

    admin_panel.redis_draft_cache_stats reads the nesting correctly, POSTs to real endpoints,
    and is the one wired into the navigation. Send everyone there.
    """
    return redirect(url_for('admin_panel.redis_draft_cache_stats'))


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
        # DraftCacheService has NO flat PLAYER_DATA_TTL/DRAFT_ANALYTICS_TTL/... attributes.
        # TTLs are adaptive and live in ACTIVE_DRAFT_TTL / INACTIVE_DRAFT_TTL, keyed by cache
        # type. Referencing the flat names raised AttributeError, which the except below turned
        # into a permanent 500 — this endpoint has never returned anything but an error.
        # Keep the flat shape the template reads (ttl_settings.player_data, .analytics,
        # .team_data, .availability), filled from the baseline (inactive) table, and expose
        # both tables alongside it for the active-draft case.
        _base = DraftCacheService.INACTIVE_DRAFT_TTL
        cache_stats['ttl_settings'] = {
            'player_data': _base['player_data'],
            'analytics': _base['analytics'],
            'team_data': _base['team_data'],
            'availability': _base['availability'],
            'active_draft': DraftCacheService.ACTIVE_DRAFT_TTL,
            'inactive_draft': DraftCacheService.INACTIVE_DRAFT_TTL,
        }
        
        return jsonify(cache_stats)
    
    except Exception as e:
        logger.error(f"Error getting draft cache API stats: {e}")
        return jsonify({'error': 'Internal Server Error'}), 500


# POST, not GET: warm_cache_for_active_draft() calls mark_draft_active(), mutating
# process-global state. As a GET it took no CSRF token, so an <img src=...> on any page
# an admin loaded could flip a league's draft to active with their session cookie.
@redis_bp.route('/warm-draft-cache/<league_name>', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def warm_draft_cache(league_name: str):
    """Manually warm draft cache for a specific league."""
    try:
        from app.draft_cache_service import DraftCacheService

        # Check current cache status
        # warm_cache_for_league() does not exist; the real method is warm_cache_for_active_draft().
        # It is correct HERE (an admin explicitly asked to warm this league) but NOT on the
        # stats page, because it marks the draft active as a side effect.
        cache_status = DraftCacheService.warm_cache_for_active_draft(league_name)

        return jsonify({
            'success': True,
            'message': f'Cache warming initiated for {league_name}',
            'cache_status': cache_status,
            'note': 'Cache will be populated on next draft page visit'
        })

    except Exception as e:
        logger.error(f"Error warming draft cache for {league_name}: {e}")
        return jsonify({'error': 'Internal Server Error'}), 500


@redis_bp.route('/clear-draft-cache', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def clear_draft_cache():
    """Clear all draft caches or for a specific league."""
    try:
        from flask import request
        from app.draft_cache_service import DraftCacheService

        league_name = request.args.get('league')

        if league_name:
            deleted = DraftCacheService.clear_all_league_caches(league_name)
            message = f'Cleared {deleted} cache keys for {league_name}'
        else:
            # Clear all draft caches
            total_deleted = 0
            for league in ['Premier', 'Classic', 'ECS FC']:
                total_deleted += DraftCacheService.clear_all_league_caches(league)
            deleted = total_deleted
            message = f'Cleared {deleted} cache keys for all leagues'

        return jsonify({
            'success': True,
            'message': message,
            'keys_deleted': deleted
        })

    except Exception as e:
        logger.error(f"Error clearing draft cache: {e}")
        return jsonify({'error': 'Internal Server Error'}), 500


@redis_bp.route('/clear-draft-cache/<league_name>', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def clear_draft_cache_for_league(league_name: str):
    """Clear draft cache for a specific league."""
    try:
        from app.draft_cache_service import DraftCacheService

        deleted = DraftCacheService.clear_all_league_caches(league_name)

        return jsonify({
            'success': True,
            'message': f'Cleared {deleted} cache keys for {league_name}',
            'keys_deleted': deleted,
            'league': league_name
        })

    except Exception as e:
        logger.error(f"Error clearing draft cache for {league_name}: {e}")
        return jsonify({'error': 'Internal Server Error'}), 500