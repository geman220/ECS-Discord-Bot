#!/usr/bin/env python3
# run_realtime_service.py

"""
Real-Time Live Reporting Service Runner

This script runs the dedicated real-time live reporting service as a standalone process.
It can be run alongside the Flask web app and Celery workers to provide real-time
match updates during live games.

Usage:
    python run_realtime_service.py [--debug] [--log-level INFO]
"""

import asyncio
import logging
import signal
import sys
import argparse
from pathlib import Path

# Add the app directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

from app.services.realtime_reporting_service import realtime_service
from app import create_app


class RealtimeServiceManager:
    """Manager for the real-time service with proper lifecycle management."""

    def __init__(self, log_level: str = "INFO"):
        self.log_level = log_level
        self.service_task = None
        self.is_shutting_down = False

    def setup_logging(self):
        """Setup logging for the service."""
        # Basic logging configuration
        logging.basicConfig(
            level=getattr(logging, self.log_level.upper()),
            format='%(asctime)s [%(levelname)s] %(name)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        # Create service-specific logger
        logger = logging.getLogger("realtime_service")
        logger.info(f"Real-time service logging initialized at {self.log_level} level")
        return logger

    def setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown."""
        def signal_handler(signum, frame):
            if not self.is_shutting_down:
                self.is_shutting_down = True
                logger.info(f"Received signal {signum}, initiating graceful shutdown...")
                asyncio.create_task(self.shutdown())

        # Register signal handlers
        signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
        signal.signal(signal.SIGTERM, signal_handler)  # Termination signal

    async def start_service(self):
        """Start the real-time service with proper error handling."""
        logger = logging.getLogger("realtime_service")

        try:
            logger.info("=" * 60)
            logger.info("🚀 Starting ECS Real-Time Live Reporting Service")
            logger.info("=" * 60)

            # Initialize Flask app context (needed for database connections)
            app = create_app()

            with app.app_context():
                # Start the real-time service
                self.service_task = asyncio.create_task(realtime_service.start_service())
                await self.service_task

        except asyncio.CancelledError:
            logger.info("Service task was cancelled")
        except Exception as e:
            logger.error(f"Fatal error in real-time service: {e}", exc_info=True)
            raise
        finally:
            logger.info("Real-time service stopped")

    async def shutdown(self):
        """Graceful shutdown of the service."""
        logger = logging.getLogger("realtime_service")

        logger.info("🛑 Initiating graceful shutdown...")

        try:
            # Stop the real-time service
            await realtime_service.stop_service()

            # Cancel the service task
            if self.service_task and not self.service_task.done():
                self.service_task.cancel()
                try:
                    await self.service_task
                except asyncio.CancelledError:
                    pass

            logger.info("✅ Graceful shutdown completed")

        except Exception as e:
            logger.error(f"Error during shutdown: {e}")

        # Exit the event loop
        loop = asyncio.get_running_loop()
        loop.stop()

    async def health_check_loop(self):
        """Periodic health check and status reporting."""
        logger = logging.getLogger("realtime_service.health")

        while not self.is_shutting_down:
            try:
                status = await realtime_service.get_service_status()

                # Log status every 5 minutes
                active_count = status.get('active_sessions_count', 0)
                if active_count > 0:
                    logger.info(f"📊 Health Check: {active_count} active sessions being monitored")
                else:
                    logger.debug("📊 Health Check: No active sessions")

                # Wait 5 minutes between health checks
                await asyncio.sleep(300)

            except Exception as e:
                logger.error(f"Error in health check: {e}")
                await asyncio.sleep(60)  # Shorter retry on error

    async def run(self):
        """Main run method that starts all service components."""
        # Setup signal handlers
        self.setup_signal_handlers()

        # Start health check loop
        health_task = asyncio.create_task(self.health_check_loop())

        try:
            # Run the main service
            await self.start_service()
        finally:
            # Cancel health check task
            health_task.cancel()
            try:
                await health_task
            except asyncio.CancelledError:
                pass


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="ECS Real-Time Live Reporting Service",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_realtime_service.py                    # Run with default settings
  python run_realtime_service.py --debug            # Run with debug logging
  python run_realtime_service.py --log-level DEBUG  # Set specific log level
        """
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode (sets log level to DEBUG)"
    )

    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Set logging level (default: INFO)"
    )

    args = parser.parse_args()

    # Determine log level
    log_level = "DEBUG" if args.debug else args.log_level

    # Create and run the service manager
    manager = RealtimeServiceManager(log_level=log_level)
    logger = manager.setup_logging()

    try:
        # Run the service
        asyncio.run(manager.run())
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error(f"Failed to start service: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()