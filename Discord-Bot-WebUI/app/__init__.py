# app/__init__.py

"""
Flask Application Factory

This module provides the create_app function to initialize and configure the Flask
application. It sets up configuration from a specified config object, initializes
extensions (e.g., SQLAlchemy, Celery, SocketIO, Flask-Login, Mail, CSRF, Migrate),
configures Redis for caching and session storage, registers blueprints, context
processors, and error handlers, and applies middleware such as ProxyFix and debugging
support when in debug mode.
"""

import redis
import logging
import logging.config
import os

# Fix eventlet database connection handling
try:
    import eventlet.debug
    eventlet.debug.hub_prevent_multiple_readers(False)
except ImportError:
    pass

from datetime import timedelta
from flask import Flask, request, session, redirect, url_for, render_template, g, abort
from flask_assets import Environment
from flask_login import LoginManager, current_user
from flask_mail import Mail
from flask_wtf.csrf import CSRFProtect
from flask_session import Session
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_migrate import Migrate
from werkzeug.routing import BuildError
from werkzeug.routing.exceptions import WebsocketMismatch
from sqlalchemy.orm import joinedload, selectinload, sessionmaker
from sqlalchemy import text

from app.assets import init_assets
from app.log_config.logging_config import LOGGING_CONFIG
from app.utils.user_helpers import safe_current_user
from app.models import User, Role, Season
from app.models_substitute_pools import (
    SubstitutePool, SubstitutePoolHistory, SubstituteRequest, 
    SubstituteResponse, SubstituteAssignment
)
from app.models_draft_predictions import (
    DraftSeason, DraftPrediction, DraftPredictionSummary
)
from app.lifecycle import request_lifecycle
from app.alert_helpers import show_success, show_error, show_warning, show_info
from app.utils.display_helpers import format_position_name, format_field_name, format_datetime_pacific, format_datetime_pacific_short
from app.db_management import db_manager
from app.database.config import configure_db_settings
from app.utils.pgbouncer_utils import set_session_timeout

# Initialize Flask extensions.
login_manager = LoginManager()
mail = Mail()
csrf = CSRFProtect()
migrate = Migrate()

logger = logging.getLogger(__name__)

from app.core import db, socketio, configure_celery

