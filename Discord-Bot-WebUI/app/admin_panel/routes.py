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
    # Import all route modules to register their routes
    from .routes import dashboard
    from .routes import communication  
    from .routes import user_management
    from .routes import monitoring
    from .routes import match_operations
    from .routes import mobile_features
    from .routes import services
    from .routes import store_management
    from .routes import api_management
    from .routes import helpers
    
    # All routes are automatically registered when modules are imported
    # due to the @admin_panel_bp.route decorators
    pass