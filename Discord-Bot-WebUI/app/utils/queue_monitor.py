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

    # IMPORTANT ordering note: Celery/Kombu LPUSHes new messages at the HEAD
    # (LRANGE index 0) and workers BRPOP from the TAIL. So the tail is the
    # next-to-run work. The previous implementation kept the NEWEST N (head) and
    # deleted the tail — i.e. it threw away the tasks about to execute. That is
    # the "recovery made it worse" bug: a backed-up queue would lose its
    # next-to-run tasks every few minutes. Both methods below now remove ONLY
    # genuinely expired/malformed messages and preserve every valid task in
    # execution order — recovery can no longer drop live work. (Draft-critical
    # tasks are additionally isolated on the unmonitored 'draft' queue.)

    def _prune_expired(self, queue_name: str, current_size: int, action_label: str) -> Dict[str, Any]:
        """Remove only expired + malformed messages; keep all valid tasks in order."""
        try:
            import json
            now = datetime.utcnow()

            # LRANGE returns [head..tail] == [newest..oldest]. Preserve this order.
            tasks = self.redis.execute_command('LRANGE', queue_name, 0, -1)
            valid_tasks = []
            removed_count = 0

            for task_data in tasks:
                try:
                    task = json.loads(task_data)
                    expires = task.get('headers', {}).get('expires')
                    if expires:
                        expire_time = datetime.fromisoformat(
                            expires.replace('Z', '+00:00').replace('+00:00', '')
                        )
                        if expire_time < now:
                            removed_count += 1
                            continue
                    valid_tasks.append(task_data)
                except Exception:
                    # Malformed/unparseable message — safe to drop.
                    removed_count += 1
                    continue

            # Rebuild the queue with the SAME ordering: LPUSH oldest first so the
            # newest ends back at the head (mirrors how Kombu built it).
            self.redis.execute_command('DEL', queue_name)
            for task in reversed(valid_tasks):
                self.redis.execute_command('LPUSH', queue_name, task)

            if len(valid_tasks) > self.QUEUE_THRESHOLDS.get(queue_name, {}).get('warning', 10**9):
                # Deliberately do NOT trim valid tasks — dropping live work is exactly
                # the failure we're preventing. Surface it loudly instead so a human
                # (or the isolated worker topology) resolves the real backlog cause.
                logger.critical(
                    f"{action_label}: {queue_name} still has {len(valid_tasks)} VALID tasks after "
                    f"pruning {removed_count} expired — NOT dropping live work; investigate the backlog source."
                )
            else:
                logger.warning(f"{action_label}: removed {removed_count} expired/malformed tasks from {queue_name}")

            return {
                'action': action_label.lower().replace(' ', '_'),
                'queue': queue_name,
                'original_size': current_size,
                'removed_count': removed_count,
                'remaining_count': len(valid_tasks),
                'timestamp': datetime.utcnow().isoformat()
            }

        except Exception as e:
            logger.error(f"Error during {action_label} of {queue_name}: {e}")
            return {
                'action': f'{action_label.lower().replace(" ", "_")}_failed',
                'queue': queue_name,
                'error': str(e),
                'timestamp': datetime.utcnow().isoformat()
            }

    def _emergency_purge(self, queue_name: str, current_size: int) -> Dict[str, Any]:
        """Emergency: prune expired/malformed only — never drop valid next-to-run tasks."""
        return self._prune_expired(queue_name, current_size, 'EMERGENCY PRUNE')

    def _critical_cleanup(self, queue_name: str, current_size: int) -> Dict[str, Any]:
        """Critical: prune expired/malformed only — never drop valid next-to-run tasks."""
        return self._prune_expired(queue_name, current_size, 'CRITICAL CLEANUP')

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