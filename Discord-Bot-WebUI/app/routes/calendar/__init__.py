# app/routes/calendar/__init__.py

"""
Calendar Routes Package

This package provides API endpoints for the enhanced calendar system:
- events.py: Unified event fetching (matches + league events)
- league_events.py: League event CRUD operations
- subscriptions.py: iCal subscription management
"""

from flask import Blueprint

# Create the main calendar blueprint
calendar_bp = Blueprint('calendar_api', __name__, url_prefix='/api/calendar')

# Import and register sub-blueprints
from .events import events_bp
from .league_events import league_events_bp
from .subscriptions import subscriptions_bp

calendar_bp.register_blueprint(events_bp)
calendar_bp.register_blueprint(league_events_bp)
calendar_bp.register_blueprint(subscriptions_bp)

__all__ = ['calendar_bp']
