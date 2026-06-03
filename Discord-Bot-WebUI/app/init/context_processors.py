# app/init/context_processors.py

"""
Context Processors

Template context processors for user info, roles, permissions, and admin settings.
"""

import logging

from flask import g, has_request_context
from sqlalchemy.exc import OperationalError, DBAPIError

from app.utils.user_helpers import safe_current_user

logger = logging.getLogger(__name__)


def build_nav_sections(user_roles, admin_settings):
    """
    Single source of truth for the primary navigation.

    Returns a role-gated list of section dicts so that every shell (classic
    sidebar, console icon-rail) renders the SAME, permission-correct set of
    items. Presentation is left entirely to each shell template;
    this function owns only *what* a user may see, never *how* it looks.

    Section shape: {'title': str, 'items': [item, ...]}  (omitted if it has no
    visible items). Item shape:
        {'label', 'icon', 'url', 'endpoint', 'active', 'badge', 'highlight',
         'children'}  where children (if present) marks a dropdown group.
    """
    from flask import url_for, request

    try:
        def has_any(*roles):
            return any(r in user_roles for r in roles)

        is_admin = has_any('Global Admin', 'Pub League Admin')
        authenticated = bool(safe_current_user and safe_current_user.is_authenticated)

        # Role capability flags — kept verbatim from the legacy sidebar gating.
        can_view_draft = has_any('Pub League Admin', 'Global Admin', 'Pub League Coach', 'ECS FC Coach')
        can_view_draft_predictions = has_any('Pub League Admin', 'Global Admin', 'Pub League Coach')
        can_view_teams = has_any('Pub League Admin', 'Global Admin', 'Pub League Coach', 'ECS FC Coach', 'pl-classic', 'pl-ecs-fc', 'pl-premier')
        can_view_standings = has_any('Pub League Admin', 'Global Admin', 'Pub League Coach', 'ECS FC Coach')
        can_view_calendar = has_any('Pub League Admin', 'Global Admin', 'Pub League Coach', 'ECS FC Coach', 'Pub League Ref', 'pl-classic', 'pl-premier', 'pl-ecs-fc')
        store_enabled = admin_settings.get('store_navigation_enabled', True)
        can_view_store = has_any('Pub League Coach', 'Pub League Admin', 'Global Admin') and (store_enabled or 'Global Admin' in user_roles)

        endpoint = request.endpoint if has_request_context() else None
        path = request.path if has_request_context() else ''

        def item(label, icon, endpoint_name=None, *, args=None, badge=None,
                 highlight=False, children=None, active_path=None):
            url = url_for(endpoint_name, **(args or {})) if endpoint_name else None
            active = False
            if endpoint_name:
                active = (active_path in path) if active_path is not None else (endpoint == endpoint_name)
            if children:
                active = active or any(c['active'] for c in children)
            return {
                'label': label, 'icon': icon, 'url': url, 'endpoint': endpoint_name,
                'active': active, 'badge': badge, 'highlight': highlight,
                'children': children,
            }

        sections = []

        # --- Main ---
        main_items = []
        if authenticated:
            main_items.append(item('Dashboard', 'ti-home', 'main.index'))
            main_items.append(item('Submit Feedback', 'ti-message-report', 'feedback.submit_feedback'))
        if has_any('Pub League Coach', 'ECS FC Coach', 'Pub League Admin', 'Global Admin'):
            main_items.append(item('Coach Dashboard', 'ti-clipboard', 'teams.coach_dashboard'))
        if authenticated:
            main_items.append(item('Help Topics', 'ti-help-circle', 'help.index'))
        if main_items:
            sections.append({'title': 'Main', 'items': main_items})

        # --- ECS FC League ---
        league_items = []
        if can_view_draft:
            draft_children = [
                item('Classic Division', 'ti-point', 'draft_enhanced.draft_league', args={'league_name': 'classic'}),
                item('Premier Division', 'ti-point', 'draft_enhanced.draft_league', args={'league_name': 'premier'}),
                item('ECS FC Division', 'ti-point', 'draft_enhanced.draft_league', args={'league_name': 'ecs_fc'}),
            ]
            if can_view_draft_predictions:
                draft_children.append(item('Draft Predictions', 'ti-point', 'draft_predictions.index'))
            if is_admin:
                draft_children.append(item('Draft History', 'ti-point', 'admin_panel.draft_history'))
            league_items.append(item('Draft', 'ti-list', children=draft_children))
        if can_view_teams and admin_settings.get('teams_navigation_enabled', True):
            league_items.append(item('Teams', 'ti-users', 'teams.teams_overview'))
        if can_view_standings:
            league_items.append(item('Standings', 'ti-chart-bar', 'teams.view_standings'))
        if can_view_store:
            league_items.append(item('League Store', 'ti-shopping-cart', 'store.index', active_path='store'))
        if can_view_calendar:
            league_items.append(item('Calendar', 'ti-calendar', 'calendar.calendar_view'))
        if league_items:
            sections.append({'title': 'ECS FC League', 'items': league_items})

        # --- Administration ---
        if is_admin:
            wallet_children = [
                item('Setup Wizard', 'ti-point', 'wallet_config.setup_wizard'),
                item('Dashboard', 'ti-point', 'wallet_admin.wallet_management'),
                item('Pass Studio', 'ti-point', 'pass_studio.index'),
                item('Manage Passes', 'ti-point', 'wallet_admin.passes_list'),
                item('Scanner', 'ti-point', 'wallet_admin.scanner'),
                item('Check-ins', 'ti-point', 'wallet_admin.checkins_list'),
            ]
            sections.append({'title': 'Administration', 'items': [
                item('Admin Panel', 'ti-layout-dashboard', 'admin_panel.dashboard', badge='NEW', highlight=True),
                item('Digital Wallets', 'ti-device-mobile', children=wallet_children),
            ]})

        return sections
    except Exception as e:
        logger.error(f"Error building nav sections: {e}")
        return []


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
    _register_ai_assistant_processor(app)
    _register_nav_counts_processor(app)


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

        def is_real_global_admin():
            """Check if the REAL user (not impersonated) is a Global Admin."""
            if not safe_current_user or not safe_current_user.is_authenticated:
                return False
            try:
                session_db = getattr(g, 'db_session', None)
                if session_db:
                    from app.models import User
                    from sqlalchemy.orm import selectinload
                    db_user = session_db.query(User).options(
                        selectinload(User.roles)
                    ).get(safe_current_user.id)
                    if db_user:
                        real_roles = [role.name for role in db_user.roles]
                        return 'Global Admin' in real_roles
            except Exception as e:
                logger.error(f"Error checking real global admin status: {e}")
            return False

        # Check if real user is Global Admin (for impersonation UI)
        real_is_global_admin = is_real_global_admin()

        # Get available roles for impersonation (only for real Global Admins)
        available_roles = []
        if real_is_global_admin:
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

        def is_ecs_fc_coach():
            """Check if user has ECS FC Coach role."""
            return 'ECS FC Coach' in user_roles

        def is_ecs_fc_coach_only():
            """Check if user is ONLY an ECS FC Coach (not a full admin)."""
            return 'ECS FC Coach' in user_roles and not is_admin()

        def can_access_admin_panel():
            """Check if user can access some part of the admin panel."""
            return is_admin() or 'ECS FC Coach' in user_roles

        # Resolve the active UI shell (layout). 'classic' is the default for
        # everyone; alternate shells are admin-only during the trial.
        #
        # The admin panel is a FIXED layout: it renders the Modern ('console')
        # page CONTENT but keeps the FULL standard sidebar + the Modern header
        # (user name top-right) — it must NOT collapse to the console icon rail.
        # The `console_full_sidebar` flag tells base_flowbite to use the full
        # sidebar (not the rail) when shell=='console'. Every OTHER page honors
        # the admin's chosen shell so the user-facing app A/B tests Classic vs Modern.
        # Modern ("console") is the default shell for EVERYONE as of the player
        # cutover (the admin-only A/B is over). Classic is now a dormant break-glass:
        # it still renders if session['ui_shell'] == 'classic' is explicitly set, but
        # no UI exposes that anymore (the switcher was removed). The admin panel always
        # uses the full console sidebar; every other page uses the console rail.
        shell = 'console'
        console_full_sidebar = False
        # nav_is_admin is a RESERVED boolean for shared chrome (topbar/shell/nav).
        # Page routes commonly pass `is_admin` as a bool in their render context,
        # shadowing the callable `is_admin()` — so chrome must NOT call is_admin().
        # This name is never set by a route, so it stays a reliable bool.
        nav_is_admin = False
        try:
            from flask import session, request
            nav_is_admin = bool(is_admin())
            if nav_is_admin and has_request_context() and request.blueprint == 'admin_panel':
                console_full_sidebar = True   # full sidebar + Modern header, not the rail
            elif session.get('ui_shell') == 'classic':
                # Break-glass: an explicit classic override (no UI sets this anymore).
                shell = 'classic'
        except Exception as e:
            logger.error(f"Error resolving UI shell: {e}")
            shell = 'console'
            console_full_sidebar = False

        return {
            'safe_current_user': safe_current_user,
            'user_roles': user_roles,
            'has_permission': has_permission,
            'has_role': has_role,
            'is_admin': is_admin,
            'is_ecs_fc_coach': is_ecs_fc_coach,
            'is_ecs_fc_coach_only': is_ecs_fc_coach_only,
            'can_access_admin_panel': can_access_admin_panel,
            'is_role_impersonation_active': is_role_impersonation_active,
            'real_is_global_admin': real_is_global_admin,
            'admin_settings': admin_settings,
            'available_roles': available_roles,
            'nav_sections': build_nav_sections(user_roles, admin_settings),
            'shell': shell,
            'console_full_sidebar': console_full_sidebar,
            'nav_is_admin': nav_is_admin
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
        except (OperationalError, DBAPIError) as e:
            logger.warning(f"DB unavailable fetching pub league season: {e.__class__.__name__}")
            return dict(current_pub_league_season=None)
        except Exception as e:
            logger.error(f"Error fetching pub league season: {e}", exc_info=True)
            return dict(current_pub_league_season=None)


def _register_ai_assistant_processor(app):
    """Register AI assistant enabled flag for templates."""

    @app.context_processor
    def inject_ai_assistant_enabled():
        try:
            from app.models.admin_config import AdminConfig
            enabled = AdminConfig.get_setting('ai_assistant_enabled', True)
            return dict(ai_assistant_enabled=enabled)
        except Exception:
            return dict(ai_assistant_enabled=False)


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


def _register_nav_counts_processor(app):
    """Register navigation badge counts globally so any template that includes
    the admin navigation partial has access to pending approval / waitlist counts."""

    @app.context_processor
    def inject_nav_counts():
        try:
            from sqlalchemy import func
            from app.core import db
            from app.models.core import User, Role
            pending = db.session.query(func.count(User.id)).filter(
                User.approval_status == 'pending'
            ).scalar() or 0
            waitlist = db.session.query(User).join(User.roles).filter(
                Role.name == 'pl-waitlist'
            ).count()
            return {'nav_pending_approvals': pending, 'nav_waitlist_count': waitlist}
        except Exception:
            return {'nav_pending_approvals': 0, 'nav_waitlist_count': 0}


def _hex_to_rgb_channels(hex_color):
    """Convert '#1a472a' to '26 71 42' for CSS rgb() channel syntax."""
    if not hex_color:
        return None
    hex_color = hex_color.lstrip('#')
    if len(hex_color) == 6:
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        return f'{r} {g} {b}'
    return None


def _register_theme_colors_processor(app):
    """Register theme colors context processor for custom color palette."""

    @app.context_processor
    def inject_theme_colors():
        """Inject custom theme colors and preset colors into templates."""
        from flask import session, request

        result = {
            'site_settings': None,
            'preset_colors': None,
            'preset_colors_json': 'null',
            'hex_to_rgb': _hex_to_rgb_channels
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
