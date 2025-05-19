# app/extensions.py

"""
Extensions Module

This module initializes and configures various application extensions,
including Celery and SQLAlchemy. It provides a function to initialize
Celery with Flask's application context and manages database connection
initialization and cleanup for Celery worker processes.
"""

import logging
import os
import time
import hashlib
import gc
from flask import current_app
from celery.signals import worker_process_init, worker_process_shutdown, task_prerun, task_postrun
from app.core import db, celery

logger = logging.getLogger(__name__)

def init_celery(app=None):
    """
    Initialize Celery with the Flask application context.

    Parameters:
        app (Flask): The Flask application instance.

    Returns:
        Celery: The configured Celery instance.
    """
    if app:
        celery.conf.update(app.config)

    class FlaskTask(celery.Task):
        abstract = True

        def __call__(self, *args, **kwargs):
            flask_app = app or current_app._get_current_object()
            with flask_app.app_context():
                session = flask_app.SessionLocal()
                self._session = session
                try:
                    result = self.run(*args, **kwargs)
                    session.commit()
                    return result
                except Exception as e:
                    session.rollback()
                    logger.error(f"Error in Celery task {self.name}: {str(e)}", exc_info=True)
                    raise
                finally:
                    session.close()
                    del self._session

        @property
        def session(self):
            if not hasattr(self, '_session'):
                raise RuntimeError("No database session available in this context")
            return self._session

    celery.Task = FlaskTask

    celery.conf.update(
        task_serializer='json',
        accept_content=['json'],
        result_serializer='json',
        timezone='UTC',
        enable_utc=True,
        broker_connection_retry_on_startup=True,
        worker_prefetch_multiplier=1,
        task_track_started=True,
        task_time_limit=45 * 60,          # Increased from 30 to 45 minutes with more resources
        task_soft_time_limit=30 * 60,     # Increased from 15 to 30 minutes with more resources
        worker_max_tasks_per_child=100,   # Increased from 50 to 100 with more resources
        worker_max_memory_per_child=300000, # Increased from 150000 to 300000 with more RAM
        worker_concurrency=2              # Set to match the number of CPUs
    )

    return celery

@worker_process_init.connect
def init_worker_process(**kwargs):
    """
    Initialize the worker process by disposing old engine connections and
    re-creating the SQLAlchemy engine using the Flask application's configuration.
    Then re-attach the DatabaseManager instrumentation to the new engine.
    """
    if hasattr(db, 'engine'):
        db.engine.dispose()

    app = current_app._get_current_object()
    engine_options = app.config.get('SQLALCHEMY_ENGINE_OPTIONS', {})

    # Recreate a new engine
    db.engine = db.create_engine(db.engine.url, **engine_options)

    # Re-init instrumentation for the *new* engine
    with app.app_context():
        db_manager.init_app(app)

@worker_process_shutdown.connect
def cleanup_worker_process(**kwargs):
    """
    Cleanup database connections when the worker process shuts down.
    """
    if hasattr(db, 'engine'):
        db.engine.dispose()
        
    # Clean up Redis connections
    try:
        from app.utils.redis_manager import RedisManager
        redis_manager = RedisManager()
        if hasattr(redis_manager, 'shutdown'):
            redis_manager.shutdown()
    except Exception as e:
        logger.error(f"Error cleaning up Redis connections: {e}")
        
    # Force garbage collection
    gc.collect()
    
@task_postrun.connect
def cleanup_after_task(sender=None, task_id=None, task=None, **kwargs):
    """
    Cleanup resources after each task to reduce memory usage.
    """
    try:
        # Run garbage collection cycle for long-running workers
        gc.collect()
        
        # Check memory usage if monitor is available
        try:
            from app.utils.memory_monitor import check_memory_usage
            check_memory_usage()
        except ImportError:
            pass
            
    except Exception as e:
        logger.error(f"Error in post-task cleanup: {e}")

# File versioning cache system for static assets
class StaticFileVersioning:
    """
    Helper class to manage static file versioning for cache busting.
    Provides a version parameter based on file modification time or content hash.
    """
    def __init__(self):
        self.version_cache = {}
        self.last_cache_clear = time.time()
        self.cache_lifetime = 86400  # 24 hours (increased from 1 hour)
        
    def get_version(self, filepath, method='mtime'):
        """
        Returns a version string for the given file path.
        
        Args:
            filepath (str): Path to the static file, relative to the static folder
            method (str): Versioning method - 'mtime' for modification time or 'hash' for content hash
            
        Returns:
            str: Version string (timestamp or hash)
        """
        current_time = time.time()
        
        # Clear cache periodically to avoid memory issues on long-running servers
        if current_time - self.last_cache_clear > self.cache_lifetime:
            self.version_cache = {}
            self.last_cache_clear = current_time
            
        # Check if version is already cached
        cache_key = f"{filepath}:{method}"
        if cache_key in self.version_cache:
            return self.version_cache[cache_key]
            
        # Get the absolute path to the file
        static_folder = current_app.static_folder
        full_path = os.path.join(static_folder, filepath)
        
        # Get version based on method
        version = None
        try:
            if os.path.exists(full_path):
                if method == 'mtime':
                    # Use file modification time
                    version = str(int(os.path.getmtime(full_path)))
                elif method == 'hash':
                    # Use a hash of the file content
                    # Skip large files to avoid memory issues
                    file_size = os.path.getsize(full_path)
                    if file_size > 10 * 1024 * 1024:  # Skip files larger than 10MB
                        # Use mtime instead for large files
                        version = str(int(os.path.getmtime(full_path)))
                    else:
                        with open(full_path, 'rb') as f:
                            content = f.read()
                            version = hashlib.md5(content).hexdigest()[:8]
                else:
                    # Fallback to current timestamp
                    version = str(int(time.time()))
            else:
                # File doesn't exist, use current timestamp
                version = str(int(time.time()))
        except Exception as e:
            logger.error(f"Error generating version for {filepath}: {str(e)}")
            version = str(int(time.time()))
            
        # Cache the version
        self.version_cache[cache_key] = version
        return version
        
# Initialize the static file versioning helper
file_versioning = StaticFileVersioning()