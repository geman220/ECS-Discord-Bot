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
        # 'Premier Coach'/'Classic Coach' are the DIVISION coach roles granted by
        # the seasons/coaches page; before the draft those coaches have no
        # player_teams.is_coach row and often no 'Pub League Coach' role, so the
        # division roles must open the draft links or draft-night coaches see nothing.
        can_view_draft = has_any('Pub League Admin', 'Global Admin', 'Pub League Coach',
                                 'Premier Coach', 'Classic Coach', 'ECS FC Coach')
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
                if active_path is not None:
                    active = active_path in path
                elif args:
                    # Parameterized routes (e.g. draft_enhanced.draft_league for
                    # classic/premier/ecs_fc) share one endpoint — endpoint
                    # equality would light ALL variants at once. Match the
                    # concrete URL instead.
                    active = (url == path)
                else:
                    active = (endpoint == endpoint_name)
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
        if has_any('Pub League Coach', 'Premier Coach', 'Classic Coach', 'ECS FC Coach',
                   'Pub League Admin', 'Global Admin'):
            main_items.append(item('Coach Dashboard', 'ti-clipboard', 'teams.coach_dashboard'))
        # NAD Board — scouting board for newly acquired Pub League players. Coaches
        # (who rotate often and are NOT admins) get it here in the normal shell; it
        # is deliberately NOT in the admin panel and carries no "admin" wording.
        if has_any('Pub League Coach', 'Premier Coach', 'Classic Coach',
                   'Pub League Admin', 'Global Admin'):
            main_items.append(item('NAD Board', 'ti-user-plus', 'nad_board.index'))
        if authenticated:
            main_items.append(item('Help Topics', 'ti-help-circle', 'help.index'))
        if main_items:
            sections.append({'title': 'Main', 'items': main_items})

        # --- Classic --- (board + blind rating queue + the balanced draft —
        # the whole Classic workflow in one section, normal shell, no admin
        # chrome; the NAD-board reasoning applies).
        classic_items = []
        if has_any('Pub League Coach', 'Classic Coach', 'Pub League Admin', 'Global Admin'):
            classic_items.append(item('Classic Board', 'ti-clipboard-data', 'classic_board.index'))
        if has_any('Classic Coach', 'Pub League Admin', 'Global Admin'):
            classic_items.append(item('Rate Players', 'ti-star', 'classic_board.rate'))
            classic_items.append(item('Classic Draft', 'ti-scale', 'draft_enhanced.draft_league',
                                      args={'league_name': 'classic'}))
        if classic_items:
            sections.append({'title': 'Classic', 'items': classic_items})

        # --- ECS FC League ---
        league_items = []
        if can_view_draft and (admin_settings.get('drafts_navigation_enabled', True) or is_admin):
            # Classic lives in its own sidebar section (balanced draft);
            # this dropdown keeps the turn-based drafts only.
            draft_children = [
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
        if can_view_standings and (admin_settings.get('leagues_navigation_enabled', True) or is_admin):
            league_items.append(item('Standings', 'ti-chart-bar', 'teams.view_standings'))
        if can_view_store:
            league_items.append(item('League Store', 'ti-shopping-cart', 'store.index', active_path='store'))
        if can_view_calendar:
            league_items.append(item('Calendar', 'ti-calendar', 'calendar.calendar_view'))
        if league_items:
            sections.append({'title': 'ECS FC League', 'items': league_items})

        # --- Administration ---
        if is_admin:
            # Digital Wallets moved into the admin panel (Wallet topnav dropdown);
            # the sidebar keeps a single admin entry point.
            sections.append({'title': 'Administration', 'items': [
                item('Admin Panel', 'ti-layout-dashboard', 'admin_panel.dashboard', badge='NEW', highlight=True),
            ]})
        elif has_any('ECS FC Coach'):
            # ECS FC Coaches get a single entry into their slice of the admin
            # panel. admin_panel.dashboard auto-redirects coach-only users to the
            # ECS FC Hub, where the simplified ECS-FC-only nav takes over.
            sections.append({'title': 'Administration', 'items': [
                item('ECS FC Admin', 'ti-shield', 'admin_panel.ecs_fc_dashboard', highlight=True),
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
    # _register_season_processor(app) — REMOVED, see note below (dead query per render)
    _register_file_versioning_processor(app)
    _register_theme_colors_processor(app)
    _register_ai_assistant_processor(app)
    _register_nav_counts_processor(app)
    _register_endpoint_helper(app)
    _register_page_header_icon(app)
    _register_pending_access_processor(app)
    _register_waitlist_offer_processor(app)


def _register_pending_access_processor(app):
    """Expose ``pending_access`` to every template.

    Non-None only for an authenticated, non-admin user who is NOT an active
    league member (pending admin approval and/or hasn't paid for the season).
    Templates render a slim banner from it (see base_flowbite.html). Fails
    closed to None on any error so a data hiccup never shows a spurious banner.
    """

    @app.context_processor
    def inject_pending_access():
        try:
            user = safe_current_user
            if not (user and user.is_authenticated):
                return dict(pending_access=None)

            # Only show the banner when the access gate is enabled. Same flag +
            # default (True/locked-down) the gate uses.
            from app.models.admin_config import AdminConfig
            if not AdminConfig.get_setting('league_access_gating_enabled', True):
                return dict(pending_access=None)

            # Admin / staff never see the banner.
            from app.init.access_gating import (
                _BYPASS_ROLES, _is_approved_member,
            )
            roles = getattr(g, '_cached_user_roles', None) or []
            if any(r in _BYPASS_ROLES for r in roles):
                return dict(pending_access=None)

            # Approved members never see the banner — access is approval-based,
            # so an approved-but-unpaid member is a normal, fully-access user and
            # is NOT nagged. The banner is only for not-yet-approved signups.
            if _is_approved_member(user):
                return dict(pending_access=None)

            # Denied applicants can't log in, so everyone left here is pending
            # admin approval.
            player = getattr(user, 'player', None)
            return dict(pending_access={
                'is_approved': bool(getattr(user, 'is_approved', False)),
                'is_paid': bool(player and getattr(player, 'is_current_player', False)),
            })
        except Exception as e:
            logger.debug(f"pending_access banner check failed: {e}")
            return dict(pending_access=None)


def _register_waitlist_offer_processor(app):
    """Expose ``waitlist_offer`` to every template.

    Offers the waitlist to a returning member who is APPROVED but hasn't paid
    for the current season (Player.is_current_player is False — the classic
    "didn't buy a pass before the season sold out" case). These users have full
    app access and are deliberately NOT nagged by ``pending_access``; this is a
    soft, optional invite to get in line for a spot.

    Non-None only when the waitlist is enabled, the user is an approved member,
    has a player who is not active this season, and is not already on the
    waitlist. Fails closed to None so a data hiccup never shows a spurious offer.
    """

    @app.context_processor
    def inject_waitlist_offer():
        try:
            user = safe_current_user
            if not (user and user.is_authenticated):
                return dict(waitlist_offer=None)

            from app.models.admin_config import AdminConfig
            if not AdminConfig.get_setting('waitlist_registration_enabled', True):
                return dict(waitlist_offer=None)

            # Only approved members are offered this — unapproved signups already
            # get the pending banner and belong in the normal approval queue.
            from app.init.access_gating import _is_approved_member
            if not _is_approved_member(user):
                return dict(waitlist_offer=None)

            # Already on the waitlist? Don't re-offer.
            if getattr(user, 'waitlist_joined_at', None):
                return dict(waitlist_offer=None)

            # Only for players who aren't IN the season yet — same gate as the
            # waitlist join guard (not active/paid AND not on a current-season
            # roster), so the banner never offers something that'll be blocked.
            from app.auth.waitlist import is_actively_playing
            player = getattr(user, 'player', None)
            if not player or is_actively_playing(user):
                return dict(waitlist_offer=None)

            return dict(waitlist_offer=True)
        except Exception as e:
            logger.debug(f"waitlist_offer banner check failed: {e}")
            return dict(waitlist_offer=None)


def _register_endpoint_helper(app):
    """Expose endpoint_exists() to templates so optional nav links can degrade
    gracefully instead of raising BuildError (which would 500 the whole page)
    when a route module failed to register."""

    @app.template_global()
    def endpoint_exists(name):
        return name in app.view_functions


def _register_page_header_icon(app):
    """Expose page_header_icon() to templates so the shared page_header macro can
    render a Tabler icon that matches the page's navigation icon — keeping every
    admin page header visually consistent with the nav without per-page edits.

    The mapping is derived from the admin nav + section tabs so the header icon
    always matches what the user clicked to get here. Unmapped endpoints return
    '' (the header renders icon-less rather than showing a wrong icon)."""

    _PAGE_HEADER_ICONS = {
        'admin.discord_onboarding.admin_test_onboarding': 'ti-flask',
        'admin_panel.animations': 'ti-bounce-right',
        'admin_panel.announcements': 'ti-speakerphone',
        'admin_panel.api_management': 'ti-api',
        'admin_panel.appearance': 'ti-palette',
        'admin_panel.audit_logs': 'ti-file-text',
        'admin_panel.cache_redis_consolidated': 'ti-database',
        'admin_panel.campaigns_list': 'ti-broadcast',
        'admin_panel.coach_dashboard': 'ti-clipboard-list',
        'admin_panel.coach_engagement': 'ti-whistle',
        'admin_panel.communication_hub': 'ti-message-circle',
        'admin_panel.community_analytics': 'ti-message-2',
        'admin_panel.components': 'ti-components',
        'admin_panel.dashboard': 'ti-dashboard',
        'admin_panel.database_monitor': 'ti-database-cog',
        'admin_panel.direct_messaging': 'ti-send',
        'admin_panel.discord_bot_management': 'ti-robot',
        'admin_panel.discord_onboarding': 'ti-user-plus',
        'admin_panel.discord_overview': 'ti-dashboard',
        'admin_panel.discord_players': 'ti-users',
        'admin_panel.discord_role_mapping': 'ti-link',
        'admin_panel.discord_roles': 'ti-refresh',
        'admin_panel.docker_management': 'ti-box',
        'admin_panel.draft_history': 'ti-history',
        'admin_panel.draft_setup_page': 'ti-settings',
        'admin_panel.duplicate_registrations': 'ti-copy',
        'admin_panel.ecs_fc_dashboard': 'ti-dashboard',
        'admin_panel.ecs_fc_import': 'ti-file-import',
        'admin_panel.ecs_fc_matches': 'ti-list',
        'admin_panel.ecs_fc_opponents': 'ti-users-group',
        'admin_panel.ecs_fc_sub_requests': 'ti-clipboard-list',
        'admin_panel.ecs_fc_team_schedule': 'ti-calendar',
        'admin_panel.email_broadcasts_list': 'ti-mail-forward',
        'admin_panel.email_templates_list': 'ti-template',
        'admin_panel.feature_toggles': 'ti-toggle-left',
        'admin_panel.feedback_list': 'ti-message',
        'admin_panel.ispy_analytics': 'ti-chart-bar',
        'admin_panel.ispy_categories': 'ti-category',
        'admin_panel.ispy_management': 'ti-eye',
        'admin_panel.ispy_players': 'ti-users',
        'admin_panel.ispy_seasons': 'ti-calendar',
        'admin_panel.ispy_shots': 'ti-camera',
        'admin_panel.league_management_history': 'ti-history',
        'admin_panel.league_management_seasons': 'ti-calendar-stats',
        'admin_panel.league_management_teams': 'ti-shirt-sport',
        'admin_panel.league_settings': 'ti-adjustments',
        'admin_panel.league_standings': 'ti-table',
        'admin_panel.live_reporting_dashboard': 'ti-antenna',
        'admin_panel.manage_leagues': 'ti-trophy',
        'admin_panel.match_check_in_index': 'ti-qrcode',
        'admin_panel.match_operations': 'ti-dashboard',
        'admin_panel.match_reports': 'ti-report',
        'admin_panel.match_verification': 'ti-check',
        'admin_panel.messaging_settings': 'ti-settings',
        'admin_panel.mls_matches': 'ti-list',
        'admin_panel.mls_sessions': 'ti-broadcast',
        'admin_panel.mls_settings': 'ti-settings',
        'admin_panel.mls_task_monitoring': 'ti-list-check',
        'admin_panel.mobile_analytics': 'ti-chart-line',
        'admin_panel.mobile_app_analytics': 'ti-device-mobile',
        'admin_panel.mobile_app_config': 'ti-adjustments',
        'admin_panel.mobile_error_analytics': 'ti-bug',
        'admin_panel.mobile_error_list': 'ti-list-details',
        'admin_panel.mobile_features': 'ti-device-mobile',
        'admin_panel.mobile_users': 'ti-users',
        'admin_panel.navigation_settings': 'ti-menu-2',
        'admin_panel.message_composer': 'ti-pencil-bolt',
        'admin_panel.notification_groups_list': 'ti-users-group',
        'admin_panel.playoff_management': 'ti-trophy',
        'admin_panel.push_history': 'ti-history',
        'admin_panel.push_notifications': 'ti-bell',
        'admin_panel.push_notifications_dashboard': 'ti-dashboard',
        'admin_panel.push_notifications_settings': 'ti-settings',
        'admin_panel.push_subscriptions': 'ti-users',
        'admin_panel.quick_profiles_management': 'ti-id-badge',
        'admin_panel.redis_draft_cache_stats': 'ti-stack',
        'admin_panel.reports_center': 'ti-report-analytics',
        'admin_panel.roles_comprehensive': 'ti-shield',
        'admin_panel.schedule_matches': 'ti-calendar-plus',
        'admin_panel.scheduled_messages_history': 'ti-history',
        'admin_panel.scheduled_messages_queue': 'ti-clock',
        'admin_panel.season_coaches': 'ti-whistle',
        'admin_panel.season_manage': 'ti-adjustments',
        'admin_panel.season_rollover': 'ti-rotate-clockwise',
        'admin_panel.security_dashboard': 'ti-shield-check',
        'admin_panel.sms_analytics_dashboard': 'ti-chart-bar',
        'admin_panel.spacing': 'ti-ruler-2',
        'admin_panel.store_analytics': 'ti-chart-bar',
        'admin_panel.store_items': 'ti-package',
        'admin_panel.store_management': 'ti-shopping-cart',
        'admin_panel.store_orders': 'ti-receipt',
        'admin_panel.substitute_management': 'ti-user-plus',
        'admin_panel.substitute_pools': 'ti-user-plus',
        'admin_panel.surveys_list': 'ti-clipboard-list',
        'admin_panel.system_health_consolidated': 'ti-heartbeat',
        'admin_panel.system_info': 'ti-info-circle',
        'admin_panel.system_logs': 'ti-file-text',
        'admin_panel.system_performance': 'ti-gauge',
        'admin_panel.task_monitoring_page': 'ti-list-check',
        'admin_panel.theme_variant': 'ti-color-swatch',
        'admin_panel.typography': 'ti-typography',
        'admin_panel.unified_substitutes': 'ti-layout-grid',
        'admin_panel.user_analytics': 'ti-chart-line',
        'admin_panel.user_approvals': 'ti-user-check',
        'admin_panel.user_waitlist': 'ti-clock',
        'admin_panel.users_comprehensive': 'ti-users',
        'admin_panel.view_matches': 'ti-list',
        'ai_assistant.admin_metrics': 'ti-sparkles',
        'ai_prompts.list_prompts': 'ti-brain',
        'auto_schedule.current_season_schedule': 'ti-calendar-event',
        'draft_predictions.admin_dashboard': 'ti-chart-dots',
        'help.admin_help_topics': 'ti-help',
        'pub_league_orders_admin.orders_list': 'ti-receipt',
        'wallet_admin.checkins_list': 'ti-checkbox',
        'wallet_admin.create_ecs_pass': 'ti-plus',
        'wallet_admin.create_pub_league_pass': 'ti-plus',
        'wallet_admin.passes_list': 'ti-id',
        'wallet_admin.scanner': 'ti-scan',
        'wallet_admin.wallet_management': 'ti-dashboard',
        'wallet_admin.wallet_players': 'ti-users',
        # Secondary / detail / create-edit pages (icons inherit their cluster).
        'admin_panel.api_analytics': 'ti-chart-bar',
        'admin_panel.api_endpoints': 'ti-api',
        'admin_panel.api_integrations': 'ti-plug',
        'admin_panel.create_announcement': 'ti-speakerphone',
        'admin_panel.edit_announcement': 'ti-speakerphone',
        'admin_panel.live_matches': 'ti-broadcast',
        'admin_panel.match_check_in_detail': 'ti-qrcode',
        'admin_panel.quick_actions': 'ti-bolt',
        'admin_panel.role_comprehensive_users': 'ti-shield',
        'admin_panel.rsvp_status': 'ti-checkbox',
        'admin_panel.schedule_new_message': 'ti-clock',
        'admin_panel.scheduled_messages': 'ti-clock',
        'admin_panel.scheduled_messages_history': 'ti-history',
        'admin_panel.task_history': 'ti-list-check',
        'admin_panel.upcoming_matches': 'ti-calendar-up',
        'admin_panel.match_results': 'ti-list-check',
        'admin_panel.live_reporting_dashboard': 'ti-antenna',
        'admin_panel.create_store_item': 'ti-package',
        'admin_panel.edit_store_item': 'ti-package',
        'admin_panel.create_ispy_season': 'ti-calendar',
        'admin_panel.edit_ispy_season': 'ti-calendar',
        'admin_panel.ecs_fc_match_create': 'ti-calendar-plus',
        'admin_panel.ecs_fc_match_edit': 'ti-calendar',
        'admin_panel.survey_builder_new': 'ti-clipboard-list',
        'admin_panel.survey_builder_edit': 'ti-clipboard-list',
        'admin_panel.survey_templates_list': 'ti-clipboard-list',
        'admin_panel.survey_results': 'ti-chart-bar',
        'admin_panel.survey_responses_list': 'ti-clipboard-check',
        'admin_panel.survey_distribute': 'ti-send',
        'admin_panel.email_broadcast_compose': 'ti-mail-forward',
        'admin_panel.email_broadcast_detail': 'ti-mail-forward',
        'admin_panel.email_broadcast_edit': 'ti-mail-forward',
        'admin_panel.email_template_new': 'ti-template',
        'admin_panel.email_template_edit': 'ti-template',
        'admin_panel.coach_history': 'ti-whistle',
        'admin_panel.substitute_reconcile_list': 'ti-layout-grid',
        'admin_panel.notification_groups_detail': 'ti-users-group',
        'admin_panel.attendance_report': 'ti-calendar-stats',
        'admin_panel.contactability_report': 'ti-address-book',
        'admin_panel.discipline_report': 'ti-alert-triangle',
        'admin_panel.jersey_report': 'ti-shirt',
        'admin_panel.leaderboards_report': 'ti-trophy',
        'admin_panel.movement_report': 'ti-arrows-exchange',
        'admin_panel.player_stats_report': 'ti-chart-bar',
        'admin_panel.retention_report': 'ti-users',
        'admin_panel.roster_history_report': 'ti-history',
        'admin_panel.standings_report': 'ti-table',
    }

    @app.template_global()
    def page_header_icon(endpoint=None):
        """Return the Tabler icon (e.g. 'ti-whistle') for the given endpoint, or
        the current request endpoint when none is passed. '' if unmapped."""
        from flask import request
        if endpoint is None:
            if not has_request_context():
                return ''
            endpoint = request.endpoint
        return _PAGE_HEADER_ICONS.get(endpoint or '', '')


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
            # Only settings something downstream actually consumes: the four
            # nav toggles feed build_nav_sections, waitlist drives the
            # returning-member banner, maintenance_mode drives display copy.
            # (The old matches/players/messaging/mobile_features nav keys,
            # apple_wallet_enabled and push_notifications_enabled were ghost
            # flags nothing read — removed 2026-07.)
            admin_settings = {
                'teams_navigation_enabled': True,
                'store_navigation_enabled': True,
                'leagues_navigation_enabled': True,
                'drafts_navigation_enabled': True,
                'waitlist_registration_enabled': True,
                'maintenance_mode': False
            }
        else:
            admin_settings = {
                'teams_navigation_enabled': AdminConfig.get_setting('teams_navigation_enabled', True),
                'store_navigation_enabled': AdminConfig.get_setting('store_navigation_enabled', True),
                'leagues_navigation_enabled': AdminConfig.get_setting('leagues_navigation_enabled', True),
                'drafts_navigation_enabled': AdminConfig.get_setting('drafts_navigation_enabled', True),
                'waitlist_registration_enabled': AdminConfig.get_setting('waitlist_registration_enabled', True),
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
            # Cache per request: this runs on EVERY template render, and the
            # uncached version re-loaded the full User row plus a selectinload of
            # roles each time — one of the heaviest queries in the log, purely to
            # decide whether to show the impersonation menu.
            if hasattr(g, '_is_real_global_admin'):
                return g._is_real_global_admin

            result = False
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
                        result = 'Global Admin' in real_roles
            except Exception as e:
                logger.error(f"Error checking real global admin status: {e}")

            g._is_real_global_admin = result
            return result

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

        # Reveal gate for templates (make_teams_public): cached per request.
        # True when teams are public or the viewer is coach/admin-exempt.
        if hasattr(g, '_viewer_can_see_teams'):
            viewer_can_see_teams = g._viewer_can_see_teams
        else:
            viewer_can_see_teams = True
            try:
                from app.services.team_visibility import user_can_view_teams
                viewer_can_see_teams = user_can_view_teams(
                    safe_current_user, session=getattr(g, 'db_session', None)
                )
            except Exception as e:
                logger.error(f"Error computing viewer_can_see_teams: {e}")
            g._viewer_can_see_teams = viewer_can_see_teams

        return {
            'safe_current_user': safe_current_user,
            'user_roles': user_roles,
            'viewer_can_see_teams': viewer_can_see_teams,
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


# _register_season_processor REMOVED.
#
# It was an @app.context_processor that ran a SELECT on `season` for EVERY rendered
# template, on every page, for every user — including anonymous ones. Not one of the
# 427 templates references `current_pub_league_season`. Under a 30-user burst that is
# 30 pointless queries against a 1-vCPU Postgres.
#
# NOTE: app/utils/season_context.current_pub_league_season() and g.current_pub_league_season
# (app/publeague.py) are DIFFERENT things and are still in use. Do not grep-and-delete
# the name.


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
        empty = {'nav_pending_approvals': 0, 'nav_waitlist_count': 0}

        # These two COUNTs used to run on EVERY render for EVERY user — including
        # anonymous visitors and mobile API callers — even though only admins see
        # the badges they feed. They also ran on db.session, which checks out a
        # SECOND pooled connection (and, under pgbouncer transaction pooling, pins
        # a second server slot) alongside the request's own open transaction.
        if not (safe_current_user and safe_current_user.is_authenticated):
            return empty

        # before_request caches effective roles on g; fall back to the auth object
        # so an admin never sees a silently-zeroed badge if that cache is missing.
        # NOTE the two sources disagree on type: g._cached_user_roles holds role
        # NAME STRINGS, while safe_current_user.roles delegates to the ORM and
        # yields Role OBJECTS. Normalise, or the membership test below is always
        # False on the fallback path and admins lose their badges.
        roles = getattr(g, '_cached_user_roles', None)
        if not roles:
            roles = getattr(safe_current_user, 'roles', None) or []
        role_names = {r if isinstance(r, str) else getattr(r, 'name', '') for r in roles}
        if not role_names & {'Global Admin', 'Pub League Admin'}:
            return empty

        if hasattr(g, '_nav_counts'):
            return g._nav_counts

        try:
            from sqlalchemy import func
            from app.models.core import User, Role
            session_db = getattr(g, 'db_session', None)
            if session_db is None:
                return empty

            # "Pending" here means awaiting a DECISION — waitlisted users (pending +
            # pl-waitlist role) are parked on the waitlist page, not this queue, so
            # the shared helper excludes them. Keeps this badge equal to the count on
            # the approvals page it links to.
            pending = User.count_pending_approvals(session_db)
            waitlist = session_db.query(func.count(func.distinct(User.id))).select_from(
                User
            ).join(User.roles).filter(Role.name == 'pl-waitlist').scalar() or 0

            g._nav_counts = {
                'nav_pending_approvals': pending,
                'nav_waitlist_count': waitlist,
            }
            return g._nav_counts
        except Exception:
            return empty


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
                from app.utils.user_locking import get_session
                # get_session(), not ThemePreset.query: Model.query binds to db.session,
                # a different session from the request's g.db_session, so this context
                # processor was checking out a second pooled connection on every render
                # for any user with a non-default theme.
                preset = get_session().query(ThemePreset).filter_by(
                    slug=preset_slug, is_enabled=True
                ).first()
                if preset and preset.colors:
                    result['preset_colors'] = preset.colors
                    # JSON for injection into blocking script
                    result['preset_colors_json'] = json.dumps(preset.colors)
        except Exception as e:
            logger.debug(f"Preset colors not loaded: {e}")

        return result
