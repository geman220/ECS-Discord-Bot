# app/admin_panel/__init__.py

"""
Admin Panel Module

This module provides a centralized admin panel for global administrators
to manage application settings, features, and configurations.
"""

import logging
import time

from flask import Blueprint, url_for, current_app, g

logger = logging.getLogger(__name__)

# Create the admin panel blueprint
admin_panel_bp = Blueprint(
    'admin_panel',
    __name__,
    url_prefix='/admin-panel'
)

# Built index cached per role-set so admin page loads don't re-run ~100
# url_for calls plus the teams/settings queries on every request.
_index_cache = {}
_INDEX_CACHE_TTL = 300  # seconds; new teams/settings appear within this window


def _effective_roles_cached():
    """Effective roles, resolved at most once per request.

    get_effective_roles() caches on g only when g.db_session exists; in a
    bare template context it opens a temporary DB session PER CALL — and the
    index builders call _safe_url ~100 times. This wrapper pins the answer
    on g so a cache-miss index build costs at most one lookup.
    """
    roles = getattr(g, '_admin_search_roles', None)
    if roles is None:
        from app.role_impersonation import get_effective_roles
        roles = list(get_effective_roles())
        g._admin_search_roles = roles
    return roles


def _safe_url(endpoint, **values):
    """url_for that returns None instead of raising, so one stale endpoint
    drops its own search entry rather than blanking the whole index.

    Also role-filters: if the target view was wrapped in @role_required and
    the current user has none of those roles, returns None so the entry is
    dropped — no suggesting pages the user would 403 on. Views without
    @role_required (e.g. permission-gated) are left visible. If roles can't
    be determined, entries stay visible — the route still enforces access;
    this filter is navigation UX, not a security boundary.
    """
    try:
        view = current_app.view_functions.get(endpoint)
        required = getattr(view, 'required_roles', None)
        if required:
            try:
                user_roles = _effective_roles_cached()
            except Exception:
                user_roles = None
            if user_roles is not None and not any(role in user_roles for role in required):
                return None
        return url_for(endpoint, **values)
    except Exception:
        logger.warning("Admin search index: no URL for endpoint %r", endpoint)
        return None


@admin_panel_bp.context_processor
def inject_ecs_fc_teams():
    """
    Inject ECS FC teams into all admin panel templates.
    Used for dynamic navigation in the ECS FC section.
    """
    try:
        from app.models.ecs_fc import get_ecs_fc_teams
        return {'ecs_fc_teams': get_ecs_fc_teams()}
    except Exception:
        return {'ecs_fc_teams': []}


@admin_panel_bp.context_processor
def inject_admin_search_index():
    """Build a searchable index of all admin panel pages for universal search."""
    try:
        user_roles = _effective_roles_cached()
        is_coach_only = 'ECS FC Coach' in user_roles and 'Global Admin' not in user_roles and 'Pub League Admin' not in user_roles

        cache_key = ('coach' if is_coach_only else 'admin', frozenset(user_roles))
        cached = _index_cache.get(cache_key)
        if cached and time.time() - cached[0] < _INDEX_CACHE_TTL:
            return {'admin_search_index': cached[1]}

        if is_coach_only:
            items = _build_coach_search_index()
        else:
            items = _build_admin_search_index()

        _index_cache[cache_key] = (time.time(), items)
        return {'admin_search_index': items}
    except Exception:
        logger.exception("Admin search index build failed; search will be empty")
        return {'admin_search_index': []}


def _build_coach_search_index():
    """Search index for ECS FC Coach-only users."""
    from app.models.ecs_fc import get_ecs_fc_teams

    items = [
        # Check-in keywords live here: coaches 403 on match_check_in_index (see
        # check_in.py docstring) — their check-in surface is this dashboard.
        {'name': 'ECS FC Hub', 'category': 'ECS FC', 'description': 'ECS FC dashboard overview',
         'keywords': ['dashboard', 'home', 'check-in', 'attendance', 'qr'],
         'url': _safe_url('admin_panel.ecs_fc_dashboard'), 'icon': 'ti-dashboard'},
        {'name': 'All Matches', 'category': 'ECS FC', 'description': 'View and manage all ECS FC matches',
         'keywords': ['games', 'fixtures', 'results'], 'url': _safe_url('admin_panel.ecs_fc_matches'), 'icon': 'ti-list'},
        {'name': 'Opponents', 'category': 'ECS FC', 'description': 'Manage opponent teams library',
         'keywords': ['teams', 'rivals', 'library'], 'url': _safe_url('admin_panel.ecs_fc_opponents'), 'icon': 'ti-users-group'},
        {'name': 'Import Schedule', 'category': 'ECS FC', 'description': 'Import match schedules from file',
         'keywords': ['upload', 'csv', 'import'], 'url': _safe_url('admin_panel.ecs_fc_import'), 'icon': 'ti-file-import'},
        {'name': 'Substitute Pool', 'category': 'ECS FC', 'description': 'Manage ECS FC substitute player pool',
         'keywords': ['subs', 'reserves', 'bench'], 'url': _safe_url('admin_panel.substitute_pools', context='ecs-fc'), 'icon': 'ti-user-plus'},
    ]

    try:
        for team in get_ecs_fc_teams():
            items.append({
                'name': f'{team.name} Schedule', 'category': 'ECS FC', 'subcategory': 'Team Schedules',
                'description': f'View schedule for {team.name}',
                'keywords': ['calendar', 'fixtures', team.name.lower()],
                'url': _safe_url('admin_panel.ecs_fc_team_schedule', team_id=team.id), 'icon': 'ti-calendar',
            })
    except Exception:
        pass

    return [i for i in items if i['url']]


