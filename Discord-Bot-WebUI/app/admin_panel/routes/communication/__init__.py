# app/admin_panel/routes/communication/__init__.py

"""
Communication Routes Package

This package contains routes for communication management:
- Communication hub (task-oriented landing page)
- Multi-channel composer (write once, send via orchestrator)
- Match RSVP posts (scheduled Discord availability embeds)
- Push notifications (views, send, admin, targeting APIs)
- Homepage announcements
- Direct messaging (SMS & Discord DM)
- Audiences (notification groups for push targeting)
- Push scheduling & history (campaigns)
- Email blasts (email campaigns)
- Email layouts (email templates)
- In-app messaging settings (DM permissions)
- Discord welcome messages (per-league bot onboarding copy)
- SMS delivery & costs
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
        composer,
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
