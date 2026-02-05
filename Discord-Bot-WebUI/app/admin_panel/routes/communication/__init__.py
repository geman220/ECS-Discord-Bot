# app/admin_panel/routes/communication/__init__.py

"""
Communication Routes Package

This package contains routes for communication management:
- Communication hub with statistics
- Message template management (CRUD)
- Message category management (CRUD)
- Scheduled messages management
- Push notifications management
- Announcements management
- Direct messaging (SMS & Discord DM)

Refactored from monolithic communication.py for better maintainability.

To rollback: Rename communication_legacy.py back to communication.py
and update the import in app/admin_panel/routes/__init__.py
"""


def register_communication_routes():
    """
    Register all communication routes by importing route modules.

    This uses deferred imports to register routes with the admin_panel_bp blueprint.
    Each module contains related routes that were extracted from the original
    monolithic communication.py file.
    """
    # Import all route modules to register them with the blueprint
    from app.admin_panel.routes.communication import (
        hub,
        templates,
        categories,
        announcements,
        scheduled,
        push,
        push_admin,
        push_enhanced,
        notification_groups,
        campaigns,
        direct_messaging,
        messaging_settings,
        league_settings,  # League-specific settings for Discord bot
        sms_analytics,  # SMS cost tracking & analytics dashboard
        email_broadcasts,  # Bulk email campaign management
        ajax,
    )
