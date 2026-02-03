# app/services/mobile/admin_service.py

"""
Mobile Admin Service

Handles administrative operations for mobile clients including:
- Role management (view, assign, remove roles)
- League membership management (add/remove players from leagues)
- Discord role synchronization

All methods accept player_id (not user_id) for easier mobile app integration.
"""

import logging
from typing import Optional, Dict, Any, List

from sqlalchemy.orm import Session, joinedload

from app.services.base_service import BaseService, ServiceResult
from app.models import User, Player, Role, League, Season, player_league
from app.tasks.tasks_discord import assign_roles_to_player_task
from app.utils.user_locking import lock_user_for_role_update, LockAcquisitionError
from app.utils.deferred_discord import DeferredDiscordQueue

logger = logging.getLogger(__name__)

# Role name that cannot be assigned via mobile API
PROTECTED_ROLE = 'Global Admin'

# League types that trigger auto-role assignment
LEAGUE_ROLE_MAPPING = {
    'Classic': 'Pub League Classic',
    'Premier': 'Pub League Premier',
}


class MobileAdminService(BaseService):
    """
    Service for admin operations on players, roles, and leagues.

    Handles all administrative business logic for mobile clients,
    including role assignment, league membership, and Discord sync.
    All methods accept player_id for easier mobile integration.
    """

    def __init__(self, session: Session):
        super().__init__(session)

    # ==================== Role Management ====================

    def get_player_roles(self, player_id: int) -> ServiceResult[Dict[str, Any]]:
        """
        Get a player's current roles and list of assignable roles.

        Args:
            player_id: The player's ID

        Returns:
            ServiceResult with player's roles and assignable roles
        """
        player = self.session.query(Player).options(
            joinedload(Player.user).joinedload(User.roles)
        ).get(player_id)

        if not player:
            return ServiceResult.fail("Player not found", "PLAYER_NOT_FOUND")

        if not player.user:
            return ServiceResult.fail(
                "Player does not have a user account",
                "NO_USER_ACCOUNT"
            )

        user = player.user

        # Show ALL current roles (including Global Admin if they have it)
        current_roles = [
            {
                "id": role.id,
                "name": role.name,
                "description": role.description,
                "is_protected": role.name == PROTECTED_ROLE
            }
            for role in user.roles
        ]

        # Get assignable roles (exclude Global Admin - can't assign via mobile)
        assignable_roles = self.session.query(Role).filter(
            Role.name != PROTECTED_ROLE
        ).order_by(Role.name).all()

        assignable_list = [
            {"id": role.id, "name": role.name, "description": role.description}
            for role in assignable_roles
        ]

        return ServiceResult.ok({
            "player_id": player.id,
            "player_name": player.name,
            "user_id": user.id,
            "username": user.username,
            "current_roles": current_roles,
            "assignable_roles": assignable_list
        })

    def update_player_roles(
        self,
        player_id: int,
        add_role_ids: Optional[List[int]] = None,
        remove_role_ids: Optional[List[int]] = None
    ) -> ServiceResult[Dict[str, Any]]:
        """
        Add or remove roles from a player.

        Args:
            player_id: The player's ID
            add_role_ids: List of role IDs to add
            remove_role_ids: List of role IDs to remove

        Returns:
            ServiceResult with updated roles and Discord sync status
        """
        add_role_ids = add_role_ids or []
        remove_role_ids = remove_role_ids or []

        if not add_role_ids and not remove_role_ids:
            return ServiceResult.fail(
                "No role changes specified",
                "NO_CHANGES"
            )

        player = self.session.query(Player).options(
            joinedload(Player.user).joinedload(User.roles)
        ).get(player_id)

        if not player:
            return ServiceResult.fail("Player not found", "PLAYER_NOT_FOUND")

        if not player.user:
            return ServiceResult.fail(
                "Player does not have a user account",
                "NO_USER_ACCOUNT"
            )

        user = player.user

        # Refresh user roles from database to avoid stale data issues
        self.session.refresh(user, ['roles'])

        # Validate and get roles to add
        roles_to_add = []
        for role_id in add_role_ids:
            role = self.session.query(Role).get(role_id)
            if not role:
                return ServiceResult.fail(
                    f"Role with ID {role_id} not found",
                    "ROLE_NOT_FOUND"
                )
            if role.name == PROTECTED_ROLE:
                return ServiceResult.fail(
                    f"Cannot assign {PROTECTED_ROLE} role via mobile API",
                    "PROTECTED_ROLE"
                )
            roles_to_add.append(role)

        # Validate roles to remove
        roles_to_remove = []
        for role_id in remove_role_ids:
            role = self.session.query(Role).get(role_id)
            if not role:
                return ServiceResult.fail(
                    f"Role with ID {role_id} not found",
                    "ROLE_NOT_FOUND"
                )
            if role.name == PROTECTED_ROLE:
                return ServiceResult.fail(
                    f"Cannot remove {PROTECTED_ROLE} role via mobile API",
                    "PROTECTED_ROLE"
                )
            roles_to_remove.append(role)

        # Queue for deferred Discord operations
        discord_queue = DeferredDiscordQueue()

        try:
            # Acquire lock on user for role modification
            with lock_user_for_role_update(user.id, session=self.session) as locked_user:
                # Apply changes
                added_names = []
                removed_names = []

                for role in roles_to_add:
                    if role not in locked_user.roles:
                        locked_user.roles.append(role)
                        added_names.append(role.name)
                        logger.info(f"Added role '{role.name}' to player {player.id}")

                for role in roles_to_remove:
                    if role in locked_user.roles:
                        locked_user.roles.remove(role)
                        removed_names.append(role.name)
                        logger.info(f"Removed role '{role.name}' from player {player.id}")

                # Queue Discord sync (deferred until after commit)
                if player.discord_id:
                    discord_queue.add_role_sync(player.id, only_add=False)

                self.session.commit()

                # Build result
                updated_roles = [
                    {"id": role.id, "name": role.name}
                    for role in locked_user.roles
                ]

        except LockAcquisitionError:
            self.session.rollback()
            return ServiceResult.fail(
                "User is being modified by another request. Please try again.",
                "LOCK_CONFLICT"
            )

        # Execute deferred Discord operations after successful commit
        discord_sync_queued = bool(discord_queue._operations)
        discord_queue.execute_all()

        return ServiceResult.ok({
            "player_id": player.id,
            "player_name": player.name,
            "user_id": user.id,
            "roles": updated_roles,
            "added": added_names,
            "removed": removed_names,
            "discord_sync_queued": discord_sync_queued
        })

    def get_assignable_roles(self) -> ServiceResult[List[Dict[str, Any]]]:
        """
        Get list of all roles that can be assigned via mobile API.

        Returns:
            ServiceResult with list of assignable roles
        """
        roles = self.session.query(Role).filter(
            Role.name != PROTECTED_ROLE
        ).order_by(Role.name).all()

        role_list = [
            {"id": role.id, "name": role.name, "description": role.description}
            for role in roles
        ]

        return ServiceResult.ok(role_list)

    # ==================== League Management ====================

    def get_player_leagues(self, player_id: int) -> ServiceResult[Dict[str, Any]]:
        """
        Get a player's current league memberships.

        Args:
            player_id: The player's ID

        Returns:
            ServiceResult with player's league memberships
        """
        player = self.session.query(Player).options(
            joinedload(Player.other_leagues).joinedload(League.season)
        ).get(player_id)

        if not player:
            return ServiceResult.fail("Player not found", "PLAYER_NOT_FOUND")

        leagues = [
            {
                "id": league.id,
                "name": league.name,
                "season": league.season.name if league.season else None,
                "season_id": league.season_id
            }
            for league in player.other_leagues
        ]

        return ServiceResult.ok({
            "player_id": player.id,
            "player_name": player.name,
            "leagues": leagues
        })

    def add_player_to_league(
        self,
        player_id: int,
        league_id: int
    ) -> ServiceResult[Dict[str, Any]]:
        """
        Add a player to a league.

        Uses pessimistic locking to prevent concurrent role modifications.
        Discord sync is deferred until after transaction commits.

        Args:
            player_id: The player's ID
            league_id: The league's ID

        Returns:
            ServiceResult with result and any auto-assigned role
        """
        player = self.session.query(Player).options(
            joinedload(Player.other_leagues),
            joinedload(Player.user)
        ).get(player_id)

        if not player:
            return ServiceResult.fail("Player not found", "PLAYER_NOT_FOUND")

        league = self.session.query(League).options(
            joinedload(League.season)
        ).get(league_id)

        if not league:
            return ServiceResult.fail("League not found", "LEAGUE_NOT_FOUND")

        # Check if already in league
        if league in player.other_leagues:
            return ServiceResult.fail(
                f"Player is already in {league.name}",
                "ALREADY_IN_LEAGUE"
            )

        # Add to league
        player.other_leagues.append(league)
        logger.info(f"Added player {player.id} to league {league.name}")

        # Queue for deferred Discord operations
        discord_queue = DeferredDiscordQueue()
        auto_assigned_role = None

        # Auto-assign league role if player has user account
        if player.user:
            try:
                with lock_user_for_role_update(player.user.id, session=self.session) as locked_user:
                    auto_assigned_role = self._auto_assign_league_role(locked_user, league)

                    # Queue Discord sync (deferred until after commit)
                    if player.discord_id:
                        discord_queue.add_role_sync(player.id, only_add=False)

                    self.session.commit()

            except LockAcquisitionError:
                self.session.rollback()
                return ServiceResult.fail(
                    "User is being modified by another request. Please try again.",
                    "LOCK_CONFLICT"
                )
        else:
            self.session.commit()

        # Execute deferred Discord operations after successful commit
        discord_sync_queued = bool(discord_queue._operations)
        discord_queue.execute_all()

        return ServiceResult.ok({
            "player_id": player.id,
            "player_name": player.name,
            "league_id": league.id,
            "league_name": league.name,
            "auto_assigned_role": auto_assigned_role,
            "discord_sync_queued": discord_sync_queued
        })

    def remove_player_from_league(
        self,
        player_id: int,
        league_id: int
    ) -> ServiceResult[Dict[str, Any]]:
        """
        Remove a player from a league.

        Uses pessimistic locking to prevent concurrent role modifications.
        Discord sync is deferred until after transaction commits.

        Args:
            player_id: The player's ID
            league_id: The league's ID

        Returns:
            ServiceResult with result and any removed role
        """
        player = self.session.query(Player).options(
            joinedload(Player.other_leagues),
            joinedload(Player.user)
        ).get(player_id)

        if not player:
            return ServiceResult.fail("Player not found", "PLAYER_NOT_FOUND")

        league = self.session.query(League).get(league_id)

        if not league:
            return ServiceResult.fail("League not found", "LEAGUE_NOT_FOUND")

        # Check if in league
        if league not in player.other_leagues:
            return ServiceResult.fail(
                f"Player is not in {league.name}",
                "NOT_IN_LEAGUE"
            )

        # Remove from league
        player.other_leagues.remove(league)
        logger.info(f"Removed player {player.id} from league {league.name}")

        # Queue for deferred Discord operations
        discord_queue = DeferredDiscordQueue()
        removed_role = None

        # Cleanup league role if no longer in any league of that type
        if player.user:
            try:
                with lock_user_for_role_update(player.user.id, session=self.session) as locked_user:
                    removed_role = self._cleanup_league_role(locked_user, league, player)

                    # Queue Discord sync (deferred until after commit)
                    if player.discord_id:
                        discord_queue.add_role_sync(player.id, only_add=False)

                    self.session.commit()

            except LockAcquisitionError:
                self.session.rollback()
                return ServiceResult.fail(
                    "User is being modified by another request. Please try again.",
                    "LOCK_CONFLICT"
                )
        else:
            self.session.commit()

        # Execute deferred Discord operations after successful commit
        discord_sync_queued = bool(discord_queue._operations)
        discord_queue.execute_all()

        return ServiceResult.ok({
            "player_id": player.id,
            "player_name": player.name,
            "league_id": league.id,
            "league_name": league.name,
            "removed_role": removed_role,
            "discord_sync_queued": discord_sync_queued
        })

    def get_available_leagues(self) -> ServiceResult[List[Dict[str, Any]]]:
        """
        Get list of current season leagues available for assignment.

        Returns:
            ServiceResult with list of available leagues
        """
        current_seasons = self.session.query(Season).filter_by(
            is_current=True
        ).all()

        if not current_seasons:
            return ServiceResult.ok([])

        leagues = []
        for season in current_seasons:
            for league in season.leagues:
                leagues.append({
                    "id": league.id,
                    "name": league.name,
                    "season": season.name,
                    "season_id": season.id
                })

        return ServiceResult.ok(leagues)

    # ==================== Internal Helpers ====================

    def _auto_assign_league_role(
        self,
        user: User,
        league: League
    ) -> Optional[str]:
        """
        Auto-assign a role based on league type (Classic/Premier).

        Note: This should be called within a lock_user_for_role_update context.
        The caller is responsible for locking.

        Args:
            user: The user to assign role to (should be locked)
            league: The league that was joined

        Returns:
            Name of assigned role, or None if no role was assigned
        """
        for league_type, role_name in LEAGUE_ROLE_MAPPING.items():
            if league_type in league.name:
                role = self.session.query(Role).filter_by(name=role_name).first()
                if role and role not in user.roles:
                    user.roles.append(role)
                    logger.info(
                        f"Auto-assigned role '{role_name}' to user {user.id} "
                        f"for joining {league.name}"
                    )
                    return role_name
        return None

    def _cleanup_league_role(
        self,
        user: User,
        removed_league: League,
        player: Player
    ) -> Optional[str]:
        """
        Remove league role if user is no longer in any league of that type.

        Args:
            user: The user to potentially remove role from
            removed_league: The league that was left
            player: The player with updated league memberships

        Returns:
            Name of removed role, or None if no role was removed
        """
        for league_type, role_name in LEAGUE_ROLE_MAPPING.items():
            if league_type in removed_league.name:
                # Check if still in any league of this type
                still_in_type = any(
                    league_type in league.name
                    for league in player.other_leagues
                )

                if not still_in_type:
                    role = self.session.query(Role).filter_by(
                        name=role_name
                    ).first()
                    if role and role in user.roles:
                        user.roles.remove(role)
                        logger.info(
                            f"Removed role '{role_name}' from user {user.id} "
                            f"after leaving {removed_league.name}"
                        )
                        return role_name
        return None

    def _trigger_discord_sync(self, player: Player) -> bool:
        """
        Queue Discord role sync task if player has Discord ID.

        Args:
            player: The player whose roles should be synced

        Returns:
            True if sync was queued, False otherwise
        """
        if player.discord_id:
            try:
                assign_roles_to_player_task.delay(
                    player_id=player.id,
                    only_add=False
                )
                logger.info(
                    f"Queued Discord sync for player {player.id}"
                )
                return True
            except Exception as e:
                logger.error(f"Failed to queue Discord sync: {e}")
                return False
        return False
