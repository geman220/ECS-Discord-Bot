# app/db_management.py

# Import Eventlet's green modules
from eventlet.green import threading, time
import logging
import sys
import uuid
import collections
from datetime import datetime, timedelta
from contextlib import contextmanager
from flask import g, has_app_context, current_app
from sqlalchemy import event, text
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import QueuePool
from sqlalchemy.exc import OperationalError, SQLAlchemyError, DisconnectionError
from typing import Optional, Dict, Set, Any
from app.core import db
from app.lifecycle import request_lifecycle
from sqlalchemy.sql import text
import eventlet
import traceback

logger = logging.getLogger(__name__)

# Use Eventlet's Semaphore
lock = eventlet.semaphore.Semaphore()

class DatabaseManager:
    def __init__(self, db):
        """Initialize database manager with enhanced monitoring"""
        self._cleanup_lock = threading.RLock()
        self.db = db
        self._engine = None
        self.app = None
        self.initialized = False
        self._active_connections = {}
        self._connection_timeouts = {}
        self.transaction_metadata = collections.defaultdict(lambda: {
            'transaction_name': 'Unknown',
            'stack_trace': None,
            'start_time': None,
            'query_log': [],
            'thread_info': None,
            'context': None
        })
        self._long_running_transactions = collections.defaultdict(float)
        self.connection_history = collections.deque(maxlen=100)
        self.pool_stats = {
            'checkouts': 0,
            'checkins': 0,
            'connections_created': 0,
            'leaked_connections': 0,
            'failed_connections': 0,
            'long_transactions': 0
        }
        self._transaction_times = collections.defaultdict(list)
        self._session_monitor = collections.defaultdict(dict)

    def init_app(self, app):
        """Initialize with Flask app and setup event handlers"""
        if self.initialized:
            return
        
        try:
            self.app = app
            self._engine = self.db.engine
        
            # Ensure app context for engine access
            ctx = None
            try:
                if not has_app_context():
                    ctx = app.app_context()
                    ctx.push()
                
                # Get existing engine from SQLAlchemy
                self._engine = self.db.get_engine(app, bind=None)
                if not self._engine:
                    raise RuntimeError("Database engine not properly initialized")
                
                logger.debug("Successfully acquired database engine")
            
                # Setup both engine and session events
                self._setup_engine_events()
                self._setup_session_events()  # Add this line
            
                # Register lifecycle handlers
                request_lifecycle.register_cleanup(self._cleanup_request)
                request_lifecycle.register_before_request(self._check_connections)
                app.teardown_appcontext(self._cleanup_app_context)
            
                # Initialize monitoring structures
                self._active_connections.clear()
                self._long_running_transactions.clear()
                self._session_monitor.clear()
                self.connection_history.clear()
            
                # Reset stats
                self.pool_stats = {
                    'checkouts': 0,
                    'checkins': 0,
                    'connections_created': 0,
                    'leaked_connections': 0,
                    'failed_connections': 0,
                    'long_transactions': 0
                }
            
                # Schedule cleanup
                self.schedule_metadata_cleanup()
            
                self.initialized = True
                logger.info("Database manager initialized successfully")
            
            finally:
                if ctx is not None:
                    ctx.pop()
                
        except Exception as e:
            logger.error(f"Failed to initialize database manager: {e}", exc_info=True)
            self.initialized = False
            raise

    def _capture_transaction_context(self, pid):
        """Capture detailed transaction context"""
        stack = traceback.extract_stack()
        # Skip internal frames
        relevant_frames = [
            f for f in stack 
            if not any(x in f.filename for x in ['sqlalchemy', 'db_manager', 'database'])
        ]
        
        if relevant_frames:
            frame = relevant_frames[-1]
            # Get local variables from the frame
            try:
                frame_locals = frame.frame.f_locals
                # Filter out private variables and large objects
                locals_dict = {
                    k: repr(v)[:100] for k, v in frame_locals.items()
                    if not k.startswith('_') and not callable(v)
                }
            except Exception:
                locals_dict = {}

            return {
                'file': frame.filename,
                'line': frame.lineno,
                'function': frame.name,
                'code': frame.line,
                'locals': locals_dict
            }
        return None

    def get_pool_stats(self):
        """
        Get comprehensive connection pool statistics
    
        Returns:
            dict: Dictionary containing pool statistics and metrics
        """
        try:
            if not self._engine:
                logger.warning("Database engine not initialized")
                return {}
            
            # Get current pool state
            pool = self._engine.pool
            current_connections = len(self._active_connections)
        
            # Calculate pool utilization metrics
            pool_size = pool.size() if hasattr(pool, 'size') else 0
            max_overflow = pool._max_overflow if hasattr(pool, '_max_overflow') else 0
            total_capacity = pool_size + max_overflow
            utilization = (current_connections / total_capacity * 100) if total_capacity > 0 else 0
        
            # Combine with tracked statistics
            stats = {
                # Current pool state
                'current_size': pool_size,
                'max_size': total_capacity, 
                'active_connections': current_connections,
                'available_connections': max(0, total_capacity - current_connections),
                'utilization_percentage': round(utilization, 2),
            
                # Lifetime statistics from self.pool_stats
                'total_checkouts': self.pool_stats['checkouts'],
                'total_checkins': self.pool_stats['checkins'],
                'connections_created': self.pool_stats['connections_created'],
                'leaked_connections': self.pool_stats['leaked_connections'],
                'failed_connections': self.pool_stats['failed_connections'],
                'long_transactions': self.pool_stats['long_transactions'],
            
                # Additional metrics
                'checkout_pending': pool._overflow if hasattr(pool, '_overflow') else 0,
                'checkedin': pool.checkedin() if hasattr(pool, 'checkedin') else 0
            }
        
            # Add timing statistics if available
            if hasattr(self, '_transaction_times') and self._transaction_times:
                times = [t for sublist in self._transaction_times.values() for t in sublist]
                if times:
                    stats.update({
                        'avg_transaction_time': sum(times) / len(times),
                        'max_transaction_time': max(times),
                        'min_transaction_time': min(times)
                    })
                
            return stats
        
        except Exception as e:
            logger.error(f"Error getting pool stats: {e}", exc_info=True)
            return {
                'error': str(e),
                'checkouts': self.pool_stats['checkouts'],
                'checkins': self.pool_stats['checkins']
            }

    def cleanup_connections(self, exception=None):
        """Clean up database connections with proper error handling"""
        try:
            with self._cleanup_lock:
                self.check_for_leaked_connections()
                self.terminate_idle_transactions()
                if self._engine:
                    self._engine.dispose()
        except Exception as e:
            logger.error(f"Error during connection cleanup: {e}")
        finally:
            self._active_connections.clear()

    def _cleanup_request(self, exception=None):
        """Consolidated request cleanup"""
        try:
            if has_app_context() and hasattr(g, 'db_session'):
                session = g.db_session
                try:
                    if exception is not None:
                        session.rollback()
                    elif session.is_active:
                        session.commit()
                finally:
                    session.close()
                    if hasattr(session, 'remove'):
                        session.remove()
                    delattr(g, 'db_session')
        except Exception as e:
            logger.error(f"Error during request cleanup: {e}")

    def _cleanup_app_context(self, exception=None):
        """App context cleanup"""
        try:
            self.check_for_leaked_connections()
            self.terminate_idle_transactions()
            if self._engine:
                self._engine.dispose()
        except Exception as e:
            logger.error(f"App context cleanup error: {e}")
        finally:
            self._active_connections.clear()

    def _check_connections(self):
        """Combined connection check handler"""
        if not self.app.debug:
            self.check_for_leaked_connections()
            self.terminate_idle_transactions()

    def terminate_idle_transactions(self, idle_timeout=30, transaction_timeout=15):
        """Terminate idle or long-running transactions."""
        with self._cleanup_lock:
            try:
                with self.session_scope(transaction_name='terminate_idle') as session:
                    session.execute(text(f"""
                        SELECT pg_terminate_backend(pid)
                        FROM pg_stat_activity
                        WHERE state = 'idle in transaction'
                        AND pid != pg_backend_pid()
                        AND (now() - state_change) > interval '{transaction_timeout} seconds'
                    """))
                    session.execute(text(f"""
                        SELECT pg_terminate_backend(pid)
                        FROM pg_stat_activity
                        WHERE state = 'idle'
                        AND pid != pg_backend_pid()
                        AND (now() - state_change) > interval '{idle_timeout} seconds'
                        AND application_name LIKE 'app_app%'
                    """))
            except Exception as e:
                logger.error(f"Error terminating idle transactions: {e}")

    def check_for_leaked_connections(self):
        """Identify and cleanup leaked connections"""
        current_time = time.time()
        leaked = []

        for conn_id, checkout_time in list(self._active_connections.items()):
            age = current_time - checkout_time
            if age > 60:  # Consider leaked after 60 seconds
                leaked.append(conn_id)
                logger.error(f"Leaked connection detected: {age:.1f}s old")
                self.pool_stats['leaked_connections'] += 1

        for conn_id in leaked:
            self._active_connections.pop(conn_id, None)

        if leaked:
            self.terminate_idle_transactions()

    def _log_connection_event(self, event_type: str, connection_id: str, duration: Optional[float] = None, extra: Optional[Dict[str, Any]] = None):
        """Enhanced connection event logging with stack trace."""
        stack_trace = traceback.format_stack()
        event = {
            'timestamp': datetime.utcnow().isoformat(),
            'event_type': event_type,
            'connection_id': connection_id,
            'thread_id': threading.get_ident(),
            'duration': duration,
            'stack_trace': ''.join(stack_trace),  # Add stack trace for debugging
            **(extra or {})
        }
        self.connection_history.append(event)
        if duration and duration > 1.0:
            logger.warning(f"Slow database operation: {event_type} took {duration:.2f}s")

    def _monitor_session(self, session_id: str, action: str):
        """Track session lifecycle"""
        self._session_monitor[session_id].update({
            'last_action': action,
            'timestamp': time.time(),
            'thread_id': threading.get_ident()
        })

        @event.listens_for(self._engine, 'checkout')
        def on_checkout(dbapi_conn, connection_record, connection_proxy):
            conn_id = str(uuid.uuid4())
            self._active_connections[conn_id] = time.time()
            self.pool_stats['checkouts'] += 1

            # Capture stack trace
            stack_trace = ''.join(traceback.format_stack())

            logger.info(
                f"Connection checked out: {conn_id}",
                extra={'connection_id': conn_id, 'stack_trace': stack_trace}
            )

            try:
                cursor = dbapi_conn.cursor()
                cursor.execute("""
                    SET LOCAL statement_timeout = '10s';
                    SET LOCAL idle_in_transaction_session_timeout = '10s';
                    SET LOCAL lock_timeout = '5s';
                """)
                cursor.close()
            except Exception as e:
                self.pool_stats['failed_connections'] += 1
                logger.error(f"Connection checkout failed: {e}")
                raise

        @event.listens_for(self._engine, 'checkin')
        def on_checkin(dbapi_conn, connection_record):
            conn_id = id(connection_record)
            if conn_id in self._active_connections:
                checkout_time = self._active_connections.pop(conn_id)
                duration = time.time() - checkout_time
                self._log_connection_event('checkin', str(conn_id), duration)

                if duration > 30:
                    self.pool_stats['long_transactions'] += 1
                    logger.warning(f"Long-lived connection detected: {duration:.1f}s")
            self.pool_stats['checkins'] += 1

        @event.listens_for(self._engine, 'connect')
        def on_connect(dbapi_conn, connection_record):
            self.pool_stats['connections_created'] += 1
            conn_id = str(uuid.uuid4())
            try:
                cursor = dbapi_conn.cursor()
                cursor.execute("""
                    SET SESSION statement_timeout = '10s';
                    SET SESSION idle_in_transaction_session_timeout = '10s';
                    SET SESSION lock_timeout = '5s';
                """)
                cursor.close()
                self._log_connection_event('connect', conn_id)
            except Exception as e:
                logger.error(f"Connection initialization failed: {e}")
                raise

        @event.listens_for(self._engine, 'reset')
        def on_reset(dbapi_conn, connection_record):
            conn_id = str(uuid.uuid4())
            try:
                cursor = dbapi_conn.cursor()
                cursor.execute("ROLLBACK")
                cursor.execute("""
                    SET SESSION statement_timeout = '10s';
                    SET SESSION idle_in_transaction_session_timeout = '10s';
                    SET SESSION lock_timeout = '5s';
                """)
                cursor.close()
                self._log_connection_event('reset', conn_id)
            except Exception as e:
                logger.error(f"Connection reset failed: {e}")
                raise

        @event.listens_for(self._engine, 'invalidate')
        def on_invalidate(dbapi_conn, connection_record, exception):
            conn_id = str(uuid.uuid4())
            logger.error(f"Connection invalidated due to: {exception}")
            self._log_connection_event('invalidate', conn_id, extra={'error': str(exception)})

    @contextmanager
    def session_scope(self, nested=False, transaction_name=None):
        logger.debug(f"Current metadata keys before session: {list(self.transaction_metadata.keys())}")
        session = None
        session_id = str(uuid.uuid4())
        start_time = time.time()
        stack_trace = traceback.format_stack()
    
        # Capture current thread information
        thread = threading.current_thread()
        thread_info = {
            'id': thread.ident,
            'name': thread.name
        }

        # Log a warning if no transaction_name is provided
        if not transaction_name:
            logger.warning(
                "Transaction started without a name",
                extra={'stack_trace': ''.join(stack_trace)}
            )

        # Initialize transaction metadata
        transaction_info = {
            'transaction_name': transaction_name or 'Unnamed Transaction',
            'stack_trace': ''.join(stack_trace),
            'start_time': datetime.utcnow().isoformat(),
            'session_id': session_id,
            'thread_info': thread_info,
            'query_log': [],
            'status': 'started'
        }

        # Store initial metadata
        self.transaction_metadata[session_id] = transaction_info

        logger.info(
            f"Starting session {session_id} for {transaction_name or 'Unnamed Transaction'}",
            extra={
                'session_id': session_id,
                'transaction': transaction_name,
                'stack_trace': ''.join(stack_trace)
            }
        )

        try:
            # Reuse existing session if available
            if has_app_context() and hasattr(g, 'db_session'):
                session = g.db_session
                if nested:
                    logger.debug(f"Starting nested transaction in session {session_id}")
                    with session.begin_nested():
                        yield session
                    return

            # Create new session
            Session = sessionmaker(
                bind=self.db.engine,
                autocommit=False,
                autoflush=False,
                expire_on_commit=False
            )
            session = Session()

            if has_app_context():
                g.db_session = session
                logger.debug(f"Created new session {session_id} in request context")

            # Configure session
            try:
                session.execute(text("""
                    SET LOCAL statement_timeout = '30s';
                    SET LOCAL idle_in_transaction_session_timeout = '30s';
                    SET LOCAL lock_timeout = '10s';
                """))
            except Exception as e:
                logger.warning(f"Failed to set session parameters: {e}")

            # Get and log PostgreSQL backend PID
            try:
                pid_result = session.execute(text("SELECT pg_backend_pid()")).scalar()
                if pid_result:
                    # Store metadata with PID as key for easier lookup
                    self.transaction_metadata[pid_result] = transaction_info
                    self.transaction_metadata[session_id] = transaction_info
                
                    # Set up query logging
                    @event.listens_for(session, 'after_execute')
                    def after_execute(session, clauseelement, multiparams, params, result):
                        query_info = {
                            'timestamp': datetime.utcnow().isoformat(),
                            'query': str(clauseelement),
                            'parameters': str(multiparams) if multiparams else str(params)
                        }
                        self.transaction_metadata[pid_result]['query_log'].append(query_info)
                    
            except Exception as e:
                logger.warning(f"Failed to retrieve PostgreSQL PID: {e}")

            yield session

            # Commit if active
            if session.is_active:
                try:
                    session.commit()
                    logger.debug(f"Committed session {session_id}")
                    if pid_result:
                        self.transaction_metadata[pid_result]['status'] = 'committed'
                except Exception as e:
                    logger.error(f"Commit failed for session {session_id}: {e}")
                    if pid_result:
                        self.transaction_metadata[pid_result]['status'] = 'commit_failed'
                    session.rollback()
                    raise

        except Exception as e:
            error_info = {
                'error': str(e),
                'error_type': type(e).__name__,
                'traceback': traceback.format_exc()
            }
            if pid_result:
                self.transaction_metadata[pid_result]['error'] = error_info
                self.transaction_metadata[pid_result]['status'] = 'error'
            
            logger.error(f"Session {session_id} failed: {e}", extra={'session_id': session_id, 'error': str(e)})
            if session and session.is_active:
                try:
                    session.rollback()
                    logger.info(f"Rolled back session {session_id}")
                except Exception as rollback_error:
                    logger.error(f"Rollback failed for session {session_id}: {rollback_error}")
            raise

        finally:
            duration = time.time() - start_time
            completion_info = {
                'end_time': datetime.utcnow().isoformat(),
                'duration': duration
            }

            # Update metadata in both places if it exists
            if pid_result:
                if pid_result in self.transaction_metadata:
                    self.transaction_metadata[pid_result].update(completion_info)
                if session_id in self.transaction_metadata:
                    self.transaction_metadata[session_id].update(completion_info)

            # Log operation timing
            request_lifecycle.log_db_operation(
                operation=transaction_name or 'Unnamed Transaction',
                duration=duration
            )

            # Cleanup session
            if session and not has_app_context():
                try:
                    session.close()
                    logger.debug(f"Closed session {session_id}")
                except Exception as e:
                    logger.error(f"Error closing session {session_id}: {e}")

            if has_app_context() and hasattr(g, 'db_session') and duration > 5:
                logger.warning(f"Long running session detected: {duration:.2f}s",
                              extra={
                                  'session_id': session_id,
                                  'duration': duration,
                                  'transaction': transaction_name
                              })

            logger.info(f"Session {session_id} completed in {duration:.2f}s",
                        extra={
                            'session_id': session_id,
                            'duration': duration,
                            'transaction': transaction_name
                        })

            logger.debug(f"Scheduling cleanup for session {session_id} and PID {pid_result}")
            logger.debug(f"Current metadata keys: {list(self.transaction_metadata.keys())}")

            # Schedule metadata cleanup after 5 minutes
            def cleanup_metadata():
                with self._cleanup_lock:
                    self.transaction_metadata.pop(session_id, None)
                    if pid_result:
                        self.transaction_metadata.pop(pid_result, None)

            eventlet.spawn_after(300, cleanup_metadata)

    def get_transaction_details(self, pid):
        """Get detailed information about a transaction."""
        try:
            # Convert pid to int if it's a string
            pid = int(pid)
        
            # First try direct PID lookup
            metadata = self.transaction_metadata.get(pid)
        
            # If not found by PID, try to find in session metadata
            if not metadata:
                # Search through all metadata for matching session info
                for meta in self.transaction_metadata.values():
                    if isinstance(meta, dict) and meta.get('session_id') == str(pid):
                        metadata = meta
                        break

            if not metadata:
                return None
            
            return {
                'transaction_name': metadata.get('transaction_name', 'Unknown'),
                'session_id': metadata.get('session_id'),
                'timing': {
                    'start_time': metadata.get('start_time'),
                    'end_time': metadata.get('end_time'),
                    'duration': metadata.get('duration')
                },
                'thread_info': metadata.get('thread_info'),
                'stack_trace': metadata.get('stack_trace'),
                'query_log': metadata.get('query_log', []),
                'error': metadata.get('error'),
                'status': metadata.get('status', 'unknown'),
                'pid': pid
            }
        except Exception as e:
            logger.error(f"Error getting transaction details: {e}", exc_info=True)
            return None

    def get_long_running_queries(self):
        """Get information about long-running queries"""
        try:
            with self.session_scope(transaction_name='get_long_running_queries') as session:
                result = session.execute(text("""
                    SELECT pid, now() - query_start as duration, query
                    FROM pg_stat_activity
                    WHERE state = 'active'
                    AND now() - query_start > interval '5 seconds'
                    AND pid != pg_backend_pid()
                """))
                return {row.pid: {'duration': row.duration, 'query': row.query}
                        for row in result}
        except Exception as e:
            logger.error(f"Error getting long running queries: {e}")
            return {}

    def get_detailed_stats(self):
        """Get detailed database statistics"""
        return {
            'pool_stats': self.pool_stats,
            'active_connections': {
                'count': len(self._active_connections),
                'ages': {conn_id: time.time() - checkout_time
                         for conn_id, checkout_time in self._active_connections.items()}
            },
            'long_running_transactions': dict(self._long_running_transactions),
            'recent_events': list(self.connection_history),
            'session_monitor': dict(self._session_monitor)
        }

    def cleanup_request(self, exception=None):
        """Clean up database session and connections for the current request."""
        try:
            if has_app_context():
                session = getattr(g, 'db_session', None)
                if session:
                    try:
                        if exception:
                            session.rollback()
                            logger.info("Session rolled back due to exception.")
                        elif session.is_active:
                            session.commit()
                            logger.info("Session committed successfully.")
                    except Exception as commit_or_rollback_error:
                        logger.error(
                            f"Error during commit/rollback: {commit_or_rollback_error}",
                            exc_info=True
                        )
                        session.rollback()
                    finally:
                        session.close()
                        logger.debug("Session closed successfully.")
                    delattr(g, 'db_session')  # Safely remove session from `g`
        except Exception as e:
            logger.error(f"Error during request cleanup: {e}", exc_info=True)

    def check_for_leaked_connections(self):
        current_time = time.time()
        leaked = []

        for conn_id, checkout_time in list(self._active_connections.items()):
            age = current_time - checkout_time
            if age > 60:  # Consider leaked after 60 seconds
                leaked.append(conn_id)
                metadata = self.transaction_metadata.get(conn_id, {})
                logger.error(f"Leaked connection detected: {age:.1f}s old", extra=metadata)
                self.pool_stats['leaked_connections'] += 1

        for conn_id in leaked:
            self._active_connections.pop(conn_id, None)

        return leaked

    def schedule_metadata_cleanup(self):
        """Schedule periodic cleanup of old transaction metadata"""
        def cleanup():
            try:
                current_time = datetime.utcnow()
                with self._cleanup_lock:
                    for pid, metadata in list(self.transaction_metadata.items()):
                        # Clean up completed transactions older than 1 hour
                        if metadata.get('end_time'):
                            end_time = datetime.fromisoformat(metadata['end_time'])
                            if (current_time - end_time).total_seconds() > 3600:
                                self.transaction_metadata.pop(pid, None)
                            
                        # Clean up stale transactions that never completed
                        elif metadata.get('start_time'):
                            start_time = datetime.fromisoformat(metadata['start_time'])
                            if (current_time - start_time).total_seconds() > 7200:  # 2 hours
                                self.transaction_metadata[pid].update({
                                    'status': 'stale',
                                    'error': 'Transaction never completed'
                                })
            except Exception as e:
                logger.error(f"Error during metadata cleanup: {e}")
            
        eventlet.spawn_after(300, cleanup)  # Run every 5 minutes

    def analyze_connection_patterns(self):
        """Analyze connection usage patterns for potential issues."""
        analysis = {
            'frequent_rollers': [],  # Sessions with many rollbacks
            'long_holders': [],      # Sessions holding connections too long
            'repeat_offenders': []   # PIDs frequently appearing in issues
        }
    
        for pid, metadata in self.transaction_metadata.items():
            if metadata.get('status') == 'error':
                # Track rollback patterns
                if metadata.get('error', {}).get('error_type') == 'OperationalError':
                    analysis['frequent_rollers'].append(pid)
                
            # Check connection hold times
            if metadata.get('duration', 0) > 30:  # 30 seconds
                analysis['long_holders'].append({
                    'pid': pid,
                    'duration': metadata['duration'],
                    'transaction_name': metadata['transaction_name']
                })
    
        return analysis

    def get_transaction_details(self, pid):
        """Get enhanced transaction details with analysis."""
        metadata = self.transaction_metadata.get(pid, {})
        if not metadata:
            return None
    
        # Get related transactions
        related_transactions = []
        for other_pid, other_meta in self.transaction_metadata.items():
            if other_pid != pid and other_meta.get('thread_info', {}).get('id') == metadata.get('thread_info', {}).get('id'):
                related_transactions.append({
                    'pid': other_pid,
                    'transaction_name': other_meta.get('transaction_name'),
                    'status': other_meta.get('status')
                })
    
        # Analyze queries
        long_queries = []
        total_query_time = 0
        for query in metadata.get('query_log', []):
            duration = query.get('duration', 0)
            total_query_time += duration
            if duration > 1.0:
                long_queries.append({
                    'query': query.get('query'),
                    'duration': duration,
                    'timestamp': query.get('timestamp')
                })
    
        return {
            'transaction_name': metadata.get('transaction_name', 'Unknown'),
            'session_id': metadata.get('session_id'),
            'timing': {
                'start_time': metadata.get('start_time'),
                'end_time': metadata.get('end_time'),
                'duration': metadata.get('duration'),
                'total_query_time': total_query_time
            },
            'thread_info': metadata.get('thread_info'),
            'stack_trace': metadata.get('stack_trace'),
            'query_log': metadata.get('query_log', []),
            'long_queries': long_queries,
            'error': metadata.get('error'),
            'status': metadata.get('status', 'unknown'),
            'related_transactions': related_transactions,
            'linked_sessions': metadata.get('linked_sessions', []),
            'analysis': {
                'has_long_queries': bool(long_queries),
                'query_count': len(metadata.get('query_log', [])),
                'had_retries': bool(metadata.get('retries')),
                'completion_status': 'completed' if metadata.get('end_time') else 'pending',
                'average_query_time': total_query_time / len(metadata.get('query_log', [])) if metadata.get('query_log') else 0
            }
        }

    def _setup_session_events(self):
        """Setup session-level event listeners"""
    
        # Listen to session events at the Session class level
        event.listen(db.session.__class__, 'after_begin', self._after_begin)
        event.listen(db.session.__class__, 'before_commit', self._before_commit)
        event.listen(db.session.__class__, 'after_commit', self._after_commit)
        event.listen(db.session.__class__, 'after_rollback', self._after_rollback)

    def _after_begin(self, session, transaction, connection):
        """Called when a transaction begins"""
        try:
            # Get PID directly from connection
            cursor = connection.connection.cursor()
            cursor.execute("SELECT pg_backend_pid()")
            pid = cursor.fetchone()[0]
            cursor.close()
        
            stack_trace = ''.join(traceback.format_stack())
            thread = threading.current_thread()
        
            # Store metadata
            session.info['pid'] = pid
            self.transaction_metadata[pid] = {
                'transaction_name': getattr(session, 'transaction_name', 'Unknown'),
                'stack_trace': stack_trace,
                'start_time': datetime.utcnow().isoformat(),
                'query_log': [],
                'thread_info': {
                    'id': thread.ident,
                    'name': thread.name
                },
                'session_id': str(uuid.uuid4())
            }
        
            # Add query logging to the session
            if not hasattr(session, '_query_logging_set'):
                event.listen(session, 'after_execute', self._after_execute)
                session._query_logging_set = True
            
        except Exception as e:
            logger.warning(f"Error in after_begin: {e}")

    def _before_commit(self, session):
        """Called before a commit"""
        pid = session.info.get('pid')
        if pid and pid in self.transaction_metadata:
            self.transaction_metadata[pid]['status'] = 'committing'

    def _after_commit(self, session):
        """Called after a commit"""
        pid = session.info.get('pid')
        if pid and pid in self.transaction_metadata:
            self.transaction_metadata[pid].update({
                'status': 'committed',
                'end_time': datetime.utcnow().isoformat()
            })

    def _after_rollback(self, session):
        """Called after a rollback"""
        pid = session.info.get('pid')
        if pid and pid in self.transaction_metadata:
            self.transaction_metadata[pid].update({
                'status': 'rolled_back',
                'end_time': datetime.utcnow().isoformat()
            })

    def _after_execute(self, session, clauseelement, multiparams, params, result):
        """Called after executing a query"""
        try:
            pid = session.info.get('pid')
            if pid and pid in self.transaction_metadata:
                query_info = {
                    'timestamp': datetime.utcnow().isoformat(),
                    'query': str(clauseelement),
                    'parameters': str(multiparams) if multiparams else str(params),
                    'context': self._capture_transaction_context(pid)
                }
                self.transaction_metadata[pid]['query_log'].append(query_info)
        except Exception as e:
            logger.warning(f"Error in after_execute: {e}")

    def _setup_engine_events(self):
        """Setup enhanced engine event listeners"""
        if not self._engine:
            return

        # Set up thread local storage
        self._local = threading.local()

        @event.listens_for(self._engine, 'before_cursor_execute')
        def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            self._local.query_start = time.time()
        
        @event.listens_for(self._engine, 'after_cursor_execute')
        def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            duration = time.time() - getattr(self._local, 'query_start', time.time())
        
            # Try to get current PID
            try:
                pid_result = cursor.connection.info.dbapi_connection.get_backend_pid()
                if pid_result in self.transaction_metadata:
                    query_info = {
                        'timestamp': datetime.utcnow().isoformat(),
                        'query': statement,
                        'parameters': str(parameters),
                        'duration': duration,
                        'context': self._capture_transaction_context(pid_result)
                    }
                    self.transaction_metadata[pid_result]['query_log'].append(query_info)
                
                    # Track if this is a long-running query
                    if duration > 1.0:  # More than 1 second
                        logger.warning(f"Long running query detected (PID: {pid_result}): {duration:.2f}s")
            except Exception as e:
                logger.warning(f"Error recording query information: {e}")

# Create global instance
db_manager = DatabaseManager(db)
