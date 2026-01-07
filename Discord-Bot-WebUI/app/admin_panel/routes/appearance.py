# app/admin_panel/routes/appearance.py

"""
Appearance Management Routes

Admin panel routes for customizing the application's visual appearance,
including comprehensive design token management:
- Colors (light/dark modes)
- Typography (fonts, scale)
- Spacing (scale multipliers)
- Components (border radius, shadows)
- Animations (enabled, speed)
- Theme variants (modern, modern-v2)
"""

import json
import os
from flask import (
    render_template, request, jsonify, flash, redirect, url_for,
    current_app, g, send_file
)
from flask_login import login_required, current_user
from app.admin_panel import admin_panel_bp
from app.decorators import role_required
from typing import Dict, Any, Optional

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
        "primary": "#60A5FA",
        "primary_light": "#93C5FD",
        "primary_dark": "#3B82F6",
        "secondary": "#94A3B8",
        "accent": "#FBBF24",
        "success": "#34D399",
        "warning": "#FBBF24",
        "danger": "#F87171",
        "info": "#60A5FA",
        "text_heading": "#F8FAFC",
        "text_body": "#CBD5E1",
        "text_muted": "#94A3B8",
        "text_link": "#60A5FA",
        "bg_body": "#0F172A",
        "bg_card": "#1E293B",
        "bg_input": "#334155",
        "bg_sidebar": "#0F172A",
        "border": "#475569",
        "border_input": "#475569"
    }
}

# Default design tokens (full system)
DEFAULT_DESIGN_TOKENS = {
    "theme_variant": "modern",
    "colors": DEFAULT_COLORS,
    "typography": {
        "display_font": "Inter",
        "body_font": "Inter",
        "mono_font": "JetBrains Mono",
        "scale_multiplier": 1.0
    },
    "spacing": {
        "scale_multiplier": 1.0
    },
    "components": {
        "border_radius": "default",  # "sharp", "default", "rounded"
        "shadow_intensity": "default"  # "none", "subtle", "default", "strong"
    },
    "animations": {
        "enabled": True,
        "speed": "default"  # "slow", "default", "fast"
    }
}

# ============================================================================
# File Path Management
# ============================================================================

def get_colors_file_path():
    """Get the path to the custom colors JSON file (LEGACY)."""
    instance_path = current_app.instance_path
    os.makedirs(instance_path, exist_ok=True)
    return os.path.join(instance_path, 'theme_colors.json')


def get_design_tokens_file_path():
    """Get the path to the design tokens JSON file."""
    instance_path = current_app.instance_path
    os.makedirs(instance_path, exist_ok=True)
    return os.path.join(instance_path, 'design_tokens.json')


# ============================================================================
# Design Token Management
# ============================================================================

def load_design_tokens() -> Optional[Dict[str, Any]]:
    """
    Load design tokens from file with migration support.

    Priority:
    1. design_tokens.json (new format)
    2. theme_colors.json (legacy format - auto-migrate)
    3. None (use defaults)
    """
    try:
        # Try new format first
        tokens_path = get_design_tokens_file_path()
        if os.path.exists(tokens_path):
            with open(tokens_path, 'r') as f:
                tokens = json.load(f)
                # Validate structure
                if validate_design_tokens(tokens):
                    return tokens
                else:
                    current_app.logger.warning("Invalid design tokens structure, using defaults")
                    return None

        # Try legacy format and migrate
        colors_path = get_colors_file_path()
        if os.path.exists(colors_path):
            with open(colors_path, 'r') as f:
                colors = json.load(f)
                # Migrate to new format
                tokens = migrate_colors_to_tokens(colors)
                # Save migrated format
                save_design_tokens(tokens)
                current_app.logger.info("Migrated theme_colors.json to design_tokens.json")
                return tokens

    except Exception as e:
        current_app.logger.error(f"Error loading design tokens: {e}")

    return None


def save_design_tokens(tokens: Dict[str, Any]) -> bool:
    """Save design tokens to file."""
    try:
        file_path = get_design_tokens_file_path()
        with open(file_path, 'w') as f:
            json.dump(tokens, f, indent=2)
        return True
    except Exception as e:
        current_app.logger.error(f"Error saving design tokens: {e}")
        return False


def validate_design_tokens(tokens: Dict[str, Any]) -> bool:
    """Validate design tokens structure."""
    if not isinstance(tokens, dict):
        return False

    # Check required top-level keys
    required_keys = ['colors', 'typography', 'spacing', 'components', 'animations']
    for key in required_keys:
        if key not in tokens:
            return False

    # Validate colors structure
    if 'light' not in tokens['colors'] or 'dark' not in tokens['colors']:
        return False

    return True


