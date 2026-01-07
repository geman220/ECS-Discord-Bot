# app/init/context_processors.py

"""
Context Processors

Template context processors for user info, roles, permissions, and admin settings.
"""

import logging

from flask import g, has_request_context

from app.utils.user_helpers import safe_current_user

logger = logging.getLogger(__name__)


def init_context_processors(app):
    """
    Register context processors with the Flask application.

    Args:
        app: The Flask application instance.
    """
    _register_utility_processor(app)
    _register_season_processor(app)
    _register_file_versioning_processor(app)
    _register_theme_colors_processor(app)


def _register_utility_processor(app):
    """Register utility context processor."""

    @app.context_processor
    def utility_processor():
        from app.role_impersonation import (
            is_impersonation_active, get_effective_roles, get_effective_permissions
        )
        from app.models.admin_config import AdminConfig

        user_roles = []
        user_permissions = []

        # Get admin settings for template use
        # Check if we're in a failed transaction state first
        if (has_request_context() and
            hasattr(g, '_session_creation_failed') and g._session_creation_failed):
            # Return defaults when database is unavailable
            admin_settings = {
                'teams_navigation_enabled': True,
                'store_navigation_enabled': True,
                'matches_navigation_enabled': True,
                'leagues_navigation_enabled': True,
                'drafts_navigation_enabled': True,
                'players_navigation_enabled': True,
                'messaging_navigation_enabled': True,
                'mobile_features_navigation_enabled': True,
                'waitlist_registration_enabled': True,
                'apple_wallet_enabled': True,
                'push_notifications_enabled': True,
                'maintenance_mode': False
            }
        else:
            admin_settings = {
                'teams_navigation_enabled': AdminConfig.get_setting('teams_navigation_enabled', True),
                'store_navigation_enabled': AdminConfig.get_setting('store_navigation_enabled', True),
                'matches_navigation_enabled': AdminConfig.get_setting('matches_navigation_enabled', True),
                'leagues_navigation_enabled': AdminConfig.get_setting('leagues_navigation_enabled', True),
                'drafts_navigation_enabled': AdminConfig.get_setting('drafts_navigation_enabled', True),
                'players_navigation_enabled': AdminConfig.get_setting('players_navigation_enabled', True),
                'messaging_navigation_enabled': AdminConfig.get_setting('messaging_navigation_enabled', True),
                'mobile_features_navigation_enabled': AdminConfig.get_setting('mobile_features_navigation_enabled', True),
                'waitlist_registration_enabled': AdminConfig.get_setting('waitlist_registration_enabled', True),
                'apple_wallet_enabled': AdminConfig.get_setting('apple_wallet_enabled', True),
                'push_notifications_enabled': AdminConfig.get_setting('push_notifications_enabled', True),
                'maintenance_mode': AdminConfig.get_setting('maintenance_mode', False)
            }

        # Only get roles if we have an active request context and user is authenticated
        if safe_current_user and safe_current_user.is_authenticated:
            try:
                if hasattr(g, '_cached_user_roles'):
                    user_roles = g._cached_user_roles
                    user_permissions = g._cached_user_permissions
                else:
                    user_roles = get_effective_roles()
                    user_permissions = get_effective_permissions()
                    g._cached_user_roles = user_roles
                    g._cached_user_permissions = user_permissions
            except Exception as e:
                logger.error(f"Error getting effective roles/permissions in template context: {e}")
                user_roles = []
                user_permissions = []

        def has_permission(permission_name):
            return permission_name in user_permissions

        def has_role(role_name):
            return role_name in user_roles

        def is_admin():
            return 'Global Admin' in user_roles or 'Pub League Admin' in user_roles

        def is_role_impersonation_active():
            return is_impersonation_active()

        # Get available roles for impersonation (only for Global Admins)
        available_roles = []
        if 'Global Admin' in user_roles:
            try:
                from app.models import Role
                session_db = getattr(g, 'db_session', None)
                if session_db:
                    from sqlalchemy.orm import joinedload
                    roles = session_db.query(Role).options(
                        joinedload(Role.permissions)
                    ).all()
                    available_roles = [
                        {
                            'name': role.name,
                            'permission_count': len(role.permissions) if role.permissions else 0
                        }
                        for role in roles
                    ]
            except Exception as e:
                logger.error(f"Error getting available roles for impersonation: {e}")

        return {
            'safe_current_user': safe_current_user,
            'user_roles': user_roles,
            'has_permission': has_permission,
            'has_role': has_role,
            'is_admin': is_admin,
            'is_role_impersonation_active': is_role_impersonation_active,
            'admin_settings': admin_settings,
            'available_roles': available_roles
        }


