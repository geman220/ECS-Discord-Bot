"""
Queue Clogging Detector Task

Periodic task that monitors for queue clogging patterns and sends alerts.
This helps ensure the clogging issue doesn't return.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any
import redis

from app.decorators import celery_task
from app.core import celery

logger = logging.getLogger(__name__)

# Store historical data in Redis
HISTORY_KEY_PREFIX = "queue_health_history:"
HISTORY_RETENTION_HOURS = 24


@celery_task(
    name='app.tasks.queue_clogging_detector.detect_queue_clogging',
    queue='celery',
    max_retries=3,
    soft_time_limit=30,
    time_limit=45
)
def detect_queue_clogging(self, session) -> Dict[str, Any]:
    """
    Monitor queue health and detect clogging patterns.

    This task:
    1. Checks current queue lengths
    2. Compares against historical data
    3. Detects growth patterns
    4. Sends alerts if clogging is detected

    Returns:
        dict: Health status and any alerts
    """
    try:
        from app.services.redis_connection_service import get_redis_service

        redis_client = get_redis_service()
        now = datetime.utcnow()

        # Get current queue metrics
        current_metrics = _get_queue_metrics(redis_client)

        # Store current metrics in history
        _store_metrics_history(redis_client, now, current_metrics)

        # Get historical metrics (from 5, 15, 30 minutes ago)
        historical_metrics = _get_historical_metrics(redis_client, now)

        # Detect clogging patterns
        alerts = _detect_clogging_patterns(current_metrics, historical_metrics)

        # Log alerts
        if alerts:
            for alert in alerts:
                severity = alert.get('severity', 'WARNING')
                message = alert.get('message', '')

                if severity == 'CRITICAL':
                    logger.critical(f"🚨 QUEUE CLOGGING DETECTED: {message}")
                elif severity == 'WARNING':
                    logger.warning(f"⚠️  Queue health warning: {message}")
                else:
                    logger.info(f"ℹ️  Queue info: {message}")

        # Calculate health score (0-100, higher is better)
        health_score = _calculate_health_score(current_metrics, historical_metrics)

        result = {
            'success': True,
            'timestamp': now.isoformat(),
            'health_score': health_score,
            'current_metrics': current_metrics,
            'alerts': alerts,
            'status': 'healthy' if health_score > 70 else 'degraded' if health_score > 40 else 'critical'
        }

        # Log summary
        total_queued = sum(current_metrics['queues'].values())
        logger.info(
            f"Queue health check: {result['status'].upper()} "
            f"(score: {health_score}/100, total queued: {total_queued})"
        )

        return result

    except Exception as e:
        logger.error(f"Error in queue clogging detector: {e}", exc_info=True)
        raise self.retry(exc=e, countdown=60)


def _get_queue_metrics(redis_client) -> Dict[str, Any]:
    """Get current queue metrics."""
    metrics = {
        'queues': {},
        'workers': {},
        'timestamp': datetime.utcnow().isoformat()
    }

    # Get queue lengths from Redis
    for queue_name in ['live_reporting', 'celery', 'discord', 'player_sync']:
        try:
            length = redis_client.llen(queue_name)
            metrics['queues'][queue_name] = int(length) if length else 0
        except Exception as e:
            logger.warning(f"Error getting length for queue {queue_name}: {e}")
            metrics['queues'][queue_name] = 0

    # Get worker stats from Celery
    try:
        i = celery.control.inspect()

        # Count active tasks
        active = i.active()
        if active:
            total_active = sum(len(tasks) for tasks in active.values())
            metrics['workers']['active_tasks'] = total_active
        else:
            metrics['workers']['active_tasks'] = 0

        # Count scheduled tasks
        scheduled = i.scheduled()
        if scheduled:
            total_scheduled = sum(len(tasks) for tasks in scheduled.values())
            metrics['workers']['scheduled_tasks'] = total_scheduled
        else:
            metrics['workers']['scheduled_tasks'] = 0

    except Exception as e:
        logger.warning(f"Error getting worker stats: {e}")
        metrics['workers']['active_tasks'] = 0
        metrics['workers']['scheduled_tasks'] = 0

    return metrics


def _store_metrics_history(redis_client, timestamp: datetime, metrics: Dict[str, Any]):
    """Store metrics in Redis for historical analysis."""
    try:
        # Use timestamp as key
        key = f"{HISTORY_KEY_PREFIX}{timestamp.strftime('%Y%m%d_%H%M%S')}"

        # Store as JSON string
        import json
        redis_client.setex(
            key,
            HISTORY_RETENTION_HOURS * 3600,  # TTL in seconds
            json.dumps(metrics)
        )
    except Exception as e:
        logger.warning(f"Error storing metrics history: {e}")


def _get_historical_metrics(redis_client, now: datetime) -> Dict[str, Dict[str, Any]]:
    """Get historical metrics from Redis."""
    historical = {}

    # Get metrics from 5, 15, 30 minutes ago
    intervals = [5, 15, 30]

    for minutes_ago in intervals:
        target_time = now - timedelta(minutes=minutes_ago)

        # Look for metrics within +/- 2 minutes of target
        for offset in range(-2, 3):
            check_time = target_time + timedelta(minutes=offset)
            key = f"{HISTORY_KEY_PREFIX}{check_time.strftime('%Y%m%d_%H%M%S')}"

            try:
                import json
                data = redis_client.get(key)
                if data:
                    historical[f'{minutes_ago}min'] = json.loads(data)
                    break
            except Exception:
                continue

    return historical


def _detect_clogging_patterns(current: Dict[str, Any], historical: Dict[str, Dict[str, Any]]) -> list:
    """Detect queue clogging patterns."""
    alerts = []

    current_queues = current['queues']

    # Check absolute thresholds
    thresholds = {
        'live_reporting': 20,
        'celery': 100,
        'discord': 50,
        'player_sync': 50
    }

    for queue, threshold in thresholds.items():
        length = current_queues.get(queue, 0)
        if length > threshold:
            alerts.append({
                'severity': 'WARNING',
                'queue': queue,
                'message': f'Queue {queue} has {length} tasks (threshold: {threshold})'
            })

    # Check growth patterns
    if '5min' in historical:
        prev_queues = historical['5min']['queues']

        for queue in current_queues:
            current_len = current_queues.get(queue, 0)
            prev_len = prev_queues.get(queue, 0)
            growth = current_len - prev_len

            # Alert on rapid growth (>10 tasks in 5 minutes)
            if growth > 10:
                alerts.append({
                    'severity': 'CRITICAL',
                    'queue': queue,
                    'message': f'Queue {queue} growing rapidly: +{growth} tasks in 5 min (was {prev_len}, now {current_len})'
                })

    # Check sustained growth over 30 minutes
    if '30min' in historical:
        prev_queues = historical['30min']['queues']

        total_current = sum(current_queues.values())
        total_prev = sum(prev_queues.values())
        growth = total_current - total_prev

        if growth > 50:
            alerts.append({
                'severity': 'CRITICAL',
                'message': f'Total queue size increased by {growth} tasks over 30 minutes - CLOGGING DETECTED'
            })

    # Check for excessive total queue size
    total_queued = sum(current_queues.values())
    if total_queued > 200:
        alerts.append({
            'severity': 'CRITICAL',
            'message': f'Excessive total queue size: {total_queued} tasks'
        })

    return alerts


def _calculate_health_score(current: Dict[str, Any], historical: Dict[str, Dict[str, Any]]) -> int:
    """Calculate overall queue health score (0-100)."""
    score = 100

    current_queues = current['queues']

    # Deduct points for queue lengths
    total_queued = sum(current_queues.values())
    if total_queued > 200:
        score -= 50  # Critical
    elif total_queued > 100:
        score -= 30  # Warning
    elif total_queued > 50:
        score -= 15  # Caution

    # Deduct points for specific queue issues
    if current_queues.get('live_reporting', 0) > 20:
        score -= 20

    # Deduct points for growth
    if '5min' in historical:
        prev_queues = historical['5min']['queues']
        total_prev = sum(prev_queues.values())
        growth = total_queued - total_prev

        if growth > 20:
            score -= 20  # Rapid growth
        elif growth > 10:
            score -= 10  # Moderate growth

    # Ensure score is in 0-100 range
    return max(0, min(100, score))
