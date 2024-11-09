# app/__init__.py
import eventlet
eventlet.monkey_patch()
from datetime import datetime
from flask import Flask, request
from flask_jwt_extended import JWTManager
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_mail import Mail
from flask_wtf.csrf import CSRFProtect
from flask_session import Session
from flask_cors import CORS
from sqlalchemy.orm import joinedload, sessionmaker , scoped_session
from werkzeug.middleware.proxy_fix import ProxyFix
from sqlalchemy.pool import QueuePool
from app.decorators import query_operation
from app.db_management import db_manager
from app.models import User, Role
from app.utils.user_helpers import safe_current_user
from app.utils.db_monitoring import db_metrics
import threading
import logging

# Import extensions
from app.extensions import db, socketio, celery, create_celery

# Initialize other extensions
migrate = Migrate()
login_manager = LoginManager()
mail = Mail()
csrf = CSRFProtect()
sess = Session()
logger = logging.getLogger(__name__)

# Configure SQLAlchemy session factory outside create_app
session_factory = None

@login_manager.user_loader
def load_user(user_id):
    with db_manager.session_scope(nested=True):
        return User.query.options(
            db.joinedload(User.roles).joinedload(Role.permissions),
            db.joinedload(User.notifications)
        ).get(int(user_id))

def init_extensions(app):
    """Initialize Flask extensions with enhanced database monitoring"""
    
    # Configure database monitoring
    app.config.setdefault('DB_SLOW_QUERY_THRESHOLD', 1.0)
    app.config.setdefault('DB_MONITOR_ENABLED', True)
    app.config.setdefault('DB_POOL_MONITORING_INTERVAL', 300)
    
    # Register database monitoring and cleanup
    @app.before_request
    def cleanup_db_connections():
        """Combined cleanup for metrics and connections"""
        db_metrics.cleanup_old_data()
        db_manager.check_for_leaked_connections()
        db_manager.terminate_idle_transactions()
        db_manager.monitor_celery_connections()
    
    # Add database metrics endpoint
    @app.route('/metrics/db')
    def db_metrics_endpoint():
        if not current_app.config['DB_MONITOR_ENABLED']:
            return {'status': 'disabled'}, 404
        return {
            'metrics': db_metrics.get_metrics(),
            'pool_stats': db_manager.get_pool_stats()
        }
    
    # Initialize other extensions as before
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message_category = 'info'
    mail.init_app(app)
    csrf.init_app(app)
    sess.init_app(app)

    socketio.init_app(
        app,
        message_queue='redis://redis:6379/0',
        manage_session=False
    )
    
    CORS(app, resources={r"/api/*": {"origins": "*"}})
    JWTManager(app)

def init_tasks(app):
    """Initialize Celery tasks"""
    app.celery = create_celery(app)
    # Import tasks to register them with Celery
    with app.app_context():
        import app.tasks.tasks_core
        import app.tasks.tasks_live_reporting
        import app.tasks.tasks_match_updates
        import app.tasks.tasks_rsvp
        import app.tasks.tasks_discord

def init_blueprints(app):
    """Initialize blueprints with endpoint logging for debugging."""
    logger = logging.getLogger(__name__)
    registered = set()  # Track registered blueprints

    # Import blueprints to avoid circular imports
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

    def register_blueprint(bp, url_prefix=None):
        """Helper to safely register a blueprint with endpoint logging."""
        bp_id = f"{bp.name}:{id(bp)}"
        if bp_id in registered:
            logger.warning(f"Blueprint {bp.name} already registered")
            return
        
        try:
            app.register_blueprint(bp, url_prefix=url_prefix)
            registered.add(bp_id)
            logger.debug(f"Registered blueprint: {bp.name} with URL prefix: {url_prefix}")
            
            # Log all endpoints in the blueprint to debug duplicates
            for rule in app.url_map.iter_rules():
                if rule.endpoint.startswith(bp.name):
                    logger.debug(f"Blueprint '{bp.name}' - Registered endpoint: '{rule.endpoint}' with rule: '{rule}'")

        except Exception as e:
            logger.error(f"Failed to register blueprint {bp.name}: {str(e)}")
            raise

    # Define blueprints and their prefixes
    blueprint_configs = [
        (auth_bp, '/auth'),
        (publeague_bp, '/publeague'),
        (draft_bp, '/draft'),
        (players_bp, '/players'),
        (teams_bp, '/teams'),
        (availability_bp, '/api'),
        (account_bp, '/account'),
        (match_pages, None),
        (bot_admin_bp, None),
        (main_bp, None),
        (admin_bp, None),
        (feedback_bp, None),
        (email_bp, None),
        (calendar_bp, None),
        (sms_rsvp_bp, None),
        (match_api, '/api'),
        (user_management_bp, None),
        (mobile_api, '/api/v1'),
        (monitoring_bp, None)
    ]

    # Register each blueprint
    for bp, url_prefix in blueprint_configs:
        register_blueprint(bp, url_prefix)