def migrate_colors_to_tokens(colors: Dict[str, Any]) -> Dict[str, Any]:
    """Migrate legacy theme_colors.json to design_tokens.json format."""
    tokens = DEFAULT_DESIGN_TOKENS.copy()
    tokens['colors'] = colors
    return tokens


# ============================================================================
# Legacy Support Functions (for backward compatibility)
# ============================================================================

def load_custom_colors() -> Optional[Dict[str, Any]]:
    """
    Load custom colors from file, or return None if not set.

    This function maintains backward compatibility by returning just the colors
    from the design tokens system.
    """
    tokens = load_design_tokens()
    return tokens['colors'] if tokens else None


def save_custom_colors(colors: Dict[str, Any]) -> bool:
    """
    Save custom colors to file.

    This function maintains backward compatibility by updating only the colors
    in the design tokens system.
    """
    tokens = load_design_tokens()
    if tokens is None:
        tokens = DEFAULT_DESIGN_TOKENS.copy()

    tokens['colors'] = colors
    return save_design_tokens(tokens)


# ============================================================================
# Main Routes
# ============================================================================

@admin_panel_bp.route('/appearance')
@login_required
@role_required(['Global Admin'])
def appearance():
    """
    Display the appearance customization page.
    Allows admins to customize the color palette (legacy support).
    """
    custom_colors = load_custom_colors()
    colors = custom_colors if custom_colors else DEFAULT_COLORS

    # Load full tokens for context
    tokens = load_design_tokens()
    has_custom_tokens = tokens is not None

    return render_template(
        'admin_panel/appearance.html',
        colors=colors,
        default_colors=DEFAULT_COLORS,
        has_custom_colors=custom_colors is not None,
        design_tokens=tokens if tokens else DEFAULT_DESIGN_TOKENS,
        has_custom_tokens=has_custom_tokens
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


# ============================================================================
# Typography Routes
# ============================================================================

@admin_panel_bp.route('/appearance/typography')
@login_required
@role_required(['Global Admin'])
def typography():
    """Display typography settings page."""
    tokens = load_design_tokens()
    current_typography = tokens['typography'] if tokens else DEFAULT_DESIGN_TOKENS['typography']

    return render_template(
        'admin_panel/appearance_typography.html',
        typography=current_typography,
        default_typography=DEFAULT_DESIGN_TOKENS['typography']
    )


@admin_panel_bp.route('/appearance/save-typography', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def save_typography():
    """Save typography settings."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "message": "No data provided"}), 400

        # Validate typography data
        required_keys = ['display_font', 'body_font', 'mono_font', 'scale_multiplier']
        for key in required_keys:
            if key not in data:
                return jsonify({"success": False, "message": f"Missing required field: {key}"}), 400

        # Validate scale multiplier
        scale = float(data['scale_multiplier'])
        if scale < 0.5 or scale > 2.0:
            return jsonify({"success": False, "message": "Scale multiplier must be between 0.5 and 2.0"}), 400

        # Load current tokens
        tokens = load_design_tokens()
        if tokens is None:
            tokens = DEFAULT_DESIGN_TOKENS.copy()

        # Update typography
        tokens['typography'] = {
            'display_font': data['display_font'],
            'body_font': data['body_font'],
            'mono_font': data['mono_font'],
            'scale_multiplier': scale
        }

        # Save tokens
        if save_design_tokens(tokens):
            return jsonify({
                "success": True,
                "message": "Typography settings saved successfully. Refresh to see changes."
            })
        else:
            return jsonify({"success": False, "message": "Failed to save typography settings"}), 500

    except Exception as e:
        current_app.logger.error(f"Error saving typography: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


# ============================================================================
# Spacing Routes
# ============================================================================

@admin_panel_bp.route('/appearance/spacing')
@login_required
@role_required(['Global Admin'])
def spacing():
    """Display spacing settings page."""
    tokens = load_design_tokens()
    current_spacing = tokens['spacing'] if tokens else DEFAULT_DESIGN_TOKENS['spacing']

    return render_template(
        'admin_panel/appearance_spacing.html',
        spacing=current_spacing,
        default_spacing=DEFAULT_DESIGN_TOKENS['spacing']
    )


@admin_panel_bp.route('/appearance/save-spacing', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def save_spacing():
    """Save spacing settings."""
    try:
        data = request.get_json()
        if not data or 'scale_multiplier' not in data:
            return jsonify({"success": False, "message": "No scale multiplier provided"}), 400

        # Validate scale multiplier
        scale = float(data['scale_multiplier'])
        if scale < 0.5 or scale > 2.0:
            return jsonify({"success": False, "message": "Scale multiplier must be between 0.5 and 2.0"}), 400

        # Load current tokens
        tokens = load_design_tokens()
        if tokens is None:
            tokens = DEFAULT_DESIGN_TOKENS.copy()

        # Update spacing
        tokens['spacing'] = {'scale_multiplier': scale}

        # Save tokens
        if save_design_tokens(tokens):
            return jsonify({
                "success": True,
                "message": "Spacing settings saved successfully. Refresh to see changes."
            })
        else:
            return jsonify({"success": False, "message": "Failed to save spacing settings"}), 500

    except Exception as e:
        current_app.logger.error(f"Error saving spacing: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


# ============================================================================
# Component Routes
# ============================================================================

@admin_panel_bp.route('/appearance/components')
@login_required
@role_required(['Global Admin'])
def components():
    """Display component settings page."""
    tokens = load_design_tokens()
    current_components = tokens['components'] if tokens else DEFAULT_DESIGN_TOKENS['components']

    return render_template(
        'admin_panel/appearance_components.html',
        components=current_components,
        default_components=DEFAULT_DESIGN_TOKENS['components']
    )


@admin_panel_bp.route('/appearance/save-components', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def save_components():
    """Save component settings."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "message": "No data provided"}), 400

        # Validate component data
        valid_border_radius = ['sharp', 'default', 'rounded']
        valid_shadow_intensity = ['none', 'subtle', 'default', 'strong']

        border_radius = data.get('border_radius')
        shadow_intensity = data.get('shadow_intensity')

        if border_radius not in valid_border_radius:
            return jsonify({"success": False, "message": "Invalid border_radius value"}), 400

        if shadow_intensity not in valid_shadow_intensity:
            return jsonify({"success": False, "message": "Invalid shadow_intensity value"}), 400

        # Load current tokens
        tokens = load_design_tokens()
        if tokens is None:
            tokens = DEFAULT_DESIGN_TOKENS.copy()

        # Update components
        tokens['components'] = {
            'border_radius': border_radius,
            'shadow_intensity': shadow_intensity
        }

        # Save tokens
        if save_design_tokens(tokens):
            return jsonify({
                "success": True,
                "message": "Component settings saved successfully. Refresh to see changes."
            })
        else:
            return jsonify({"success": False, "message": "Failed to save component settings"}), 500

    except Exception as e:
        current_app.logger.error(f"Error saving components: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


# ============================================================================
# Animation Routes
# ============================================================================

@admin_panel_bp.route('/appearance/animations')
@login_required
@role_required(['Global Admin'])
def animations():
    """Display animation settings page."""
    tokens = load_design_tokens()
    current_animations = tokens['animations'] if tokens else DEFAULT_DESIGN_TOKENS['animations']

    return render_template(
        'admin_panel/appearance_animations.html',
        animations=current_animations,
        default_animations=DEFAULT_DESIGN_TOKENS['animations']
    )


@admin_panel_bp.route('/appearance/save-animations', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def save_animations():
    """Save animation settings."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "message": "No data provided"}), 400

        # Validate animation data
        valid_speeds = ['slow', 'default', 'fast']

        enabled = data.get('enabled', True)
        speed = data.get('speed', 'default')

        if speed not in valid_speeds:
            return jsonify({"success": False, "message": "Invalid speed value"}), 400

        # Load current tokens
        tokens = load_design_tokens()
        if tokens is None:
            tokens = DEFAULT_DESIGN_TOKENS.copy()

        # Update animations
        tokens['animations'] = {
            'enabled': bool(enabled),
            'speed': speed
        }

        # Save tokens
        if save_design_tokens(tokens):
            return jsonify({
                "success": True,
                "message": "Animation settings saved successfully. Refresh to see changes."
            })
        else:
            return jsonify({"success": False, "message": "Failed to save animation settings"}), 500

    except Exception as e:
        current_app.logger.error(f"Error saving animations: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


# ============================================================================
# Theme Variant Routes
# ============================================================================

@admin_panel_bp.route('/appearance/theme-variant')
@login_required
@role_required(['Global Admin'])
def theme_variant():
    """Display theme variant settings page."""
    tokens = load_design_tokens()
    current_variant = tokens.get('theme_variant', 'modern') if tokens else 'modern'

    return render_template(
        'admin_panel/appearance_theme_variant.html',
        current_variant=current_variant,
        available_variants=['modern', 'modern-v2']
    )


@admin_panel_bp.route('/appearance/save-theme-variant', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def save_theme_variant():
    """Save theme variant setting."""
    try:
        data = request.get_json()
        if not data or 'variant' not in data:
            return jsonify({"success": False, "message": "No variant provided"}), 400

        # Validate variant
        valid_variants = ['modern', 'modern-v2']
        variant = data['variant']

        if variant not in valid_variants:
            return jsonify({"success": False, "message": "Invalid variant value"}), 400

        # Load current tokens
        tokens = load_design_tokens()
        if tokens is None:
            tokens = DEFAULT_DESIGN_TOKENS.copy()

        # Update variant
        tokens['theme_variant'] = variant

        # Save tokens
        if save_design_tokens(tokens):
            return jsonify({
                "success": True,
                "message": f"Theme variant changed to {variant}. Refresh to see changes."
            })
        else:
            return jsonify({"success": False, "message": "Failed to save theme variant"}), 500

    except Exception as e:
        current_app.logger.error(f"Error saving theme variant: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


# ============================================================================
# Import/Export Routes (Full Design Tokens)
# ============================================================================

@admin_panel_bp.route('/appearance/export', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def export_design_tokens():
    """Export full design token system as JSON."""
    tokens = load_design_tokens()
    if tokens is None:
        tokens = DEFAULT_DESIGN_TOKENS

    return jsonify({
        "success": True,
        "tokens": tokens,
        "is_custom": load_design_tokens() is not None
    })


@admin_panel_bp.route('/appearance/import', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def import_design_tokens():
    """Import full design token system from JSON."""
    try:
        data = request.get_json()
        if not data or 'tokens' not in data:
            return jsonify({"success": False, "message": "No tokens provided"}), 400

        tokens = data['tokens']

        # Validate structure
        if not validate_design_tokens(tokens):
            return jsonify({"success": False, "message": "Invalid design tokens structure"}), 400

        if save_design_tokens(tokens):
            return jsonify({
                "success": True,
                "message": "Design tokens imported successfully. Refresh to see changes."
            })
        else:
            return jsonify({"success": False, "message": "Failed to import design tokens"}), 500

    except Exception as e:
        current_app.logger.error(f"Error importing design tokens: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@admin_panel_bp.route('/appearance/reset-all', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def reset_all_tokens():
    """Reset all design tokens to defaults."""
    try:
        tokens_path = get_design_tokens_file_path()
        colors_path = get_colors_file_path()

        # Remove both files
        if os.path.exists(tokens_path):
            os.remove(tokens_path)
        if os.path.exists(colors_path):
            os.remove(colors_path)

        return jsonify({
            "success": True,
            "message": "All design tokens reset to defaults. Refresh to see changes.",
            "tokens": DEFAULT_DESIGN_TOKENS
        })

    except Exception as e:
        current_app.logger.error(f"Error resetting design tokens: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


# ============================================================================
# Helper Functions for Templates
# ============================================================================

def get_site_theme_colors():
    """
    Get the current theme colors for use in templates.
    Returns custom colors if set, otherwise returns None.
    """
    return load_custom_colors()


def get_site_design_tokens():
    """
    Get the current design tokens for use in templates.
    Returns custom tokens if set, otherwise returns None.
    """
    return load_design_tokens()


# ============================================================================
# Theme Preset Routes
# ============================================================================

@admin_panel_bp.route('/api/presets')
@login_required
def list_presets():
    """
    List all enabled theme presets for navbar dropdown.
    This is a public endpoint (any logged-in user can see presets).
    """
    try:
        from app.models import ThemePreset

        presets = ThemePreset.get_enabled_presets()
        preset_list = [preset.to_summary_dict() for preset in presets]

        return jsonify({
            "success": True,
            "presets": preset_list
        })
    except Exception as e:
        current_app.logger.error(f"Error listing presets: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@admin_panel_bp.route('/api/presets/<slug>')
@login_required
def get_preset(slug):
    """
    Get a single preset's full data including colors.
    """
    try:
        from app.models import ThemePreset

        preset = ThemePreset.get_by_slug(slug)
        if not preset:
            return jsonify({"success": False, "message": "Preset not found"}), 404

        return jsonify({
            "success": True,
            "preset": preset.to_dict()
        })
    except Exception as e:
        current_app.logger.error(f"Error getting preset: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@admin_panel_bp.route('/appearance/presets/create', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def create_preset():
    """
    Create a new theme preset.
    """
    try:
        from app.models import ThemePreset

        data = request.get_json()
        if not data:
            return jsonify({"success": False, "message": "No data provided"}), 400

        name = data.get('name')
        colors = data.get('colors')
        description = data.get('description')

        if not name or not colors:
            return jsonify({"success": False, "message": "Name and colors are required"}), 400

        # Validate colors structure
        if 'light' not in colors or 'dark' not in colors:
            return jsonify({"success": False, "message": "Invalid color structure"}), 400

        preset = ThemePreset.create_preset(
            name=name,
            colors=colors,
            description=description,
            user_id=current_user.id
        )

        return jsonify({
            "success": True,
            "message": f"Preset '{name}' created successfully.",
            "preset": preset.to_dict()
        })

    except Exception as e:
        current_app.logger.error(f"Error creating preset: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@admin_panel_bp.route('/appearance/presets/save-current', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def save_current_as_preset():
    """
    Save the current appearance settings as a new named preset.
    """
    try:
        from app.models import ThemePreset

        data = request.get_json()
        if not data:
            return jsonify({"success": False, "message": "No data provided"}), 400

        name = data.get('name')
        description = data.get('description')

        if not name:
            return jsonify({"success": False, "message": "Name is required"}), 400

        # Get current colors
        colors = load_custom_colors()
        if not colors:
            colors = DEFAULT_COLORS

        preset = ThemePreset.create_preset(
            name=name,
            colors=colors,
            description=description,
            user_id=current_user.id
        )

        return jsonify({
            "success": True,
            "message": f"Current colors saved as preset '{name}'.",
            "preset": preset.to_dict()
        })

    except Exception as e:
        current_app.logger.error(f"Error saving current as preset: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@admin_panel_bp.route('/appearance/presets/<int:preset_id>/update', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def update_preset(preset_id):
    """
    Update an existing preset's name, description, or colors.
    """
    try:
        from app.models import ThemePreset, db

        preset = ThemePreset.query.get(preset_id)
        if not preset:
            return jsonify({"success": False, "message": "Preset not found"}), 404

        data = request.get_json()
        if not data:
            return jsonify({"success": False, "message": "No data provided"}), 400

        # Update fields if provided
        if 'name' in data:
            preset.name = data['name']
        if 'description' in data:
            preset.description = data['description']
        if 'colors' in data:
            colors = data['colors']
            if 'light' not in colors or 'dark' not in colors:
                return jsonify({"success": False, "message": "Invalid color structure"}), 400
            preset.colors = colors

        db.session.commit()

        return jsonify({
            "success": True,
            "message": f"Preset '{preset.name}' updated successfully.",
            "preset": preset.to_dict()
        })

    except Exception as e:
        current_app.logger.error(f"Error updating preset: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@admin_panel_bp.route('/appearance/presets/<int:preset_id>/delete', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def delete_preset(preset_id):
    """
    Delete a theme preset (cannot delete system presets).
    """
    try:
        from app.models import ThemePreset, db

        preset = ThemePreset.query.get(preset_id)
        if not preset:
            return jsonify({"success": False, "message": "Preset not found"}), 404

        if preset.is_system:
            return jsonify({"success": False, "message": "Cannot delete system presets"}), 400

        name = preset.name
        db.session.delete(preset)
        db.session.commit()

        return jsonify({
            "success": True,
            "message": f"Preset '{name}' deleted successfully."
        })

    except Exception as e:
        current_app.logger.error(f"Error deleting preset: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@admin_panel_bp.route('/appearance/presets/<int:preset_id>/set-default', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def set_default_preset(preset_id):
    """
    Set a preset as the default for new users.
    """
    try:
        from app.models import ThemePreset

        preset = ThemePreset.set_default(preset_id)
        if not preset:
            return jsonify({"success": False, "message": "Preset not found"}), 404

        return jsonify({
            "success": True,
            "message": f"'{preset.name}' is now the default preset."
        })

    except Exception as e:
        current_app.logger.error(f"Error setting default preset: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@admin_panel_bp.route('/appearance/presets/<int:preset_id>/apply', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def apply_preset_colors(preset_id):
    """
    Apply a preset's colors to the current appearance settings.
    """
    try:
        from app.models import ThemePreset

        preset = ThemePreset.query.get(preset_id)
        if not preset:
            return jsonify({"success": False, "message": "Preset not found"}), 404

        # Save preset colors as current colors
        if save_custom_colors(preset.colors):
            return jsonify({
                "success": True,
                "message": f"Applied colors from '{preset.name}'. Refresh to see changes."
            })
        else:
            return jsonify({"success": False, "message": "Failed to apply preset colors"}), 500

    except Exception as e:
        current_app.logger.error(f"Error applying preset: {e}")
        return jsonify({"success": False, "message": str(e)}), 500
