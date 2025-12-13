# app/monitoring/queues.py

"""
Queue Monitoring Routes

Provides endpoints for monitoring and managing Celery queues:
- Queue status and health
- Queue details
- Queue purging
"""

import json
import logging
from datetime import datetime

from flask import jsonify, request
from flask_login import login_required

from app.monitoring import monitoring_bp
from app.decorators import role_required
from app.utils.safe_redis import get_safe_redis
from app.core import celery

logger = logging.getLogger(__name__)


@monitoring_bp.route('/queues/status', endpoint='get_queue_status')
@login_required
def get_queue_status():
    """
    Get real-time queue lengths and health status.

    Returns:
        JSON response with queue lengths, health status, and alerts.
    """
    try:
        # Try direct Redis connection first
        try:
            from app.utils.redis_manager import UnifiedRedisManager
            redis_manager = UnifiedRedisManager()
            direct_redis = redis_manager.get_decoded_client()
            direct_redis.ping()
            logger.info("Direct Redis connection successful")
            redis_client = direct_redis

        except Exception as e:
            logger.error(f"Direct Redis connection failed: {e}")
            return jsonify({
                'success': False,
                'error': f'Redis connection failed: {str(e)}',
                'queues': {},
                'alerts': []
            })

        queues = ['live_reporting', 'discord', 'celery', 'player_sync']
        queue_thresholds = {
            'live_reporting': 50,
            'discord': 25,
            'celery': 100,
            'player_sync': 15
        }

        queue_data = {}
        alerts = []
        total_tasks = 0

        for queue_name in queues:
            try:
                length = redis_client.llen(queue_name)
                threshold = queue_thresholds.get(queue_name, 50)

                status = 'healthy'
                if length > threshold * 2:
                    status = 'critical'
                    alerts.append({
                        'queue': queue_name,
                        'message': f'Queue {queue_name} critically backed up: {length} tasks',
                        'severity': 'error'
                    })
                elif length > threshold:
                    status = 'warning'
                    alerts.append({
                        'queue': queue_name,
                        'message': f'Queue {queue_name} growing: {length} tasks',
                        'severity': 'warning'
                    })

                queue_data[queue_name] = {
                    'length': length,
                    'threshold': threshold,
                    'status': status,
                    'percentage': min(100, (length / threshold) * 100) if threshold > 0 else 0
                }
                total_tasks += length

            except Exception as e:
                queue_data[queue_name] = {
                    'error': str(e),
                    'status': 'error',
                    'length': 0
                }

        return jsonify({
            'success': True,
            'queues': queue_data,
            'total_tasks': total_tasks,
            'alerts': alerts,
            'timestamp': datetime.utcnow().isoformat()
        })

    except Exception as e:
        logger.error(f"Error getting queue status: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@monitoring_bp.route('/queue/details', endpoint='get_queue_details')
@login_required
def get_queue_details():
    """
    Get detailed information about tasks in all queues.

    Returns:
        JSON response with detailed task information for each queue.
    """
    try:
        # Use direct Redis connection
        try:
            from app.utils.redis_manager import UnifiedRedisManager
            redis_manager = UnifiedRedisManager()
            direct_redis = redis_manager.get_decoded_client()
            direct_redis.ping()
            logger.info("Direct Redis connection successful for queue details")
            redis_client = direct_redis
        except Exception as e:
            logger.error(f"Direct Redis connection failed for queue details: {e}")
            return jsonify({'success': False, 'error': f'Redis connection failed: {str(e)}'}), 500

        # Use Celery inspect to get detailed queue information
        timeout = 2.0
        i = celery.control.inspect(timeout=timeout)

        scheduled = i.scheduled() or {}
        reserved = i.reserved() or {}
        active = i.active() or {}

        queues = {}

        # Process scheduled tasks
        for worker_name, tasks in scheduled.items():
            for task in tasks:
                queue_name = task.get('delivery_info', {}).get('routing_key', 'celery')
                if queue_name not in queues:
                    queues[queue_name] = []

                task_info = {
                    'id': task.get('id', ''),
                    'name': task.get('request', {}).get('task') or task.get('name', 'Unknown'),
                    'args': task.get('request', {}).get('args', []),
                    'kwargs': task.get('request', {}).get('kwargs', {}),
                    'eta': task.get('eta'),
                    'priority': task.get('priority'),
                    'worker': worker_name,
                    'status': 'scheduled'
                }
                queues[queue_name].append(task_info)

        # Process reserved tasks
        for worker_name, tasks in reserved.items():
            for task in tasks:
                queue_name = task.get('delivery_info', {}).get('routing_key', 'celery')
                if queue_name not in queues:
                    queues[queue_name] = []

                task_info = {
                    'id': task.get('id', ''),
                    'name': task.get('name', 'Unknown'),
                    'args': task.get('args', []),
                    'kwargs': task.get('kwargs', {}),
                    'eta': task.get('eta'),
                    'priority': task.get('priority'),
                    'worker': worker_name,
                    'status': 'reserved'
                }
                queues[queue_name].append(task_info)

        # Process active tasks
        for worker_name, tasks in active.items():
            for task in tasks:
                queue_name = task.get('delivery_info', {}).get('routing_key', 'celery')
                if queue_name not in queues:
                    queues[queue_name] = []

                task_info = {
                    'id': task.get('id', ''),
                    'name': task.get('name', 'Unknown'),
                    'args': task.get('args', []),
                    'kwargs': task.get('kwargs', {}),
                    'eta': None,
                    'priority': None,
                    'worker': worker_name,
                    'status': 'active'
                }
                queues[queue_name].append(task_info)

        # Also check Redis directly for any queued messages
        try:
            queue_names = ['celery', 'live_reporting', 'thread_creation', 'default']
            for queue_name in queue_names:
                queue_length = redis_client.llen(queue_name)

                if queue_length > 0:
                    if queue_name not in queues:
                        queues[queue_name] = []

                    sample_tasks = redis_client.lrange(queue_name, 0, 9)
                    logger.info(f"Found {len(sample_tasks)} tasks in {queue_name} queue")

                    for i, task_data in enumerate(sample_tasks):
                        try:
                            task_json = None
                            if isinstance(task_data, str):
                                try:
                                    task_json = json.loads(task_data)
                                except json.JSONDecodeError:
                                    try:
                                        import base64
                                        decoded = base64.b64decode(task_data)
                                        task_json = json.loads(decoded.decode('utf-8'))
                                    except:
                                        pass
                            else:
                                task_json = task_data

                            if task_json:
                                task_name = (
                                    task_json.get('task') or
                                    task_json.get('name') or
                                    task_json.get('headers', {}).get('task') or
                                    'Unknown Task'
                                )

                                task_id = (
                                    task_json.get('id') or
                                    task_json.get('uuid') or
                                    task_json.get('headers', {}).get('id') or
                                    f"queue_item_{i}"
                                )

                                task_info = {
                                    'id': task_id,
                                    'name': task_name,
                                    'args': task_json.get('args', []),
                                    'kwargs': task_json.get('kwargs', {}),
                                    'eta': task_json.get('eta'),
                                    'priority': task_json.get('priority'),
                                    'worker': 'N/A',
                                    'status': 'queued_in_redis'
                                }
                            else:
                                task_info = {
                                    'id': f"unparsed_{i}",
                                    'name': 'Raw Redis Entry',
                                    'args': [],
                                    'kwargs': {},
                                    'eta': None,
                                    'priority': None,
                                    'worker': 'N/A',
                                    'status': 'queued_in_redis'
                                }

                            queues[queue_name].append(task_info)

                        except Exception as task_error:
                            logger.error(f"Error processing task {i}: {task_error}", exc_info=True)

        except Exception as redis_error:
            logger.error(f"Error checking Redis queues directly: {redis_error}", exc_info=True)

        return jsonify({
            'success': True,
            'queues': queues,
            'total_tasks': sum(len(tasks) for tasks in queues.values())
        })

    except Exception as e:
        logger.error(f"Error getting queue details: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@monitoring_bp.route('/queue/purge', endpoint='purge_queue', methods=['POST'])
@login_required
@role_required('Global Admin')
def purge_queue():
    """
    Emergency queue purge - clears all tasks from a specific queue.

    Expects JSON payload with 'queue' name.

    Returns:
        JSON response indicating purge status.
    """
    try:
        data = request.get_json()
        queue_name = data.get('queue', 'live_reporting')

        logger.info(f"Emergency purge requested for queue: {queue_name}")

        total_purged = 0

        # Method 1: Try direct queue purge
        try:
            result = celery.control.purge(queue_name)
            logger.info(f"Purge result for queue {queue_name}: {result}")

            if result:
                for worker, count in result.items():
                    if count:
                        total_purged += count

        except Exception as purge_error:
            logger.warning(f"Error during direct queue purge: {purge_error}")

            # Method 2: Try Redis-based cleanup
            try:
                redis_client = get_safe_redis()
                celery_keys = redis_client.keys(f"celery*{queue_name}*") + redis_client.keys(f"*{queue_name}*")

                for key in celery_keys:
                    try:
                        key_str = key.decode('utf-8') if isinstance(key, bytes) else str(key)
                        if any(pattern in key_str.lower() for pattern in ['queue', 'task', 'job']):
                            redis_client.delete(key)
                            total_purged += 1
                            logger.info(f"Deleted Redis queue key: {key_str}")
                    except Exception as key_error:
                        logger.warning(f"Error deleting Redis key {key}: {key_error}")

            except Exception as redis_purge_error:
                logger.warning(f"Error during Redis-based purge: {redis_purge_error}")

        # Also try to revoke any scheduled tasks in that queue
        revoked_scheduled = 0
        try:
            i = celery.control.inspect(timeout=2.0)
            scheduled = i.scheduled() or {}

            for worker_name, tasks in scheduled.items():
                for task in tasks:
                    task_queue = 'default'
                    if 'request' in task and 'delivery_info' in task['request']:
                        task_queue = task['request']['delivery_info'].get('routing_key', 'default')
                    elif 'delivery_info' in task:
                        task_queue = task['delivery_info'].get('routing_key', 'default')

                    if task_queue == queue_name:
                        task_id = task.get('id')
                        if task_id:
                            try:
                                celery.control.revoke(task_id, terminate=True)
                                revoked_scheduled += 1
                                logger.info(f"Revoked scheduled task {task_id} from queue {queue_name}")
                            except Exception as e:
                                logger.warning(f"Error revoking scheduled task {task_id}: {e}")

        except Exception as scheduled_error:
            logger.warning(f"Error revoking scheduled tasks: {scheduled_error}")

        # Clean up any Redis keys related to the queue
        redis_cleaned = 0
        try:
            redis_client = get_safe_redis()

            if queue_name == 'live_reporting':
                reporting_keys = redis_client.keys('match_scheduler:*:reporting')
                for key in reporting_keys:
                    redis_client.delete(key)
                    redis_cleaned += 1
                    logger.info(f"Cleaned up Redis key: {key}")

        except Exception as redis_error:
            logger.warning(f"Error cleaning Redis keys: {redis_error}")

        message = f"Emergency purge of queue '{queue_name}' completed. "
        message += f"Purged {total_purged} queued tasks, "
        message += f"revoked {revoked_scheduled} scheduled tasks, "
        message += f"cleaned {redis_cleaned} Redis keys."

        return jsonify({
            'success': True,
            'message': message,
            'queue': queue_name,
            'purged_tasks': total_purged,
            'revoked_scheduled': revoked_scheduled,
            'redis_cleaned': redis_cleaned
        })

    except Exception as e:
        logger.error(f"Error purging queue: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
