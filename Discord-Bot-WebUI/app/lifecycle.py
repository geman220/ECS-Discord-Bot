# app/lifecycle.py

"""
Lifecycle Module

This module provides a RequestLifecycle class that manages the lifecycle of each request.
It sets up before, after, and teardown request handlers to track performance, manage caching,
log database operations, and ensure proper cleanup of resources. This module is essential
for monitoring request performance and ensuring optimal resource usage throughout the application.
"""

import logging
from flask import g, has_app_context, request
import time
import uuid
from typing import List, Callable, Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

class RequestLifecycle:
    def __init__(self):
        self.cleanup_handlers: List[Callable] = []
        self.before_request_handlers: List[Callable] = []
        self.after_request_handlers: List[Callable] = []
        self._template_cache: dict = {}
        self._static_cache: dict = {}
        self._db_operation_log: List[dict] = []
        self.db = None  # Will be set in init_app

    def init_app(self, app, db):
        """Initialize request lifecycle with app and database."""
        self.db = db

        @app.before_request
        def setup_request():
            if request.path.startswith('/static/'):
                g._bypass_db = True
                g._static_request = True
                return

            g._bypass_db = False
            g._static_request = False
            g._request_start_time = time.time()
            g._db_operations = []
            g._session_id = str(uuid.uuid4())
            g._cache_hits = 0
            g._cache_misses = 0

            # Batch execute before-request handlers
            for handler in self.before_request_handlers:
                try:
                    handler()
                except Exception as e:
                    logger.error(f"Error in before-request handler: {e}")

        @app.after_request
        def add_cache_headers(response):
            if getattr(g, '_static_request', False):
                response.cache_control.max_age = 31536000
                response.cache_control.public = True
                response.add_etag()
            
            # Log request performance metrics
            self.log_request_performance(response)
            return response

        @app.teardown_request
        def cleanup_request(exc):
            if getattr(g, '_bypass_db', False):
                return
    
            try:
                from app.core.session_manager import cleanup_request
                cleanup_request(exc)
        
                if hasattr(g, '_cleanups'):
                    for cleanup_func in g._cleanups:
                        try:
                            cleanup_func()
                        except Exception as e:
                            logger.error(f"Cleanup handler error: {e}")
        
                self._clear_request_context()
        
            except Exception as e:
                logger.error(f"Request cleanup error: {e}", exc_info=True)

        @app.teardown_appcontext
        def cleanup_app_context(exc):
            """Final cleanup when app context ends."""
            try:
                if hasattr(g, 'db_session'):
                    # Double-check that db_session is properly closed
                    try:
                        g.db_session.close()
                        logger.debug("Closed db_session in teardown_appcontext as final safety check")
                    except Exception as session_err:
                        logger.error(f"Error closing session in teardown_appcontext: {session_err}", exc_info=True)
                    finally:
                        if hasattr(g, 'db_session'):
                            delattr(g, 'db_session')
                
                self._template_cache.clear()
                self._static_cache.clear()
            except Exception as e:
                logger.error(f"App context cleanup error: {e}", exc_info=True)

        @app.context_processor
        def inject_template_vars():
            """Inject template variables into all templates."""
            if getattr(g, '_bypass_db', False):
                return {}
            
            if request.endpoint not in self._template_cache:
                self._template_cache[request.endpoint] = self._get_template_vars()
            
            return self._template_cache[request.endpoint]

    def _get_template_vars(self) -> Dict[str, Any]:
        """Get template variables with caching."""
        from app.models import Season
        from flask import current_app
        
        # Always create a separate short-lived session for template variables
        # to avoid keeping the main request transaction open during template rendering
        session = current_app.SessionLocal()
        try:
            seasons = session.query(Season).filter_by(is_current=True).all()
            seasons_dict = {}
            for s in seasons:
                # Trigger loading of all needed attributes before expunging
                _ = s.id, s.name, s.league_type, s.is_current
                # Expunge the object so it's no longer bound to this session
                session.expunge(s)
                seasons_dict[s.league_type] = s
            # Commit and close quickly
            session.commit()
            return {'current_seasons': seasons_dict}
        except Exception as e:
            # If database query fails (e.g., connection timeout), return empty data
            # to prevent template rendering from crashing
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to get template variables due to database error: {e}")
            session.rollback()
            return {'current_seasons': {}}
        finally:
            session.close()

    def _clear_request_context(self):
        """Clear all request-specific attributes."""
        for attr in list(vars(g)):
            try:
                delattr(g, attr)
            except (AttributeError, TypeError):
                pass

    def register_cleanup(self, cleanup_func: Callable):
        """Register a cleanup function to run at request end."""
        if has_app_context() and not getattr(g, '_bypass_db', False):
            if not hasattr(g, '_cleanups'):
                g._cleanups = []
            g._cleanups.append(cleanup_func)

    def register_before_request(self, handler: Callable):
        """Add a before-request handler."""
        self.before_request_handlers.append(handler)

    def register_after_request(self, handler: Callable):
        """Add an after-request handler."""
        self.after_request_handlers.append(handler)

    def log_db_operation(self, operation: str, duration: float, sql_query: Optional[str] = None):
        """Log database operation timing with details."""
        if has_app_context() and not getattr(g, '_bypass_db', False):
            if not hasattr(g, '_db_operations'):
                g._db_operations = []
            
            operation_data = {
                'operation': operation,
                'duration': duration,
                'timestamp': time.time(),
                'sql_query': sql_query,
                'session_id': getattr(g, '_session_id', None)
            }
            
            g._db_operations.append(operation_data)
            self._db_operation_log.append(operation_data)
            
            logger.debug(
                f"DB Operation: {operation}, Duration: {duration:.2f}s, "
                f"Query: {sql_query}, Session: {getattr(g, '_session_id', None)}"
            )

    def log_request_performance(self, response):
        """Log detailed request performance metrics."""
        if not getattr(g, '_bypass_db', False):
            try:
                duration = time.time() - g._request_start_time
                db_ops = len(getattr(g, '_db_operations', []))
                
                metrics = {
                    'path': request.path,
                    'method': request.method,
                    'duration': f"{duration:.3f}s",
                    'db_operations': db_ops,
                    'status_code': response.status_code,
                    'session_id': getattr(g, '_session_id', None),
                    'cache_hits': getattr(g, '_cache_hits', 0),
                    'cache_misses': getattr(g, '_cache_misses', 0),
                    'timestamp': datetime.utcnow().isoformat()
                }
                
                if duration > 1.0:
                    logger.warning(f"Slow request detected: {metrics}")
                else:
                    logger.info(f"Request performance: {metrics}")
                
                return metrics
                
            except Exception as e:
                logger.error(f"Error logging request performance: {e}")
                return None

    def get_request_stats(self) -> Dict[str, Any]:
        """Get current request statistics."""
        return {
            'db_operations': len(self._db_operation_log),
            'cache_hits': getattr(g, '_cache_hits', 0),
            'cache_misses': getattr(g, '_cache_misses', 0),
            'active_handlers': {
                'cleanup': len(self.cleanup_handlers),
                'before_request': len(self.before_request_handlers),
                'after_request': len(self.after_request_handlers)
            }
        }

request_lifecycle = RequestLifecycle()