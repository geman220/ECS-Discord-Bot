# app/admin_panel/__init__.py

"""
Admin Panel Module

This module provides a centralized admin panel for global administrators
to manage application settings, features, and configurations.
"""

from flask import Blueprint

# Create the admin panel blueprint
admin_panel_bp = Blueprint(
    'admin_panel',
    __name__,
    url_prefix='/admin-panel'
)


@admin_panel_bp.context_processor
def inject_ecs_fc_teams():
    """
    Inject ECS FC teams into all admin panel templates.
    Used for dynamic navigation in the ECS FC section.
    """
    try:
        from app.models.ecs_fc import get_ecs_fc_teams
        return {'ecs_fc_teams': get_ecs_fc_teams()}
    except Exception:
        return {'ecs_fc_teams': []}


# Import modular routes after blueprint creation to avoid circular imports
from .routes import register_all_routes

# Register all route modules
register_all_routes(admin_panel_bp)