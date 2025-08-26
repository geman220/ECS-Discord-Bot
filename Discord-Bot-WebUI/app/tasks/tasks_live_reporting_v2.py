# app/tasks/tasks_live_reporting_v2.py

"""
Live Reporting Tasks V2

Modern async architecture implementation for live reporting tasks.
Uses industry standard patterns and the new service layer.
"""

import logging
import asyncio
from typing import Dict, Any, List
from datetime import datetime

from app.core import celery
from app.services.live_reporting import (
    LiveReportingOrchestrator,
    LiveReportingConfig,
    get_config,
    setup_metrics
)
from app.services.redis_connection_service import get_redis_service

logger = logging.getLogger(__name__)


def run_async_in_celery(coro):
    """
    Helper function to run async functions in Celery tasks.
    
    Handles the event loop conflict when Celery is already running in an event loop.
    """
    try:
        loop = asyncio.get_running_loop()
        # We're in a running event loop (Celery context)
        # Create a new thread to run the async code
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, coro)
            return future.result()
    except RuntimeError:
        # No running event loop, safe to use asyncio.run()
        return asyncio.run(coro)


@celery.task(
    name='app.tasks.tasks_live_reporting_v2.process_all_active_sessions_v2',
    bind=True,
    queue='live_reporting',
    max_retries=3
)
def process_all_active_sessions_v2(self) -> Dict[str, Any]:
    """
    Process all active live reporting sessions using new architecture.
    
    This replaces the old robust live reporting system with a cleaner,
    more maintainable approach using industry standard patterns.
    """
    try:
        logger.info("Processing all active sessions (V2)")
        
        # Use helper function to handle event loop conflicts
        result = run_async_in_celery(_process_sessions_async())
        
        logger.info(f"V2 session processing completed: {result}")
        return result
        
    except Exception as e:
        logger.error(f"Error in V2 session processing: {e}", exc_info=True)
        return {
            'success': False,
            'message': str(e),
            'processed_count': 0,
            'error_count': 1
        }


async def _process_sessions_async() -> Dict[str, Any]:
    """
    Async function to process all active sessions.
    
    Uses the new service architecture with proper dependency injection,
    error handling, and resource management.
    """
    processed_count = 0
    error_count = 0
    results = []
    
    try:
        # Initialize configuration and metrics
        config = get_config()
        metrics = setup_metrics(config)
        
        # Use orchestrator with proper resource management
        async with LiveReportingOrchestrator(config) as orchestrator:
            
            # Get all active sessions
            active_sessions = await orchestrator.get_active_sessions()
            
            if not active_sessions:
                logger.info("No active sessions to process")
                return {
                    'success': True,
                    'message': 'No active sessions',
                    'processed_count': 0,
                    'error_count': 0,
                    'results': []
                }
            
            logger.info(f"Processing {len(active_sessions)} active sessions")
            
            # Update metrics
            metrics.set_active_sessions(len(active_sessions))
            
            # Process each session
            tasks = []
            for session in active_sessions:
                task = _process_single_session(
                    orchestrator,
                    session.match_id,
                    session.thread_id,
                    session.competition
                )
                tasks.append(task)
            
            # Process sessions concurrently for better performance
            session_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Analyze results
            for i, result in enumerate(session_results):
                session = active_sessions[i]
                
                if isinstance(result, Exception):
                    logger.error(f"Error processing session {session.match_id}: {result}")
                    error_count += 1
                    results.append({
                        'match_id': session.match_id,
                        'success': False,
                        'error': str(result)
                    })
                elif result and result.success:
                    processed_count += 1
                    results.append({
                        'match_id': session.match_id,
                        'success': True,
                        'status': result.status,
                        'events_processed': result.events_processed,
                        'match_ended': result.match_ended
                    })
                else:
                    error_count += 1
                    results.append({
                        'match_id': session.match_id,
                        'success': False,
                        'error': result.error_message if result else 'Unknown error'
                    })
            
            # Update final metrics
            metrics.set_monitored_matches(processed_count)
            
            return {
                'success': True,
                'message': f'Processed {processed_count} sessions, {error_count} errors',
                'processed_count': processed_count,
                'error_count': error_count,
                'total_sessions': len(active_sessions),
                'results': results
            }
            
    except Exception as e:
        logger.error(f"Critical error in session processing: {e}", exc_info=True)
        return {
            'success': False,
            'message': f'Critical error: {e}',
            'processed_count': processed_count,
            'error_count': error_count + 1,
            'results': results
        }


