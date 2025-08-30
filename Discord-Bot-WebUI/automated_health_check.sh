#!/bin/bash

# Automated Celery Health Check Script
# Run this via cron to prevent queue backups
# Suggested cron: */15 * * * * /path/to/automated_health_check.sh

set -e

# Configuration
CONTAINER_PREFIX="ecs-discord-bot"
WEBUI_CONTAINER="${CONTAINER_PREFIX}-webui-1"
WORKER_CONTAINER="${CONTAINER_PREFIX}-celery-worker-1"
LIVE_REPORTING_CONTAINER="${CONTAINER_PREFIX}-celery-live-reporting-worker-1"
BEAT_CONTAINER="${CONTAINER_PREFIX}-celery-beat-1"

# Alert thresholds
QUEUE_ALERT_THRESHOLD=2000
CRITICAL_THRESHOLD=10000

# Logging
LOG_FILE="/var/log/celery_health.log"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

log() {
    echo "[$TIMESTAMP] $1" | tee -a "$LOG_FILE"
}

send_alert() {
    local severity="$1"
    local message="$2"
    
    log "$severity: $message"
    
    # Add your notification method here (email, Slack, Discord webhook, etc.)
    # Example for webhook:
    # curl -X POST -H 'Content-type: application/json' \
    #   --data "{\"text\":\"🚨 Celery Alert [$severity]: $message\"}" \
    #   "$WEBHOOK_URL"
}

check_containers_running() {
    log "Checking if containers are running..."
    
    local containers=("$WEBUI_CONTAINER" "$WORKER_CONTAINER" "$LIVE_REPORTING_CONTAINER" "$BEAT_CONTAINER")
    
    for container in "${containers[@]}"; do
        if ! docker ps --filter "name=$container" --filter "status=running" | grep -q "$container"; then
            send_alert "CRITICAL" "Container $container is not running"
            return 1
        fi
    done
    
    log "✅ All containers are running"
    return 0
}

check_queue_health() {
    log "Checking queue health..."
    
    # Run health monitor
    if docker exec -it "$WEBUI_CONTAINER" python monitor_celery_health.py --alert-threshold "$QUEUE_ALERT_THRESHOLD" >/tmp/health_check.out 2>&1; then
        log "✅ Celery health check passed"
        return 0
    else
        local exit_code=$?
        local output=$(cat /tmp/health_check.out)
        
        if [ $exit_code -eq 1 ]; then
            send_alert "HIGH" "Celery health issues detected: $output"
        else
            send_alert "CRITICAL" "Celery health check failed: $output"
        fi
        
        return $exit_code
    fi
}

auto_fix_issues() {
    log "Running auto-fix for detected issues..."
    
    if docker exec -it "$WEBUI_CONTAINER" python monitor_celery_health.py --fix-issues --alert-threshold "$QUEUE_ALERT_THRESHOLD" >/tmp/auto_fix.out 2>&1; then
        log "✅ Auto-fix completed successfully"
        return 0
    else
        local output=$(cat /tmp/auto_fix.out)
        send_alert "HIGH" "Auto-fix failed: $output"
        return 1
    fi
}

emergency_cleanup() {
    log "🚨 EMERGENCY: Queue backup > $CRITICAL_THRESHOLD - triggering cleanup"
    
    # Check current queue length
    local queue_length=$(docker exec -it "$WEBUI_CONTAINER" python -c "
import redis, os
r = redis.from_url(os.getenv('REDIS_URL', 'redis://redis:6379/0'))
total = r.llen('celery') + r.llen('live_reporting')
print(total)
" 2>/dev/null || echo "0")
    
    if [ "$queue_length" -gt "$CRITICAL_THRESHOLD" ]; then
        send_alert "CRITICAL" "Emergency cleanup triggered - $queue_length messages in queue"
        
        # Run emergency cleanup (with auto-confirmation)
        echo "YES DELETE ALL" | docker exec -i "$WEBUI_CONTAINER" python emergency_cleanup.py >/tmp/emergency_cleanup.out 2>&1
        
        # Restart services
        log "Restarting Celery services..."
        docker restart "$BEAT_CONTAINER" "$WORKER_CONTAINER" "$LIVE_REPORTING_CONTAINER"
        
        # Wait for services to come back up
        sleep 30
        
        send_alert "HIGH" "Emergency cleanup completed - services restarted"
    fi
}

check_critical_thresholds() {
    log "Checking for critical queue thresholds..."
    
    local queue_length=$(docker exec -it "$WEBUI_CONTAINER" python -c "
import redis, os
r = redis.from_url(os.getenv('REDIS_URL', 'redis://redis:6379/0'))
total = r.llen('celery') + r.llen('live_reporting')
print(total)
" 2>/dev/null || echo "0")
    
    log "Current total queue length: $queue_length"
    
    if [ "$queue_length" -gt "$CRITICAL_THRESHOLD" ]; then
        emergency_cleanup
        return 1
    elif [ "$queue_length" -gt "$QUEUE_ALERT_THRESHOLD" ]; then
        send_alert "HIGH" "Queue backup detected: $queue_length messages"
        return 1
    fi
    
    return 0
}

run_root_cause_analysis() {
    log "Running root cause analysis..."
    
    if docker exec -it "$WEBUI_CONTAINER" python root_cause_analyzer.py >/tmp/root_cause.out 2>&1; then
        log "✅ Root cause analysis completed - no critical issues"
    else
        local exit_code=$?
        local output=$(cat /tmp/root_cause.out)
        
        if [ $exit_code -eq 2 ]; then
            send_alert "CRITICAL" "Critical issues found in root cause analysis: $output"
        elif [ $exit_code -eq 1 ]; then
            send_alert "HIGH" "High severity issues found: $output"
        fi
    fi
}

cleanup_old_logs() {
    # Keep only last 7 days of logs
    if [ -f "$LOG_FILE" ]; then
        tail -n 10000 "$LOG_FILE" > "${LOG_FILE}.tmp" && mv "${LOG_FILE}.tmp" "$LOG_FILE"
    fi
}

main() {
    log "🔍 Starting automated Celery health check"
    
    # Cleanup old logs
    cleanup_old_logs
    
    # Check if containers are running
    if ! check_containers_running; then
        log "❌ Container check failed - aborting health check"
        exit 1
    fi
    
    # Check for critical thresholds first
    if ! check_critical_thresholds; then
        log "⚠️ Critical threshold check triggered emergency actions"
    fi
    
    # Run regular health check
    if ! check_queue_health; then
        log "⚠️ Health check detected issues - attempting auto-fix"
        auto_fix_issues
    fi
    
    # Run root cause analysis every 4th run (hourly if running every 15min)
    local minute=$(date +%M)
    if [ $((minute % 60)) -eq 0 ]; then
        run_root_cause_analysis
    fi
    
    log "✅ Health check completed"
}

# Create log file if it doesn't exist
touch "$LOG_FILE"

# Run main function
main "$@"