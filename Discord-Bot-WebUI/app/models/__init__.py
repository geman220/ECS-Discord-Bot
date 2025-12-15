# app/models/__init__.py

"""
Models Package

This package provides a unified interface to all database models while maintaining
backward compatibility with existing imports. All models are organized into logical
modules but can still be imported from the main models package.

Usage:
    from app.models import User, Player, Team  # Works as before
    from app.models.core import User  # Also works
"""

# Import db from core for backward compatibility
from app.core import db

# Import all models from their respective modules
from .core import (
    League, User, Role, Permission, Season, DuplicateRegistrationAlert,
    user_roles, role_permissions
)

from .players import (
    Team, Player, PlayerOrderHistory, PlayerTeamSeason, 
    PlayerTeamHistory, PlayerImageCache,
    player_league, player_teams
)

from .matches import (
    Schedule, Match, Availability, TemporarySubAssignment,
    AutoScheduleConfig, ScheduleTemplate, WeekConfiguration, SeasonConfiguration
)

from .stats import (
    PlayerSeasonStats, PlayerCareerStats, Standings, StatChangeLog,
    PlayerAttendanceStats, PlayerEventType, PlayerEvent, 
    StatChangeType, PlayerStatAudit
)

from .communication import (
    Notification, Announcement, ScheduledMessage, Feedback,
    FeedbackReply, Note, DeviceToken
)

from .notifications import (
    UserFCMToken
)

from .push_campaigns import (
    NotificationGroup, NotificationGroupMember, PushNotificationCampaign,
    GroupType, CampaignStatus, CampaignPriority, TargetType
)

from .store import (
    StoreItem, StoreOrder
)

from .external import (
    Token, MLSMatch, Progress, HelpTopic, Prediction,
    help_topic_roles
)

from .live_reporting_session import (
    LiveReportingSession
)

from .scheduled_task import (
    ScheduledTask, TaskType, TaskState
)

from .match_status import (
    MatchStatus
)

from .ecs_fc import (
    EcsFcMatch, EcsFcAvailability, EcsFcScheduleTemplate,
    get_ecs_fc_teams, is_ecs_fc_team, get_ecs_fc_matches_for_team,
    get_ecs_fc_matches_for_date_range
)

from .substitutes import (
    # ECS FC substitute models
    EcsFcSubRequest, EcsFcSubResponse, EcsFcSubAssignment, EcsFcSubPool,
    # Unified substitute models
    SubstitutePool, SubstitutePoolHistory, SubstituteRequest,
    SubstituteResponse, SubstituteAssignment,
    # Helper functions
    get_eligible_players, get_active_substitutes, log_pool_action
)

from .predictions import (
    DraftSeason, DraftPrediction, DraftPredictionSummary
)

from .league_features import (
    SubRequest, LeaguePoll, LeaguePollResponse, LeaguePollDiscordMessage,
    DraftOrderHistory, MessageCategory, MessageTemplate
)

from .ispy import (
    ISpySeason, ISpyCategory, ISpyShot, ISpyShotTarget, ISpyCooldown,
    ISpyUserJail, ISpyUserStats
)

from .admin_config import (
    AdminConfig, AdminAuditLog
)

from .api_logs import (
    APIRequestLog
)

from .security import (
    IPBan, SecurityEvent
)

from .ai_prompt_config import (
    AIPromptConfig, AIPromptTemplate
)

from .calendar import (
    LeagueEvent, LeagueEventType, CalendarSubscription
)

from .wallet import (
    WalletPassType, WalletPass, WalletPassDevice, WalletPassCheckin,
    PassValidityType, PassStatus, CheckInType,
    create_ecs_membership_pass, create_pub_league_pass, create_pub_league_pass_manual
)

from .wallet_asset import (
    WalletAsset, WalletTemplate, WalletCertificate
)

from .wallet_config import (
    WalletLocation, WalletSponsor, WalletSubgroup,
    WalletPassFieldConfig, WalletBackField,
    initialize_wallet_config_defaults
)

