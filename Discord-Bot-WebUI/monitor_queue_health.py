#!/usr/bin/env python3
"""
Queue Health Monitor

Monitors Celery queue health over time to ensure the clogging issue is fixed.
Logs metrics to a file and alerts if problematic patterns are detected.

Usage:
    python monitor_queue_health.py [--duration MINUTES] [--interval SECONDS]
"""

import argparse
import time
import json
from datetime import datetime
from pathlib import Path
from app import create_app
from app.core import celery
import redis


class QueueHealthMonitor:
    def __init__(self, log_file='queue_health_monitor.log'):
        self.log_file = Path(log_file)
        self.app = create_app()
        self.redis_client = redis.Redis(host='redis', port=6379, db=0)

    def get_queue_metrics(self):
        """Get current queue metrics."""
        metrics = {
            'timestamp': datetime.utcnow().isoformat(),
            'queues': {},
            'workers': {},
            'alerts': []
        }

        # Get queue lengths from Redis
        for queue_name in ['live_reporting', 'celery', 'discord', 'player_sync']:
            try:
                length = self.redis_client.llen(queue_name)
                metrics['queues'][queue_name] = length
            except Exception as e:
                metrics['queues'][queue_name] = f'ERROR: {str(e)}'

        # Get worker stats from Celery
        try:
            i = celery.control.inspect()

            # Active tasks
            active = i.active()
            if active:
                for worker, tasks in active.items():
                    if worker not in metrics['workers']:
                        metrics['workers'][worker] = {}
                    metrics['workers'][worker]['active'] = len(tasks)

            # Scheduled tasks
            scheduled = i.scheduled()
            if scheduled:
                for worker, tasks in scheduled.items():
                    if worker not in metrics['workers']:
                        metrics['workers'][worker] = {}
                    metrics['workers'][worker]['scheduled'] = len(tasks)

            # Reserved tasks
            reserved = i.reserved()
            if reserved:
                for worker, tasks in reserved.items():
                    if worker not in metrics['workers']:
                        metrics['workers'][worker] = {}
                    metrics['workers'][worker]['reserved'] = len(tasks)

        except Exception as e:
            metrics['workers']['error'] = str(e)

        # Check for problematic patterns
        metrics['alerts'] = self._check_for_issues(metrics)

        return metrics

    def _check_for_issues(self, metrics):
        """Check for problematic patterns that indicate clogging."""
        alerts = []

        # Alert if queue lengths exceed thresholds
        thresholds = {
            'live_reporting': 20,  # Should be nearly empty
            'celery': 100,
            'discord': 50,
            'player_sync': 50
        }

        for queue, threshold in thresholds.items():
            length = metrics['queues'].get(queue, 0)
            if isinstance(length, int) and length > threshold:
                alerts.append({
                    'severity': 'WARNING',
                    'queue': queue,
                    'message': f'Queue {queue} has {length} tasks (threshold: {threshold})'
                })

        # Alert if queue is growing rapidly
        if hasattr(self, 'last_metrics'):
            for queue in ['live_reporting', 'celery', 'discord']:
                current = metrics['queues'].get(queue, 0)
                previous = self.last_metrics['queues'].get(queue, 0)

                if isinstance(current, int) and isinstance(previous, int):
                    growth = current - previous
                    if growth > 10:  # Growing by >10 tasks per interval
                        alerts.append({
                            'severity': 'CRITICAL',
                            'queue': queue,
                            'message': f'Queue {queue} growing rapidly: +{growth} tasks'
                        })

        # Alert if total queue size is excessive
        total_queued = sum(
            v for v in metrics['queues'].values()
            if isinstance(v, int)
        )
        if total_queued > 200:
            alerts.append({
                'severity': 'CRITICAL',
                'message': f'Total queued tasks: {total_queued} (excessive)'
            })

        return alerts

    def log_metrics(self, metrics):
        """Log metrics to file."""
        with open(self.log_file, 'a') as f:
            f.write(json.dumps(metrics) + '\n')

    def print_summary(self, metrics):
        """Print a human-readable summary."""
        print(f"\n{'='*60}")
        print(f"Queue Health Check - {metrics['timestamp']}")
        print(f"{'='*60}")

        print("\nQueue Lengths:")
        for queue, length in metrics['queues'].items():
            status = '✓' if isinstance(length, int) and length < 20 else '⚠'
            print(f"  {status} {queue:20} {length:>5}")

        print("\nWorker Status:")
        for worker, stats in metrics['workers'].items():
            if isinstance(stats, dict):
                active = stats.get('active', 0)
                scheduled = stats.get('scheduled', 0)
                reserved = stats.get('reserved', 0)
                print(f"  {worker[:40]:40} A:{active:>3} S:{scheduled:>3} R:{reserved:>3}")

        if metrics['alerts']:
            print("\n⚠️  ALERTS:")
            for alert in metrics['alerts']:
                severity = alert.get('severity', 'INFO')
                message = alert.get('message', 'Unknown alert')
                queue = alert.get('queue', '')
                print(f"  [{severity}] {queue} {message}")
        else:
            print("\n✅ No alerts - queues are healthy")

        # Calculate growth rate if we have previous data
        if hasattr(self, 'last_metrics'):
            total_current = sum(v for v in metrics['queues'].values() if isinstance(v, int))
            total_previous = sum(v for v in self.last_metrics['queues'].values() if isinstance(v, int))
            growth = total_current - total_previous

            time_diff = (
                datetime.fromisoformat(metrics['timestamp']) -
                datetime.fromisoformat(self.last_metrics['timestamp'])
            ).total_seconds()

            if time_diff > 0:
                growth_rate = (growth / time_diff) * 60  # Tasks per minute
                print(f"\nGrowth Rate: {growth_rate:+.2f} tasks/minute")

                if growth_rate > 2:
                    print("  ⚠️  WARNING: Positive growth rate detected!")
                elif growth_rate < -2:
                    print("  ✓ Queue is draining")
                else:
                    print("  ✓ Queue is stable")

    def monitor(self, duration_minutes=60, interval_seconds=30):
        """Monitor queue health for a specified duration."""
        print(f"Starting queue health monitoring...")
        print(f"Duration: {duration_minutes} minutes")
        print(f"Interval: {interval_seconds} seconds")
        print(f"Log file: {self.log_file}")

        end_time = time.time() + (duration_minutes * 60)
        iteration = 0

        try:
            while time.time() < end_time:
                iteration += 1

                # Get and log metrics
                metrics = self.get_queue_metrics()
                self.log_metrics(metrics)
                self.print_summary(metrics)

                # Store for growth rate calculation
                self.last_metrics = metrics

                # Sleep until next check
                if time.time() < end_time:
                    print(f"\nWaiting {interval_seconds}s until next check...")
                    time.sleep(interval_seconds)

            print(f"\n{'='*60}")
            print("Monitoring complete!")
            print(f"Total iterations: {iteration}")
            print(f"Log saved to: {self.log_file}")

            # Final analysis
            self.analyze_log()

        except KeyboardInterrupt:
            print("\n\nMonitoring interrupted by user")
            print(f"Partial log saved to: {self.log_file}")

    def analyze_log(self):
        """Analyze the log file for trends."""
        print(f"\n{'='*60}")
        print("Analysis of Monitoring Session")
        print(f"{'='*60}")

        if not self.log_file.exists():
            print("No log file found")
            return

        with open(self.log_file, 'r') as f:
            lines = f.readlines()

        if len(lines) < 2:
            print("Insufficient data for analysis")
            return

        # Parse all metrics
        all_metrics = [json.loads(line) for line in lines]

        # Calculate average queue lengths
        print("\nAverage Queue Lengths:")
        queue_totals = {}
        for metrics in all_metrics:
            for queue, length in metrics['queues'].items():
                if isinstance(length, int):
                    if queue not in queue_totals:
                        queue_totals[queue] = []
                    queue_totals[queue].append(length)

        for queue, lengths in queue_totals.items():
            avg = sum(lengths) / len(lengths)
            max_val = max(lengths)
            min_val = min(lengths)
            print(f"  {queue:20} avg:{avg:>6.1f}  min:{min_val:>5}  max:{max_val:>5}")

        # Check if queues are growing
        print("\nGrowth Analysis:")
        for queue in ['live_reporting', 'celery', 'discord']:
            lengths = queue_totals.get(queue, [])
            if len(lengths) >= 2:
                start = lengths[0]
                end = lengths[-1]
                growth = end - start

                if growth > 50:
                    print(f"  ❌ {queue}: GROWING (+{growth} tasks) - ISSUE NOT FIXED")
                elif growth > 10:
                    print(f"  ⚠️  {queue}: Slight growth (+{growth} tasks) - Monitor closely")
                elif growth < -10:
                    print(f"  ✅ {queue}: Draining ({growth} tasks) - Healthy")
                else:
                    print(f"  ✅ {queue}: Stable ({growth:+d} tasks) - Healthy")

        # Count alerts
        total_alerts = sum(len(m.get('alerts', [])) for m in all_metrics)
        critical_alerts = sum(
            sum(1 for a in m.get('alerts', []) if a.get('severity') == 'CRITICAL')
            for m in all_metrics
        )

        print(f"\nAlert Summary:")
        print(f"  Total alerts: {total_alerts}")
        print(f"  Critical alerts: {critical_alerts}")

        if critical_alerts > 0:
            print(f"\n❌ CRITICAL ALERTS DETECTED - Issue may not be fully fixed!")
        elif total_alerts > 0:
            print(f"\n⚠️  Some warnings detected - Monitor recommended")
        else:
            print(f"\n✅ No alerts - System is healthy!")


def main():
    parser = argparse.ArgumentParser(description='Monitor Celery queue health')
    parser.add_argument(
        '--duration',
        type=int,
        default=60,
        help='Monitoring duration in minutes (default: 60)'
    )
    parser.add_argument(
        '--interval',
        type=int,
        default=30,
        help='Check interval in seconds (default: 30)'
    )
    parser.add_argument(
        '--log-file',
        type=str,
        default='queue_health_monitor.log',
        help='Log file path (default: queue_health_monitor.log)'
    )

    args = parser.parse_args()

    monitor = QueueHealthMonitor(log_file=args.log_file)
    monitor.monitor(
        duration_minutes=args.duration,
        interval_seconds=args.interval
    )


if __name__ == '__main__':
    main()
