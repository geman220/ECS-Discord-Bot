# app/__init__.py
import eventlet
eventlet.monkey_patch()
from datetime import datetime
from flask import Flask, request
from flask_jwt_extended import JWTManager
from flask_migrate import Migrate
from flask_login import LoginManager, current_user
from flask_mail import Mail
from flask_wtf.csrf import CSRFProtect
from flask_session import Session
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
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

def init_extensions(app):
    """Initialize Flask extensions"""
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message_category = 'info'
    mail.init_app(app)
    csrf.init_app(app)
    sess.init_app(app)
    
    # Initialize SocketIO with updated settings
    socketio.init_app(
        app,
        message_queue='redis://redis:6379/0',
        manage_session=False
    )
    
    # Initialize CORS and JWT after SocketIO
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
    """Initialize blueprints"""
    # Import blueprints here to avoid circular imports
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
    """Initialize context processors"""
    @app.context_processor
    def inject_roles():
        user_roles = []
        if current_user.is_authenticated:
            user_roles = [role.name for role in current_user.roles]
        return dict(user_roles=user_roles)

    @app.context_processor
    def inject_notifications():
        notifications = []
        if current_user.is_authenticated:
            from app.models import Notification
            notifications = Notification.query.filter_by(
                user_id=current_user.id
            ).order_by(
                Notification.created_at.desc()
            ).limit(10).all()
        return dict(notifications=notifications)

    @app.context_processor
    def inject_form():
        from app.forms import EmptyForm
        return dict(empty_form=EmptyForm())

    @app.context_processor
    def inject_permissions():
        def has_permission(permission_name):
            if not current_user.is_authenticated:
                return False
            return current_user.has_permission(permission_name)
        return dict(has_permission=has_permission)

    @app.context_processor
    def inject_auth_utilities():
        def has_role(role_name):
            if not current_user.is_authenticated:
                return False
            return current_user.has_role(role_name)

        def is_admin():
            if not current_user.is_authenticated:
                return False
            admin_roles = ['Global Admin', 'Pub League Admin']
            return any(role.name in admin_roles for role in current_user.roles)
            
        def is_owner(user_id):
            if not current_user.is_authenticated:
                return False
            return current_user.id == user_id

        return dict(
            has_role=has_role,
            is_admin=is_admin,
            is_owner=is_owner
        )

def create_app(config_object='web_config.Config'):
    """Create and configure Flask application instance"""
    app = Flask(__name__)
    app.config.from_object(config_object)
    
    # Configure logging
    logging.basicConfig(level=logging.DEBUG)
    app.logger.setLevel(logging.DEBUG)

    # Add ProxyFix middleware
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

    # Initialize all components
    init_extensions(app)
    init_tasks(app)
    init_blueprints(app)
    init_context_processors(app)

    @app.after_request
    def add_header(response):
        if '.js' in request.path:
            response.headers['Content-Type'] = 'application/javascript'
        return response

    # Register template filters
    @app.template_filter('datetimeformat')
    def datetimeformat(value, format='%B %d, %Y'):
        if not value:
            return value
        try:
            if isinstance(value, datetime):
                date_obj = value
            else:
                date_obj = datetime.strptime(value, '%Y-%m-%d')
            return date_obj.strftime(format)
        except (ValueError, TypeError) as e:
            app.logger.error(f"datetimeformat filter error: {e} for value: {value}")
            return value

    # Add teardown context
    @app.teardown_appcontext
    def shutdown_session(exception=None):
        """Clean up the session at the end of the request or when the application context ends."""
        if exception:
            db.session.rollback()
            logger.info(f"Request completed with exception: {str(exception)}")
        else:
            db.session.commit()
            logger.debug("Request completed successfully")
        db.session.remove()

    return app

# Create the application instance
app = create_app()