async def _process_single_session(
    orchestrator: LiveReportingOrchestrator,
    match_id: str,
    thread_id: str,
    competition: str
):
    """
    Process a single live reporting session.
    
    Args:
        orchestrator: Service orchestrator
        match_id: ESPN match ID
        thread_id: Discord thread ID
        competition: Competition identifier
        
    Returns:
        MonitoringResult from the service
    """
    try:
        logger.debug(f"Processing session for match {match_id}")
        
        # Monitor the match using the new service architecture
        result = await orchestrator.monitor_match(
            match_id=match_id,
            thread_id=thread_id,
            competition=competition
        )
        
        if result.success:
            logger.debug(f"Successfully processed match {match_id}: {result.events_processed} events")
        else:
            logger.warning(f"Failed to process match {match_id}: {result.error_message}")
        
        return result
        
    except Exception as e:
        logger.error(f"Error processing session {match_id}: {e}", exc_info=True)
        raise e


@celery.task(
    name='app.tasks.tasks_live_reporting_v2.start_live_reporting_v2',
    bind=True,
    queue='live_reporting',
    max_retries=3
)
def start_live_reporting_v2(self, match_id: str, thread_id: str, competition: str = "usa.1") -> Dict[str, Any]:
    """
    Start live reporting using new architecture.
    
    Args:
        match_id: ESPN match ID
        thread_id: Discord thread ID  
        competition: Competition identifier
        
    Returns:
        Task result dictionary
    """
    try:
        logger.info(f"Starting live reporting V2 for match {match_id}")
        
        # Run async initialization
        result = run_async_in_celery(_start_live_reporting_async(match_id, thread_id, competition))
        
        logger.info(f"V2 live reporting started: {result}")
        return result
        
    except Exception as e:
        logger.error(f"Error starting V2 live reporting for match {match_id}: {e}", exc_info=True)
        return {
            'success': False,
            'message': str(e),
            'match_id': match_id
        }


async def _start_live_reporting_async(match_id: str, thread_id: str, competition: str) -> Dict[str, Any]:
    """
    Async function to start live reporting.
    
    Creates or reactivates live reporting session using the new architecture.
    """
    try:
        # First, ensure session exists using synchronous database operations
        # This ensures compatibility with the rest of the application
        from app.models import LiveReportingSession
        from app.core.session_manager import managed_session
        import json
        
        session_id = None
        reactivated = False
        
        with managed_session() as db_session:
            # Check for existing session
            existing = db_session.query(LiveReportingSession).filter_by(
                match_id=match_id
            ).first()
            
            if existing:
                if existing.is_active:
                    logger.info(f"Live reporting already active for match {match_id}")
                    return {
                        'success': True,
                        'message': f'Live reporting already active for match {match_id}',
                        'match_id': match_id,
                        'session_id': existing.id,
                        'reactivated': False
                    }
                else:
                    # Reactivate existing session
                    existing.is_active = True
                    existing.started_at = datetime.utcnow()
                    existing.ended_at = None
                    existing.thread_id = thread_id
                    existing.competition = competition
                    existing.error_count = 0
                    existing.last_error = None
                    existing.last_status = "STATUS_SCHEDULED"
                    existing.last_score = "0-0"
                    db_session.commit()
                    session_id = existing.id
                    reactivated = True
                    logger.info(f"Reactivated session {existing.id} for match {match_id}")
            else:
                # Create new session
                new_session = LiveReportingSession(
                    match_id=match_id,
                    competition=competition,
                    thread_id=thread_id,
                    is_active=True,
                    started_at=datetime.utcnow(),
                    last_status="STATUS_SCHEDULED",
                    last_score="0-0",
                    last_event_keys=json.dumps([]),
                    update_count=0,
                    error_count=0
                )
                db_session.add(new_session)
                db_session.commit()
                session_id = new_session.id
                logger.info(f"Created session {new_session.id} for match {match_id}")
        
        # Now use the orchestrator for any additional setup if needed
        config = get_config()
        
        async with LiveReportingOrchestrator(config) as orchestrator:
            # Create match context
            from app.services.live_reporting import MatchEventContext
            context = MatchEventContext(
                match_id=match_id,
                competition=competition,
                thread_id=thread_id
            )
            
            # Auto-create match record if needed
            match_repo = orchestrator._match_repo
            existing_match = await match_repo.get_match(match_id)
            if not existing_match:
                await match_repo.create_match(context)
                logger.info(f"Auto-created match record for {match_id}")
        
        return {
            'success': True,
            'message': f'{"Reactivated" if reactivated else "Started"} live reporting for match {match_id}',
            'match_id': match_id,
            'session_id': session_id,
            'reactivated': reactivated
        }
                
    except Exception as e:
        logger.error(f"Error in async live reporting start: {e}", exc_info=True)
        return {
            'success': False,
            'message': str(e),
            'match_id': match_id
        }


