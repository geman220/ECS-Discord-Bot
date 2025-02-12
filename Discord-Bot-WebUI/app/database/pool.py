from sqlalchemy.pool import QueuePool
from sqlalchemy import event
from sqlalchemy.exc import DisconnectionError
import traceback
import time
import logging

logger = logging.getLogger(__name__)

# Set these flags as needed. In production, both should be False.
DEBUG_POOL = False
LOG_CONNECTION_RESET = False

class RateLimitedPool(QueuePool):
    def __init__(self, *args, **kwargs):
        self._last_checkout = 0
        self._min_checkout_interval = 0.1
        self._active_connections = {}
        self._last_transaction_check = 0
        self._transaction_check_interval = 60

        super().__init__(*args, **kwargs)

        event.listen(self, 'checkout', self._on_checkout)
        event.listen(self, 'checkin', self._on_checkin)
        event.listen(self, 'reset', self._on_reset)

    def _get_stack_info(self, depth=10):
        """Get partial stack trace info."""
        stack = traceback.extract_stack(limit=depth)
        return "\n".join(
            f"File: {frame.filename}, Line: {frame.lineno}, "
            f"Function: {frame.name}, Code: {frame.line}"
            for frame in stack
        )

    def _get_transaction_state(self):
        """Summarize connections currently checked out."""
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
        """Warn if a connection is checked out longer than threshold."""
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
        """Periodically scan for long-running connections."""
        now = time.time()
        if now - self._last_transaction_check > self._transaction_check_interval:
            self.log_long_running_transactions()
            self._last_transaction_check = now

    def _do_get(self):
        self._check_transactions()

        now = time.time()
        if now - self._last_checkout < self._min_checkout_interval:
            time.sleep(self._min_checkout_interval)
        self._last_checkout = now

        conn = super()._do_get()
        stack = self._get_stack_info(depth=20) if DEBUG_POOL else "<stack omitted>"
        self._active_connections[id(conn)] = (time.time(), stack, None)
        return conn

    def _on_checkout(self, dbapi_conn, con_record, con_proxy):
        conn_id = id(dbapi_conn)
        route = None
        try:
            from flask import has_request_context, request
            if has_request_context():
                route = request.path
        except Exception:
            pass

        checkout_time, old_stack, _ = self._active_connections.get(conn_id, (time.time(), "<stack omitted>", None))
        if DEBUG_POOL:
            old_stack = self._get_stack_info(depth=20)
        self._active_connections[conn_id] = (checkout_time, old_stack, route)

    def _on_checkin(self, dbapi_conn, con_record):
        """When a connection is returned to the pool."""
        conn_id = id(dbapi_conn)
        self._active_connections.pop(conn_id, None)

        try:
            if dbapi_conn and not dbapi_conn.closed:
                dbapi_conn.rollback()
        except Exception as e:
            logger.error(f"Error during connection {conn_id} cleanup: {e}", exc_info=True)

    def _on_reset(self, dbapi_conn, record):
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
            '-c statement_timeout=10000 '
            '-c idle_in_transaction_session_timeout=10000 '
            '-c lock_timeout=5000'
        )
    },
    'echo': False,
    'echo_pool': False,
}

def create_engine_with_retry(*args, **kwargs):
    """
    Create engine with simple retry logic for initial connection attempts.
    """
    from sqlalchemy import create_engine
    import time

    max_retries = 3
    retry_delay = 1

    for attempt in range(max_retries):
        try:
            engine = create_engine(*args, **kwargs)
            with engine.connect() as conn:
                conn.execute("SELECT 1")
            return engine
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            logger.warning(f"Engine creation attempt {attempt+1} failed: {e}")
            time.sleep(retry_delay)