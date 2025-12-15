# app/services/push_targeting_service.py

"""
Push Notification Targeting Service

Resolves targeting criteria to FCM tokens for push notifications.
Supports targeting by:
- All users
- Teams
- Leagues
- Roles
- Substitute pools
- Platforms (iOS/Android/Web)
- Custom notification groups
"""

import logging
from typing import List, Dict, Any, Optional, Set
from sqlalchemy import or_

from app.core import db
from app.models import (
    User, Player, Team, League, Role,
    UserFCMToken, SubstitutePool, EcsFcSubPool,
    NotificationGroup, NotificationGroupMember,
    user_roles
)
from app.models.players import player_teams

logger = logging.getLogger(__name__)


class PushTargetingService:
    """Service for resolving push notification targets to FCM tokens."""

    def __init__(self, session=None):
        """Initialize with optional database session."""
        self._session = session

    @property
    def session(self):
        """Get database session."""
        return self._session or db.session

    def resolve_targets(
        self,
        target_type: str,
        target_ids: Optional[List[Any]] = None,
        platform: Optional[str] = None
    ) -> List[str]:
        """
        Resolve targeting criteria to FCM tokens.

        Args:
            target_type: Type of target ('all', 'team', 'league', 'role', 'pool', 'group', 'platform')
            target_ids: List of IDs or names for the target type
            platform: Optional platform filter ('ios', 'android', 'web', 'all')

        Returns:
            List of FCM token strings
        """
        try:
            if target_type == 'all':
                return self.get_all_tokens(platform)
            elif target_type == 'team':
                return self.get_tokens_for_teams(target_ids or [], platform)
            elif target_type == 'league':
                return self.get_tokens_for_leagues(target_ids or [], platform)
            elif target_type == 'role':
                return self.get_tokens_for_roles(target_ids or [], platform)
            elif target_type == 'pool':
                return self.get_tokens_for_substitute_pools(target_ids or [], platform)
            elif target_type == 'group':
                group_id = target_ids[0] if target_ids else None
                return self.get_tokens_for_notification_group(group_id, platform)
            elif target_type == 'platform':
                return self.get_tokens_for_platform(platform or 'all')
            elif target_type == 'custom':
                # Custom targets are user IDs
                return self.get_tokens_for_users(target_ids or [], platform)
            else:
                logger.warning(f"Unknown target type: {target_type}")
                return []
        except Exception as e:
            logger.error(f"Error resolving targets: {e}")
            return []

    def get_all_tokens(self, platform: Optional[str] = None) -> List[str]:
        """Get all active FCM tokens, optionally filtered by platform."""
        query = self.session.query(UserFCMToken.fcm_token).filter(
            UserFCMToken.is_active == True
        )

        if platform and platform != 'all':
            query = query.filter(UserFCMToken.platform == platform)

        tokens = [row[0] for row in query.all()]
        logger.info(f"Found {len(tokens)} tokens for all users (platform={platform})")
        return list(set(tokens))  # Deduplicate

    def get_tokens_for_teams(
        self,
        team_ids: List[int],
        platform: Optional[str] = None
    ) -> List[str]:
        """
        Get FCM tokens for players on specific teams.

        Args:
            team_ids: List of team IDs
            platform: Optional platform filter

        Returns:
            List of FCM tokens
        """
        if not team_ids:
            return []

        # Query: User -> Player -> player_teams -> Team, then join FCM tokens
        query = self.session.query(UserFCMToken.fcm_token).select_from(User).join(
            Player, Player.user_id == User.id
        ).join(
            player_teams, player_teams.c.player_id == Player.id
        ).join(
            UserFCMToken, UserFCMToken.user_id == User.id
        ).filter(
            player_teams.c.team_id.in_(team_ids),
            UserFCMToken.is_active == True
        )

        if platform and platform != 'all':
            query = query.filter(UserFCMToken.platform == platform)

        tokens = [row[0] for row in query.all()]
        logger.info(f"Found {len(tokens)} tokens for teams {team_ids} (platform={platform})")
        return list(set(tokens))

    def get_tokens_for_leagues(
        self,
        league_ids: List[int],
        platform: Optional[str] = None
    ) -> List[str]:
        """
        Get FCM tokens for users in specific leagues.

        Uses User.league_id for primary league membership.

        Args:
            league_ids: List of league IDs
            platform: Optional platform filter

        Returns:
            List of FCM tokens
        """
        if not league_ids:
            return []

        query = self.session.query(UserFCMToken.fcm_token).select_from(User).join(
            UserFCMToken, UserFCMToken.user_id == User.id
        ).filter(
            User.league_id.in_(league_ids),
            UserFCMToken.is_active == True
        )

        if platform and platform != 'all':
            query = query.filter(UserFCMToken.platform == platform)

        tokens = [row[0] for row in query.all()]
        logger.info(f"Found {len(tokens)} tokens for leagues {league_ids} (platform={platform})")
        return list(set(tokens))

    def get_tokens_for_roles(
        self,
        role_names: List[str],
        platform: Optional[str] = None
    ) -> List[str]:
        """
        Get FCM tokens for users with specific roles.

        Args:
            role_names: List of role names (e.g., ['Coach', 'Admin'])
            platform: Optional platform filter

        Returns:
            List of FCM tokens
        """
        if not role_names:
            return []

        query = self.session.query(UserFCMToken.fcm_token).select_from(User).join(
            user_roles, user_roles.c.user_id == User.id
        ).join(
            Role, Role.id == user_roles.c.role_id
        ).join(
            UserFCMToken, UserFCMToken.user_id == User.id
        ).filter(
            Role.name.in_(role_names),
            UserFCMToken.is_active == True
        )

        if platform and platform != 'all':
            query = query.filter(UserFCMToken.platform == platform)

        tokens = [row[0] for row in query.distinct().all()]
        logger.info(f"Found {len(tokens)} tokens for roles {role_names} (platform={platform})")
        return list(set(tokens))

    def get_tokens_for_substitute_pools(
        self,
        pool_types: Optional[List[str]] = None,
        platform: Optional[str] = None
    ) -> List[str]:
        """
        Get FCM tokens for substitute pool members.

        Args:
            pool_types: List of pool types ('pub_league', 'ecs_fc', 'all')
            platform: Optional platform filter

        Returns:
            List of FCM tokens
        """
        tokens = set()

        # Default to all pools if not specified
        if not pool_types or 'all' in pool_types:
            pool_types = ['pub_league', 'ecs_fc']

        # Pub League substitute pool
        if 'pub_league' in pool_types:
            query = self.session.query(UserFCMToken.fcm_token).select_from(User).join(
                Player, Player.user_id == User.id
            ).join(
                SubstitutePool, SubstitutePool.player_id == Player.id
            ).join(
                UserFCMToken, UserFCMToken.user_id == User.id
            ).filter(
                SubstitutePool.is_active == True,
                UserFCMToken.is_active == True
            )

            if platform and platform != 'all':
                query = query.filter(UserFCMToken.platform == platform)

            tokens.update(row[0] for row in query.all())

        # ECS FC substitute pool
        if 'ecs_fc' in pool_types:
            query = self.session.query(UserFCMToken.fcm_token).select_from(User).join(
                Player, Player.user_id == User.id
            ).join(
                EcsFcSubPool, EcsFcSubPool.player_id == Player.id
            ).join(
                UserFCMToken, UserFCMToken.user_id == User.id
            ).filter(
                EcsFcSubPool.is_active == True,
                UserFCMToken.is_active == True
            )

            if platform and platform != 'all':
                query = query.filter(UserFCMToken.platform == platform)

            tokens.update(row[0] for row in query.all())

        logger.info(f"Found {len(tokens)} tokens for substitute pools {pool_types} (platform={platform})")
        return list(tokens)

    def get_tokens_for_notification_group(
        self,
        group_id: int,
        platform: Optional[str] = None
    ) -> List[str]:
        """
        Get FCM tokens for a notification group.

        Handles both dynamic (criteria-based) and static (member list) groups.

        Args:
            group_id: Notification group ID
            platform: Optional platform filter

        Returns:
            List of FCM tokens
        """
        if not group_id:
            return []

        group = self.session.query(NotificationGroup).get(group_id)
        if not group or not group.is_active:
            logger.warning(f"Notification group {group_id} not found or inactive")
            return []

        if group.is_dynamic:
            # Resolve dynamic group based on criteria
            return self._resolve_dynamic_group(group, platform)
        else:
            # Static group - get tokens for members
            return self._resolve_static_group(group, platform)

    def _resolve_dynamic_group(
        self,
        group: NotificationGroup,
        platform: Optional[str] = None
    ) -> List[str]:
        """Resolve a dynamic notification group to tokens."""
        criteria = group.criteria or {}
        target_type = criteria.get('target_type', 'all')

        # Map criteria to targeting method
        if target_type == 'all':
            return self.get_all_tokens(platform)
        elif target_type == 'role':
            role_names = criteria.get('role_names', [])
            return self.get_tokens_for_roles(role_names, platform)
        elif target_type == 'team':
            team_ids = criteria.get('team_ids', [])
            return self.get_tokens_for_teams(team_ids, platform)
        elif target_type == 'league':
            league_ids = criteria.get('league_ids', [])
            return self.get_tokens_for_leagues(league_ids, platform)
        elif target_type == 'pool':
            pool_type = criteria.get('pool_type', 'all')
            return self.get_tokens_for_substitute_pools([pool_type], platform)
        elif target_type == 'platform':
            return self.get_tokens_for_platform(criteria.get('platform', 'all'))
        else:
            logger.warning(f"Unknown dynamic group target type: {target_type}")
            return []

    def _resolve_static_group(
        self,
        group: NotificationGroup,
        platform: Optional[str] = None
    ) -> List[str]:
        """Resolve a static notification group to tokens."""
        query = self.session.query(UserFCMToken.fcm_token).select_from(
            NotificationGroupMember
        ).join(
            User, User.id == NotificationGroupMember.user_id
        ).join(
            UserFCMToken, UserFCMToken.user_id == User.id
        ).filter(
            NotificationGroupMember.group_id == group.id,
            UserFCMToken.is_active == True
        )

        if platform and platform != 'all':
            query = query.filter(UserFCMToken.platform == platform)

        tokens = [row[0] for row in query.all()]
        logger.info(f"Found {len(tokens)} tokens for static group {group.id} (platform={platform})")
        return list(set(tokens))

    def get_tokens_for_platform(self, platform: str) -> List[str]:
        """Get all tokens for a specific platform."""
        if platform == 'all':
            return self.get_all_tokens()

        query = self.session.query(UserFCMToken.fcm_token).filter(
            UserFCMToken.is_active == True,
            UserFCMToken.platform == platform
        )

        tokens = [row[0] for row in query.all()]
        logger.info(f"Found {len(tokens)} tokens for platform {platform}")
        return list(set(tokens))

    def get_tokens_for_users(
        self,
        user_ids: List[int],
        platform: Optional[str] = None
    ) -> List[str]:
        """Get FCM tokens for specific users."""
        if not user_ids:
            return []

        query = self.session.query(UserFCMToken.fcm_token).filter(
            UserFCMToken.user_id.in_(user_ids),
            UserFCMToken.is_active == True
        )

        if platform and platform != 'all':
            query = query.filter(UserFCMToken.platform == platform)

        tokens = [row[0] for row in query.all()]
        logger.info(f"Found {len(tokens)} tokens for {len(user_ids)} users (platform={platform})")
        return list(set(tokens))

    def preview_recipient_count(
        self,
        target_type: str,
        target_ids: Optional[List[Any]] = None,
        platform: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Preview how many users/tokens would receive a notification.

        Args:
            target_type: Type of target
            target_ids: Target identifiers
            platform: Optional platform filter

        Returns:
            Dictionary with counts and breakdown
        """
        try:
            # Get tokens for the targeting criteria
            tokens = self.resolve_targets(target_type, target_ids, platform)

            # If no platform filter, get breakdown
            breakdown = {'all': len(tokens)}
            if not platform or platform == 'all':
                ios_tokens = self.resolve_targets(target_type, target_ids, 'ios')
                android_tokens = self.resolve_targets(target_type, target_ids, 'android')
                web_tokens = self.resolve_targets(target_type, target_ids, 'web')
                breakdown = {
                    'ios': len(ios_tokens),
                    'android': len(android_tokens),
                    'web': len(web_tokens),
                }

            # Get unique user count
            user_ids = self._get_user_ids_for_tokens(tokens)

            return {
                'total_users': len(user_ids),
                'total_tokens': len(tokens),
                'breakdown': breakdown,
                'target_type': target_type,
                'target_ids': target_ids,
                'platform': platform,
            }
        except Exception as e:
            logger.error(f"Error previewing recipients: {e}")
            return {
                'total_users': 0,
                'total_tokens': 0,
                'breakdown': {},
                'error': str(e),
            }

    def _get_user_ids_for_tokens(self, tokens: List[str]) -> Set[int]:
        """Get unique user IDs for a list of tokens."""
        if not tokens:
            return set()

        query = self.session.query(UserFCMToken.user_id).filter(
            UserFCMToken.fcm_token.in_(tokens)
        ).distinct()

        return set(row[0] for row in query.all())

    def get_target_details(
        self,
        target_type: str,
        target_ids: Optional[List[Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Get details about the target entities (teams, leagues, etc.)

        Args:
            target_type: Type of target
            target_ids: Target identifiers

        Returns:
            List of dictionaries with target details
        """
        details = []

        try:
            if target_type == 'team' and target_ids:
                teams = self.session.query(Team).filter(Team.id.in_(target_ids)).all()
                for team in teams:
                    token_count = len(self.get_tokens_for_teams([team.id]))
                    details.append({
                        'id': team.id,
                        'name': team.name,
                        'token_count': token_count,
                    })

            elif target_type == 'league' and target_ids:
                leagues = self.session.query(League).filter(League.id.in_(target_ids)).all()
                for league in leagues:
                    token_count = len(self.get_tokens_for_leagues([league.id]))
                    details.append({
                        'id': league.id,
                        'name': league.name,
                        'token_count': token_count,
                    })

            elif target_type == 'role' and target_ids:
                for role_name in target_ids:
                    token_count = len(self.get_tokens_for_roles([role_name]))
                    details.append({
                        'name': role_name,
                        'token_count': token_count,
                    })

            elif target_type == 'group' and target_ids:
                group = self.session.query(NotificationGroup).get(target_ids[0])
                if group:
                    token_count = len(self.get_tokens_for_notification_group(group.id))
                    details.append({
                        'id': group.id,
                        'name': group.name,
                        'type': group.group_type,
                        'token_count': token_count,
                    })

        except Exception as e:
            logger.error(f"Error getting target details: {e}")

        return details


# Singleton instance for easy import
push_targeting_service = PushTargetingService()
