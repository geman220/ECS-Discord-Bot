#!/usr/bin/env python3
"""
Production Stress Test - CAREFUL VERSION

This will make controlled concurrent requests to test for connection leaks.
It monitors the health endpoints to track connection growth.
"""

import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import sys
import json

def check_health(base_url):
    """Check current connection status."""
    try:
        # Check DB health
        db_resp = requests.get(f"{base_url}/api/health/db", timeout=5)
        db_data = db_resp.json()
        
        # Check pool health
        pool_resp = requests.get(f"{base_url}/api/health/pool", timeout=5)
        pool_data = pool_resp.json()
        
        return {
            'db_connections': db_data.get('connection_stats', {}).get('total', 0),
            'pool_checked_out': pool_data.get('pool_stats', {}).get('checked_out', 0),
            'pool_checked_in': pool_data.get('pool_stats', {}).get('checked_in', 0),
            'status': 'healthy' if db_data['status'] == 'healthy' else 'unhealthy'
        }
    except Exception as e:
        return {'error': str(e), 'status': 'error'}

def make_request(base_url, endpoint="/teams/180"):
    """Make a single request."""
    try:
        resp = requests.get(f"{base_url}{endpoint}", timeout=10)
        return {'status': resp.status_code, 'error': None}
    except Exception as e:
        return {'status': None, 'error': str(e)}

def run_wave(base_url, num_requests=5):
    """Run a wave of concurrent requests."""
    results = {'success': 0, 'failed': 0, 'errors': []}
    
    with ThreadPoolExecutor(max_workers=num_requests) as executor:
        futures = [executor.submit(make_request, base_url) for _ in range(num_requests)]
        
        for future in as_completed(futures):
            result = future.result()
            if result['error'] or result['status'] not in [200, 302]:
                results['failed'] += 1
                if result['error']:
                    results['errors'].append(result['error'])
            else:
                results['success'] += 1
    
    return results

def main(base_url):
    print("🧪 PRODUCTION CONNECTION LEAK TEST")
    print("=" * 60)
    print("⚠️  This will make real requests to production!")
    confirm = input("Continue? (yes/no): ")
    if confirm.lower() != 'yes':
        print("Aborted.")
        return
    
    # Initial health check
    print("\n📊 Initial State:")
    initial = check_health(base_url)
    print(f"DB Connections: {initial.get('db_connections', 'N/A')}")
    print(f"Pool Checked Out: {initial.get('pool_checked_out', 'N/A')}")
    print(f"Pool Checked In: {initial.get('pool_checked_in', 'N/A')}")
    
    # Run waves of requests
    waves = [
        (5, 1),   # 5 concurrent, 1 second pause
        (10, 2),  # 10 concurrent, 2 second pause
        (15, 3),  # 15 concurrent, 3 second pause
        (20, 5),  # 20 concurrent, 5 second pause
    ]
    
    for wave_num, (concurrent, pause) in enumerate(waves, 1):
        print(f"\n🌊 Wave {wave_num}: {concurrent} concurrent requests...")
        
        # Run the wave
        results = run_wave(base_url, concurrent)
        print(f"  ✅ Success: {results['success']}")
        print(f"  ❌ Failed: {results['failed']}")
        
        if results['errors']:
            print(f"  Errors: {results['errors'][:3]}")  # Show first 3 errors
        
        # Check health after wave
        time.sleep(1)  # Let connections settle
        health = check_health(base_url)
        print(f"  📊 After wave:")
        print(f"     DB Connections: {health.get('db_connections', 'N/A')}")
        print(f"     Pool Checked Out: {health.get('pool_checked_out', 'N/A')}")
        
        # Check for connection growth
        if health.get('db_connections', 0) > initial.get('db_connections', 0) + 5:
            print("  ⚠️  WARNING: Significant connection growth detected!")
        
        if health['status'] == 'unhealthy':
            print("  💥 System unhealthy! Stopping test.")
            break
        
        # Pause before next wave
        print(f"  ⏸️  Pausing {pause} seconds...")
        time.sleep(pause)
    
    # Final check after all waves
    print("\n📊 Final State (after 10 second cooldown):")
    time.sleep(10)
    final = check_health(base_url)
    print(f"DB Connections: {final.get('db_connections', 'N/A')}")
    print(f"Pool Checked Out: {final.get('pool_checked_out', 'N/A')}")
    print(f"Pool Checked In: {final.get('pool_checked_in', 'N/A')}")
    
    # Compare initial vs final
    initial_conns = initial.get('db_connections', 0)
    final_conns = final.get('db_connections', 0)
    
    print("\n🔍 ANALYSIS:")
    print(f"Connection growth: {final_conns - initial_conns}")
    
    if final_conns > initial_conns + 2:
        print("❌ POTENTIAL LEAK: Connections grew significantly")
        print("   This suggests connections aren't being properly released")
    elif final_conns > initial_conns:
        print("⚠️  MINOR GROWTH: Small connection increase")
        print("   This might be normal caching or could indicate a slow leak")
    else:
        print("✅ NO LEAK DETECTED: Connections returned to baseline")
        print("   Connection pooling appears to be working correctly")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python prod_stress_test.py https://portal.ecsfc.com")
        sys.exit(1)
    
    base_url = sys.argv[1].rstrip('/')
    
    try:
        main(base_url)
    except KeyboardInterrupt:
        print("\n⛔ Test interrupted")
    except Exception as e:
        print(f"\n💥 Test failed: {e}")