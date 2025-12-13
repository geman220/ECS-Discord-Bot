# app/init/template_helpers.py

"""
Template Helpers

Register template filters and global functions for display formatting.
"""

import logging

logger = logging.getLogger(__name__)


def init_template_helpers(app):
    """
    Initialize template helpers for the Flask application.

    Args:
        app: The Flask application instance.
    """
    from app.utils.display_helpers import (
        format_position_name, format_field_name,
        format_datetime_pacific, format_datetime_pacific_short
    )

    @app.template_filter('format_position')
    def format_position_filter(position):
        """
        Template filter to format position names for display.
        Usage in templates: {{ player.favorite_position|format_position }}
        """
        return format_position_name(position)

    @app.template_global()
    def format_position(position):
        """
        Template global function to format position names for display.
        Usage in templates: {{ format_position('central_midfielder') }}
        """
        return format_position_name(position)

    @app.template_global()
    def format_field(field_name):
        """
        Template global function to format field names for display.
        Usage in templates: {{ format_field('favorite_position') }}
        """
        return format_field_name(field_name)

    @app.template_global()
    def format_pacific_time(utc_dt):
        """
        Template global function to format UTC datetime as Pacific Time.
        Usage in templates: {{ format_pacific_time(player.profile_last_updated) }}
        """
        return format_datetime_pacific(utc_dt)

    @app.template_global()
    def format_pacific_time_short(utc_dt):
        """
        Template global function to format UTC datetime as Pacific Time (short format).
        Usage in templates: {{ format_pacific_time_short(player.profile_last_updated) }}
        """
        return format_datetime_pacific_short(utc_dt)

    @app.template_filter('fromjson')
    def fromjson_filter(json_string):
        """
        Template filter to parse JSON strings.
        Usage in templates: {{ item.available_colors | fromjson }}
        """
        if not json_string:
            return []
        try:
            import json
            return json.loads(json_string)
        except (ValueError, TypeError, json.JSONDecodeError):
            return []

    # Register schedule display template helpers
    from app.template_helpers import register_template_helpers
    register_template_helpers(app)
