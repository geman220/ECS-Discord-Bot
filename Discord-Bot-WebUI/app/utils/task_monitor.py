# app/utils/task_monitor.py

"""
Task Monitor Module

This module provides utilities for monitoring Celery tasks and their lifecycle.
It helps detect and handle zombie tasks (tasks that are stuck in a running state),
manages stale tasks, and provides insights into task execution patterns.
"""

import logging
import time
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from celery.states import STARTED, PENDING, RETRY, FAILURE, SUCCESS, REVOKED
from celery.result import AsyncResult

from app.core import celery
from app.utils.safe_redis import get_safe_redis

logger = logging.getLogger(__name__)


class TaskMonitor:
    """
    A class for monitoring and managing Celery tasks.
    
    This class provides functionality to track task states, detect zombie tasks,
    and clean up task-related resources. It uses Redis for persistent state tracking.
    """
    
    def __init__(self):
        """Initialize the TaskMonitor with Redis-backed storage."""
        self._redis = get_safe_redis()
        self.redis = self._redis
        self.task_prefix = "task_monitor:"
        self.zombie_threshold = 7200  # 2 hours - increased to prevent false positives
    
    def register_task_start(self, task_id: str, task_name: str) -> None:
        """
        Register a task as started.
        
        Args:
            task_id: The ID of the task.
            task_name: The name of the task.
        """
        key = f"{self.task_prefix}{task_id}"
        
        # Store task information
        task_info = {
            "task_id": task_id,
            "task_name": task_name,
            "start_time": time.time(),
            "status": STARTED
        }
        
        # Set expiration to avoid leaking memory
        self.redis.hmset(key, task_info)
        self.redis.expire(key, 86400)  # 24 hours
        logger.debug(f"Registered task start: {task_id} ({task_name})")
    
    def register_task_completion(self, task_id: str, status: str) -> None:
        """
        Register a task as completed (or failed).
        
        Args:
            task_id: The ID of the task.
            status: The final status of the task.
        """
        key = f"{self.task_prefix}{task_id}"
        
        # Update task information
        if self.redis.exists(key):
            self.redis.hset(key, "status", status)
            self.redis.hset(key, "end_time", time.time())
            self.redis.expire(key, 86400)  # 24 hours after completion
            logger.debug(f"Registered task completion: {task_id} ({status})")
        else:
            logger.warning(f"Attempted to update unknown task: {task_id}")
    
    def detect_zombie_tasks(self) -> List[Dict[str, Any]]:
        """
        Detect tasks that have been running for too long.
        
        Returns:
            A list of dictionaries containing information about zombie tasks.
        """
        # Check if Redis is available before proceeding
        if not self.redis.is_available:
            logger.warning("Redis is not available - skipping zombie task detection")
            return []
            
        current_time = time.time()
        zombie_tasks = []
        
        # Use SCAN instead of KEYS for better performance
        cursor = 0
        batch_size = 100
        
        while True:
            try:
                cursor, keys = self.redis.scan(cursor, match=f"{self.task_prefix}*", count=batch_size)
            except Exception as e:
                logger.error(f"Error scanning Redis for zombie tasks: {e}")
                break
            
            if not keys:
                if cursor == 0:
                    break
                continue
            
            # Use pipeline for batch operations
            try:
                pipe = self.redis.pipeline()
                for key in keys:
                    pipe.hgetall(key)
                
                task_infos = pipe.execute()
            except Exception as e:
                logger.error(f"Error executing Redis pipeline: {e}")
                continue
            
            for key, task_info in zip(keys, task_infos):
                if not task_info:
                    continue
                    
                # Skip if not in STARTED state
                if task_info.get("status") != STARTED:
                    continue
                
                # Check if task has been running too long
                start_time = float(task_info.get("start_time", 0))
                runtime = current_time - start_time

                if runtime > self.zombie_threshold:
                    task_id = task_info.get("task_id")
                    task_name = task_info.get("task_name")

                    # Safety check: Don't revoke certain critical tasks that may run long
                    safe_task_patterns = [
                        'app.tasks.security_cleanup',  # These are legitimate and should run
                        'app.tasks.tasks_cache_management',  # Cache tasks can be slow
                        'app.tasks.monitoring_tasks',  # Monitoring tasks are periodic
                    ]

                    is_safe_task = any(pattern in task_name for pattern in safe_task_patterns)

                    # For safe tasks, use a much longer threshold (6 hours)
                    threshold_to_use = 21600 if is_safe_task else self.zombie_threshold

                    if runtime < threshold_to_use:
                        continue  # Don't mark as zombie yet

                    # Try to get the current state from Celery
                    try:
                        task_result = AsyncResult(task_id)
                        current_status = task_result.state
                    except Exception as e:
                        logger.error(f"Error getting task status for {task_id}: {e}")
                        continue

                    # Additional safety: Only mark as zombie if truly stuck
                    # If Celery says PENDING or SUCCESS, don't revoke
                    if current_status in [PENDING, SUCCESS, FAILURE]:
                        # Update our records to match Celery's status
                        self.register_task_completion(task_id, current_status)
                        continue

                    # If the task is still running according to Celery, it's a zombie
                    if current_status == STARTED:
                        # Extra safety check: Log warning first, only revoke if runtime > 4 hours
                        if runtime > 14400:  # 4 hours
                            zombie_tasks.append({
                                "task_id": task_id,
                                "task_name": task_name,
                                "runtime": runtime,
                                "start_time": datetime.fromtimestamp(start_time).isoformat()
                            })
                        else:
                            logger.warning(f"Long-running task detected but not yet revoking: {task_name} ({runtime:.0f}s)")
                    else:
                        # Update our records if Celery has a different status
                        self.register_task_completion(task_id, current_status)
            
            if cursor == 0:
                break
        
        return zombie_tasks
    
    def clean_up_zombie_tasks(self) -> int:
        """
        Terminate zombie tasks and clean up related resources.
        
        Returns:
            The number of tasks terminated.
        """
        zombies = self.detect_zombie_tasks()
        terminated = 0
        
        for zombie in zombies:
            task_id = zombie["task_id"]
            logger.warning(f"Terminating zombie task: {task_id} ({zombie['task_name']})")
            
            try:
                # Revoke and terminate the task
                celery.control.revoke(task_id, terminate=True)
                
                # Update our records
                self.register_task_completion(task_id, REVOKED)
                terminated += 1
            except Exception as e:
                logger.error(f"Failed to terminate task {task_id}: {e}", exc_info=True)
        
        return terminated
    
    def get_task_stats(self, time_window: Optional[int] = None) -> Dict[str, Any]:
        """
        Get statistics about tasks.
        
        Args:
            time_window: Optional time window in seconds to limit statistics.
                         If None, all available data is used.
        
        Returns:
            A dictionary containing task statistics.
        """
        stats = {
            "total": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,
            "pending": 0,
            "by_name": {}
        }
        
        current_time = time.time()
        min_time = current_time - time_window if time_window else 0
        
        # Find keys with the task prefix
        keys = self.redis.keys(f"{self.task_prefix}*")
        
        for key in keys:
            task_info = self.redis.hgetall(key)
            start_time = float(task_info.get("start_time", 0))
            
            # Skip if outside the time window
            if start_time < min_time:
                continue
            
            task_name = task_info.get("task_name", "unknown")
            status = task_info.get("status", PENDING)
            
            # Update overall stats
            stats["total"] += 1
            
            if status == STARTED:
                stats["running"] += 1
            elif status in (SUCCESS, REVOKED):
                stats["completed"] += 1
            elif status == FAILURE:
                stats["failed"] += 1
            else:
                stats["pending"] += 1
            
            # Update per-task stats
            if task_name not in stats["by_name"]:
                stats["by_name"][task_name] = {
                    "total": 0,
                    "running": 0,
                    "completed": 0,
                    "failed": 0,
                    "avg_runtime": 0,
                    "longest_runtime": 0
                }
            
            task_stats = stats["by_name"][task_name]
            task_stats["total"] += 1
            
            if status == STARTED:
                task_stats["running"] += 1
                runtime = current_time - start_time
                task_stats["longest_runtime"] = max(task_stats["longest_runtime"], runtime)
            elif status in (SUCCESS, REVOKED):
                task_stats["completed"] += 1
                if "end_time" in task_info:
                    runtime = float(task_info["end_time"]) - start_time
                    # Update running average
                    task_stats["avg_runtime"] = (
                        (task_stats["avg_runtime"] * (task_stats["completed"] - 1) + runtime)
                        / task_stats["completed"]
                    )
            elif status == FAILURE:
                task_stats["failed"] += 1
        
        return stats


