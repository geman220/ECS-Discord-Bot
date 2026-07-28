# app/services/discord_relink_service.py

"""
Discord ID relink service.

One place that knows how to move a Discord ID onto a Player, shared by the
two surfaces that do it:

- Admin Panel -> Discord -> Discord Players -> "Edit Discord ID" (manual)
- Admin Panel -> Discord -> Account Recovery -> "Approve" (queue)

They used to be one route; the queue would have been a second, subtly
different copy. Relinking has non-obvious housekeeping -- every cached
Discord field on the Player is now describing the WRONG account and must be
cleared, or the player shows as "in server" based on an account they no
longer control.

Transaction shape matters here. Role sync runs in Celery and re-reads the
player row, so the caller MUST commit before triggering it. Splitting apply
(pure DB) from sync (Celery + HTTP) keeps HTTP work out of an open
transaction -- under pgbouncer transaction pooling, holding a server slot
across a network call is how the pool starves.
"""

import re
import logging

from app.models import Player
from app.models.admin_config import AdminAuditLog

logger = logging.getLogger(__name__)

# Discord snowflakes are 17-20 digits today. Same rule the manual edit dialog
# enforces client-side; re-checked here because the queue path never sees it.
DISCORD_ID_PATTERN = re.compile(r'^\d{17,20}$')

# Every Player column that caches state about the LINKED Discord account.
# After a relink these all describe an account the member no longer controls,
# so they are reset rather than left to lie until the next sync.
_STALE_DISCORD_FIELDS = {
    'discord_username': None,
    'discord_in_server': None,
    'discord_last_checked': None,
    'discord_roles': None,
    'discord_last_verified': None,
    'discord_roles_synced': False,
    'last_sync_attempt': None,
}


class RelinkError(Exception):
    """Relink refused. ``code`` maps to an HTTP status for the API surfaces."""

    def __init__(self, message, code=400, details=None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}


def _reset_discord_cache(player, needs_update):
    for field, value in _STALE_DISCORD_FIELDS.items():
        setattr(player, field, value)
    player.discord_needs_update = needs_update


def clear_discord_id(session, player, *, actor_user_id, ip_address=None,
                     user_agent=None, reason=None):
    """Unlink a player's Discord account and wipe the cached Discord state."""
    old_discord_id = player.discord_id

    player.discord_id = None
    _reset_discord_cache(player, needs_update=False)

    AdminAuditLog.log_action(
        user_id=actor_user_id,
        action='discord_id_unlinked',
        resource_type='player',
        resource_id=str(player.id),
        old_value=old_discord_id,
        new_value=reason,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    logger.info(
        f"Unlinked discord_id={old_discord_id} from player {player.id} "
        f"by user {actor_user_id}"
        + (f" ({reason})" if reason else "")
    )
    return old_discord_id


def apply_discord_id(session, player, new_discord_id, *, actor_user_id,
                     ip_address=None, user_agent=None, take_from_other=False,
                     reason=None):
    """
    Point ``player`` at ``new_discord_id``.

    Args:
        take_from_other: when the target ID is already on a DIFFERENT player,
            unlink it there first instead of refusing. This is the
            "they already registered a duplicate account with the new
            Discord" case -- common in recovery, and impossible to resolve
            otherwise because the uniqueness constraint blocks the fix.
            Off by default so the manual path still fails loudly.

    Returns a dict describing what happened (for the caller's flash message).
    Raises ``RelinkError`` on refusal. Does NOT commit, and does NOT sync
    roles -- commit, then call ``sync_roles_after_relink``.
    """
    new_discord_id = str(new_discord_id or '').strip()
    if not DISCORD_ID_PATTERN.match(new_discord_id):
        raise RelinkError('Invalid Discord ID format. Must be a 17-20 digit number.')

    old_discord_id = player.discord_id
    if new_discord_id == old_discord_id:
        raise RelinkError('This is already the current Discord ID.')

    displaced_player_name = None
    other = session.query(Player).filter(
        Player.discord_id == new_discord_id,
        Player.id != player.id,
    ).first()

    if other is not None:
        if not take_from_other:
            raise RelinkError(
                f'Discord ID already linked to another player: {other.name}',
                code=409,
                details={'conflicting_player_id': other.id,
                         'conflicting_player_name': other.name},
            )
        displaced_player_name = other.name
        clear_discord_id(
            session, other,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            reason=f'Discord ID moved to player {player.id} ({player.name})',
        )
        # Flush so the unique index sees the NULL before we write the ID onto
        # the target player in the same transaction.
        session.flush()

    player.discord_id = new_discord_id
    _reset_discord_cache(player, needs_update=True)

    AdminAuditLog.log_action(
        user_id=actor_user_id,
        action='discord_id_updated',
        resource_type='player',
        resource_id=str(player.id),
        old_value=old_discord_id,
        new_value=new_discord_id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    logger.info(
        f"Relinked player {player.id} ({player.name}): "
        f"discord_id {old_discord_id} -> {new_discord_id} by user {actor_user_id}"
        + (f" (taken from {displaced_player_name})" if displaced_player_name else "")
        + (f" ({reason})" if reason else "")
    )

    return {
        'player_id': player.id,
        'player_name': player.name,
        'old_discord_id': old_discord_id,
        'new_discord_id': new_discord_id,
        'displaced_player_name': displaced_player_name,
    }


def sync_roles_after_relink(player_id, wait_seconds=None):
    """
    Push the player's roles onto the newly linked Discord account.

    Call AFTER committing -- the Celery worker re-reads the player row and
    would otherwise see the old Discord ID.

    ``wait_seconds`` blocks for the result so the admin gets a definitive
    message; None fires and forgets. Never raises -- a role-sync hiccup must
    not make a successful relink look failed.
    """
    from app.tasks.tasks_discord import update_player_discord_roles

    try:
        async_result = update_player_discord_roles.delay(player_id)
        if not wait_seconds:
            return 'Role sync queued for the new Discord account.'

        task_result = async_result.get(timeout=wait_seconds)
        if task_result.get('success'):
            return 'Roles synced to new Discord account.'
        return f"Role sync issue: {task_result.get('message', 'Unknown error')}"
    except Exception as e:
        logger.warning(f"Role sync after Discord relink failed for player {player_id}: {e}")
        return 'Role sync was queued but may still be processing.'
