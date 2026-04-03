# app/mobile_api/__init__.py

"""
Mobile API Package

This package provides RESTful API endpoints for mobile clients, organized by domain:
- auth: Authentication and Discord OAuth
- matches: Match data and events
- teams: Team information and statistics
- players: Player profiles and stats
- rsvp: Availability and RSVP management
- schedule: Match scheduling
- notifications: Push notification management
- utils: Health checks and debugging
- ispy: ISpy game endpoints
- wallet: Membership pass endpoints
- draft: Draft system for coaches
- store: League store ordering
- match_reporting: Match event reporting for coaches
- referees: Referee management for admins
- account: Account settings, 2FA, and profile picture upload
- leagues: Season and league information
- coach_rsvp: Coach RSVP dashboard for team management
- substitutes: Substitute request and pool management
- calendar: Calendar events (matches + league events)
- admin: Admin role and league management
- messages: Direct messaging between users
- ecs_fc_matches: ECS FC match details and RSVP management
- stats: League-separated statistics and leaderboards
- pitch_view: Unified pitch view for draft and match lineups
- quick_profiles: Quick profiles for tryout players (claim codes)
- feedback: Feedback submission and management
- app_config: App version/update configuration (unauthenticated)

All endpoints are CSRF-exempt and use JWT authentication where required.
"""

from flask import Blueprint

# Create main mobile API blueprint with /api/v1 prefix
# This will eventually replace app/app_api.py
mobile_api_v2 = Blueprint('mobile_api_v2', __name__, url_prefix='/api/v1')

# Module-level flag to prevent re-registering middleware/routes on the singleton
# blueprint when create_app() is called multiple times (e.g. Celery workers).
# Set BEFORE any @blueprint.before_request calls to close re-entrancy windows.
_setup_done = False


def register_mobile_api_routes():
    """
    Register all mobile API route modules with the blueprint.
    Routes are imported here to register them with the blueprint.
    """
    # Import route modules to register their routes with mobile_api_v2
    from app.mobile_api import (
        auth,
        matches,
        teams,
        players,
        rsvp,
        schedule,
        notifications,
        utils,
        ispy,
        wallet,
        draft,
        store,
        match_reporting,
        referees,
        account,
        leagues,
        coach_rsvp,
        substitutes,
        calendar,
        admin,
        messages,
        ecs_fc_matches,
        stats,
        pitch_view,
        quick_profiles,
        feedback,
        app_config,
        telemetry,
    )


def init_mobile_api(app, csrf):
    """
    Initialize the mobile API blueprint with the Flask app.

    Args:
        app: Flask application instance
        csrf: Flask-WTF CSRF protection instance
    """
    global _setup_done
    if not _setup_done:
        _setup_done = True  # Set BEFORE setup calls — prevents re-entry
        csrf.exempt(mobile_api_v2)
        from app.mobile_api.middleware import register_api_middleware
        register_api_middleware(mobile_api_v2)
        register_mobile_api_routes()

    if 'mobile_api_v2' not in app.blueprints:
        app.register_blueprint(mobile_api_v2)
