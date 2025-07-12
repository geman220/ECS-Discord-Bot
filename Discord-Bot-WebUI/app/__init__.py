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

from datetime import timedelta
from flask import Flask, request, session, redirect, url_for, render_template, g
from flask_assets import Environment
from flask_login import LoginManager, current_user
from flask_mail import Mail
from flask_wtf.csrf import CSRFProtect
from flask_session import Session
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_migrate import Migrate
from werkzeug.routing import BuildError
from sqlalchemy.orm import joinedload, sessionmaker
from sqlalchemy import text

from app.assets import init_assets
from app.log_config.logging_config import LOGGING_CONFIG
from app.utils.user_helpers import safe_current_user
from app.models import User, Role, Season
from app.models_substitute_pools import (
    SubstitutePool, SubstitutePoolHistory, SubstituteRequest, 
    SubstituteResponse, SubstituteAssignment
)
from app.lifecycle import request_lifecycle
from app.alert_helpers import show_success, show_error, show_warning, show_info
from app.utils.display_helpers import format_position_name, format_field_name
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
        app.logger.setLevel(logging.DEBUG)
        if app.debug:
            logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)

    # SECRET_KEY is mandatory.
    if not app.config.get('SECRET_KEY'):
        raise RuntimeError('SECRET_KEY must be set')

    # Initialize Redis clients using RedisManager for persistent connections
    from app.utils.redis_manager import RedisManager
    
    # Initialize a single Redis manager for the application
    redis_manager = RedisManager()
    app.redis = redis_manager.client
    
    # Create a dedicated connection pool for Flask sessions that doesn't use decode_responses
    from redis import ConnectionPool, Redis
    redis_url = app.config['REDIS_URL']
    session_pool = ConnectionPool.from_url(
        redis_url,
        decode_responses=False,
        socket_timeout=10,
        socket_connect_timeout=10,
        socket_keepalive=True,
        socket_keepalive_options={},
        health_check_interval=30,
        retry_on_timeout=True,
        max_connections=50
    )
    session_redis = Redis(connection_pool=session_pool)
    
    # Test connections once during startup
    try:
        app.redis.ping()
        session_redis.ping()
        logger.info("Redis connections established successfully")
        
        # Log initial connection pool stats
        if hasattr(redis_manager, 'get_connection_stats'):
            stats = redis_manager.get_connection_stats()
            logger.info(f"Redis connection pool initialized: {stats}")
            
    except Exception as e:
        logger.error(f"Redis connection failed: {e}")
        # Continue anyway - the Redis manager will handle reconnection attempts
    
    # Register shutdown handler to properly close Redis connections
    @app.teardown_appcontext
    def shutdown_redis_connections(exception=None):
        redis_manager.shutdown()

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
        
        # Ensure the pl-unverified role exists
        try:
            session = SessionLocal()
            sub_role = session.query(Role).filter_by(name='pl-unverified').first()
            if not sub_role:
                logger.info("Creating pl-unverified role in database")
                sub_role = Role(name='pl-unverified', description='Substitute Player')
                session.add(sub_role)
                session.commit()
                logger.info("pl-unverified role created successfully")
            session.close()
        except Exception as e:
            logger.error(f"Error ensuring pl-unverified role exists: {e}", exc_info=True)

    # Initialize request lifecycle hooks.
    request_lifecycle.init_app(app, db)
    def custom_before_request():
        logger.debug(f"Custom logic for request: {request.path}")
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
            request.path.startswith('/api/predictions/')):
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
    
    # Exempt specific admin routes from CSRF protection since they're protected by authentication and role requirements
    @app.after_request
    def csrf_exempt_admin_routes(response):
        # Get current request path
        path = request.path
        
        # List of routes to exempt from CSRF protection
        exempt_routes = [
            '/admin/force_send/',  # Route handling force sending of scheduled messages
            '/admin/delete_message/',  # Route handling message deletion
            '/admin/update_rsvp'  # Route handling RSVP updates
        ]
        
        # Check if the current request path starts with any of the exempt routes
        for route in exempt_routes:
            if path.startswith(route):
                # This is a protected admin route, exempt it from CSRF protection
                logger.info(f"Exempting admin route from CSRF: {path}")
                request.csrf_exempt = True
                break
                
        return response

    @login_manager.user_loader
    def load_user(user_id):
        """
        Load user for Flask-Login with proper session management.
        
        Uses a dedicated short-lived session to avoid connection leaks.
        This is called frequently and must not hold connections open.
        """
        if not user_id:
            return None
            
        try:
            # Use a dedicated short-lived session for user loading
            session = app.SessionLocal()
            try:
                user = session.query(User).options(
                    joinedload(User.roles).joinedload(Role.permissions),
                    joinedload(User.notifications),
                    joinedload(User.player)
                ).get(int(user_id))
                
                if user:
                    # Trigger loading of all needed attributes before expunging
                    _ = user.id, user.username, user.email
                    if user.roles:
                        for role in user.roles:
                            _ = role.id, role.name
                            if role.permissions:
                                for perm in role.permissions:
                                    _ = perm.id, perm.name
                    if user.notifications:
                        for notif in user.notifications:
                            _ = notif.id, notif.content
                    if user.player:
                        _ = user.player.id, user.player.name
                    
                    # Expunge the user so it's no longer bound to this session
                    session.expunge(user)
                
                # Commit quickly to release any locks
                session.commit()
                return user
                
            except Exception as e:
                session.rollback()
                logger.error(f"Error loading user {user_id}: {str(e)}", exc_info=True)
                return None
            finally:
                session.close()
                
        except Exception as e:
            logger.error(f"Critical error in user loader for user {user_id}: {str(e)}", exc_info=True)
            return None

    # Initialize SocketIO with Redis as the message queue
    socketio.init_app(
        app,
        message_queue=app.config.get('REDIS_URL', 'redis://redis:6379/0'),
        manage_session=False,
        async_mode='eventlet',
        cors_allowed_origins=app.config.get('CORS_ORIGINS', '*')
    )

    # CRITICAL: Import handlers AFTER socketio.init_app() so they register on the correct instance
    from . import socket_handlers
    
    # Register blueprints, context processors, and error handlers
    init_blueprints(app)
    init_context_processors(app)
    
    logger.info("🎯 Socket.IO system initialized successfully")
    
    install_error_handlers(app)

    # Apply ProxyFix to handle reverse proxy headers.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
    
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
    logger.debug("Applied SessionPersistenceMiddleware")

    # Apply DebugMiddleware in debug mode.
    if app.debug:
        app.wsgi_app = DebugMiddleware(app.wsgi_app, app)
        logger.debug("Applied DebugMiddleware")
        
    # Register CLI commands
    from app.cli import build_assets, init_discord_roles, sync_coach_roles
    app.cli.add_command(build_assets)
    app.cli.add_command(init_discord_roles)
    app.cli.add_command(sync_coach_roles)

    # Configure session management to use Redis (skip in testing).
    if not app.config.get('TESTING'):
        app.config.update({
            'SESSION_TYPE': 'redis',
            'SESSION_REDIS': session_redis,
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

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        app.logger.error(f"Unhandled Exception: {error}", exc_info=True)
        return render_template("500.html"), 500

    @app.errorhandler(401)
    def unauthorized(error):
        logger.debug("Unauthorized access attempt")
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
        logger.debug(f"404 error for URL: {request.url}")
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
        # Create a new database session for each request (excluding static assets).
        if not request.path.startswith('/static/'):
            g.db_session = app.SessionLocal()
            
            # Register session with monitor
            session_id = str(id(g.db_session))
            from app.utils.session_monitor import get_session_monitor
            from app.utils.user_helpers import safe_current_user
            
            user_id = None
            if safe_current_user and safe_current_user.is_authenticated:
                user_id = safe_current_user.id
                
            get_session_monitor().register_session_start(session_id, request.path, user_id)
            g.session_id = session_id
            
            # Set appropriate timeouts for this session based on request type
            # This will automatically skip timeout settings when using PgBouncer
            if request.path.startswith('/admin/'):
                # Admin routes may need longer timeouts for complex operations
                set_session_timeout(g.db_session, statement_timeout_seconds=15, idle_timeout_seconds=10)
            elif request.path.startswith('/api/'):
                # API routes should be fast
                set_session_timeout(g.db_session, statement_timeout_seconds=5, idle_timeout_seconds=3)
            else:
                # Regular routes get standard timeouts
                set_session_timeout(g.db_session, statement_timeout_seconds=8, idle_timeout_seconds=5)

    @app.context_processor
    def inject_current_pub_league_season():
        """Inject the current Pub League season into every template's context."""
        # Always create a separate short-lived session for context processors
        # to avoid keeping the main request transaction open during template rendering
        session = app.SessionLocal()
        try:
            season = session.query(Season).filter_by(
                league_type='Pub League',
                is_current=True
            ).first()
            if season:
                # Trigger loading of all needed attributes before expunging
                _ = season.id, season.name, season.league_type, season.is_current
                # Expunge the object so it's no longer bound to this session
                session.expunge(season)
            # Commit and close quickly
            session.commit()
        except Exception as e:
            logger.error(f"Error fetching pub league season: {e}", exc_info=True)
            season = None
            session.rollback()
        finally:
            session.close()
        return dict(current_pub_league_season=season)

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

    # Note: teardown_request is handled by lifecycle.py to avoid duplicate cleanup
        
    @app.teardown_appcontext
    def teardown_appcontext(exception):
        # Clean up any Redis connection pools on app context teardown
        try:
            from app.utils.redis_manager import RedisManager
            redis_manager = RedisManager()
            redis_manager.shutdown()
        except Exception as e:
            # Just log errors but don't propagate them during teardown
            app.logger.error(f"Error in teardown_appcontext: {e}")
            pass
        
    # Register a function to gracefully shutdown when a worker terminates
    def worker_shutdown_cleanup():
        """
        Perform cleanup operations when a worker shuts down.
        This ensures proper resource release for Celery workers.
        """
        logger.info("Running worker shutdown cleanup")
        
        # Clean up Redis connections
        from app.utils.redis_manager import RedisManager
        redis_manager = RedisManager()
        redis_manager.shutdown()
        
        # Clean up any orphaned database sessions
        from app.db_management import db_manager
        try:
            db_manager.cleanup_orphaned_sessions()
        except Exception as e:
            logger.error(f"Error cleaning up orphaned sessions: {e}", exc_info=True)
            
    # Register the worker shutdown handler with Celery
    from app.core import celery
    celery.conf.worker_shutdown = worker_shutdown_cleanup

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
    from app.batch_api import batch_bp

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
    
    # Register cache admin routes
    from app.cache_admin_routes import cache_admin_bp
    app.register_blueprint(cache_admin_bp)

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
        
        # Get effective roles and permissions (considering impersonation)
        user_roles = get_effective_roles()
        user_permissions = get_effective_permissions()

        def has_permission(permission_name):
            return has_effective_permission(permission_name)

        def has_role(role_name):
            return has_effective_role(role_name)

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
            'is_role_impersonation_active': is_role_impersonation_active
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
                logger.debug(f"Request Path: {environ.get('PATH_INFO')}")
                logger.debug(f"Request Method: {environ.get('REQUEST_METHOD')}")
                logger.debug(f"Request Headers: {dict(request.headers)}")

                try:
                    session_data = dict(session) if session else {}
                    logger.debug(f"Session Data: {session_data}")
                    logger.debug(f"Session ID: {session.sid if hasattr(session, 'sid') else 'No session ID'}")
                except RuntimeError:
                    logger.debug("Session: Not available in current context")

                try:
                    user_info = current_user.is_authenticated
                    logger.debug(f"User authenticated: {user_info}")
                except RuntimeError:
                    logger.debug("User: Not available in current context")

                def debug_start_response(status, headers, exc_info=None):
                    logger.debug(f"Response Status: {status}")
                    logger.debug(f"Response Headers: {headers}")
                    return start_response(status, headers, exc_info)

                try:
                    response = self.wsgi_app(environ, debug_start_response)
                    return response
                except Exception as e:
                    logger.error(f"Error in request: {str(e)}", exc_info=True)
                    raise