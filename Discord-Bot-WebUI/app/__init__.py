from datetime import datetime
from flask import Flask
from flask_jwt_extended import JWTManager
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, current_user
from flask_mail import Mail
from flask_wtf.csrf import CSRFProtect
from flask_socketio import SocketIO
from flask_session import Session
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
from web_config import Config
from app.celery import make_celery
from app.sql_log import * 
import logging

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

    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    mail.init_app(app)
    csrf.init_app(app)
    socketio.init_app(app)
    #sess.init_app(app)
    CORS(app, resources={r"/api/*": {"origins": "*"}})
    jwt = JWTManager(app)

    login_manager.login_view = 'auth.login'
    login_manager.login_message_category = 'info'

    logging.basicConfig(level=logging.DEBUG)
    app.logger.setLevel(logging.DEBUG)

    from app.blueprints import register_blueprints
    register_blueprints(app)

    celery = make_celery(app)

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
            notifications = current_user.notifications.order_by(Notification.created_at.desc()).limit(10).all()
        return dict(notifications=notifications)

    @app.context_processor
    def inject_form():
        from app.forms import EmptyForm
        return dict(empty_form=EmptyForm())

    @app.context_processor
    def inject_permissions():
        def has_permission(permission_name):
            return current_user.is_authenticated and current_user.has_permission(permission_name)
    
        return dict(has_permission=has_permission)

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

    @app.teardown_appcontext
    def shutdown_session(exception=None):
        if exception:
            db.session.rollback()
            logger.info(f"Exception occurred: {exception}. Rollback triggered.")
        db.session.remove()
        logger.info("Session closed after request.")

    return app, celery