def get_task_info(task_id: str) -> Dict[str, Any]:
    """
    Get detailed information about a Celery task.
    
    Args:
        task_id: The ID of the task to get information for.
        
    Returns:
        A dictionary containing task information.
    """
    try:
        # Get task result from Celery
        task_result = AsyncResult(task_id)
        
        # Get basic task info
        task_info = {
            'task_id': task_id,
            'state': task_result.state,
            'result': None,
            'date_started': None,
            'duration': None
        }
        
        # Try to get additional info from task result
        try:
            if hasattr(task_result, 'info') and task_result.info:
                if isinstance(task_result.info, dict):
                    task_info.update(task_result.info)
                else:
                    task_info['result'] = str(task_result.info)
        except Exception as e:
            logger.debug(f"Could not get task info for {task_id}: {e}")
        
        # Get date started if available
        try:
            if hasattr(task_result, 'date_done') and task_result.date_done:
                task_info['date_done'] = task_result.date_done.isoformat()
        except Exception as e:
            logger.debug(f"Could not get date_done for {task_id}: {e}")
        
        # Try to get additional info from our task monitor
        try:
            redis = get_safe_redis()
            monitor_key = f"task_monitor:{task_id}"
            monitor_info = redis.hgetall(monitor_key)
            
            if monitor_info:
                start_time = monitor_info.get('start_time')
                if start_time:
                    start_timestamp = float(start_time)
                    task_info['date_started'] = datetime.fromtimestamp(start_timestamp).isoformat()
                    
                    # Calculate duration if task is completed
                    end_time = monitor_info.get('end_time')
                    if end_time:
                        end_timestamp = float(end_time)
                        duration_seconds = end_timestamp - start_timestamp
                        task_info['duration'] = f"{duration_seconds:.1f} seconds"
                    elif task_result.state == STARTED:
                        # Task is still running
                        current_time = time.time()
                        duration_seconds = current_time - start_timestamp
                        task_info['duration'] = f"{duration_seconds:.1f} seconds (running)"
                
                # Add task name if available
                task_name = monitor_info.get('task_name')
                if task_name:
                    task_info['task_name'] = task_name
                    
        except Exception as e:
            logger.debug(f"Could not get monitor info for {task_id}: {e}")
        
        return task_info
        
    except Exception as e:
        logger.error(f"Error getting task info for {task_id}: {e}")
        return {
            'task_id': task_id,
            'state': 'UNKNOWN',
            'result': f'Error getting task info: {str(e)}',
            'date_started': None,
            'duration': None
        }


