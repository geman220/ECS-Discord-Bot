#!/usr/bin/env python3
"""
Connection Leak Detector

This script analyzes your PostgreSQL connections to identify potential leaks
by showing which connections are long-running, idle, or from unexpected sources.
"""

import os
import psycopg2
from psycopg2 import sql
import sys
from urllib.parse import urlparse
from dotenv import load_dotenv
from datetime import datetime

# Load environment variables
load_dotenv()

def get_db_connection():
    """Get a direct PostgreSQL connection using DATABASE_URL."""
    try:
        database_url = os.getenv('DATABASE_URL')
        if not database_url:
            print("ERROR: DATABASE_URL not found in environment variables")
            return None
        
        # Parse the URL
        parsed = urlparse(database_url)
        
        conn = psycopg2.connect(
            host=parsed.hostname,
            port=parsed.port or 5432,
            database=parsed.path.lstrip('/'),
            user=parsed.username,
            password=parsed.password
        )
        return conn
    except Exception as e:
        print(f"ERROR: Could not connect to database: {e}")
        return None

def analyze_connections(conn):
    """Analyze all current database connections for potential leaks."""
    cursor = conn.cursor()
    
    # Get detailed connection information
    detailed_query = """
    SELECT 
        pid,
        usename,
        application_name,
        client_addr,
        client_port,
        backend_start,
        query_start,
        state_change,
        state,
        query,
        EXTRACT(EPOCH FROM (now() - backend_start)) as backend_age_seconds,
        EXTRACT(EPOCH FROM (now() - query_start)) as query_age_seconds,
        EXTRACT(EPOCH FROM (now() - state_change)) as state_age_seconds
    FROM pg_stat_activity 
    WHERE pid != pg_backend_pid()
    ORDER BY backend_start ASC;
    """
    
    cursor.execute(detailed_query)
    connections = cursor.fetchall()
    
    print(f"=== DETAILED CONNECTION ANALYSIS ===")
    print(f"Total connections found: {len(connections)}")
    print()
    
    # Categorize connections
    categories = {
        'long_running': [],  # > 1 hour
        'idle_in_transaction': [],  # idle in transaction
        'flask_connections': [],  # application_name contains flask
        'celery_connections': [],  # application_name contains celery
        'unknown_connections': [],  # application_name is empty/unknown
        'active_queries': []  # currently running queries
    }
    
    for conn_data in connections:
        (pid, usename, app_name, client_addr, client_port, backend_start, 
         query_start, state_change, state, query, backend_age, query_age, state_age) = conn_data
        
        # Long running connections (> 1 hour)
        if backend_age and backend_age > 3600:
            categories['long_running'].append(conn_data)
        
        # Idle in transaction
        if state == 'idle in transaction':
            categories['idle_in_transaction'].append(conn_data)
        
        # Categorize by application
        if app_name:
            if 'flask' in app_name.lower():
                categories['flask_connections'].append(conn_data)
            elif 'celery' in app_name.lower():
                categories['celery_connections'].append(conn_data)
            else:
                categories['unknown_connections'].append(conn_data)
        else:
            categories['unknown_connections'].append(conn_data)
        
        # Active queries
        if state == 'active':
            categories['active_queries'].append(conn_data)
    
    # Print analysis
    print("=== CONNECTION CATEGORIES ===")
    for category, conns in categories.items():
        print(f"{category.replace('_', ' ').title()}: {len(conns)}")
    
    print("\n=== POTENTIAL LEAK SOURCES ===")
    
    # Long running connections (likely leaks)
    if categories['long_running']:
        print(f"\n🚨 LONG RUNNING CONNECTIONS ({len(categories['long_running'])} found):")
        for conn_data in categories['long_running']:
            pid, usename, app_name, client_addr, client_port, backend_start, query_start, state_change, state, query, backend_age, query_age, state_age = conn_data
            hours = backend_age / 3600
            print(f"  PID {pid}: {app_name or 'UNKNOWN'} - Running for {hours:.1f} hours")
            print(f"    State: {state}")
            print(f"    Client: {client_addr}:{client_port}")
            print(f"    Last Query: {query[:100] if query else 'None'}...")
            print()
    
    # Idle in transaction (potential leaks)
    if categories['idle_in_transaction']:
        print(f"\n⚠️  IDLE IN TRANSACTION ({len(categories['idle_in_transaction'])} found):")
        for conn_data in categories['idle_in_transaction']:
            pid, usename, app_name, client_addr, client_port, backend_start, query_start, state_change, state, query, backend_age, query_age, state_age = conn_data
            minutes = state_age / 60 if state_age else 0
            print(f"  PID {pid}: {app_name or 'UNKNOWN'} - Idle for {minutes:.1f} minutes")
            print(f"    Last Query: {query[:100] if query else 'None'}...")
            print()
    
    # Unknown connections (potential leaks)
    if categories['unknown_connections']:
        print(f"\n❓ UNKNOWN CONNECTIONS ({len(categories['unknown_connections'])} found):")
        for conn_data in categories['unknown_connections']:
            pid, usename, app_name, client_addr, client_port, backend_start, query_start, state_change, state, query, backend_age, query_age, state_age = conn_data
            hours = backend_age / 3600 if backend_age else 0
            print(f"  PID {pid}: {app_name or 'NO APP NAME'} - Running for {hours:.1f} hours")
            print(f"    State: {state}")
            print(f"    Client: {client_addr}:{client_port}")
            print()
    
    # Summary statistics
    print("\n=== SUMMARY ===")
    flask_count = len(categories['flask_connections'])
    celery_count = len(categories['celery_connections'])
    unknown_count = len(categories['unknown_connections'])
    total_app_connections = flask_count + celery_count
    
    print(f"Flask connections: {flask_count}")
    print(f"Celery connections: {celery_count}")
    print(f"Unknown connections: {unknown_count}")
    print(f"Total application connections: {total_app_connections}")
    print(f"Total connections: {len(connections)}")
    
    # Expected vs actual
    expected_connections = 6 * 2  # 6 processes * 2 pool size
    print(f"\nExpected connections (6 processes × 2 pool): {expected_connections}")
    print(f"Actual connections: {len(connections)}")
    print(f"Potential leak: {len(connections) - expected_connections} connections")
    
    # Recommendations
    print("\n=== RECOMMENDATIONS ===")
    if categories['long_running']:
        print("🔥 CRITICAL: Long-running connections found - these are likely leaks!")
        print("   Consider restarting processes or investigating connection cleanup code.")
    
    if categories['idle_in_transaction']:
        print("⚠️  WARNING: Idle in transaction connections found.")
        print("   These may be caused by uncommitted transactions or connection pool issues.")
    
    if unknown_count > 2:
        print("❓ INVESTIGATE: Many unknown connections found.")
        print("   Check if external tools or scripts are connecting to the database.")
    
    if len(connections) > expected_connections + 3:
        print("🚨 LEAK DETECTED: More connections than expected!")
        print("   Investigate application code for proper session cleanup.")
    
    cursor.close()
    return categories

def main():
    print("=== CONNECTION LEAK DETECTOR ===")
    print("Analyzing PostgreSQL connections for potential leaks...\n")
    
    # Get database connection
    conn = get_db_connection()
    if not conn:
        sys.exit(1)
    
    try:
        # Analyze connections
        categories = analyze_connections(conn)
        
        print("\n=== NEXT STEPS ===")
        print("1. Review the connections marked as potential leaks above")
        print("2. Consider restarting processes that have long-running connections")
        print("3. If leaks persist, investigate application code for unclosed sessions")
        print("4. Run this script again after making changes to verify improvements")
        
    finally:
        conn.close()

if __name__ == "__main__":
    main()