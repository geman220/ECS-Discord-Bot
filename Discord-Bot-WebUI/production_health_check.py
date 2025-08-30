#!/usr/bin/env python3
"""
Production Health Check - Quick verification for match thread system
Usage: docker exec ecs-discord-bot-webui-1 python production_health_check.py
"""

import os
import redis
from celery import Celery
from datetime import datetime

def main():
    REDIS_URL = os.getenv('REDIS_URL', 'redis://redis:6379/0')
    app = Celery('tasks', broker=REDIS_URL, backend=REDIS_URL)
    redis_client = redis.from_url(REDIS_URL)
    
    print("🏥 PRODUCTION HEALTH CHECK")
    print("=" * 50)
    print(f"Timestamp: {datetime.now()}")
    print()
    
    # Check Redis connection
    try:
        redis_client.ping()
        print("✅ Redis: Connected")
    except Exception as e:
        print(f"❌ Redis: Connection failed - {e}")
        return False
    
    # Check queue lengths
    print("\n📊 Queue Status:")
    queues = ['celery', 'live_reporting', 'discord', 'enterprise_rsvp', 'player_sync']
    total_messages = 0
    for queue in queues:
        try:
            length = redis_client.llen(queue)
            total_messages += length
            status = "🟢" if length == 0 else "🟡" if length < 10 else "🔴"
            print(f"  {status} {queue}: {length} messages")
        except Exception as e:
            print(f"  ❌ {queue}: Error - {e}")
    
    print(f"\nTotal messages: {total_messages}")
    
    # Check workers
    print("\n👷 Worker Status:")
    try:
        inspect = app.control.inspect()
        stats = inspect.stats()
        if stats:
            print(f"Found {len(stats)} active workers:")
            
            # Check queue coverage
            active_queues = inspect.active_queues()
            queue_coverage = {}
            
            for worker, stat in stats.items():
                worker_name = worker.split('@')[0]
                print(f"  ✅ {worker_name}")
                
                if active_queues and worker in active_queues:
                    queues_consumed = [q['name'] for q in active_queues[worker]]
                    print(f"     Consuming: {queues_consumed}")
                    for q in queues_consumed:
                        queue_coverage[q] = True
                else:
                    print(f"     Consuming: Unknown")
            
            # Verify critical queues have workers
            critical_queues = ['live_reporting', 'celery']
            missing_coverage = [q for q in critical_queues if q not in queue_coverage]
            
            if missing_coverage:
                print(f"\n❌ CRITICAL: Missing workers for queues: {missing_coverage}")
                return False
            else:
                print(f"\n✅ All critical queues have worker coverage")
                
        else:
            print("❌ No workers responding")
            return False
            
    except Exception as e:
        print(f"❌ Worker check failed: {e}")
        return False
    
    # Test match thread task submission
    print("\n🧪 Testing Match Thread System:")
    try:
        from app.tasks.tasks_live_reporting import force_create_mls_thread_task
        task = force_create_mls_thread_task.delay('health_check_test')
        print(f"✅ Match thread task queued: {task.id}")
        
        # Check if it went to the right queue
        live_reporting_length = redis_client.llen('live_reporting')
        if live_reporting_length > 0:
            print(f"✅ Task routed to live_reporting queue")
        else:
            print(f"⚠️  Task may have been processed immediately")
        
    except Exception as e:
        print(f"❌ Match thread test failed: {e}")
        return False
    
    print("\n" + "=" * 50)
    print("🎉 SYSTEM HEALTHY - Match thread creation should work")
    return True

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)