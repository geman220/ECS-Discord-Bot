# app/tasks/tasks_cache_management.py

"""
Cache Management Tasks

Background tasks for maintaining and updating various application caches,
including task status cache, match data cache, and other performance-critical data.
"""

import logging
from datetime import datetime
from celery import current_task
from app.core import celery
from app.services.task_status_cache import task_status_cache
from app.services.redis_connection_service import get_redis_service

logger = logging.getLogger(__name__)


@celery.task(bind=True, name='app.tasks.tasks_cache_management.update_task_status_cache')
def update_task_status_cache(self):
    """
    Background task to update task status cache for all active matches.
    
    Runs every 3 minutes to keep task status information fresh and reduce
    real-time database/Redis queries from the API endpoints.
    """
    task_start = datetime.utcnow()
    
    try:
        logger.info("Starting task status cache update")
        
        # Update the task progress
        if current_task:
            current_task.update_state(
                state='PROGRESS',
                meta={
                    'stage': 'starting',
                    'message': 'Initializing cache update process',
                    'timestamp': task_start.isoformat()
                }
            )
        
        # Perform the cache update
        result = task_status_cache.update_all_caches()
        
        duration = (datetime.utcnow() - task_start).total_seconds()
        
        if result['success']:
            logger.info(
                f"Task status cache update completed successfully: "
                f"{result['updated_count']} matches updated, "
                f"{result['error_count']} errors in {duration:.2f}s"
            )
            
            if current_task:
                current_task.update_state(
                    state='SUCCESS',
                    meta={
                        'stage': 'completed',
                        'updated_count': result['updated_count'],
                        'error_count': result['error_count'],
                        'total_matches': result['total_matches'],
                        'duration': duration,
                        'timestamp': datetime.utcnow().isoformat()
                    }
                )
        else:
            logger.error(f"Task status cache update failed: {result.get('error', 'Unknown error')}")
            if current_task:
                current_task.update_state(
                    state='FAILURE',
                    meta={
                        'stage': 'failed',
                        'error': result.get('error', 'Unknown error'),
                        'timestamp': datetime.utcnow().isoformat()
                    }
                )
        
        return result
        
    except Exception as e:
        logger.error(f"Error in update_task_status_cache: {e}", exc_info=True)
        
        error_result = {
            'success': False,
            'error': str(e)[:500],  # Limit error message length for serialization
            'error_type': type(e).__name__,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        if current_task:
            current_task.update_state(
                state='FAILURE',
                meta={
                    'stage': 'exception',
                    'error': str(e)[:500],
                    'error_type': type(e).__name__,
                    'timestamp': datetime.utcnow().isoformat()
                }
            )
        
        return error_result


@celery.task(bind=True, name='app.tasks.tasks_cache_management.invalidate_match_cache')
def invalidate_match_cache(self, match_id: int):
    """
    Task to invalidate cache for a specific match.
    
    Called when match data changes or task status updates occur.
    """
    try:
        logger.info(f"Invalidating cache for match {match_id}")
        
        # Invalidate the cache
        success = task_status_cache.invalidate_cache(match_id)
        
        if success:
            logger.info(f"Successfully invalidated cache for match {match_id}")
            
            # Immediately refresh the cache for this match using managed session
            try:
                from app.models.external import MLSMatch
                from app.core.session_manager import managed_session
                
                with managed_session() as session:
                    match = session.query(MLSMatch).filter_by(id=match_id).first()
                    if match:
                        # Extract match data while session is active
                        match_data = {
                            'id': match.id,
                            'discord_thread_id': getattr(match, 'discord_thread_id', None),
                            'date_time': getattr(match, 'date_time', None),
                            'opponent': getattr(match, 'opponent', None),
                            'is_home_game': getattr(match, 'is_home_game', None)
                        }
                        session.flush()
                        # Pass data to cache update to avoid lazy loading
                        task_status_cache.update_match_cache(match)
                        logger.info(f"Refreshed cache for match {match_id}")
                    else:
                        logger.warning(f"Match {match_id} not found for cache refresh")
            except Exception as cache_error:
                logger.error(f"Error refreshing cache for match {match_id}: {cache_error}")
        
        return {
            'success': success,
            'match_id': match_id,
            'timestamp': datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error invalidating cache for match {match_id}: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e),
            'match_id': match_id,
            'timestamp': datetime.utcnow().isoformat()
        }


