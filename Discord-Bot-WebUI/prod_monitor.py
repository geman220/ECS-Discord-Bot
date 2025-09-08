#!/usr/bin/env python3
"""
Production Connection Monitor

Leave this running to monitor connection usage over time.
It will alert if connections grow beyond expected levels.
"""

import requests
import time
import sys
from datetime import datetime

def get_stats(base_url):
    """Get current stats from health endpoints."""
    try:
        db_resp = requests.get(f"{base_url}/api/health/db", timeout=5)
        pool_resp = requests.get(f"{base_url}/api/health/pool", timeout=5)
        
        db_data = db_resp.json()
        pool_data = pool_resp.json()
        
        return {
            'timestamp': datetime.now().strftime("%H:%M:%S"),
            'db_total': db_data.get('connection_stats', {}).get('total', 0),
            'db_active': db_data.get('connection_stats', {}).get('active', 0),
            'db_idle': db_data.get('connection_stats', {}).get('idle', 0),
            'pool_out': pool_data.get('pool_stats', {}).get('checked_out', 0),
            'pool_in': pool_data.get('pool_stats', {}).get('checked_in', 0),
            'healthy': db_data.get('status') == 'healthy'
        }
    except Exception as e:
        return {
            'timestamp': datetime.now().strftime("%H:%M:%S"),
            'error': str(e),
            'healthy': False
        }

def main(base_url, interval=30):
    print("📊 PRODUCTION CONNECTION MONITOR")
    print("=" * 60)
    print(f"Monitoring: {base_url}")
    print(f"Interval: {interval} seconds")
    print("Press Ctrl+C to stop")
    print("=" * 60)
    
    # Track baseline
    baseline = None
    max_connections = 0
    leak_warnings = 0
    
    print("\nTime     | Total | Active | Idle | Pool Out | Status")
    print("-" * 60)
    
    try:
        while True:
            stats = get_stats(base_url)
            
            if 'error' in stats:
                print(f"{stats['timestamp']} | ERROR: {stats['error']}")
            else:
                # Track baseline after first successful read
                if baseline is None:
                    baseline = stats['db_total']
                
                # Track maximum
                max_connections = max(max_connections, stats['db_total'])
                
                # Format status
                status = "✅" if stats['healthy'] else "❌"
                
                # Check for issues
                warning = ""
                if stats['db_total'] > baseline + 5:
                    warning = " ⚠️ HIGH"
                    leak_warnings += 1
                elif stats['db_total'] > baseline + 3:
                    warning = " ⚡ GROWING"
                
                # Print stats
                print(f"{stats['timestamp']} | {stats['db_total']:5} | {stats['db_active']:6} | {stats['db_idle']:4} | {stats['pool_out']:8} | {status}{warning}")
                
                # Alert on significant growth
                if leak_warnings > 3:
                    print("\n🚨 ALERT: Sustained connection growth detected!")
                    print(f"   Baseline: {baseline}")
                    print(f"   Current: {stats['db_total']}")
                    print(f"   Maximum: {max_connections}")
                    leak_warnings = 0  # Reset counter
            
            time.sleep(interval)
            
    except KeyboardInterrupt:
        print("\n" + "=" * 60)
        print("MONITORING STOPPED")
        if baseline:
            print(f"Baseline connections: {baseline}")
            print(f"Maximum connections: {max_connections}")
            print(f"Growth: {max_connections - baseline}")
            
            if max_connections > baseline + 5:
                print("\n⚠️ Significant connection growth observed")
                print("This may indicate a connection leak")
            else:
                print("\n✅ Connection usage appears stable")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python prod_monitor.py https://portal.ecsfc.com [interval_seconds]")
        sys.exit(1)
    
    base_url = sys.argv[1].rstrip('/')
    interval = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    
    main(base_url, interval)