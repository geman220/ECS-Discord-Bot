#!/bin/bash
# Quick monitoring script for ECS Discord Bot

echo "🔍 ECS Discord Bot - Quick Health Check"
echo "========================================"

# Check container status
echo -e "\n📦 Container Status:"
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.State}}" | grep ecs-discord

# Check memory usage
echo -e "\n💾 Memory Usage:"
docker stats --no-stream --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}" | grep ecs-discord

# Check database connections
echo -e "\n🗄️ Database Connections:"
docker exec ecs-discord-bot-webui-1 python -c "
import requests
try:
    r = requests.get('http://localhost:5000/api/db_diagnostic', timeout=5)
    data = r.json()
    print(f'  Total: {data.get(\"db_connections\", \"N/A\")}')
    print(f'  Pool Checked Out: {data.get(\"pool_checked_out\", \"N/A\")}')
except:
    print('  Unable to fetch DB stats')
" 2>/dev/null || echo "  WebUI container not accessible"

# Check Redis
echo -e "\n📊 Redis Status:"
docker exec ecs-discord-bot-redis-1 redis-cli INFO clients | grep connected_clients || echo "  Redis not accessible"

# Recent errors
echo -e "\n⚠️ Recent Errors (last 10 lines):"
docker logs ecs-discord-bot-webui-1 2>&1 | grep -i error | tail -5 || echo "  No recent errors"

echo -e "\n✅ Health check complete!"