@celery.task(bind=True, name='app.tasks.tasks_cache_management.warm_cache_for_match')
def warm_cache_for_match(self, match_id: int):
    """
    Task to proactively warm cache for a specific match.
    
    Called when a new match is created or when we want to ensure
    fresh cache data for a specific match.
    """
    try:
        logger.info(f"Warming cache for match {match_id}")
        
        from app.models.external import MLSMatch
        from app.core.session_manager import managed_session
        
        with managed_session() as session:
            match = session.query(MLSMatch).filter_by(id=match_id).first()
            if not match:
                logger.warning(f"Match {match_id} not found for cache warming")
                return {
                    'success': False,
                    'error': f'Match {match_id} not found',
                    'match_id': match_id,
                    'timestamp': datetime.utcnow().isoformat()
                }
            
            # Force evaluation of lazy-loaded attributes while session is active
            _ = match.discord_thread_id  # Touch to load
            _ = match.date_time
            _ = match.opponent
            _ = match.is_home_game
            session.flush()
            
            success = task_status_cache.update_match_cache(match)
        
        if success:
            logger.info(f"Successfully warmed cache for match {match_id}")
        else:
            logger.error(f"Failed to warm cache for match {match_id}")
        
        return {
            'success': success,
            'match_id': match_id,
            'timestamp': datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error warming cache for match {match_id}: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e),
            'match_id': match_id,
            'timestamp': datetime.utcnow().isoformat()
        }


@celery.task(bind=True, name='app.tasks.tasks_cache_management.cache_health_check')
def cache_health_check(self):
    """
    Health check task for cache system.
    
    Monitors cache performance, hit rates, and system health.
    """
    try:
        logger.info("Running cache health check")
        
        redis_service = get_redis_service()
        
        with redis_service.get_connection() as redis_client:
            # Basic Redis health check
            redis_client.ping()
            
            # Check cache statistics
            cache_keys = redis_client.keys(f"{task_status_cache.CACHE_PREFIX}:*")
            cache_count = len(cache_keys)
            
            # Sample a few cache entries to check validity
            sample_size = min(5, cache_count)
            valid_entries = 0
            
            if sample_size > 0:
                import random
                sample_keys = random.sample(cache_keys, sample_size)
                
                for key in sample_keys:
                    try:
                        data = redis_client.get(key)
                        if data:
                            import json
                            json.loads(data)  # Validate JSON
                            valid_entries += 1
                    except Exception:
                        pass
        
        health_score = (valid_entries / sample_size * 100) if sample_size > 0 else 100
        
        # Get Redis service metrics if available
        service_metrics = None
        try:
            service_metrics = redis_service.get_metrics()
        except Exception as e:
            logger.warning(f"Could not get Redis service metrics: {e}")
            service_metrics = {'error': 'metrics unavailable'}
        
        result = {
            'success': True,
            'cache_count': cache_count,
            'sample_size': sample_size,
            'valid_entries': valid_entries,
            'health_score': health_score,
            'redis_connected': True,
            'redis_metrics': service_metrics,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        logger.info(f"Cache health check completed: {cache_count} entries, {health_score:.1f}% health")
        return result
        
    except Exception as e:
        logger.error(f"Cache health check failed: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e)[:500],  # Limit error message length for serialization
            'error_type': type(e).__name__,
            'redis_connected': False,
            'timestamp': datetime.utcnow().isoformat()
        }