def create_app(config_object='web_config.Config'):
    """
    Application factory function for creating a Flask app instance.

    Loads configuration from the specified config object, initializes Flask extensions,
    sets up logging, Redis, SQLAlchemy, Celery, and other components, and registers
    blueprints, context processors, and error handlers.

    Args:
        config_object: The configuration object to load (default is 'web_config.Config').

    Returns:
        A configured Flask application instance.
    """
    app = Flask(__name__, static_folder="static")
    app.config.from_object(config_object)
    
    # Initialize asset management.
    #assets = Environment(app)
    app.config['FLASK_ASSETS_USE_CDN'] = False
    #init_assets(app)
    app.assets = init_assets(app)

    # Configure logging using a dictConfig.
    # Use simplified logging for testing to avoid file permission issues
    if app.config.get('TESTING'):
        # Simple console-only logging for tests
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter(
            '%(asctime)s [%(levelname)s] %(name)s - %(message)s'
        ))
        
        # Configure root logger for tests
        root_logger = logging.getLogger()
        root_logger.handlers = [console_handler]
        root_logger.setLevel(logging.WARNING)
        
        # Configure app logger
        app.logger.handlers = [console_handler]
        app.logger.setLevel(logging.DEBUG if app.debug else logging.INFO)
    else:
        # Use full logging configuration for production
        logging.config.dictConfig(LOGGING_CONFIG)
        app.logger.setLevel(logging.INFO if app.debug else logging.WARNING)
        if app.debug:
            logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)

    # SECRET_KEY is mandatory.
    if not app.config.get('SECRET_KEY'):
        raise RuntimeError('SECRET_KEY must be set')

    # Initialize unified Redis connection manager
    from app.utils.redis_manager import get_redis_manager, get_redis_connection
    
    # Get the unified Redis manager instance
    redis_manager = get_redis_manager()
    
    # Use the unified manager for all Redis operations
    app.redis = redis_manager.client  # Decoded client for general use
    app.session_redis = redis_manager.raw_client  # Raw client for sessions
    app.redis_manager = redis_manager
    
    # Test unified Redis connections
    try:
        app.redis.ping()
        app.session_redis.ping()
        logger.info("Unified Redis connections established successfully")
        
        # Log connection pool statistics
        stats = redis_manager.get_connection_stats()
        logger.info(f"Unified Redis connection pool: {stats}")
            
    except Exception as e:
        logger.error(f"Redis connection failed: {e}")
        # Continue anyway - the unified manager will handle reconnection attempts
    
    # Register shutdown handler only for application shutdown (not request teardown)
    import atexit
    def cleanup_redis_on_shutdown():
        try:
            redis_manager.cleanup()
            logger.info("Unified Redis connections cleaned up on application shutdown")
        except Exception as e:
            logger.error(f"Error during Redis shutdown: {e}")
    
    atexit.register(cleanup_redis_on_shutdown)
    
    # Redis monitoring can be enabled if needed for debugging
    
    # Register database session cleanup
    from app.core.session_manager import cleanup_request
    app.teardown_appcontext(cleanup_request)

    # Configure database settings.
    configure_db_settings(app)
    db.init_app(app)

    # Create the engine and session factory within the app context.
    with app.app_context():
        db_manager.init_app(app)
        engine = db.engine
        SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        app.SessionLocal = SessionLocal
        
        # Import ECS FC models to ensure they are registered
        from app.models_ecs import EcsFcMatch, EcsFcAvailability
        from app.models_ecs_subs import EcsFcSubRequest, EcsFcSubResponse, EcsFcSubAssignment, EcsFcSubPool
        
        # Ensure the pl-unverified and pl-waitlist roles exist
        try:
            session = SessionLocal()
            try:
                # Check for pl-unverified role
                sub_role = session.query(Role).filter_by(name='pl-unverified').first()
                if not sub_role:
                    logger.info("Creating pl-unverified role in database")
                    sub_role = Role(name='pl-unverified', description='Substitute Player')
                    session.add(sub_role)
                    logger.info("pl-unverified role created successfully")
                
                # Check for pl-waitlist role
                waitlist_role = session.query(Role).filter_by(name='pl-waitlist').first()
                if not waitlist_role:
                    logger.info("Creating pl-waitlist role in database")
                    waitlist_role = Role(name='pl-waitlist', description='Player on waitlist for current season')
                    session.add(waitlist_role)
                    logger.info("pl-waitlist role created successfully")
                
                session.commit()
            except Exception as e:
                session.rollback()
                logger.error(f"Error ensuring roles exist: {e}", exc_info=True)
                raise
            finally:
                session.close()
        except Exception as e:
            logger.error(f"Failed to initialize roles: {e}", exc_info=True)

    # Initialize request lifecycle hooks.
    request_lifecycle.init_app(app, db)
    def custom_before_request():
        # Request-specific logging moved to DebugMiddleware
        pass
    request_lifecycle.register_before_request(custom_before_request)

    # Initialize additional extensions.
    # Configure login manager
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = None  # Disable the default "Please log in to access this page" message
    
    # Initialize CSRF with explicit configuration
    csrf.init_app(app)
    # Register admin routes that should be exempt from CSRF
    for endpoint in ['admin.force_send_message', 'admin.delete_message', 'admin.update_rsvp']:
        csrf._exempt_views.add(endpoint)  # Directly exempt these views from CSRF
    
    mail.init_app(app)
    migrate.init_app(app, db)
    app.celery = configure_celery(app)

    from app.API.predictions import predictions_api
    csrf.exempt(predictions_api)
    
    # Exempt specific admin routes from CSRF protection
    @csrf.exempt
    def csrf_exempt_route(route):
        # Admin routes that need to be exempt from CSRF
        admin_routes = [
            'admin.force_send_message',
            'admin.delete_message',
            'admin.update_rsvp',
            'admin.cleanup_old_messages_route',
            'admin.schedule_next_week',
            'admin.schedule_season',
            'admin.process_scheduled_messages',
            'admin.send_custom_sms',
            'admin.send_discord_dm'
        ]
        
        if route in admin_routes:
            return True
        return False
    
    # Fix for CSRF session token issues - set CSRF token if missing
    @app.before_request
    def ensure_csrf_token():
        # Skip for static resources and exempt routes
        if request.path.startswith('/static/') or request.method == 'GET':
            return None
        
        # Skip for API routes that should be exempt from CSRF
        if (request.path.startswith('/api/substitute-pools/') or 
            request.path.startswith('/api/ecs-fc/') or
            request.path.startswith('/api/availability/') or
            request.path.startswith('/api/predictions/') or
            request.path.startswith('/api/v2/') or
            request.path.startswith('/api/v1/') or
            request.path.startswith('/api/discord_bot_') or
            request.path.startswith('/api/sync_')):
            return None
        
        # Get session from flask
        from flask import session as flask_session
        
        # Check if session exists but CSRF token is missing
        if flask_session and 'csrf_token' not in flask_session:
            from flask_wtf.csrf import generate_csrf
            # Generate a token and store it in session
            token = generate_csrf()
            logger.info(f"Generated missing CSRF token for path: {request.path}")
            
        return None
    

    @login_manager.user_loader
    def load_user(user_id):
        """
        Load user for Flask-Login with efficient session management.
        
        Uses optimized query session to minimize connection holding time.
        """
        if not user_id:
            return None
            
        try:
            from app.utils.efficient_session_manager import EfficientQuery
            return EfficientQuery.get_user_for_auth(user_id)
        except Exception as e:
            logger.error(f"Error loading user {user_id}: {str(e)}", exc_info=True)
            return None

    # Initialize SocketIO with Redis as the message queue
    # Configure SocketIO to avoid conflicts with HTTP routes
    socketio.init_app(
        app,
        message_queue=app.config.get('REDIS_URL', 'redis://redis:6379/0'),
        manage_session=False,
        async_mode='eventlet',
        cors_allowed_origins=app.config.get('CORS_ORIGINS', '*'),
        path='/socket.io/',  # Explicitly set SocketIO path to avoid conflicts
        allow_upgrades=True,  # Allow HTTP to WebSocket upgrades
        transports=['websocket', 'polling']  # Support both transport methods
    )

    # CRITICAL: Import handlers AFTER socketio.init_app() so they register on the correct instance
    from . import socket_handlers
    # Import live reporting handlers to register /live namespace
    from app.sockets import live_reporting
    
    # Debug: Check if /live namespace handlers are registered
    try:
        if hasattr(socketio.server, 'handlers'):
            live_handlers = socketio.server.handlers.get('/live', {})
            logger.info(f"🔥 Handlers in /live namespace: {list(live_handlers.keys())}")
        else:
            logger.warning("🚫 No server.handlers attribute found for /live namespace")
    except Exception as e:
        logger.error(f"🚫 Error checking /live handlers: {e}")
    
    # Register blueprints, context processors, and error handlers
    init_blueprints(app)
    init_context_processors(app)
    
    logger.info("🎯 Socket.IO system initialized successfully")
    
    install_error_handlers(app)

    # Apply ProxyFix to handle reverse proxy headers.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
    
    # Add security middleware (non-breaking implementation)
    from app.security_middleware import SecurityMiddleware
    security_middleware = SecurityMiddleware(app)
    
    # Add rate limiting (with Redis backend)
    try:
        from flask_limiter import Limiter
        from flask_limiter.util import get_remote_address
        
        # Custom key function that respects proxy headers and exempts local traffic
        def get_client_ip():
            # Get real client IP from proxy headers
            if request.headers.get('X-Forwarded-For'):
                client_ip = request.headers.get('X-Forwarded-For').split(',')[0].strip()
            elif request.headers.get('X-Real-IP'):
                client_ip = request.headers.get('X-Real-IP')
            elif request.headers.get('CF-Connecting-IP'):
                client_ip = request.headers.get('CF-Connecting-IP')
            else:
                client_ip = request.remote_addr or 'unknown'
            
            # Exempt local and Docker network traffic from rate limiting
            local_networks = [
                '127.0.0.1',          # Localhost
                '172.18.0.1',         # Docker host
                'host.docker.internal' # Docker host alias
            ]
            
            # Exempt Docker internal networks (172.x.x.x)
            if (client_ip.startswith('172.') or 
                client_ip.startswith('192.168.') or 
                client_ip.startswith('10.') or
                client_ip in local_networks):
                return 'local_exempted'  # All local traffic uses same key, effectively unlimited
            
            return client_ip
        
        # Use Redis URL for limiter storage
        redis_url = app.config.get('REDIS_URL', 'redis://redis:6379/0')
        
        limiter = Limiter(
            app=app,
            key_func=get_client_ip,
            storage_uri=redis_url,
            default_limits=["5000 per day", "2000 per hour", "200 per minute"],
            headers_enabled=True,
            strategy="fixed-window"
        )
        
        # Exempt security endpoints from rate limiting to prevent middleware conflicts
        limiter.exempt('security_status.security_status')
        limiter.exempt('security_status.security_health')  
        limiter.exempt('security_status.security_logs')
        limiter.exempt('security_status.security_events')
        limiter.exempt('security_status.recent_threats')
        
        # Exempt admin endpoints from rate limiting to prevent admin lockout
        limiter.exempt('admin.match_management')
        limiter.exempt('admin.match_tasks')
        limiter.exempt('admin.get_match_task_status')
        limiter.exempt('admin_panel.dashboard')
        limiter.exempt('admin_panel.system_status')
        limiter.exempt('admin_panel.performance_monitoring')
        
        # Auth endpoints will use default rate limits
        # (removed problematic auth endpoint rate limiting that was causing the warning)
        
        # Store limiter reference for potential use in routes
        app.limiter = limiter
        logger.info("Rate limiting initialized with Redis backend")
        
    except Exception as e:
        logger.warning(f"Rate limiting initialization failed: {e}")
        # Continue without rate limiting - non-breaking
    
    # Create a session persistence middleware
    class SessionPersistenceMiddleware:
        def __init__(self, app, flask_app):
            self.app = app
            self.flask_app = flask_app
            self.logger = logging.getLogger(__name__)
            
        def __call__(self, environ, start_response):
            def session_aware_start_response(status, headers, exc_info=None):
                # Process the session before sending the response
                if hasattr(self.flask_app, 'session_interface') and 'flask.session' in environ:
                    session = environ['flask.session']
                    if session and session.modified:
                        self.logger.debug(f"Ensuring session is persisted in middleware: {session.sid if hasattr(session, 'sid') else 'unknown'}")
                        session.permanent = True
                return start_response(status, headers, exc_info)
            
            return self.app(environ, session_aware_start_response)
    
    # Apply session persistence middleware
    app.wsgi_app = SessionPersistenceMiddleware(app.wsgi_app, app)
    # SessionPersistenceMiddleware applied
    
    # Add basic security headers (non-breaking)
    @app.after_request
    def add_security_headers(response):
        """Add basic security headers to all responses."""
        # Only add headers to non-static content
        if not request.path.startswith('/static/'):
            response.headers.update({
                'X-Content-Type-Options': 'nosniff',
                'X-Frame-Options': 'SAMEORIGIN',  # Less restrictive than DENY
                'X-XSS-Protection': '1; mode=block',
                'Referrer-Policy': 'strict-origin-when-cross-origin',
                'Server': 'ECS Portal'  # Hide server details
            })
            
            # Add HSTS for HTTPS connections
            if request.is_secure:
                response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        
        return response

    # Apply DebugMiddleware in debug mode.
    if app.debug:
        app.wsgi_app = DebugMiddleware(app.wsgi_app, app)
        logger.info("Debug mode enabled with request logging")
        
    # Register CLI commands
    from app.cli import build_assets, init_discord_roles, sync_coach_roles
    app.cli.add_command(build_assets)
    app.cli.add_command(init_discord_roles)
    app.cli.add_command(sync_coach_roles)

    # Configure session management to use Redis (skip in testing).
    if not app.config.get('TESTING'):
        # Create a Redis client specifically for sessions that shares the connection pool
        # This ensures proper connection pool usage with Flask-Session
        from redis import Redis
        session_redis_client = Redis(connection_pool=redis_manager._pool, decode_responses=False)
        
        app.config.update({
            'SESSION_TYPE': 'redis',
            'SESSION_REDIS': session_redis_client,
            'PERMANENT_SESSION_LIFETIME': timedelta(days=7),
            'SESSION_KEY_PREFIX': 'session:',
            'SESSION_USE_SIGNER': True
        })
        Session(app)
    else:
        # Use Flask's default session implementation for testing
        app.logger.info("Testing mode: Using Flask default sessions instead of Redis")
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    # Initialize JWT for API authentication.
    from flask_jwt_extended import JWTManager
    JWTManager(app)
    
    # Initialize notification service
    from app.services.notification_service import notification_service
    import os
    
    service_account_path = os.path.join(app.instance_path, 'firebase-service-account.json')
    if os.path.exists(service_account_path):
        try:
            notification_service.initialize(service_account_path)
            logger.info("Firebase notification service initialized successfully")
        except Exception as e:
            logger.warning(f"Firebase service account file found but initialization failed: {e}")
    else:
        logger.warning("Firebase service account file not found at expected path")
    
    # Initialize PII encryption auto-update
    try:
        from app.utils.pii_update_wrapper import init_pii_encryption
        init_pii_encryption()
        logger.info("PII encryption auto-update initialized")
    except Exception as e:
        logger.warning(f"PII encryption initialization failed: {e}")

    @app.errorhandler(WebsocketMismatch)
    def handle_websocket_mismatch(error):
        """Handle WebSocket mismatch errors - now properly configured with Traefik"""
        app.logger.warning(f"WebSocket mismatch for {request.path} - this should be rare now")
        
        # With proper Traefik configuration, let Flask-SocketIO handle this normally
        # Returning None tells Flask-SocketIO to pass the request through
        return None

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        app.logger.error(f"Unhandled Exception: {error}", exc_info=True)
        return render_template("500.html"), 500

    @app.errorhandler(401)
    def unauthorized(error):
        # Unauthorized access redirected to login
        next_url = request.path
        # Use Flask's session explicitly
        from flask import session as flask_session
        
        # Don't show a flash message for unauthenticated users
        # Simply redirect to login
        if next_url != '/':
            flask_session['next'] = next_url
        return redirect(url_for('auth.login'))

    @app.errorhandler(404)
    def not_found(error):
        logger.warning(f"404 error: {request.path}")
        return render_template("404.html"), 404

    @app.errorhandler(BuildError)
    def handle_url_build_error(error):
        logger.error(f"URL build error: {str(error)}")
        if 'main.index' in str(error):
            try:
                return redirect(url_for('main.index'))
            except:
                return redirect('/')
        show_error('An error occurred while redirecting. You have been returned to the home page.')
        return redirect('/')

    @app.before_request
    def before_request():
        # Check for CSRF exemption first
        path = request.path
        exempt_routes = [
            '/admin/force_send/',  # Route handling force sending of scheduled messages
            '/admin/delete_message/',  # Route handling message deletion
            '/admin/update_rsvp',  # Route handling RSVP updates
            '/api/v1/',  # All API v1 routes (mobile app endpoints)
            '/api/v2/',  # All API v2 routes (enterprise RSVP endpoints)
            '/api/substitute-pools/',
            '/api/ecs-fc/',
            '/api/availability/',
            '/api/predictions/'
        ]
        
        # Check if the current request path starts with any of the exempt routes
        for route in exempt_routes:
            if path.startswith(route):
                # This is a protected admin route, exempt it from CSRF protection
                logger.info(f"Exempting route from CSRF: {path}")
                request.csrf_exempt = True
                break
        
        # Create a new database session for each request (excluding static assets).
        if not request.path.startswith('/static/'):
            # Try to create session with retry logic for pool exhaustion
            session_created = False
            max_retries = 3
            retry_delay = 0.1  # 100ms
            
            for attempt in range(max_retries):
                try:
                    g.db_session = app.SessionLocal()
                    session_created = True
                    break
                except Exception as e:
                    if "pool" in str(e).lower() or "timeout" in str(e).lower():
                        logger.warning(f"Session creation attempt {attempt + 1}/{max_retries} failed: {e}")
                        if attempt < max_retries - 1:
                            import time
                            time.sleep(retry_delay)
                            retry_delay *= 2  # Exponential backoff
                        else:
                            logger.error(f"Failed to create session after {max_retries} attempts: {e}")
                            # Set a flag to indicate degraded mode
                            g._session_creation_failed = True
                            break
                    else:
                        # Non-pool related error, don't retry
                        logger.error(f"Session creation failed with non-pool error: {e}", exc_info=True)
                        g._session_creation_failed = True
                        break
            
            # Only proceed with connection tracking if session was created
            if session_created and hasattr(g, 'db_session'):
                # CRITICAL: Register the underlying connection for tracking
                try:
                    # Get the actual database connection
                    conn = g.db_session.connection()
                    if hasattr(conn, 'connection') and hasattr(conn.connection, 'dbapi_connection'):
                        dbapi_conn = conn.connection.dbapi_connection
                        conn_id = id(dbapi_conn)
                        from app.utils.db_connection_monitor import register_connection
                        register_connection(conn_id, "flask_request")
                        # Connection registered silently
                except Exception as e:
                    logger.error(f"Failed to register Flask connection: {e}", exc_info=True)
            
            # Register session with monitor only if session was created successfully
            if session_created and hasattr(g, 'db_session'):
                session_id = str(id(g.db_session))
                from app.utils.session_monitor import get_session_monitor
                from app.utils.user_helpers import safe_current_user
                
                user_id = None
                try:
                    if safe_current_user and safe_current_user.is_authenticated:
                        user_id = safe_current_user.id
                except Exception as e:
                    # Don't fail the entire request if user lookup fails
                    logger.warning(f"Could not get user ID for session monitoring: {e}")
                    
                get_session_monitor().register_session_start(session_id, request.path, user_id)
                g.session_id = session_id
                
                # Set appropriate timeouts for this session based on request type
                # This will automatically skip timeout settings when using PgBouncer
                try:
                    if request.path.startswith('/admin/'):
                        # Admin routes may need longer timeouts for complex operations
                        set_session_timeout(g.db_session, statement_timeout_seconds=15, idle_timeout_seconds=10)
                    elif request.path.startswith('/api/'):
                        # API routes should be fast
                        set_session_timeout(g.db_session, statement_timeout_seconds=5, idle_timeout_seconds=3)
                    else:
                        # Regular routes get standard timeouts
                        set_session_timeout(g.db_session, statement_timeout_seconds=8, idle_timeout_seconds=5)
                except Exception as e:
                    logger.warning(f"Could not set session timeouts: {e}")
            else:
                # No session created - set degraded mode flag
                logger.warning(f"Request {request.path} proceeding without database session due to pool exhaustion")
                g.session_id = "no-session"
            
            # Pre-load and cache user roles early in the request to avoid session binding issues during template rendering
            from app.utils.user_helpers import safe_current_user
            if safe_current_user and safe_current_user.is_authenticated:
                try:
                    from app.role_impersonation import get_effective_roles, get_effective_permissions
                    # Cache roles for use in templates - ensure we get strings, not objects
                    roles = get_effective_roles()
                    permissions = get_effective_permissions()
                    
                    # Ensure these are simple lists of strings, not objects
                    g._cached_user_roles = list(roles) if roles else []
                    g._cached_user_permissions = list(permissions) if permissions else []
                    
                    # User roles and permissions cached silently
                except Exception as e:
                    logger.error(f"Error pre-loading user roles: {e}", exc_info=True)
                    g._cached_user_roles = []
                    g._cached_user_permissions = []

    @app.context_processor
    def inject_current_pub_league_season():
        """Inject the current Pub League season into every template's context."""
        from flask import g, has_request_context
        
        # Check if we're in degraded mode or have no Flask request session
        if (has_request_context() and 
            hasattr(g, '_session_creation_failed') and g._session_creation_failed):
            # Degraded mode - return default
            return dict(current_pub_league_season=None)
        
        # Try to use Flask's request session first to avoid creating competing sessions
        if has_request_context() and hasattr(g, 'db_session') and g.db_session:
            try:
                season = g.db_session.query(Season).filter_by(
                    league_type='Pub League',
                    is_current=True
                ).first()
                # Don't expunge since we're using the request session
                return dict(current_pub_league_season=season)
            except Exception as e:
                # If pool exhaustion or other DB errors, don't fall through - return None to prevent more sessions
                if "pool" in str(e).lower() or "timeout" in str(e).lower():
                    logger.warning(f"Pool exhaustion in context processor, returning default: {e}")
                    return dict(current_pub_league_season=None)
                logger.warning(f"Error fetching pub league season from request session: {e}")
                # Fall through to managed session approach only for non-pool errors
        
        # Fallback: Use managed_session for non-request contexts or when request session fails
        try:
            from app.core.session_manager import managed_session
            with managed_session() as session:
                season = session.query(Season).filter_by(
                    league_type='Pub League',
                    is_current=True
                ).first()
                if season:
                    # Trigger loading of all needed attributes before session closes
                    _ = season.id, season.name, season.league_type, season.is_current
                    session.expunge(season)
            return dict(current_pub_league_season=season)
        except Exception as e:
            logger.error(f"Error fetching pub league season: {e}", exc_info=True)
            # Return None instead of failing the entire template context
            return dict(current_pub_league_season=None)

    # Register template filter and global functions for display formatting
    @app.template_filter('format_position')
    def format_position_filter(position):
        """
        Template filter to format position names for display.
        Usage in templates: {{ player.favorite_position|format_position }}
        """
        return format_position_name(position)
    
    @app.template_global()
    def format_position(position):
        """
        Template global function to format position names for display.
        Usage in templates: {{ format_position('central_midfielder') }}
        """
        return format_position_name(position)
    
    @app.template_global()
    def format_field(field_name):
        """
        Template global function to format field names for display.
        Usage in templates: {{ format_field('favorite_position') }}
        """
        return format_field_name(field_name)
    
    @app.template_global()
    def format_pacific_time(utc_dt):
        """
        Template global function to format UTC datetime as Pacific Time.
        Usage in templates: {{ format_pacific_time(player.profile_last_updated) }}
        """
        return format_datetime_pacific(utc_dt)
    
    @app.template_global()
    def format_pacific_time_short(utc_dt):
        """
        Template global function to format UTC datetime as Pacific Time (short format).
        Usage in templates: {{ format_pacific_time_short(player.profile_last_updated) }}
        """
        return format_datetime_pacific_short(utc_dt)
    
    @app.template_filter('fromjson')
    def fromjson_filter(json_string):
        """
        Template filter to parse JSON strings.
        Usage in templates: {{ item.available_colors | fromjson }}
        """
        if not json_string:
            return []
        try:
            import json
            return json.loads(json_string)
        except (ValueError, TypeError, json.JSONDecodeError):
            return []
    
    # Register schedule display template helpers
    from app.template_helpers import register_template_helpers
    register_template_helpers(app)

    # Note: teardown_request is handled by lifecycle.py to avoid duplicate cleanup
        
    @app.teardown_appcontext
    def teardown_appcontext(exception):
        # DO NOT cleanup Redis connections here - this runs after every request!
        # The connection pool should persist across requests.
        # Only cleanup database sessions here if needed.
        pass
        
    # Register a function to gracefully shutdown when a worker terminates
    def worker_shutdown_cleanup():
        """
        Perform cleanup operations when a worker shuts down.
        This ensures proper resource release for Celery workers.
        """
        logger.info("Running worker shutdown cleanup")
        
        # Clean up Redis connections
        from app.utils.redis_manager import get_redis_manager
        redis_manager = get_redis_manager()
        redis_manager.cleanup()
        
        # Clean up any orphaned database sessions
        from app.db_management import db_manager
        try:
            db_manager.cleanup_orphaned_sessions()
        except Exception as e:
            logger.error(f"Error cleaning up orphaned sessions: {e}", exc_info=True)
            
    # Register the worker shutdown handler with Celery
    from app.core import celery
    celery.conf.worker_shutdown = worker_shutdown_cleanup

    # Initialize Enterprise RSVP Event Consumers
    logger.info("🚀 Initializing Enterprise RSVP Event Consumers...")
    try:
        # Import and start event consumers in a background thread
        import threading
        import asyncio
        from app.services.event_consumer import initialize_default_consumers, start_all_consumers
        
        def start_event_consumers():
            """Start event consumers in a separate thread."""
            try:
                logger.info("🔧 Starting Enterprise RSVP Event Consumers thread...")
                
                # Create new event loop for this thread
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                async def run_consumers():
                    """Initialize and run the event consumers."""
                    try:
                        # Initialize default consumers (WebSocket, Discord)
                        await initialize_default_consumers()
                        
                        # Start all consumers
                        await start_all_consumers()
                        
                        logger.info("✅ Enterprise RSVP Event Consumers started successfully!")
                        
                        # Keep the consumers running
                        while True:
                            await asyncio.sleep(1)
                            
                    except Exception as e:
                        logger.error(f"❌ Error in event consumer thread: {e}", exc_info=True)
                
                # Run the async consumer setup
                loop.run_until_complete(run_consumers())
                
            except Exception as e:
                logger.error(f"❌ Failed to start event consumers: {e}", exc_info=True)
        
        # Start event consumers in daemon thread (won't block app shutdown)
        consumer_thread = threading.Thread(target=start_event_consumers, daemon=True)
        consumer_thread.start()
        
        # Store thread reference for potential cleanup
        app.consumer_thread = consumer_thread
        
        logger.info("✅ Enterprise RSVP Event Consumers initialization started")
        
    except Exception as e:
        logger.error(f"⚠️ Enterprise RSVP Event Consumers initialization failed: {e}", exc_info=True)
        logger.info("Flask app will continue without event-driven features")

    return app

