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
from flask import Flask, request, session, redirect, url_for, render_template, flash, g
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

from app.assets import init_assets
from app.log_config.logging_config import LOGGING_CONFIG
from app.utils.user_helpers import safe_current_user
from app.models import User, Role, Season
from app.lifecycle import request_lifecycle
from app.db_management import db_manager
from app.database.config import configure_db_settings

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
    logging.config.dictConfig(LOGGING_CONFIG)
    app.logger.setLevel(logging.DEBUG)
    if app.debug:
        logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)

    # SECRET_KEY is mandatory.
    if not app.config.get('SECRET_KEY'):
        raise RuntimeError('SECRET_KEY must be set')

    # Initialize Redis clients: one for general use and one for session storage.
    redis_client = redis.from_url(
        app.config['REDIS_URL'],
        decode_responses=True,
        socket_timeout=5,
        socket_connect_timeout=5,
        socket_keepalive=True,
        health_check_interval=30,
        retry_on_timeout=True,
        max_connections=10
    )
    session_redis = redis.from_url(
        app.config['REDIS_URL'],
        decode_responses=False,
        socket_timeout=5,
        socket_connect_timeout=5,
        socket_keepalive=True,
        health_check_interval=30,
        retry_on_timeout=True,
        max_connections=10
    )
    try:
        redis_client.ping()
        session_redis.ping()
        logger.info("Redis connection successful")
    except redis.ConnectionError as e:
        logger.error(f"Redis connection failed: {str(e)}")
        raise

    app.redis = redis_client

    # Configure database settings.
    configure_db_settings(app)
    db.init_app(app)

    # Create the engine and session factory within the app context.
    with app.app_context():
        db_manager.init_app(app)
        engine = db.engine
        SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        app.SessionLocal = SessionLocal
        
        # Ensure the SUB role exists
        try:
            session = SessionLocal()
            sub_role = session.query(Role).filter_by(name='SUB').first()
            if not sub_role:
                logger.info("Creating SUB role in database")
                sub_role = Role(name='SUB', description='Substitute Player')
                session.add(sub_role)
                session.commit()
                logger.info("SUB role created successfully")
            session.close()
        except Exception as e:
            logger.error(f"Error ensuring SUB role exists: {e}", exc_info=True)

    # Initialize request lifecycle hooks.
    request_lifecycle.init_app(app, db)
    def custom_before_request():
        logger.debug(f"Custom logic for request: {request.path}")
    request_lifecycle.register_before_request(custom_before_request)

    # Initialize additional extensions.
    login_manager.init_app(app)
    csrf.init_app(app)
    mail.init_app(app)
    migrate.init_app(app, db)
    app.celery = configure_celery(app)

    from app.API.predictions import predictions_api
    csrf.exempt(predictions_api)

    @login_manager.user_loader
    def load_user(user_id):
        try:
            return User.query.options(
                joinedload(User.roles).joinedload(Role.permissions),
                joinedload(User.notifications),
                joinedload(User.player)
            ).get(int(user_id))
        except Exception as e:
            logger.error(f"Error loading user {user_id}: {str(e)}", exc_info=True)
            return None

    # Initialize SocketIO with Redis as the message queue.
    socketio.init_app(
        app,
        message_queue=app.config.get('REDIS_URL', 'redis://redis:6379/0'),
        manage_session=False,
        async_mode='eventlet',
        cors_allowed_origins=app.config.get('CORS_ORIGINS', '*')
    )

    # Register blueprints, context processors, and error handlers.
    init_blueprints(app)
    init_context_processors(app)
    install_error_handlers(app)

    # Apply ProxyFix to handle reverse proxy headers.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

    # Apply DebugMiddleware in debug mode.
    if app.debug:
        app.wsgi_app = DebugMiddleware(app.wsgi_app, app)
        logger.debug("Applied DebugMiddleware")
        
    # Register CLI commands
    from app.cli import build_assets, init_discord_roles
    app.cli.add_command(build_assets)
    app.cli.add_command(init_discord_roles)

    # Configure session management to use Redis.
    app.config.update({
        'SESSION_TYPE': 'redis',
        'SESSION_REDIS': session_redis,
        'PERMANENT_SESSION_LIFETIME': timedelta(days=7),
        'SESSION_KEY_PREFIX': 'session:',
        'SESSION_USE_SIGNER': True
    })
    Session(app)
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
        if '401_flash_shown' not in flask_session:
            flash('Please log in to access this page.', 'info')
            flask_session['401_flash_shown'] = True
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
        flash('An error occurred while redirecting. You have been returned to the home page.', 'error')
        return redirect('/')

    @app.before_request
    def before_request():
        # Create a new database session for each request (excluding static assets).
        if not request.path.startswith('/static/'):
            g.db_session = app.SessionLocal()

    @app.context_processor
    def inject_current_pub_league_season():
        """Inject the current Pub League season into every template's context."""
        # Use g.db_session instead of creating a new session
        if hasattr(g, 'db_session'):
            try:
                season = g.db_session.query(Season).filter_by(
                    league_type='Pub League',
                    is_current=True
                ).first()
            except Exception as e:
                logger.error(f"Error fetching pub league season: {e}", exc_info=True)
                season = None
            return dict(current_pub_league_season=season)
        else:
            # Only create a new session if no request context
            session = app.SessionLocal()
            try:
                season = session.query(Season).filter_by(
                    league_type='Pub League',
                    is_current=True
                ).first()
            except Exception as e:
                logger.error(f"Error fetching pub league season: {e}", exc_info=True)
                season = None
            finally:
                session.close()
            return dict(current_pub_league_season=season)

    @app.teardown_request
    def teardown_request(exception):
        from app.core.session_manager import cleanup_request
        cleanup_request(exception)
        
    @app.teardown_appcontext
    def teardown_appcontext(exception):
        # Clean up any Redis connection pools on app context teardown
        from app.utils.redis_manager import RedisManager
        redis_manager = RedisManager()
        redis_manager.shutdown()
        
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
    from app.draft import draft as draft_bp
    from app.players import players_bp
    from app.main import main as main_bp
    from app.teams import teams_bp
    from app.bot_admin import bot_admin_bp
    from app.availability_api import availability_bp
    from app.admin_routes import admin_bp
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

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(publeague_bp, url_prefix='/publeague')
    app.register_blueprint(draft_bp, url_prefix='/draft')
    app.register_blueprint(players_bp, url_prefix='/players')
    app.register_blueprint(teams_bp, url_prefix='/teams')
    app.register_blueprint(availability_bp, url_prefix='/api')
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

def init_context_processors(app):
    """
    Register context processors with the Flask application.

    Provides utilities such as safe_current_user, user roles, and permission-checking functions
    for use in templates.
    """
    @app.context_processor
    def utility_processor():
        user_roles = []
        user_permissions = []

        if safe_current_user.is_authenticated and hasattr(g, 'db_session'):
            try:
                session = g.db_session
                from app.models import User, Role
                user = session.query(User).options(
                    joinedload(User.roles).joinedload(Role.permissions)
                ).get(safe_current_user.id)
                if user:
                    user_roles = [role.name for role in user.roles]
                    user_permissions = [
                        permission.name
                        for role in user.roles
                        for permission in role.permissions
                    ]
            except Exception as e:
                logger.error(f"Error loading safe_current_user: {e}")
                user_roles = []
                user_permissions = []

        def has_permission(permission_name):
            return permission_name in user_permissions

        def is_admin():
            return 'Global Admin' in user_roles or 'Pub League Admin' in user_roles

        return {
            'safe_current_user': safe_current_user,
            'user_roles': user_roles,
            'has_permission': has_permission,
            'is_admin': is_admin
        }

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