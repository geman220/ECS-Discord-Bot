# app/admin_panel/routes/communication/__init__.py

"""
Communication Routes Package

This package contains routes for communication management:
- Communication hub with statistics
- Message template management (CRUD)
- Message category management (CRUD)
- Scheduled messages management
- Push notifications management (consolidated: views, send, admin, targeting APIs)
- Announcements management
- Direct messaging (SMS & Discord DM)
- Notification groups
- Campaigns (push notification campaigns)
- Email broadcasts (email campaigns)
- Email templates
- Messaging settings (DM permissions)
- League settings (Discord bot league config)
- SMS analytics
"""


def register_communication_routes():
    """
    Register all communication routes by importing route modules.

    This uses deferred imports to register routes with the admin_panel_bp blueprint.
    Each module contains related routes that were extracted from the original
    monolithic communication.py file.
    """
    from app.admin_panel.routes.communication import (
        hub,
        templates,
        categories,
        announcements,
        scheduled,
        push,
        notification_groups,
        campaigns,
        direct_messaging,
        messaging_settings,
        league_settings,
        sms_analytics,
        email_broadcasts,
        email_templates,
        ajax,
    )