# Initialize a global TaskMonitor instance
task_monitor = TaskMonitor()

# Track sessions by their ID to identify leaks
session_tracking = {}

def register_session_start(session_id, source_task, stack_trace):
    """Register the start of a database session for tracking purposes"""
    session_tracking[session_id] = {
        'start_time': datetime.now(),
        'task_id': source_task,
        'stack_trace': stack_trace,
        'status': 'open'
    }
    
def register_session_end(session_id, status='closed'):
    """Register the end of a database session"""
    if session_id in session_tracking:
        session_tracking[session_id]['status'] = status
        session_tracking[session_id]['end_time'] = datetime.now()
        
        # Calculate session lifetime
        lifetime = session_tracking[session_id]['end_time'] - session_tracking[session_id]['start_time'] 
        
        # If this was a long session, log it
        if lifetime.total_seconds() > 60:  # sessions lasting over 1 minute
            logger.warning(
                f"Long-lived session detected: {session_id}, "
                f"Duration: {lifetime.total_seconds():.1f}s, "
                f"Task: {session_tracking[session_id]['task_id']}"
            )
    else:
        logger.warning(f"Attempted to end untracked session: {session_id}")
        
def get_open_sessions(age_threshold_seconds=3600):
    """Get all sessions that have been open too long"""
    now = datetime.now()
    old_sessions = []
    
    for session_id, info in session_tracking.items():
        if info['status'] == 'open':
            age = (now - info['start_time']).total_seconds()
            if age > age_threshold_seconds:
                old_sessions.append({
                    'session_id': session_id,
                    'age_seconds': age,
                    'task_id': info['task_id'],
                    'stack_trace': info['stack_trace']
                })
    
    return old_sessions


# Define Celery task hooks for automatic monitoring
@celery.signals.before_task_publish.connect
def task_publish_handler(sender=None, headers=None, **kwargs):
    """
    Celery signal handler for task publication.
    This records the initial task state.
    """
    task_id = headers.get('id')
    if task_id:
        task_monitor.register_task_start(task_id, sender)


@celery.signals.task_success.connect
def task_success_handler(sender=None, **kwargs):
    """
    Celery signal handler for task success.
    This records successful task completion.
    """
    task_id = sender.request.id
    if task_id:
        task_monitor.register_task_completion(task_id, SUCCESS)


