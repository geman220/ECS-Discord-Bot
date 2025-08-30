#!/usr/bin/env python3
"""
Celery Health Monitor - Prevents queue backups and detects issues early
Usage: python monitor_celery_health.py [--fix-issues] [--alert-threshold 1000]
"""

import os
import redis
import json
import argparse
from datetime import datetime, timedelta
from celery import Celery
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

REDIS_URL = os.getenv('REDIS_URL', 'redis://redis:6379/0')
app = Celery('tasks', broker=REDIS_URL, backend=REDIS_URL)
redis_client = redis.from_url(REDIS_URL)

class CeleryHealthMonitor:
    def __init__(self, alert_threshold=1000, auto_fix=False):
        self.alert_threshold = alert_threshold
        self.auto_fix = auto_fix
        self.issues_found = []
        
    def check_queue_lengths(self):
        """Check for queue backups"""
        queues = ['celery', 'live_reporting', 'match_management', 'discord_tasks']
        queue_lengths = {}
        total_messages = 0
        
        for queue in queues:
            length = redis_client.llen(queue)
            queue_lengths[queue] = length
            total_messages += length
            
            if length > self.alert_threshold:
                self.issues_found.append({
                    'type': 'QUEUE_BACKUP',
                    'queue': queue,
                    'length': length,
                    'severity': 'HIGH' if length > 5000 else 'MEDIUM'
                })
        
        return queue_lengths, total_messages
    
    def check_worker_connectivity(self):
        """Check if workers are responding"""
        try:
            inspect = app.control.inspect()
            pong = inspect.ping()
            
            if not pong:
                self.issues_found.append({
                    'type': 'NO_WORKERS',
                    'message': 'No workers responding to ping',
                    'severity': 'CRITICAL'
                })
                return False, []
            
            return True, list(pong.keys())
        except Exception as e:
            self.issues_found.append({
                'type': 'WORKER_CONNECTION_ERROR',
                'error': str(e),
                'severity': 'HIGH'
            })
            return False, []
    
    def check_consumers_active(self):
        """Check if consumers are actually consuming from queues"""
        try:
            inspect = app.control.inspect()
            active = inspect.active()
            reserved = inspect.reserved()
            
            # If we have workers but no active/reserved tasks, might be consumption issue
            if active and not any(tasks for tasks in active.values()):
                # Check if there are messages in queues but no consumption
                queue_lengths, _ = self.check_queue_lengths()
                if any(length > 100 for length in queue_lengths.values()):
                    self.issues_found.append({
                        'type': 'CONSUMPTION_STOPPED',
                        'message': 'Messages in queue but no active consumption',
                        'severity': 'HIGH'
                    })
            
            return active, reserved
        except Exception as e:
            logger.error(f"Error checking consumers: {e}")
            return None, None
    
    def check_beat_schedule(self):
        """Check if CeleryBeat is working"""
        try:
            has_schedule = redis_client.exists('celerybeat-schedule')
            last_run = redis_client.get('celerybeat-last-run')
            
            if not has_schedule:
                self.issues_found.append({
                    'type': 'NO_BEAT_SCHEDULE',
                    'message': 'No CeleryBeat schedule found',
                    'severity': 'HIGH'
                })
            
            if last_run:
                last_run_str = last_run.decode('utf-8')
                # Check if beat ran recently (within last hour)
                try:
                    last_run_time = datetime.fromisoformat(last_run_str.replace('Z', '+00:00'))
                    if datetime.now().timestamp() - last_run_time.timestamp() > 3600:
                        self.issues_found.append({
                            'type': 'BEAT_NOT_RUNNING',
                            'message': f'Beat last ran: {last_run_str} (over 1 hour ago)',
                            'severity': 'MEDIUM'
                        })
                except:
                    pass  # If we can't parse the timestamp, skip this check
            
            return has_schedule, last_run_str if last_run else None
        except Exception as e:
            logger.error(f"Error checking beat schedule: {e}")
            return False, None
    
    def check_revoked_tasks(self):
        """Check for excessive revoked tasks"""
        try:
            task_keys = redis_client.keys('celery-task-meta-*')
            revoked_count = 0
            old_tasks = 0
            
            for key in task_keys[:1000]:  # Sample first 1000
                try:
                    task_data = redis_client.get(key)
                    if task_data:
                        task_info = json.loads(task_data)
                        status = task_info.get('status')
                        
                        if status == 'REVOKED':
                            revoked_count += 1
                        elif status in ['PENDING', 'RETRY']:
                            old_tasks += 1
                except:
                    pass
            
            if revoked_count > 100:
                self.issues_found.append({
                    'type': 'EXCESSIVE_REVOKED_TASKS',
                    'count': revoked_count,
                    'message': f'{revoked_count} revoked tasks clogging Redis',
                    'severity': 'MEDIUM'
                })
            
            if old_tasks > 500:
                self.issues_found.append({
                    'type': 'STALE_TASK_METADATA',
                    'count': old_tasks,
                    'message': f'{old_tasks} old PENDING/RETRY tasks',
                    'severity': 'MEDIUM'
                })
                
            return len(task_keys), revoked_count, old_tasks
        except Exception as e:
            logger.error(f"Error checking revoked tasks: {e}")
            return 0, 0, 0
    
    def auto_fix_issues(self):
        """Automatically fix detected issues"""
        if not self.auto_fix:
            return []
        
        fixes_applied = []
        
        for issue in self.issues_found:
            if issue['type'] == 'EXCESSIVE_REVOKED_TASKS':
                # Clear revoked tasks
                try:
                    task_keys = redis_client.keys('celery-task-meta-*')
                    cleared = 0
                    for key in task_keys:
                        try:
                            task_data = redis_client.get(key)
                            if task_data:
                                task_info = json.loads(task_data)
                                if task_info.get('status') == 'REVOKED':
                                    redis_client.delete(key)
                                    cleared += 1
                        except:
                            pass
                    fixes_applied.append(f"Cleared {cleared} revoked tasks")
                except Exception as e:
                    logger.error(f"Failed to clear revoked tasks: {e}")
            
            elif issue['type'] == 'NO_BEAT_SCHEDULE':
                # Clear beat schedule to force rebuild
                try:
                    redis_client.delete('celerybeat-schedule')
                    redis_client.delete('celerybeat-last-run')
                    fixes_applied.append("Reset CeleryBeat schedule")
                except Exception as e:
                    logger.error(f"Failed to reset beat schedule: {e}")
        
        return fixes_applied
    
    def run_health_check(self):
        """Run complete health check"""
        print("=" * 80)
        print("CELERY HEALTH MONITOR")
        print("=" * 80)
        print(f"Timestamp: {datetime.now()}")
        print(f"Alert threshold: {self.alert_threshold} messages")
        print(f"Auto-fix enabled: {self.auto_fix}")
        print()
        
        # Run all checks
        queue_lengths, total_messages = self.check_queue_lengths()
        workers_ok, worker_list = self.check_worker_connectivity()
        active_tasks, reserved_tasks = self.check_consumers_active()
        has_schedule, last_run = self.check_beat_schedule()
        total_keys, revoked_count, old_tasks = self.check_revoked_tasks()
        
        # Report current status
        print("📊 CURRENT STATUS:")
        print(f"  Total messages in queues: {total_messages}")
        print(f"  Workers responding: {len(worker_list) if worker_list else 0}")
        print(f"  Beat schedule exists: {has_schedule}")
        print(f"  Task metadata keys: {total_keys}")
        print(f"  Revoked tasks: {revoked_count}")
        print()
        
        # Report queue details
        print("📋 QUEUE DETAILS:")
        for queue, length in queue_lengths.items():
            status = "🟢" if length < 100 else "🟡" if length < 1000 else "🔴"
            print(f"  {status} {queue}: {length} messages")
        print()
        
        # Report issues
        if self.issues_found:
            print("⚠️  ISSUES DETECTED:")
            for issue in self.issues_found:
                severity_icon = {"CRITICAL": "🚨", "HIGH": "🔴", "MEDIUM": "🟡"}.get(issue['severity'], "ℹ️")
                print(f"  {severity_icon} {issue['type']}: {issue.get('message', json.dumps(issue))}")
            print()
            
            # Apply auto-fixes
            fixes = self.auto_fix_issues()
            if fixes:
                print("🔧 AUTO-FIXES APPLIED:")
                for fix in fixes:
                    print(f"  ✅ {fix}")
                print()
        else:
            print("✅ NO ISSUES DETECTED - System healthy!")
            print()
        
        # Recommendations
        print("💡 RECOMMENDATIONS:")
        if total_messages > 5000:
            print(f"  🚨 URGENT: Queue backup detected ({total_messages} messages)")
            print("     Run: python emergency_cleanup.py")
        elif total_messages > 1000:
            print(f"  ⚠️  High queue volume ({total_messages} messages)")
            print("     Monitor closely, consider clearing stuck tasks")
        
        if not workers_ok:
            print("  🚨 URGENT: No workers responding")
            print("     Check worker containers and restart if needed")
        
        if revoked_count > 100:
            print(f"  🧹 Clean up {revoked_count} revoked tasks")
            print("     Run with --fix-issues flag")
        
        if not has_schedule:
            print("  📅 Restart CeleryBeat to rebuild schedule")
        
        print()
        print("=" * 80)
        
        return len(self.issues_found) == 0

def main():
    parser = argparse.ArgumentParser(description='Monitor Celery health')
    parser.add_argument('--fix-issues', action='store_true', 
                       help='Automatically fix detected issues')
    parser.add_argument('--alert-threshold', type=int, default=1000,
                       help='Alert when queue length exceeds this number')
    
    args = parser.parse_args()
    
    monitor = CeleryHealthMonitor(
        alert_threshold=args.alert_threshold,
        auto_fix=args.fix_issues
    )
    
    healthy = monitor.run_health_check()
    
    # Exit with non-zero status if issues found (useful for monitoring systems)
    exit(0 if healthy else 1)

if __name__ == "__main__":
    main()