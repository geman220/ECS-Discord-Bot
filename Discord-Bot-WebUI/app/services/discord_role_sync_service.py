# app/services/discord_role_sync_service.py

"""
Discord Role Sync Service

Bidirectional synchronization service for Flask roles and Discord roles.
This service handles:
- Syncing Flask roles to Discord when users gain/lose roles
- Bulk syncing all users with a specific Flask role to Discord
- Fetching available Discord roles for mapping
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

import aiohttp

from app.core import db
from app.models.core import Role, User
from app.utils.discord_request_handler import make_discord_request

logger = logging.getLogger(__name__)


class DiscordRoleSyncService:
    """
    Service for bidirectional synchronization between Flask roles and Discord roles.
    """

    def __init__(self):
        self.bot_api_url = os.getenv('BOT_API_URL', 'http://discord-bot:5001')
        self.guild_id = os.getenv('SERVER_ID')
        self._session = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=30, connect=10, sock_read=20)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def close(self):
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()

    # -------------------------------------------------------------------------
    # Discord Role Fetching
    # -------------------------------------------------------------------------

    async def fetch_discord_roles(self) -> List[Dict[str, Any]]:
        """
        Fetch all Discord roles from the server via bot API.

        Returns:
            List of role dictionaries with id, name, color, position, member_count, etc.
        """
        if not self.guild_id:
            logger.error("SERVER_ID environment variable not set")
            return []

        try:
            session = await self._get_session()
            url = f"{self.bot_api_url}/api/discord/roles"

            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    roles = data.get('roles', [])
                    logger.info(f"Fetched {len(roles)} Discord roles from server")
                    return roles
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to fetch Discord roles (status {response.status}): {error_text}")
                    return []

        except Exception as e:
            logger.error(f"Error fetching Discord roles: {e}")
            return []

    async def get_role_members(self, discord_role_id: str) -> List[Dict[str, Any]]:
        """
        Get all members who have a specific Discord role.

        Args:
            discord_role_id: The Discord role ID to query

        Returns:
            List of member dictionaries with id, username, etc.
        """
        if not discord_role_id:
            return []

        try:
            session = await self._get_session()
            url = f"{self.bot_api_url}/api/discord/roles/{discord_role_id}/members"

            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get('members', [])
                else:
                    logger.error(f"Failed to get members for role {discord_role_id}")
                    return []

        except Exception as e:
            logger.error(f"Error getting role members: {e}")
            return []

    # -------------------------------------------------------------------------
    # Individual User Sync
    # -------------------------------------------------------------------------

    async def assign_discord_role_to_user(
        self,
        discord_user_id: str,
        discord_role_id: str
    ) -> Tuple[bool, str]:
        """
        Assign a Discord role to a user.

        Args:
            discord_user_id: The Discord user's ID
            discord_role_id: The Discord role ID to assign

        Returns:
            Tuple of (success, message)
        """
        if not discord_user_id or not discord_role_id:
            return False, "Missing user or role ID"

        try:
            session = await self._get_session()
            url = f"{self.bot_api_url}/api/discord/roles/assign"

            payload = {
                'user_id': discord_user_id,
                'role_id': discord_role_id
            }

            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    logger.info(f"Assigned Discord role {discord_role_id} to user {discord_user_id}")
                    return True, "Role assigned successfully"
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to assign role: {error_text}")
                    return False, f"Failed to assign role: {error_text}"

        except Exception as e:
            logger.error(f"Error assigning Discord role: {e}")
            return False, str(e)

    async def remove_discord_role_from_user(
        self,
        discord_user_id: str,
        discord_role_id: str
    ) -> Tuple[bool, str]:
        """
        Remove a Discord role from a user.

        Args:
            discord_user_id: The Discord user's ID
            discord_role_id: The Discord role ID to remove

        Returns:
            Tuple of (success, message)
        """
        if not discord_user_id or not discord_role_id:
            return False, "Missing user or role ID"

        try:
            session = await self._get_session()
            url = f"{self.bot_api_url}/api/discord/roles/remove"

            payload = {
                'user_id': discord_user_id,
                'role_id': discord_role_id
            }

            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    logger.info(f"Removed Discord role {discord_role_id} from user {discord_user_id}")
                    return True, "Role removed successfully"
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to remove role: {error_text}")
                    return False, f"Failed to remove role: {error_text}"

        except Exception as e:
            logger.error(f"Error removing Discord role: {e}")
            return False, str(e)

    # -------------------------------------------------------------------------
    # Flask Role Events - Sync on Role Assignment/Removal
    # -------------------------------------------------------------------------

    async def on_flask_role_assigned(self, user: User, role: Role) -> bool:
        """
        Called when a Flask role is assigned to a user.
        Syncs the corresponding Discord role if mapping exists.

        Args:
            user: The Flask User object
            role: The Flask Role object being assigned

        Returns:
            True if sync successful or not needed, False on error
        """
        # Check if role has Discord mapping and sync is enabled
        if not role.discord_role_id or not role.sync_enabled:
            logger.debug(f"Role {role.name} has no Discord mapping or sync disabled")
            return True

        # Get user's Discord ID from their player profile
        discord_id = self._get_user_discord_id(user)
        if not discord_id:
            logger.debug(f"User {user.username} has no Discord ID linked")
            return True

        # Assign the Discord role
        success, message = await self.assign_discord_role_to_user(discord_id, role.discord_role_id)

        if success:
            logger.info(f"Synced Flask role '{role.name}' to Discord for user {user.username}")
        else:
            logger.error(f"Failed to sync role '{role.name}' to Discord for user {user.username}: {message}")

        return success

    async def on_flask_role_removed(self, user: User, role: Role) -> bool:
        """
        Called when a Flask role is removed from a user.
        Removes the corresponding Discord role if mapping exists.

        Args:
            user: The Flask User object
            role: The Flask Role object being removed

        Returns:
            True if sync successful or not needed, False on error
        """
        # Check if role has Discord mapping and sync is enabled
        if not role.discord_role_id or not role.sync_enabled:
            logger.debug(f"Role {role.name} has no Discord mapping or sync disabled")
            return True

        # Get user's Discord ID from their player profile
        discord_id = self._get_user_discord_id(user)
        if not discord_id:
            logger.debug(f"User {user.username} has no Discord ID linked")
            return True

        # Remove the Discord role
        success, message = await self.remove_discord_role_from_user(discord_id, role.discord_role_id)

        if success:
            logger.info(f"Removed Discord role for Flask role '{role.name}' from user {user.username}")
        else:
            logger.error(f"Failed to remove Discord role for '{role.name}' from user {user.username}: {message}")

        return success

    # -------------------------------------------------------------------------
    # Bulk Sync Operations
    # -------------------------------------------------------------------------

    async def sync_flask_role_to_discord(self, role: Role) -> Dict[str, Any]:
        """
        Sync all users with a Flask role to have the corresponding Discord role.

        Args:
            role: The Flask Role object to sync

        Returns:
            Dictionary with sync results
        """
        if not role.discord_role_id:
            return {
                'success': False,
                'error': 'Role has no Discord role mapping'
            }

        if not role.sync_enabled:
            return {
                'success': False,
                'error': 'Sync is disabled for this role'
            }

        results = {
            'success': True,
            'total_users': 0,
            'synced': 0,
            'skipped': 0,
            'failed': 0,
            'errors': []
        }

        try:
            # Get all users with this Flask role
            users_with_role = role.users
            results['total_users'] = len(users_with_role)

            for user in users_with_role:
                discord_id = self._get_user_discord_id(user)

                if not discord_id:
                    results['skipped'] += 1
                    continue

                success, message = await self.assign_discord_role_to_user(
                    discord_id,
                    role.discord_role_id
                )

                if success:
                    results['synced'] += 1
                else:
                    results['failed'] += 1
                    results['errors'].append({
                        'user': user.username,
                        'error': message
                    })

                # Rate limiting - small delay between API calls
                await asyncio.sleep(0.5)

            # Update last synced timestamp
            role.last_synced_at = datetime.utcnow()
            db.session.commit()

            logger.info(
                f"Synced role '{role.name}': {results['synced']}/{results['total_users']} users, "
                f"{results['skipped']} skipped, {results['failed']} failed"
            )

        except Exception as e:
            logger.error(f"Error during bulk sync for role '{role.name}': {e}")
            results['success'] = False
            results['errors'].append({'error': str(e)})

        return results

    async def sync_all_mapped_roles(self) -> Dict[str, Any]:
        """
        Sync all Flask roles that have Discord mappings.

        Returns:
            Dictionary with overall sync results
        """
        results = {
            'success': True,
            'roles_processed': 0,
            'roles_synced': 0,
            'roles_failed': 0,
            'details': []
        }

        try:
            # Get all roles with Discord mappings
            mapped_roles = Role.query.filter(
                Role.discord_role_id.isnot(None),
                Role.sync_enabled == True
            ).all()

            results['roles_processed'] = len(mapped_roles)

            for role in mapped_roles:
                role_result = await self.sync_flask_role_to_discord(role)

                results['details'].append({
                    'role_name': role.name,
                    'result': role_result
                })

                if role_result['success']:
                    results['roles_synced'] += 1
                else:
                    results['roles_failed'] += 1

                # Rate limiting between roles
                await asyncio.sleep(1)

            logger.info(
                f"Bulk role sync complete: {results['roles_synced']}/{results['roles_processed']} roles synced"
            )

        except Exception as e:
            logger.error(f"Error during bulk role sync: {e}")
            results['success'] = False
            results['error'] = str(e)

        return results

    # -------------------------------------------------------------------------
    # Role Mapping Management
    # -------------------------------------------------------------------------

    def update_role_mapping(
        self,
        flask_role_id: int,
        discord_role_id: Optional[str],
        discord_role_name: Optional[str] = None,
        sync_enabled: bool = True
    ) -> Tuple[bool, str]:
        """
        Update the Discord role mapping for a Flask role.

        Args:
            flask_role_id: The Flask role ID
            discord_role_id: The Discord role ID to map (or None to clear)
            discord_role_name: Optional Discord role name to cache
            sync_enabled: Whether to enable sync for this mapping

        Returns:
            Tuple of (success, message)
        """
        try:
            role = Role.query.get(flask_role_id)
            if not role:
                return False, "Flask role not found"

            role.discord_role_id = discord_role_id
            role.discord_role_name = discord_role_name
            role.sync_enabled = sync_enabled

            if discord_role_id:
                logger.info(f"Mapped Flask role '{role.name}' to Discord role {discord_role_id}")
            else:
                role.last_synced_at = None
                logger.info(f"Cleared Discord mapping for Flask role '{role.name}'")

            db.session.commit()
            return True, "Mapping updated successfully"

        except Exception as e:
            logger.error(f"Error updating role mapping: {e}")
            db.session.rollback()
            return False, str(e)

    def get_role_mapping_status(self) -> List[Dict[str, Any]]:
        """
        Get the Discord mapping status for all Flask roles.

        Returns:
            List of role mapping status dictionaries
        """
        try:
            roles = Role.query.all()
            return [
                {
                    'id': role.id,
                    'name': role.name,
                    'description': role.description,
                    'discord_role_id': role.discord_role_id,
                    'discord_role_name': role.discord_role_name,
                    'sync_enabled': role.sync_enabled,
                    'last_synced_at': role.last_synced_at.isoformat() if role.last_synced_at else None,
                    'user_count': len(role.users)
                }
                for role in roles
            ]
        except Exception as e:
            logger.error(f"Error getting role mapping status: {e}")
            return []

    # -------------------------------------------------------------------------
    # Preview/Dry Run
    # -------------------------------------------------------------------------

    def preview_role_sync(self, flask_role_id: int) -> Dict[str, Any]:
        """
        Preview what would happen if a role sync was executed.

        Args:
            flask_role_id: The Flask role ID to preview

        Returns:
            Preview information including users and their Discord status
        """
        try:
            role = Role.query.get(flask_role_id)
            if not role:
                return {'success': False, 'error': 'Role not found'}

            users_info = []
            users_with_discord = 0

            for user in role.users:
                discord_id = self._get_user_discord_id(user)
                has_discord = discord_id is not None

                if has_discord:
                    users_with_discord += 1

                users_info.append({
                    'id': user.id,
                    'username': user.username,
                    'discord_id': discord_id,
                    'has_discord': has_discord,
                    'discord_username': self._get_user_discord_username(user)
                })

            return {
                'success': True,
                'role': {
                    'id': role.id,
                    'name': role.name,
                    'discord_role_id': role.discord_role_id,
                    'discord_role_name': role.discord_role_name
                },
                'total_users': len(users_info),
                'users_with_discord': users_with_discord,
                'users': users_info
            }

        except Exception as e:
            logger.error(f"Error previewing role sync: {e}")
            return {'success': False, 'error': str(e)}

    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------

    def _get_user_discord_id(self, user: User) -> Optional[str]:
        """Get the Discord ID for a user via their player profile."""
        if user.player and user.player.discord_id:
            return user.player.discord_id
        return None

    def _get_user_discord_username(self, user: User) -> Optional[str]:
        """Get the Discord username for a user via their player profile."""
        if user.player and user.player.discord_username:
            return user.player.discord_username
        return None


# Global service instance
_discord_role_sync_service = None


def get_discord_role_sync_service() -> DiscordRoleSyncService:
    """Get the global Discord role sync service instance."""
    global _discord_role_sync_service
    if _discord_role_sync_service is None:
        _discord_role_sync_service = DiscordRoleSyncService()
    return _discord_role_sync_service


# -------------------------------------------------------------------------
# Convenience Functions for Integration
# -------------------------------------------------------------------------

def sync_role_assignment(user: User, role: Role) -> bool:
    """
    Synchronous wrapper to sync a role assignment to Discord.
    Call this when assigning a Flask role to a user.

    Args:
        user: The User being assigned the role
        role: The Role being assigned

    Returns:
        True if sync successful
    """
    service = get_discord_role_sync_service()
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(service.on_flask_role_assigned(user, role))


def sync_role_removal(user: User, role: Role) -> bool:
    """
    Synchronous wrapper to sync a role removal to Discord.
    Call this when removing a Flask role from a user.

    Args:
        user: The User losing the role
        role: The Role being removed

    Returns:
        True if sync successful
    """
    service = get_discord_role_sync_service()
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(service.on_flask_role_removed(user, role))


async def fetch_discord_roles_async() -> List[Dict[str, Any]]:
    """
    Async function to fetch Discord roles.

    Returns:
        List of Discord role dictionaries
    """
    service = get_discord_role_sync_service()
    return await service.fetch_discord_roles()


def fetch_discord_roles_sync() -> List[Dict[str, Any]]:
    """
    Synchronous wrapper to fetch Discord roles.

    Returns:
        List of Discord role dictionaries
    """
    service = get_discord_role_sync_service()
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(service.fetch_discord_roles())
