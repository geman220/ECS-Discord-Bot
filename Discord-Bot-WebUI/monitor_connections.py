#!/usr/bin/env python3
"""
Connection Pool Monitor Script

This script monitors database connections and helps detect leaks.
Run it alongside your dev environment to track connection usage.
"""

import os
import time
import psycopg2
from datetime import datetime
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

# Get database URL from environment
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://localhost/ecsfc')

def get_connection_stats():
    """Get current connection statistics from PostgreSQL."""
    # Use NullPool to avoid creating additional pooled connections
    engine = create_engine(DATABASE_URL, poolclass=NullPool)
    
    with engine.connect() as conn:
        # Get overall connection count
        result = conn.execute(text("""
            SELECT 
                datname,
                count(*) as connections,
                count(*) filter (where state = 'active') as active,
                count(*) filter (where state = 'idle') as idle,
                count(*) filter (where state = 'idle in transaction') as idle_in_transaction,
                count(*) filter (where state = 'idle in transaction (aborted)') as aborted
            FROM pg_stat_activity
            WHERE datname = current_database()
            GROUP BY datname
        """))
        
        stats = result.fetchone()
        
        # Get detailed connection info
        detailed = conn.execute(text("""
            SELECT 
                pid,
                usename,
                application_name,
                client_addr,
                state,
                COALESCE(EXTRACT(EPOCH FROM (NOW() - query_start)), 0) as query_duration,
                EXTRACT(EPOCH FROM (NOW() - backend_start)) as connection_age,
                EXTRACT(EPOCH FROM (NOW() - xact_start)) as transaction_age,
                LEFT(query, 100) as query_snippet
            FROM pg_stat_activity
            WHERE datname = current_database()
                AND pid != pg_backend_pid()
            ORDER BY backend_start
        """))
        
        connections = detailed.fetchall()
        
    engine.dispose()
    return stats, connections

def monitor_connections(interval=5, alert_threshold=10):
    """
    Monitor connections continuously.
    
    Args:
        interval: Seconds between checks
        alert_threshold: Alert if connections exceed this number
    """
    print("=" * 80)
    print("DATABASE CONNECTION MONITOR")
    print("=" * 80)
    print(f"Monitoring every {interval} seconds (Press Ctrl+C to stop)")
    print(f"Alert threshold: {alert_threshold} connections")
    print("=" * 80)
    
    max_connections = 0
    leak_warnings = []
    
    try:
        while True:
            stats, connections = get_connection_stats()
            
            if stats:
                total = stats['connections']
                active = stats['active']
                idle = stats['idle']
                idle_tx = stats['idle_in_transaction']
                aborted = stats['aborted']
                
                # Track maximum
                if total > max_connections:
                    max_connections = total
                
                # Display stats
                timestamp = datetime.now().strftime("%H:%M:%S")
                status_line = f"[{timestamp}] Total: {total} | Active: {active} | Idle: {idle} | Idle TX: {idle_tx}"
                
                # Color coding for warnings
                if total > alert_threshold:
                    print(f"⚠️  {status_line} ⚠️  EXCEEDS THRESHOLD!")
                elif idle_tx > 0:
                    print(f"⚡ {status_line} - IDLE TRANSACTIONS DETECTED")
                else:
                    print(f"✓  {status_line}")
                
                # Check for potential leaks (connections older than 5 minutes)
                old_connections = []
                for conn in connections:
                    age_minutes = conn['connection_age'] / 60
                    if age_minutes > 5:
                        old_connections.append({
                            'pid': conn['pid'],
                            'app': conn['application_name'],
                            'state': conn['state'],
                            'age_min': int(age_minutes),
                            'query': conn['query_snippet'][:50] if conn['query_snippet'] else 'None'
                        })
                
                if old_connections:
                    print("   ⏰ OLD CONNECTIONS (>5 min):")
                    for oc in old_connections:
                        print(f"      PID {oc['pid']}: {oc['app']} | {oc['state']} | {oc['age_min']}min | {oc['query']}")
                
                # Check for stuck transactions
                stuck_tx = []
                for conn in connections:
                    if conn['transaction_age'] and conn['transaction_age'] > 30:
                        stuck_tx.append({
                            'pid': conn['pid'],
                            'tx_age': int(conn['transaction_age']),
                            'state': conn['state']
                        })
                
                if stuck_tx:
                    print("   🔒 STUCK TRANSACTIONS (>30s):")
                    for st in stuck_tx:
                        print(f"      PID {st['pid']}: {st['state']} for {st['tx_age']}s")
                
                print(f"   Max seen: {max_connections} connections")
                print("-" * 80)
            
            time.sleep(interval)
            
    except KeyboardInterrupt:
        print("\n" + "=" * 80)
        print("MONITORING STOPPED")
        print(f"Session maximum connections: {max_connections}")
        print("=" * 80)

def check_pgbouncer_stats():
    """Check PgBouncer statistics if available."""
    try:
        # Try to connect to PgBouncer admin interface
        pgb_conn = psycopg2.connect(
            host='localhost',
            port=6432,
            database='pgbouncer',
            user='pgbouncer'
        )
        
        with pgb_conn.cursor() as cur:
            # Get pool stats
            cur.execute("SHOW POOLS;")
            pools = cur.fetchall()
            
            print("\nPGBOUNCER POOL STATS:")
            print("-" * 40)
            for pool in pools:
                print(f"Database: {pool[0]}")
                print(f"  Active: {pool[4]}, Waiting: {pool[5]}")
                print(f"  Server connections: {pool[6]}")
            
            # Get client stats
            cur.execute("SHOW CLIENTS;")
            clients = cur.fetchall()
            print(f"\nTotal PgBouncer clients: {len(clients)}")
            
        pgb_conn.close()
        
    except Exception as e:
        print(f"Could not connect to PgBouncer admin: {e}")

if __name__ == "__main__":
    import sys
    
    # Check PgBouncer first
    check_pgbouncer_stats()
    
    # Start monitoring
    interval = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    threshold = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    
    monitor_connections(interval, threshold)