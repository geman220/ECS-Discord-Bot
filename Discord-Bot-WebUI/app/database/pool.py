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
        self._min_checkout_interval = 0.1  # in seconds

        # Dictionary to track active connections:
        # { connection_id: (checkout_time, stack_trace, route) }
        self._active_connections = {}

        # For periodic checking of long-running transactions.
        self._last_transaction_check = 0
        self._transaction_check_interval = 60  # in seconds

        super().__init__(*args, **kwargs)

        # Listen for pool events.
        event.listen(self, 'checkout', self._on_checkout)
        event.listen(self, 'checkin', self._on_checkin)
        event.listen(self, 'reset', self._on_reset)

    def _get_stack_info(self, depth=10):
        """
        Retrieve partial stack trace information up to the specified depth.
        
        :param depth: The number of stack frames to include.
        :return: A string representation of the stack trace.
        """
        stack = traceback.extract_stack(limit=depth)
        return "\n".join(
            f"File: {frame.filename}, Line: {frame.lineno}, Function: {frame.name}, Code: {frame.line}"
            for frame in stack
        )

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
        self._active_connections.pop(conn_id, None)

        try:
            if dbapi_conn and not dbapi_conn.closed:
                dbapi_conn.rollback()
        except Exception as e:
            logger.error(f"Error during connection {conn_id} cleanup: {e}", exc_info=True)

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


# ENGINE_OPTIONS for SQLAlchemy engine creation using RateLimitedPool.
ENGINE_OPTIONS = {
    'pool_pre_ping': True,
    'pool_size': 10,
    'max_overflow': 5,
    'pool_recycle': 60,
    'pool_timeout': 10,
    'poolclass': RateLimitedPool,
    'pool_use_lifo': True,
    'connect_args': {
        'connect_timeout': 3,
        'options': (
            '-c statement_timeout=5000 '
            '-c idle_in_transaction_session_timeout=5000 '
            '-c lock_timeout=2000'
        )
    },
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
                conn.execute("SELECT 1")
            return engine
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            logger.warning(f"Engine creation attempt {attempt+1} failed: {e}")
            time.sleep(retry_delay)