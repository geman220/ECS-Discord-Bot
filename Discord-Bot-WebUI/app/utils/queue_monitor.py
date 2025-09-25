#!/usr/bin/env python3
"""
Queue Health Monitor and Auto-Recovery

Monitors queue sizes and automatically takes action when queues get backed up.
"""

import logging
import redis
from typing import Dict, Any
from datetime import datetime, timedelta

from app.services.redis_connection_service import get_redis_service

logger = logging.getLogger(__name__)


class QueueMonitor:
    """Monitor and maintain healthy queue sizes."""

    # Queue thresholds - when to take action
    QUEUE_THRESHOLDS = {
        'celery': {
            'warning': 100,    # Log warning
            'critical': 200,   # Auto-purge oldest tasks
            'emergency': 500   # Emergency purge
        },
        'live_reporting': {
            'warning': 10,
            'critical': 50,
            'emergency': 100
        },
        'discord': {
            'warning': 150,
            'critical': 300,
            'emergency': 600
        },
        'player_sync': {
            'warning': 50,
            'critical': 100,
            'emergency': 200
        }
    }

    def __init__(self):
        self.redis = get_redis_service()

    def check_queue_health(self) -> Dict[str, Any]:
        """Check health of all queues and take corrective action."""

        results = {
            'timestamp': datetime.utcnow().isoformat(),
            'queues': {},
            'actions_taken': [],
            'alerts': []
        }

        for queue_name, thresholds in self.QUEUE_THRESHOLDS.items():
            try:
                queue_size = self.redis.execute_command('LLEN', queue_name)
                queue_info = {
                    'size': queue_size,
                    'status': 'healthy'
                }

                if queue_size >= thresholds['emergency']:
                    queue_info['status'] = 'emergency'
                    action = self._emergency_purge(queue_name, queue_size)
                    results['actions_taken'].append(action)
                    results['alerts'].append(f"EMERGENCY: Queue {queue_name} had {queue_size} tasks - emergency purge executed")

                elif queue_size >= thresholds['critical']:
                    queue_info['status'] = 'critical'
                    action = self._critical_cleanup(queue_name, queue_size)
                    results['actions_taken'].append(action)
                    results['alerts'].append(f"CRITICAL: Queue {queue_name} has {queue_size} tasks - cleanup initiated")

                elif queue_size >= thresholds['warning']:
                    queue_info['status'] = 'warning'
                    results['alerts'].append(f"WARNING: Queue {queue_name} has {queue_size} tasks - monitoring closely")

                results['queues'][queue_name] = queue_info

            except Exception as e:
                logger.error(f"Error checking queue {queue_name}: {e}")
                results['queues'][queue_name] = {
                    'size': -1,
                    'status': 'error',
                    'error': str(e)
                }

        return results

    def _emergency_purge(self, queue_name: str, current_size: int) -> Dict[str, Any]:
        """Emergency purge - remove 80% of tasks from queue."""
        try:
            # Keep only the newest 20% of tasks
            keep_count = int(current_size * 0.2)

            # Get the newest tasks
            newest_tasks = self.redis.execute_command('LRANGE', queue_name, 0, keep_count - 1)

            # Clear the entire queue
            self.redis.execute_command('DEL', queue_name)

            # Re-add only the newest tasks
            if newest_tasks:
                for task in reversed(newest_tasks):  # Add in reverse to maintain order
                    self.redis.execute_command('LPUSH', queue_name, task)

            purged_count = current_size - keep_count
            logger.critical(f"EMERGENCY PURGE: Removed {purged_count} tasks from {queue_name}, kept {keep_count}")

            return {
                'action': 'emergency_purge',
                'queue': queue_name,
                'original_size': current_size,
                'purged_count': purged_count,
                'remaining_count': keep_count,
                'timestamp': datetime.utcnow().isoformat()
            }

        except Exception as e:
            logger.error(f"Error during emergency purge of {queue_name}: {e}")
            return {
                'action': 'emergency_purge_failed',
                'queue': queue_name,
                'error': str(e),
                'timestamp': datetime.utcnow().isoformat()
            }

    def _critical_cleanup(self, queue_name: str, current_size: int) -> Dict[str, Any]:
        """Critical cleanup - remove expired and old tasks."""
        try:
            removed_count = 0

            # Get all tasks and check expiration
            tasks = self.redis.execute_command('LRANGE', queue_name, 0, -1)
            valid_tasks = []

            import json
            now = datetime.utcnow()

            for task_data in tasks:
                try:
                    task = json.loads(task_data)
                    headers = task.get('headers', {})
                    expires = headers.get('expires')

                    # Remove expired tasks
                    if expires:
                        expire_time = datetime.fromisoformat(expires.replace('Z', '+00:00').replace('+00:00', ''))
                        if expire_time < now:
                            removed_count += 1
                            continue

                    valid_tasks.append(task_data)

                except Exception:
                    # Remove malformed tasks
                    removed_count += 1
                    continue

            # If still too many tasks, keep only newest 50%
            if len(valid_tasks) > self.QUEUE_THRESHOLDS[queue_name]['warning']:
                keep_count = len(valid_tasks) // 2
                valid_tasks = valid_tasks[:keep_count]
                removed_count += (current_size - keep_count)

            # Replace queue contents
            self.redis.execute_command('DEL', queue_name)
            if valid_tasks:
                for task in reversed(valid_tasks):
                    self.redis.execute_command('LPUSH', queue_name, task)

            logger.warning(f"CRITICAL CLEANUP: Removed {removed_count} tasks from {queue_name}")

            return {
                'action': 'critical_cleanup',
                'queue': queue_name,
                'original_size': current_size,
                'removed_count': removed_count,
                'remaining_count': len(valid_tasks),
                'timestamp': datetime.utcnow().isoformat()
            }

        except Exception as e:
            logger.error(f"Error during critical cleanup of {queue_name}: {e}")
            return {
                'action': 'critical_cleanup_failed',
                'queue': queue_name,
                'error': str(e),
                'timestamp': datetime.utcnow().isoformat()
            }

    def get_queue_summary(self) -> Dict[str, Any]:
        """Get a summary of all queue sizes."""
        summary = {
            'timestamp': datetime.utcnow().isoformat(),
            'total_tasks': 0,
            'queues': {}
        }

        for queue_name in self.QUEUE_THRESHOLDS.keys():
            try:
                size = self.redis.execute_command('LLEN', queue_name)
                summary['queues'][queue_name] = size
                summary['total_tasks'] += size
            except Exception as e:
                summary['queues'][queue_name] = f"error: {e}"

        return summary


# Global instance
queue_monitor = QueueMonitor()