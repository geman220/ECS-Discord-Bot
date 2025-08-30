#!/usr/bin/env python3
"""
Redis Connection Audit - Find and fix connection leaks
Usage: python redis_connection_audit.py
"""

import os
import redis
import subprocess
from collections import defaultdict
from datetime import datetime

def get_container_ips():
    """Map container IPs to container names"""
    try:
        result = subprocess.run(['docker', 'ps', '--format', '{{.Names}}'], 
                              capture_output=True, text=True, check=True)
        container_names = [name.strip() for name in result.stdout.split('\n') if 'ecs-discord-bot' in name]
        
        ip_mapping = {}
        for container_name in container_names:
            if container_name:
                try:
                    ip_result = subprocess.run(
                        ['docker', 'inspect', container_name, '--format', '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'],
                        capture_output=True, text=True, check=True
                    )
                    ip = ip_result.stdout.strip()
                    if ip:
                        ip_mapping[ip] = container_name
                except:
                    pass
        
        return ip_mapping
    except:
        return {}

def analyze_redis_connections():
    """Analyze Redis connections by container"""
    redis_client = redis.from_url('redis://redis:6379/0', socket_timeout=5)
    
    # Get all client connections
    clients = redis_client.execute_command('CLIENT', 'LIST')
    client_lines = clients.decode('utf-8').strip().split('\n')
    
    # Parse client information
    container_stats = defaultdict(lambda: {
        'total_connections': 0,
        'commands': defaultdict(int),
        'idle_times': [],
        'ages': [],
        'flags': defaultdict(int)
    })
    
    ip_mapping = get_container_ips()
    
    for client_line in client_lines:
        if not client_line:
            continue
            
        # Parse client info
        client_info = {}
        for part in client_line.split(' '):
            if '=' in part:
                key, value = part.split('=', 1)
                client_info[key] = value
        
        if 'addr' in client_info:
            ip = client_info['addr'].split(':')[0]
            container_name = ip_mapping.get(ip, f"unknown-{ip}")
            
            stats = container_stats[container_name]
            stats['total_connections'] += 1
            
            if 'cmd' in client_info:
                stats['commands'][client_info['cmd']] += 1
            
            if 'idle' in client_info:
                try:
                    stats['idle_times'].append(int(client_info['idle']))
                except:
                    pass
            
            if 'age' in client_info:
                try:
                    stats['ages'].append(int(client_info['age']))
                except:
                    pass
            
            if 'flags' in client_info:
                stats['flags'][client_info['flags']] += 1
    
    return container_stats

def main():
    print("🔍 REDIS CONNECTION AUDIT")
    print("=" * 60)
    print(f"Timestamp: {datetime.now()}")
    print()
    
    try:
        container_stats = analyze_redis_connections()
        
        total_connections = sum(stats['total_connections'] for stats in container_stats.values())
        print(f"📊 TOTAL REDIS CONNECTIONS: {total_connections}")
        print()
        
        # Analyze by container
        for container_name, stats in sorted(container_stats.items()):
            connections = stats['total_connections']
            
            # Determine if this is excessive
            expected_max = {
                'webui': 5,  # Flask app should have minimal connections
                'celery-worker': 3,
                'celery-live-reporting-worker': 3,
                'celery-discord-worker': 3,
                'celery-enterprise-rsvp-worker': 3,
                'celery-player-sync-worker': 3,
                'celery-beat': 2,
                'flower': 2,
                'discord-bot': 5,
            }
            
            expected = 10  # Default
            for key, max_conn in expected_max.items():
                if key in container_name:
                    expected = max_conn
                    break
            
            status = "🔴" if connections > expected else "🟡" if connections > expected//2 else "🟢"
            print(f"{status} {container_name}: {connections} connections (expected: ≤{expected})")
            
            # Show connection details if excessive
            if connections > expected:
                print(f"   Commands: {dict(stats['commands'])}")
                if stats['idle_times']:
                    avg_idle = sum(stats['idle_times']) / len(stats['idle_times'])
                    max_idle = max(stats['idle_times'])
                    print(f"   Idle times: avg={avg_idle:.1f}s, max={max_idle}s")
                if stats['ages']:
                    avg_age = sum(stats['ages']) / len(stats['ages'])
                    max_age = max(stats['ages'])
                    print(f"   Connection ages: avg={avg_age:.1f}s, max={max_age}s")
                print()
        
        print("💡 RECOMMENDATIONS:")
        print("-" * 40)
        
        # Check for specific issues
        webui_stats = None
        for container_name, stats in container_stats.items():
            if 'webui' in container_name:
                webui_stats = stats
                break
        
        if webui_stats and webui_stats['total_connections'] > 5:
            print(f"🚨 WebUI has {webui_stats['total_connections']} connections - likely connection leak")
            print("   Fix: Use UnifiedRedisManager instead of direct redis.Redis() calls")
            print()
        
        if total_connections > 30:
            print(f"🚨 Total connections ({total_connections}) is excessive for your setup")
            print("   Expected: ~15-20 connections total")
            print("   Issue: Multiple Redis connection pools instead of centralized management")
            print()
        
        # Check for old connections
        old_connections = []
        for container_name, stats in container_stats.items():
            if stats['ages'] and max(stats['ages']) > 3600:  # 1 hour
                old_connections.append((container_name, max(stats['ages'])))
        
        if old_connections:
            print("⚠️  Found long-lived connections (may indicate leaks):")
            for container, max_age in old_connections:
                hours = max_age / 3600
                print(f"   {container}: {hours:.1f} hours")
            print()
        
        # Connection efficiency score
        efficiency_score = min(100, max(0, 100 - (total_connections - 15) * 5))
        print(f"📈 Connection Efficiency Score: {efficiency_score}% ")
        
        if efficiency_score < 70:
            print("   🔧 Action required: Fix connection leaks")
        elif efficiency_score < 90:
            print("   ⚠️  Room for improvement")
        else:
            print("   ✅ Good connection management")
            
    except Exception as e:
        print(f"❌ Error during audit: {e}")

if __name__ == "__main__":
    main()