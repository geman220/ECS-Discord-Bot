# app/admin_panel/routes.py

"""
Admin Panel Routes

This module serves as the main entry point for admin panel routes.
All routes have been modularized into focused files for better maintainability.

Route modules:
- dashboard.py: Core dashboard, feature toggles, audit logs, system info
- communication.py: Message templates, notifications, scheduled messages  
- user_management.py: User approvals, roles, waitlist management
- monitoring.py: System monitoring, task monitoring, database health
- match_operations.py: Match/league/team/season management
- mobile_features.py: Mobile app features, wallet passes, push campaigns
- services.py: Cache management, API management, quick actions
- helpers.py: Shared utility functions and service status checks
"""

def register_all_routes(admin_panel_bp):
    """
    Register all admin panel routes with the blueprint.
    
    This function imports and registers all route modules to ensure
    they are available when the admin panel blueprint is used.
    
    Args:
        admin_panel_bp: The admin panel Flask blueprint
    """
    # Import each route module to register its routes (the @admin_panel_bp.route
    # decorators run on import). Each is imported independently so a failure in
    # one module is logged loudly but doesn't prevent the others from
    # registering — a single broken module must not take down the whole panel.
    import importlib
    import logging
    logger = logging.getLogger(__name__)

    modules = [
        'dashboard', 'communication', 'user_management', 'monitoring',
        'match_operations', 'mobile_features', 'services', 'store_management',
        'api_management', 'helpers', 'surveys',
    ]
    for name in modules:
        try:
            importlib.import_module(f'.routes.{name}', package='app.admin_panel')
        except Exception:
            logger.error("Failed to register admin_panel route module '%s'", name, exc_info=True)