# Make all models available at package level for backward compatibility
__all__ = [
    # Database instance
    'db',
    
    # Core models
    'League', 'User', 'Role', 'Permission', 'Season', 'DuplicateRegistrationAlert',
    'user_roles', 'role_permissions',
    
    # Player and team models
    'Team', 'Player', 'PlayerOrderHistory', 'PlayerTeamSeason',
    'PlayerTeamHistory', 'PlayerImageCache',
    'player_league', 'player_teams',
    
    # Match and schedule models
    'Schedule', 'Match', 'Availability', 'TemporarySubAssignment',
    'AutoScheduleConfig', 'ScheduleTemplate', 'WeekConfiguration', 'SeasonConfiguration',
    'help_topic_roles',
    
    # Statistics models
    'PlayerSeasonStats', 'PlayerCareerStats', 'Standings', 'StatChangeLog',
    'PlayerAttendanceStats', 'PlayerEventType', 'PlayerEvent', 
    'StatChangeType', 'PlayerStatAudit',
    
    # Communication models
    'Notification', 'Announcement', 'ScheduledMessage', 'Feedback',
    'FeedbackReply', 'Note', 'DeviceToken',
    
    # Push notification models
    'UserFCMToken',

    # Push campaign models
    'NotificationGroup', 'NotificationGroupMember', 'PushNotificationCampaign',
    'GroupType', 'CampaignStatus', 'CampaignPriority', 'TargetType',
    
    # Store models
    'StoreItem', 'StoreOrder',
    
    # External integration models
    'Token', 'MLSMatch', 'Progress', 'HelpTopic', 'Prediction',
    
    # Live reporting models
    'LiveReportingSession',

    # Task scheduling models
    'ScheduledTask', 'TaskType', 'TaskState',

    # Match status enum
    'MatchStatus',

    # ECS FC models
    'EcsFcMatch', 'EcsFcAvailability', 'EcsFcScheduleTemplate',
    'get_ecs_fc_teams', 'is_ecs_fc_team', 'get_ecs_fc_matches_for_team',
    'get_ecs_fc_matches_for_date_range',
    
    # Substitute models
    'EcsFcSubRequest', 'EcsFcSubResponse', 'EcsFcSubAssignment', 'EcsFcSubPool',
    'SubstitutePool', 'SubstitutePoolHistory', 'SubstituteRequest',
    'SubstituteResponse', 'SubstituteAssignment',
    'get_eligible_players', 'get_active_substitutes', 'log_pool_action',
    
    # Prediction models
    'DraftSeason', 'DraftPrediction', 'DraftPredictionSummary',
    
    # League features models
    'SubRequest', 'LeaguePoll', 'LeaguePollResponse', 'LeaguePollDiscordMessage',
    'DraftOrderHistory', 'MessageCategory', 'MessageTemplate',
    
    # I-Spy models
    'ISpySeason', 'ISpyCategory', 'ISpyShot', 'ISpyShotTarget', 'ISpyCooldown',
    'ISpyUserJail', 'ISpyUserStats',
    
    # Admin configuration models
    'AdminConfig', 'AdminAuditLog',

    # API logging models
    'APIRequestLog',

    # Security models
    'IPBan', 'SecurityEvent',

    # AI Prompt Configuration models
    'AIPromptConfig', 'AIPromptTemplate',

    # Calendar models
    'LeagueEvent', 'LeagueEventType', 'CalendarSubscription',

    # Wallet pass models
    'WalletPassType', 'WalletPass', 'WalletPassDevice', 'WalletPassCheckin',
    'PassValidityType', 'PassStatus', 'CheckInType',
    'create_ecs_membership_pass', 'create_pub_league_pass', 'create_pub_league_pass_manual',

    # Wallet asset models
    'WalletAsset', 'WalletTemplate', 'WalletCertificate',

    # Wallet configuration models
    'WalletLocation', 'WalletSponsor', 'WalletSubgroup',
    'WalletPassFieldConfig', 'WalletBackField',
    'initialize_wallet_config_defaults'
]