# app/database/pool.py

"""
Custom SQLAlchemy engine and connection pool with rate limiting.

This module provides a RateLimitedPool class that extends SQLAlchemy's QueuePool
to add rate limiting on connection checkouts, tracking of active connections,
and logging for long-running transactions. It also defines ENGINE_OPTIONS for the pool
configuration and a helper function, create_engine_with_retry(), to create an engine
with retry logic for initial connection attempts.
"""

from sqlalchemy.pool import QueuePool
from sqlalchemy import event, create_engine
from flask import has_request_context, request
import traceback
import time
import logging
import os

logger = logging.getLogger(__name__)

# Toggle for including detailed stack traces during pool operations.
DEBUG_POOL = False
# Toggle for logging connection resets at warning level.
LOG_CONNECTION_RESET = False


class RateLimitedPool(QueuePool):
    """
    A custom SQLAlchemy connection pool that rate limits checkouts and monitors
    connection usage to warn about long-running transactions.
    """
    def __init__(self, *args, **kwargs):
        # Track the last checkout time to enforce a minimum interval between checkouts.
        self._last_checkout = 0
        self._min_checkout_interval = 0.01  # Reduced from 0.1 to 0.01 for faster RSVP updates

        # Dictionary to track active connections:
        # { connection_id: (checkout_time, stack_trace, route) }
        self._active_connections = {}

        # For periodic checking of long-running transactions.
        self._last_transaction_check = 0
        self._transaction_check_interval = 15  # in seconds - reduced from 60s to 15s for more frequent checks

        super().__init__(*args, **kwargs)

        # Listen for pool events.
        event.listen(self, 'checkout', self._on_checkout)
        event.listen(self, 'checkin', self._on_checkin)
        event.listen(self, 'reset', self._on_reset)
        event.listen(self, 'connect', self._on_connect)
    
    def _on_connect(self, dbapi_conn, connection_record):
        """
        Event handler called when a new connection is created.
        
        Logs the new connection and registers it with the global connection tracker.
        """
        conn_id = id(dbapi_conn)
        logger.warning(f"POOL EVENT: _on_connect fired for connection {conn_id}")
        
        # Register with global connection tracker if it exists
        try:
            from app.utils.db_connection_monitor import register_connection
            register_connection(conn_id, "pool_connect")
            logger.warning(f"POOL EVENT: Successfully registered connection {conn_id}")
            
            # Add a weakref finalizer to ensure cleanup even if events fail
            import weakref
            def cleanup_on_gc():
                try:
                    from app.utils.db_connection_monitor import unregister_connection
                    unregister_connection(conn_id)
                    logger.debug(f"Finalizer unregistered connection {conn_id}")
                except:
                    pass
            
            weakref.finalize(dbapi_conn, cleanup_on_gc)
            
        except ImportError:
            logger.debug("Connection monitor not available")
        except Exception as e:
            logger.error(f"Error registering connection {conn_id}: {e}", exc_info=True)

    def _get_stack_info(self, depth=10):
        """
        Retrieve partial stack trace information up to the specified depth.
        
        :param depth: The number of stack frames to include.
        :return: A string representation of the stack trace.
        """
        try:
            stack = traceback.extract_stack(limit=depth)
            return "\n".join(
                f"File: {frame.filename}, Line: {frame.lineno}, Function: {frame.name}, Code: {frame.line}"
                for frame in stack
            )
        except Exception as e:
            logger.error(f"Error getting stack info: {e}")
            return "<stack trace error>"

    def _get_transaction_state(self):
        """
        Summarize the state of currently checked-out connections.
        
        :return: A dictionary containing the number of active connections and details for each.
        """
        now = time.time()
        active_conns = []
        for conn_id, (checkout_time, stack, route) in self._active_connections.items():
            duration = now - checkout_time
            active_conns.append({
                'connection_id': conn_id,
                'duration_seconds': f"{duration:.2f}",
                'route': route,
                'stack_at_checkout': stack,
            })
        return {
            'active_connections': len(self._active_connections),
            'connection_details': active_conns
        }

    def log_long_running_transactions(self, threshold_seconds=30):
        """
        Log a warning if any connection has been checked out longer than the threshold.
        
        :param threshold_seconds: Duration in seconds beyond which a connection is considered long-running.
        """
        now = time.time()
        for conn_id, (checkout_time, stack, route) in self._active_connections.items():
            duration = now - checkout_time
            if duration > threshold_seconds:
                logger.warning(
                    f"LONG RUNNING TRANSACTION DETECTED\n"
                    f"Duration: {duration:.1f}s\n"
                    f"Connection ID: {conn_id}\n"
                    f"Route: {route}\n"
                    f"Stack trace at checkout:\n{stack}\n"
                    f"Current stack:\n{self._get_stack_info() if DEBUG_POOL else '<stack omitted>'}"
                )

    def _check_transactions(self):
        """
        Periodically check and log long-running transactions.
        """
        now = time.time()
        if now - self._last_transaction_check > self._transaction_check_interval:
            self.log_long_running_transactions()
            self._last_transaction_check = now

    def _do_get(self):
        """
        Override the pool's _do_get to enforce a minimum interval between checkouts and track active connections.
        
        :return: A database connection from the underlying pool.
        """
        self._check_transactions()

        now = time.time()
        # Enforce a minimum checkout interval.
        if now - self._last_checkout < self._min_checkout_interval:
            time.sleep(self._min_checkout_interval)
        self._last_checkout = now

        conn = super()._do_get()
        # Capture stack trace at checkout if debugging is enabled.
        stack = self._get_stack_info(depth=20) if DEBUG_POOL else "<stack omitted>"
        self._active_connections[id(conn)] = (time.time(), stack, None)
        return conn

    def _on_checkout(self, dbapi_conn, con_record, con_proxy):
        """
        Event handler called when a connection is checked out from the pool.
        
        Attempts to capture the route (request path) if in a Flask request context.
        """
        conn_id = id(dbapi_conn)
        route = None
        try:
            if has_request_context():
                route = request.path
        except Exception:
            pass

        # Retrieve the initial checkout time and stack, if available.
        checkout_time, old_stack, _ = self._active_connections.get(
            conn_id, (time.time(), "<stack omitted>", None)
        )
        if DEBUG_POOL:
            old_stack = self._get_stack_info(depth=20)
        self._active_connections[conn_id] = (checkout_time, old_stack, route)

    def _on_checkin(self, dbapi_conn, con_record):
        """
        Event handler called when a connection is returned to the pool.
        
        Removes the connection from the active connections tracker and attempts a rollback.
        """
        conn_id = id(dbapi_conn)
        logger.warning(f"POOL EVENT: _on_checkin fired for connection {conn_id}")
        
        conn_info = self._active_connections.pop(conn_id, None)
        
        # Log if connection was checked out for too long
        if conn_info:
            checkout_time, _, route = conn_info
            duration = time.time() - checkout_time
            if duration > 30:
                logger.warning(f"Connection {conn_id} was checked out for {duration:.1f}s (route: {route})")

        try:
            if dbapi_conn and not dbapi_conn.closed:
                # Force rollback to clear any pending transactions
                dbapi_conn.rollback()
                # Reset connection state for PgBouncer
                if hasattr(dbapi_conn, 'reset'):
                    dbapi_conn.reset()
        except Exception as e:
            logger.error(f"Error during connection {conn_id} rollback: {e}", exc_info=True)
            # Mark connection as invalid to force recreation
            con_record.invalidate()
        finally:
            # Always unregister from global connection tracker, even if rollback fails
            try:
                from app.utils.db_connection_monitor import unregister_connection
                unregister_connection(conn_id)
                logger.warning(f"POOL EVENT: Successfully unregistered connection {conn_id}")
            except ImportError:
                logger.debug("Connection monitor not available - skipping unregister")
            except Exception as e:
                logger.error(f"CRITICAL: Failed to unregister connection {conn_id}: {e}", exc_info=True)
                # Force cleanup by clearing from active connections manually
                if hasattr(self, '_active_connections') and conn_id in self._active_connections:
                    self._active_connections.pop(conn_id, None)
                    logger.warning(f"Force removed connection {conn_id} from pool tracking")

    def _on_reset(self, dbapi_conn, record):
        """
        Event handler called when a connection is reset.
        
        Logs the reset event along with connection details and current transaction state.
        """
        conn_id = id(dbapi_conn)
        checkout_info = self._active_connections.get(conn_id, ("<unknown>", "<no stack>", None))
        checkout_time, checkout_stack, route = checkout_info
        current_stack = self._get_stack_info(depth=20) if DEBUG_POOL else "<stack omitted>"
        message = (
            f"CONNECTION RESET\n"
            f"Connection ID: {conn_id}\n"
            f"Route: {route}\n"
            f"Checked out at: {checkout_time}\n"
            f"Checkout Stack:\n{checkout_stack}\n"
            f"Current Transaction State: {self._get_transaction_state()}\n"
            f"Current Stack:\n{current_stack}"
        )
        if LOG_CONNECTION_RESET:
            logger.warning(message)
        else:
            if DEBUG_POOL and logger.isEnabledFor(logging.DEBUG):
                logger.debug(message)


