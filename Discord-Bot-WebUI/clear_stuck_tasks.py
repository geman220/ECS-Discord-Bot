#!/usr/bin/env python3
"""
Clear Stuck Celery Tasks and Fix Queue Issues
Usage: python clear_stuck_tasks.py [--purge-all] [--restart-beat] [--clear-locks] [--force-match-thread MATCH_ID]
"""

import os
import sys
import json
import argparse
from datetime import datetime, timedelta
from celery import Celery
# Removed deprecated import - using app.control.purge() instead
import redis
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
app = Celery('tasks', broker=REDIS_URL, backend=REDIS_URL)
redis_client = redis.from_url(REDIS_URL)

def purge_queue(queue_name='celery'):
    """Purge all tasks from a specific queue"""
    try:
        app.control.purge()
        logger.info(f"Purged all tasks from queue: {queue_name}")
        return True
    except Exception as e:
        logger.error(f"Error purging queue {queue_name}: {e}")
        return False

def revoke_task(task_id, terminate=True):
    """Revoke a specific task"""
    try:
        app.control.revoke(task_id, terminate=terminate)
        logger.info(f"Revoked task: {task_id}")
        return True
    except Exception as e:
        logger.error(f"Error revoking task {task_id}: {e}")
        return False

def clear_stuck_match_tasks():
    """Clear stuck match management tasks"""
    cleared_count = 0
    
    try:
        # Get all task keys
        task_keys = redis_client.keys('celery-task-meta-*')
        
        for key in task_keys:
            try:
                task_data = redis_client.get(key)
                if task_data:
                    task_info = json.loads(task_data)
                    task_name = task_info.get('name', '')
                    
                    # Check if it's a match-related task
                    if ('match' in task_name.lower() or 
                        'thread' in task_name.lower() or 
                        'force_create_mls_thread' in task_name.lower() or
                        'live_reporting' in task_name.lower()):
                        
                        task_id = key.decode('utf-8').replace('celery-task-meta-', '')
                        status = task_info.get('status')
                        
                        # If task is stuck (PENDING for too long or RETRY)
                        if status in ['PENDING', 'RETRY']:
                            logger.info(f"Found stuck match task: {task_id} ({task_name}) - Status: {status}")
                            
                            # Revoke the task
                            revoke_task(task_id)
                            
                            # Delete the task metadata
                            redis_client.delete(key)
                            cleared_count += 1
                            
            except Exception as e:
                logger.error(f"Error processing task key {key}: {e}")
                
    except Exception as e:
        logger.error(f"Error clearing stuck tasks: {e}")
    
    logger.info(f"Cleared {cleared_count} stuck match tasks")
    return cleared_count

def restart_celerybeat():
    """Clear celerybeat schedule to force restart"""
    try:
        # Clear the schedule
        redis_client.delete('celerybeat-schedule')
        redis_client.delete('celerybeat-last-run')
        
        # Clear any scheduled message keys
        scheduled_keys = redis_client.keys('scheduled_*')
        for key in scheduled_keys:
            redis_client.delete(key)
        
        logger.info("Cleared celerybeat schedule - it will rebuild on restart")
        return True
    except Exception as e:
        logger.error(f"Error clearing celerybeat schedule: {e}")
        return False

def clear_redis_locks():
    """Clear any Redis locks that might be stuck"""
    try:
        # Clear various types of locks
        lock_patterns = ['lock:*', 'celery-task-lock-*', 'thread-creation-*', 'match-*-lock']
        total_cleared = 0
        
        for pattern in lock_patterns:
            lock_keys = redis_client.keys(pattern)
            for key in lock_keys:
                redis_client.delete(key)
                logger.info(f"Cleared lock: {key.decode('utf-8')}")
                total_cleared += 1
        
        logger.info(f"Cleared {total_cleared} total locks")
        return True
    except Exception as e:
        logger.error(f"Error clearing locks: {e}")
        return False

def inspect_and_clear_reserved():
    """Inspect and optionally clear reserved tasks"""
    try:
        inspect = app.control.inspect()
        reserved = inspect.reserved()
        
        if reserved:
            total_reserved = sum(len(tasks) for tasks in reserved.values())
            logger.info(f"Found {total_reserved} reserved tasks across workers")
            
            # Clear reserved tasks from each worker
            for worker, tasks in reserved.items():
                logger.info(f"Worker {worker} has {len(tasks)} reserved tasks")
                for task in tasks:
                    task_id = task.get('id')
                    task_name = task.get('name', '')
                    
                    # Focus on match-related tasks
                    if ('match' in task_name.lower() or 
                        'thread' in task_name.lower() or 
                        'force_create_mls_thread' in task_name.lower()):
                        logger.info(f"Revoking reserved match task: {task_id} ({task_name})")
                        revoke_task(task_id)
        else:
            logger.info("No reserved tasks found")
            
    except Exception as e:
        logger.error(f"Error inspecting reserved tasks: {e}")

def force_run_match_thread_task(match_id=None):
    """Force run a match thread creation task"""
    try:
        # Try to import the task
        try:
            from app.tasks.tasks_live_reporting import force_create_mls_thread_task
        except ImportError:
            try:
                from app.tasks.tasks_match_updates import create_match_thread
                force_create_mls_thread_task = create_match_thread
            except ImportError:
                logger.error("Could not import match thread task - check import paths")
                return None
        
        if match_id:
            logger.info(f"Force running match thread creation for match_id: {match_id}")
            result = force_create_mls_thread_task.apply_async(
                args=[match_id], 
                queue='live_reporting',
                priority=9
            )
            logger.info(f"Task submitted with ID: {result.id}")
            return result.id
        else:
            logger.info("No match_id provided, skipping force run")
            return None
    except Exception as e:
        logger.error(f"Error forcing match thread task: {e}")
        return None