def init_blueprints(app):
    """
    Register blueprints with the Flask application.

    Imports and registers all blueprints for modular functionality.
    """
    logger = logging.getLogger(__name__)
    from app.auth import auth as auth_bp
    from app.publeague import publeague as publeague_bp
    from app.draft_enhanced import draft_enhanced as draft_enhanced_bp
    from app.players import players_bp
    from app.main import main as main_bp
    from app.teams import teams_bp
    from app.bot_admin import bot_admin_bp
    from app.availability_api import availability_bp
    from app.admin.blueprint import admin_bp
    from app.match_pages import match_pages
    from app.account import account_bp
    from app.email import email_bp
    from app.feedback import feedback_bp
    from app.user_management import user_management_bp
    from app.calendar import calendar_bp
    from app.sms_rsvp import sms_rsvp_bp
    from app.match_api import match_api
    from app.app_api import mobile_api
    from app.monitoring import monitoring_bp
    from app.user_api import user_bp
    from app.help import help_bp
    from app.search import search_bp
    from app.API.predictions import predictions_api
    from app.design_routes import design as design_bp
    from app.modals import modals as modals_bp
    from app.clear_cache import clear_cache_bp
    from app.external_api import external_api_bp
    from app.auto_schedule_routes import auto_schedule_bp
    from app.role_impersonation import role_impersonation_bp
    from app.ecs_fc_api import ecs_fc_api
    from app.admin.substitute_pool_routes import substitute_pool_bp
    from app.admin.redis_routes import redis_bp
    from app.batch_api import batch_bp
    from app.store import store_bp
    from app.draft_predictions_routes import draft_predictions_bp
    from app.wallet_routes import wallet_bp
    from app.admin.wallet_admin_routes import wallet_admin_bp
    from app.admin.notification_admin_routes import notification_admin_bp
    from app.admin_panel import admin_panel_bp
    from app.routes.notifications import notifications_bp
    from app.api_smart_sync import smart_sync_bp

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(publeague_bp, url_prefix='/publeague')
    app.register_blueprint(draft_enhanced_bp, url_prefix='/draft')
    app.register_blueprint(players_bp, url_prefix='/players')
    app.register_blueprint(teams_bp, url_prefix='/teams')
    app.register_blueprint(availability_bp, url_prefix='/api')
    app.register_blueprint(batch_bp)
    app.register_blueprint(account_bp, url_prefix='/account')
    app.register_blueprint(match_pages)
    app.register_blueprint(bot_admin_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(feedback_bp)
    app.register_blueprint(email_bp)
    app.register_blueprint(calendar_bp)
    app.register_blueprint(sms_rsvp_bp)
    app.register_blueprint(match_api, url_prefix='/api')
    app.register_blueprint(user_management_bp)
    app.register_blueprint(mobile_api, url_prefix='/api/v1')
    app.register_blueprint(user_bp, url_prefix='/api')
    app.register_blueprint(predictions_api, url_prefix='/api')
    app.register_blueprint(monitoring_bp)
    app.register_blueprint(help_bp, url_prefix='/help')
    app.register_blueprint(search_bp)
    app.register_blueprint(design_bp, url_prefix='/design')
    app.register_blueprint(modals_bp, url_prefix='/modals')
    app.register_blueprint(clear_cache_bp)
    app.register_blueprint(external_api_bp)
    app.register_blueprint(auto_schedule_bp, url_prefix='/auto-schedule')
    app.register_blueprint(role_impersonation_bp)
    app.register_blueprint(ecs_fc_api)  # Blueprint has url_prefix='/api/ecs-fc'
    app.register_blueprint(substitute_pool_bp)
    app.register_blueprint(redis_bp)
    app.register_blueprint(store_bp)  # Blueprint has url_prefix='/store'
    app.register_blueprint(draft_predictions_bp)  # Blueprint has url_prefix='/draft-predictions'
    app.register_blueprint(wallet_bp)  # Blueprint has url_prefix='/wallet'
    app.register_blueprint(wallet_admin_bp)  # Blueprint has url_prefix='/admin/wallet'
    app.register_blueprint(notification_admin_bp)  # Blueprint has url_prefix='/admin/notifications'
    app.register_blueprint(admin_panel_bp)  # Centralized admin panel
    app.register_blueprint(notifications_bp)  # Blueprint has url_prefix='/api/v1/notifications'
    app.register_blueprint(smart_sync_bp)  # Smart RSVP sync API endpoints
    csrf.exempt(smart_sync_bp)  # Exempt smart sync endpoints from CSRF
    
    # Import and register playoff management blueprint
    from app.playoff_routes import playoff_bp
    app.register_blueprint(playoff_bp)
    
    # Register cache admin routes
    from app.cache_admin_routes import cache_admin_bp
    from app.api_enterprise_rsvp import enterprise_rsvp_bp
    from app.api_observability import observability_bp
    # Mobile analytics blueprint
    from app.api_mobile_analytics import mobile_analytics_bp
    app.register_blueprint(cache_admin_bp)
    app.register_blueprint(enterprise_rsvp_bp)  # Enterprise RSVP API with reliability patterns
    app.register_blueprint(observability_bp)  # Observability and monitoring endpoints
    app.register_blueprint(mobile_analytics_bp)  # Mobile error analytics and logging endpoints
    
    # Register team notifications API
    from app.api_team_notifications import team_notifications_bp
    app.register_blueprint(team_notifications_bp)
    
    # Register test routes (only in development)
    if app.config.get('DEBUG', False):
        from app.test_team_notifications_route import test_bp
        app.register_blueprint(test_bp)
        
        # Live reporting test routes removed - use V2 production system for testing
    
    # Initialize enterprise RSVP system on app startup (simplified for Flask compatibility)
    try:
        # Only start in main web process, not in workers
        if not app.config.get('TESTING') and not os.environ.get('CELERY_WORKER'):
            logger.info("🚀 Enterprise RSVP system ready for initialization")
            logger.info("✅ Enterprise RSVP endpoints are active and ready")
        else:
            logger.info("ℹ️ Skipping enterprise RSVP initialization in worker process")
                
    except Exception as e:
        logger.error(f"❌ Enterprise RSVP initialization error: {e}")
    
    # Register duplicate management routes
    from app.admin.duplicate_management_routes import duplicate_management
    app.register_blueprint(duplicate_management)
    
    # Register AI Prompt Management (Enterprise Feature)
    from app.routes.ai_prompts import ai_prompts_bp
    app.register_blueprint(ai_prompts_bp)
    
    # Register AI Enhancement Routes for Live Reporting
    from app.routes.ai_enhancement_routes import ai_enhancement_bp
    app.register_blueprint(ai_enhancement_bp)
    
    # Register Security Status Routes
    try:
        app.logger.info("🔧 Attempting to import Security Status Blueprint...")
        from app.routes.security_status import security_status_bp
        app.logger.info("🔧 Security Status Blueprint imported, registering routes...")
        app.register_blueprint(security_status_bp, url_prefix='')
        app.logger.info("✅ Security Status Blueprint registered successfully")
        
        # Log the routes that were added
        security_routes = []
        for rule in app.url_map.iter_rules():
            if rule.endpoint and rule.endpoint.startswith('security_status.'):
                security_routes.append(f"{rule.rule} -> {rule.endpoint}")
        if security_routes:
            app.logger.info(f"🔧 Security routes registered: {security_routes}")
        else:
            app.logger.warning("⚠️ No security routes found after registration")
            
    except ImportError as ie:
        app.logger.error(f"❌ Import error for Security Status Blueprint: {ie}")
        app.logger.error(f"❌ This is likely a circular import or missing dependency issue in production")
    except Exception as e:
        app.logger.error(f"❌ Failed to register Security Status Blueprint: {e}")
        app.logger.error(f"❌ Error type: {type(e).__name__}")
        import traceback
        app.logger.error(f"❌ Traceback: {traceback.format_exc()}")
        # Don't let this prevent the app from starting
        pass

def init_context_processors(app):
    """
    Register context processors with the Flask application.

    Provides utilities such as safe_current_user, user roles, and permission-checking functions
    for use in templates.
    """
    @app.context_processor
    def utility_processor():
        from app.role_impersonation import (
            is_impersonation_active, get_effective_roles, get_effective_permissions,
            has_effective_permission, has_effective_role
        )
        from app.models.admin_config import AdminConfig
        
        # Get effective roles and permissions (considering impersonation)
        # Avoid database calls during template rendering by caching the results
        user_roles = []
        user_permissions = []
        
        # Get admin settings for template use
        admin_settings = {
            'teams_navigation_enabled': AdminConfig.get_setting('teams_navigation_enabled', True),
            'store_navigation_enabled': AdminConfig.get_setting('store_navigation_enabled', True),
            'matches_navigation_enabled': AdminConfig.get_setting('matches_navigation_enabled', True),
            'leagues_navigation_enabled': AdminConfig.get_setting('leagues_navigation_enabled', True),
            'drafts_navigation_enabled': AdminConfig.get_setting('drafts_navigation_enabled', True),
            'players_navigation_enabled': AdminConfig.get_setting('players_navigation_enabled', True),
            'messaging_navigation_enabled': AdminConfig.get_setting('messaging_navigation_enabled', True),
            'mobile_features_navigation_enabled': AdminConfig.get_setting('mobile_features_navigation_enabled', True),
            'waitlist_registration_enabled': AdminConfig.get_setting('waitlist_registration_enabled', True),
            'apple_wallet_enabled': AdminConfig.get_setting('apple_wallet_enabled', True),
            'push_notifications_enabled': AdminConfig.get_setting('push_notifications_enabled', True),
            'maintenance_mode': AdminConfig.get_setting('maintenance_mode', False)
        }
        
        # Only get roles if we have an active request context and user is authenticated
        if safe_current_user and safe_current_user.is_authenticated:
            try:
                # Use the cached roles from the request context if available
                if hasattr(g, '_cached_user_roles'):
                    user_roles = g._cached_user_roles
                    user_permissions = g._cached_user_permissions
                else:
                    # Get and cache roles for this request
                    user_roles = get_effective_roles()
                    user_permissions = get_effective_permissions()
                    g._cached_user_roles = user_roles
                    g._cached_user_permissions = user_permissions
            except Exception as e:
                logger.error(f"Error getting effective roles/permissions in template context: {e}")
                # Fallback to empty lists if there's an issue
                user_roles = []
                user_permissions = []

        def has_permission(permission_name):
            return permission_name in user_permissions

        def has_role(role_name):
            return role_name in user_roles

        def is_admin():
            return 'Global Admin' in user_roles or 'Pub League Admin' in user_roles
        
        def is_role_impersonation_active():
            return is_impersonation_active()

        return {
            'safe_current_user': safe_current_user,
            'user_roles': user_roles,
            'has_permission': has_permission,
            'has_role': has_role,
            'is_admin': is_admin,
            'is_role_impersonation_active': is_role_impersonation_active,
            'admin_settings': admin_settings
        }
    
    @app.context_processor
    def inject_file_versioning():
        """
        Add a file versioning function to templates for cache busting.
        
        This function allows templates to use {{ asset_version('path/to/file.js') }}
        to generate URLs with automatic version parameters based on file modification time.
        """
        import random
        import os
        from app.extensions import file_versioning
        
        def asset_version(filename):
            """
            Generate a versioned URL for a static file to bust browser caches.
            
            Uses a timestamp-based version from the file_versioning helper.
            """
            try:
                # Return the URL with version parameter
                from flask import url_for
                version = file_versioning.get_version(filename, 'mtime')
                return f"{url_for('static', filename=filename)}?v={version}"
            except Exception as e:
                logger.error(f"Error generating version for {filename}: {str(e)}")
                # Fallback to a random version
                return f"{url_for('static', filename=filename)}?v={random.randint(1, 1000000)}"
        
        return {'asset_version': asset_version}

def install_error_handlers(app):
    """
    Install custom error handlers with the Flask application.

    Additional error handlers can be defined and registered here.
    """
    pass

class DebugMiddleware:
    def __init__(self, wsgi_app, app):
        """
        Initialize DebugMiddleware.

        Args:
            wsgi_app: The original WSGI application.
            app: The Flask application instance.
        """
        self.wsgi_app = wsgi_app
        self.flask_app = app

    def __call__(self, environ, start_response):
        with self.flask_app.app_context():
            with self.flask_app.request_context(environ):
                from flask import request, session
                # Only log critical path information at INFO level
                path = environ.get('PATH_INFO')
                if not path.startswith('/static/') and not path.startswith('/test/status/'):
                    logger.info(f"{environ.get('REQUEST_METHOD')} {path}")

                def debug_start_response(status, headers, exc_info=None):
                    # Only log non-200 responses
                    if not status.startswith('200'):
                        logger.info(f"Response Status: {status} for {environ.get('PATH_INFO')}")
                    return start_response(status, headers, exc_info)

                try:
                    response = self.wsgi_app(environ, debug_start_response)
                    return response
                except Exception as e:
                    logger.error(f"Error in request: {str(e)}", exc_info=True)
                    raise