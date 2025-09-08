#!/usr/bin/env python3
"""
Production Leak Diagnostics

This script helps identify WHERE connections are leaking by:
1. Testing specific endpoints that might have issues
2. Tracking which endpoints leave connections open
3. Monitoring connection state after each request
"""

import requests
import time
import sys
from datetime import datetime
import json

class LeakDiagnostics:
    def __init__(self, base_url):
        self.base_url = base_url.rstrip('/')
        self.results = {}
        
    def get_connection_state(self):
        """Get detailed connection state."""
        try:
            db_resp = requests.get(f"{self.base_url}/api/health/db", timeout=5)
            pool_resp = requests.get(f"{self.base_url}/api/health/pool", timeout=5)
            
            db_data = db_resp.json()
            pool_data = pool_resp.json()
            
            return {
                'total': db_data.get('connection_stats', {}).get('total', 0),
                'active': db_data.get('connection_stats', {}).get('active', 0),
                'idle': db_data.get('connection_stats', {}).get('idle', 0),
                'pool_out': pool_data.get('pool_stats', {}).get('checked_out', 0),
                'pool_in': pool_data.get('pool_stats', {}).get('checked_in', 0),
            }
        except:
            return None
    
    def test_endpoint(self, endpoint, method='GET', data=None):
        """Test a specific endpoint and check for leaks."""
        print(f"\n🔍 Testing: {method} {endpoint}")
        
        # Get baseline
        before = self.get_connection_state()
        if not before:
            print("  ❌ Could not get baseline connection state")
            return False
        
        print(f"  Before: {before['total']} total, {before['active']} active, {before['pool_out']} checked out")
        
        # Make request
        try:
            if method == 'GET':
                resp = requests.get(f"{self.base_url}{endpoint}", timeout=15)
            elif method == 'POST':
                resp = requests.post(f"{self.base_url}{endpoint}", json=data, timeout=15)
            
            status = resp.status_code
            print(f"  Response: {status}")
            
            # If 503, that's a connection issue
            if status == 503:
                print("  ⚠️ 503 Error - Connection pool exhausted!")
                return False
                
        except Exception as e:
            print(f"  ❌ Request failed: {e}")
            return False
        
        # Wait for connections to settle
        time.sleep(2)
        
        # Check after
        after = self.get_connection_state()
        if not after:
            print("  ❌ Could not get after state")
            return False
            
        print(f"  After:  {after['total']} total, {after['active']} active, {after['pool_out']} checked out")
        
        # Analyze
        leaked = False
        if after['total'] > before['total']:
            print(f"  ⚠️ LEAK: Total connections increased by {after['total'] - before['total']}")
            leaked = True
        
        if after['pool_out'] > before['pool_out']:
            print(f"  ⚠️ LEAK: Pool checked-out increased by {after['pool_out'] - before['pool_out']}")
            leaked = True
            
        if after['active'] > before['active']:
            print(f"  ⚡ Active connections still running (+{after['active'] - before['active']})")
            # This might be OK if request is still processing
            
        if not leaked:
            print("  ✅ No leak detected")
            
        # Store result
        self.results[endpoint] = {
            'leaked': leaked,
            'connection_growth': after['total'] - before['total'],
            'pool_growth': after['pool_out'] - before['pool_out']
        }
        
        return not leaked
    
    def test_suspicious_endpoints(self):
        """Test endpoints that are likely to have issues."""
        print("\n" + "=" * 60)
        print("TESTING SUSPICIOUS ENDPOINTS")
        print("=" * 60)
        
        # These are the endpoints from your error logs
        suspicious = [
            # The main failing endpoint
            ('/teams/180', 'GET'),
            
            # Related team endpoints
            ('/teams/', 'GET'),
            ('/teams/176', 'GET'),
            
            # Player endpoints that had session issues
            ('/players/profile/908', 'GET'),
            ('/api/role-impersonation/status', 'GET'),
            ('/api/role-impersonation/available-roles', 'GET'),
            
            # Scheduled messages endpoint
            ('/api/get_scheduled_messages', 'GET'),
            
            # API endpoints that might not clean up properly
            ('/api/availability/', 'GET'),
            ('/clear_sweet_alert', 'POST'),
        ]
        
        for endpoint, method in suspicious:
            self.test_endpoint(endpoint, method)
            time.sleep(3)  # Pause between tests
    
    def test_concurrent_same_endpoint(self):
        """Test if the same endpoint leaks under concurrent access."""
        print("\n" + "=" * 60)
        print("TESTING CONCURRENT ACCESS TO SAME ENDPOINT")
        print("=" * 60)
        
        endpoint = '/teams/180'
        
        # Get baseline
        before = self.get_connection_state()
        print(f"Baseline: {before['total']} connections")
        
        # Make 5 concurrent requests
        from concurrent.futures import ThreadPoolExecutor
        
        def make_request():
            try:
                return requests.get(f"{self.base_url}{endpoint}", timeout=10)
            except:
                return None
        
        print(f"Making 5 concurrent requests to {endpoint}...")
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(make_request) for _ in range(5)]
            results = [f.result() for f in futures]
        
        successful = sum(1 for r in results if r and r.status_code in [200, 302])
        print(f"Successful: {successful}/5")
        
        # Wait and check
        time.sleep(5)
        after = self.get_connection_state()
        
        print(f"After: {after['total']} connections")
        growth = after['total'] - before['total']
        
        if growth > 2:
            print(f"⚠️ CONCURRENT LEAK: Connections grew by {growth}")
            print("   This endpoint doesn't handle concurrent access well")
        elif growth > 0:
            print(f"⚡ Minor growth: {growth} connection(s)")
        else:
            print("✅ No leak under concurrent access")
    
    def test_error_paths(self):
        """Test endpoints that might error and not clean up."""
        print("\n" + "=" * 60)
        print("TESTING ERROR PATHS")
        print("=" * 60)
        
        # Test non-existent resources that might trigger error paths
        error_endpoints = [
            '/teams/99999',  # Non-existent team
            '/players/profile/99999',  # Non-existent player
            '/api/invalid_endpoint',  # Invalid API endpoint
        ]
        
        for endpoint in error_endpoints:
            self.test_endpoint(endpoint)
            time.sleep(2)
    
    def generate_report(self):
        """Generate a leak report."""
        print("\n" + "=" * 60)
        print("LEAK DIAGNOSTICS REPORT")
        print("=" * 60)
        
        leaking_endpoints = []
        clean_endpoints = []
        
        for endpoint, result in self.results.items():
            if result['leaked']:
                leaking_endpoints.append((endpoint, result))
            else:
                clean_endpoints.append(endpoint)
        
        if leaking_endpoints:
            print("\n❌ ENDPOINTS WITH LEAKS:")
            for endpoint, result in leaking_endpoints:
                print(f"  {endpoint}")
                print(f"    Connection growth: {result['connection_growth']}")
                print(f"    Pool growth: {result['pool_growth']}")
        
        if clean_endpoints:
            print("\n✅ CLEAN ENDPOINTS:")
            for endpoint in clean_endpoints:
                print(f"  {endpoint}")
        
        # Diagnosis
        print("\n🔍 DIAGNOSIS:")
        
        if not leaking_endpoints:
            print("  No leaks detected! Connection handling appears correct.")
        else:
            print("  Found leaks in specific endpoints. Likely causes:")
            print("  1. Session not closed in error handlers")
            print("  2. Background tasks holding connections")
            print("  3. Lazy loading triggering extra connections")
            print("  4. Transaction not committed/rolled back properly")
            
            # Check patterns
            if any('teams' in ep[0] for ep in leaking_endpoints):
                print("\n  📌 Team endpoints are leaking - check teams.py")
                print("     Look for: lazy loading of league.id, unclosed sessions")
            
            if any('role-impersonation' in ep[0] for ep in leaking_endpoints):
                print("\n  📌 Role impersonation endpoints are leaking")
                print("     Look for: missing session cleanup in API routes")

def main():
    if len(sys.argv) != 2:
        print("Usage: python prod_leak_diagnostics.py https://portal.ecsfc.com")
        sys.exit(1)
    
    base_url = sys.argv[1]
    
    print("🔬 PRODUCTION LEAK DIAGNOSTICS")
    print("=" * 60)
    print(f"Target: {base_url}")
    print("\n⚠️  This will make real requests to production!")
    confirm = input("Continue? (yes/no): ")
    if confirm.lower() != 'yes':
        print("Aborted.")
        return
    
    diagnostics = LeakDiagnostics(base_url)
    
    try:
        # Run tests
        diagnostics.test_suspicious_endpoints()
        diagnostics.test_concurrent_same_endpoint()
        diagnostics.test_error_paths()
        
        # Generate report
        diagnostics.generate_report()
        
    except KeyboardInterrupt:
        print("\n⛔ Diagnostics interrupted")
    except Exception as e:
        print(f"\n💥 Diagnostics failed: {e}")

if __name__ == "__main__":
    main()