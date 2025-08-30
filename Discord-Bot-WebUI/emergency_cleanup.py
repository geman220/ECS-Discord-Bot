#!/usr/bin/env python3
"""
Emergency Celery Queue Cleanup - Compatible with all Celery versions
Usage: python emergency_cleanup.py
"""

import os
import redis
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Redis connection
REDIS_URL = os.getenv('REDIS_URL', 'redis://redis:6379/0')
redis_client = redis.from_url(REDIS_URL)

def emergency_queue_purge():
    """Emergency purge of all Celery queues using Redis directly"""
    print("=" * 80)
    print("EMERGENCY CELERY QUEUE CLEANUP")
    print("=" * 80)
    print(f"Timestamp: {datetime.now()}")
    print(f"Redis URL: {REDIS_URL}")
    print()
    
    try:
        # Get initial queue lengths
        celery_len = redis_client.llen('celery')
        live_reporting_len = redis_client.llen('live_reporting')
        total_before = celery_len + live_reporting_len
        
        print(f"📊 BEFORE CLEANUP:")
        print(f"  celery queue: {celery_len} messages")
        print(f"  live_reporting queue: {live_reporting_len} messages")
        print(f"  Total: {total_before} messages")
        print()
        
        if total_before == 0:
            print("✅ Queues are already empty - no cleanup needed")
            return
        
        # Confirm cleanup
        print("⚠️  WARNING: This will DELETE ALL tasks in these queues:")
        print("  - All pending match threads")
        print("  - All live reporting tasks") 
        print("  - All scheduled messages")
        print("  - All other queued tasks")
        print()
        
        response = input("Are you sure you want to continue? Type 'YES DELETE ALL' to proceed: ")
        if response != 'YES DELETE ALL':
            print("❌ Cleanup cancelled")
            return
        
        print("\n🧹 PURGING QUEUES...")
        
        # Delete all queue contents
        queues_to_clear = [
            'celery',
            'live_reporting', 
            'match_management',
            'discord_tasks',
            'scheduled_tasks'
        ]
        
        total_cleared = 0
        for queue in queues_to_clear:
            length_before = redis_client.llen(queue)
            if length_before > 0:
                redis_client.delete(queue)
                print(f"  ✅ Cleared {queue}: {length_before} messages")
                total_cleared += length_before
            else:
                print(f"  ➖ {queue}: already empty")
        
        # Clear task metadata
        print("\n🗑️  CLEARING TASK METADATA...")
        task_keys = redis_client.keys('celery-task-meta-*')
        if task_keys:
            for key in task_keys:
                redis_client.delete(key)
            print(f"  ✅ Cleared {len(task_keys)} task metadata entries")
        else:
            print("  ➖ No task metadata to clear")
        
        # Clear beat schedule
        print("\n📅 CLEARING CELERYBEAT SCHEDULE...")
        schedule_keys = [
            'celerybeat-schedule',
            'celerybeat-last-run'
        ]
        
        cleared_schedule = 0
        for key in schedule_keys:
            if redis_client.exists(key):
                redis_client.delete(key)
                cleared_schedule += 1
        
        if cleared_schedule > 0:
            print(f"  ✅ Cleared {cleared_schedule} schedule entries")
        else:
            print("  ➖ No schedule to clear")
        
        # Clear any locks
        print("\n🔒 CLEARING LOCKS...")
        lock_patterns = ['lock:*', '*-lock', 'celery-task-lock-*']
        total_locks = 0
        
        for pattern in lock_patterns:
            lock_keys = redis_client.keys(pattern)
            for key in lock_keys:
                redis_client.delete(key)
                total_locks += 1
        
        if total_locks > 0:
            print(f"  ✅ Cleared {total_locks} locks")
        else:
            print("  ➖ No locks to clear")
        
        print("\n" + "=" * 80)
        print("✅ EMERGENCY CLEANUP COMPLETE")
        print("=" * 80)
        print(f"📊 SUMMARY:")
        print(f"  Total messages cleared: {total_cleared}")
        print(f"  Task metadata cleared: {len(task_keys) if task_keys else 0}")
        print(f"  Schedule entries cleared: {cleared_schedule}")
        print(f"  Locks cleared: {total_locks}")
        print()
        print("🔄 NEXT STEPS:")
        print("1. Restart celery services:")
        print("   docker restart ecs-discord-bot-celery-beat-1")
        print("   docker restart ecs-discord-bot-celery-worker-1") 
        print("   docker restart ecs-discord-bot-celery-live-reporting-worker-1")
        print()
        print("2. Verify cleanup:")
        print("   python diagnose_celery_tasks.py")
        print()
        print("3. Force run your missing match thread:")
        print("   python clear_stuck_tasks.py --force-match-thread ESPN_MATCH_ID")
        print()
        
    except Exception as e:
        logger.error(f"Error during emergency cleanup: {e}")
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    emergency_queue_purge()