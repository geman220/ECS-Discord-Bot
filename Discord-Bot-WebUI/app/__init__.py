# app/__init__.py

import os
import logging
import logging.config
from datetime import datetime, timedelta

from flask import Flask, request, session, redirect, url_for, render_template, flash, g
from flask_login import LoginManager, current_user
from flask_mail import Mail
from flask_wtf.csrf import CSRFProtect
from flask_session import Session
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix

import redis
import time

# Import configuration and logging
from app.log_config.logging_config import LOGGING_CONFIG
from app.utils.user_helpers import safe_current_user
from app.models import User, Role
from app.utils.db_utils import transactional
from app.lifecycle import request_lifecycle

# Import Flask-Migrate
from flask_migrate import Migrate
from werkzeug.routing import BuildError
from sqlalchemy.orm import joinedload

# Initialize Flask extensions
login_manager = LoginManager()
mail = Mail()
csrf = CSRFProtect()
migrate = Migrate()  # Now Migrate is defined

logger = logging.getLogger(__name__)

# Import core extensions
from app.core import db, socketio, configure_celery

# Expose socketio at the package level
__all__ = ['create_app', 'socketio']

def create_app(config_object='web_config.Config'):
    app = Flask(__name__)
    app.config.from_object(config_object)

    # Configure logging
    logging.config.dictConfig(LOGGING_CONFIG)
    app.logger.setLevel(logging.DEBUG)
    if app.debug:
        logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)

    # Ensure SECRET_KEY is set
    if not app.config.get('SECRET_KEY'):
        raise RuntimeError('SECRET_KEY must be set')

    # Initialize Redis
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

    # Configure database settings
    from app.database.config import configure_db_settings
    configure_db_settings(app)

    # Initialize core extensions
    db.init_app(app)

    # Delegate lifecycle management to lifecycle.py
    request_lifecycle.init_app(app, db)

    # Add any custom before-request handlers (if needed)
    def custom_before_request():
        logger.debug(f"Custom logic for request: {request.path}")

    request_lifecycle.register_before_request(custom_before_request)

    # Initialize other extensions
    login_manager.init_app(app)
    csrf.init_app(app)
    mail.init_app(app)
    migrate.init_app(app, db)

    # Configure Celery
    app.celery = configure_celery(app)

    # Add Flask-Login user loader
    @login_manager.user_loader
    def load_user(user_id):
        try:
            # Fetch the user from the database
            return User.query.options(
                joinedload(User.roles).joinedload(Role.permissions),
                joinedload(User.notifications),
                joinedload(User.player)
            ).get(int(user_id))
        except Exception as e:
            logger.error(f"Error loading user {user_id}: {str(e)}", exc_info=True)
            return None

    # Initialize SocketIO
    socketio.init_app(
        app,
        message_queue=app.config.get('REDIS_URL', 'redis://redis:6379/0'),
        manage_session=False,
        async_mode='eventlet',
        cors_allowed_origins=app.config.get('CORS_ORIGINS', '*')
    )

    # Initialize blueprints
    init_blueprints(app)

    # Initialize context processors
    init_context_processors(app)

    # Install error handlers
    install_error_handlers(app)

    # Apply middlewares
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

    if app.debug:
        app.wsgi_app = DebugMiddleware(app.wsgi_app, app)
        logger.debug("Applied DebugMiddleware")

    # Session configuration
    app.config.update({
        'SESSION_TYPE': 'redis',
        'SESSION_REDIS': session_redis,
        'PERMANENT_SESSION_LIFETIME': timedelta(days=7),
        'SESSION_KEY_PREFIX': 'session:',
        'SESSION_USE_SIGNER': True
    })

    Session(app)

    # Enable CORS
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    # Initialize JWT
    from flask_jwt_extended import JWTManager
    JWTManager(app)

    # Global error handler
    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        app.logger.error(f"Unhandled Exception: {error}", exc_info=True)
        return render_template("500.html"), 500

    # Error handlers
    @app.errorhandler(401)
    def unauthorized(error):
        logger.debug("Unauthorized access attempt")
        next_url = request.path

        if not session.get('401_flash_shown'):
            flash('Please log in to access this page.', 'info')
            session['401_flash_shown'] = True

        if next_url != '/':
            session['next'] = next_url

        return redirect(url_for('auth.login'))

    @app.errorhandler(404)
    def not_found(error):
        logger.debug(f"404 error for URL: {request.url}")
        if 'redirect_count' not in session:
            session['redirect_count'] = 0

        if session['redirect_count'] > 3:  # Prevent loops
            flash("Repeated redirects detected. Check your requested URL.", "error")
            return render_template("404.html"), 404

        session['redirect_count'] += 1
        return redirect('/')

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

    return app

def init_blueprints(app):
    logger = logging.getLogger(__name__)

    # Import blueprints
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

    # Register blueprints
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
    app.register_blueprint(monitoring_bp)

def init_context_processors(app):
    @app.context_processor
    def utility_processor():
        user_roles = []
        user_permissions = []

        if safe_current_user.is_authenticated:
            try:
                # Ensure session-bound user object
                user = db.session.query(User).options(
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
    # Define custom error handlers here
    pass

class DebugMiddleware:
    def __init__(self, wsgi_app, app):
        self.wsgi_app = wsgi_app
        self.flask_app = app

    def __call__(self, environ, start_response):
        with self.flask_app.app_context():
            with self.flask_app.request_context(environ):
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