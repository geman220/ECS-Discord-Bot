# app/init/request_handlers.py

"""
Request Handlers

Before request, teardown, and CSRF handling.
"""

import logging

from flask import request, session as flask_session, g, render_template
from flask_wtf.csrf import generate_csrf

logger = logging.getLogger(__name__)


def init_request_handlers(app, csrf):
    """
    Initialize request handlers for the Flask application.

    Args:
        app: The Flask application instance.
        csrf: The CSRF protection instance.
    """
    _init_csrf_handlers(app, csrf)
    _init_before_request(app)
    _init_teardown_handlers(app)


def _init_csrf_handlers(app, csrf):
    """Initialize CSRF token handling."""

    @app.before_request
    def ensure_csrf_token():
        # Skip for static resources and exempt routes
        if request.path.startswith('/static/') or request.method == 'GET':
            return None

        # Skip for API routes that should be exempt from CSRF
        exempt_prefixes = [
            '/socket.io/',  # Socket.IO has its own authentication
            '/api/notifications/',  # Presence refresh is a background heartbeat
            '/api/substitute-pools/',
            '/api/ecs-fc/',
            '/api/availability/',
            '/api/predictions/',
            '/api/v2/',
            '/api/v1/',
            '/api/discord_bot_',
            '/api/sync_'
        ]

        for prefix in exempt_prefixes:
            if request.path.startswith(prefix):
                return None

        # Check if session exists but CSRF token is missing
        if flask_session and 'csrf_token' not in flask_session:
            token = generate_csrf()
            logger.info(f"Generated missing CSRF token for path: {request.path}")

        return None


def _init_before_request(app):
    """Initialize before_request handler."""
    from app.utils.user_helpers import safe_current_user
    from app.utils.pgbouncer_utils import set_session_timeout

    @app.before_request
    def before_request():
        # Skip all session/Redis operations for static files
        # This prevents Redis connection exhaustion when serving static assets
        if request.path.startswith('/static/'):
            return

        # Sync theme settings from cookies to session (for anti-flash support)
        # This must happen before any template rendering
        _sync_theme_from_cookie()
        _sync_theme_variant_from_cookie()
        _sync_theme_preset_from_cookie()

        # Check for CSRF exemption first
        path = request.path
        exempt_routes = [
            '/socket.io/',  # Socket.IO has its own authentication
            '/api/notifications/',  # Presence refresh is a background heartbeat
            '/admin/force_send/',
            '/admin/delete_message/',
            '/admin/update_rsvp',
            '/api/v1/',
            '/api/v2/',
            '/api/substitute-pools/',
            '/api/ecs-fc/',
            '/api/availability/',
            '/api/predictions/'
        ]

        for route in exempt_routes:
            if path.startswith(route):
                logger.info(f"Exempting route from CSRF: {path}")
                request.csrf_exempt = True
                break

        # Create a new database session for each request (excluding static assets)
        if not request.path.startswith('/static/'):
            session_created = _create_db_session(app)

            if session_created and hasattr(g, 'db_session'):
                _register_session_with_monitor(path)
                _set_session_timeouts(path)
            else:
                logger.warning(f"Request {request.path} proceeding without database session due to pool exhaustion")
                g.session_id = "no-session"

            # Pre-load and cache user roles
            _cache_user_roles()


