# app/init/extensions.py

"""
Flask Extensions Initialization

Initialize Flask-Login, Flask-Mail, Flask-WTF CSRF, Flask-Migrate, and Celery.
"""

import logging
from flask_login import LoginManager
from flask_mail import Mail
from flask_wtf.csrf import CSRFProtect
from flask_migrate import Migrate

logger = logging.getLogger(__name__)

# Initialize Flask extensions
login_manager = LoginManager()
mail = Mail()
csrf = CSRFProtect()
migrate = Migrate()


def init_extensions(app, db):
    """
    Initialize Flask extensions for the application.

    Args:
        app: The Flask application instance.
        db: The SQLAlchemy db instance.

    Returns:
        tuple: (login_manager, mail, csrf, migrate)
    """
    from app.core import configure_celery
    from app.lifecycle import request_lifecycle

    # Initialize request lifecycle hooks
    request_lifecycle.init_app(app, db)

    def custom_before_request():
        # Request-specific logging moved to DebugMiddleware
        pass

    request_lifecycle.register_before_request(custom_before_request)

    # Configure login manager
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = None  # Disable the default message

    # IMPORTANT: Register CSRF exemptions BEFORE csrf.init_app()
    # Flask-WTF checks request.csrf_exempt attribute in its protect() method
    @app.before_request
    def exempt_background_endpoints_from_csrf():
        """Exempt background/polling endpoints from CSRF - they have their own auth."""
        from flask import request
        # Socket.IO has its own authentication mechanism
        # Navbar notifications uses session auth but is a background heartbeat
        exempt_prefixes = (
            '/socket.io/',
            '/api/notifications/',  # Presence refresh is a background heartbeat
        )
        if request.path.startswith(exempt_prefixes):
            request.csrf_exempt = True

    # Initialize CSRF with explicit configuration
    csrf.init_app(app)
    # Register admin routes that should be exempt from CSRF
    for endpoint in ['admin.force_send_message', 'admin.delete_message', 'admin.update_rsvp']:
        csrf._exempt_views.add(endpoint)

    mail.init_app(app)
    migrate.init_app(app, db)
    app.celery = configure_celery(app)

    # Exempt predictions API from CSRF
    from app.mobile_api.predictions import predictions_api
    csrf.exempt(predictions_api)

    # Register user loader
    @login_manager.user_loader
    def load_user(user_id):
        """
        Load user for Flask-Login with efficient session management.

        Uses request-level caching to prevent repeated DB queries within
        the same request, plus optimized query session for minimal connection time.
        """
        if not user_id:
            return None

        # Check request-level cache first to avoid redundant DB queries
        from flask import g, has_request_context
        cache_key = f'_loaded_user_{user_id}'
        if has_request_context():
            cached_user = getattr(g, cache_key, None)
            if cached_user is not None:
                return cached_user

        try:
            from app.utils.efficient_session_manager import EfficientQuery
            user = EfficientQuery.get_user_for_auth(user_id)

            # Cache in request context for subsequent calls
            if has_request_context() and user is not None:
                setattr(g, cache_key, user)

            return user
        except Exception as e:
            logger.error(f"Error loading user {user_id}: {str(e)}", exc_info=True)
            return None

    return login_manager, mail, csrf, migrate


def get_csrf():
    """Get the CSRF protection instance."""
    return csrf


def get_login_manager():
    """Get the login manager instance."""
    return login_manager
