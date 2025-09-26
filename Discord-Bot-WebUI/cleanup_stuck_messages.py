#!/usr/bin/env python3
"""
Clean up stuck messages in Celery queues.
Run this to clear messages that have been retrying indefinitely.
"""

import redis
import json
import sys
from datetime import datetime

def cleanup_queue(redis_client, queue_name, max_retries=5):
    """Remove messages that have exceeded retry limit."""

    queue_length = redis_client.llen(queue_name)
    if queue_length == 0:
        print(f"Queue {queue_name} is empty")
        return 0

    print(f"Processing {queue_length} messages in {queue_name}")

    removed_count = 0
    processed_count = 0

    # Process all messages
    for _ in range(queue_length):
        # Pop from the left (oldest first)
        message_raw = redis_client.lpop(queue_name)
        if not message_raw:
            break

        processed_count += 1

        try:
            message = json.loads(message_raw)
            headers = message.get('headers', {})
            task_name = headers.get('task', 'Unknown')
            retries = headers.get('retries', 0)

            # Check if this task should be removed
            should_remove = False

            # Remove tasks with too many retries
            if retries >= max_retries:
                should_remove = True
                print(f"  Removing {task_name} with {retries} retries")

            # Remove specific problematic tasks
            problematic_tasks = [
                'monitor_rsvp_health',
                'check_and_start_missing_live_reporting'
            ]

            if any(task in task_name for task in problematic_tasks) and retries >= 3:
                should_remove = True
                print(f"  Removing problematic task {task_name} with {retries} retries")

            if not should_remove:
                # Put it back at the end of the queue
                redis_client.rpush(queue_name, message_raw)
            else:
                removed_count += 1

        except json.JSONDecodeError:
            # Can't parse, put it back
            redis_client.rpush(queue_name, message_raw)
        except Exception as e:
            print(f"  Error processing message: {e}")
            # Put it back to be safe
            redis_client.rpush(queue_name, message_raw)

    print(f"Processed {processed_count} messages, removed {removed_count}")
    return removed_count

def main():
    # Connect to Redis
    redis_host = 'redis' if len(sys.argv) <= 1 else sys.argv[1]
    redis_client = redis.Redis(host=redis_host, port=6379, db=0, decode_responses=True)

    # Check if Redis is accessible
    try:
        redis_client.ping()
    except redis.ConnectionError:
        print(f"Error: Cannot connect to Redis at {redis_host}:6379")
        print("Usage: python cleanup_stuck_messages.py [redis_host]")
        sys.exit(1)

    print(f"Connected to Redis at {redis_host}:6379")
    print("Starting queue cleanup...")
    print("-" * 50)

    total_removed = 0

    # Clean each queue
    for queue in ['celery', 'live_reporting', 'match_management', 'discord_tasks']:
        removed = cleanup_queue(redis_client, queue)
        total_removed += removed
        print("")

    print("-" * 50)
    print(f"Cleanup complete. Removed {total_removed} stuck messages.")

    # Show current queue status
    print("\nCurrent queue lengths:")
    for queue in ['celery', 'live_reporting', 'match_management', 'discord_tasks']:
        length = redis_client.llen(queue)
        print(f"  {queue}: {length}")

if __name__ == "__main__":
    main()