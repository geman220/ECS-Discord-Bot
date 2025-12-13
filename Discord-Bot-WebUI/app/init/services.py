# app/init/services.py

"""
Services Initialization

Initialize application services like Firebase notifications and PII encryption.
"""

import logging
import os

logger = logging.getLogger(__name__)


def init_services(app):
    """
    Initialize application services.

    Args:
        app: The Flask application instance.
    """
    _init_notification_service(app)
    _init_pii_encryption()
    _init_worker_shutdown(app)


def _init_notification_service(app):
    """Initialize Firebase notification service."""
    from app.services.notification_service import notification_service

    service_account_path = os.path.join(app.instance_path, 'firebase-service-account.json')
    if os.path.exists(service_account_path):
        try:
            notification_service.initialize(service_account_path)
            logger.info("Firebase notification service initialized successfully")
        except Exception as e:
            logger.warning(f"Firebase service account file found but initialization failed: {e}")
    else:
        logger.warning("Firebase service account file not found at expected path")


def _init_pii_encryption():
    """Initialize PII encryption auto-update."""
    try:
        from app.utils.pii_update_wrapper import init_pii_encryption
        init_pii_encryption()
        logger.info("PII encryption auto-update initialized")
    except Exception as e:
        logger.warning(f"PII encryption initialization failed: {e}")


def _init_worker_shutdown(app):
    """Register worker shutdown cleanup handler."""
    from app.core import celery

    def worker_shutdown_cleanup():
        """
        Perform cleanup operations when a worker shuts down.
        This ensures proper resource release for Celery workers.
        """
        logger.info("Running worker shutdown cleanup")

        # Clean up Redis connections
        from app.utils.redis_manager import get_redis_manager
        redis_manager = get_redis_manager()
        redis_manager.cleanup()

        # Clean up any orphaned database sessions
        from app.db_management import db_manager
        try:
            db_manager.cleanup_orphaned_sessions()
        except Exception as e:
            logger.error(f"Error cleaning up orphaned sessions: {e}", exc_info=True)

    celery.conf.worker_shutdown = worker_shutdown_cleanup
