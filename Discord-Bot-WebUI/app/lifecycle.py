# app/lifecycle.py

import logging
from flask import g, has_app_context, request, current_app
from contextlib import contextmanager
import time
from functools import lru_cache

logger = logging.getLogger(__name__)

class RequestLifecycle:
    """Enhanced request and database lifecycle management"""
    
    def __init__(self):
        self.cleanup_handlers = []
        self.before_request_handlers = []
        self.after_request_handlers = []
        self._template_cache = {}

    def init_app(self, app, db):
        """Initialize request lifecycle handlers"""
        @app.before_request
        def setup_request():
            """Initialize request-specific state."""
            g._cleanups = []
            if request.path.startswith('/static/'):  # Skip for static files
                g._bypass_db = True
                return
            g._bypass_db = False
            g._db_operations = []
            g._request_start_time = time.time()

            # Run registered before-request handlers
            for handler in self.before_request_handlers:
                try:
                    handler()
                except Exception as e:
                    logger.error(f"Error in before-request handler: {e}", exc_info=True)
                    
        @app.after_request
        def log_request_stats(response):
            """Log request statistics and run after-request handlers."""
            if not getattr(g, '_bypass_db', False):
                duration = time.time() - g._request_start_time
                logger.info(
                    f"Request stats: path={request.path}, duration={duration:.3f}s, "
                    f"db_ops={len(g._db_operations)}"
                )

            # Run registered after-request handlers
            for handler in self.after_request_handlers:
                try:
                    handler(response)
                except Exception as e:
                    logger.error(f"Error in after-request handler: {e}", exc_info=True)

            return response
                    
        @app.teardown_request
        def cleanup_request(exc):
            from app.db_management import db_manager
            """Clean up request resources."""
            if getattr(g, '_bypass_db', False):
                return
            try:
                db_manager.cleanup_request(exc)  # Delegate to DatabaseManager
            except Exception as e:
                logger.error(f"Session cleanup error: {e}", exc_info=True)
        
        @app.teardown_appcontext
        def cleanup_app_context(exc):
            from app.db_management import db_manager
            """Final cleanup when app context ends."""
            try:
                db_manager.cleanup_connections(exc)  # Consolidate cleanup
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

    def _clear_request_context(self):
        """Clear all request-specific attributes"""
        for attr in list(vars(g)):
            try:
                delattr(g, attr)
            except (AttributeError, TypeError):
                pass

    @lru_cache(maxsize=32)
    def _get_template_vars(self):
        from app.db_management import db_manager
        """Cache and return template variables."""
        from app.models import Season
        with db_manager.session_scope('get_template_vars') as session:
            return {
                'current_seasons': {
                    league_type: session.query(Season).filter_by(
                        league_type=league_type, 
                        is_current=True
                    ).first()
                    for league_type in ['Pub League', 'ECS FC']
                }
            }

    def register_cleanup(self, cleanup_func):
        """Register a cleanup function to run at request end."""
        if has_app_context() and not getattr(g, '_bypass_db', False):
            if not hasattr(g, '_cleanups'):
                g._cleanups = []  # Initialize `g._cleanups` if missing
            g._cleanups.append(cleanup_func)

    def register_before_request(self, handler):
        """Add a before-request handler."""
        self.before_request_handlers.append(handler)

    def register_after_request(self, handler):
        """Add an after-request handler."""
        self.after_request_handlers.append(handler)

    def log_db_operation(self, operation, duration, sql_query=None):
        """Log database operation timing with additional details."""
        if has_app_context() and not getattr(g, '_bypass_db', False):
            if not hasattr(g, '_db_operations'):
                g._db_operations = []
            g._db_operations.append({
                'operation': operation,
                'duration': duration,
                'timestamp': time.time(),
                'sql_query': sql_query  # Log query details if available
            })
        logger.debug(f"DB Operation: {operation}, Duration: {duration:.2f}s, Query: {sql_query}")

request_lifecycle = RequestLifecycle()
