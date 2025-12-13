# app/init/database.py

"""
Database Initialization

Initialize SQLAlchemy, create session factory, and ensure required roles exist.
"""

import logging
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)


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


def _ensure_required_roles(SessionLocal):
    """
    Ensure required roles exist in the database.

    Args:
        SessionLocal: The SQLAlchemy session factory.
    """
    from app.models import Role

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
