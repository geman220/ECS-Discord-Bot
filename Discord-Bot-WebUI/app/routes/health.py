"""
Health Check Routes

Provides endpoints for monitoring system health and queue status.
"""

import logging
from flask import Blueprint, jsonify, request
from datetime import datetime

from app.utils.queue_monitor import queue_monitor
from app.services.redis_connection_service import get_redis_service

logger = logging.getLogger(__name__)

health_bp = Blueprint('health', __name__)


@health_bp.route('/health/', methods=['GET'])
def basic_health():
    """Basic health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'service': 'ECS Discord Bot'
    }), 200


@health_bp.route('/health/queues', methods=['GET'])
def queue_health():
    """Detailed queue health check."""
    try:
        health_check = queue_monitor.check_queue_health()
        summary = queue_monitor.get_queue_summary()

        # Determine overall health status
        overall_status = 'healthy'
        for queue_data in health_check['queues'].values():
            if queue_data.get('status') in ['critical', 'emergency']:
                overall_status = 'critical'
                break
            elif queue_data.get('status') == 'warning':
                overall_status = 'warning'

        return jsonify({
            'status': overall_status,
            'timestamp': datetime.utcnow().isoformat(),
            'queue_health': health_check,
            'queue_summary': summary
        }), 200

    except Exception as e:
        logger.error(f"Error in queue health check: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }), 500


@health_bp.route('/health/workers', methods=['GET'])
def worker_health():
    """Check Celery worker health."""
    try:
        redis_service = get_redis_service()

        # Basic Redis connectivity test
        redis_service.execute_command('ping')

        # Check realtime service
        realtime_status = redis_service.execute_command('get', 'realtime_service:status')
        realtime_heartbeat = redis_service.execute_command('get', 'realtime_service:heartbeat')

        worker_info = {
            'redis_connected': True,
            'realtime_service': {
                'status': realtime_status.decode() if realtime_status else 'stopped',
                'last_heartbeat': realtime_heartbeat.decode() if realtime_heartbeat else None
            }
        }

        # Try to get Celery worker info
        try:
            from celery import current_app as celery_app
            inspect = celery_app.control.inspect()
            active_workers = inspect.ping() or {}

            worker_info['celery_workers'] = {
                'online': len(active_workers),
                'workers': list(active_workers.keys())
            }
        except Exception as e:
            worker_info['celery_workers'] = {
                'error': str(e)
            }

        # Determine status
        status = 'healthy'
        if not worker_info['redis_connected']:
            status = 'critical'
        elif worker_info['realtime_service']['status'] != 'running':
            status = 'warning'

        return jsonify({
            'status': status,
            'timestamp': datetime.utcnow().isoformat(),
            'workers': worker_info
        }), 200

    except Exception as e:
        logger.error(f"Error in worker health check: {e}")
        return jsonify({
            'status': 'critical',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }), 500


@health_bp.route('/health/full', methods=['GET'])
def full_health_check():
    """Comprehensive health check."""
    try:
        # Get queue health
        queue_check = queue_monitor.check_queue_health()
        queue_summary = queue_monitor.get_queue_summary()

        # Get worker status
        redis_service = get_redis_service()
        redis_connected = True
        try:
            redis_service.execute_command('ping')
        except:
            redis_connected = False

        # Check realtime service
        realtime_status = 'unknown'
        if redis_connected:
            status_bytes = redis_service.execute_command('get', 'realtime_service:status')
            realtime_status = status_bytes.decode() if status_bytes else 'stopped'

        # Determine overall health
        overall_status = 'healthy'

        if not redis_connected:
            overall_status = 'critical'
        elif realtime_status != 'running':
            overall_status = 'degraded'
        elif any(q.get('status') in ['critical', 'emergency'] for q in queue_check['queues'].values()):
            overall_status = 'warning'

        return jsonify({
            'status': overall_status,
            'timestamp': datetime.utcnow().isoformat(),
            'components': {
                'redis': 'healthy' if redis_connected else 'critical',
                'realtime_service': 'healthy' if realtime_status == 'running' else 'degraded',
                'queues': 'healthy' if overall_status != 'warning' else 'warning'
            },
            'queue_health': queue_check,
            'queue_summary': queue_summary,
            'metrics': {
                'total_tasks': queue_summary['total_tasks'],
                'alerts_active': len(queue_check.get('alerts', [])),
                'actions_taken': len(queue_check.get('actions_taken', []))
            }
        }), 200

    except Exception as e:
        logger.error(f"Error in full health check: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }), 500