# Check if using PgBouncer (detect from DATABASE_URL)
def _is_using_pgbouncer():
    """Check if the database URL indicates PgBouncer usage."""
    database_url = os.getenv('DATABASE_URL', '')
    return 'pgbouncer' in database_url.lower() or ':6432' in database_url

# ENGINE_OPTIONS for SQLAlchemy engine creation using RateLimitedPool.
def _get_connect_args():
    """Get connection arguments, conditionally including options for direct PostgreSQL connections."""
    connect_args = {
        'connect_timeout': int(os.getenv('SQLALCHEMY_ENGINE_OPTIONS_CONNECT_TIMEOUT', 5)),
    }
    
    # Only add PostgreSQL-specific options if not using PgBouncer
    if not _is_using_pgbouncer():
        connect_args['options'] = (
            f'-c statement_timeout={os.getenv("SQLALCHEMY_ENGINE_OPTIONS_STATEMENT_TIMEOUT", 30000)} '
            f'-c idle_in_transaction_session_timeout={os.getenv("SQLALCHEMY_ENGINE_OPTIONS_IDLE_IN_TRANSACTION_SESSION_TIMEOUT", 30000)} '
            '-c lock_timeout=3000 '
            '-c tcp_keepalives_idle=60 '
            '-c tcp_keepalives_interval=60 '
            '-c tcp_keepalives_count=3'
        )
    
    return connect_args