@celery.task(
    name='app.tasks.tasks_live_reporting_v2.stop_live_reporting_v2',
    bind=True,
    queue='live_reporting'
)
def stop_live_reporting_v2(self, match_id: str) -> Dict[str, Any]:
    """
    Stop live reporting using new architecture.
    
    Args:
        match_id: ESPN match ID
        
    Returns:
        Task result dictionary
    """
    try:
        logger.info(f"Stopping live reporting V2 for match {match_id}")
        
        # Run async stop
        result = run_async_in_celery(_stop_live_reporting_async(match_id))
        
        logger.info(f"V2 live reporting stopped: {result}")
        return result
        
    except Exception as e:
        logger.error(f"Error stopping V2 live reporting for match {match_id}: {e}", exc_info=True)
        return {
            'success': False,
            'message': str(e),
            'match_id': match_id
        }


async def _stop_live_reporting_async(match_id: str) -> Dict[str, Any]:
    """
    Async function to stop live reporting.
    """
    try:
        config = get_config()
        
        async with LiveReportingOrchestrator(config) as orchestrator:
            live_repo = orchestrator._live_repo
            
            # Deactivate the session
            success = await live_repo.deactivate_session(match_id, "Manual stop via V2 interface")
            
            if success:
                logger.info(f"Successfully stopped live reporting for match {match_id}")
                return {
                    'success': True,
                    'message': f'Stopped live reporting for match {match_id}',
                    'match_id': match_id
                }
            else:
                logger.warning(f"No active session found for match {match_id}")
                return {
                    'success': False,
                    'message': f'No active session found for match {match_id}',
                    'match_id': match_id
                }
                
    except Exception as e:
        logger.error(f"Error in async live reporting stop: {e}", exc_info=True)
        return {
            'success': False,
            'message': str(e),
            'match_id': match_id
        }


@celery.task(
    name='app.tasks.tasks_live_reporting_v2.health_check_v2',
    bind=True,
    queue='live_reporting'
)
def health_check_v2(self) -> Dict[str, Any]:
    """
    Health check for V2 live reporting system.
    
    Returns:
        Health status dictionary
    """
    try:
        logger.debug("Running V2 health check")
        
        # Run async health check
        result = run_async_in_celery(_health_check_async())
        
        return result
        
    except Exception as e:
        logger.error(f"Error in V2 health check: {e}", exc_info=True)
        return {
            'overall': False,
            'timestamp': datetime.utcnow().isoformat(),
            'error': str(e),
            'components': {}
        }


async def _health_check_async() -> Dict[str, Any]:
    """Async health check implementation."""
    try:
        config = get_config()
        
        async with LiveReportingOrchestrator(config) as orchestrator:
            health_status = await orchestrator.get_health_status()
            return health_status
            
    except Exception as e:
        logger.error(f"Error in async health check: {e}", exc_info=True)
        return {
            'overall': False,
            'timestamp': datetime.utcnow().isoformat(),
            'error': str(e),
            'components': {}
        }