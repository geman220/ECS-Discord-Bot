#!/bin/bash
# Queue monitoring script - run this to track queue growth
echo "Starting 10-minute queue monitoring..."
echo "Time,Celery,Live_Reporting,Discord,Total" > queue_log.csv

for i in {1..20}; do
    timestamp=$(date '+%H:%M:%S')

    # Get queue lengths
    result=$(docker exec ecs-discord-bot-webui-1 python -c "
import redis
r = redis.from_url('redis://redis:6379/0')
queues = ['celery', 'live_reporting', 'discord', 'player_sync', 'enterprise_rsvp']
lengths = [r.llen(q) for q in queues]
total = sum(lengths)
print(f'{lengths[0]},{lengths[1]},{lengths[2]},{total}')
")

    echo "$timestamp,$result" | tee -a queue_log.csv
    echo "[$timestamp] Celery: $(echo $result | cut -d',' -f1), Total: $(echo $result | cut -d',' -f4)"

    # Break early if we see significant growth
    celery_count=$(echo $result | cut -d',' -f1)
    if [ "$celery_count" -gt 100 ]; then
        echo "ALERT: Celery queue exceeded 100 tasks - stopping monitoring"
        break
    fi

    sleep 30
done

echo "Monitoring complete. Check queue_log.csv for full data."