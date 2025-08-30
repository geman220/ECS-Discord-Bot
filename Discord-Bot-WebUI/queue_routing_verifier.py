#!/usr/bin/env python3
"""
Queue Routing Verifier - Comprehensive check of Celery queue routing
Verifies that all tasks have proper queue assignments and worker coverage
Usage: python queue_routing_verifier.py
"""

import os
import redis
import json
import subprocess
from datetime import datetime
from celery import Celery
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

REDIS_URL = os.getenv('REDIS_URL', 'redis://redis:6379/0')
app = Celery('tasks', broker=REDIS_URL, backend=REDIS_URL)
redis_client = redis.from_url(REDIS_URL)

class QueueRoutingVerifier:
    def __init__(self):
        self.issues = []
        self.task_queue_mapping = {}
        self.worker_queue_mapping = {}
        self.container_names = {
            'webui': 'ecs-discord-bot-webui-1',
            'worker': 'ecs-discord-bot-celery-worker-1', 
            'live_reporting': 'ecs-discord-bot-celery-live-reporting-worker-1',
            'discord': 'ecs-discord-bot-celery-discord-worker-1',
            'enterprise_rsvp': 'ecs-discord-bot-celery-enterprise-rsvp-worker-1',
            'player_sync': 'ecs-discord-bot-celery-player-sync-worker-1',
            'beat': 'ecs-discord-bot-celery-beat-1'
        }

    def get_expected_task_queues(self):
        """Map known tasks to their expected queues based on code analysis"""
        return {
            # Live Reporting Tasks (live_reporting queue)
            'app.tasks.tasks_live_reporting.force_create_mls_thread_task': 'live_reporting',
            'app.tasks.tasks_live_reporting.schedule_mls_thread_task': 'live_reporting', 
            'app.tasks.tasks_live_reporting.schedule_all_mls_threads_task': 'live_reporting',
            'app.tasks.tasks_live_reporting_v2.start_live_reporting_v2': 'live_reporting',
            'app.tasks.tasks_live_reporting_v2.stop_live_reporting_v2': 'live_reporting',
            'app.tasks.tasks_live_reporting.start_live_reporting_robust': 'live_reporting',
            'app.tasks.tasks_live_reporting.stop_live_reporting': 'live_reporting',
            
            # Discord Tasks (discord queue)
            'app.tasks.tasks_discord.notify_discord_of_rsvp_change_task': 'discord',
            'app.tasks.tasks_discord.update_discord_rsvp_task': 'discord',
            'app.tasks.tasks_rsvp.notify_frontend_of_rsvp_change_task': 'discord',
            'app.tasks.tasks_rsvp.send_rsvp_reminder_task': 'discord',
            
            # General Tasks (celery queue) 
            'app.tasks.tasks_core.cleanup_old_logs': 'celery',
            'app.tasks.tasks_core.send_notification': 'celery',
            'app.tasks.tasks_maintenance.cleanup_expired_tokens': 'celery',
            'app.tasks.tasks_maintenance.backup_database': 'celery',
            
            # Enterprise RSVP Tasks (enterprise_rsvp queue)
            'app.tasks.tasks_rsvp_ecs.process_enterprise_rsvp': 'enterprise_rsvp',
            'app.tasks.tasks_rsvp_ecs.sync_enterprise_rsvp': 'enterprise_rsvp',
            
            # Player Sync Tasks (player_sync queue)
            'app.tasks.tasks_core.sync_player_data': 'player_sync',
            'app.tasks.tasks_core.update_player_stats': 'player_sync',
        }

    def get_expected_worker_queues(self):
        """Map worker containers to their expected queue consumption"""
        return {
            'ecs-discord-bot-celery-worker-1': ['celery'],
            'ecs-discord-bot-celery-live-reporting-worker-1': ['live_reporting'], 
            'ecs-discord-bot-celery-discord-worker-1': ['discord'],
            'ecs-discord-bot-celery-enterprise-rsvp-worker-1': ['enterprise_rsvp'],
            'ecs-discord-bot-celery-player-sync-worker-1': ['player_sync']
        }

    def check_celery_workers(self):
        """Check active Celery workers and their queue consumption"""
        print("🔍 CHECKING CELERY WORKERS...")
        
        try:
            inspect = app.control.inspect()
            
            # Get worker stats
            stats = inspect.stats()
            if stats:
                print(f"📊 Found {len(stats)} active workers:")
                for worker, stat in stats.items():
                    print(f"  • {worker}")
                    pool_info = stat.get('pool', {})
                    print(f"    - Pool: {pool_info.get('implementation', 'Unknown')}")
                    print(f"    - Concurrency: {pool_info.get('max-concurrency', 'Unknown')}")
                    
                    # Get queue assignments
                    active_queues = inspect.active_queues()
                    if active_queues and worker in active_queues:
                        queues = [q['name'] for q in active_queues[worker]]
                        print(f"    - Queues: {queues}")
                        self.worker_queue_mapping[worker] = queues
                    else:
                        print(f"    - ⚠️  Cannot determine queue consumption")
                        self.issues.append({
                            'type': 'WORKER_QUEUE_UNKNOWN',
                            'worker': worker,
                            'severity': 'MEDIUM'
                        })
            else:
                print("❌ No workers responding to inspection")
                self.issues.append({
                    'type': 'NO_WORKERS_RESPONDING',
                    'severity': 'CRITICAL'
                })
            
            print()
            return bool(stats)
            
        except Exception as e:
            print(f"❌ Error checking workers: {e}")
            self.issues.append({
                'type': 'WORKER_INSPECTION_FAILED',
                'error': str(e),
                'severity': 'HIGH'
            })
            return False

    def check_queue_coverage(self):
        """Check if all expected queues have worker coverage"""
        print("🔍 CHECKING QUEUE COVERAGE...")
        
        expected_workers = self.get_expected_worker_queues()
        expected_tasks = self.get_expected_task_queues()
        
        # Get all unique queues that tasks expect
        expected_queues = set(expected_tasks.values())
        
        # Get all queues that workers are consuming from
        covered_queues = set()
        for worker, queues in self.worker_queue_mapping.items():
            covered_queues.update(queues)
        
        print(f"📋 Expected queues: {sorted(expected_queues)}")
        print(f"🛠️  Covered queues: {sorted(covered_queues)}")
        
        # Check for uncovered queues
        uncovered = expected_queues - covered_queues
        if uncovered:
            print(f"❌ Uncovered queues: {sorted(uncovered)}")
            for queue in uncovered:
                self.issues.append({
                    'type': 'UNCOVERED_QUEUE',
                    'queue': queue,
                    'severity': 'HIGH'
                })
        else:
            print("✅ All expected queues have worker coverage")
        
        # Check for unexpected queues
        unexpected = covered_queues - expected_queues
        if unexpected:
            print(f"⚠️  Workers consuming unexpected queues: {sorted(unexpected)}")
            for queue in unexpected:
                self.issues.append({
                    'type': 'UNEXPECTED_QUEUE_CONSUMPTION',
                    'queue': queue,
                    'severity': 'LOW'
                })
        
        print()

    def check_docker_containers(self):
        """Check if expected Docker containers are running"""
        print("🔍 CHECKING DOCKER CONTAINERS...")
        
        expected_containers = list(self.container_names.values())
        
        try:
            result = subprocess.run(['docker', 'ps', '--format', 'table {{.Names}}\t{{.Status}}'], 
                                  capture_output=True, text=True, check=True)
            
            running_containers = []
            lines = result.stdout.strip().split('\n')[1:]  # Skip header
            for line in lines:
                if line.strip():
                    name = line.split('\t')[0]
                    status = line.split('\t')[1] if '\t' in line else 'Unknown'
                    running_containers.append((name, status))
            
            print(f"📊 Expected containers: {len(expected_containers)}")
            print(f"🏃 Running containers matching expected names:")
            
            found_containers = []
            for name, status in running_containers:
                if name in expected_containers:
                    print(f"  ✅ {name}: {status}")
                    found_containers.append(name)
            
            missing = set(expected_containers) - set(found_containers)
            if missing:
                print(f"❌ Missing containers: {sorted(missing)}")
                for container in missing:
                    self.issues.append({
                        'type': 'MISSING_CONTAINER',
                        'container': container,
                        'severity': 'HIGH'
                    })
            
            print()
            return len(missing) == 0
            
        except subprocess.CalledProcessError as e:
            print(f"❌ Error checking Docker containers: {e}")
            self.issues.append({
                'type': 'DOCKER_CHECK_FAILED',
                'error': str(e),
                'severity': 'HIGH'
            })
            return False
        except FileNotFoundError:
            print("❌ Docker command not found")
            self.issues.append({
                'type': 'DOCKER_NOT_AVAILABLE',
                'severity': 'MEDIUM'
            })
            return False

    def check_queue_lengths(self):
        """Check current queue lengths and activity"""
        print("🔍 CHECKING QUEUE LENGTHS...")
        
        queues_to_check = ['celery', 'live_reporting', 'discord', 'enterprise_rsvp', 'player_sync']
        
        queue_info = {}
        total_messages = 0
        
        for queue in queues_to_check:
            length = redis_client.llen(queue)
            queue_info[queue] = length
            total_messages += length
            
            status = "🟢" if length == 0 else "🟡" if length < 10 else "🔴"
            print(f"  {status} {queue}: {length} messages")
            
            if length > 100:
                self.issues.append({
                    'type': 'HIGH_QUEUE_LENGTH',
                    'queue': queue,
                    'length': length,
                    'severity': 'HIGH' if length > 1000 else 'MEDIUM'
                })
        
        print(f"📊 Total messages in queues: {total_messages}")
        
        if total_messages > 5000:
            self.issues.append({
                'type': 'TOTAL_QUEUE_BACKUP',
                'total_messages': total_messages,
                'severity': 'CRITICAL'
            })
        
        print()
        return queue_info

    def test_task_routing(self):
        """Test that a simple task can be routed correctly"""
        print("🔍 TESTING TASK ROUTING...")
        
        try:
            # Try to get registered tasks
            inspect = app.control.inspect()
            registered = inspect.registered()
            
            if registered:
                print(f"📋 Found registered tasks in {len(registered)} workers:")
                task_coverage = {}
                
                expected_tasks = self.get_expected_task_queues()
                for worker, tasks in registered.items():
                    print(f"  • {worker}: {len(tasks)} tasks")
                    
                    # Check if critical tasks are registered
                    for expected_task in expected_tasks.keys():
                        if expected_task in tasks:
                            if expected_task not in task_coverage:
                                task_coverage[expected_task] = []
                            task_coverage[expected_task].append(worker)
                
                # Check for missing task registrations
                missing_tasks = set(expected_tasks.keys()) - set(task_coverage.keys())
                if missing_tasks:
                    print(f"❌ Tasks not registered on any worker: {list(missing_tasks)[:5]}...")
                    for task in list(missing_tasks)[:3]:  # Show first 3
                        self.issues.append({
                            'type': 'TASK_NOT_REGISTERED',
                            'task': task,
                            'severity': 'HIGH'
                        })
                else:
                    print("✅ All expected tasks are registered on workers")
            else:
                print("❌ Cannot retrieve registered tasks from workers")
                self.issues.append({
                    'type': 'CANNOT_GET_REGISTERED_TASKS',
                    'severity': 'MEDIUM'
                })
                
        except Exception as e:
            print(f"❌ Error testing task routing: {e}")
            self.issues.append({
                'type': 'TASK_ROUTING_TEST_FAILED',
                'error': str(e),
                'severity': 'MEDIUM'
            })
        
        print()

    def generate_report(self):
        """Generate comprehensive report of findings"""
        print("=" * 80)
        print("📋 QUEUE ROUTING VERIFICATION REPORT")
        print("=" * 80)
        print(f"Timestamp: {datetime.now()}")
        print(f"Total issues found: {len(self.issues)}")
        print()
        
        if not self.issues:
            print("✅ NO ISSUES FOUND - Queue routing configuration appears correct!")
            print()
            print("💡 If match threads are still not working, the issue may be:")
            print("  1. Task execution errors within workers")
            print("  2. Database connectivity issues")
            print("  3. Discord API permissions or rate limiting")
            print("  4. Application logic errors")
            print()
            print("🔧 NEXT DEBUGGING STEPS:")
            print("  1. Check worker logs: docker logs ecs-discord-bot-celery-live-reporting-worker-1")
            print("  2. Force run a single task and monitor logs")
            print("  3. Check database connectivity from workers")
            print("  4. Verify Discord bot permissions and API tokens")
            return
        
        # Group issues by severity
        critical = [i for i in self.issues if i['severity'] == 'CRITICAL']
        high = [i for i in self.issues if i['severity'] == 'HIGH']
        medium = [i for i in self.issues if i['severity'] == 'MEDIUM']
        low = [i for i in self.issues if i['severity'] == 'LOW']
        
        for severity, issues_list in [('CRITICAL', critical), ('HIGH', high), ('MEDIUM', medium), ('LOW', low)]:
            if not issues_list:
                continue
                
            icon = {'CRITICAL': '🚨', 'HIGH': '🔴', 'MEDIUM': '🟡', 'LOW': '🟢'}[severity]
            print(f"{icon} {severity} ISSUES ({len(issues_list)}):")
            print("-" * 50)
            
            for i, issue in enumerate(issues_list, 1):
                print(f"{i}. {issue['type']}")
                for key, value in issue.items():
                    if key not in ['type', 'severity']:
                        print(f"   {key}: {value}")
                print()
        
        print("🔧 RECOMMENDED ACTIONS:")
        print("-" * 50)
        
        if critical or high:
            print("🚨 URGENT: Address critical and high severity issues first")
            print("   - Restart affected containers")
            print("   - Check container logs for errors")
            print("   - Verify Redis connectivity")
        
        if any(i['type'] == 'UNCOVERED_QUEUE' for i in self.issues):
            print("📋 Missing queue coverage detected:")
            print("   - Check worker startup commands")
            print("   - Verify Docker container configurations")
            print("   - Restart affected worker containers")
        
        if any(i['type'] in ['HIGH_QUEUE_LENGTH', 'TOTAL_QUEUE_BACKUP'] for i in self.issues):
            print("🧹 Queue backup detected:")
            print("   - Run: python emergency_cleanup.py")
            print("   - Restart Celery services after cleanup")
        
        print()

    def run_verification(self):
        """Run complete verification"""
        print("=" * 80)
        print("🔬 QUEUE ROUTING VERIFIER")
        print("=" * 80)
        print(f"Timestamp: {datetime.now()}")
        print()
        
        # Run all checks
        workers_ok = self.check_celery_workers()
        containers_ok = self.check_docker_containers()
        queue_info = self.check_queue_lengths()
        
        if workers_ok:
            self.check_queue_coverage()
            self.test_task_routing()
        
        # Generate final report
        self.generate_report()

def main():
    verifier = QueueRoutingVerifier()
    verifier.run_verification()

if __name__ == "__main__":
    main()