def init_context_processors(app):
    """Initialize context processors with coordinated session handling"""
    @app.context_processor
    @query_operation
    def inject_roles():
        user_roles = []
        user = safe_current_user  # Use safe_current_user here
        if user:
            user_roles = [role.name for role in user.roles]
        return dict(user_roles=user_roles, safe_current_user=user)

    @app.context_processor
    def inject_notifications():
        notifications = []
        if safe_current_user.is_authenticated:
            from app.models import Notification
            notifications = Notification.query.filter_by(
                user_id=safe_current_user.id
            ).order_by(
                Notification.created_at.desc()
            ).limit(10).all()
        return dict(notifications=notifications)

    @app.context_processor
    def inject_safe_user():
        return dict(safe_current_user=safe_current_user)

    @app.context_processor
    def inject_form():
        from app.forms import EmptyForm
        return dict(empty_form=EmptyForm())

    @app.context_processor
    def inject_permissions():
        def has_permission(permission_name):
            if not safe_current_user.is_authenticated:
                return False
            return safe_current_user.has_permission(permission_name)
        return dict(has_permission=has_permission)

    @app.context_processor
    def inject_auth_utilities():
        def has_role(role_name):
            if not safe_current_user.is_authenticated:
                return False
            return safe_current_user.has_role(role_name)

        def is_admin():
            if not safe_current_user.is_authenticated:
                return False
            admin_roles = ['Global Admin', 'Pub League Admin']
            return any(role.name in admin_roles for role in safe_current_user.roles)
            
        def is_owner(user_id):
            if not safe_current_user.is_authenticated:
                return False
            return safe_current_user.id == user_id

        return dict(
            has_role=has_role,
            is_admin=is_admin,
            is_owner=is_owner
        )

def create_app(config_object='web_config.Config'):
    """Create and configure Flask application instance"""
    app = Flask(__name__)
    app.config.from_object(config_object)
    
    # Configure logging first
    logging.basicConfig(level=logging.DEBUG)
    app.logger.setLevel(logging.DEBUG)

    # Add ProxyFix middleware
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

    # Configure SQLAlchemy engine options
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_size': app.config.get('SQLALCHEMY_POOL_SIZE', 5),
        'max_overflow': app.config.get('SQLALCHEMY_MAX_OVERFLOW', 10),
        'pool_timeout': app.config.get('SQLALCHEMY_POOL_TIMEOUT', 20),
        'pool_recycle': app.config.get('SQLALCHEMY_POOL_RECYCLE', 300),
        'pool_pre_ping': True,
        'pool_use_lifo': True,
        'pool_reset_on_return': 'rollback',
        'echo_pool': app.config.get('SQLALCHEMY_ECHO_POOL', False),
        'poolclass': QueuePool,
        'connect_args': {
            'connect_timeout': 10,
            'application_name': f"{app.name}_app",
            'options': '-c statement_timeout=15000 -c idle_in_transaction_session_timeout=30000'
        }
    }

    # Initialize extensions
    db.init_app(app)
    
    # Initialize non-db extensions
    mail.init_app(app)
    csrf.init_app(app)
    sess.init_app(app)

    with app.app_context():
        # Initialize the database manager
        db_manager.init_app(app)
        
        # Create global session factory
        global session_factory
        session_factory = sessionmaker(
            bind=db.engine,
            autocommit=False,
            autoflush=False
        )
        
        # Configure scoped session
        db.session = scoped_session(session_factory)
        
        # Initialize remaining database-dependent components
        migrate.init_app(app, db)
        
        # Initialize login manager
        login_manager.init_app(app)
        login_manager.login_view = 'auth.login'
        login_manager.login_message_category = 'info'
        
        # Initialize remaining components
        init_extensions(app)
        init_blueprints(app)
        init_tasks(app)
        init_context_processors(app)
    
    # Initialize network-related extensions last
    socketio.init_app(
        app,
        message_queue='redis://redis:6379/0',
        manage_session=False
    )
    
    CORS(app, resources={r"/api/*": {"origins": "*"}})
    JWTManager(app)
        
    return app