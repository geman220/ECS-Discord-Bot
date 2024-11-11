# app/lifecycle.py
import logging
from flask import g, has_app_context, request, current_app
from functools import wraps
from contextlib import contextmanager
import time
from functools import lru_cache

logger = logging.getLogger(__name__)

class RequestLifecycle:
    """Enhanced request and database lifecycle management"""
    
    def __init__(self):
        self.cleanup_handlers = []
        self.before_request_handlers = []
        self._template_cache = {}
        self._db = None  # Store db reference
        
    def init_app(self, app, db):
        """Initialize request lifecycle handlers"""
        self._db = db  # Store db reference for use in session_scope
        
        @app.before_request
        def setup_request():
            """Initialize request-state and handle request type"""
            # Skip DB operations for static files
            if request.path.startswith('/static/'):
                g._bypass_db = True
                return
                
            # Initialize request monitoring
            g._request_start_time = time.time()
            g._cleanups = []
            g._db_operations = []
            
            # Run registered before-request handlers
            for handler in self.before_request_handlers:
                try:
                    handler()
                except Exception as e:
                    logger.error(f"Before request handler error: {e}", exc_info=True)
                    
        @app.after_request
        def log_request_stats(response):
            """Log request statistics"""
            if not getattr(g, '_bypass_db', False):
                duration = time.time() - getattr(g, '_request_start_time', time.time())
                db_ops = getattr(g, '_db_operations', [])
                
                logger.info(f"Request completed: {request.path}",
                    extra={
                        'path': request.path,
                        'duration': duration,
                        'db_operations': len(db_ops),
                        'db_time': sum(op.get('duration', 0) for op in db_ops),
                        'status_code': response.status_code
                    })
            return response
                    
        @app.teardown_request
        def cleanup_request(exc):
            """Coordinated cleanup of request resources"""
            try:
                # Skip cleanup for static files
                if getattr(g, '_bypass_db', False):
                    return
                    
                duration = time.time() - getattr(g, '_request_start_time', time.time())
                
                # Log slow requests
                if duration > current_app.config.get('SLOW_REQUEST_THRESHOLD', 1.0):
                    logger.warning(f"Slow request: {request.path} took {duration:.2f}s")
                
                # Run registered cleanup handlers in reverse order
                if hasattr(g, '_cleanups'):
                    for cleanup in reversed(g._cleanups):
                        try:
                            cleanup(exc)
                        except Exception as e:
                            logger.error(f"Cleanup handler error: {e}", exc_info=True)
                            
                # Database session cleanup
                if hasattr(g, 'db_session'):
                    session = g.db_session
                    try:
                        if exc is not None:
                            session.rollback()
                        elif session.is_active:
                            session.commit()
                    except Exception as e:
                        logger.error(f"Session cleanup error: {e}", exc_info=True)
                        session.rollback()
                    finally:
                        session.close()
                        delattr(g, 'db_session')
                        
            except Exception as e:
                logger.error(f"Request cleanup error: {e}", exc_info=True)
                
            finally:
                if has_app_context():
                    self._clear_request_context()
        
        @app.teardown_appcontext
        def cleanup_app_context(exc):
            """Final cleanup when app context ends"""
            try:
                if not getattr(g, '_bypass_db', False):
                    from app.db_management import db_manager
                    db_manager.cleanup_connections(exc)
            except Exception as e:
                logger.error(f"App context cleanup error: {e}", exc_info=True)

        @app.context_processor
        def inject_template_vars():
            """Inject cached template variables"""
            if getattr(g, '_bypass_db', False):
                return {}
                
            if not hasattr(g, '_template_vars'):
                g._template_vars = self._get_template_vars()
            return g._template_vars

    @contextmanager
    def session_scope(self, transaction_name=None):
        """Database session context manager"""
        if not self._db:
            raise RuntimeError("Database not initialized. Call init_app first.")
            
        if getattr(g, '_bypass_db', False):
            raise RuntimeError("Database operations not allowed for static files")
            
        start_time = time.time()
        
        try:
            if hasattr(g, 'db_session'):
                yield g.db_session
                return
                
            session = self._db.session()
            g.db_session = session
            
            yield session
            
            if session.is_active:
                session.commit()
                
        except Exception as e:
            if hasattr(g, 'db_session'):
                g.db_session.rollback()
            logger.error(f"Session error: {e}", exc_info=True)
            raise
            
        finally:
            duration = time.time() - start_time
            self.log_db_operation(
                operation=transaction_name or 'unnamed_transaction',
                duration=duration
            )

    def _clear_request_context(self):
        """Clear all request-specific attributes"""
        for attr in list(vars(g)):
            try:
                delattr(g, attr)
            except (AttributeError, TypeError):
                pass

    @lru_cache(maxsize=32)
    def _get_template_vars(self):
        """Cache and return template variables"""
        # Avoid circular import
        if not hasattr(g, '_template_vars_loading'):
            g._template_vars_loading = True
            try:
                from app.models import Season
                with self.session_scope('get_template_vars'):
                    return {
                        'current_seasons': {
                            league_type: Season.query.filter_by(
                                league_type=league_type, 
                                is_current=True
                            ).first()
                            for league_type in ['Pub League', 'ECS FC']
                        }
                    }
            finally:
                delattr(g, '_template_vars_loading')
        return {}

    def log_db_operation(self, operation, duration):
        """Log database operation timing"""
        if has_app_context() and not getattr(g, '_bypass_db', False):
            if not hasattr(g, '_db_operations'):
                g._db_operations = []
            g._db_operations.append({
                'operation': operation,
                'duration': duration,
                'timestamp': time.time()
            })
            
    def register_cleanup(self, cleanup_func):
        """Register a cleanup function to run at request end"""
        if has_app_context() and not getattr(g, '_bypass_db', False):
            if not hasattr(g, '_cleanups'):
                g._cleanups = []
            g._cleanups.append(cleanup_func)
            
    def register_before_request(self, handler):
        """Register a function to run before each request"""
        self.before_request_handlers.append(handler)
        
    @contextmanager
    def request_context(self, cleanup_func=None):
        """Context manager for request-scoped operations"""
        try:
            if cleanup_func and not getattr(g, '_bypass_db', False):
                self.register_cleanup(cleanup_func)
            yield
        except Exception as e:
            logger.error(f"Error in request context: {e}", exc_info=True)
            raise
        finally:
            if cleanup_func and hasattr(g, '_cleanups'):
                try:
                    g._cleanups.remove(cleanup_func)
                except ValueError:
                    pass

request_lifecycle = RequestLifecycle()