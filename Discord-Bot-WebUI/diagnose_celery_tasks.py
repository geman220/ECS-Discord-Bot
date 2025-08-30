#!/usr/bin/env python3
"""
Celery Task Queue Diagnostic Tool
Usage: python diagnose_celery_tasks.py
"""

import os
import sys
import json
from datetime import datetime, timedelta
from celery import Celery
from kombu import Connection
import redis
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Initialize Celery app (adjust broker URL as needed)
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
app = Celery('tasks', broker=REDIS_URL, backend=REDIS_URL)

# Redis client for direct access
redis_client = redis.from_url(REDIS_URL)

def get_queue_stats():
    """Get statistics for all Celery queues"""
    stats = {}
    
    try:
        with Connection(REDIS_URL) as conn:
            with conn.channel() as channel:
                # Check default celery queue
                queue = channel.queue_declare(queue='celery', passive=True)
                stats['celery'] = {
                    'message_count': queue.message_count,
                    'consumer_count': queue.consumer_count
                }
                
                # Check other common queues
                for queue_name in ['match_management', 'discord_tasks', 'scheduled_tasks', 'live_reporting']:
                    try:
                        queue = channel.queue_declare(queue=queue_name, passive=True)
                        stats[queue_name] = {
                            'message_count': queue.message_count,
                            'consumer_count': queue.consumer_count
                        }
                    except:
                        stats[queue_name] = {'message_count': 0, 'consumer_count': 0}
    except Exception as e:
        logger.error(f"Error getting queue stats: {e}")
    
    return stats

def get_active_tasks():
    """Get currently active tasks"""
    active_tasks = []
    
    try:
        # Get active tasks from Celery
        inspect = app.control.inspect()
        active = inspect.active()
        
        if active:
            for worker, tasks in active.items():
                for task in tasks:
                    active_tasks.append({
                        'worker': worker,
                        'task_id': task.get('id'),
                        'name': task.get('name'),
                        'args': task.get('args'),
                        'kwargs': task.get('kwargs'),
                        'time_start': task.get('time_start')
                    })
    except Exception as e:
        logger.error(f"Error getting active tasks: {e}")
    
    return active_tasks

def get_scheduled_tasks():
    """Get scheduled tasks from Redis"""
    scheduled_tasks = []
    
    try:
        # Check for scheduled tasks in Redis
        scheduled_keys = redis_client.keys('celery-task-meta-*')
        
        for key in scheduled_keys[:100]:  # Limit to first 100 for performance
            try:
                task_data = redis_client.get(key)
                if task_data:
                    task_info = json.loads(task_data)
                    scheduled_tasks.append({
                        'task_id': key.decode('utf-8').replace('celery-task-meta-', ''),
                        'status': task_info.get('status'),
                        'result': task_info.get('result'),
                        'traceback': task_info.get('traceback')
                    })
            except:
                pass
    except Exception as e:
        logger.error(f"Error getting scheduled tasks: {e}")
    
    return scheduled_tasks

def get_reserved_tasks():
    """Get reserved (pending) tasks"""
    reserved_tasks = []
    
    try:
        inspect = app.control.inspect()
        reserved = inspect.reserved()
        
        if reserved:
            for worker, tasks in reserved.items():
                for task in tasks:
                    reserved_tasks.append({
                        'worker': worker,
                        'task_id': task.get('id'),
                        'name': task.get('name'),
                        'args': task.get('args'),
                        'kwargs': task.get('kwargs')
                    })
    except Exception as e:
        logger.error(f"Error getting reserved tasks: {e}")
    
    return reserved_tasks

def find_match_management_tasks():
    """Find all match management related tasks"""
    match_tasks = []
    
    # Check active tasks
    active = get_active_tasks()
    for task in active:
        if 'match' in task.get('name', '').lower() or 'thread' in task.get('name', '').lower():
            task['status'] = 'ACTIVE'
            match_tasks.append(task)
    
    # Check reserved tasks
    reserved = get_reserved_tasks()
    for task in reserved:
        if 'match' in task.get('name', '').lower() or 'thread' in task.get('name', '').lower():
            task['status'] = 'RESERVED'
            match_tasks.append(task)
    
    return match_tasks

def check_celerybeat_schedule():
    """Check CeleryBeat schedule from Redis"""
    schedule_info = {}
    
    try:
        # Check for celerybeat schedule
        schedule_key = redis_client.get('celerybeat-schedule')
        if schedule_key:
            logger.info("Found celerybeat schedule in Redis")
            schedule_info['has_schedule'] = True
        else:
            logger.warning("No celerybeat schedule found in Redis")
            schedule_info['has_schedule'] = False
            
        # Check last run time
        last_run = redis_client.get('celerybeat-last-run')
        if last_run:
            schedule_info['last_run'] = last_run.decode('utf-8')
        else:
            schedule_info['last_run'] = None
            
    except Exception as e:
        logger.error(f"Error checking celerybeat schedule: {e}")
    
    return schedule_info

def get_worker_stats():
    """Get worker statistics"""
    worker_stats = {}
    
    try:
        inspect = app.control.inspect()
        stats = inspect.stats()
        
        if stats:
            for worker, stat in stats.items():
                worker_stats[worker] = {
                    'total_tasks': stat.get('total', {}),
                    'pool': stat.get('pool', {}),
                    'rusage': stat.get('rusage', {})
                }
    except Exception as e:
        logger.error(f"Error getting worker stats: {e}")
    
    return worker_stats

