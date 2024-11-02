# app/__init__.py
import eventlet
eventlet.monkey_patch()
from datetime import datetime
from flask import Flask
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
from app.extensions import db, socketio, celery

# Initialize other extensions
migrate = Migrate()
login_manager = LoginManager()
mail = Mail()
csrf = CSRFProtect()
sess = Session()
logger = logging.getLogger(__name__)

def create_app(config_object='web_config.Config'):
    """Create and configure Flask application instance"""
    app = Flask(__name__)
    app.config.from_object(config_object)
    
    # Configure logging
    logging.basicConfig(level=logging.DEBUG)
    app.logger.setLevel(logging.DEBUG)

    # Add ProxyFix middleware
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

    # Initialize extensions
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

    # Register blueprints
    from app.blueprints import register_blueprints
    register_blueprints(app)

    # Add context processors
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
            # Using filter instead of relationship access
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
        if exception:
            db.session.rollback()
            logger.info(f"Exception occurred: {exception}. Rollback triggered.")
        db.session.remove()
        logger.info("Session closed after request.")

    return app

def init_celery(app=None):
    """Initialize Celery with Flask app context"""
    if app is None:
        from flask import current_app
        app = current_app

    class ContextTask(celery.Task):
        abstract = True
        
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask

    # Import tasks to register them with Celery
    import app.tasks.tasks_core
    import app.tasks.tasks_live_reporting
    import app.tasks.tasks_match_updates
    import app.tasks.tasks_rsvp
    import app.tasks.tasks_discord

    return celery