# app/admin_panel/routes/system_infrastructure.py

"""
Admin Panel System Infrastructure Routes

This module contains routes for system infrastructure management:
- System health checks and diagnostics
- Redis connection monitoring and management
- Docker container management
- Twilio configuration testing
"""

import os
import time
import logging
from datetime import datetime, timedelta
from flask import render_template, request, jsonify, flash, redirect, url_for, current_app, g
from flask_login import login_required, current_user
from celery.result import AsyncResult

from .. import admin_panel_bp
from app.decorators import role_required
from app.models.admin_config import AdminAuditLog
from app.sms_helpers import check_sms_config
from app.utils.db_utils import transactional

logger = logging.getLogger(__name__)


# -----------------------------------------------------------
# System Health Routes
# -----------------------------------------------------------

@admin_panel_bp.route('/system/health')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def health_dashboard():
    """System health dashboard with comprehensive health checks."""
    try:
        health_status = _check_system_health()

        # Get additional diagnostics
        diagnostics = {
            'timestamp': datetime.now().isoformat(),
            'environment': current_app.config.get('ENV', 'production'),
            'debug_mode': current_app.debug
        }

        return render_template('admin_panel/system/health_dashboard_flowbite.html',
                             health_status=health_status,
                             diagnostics=diagnostics)
    except Exception as e:
        logger.error(f"Error loading health dashboard: {e}")
        flash('Health dashboard unavailable. Check system connectivity.', 'error')
        return redirect(url_for('admin_panel.system_monitoring'))


@admin_panel_bp.route('/system/health/api')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def health_check_api():
    """API endpoint for system health check."""
    try:
        health_status = _check_system_health()
        return jsonify(health_status)
    except Exception as e:
        logger.error(f"Error in health check API: {e}")
        return jsonify({
            'status': 'error',
            'message': f'Health check failed: {str(e)}',
            'timestamp': datetime.now().isoformat()
        }), 500


