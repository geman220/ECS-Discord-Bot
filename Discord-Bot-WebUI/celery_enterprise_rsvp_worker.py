#!/usr/bin/env python3

"""
Enterprise RSVP Event Consumer Worker

Dedicated Celery worker for processing RSVP events from Redis Streams.
This worker handles WebSocket broadcasts and Discord embed updates
with enterprise reliability patterns.
"""

import asyncio
import logging
import signal
import sys
from celery import Celery
from kombu import Queue

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import app configuration
from app import create_app
from app.core import configure_celery

# Create Flask app and configure Celery
flask_app = create_app()
celery_app = configure_celery(flask_app)

# Configure this worker to process enterprise RSVP events
celery_app.conf.update(
    task_routes={
        'app.tasks.enterprise_rsvp.*': {'queue': 'enterprise_rsvp'},
    },
    worker_prefetch_multiplier=1,  # Process one task at a time for reliability
    task_acks_late=True,  # Acknowledge only after successful completion
    worker_max_tasks_per_child=1000,  # Restart worker after 1000 tasks
)

# Global enterprise RSVP system
_enterprise_rsvp_system = None


async def start_enterprise_rsvp_consumers():
    """Start the enterprise RSVP event consumers."""
    global _enterprise_rsvp_system
    
    try:
        logger.info("🚀 Starting enterprise RSVP event consumers...")
        
        from app.startup_enterprise_rsvp import start_enterprise_rsvp_system
        _enterprise_rsvp_system = await start_enterprise_rsvp_system()
        
        logger.info("✅ Enterprise RSVP event consumers started successfully")
        
    except Exception as e:
        logger.error(f"❌ Failed to start enterprise RSVP consumers: {e}")
        raise


async def stop_enterprise_rsvp_consumers():
    """Stop the enterprise RSVP event consumers."""
    global _enterprise_rsvp_system
    
    if _enterprise_rsvp_system:
        try:
            logger.info("🛑 Stopping enterprise RSVP event consumers...")
            await _enterprise_rsvp_system.stop()
            _enterprise_rsvp_system = None
            logger.info("✅ Enterprise RSVP event consumers stopped")
        except Exception as e:
            logger.error(f"❌ Error stopping enterprise RSVP consumers: {e}")


@celery_app.task(bind=True, queue='enterprise_rsvp')
def health_check_task(self):
    """Health check task for enterprise RSVP worker."""
    try:
        # Check if consumers are running
        if _enterprise_rsvp_system and _enterprise_rsvp_system.running:
            return {
                'status': 'healthy',
                'worker_id': self.request.id,
                'consumers_running': True
            }
        else:
            return {
                'status': 'degraded',
                'worker_id': self.request.id,
                'consumers_running': False
            }
    except Exception as e:
        logger.error(f"❌ Health check failed: {e}")
        return {
            'status': 'critical',
            'worker_id': self.request.id,
            'error': str(e)
        }


def setup_signal_handlers():
    """Setup signal handlers for graceful shutdown."""
    def signal_handler(signum, frame):
        logger.info(f"📡 Received signal {signum}, initiating graceful shutdown...")
        
        # Stop enterprise RSVP consumers
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(stop_enterprise_rsvp_consumers())
        loop.close()
        
        # Exit gracefully
        sys.exit(0)
    
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)


def main():
    """Main entry point for the enterprise RSVP worker."""
    logger.info("🏗️ Initializing enterprise RSVP event consumer worker...")
    
    # Setup signal handlers
    setup_signal_handlers()
    
    # Start enterprise RSVP consumers in background
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        loop.run_until_complete(start_enterprise_rsvp_consumers())
        
        # Keep the event loop running for async consumers
        def run_consumers():
            loop.run_forever()
        
        import threading
        consumer_thread = threading.Thread(target=run_consumers, daemon=True)
        consumer_thread.start()
        
        logger.info("🎉 Enterprise RSVP worker ready to process events")
        
        # Start Celery worker
        celery_app.worker_main([
            'worker',
            '--loglevel=info',
            '--queues=enterprise_rsvp',
            '--concurrency=2',
            '--hostname=enterprise-rsvp-worker@%h',
        ])
        
    except KeyboardInterrupt:
        logger.info("📡 Received keyboard interrupt")
    except Exception as e:
        logger.error(f"❌ Worker startup failed: {e}")
        raise
    finally:
        # Cleanup
        loop.run_until_complete(stop_enterprise_rsvp_consumers())
        loop.close()


if __name__ == '__main__':
    main()