# app/init/database.py

"""
Database Initialization

Initialize SQLAlchemy, create session factory, and ensure required roles exist.
"""

import logging
import time

from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)

# Startup tasks (role/preset bootstrap) tolerate a brief pgbouncer DNS race —
# during a deploy, the webui container can come up just before docker DNS has
# the pgbouncer hostname ready. A couple of short retries usually clears it.
_STARTUP_DB_RETRIES = 3
_STARTUP_DB_RETRY_DELAY = 2  # seconds


def init_database(app, db):
    """
    Initialize database for the Flask application.

    Args:
        app: The Flask application instance.
        db: The SQLAlchemy db instance.
    """
    from app.database.config import configure_db_settings
    from app.db_management import db_manager
    from app.models import Role
    from app.core.session_manager import cleanup_request

    # Register database session cleanup
    app.teardown_appcontext(cleanup_request)

    # Configure database settings
    configure_db_settings(app)
    db.init_app(app)

    # Create the engine and session factory within the app context
    with app.app_context():
        db_manager.init_app(app)
        engine = db.engine
        SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        app.SessionLocal = SessionLocal

        # Import ECS FC models to ensure they are registered
        from app.models_ecs import EcsFcMatch, EcsFcAvailability
        from app.models_ecs_subs import EcsFcSubRequest, EcsFcSubResponse, EcsFcSubAssignment, EcsFcSubPool

        # Ensure the pl-unverified and pl-waitlist roles exist
        _ensure_required_roles(SessionLocal)

        # Initialize/update system theme presets
        _ensure_system_presets(db)


def _log_startup_db_failure(stage: str, exc: Exception) -> None:
    """Log a startup-time DB failure, downgrading transient disconnects to WARNING."""
    from app.core.session_manager import is_transient_db_disconnect
    if is_transient_db_disconnect(exc):
        logger.warning(
            f"{stage}: transient DB disconnect ({exc.__class__.__name__}) — "
            f"app will continue and recover on next request"
        )
    else:
        logger.error(f"{stage}: {exc}", exc_info=True)


def _ensure_system_presets(db):
    """Ensure system theme presets exist and are up-to-date."""
    from sqlalchemy import inspect
    from app.core.session_manager import is_transient_db_disconnect
    from app.models.theme_preset import ThemePreset

    last_exc = None
    for attempt in range(_STARTUP_DB_RETRIES):
        try:
            inspector = inspect(db.engine)
            if not inspector.has_table('theme_presets'):
                logger.warning("theme_presets table does not exist yet, skipping preset initialization")
                return
            ThemePreset.initialize_system_presets()
            return
        except Exception as e:
            last_exc = e
            if is_transient_db_disconnect(e) and attempt < _STARTUP_DB_RETRIES - 1:
                time.sleep(_STARTUP_DB_RETRY_DELAY)
                continue
            break

    _log_startup_db_failure("Error initializing theme presets", last_exc)


def _ensure_required_roles(SessionLocal):
    """
    Ensure required roles exist in the database.

    Args:
        SessionLocal: The SQLAlchemy session factory.
    """
    from sqlalchemy import inspect
    from app.core.session_manager import is_transient_db_disconnect
    from app.models import Role

    last_exc = None
    for attempt in range(_STARTUP_DB_RETRIES):
        session = SessionLocal()
        try:
            inspector = inspect(session.bind)
            if not inspector.has_table('roles'):
                logger.warning("Roles table does not exist yet, skipping role initialization")
                return

            sub_role = session.query(Role).filter_by(name='pl-unverified').first()
            if not sub_role:
                logger.info("Creating pl-unverified role in database")
                sub_role = Role(name='pl-unverified', description='Substitute Player')
                session.add(sub_role)
                logger.info("pl-unverified role created successfully")

            waitlist_role = session.query(Role).filter_by(name='pl-waitlist').first()
            if not waitlist_role:
                logger.info("Creating pl-waitlist role in database")
                waitlist_role = Role(name='pl-waitlist', description='Player on waitlist for current season')
                session.add(waitlist_role)
                logger.info("pl-waitlist role created successfully")

            session.commit()
            return
        except Exception as e:
            last_exc = e
            try:
                session.rollback()
            except Exception:
                pass
            if is_transient_db_disconnect(e) and attempt < _STARTUP_DB_RETRIES - 1:
                time.sleep(_STARTUP_DB_RETRY_DELAY)
                continue
            break
        finally:
            session.close()

    _log_startup_db_failure("Failed to initialize roles", last_exc)