def clear_failed_tasks():
    """Clear failed tasks from Redis"""
    cleared_count = 0
    try:
        task_keys = redis_client.keys('celery-task-meta-*')
        
        for key in task_keys:
            try:
                task_data = redis_client.get(key)
                if task_data:
                    task_info = json.loads(task_data)
                    status = task_info.get('status')
                    
                    # Clear FAILURE, RETRY, or old PENDING tasks
                    if status in ['FAILURE', 'RETRY']:
                        task_id = key.decode('utf-8').replace('celery-task-meta-', '')
                        logger.info(f"Clearing failed task: {task_id} (Status: {status})")
                        redis_client.delete(key)
                        cleared_count += 1
            except Exception as e:
                pass
                
    except Exception as e:
        logger.error(f"Error clearing failed tasks: {e}")
    
    logger.info(f"Cleared {cleared_count} failed tasks")
    return cleared_count

def check_worker_connectivity():
    """Check if workers are responding"""
    try:
        inspect = app.control.inspect()
        
        # Ping workers
        pong = inspect.ping()
        if pong:
            logger.info(f"Workers responding: {list(pong.keys())}")
            return True
        else:
            logger.error("No workers responding to ping")
            return False
    except Exception as e:
        logger.error(f"Error checking worker connectivity: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description='Clear stuck Celery tasks')
    parser.add_argument('--purge-all', action='store_true', 
                       help='Purge all tasks from all queues (DANGEROUS)')
    parser.add_argument('--restart-beat', action='store_true', 
                       help='Clear celerybeat schedule to force restart')
    parser.add_argument('--clear-locks', action='store_true', 
                       help='Clear Redis locks')
    parser.add_argument('--force-match-thread', type=str, 
                       help='Force run match thread for specific match ID')
    parser.add_argument('--clear-reserved', action='store_true', 
                       help='Clear reserved (pending) tasks')
    parser.add_argument('--clear-failed', action='store_true', 
                       help='Clear failed tasks from Redis')
    parser.add_argument('--check-workers', action='store_true', 
                       help='Check worker connectivity')
    
    args = parser.parse_args()
    
    print("=" * 80)
    print("CLEARING STUCK CELERY TASKS")
    print("=" * 80)
    print(f"Timestamp: {datetime.now()}")
    print(f"Redis URL: {REDIS_URL}")
    print()
    
    # Check worker connectivity first
    print("Checking worker connectivity...")
    worker_ok = check_worker_connectivity()
    if not worker_ok:
        print("⚠️  WARNING: Workers not responding - some operations may not work")
    print()
    
    # Clear stuck match tasks (always run this)
    print("Clearing stuck match management tasks...")
    cleared = clear_stuck_match_tasks()
    print(f"Cleared {cleared} stuck match tasks")
    print()
    
    # Clear failed tasks if requested
    if args.clear_failed:
        print("Clearing failed tasks...")
        failed_cleared = clear_failed_tasks()
        print(f"Cleared {failed_cleared} failed tasks")
        print()
    
    # Clear reserved tasks if requested
    if args.clear_reserved:
        print("Inspecting and clearing reserved tasks...")
        inspect_and_clear_reserved()
        print()
    
    # Clear locks if requested
    if args.clear_locks:
        print("Clearing Redis locks...")
        clear_redis_locks()
        print()
    
    # Restart beat if requested
    if args.restart_beat:
        print("Clearing celerybeat schedule...")
        restart_celerybeat()
        print("⚠️  Remember to restart celery-beat container after this!")
        print()
    
    # Force run match thread if requested
    if args.force_match_thread:
        print(f"Force running match thread for match {args.force_match_thread}...")
        task_id = force_run_match_thread_task(args.force_match_thread)
        if task_id:
            print(f"✅ Task submitted: {task_id}")
        else:
            print("❌ Failed to submit task")
        print()
    
    # Purge all if requested (dangerous)
    if args.purge_all:
        print("⚠️  WARNING: About to purge ALL tasks from ALL queues!")
        print("This will clear:")
        print("  - All pending tasks")
        print("  - All scheduled tasks") 
        print("  - All reserved tasks")
        print("  - All task metadata")
        print()
        response = input("Are you absolutely sure? Type 'YES I AM SURE' to continue: ")
        if response == 'YES I AM SURE':
            print("Purging all tasks...")
            purge_queue()
            
            # Also clear Redis task metadata
            task_keys = redis_client.keys('celery-task-meta-*')
            for key in task_keys:
                redis_client.delete(key)
            print(f"Cleared {len(task_keys)} task metadata entries")
        else:
            print("Purge cancelled")
        print()
    
    # Check workers again if requested
    if args.check_workers:
        print("Final worker connectivity check...")
        check_worker_connectivity()
        print()
    
    print("=" * 80)
    print("CLEANUP COMPLETE")
    print("=" * 80)
    print()
    print("Next steps:")
    print("1. Run diagnose_celery_tasks.py to verify cleanup")
    if args.restart_beat:
        print("2. Restart celery-beat container: docker restart celery-beat")
    print("3. Monitor logs for any remaining issues")
    print("4. Check /admin/match_management for stuck matches")
    print()

if __name__ == "__main__":
    main()