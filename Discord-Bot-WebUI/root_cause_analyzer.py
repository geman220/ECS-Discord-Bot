#!/usr/bin/env python3
"""
Root Cause Analyzer for Celery Issues
Identifies why tasks get stuck and provides specific fixes
Usage: python root_cause_analyzer.py
"""

import os
import redis
import json
import subprocess
from datetime import datetime, timedelta
from celery import Celery
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

REDIS_URL = os.getenv('REDIS_URL', 'redis://redis:6379/0')
app = Celery('tasks', broker=REDIS_URL, backend=REDIS_URL)
redis_client = redis.from_url(REDIS_URL)

class RootCauseAnalyzer:
    def __init__(self):
        self.findings = []
        
    def analyze_worker_configuration(self):
        """Analyze worker setup and configuration"""
        print("🔍 ANALYZING WORKER CONFIGURATION...")
        
        try:
            inspect = app.control.inspect()
            
            # Check worker stats
            stats = inspect.stats()
            if stats:
                print(f"📊 Found {len(stats)} workers:")
                for worker, stat in stats.items():
                    pool_info = stat.get('pool', {})
                    print(f"  • {worker}:")
                    print(f"    - Pool size: {pool_info.get('max-concurrency', 'Unknown')}")
                    print(f"    - Pool type: {pool_info.get('implementation', 'Unknown')}")
                    
                    # Check if worker is consuming from expected queues
                    active_queues = inspect.active_queues()
                    if active_queues and worker in active_queues:
                        queues = [q['name'] for q in active_queues[worker]]
                        print(f"    - Consuming from: {queues}")
                        
                        # Check if critical queues are being consumed
                        critical_queues = ['live_reporting', 'celery']
                        missing_queues = [q for q in critical_queues if q not in queues]
                        if missing_queues:
                            self.findings.append({
                                'type': 'MISSING_QUEUE_CONSUMERS',
                                'worker': worker,
                                'missing_queues': missing_queues,
                                'severity': 'HIGH',
                                'fix': f"Check worker routing configuration for {missing_queues}"
                            })
                    else:
                        print(f"    - ⚠️  Cannot determine queue consumption")
            else:
                self.findings.append({
                    'type': 'NO_WORKER_STATS',
                    'severity': 'CRITICAL',
                    'fix': 'Check if workers are running and can connect to broker'
                })
                
        except Exception as e:
            self.findings.append({
                'type': 'WORKER_ANALYSIS_FAILED',
                'error': str(e),
                'severity': 'HIGH',
                'fix': 'Check worker connectivity and Celery configuration'
            })
        
        print()
    
    def analyze_task_routing(self):
        """Analyze task routing and queue assignments"""
        print("🔍 ANALYZING TASK ROUTING...")
        
        # Check if tasks are going to correct queues
        queue_lengths = {}
        queues_to_check = ['celery', 'live_reporting', 'match_management', 'discord_tasks']
        
        for queue in queues_to_check:
            length = redis_client.llen(queue)
            queue_lengths[queue] = length
            print(f"  📋 {queue}: {length} messages")
        
        # Analyze routing issues
        if queue_lengths['live_reporting'] > 1000 and queue_lengths['celery'] < 100:
            self.findings.append({
                'type': 'LIVE_REPORTING_BACKUP',
                'queue_length': queue_lengths['live_reporting'],
                'severity': 'HIGH',
                'fix': 'live_reporting worker may be down or not consuming from live_reporting queue'
            })
        
        if queue_lengths['celery'] > 1000:
            self.findings.append({
                'type': 'GENERAL_QUEUE_BACKUP', 
                'queue_length': queue_lengths['celery'],
                'severity': 'HIGH',
                'fix': 'General worker may be down or overloaded'
            })
        
        print()
    
    def analyze_task_failures(self):
        """Analyze task failure patterns"""
        print("🔍 ANALYZING TASK FAILURE PATTERNS...")
        
        try:
            # Sample task metadata to find failure patterns
            task_keys = redis_client.keys('celery-task-meta-*')
            
            failure_counts = {}
            revoked_counts = {}
            pending_old = 0
            
            sample_size = min(1000, len(task_keys))
            for key in task_keys[:sample_size]:
                try:
                    task_data = redis_client.get(key)
                    if task_data:
                        task_info = json.loads(task_data)
                        status = task_info.get('status')
                        task_name = task_info.get('name', 'unknown')
                        
                        if status == 'FAILURE':
                            failure_counts[task_name] = failure_counts.get(task_name, 0) + 1
                        elif status == 'REVOKED':
                            revoked_counts[task_name] = revoked_counts.get(task_name, 0) + 1
                        elif status == 'PENDING':
                            # Check if task is old
                            pending_old += 1
                            
                except Exception:
                    pass
            
            print(f"  📊 Analyzed {sample_size} task metadata entries:")
            print(f"  💥 Failed tasks by type:")
            for task_name, count in sorted(failure_counts.items(), key=lambda x: x[1], reverse=True)[:5]:
                print(f"    - {task_name}: {count} failures")
                
                if 'live_reporting' in task_name:
                    self.findings.append({
                        'type': 'LIVE_REPORTING_TASK_FAILURES',
                        'task': task_name,
                        'count': count,
                        'severity': 'HIGH',
                        'fix': 'Check live reporting worker logs for errors'
                    })
            
            print(f"  🚫 Revoked tasks by type:")
            for task_name, count in sorted(revoked_counts.items(), key=lambda x: x[1], reverse=True)[:5]:
                print(f"    - {task_name}: {count} revoked")
            
            if pending_old > 100:
                self.findings.append({
                    'type': 'MANY_OLD_PENDING_TASKS',
                    'count': pending_old,
                    'severity': 'MEDIUM',
                    'fix': 'Old pending tasks may indicate workers not processing queues'
                })
            
        except Exception as e:
            logger.error(f"Error analyzing task failures: {e}")
        
        print()
    
    def analyze_beat_scheduling(self):
        """Analyze CeleryBeat scheduling issues"""
        print("🔍 ANALYZING CELERYBEAT SCHEDULING...")
        
        try:
            # Check beat schedule
            has_schedule = redis_client.exists('celerybeat-schedule')
            last_run = redis_client.get('celerybeat-last-run')
            
            print(f"  📅 Schedule exists: {has_schedule}")
            if last_run:
                last_run_str = last_run.decode('utf-8')
                print(f"  ⏰ Last run: {last_run_str}")
                
                # Check if beat is running regularly
                try:
                    from dateutil import parser
                    last_run_time = parser.parse(last_run_str)
                    time_since_last_run = datetime.now(last_run_time.tzinfo) - last_run_time
                    
                    if time_since_last_run > timedelta(hours=2):
                        self.findings.append({
                            'type': 'BEAT_NOT_RUNNING_REGULARLY',
                            'last_run': last_run_str,
                            'hours_ago': time_since_last_run.total_seconds() / 3600,
                            'severity': 'HIGH',
                            'fix': 'CeleryBeat container may be down or stuck'
                        })
                except Exception as e:
                    print(f"  ⚠️  Could not parse last run time: {e}")
            else:
                print("  ❌ No last run time recorded")
                
            if not has_schedule:
                self.findings.append({
                    'type': 'NO_BEAT_SCHEDULE',
                    'severity': 'HIGH',
                    'fix': 'CeleryBeat schedule missing - restart beat container'
                })
            
            # Check for scheduled match tasks specifically
            scheduled_keys = redis_client.keys('scheduled_*')
            print(f"  📋 Found {len(scheduled_keys)} scheduled task keys")
            
            if len(scheduled_keys) == 0:
                self.findings.append({
                    'type': 'NO_SCHEDULED_TASKS',
                    'severity': 'MEDIUM', 
                    'fix': 'No scheduled tasks found - check if beat is creating match schedules'
                })
                
        except Exception as e:
            logger.error(f"Error analyzing beat scheduling: {e}")
        
        print()
    
    def analyze_system_resources(self):
        """Analyze system resource issues"""
        print("🔍 ANALYZING SYSTEM RESOURCES...")
        
        try:
            # Check Redis memory usage
            redis_info = redis_client.info('memory')
            used_memory_mb = redis_info.get('used_memory', 0) / 1024 / 1024
            max_memory = redis_info.get('maxmemory', 0)
            
            print(f"  💾 Redis memory usage: {used_memory_mb:.1f} MB")
            if max_memory > 0:
                usage_pct = (redis_info.get('used_memory', 0) / max_memory) * 100
                print(f"  📊 Redis memory usage: {usage_pct:.1f}%")
                
                if usage_pct > 90:
                    self.findings.append({
                        'type': 'REDIS_MEMORY_HIGH',
                        'usage_percent': usage_pct,
                        'severity': 'HIGH',
                        'fix': 'Redis running out of memory - may cause task failures'
                    })
            
            # Check Redis connection count
            connected_clients = redis_info.get('connected_clients', 0)
            print(f"  🔗 Redis connections: {connected_clients}")
            
            if connected_clients > 50:
                self.findings.append({
                    'type': 'HIGH_REDIS_CONNECTIONS',
                    'count': connected_clients,
                    'severity': 'MEDIUM',
                    'fix': 'High Redis connection count may indicate connection leaks'
                })
                
        except Exception as e:
            logger.error(f"Error analyzing system resources: {e}")
        
        print()
    
    def generate_fixes(self):
        """Generate specific fixes for found issues"""
        if not self.findings:
            return
            
        print("🔧 RECOMMENDED FIXES:")
        print("=" * 50)
        
        # Group by severity
        critical = [f for f in self.findings if f['severity'] == 'CRITICAL']
        high = [f for f in self.findings if f['severity'] == 'HIGH']
        medium = [f for f in self.findings if f['severity'] == 'MEDIUM']
        
        for severity, issues in [('CRITICAL', critical), ('HIGH', high), ('MEDIUM', medium)]:
            if not issues:
                continue
                
            icon = {'CRITICAL': '🚨', 'HIGH': '🔴', 'MEDIUM': '🟡'}[severity]
            print(f"\n{icon} {severity} ISSUES:")
            
            for i, issue in enumerate(issues, 1):
                print(f"\n{i}. {issue['type']}")
                print(f"   Fix: {issue['fix']}")
                
                # Provide specific commands where possible
                if issue['type'] == 'LIVE_REPORTING_BACKUP':
                    print(f"   Commands:")
                    print(f"     docker restart ecs-discord-bot-celery-live-reporting-worker-1")
                    print(f"     docker logs ecs-discord-bot-celery-live-reporting-worker-1")
                
                elif issue['type'] == 'NO_BEAT_SCHEDULE':
                    print(f"   Commands:")
                    print(f"     python emergency_cleanup.py  # Clear schedule")
                    print(f"     docker restart ecs-discord-bot-celery-beat-1")
                
                elif issue['type'] == 'MISSING_QUEUE_CONSUMERS':
                    print(f"   Commands:")
                    print(f"     Check worker startup command includes: -Q {','.join(issue['missing_queues'])}")
                    print(f"     docker logs {issue['worker']}")
        
        print("\n" + "=" * 50)
    
    def run_analysis(self):
        """Run complete root cause analysis"""
        print("=" * 80)
        print("🔬 CELERY ROOT CAUSE ANALYZER")
        print("=" * 80)
        print(f"Timestamp: {datetime.now()}")
        print()
        
        # Run all analyses
        self.analyze_worker_configuration()
        self.analyze_task_routing()
        self.analyze_task_failures()
        self.analyze_beat_scheduling()
        self.analyze_system_resources()
        
        # Generate specific fixes
        self.generate_fixes()
        
        print("\n💡 PREVENTION RECOMMENDATIONS:")
        print("1. Run monitor_celery_health.py daily to catch issues early")
        print("2. Set up alerts when queue length > 1000 messages") 
        print("3. Monitor worker logs for import/connection errors")
        print("4. Ensure beat container restarts if it crashes")
        print("5. Regular cleanup of old task metadata")
        
        print("\n" + "=" * 80)
        
        return self.findings

def main():
    analyzer = RootCauseAnalyzer()
    findings = analyzer.run_analysis()
    
    # Exit with status code indicating severity of issues found
    if any(f['severity'] == 'CRITICAL' for f in findings):
        exit(2)  # Critical issues
    elif any(f['severity'] == 'HIGH' for f in findings):
        exit(1)  # High severity issues
    else:
        exit(0)  # No critical/high issues

if __name__ == "__main__":
    main()