def _build_admin_search_index():
    """Full search index for admin users."""
    from app.models.ecs_fc import get_ecs_fc_teams

    items = [
        # Dashboard
        {'name': 'Dashboard', 'category': 'Dashboard', 'description': 'Admin panel overview and quick stats',
         'keywords': ['home', 'overview', 'stats', 'summary'], 'url': _safe_url('admin_panel.dashboard'), 'icon': 'ti-dashboard'},

        # --- Pub League: League Management ---
        {'name': 'Season Builder', 'category': 'Pub League', 'subcategory': 'League Management',
         'description': 'Create and configure new seasons with scheduling wizard',
         'keywords': ['schedule', 'wizard', 'create season', 'auto-schedule', 'new season'],
         'url': _safe_url('auto_schedule.schedule_manager'), 'icon': 'ti-wand'},
        {'name': 'Current Schedule', 'category': 'Pub League', 'subcategory': 'League Management',
         'description': 'View the current season schedule and matchdays',
         'keywords': ['calendar', 'fixtures', 'matchday', 'upcoming'],
         'url': _safe_url('auto_schedule.current_season_schedule'), 'icon': 'ti-calendar-event'},
        {'name': 'All Seasons', 'category': 'Pub League', 'subcategory': 'League Management',
         'description': 'Browse and manage all seasons',
         'keywords': ['history', 'past seasons', 'archive'],
         'url': _safe_url('admin_panel.league_management_seasons'), 'icon': 'ti-calendar-stats'},
        {'name': 'All Teams', 'category': 'Pub League', 'subcategory': 'League Management',
         'description': 'View and manage all teams across leagues',
         'keywords': ['rosters', 'squads', 'clubs'],
         'url': _safe_url('admin_panel.league_management_teams'), 'icon': 'ti-shirt-sport'},
        {'name': 'Coach Dashboard', 'category': 'Pub League', 'subcategory': 'League Management',
         'description': 'Coach-specific dashboard and tools',
         'keywords': ['coaching', 'staff', 'team management'],
         'url': _safe_url('admin_panel.coach_dashboard'), 'icon': 'ti-clipboard-list'},

        # --- Pub League: Match Management ---
        {'name': 'Match Dashboard', 'category': 'Pub League', 'subcategory': 'Match Management',
         'description': 'Central hub for match operations and reporting',
         'keywords': ['games', 'fixtures', 'operations', 'match ops'],
         'url': _safe_url('admin_panel.match_operations'), 'icon': 'ti-dashboard'},
        {'name': 'Leagues', 'category': 'Pub League', 'subcategory': 'Match Management',
         'description': 'Manage league configurations and divisions',
         'keywords': ['divisions', 'tiers', 'competition'],
         'url': _safe_url('admin_panel.manage_leagues'), 'icon': 'ti-trophy'},
        {'name': 'Match Verification', 'category': 'Pub League', 'subcategory': 'Match Management',
         'description': 'Verify and approve submitted match results',
         'keywords': ['approve', 'confirm', 'results', 'scores', 'validate'],
         'url': _safe_url('admin_panel.match_verification'), 'icon': 'ti-check'},
        {'name': 'Live Reporting', 'category': 'Pub League', 'subcategory': 'Match Management',
         'description': 'Real-time match reporting and commentary',
         'keywords': ['live', 'real-time', 'commentary', 'broadcast'],
         'url': _safe_url('admin_panel.live_reporting_dashboard'), 'icon': 'ti-live-view'},
        {'name': 'Match Check-In', 'category': 'Pub League', 'subcategory': 'Match Management',
         'description': 'Generate venue QR codes and review attendance for upcoming matches',
         'keywords': ['check-in', 'attendance', 'qr', 'venue', 'roster', 'present', 'pitch'],
         'url': _safe_url('admin_panel.match_check_in_index'), 'icon': 'ti-qrcode'},

        # --- Pub League: Substitutes ---
        {'name': 'Manage Substitutes', 'category': 'Pub League', 'subcategory': 'Substitutes',
         'description': 'Handle substitute player requests and assignments',
         'keywords': ['subs', 'replacements', 'player swap'],
         'url': _safe_url('admin_panel.substitute_management'), 'icon': 'ti-user-plus'},
        {'name': 'Substitute Pools', 'category': 'Pub League', 'subcategory': 'Substitutes',
         'description': 'Manage pools of available substitute players',
         'keywords': ['available subs', 'bench', 'reserves', 'pool'],
         'url': _safe_url('admin_panel.substitute_pools'), 'icon': 'ti-users'},

        # --- Pub League: Draft ---
        {'name': 'Draft History', 'category': 'Pub League', 'subcategory': 'Draft',
         'description': 'View past draft results and picks',
         'keywords': ['past drafts', 'previous', 'archive'],
         'url': _safe_url('admin_panel.draft_history'), 'icon': 'ti-history'},
        {'name': 'Draft Predictions', 'category': 'Pub League', 'subcategory': 'Draft',
         'description': 'AI-powered draft prediction analytics',
         'keywords': ['forecast', 'analytics', 'ai', 'predict'],
         'url': _safe_url('draft_predictions.admin_dashboard'), 'icon': 'ti-chart-dots'},

        # --- Pub League: Pub League ---
        {'name': 'Pub League Orders', 'category': 'Pub League', 'subcategory': 'Pub League',
         'description': 'View and manage pub league registration orders',
         'keywords': ['registrations', 'payments', 'signups', 'orders'],
         'url': _safe_url('pub_league_orders_admin.orders_list'), 'icon': 'ti-receipt'},
        {'name': 'Season Pass QR Codes', 'category': 'Pub League', 'subcategory': 'Pub League',
         'description': 'Printable QR codes that send players into the pass checkout',
         'keywords': ['qr', 'buy', 'purchase', 'pre-season party', 'sign up', 'season pass', 'print'],
         'url': _safe_url('pub_league_orders_admin.buy_qr_print'), 'icon': 'ti-qrcode'},

        # --- MLS ---
        {'name': 'MLS Overview', 'category': 'MLS', 'description': 'MLS integration dashboard and status',
         'keywords': ['sounders', 'major league soccer', 'mls hub'],
         'url': _safe_url('admin_panel.mls_overview'), 'icon': 'ti-dashboard'},
        {'name': 'MLS Matches', 'category': 'MLS', 'description': 'View and manage MLS match data',
         'keywords': ['games', 'fixtures', 'mls schedule'],
         'url': _safe_url('admin_panel.mls_matches'), 'icon': 'ti-list'},
        {'name': 'MLS Task Monitoring', 'category': 'MLS', 'description': 'Monitor MLS data sync tasks',
         'keywords': ['jobs', 'celery', 'sync', 'background tasks'],
         'url': _safe_url('admin_panel.mls_task_monitoring'), 'icon': 'ti-list-check'},
        {'name': 'MLS Sessions', 'category': 'MLS', 'description': 'Manage MLS live reporting sessions',
         'keywords': ['live', 'streaming', 'broadcast'],
         'url': _safe_url('admin_panel.mls_sessions'), 'icon': 'ti-player-play'},
        {'name': 'MLS Settings', 'category': 'MLS', 'description': 'Configure MLS integration settings',
         'keywords': ['config', 'configuration', 'preferences', 'api'],
         'url': _safe_url('admin_panel.mls_settings'), 'icon': 'ti-settings'},

        # --- ECS FC ---
        {'name': 'ECS FC Hub', 'category': 'ECS FC', 'description': 'ECS FC management dashboard',
         'keywords': ['dashboard', 'home', 'ecs fc overview'],
         'url': _safe_url('admin_panel.ecs_fc_dashboard'), 'icon': 'ti-dashboard'},
        {'name': 'ECS FC All Matches', 'category': 'ECS FC', 'subcategory': 'Management',
         'description': 'View and manage all ECS FC matches',
         'keywords': ['games', 'fixtures', 'results'],
         'url': _safe_url('admin_panel.ecs_fc_matches'), 'icon': 'ti-list'},
        {'name': 'Opponents Library', 'category': 'ECS FC', 'subcategory': 'Management',
         'description': 'Manage opponent teams for ECS FC',
         'keywords': ['teams', 'rivals', 'opposition'],
         'url': _safe_url('admin_panel.ecs_fc_opponents'), 'icon': 'ti-users-group'},
        {'name': 'Import Schedule', 'category': 'ECS FC', 'subcategory': 'Management',
         'description': 'Import ECS FC match schedules from file',
         'keywords': ['upload', 'csv', 'import', 'bulk'],
         'url': _safe_url('admin_panel.ecs_fc_import'), 'icon': 'ti-file-import'},
        {'name': 'ECS FC Substitute Pool', 'category': 'ECS FC',
         'description': 'Manage ECS FC substitute player pool',
         'keywords': ['subs', 'reserves', 'bench', 'available'],
         'url': _safe_url('admin_panel.substitute_pools', context='ecs-fc'), 'icon': 'ti-user-plus'},

        # --- Discord ---
        {'name': 'Discord Hub', 'category': 'Discord', 'description': 'Discord integration overview and management',
         'keywords': ['discord overview', 'bot', 'server'],
         'url': _safe_url('admin_panel.discord_overview'), 'icon': 'ti-dashboard'},
        {'name': 'Discord Players', 'category': 'Discord', 'subcategory': 'Members',
         'description': 'View and manage Discord server members',
         'keywords': ['members', 'users', 'discord users'],
         'url': _safe_url('admin_panel.discord_players'), 'icon': 'ti-users'},
        {'name': 'Discord Onboarding', 'category': 'Discord', 'subcategory': 'Members',
         'description': 'Manage new member onboarding flow',
         'keywords': ['welcome', 'new members', 'setup', 'join'],
         'url': _safe_url('admin_panel.discord_onboarding'), 'icon': 'ti-user-plus'},
        {'name': 'Role Sync', 'category': 'Discord', 'subcategory': 'Roles & Sync',
         'description': 'Synchronize Discord roles with website roles',
         'keywords': ['sync', 'refresh', 'update roles', 'discord roles'],
         'url': _safe_url('admin_panel.discord_roles'), 'icon': 'ti-refresh'},
        {'name': 'Role Mapping', 'category': 'Discord', 'subcategory': 'Roles & Sync',
         'description': 'Map Discord roles to website permissions',
         'keywords': ['permissions', 'link', 'mapping', 'connect'],
         'url': _safe_url('admin_panel.discord_role_mapping'), 'icon': 'ti-link'},
        {'name': 'Bot Management', 'category': 'Discord', 'description': 'Configure and manage the Discord bot',
         'keywords': ['bot', 'commands', 'discord bot', 'slash commands', 'restart'],
         'url': _safe_url('admin_panel.discord_bot_management'), 'icon': 'ti-robot'},
        {'name': 'AI Prompt Config', 'category': 'Discord', 'subcategory': 'AI Commentary',
         'description': 'Configure AI-generated match commentary prompts',
         'keywords': ['ai', 'commentary', 'prompts', 'openai', 'chatgpt'],
         'url': _safe_url('ai_prompts.list_prompts'), 'icon': 'ti-brain'},

        # --- Apps & Engagement: Mobile App ---
        {'name': 'Mobile Features', 'category': 'Apps & Engagement', 'subcategory': 'Mobile App',
         'description': 'Manage mobile app feature availability',
         'keywords': ['app', 'pwa', 'mobile settings', 'features'],
         'url': _safe_url('admin_panel.mobile_features'), 'icon': 'ti-device-mobile'},
        {'name': 'Mobile Analytics', 'category': 'Apps & Engagement', 'subcategory': 'Mobile App',
         'description': 'View mobile app usage analytics and metrics',
         'keywords': ['stats', 'usage', 'installs', 'engagement'],
         'url': _safe_url('admin_panel.mobile_analytics'), 'icon': 'ti-chart-line'},
        {'name': 'Mobile Users', 'category': 'Apps & Engagement', 'subcategory': 'Mobile App',
         'description': 'View users who have installed the mobile app',
         'keywords': ['app users', 'installs', 'devices'],
         'url': _safe_url('admin_panel.mobile_users'), 'icon': 'ti-users'},
        {'name': 'Error Analytics', 'category': 'Apps & Engagement', 'subcategory': 'Mobile App',
         'description': 'Track and analyze mobile app errors',
         'keywords': ['bugs', 'crashes', 'errors', 'debugging'],
         'url': _safe_url('admin_panel.mobile_error_analytics'), 'icon': 'ti-bug'},

        # --- Apps & Engagement: Store ---
        {'name': 'Store Management', 'category': 'Apps & Engagement', 'subcategory': 'Store',
         'description': 'Manage the online store settings and configuration',
         'keywords': ['shop', 'e-commerce', 'store config'],
         'url': _safe_url('admin_panel.store_management'), 'icon': 'ti-shopping-cart'},
        {'name': 'Store Items', 'category': 'Apps & Engagement', 'subcategory': 'Store',
         'description': 'Manage store products and inventory',
         'keywords': ['products', 'merchandise', 'inventory', 'items'],
         'url': _safe_url('admin_panel.store_items'), 'icon': 'ti-package'},
        {'name': 'Store Orders', 'category': 'Apps & Engagement', 'subcategory': 'Store',
         'description': 'View and manage customer orders',
         'keywords': ['purchases', 'sales', 'fulfillment'],
         'url': _safe_url('admin_panel.store_orders'), 'icon': 'ti-list'},
        {'name': 'Store Analytics', 'category': 'Apps & Engagement', 'subcategory': 'Store',
         'description': 'View store sales and performance analytics',
         'keywords': ['revenue', 'sales stats', 'metrics'],
         'url': _safe_url('admin_panel.store_analytics'), 'icon': 'ti-chart-bar'},

        # --- Apps & Engagement: Engagement ---
        {'name': 'I-Spy Management', 'category': 'Apps & Engagement', 'subcategory': 'Engagement',
         'description': 'Manage I-Spy game challenges and submissions',
         'keywords': ['game', 'challenge', 'scavenger hunt', 'ispy'],
         'url': _safe_url('admin_panel.ispy_management'), 'icon': 'ti-eye'},
        {'name': 'I-Spy Analytics', 'category': 'Apps & Engagement', 'subcategory': 'Engagement',
         'description': 'View I-Spy game participation analytics',
         'keywords': ['game stats', 'participation', 'ispy stats'],
         'url': _safe_url('admin_panel.ispy_analytics'), 'icon': 'ti-chart-dots'},

        # --- Communications ---
        {'name': 'Communication Hub', 'category': 'Comms', 'description': 'Central hub for all communication tools',
         'keywords': ['messaging', 'notifications', 'channels'],
         'url': _safe_url('admin_panel.communication_hub'), 'icon': 'ti-message-circle'},
        {'name': 'Message Templates', 'category': 'Comms', 'description': 'Create and manage reusable message templates',
         'keywords': ['templates', 'email templates', 'sms templates', 'presets'],
         'url': _safe_url('admin_panel.message_templates'), 'icon': 'ti-template'},
        {'name': 'Push Notifications', 'category': 'Comms', 'description': 'Send and manage push notifications',
         'keywords': ['push', 'alerts', 'mobile notifications', 'web push'],
         'url': _safe_url('admin_panel.push_notifications'), 'icon': 'ti-bell'},
        {'name': 'Announcements', 'category': 'Comms', 'description': 'Create and manage site-wide announcements',
         'keywords': ['news', 'banner', 'announcement', 'notice'],
         'url': _safe_url('admin_panel.announcements'), 'icon': 'ti-speakerphone'},
        {'name': 'Scheduled Messages', 'category': 'Comms', 'description': 'View and manage scheduled message queue',
         'keywords': ['queue', 'scheduled', 'timed', 'future messages'],
         'url': _safe_url('admin_panel.scheduled_messages_queue'), 'icon': 'ti-clock'},
        {'name': 'Campaigns', 'category': 'Comms', 'description': 'Create and manage communication campaigns',
         'keywords': ['campaign', 'outreach', 'bulk messaging'],
         'url': _safe_url('admin_panel.campaigns_list'), 'icon': 'ti-broadcast'},
        {'name': 'Email Broadcasts', 'category': 'Comms', 'description': 'Send bulk email broadcasts to members',
         'keywords': ['email', 'mass email', 'newsletter', 'bulk email'],
         'url': _safe_url('admin_panel.email_broadcasts_list'), 'icon': 'ti-mail-forward'},
        {'name': 'Email Templates', 'category': 'Comms', 'description': 'Design and manage email templates',
         'keywords': ['email design', 'html email', 'template editor'],
         'url': _safe_url('admin_panel.email_templates_list'), 'icon': 'ti-template'},
        {'name': 'Notification Groups', 'category': 'Comms', 'description': 'Manage notification recipient groups',
         'keywords': ['groups', 'recipients', 'mailing lists', 'segments'],
         'url': _safe_url('admin_panel.notification_groups_list'), 'icon': 'ti-users-group'},
        {'name': 'Messaging Settings', 'category': 'Comms', 'description': 'Configure messaging system settings',
         'keywords': ['config', 'sms settings', 'email settings', 'twilio'],
         'url': _safe_url('admin_panel.messaging_settings'), 'icon': 'ti-settings'},

        # --- Users ---
        {'name': 'Users', 'category': 'Users', 'description': 'Browse, search, and manage all user accounts',
         'keywords': ['accounts', 'profiles', 'members', 'players', 'all users', 'user list', 'manage', 'search', 'find user', 'lookup'],
         'url': _safe_url('admin_panel.users_comprehensive'), 'icon': 'ti-users'},
        {'name': 'Approvals', 'category': 'Users', 'description': 'Review and approve pending user registrations',
         'keywords': ['pending', 'approve', 'registration', 'new users', 'verify'],
         'url': _safe_url('admin_panel.user_approvals'), 'icon': 'ti-user-check'},
        {'name': 'Waitlist', 'category': 'Users', 'description': 'Manage user registration waitlist',
         'keywords': ['queue', 'waiting', 'signup', 'waitlist'],
         'url': _safe_url('admin_panel.user_waitlist'), 'icon': 'ti-user-plus'},
        {'name': 'Roles', 'category': 'Users', 'description': 'Create and manage user roles and permissions',
         'keywords': ['permissions', 'access control', 'rbac', 'roles'],
         'url': _safe_url('admin_panel.roles_comprehensive'), 'icon': 'ti-shield'},
        {'name': 'Quick Profiles', 'category': 'Users', 'description': 'Manage quick profile entries for tryouts',
         'keywords': ['tryouts', 'quick profile', 'temporary', 'trial'],
         'url': _safe_url('admin_panel.quick_profiles_management'), 'icon': 'ti-id-badge'},
        {'name': 'User Analytics', 'category': 'Users', 'description': 'User registration and activity analytics',
         'keywords': ['analytics', 'user stats', 'growth', 'registrations'],
         'url': _safe_url('admin_panel.user_analytics'), 'icon': 'ti-chart-line'},
        {'name': 'Duplicate Detection', 'category': 'Users', 'description': 'Find and merge duplicate user accounts',
         'keywords': ['duplicates', 'merge', 'dedup', 'double accounts'],
         'url': _safe_url('admin_panel.duplicate_registrations'), 'icon': 'ti-copy'},

        # --- Pub League: Additional ---
        {'name': 'Team Rosters', 'category': 'Pub League', 'subcategory': 'Match Management',
         'description': 'View and manage team player rosters',
         'keywords': ['roster', 'squad', 'players', 'lineup'],
         'url': _safe_url('admin_panel.team_rosters'), 'icon': 'ti-list-details'},
        {'name': 'League History', 'category': 'Pub League', 'subcategory': 'League Management',
         'description': 'Browse historical league data and past seasons',
         'keywords': ['history', 'archive', 'past', 'records'],
         'url': _safe_url('admin_panel.league_management_history'), 'icon': 'ti-history'},

        # --- Reports & Exports ---
        {'name': 'Reports Hub', 'category': 'Reports', 'description': 'Central hub for data reports and Excel exports',
         'keywords': ['reports', 'export', 'excel', 'download', 'data', 'spreadsheet', 'xlsx'],
         'url': _safe_url('admin_panel.reports_center'), 'icon': 'ti-report-analytics'},
        {'name': 'Player Stats Export', 'category': 'Reports',
         'description': 'Export goals, assists, and cards (career or by season) to Excel',
         'keywords': ['stats', 'goals', 'assists', 'cards', 'export', 'excel', 'career', 'season'],
         'url': _safe_url('admin_panel.player_stats_report'), 'icon': 'ti-soccer-field'},
        {'name': 'Attendance Report', 'category': 'Reports',
         'description': 'Export RSVP response, attendance, and reliability per player',
         'keywords': ['attendance', 'rsvp', 'reliability', 'response rate', 'export'],
         'url': _safe_url('admin_panel.attendance_report'), 'icon': 'ti-calendar-check'},
        {'name': 'Player Movement Report', 'category': 'Reports',
         'description': 'Track Classic to Premier promotions and drops across seasons',
         'keywords': ['movement', 'promotion', 'relegation', 'classic', 'premier', 'transfers'],
         'url': _safe_url('admin_panel.movement_report'), 'icon': 'ti-arrows-up-down'},
        {'name': 'Retention Report', 'category': 'Reports',
         'description': 'New vs returning vs lapsed players, season over season',
         'keywords': ['retention', 'churn', 'returning', 'new players', 'lapsed'],
         'url': _safe_url('admin_panel.retention_report'), 'icon': 'ti-users-group'},
        {'name': 'Roster History Report', 'category': 'Reports',
         'description': "Each player's team-by-season timeline with roles",
         'keywords': ['roster', 'history', 'timeline', 'teams', 'seasons'],
         'url': _safe_url('admin_panel.roster_history_report'), 'icon': 'ti-history'},
        {'name': 'Leaderboards Report', 'category': 'Reports',
         'description': 'Top scorers, assists, and discipline by season or all-time',
         'keywords': ['leaderboard', 'golden boot', 'top scorers', 'discipline', 'ranking'],
         'url': _safe_url('admin_panel.leaderboards_report'), 'icon': 'ti-trophy'},
        {'name': 'Kit / Jersey Size Report', 'category': 'Reports',
         'description': 'Jersey-size counts per team/league for ordering kit',
         'keywords': ['jersey', 'kit', 'shirt', 'size', 'sizes', 'order', 'uniform'],
         'url': _safe_url('admin_panel.jersey_report'), 'icon': 'ti-shirt-sport'},
        {'name': 'Team Standings Report', 'category': 'Reports',
         'description': 'W/D/L, goals, goal difference, and points by season',
         'keywords': ['standings', 'table', 'points', 'wins', 'losses', 'league table'],
         'url': _safe_url('admin_panel.standings_report'), 'icon': 'ti-table'},
        {'name': 'Discipline Report', 'category': 'Reports',
         'description': 'Yellow/red cards per player broken down by reason',
         'keywords': ['discipline', 'cards', 'yellow', 'red', 'fouls', 'bookings'],
         'url': _safe_url('admin_panel.discipline_report'), 'icon': 'ti-cards'},
        {'name': 'Contactability Report', 'category': 'Reports',
         'description': 'SMS/phone/Discord reachability and profile freshness',
         'keywords': ['contact', 'sms', 'phone', 'discord', 'reach', 'comms', 'email'],
         'url': _safe_url('admin_panel.contactability_report'), 'icon': 'ti-address-book'},

        # --- System: Feedback & Logs ---
        {'name': 'Feedback', 'category': 'System', 'subcategory': 'Feedback & Logs',
         'description': 'View and manage user feedback submissions',
         'keywords': ['reviews', 'suggestions', 'complaints', 'user feedback', 'reports'],
         'url': _safe_url('admin_panel.feedback_list'), 'icon': 'ti-message'},
        {'name': 'Audit Logs', 'category': 'System', 'subcategory': 'Feedback & Logs',
         'description': 'View admin action audit trail and history',
         'keywords': ['logs', 'history', 'audit', 'trail', 'actions'],
         'url': _safe_url('admin_panel.audit_logs'), 'icon': 'ti-file-text'},

        # --- System: Monitoring ---
        {'name': 'Data Integrity', 'category': 'System', 'subcategory': 'Monitoring',
         'description': 'Detect roster, league, sub, coach, and approval conflicts that silently break Discord roles or stats',
         'keywords': ['integrity', 'conflicts', 'guards', 'roster', 'sub', 'approval', 'drift', 'consistency', 'discord roles'],
         'url': _safe_url('admin_panel.integrity_dashboard'), 'icon': 'ti-shield-check'},
        {'name': 'System Health', 'category': 'System', 'subcategory': 'Monitoring',
         'description': 'System health, service status, performance metrics, and diagnostics',
         'keywords': ['health', 'uptime', 'status', 'services', 'cpu', 'memory', 'disk', 'performance', 'monitoring'],
         'url': _safe_url('admin_panel.system_health_consolidated'), 'icon': 'ti-heartbeat'},
        {'name': 'Task Monitor', 'category': 'System', 'subcategory': 'Monitoring',
         'description': 'Monitor background task execution and Celery workers',
         'keywords': ['celery', 'tasks', 'background jobs', 'workers', 'queue'],
         'url': _safe_url('admin_panel.task_monitoring_page'), 'icon': 'ti-list-check'},

        # --- System: System ---
        {'name': 'Feature Toggles', 'category': 'System', 'subcategory': 'System',
         'description': 'Enable or disable system features and settings',
         'keywords': ['toggles', 'switches', 'enable', 'disable', 'feature flags', 'settings'],
         'url': _safe_url('admin_panel.feature_toggles'), 'icon': 'ti-toggle-left'},
        {'name': 'Security Dashboard', 'category': 'System', 'subcategory': 'System',
         'description': 'Security overview, login attempts, and threat monitoring',
         'keywords': ['security', 'login attempts', 'threats', '2fa', 'authentication'],
         'url': _safe_url('admin_panel.security_dashboard'), 'icon': 'ti-shield-check'},
        {'name': 'Theme Settings', 'category': 'System', 'subcategory': 'System',
         'description': 'Customize site theme colors and branding',
         'keywords': ['colors', 'branding', 'design', 'look', 'appearance', 'dark mode'],
         'url': _safe_url('admin_panel.appearance'), 'icon': 'ti-palette'},

        # --- System: Infrastructure ---
        {'name': 'Cache & Redis', 'category': 'System', 'subcategory': 'Infrastructure',
         'description': 'Cache operations, Redis connection pool, and memory management',
         'keywords': ['cache', 'clear cache', 'redis', 'flush', 'memory store', 'connection pool'],
         'url': _safe_url('admin_panel.cache_redis_consolidated'), 'icon': 'ti-database'},
        {'name': 'Docker Management', 'category': 'System', 'subcategory': 'Infrastructure',
         'description': 'View and manage Docker containers',
         'keywords': ['docker', 'containers', 'services', 'compose'],
         'url': _safe_url('admin_panel.docker_management'), 'icon': 'ti-box'},
        {'name': 'API Management', 'category': 'System', 'subcategory': 'Infrastructure',
         'description': 'Manage API keys and rate limits',
         'keywords': ['api keys', 'tokens', 'rate limit', 'endpoints'],
         'url': _safe_url('admin_panel.api_management'), 'icon': 'ti-api'},

        # --- Wallet ---
        {'name': 'Wallet Passes Overview', 'category': 'Apps & Engagement', 'subcategory': 'Wallet',
         'description': 'Manage Apple and Google Wallet pass generation and distribution',
         'keywords': ['wallet', 'apple', 'google', 'pass', 'pkpass', 'digital card', 'digital wallet'],
         'url': _safe_url('wallet_admin.wallet_management'), 'icon': 'ti-wallet'},
        {'name': 'Membership Passes', 'category': 'Apps & Engagement', 'subcategory': 'Wallet',
         'description': 'Browse, void, and reactivate issued wallet passes',
         'keywords': ['passes', 'membership', 'void', 'reactivate'],
         'url': _safe_url('wallet_admin.passes_list'), 'icon': 'ti-id'},
        {'name': 'Pass Scanner', 'category': 'Apps & Engagement', 'subcategory': 'Wallet',
         'description': 'Scan wallet passes for event check-in',
         'keywords': ['scanner', 'scan', 'qr', 'barcode', 'check in'],
         'url': _safe_url('wallet_admin.scanner'), 'icon': 'ti-scan'},
        {'name': 'Pass Check-Ins', 'category': 'Apps & Engagement', 'subcategory': 'Wallet',
         'description': 'View and export wallet pass check-in history',
         'keywords': ['check-ins', 'checkins', 'attendance', 'export'],
         'url': _safe_url('wallet_admin.checkins_list'), 'icon': 'ti-checkbox'},
        {'name': 'Player Eligibility', 'category': 'Apps & Engagement', 'subcategory': 'Wallet',
         'description': 'Manage player eligibility for wallet passes',
         'keywords': ['eligible', 'players', 'pass eligibility'],
         'url': _safe_url('wallet_admin.wallet_players'), 'icon': 'ti-user-cog'},
        {'name': 'Pass Studio', 'category': 'Apps & Engagement', 'subcategory': 'Wallet',
         'description': 'Design wallet pass appearance, fields, and sponsors',
         'keywords': ['pass studio', 'design', 'appearance', 'branding', 'wallet design'],
         'url': _safe_url('pass_studio.index'), 'icon': 'ti-brush'},
        {'name': 'Wallet Setup Wizard', 'category': 'Apps & Engagement', 'subcategory': 'Wallet',
         'description': 'Step-by-step wallet configuration: certificates, assets, templates',
         'keywords': ['wallet setup', 'wizard', 'certificates', 'configure wallet', 'config'],
         'url': _safe_url('wallet_config.setup_wizard'), 'icon': 'ti-wand'},
        {'name': 'Wallet Diagnostics', 'category': 'Apps & Engagement', 'subcategory': 'Wallet',
         'description': 'Diagnose wallet pass configuration issues',
         'keywords': ['wallet diagnostics', 'troubleshoot', 'pass errors'],
         'url': _safe_url('wallet_config.diagnostics'), 'icon': 'ti-stethoscope'},

        # --- System: AI Assistant ---
        {'name': 'AI Assistant', 'category': 'System', 'subcategory': 'AI',
         'description': 'AI assistant usage metrics, budget tracking, and configuration',
         'keywords': ['ai', 'assistant', 'claude', 'gpt', 'chatbot', 'help', 'budget', 'usage'],
         'url': _safe_url('ai_assistant.admin_metrics'), 'icon': 'ti-sparkles'},
    ]

    # Dynamic: ECS FC team schedules
    try:
        for team in get_ecs_fc_teams():
            items.append({
                'name': f'{team.name} Schedule', 'category': 'ECS FC', 'subcategory': 'Team Schedules',
                'description': f'View schedule for {team.name}',
                'keywords': ['calendar', 'fixtures', team.name.lower()],
                'url': _safe_url('admin_panel.ecs_fc_team_schedule', team_id=team.id), 'icon': 'ti-calendar',
            })
    except Exception:
        pass

    # Dynamic: individual feature toggles, deep-linked to their row on the
    # features page (#setting-<key> anchors). Results are cached per role-set
    # by the context processor, so this query runs at most once per TTL.
    try:
        from app.models.admin_config import AdminConfig
        from app.admin_panel.routes.dashboard import FEATURE_TOGGLE_CATEGORIES
        # Same category allowlist as the features page itself — rows outside it
        # (generated api_key_* secrets, stray 'general' rows, dedicated-page
        # settings) neither render there nor belong in search results.
        for setting in AdminConfig.query.filter(
                AdminConfig.is_enabled.is_(True),
                AdminConfig.category.in_(FEATURE_TOGGLE_CATEGORIES)).all():
            pretty_name = setting.key.replace('_', ' ').title()
            items.append({
                'name': pretty_name, 'category': 'System', 'subcategory': 'Feature Toggles',
                'description': setting.description or f'{pretty_name} setting',
                'keywords': ['feature', 'toggle', 'setting', setting.key,
                             setting.key.replace('_', ' '), (setting.category or '').lower()],
                'url': _safe_url('admin_panel.feature_toggles', _anchor=f'setting-{setting.key}'),
                'icon': 'ti-toggle-right',
            })
    except Exception:
        logger.warning("Admin search index: could not add feature toggle entries", exc_info=True)

    # Surveys link is optional — only advertise it if the route registered, so a
    # missing module can't blank out the whole search index via a BuildError.
    if 'admin_panel.surveys_list' in current_app.view_functions:
        items.append({
            'name': 'Surveys & Polls', 'category': 'Comms',
            'description': 'Build surveys/polls, collect responses, view metrics',
            'keywords': ['survey', 'poll', 'questionnaire', 'feedback', 'form', 'end of season', 'vote'],
            'url': _safe_url('admin_panel.surveys_list'), 'icon': 'ti-clipboard-list',
        })

    return [i for i in items if i['url']]


# Import modular routes after blueprint creation to avoid circular imports
from .routes import register_all_routes

# Register all route modules
register_all_routes(admin_panel_bp)