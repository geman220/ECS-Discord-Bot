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
from typing import List, Callable, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)

class RequestLifecycle:
    def __init__(self):
        self.cleanup_handlers: List[Callable] = []
        self.before_request_handlers: List[Callable] = []
        self.after_request_handlers: List[Callable] = []
        self._template_cache: dict = {}
        self._static_cache: dict = {}
        self.db = None  # Will be set in init_app

    def init_app(self, app, db):
        """Initialize request lifecycle with app and database."""
        self.db = db

        self._register_render_transaction_release(app, db)

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
                if hasattr(g, 'db_session') and g.db_session is not None:
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

            # Cache on `g`, i.e. per request. The old cache was a dict on the
            # extension object, shared by every concurrent greenlet, and it now
            # holds ORM objects bound to one request's session — handing those to
            # another request is a session-leak waiting to happen. It was cleared
            # on every teardown anyway, so it never spanned requests in practice.
            if not hasattr(g, '_template_vars'):
                g._template_vars = self._get_template_vars()
            return g._template_vars

    def _register_render_transaction_release(self, app, db):
        """
        Commit (and thereby release) the request's DB transaction immediately
        BEFORE Jinja starts rendering.

        The database is a 1-vCPU box behind pgbouncer in transaction pooling mode,
        so a server connection is pinned for exactly as long as a transaction is
        open. This app opened one in before_request and held it until teardown —
        through the view, through template rendering, through everything. That made
        the pool a hard ceiling on CONCURRENT REQUESTS rather than concurrent
        queries, and any request that stalled past pgbouncer's 30s
        idle-transaction timeout had its connection killed mid-flight
        ("FATAL: idle transaction timeout").

        Rendering is the longest stretch of a page request that needs no database,
        so handing the slot back here is where the win is.

        Four guards, each of which we would be broken without:

        1. GET/HEAD only. POST handlers legitimately render mid-transaction — the
           feedback routes render an email body and then keep using the new row's
           id (app/feedback.py:155) — and committing there would split the write in
           half. Worse, @transactional (app/db_utils.py:147) RETRIES the whole view
           on OperationalError, so a half-committed POST could double-apply.
        2. Once per request. The signal fires for every render_template and
           render_template_string, including nested ones.
        3. Commit BOTH sessions. g.db_session and db.session are different sessions
           and either can hold a transaction open.
        4. Skip in degraded mode, where there is no usable session to begin with.

        This is safe only because SessionLocal now uses expire_on_commit=False
        (app/init/database.py) — otherwise the commit would expire every object in
        the template context and the first attribute access would immediately check
        out a fresh connection.
        """
        from flask.signals import before_render_template

        @before_render_template.connect_via(app)
        def _release_transaction_before_render(sender, template=None, context=None, **extra):
            if not has_app_context() or getattr(g, '_bypass_db', False):
                return
            if g.get('_txn_released_for_render', False):
                return
            if getattr(g, '_session_creation_failed', False):
                return
            try:
                if request.method not in ('GET', 'HEAD'):
                    return
            except RuntimeError:
                # No request context (e.g. rendering from a background job).
                return

            g._txn_released_for_render = True

            request_session = getattr(g, 'db_session', None)

            # g.db_session: commit. Teardown commits it anyway, so this changes
            # only WHEN its writes land, not WHETHER they do.
            #
            # db.session: commit ONLY if nothing is pending. This is not
            # squeamishness — Flask-SQLAlchemy's teardown calls db.session.remove(),
            # i.e. a ROLLBACK, so on a plain GET anything pending on db.session was
            # historically DISCARDED. Several admin pages rely on that: they
            # decorate ORM objects with display data before rendering, e.g.
            # `user.approved_by_user = <User>` (user_management/approvals.py:110,
            # waitlist.py:86, admin/user_approval_routes.py:284). approved_by_user
            # is a real relationship, so committing db.session on a GET turns those
            # scratch assignments into actual UPDATEs. They happen to be idempotent
            # today, but blanket-committing would remove the safety net for the
            # next one somebody writes. If db.session has pending state we leave it
            # alone and simply keep holding its connection through the render,
            # exactly as before this hook existed.
            sessions = [(request_session, True)]
            if db.session is not None:
                has_pending = bool(db.session.new or db.session.dirty or db.session.deleted)
                sessions.append((db.session, not has_pending))

            for session, may_commit in sessions:
                if session is None or not may_commit:
                    continue
                try:
                    session.commit()
                except Exception as e:
                    # The commit failed, so the session needs a rollback before it
                    # can be used again — but rollback EXPIRES the identity map
                    # regardless of expire_on_commit, so every object already handed
                    # to the template is now expired and its next attribute access
                    # will re-SELECT on a connection that just failed. Rendering is
                    # very likely to blow up. Log loudly: a confusing mid-Jinja
                    # traceback is much easier to diagnose with this line above it.
                    logger.error(
                        f"Failed to release transaction before render; the template "
                        f"context is now expired and rendering may fail: {e}",
                        exc_info=True,
                    )
                    try:
                        session.rollback()
                    except Exception:
                        pass

    def _get_template_vars(self) -> Dict[str, Any]:
        """Get template variables for the current request."""
        from app.models import Season

        # Reuse the request's session. This used to open a SECOND session via
        # current_app.SessionLocal(), which checks out a second connection — and
        # under pgbouncer transaction pooling that pins a second server slot,
        # simultaneously with the request session's still-open transaction. Every
        # rendered page therefore consumed two of a small, cluster-wide pool. The
        # per-endpoint cache that was supposed to make this rare is cleared on
        # every teardown (see cleanup_app_context), so it never actually hit.
        session = getattr(g, 'db_session', None)
        if session is None:
            return {'current_seasons': {}}

        try:
            seasons = session.query(Season).filter_by(is_current=True).all()
            return {'current_seasons': {s.league_type: s for s in seasons}}
        except Exception as e:
            # A DB hiccup here must not take down template rendering.
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to get template variables due to database error: {e}")
            return {'current_seasons': {}}

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


request_lifecycle = RequestLifecycle()