@admin_panel_bp.route('/system/health/task-status')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def task_status_api():
    """API endpoint for task status monitoring."""
    try:
        from app.utils.task_monitor import TaskMonitor

        monitor = TaskMonitor()
        stats = monitor.get_task_stats(time_window=3600)  # Last hour
        zombie_tasks = monitor.detect_zombie_tasks()

        return jsonify({
            'status': 'success',
            'stats': stats,
            'zombie_tasks': zombie_tasks,
            'zombie_count': len(zombie_tasks),
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Error getting task status: {e}")
        return jsonify({
            'status': 'error',
            'message': f'Failed to retrieve task status: {str(e)}',
            'timestamp': datetime.now().isoformat()
        }), 500


@admin_panel_bp.route('/system/health/task/<task_id>')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def check_specific_task(task_id):
    """Check the detailed status of a specific task."""
    try:
        from app.utils.task_monitor import get_task_info
        task_info = get_task_info(task_id)
        return jsonify(task_info)
    except Exception as e:
        logger.error(f"Error checking task {task_id}: {e}")
        return jsonify({
            'status': 'error',
            'task_id': task_id,
            'message': f'Failed to get task info: {str(e)}',
            'timestamp': datetime.now().isoformat()
        }), 500


@admin_panel_bp.route('/system/health/twilio-test')
@login_required
@role_required(['Global Admin'])
def test_twilio_config():
    """Test the Twilio configuration without sending SMS."""
    try:
        from twilio.rest import Client

        result = {
            'config_check': check_sms_config(),
            'environment_vars': {},
            'auth_check': {},
            'connection_test': {'status': 'UNKNOWN'}
        }

        # Check environment variables (hide actual values)
        for key in os.environ:
            if 'TWILIO' in key or 'TEXTMAGIC' in key:
                result['environment_vars'][key] = "PRESENT"

        twilio_sid = current_app.config.get('TWILIO_SID') or current_app.config.get('TWILIO_ACCOUNT_SID')
        twilio_auth_token = current_app.config.get('TWILIO_AUTH_TOKEN')

        if twilio_sid and twilio_auth_token:
            result['auth_check']['sid_length'] = len(twilio_sid)
            result['auth_check']['token_length'] = len(twilio_auth_token)
            result['auth_check']['sid_starts_with'] = twilio_sid[:2] if len(twilio_sid) >= 2 else ""

            # Check if token could be valid Base64
            try:
                is_valid_base64 = all(c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/='
                                    for c in twilio_auth_token)
                result['auth_check']['valid_token_format'] = is_valid_base64
            except Exception:
                result['auth_check']['valid_token_format'] = False

            # Test actual connection
            try:
                raw_auth_token = os.environ.get('TWILIO_AUTH_TOKEN')
                result['auth_check']['token_has_whitespace'] = any(c.isspace() for c in twilio_auth_token)
                cleaned_token = twilio_auth_token.strip()

                client = Client(twilio_sid, cleaned_token)
                account = client.api.accounts(twilio_sid).fetch()
                result['connection_test'] = {
                    'status': 'SUCCESS',
                    'account_status': account.status,
                    'account_type': account.type
                }
            except Exception as e:
                result['connection_test'] = {
                    'status': 'FAILED',
                    'message': str(e)
                }
        else:
            result['auth_check']['sid_present'] = bool(twilio_sid)
            result['auth_check']['token_present'] = bool(twilio_auth_token)
            result['connection_test'] = {
                'status': 'FAILED',
                'message': 'Missing Twilio credentials'
            }

        # Log the test
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='twilio_config_test',
            resource_type='system',
            resource_id='twilio',
            new_value=f"Status: {result['connection_test']['status']}",
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify(result)
    except Exception as e:
        logger.error(f"Error testing Twilio config: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


# -----------------------------------------------------------
# Redis Management Routes
# -----------------------------------------------------------

@admin_panel_bp.route('/system/redis')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def redis_management():
    """Redis connection management dashboard."""
    try:
        from app.utils.redis_manager import get_redis_manager, get_redis_connection

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

        # Get Redis server info
        server_info = {}
        try:
            redis_client = get_redis_connection()
            server_info = redis_client.info()
        except Exception as e:
            server_info = {'error': f'Could not get server info: {e}'}

        return render_template('admin_panel/system/redis_management_flowbite.html',
                             stats=stats,
                             connection_health=connection_health,
                             server_info=server_info)
    except Exception as e:
        logger.error(f"Error loading Redis management: {e}")
        flash('Redis management unavailable. Check Redis connectivity.', 'error')
        return redirect(url_for('admin_panel.system_monitoring'))


@admin_panel_bp.route('/system/redis/api/stats')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def redis_stats_api():
    """API endpoint for Redis statistics."""
    try:
        from app.utils.redis_manager import get_redis_manager, get_redis_connection

        redis_manager = get_redis_manager()
        stats = redis_manager.get_connection_stats()

        # Add health check
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

        # Add server metrics
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


@admin_panel_bp.route('/system/redis/test-connection')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def redis_test_connection():
    """Test Redis connection and return detailed results."""
    try:
        from app.utils.redis_manager import get_redis_manager

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

        # Log the test
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='redis_connection_test',
            resource_type='system',
            resource_id='redis',
            new_value=f"Tests: {sum(1 for t in test_results['tests'].values() if t['status'] == 'success')}/{len(test_results['tests'])} passed",
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify(test_results)
    except Exception as e:
        logger.error(f"Error testing Redis connection: {e}")
        return jsonify({'error': str(e)}), 500


@admin_panel_bp.route('/system/redis/connection-cleanup', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def redis_cleanup_connections():
    """Trigger connection pool cleanup."""
    try:
        from app.utils.redis_manager import get_redis_manager

        redis_manager = get_redis_manager()
        stats_before = redis_manager.get_connection_stats()
        stats_after = redis_manager.get_connection_stats()

        # Log the cleanup action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='redis_connection_cleanup',
            resource_type='system',
            resource_id='redis',
            new_value='Connection cleanup completed',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({
            'success': True,
            'message': 'Connection pool cleanup completed',
            'stats_before': stats_before,
            'stats_after': stats_after
        })
    except Exception as e:
        logger.error(f"Error during connection cleanup: {e}")
        return jsonify({'error': str(e)}), 500


@admin_panel_bp.route('/system/redis/pool-status')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def redis_pool_status():
    """Get detailed Redis connection pool status."""
    try:
        from app.utils.redis_manager import get_redis_manager
        from app.utils.redis_monitor import get_monitor

        redis_manager = get_redis_manager()
        main_pool_stats = redis_manager.get_connection_stats()

        # Get session pool stats if available
        session_pool_stats = {}
        if hasattr(current_app, 'session_redis'):
            monitor = get_monitor()
            session_pool_stats = monitor._get_session_pool_stats()

        pool_status = {
            'status': 'success',
            'timestamp': datetime.now().isoformat(),
            'pools': {
                'main_redis': main_pool_stats,
                'session_redis': session_pool_stats
            }
        }

        # Add health assessment
        main_util = main_pool_stats.get('utilization_percent', 0)
        session_util = session_pool_stats.get('utilization_percent', 0)

        if main_util > 90 or session_util > 90:
            pool_status['health'] = 'critical'
            pool_status['recommendation'] = 'Connection pools are near capacity. Consider restarting the application.'
        elif main_util > 75 or session_util > 75:
            pool_status['health'] = 'warning'
            pool_status['recommendation'] = 'Monitor connection usage closely.'
        else:
            pool_status['health'] = 'healthy'

        return jsonify(pool_status)
    except Exception as e:
        logger.error(f"Error getting Redis pool status: {e}")
        return jsonify({
            'status': 'error',
            'message': f'Failed to get Redis pool status: {str(e)}',
            'timestamp': datetime.now().isoformat()
        }), 500


@admin_panel_bp.route('/system/redis/draft-cache')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def redis_draft_cache_stats():
    """Display draft cache statistics."""
    try:
        from app.draft_cache_service import DraftCacheService
        from app.models import League, Season

        cache_stats = DraftCacheService.get_cache_stats()

        # Get cache warmth for leagues in current season
        session = g.db_session
        leagues = session.query(League).join(Season).filter(Season.is_current == True).all()

        league_cache_status = {}
        for league in leagues:
            league_cache_status[league.name] = DraftCacheService.warm_cache_for_league(league.name)

        return render_template('admin_panel/system/draft_cache_stats_flowbite.html',
                             cache_stats=cache_stats,
                             league_cache_status=league_cache_status,
                             leagues=[l.name for l in leagues])
    except Exception as e:
        logger.error(f"Error getting draft cache stats: {e}")
        flash('Draft cache statistics unavailable.', 'error')
        return redirect(url_for('admin_panel.redis_management'))


@admin_panel_bp.route('/system/redis/draft-cache/api')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def redis_draft_cache_api():
    """API endpoint for draft cache statistics."""
    try:
        from app.draft_cache_service import DraftCacheService

        cache_stats = DraftCacheService.get_cache_stats()
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


@admin_panel_bp.route('/system/redis/warm-draft-cache/<league_name>', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def redis_warm_draft_cache(league_name):
    """Manually warm draft cache for a specific league."""
    try:
        from app.draft_cache_service import DraftCacheService

        cache_status = DraftCacheService.warm_cache_for_league(league_name)

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='warm_draft_cache',
            resource_type='system',
            resource_id=f'draft_cache_{league_name}',
            new_value=f'Cache warming initiated for {league_name}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({
            'success': True,
            'message': f'Cache warming initiated for {league_name}',
            'cache_status': cache_status,
            'note': 'Cache will be populated on next draft page visit'
        })
    except Exception as e:
        logger.error(f"Error warming draft cache for {league_name}: {e}")
        return jsonify({'error': str(e)}), 500


# -----------------------------------------------------------
# Docker Management Routes
# -----------------------------------------------------------

@admin_panel_bp.route('/system/docker')
@login_required
@role_required(['Global Admin'])
def docker_management():
    """Docker container management dashboard."""
    try:
        from app.admin_helpers import get_container_data

        containers = get_container_data() or []

        return render_template('admin_panel/system/docker_management_flowbite.html',
                             containers=containers)
    except Exception as e:
        logger.error(f"Error loading Docker management: {e}")
        flash('Docker management unavailable. Check Docker connectivity.', 'error')
        return redirect(url_for('admin_panel.system_monitoring'))


@admin_panel_bp.route('/system/docker/status')
@login_required
@role_required(['Global Admin'])
def docker_status_api():
    """Get status information for all Docker containers."""
    try:
        from app.admin_helpers import get_container_data

        containers = get_container_data()
        if containers is None:
            return jsonify({"success": False, "error": "Failed to fetch container data"}), 500
        return jsonify({"success": True, "containers": containers})
    except Exception as e:
        logger.error(f"Error getting Docker status: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@admin_panel_bp.route('/system/docker/container/<container_id>/<action>', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def docker_manage_container(container_id, action):
    """Manage Docker container actions (start, stop, restart)."""
    try:
        from app.admin_helpers import manage_docker_container

        if action not in ['start', 'stop', 'restart']:
            return jsonify({'success': False, 'error': 'Invalid action'}), 400

        success = manage_docker_container(container_id, action)

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action=f'docker_container_{action}',
            resource_type='system',
            resource_id=container_id,
            new_value=f'Container {action} {"successful" if success else "failed"}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        if success:
            return jsonify({'success': True, 'message': f'Container {action} successful'})
        else:
            return jsonify({'success': False, 'error': f'Failed to {action} container'}), 500
    except Exception as e:
        logger.error(f"Error managing container {container_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/system/docker/container/<container_id>/logs')
@login_required
@role_required(['Global Admin'])
def docker_view_logs(container_id):
    """Retrieve logs for a given container."""
    try:
        from app.admin_helpers import get_container_logs

        logs = get_container_logs(container_id)
        if logs is None:
            return jsonify({"error": "Failed to retrieve logs"}), 500
        return jsonify({"logs": logs})
    except Exception as e:
        logger.error(f"Error getting container logs for {container_id}: {e}")
        return jsonify({"error": str(e)}), 500


# -----------------------------------------------------------
# Docker Container Management - JSON Body Routes (for JS compatibility)
# -----------------------------------------------------------

@admin_panel_bp.route('/system/docker/restart', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def docker_restart_container():
    """Restart a Docker container (accepts container_id in JSON body)."""
    try:
        from app.admin_helpers import manage_docker_container

        data = request.get_json() or {}
        container_id = data.get('container_id')

        if not container_id:
            return jsonify({'success': False, 'error': 'container_id is required'}), 400

        success = manage_docker_container(container_id, 'restart')

        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='docker_container_restart',
            resource_type='system',
            resource_id=container_id,
            new_value=f'Container restart {"successful" if success else "failed"}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        if success:
            return jsonify({'success': True, 'message': 'Container restart successful'})
        else:
            return jsonify({'success': False, 'error': 'Failed to restart container'}), 500
    except Exception as e:
        logger.error(f"Error restarting container: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/system/docker/stop', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def docker_stop_container():
    """Stop a Docker container (accepts container_id in JSON body)."""
    try:
        from app.admin_helpers import manage_docker_container

        data = request.get_json() or {}
        container_id = data.get('container_id')

        if not container_id:
            return jsonify({'success': False, 'error': 'container_id is required'}), 400

        success = manage_docker_container(container_id, 'stop')

        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='docker_container_stop',
            resource_type='system',
            resource_id=container_id,
            new_value=f'Container stop {"successful" if success else "failed"}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        if success:
            return jsonify({'success': True, 'message': 'Container stop successful'})
        else:
            return jsonify({'success': False, 'error': 'Failed to stop container'}), 500
    except Exception as e:
        logger.error(f"Error stopping container: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/system/docker/start', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def docker_start_container():
    """Start a Docker container (accepts container_id in JSON body)."""
    try:
        from app.admin_helpers import manage_docker_container

        data = request.get_json() or {}
        container_id = data.get('container_id')

        if not container_id:
            return jsonify({'success': False, 'error': 'container_id is required'}), 400

        success = manage_docker_container(container_id, 'start')

        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='docker_container_start',
            resource_type='system',
            resource_id=container_id,
            new_value=f'Container start {"successful" if success else "failed"}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        if success:
            return jsonify({'success': True, 'message': 'Container start successful'})
        else:
            return jsonify({'success': False, 'error': 'Failed to start container'}), 500
    except Exception as e:
        logger.error(f"Error starting container: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# -----------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------

def _check_system_health():
    """Comprehensive system health check."""
    health_status = {
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'components': {}
    }

    try:
        # Database health check
        try:
            from sqlalchemy import text
            session = g.db_session
            session.execute(text('SELECT 1'))
            health_status['components']['database'] = {
                'status': 'healthy',
                'message': 'Database connection successful'
            }
        except Exception as db_error:
            health_status['components']['database'] = {
                'status': 'unhealthy',
                'message': f'Database error: {str(db_error)}'
            }
            health_status['status'] = 'degraded'

        # Redis health check
        try:
            from app.utils.redis_manager import get_redis_manager
            redis_manager = get_redis_manager()
            redis_manager.client.ping()
            pool_stats = redis_manager.get_connection_stats()

            health_status['components']['redis'] = {
                'status': 'healthy',
                'message': 'Redis connection successful',
                'connection_pool': pool_stats
            }

            # Check session Redis pool if available
            if hasattr(current_app, 'session_redis'):
                try:
                    current_app.session_redis.ping()
                    health_status['components']['redis']['session_pool'] = 'healthy'
                except Exception as session_error:
                    health_status['components']['redis']['session_pool'] = f'unhealthy: {session_error}'
        except Exception as redis_error:
            health_status['components']['redis'] = {
                'status': 'unhealthy',
                'message': f'Redis error: {str(redis_error)}'
            }
            health_status['status'] = 'degraded'

        # Celery health check
        try:
            from app.core import celery
            inspect = celery.control.inspect()
            stats = inspect.stats()
            if stats:
                health_status['components']['celery'] = {
                    'status': 'healthy',
                    'message': f'Celery workers active: {len(stats)}',
                    'worker_count': len(stats)
                }
            else:
                health_status['components']['celery'] = {
                    'status': 'warning',
                    'message': 'No active Celery workers detected'
                }
                if health_status['status'] == 'healthy':
                    health_status['status'] = 'degraded'
        except Exception as celery_error:
            health_status['components']['celery'] = {
                'status': 'unhealthy',
                'message': f'Celery error: {str(celery_error)}'
            }
            health_status['status'] = 'degraded'

        # Docker health check
        try:
            from app.admin_helpers import get_container_data
            containers = get_container_data()
            if containers is not None:
                running = sum(1 for c in containers if c.get('status', '').startswith('running'))
                health_status['components']['docker'] = {
                    'status': 'healthy',
                    'message': f'{running}/{len(containers)} containers running',
                    'container_count': len(containers),
                    'running_count': running
                }
            else:
                health_status['components']['docker'] = {
                    'status': 'warning',
                    'message': 'Docker not available or no containers'
                }
        except Exception as docker_error:
            health_status['components']['docker'] = {
                'status': 'warning',
                'message': f'Docker check skipped: {str(docker_error)}'
            }

    except Exception as e:
        health_status = {
            'status': 'unhealthy',
            'message': f'Health check failed: {str(e)}',
            'timestamp': datetime.now().isoformat()
        }

    return health_status


# -----------------------------------------------------------
# Security Dashboard Integration
# -----------------------------------------------------------

@admin_panel_bp.route('/system/security')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def security_dashboard():
    """
    Integrated security dashboard within Admin Panel.

    Shows security status, threat monitoring, IP bans, and security configuration.
    """
    # Log the access
    AdminAuditLog.log_action(
        user_id=current_user.id,
        action='access_security_dashboard',
        resource_type='system',
        resource_id='security',
        new_value='Accessed security dashboard via Admin Panel',
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent')
    )

    try:
        # Get current security status
        security_middleware = None
        if hasattr(current_app, 'security_middleware'):
            security_middleware = current_app.security_middleware

        # Get comprehensive security stats
        stats = {
            'security_features': {
                'rate_limiting': True,
                'csrf_protection': current_app.config.get('WTF_CSRF_ENABLED', False),
                'session_security': current_app.config.get('SESSION_COOKIE_SECURE', False),
                'security_headers': True,
                'attack_detection': security_middleware is not None,
                'auto_ban': current_app.config.get('SECURITY_AUTO_BAN_ENABLED', True)
            },
            'auto_ban_config': {
                'enabled': current_app.config.get('SECURITY_AUTO_BAN_ENABLED', True),
                'attack_threshold': current_app.config.get('SECURITY_AUTO_BAN_ATTACK_THRESHOLD', 3),
                'rate_threshold': current_app.config.get('SECURITY_AUTO_BAN_RATE_THRESHOLD', 500),
                'duration_hours': current_app.config.get('SECURITY_AUTO_BAN_DURATION_HOURS', 1),
                'escalation_enabled': current_app.config.get('SECURITY_AUTO_BAN_ESCALATION_ENABLED', True),
                'max_duration_hours': current_app.config.get('SECURITY_AUTO_BAN_MAX_DURATION_HOURS', 168)
            },
            'redis_status': 'unknown',
            'total_monitored_ips': 0,
            'total_blacklisted_ips': 0,
            'total_attack_attempts': 0,
            'unique_attackers': 0,
            'monitored_ips': []
        }

        # Check Redis connectivity
        try:
            if hasattr(current_app, 'redis') and current_app.redis:
                current_app.redis.ping()
                stats['redis_status'] = 'connected'
        except Exception:
            stats['redis_status'] = 'disconnected'

        # Helper function to check if IP is private
        def is_private_ip(ip):
            try:
                import ipaddress
                ip_obj = ipaddress.ip_address(ip)
                return ip_obj.is_private
            except:
                return False

        # Get security middleware stats and database bans
        blacklisted_ips = []
        try:
            # Get database bans
            from app.models import IPBan
            db_bans = IPBan.get_active_bans()

            for ban in db_bans:
                if not is_private_ip(ban.ip_address):
                    blacklisted_ips.append({
                        'ip': ban.ip_address,
                        'expires_at': ban.expires_at or datetime.utcnow() + timedelta(days=365),
                        'time_remaining': ban.time_remaining or 999999999,
                        'reason': ban.reason,
                        'banned_by': ban.banned_by,
                        'banned_at': ban.banned_at,
                        'is_permanent': ban.expires_at is None
                    })

            stats['total_blacklisted_ips'] = len(blacklisted_ips)

            if security_middleware and hasattr(security_middleware, 'rate_limiter'):
                try:
                    security_stats = security_middleware.get_stats()
                    monitored_details = security_middleware.get_monitored_ips()

                    stats.update({
                        'total_monitored_ips': security_stats['total_monitored_ips'],
                        'total_attack_attempts': security_stats['total_attack_attempts'],
                        'unique_attackers': security_stats['unique_attackers'],
                        'monitored_ips': monitored_details[:10]
                    })
                except Exception as e:
                    logger.warning(f"Error getting security middleware stats: {e}")
                    try:
                        rate_limiter = security_middleware.rate_limiter
                        stats['total_monitored_ips'] = len(rate_limiter.requests)
                        stats['total_attack_attempts'] = sum(rate_limiter.attack_counts.values()) if hasattr(rate_limiter, 'attack_counts') else 0
                        stats['unique_attackers'] = len(rate_limiter.attack_counts) if hasattr(rate_limiter, 'attack_counts') else 0
                    except:
                        pass

                # Add in-memory bans
                current_time = time.time()
                for ip, expiry in security_middleware.rate_limiter.blacklist.items():
                    if current_time < expiry and not is_private_ip(ip):
                        if not any(ban['ip'] == ip for ban in blacklisted_ips):
                            blacklisted_ips.append({
                                'ip': ip,
                                'expires_at': datetime.fromtimestamp(expiry),
                                'time_remaining': int(expiry - current_time),
                                'reason': 'Automatic detection',
                                'banned_by': 'Security System',
                                'banned_at': datetime.fromtimestamp(expiry - 1800),
                                'is_permanent': False
                            })
        except ImportError:
            logger.warning("IPBan model not available")
        except Exception as e:
            logger.error(f"Error getting security stats: {e}")

        current_time = datetime.now().strftime('%H:%M:%S')

        return render_template('admin_panel/system/security_dashboard_flowbite.html',
                             stats=stats,
                             blacklisted_ips=blacklisted_ips,
                             current_time=current_time)

    except Exception as e:
        logger.error(f"Error loading security dashboard: {e}")
        flash('Error loading security dashboard', 'error')
        return redirect(url_for('admin_panel.dashboard'))


@admin_panel_bp.route('/system/security/ban-ip', methods=['POST'])
@login_required
@role_required(['Global Admin'])
@transactional
def security_ban_ip():
    """Manually ban an IP address."""
    from app.models import IPBan
    from app.core import db

    data = request.get_json()
    ip_address = data.get('ip_address')
    reason = data.get('reason', 'Manual ban from admin panel')
    duration_hours = data.get('duration_hours', 24)
    permanent = data.get('permanent', False)

    if not ip_address:
        return jsonify({'success': False, 'message': 'IP address is required'}), 400

    # Create ban
    expires_at = None if permanent else datetime.utcnow() + timedelta(hours=duration_hours)

    ban = IPBan(
        ip_address=ip_address,
        reason=reason,
        banned_by=current_user.username,
        banned_at=datetime.utcnow(),
        expires_at=expires_at
    )

    db.session.add(ban)

    # Log the action
    AdminAuditLog.log_action(
        user_id=current_user.id,
        action='ban_ip',
        resource_type='security',
        resource_id=ip_address,
        new_value=f'Banned for: {reason}',
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent')
    )

    return jsonify({
        'success': True,
        'message': f'IP {ip_address} has been banned'
    })


@admin_panel_bp.route('/system/security/unban-ip', methods=['POST'])
@login_required
@role_required(['Global Admin'])
@transactional
def security_unban_ip():
    """Unban an IP address."""
    from app.models import IPBan
    from app.core import db

    data = request.get_json()
    ip_address = data.get('ip_address')

    if not ip_address:
        return jsonify({'success': False, 'message': 'IP address is required'}), 400

    # Remove from database
    IPBan.query.filter_by(ip_address=ip_address).delete()

    # Also remove from in-memory blacklist if security middleware exists
    if hasattr(current_app, 'security_middleware') and current_app.security_middleware:
        if hasattr(current_app.security_middleware, 'rate_limiter'):
            if ip_address in current_app.security_middleware.rate_limiter.blacklist:
                del current_app.security_middleware.rate_limiter.blacklist[ip_address]

    # Log the action
    AdminAuditLog.log_action(
        user_id=current_user.id,
        action='unban_ip',
        resource_type='security',
        resource_id=ip_address,
        new_value='IP unbanned',
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent')
    )

    return jsonify({
        'success': True,
        'message': f'IP {ip_address} has been unbanned'
    })


# -----------------------------------------------------------
# Security Routes - Alias routes for JavaScript compatibility
# JS calls /security/block-ip but original routes are /system/security/ban-ip
# -----------------------------------------------------------

@admin_panel_bp.route('/security/block-ip', methods=['POST'])
@login_required
@role_required(['Global Admin'])
@transactional
def security_block_ip_alias():
    """Alias for ban-ip to match JavaScript API calls."""
    return security_ban_ip()


@admin_panel_bp.route('/security/unblock-ip', methods=['POST'])
@login_required
@role_required(['Global Admin'])
@transactional
def security_unblock_ip_alias():
    """Alias for unban-ip to match JavaScript API calls."""
    return security_unban_ip()


@admin_panel_bp.route('/system/security/clear-all-bans', methods=['POST'])
@login_required
@role_required(['Global Admin'])
@transactional
def security_clear_all_bans():
    """Clear all IP bans."""
    from app.models import IPBan
    from app.core import db

    # Clear database bans
    count = IPBan.query.delete()

    # Clear in-memory blacklist
    if hasattr(current_app, 'security_middleware') and current_app.security_middleware:
        if hasattr(current_app.security_middleware, 'rate_limiter'):
            current_app.security_middleware.rate_limiter.blacklist.clear()

    # Log the action
    AdminAuditLog.log_action(
        user_id=current_user.id,
        action='clear_all_bans',
        resource_type='security',
        resource_id='all',
        new_value=f'Cleared {count} bans',
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent')
    )

    return jsonify({
        'success': True,
        'message': f'Cleared {count} IP bans'
    })


@admin_panel_bp.route('/api/security/status')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def api_security_status():
    """API endpoint for security status (for AJAX refresh)."""
    try:
        security_middleware = None
        if hasattr(current_app, 'security_middleware'):
            security_middleware = current_app.security_middleware

        stats = {
            'total_monitored_ips': 0,
            'total_blacklisted_ips': 0,
            'total_attack_attempts': 0,
            'unique_attackers': 0
        }

        # Get stats
        try:
            from app.models import IPBan
            stats['total_blacklisted_ips'] = IPBan.query.filter(
                (IPBan.expires_at.is_(None)) | (IPBan.expires_at > datetime.utcnow())
            ).count()
        except:
            pass

        if security_middleware and hasattr(security_middleware, 'rate_limiter'):
            try:
                security_stats = security_middleware.get_stats()
                stats.update({
                    'total_monitored_ips': security_stats['total_monitored_ips'],
                    'total_attack_attempts': security_stats['total_attack_attempts'],
                    'unique_attackers': security_stats['unique_attackers']
                })
            except:
                pass

        stats['current_time'] = datetime.now().strftime('%H:%M:%S')

        return jsonify({'success': True, 'stats': stats})

    except Exception as e:
        logger.error(f"Error getting security status: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


# -----------------------------------------------------------
# Redis Cache Clear Routes
# -----------------------------------------------------------

@admin_panel_bp.route('/system/redis/clear', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def redis_clear_cache():
    """
    Clear Redis cache by type.

    Accepts JSON with 'cache_type' field:
    - 'all': Clear all cache keys
    - 'session': Clear session-related keys
    - 'draft': Clear draft-related keys
    - 'mls': Clear MLS match-related keys
    - 'rsvp': Clear RSVP-related keys
    """
    try:
        from app.utils.safe_redis import get_safe_redis

        data = request.get_json() or {}
        cache_type = data.get('cache_type', 'all')

        redis_client = get_safe_redis()

        if not redis_client.is_available:
            return jsonify({
                'success': False,
                'error': 'Redis is not available'
            }), 503

        # Define patterns for each cache type
        cache_patterns = {
            'all': ['*'],
            'session': ['session:*', 'flask_session:*'],
            'draft': ['draft:*'],
            'mls': ['mls:*', 'match:*', 'live_reporting:*', 'match_scheduler:*'],
            'rsvp': ['rsvp:*', 'rsvp_cache:*'],
            'task': ['task:*', 'celery-task-meta-*']
        }

        patterns = cache_patterns.get(cache_type, [f'{cache_type}:*'])
        deleted_count = 0

        for pattern in patterns:
            try:
                keys = redis_client.keys(pattern)
                if keys:
                    for key in keys:
                        redis_client.delete(key)
                        deleted_count += 1
            except Exception as e:
                logger.warning(f"Error clearing pattern {pattern}: {e}")

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='redis_cache_clear',
            resource_type='system',
            resource_id='redis',
            new_value=f'Cleared {deleted_count} keys (type: {cache_type})',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        logger.info(f"Redis cache cleared by {current_user.username}: type={cache_type}, keys={deleted_count}")

        return jsonify({
            'success': True,
            'message': f'Successfully cleared {deleted_count} cache keys',
            'cache_type': cache_type,
            'deleted_count': deleted_count
        })

    except Exception as e:
        logger.error(f"Error clearing Redis cache: {e}")
        return jsonify({
            'success': False,
            'error': f'Failed to clear cache: {str(e)}'
        }), 500


@admin_panel_bp.route('/system/redis/delete-key', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def redis_delete_key():
    """
    Delete a specific Redis key.

    Accepts JSON with 'key' field containing the exact key name to delete.
    """
    try:
        from app.utils.safe_redis import get_safe_redis

        data = request.get_json() or {}
        key_name = data.get('key')

        if not key_name:
            return jsonify({
                'success': False,
                'error': 'Key name is required'
            }), 400

        redis_client = get_safe_redis()

        if not redis_client.is_available:
            return jsonify({
                'success': False,
                'error': 'Redis is not available'
            }), 503

        # Check if key exists before deletion
        exists = redis_client.exists(key_name)

        if not exists:
            return jsonify({
                'success': False,
                'error': f'Key "{key_name}" does not exist'
            }), 404

        # Delete the key
        deleted = redis_client.delete(key_name)

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='redis_key_delete',
            resource_type='system',
            resource_id='redis',
            new_value=f'Deleted key: {key_name}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        logger.info(f"Redis key deleted by {current_user.username}: {key_name}")

        return jsonify({
            'success': True,
            'message': f'Successfully deleted key "{key_name}"',
            'key': key_name,
            'deleted': bool(deleted)
        })

    except Exception as e:
        logger.error(f"Error deleting Redis key: {e}")
        return jsonify({
            'success': False,
            'error': f'Failed to delete key: {str(e)}'
        }), 500


@admin_panel_bp.route('/system/draft-cache/clear', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def draft_cache_clear():
    """
    Clear draft cache entries.

    Accepts JSON with optional 'cache_key' field:
    - If provided: Clear only the specified cache entry
    - If not provided: Clear all draft cache entries
    """
    try:
        from app.utils.safe_redis import get_safe_redis
        from app.draft_cache_service import DraftCacheService

        data = request.get_json() or {}
        cache_key = data.get('cache_key')

        redis_client = get_safe_redis()

        if not redis_client.is_available:
            return jsonify({
                'success': False,
                'error': 'Redis is not available'
            }), 503

        deleted_count = 0

        if cache_key:
            # Delete specific cache key
            if redis_client.exists(cache_key):
                redis_client.delete(cache_key)
                deleted_count = 1
                message = f'Cleared draft cache entry: {cache_key}'
            else:
                return jsonify({
                    'success': False,
                    'error': f'Cache key "{cache_key}" does not exist'
                }), 404
        else:
            # Clear all draft cache entries
            draft_patterns = [
                'draft:players:*',
                'draft:analytics:*',
                'draft:teams:*',
                'draft:availability:*'
            ]

            for pattern in draft_patterns:
                try:
                    keys = redis_client.keys(pattern)
                    for key in keys:
                        redis_client.delete(key)
                        deleted_count += 1
                except Exception as e:
                    logger.warning(f"Error clearing draft pattern {pattern}: {e}")

            message = f'Cleared {deleted_count} draft cache entries'

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='draft_cache_clear',
            resource_type='system',
            resource_id='draft_cache',
            new_value=message,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        logger.info(f"Draft cache cleared by {current_user.username}: {deleted_count} entries")

        return jsonify({
            'success': True,
            'message': message,
            'deleted_count': deleted_count
        })

    except Exception as e:
        logger.error(f"Error clearing draft cache: {e}")
        return jsonify({
            'success': False,
            'error': f'Failed to clear draft cache: {str(e)}'
        }), 500
