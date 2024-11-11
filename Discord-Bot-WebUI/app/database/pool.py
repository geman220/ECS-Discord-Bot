# app/database/pool.py
from sqlalchemy.pool import QueuePool
from sqlalchemy import event
from sqlalchemy.exc import DisconnectionError
import time
import logging

logger = logging.getLogger(__name__)

class RateLimitedPool(QueuePool):
    """Custom connection pool with rate limiting and enhanced connection validation"""
    
    def __init__(self, *args, **kwargs):
        self._last_checkout = 0
        self._min_checkout_interval = 0.1
        self._active_connections = {}
        super().__init__(*args, **kwargs)
        
        # Register connection validation
        event.listen(self, 'checkout', self._on_checkout)
        event.listen(self, 'checkin', self._on_checkin)
    
    def _do_get(self):
        now = time.time()
        if now - self._last_checkout < self._min_checkout_interval:
            time.sleep(self._min_checkout_interval)
        self._last_checkout = time.time()
        
        conn = super()._do_get()
        self._active_connections[id(conn)] = now
        return conn
    
    def _do_return_conn(self, conn):
        conn_id = id(conn)
        if conn_id in self._active_connections:
            del self._active_connections[conn_id]
        super()._do_return_conn(conn)
    
    def _on_checkout(self, dbapi_conn, con_record, con_proxy):
        """Validate connection on checkout"""
        try:
            cursor = dbapi_conn.cursor()
            try:
                cursor.execute("SELECT 1")
                cursor.fetchall()
            except Exception as e:
                logger.error(f"Connection validation failed: {e}")
                raise DisconnectionError("Connection validation failed")
            finally:
                cursor.close()
        except Exception as e:
            logger.error(f"Connection checkout failed: {e}")
            raise DisconnectionError(f"Failed to validate connection: {e}")
    
    def _on_checkin(self, dbapi_conn, con_record):
        """Clean up connection on checkin"""
        try:
            # Ensure any open transaction is rolled back
            if not dbapi_conn.closed:
                dbapi_conn.rollback()
        except Exception as e:
            logger.warning(f"Error during connection checkin cleanup: {e}")
    
    def dispose(self):
        """Enhanced disposal with cleanup"""
        # Log active connections before disposal
        if self._active_connections:
            logger.warning(f"Disposing pool with {len(self._active_connections)} active connections")
            
        # Attempt to close all active connections
        for conn_id in list(self._active_connections.keys()):
            try:
                logger.info(f"Closing active connection {conn_id}")
                del self._active_connections[conn_id]
            except Exception as e:
                logger.error(f"Error closing connection {conn_id}: {e}")
        
        super().dispose()

# Default engine configuration with enhanced settings
ENGINE_OPTIONS = {
    'pool_pre_ping': True,
    'pool_size': 10,
    'max_overflow': 20,
    'pool_recycle': 1800,  # 30 minutes
    'pool_timeout': 30,
    'poolclass': RateLimitedPool,
    'pool_use_lifo': True,
    'connect_args': {
        'connect_timeout': 5,
        'options': '-c statement_timeout=30000 -c idle_in_transaction_session_timeout=30000'
    },
    'echo': False,  # Set to True for debugging SQL
    'echo_pool': False  # Set to True for debugging connection pool
}

def create_engine_with_retry(*args, **kwargs):
    """Create engine with retry logic for initial connection"""
    from sqlalchemy import create_engine
    import time
    
    max_retries = 3
    retry_delay = 1
    
    for attempt in range(max_retries):
        try:
            engine = create_engine(*args, **kwargs)
            # Test the connection
            with engine.connect() as conn:
                conn.execute("SELECT 1")
            return engine
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            logger.warning(f"Engine creation attempt {attempt + 1} failed: {e}")
            time.sleep(retry_delay)