# app/admin_panel/routes/__init__.py

"""
Admin Panel Routes Package

This package contains modularized admin panel routes, broken down into logical
functional areas for better maintainability and scalability.

Module Organization:
- dashboard.py: Core dashboard, feature toggles, audit logs, system info
- communication/: Message templates, notifications, scheduled messages (modular package)
- user_management/: User approvals, roles, waitlist management (modular package)
- monitoring.py: System monitoring, task monitoring, database health
- match_operations/: Match/league/team/season management (modular package)
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

    # Communication - now a modular package
    # Old monolithic: from . import communication
    # To rollback: rename communication/ to communication_new/ and rename communication_legacy.py to communication.py
    from .communication import register_communication_routes
    register_communication_routes()

    # User management - now a modular package
    # Old monolithic: from . import user_management
    # To rollback: rename user_management/ to user_management_new/ and rename user_management_legacy.py to user_management.py
    from .user_management import register_user_management_routes
    register_user_management_routes()

    from . import roles  # New role management
    from . import monitoring

    # Match operations - now a modular package
    # Old monolithic: from . import match_operations
    # To rollback: rename match_operations/ to match_operations_new/ and rename match_operations_legacy.py to match_operations.py
    from .match_operations import register_match_operations_routes
    register_match_operations_routes()
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

    # Phase 5: League Management Hub (Centralized season/team management)
    from . import league_management

    # All routes are automatically registered when modules are imported
    # due to the @admin_panel_bp.route decorators
    pass