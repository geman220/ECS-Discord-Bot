# app/utils/task_status_helper.py

"""
Task Status Helper Module

Provides enhanced task status functionality that can be shared across
the application, including match management and monitoring pages.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


def get_enhanced_match_task_status(match_id: int, use_cache: bool = True) -> Dict[str, Any]:
    """
    Get enhanced task status for a match with cache-first approach and fallback logic.
    
    This function first tries to get data from the background cache for optimal performance.
    If cache miss or disabled, it falls back to real-time calculation.
    
    Args:
        match_id: The match ID to check
        use_cache: Whether to use cache-first approach (default: True)
        
    Returns:
        Dictionary with success flag, match_id, tasks dict, timestamp, and cache info
    """
    
    # Try cache first if enabled
    if use_cache:
        try:
            from app.services.task_status_cache import task_status_cache
            cached_result = task_status_cache.get_cached_status(match_id)
            
            if cached_result:
                logger.debug(f"Serving task status for match {match_id} from cache")
                return cached_result
            
            logger.debug(f"Cache miss for match {match_id}, falling back to real-time calculation")
            
        except Exception as e:
            logger.warning(f"Cache lookup failed for match {match_id}: {e}, falling back to real-time")
    
    # Real-time calculation (original logic)
    try:
        # Import here to avoid circular imports
        from app.utils.safe_redis import get_safe_redis
        from datetime import datetime
        
        # Try direct Redis connection first
        try:
            import redis
            direct_redis = redis.Redis(host='redis', port=6379, db=0, decode_responses=True, socket_timeout=5)
            direct_redis.ping()
            redis_client = direct_redis
            
            # Helper function for decoding Redis data
            def safe_decode(data):
                if data is None:
                    return None
                return data if isinstance(data, str) else data.decode('utf-8')
                
        except Exception as e:
            return {
                'success': False,
                'error': f'Redis connection failed: {str(e)}',
                'tasks': {},
                'match_id': match_id
            }
        
        tasks = {}
        
        # Get match details for fallback logic
        from app.core.helpers import get_match
        from app.core.session_manager import managed_session
        match_data = None
        with managed_session() as session:
            match = get_match(session, match_id)
            if match:
                # Extract data while session is active to prevent lazy loading issues
                match_data = {
                    'discord_thread_id': match.discord_thread_id,
                    'date_time': match.date_time,
                    'opponent': match.opponent,
                    'is_home_game': match.is_home_game
                }
        
        # Check for thread creation task
        thread_key = f"match_scheduler:{match_id}:thread"
        thread_data = redis_client.get(thread_key)
        thread_ttl = redis_client.ttl(thread_key)
        
        if thread_data:
            try:
                thread_json = json.loads(safe_decode(thread_data))
                task_id = thread_json.get('task_id')
                eta = thread_json.get('eta')
                
                # Get task status from Celery
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
            except (json.JSONDecodeError, Exception) as e:
                tasks['thread'] = {
                    'error': f'Failed to parse thread task: {str(e)}',
                    'raw_data': safe_decode(thread_data)
                }
        else:
            # Fallback logic for thread creation
            if match_data and match_data.get('discord_thread_id'):
                # Thread exists, so task completed successfully
                tasks['thread'] = {
                    'task_id': 'unknown',
                    'eta': 'completed',
                    'status': 'SUCCESS',
                    'result': f'Thread created: {match_data["discord_thread_id"]}',
                    'type': 'Thread Creation',
                    'fallback': True,
                    'message': f'{"Sounders vs " + match_data["opponent"] if match_data["is_home_game"] else match_data["opponent"] + " vs Sounders"} thread created'
                }
            elif match_data:
                # Check if thread creation should have happened by now
                from datetime import datetime, timedelta
                import pytz
                utc_tz = pytz.UTC
                match_time = match_data['date_time'].replace(tzinfo=utc_tz) if match_data['date_time'] else None
                if match_time:
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
                            'message': f'{"Sounders vs " + match_data["opponent"] if match_data["is_home_game"] else match_data["opponent"] + " vs Sounders"} - thread creation overdue'
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
                            'message': f'{"Sounders vs " + match_data["opponent"] if match_data["is_home_game"] else match_data["opponent"] + " vs Sounders"} - thread scheduled'
                        }
        
        # Check for live reporting task
        reporting_key = f"match_scheduler:{match_id}:reporting"
        reporting_data = redis_client.get(reporting_key)
        reporting_ttl = redis_client.ttl(reporting_key)
        
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
            except (json.JSONDecodeError, Exception) as e:
                tasks['reporting'] = {
                    'error': f'Failed to parse reporting task: {str(e)}',
                    'raw_data': safe_decode(reporting_data)
                }
        else:
            # Fallback logic for live reporting
            if match_data:
                from datetime import datetime, timedelta
                import pytz
                utc_tz = pytz.UTC
                match_time = match_data['date_time'].replace(tzinfo=utc_tz) if match_data['date_time'] else None
                if match_time:
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
                            'message': f'{"Sounders vs " + match_data["opponent"] if match_data["is_home_game"] else match_data["opponent"] + " vs Sounders"} - match completed'
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
                            'message': f'{"Sounders vs " + match_data["opponent"] if match_data["is_home_game"] else match_data["opponent"] + " vs Sounders"} - live reporting active'
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
                            'message': f'{"Sounders vs " + match_data["opponent"] if match_data["is_home_game"] else match_data["opponent"] + " vs Sounders"} - reporting scheduled'
                        }
        
        return {
            'success': True,
            'match_id': match_id,
            'tasks': tasks,
            'timestamp': datetime.utcnow().isoformat(),
            'cached': False,
            'source': 'real-time'
        }
        
    except Exception as e:
        logger.error(f"Error getting enhanced match tasks for {match_id}: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e),
            'match_id': match_id,
            'tasks': {},
            'cached': False,
            'source': 'error'
        }