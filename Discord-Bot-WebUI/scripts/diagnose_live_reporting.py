#!/usr/bin/env python3
"""
Diagnose and Clean Up Live Reporting Issues

This script helps diagnose and fix issues with the live reporting system:
1. Shows status of all live reporting components
2. Identifies stuck tasks and sessions
3. Provides options to clean up problematic tasks
"""

import sys
import os
import argparse
import redis
from datetime import datetime, timedelta

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.models import LiveReportingSession, MLSMatch
from app.services.redis_connection_service import get_redis_service
from app.utils.task_session_manager import task_session
from celery import Celery


def get_redis_client():
    """Get Redis client."""
    redis_url = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
    return redis.from_url(redis_url)


def check_redis_queues():
    """Check Redis queue lengths."""
    print("\n" + "="*60)
    print("REDIS QUEUE STATUS")
    print("="*60)

    r = get_redis_client()

    queues = [
        'celery',
        'live_reporting',
        'live_reporting_queue',
        'discord_queue',
        'player_sync_queue',
        'enterprise_rsvp_queue'
    ]

    for queue in queues:
        try:
            length = r.llen(queue)
            if length > 0:
                print(f"  {queue:<30} {length:>10} tasks")

                # Show sample of first few tasks if queue is backed up
                if length > 10:
                    print(f"    WARNING: Queue appears backed up!")
                    sample = r.lrange(queue, 0, 2)
                    for i, task in enumerate(sample[:3]):
                        try:
                            import json
                            task_data = json.loads(task)
                            task_name = task_data.get('headers', {}).get('task', 'unknown')
                            print(f"      Sample task {i+1}: {task_name}")
                        except:
                            pass
        except Exception as e:
            print(f"  {queue:<30} Error: {e}")

    # Check realtime service status
    try:
        status = r.get('realtime_service:status')
        heartbeat = r.get('realtime_service:heartbeat')
        print(f"\n  Realtime Service Status: {status.decode() if status else 'NOT RUNNING'}")
        if heartbeat:
            print(f"  Last Heartbeat: {heartbeat.decode()}")
    except:
        print(f"\n  Realtime Service Status: NOT RUNNING or ERROR")


def check_active_sessions():
    """Check active live reporting sessions."""
    print("\n" + "="*60)
    print("ACTIVE LIVE REPORTING SESSIONS")
    print("="*60)

    app = create_app()
    with app.app_context():
        with task_session() as session:
            active_sessions = session.query(LiveReportingSession).filter_by(
                is_active=True
            ).all()

            if not active_sessions:
                print("  No active sessions found")
            else:
                print(f"  Found {len(active_sessions)} active session(s):\n")

                now = datetime.utcnow()
                for live_session in active_sessions:
                    print(f"  Session ID: {live_session.id}")
                    print(f"    Match ID: {live_session.match_id}")
                    print(f"    Thread ID: {live_session.thread_id}")
                    print(f"    Started: {live_session.started_at}")
                    print(f"    Last Update: {live_session.last_update}")

                    # Check if session is stale
                    if live_session.last_update:
                        time_since_update = now - live_session.last_update
                        if time_since_update > timedelta(minutes=5):
                            print(f"    ⚠️  WARNING: No update for {time_since_update.total_seconds()/60:.1f} minutes")

                    # Check associated match
                    match = session.query(MLSMatch).filter_by(
                        match_id=live_session.match_id
                    ).first()
                    if match:
                        print(f"    Match Status: {match.live_reporting_status}")
                        print(f"    Task ID: {match.live_reporting_task_id}")

                    print()


