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
from app.services.redis_connection_service import get_redis_service
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
        self._redis_service = get_redis_service()
    
    def get_redis_client(self):
        """Get Redis service with enterprise-grade connection pooling."""
        return self._redis_service
    
    def get_cache_key(self, match_id: int) -> str:
        """Generate cache key for match task status."""
        return f"{self.CACHE_PREFIX}:{match_id}"
    
    def get_active_matches(self) -> List[Dict[str, Any]]:
        """
        Get match data that needs task status caching.
        Includes matches from 2 days ago to 7 days in the future.
        Returns match data as dictionaries to avoid session attachment issues.
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
                
                # Extract data to avoid session attachment issues
                match_data = []
                for match in matches:
                    match_data.append({
                        'id': match.id,
                        'date_time': match.date_time,
                        'opponent': getattr(match, "opponent", "TBD"),
                        'is_home_game': getattr(match, "is_home_game", False),
                        'discord_thread_id': match.discord_thread_id
                    })
                
                logger.info(f"Found {len(match_data)} active matches for cache update")
                return match_data
                
        except Exception as e:
            logger.error(f"Error getting active matches: {e}", exc_info=True)
            return []
    
    def calculate_task_status(self, match_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculate task status for a single match using enhanced logic.
        This is the same logic as the real-time version but optimized for batch processing.
        """
        try:
            redis_service = self.get_redis_client()
            tasks = {}
            match_id = match_data['id']
            
            # Helper function for decoding Redis data
            def safe_decode(data):
                if data is None:
                    return None
                return data if isinstance(data, str) else data.decode('utf-8')
            
            with redis_service.get_connection() as redis_client:
                # Check thread creation task
                thread_key = f"match_scheduler:{match_id}:thread"
                thread_data = redis_client.get(thread_key)
                thread_ttl = redis_client.ttl(thread_key) if thread_data else None
                
                # Check live reporting task
                reporting_key = f"match_scheduler:{match_id}:reporting"
                reporting_data = redis_client.get(reporting_key)
                reporting_ttl = redis_client.ttl(reporting_key) if reporting_data else None
            
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
                    logger.warning(f"Error parsing thread task for match {match_id}: {e}")
                    tasks['thread'] = {
                        'error': f'Failed to parse thread task: {str(e)}',
                        'raw_data': safe_decode(thread_data)
                    }
            else:
                # Fallback logic for thread creation
                if match_data['discord_thread_id']:
                    # Thread exists, so task completed successfully
                    tasks['thread'] = {
                        'task_id': 'unknown',
                        'eta': 'completed',
                        'status': 'SUCCESS',
                        'result': f'Thread created: {match_data["discord_thread_id"]}',
                        'type': 'Thread Creation',
                        'fallback': True,
                        'message': f'{"Sounders vs " + match_data.get("opponent", "TBD") if match_data.get("is_home_game") else match_data.get("opponent", "TBD") + " vs Sounders"} thread created'
                    }
                elif match_data.get("date_time"):
                    # Check if thread creation should have happened by now
                    import pytz
                    utc_tz = pytz.UTC
                    
                    # Handle both datetime objects and ISO strings
                    date_time = match_data['date_time']
                    if isinstance(date_time, str):
                        from dateutil.parser import parse
                        match_time = parse(date_time).replace(tzinfo=utc_tz)
                    else:
                        match_time = date_time.replace(tzinfo=utc_tz)
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
                            'message': f'{"Sounders vs " + match_data.get("opponent", "TBD") if match_data.get("is_home_game", False) else match_data.get("opponent", "TBD") + " vs Sounders"} - thread creation overdue'
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
                            'message': f'{"Sounders vs " + match_data.get("opponent", "TBD") if match_data.get("is_home_game", False) else match_data.get("opponent", "TBD") + " vs Sounders"} - thread scheduled'
                        }
            
            
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
                    logger.warning(f"Error parsing reporting task for match {match_data['id']}: {e}")
                    tasks['reporting'] = {
                        'error': f'Failed to parse reporting task: {str(e)}',
                        'raw_data': safe_decode(reporting_data)
                    }
            else:
                # Fallback logic for live reporting
                if match_data.get("date_time"):
                    import pytz
                    utc_tz = pytz.UTC
                    
                    # Handle both datetime objects and ISO strings
                    date_time = match_data['date_time']
                    if isinstance(date_time, str):
                        from dateutil.parser import parse
                        match_time = parse(date_time).replace(tzinfo=utc_tz)
                    else:
                        match_time = date_time.replace(tzinfo=utc_tz)
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
                            'message': f'{"Sounders vs " + match_data.get("opponent", "TBD") if match_data.get("is_home_game", False) else match_data.get("opponent", "TBD") + " vs Sounders"} - match completed'
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
                            'message': f'{"Sounders vs " + match_data.get("opponent", "TBD") if match_data.get("is_home_game", False) else match_data.get("opponent", "TBD") + " vs Sounders"} - live reporting active'
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
                            'message': f'{"Sounders vs " + match_data.get("opponent", "TBD") if match_data.get("is_home_game", False) else match_data.get("opponent", "TBD") + " vs Sounders"} - reporting scheduled'
                        }
            
            return {
                'success': True,
                'match_id': match_data['id'],
                'tasks': tasks,
                'timestamp': datetime.utcnow().isoformat(),
                'cached': True
            }
            
        except Exception as e:
            logger.error(f"Error calculating task status for match {match_data['id']}: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e),
                'match_id': match_data['id'],
                'tasks': {},
                'cached': True
            }
    
    def update_match_cache(self, match_data) -> bool:
        """Update cache for a single match using match data dictionary or SQLAlchemy object."""
        try:
            redis_service = self.get_redis_client()

            # Handle both dictionary and SQLAlchemy object
            if hasattr(match_data, 'id'):
                # SQLAlchemy object
                match_id = match_data.id
                # Convert to dict for calculate_task_status
                # Handle both MLSMatch (date_time) and regular Match (date/time)
                if hasattr(match_data, 'date_time'):
                    # MLSMatch object
                    match_dict = {
                        'id': match_data.id,
                        'date': match_data.date_time.date() if match_data.date_time else None,
                        'time': match_data.date_time.time() if match_data.date_time else None,
                        'home_team_id': None,  # MLSMatch doesn't have team IDs
                        'away_team_id': None,
                        'home_team_message_id': None,
                        'away_team_message_id': None,
                        # Add other relevant fields as needed
                    }
                else:
                    # Regular Match object
                    match_dict = {
                        'id': match_data.id,
                        'date': match_data.date,
                        'time': match_data.time,
                        'home_team_id': match_data.home_team_id,
                        'away_team_id': match_data.away_team_id,
                        'home_team_message_id': match_data.home_team_message_id,
                        'away_team_message_id': match_data.away_team_message_id,
                        # Add other relevant fields as needed
                    }
            else:
                # Dictionary
                match_id = match_data['id']
                match_dict = match_data

            cache_key = self.get_cache_key(match_id)
            status_data = self.calculate_task_status(match_dict)

            # Store in cache with TTL using connection pooling
            with redis_service.get_connection() as redis_client:
                redis_client.setex(
                    cache_key,
                    self.CACHE_TTL,
                    json.dumps(status_data)
                )

            logger.debug(f"Updated cache for match {match_id}")
            return True

        except Exception as e:
            # Handle both object types for error logging
            if hasattr(match_data, 'id'):
                match_id = getattr(match_data, 'id', 'unknown')
            else:
                match_id = match_data.get('id', 'unknown') if isinstance(match_data, dict) else 'unknown'
            logger.error(f"Failed to update cache for match {match_id}: {e}", exc_info=True)
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
            
            for match_data in active_matches:
                try:
                    if self.update_match_cache(match_data):
                        updated_count += 1
                    else:
                        error_count += 1
                        
                except Exception as e:
                    match_id = match_data.get('id', 'unknown')
                    logger.error(f"Error updating cache for match {match_id}: {e}")
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
            redis_service = self.get_redis_client()
            cache_key = self.get_cache_key(match_id)
            
            with redis_service.get_connection() as redis_client:
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
            redis_service = self.get_redis_client()
            cache_key = self.get_cache_key(match_id)
            
            with redis_service.get_connection() as redis_client:
                redis_client.delete(cache_key)
            
            logger.info(f"Invalidated cache for match {match_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error invalidating cache for match {match_id}: {e}", exc_info=True)
            return False


# Global instance
task_status_cache = TaskStatusCacheService()