def _register_season_processor(app):
    """Register current Pub League season context processor."""
    from app.models import Season

    @app.context_processor
    def inject_current_pub_league_season():
        """Inject the current Pub League season into every template's context."""
        # Check if we're in degraded mode
        if (has_request_context() and
            hasattr(g, '_session_creation_failed') and g._session_creation_failed):
            return dict(current_pub_league_season=None)

        # Try to use Flask's request session first
        if has_request_context() and hasattr(g, 'db_session') and g.db_session:
            try:
                season = g.db_session.query(Season).filter_by(
                    league_type='Pub League',
                    is_current=True
                ).first()
                return dict(current_pub_league_season=season)
            except Exception as e:
                if "pool" in str(e).lower() or "timeout" in str(e).lower():
                    logger.warning(f"Pool exhaustion in context processor, returning default: {e}")
                    return dict(current_pub_league_season=None)
                logger.warning(f"Error fetching pub league season from request session: {e}")
                # Rollback to clear failed transaction state
                try:
                    g.db_session.rollback()
                except Exception:
                    pass

        # Fallback: Use managed_session
        try:
            from app.core.session_manager import managed_session
            with managed_session() as session:
                season = session.query(Season).filter_by(
                    league_type='Pub League',
                    is_current=True
                ).first()
                if season:
                    _ = season.id, season.name, season.league_type, season.is_current
                    session.expunge(season)
            return dict(current_pub_league_season=season)
        except Exception as e:
            logger.error(f"Error fetching pub league season: {e}", exc_info=True)
            return dict(current_pub_league_season=None)


def _register_file_versioning_processor(app):
    """Register file versioning context processor."""
    import random

    @app.context_processor
    def inject_file_versioning():
        """Add a file versioning function to templates for cache busting."""
        from app.extensions import file_versioning

        def asset_version(filename):
            """Generate a versioned URL for a static file to bust browser caches."""
            try:
                from flask import url_for
                version = file_versioning.get_version(filename, 'mtime')
                return f"{url_for('static', filename=filename)}?v={version}"
            except Exception as e:
                logger.error(f"Error generating version for {filename}: {str(e)}")
                from flask import url_for
                return f"{url_for('static', filename=filename)}?v={random.randint(1, 1000000)}"

        return {'asset_version': asset_version}


def _register_theme_colors_processor(app):
    """Register theme colors context processor for custom color palette."""

    @app.context_processor
    def inject_theme_colors():
        """Inject custom theme colors and preset colors into templates."""
        from flask import session, request

        result = {
            'site_settings': None,
            'preset_colors': None,
            'preset_colors_json': 'null'
        }

        try:
            from app.admin_panel.routes.appearance import load_custom_colors
            custom_colors = load_custom_colors()
            if custom_colors:
                result['site_settings'] = {'custom_colors': custom_colors}
        except Exception as e:
            logger.debug(f"Theme colors not loaded: {e}")

        # Load user's selected preset colors for anti-flash script
        try:
            import json
            # Check cookie first (for initial page load), then session
            preset_slug = request.cookies.get('theme_preset') or session.get('theme_preset', 'default')

            if preset_slug and preset_slug != 'default':
                from app.models import ThemePreset
                preset = ThemePreset.query.filter_by(slug=preset_slug, is_enabled=True).first()
                if preset and preset.colors:
                    result['preset_colors'] = preset.colors
                    # JSON for injection into blocking script
                    result['preset_colors_json'] = json.dumps(preset.colors)
        except Exception as e:
            logger.debug(f"Preset colors not loaded: {e}")

        return result
