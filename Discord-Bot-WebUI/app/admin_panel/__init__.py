# app/admin_panel/__init__.py

"""
Admin Panel Module

This module provides a centralized admin panel for global administrators
to manage application settings, features, and configurations.
"""

from flask import Blueprint, url_for

# Create the admin panel blueprint
admin_panel_bp = Blueprint(
    'admin_panel',
    __name__,
    url_prefix='/admin-panel'
)


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
def inject_nav_counts():
    """Inject pending approval and waitlist counts for navigation badges."""
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


@admin_panel_bp.context_processor
def inject_admin_search_index():
    """Build a searchable index of all admin panel pages for universal search."""
    try:
        from app.role_impersonation import get_effective_roles
        user_roles = get_effective_roles()
        is_coach_only = 'ECS FC Coach' in user_roles and 'Global Admin' not in user_roles and 'Pub League Admin' not in user_roles

        if is_coach_only:
            items = _build_coach_search_index()
        else:
            items = _build_admin_search_index()

        return {'admin_search_index': items}
    except Exception:
        return {'admin_search_index': []}


def _build_coach_search_index():
    """Search index for ECS FC Coach-only users."""
    from app.models.ecs_fc import get_ecs_fc_teams

    items = [
        {'name': 'ECS FC Hub', 'category': 'ECS FC', 'description': 'ECS FC dashboard overview',
         'keywords': ['dashboard', 'home'], 'url': url_for('admin_panel.ecs_fc_dashboard'), 'icon': 'ti-dashboard'},
        {'name': 'All Matches', 'category': 'ECS FC', 'description': 'View and manage all ECS FC matches',
         'keywords': ['games', 'fixtures', 'results'], 'url': url_for('admin_panel.ecs_fc_matches'), 'icon': 'ti-list'},
        {'name': 'Opponents', 'category': 'ECS FC', 'description': 'Manage opponent teams library',
         'keywords': ['teams', 'rivals', 'library'], 'url': url_for('admin_panel.ecs_fc_opponents'), 'icon': 'ti-users-group'},
        {'name': 'Import Schedule', 'category': 'ECS FC', 'description': 'Import match schedules from file',
         'keywords': ['upload', 'csv', 'import'], 'url': url_for('admin_panel.ecs_fc_import'), 'icon': 'ti-file-import'},
        {'name': 'Substitute Pool', 'category': 'ECS FC', 'description': 'Manage ECS FC substitute player pool',
         'keywords': ['subs', 'reserves', 'bench'], 'url': url_for('admin_panel.substitute_pools', context='ecs-fc'), 'icon': 'ti-user-plus'},
    ]

    try:
        for team in get_ecs_fc_teams():
            items.append({
                'name': f'{team.name} Schedule', 'category': 'ECS FC', 'subcategory': 'Team Schedules',
                'description': f'View schedule for {team.name}',
                'keywords': ['calendar', 'fixtures', team.name.lower()],
                'url': url_for('admin_panel.ecs_fc_team_schedule', team_id=team.id), 'icon': 'ti-calendar',
            })
    except Exception:
        pass

    return items


