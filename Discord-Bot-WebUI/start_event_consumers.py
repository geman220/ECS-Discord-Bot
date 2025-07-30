#!/usr/bin/env python3
"""
Start Event Consumers for Enterprise RSVP System

This script starts the event consumers that handle:
- WebSocket broadcasts for real-time updates
- Discord embed updates when RSVPs change

Run this alongside the Flask app to enable event-driven updates.
"""

import asyncio
import logging
import signal
import sys
from app import create_app
from app.services.event_consumer import (
    initialize_default_consumers,
    start_all_consumers,
    stop_all_consumers,
    get_consumer_health
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global flag for graceful shutdown
shutdown_requested = False

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global shutdown_requested
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    shutdown_requested = True

async def health_check_loop():
    """Periodically check and log consumer health."""
    while not shutdown_requested:
        try:
            health = get_consumer_health()
            logger.info(f"🏥 Consumer health: {health['overall_status']} "
                       f"({health['total_consumers']} consumers)")
            
            # Log any unhealthy consumers
            for name, consumer_health in health['consumers'].items():
                if consumer_health['status'] != 'healthy':
                    logger.warning(f"⚠️ Consumer '{name}' is {consumer_health['status']}")
            
            # Wait 60 seconds before next health check
            await asyncio.sleep(60)
            
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in health check loop: {e}")
            await asyncio.sleep(60)

async def main():
    """Main async function to run event consumers."""
    logger.info("🚀 Starting Enterprise RSVP Event Consumers...")
    
    # Create Flask app context for database access
    app = create_app()
    
    with app.app_context():
        try:
            # Initialize default consumers (WebSocket, Discord)
            logger.info("🔧 Initializing event consumers...")
            await initialize_default_consumers()
            
            # Start all consumers
            logger.info("▶️ Starting event consumers...")
            await start_all_consumers()
            
            # Start health check loop
            health_task = asyncio.create_task(health_check_loop())
            
            logger.info("✅ Event consumers started successfully!")
            logger.info("📡 Listening for RSVP events...")
            
            # Keep running until shutdown is requested
            while not shutdown_requested:
                await asyncio.sleep(1)
            
            # Graceful shutdown
            logger.info("🛑 Shutting down event consumers...")
            
            # Cancel health check
            health_task.cancel()
            try:
                await health_task
            except asyncio.CancelledError:
                pass
            
            # Stop all consumers
            await stop_all_consumers()
            
            logger.info("✅ Event consumers shut down successfully")
            
        except Exception as e:
            logger.error(f"❌ Fatal error in event consumer system: {e}", exc_info=True)
            sys.exit(1)

if __name__ == "__main__":
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Run the async main function
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error(f"Unhandled exception: {e}", exc_info=True)
        sys.exit(1)