def _create_db_session(app):
    """Create database session with retry logic."""
    import time

    max_retries = 3
    retry_delay = 0.1

    for attempt in range(max_retries):
        try:
            g.db_session = app.SessionLocal()
            return True
        except Exception as e:
            if "pool" in str(e).lower() or "timeout" in str(e).lower():
                logger.warning(f"Session creation attempt {attempt + 1}/{max_retries} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    logger.error(f"Failed to create session after {max_retries} attempts: {e}")
                    g._session_creation_failed = True
                    return False
            else:
                logger.error(f"Session creation failed with non-pool error: {e}", exc_info=True)
                g._session_creation_failed = True
                return False

    return False


def _register_session_with_monitor(path):
    """Register session with session monitor."""
    from app.utils.session_monitor import get_session_monitor
    from app.utils.user_helpers import safe_current_user

    session_id = str(id(g.db_session))
    user_id = None

    try:
        if safe_current_user and safe_current_user.is_authenticated:
            user_id = safe_current_user.id
    except Exception as e:
        logger.warning(f"Could not get user ID for session monitoring: {e}")
        # Rollback session to clear any failed transaction state
        if hasattr(g, 'db_session') and g.db_session:
            try:
                g.db_session.rollback()
            except Exception:
                pass

    get_session_monitor().register_session_start(session_id, path, user_id)
    g.session_id = session_id


def _set_session_timeouts(path):
    """Set appropriate timeouts for the session based on request type."""
    from app.utils.pgbouncer_utils import set_session_timeout

    try:
        if path.startswith('/admin/'):
            set_session_timeout(g.db_session, statement_timeout_seconds=15, idle_timeout_seconds=10)
        elif path.startswith('/api/'):
            set_session_timeout(g.db_session, statement_timeout_seconds=5, idle_timeout_seconds=3)
        else:
            set_session_timeout(g.db_session, statement_timeout_seconds=8, idle_timeout_seconds=5)
    except Exception as e:
        logger.warning(f"Could not set session timeouts: {e}")
        # Rollback session to clear any failed transaction state
        if hasattr(g, 'db_session') and g.db_session:
            try:
                g.db_session.rollback()
            except Exception:
                pass


def _cache_user_roles():
    """Pre-load and cache user roles early in the request."""
    from app.utils.user_helpers import safe_current_user

    if safe_current_user and safe_current_user.is_authenticated:
        try:
            from app.role_impersonation import get_effective_roles, get_effective_permissions
            roles = get_effective_roles()
            permissions = get_effective_permissions()

            g._cached_user_roles = list(roles) if roles else []
            g._cached_user_permissions = list(permissions) if permissions else []
        except Exception as e:
            logger.error(f"Error pre-loading user roles: {e}", exc_info=True)
            g._cached_user_roles = []
            g._cached_user_permissions = []
            # Rollback session to clear failed transaction state
            if hasattr(g, 'db_session') and g.db_session:
                try:
                    g.db_session.rollback()
                except Exception:
                    pass


def _sync_theme_from_cookie():
    """
    Sync theme preference from cookie to session.

    This ensures the server knows the user's theme preference on the first request,
    which is critical for rendering the correct data-style attribute and color-scheme
    to prevent FOUC (Flash of Unstyled Content).
    """
    try:
        # Get theme from cookie
        theme_cookie = request.cookies.get('theme')

        if theme_cookie and theme_cookie in ['light', 'dark', 'system']:
            # Only update session if cookie value differs
            current_session_theme = flask_session.get('theme', 'light')
            if theme_cookie != current_session_theme:
                flask_session['theme'] = theme_cookie
                logger.debug(f"Synced theme from cookie: {theme_cookie}")
    except Exception as e:
        # Don't let theme sync errors break the request
        logger.debug(f"Could not sync theme from cookie: {e}")


def _sync_theme_variant_from_cookie():
    """
    Sync theme variant preference from cookie to session.

    This ensures the server knows the user's variant preference (e.g., 'modern')
    for proper server-side rendering.
    """
    try:
        # Get variant from cookie
        variant_cookie = request.cookies.get('theme_variant')

        if variant_cookie and variant_cookie in ['modern', 'classic']:
            # Only update session if cookie value differs
            current_session_variant = flask_session.get('theme_variant', 'modern')
            if variant_cookie != current_session_variant:
                flask_session['theme_variant'] = variant_cookie
                logger.debug(f"Synced theme variant from cookie: {variant_cookie}")
    except Exception as e:
        # Don't let theme sync errors break the request
        logger.debug(f"Could not sync theme variant from cookie: {e}")


def _sync_theme_preset_from_cookie():
    """
    Sync theme preset preference from cookie to session.

    This ensures the server knows the user's preset preference on the first request,
    which is critical for injecting the correct colors in the blocking script
    to prevent theme flash.
    """
    try:
        # Get preset from cookie
        preset_cookie = request.cookies.get('theme_preset')

        if preset_cookie:
            # Only update session if cookie value differs
            current_session_preset = flask_session.get('theme_preset', 'default')
            if preset_cookie != current_session_preset:
                flask_session['theme_preset'] = preset_cookie
                logger.debug(f"Synced theme preset from cookie: {preset_cookie}")
    except Exception as e:
        # Don't let theme sync errors break the request
        logger.debug(f"Could not sync theme preset from cookie: {e}")


def _init_teardown_handlers(app):
    """Initialize teardown handlers."""

    @app.teardown_appcontext
    def teardown_appcontext(exception):
        # DO NOT cleanup Redis connections here - this runs after every request!
        # Only cleanup database sessions here if needed.
        pass
