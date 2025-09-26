#!/bin/bash

# Production Celery Queue Diagnostic Script
# Run this on production to gather critical debugging information

echo "================================================================================"
echo "CELERY QUEUE PRODUCTION DIAGNOSTICS"
echo "Generated: $(date)"
echo "================================================================================"

# 1. Queue Depths and Message Analysis
echo -e "\n📊 QUEUE DEPTHS AND MESSAGE SAMPLING"
echo "--------------------------------------------------------------------------------"

# Check all queue lengths
for queue in celery live_reporting match_management discord_tasks; do
    length=$(docker exec ecs-discord-bot-redis-1 redis-cli --raw LLEN $queue)
    echo "Queue: $queue = $length messages"

    # Sample first message to understand structure
    if [ ! -z "$length" ] && [ "$length" -gt "0" ]; then
        echo "  Sample message from $queue:"
        docker exec ecs-discord-bot-redis-1 redis-cli --raw LRANGE $queue 0 0 | python3 -c "
import sys, json
try:
    msg = json.loads(sys.stdin.read())
    print(f'    Task: {msg.get(\"headers\", {}).get(\"task\", \"Unknown\")}')
    print(f'    ID: {msg.get(\"headers\", {}).get(\"id\", \"Unknown\")[:8]}...')
    if 'headers' in msg and 'retries' in msg['headers']:
        print(f'    Retries: {msg[\"headers\"][\"retries\"]}')
except: pass
" 2>/dev/null
    fi
done

# Check unacknowledged messages
unack=$(docker exec ecs-discord-bot-redis-1 redis-cli --raw LLEN celery.unacked 2>/dev/null)
if [ ! -z "$unack" ] && [ "$unack" -gt "0" ]; then
    echo -e "\n⚠️  Unacknowledged messages: $unack"
fi

# 2. Worker Status
echo -e "\n🔧 WORKER STATUS AND ACTIVITY"
echo "--------------------------------------------------------------------------------"

# Check Celery inspect via Docker
docker exec ecs-discord-bot-celery-worker-1 python -c "
import subprocess
try:
    result = subprocess.run(['celery', '-A', 'celery_worker', 'inspect', 'active', '--timeout=5'],
                          capture_output=True, text=True)
    print(result.stdout[:1000] if result.stdout else 'No active tasks')
except Exception as e:
    print(f'Could not inspect: {e}')
" 2>/dev/null || echo "Cannot inspect Celery workers"

# 3. Database Connection Analysis
echo -e "\n🔌 DATABASE CONNECTION STATUS"
echo "--------------------------------------------------------------------------------"

# Check PGBouncer stats
psql -h localhost -p 6432 -U postgres -d pgbouncer -c "SHOW POOLS;" 2>/dev/null || echo "Cannot access PGBouncer stats"

# Check active PostgreSQL connections
psql -U postgres -c "
SELECT
    datname as database,
    usename as user,
    application_name,
    state,
    COUNT(*) as connections,
    MAX(EXTRACT(EPOCH FROM (now() - state_change))) as longest_idle_seconds
FROM pg_stat_activity
WHERE datname IS NOT NULL
GROUP BY datname, usename, application_name, state
ORDER BY connections DESC
LIMIT 10;
" 2>/dev/null || echo "Cannot query PostgreSQL connections"

# 4. Recent Task Failures
echo -e "\n❌ RECENT TASK FAILURES (last 100 lines)"
echo "--------------------------------------------------------------------------------"

# Check for task failures in Docker logs
for worker in celery-worker celery-live-reporting-worker celery-discord-worker; do
    echo "Worker: $worker"
    docker logs ecs-discord-bot-${worker}-1 --since 1h 2>&1 | grep -E "ERROR|CRITICAL|Retry|ResourceClosedError|OperationalError" | tail -10
    echo ""
done

# 5. Memory and CPU Usage
echo -e "\n💻 RESOURCE USAGE"
echo "--------------------------------------------------------------------------------"

# Check memory and CPU for Celery processes
ps aux | grep -E "celery|pgbouncer|redis" | grep -v grep | awk '{printf "%-30s CPU:%-6s MEM:%-6s\n", substr($11, 0, 30), $3, $4}'

# 6. Task Distribution Analysis
echo -e "\n📈 TASK DISTRIBUTION AND RETRY ANALYSIS"
echo "--------------------------------------------------------------------------------"

