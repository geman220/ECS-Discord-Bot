# app/monitoring/__init__.py

"""
Monitoring Package

This package provides endpoints and utilities for application monitoring, including:
- Task monitoring (Celery tasks, scheduled tasks)
- Queue monitoring (queue lengths, health status)
- Redis monitoring (key inspection, connection testing)
- Database monitoring (connections, stats, cleanup)
- Debug utilities (logs, queries, system stats)
- Worker monitoring (Celery workers info)
- Session monitoring (active sessions, cleanup)

All endpoints require Global Admin role unless otherwise specified.
"""

from flask import Blueprint

# Create main monitoring blueprint with /monitoring prefix
monitoring_bp = Blueprint('monitoring', __name__, url_prefix='/monitoring')


def register_monitoring_routes():
    """
    Register all monitoring route modules with the blueprint.
    Routes are imported here to register them with the blueprint.
    """
    from app.monitoring import (
        tasks,
        queues,
        redis_monitor,
        database,
        debug,
        workers,
        sessions,
    )


def init_monitoring(app):
    """
    Initialize the monitoring blueprint with the Flask app.

    Args:
        app: Flask application instance
    """
    # Register all routes
    register_monitoring_routes()

    # Register blueprint
    app.register_blueprint(monitoring_bp)