def _build_admin_search_index():
    """Full search index for admin users."""
    from app.models.ecs_fc import get_ecs_fc_teams

    items = [
        # Dashboard
        {'name': 'Dashboard', 'category': 'Dashboard', 'description': 'Admin panel overview and quick stats',
         'keywords': ['home', 'overview', 'stats', 'summary'], 'url': url_for('admin_panel.dashboard'), 'icon': 'ti-dashboard'},

        # --- Pub League: League Management ---
        {'name': 'Season Builder', 'category': 'Pub League', 'subcategory': 'League Management',
         'description': 'Create and configure new seasons with scheduling wizard',
         'keywords': ['schedule', 'wizard', 'create season', 'auto-schedule', 'new season'],
         'url': url_for('auto_schedule.schedule_manager'), 'icon': 'ti-wand'},
        {'name': 'Current Schedule', 'category': 'Pub League', 'subcategory': 'League Management',
         'description': 'View the current season schedule and matchdays',
         'keywords': ['calendar', 'fixtures', 'matchday', 'upcoming'],
         'url': url_for('auto_schedule.current_season_schedule'), 'icon': 'ti-calendar-event'},
        {'name': 'All Seasons', 'category': 'Pub League', 'subcategory': 'League Management',
         'description': 'Browse and manage all seasons',
         'keywords': ['history', 'past seasons', 'archive'],
         'url': url_for('admin_panel.league_management_seasons'), 'icon': 'ti-calendar-stats'},
        {'name': 'All Teams', 'category': 'Pub League', 'subcategory': 'League Management',
         'description': 'View and manage all teams across leagues',
         'keywords': ['rosters', 'squads', 'clubs'],
         'url': url_for('admin_panel.league_management_teams'), 'icon': 'ti-shirt-sport'},
        {'name': 'Coach Dashboard', 'category': 'Pub League', 'subcategory': 'League Management',
         'description': 'Coach-specific dashboard and tools',
         'keywords': ['coaching', 'staff', 'team management'],
         'url': url_for('admin_panel.coach_dashboard'), 'icon': 'ti-clipboard-list'},

        # --- Pub League: Match Management ---
        {'name': 'Match Dashboard', 'category': 'Pub League', 'subcategory': 'Match Management',
         'description': 'Central hub for match operations and reporting',
         'keywords': ['games', 'fixtures', 'operations', 'match ops'],
         'url': url_for('admin_panel.match_operations'), 'icon': 'ti-dashboard'},
        {'name': 'Leagues', 'category': 'Pub League', 'subcategory': 'Match Management',
         'description': 'Manage league configurations and divisions',
         'keywords': ['divisions', 'tiers', 'competition'],
         'url': url_for('admin_panel.manage_leagues'), 'icon': 'ti-trophy'},
        {'name': 'Match Verification', 'category': 'Pub League', 'subcategory': 'Match Management',
         'description': 'Verify and approve submitted match results',
         'keywords': ['approve', 'confirm', 'results', 'scores', 'validate'],
         'url': url_for('admin_panel.match_verification'), 'icon': 'ti-check'},
        {'name': 'Live Reporting', 'category': 'Pub League', 'subcategory': 'Match Management',
         'description': 'Real-time match reporting and commentary',
         'keywords': ['live', 'real-time', 'commentary', 'broadcast'],
         'url': url_for('admin_panel.live_reporting_dashboard'), 'icon': 'ti-live-view'},

        # --- Pub League: Substitutes ---
        {'name': 'Manage Substitutes', 'category': 'Pub League', 'subcategory': 'Substitutes',
         'description': 'Handle substitute player requests and assignments',
         'keywords': ['subs', 'replacements', 'player swap'],
         'url': url_for('admin_panel.substitute_management'), 'icon': 'ti-user-plus'},
        {'name': 'Substitute Pools', 'category': 'Pub League', 'subcategory': 'Substitutes',
         'description': 'Manage pools of available substitute players',
         'keywords': ['available subs', 'bench', 'reserves', 'pool'],
         'url': url_for('admin_panel.substitute_pools'), 'icon': 'ti-users'},

        # --- Pub League: Draft ---
        {'name': 'Draft Overview', 'category': 'Pub League', 'subcategory': 'Draft',
         'description': 'Overview of player draft status and board',
         'keywords': ['picks', 'selections', 'draft board'],
         'url': url_for('admin_panel.draft_overview'), 'icon': 'ti-layout-grid'},
        {'name': 'Draft History', 'category': 'Pub League', 'subcategory': 'Draft',
         'description': 'View past draft results and picks',
         'keywords': ['past drafts', 'previous', 'archive'],
         'url': url_for('admin_panel.draft_history'), 'icon': 'ti-history'},
        {'name': 'Draft Predictions', 'category': 'Pub League', 'subcategory': 'Draft',
         'description': 'AI-powered draft prediction analytics',
         'keywords': ['forecast', 'analytics', 'ai', 'predict'],
         'url': url_for('draft_predictions.admin_dashboard'), 'icon': 'ti-chart-dots'},

        # --- Pub League: Pub League ---
        {'name': 'Pub League Orders', 'category': 'Pub League', 'subcategory': 'Pub League',
         'description': 'View and manage pub league registration orders',
         'keywords': ['registrations', 'payments', 'signups', 'orders'],
         'url': url_for('pub_league_orders_admin.orders_list'), 'icon': 'ti-receipt'},

        # --- MLS ---
        {'name': 'MLS Overview', 'category': 'MLS', 'description': 'MLS integration dashboard and status',
         'keywords': ['sounders', 'major league soccer', 'mls hub'],
         'url': url_for('admin_panel.mls_overview'), 'icon': 'ti-dashboard'},
        {'name': 'MLS Matches', 'category': 'MLS', 'description': 'View and manage MLS match data',
         'keywords': ['games', 'fixtures', 'mls schedule'],
         'url': url_for('admin_panel.mls_matches'), 'icon': 'ti-list'},
        {'name': 'MLS Task Monitoring', 'category': 'MLS', 'description': 'Monitor MLS data sync tasks',
         'keywords': ['jobs', 'celery', 'sync', 'background tasks'],
         'url': url_for('admin_panel.mls_task_monitoring'), 'icon': 'ti-list-check'},
        {'name': 'MLS Sessions', 'category': 'MLS', 'description': 'Manage MLS live reporting sessions',
         'keywords': ['live', 'streaming', 'broadcast'],
         'url': url_for('admin_panel.mls_sessions'), 'icon': 'ti-player-play'},
        {'name': 'MLS Settings', 'category': 'MLS', 'description': 'Configure MLS integration settings',
         'keywords': ['config', 'configuration', 'preferences', 'api'],
         'url': url_for('admin_panel.mls_settings'), 'icon': 'ti-settings'},

        # --- ECS FC ---
        {'name': 'ECS FC Hub', 'category': 'ECS FC', 'description': 'ECS FC management dashboard',
         'keywords': ['dashboard', 'home', 'ecs fc overview'],
         'url': url_for('admin_panel.ecs_fc_dashboard'), 'icon': 'ti-dashboard'},
        {'name': 'ECS FC All Matches', 'category': 'ECS FC', 'subcategory': 'Management',
         'description': 'View and manage all ECS FC matches',
         'keywords': ['games', 'fixtures', 'results'],
         'url': url_for('admin_panel.ecs_fc_matches'), 'icon': 'ti-list'},
        {'name': 'Opponents Library', 'category': 'ECS FC', 'subcategory': 'Management',
         'description': 'Manage opponent teams for ECS FC',
         'keywords': ['teams', 'rivals', 'opposition'],
         'url': url_for('admin_panel.ecs_fc_opponents'), 'icon': 'ti-users-group'},
        {'name': 'Import Schedule', 'category': 'ECS FC', 'subcategory': 'Management',
         'description': 'Import ECS FC match schedules from file',
         'keywords': ['upload', 'csv', 'import', 'bulk'],
         'url': url_for('admin_panel.ecs_fc_import'), 'icon': 'ti-file-import'},
        {'name': 'ECS FC Substitute Pool', 'category': 'ECS FC',
         'description': 'Manage ECS FC substitute player pool',
         'keywords': ['subs', 'reserves', 'bench', 'available'],
         'url': url_for('admin_panel.substitute_pools', context='ecs-fc'), 'icon': 'ti-user-plus'},

        # --- Discord ---
        {'name': 'Discord Hub', 'category': 'Discord', 'description': 'Discord integration overview and management',
         'keywords': ['discord overview', 'bot', 'server'],
         'url': url_for('admin_panel.discord_overview'), 'icon': 'ti-dashboard'},
        {'name': 'Discord Players', 'category': 'Discord', 'subcategory': 'Members',
         'description': 'View and manage Discord server members',
         'keywords': ['members', 'users', 'discord users'],
         'url': url_for('admin_panel.discord_players'), 'icon': 'ti-users'},
        {'name': 'Discord Onboarding', 'category': 'Discord', 'subcategory': 'Members',
         'description': 'Manage new member onboarding flow',
         'keywords': ['welcome', 'new members', 'setup', 'join'],
         'url': url_for('admin_panel.discord_onboarding'), 'icon': 'ti-user-plus'},
        {'name': 'Role Sync', 'category': 'Discord', 'subcategory': 'Roles & Sync',
         'description': 'Synchronize Discord roles with website roles',
         'keywords': ['sync', 'refresh', 'update roles', 'discord roles'],
         'url': url_for('admin_panel.discord_roles'), 'icon': 'ti-refresh'},
        {'name': 'Role Mapping', 'category': 'Discord', 'subcategory': 'Roles & Sync',
         'description': 'Map Discord roles to website permissions',
         'keywords': ['permissions', 'link', 'mapping', 'connect'],
         'url': url_for('admin_panel.discord_role_mapping'), 'icon': 'ti-link'},
        {'name': 'Bot Management', 'category': 'Discord', 'description': 'Configure and manage the Discord bot',
         'keywords': ['bot', 'commands', 'discord bot', 'slash commands', 'restart'],
         'url': url_for('admin_panel.discord_bot_management'), 'icon': 'ti-robot'},
        {'name': 'AI Prompt Config', 'category': 'Discord', 'subcategory': 'AI Commentary',
         'description': 'Configure AI-generated match commentary prompts',
         'keywords': ['ai', 'commentary', 'prompts', 'openai', 'chatgpt'],
         'url': url_for('ai_prompts.list_prompts'), 'icon': 'ti-brain'},

        # --- Apps & Engagement: Mobile App ---
        {'name': 'Mobile Features', 'category': 'Apps & Engagement', 'subcategory': 'Mobile App',
         'description': 'Manage mobile app feature availability',
         'keywords': ['app', 'pwa', 'mobile settings', 'features'],
         'url': url_for('admin_panel.mobile_features'), 'icon': 'ti-device-mobile'},
        {'name': 'Mobile Analytics', 'category': 'Apps & Engagement', 'subcategory': 'Mobile App',
         'description': 'View mobile app usage analytics and metrics',
         'keywords': ['stats', 'usage', 'installs', 'engagement'],
         'url': url_for('admin_panel.mobile_analytics'), 'icon': 'ti-chart-line'},
        {'name': 'Mobile Users', 'category': 'Apps & Engagement', 'subcategory': 'Mobile App',
         'description': 'View users who have installed the mobile app',
         'keywords': ['app users', 'installs', 'devices'],
         'url': url_for('admin_panel.mobile_users'), 'icon': 'ti-users'},
        {'name': 'Error Analytics', 'category': 'Apps & Engagement', 'subcategory': 'Mobile App',
         'description': 'Track and analyze mobile app errors',
         'keywords': ['bugs', 'crashes', 'errors', 'debugging'],
         'url': url_for('admin_panel.mobile_error_analytics'), 'icon': 'ti-bug'},

        # --- Apps & Engagement: Store ---
        {'name': 'Store Management', 'category': 'Apps & Engagement', 'subcategory': 'Store',
         'description': 'Manage the online store settings and configuration',
         'keywords': ['shop', 'e-commerce', 'store config'],
         'url': url_for('admin_panel.store_management'), 'icon': 'ti-shopping-cart'},
        {'name': 'Store Items', 'category': 'Apps & Engagement', 'subcategory': 'Store',
         'description': 'Manage store products and inventory',
         'keywords': ['products', 'merchandise', 'inventory', 'items'],
         'url': url_for('admin_panel.store_items'), 'icon': 'ti-package'},
        {'name': 'Store Orders', 'category': 'Apps & Engagement', 'subcategory': 'Store',
         'description': 'View and manage customer orders',
         'keywords': ['purchases', 'sales', 'fulfillment'],
         'url': url_for('admin_panel.store_orders'), 'icon': 'ti-list'},
        {'name': 'Store Analytics', 'category': 'Apps & Engagement', 'subcategory': 'Store',
         'description': 'View store sales and performance analytics',
         'keywords': ['revenue', 'sales stats', 'metrics'],
         'url': url_for('admin_panel.store_analytics'), 'icon': 'ti-chart-bar'},

        # --- Apps & Engagement: Engagement ---
        {'name': 'I-Spy Management', 'category': 'Apps & Engagement', 'subcategory': 'Engagement',
         'description': 'Manage I-Spy game challenges and submissions',
         'keywords': ['game', 'challenge', 'scavenger hunt', 'ispy'],
         'url': url_for('admin_panel.ispy_management'), 'icon': 'ti-eye'},
        {'name': 'I-Spy Analytics', 'category': 'Apps & Engagement', 'subcategory': 'Engagement',
         'description': 'View I-Spy game participation analytics',
         'keywords': ['game stats', 'participation', 'ispy stats'],
         'url': url_for('admin_panel.ispy_analytics'), 'icon': 'ti-chart-dots'},

        # --- Communications ---
        {'name': 'Communication Hub', 'category': 'Comms', 'description': 'Central hub for all communication tools',
         'keywords': ['messaging', 'notifications', 'channels'],
         'url': url_for('admin_panel.communication_hub'), 'icon': 'ti-message-circle'},
        {'name': 'Message Templates', 'category': 'Comms', 'description': 'Create and manage reusable message templates',
         'keywords': ['templates', 'email templates', 'sms templates', 'presets'],
         'url': url_for('admin_panel.message_templates'), 'icon': 'ti-template'},
        {'name': 'Push Notifications', 'category': 'Comms', 'description': 'Send and manage push notifications',
         'keywords': ['push', 'alerts', 'mobile notifications', 'web push'],
         'url': url_for('admin_panel.push_notifications'), 'icon': 'ti-bell'},
        {'name': 'Announcements', 'category': 'Comms', 'description': 'Create and manage site-wide announcements',
         'keywords': ['news', 'banner', 'announcement', 'notice'],
         'url': url_for('admin_panel.announcements'), 'icon': 'ti-speakerphone'},
        {'name': 'Scheduled Messages', 'category': 'Comms', 'description': 'View and manage scheduled message queue',
         'keywords': ['queue', 'scheduled', 'timed', 'future messages'],
         'url': url_for('admin_panel.scheduled_messages_queue'), 'icon': 'ti-clock'},
        {'name': 'Campaigns', 'category': 'Comms', 'description': 'Create and manage communication campaigns',
         'keywords': ['campaign', 'outreach', 'bulk messaging'],
         'url': url_for('admin_panel.campaigns_list'), 'icon': 'ti-broadcast'},
        {'name': 'Email Broadcasts', 'category': 'Comms', 'description': 'Send bulk email broadcasts to members',
         'keywords': ['email', 'mass email', 'newsletter', 'bulk email'],
         'url': url_for('admin_panel.email_broadcasts_list'), 'icon': 'ti-mail-forward'},
        {'name': 'Email Templates', 'category': 'Comms', 'description': 'Design and manage email templates',
         'keywords': ['email design', 'html email', 'template editor'],
         'url': url_for('admin_panel.email_templates_list'), 'icon': 'ti-template'},
        {'name': 'Notification Groups', 'category': 'Comms', 'description': 'Manage notification recipient groups',
         'keywords': ['groups', 'recipients', 'mailing lists', 'segments'],
         'url': url_for('admin_panel.notification_groups_list'), 'icon': 'ti-users-group'},
        {'name': 'Messaging Settings', 'category': 'Comms', 'description': 'Configure messaging system settings',
         'keywords': ['config', 'sms settings', 'email settings', 'twilio'],
         'url': url_for('admin_panel.messaging_settings'), 'icon': 'ti-settings'},

        # --- Users ---
        {'name': 'Users', 'category': 'Users', 'description': 'Browse, search, and manage all user accounts',
         'keywords': ['accounts', 'profiles', 'members', 'players', 'all users', 'user list', 'manage', 'search', 'find user', 'lookup'],
         'url': url_for('admin_panel.users_comprehensive'), 'icon': 'ti-users'},
        {'name': 'Approvals', 'category': 'Users', 'description': 'Review and approve pending user registrations',
         'keywords': ['pending', 'approve', 'registration', 'new users', 'verify'],
         'url': url_for('admin_panel.user_approvals'), 'icon': 'ti-user-check'},
        {'name': 'Waitlist', 'category': 'Users', 'description': 'Manage user registration waitlist',
         'keywords': ['queue', 'waiting', 'signup', 'waitlist'],
         'url': url_for('admin_panel.user_waitlist'), 'icon': 'ti-user-plus'},
        {'name': 'Roles', 'category': 'Users', 'description': 'Create and manage user roles and permissions',
         'keywords': ['permissions', 'access control', 'rbac', 'roles'],
         'url': url_for('admin_panel.roles_comprehensive'), 'icon': 'ti-shield'},
        {'name': 'Quick Profiles', 'category': 'Users', 'description': 'Manage quick profile entries for tryouts',
         'keywords': ['tryouts', 'quick profile', 'temporary', 'trial'],
         'url': url_for('admin_panel.quick_profiles_management'), 'icon': 'ti-id-badge'},
        {'name': 'User Analytics', 'category': 'Users', 'description': 'User registration and activity analytics',
         'keywords': ['analytics', 'user stats', 'growth', 'registrations'],
         'url': url_for('admin_panel.user_analytics'), 'icon': 'ti-chart-line'},
        {'name': 'Duplicate Detection', 'category': 'Users', 'description': 'Find and merge duplicate user accounts',
         'keywords': ['duplicates', 'merge', 'dedup', 'double accounts'],
         'url': url_for('admin_panel.duplicate_registrations'), 'icon': 'ti-copy'},

        # --- Pub League: Additional ---
        {'name': 'Team Rosters', 'category': 'Pub League', 'subcategory': 'Match Management',
         'description': 'View and manage team player rosters',
         'keywords': ['roster', 'squad', 'players', 'lineup'],
         'url': url_for('admin_panel.team_rosters'), 'icon': 'ti-list-details'},
        {'name': 'League History', 'category': 'Pub League', 'subcategory': 'League Management',
         'description': 'Browse historical league data and past seasons',
         'keywords': ['history', 'archive', 'past', 'records'],
         'url': url_for('admin_panel.league_history'), 'icon': 'ti-history'},

        # --- System: Reports ---
        {'name': 'Reports Dashboard', 'category': 'System', 'subcategory': 'Reports',
         'description': 'View admin reports and analytics overview',
         'keywords': ['analytics', 'stats', 'data', 'metrics'],
         'url': url_for('admin_panel.reports_dashboard'), 'icon': 'ti-file-analytics'},
        {'name': 'Feedback', 'category': 'System', 'subcategory': 'Reports',
         'description': 'View and manage user feedback submissions',
         'keywords': ['reviews', 'suggestions', 'complaints', 'user feedback'],
         'url': url_for('admin_panel.feedback_list'), 'icon': 'ti-message'},

        # --- System: Appearance ---
        {'name': 'Theme Settings', 'category': 'System', 'subcategory': 'Appearance',
         'description': 'Customize site theme colors and branding',
         'keywords': ['colors', 'branding', 'design', 'look', 'appearance', 'dark mode'],
         'url': url_for('admin_panel.appearance'), 'icon': 'ti-palette'},

        # --- System: System ---
        {'name': 'Feature Toggles', 'category': 'System', 'subcategory': 'System',
         'description': 'Enable or disable system features and settings',
         'keywords': ['toggles', 'switches', 'enable', 'disable', 'feature flags', 'settings'],
         'url': url_for('admin_panel.feature_toggles'), 'icon': 'ti-toggle-left'},
        {'name': 'System Monitoring', 'category': 'System', 'subcategory': 'System',
         'description': 'Monitor system information and resource usage',
         'keywords': ['system info', 'cpu', 'memory', 'disk', 'server'],
         'url': url_for('admin_panel.system_monitoring'), 'icon': 'ti-activity'},
        {'name': 'Cache Management', 'category': 'System', 'subcategory': 'System',
         'description': 'View and clear application caches',
         'keywords': ['cache', 'clear cache', 'redis', 'flush'],
         'url': url_for('admin_panel.cache_management'), 'icon': 'ti-database'},
        {'name': 'API Management', 'category': 'System', 'subcategory': 'System',
         'description': 'Manage API keys and rate limits',
         'keywords': ['api keys', 'tokens', 'rate limit', 'endpoints'],
         'url': url_for('admin_panel.api_management'), 'icon': 'ti-api'},
        {'name': 'System Health', 'category': 'System', 'subcategory': 'System',
         'description': 'Service health checks and uptime monitoring',
         'keywords': ['health', 'uptime', 'status', 'services', 'ping'],
         'url': url_for('admin_panel.health_dashboard'), 'icon': 'ti-heartbeat'},
        {'name': 'Redis Management', 'category': 'System', 'subcategory': 'System',
         'description': 'Monitor and manage Redis database',
         'keywords': ['redis', 'cache', 'queue', 'memory store'],
         'url': url_for('admin_panel.redis_management'), 'icon': 'ti-database'},
        {'name': 'Docker Management', 'category': 'System', 'subcategory': 'System',
         'description': 'View and manage Docker containers',
         'keywords': ['docker', 'containers', 'services', 'compose'],
         'url': url_for('admin_panel.docker_management'), 'icon': 'ti-box'},
        {'name': 'Performance Monitor', 'category': 'System', 'subcategory': 'System',
         'description': 'Track application performance metrics',
         'keywords': ['performance', 'speed', 'latency', 'response time'],
         'url': url_for('admin_panel.performance_monitoring'), 'icon': 'ti-chart-line'},
        {'name': 'Security Dashboard', 'category': 'System', 'subcategory': 'System',
         'description': 'Security overview, login attempts, and threat monitoring',
         'keywords': ['security', 'login attempts', 'threats', '2fa', 'authentication'],
         'url': url_for('admin_panel.security_dashboard'), 'icon': 'ti-shield-check'},
        {'name': 'Task Monitor', 'category': 'System', 'subcategory': 'System',
         'description': 'Monitor background task execution and Celery workers',
         'keywords': ['celery', 'tasks', 'background jobs', 'workers', 'queue'],
         'url': url_for('admin_panel.task_monitoring_page'), 'icon': 'ti-list-check'},
        {'name': 'Audit Logs', 'category': 'System', 'subcategory': 'System',
         'description': 'View admin action audit trail and history',
         'keywords': ['logs', 'history', 'audit', 'trail', 'actions'],
         'url': url_for('admin_panel.audit_logs'), 'icon': 'ti-file-text'},

        # --- Wallet ---
        {'name': 'Apple Wallet Passes', 'category': 'Apps & Engagement', 'subcategory': 'Wallet',
         'description': 'Manage Apple Wallet pass generation and distribution',
         'keywords': ['wallet', 'apple', 'pass', 'pkpass', 'digital card'],
         'url': url_for('wallet_admin.wallet_management'), 'icon': 'ti-wallet'},
        {'name': 'Player Eligibility', 'category': 'Apps & Engagement', 'subcategory': 'Wallet',
         'description': 'Manage player eligibility for wallet passes',
         'keywords': ['eligible', 'players', 'pass eligibility'],
         'url': url_for('wallet_admin.wallet_players'), 'icon': 'ti-user-cog'},
        {'name': 'Wallet Configuration', 'category': 'Apps & Engagement', 'subcategory': 'Wallet',
         'description': 'Configure wallet pass templates and settings',
         'keywords': ['wallet settings', 'pass template', 'config'],
         'url': url_for('wallet_admin.wallet_config'), 'icon': 'ti-settings-2'},

        # --- System: AI Assistant ---
        {'name': 'AI Assistant', 'category': 'System', 'subcategory': 'AI',
         'description': 'AI assistant usage metrics, budget tracking, and configuration',
         'keywords': ['ai', 'assistant', 'claude', 'gpt', 'chatbot', 'help', 'budget', 'usage'],
         'url': url_for('ai_assistant.admin_metrics'), 'icon': 'ti-sparkles'},
    ]

    # Dynamic: ECS FC team schedules
    try:
        for team in get_ecs_fc_teams():
            items.append({
                'name': f'{team.name} Schedule', 'category': 'ECS FC', 'subcategory': 'Team Schedules',
                'description': f'View schedule for {team.name}',
                'keywords': ['calendar', 'fixtures', team.name.lower()],
                'url': url_for('admin_panel.ecs_fc_team_schedule', team_id=team.id), 'icon': 'ti-calendar',
            })
    except Exception:
        pass

    return items


# Import modular routes after blueprint creation to avoid circular imports
from .routes import register_all_routes

# Register all route modules
register_all_routes(admin_panel_bp)