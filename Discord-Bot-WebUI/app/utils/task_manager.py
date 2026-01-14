# app/utils/task_manager.py

"""
Global Task Management System

Provides centralized task monitoring, recovery, and management capabilities
for all Celery tasks across the application.
"""

import logging
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from celery import current_app as celery_app
from celery.result import AsyncResult
from app.core import celery
from app.utils.safe_redis import get_safe_redis

logger = logging.getLogger(__name__)

class TaskManager:
    """
    Global task management for monitoring, recovery, and control.
    """
    
    TASK_REGISTRY_KEY = "global_task_registry"
    TASK_TTL = 24 * 60 * 60  # 24 hours
    
    @classmethod
    def _get_redis_client(cls):
        """Get Redis client instance."""
        return get_safe_redis()
    
    @classmethod
    def register_task(cls, task_id: str, task_type: str, user_id: int,
                     description: str, metadata: Dict = None) -> bool:
        """
        Register a task in the global registry for monitoring.

        Args:
            task_id: Celery task ID
            task_type: Type of task (e.g., 'player_sync', 'report_generation')
            user_id: User who initiated the task
            description: Human-readable description
            metadata: Additional task-specific data
        """
        try:
            task_data = {
                'task_id': task_id,
                'task_type': task_type,
                'user_id': user_id,
                'description': description,
                'metadata': metadata or {},
                'created_at': datetime.utcnow().isoformat(),
                'status': 'PENDING'
            }

            redis_client = cls._get_redis_client()
            task_key = f"{cls.TASK_REGISTRY_KEY}:{task_id}"
            user_key = f"user_tasks:{user_id}"

            # Use pipeline for atomic batch operations
            pipe = redis_client.pipeline()
            pipe.hset(
                task_key,
                mapping={k: json.dumps(v) if isinstance(v, (dict, list)) else str(v)
                        for k, v in task_data.items()}
            )
            pipe.expire(task_key, cls.TASK_TTL)
            pipe.sadd(user_key, task_id)
            pipe.expire(user_key, cls.TASK_TTL)
            pipe.execute()

            logger.info(f"Registered task {task_id} for user {user_id}: {description}")
            return True

        except Exception as e:
            logger.error(f"Failed to register task {task_id}: {e}")
            return False
    
    @classmethod
    def update_task_status(cls, task_id: str, status: str, progress: int = None, 
                          stage: str = None, message: str = None) -> bool:
        """
        Update task status in the registry.
        """
        try:
            updates = {
                'status': status,
                'updated_at': datetime.utcnow().isoformat()
            }
            
            if progress is not None:
                updates['progress'] = str(progress)
            if stage:
                updates['stage'] = stage
            if message:
                updates['message'] = message
                
            redis_client = cls._get_redis_client()
            redis_client.hset(f"{cls.TASK_REGISTRY_KEY}:{task_id}", mapping=updates)
            return True
            
        except Exception as e:
            logger.error(f"Failed to update task {task_id}: {e}")
            return False
    
    @classmethod
    def get_task_info(cls, task_id: str) -> Optional[Dict]:
        """
        Get complete task information.
        """
        try:
            redis_client = cls._get_redis_client()
            task_data = redis_client.hgetall(f"{cls.TASK_REGISTRY_KEY}:{task_id}")
            if not task_data:
                return None
                
            # Parse JSON fields
            result = {}
            for key, value in task_data.items():
                key = key.decode() if isinstance(key, bytes) else key
                value = value.decode() if isinstance(value, bytes) else value
                
                if key in ['metadata']:
                    try:
                        result[key] = json.loads(value)
                    except json.JSONDecodeError:
                        result[key] = {}
                else:
                    result[key] = value
                    
            return result
            
        except Exception as e:
            logger.error(f"Failed to get task info for {task_id}: {e}")
            return None
    
    @classmethod
    def get_user_tasks(cls, user_id: int, status_filter: str = None) -> List[Dict]:
        """
        Get all tasks for a specific user.
        """
        try:
            redis_client = cls._get_redis_client()
            task_ids = redis_client.smembers(f"user_tasks:{user_id}")
            tasks = []
            
            for task_id in task_ids:
                task_id = task_id.decode() if isinstance(task_id, bytes) else task_id
                task_info = cls.get_task_info(task_id)
                
                if task_info:
                    # Get live Celery status
                    celery_result = AsyncResult(task_id, app=celery)
                    task_info['celery_state'] = celery_result.state
                    task_info['celery_info'] = celery_result.info
                    
                    # Filter by status if requested
                    if not status_filter or task_info.get('status') == status_filter:
                        tasks.append(task_info)
            
            # Sort by creation time (newest first)
            tasks.sort(key=lambda x: x.get('created_at', ''), reverse=True)
            return tasks
            
        except Exception as e:
            logger.error(f"Failed to get tasks for user {user_id}: {e}")
            return []
    
    @classmethod
    def get_active_tasks(cls, task_type: str = None) -> List[Dict]:
        """
        Get all active tasks across the system.
        """
        try:
            redis_client = cls._get_redis_client()
            # Get all task registry keys
            pattern = f"{cls.TASK_REGISTRY_KEY}:*"
            task_keys = redis_client.keys(pattern)
            
            active_tasks = []
            for key in task_keys:
                key = key.decode() if isinstance(key, bytes) else key
                task_id = key.split(':')[-1]
                task_info = cls.get_task_info(task_id)
                
                if task_info:
                    # Get live Celery status
                    celery_result = AsyncResult(task_id, app=celery)
                    celery_state = celery_result.state
                    
                    # Get our TaskManager status
                    task_manager_status = task_info.get('status', 'UNKNOWN')
                    
                    # If TaskManager shows REVOKED but Celery doesn't, trust TaskManager
                    # This handles cases where revoke signal didn't reach the worker
                    if task_manager_status == 'REVOKED':
                        effective_state = 'REVOKED'
                    else:
                        effective_state = celery_state
                    
                    # Show tasks that are active OR recently revoked (for better UX)
                    if effective_state in ['PENDING', 'PROGRESS', 'STARTED', 'REVOKED', 'FAILURE']:
                        task_info['celery_state'] = effective_state
                        task_info['celery_info'] = celery_result.info
                        
                        # Filter by task type if requested
                        if not task_type or task_info.get('task_type') == task_type:
                            active_tasks.append(task_info)
            
            return active_tasks
            
        except Exception as e:
            logger.error(f"Failed to get active tasks: {e}")
            return []
    
    @classmethod
    def revoke_task(cls, task_id: str, terminate: bool = False) -> bool:
        """
        Revoke/cancel a running task.
        """
        try:
            celery.control.revoke(task_id, terminate=terminate)
            cls.update_task_status(task_id, 'REVOKED', message='Task cancelled by user')
            logger.info(f"Revoked task {task_id} (terminate={terminate})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to revoke task {task_id}: {e}")
            return False
    
    @classmethod
    def kill_task_completely(cls, task_id: str) -> bool:
        """
        Completely destroy a task - terminate, revoke, and purge from all storage.
        This is the nuclear option that removes all traces of the task.
        """
        try:
            redis_client = cls._get_redis_client()
            
            # Get task info before we destroy it
            task_info = cls.get_task_info(task_id)
            user_id = task_info.get('user_id') if task_info else None
            
            # Step 1: Revoke and terminate the task
            try:
                celery.control.revoke(task_id, terminate=True)
                logger.info(f"Sent terminate signal to task {task_id}")
            except Exception as e:
                logger.warning(f"Failed to send revoke signal for {task_id}: {e}")
            
            # Step 2: Remove Celery task metadata from Redis
            celery_key = f"celery-task-meta-{task_id}"
            deleted = redis_client.delete(celery_key)
            if deleted:
                logger.info(f"Removed Celery metadata: {celery_key}")
            
            # Step 3: Remove from TaskManager registry
            registry_key = f"{cls.TASK_REGISTRY_KEY}:{task_id}"
            deleted = redis_client.delete(registry_key)
            if deleted:
                logger.info(f"Removed TaskManager registry: {registry_key}")
            
            # Step 4: Remove from user task list
            if user_id:
                redis_client.srem(f"user_tasks:{user_id}", task_id)
                logger.info(f"Removed from user_tasks:{user_id}")
            
            # Step 5: Remove from task monitor (if exists)
            monitor_key = f"task_monitor:{task_id}"
            deleted = redis_client.delete(monitor_key)
            if deleted:
                logger.info(f"Removed task monitor: {monitor_key}")
            
            # Step 6: Remove any other potential Redis keys
            pattern_keys = [
                f"*{task_id}*",  # Any keys containing the task ID
            ]
            
            for pattern in pattern_keys:
                keys = redis_client.keys(pattern)
                for key in keys:
                    key_str = key.decode() if isinstance(key, bytes) else key
                    # Don't delete keys that are just coincidentally similar
                    if task_id in key_str and any(prefix in key_str for prefix in ['task', 'celery', 'sync_data']):
                        redis_client.delete(key)
                        logger.info(f"Removed additional key: {key_str}")
            
            logger.info(f"COMPLETELY DESTROYED task {task_id} - all traces removed")
            return True
            
        except Exception as e:
            logger.error(f"Failed to completely kill task {task_id}: {e}")
            return False
    
    @classmethod
    def remove_task(cls, task_id: str) -> bool:
        """
        Remove a completed task from all registries and storage.
        More thorough than the basic registry removal.
        
        Args:
            task_id: Task ID to remove
            
        Returns:
            bool: True if successfully removed, False otherwise
        """
        try:
            redis_client = cls._get_redis_client()
            
            # Get task info to find user_id before deletion
            task_info = cls.get_task_info(task_id)
            user_id = task_info.get('user_id') if task_info else None
            
            removed_count = 0
            
            # Remove from TaskManager registry
            registry_key = f"{cls.TASK_REGISTRY_KEY}:{task_id}"
            if redis_client.delete(registry_key):
                removed_count += 1
                logger.info(f"Removed TaskManager registry: {registry_key}")
            
            # Remove from user's task list if user_id exists
            if user_id:
                redis_client.srem(f"user_tasks:{user_id}", task_id)
                logger.info(f"Removed from user_tasks:{user_id}")
            
            # Remove Celery task metadata
            celery_key = f"celery-task-meta-{task_id}"
            if redis_client.delete(celery_key):
                removed_count += 1
                logger.info(f"Removed Celery metadata: {celery_key}")
            
            # Remove task monitor data
            monitor_key = f"task_monitor:{task_id}"
            if redis_client.delete(monitor_key):
                removed_count += 1
                logger.info(f"Removed task monitor: {monitor_key}")
            
            # Remove any sync data
            sync_key = f"sync_data:{task_id}"
            if redis_client.delete(sync_key):
                removed_count += 1
                logger.info(f"Removed sync data: {sync_key}")
            
            if removed_count > 0:
                logger.info(f"Successfully removed task {task_id} (cleaned {removed_count} keys)")
                return True
            else:
                logger.warning(f"Task {task_id} was not found in any registry")
                return False
                
        except Exception as e:
            logger.error(f"Failed to remove task {task_id}: {e}")
            return False
    
    @classmethod  
    def cleanup_old_celery_metadata(cls, max_age_hours: int = 168) -> int:
        """
        Clean up old Celery task metadata from Redis.
        Default: 168 hours = 7 days
        
        Args:
            max_age_hours: Maximum age in hours before cleanup
            
        Returns:
            int: Number of keys cleaned up
        """
        try:
            redis_client = cls._get_redis_client()
            cutoff_time = datetime.utcnow() - timedelta(hours=max_age_hours)
            
            # Get all celery task metadata keys
            celery_keys = redis_client.keys("celery-task-meta-*")
            cleaned_count = 0
            
            for key in celery_keys:
                key_str = key.decode() if isinstance(key, bytes) else key
                
                # Check what type of Redis data this key contains
                try:
                    key_type = redis_client.type(key).decode()
                    
                    if key_type == 'hash':
                        # Handle hash data (newer Celery format)
                        task_data = redis_client.hgetall(key)
                        if task_data:
                            # Try to get timestamp from various possible fields
                            timestamp_str = None
                            for field in [b'timestamp', b'date_done', b'created_at']:
                                if field in task_data:
                                    timestamp_str = task_data[field].decode()
                                    break
                            
                            if timestamp_str:
                                try:
                                    # Parse timestamp and check age
                                    task_time = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00').replace('+00:00', ''))
                                    if task_time < cutoff_time:
                                        redis_client.delete(key)
                                        cleaned_count += 1
                                except ValueError:
                                    # If we can't parse the timestamp, it's probably very old
                                    redis_client.delete(key) 
                                    cleaned_count += 1
                            else:
                                # No timestamp found, assume it's old
                                redis_client.delete(key)
                                cleaned_count += 1
                        else:
                            # Empty hash, delete it
                            redis_client.delete(key)
                            cleaned_count += 1
                            
                    elif key_type == 'string':
                        # Handle string data (older Celery format or pickled data)
                        # For string data, we'll use a more aggressive cleanup approach
                        # since we can't easily parse the timestamp
                        try:
                            # Try to get the TTL to see if it has an expiration
                            ttl = redis_client.ttl(key)
                            if ttl == -1:  # No expiration set
                                # Delete old string-based metadata that has no TTL
                                redis_client.delete(key)
                                cleaned_count += 1
                            # If it has TTL, let Redis handle the expiration
                        except Exception:
                            # If we can't check TTL, delete it
                            redis_client.delete(key)
                            cleaned_count += 1
                            
                    else:
                        # Unknown data type, probably safe to delete old task metadata
                        redis_client.delete(key)
                        cleaned_count += 1
                        logger.info(f"Deleted task metadata with unknown type '{key_type}': {key_str}")
                            
                except Exception as e:
                    # If we encounter any error checking the key, it's likely corrupted
                    logger.warning(f"Error checking task metadata {key_str}, deleting: {e}")
                    try:
                        redis_client.delete(key)
                        cleaned_count += 1
                    except Exception as delete_error:
                        logger.error(f"Failed to delete corrupted key {key_str}: {delete_error}")
            
            logger.info(f"Cleaned up {cleaned_count} old Celery task metadata keys")
            return cleaned_count
            
        except Exception as e:
            logger.error(f"Failed to cleanup old Celery metadata: {e}")
            return 0
    
    @classmethod
    def cleanup_completed_tasks(cls, max_age_hours: int = 24) -> int:
        """
        Clean up old completed tasks from the registry.
        """
        try:
            redis_client = cls._get_redis_client()
            cutoff_time = datetime.utcnow() - timedelta(hours=max_age_hours)
            pattern = f"{cls.TASK_REGISTRY_KEY}:*"
            task_keys = redis_client.keys(pattern)
            
            cleaned_count = 0
            for key in task_keys:
                key = key.decode() if isinstance(key, bytes) else key
                task_id = key.split(':')[-1]
                task_info = cls.get_task_info(task_id)
                
                if task_info:
                    # Check if task is old and completed
                    created_at = datetime.fromisoformat(task_info.get('created_at', ''))
                    celery_result = AsyncResult(task_id, app=celery)
                    
                    if (created_at < cutoff_time and 
                        celery_result.state in ['SUCCESS', 'FAILURE', 'REVOKED']):
                        
                        # Remove from registry
                        redis_client.delete(f"{cls.TASK_REGISTRY_KEY}:{task_id}")
                        
                        # Remove from user's task list
                        user_id = task_info.get('user_id')
                        if user_id:
                            redis_client.srem(f"user_tasks:{user_id}", task_id)
                        
                        cleaned_count += 1
            
            logger.info(f"Cleaned up {cleaned_count} old tasks")
            return cleaned_count
            
        except Exception as e:
            logger.error(f"Failed to cleanup tasks: {e}")
            return 0
    
    @classmethod
    def get_task_statistics(cls) -> Dict:
        """
        Get system-wide task statistics.
        """
        try:
            redis_client = cls._get_redis_client()
            stats = {
                'total_active': 0,
                'by_status': {},
                'by_type': {},
                'oldest_active': None
            }
            
            pattern = f"{cls.TASK_REGISTRY_KEY}:*"
            task_keys = redis_client.keys(pattern)
            
            for key in task_keys:
                key = key.decode() if isinstance(key, bytes) else key
                task_id = key.split(':')[-1]
                task_info = cls.get_task_info(task_id)
                
                if task_info:
                    celery_result = AsyncResult(task_id, app=celery)
                    state = celery_result.state
                    task_type = task_info.get('task_type', 'unknown')
                    created_at = task_info.get('created_at')
                    
                    if state in ['PENDING', 'PROGRESS', 'STARTED']:
                        stats['total_active'] += 1
                        
                        # Track oldest active task
                        if not stats['oldest_active'] or created_at < stats['oldest_active']:
                            stats['oldest_active'] = created_at
                    
                    # Count by status
                    stats['by_status'][state] = stats['by_status'].get(state, 0) + 1
                    
                    # Count by type
                    stats['by_type'][task_type] = stats['by_type'].get(task_type, 0) + 1
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get task statistics: {e}")
            return {'error': str(e)}


# Decorator to automatically register tasks
def register_task(task_type: str, description: str = None):
    """
    Decorator to automatically register tasks with the global task manager.
    
    Usage:
        @celery.task(bind=True)
        @register_task('player_sync', 'Sync players from WooCommerce')
        def sync_players_task(self, user_id):
            # Task implementation
    """
    def decorator(task_func):
        def wrapper(self, *args, **kwargs):
            # Extract user_id from args/kwargs
            user_id = kwargs.get('user_id') or (args[0] if args else None)
            
            # Register the task
            TaskManager.register_task(
                task_id=self.request.id,
                task_type=task_type,
                user_id=user_id,
                description=description or f"{task_type} task",
                metadata={'args': args, 'kwargs': kwargs}
            )
            
            try:
                # Update status to started
                TaskManager.update_task_status(self.request.id, 'STARTED')
                
                # Execute the task
                result = task_func(self, *args, **kwargs)
                
                # Update status to completed
                TaskManager.update_task_status(self.request.id, 'SUCCESS')
                
                return result
                
            except Exception as e:
                # Update status to failed
                TaskManager.update_task_status(
                    self.request.id, 
                    'FAILURE', 
                    message=str(e)
                )
                raise
        
        return wrapper
    return decorator