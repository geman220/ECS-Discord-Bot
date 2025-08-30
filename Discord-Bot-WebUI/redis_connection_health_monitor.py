#!/usr/bin/env python3
"""
Redis Connection Health Monitor
Monitors Redis connection health and automatically restarts workers on connection issues
Usage: Run as a background process in production
"""

import os
import time
import redis
import subprocess
import logging
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class RedisConnectionHealthMonitor:
    def __init__(self):
        self.redis_url = os.getenv('REDIS_URL', 'redis://redis:6379/0')
        self.check_interval = 60  # Check every minute
        self.failure_threshold = 3  # Restart workers after 3 consecutive failures
        self.consecutive_failures = 0
        self.last_restart = None
        self.restart_cooldown = timedelta(minutes=10)  # Don't restart more than once per 10 minutes
        
        self.worker_containers = [
            'ecs-discord-bot-celery-worker-1',
            'ecs-discord-bot-celery-live-reporting-worker-1',
            'ecs-discord-bot-celery-discord-worker-1', 
            'ecs-discord-bot-celery-enterprise-rsvp-worker-1',
            'ecs-discord-bot-celery-player-sync-worker-1'
        ]
        
    def check_redis_health(self):
        """Check Redis connection health"""
        try:
            redis_client = redis.from_url(self.redis_url, socket_timeout=10, socket_connect_timeout=5)
            
            # Test basic operations
            redis_client.ping()
            redis_client.set('health_check', 'ok', ex=60)
            result = redis_client.get('health_check')
            
            if result and result.decode('utf-8') == 'ok':
                redis_client.delete('health_check')
                return True
            else:
                logger.warning("Redis health check failed: Set/Get operation failed")
                return False
                
        except redis.TimeoutError:
            logger.error("Redis health check failed: Timeout")
            return False
        except redis.ConnectionError:
            logger.error("Redis health check failed: Connection error")
            return False
        except Exception as e:
            logger.error(f"Redis health check failed: {e}")
            return False
    
    def check_worker_connections(self):
        """Check if workers can connect to Redis"""
        try:
            from celery import Celery
            app = Celery('health_check', broker=self.redis_url, backend=self.redis_url)
            inspect = app.control.inspect()
            
            # Check if workers respond
            stats = inspect.stats()
            if not stats:
                logger.warning("No workers responding to inspection")
                return False
                
            # Check if expected queues are being consumed
            active_queues = inspect.active_queues()
            if not active_queues:
                logger.warning("No active queues found")
                return False
                
            expected_queues = {'celery', 'live_reporting', 'discord', 'enterprise_rsvp', 'player_sync'}
            consumed_queues = set()
            
            for worker, queues in active_queues.items():
                for queue_info in queues:
                    consumed_queues.add(queue_info['name'])
            
            missing_queues = expected_queues - consumed_queues
            if missing_queues:
                logger.warning(f"Missing queue consumers: {missing_queues}")
                return False
                
            return True
            
        except Exception as e:
            logger.error(f"Worker connection check failed: {e}")
            return False
    
    def restart_workers(self):
        """Restart all Celery workers"""
        if self.last_restart and datetime.now() - self.last_restart < self.restart_cooldown:
            logger.info("Skipping worker restart - still in cooldown period")
            return False
            
        logger.info("🔄 Restarting Celery workers due to connection issues...")
        
        try:
            for container in self.worker_containers:
                try:
                    result = subprocess.run(
                        ['docker', 'restart', container],
                        capture_output=True,
                        text=True,
                        timeout=60
                    )
                    
                    if result.returncode == 0:
                        logger.info(f"✅ Restarted {container}")
                    else:
                        logger.error(f"❌ Failed to restart {container}: {result.stderr}")
                        
                except subprocess.TimeoutExpired:
                    logger.error(f"❌ Timeout restarting {container}")
                except Exception as e:
                    logger.error(f"❌ Error restarting {container}: {e}")
            
            self.last_restart = datetime.now()
            logger.info("🎯 Worker restart completed")
            return True
            
        except Exception as e:
            logger.error(f"Failed to restart workers: {e}")
            return False
    
    def run_health_check(self):
        """Run a single health check cycle"""
        redis_healthy = self.check_redis_health()
        workers_healthy = self.check_worker_connections() if redis_healthy else False
        
        if redis_healthy and workers_healthy:
            if self.consecutive_failures > 0:
                logger.info("✅ Redis and workers recovered")
            self.consecutive_failures = 0
            return True
        else:
            self.consecutive_failures += 1
            logger.warning(f"⚠️  Health check failed (attempt {self.consecutive_failures}/{self.failure_threshold})")
            logger.warning(f"   Redis healthy: {redis_healthy}")
            logger.warning(f"   Workers healthy: {workers_healthy}")
            
            if self.consecutive_failures >= self.failure_threshold:
                logger.error("🚨 Failure threshold reached - triggering worker restart")
                if self.restart_workers():
                    self.consecutive_failures = 0
                    # Give workers time to start up
                    time.sleep(30)
                    
            return False
    
    def run_monitor(self):
        """Run the health monitor continuously"""
        logger.info("🏥 Starting Redis Connection Health Monitor")
        logger.info(f"   Check interval: {self.check_interval}s")
        logger.info(f"   Failure threshold: {self.failure_threshold}")
        logger.info(f"   Restart cooldown: {self.restart_cooldown}")
        logger.info(f"   Monitoring containers: {len(self.worker_containers)}")
        
        while True:
            try:
                self.run_health_check()
                time.sleep(self.check_interval)
                
            except KeyboardInterrupt:
                logger.info("Health monitor stopped by user")
                break
            except Exception as e:
                logger.error(f"Unexpected error in health monitor: {e}")
                time.sleep(self.check_interval)

def main():
    monitor = RedisConnectionHealthMonitor()
    monitor.run_monitor()

if __name__ == "__main__":
    main()