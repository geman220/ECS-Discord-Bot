# app/admin_panel/routes/__init__.py

"""
Admin Panel Routes Package

This package contains modularized admin panel routes, broken down into logical
functional areas for better maintainability and scalability.

Module Organization:
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
    from . import dashboard
    from . import communication
    from . import user_management
    from . import roles  # New role management
    from . import monitoring
    from . import match_operations
    from . import mobile_features
    from . import services
    from . import store_management
    from . import api_management
    from . import helpers

    # Phase 1: System Infrastructure (Health, Redis, Docker)
    from . import system_infrastructure

    # Phase 2: Discord & MLS Management
    from . import discord_management
    from . import mls_management

    # Phase 3: Reports & Feedback
    from . import reports_feedback

    # Phase 4: Draft Management
    from . import draft_management

    # All routes are automatically registered when modules are imported
    # due to the @admin_panel_bp.route decorators
    pass