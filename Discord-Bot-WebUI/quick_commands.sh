#!/bin/bash

# Quick Commands for ECS Discord Bot Production Environment
# Based on actual container names from docker ps

echo "🚀 QUICK DIAGNOSIS COMMANDS FOR YOUR SETUP"
echo "==========================================="
echo ""

# Your actual container names
WEBUI="ecs-discord-bot-webui-1"
WORKER="ecs-discord-bot-celery-worker-1"
LIVE_REPORTING="ecs-discord-bot-celery-live-reporting-worker-1"
BEAT="ecs-discord-bot-celery-beat-1"
REDIS="ecs-discord-bot-redis-1"

echo "📋 1. IMMEDIATE DIAGNOSIS:"
echo "========================="
echo "docker exec -it $WEBUI python diagnose_celery_tasks.py"
echo ""

echo "🔍 2. CHECK WHAT'S ACTIVE:"
echo "========================="
echo "docker exec -it $WORKER celery -A app.celery inspect active"
echo "docker exec -it $LIVE_REPORTING celery -A app.celery inspect active"
echo ""

echo "📊 3. CHECK RESERVED TASKS:"
echo "==========================="
echo "docker exec -it $WORKER celery -A app.celery inspect reserved"
echo "docker exec -it $LIVE_REPORTING celery -A app.celery inspect reserved"
echo ""

echo "🧹 4. CLEAR STUCK TASKS:"
echo "========================"
echo "docker exec -it $WEBUI python clear_stuck_tasks.py"
echo ""

echo "🔄 5. FULL CLEANUP (IF NEEDED):"
echo "==============================="
echo "docker exec -it $WEBUI python clear_stuck_tasks.py --clear-reserved --clear-locks --restart-beat"
echo "docker restart $BEAT $WORKER $LIVE_REPORTING"
echo ""

echo "⚡ 6. FORCE MATCH THREAD (REPLACE ESPN_MATCH_ID):"
echo "================================================="
echo "docker exec -it $WEBUI python clear_stuck_tasks.py --force-match-thread ESPN_MATCH_ID"
echo ""

echo "📋 7. VIEW LOGS:"
echo "================"
echo "# Worker logs:"
echo "docker logs --tail 50 $WORKER"
echo ""
echo "# Live reporting logs:"
echo "docker logs --tail 50 $LIVE_REPORTING"
echo ""
echo "# Beat logs:"
echo "docker logs --tail 50 $BEAT"
echo ""
echo "# Search for errors:"
echo "docker logs $WORKER 2>&1 | grep -i 'match.*thread\\|error'"
echo "docker logs $LIVE_REPORTING 2>&1 | grep -i 'match.*thread\\|error'"
echo ""

echo "🎯 8. SPECIFIC TO YOUR 8/29 5PM MATCH ISSUE:"
echo "============================================="
echo "# Step 1: Diagnose what's stuck"
echo "docker exec -it $WEBUI python diagnose_celery_tasks.py"
echo ""
echo "# Step 2: Clear the backup"
echo "docker exec -it $WEBUI python clear_stuck_tasks.py --clear-reserved --restart-beat"
echo "docker restart $BEAT"
echo ""
echo "# Step 3: Force the missing thread (get ESPN ID from /admin/match_management)"
echo "docker exec -it $WEBUI python clear_stuck_tasks.py --force-match-thread YOUR_ESPN_MATCH_ID"
echo ""

echo "📞 TROUBLESHOOTING NOTES:"
echo "========================="
echo "• Match threads are created by the LIVE REPORTING worker"
echo "• They should be scheduled 48h before match time"
echo "• Use ESPN match ID (not database ID) for force-run"
echo "• Check /admin/match_management for match details"
echo "• Monitor $LIVE_REPORTING logs for thread creation"
echo ""

# Now run the actual commands
echo "🔥 RUNNING IMMEDIATE DIAGNOSIS..."
echo "================================="