def check_celery_tasks():
    """Check active Celery tasks."""
    print("\n" + "="*60)
    print("CELERY TASK STATUS")
    print("="*60)

    try:
        from celery_worker_base import celery_app

        # Get active tasks
        inspect = celery_app.control.inspect()
        active = inspect.active()

        if active:
            for worker, tasks in active.items():
                print(f"\n  Worker: {worker}")
                print(f"  Active Tasks: {len(tasks)}")

                for task in tasks[:5]:  # Show first 5 tasks
                    print(f"    - {task['name']}")
                    print(f"      ID: {task['id']}")
                    print(f"      Args: {task.get('args', [])[:100]}")  # Truncate long args

                    # Check if it's a deprecated task
                    if 'process_match_update' in task['name']:
                        print(f"      ⚠️  WARNING: Deprecated self-scheduling task detected!")
        else:
            print("  No active tasks or unable to connect to workers")

        # Check reserved tasks
        reserved = inspect.reserved()
        if reserved:
            for worker, tasks in reserved.items():
                print(f"\n  Worker: {worker}")
                print(f"  Reserved Tasks: {len(tasks)}")

    except Exception as e:
        print(f"  Error checking Celery tasks: {e}")
        print("  Make sure Celery workers are running")


def cleanup_stuck_tasks(dry_run=True):
    """Clean up stuck tasks and sessions."""
    print("\n" + "="*60)
    print("CLEANUP RECOMMENDATIONS")
    print("="*60)

    if dry_run:
        print("  (DRY RUN - No changes will be made)")

    app = create_app()
    with app.app_context():
        with task_session() as session:
            # Find stale sessions (no update for > 10 minutes)
            now = datetime.utcnow()
            cutoff_time = now - timedelta(minutes=10)

            stale_sessions = session.query(LiveReportingSession).filter(
                LiveReportingSession.is_active == True,
                LiveReportingSession.last_update < cutoff_time
            ).all()

            if stale_sessions:
                print(f"\n  Found {len(stale_sessions)} stale session(s) to clean up:")

                for live_session in stale_sessions:
                    print(f"    - Session {live_session.id} (Match: {live_session.match_id})")

                    if not dry_run:
                        live_session.is_active = False
                        live_session.ended_at = now
                        print(f"      ✓ Deactivated session")

                        # Also update match status
                        match = session.query(MLSMatch).filter_by(
                            match_id=live_session.match_id
                        ).first()
                        if match:
                            match.live_reporting_status = 'stopped'
                            match.live_reporting_started = False
                            match.live_reporting_task_id = None
                            print(f"      ✓ Updated match status")

                if not dry_run:
                    session.commit()
                    print("\n  ✓ Changes committed to database")
            else:
                print("  No stale sessions found")

    # Suggest Redis queue cleanup if needed
    r = get_redis_client()
    queue_length = r.llen('live_reporting')

    if queue_length > 50:
        print(f"\n  ⚠️  Live reporting queue has {queue_length} tasks")
        print("  Recommended action:")
        print("    docker exec <celery-container> celery -A celery_live_reporting_worker purge -Q live_reporting --force")


def main():
    parser = argparse.ArgumentParser(
        description='Diagnose and fix live reporting issues'
    )
    parser.add_argument(
        '--cleanup',
        action='store_true',
        help='Actually perform cleanup (default is dry run)'
    )
    parser.add_argument(
        '--purge-queue',
        action='store_true',
        help='Purge the live reporting queue (DANGEROUS!)'
    )

    args = parser.parse_args()

    print("\n" + "="*60)
    print("LIVE REPORTING DIAGNOSTICS")
    print("="*60)
    print(f"Timestamp: {datetime.utcnow().isoformat()}")

    # Run diagnostics
    check_redis_queues()
    check_active_sessions()
    check_celery_tasks()

    # Cleanup if requested
    cleanup_stuck_tasks(dry_run=not args.cleanup)

    if args.purge_queue:
        print("\n" + "="*60)
        print("QUEUE PURGE")
        print("="*60)

        if input("  Are you sure you want to purge the live_reporting queue? (yes/no): ").lower() == 'yes':
            r = get_redis_client()
            r.delete('live_reporting')
            print("  ✓ Queue purged")
        else:
            print("  Purge cancelled")

    print("\n" + "="*60)
    print("RECOMMENDATIONS")
    print("="*60)
    print("  1. Restart the celery-live-reporting-worker container")
    print("  2. Ensure realtime-live-reporting service is running")
    print("  3. Monitor logs: docker logs -f <container-name>")
    print("  4. Use --cleanup flag to fix stale sessions")
    print("\n")


if __name__ == '__main__':
    main()