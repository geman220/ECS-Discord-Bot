# celery_worker.py

"""
Celery Worker (Main + Player Sync)

This script starts the main Celery worker using a prefork pool. It handles both
the 'celery' queue (general tasks) and 'player_sync' queue (WooCommerce sync).
Combining these saves memory since player sync runs infrequently.
"""

import sys
import gc
import psutil
import os
from celery_worker_base import celery_app as celery, logger

def log_memory_usage():
    """Log current memory usage to help debug OOM issues."""
    try:
        process = psutil.Process(os.getpid())
        memory_info = process.memory_info()
        memory_percent = process.memory_percent()
        logger.info(f"Memory usage: RSS={memory_info.rss / 1024 / 1024:.1f}MB ({memory_percent:.1f}%)")
    except Exception as e:
        logger.warning(f"Could not get memory info: {e}")

if __name__ == '__main__':
    try:
        logger.info("Starting Celery worker")
        log_memory_usage()
        
        # Add memory monitoring callback (reduced frequency for performance)
        @celery.signals.task_postrun.connect  
        def task_postrun_handler(sender=None, task_id=None, task=None, args=None, kwargs=None, retval=None, state=None, **kwds):
            # Only log memory for tasks that could be memory intensive
            task_name = task.name if hasattr(task, 'name') else str(task)
            if task_name and ('discord' in task_name.lower() or 'batch' in task_name.lower() or 'sync' in task_name.lower()):
                log_memory_usage()

        # Start the Celery worker with the specified options.
        # Changed from eventlet to prefork due to worker going silent after startup
        # Handles both 'celery' and 'player_sync' queues to save memory
        celery.worker_main([
            'worker',
            '--loglevel=INFO',
            '--hostname=main-celery-worker@%h',  # Explicit hostname
            '-Q', 'celery,player_sync',  # Combined: main queue + player sync
            '--pool=prefork',  # Changed from eventlet - eventlet was deadlocking
            '--concurrency=2',  # Reduced for prefork
            '--prefetch-multiplier=1',
            '--max-tasks-per-child=50',
            '--time-limit=300',
            '--soft-time-limit=240',
            '--max-memory-per-child=250000'
        ])
    except Exception as e:
        logger.error(f"Failed to start worker: {e}", exc_info=True)
        sys.exit(1)