def check_stuck_tasks():
    """Check for potentially stuck tasks"""
    stuck_tasks = []
    
    try:
        # Check for tasks that have been pending for too long
        task_keys = redis_client.keys('celery-task-meta-*')
        current_time = datetime.now()
        
        for key in task_keys[:100]:  # Limit to first 100
            try:
                task_data = redis_client.get(key)
                if task_data:
                    task_info = json.loads(task_data)
                    status = task_info.get('status')
                    
                    # Check if task is stuck in PENDING or RETRY
                    if status in ['PENDING', 'RETRY']:
                        task_id = key.decode('utf-8').replace('celery-task-meta-', '')
                        stuck_tasks.append({
                            'task_id': task_id,
                            'status': status,
                            'name': task_info.get('name', 'Unknown')
                        })
            except Exception as e:
                pass
                
    except Exception as e:
        logger.error(f"Error checking stuck tasks: {e}")
    
    return stuck_tasks

def main():
    print("=" * 80)
    print("CELERY TASK QUEUE DIAGNOSTICS")
    print("=" * 80)
    print(f"Timestamp: {datetime.now()}")
    print(f"Redis URL: {REDIS_URL}")
    print()
    
    # Queue Statistics
    print("QUEUE STATISTICS:")
    print("-" * 40)
    queue_stats = get_queue_stats()
    total_messages = 0
    for queue_name, stats in queue_stats.items():
        print(f"  {queue_name}:")
        print(f"    Messages: {stats['message_count']}")
        print(f"    Consumers: {stats['consumer_count']}")
        total_messages += stats['message_count']
    print(f"\n  Total Messages in Queues: {total_messages}")
    print()
    
    # Worker Statistics
    print("WORKER STATISTICS:")
    print("-" * 40)
    worker_stats = get_worker_stats()
    if worker_stats:
        for worker, stats in worker_stats.items():
            print(f"  {worker}:")
            print(f"    Pool: {stats.get('pool', {}).get('max-concurrency', 'N/A')} workers")
            total = stats.get('total', {})
            if total:
                print(f"    Total tasks processed: {sum(total.values())}")
    else:
        print("  No workers found or workers not responding")
    print()
    
    # Active Tasks
    print("ACTIVE TASKS:")
    print("-" * 40)
    active_tasks = get_active_tasks()
    if active_tasks:
        print(f"  Total active tasks: {len(active_tasks)}")
        for task in active_tasks[:10]:  # Show first 10
            print(f"  Task: {task['name']}")
            print(f"    ID: {task['task_id']}")
            print(f"    Worker: {task['worker']}")
            print(f"    Started: {task.get('time_start', 'Unknown')}")
            print()
    else:
        print("  No active tasks")
    print()
    
    # Reserved Tasks
    print("RESERVED (PENDING) TASKS:")
    print("-" * 40)
    reserved_tasks = get_reserved_tasks()
    if reserved_tasks:
        print(f"  Total reserved tasks: {len(reserved_tasks)}")
        for task in reserved_tasks[:10]:  # Show first 10
            print(f"  Task: {task['name']}")
            print(f"    ID: {task['task_id']}")
            print(f"    Worker: {task['worker']}")
            print()
    else:
        print("  No reserved tasks")
    print()
    
    # Stuck Tasks
    print("POTENTIALLY STUCK TASKS:")
    print("-" * 40)
    stuck_tasks = check_stuck_tasks()
    if stuck_tasks:
        print(f"  Found {len(stuck_tasks)} potentially stuck tasks")
        for task in stuck_tasks[:10]:  # Show first 10
            print(f"  Task ID: {task['task_id']}")
            print(f"    Status: {task['status']}")
            print(f"    Name: {task['name']}")
            print()
    else:
        print("  No stuck tasks detected")
    print()
    
    # Match Management Tasks
    print("MATCH MANAGEMENT TASKS:")
    print("-" * 40)
    match_tasks = find_match_management_tasks()
    if match_tasks:
        print(f"  Found {len(match_tasks)} match-related tasks")
        for task in match_tasks:
            print(f"  Task: {task['name']}")
            print(f"    ID: {task['task_id']}")
            print(f"    Status: {task['status']}")
            print(f"    Args: {task.get('args', [])}")
            print(f"    Kwargs: {task.get('kwargs', {})}")
            print()
    else:
        print("  No match management tasks found")
    print()
    
    # CeleryBeat Schedule
    print("CELERYBEAT SCHEDULE:")
    print("-" * 40)
    schedule_info = check_celerybeat_schedule()
    print(f"  Schedule exists: {schedule_info.get('has_schedule', False)}")
    print(f"  Last run: {schedule_info.get('last_run', 'Unknown')}")
    print()
    
    # Summary and Recommendations
    print("SUMMARY & RECOMMENDATIONS:")
    print("-" * 40)
    
    if total_messages > 100:
        print("  ⚠️  High number of messages in queues - may indicate backup")
    
    if stuck_tasks:
        print("  ⚠️  Found stuck tasks - consider clearing with clear_stuck_tasks.py")
    
    if not worker_stats:
        print("  ❌ No workers responding - check if Celery workers are running")
    
    if not schedule_info.get('has_schedule'):
        print("  ⚠️  No CeleryBeat schedule found - scheduled tasks won't run")
    
    if not match_tasks and total_messages == 0:
        print("  ✅ Queues are clear - no obvious issues detected")
    
    print()
    print("=" * 80)
    print("DIAGNOSTIC COMPLETE")
    print("=" * 80)

if __name__ == "__main__":
    main()