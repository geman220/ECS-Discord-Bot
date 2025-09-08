#!/usr/bin/env python3
"""
Production Health Check Script

Run this after deployment to quickly validate connection handling.
Usage: python prod_health_check.py https://portal.ecsfc.com
"""

import sys
import requests
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

def test_endpoint(base_url, endpoint, timeout=10):
    """Test a single endpoint and return status info."""
    url = f"{base_url.rstrip('/')}{endpoint}"
    try:
        start_time = time.time()
        response = requests.get(url, timeout=timeout)
        duration = time.time() - start_time
        
        return {
            'endpoint': endpoint,
            'status_code': response.status_code,
            'duration': duration,
            'success': response.status_code in [200, 302],
            'error': None
        }
    except Exception as e:
        return {
            'endpoint': endpoint,
            'status_code': None,
            'duration': None,
            'success': False,
            'error': str(e)
        }

def run_health_check(base_url):
    """Run comprehensive health check."""
    print(f"🔍 Testing {base_url}")
    print("=" * 60)
    
    # Test endpoints that were failing
    endpoints = [
        "/",
        "/teams/",
        "/teams/180",  # This was the failing endpoint
        "/players/",
        "/api/get_scheduled_messages",
        "/api/role-impersonation/status",
        "/api/role-impersonation/available-roles"
    ]
    
    # Test each endpoint sequentially first
    print("📋 Sequential Tests:")
    for endpoint in endpoints:
        result = test_endpoint(base_url, endpoint)
        status = "✅" if result['success'] else "❌"
        duration = f"{result['duration']:.2f}s" if result['duration'] else "N/A"
        
        if result['success']:
            print(f"{status} {endpoint} - {result['status_code']} ({duration})")
        else:
            print(f"{status} {endpoint} - {result.get('error', 'Unknown error')}")
    
    # Test concurrent load
    print(f"\n🚀 Concurrent Tests (10 requests):")
    
    failed_count = 0
    timeout_count = 0
    error_503_count = 0
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        # Submit 10 concurrent requests to the problematic endpoint
        futures = [
            executor.submit(test_endpoint, base_url, "/teams/180")
            for _ in range(10)
        ]
        
        for future in as_completed(futures):
            result = future.result()
            
            if not result['success']:
                failed_count += 1
                if result['status_code'] == 503:
                    error_503_count += 1
                elif 'timeout' in str(result['error']).lower():
                    timeout_count += 1
            
            status = "✅" if result['success'] else "❌"
            if result['success']:
                print(f"{status} {result['duration']:.2f}s")
            else:
                print(f"{status} {result.get('error', 'Failed')}")
    
    # Summary
    print(f"\n📊 Results:")
    print(f"Failed requests: {failed_count}/10")
    print(f"503 errors (connection issues): {error_503_count}")
    print(f"Timeouts: {timeout_count}")
    
    if error_503_count > 0:
        print("⚠️  503 errors indicate connection pool exhaustion!")
    elif failed_count > 2:
        print("⚠️  High failure rate detected!")
    else:
        print("✅ Connection handling looks healthy!")
    
    return error_503_count == 0 and failed_count <= 2

def main():
    if len(sys.argv) != 2:
        print("Usage: python prod_health_check.py https://portal.ecsfc.com")
        sys.exit(1)
    
    base_url = sys.argv[1]
    
    print("🏥 PRODUCTION HEALTH CHECK")
    print("=" * 60)
    
    try:
        success = run_health_check(base_url)
        
        if success:
            print("\n🎉 HEALTH CHECK PASSED!")
            print("Connection handling appears to be working correctly.")
            sys.exit(0)
        else:
            print("\n💥 HEALTH CHECK FAILED!")
            print("Connection issues detected. Check logs and PgBouncer configuration.")
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n🛑 Health check interrupted")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 Health check error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()