ENGINE_OPTIONS = {
    'pool_pre_ping': True,
    'pool_size': int(os.getenv('SQLALCHEMY_POOL_SIZE', 3)),  # Small pool since PgBouncer handles multiplexing
    'max_overflow': int(os.getenv('SQLALCHEMY_MAX_OVERFLOW', 2)),  # Allow some overflow for burst traffic
    'pool_recycle': int(os.getenv('SQLALCHEMY_POOL_RECYCLE', 1800)),
    'pool_timeout': int(os.getenv('SQLALCHEMY_POOL_TIMEOUT', 30)),  # Match env default
    'poolclass': RateLimitedPool,
    'pool_use_lifo': True,  # LIFO for better cache locality
    'pool_reset_on_return': 'rollback',  # Important for PgBouncer - always rollback on return
    'connect_args': _get_connect_args(),
    'echo': False,
    'echo_pool': False,
}


def create_engine_with_retry(*args, **kwargs):
    """
    Create an SQLAlchemy engine with retry logic for initial connection attempts.

    This function attempts to create and test an engine by executing a simple query.
    If the engine creation or connection fails, it retries up to a maximum number of times.

    :param args: Positional arguments to pass to create_engine.
    :param kwargs: Keyword arguments to pass to create_engine.
    :return: A connected SQLAlchemy engine.
    :raises Exception: If engine creation fails after the maximum retries.
    """
    max_retries = 3
    retry_delay = 1  # seconds

    for attempt in range(max_retries):
        try:
            engine = create_engine(*args, **kwargs)
            # Test the engine by making a simple query.
            with engine.connect() as conn:
                from sqlalchemy import text
                conn.execute(text("SELECT 1"))
            return engine
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            logger.warning(f"Engine creation attempt {attempt+1} failed: {e}")
            time.sleep(retry_delay)