from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, current_user
from flask_mail import Mail
from flask_wtf.csrf import CSRFProtect
from flask_socketio import SocketIO
from flask_session import Session
from flask_cors import CORS
from web_config import Config
from app.celery import make_celery
import logging

# Initialize Flask extensions
db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
mail = Mail()
csrf = CSRFProtect()
socketio = SocketIO()
sess = Session()

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Initialize Flask extensions with the app
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    mail.init_app(app)
    csrf.init_app(app)
    socketio.init_app(app)
    sess.init_app(app)
    CORS(app)

    # Set the login view
    login_manager.login_view = 'auth.login'
    login_manager.login_message_category = 'info'

    # Set up logging
    logging.basicConfig(level=logging.DEBUG)
    app.logger.setLevel(logging.DEBUG)

    # Register Blueprints
    from app.blueprints import register_blueprints
    register_blueprints(app)

    # Initialize Celery with the Flask app
    celery = make_celery(app)

    # Context processor to inject user roles into all templates
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
            from app.models import Notification  # Import here to avoid circular import
            notifications = current_user.notifications.order_by(Notification.created_at.desc()).limit(10).all()
        return dict(notifications=notifications)

    @app.context_processor
    def inject_form():
        from app.forms import EmptyForm  # Import inside the function
        return dict(empty_form=EmptyForm())  # Use 'empty_form' to avoid conflicts

    @app.context_processor
    def inject_permissions():
        def has_permission(permission_name):
            return current_user.is_authenticated and current_user.has_permission(permission_name)
    
        return dict(has_permission=has_permission)

    return app, celery  # Return both app and celery instances