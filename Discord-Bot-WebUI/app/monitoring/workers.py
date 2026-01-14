# app/monitoring/workers.py

"""
Worker Monitoring Routes

Provides endpoints for monitoring Celery workers:
- Worker status
- Worker details
- Scheduled tasks
"""

import json
import logging

from flask import jsonify
from flask_login import login_required

from app.monitoring import monitoring_bp
from app.decorators import role_required
from app.utils.safe_redis import get_safe_redis
from app.core import celery
from app.core.helpers import get_match
from app.core.session_manager import managed_session

logger = logging.getLogger(__name__)


@monitoring_bp.route('/workers', endpoint='get_workers')
@login_required
@role_required('Global Admin')
def get_workers():
    """
    Retrieve information about all Celery workers.

    Returns:
        JSON response with details about active Celery workers.
    """
    try:
        # Use direct Redis connection
        try:
            from app.utils.redis_manager import UnifiedRedisManager
            redis_manager = UnifiedRedisManager()
            direct_redis = redis_manager.client  # Use property, not method
            direct_redis.ping()
            logger.info("Direct Redis connection successful for workers")
            redis_client = direct_redis
        except Exception as e:
            logger.error(f"Direct Redis connection failed for workers: {e}")
            redis_client = get_safe_redis()

        # Cache key for workers data
        cache_key = "monitoring:workers_data"
        cache_ttl = 15  # seconds

        # Try to get from cache first
        cached_data = redis_client.get(cache_key)
        if cached_data:
            try:
                return jsonify(json.loads(cached_data))
            except (json.JSONDecodeError, TypeError):
                pass

        # Set timeout for Celery inspection
        timeout = 1.0
        i = celery.control.inspect(timeout=timeout)

        # Get all data with a single broadcast call
        stats = i.stats() or {}
        active = i.active() or {}
        scheduled = i.scheduled() or {}
        reserved = i.reserved() or {}
        registered = {}

        # For registered tasks, cache the count
        for worker_name, worker_stats in stats.items():
            try:
                registered_count = redis_client.get(f"monitoring:registered_tasks:{worker_name}")
                if registered_count:
                    registered[worker_name] = int(registered_count)
                else:
                    worker_registered = i.registered(destination=[worker_name]) or {}
                    count = len(worker_registered.get(worker_name, []))
                    registered[worker_name] = count
                    redis_client.setex(f"monitoring:registered_tasks:{worker_name}", 3600, str(count))
            except Exception:
                registered[worker_name] = 0

        # Collect scheduled task details
        scheduled_task_details = []
        for worker_name, tasks in scheduled.items():
            for task in tasks:
                try:
                    task_name = None
                    task_id = task.get('id', '')

                    # Try different ways to extract task name
                    if 'name' in task and task['name']:
                        task_name = task['name']
                    elif 'request' in task and task['request'].get('task'):
                        task_name = task['request']['task']
                    elif 'request' in task and task['request'].get('name'):
                        task_name = task['request']['name']

                    if not task_name:
                        task_name = 'Unknown Task'
                        logger.warning(f"Could not determine task name for task: {task}")

                    args = task.get('args', [])
                    kwargs = task.get('kwargs', {})
                    eta = task.get('eta')

                    # Extract request details
                    request = task.get('request', {})
                    delivery_info = request.get('delivery_info', {})
                    queue = delivery_info.get('routing_key', 'Unknown')

                    if queue == 'Unknown':
                        if 'delivery_info' in task and 'routing_key' in task['delivery_info']:
                            queue = task['delivery_info']['routing_key']
                        elif 'queue' in task:
                            queue = task['queue']

                    full_task = {
                        'worker': worker_name,
                        'name': task_name,
                        'args': args,
                        'kwargs': kwargs,
                        'eta': eta,
                        'id': task_id,
                        'queue': queue
                    }

                    # Simplified details for JS
                    try:
                        simplified_details = {
                            'id': task_id,
                            'name': task_name,
                            'worker': worker_name,
                            'args': str(args),
                            'kwargs': str(kwargs),
                            'eta': str(eta),
                            'queue': queue
                        }
                        full_task['full_details'] = json.dumps(simplified_details)
                    except Exception:
                        full_task['full_details'] = "{}"

                    # Add match ID if available
                    match_id = None
                    if args and len(args) > 0:
                        match_id = args[0]
                    elif kwargs and 'match_id' in kwargs:
                        match_id = kwargs['match_id']

                    if match_id:
                        full_task['match_id'] = match_id

                        try:
                            with managed_session() as session:
                                match = get_match(session, match_id)
                                if match:
                                    full_task['match_details'] = {
                                        'opponent': match.opponent if hasattr(match, 'opponent') else 'Unknown',
                                        'date_time': match.date_time.isoformat() if hasattr(match, 'date_time') else None,
                                        'location': match.location if hasattr(match, 'location') else 'Unknown'
                                    }
                        except Exception as e:
                            logger.warning(f"Error fetching match details for task: {e}")

                    scheduled_task_details.append(full_task)
                except Exception as e:
                    logger.warning(f"Error processing scheduled task: {e}")

        # Combine all information
        workers_info = {}
        for worker_name in stats.keys():
            worker_scheduled = scheduled.get(worker_name, [])
            workers_info[worker_name] = {
                'active_tasks': active.get(worker_name, []),
                'registered_tasks': registered.get(worker_name, 0),
                'scheduled_tasks': len(worker_scheduled),
                'reserved_tasks': len(reserved.get(worker_name, [])),
                'status': 'online'
            }

        # Get worker queues
        queues = {}
        scheduled_task_count = 0
        for worker, worker_stats in stats.items():
            if 'pool' in worker_stats:
                queues[worker] = {
                    'pool_size': worker_stats.get('pool', {}).get('max-concurrency', 0)
                }
            scheduled_task_count += len(scheduled.get(worker, []))

        result = {
            'success': True,
            'workers': workers_info,
            'queues': queues,
            'total_workers': len(workers_info),
            'active_workers': len(stats),
            'total_scheduled_tasks': scheduled_task_count,
            'scheduled_tasks': scheduled_task_details
        }

        # Cache the result
        try:
            redis_client.setex(cache_key, cache_ttl, json.dumps(result))
        except (TypeError, json.JSONEncodeError):
            pass

        return jsonify(result)
    except Exception as e:
        logger.error(f"Error getting worker information: {e}", exc_info=True)
        return jsonify({
            'success': True,  # Return success even on error to avoid UI disruption
            'workers': {},
            'queues': {},
            'total_workers': 0,
            'active_workers': 0,
            'total_scheduled_tasks': 0,
            'error': "Timed out waiting for worker response"
        })
