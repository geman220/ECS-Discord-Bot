# app/extensions.py
from flask_socketio import SocketIO
from flask_sqlalchemy import SQLAlchemy
from celery import Celery
from celery.signals import worker_process_init, worker_process_shutdown
import eventlet
import logging
import time
from sqlalchemy.pool import QueuePool
from contextlib import contextmanager

eventlet.monkey_patch()

logger = logging.getLogger(__name__)

class RateLimitedPool(QueuePool):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_checkout = 0
        self._min_checkout_interval = 0.1  # 100ms between checkouts

    def _do_get(self):
        # Rate limit connection creation
        now = time.time()
        if now - self._last_checkout < self._min_checkout_interval:
            time.sleep(self._min_checkout_interval)
        self._last_checkout = time.time()
        return super()._do_get()

# Initialize extensions with strict pool limits
db = SQLAlchemy(engine_options={
    'poolclass': RateLimitedPool,
    'pool_size': 2,  # Start with a small pool
    'max_overflow': 3,  # Allow few overflow connections
    'pool_timeout': 30,
    'pool_recycle': 300,
    'pool_pre_ping': True,
    'pool_use_lifo': True,
    'connect_args': {
        'connect_timeout': 10,
        'application_name': 'flask_app',
        'options': '-c statement_timeout=30000 -c idle_in_transaction_session_timeout=30000'
    }
})

socketio = SocketIO(
    async_mode='eventlet',
    engineio_logger=True,
    logger=True,
    cors_allowed_origins="*",
    ping_timeout=60,
    ping_interval=25,
)

def create_celery(app=None):
    """Create Celery instance with proper configuration"""
    _celery = Celery(
        'app',
        broker='redis://redis:6379/0',
        backend='redis://redis:6379/0',
    )

    _celery.conf.update(
        task_serializer='json',
        accept_content=['json'],
        result_serializer='json',
        timezone='UTC',
        enable_utc=True,
        broker_connection_retry_on_startup=True,
        worker_prefetch_multiplier=1,
        task_track_started=True,
        task_time_limit=30 * 60,
        task_soft_time_limit=15 * 60,
        worker_max_tasks_per_child=50,
        worker_max_memory_per_child=150000
    )

    class FlaskTask(_celery.Task):
        abstract = True
        _db_session = None

        @contextmanager
        def database_access(self):
            """Provide a context manager for database access"""
            if not hasattr(self, '_db_session') or self._db_session is None:
                self._db_session = db.create_scoped_session()
            try:
                yield self._db_session
            finally:
                if self._db_session:
                    self._db_session.remove()

        def __call__(self, *args, **kwargs):
            if app is None:
                from flask import current_app
                flask_app = current_app._get_current_object() if current_app else create_app()
            else:
                flask_app = app

            with flask_app.app_context():
                try:
                    return self.run(*args, **kwargs)
                finally:
                    if hasattr(self, '_db_session') and self._db_session:
                        self._db_session.remove()
                        self._db_session = None

    _celery.Task = FlaskTask

    # Add connection cleanup handlers
    @worker_process_init.connect
    def init_worker_process(**kwargs):
        """Initialize worker process with limited connections."""
        if hasattr(db, 'engine'):
            db.engine.dispose()
        # Force a new engine creation with proper pool size
        db.engine = db.create_engine()

    @worker_process_shutdown.connect
    def cleanup_worker_process(**kwargs):
        """Cleanup database connections when worker process shuts down."""
        if hasattr(db, 'engine'):
            db.engine.dispose()

    if app:
        _celery.conf.update(app.config)

    return _celery

# Create the base celery instance
celery = create_celery()