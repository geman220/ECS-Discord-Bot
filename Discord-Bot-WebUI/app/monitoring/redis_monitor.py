# app/monitoring/redis_monitor.py

"""
Redis Monitoring Routes

Provides endpoints for monitoring Redis:
- Key inspection
- Connection testing
"""

import json
import logging

from flask import jsonify
from flask_login import login_required
from celery.result import AsyncResult

from app.monitoring import monitoring_bp
from app.decorators import role_required
from app.utils.safe_redis import get_safe_redis
from app.core import celery

logger = logging.getLogger(__name__)


@monitoring_bp.route('/redis/keys', endpoint='get_redis_keys')
@login_required
@role_required('Global Admin')
def get_redis_keys():
    """
    Retrieve all Redis keys related to match scheduling.
    Only shows recent keys (within 24 hours) to reduce clutter.

    Returns:
        JSON response with key details including value, TTL, and task status.
    """
    try:
        redis_client = get_safe_redis()
        scheduler_keys = redis_client.keys('match_scheduler:*')
        result = {}
        filtered_count = 0

        for key in scheduler_keys:
            try:
                key_str = key.decode('utf-8') if isinstance(key, bytes) else str(key)
                value = redis_client.get(key)
                ttl = redis_client.ttl(key)

                # Skip keys that have already expired or will expire very soon
                if ttl < 60 and ttl != -1:
                    filtered_count += 1
                    continue

                stored_value = None
                if value is not None:
                    value_str = value.decode('utf-8') if isinstance(value, bytes) else str(value)
                    try:
                        stored_obj = json.loads(value_str)
                        stored_value = stored_obj.get("task_id", value_str)
                    except Exception:
                        stored_value = value_str

                task_status = None
                if stored_value and len(stored_value) == 36:
                    try:
                        task = AsyncResult(stored_value, app=celery)
                        task_status = {
                            'id': stored_value,
                            'status': task.status,
                            'ready': task.ready(),
                            'successful': task.successful() if task.ready() else None
                        }

                        # Skip completed tasks that are old
                        if task.ready() and task.successful() and ttl > 3600:
                            filtered_count += 1
                            continue

                    except Exception as task_error:
                        logger.warning(f"Error getting task status for {stored_value}: {task_error}")

                result[key_str] = {
                    'value': value.decode('utf-8') if isinstance(value, bytes) else value,
                    'ttl': ttl,
                    'task_status': task_status
                }
            except Exception as key_error:
                logger.error(f"Error processing Redis key {key}: {key_error}", exc_info=True)
                result[str(key)] = {'error': str(key_error)}

        return jsonify({
            'success': True,
            'keys': result,
            'total': len(result),
            'filtered_count': filtered_count,
            'total_found': len(scheduler_keys)
        })
    except Exception as e:
        logger.error(f"Error getting Redis keys: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@monitoring_bp.route('/redis/test', endpoint='test_redis')
@login_required
@role_required('Global Admin')
def test_redis():
    """
    Test Redis connection and retrieve scheduler keys information.

    Returns:
        JSON response with ping result, total keys, and detailed key info.
    """
    try:
        redis_client = get_safe_redis()
        ping_result = redis_client.ping()
        scheduler_keys = redis_client.keys('match_scheduler:*')
        keys_info = {}

        for key in scheduler_keys:
            try:
                key_str = key.decode('utf-8') if isinstance(key, bytes) else str(key)
                value = redis_client.get(key)
                if value is not None:
                    try:
                        value = value.decode('utf-8') if isinstance(value, bytes) else str(value)
                    except (UnicodeDecodeError, AttributeError):
                        value = str(value)
                ttl = redis_client.ttl(key)
                task_status = None

                if value and len(value) == 36:
                    try:
                        task = AsyncResult(value, app=celery)
                        task_status = {
                            'id': value,
                            'status': task.status,
                            'ready': task.ready(),
                            'successful': task.successful() if task.ready() else None
                        }
                    except Exception as task_error:
                        logger.warning(f"Error getting task status for {value}: {task_error}")

                keys_info[key_str] = {'value': value, 'ttl': ttl, 'task_status': task_status}
            except Exception as key_error:
                logger.error(f"Error processing key {key}: {key_error}", exc_info=True)
                keys_info[str(key)] = {'error': str(key_error)}

        logger.info(f"Redis connection test: {ping_result}")
        logger.info(f"Found {len(scheduler_keys)} scheduler keys")

        return jsonify({
            'success': True,
            'ping': ping_result,
            'total_keys': len(scheduler_keys),
            'keys': keys_info
        })
    except Exception as e:
        logger.error(f"Redis test failed: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
