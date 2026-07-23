# app/services/discord_role_sync_service.py

"""
Discord Role Sync Service

Bidirectional synchronization service for Flask roles and Discord roles.
This service handles:
- Syncing Flask roles to Discord when users gain/lose roles
- Bulk syncing all users with a specific Flask role to Discord
- Fetching available Discord roles for mapping
"""

import logging
import os
import time
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

import requests

from app.core import db
from app.models.core import Role, User
from app.utils.discord_request_handler import make_discord_request

logger = logging.getLogger(__name__)


class DiscordRoleSyncService:
    """
    Service for bidirectional synchronization between Flask roles and Discord roles.
    """

    # HTTP timeout (seconds) for calls to the bot REST API.
    REQUEST_TIMEOUT = 15

    def __init__(self):
        self.bot_api_url = os.getenv('BOT_API_URL', 'http://discord-bot:5001')
        self.guild_id = os.getenv('SERVER_ID')

    # -------------------------------------------------------------------------
    # Discord Role Fetching
    # -------------------------------------------------------------------------
    #
    # NOTE: These methods use the synchronous `requests` library, NOT aiohttp.
    # The web app runs under gunicorn gevent workers (see wsgi.py monkey.patch_all);
    # driving aiohttp/asyncio from a gevent greenlet fails instantly, whereas
    # `requests` is transparently made cooperative by gevent's monkey-patch.
    # Keep this path free of asyncio. (Celery workers, which are not
    # monkey-patched, use aiohttp elsewhere via app/discord_utils.py — that's fine.)

    def fetch_discord_roles(self) -> List[Dict[str, Any]]:
        """
        Fetch all Discord roles from the server via bot API.

        Returns:
            List of role dictionaries with id, name, color, position, member_count, etc.
        """
        if not self.guild_id:
            logger.error("SERVER_ID environment variable not set")
            return []

        try:
            url = f"{self.bot_api_url}/api/discord/roles"
            response = requests.get(url, timeout=self.REQUEST_TIMEOUT)

            if response.status_code == 200:
                roles = response.json().get('roles', [])
                logger.info(f"Fetched {len(roles)} Discord roles from server")
                return roles

            logger.error(
                f"Failed to fetch Discord roles (status {response.status_code}): {response.text}"
            )
            return []

        except Exception as e:
            # exc_info=True so a genuine failure surfaces a real traceback instead of
            # being silently mislabeled as "bot offline" by the caller's empty-list check.
            logger.error(f"Error fetching Discord roles: {e}", exc_info=True)
            return []

    def get_role_members(self, discord_role_id: str) -> List[Dict[str, Any]]:
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
            url = f"{self.bot_api_url}/api/discord/roles/{discord_role_id}/members"
            response = requests.get(url, timeout=self.REQUEST_TIMEOUT)

            if response.status_code == 200:
                return response.json().get('members', [])

            logger.error(f"Failed to get members for role {discord_role_id}")
            return []

        except Exception as e:
            logger.error(f"Error getting role members: {e}", exc_info=True)
            return []

    # -------------------------------------------------------------------------
    # Individual User Sync
    # -------------------------------------------------------------------------

    def assign_discord_role_to_user(
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
            url = f"{self.bot_api_url}/api/discord/roles/assign"
            payload = {'user_id': discord_user_id, 'role_id': discord_role_id}
            response = requests.post(url, json=payload, timeout=self.REQUEST_TIMEOUT)

            if response.status_code == 200:
                logger.info(f"Assigned Discord role {discord_role_id} to user {discord_user_id}")
                return True, "Role assigned successfully"

            logger.error(f"Failed to assign role: {response.text}")
            return False, f"Failed to assign role: {response.text}"

        except Exception as e:
            logger.error(f"Error assigning Discord role: {e}", exc_info=True)
            return False, str(e)

    def remove_discord_role_from_user(
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
            url = f"{self.bot_api_url}/api/discord/roles/remove"
            payload = {'user_id': discord_user_id, 'role_id': discord_role_id}
            response = requests.post(url, json=payload, timeout=self.REQUEST_TIMEOUT)

            if response.status_code == 200:
                logger.info(f"Removed Discord role {discord_role_id} from user {discord_user_id}")
                return True, "Role removed successfully"

            logger.error(f"Failed to remove role: {response.text}")
            return False, f"Failed to remove role: {response.text}"

        except Exception as e:
            logger.error(f"Error removing Discord role: {e}", exc_info=True)
            return False, str(e)

    # -------------------------------------------------------------------------
    # Flask Role Events - Sync on Role Assignment/Removal
    # -------------------------------------------------------------------------

    def on_flask_role_assigned(self, user: User, role: Role) -> bool:
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
        success, message = self.assign_discord_role_to_user(discord_id, role.discord_role_id)

        if success:
            logger.info(f"Synced Flask role '{role.name}' to Discord for user {user.username}")
        else:
            logger.error(f"Failed to sync role '{role.name}' to Discord for user {user.username}: {message}")

        return success

    def on_flask_role_removed(self, user: User, role: Role) -> bool:
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
        success, message = self.remove_discord_role_from_user(discord_id, role.discord_role_id)

        if success:
            logger.info(f"Removed Discord role for Flask role '{role.name}' from user {user.username}")
        else:
            logger.error(f"Failed to remove Discord role for '{role.name}' from user {user.username}: {message}")

        return success

    # -------------------------------------------------------------------------
    # Bulk Sync Operations
    # -------------------------------------------------------------------------

    def sync_flask_role_to_discord(self, role: Role) -> Dict[str, Any]:
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

                success, message = self.assign_discord_role_to_user(
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
                time.sleep(0.5)

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

    def sync_all_mapped_roles(self) -> Dict[str, Any]:
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
                role_result = self.sync_flask_role_to_discord(role)

                results['details'].append({
                    'role_name': role.name,
                    'result': role_result
                })

                if role_result['success']:
                    results['roles_synced'] += 1
                else:
                    results['roles_failed'] += 1

                # Rate limiting between roles
                time.sleep(1)

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
    Sync a role assignment to Discord.
    Call this when assigning a Flask role to a user.

    Args:
        user: The User being assigned the role
        role: The Role being assigned

    Returns:
        True if sync successful
    """
    return get_discord_role_sync_service().on_flask_role_assigned(user, role)


def sync_role_removal(user: User, role: Role) -> bool:
    """
    Sync a role removal to Discord.
    Call this when removing a Flask role from a user.

    Args:
        user: The User losing the role
        role: The Role being removed

    Returns:
        True if sync successful
    """
    return get_discord_role_sync_service().on_flask_role_removed(user, role)


def fetch_discord_roles_sync() -> List[Dict[str, Any]]:
    """
    Fetch Discord roles from the bot REST API.

    Returns:
        List of Discord role dictionaries
    """
    return get_discord_role_sync_service().fetch_discord_roles()


# -----------------------------------------------------------------------------
# Auto-mapping: Flask Role -> live Discord role
# -----------------------------------------------------------------------------

# Canonical Flask Role.name -> intended Discord role name(s), in priority order.
# These are lifted directly from the live role calculators that actually assign
# Discord roles today (app/discord_utils.py:get_expected_roles and the expected-
# role builder in app/tasks/tasks_discord.py). Keep this in sync with those if
# the Discord role vocabulary ever changes.
#
# Flask roles NOT listed here are intentionally app-only permission roles
# (Global Admin, Pub League Admin, Discord Admin, Pub League Coach, ECS FC Admin,
# Pub League Manager, pl-waitlist, etc.) — they have no Discord counterpart and
# are correctly left unmapped.
CANONICAL_DISCORD_ROLE_MAP: Dict[str, List[str]] = {
    'pl-premier':     ['ECS-FC-PL-PREMIER'],
    'pl-classic':     ['ECS-FC-PL-CLASSIC'],
    'pl-ecs-fc':      ['ECS-FC-PL-ECS-FC', 'ECS-FC-LEAGUE'],
    'pl-unverified':  ['ECS-FC-PL-UNVERIFIED'],
    'Premier Coach':  ['ECS-FC-PL-PREMIER-COACH'],
    'Classic Coach':  ['ECS-FC-PL-CLASSIC-COACH'],
    'ECS FC Coach':   ['ECS-FC-PL-ECS-FC-COACH'],
    'Premier Sub':    ['ECS-FC-PL-PREMIER-SUB'],
    'Classic Sub':    ['ECS-FC-PL-CLASSIC-SUB'],
    'ECS FC Sub':     ['ECS-FC-LEAGUE-SUB'],
    'Pub League Ref': ['Referee'],
}


def _normalize_role_name(name: str) -> str:
    """Normalize a role name for case/separator-insensitive matching.

    Mirrors app/discord_utils.normalize_name so matches line up with how the
    live calculators name Discord roles: UPPER, spaces/underscores -> hyphens.
    """
    if not name:
        return ''
    return name.strip().upper().replace(' ', '-').replace('_', '-')


def auto_map_flask_roles(session, discord_roles: List[Dict[str, Any]],
                         apply: bool = False) -> Dict[str, Any]:
    """Match Flask roles to live Discord roles and (optionally) persist the mapping.

    Args:
        session: SQLAlchemy session (g.db_session).
        discord_roles: live Discord roles from fetch_discord_roles_sync().
        apply: when True, write discord_role_id/name/last_synced_at onto matched
               Role rows; when False, only compute the proposed mapping.

    Returns:
        {
          'success': bool,
          'proposals': [ {role_id, role_name, matched, already_mapped, changed,
                          discord_role_id, discord_role_name, member_count,
                          reason} ],
          'matched': int, 'applied': int, 'app_only': int, 'unmatched': int,
        }
    """
    # Live Discord roles indexed by normalized name for lookup.
    live_by_norm: Dict[str, Dict[str, Any]] = {}
    for dr in discord_roles or []:
        norm = _normalize_role_name(dr.get('name', ''))
        if norm and norm not in live_by_norm:
            live_by_norm[norm] = dr

    roles = session.query(Role).order_by(Role.name).all()

    proposals: List[Dict[str, Any]] = []
    matched = applied = app_only = unmatched = 0

    for role in roles:
        # Determine candidate Discord role names for this Flask role. Roles not
        # in the canonical table are app-only permission roles with no Discord
        # counterpart — we do NOT attempt to match them, even if a live Discord
        # role happens to share their name, so a coincidental name collision can
        # never silently map (and later auto-push) a powerful admin role.
        candidates = CANONICAL_DISCORD_ROLE_MAP.get(role.name)
        is_app_only = candidates is None

        match = None
        if not is_app_only:
            for cand in candidates:
                match = live_by_norm.get(_normalize_role_name(cand))
                if match:
                    break

        current_id = role.discord_role_id or None

        if match:
            new_id = str(match.get('id'))
            new_name = match.get('name')
            already_mapped = current_id == new_id
            changed = not already_mapped
            matched += 1

            if apply and changed:
                role.discord_role_id = new_id
                role.discord_role_name = new_name
                role.last_synced_at = datetime.utcnow()
                applied += 1

            proposals.append({
                'role_id': role.id,
                'role_name': role.name,
                'matched': True,
                'already_mapped': already_mapped,
                'changed': changed,
                'discord_role_id': new_id,
                'discord_role_name': new_name,
                'member_count': match.get('member_count', 0),
                'reason': 'already mapped' if already_mapped else 'matched by name',
            })
        else:
            if is_app_only:
                app_only += 1
                reason = 'app-only permission role (no Discord equivalent)'
            else:
                unmatched += 1
                reason = 'expected Discord role not found on server'

            proposals.append({
                'role_id': role.id,
                'role_name': role.name,
                'matched': False,
                'already_mapped': False,
                'changed': False,
                'discord_role_id': current_id,
                'discord_role_name': role.discord_role_name,
                'member_count': None,
                'reason': reason,
            })

    return {
        'success': True,
        'proposals': proposals,
        'matched': matched,
        'applied': applied,
        'app_only': app_only,
        'unmatched': unmatched,
    }