# Analyze task distribution in queues with detailed retry info
for queue in celery live_reporting; do
    echo "Queue: $queue"
    docker exec ecs-discord-bot-redis-1 redis-cli --raw LRANGE $queue 0 999 2>/dev/null | python3 -c "
import sys, json
from collections import Counter, defaultdict

tasks = Counter()
retry_counts = defaultdict(list)
error_samples = {}

for line in sys.stdin:
    try:
        msg = json.loads(line.strip())
        headers = msg.get('headers', {})
        task = headers.get('task', 'Unknown')
        tasks[task] += 1
        retries = headers.get('retries', 0)
        if retries > 0:
            retry_counts[task].append(retries)
            # Capture error info if available
            if 'exc' in headers or 'errbacks' in headers:
                error_samples[task] = str(headers.get('exc', headers.get('errbacks', '')))[:200]
    except: pass

for task, count in tasks.most_common(10):
    retries = retry_counts.get(task, [])
    if retries:
        max_retry = max(retries)
        avg_retry = sum(retries) / len(retries)
        print(f'  {task}:')
        print(f'    Total: {count} messages')
        print(f'    With retries: {len(retries)} (max: {max_retry}, avg: {avg_retry:.1f})')
        if task in error_samples:
            print(f'    Error sample: {error_samples[task][:100]}...')
    else:
        print(f'  {task}: {count} messages (no retries)')
" 2>/dev/null
done

# 7. Root Cause Analysis
echo -e "\n🔍 ROOT CAUSE ANALYSIS"
echo "--------------------------------------------------------------------------------"

# Check for specific error patterns in recent logs
echo "Checking for PGBouncer/SQLAlchemy errors in last hour:"
for worker in celery-worker celery-live-reporting-worker celery-discord-worker; do
    echo "  $worker:"
    docker logs ecs-discord-bot-${worker}-1 --since 1h 2>&1 | grep -c "DISCARD ALL cannot run" | xargs echo "    DISCARD ALL errors:"
    docker logs ecs-discord-bot-${worker}-1 --since 1h 2>&1 | grep -c "ResourceClosedError" | xargs echo "    ResourceClosedError:"
    docker logs ecs-discord-bot-${worker}-1 --since 1h 2>&1 | grep -c "server closed the connection" | xargs echo "    Connection closed:"
    docker logs ecs-discord-bot-${worker}-1 --since 1h 2>&1 | grep -c "server login has been failing" | xargs echo "    Login failures:"
done

# 8. Configuration Check
echo -e "\n⚙️  CRITICAL CONFIGURATION"
echo "--------------------------------------------------------------------------------"

# Check PGBouncer pool mode
echo "PGBouncer Configuration:"
docker exec ecs-discord-bot-pgbouncer-1 cat /etc/pgbouncer/pgbouncer.ini 2>/dev/null | grep -E "pool_mode|max_client_conn|default_pool_size" || echo "  Cannot read PGBouncer config from container"

# Check if using PGBouncer via Docker
if docker exec ecs-discord-bot-pgbouncer-1 psql -h localhost -p 5432 -U postgres -d pgbouncer -c "SHOW CONFIG;" 2>/dev/null | grep -q "pool_mode"; then
    echo "  ✅ PGBouncer is active"
    docker exec ecs-discord-bot-pgbouncer-1 psql -h localhost -p 5432 -U postgres -d pgbouncer -c "SHOW CONFIG;" 2>/dev/null | grep pool_mode
else
    echo "  ⚠️  Cannot verify PGBouncer status (container may not have psql)"
fi

# Check Celery worker concurrency
ps aux | grep -E "celery.*worker" | grep -v grep | wc -l | xargs echo "Total Celery worker processes:"

echo -e "\n================================================================================"
echo "DIAGNOSTIC SUMMARY"
echo "================================================================================"

echo -e "\n🎯 KEY INDICATORS TO CHECK:"
echo "1. If DISCARD ALL errors > 0: PGBouncer transaction pooling conflict"
echo "2. If max retries >= 3: Tasks hitting retry limit"
echo "3. If connection closed/login failures > 0: Connection pool exhaustion"
echo "4. If pool_mode = 'transaction': Need session pooling or code fixes"
echo ""
echo "📋 NEXT STEPS:"
echo "1. Review the error patterns above"
echo "2. Check if code fixes have been applied"
echo "3. Only run cleanup_stuck_messages.py AFTER confirming fixes are in place"
echo "4. Monitor queue lengths after cleanup to ensure issue is resolved"