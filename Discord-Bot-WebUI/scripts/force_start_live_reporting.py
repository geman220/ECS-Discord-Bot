#!/usr/bin/env python3
"""
Force Start Live Reporting Script

This script allows you to manually start live reporting for a match.
Use this when the UI button doesn't work or you need to start reporting from command line.

Usage:
    python3 force_start_live_reporting.py <match_id> <thread_id> [competition]

Example:
    python3 force_start_live_reporting.py 727213 1297303477849276597 usa.1

For production Docker:
    docker exec ecs-discord-bot-celery-live-reporting-worker-1 python3 /app/scripts/force_start_live_reporting.py 727213 1297303477849276597 usa.1
"""

import sys
import os
import logging
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

def force_start_live_reporting(match_id: str, thread_id: str, competition: str = 'usa.1'):
    """
    Force start live reporting for a match.
    
    Args:
        match_id: ESPN match ID (e.g., '727213')
        thread_id: Discord thread ID
        competition: Competition identifier (default: 'usa.1')
    """
    try:
        # Initialize Flask app context
        logger.info("Initializing Flask app context...")
        from app import create_app
        app = create_app()
        
        with app.app_context():
            # Import tasks
            logger.info("Importing V2 live reporting tasks...")
            from app.tasks.tasks_live_reporting_v2 import start_live_reporting_v2
            
            # Check if session already exists
            logger.info(f"Checking for existing session for match {match_id}...")
            from app.models.live_reporting_session import LiveReportingSession
            from app.core.session_manager import managed_session
            
            with managed_session() as session:
                existing = session.query(LiveReportingSession).filter_by(
                    match_id=match_id,
                    is_active=True
                ).first()
                
                if existing:
                    logger.warning(f"Active session already exists (ID: {existing.id})")
                    print(f"⚠️  Active session already exists for match {match_id}")
                    print(f"   Session ID: {existing.id}")
                    print(f"   Started: {existing.started_at}")
                    print(f"   Thread ID: {existing.thread_id}")
                    print(f"   Updates: {existing.update_count}")
                    
                    response = input("\nDo you want to restart this session? (y/N): ")
                    if response.lower() != 'y':
                        logger.info("Aborted by user")
                        return
                    
                    # Deactivate existing session
                    existing.is_active = False
                    existing.ended_at = datetime.utcnow()
                    session.commit()
                    logger.info(f"Deactivated existing session {existing.id}")
            
            # Submit task to Celery queue
            logger.info(f"Submitting live reporting task for match {match_id}...")
            result = start_live_reporting_v2.apply_async(
                args=[match_id, thread_id, competition],
                queue='live_reporting'
            )
            
            print(f"\n✅ Live reporting task submitted successfully!")
            print(f"   Task ID: {result.id}")
            print(f"   Match ID: {match_id}")
            print(f"   Thread ID: {thread_id}")
            print(f"   Competition: {competition}")
            
            # Wait for task result (with timeout)
            logger.info("Waiting for task result (10 second timeout)...")
            try:
                task_result = result.get(timeout=10)
                
                if task_result.get('success'):
                    print(f"\n🎉 Live reporting started successfully!")
                    print(f"   Session ID: {task_result.get('session_id')}")
                    print(f"   Message: {task_result.get('message')}")
                else:
                    print(f"\n❌ Failed to start live reporting:")
                    print(f"   Error: {task_result.get('message')}")
                    
            except Exception as timeout_error:
                print(f"\n⏱️  Task submitted but timed out waiting for result")
                print(f"   Check logs for task ID: {result.id}")
                logger.warning(f"Timeout waiting for task result: {timeout_error}")
            
            # Verify session was created
            logger.info("Verifying session creation...")
            with managed_session() as session:
                new_session = session.query(LiveReportingSession).filter_by(
                    match_id=match_id,
                    is_active=True
                ).first()
                
                if new_session:
                    print(f"\n✅ Session verified in database!")
                    print(f"   Session ID: {new_session.id}")
                    print(f"   Active: {new_session.is_active}")
                    print(f"   Started: {new_session.started_at}")
                else:
                    print(f"\n⚠️  Session not found in database - check logs for errors")
                    
    except ImportError as e:
        logger.error(f"Import error: {e}")
        print(f"\n❌ Import error: {e}")
        print("Make sure you're running this from the correct environment")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        print(f"\n❌ Unexpected error: {e}")
        sys.exit(1)

def main():
    """Main entry point for the script."""
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    
    match_id = sys.argv[1]
    thread_id = sys.argv[2]
    competition = sys.argv[3] if len(sys.argv) > 3 else 'usa.1'
    
    print(f"🚀 Force Starting Live Reporting")
    print(f"   Match ID: {match_id}")
    print(f"   Thread ID: {thread_id}")
    print(f"   Competition: {competition}")
    print("-" * 40)
    
    force_start_live_reporting(match_id, thread_id, competition)

if __name__ == "__main__":
    main()