@celery.signals.task_failure.connect
def task_failure_handler(sender=None, task_id=None, **kwargs):
    """
    Celery signal handler for task failure.
    This records failed task completion.
    """
    if task_id:
        task_monitor.register_task_completion(task_id, FAILURE)


@celery.signals.task_revoked.connect
def task_revoked_handler(request=None, **kwargs):
    """
    Celery signal handler for task revocation.
    This records revoked task status.
    """
    if request and request.id:
        task_monitor.register_task_completion(request.id, REVOKED)


# Celery scheduled task to clean up zombie tasks
@celery.task(name='app.utils.task_monitor.clean_zombie_tasks')
def clean_zombie_tasks():
    """
    Periodic task to detect and clean up zombie tasks.
    
    Returns:
        A dictionary with clean-up results.
    """
    start_time = time.time()
    logger.info("Running zombie task cleanup")
    
    # Detect zombies first (fastest operation)
    zombies = task_monitor.detect_zombie_tasks()
    logger.info(f"Found {len(zombies)} zombie tasks")

    # Safety check: Don't revoke too many tasks at once
    max_revocations_per_run = 5
    if len(zombies) > max_revocations_per_run:
        logger.warning(f"Too many zombie tasks detected ({len(zombies)}), limiting revocations to {max_revocations_per_run}")
        zombies = zombies[:max_revocations_per_run]

    # Clean them up with additional safety
    terminated = 0
    if len(zombies) > 0:
        # Log what we're about to revoke for audit trail
        for zombie in zombies:
            logger.warning(f"About to revoke zombie task: {zombie['task_name']} (runtime: {zombie['runtime']:.0f}s)")

        terminated = task_monitor.clean_up_zombie_tasks()
        logger.info(f"Terminated {terminated} zombie tasks")
    else:
        logger.info("No zombie tasks found to terminate")
    
    # Check for orphaned database sessions (only if we found zombies or every 4th run)
    old_sessions = []
    run_full_cleanup = len(zombies) > 0 or (int(time.time()) // 900) % 4 == 0  # Every hour
    
    if run_full_cleanup:
        logger.info("Running full cleanup (found zombies or scheduled)")
        
        # Check for orphaned database sessions
        old_sessions = get_open_sessions(age_threshold_seconds=1800)  # 30 minutes
        if old_sessions:
            logger.warning(f"Found {len(old_sessions)} orphaned database sessions:")
            for idx, session in enumerate(old_sessions):
                logger.warning(
                    f"Session {idx+1}: ID={session['session_id']}, "
                    f"Age={session['age_seconds']/60:.1f} minutes, "
                    f"Task={session['task_id']}"
                )
                
                # Log the full stack trace for the first few orphaned sessions
                if idx < 3:  # Only log details for first 3 sessions to avoid log spam
                    logger.warning(f"Stack trace for session {session['session_id']}:\n{session['stack_trace']}")
        
        # DO NOT dispose the entire connection pool - this causes massive memory issues!
        # The pool should manage its own connections.
        # db.engine.dispose() was destroying and recreating the entire pool,
        # causing huge memory allocation and deallocation cycles.
        
        # Force garbage collection (only during full cleanup)
        import gc
        gc.collect()
        
        # Check memory usage
        try:
            from app.utils.memory_monitor import check_memory_usage
            memory_info = check_memory_usage()
            if memory_info:
                logger.info(f"Current memory usage: {memory_info['memory_mb']:.1f}MB")
        except ImportError:
            logger.debug("Memory monitor not available")
        
        # Clean up Redis connections
        try:
            from app.utils.redis_manager import get_redis_manager
            redis_manager = get_redis_manager()
            if hasattr(redis_manager, '_cleanup_idle_connections'):
                logger.info("Cleaning up idle Redis connections")
                redis_manager._cleanup_idle_connections()
        except Exception as e:
            logger.error(f"Error cleaning Redis connections: {e}")
    
    duration = time.time() - start_time
    logger.info(f"Zombie cleanup completed in {duration:.1f}s")
    
    return {
        "zombie_count": len(zombies),
        "terminated": terminated,
        "orphaned_sessions": len(old_sessions),
        "duration_seconds": round(duration, 1),
        "full_cleanup": run_full_cleanup,
        "zombies": [
            {
                "task_id": z["task_id"],
                "task_name": z["task_name"],
                "runtime_hours": round(z["runtime"] / 3600, 2)
            }
            for z in zombies
        ]
    }