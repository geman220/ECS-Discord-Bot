# app/admin_panel/routes/user_management/__init__.py

"""
User Management Routes Package

This package splits the monolithic user_management.py into focused modules:
- approvals.py - User approval workflow
- roles.py - Role management and assignment
- waitlist.py - Waitlist management
- bulk_operations.py - Bulk user operations
- analytics.py - User analytics and export
- comprehensive.py - Comprehensive user management
- duplicates.py - Duplicate detection and merging
- helpers.py - Shared helper functions
"""


def register_user_management_routes():
    """
    Register all user management routes.

    This function imports all route modules, which registers them
    with the admin_panel_bp blueprint via decorators.
    """
    from app.admin_panel.routes.user_management import (
        approvals,
        roles,
        waitlist,
        bulk_operations,
        analytics,
        comprehensive,
        duplicates,
    )
