# app/external_api/__init__.py

"""
External API Module for Third-Party Integrations

This package provides secure, read-only API endpoints designed for external integrations
like ChatGPT Custom GPTs, analytics tools, and other third-party services.
All endpoints require API key authentication and provide comprehensive data
about players, teams, matches, demographics, statistics, and league information.
"""

from flask import Blueprint

# Create the main blueprint
external_api_bp = Blueprint('external_api', __name__, url_prefix='/api/external/v1')

# Import all route modules to register them with the blueprint
from . import auth
from . import core_endpoints
from . import analytics
from . import serializers
from . import stats_utils
from . import help_endpoints

# Export the blueprint for registration in the main app
__all__ = ['external_api_bp']