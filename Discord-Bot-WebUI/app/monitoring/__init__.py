# app/monitoring/__init__.py

"""
DEPRECATED 2026-03-31 — Blueprint unregistered, routes return 404.
All functionality migrated to admin_panel monitoring (app/admin_panel/routes/monitoring.py).
Safe to delete once no url_for('monitoring.*') references remain in codebase.

Original: Monitoring Package — task, queue, Redis, database, debug, worker, session monitoring.
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
