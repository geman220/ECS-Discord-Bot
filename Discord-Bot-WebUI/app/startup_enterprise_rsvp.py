# app/startup_enterprise_rsvp.py

"""
Enterprise RSVP System Startup

Initializes and starts all components of the enterprise RSVP system:
- Event consumers for WebSocket and Discord updates
- Event publishers with Redis Streams
- Circuit breakers for external services
- Health monitoring and metrics collection

This module provides startup/shutdown functions for the production-grade RSVP system.
"""

import asyncio
import logging
import signal
import sys
from typing import Optional

logger = logging.getLogger(__name__)


class EnterpriseRSVPSystem:
    """
    Manager for the enterprise RSVP system components.
    
    Handles initialization, startup, and graceful shutdown of:
    - Event consumers (WebSocket broadcaster, Discord updater)
    - Event publishers and Redis Streams
    - Circuit breakers and monitoring
    """
    
    def __init__(self):
        self.consumers = []
        self.event_publisher = None
        self.running = False
        self._shutdown_event = asyncio.Event()
    
    async def initialize(self):
        """Initialize all RSVP system components."""
        try:
            logger.info("🚀 Initializing enterprise RSVP system...")
            
            # Initialize event publisher and streams
            from app.events.event_publisher import get_event_publisher
            self.event_publisher = await get_event_publisher()
            await self.event_publisher.initialize()
            logger.info("✅ Event publisher initialized")
            
            # Initialize and register default consumers
            from app.services.event_consumer import initialize_default_consumers
            consumers = await initialize_default_consumers()
            self.consumers.extend(consumers)
            logger.info(f"✅ Initialized {len(self.consumers)} event consumers")
            
            # Register circuit breakers
            from app.utils.circuit_breaker import register_circuit_breaker
            for consumer in self.consumers:
                if hasattr(consumer, 'circuit_breaker') and consumer.circuit_breaker:
                    register_circuit_breaker(consumer.circuit_breaker)
            logger.info("✅ Circuit breakers registered")
            
            logger.info("🎉 Enterprise RSVP system initialization complete")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize enterprise RSVP system: {e}")
            raise
    
    async def start(self):
        """Start all RSVP system components."""
        if self.running:
            logger.warning("⚠️ Enterprise RSVP system is already running")
            return
        
        try:
            logger.info("🚀 Starting enterprise RSVP system...")
            
            # Start all event consumers
            from app.services.event_consumer import start_all_consumers
            await start_all_consumers()
            
            self.running = True
            logger.info("✅ Enterprise RSVP system started successfully")
            
            # Set up signal handlers for graceful shutdown
            self._setup_signal_handlers()
            
        except Exception as e:
            logger.error(f"❌ Failed to start enterprise RSVP system: {e}")
            self.running = False
            raise
    
    async def stop(self):
        """Stop all RSVP system components gracefully."""
        if not self.running:
            logger.info("ℹ️ Enterprise RSVP system is not running")
            return
        
        try:
            logger.info("🛑 Stopping enterprise RSVP system...")
            
            # Stop all event consumers
            from app.services.event_consumer import stop_all_consumers
            await stop_all_consumers()
            
            self.running = False
            self._shutdown_event.set()
            
            logger.info("✅ Enterprise RSVP system stopped successfully")
            
        except Exception as e:
            logger.error(f"❌ Error stopping enterprise RSVP system: {e}")
            raise
    
    async def wait_for_shutdown(self):
        """Wait for shutdown signal."""
        await self._shutdown_event.wait()
    
    def _setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown."""
        def signal_handler(signum, frame):
            logger.info(f"📡 Received signal {signum}, initiating graceful shutdown...")
            asyncio.create_task(self.stop())
        
        if sys.platform != 'win32':
            signal.signal(signal.SIGTERM, signal_handler)
            signal.signal(signal.SIGINT, signal_handler)
    
    async def health_check(self) -> dict:
        """Get comprehensive health status of the RSVP system."""
        try:
            health = {
                "system_running": self.running,
                "timestamp": asyncio.get_event_loop().time(),
                "components": {}
            }
            
            # Check event publisher health
            if self.event_publisher:
                pub_health = await self.event_publisher.health_check()
                health["components"]["event_publisher"] = pub_health
            
            # Check consumer health
            from app.services.event_consumer import get_consumer_health
            consumer_health = await get_consumer_health()
            health["components"]["consumers"] = consumer_health
            
            # Check circuit breakers
            from app.utils.circuit_breaker import get_circuit_breaker_health
            cb_health = await get_circuit_breaker_health()
            health["components"]["circuit_breakers"] = cb_health
            
            # Determine overall status
            all_healthy = all(
                comp.get("status") == "healthy" 
                for comp in health["components"].values()
                if isinstance(comp, dict)
            )
            
            health["overall_status"] = "healthy" if all_healthy else "degraded"
            
            return health
            
        except Exception as e:
            logger.error(f"❌ Health check failed: {e}")
            return {
                "system_running": self.running,
                "overall_status": "critical",
                "error": str(e)
            }


# Global system instance
_enterprise_rsvp_system: Optional[EnterpriseRSVPSystem] = None


async def get_enterprise_rsvp_system() -> EnterpriseRSVPSystem:
    """Get or create the global enterprise RSVP system instance."""
    global _enterprise_rsvp_system
    
    if _enterprise_rsvp_system is None:
        _enterprise_rsvp_system = EnterpriseRSVPSystem()
        await _enterprise_rsvp_system.initialize()
    
    return _enterprise_rsvp_system


async def start_enterprise_rsvp_system():
    """Initialize and start the enterprise RSVP system."""
    system = await get_enterprise_rsvp_system()
    await system.start()
    return system


async def stop_enterprise_rsvp_system():
    """Stop the enterprise RSVP system."""
    global _enterprise_rsvp_system
    
    if _enterprise_rsvp_system:
        await _enterprise_rsvp_system.stop()
        _enterprise_rsvp_system = None


async def get_enterprise_rsvp_health() -> dict:
    """Get enterprise RSVP system health status."""
    if _enterprise_rsvp_system:
        return await _enterprise_rsvp_system.health_check()
    else:
        return {
            "system_running": False,
            "overall_status": "stopped",
            "message": "Enterprise RSVP system not initialized"
        }


# Standalone startup script for testing
async def main():
    """Main function for standalone testing."""
    try:
        logger.info("🧪 Starting enterprise RSVP system in standalone mode...")
        
        system = await start_enterprise_rsvp_system()
        
        logger.info("✅ System started successfully. Press Ctrl+C to stop.")
        
        # Wait for shutdown signal
        await system.wait_for_shutdown()
        
    except KeyboardInterrupt:
        logger.info("📡 Received keyboard interrupt")
    except Exception as e:
        logger.error(f"❌ Startup failed: {e}")
        raise
    finally:
        await stop_enterprise_rsvp_system()
        logger.info("👋 Enterprise RSVP system stopped")


if __name__ == "__main__":
    # Configure logging for standalone execution
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s - %(message)s'
    )
    
    # Run the startup script
    asyncio.run(main())