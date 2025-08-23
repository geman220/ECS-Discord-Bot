# app/services/task_status_cache.py

"""
Task Status Cache Service

Provides efficient background caching of match task status information.
Reduces database queries and Redis connections by pre-calculating and caching
task status data for active matches.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from app.utils.safe_redis import get_safe_redis
from app.core.session_manager import managed_session
from app.models import MLSMatch
from app.core.helpers import get_match

logger = logging.getLogger(__name__)


class TaskStatusCacheService:
    """Service for managing task status cache with background updates."""
    
    CACHE_PREFIX = "task_status"
    CACHE_TTL = 600  # 10 minutes (updated every 3 minutes by background task)
    BATCH_SIZE = 50  # Process matches in batches
    
    def __init__(self):
        self.redis = None
    
    def get_redis_client(self):
        """Get Redis client with fallback to direct connection."""
        if self.redis is None:
            try:
                import redis
                self.redis = redis.Redis(
                    host='redis', 
                    port=6379, 
                    db=0, 
                    decode_responses=True, 
                    socket_timeout=5
                )
                self.redis.ping()
                logger.debug("Direct Redis connection established for cache service")
            except Exception as e:
                logger.error(f"Failed to establish direct Redis connection: {e}")
                # Fallback to safe_redis
                self.redis = get_safe_redis()
        return self.redis
    
    def get_cache_key(self, match_id: int) -> str:
        """Generate cache key for match task status."""
        return f"{self.CACHE_PREFIX}:{match_id}"
    
    def get_active_matches(self) -> List[MLSMatch]:
        """
        Get matches that need task status caching.
        Includes matches from 2 days ago to 7 days in the future.
        """
        try:
            with managed_session() as session:
                now = datetime.utcnow()
                start_time = now - timedelta(days=2)  # Include recent matches
                end_time = now + timedelta(days=7)    # Include future matches
                
                matches = session.query(MLSMatch).filter(
                    MLSMatch.date_time >= start_time,
                    MLSMatch.date_time <= end_time
                ).order_by(MLSMatch.date_time).all()
                
                logger.info(f"Found {len(matches)} active matches for cache update")
                return matches
                
        except Exception as e:
            logger.error(f"Error getting active matches: {e}", exc_info=True)
            return []
    
    def calculate_task_status(self, match: MLSMatch) -> Dict[str, Any]:
        """
        Calculate task status for a single match using enhanced logic.
        This is the same logic as the real-time version but optimized for batch processing.
        """
        try:
            redis_client = self.get_redis_client()
            tasks = {}
            
            # Helper function for decoding Redis data
            def safe_decode(data):
                if data is None:
                    return None
                return data if isinstance(data, str) else data.decode('utf-8')
            
            # Check thread creation task
            thread_key = f"match_scheduler:{match.id}:thread"
            thread_data = redis_client.get(thread_key)
            thread_ttl = redis_client.ttl(thread_key) if thread_data else None
            
            if thread_data:
                try:
                    thread_json = json.loads(safe_decode(thread_data))
                    task_id = thread_json.get('task_id')
                    eta = thread_json.get('eta')
                    
                    # Get task status from Celery (with timeout)
                    from celery.result import AsyncResult
                    task_result = AsyncResult(task_id)
                    
                    tasks['thread'] = {
                        'task_id': task_id,
                        'eta': eta,
                        'ttl': thread_ttl,
                        'status': str(task_result.status),
                        'result': str(task_result.result) if task_result.result else None,
                        'redis_key': thread_key,
                        'type': 'Thread Creation'
                    }
                except Exception as e:
                    logger.warning(f"Error parsing thread task for match {match.id}: {e}")
                    tasks['thread'] = {
                        'error': f'Failed to parse thread task: {str(e)}',
                        'raw_data': safe_decode(thread_data)
                    }
            else:
                # Fallback logic for thread creation
                if match.discord_thread_id:
                    # Thread exists, so task completed successfully
                    tasks['thread'] = {
                        'task_id': 'unknown',
                        'eta': 'completed',
                        'status': 'SUCCESS',
                        'result': f'Thread created: {match.discord_thread_id}',
                        'type': 'Thread Creation',
                        'fallback': True,
                        'message': f'{"Sounders vs " + match.opponent if match.is_home_game else match.opponent + " vs Sounders"} thread created'
                    }
                elif match.date_time:
                    # Check if thread creation should have happened by now
                    import pytz
                    utc_tz = pytz.UTC
                    match_time = match.date_time.replace(tzinfo=utc_tz)
                    thread_time = match_time - timedelta(hours=48)  # 48 hours before
                    now = datetime.now(utc_tz)
                    
                    if now > thread_time:
                        # Thread should have been created but wasn't
                        tasks['thread'] = {
                            'task_id': 'unknown',
                            'eta': thread_time.isoformat(),
                            'status': 'MISSING',
                            'result': 'Thread creation task should have run but no thread found',
                            'type': 'Thread Creation',
                            'fallback': True,
                            'message': f'{"Sounders vs " + match.opponent if match.is_home_game else match.opponent + " vs Sounders"} - thread creation overdue'
                        }
                    else:
                        # Thread not due yet
                        tasks['thread'] = {
                            'task_id': 'scheduled',
                            'eta': thread_time.isoformat(),
                            'status': 'PENDING',
                            'result': f'Scheduled for {thread_time.strftime("%Y-%m-%d %H:%M UTC")}',
                            'type': 'Thread Creation',
                            'fallback': True,
                            'message': f'{"Sounders vs " + match.opponent if match.is_home_game else match.opponent + " vs Sounders"} - thread scheduled'
                        }
            
            # Check live reporting task
            reporting_key = f"match_scheduler:{match.id}:reporting"
            reporting_data = redis_client.get(reporting_key)
            reporting_ttl = redis_client.ttl(reporting_key) if reporting_data else None
            
            if reporting_data:
                try:
                    reporting_json = json.loads(safe_decode(reporting_data))
                    task_id = reporting_json.get('task_id')
                    eta = reporting_json.get('eta')
                    
                    # Get task status from Celery
                    from celery.result import AsyncResult
                    task_result = AsyncResult(task_id)
                    
                    tasks['reporting'] = {
                        'task_id': task_id,
                        'eta': eta,
                        'ttl': reporting_ttl,
                        'status': str(task_result.status),
                        'result': str(task_result.result) if task_result.result else None,
                        'redis_key': reporting_key,
                        'type': 'Live Reporting'
                    }
                except Exception as e:
                    logger.warning(f"Error parsing reporting task for match {match.id}: {e}")
                    tasks['reporting'] = {
                        'error': f'Failed to parse reporting task: {str(e)}',
                        'raw_data': safe_decode(reporting_data)
                    }
            else:
                # Fallback logic for live reporting
                if match.date_time:
                    import pytz
                    utc_tz = pytz.UTC
                    match_time = match.date_time.replace(tzinfo=utc_tz)
                    reporting_time = match_time - timedelta(minutes=5)  # 5 minutes before
                    now = datetime.now(utc_tz)
                    
                    if now > match_time:
                        # Match has already started/finished
                        tasks['reporting'] = {
                            'task_id': 'completed',
                            'eta': reporting_time.isoformat(),
                            'status': 'FINISHED',
                            'result': 'Match has ended',
                            'type': 'Live Reporting',
                            'fallback': True,
                            'message': f'{"Sounders vs " + match.opponent if match.is_home_game else match.opponent + " vs Sounders"} - match completed'
                        }
                    elif now > reporting_time:
                        # Reporting should have started
                        tasks['reporting'] = {
                            'task_id': 'active',
                            'eta': reporting_time.isoformat(),
                            'status': 'RUNNING',
                            'result': 'Live reporting should be active',
                            'type': 'Live Reporting',
                            'fallback': True,
                            'message': f'{"Sounders vs " + match.opponent if match.is_home_game else match.opponent + " vs Sounders"} - live reporting active'
                        }
                    else:
                        # Reporting not due yet
                        tasks['reporting'] = {
                            'task_id': 'scheduled',
                            'eta': reporting_time.isoformat(),
                            'status': 'PENDING',
                            'result': f'Scheduled for {reporting_time.strftime("%Y-%m-%d %H:%M UTC")}',
                            'type': 'Live Reporting',
                            'fallback': True,
                            'message': f'{"Sounders vs " + match.opponent if match.is_home_game else match.opponent + " vs Sounders"} - reporting scheduled'
                        }
            
            return {
                'success': True,
                'match_id': match.id,
                'tasks': tasks,
                'timestamp': datetime.utcnow().isoformat(),
                'cached': True
            }
            
        except Exception as e:
            logger.error(f"Error calculating task status for match {match.id}: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e),
                'match_id': match.id,
                'tasks': {},
                'cached': True
            }
    
    def update_match_cache(self, match: MLSMatch) -> bool:
        """Update cache for a single match."""
        try:
            redis_client = self.get_redis_client()
            cache_key = self.get_cache_key(match.id)
            
            status_data = self.calculate_task_status(match)
            
            # Store in cache with TTL
            redis_client.setex(
                cache_key, 
                self.CACHE_TTL, 
                json.dumps(status_data)
            )
            
            logger.debug(f"Updated cache for match {match.id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update cache for match {match.id}: {e}", exc_info=True)
            return False
    
    def update_all_caches(self) -> Dict[str, Any]:
        """
        Update caches for all active matches.
        This is the main method called by the background task.
        """
        start_time = datetime.utcnow()
        updated_count = 0
        error_count = 0
        
        try:
            active_matches = self.get_active_matches()
            
            for match in active_matches:
                try:
                    if self.update_match_cache(match):
                        updated_count += 1
                    else:
                        error_count += 1
                        
                except Exception as e:
                    logger.error(f"Error updating cache for match {match.id}: {e}")
                    error_count += 1
            
            duration = (datetime.utcnow() - start_time).total_seconds()
            
            result = {
                'success': True,
                'updated_count': updated_count,
                'error_count': error_count,
                'total_matches': len(active_matches),
                'duration_seconds': duration,
                'timestamp': datetime.utcnow().isoformat()
            }
            
            logger.info(f"Cache update completed: {updated_count} updated, {error_count} errors in {duration:.2f}s")
            return result
            
        except Exception as e:
            logger.error(f"Error in update_all_caches: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e),
                'updated_count': updated_count,
                'error_count': error_count,
                'timestamp': datetime.utcnow().isoformat()
            }
    
    def get_cached_status(self, match_id: int) -> Optional[Dict[str, Any]]:
        """Get cached task status for a match."""
        try:
            redis_client = self.get_redis_client()
            cache_key = self.get_cache_key(match_id)
            
            cached_data = redis_client.get(cache_key)
            if cached_data:
                return json.loads(cached_data)
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting cached status for match {match_id}: {e}", exc_info=True)
            return None
    
    def invalidate_cache(self, match_id: int) -> bool:
        """Invalidate cache for a specific match."""
        try:
            redis_client = self.get_redis_client()
            cache_key = self.get_cache_key(match_id)
            
            redis_client.delete(cache_key)
            logger.info(f"Invalidated cache for match {match_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error invalidating cache for match {match_id}: {e}", exc_info=True)
            return False


# Global instance
task_status_cache = TaskStatusCacheService()