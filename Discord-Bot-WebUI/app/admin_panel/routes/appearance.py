# app/admin_panel/routes/appearance.py

"""
Appearance Management Routes

Admin panel routes for customizing the application's visual appearance,
including color palette customization for both light and dark modes.
"""

import json
import os
from flask import (
    render_template, request, jsonify, flash, redirect, url_for,
    current_app, g
)
from flask_login import login_required, current_user
from app.admin_panel import admin_panel_bp
from app.decorators import role_required

# Default theme colors (Professional Edition - from theme-variables.css)
DEFAULT_COLORS = {
    "light": {
        "primary": "#7C3AED",
        "primary_light": "#8B5CF6",
        "primary_dark": "#6D28D9",
        "secondary": "#64748B",
        "accent": "#F59E0B",
        "success": "#10B981",
        "warning": "#F59E0B",
        "danger": "#EF4444",
        "info": "#3B82F6",
        "text_heading": "#18181B",
        "text_body": "#52525B",
        "text_muted": "#71717A",
        "text_link": "#7C3AED",
        "bg_body": "#FAFAFA",
        "bg_card": "#FFFFFF",
        "bg_input": "#FFFFFF",
        "border": "#E4E4E7",
        "border_input": "#D4D4D8"
    },
    "dark": {
        "primary": "#A78BFA",
        "primary_light": "#C4B5FD",
        "primary_dark": "#8B5CF6",
        "secondary": "#94A3B8",
        "accent": "#FBBF24",
        "success": "#34D399",
        "warning": "#FBBF24",
        "danger": "#F87171",
        "info": "#60A5FA",
        "text_heading": "#FAFAFA",
        "text_body": "#A1A1AA",
        "text_muted": "#71717A",
        "text_link": "#A78BFA",
        "bg_body": "#09090B",
        "bg_card": "#18181B",
        "bg_input": "#27272A",
        "bg_sidebar": "#09090B",
        "border": "#3F3F46",
        "border_input": "#3F3F46"
    }
}

# Path to store custom colors (in instance folder)
def get_colors_file_path():
    """Get the path to the custom colors JSON file."""
    instance_path = current_app.instance_path
    os.makedirs(instance_path, exist_ok=True)
    return os.path.join(instance_path, 'theme_colors.json')


def load_custom_colors():
    """Load custom colors from file, or return None if not set."""
    try:
        file_path = get_colors_file_path()
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                return json.load(f)
    except Exception as e:
        current_app.logger.error(f"Error loading custom colors: {e}")
    return None


def save_custom_colors(colors):
    """Save custom colors to file."""
    try:
        file_path = get_colors_file_path()
        with open(file_path, 'w') as f:
            json.dump(colors, f, indent=2)
        return True
    except Exception as e:
        current_app.logger.error(f"Error saving custom colors: {e}")
        return False


@admin_panel_bp.route('/appearance')
@login_required
@role_required(['Global Admin'])
def appearance():
    """
    Display the appearance customization page.
    Allows admins to customize the color palette.
    """
    custom_colors = load_custom_colors()
    colors = custom_colors if custom_colors else DEFAULT_COLORS

    return render_template(
        'admin_panel/appearance.html',
        colors=colors,
        default_colors=DEFAULT_COLORS,
        has_custom_colors=custom_colors is not None
    )


@admin_panel_bp.route('/appearance/save-colors', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def save_colors():
    """
    Save custom color preferences.
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "message": "No data provided"}), 400

        # Validate structure
        if 'light' not in data or 'dark' not in data:
            return jsonify({"success": False, "message": "Invalid color structure"}), 400

        # Save colors
        if save_custom_colors(data):
            return jsonify({
                "success": True,
                "message": "Colors saved successfully. Refresh the page to see changes."
            })
        else:
            return jsonify({"success": False, "message": "Failed to save colors"}), 500

    except Exception as e:
        current_app.logger.error(f"Error saving colors: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@admin_panel_bp.route('/appearance/reset-colors', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def reset_colors():
    """
    Reset colors to default values.
    """
    try:
        file_path = get_colors_file_path()
        if os.path.exists(file_path):
            os.remove(file_path)

        return jsonify({
            "success": True,
            "message": "Colors reset to defaults. Refresh the page to see changes.",
            "colors": DEFAULT_COLORS
        })

    except Exception as e:
        current_app.logger.error(f"Error resetting colors: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@admin_panel_bp.route('/appearance/export-colors')
@login_required
@role_required(['Global Admin'])
def export_colors():
    """
    Export current color scheme as JSON.
    """
    custom_colors = load_custom_colors()
    colors = custom_colors if custom_colors else DEFAULT_COLORS

    return jsonify({
        "success": True,
        "colors": colors,
        "is_custom": custom_colors is not None
    })


@admin_panel_bp.route('/appearance/import-colors', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def import_colors():
    """
    Import color scheme from JSON.
    """
    try:
        data = request.get_json()
        if not data or 'colors' not in data:
            return jsonify({"success": False, "message": "No colors provided"}), 400

        colors = data['colors']

        # Validate structure
        if 'light' not in colors or 'dark' not in colors:
            return jsonify({"success": False, "message": "Invalid color structure"}), 400

        if save_custom_colors(colors):
            return jsonify({
                "success": True,
                "message": "Colors imported successfully. Refresh the page to see changes."
            })
        else:
            return jsonify({"success": False, "message": "Failed to import colors"}), 500

    except Exception as e:
        current_app.logger.error(f"Error importing colors: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


# Helper function for templates to get custom colors
def get_site_theme_colors():
    """
    Get the current theme colors for use in templates.
    Returns custom colors if set, otherwise returns None.
    """
    return load_custom_colors()
