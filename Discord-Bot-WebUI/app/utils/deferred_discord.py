# app/utils/deferred_discord.py

"""
Deferred Discord Operations Module

This module provides utilities for deferring Discord API calls until after
database transactions complete. This prevents holding database locks during
network I/O operations.

Key features:
- Queue Discord operations during request processing
- Execute all queued operations after DB commit via Celery tasks
- Per-request queue stored in Flask's g object
- Support for role sync, role removal, and other Discord operations
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

from flask import g, has_request_context

logger = logging.getLogger(__name__)


@dataclass
class DeferredDiscordOperation:
    """
    Represents a single deferred Discord operation.

    Attributes:
        operation_type: Type of operation ('assign_roles', 'remove_roles', 'send_dm')
        player_id: The player ID for the operation
        kwargs: Additional keyword arguments for the operation
    """
    operation_type: str
    player_id: int
    kwargs: Dict[str, Any] = field(default_factory=dict)


class DeferredDiscordQueue:
    """
    Queue for collecting Discord operations to be executed after DB commit.

    This class collects Discord-related operations during request processing
    and executes them all at once after the database transaction commits.
    This prevents holding database locks while waiting for Discord API calls.

    Usage:
        queue = get_discord_queue()
        queue.add_role_sync(player_id=123, only_add=False)
        # ... later, after DB commit ...
        queue.execute_all()
    """

    def __init__(self):
        self._operations: List[DeferredDiscordOperation] = []
        self._executed = False

    def add_role_sync(self, player_id: int, only_add: bool = True):
        """
        Queue a Discord role sync operation for a player.

        Args:
            player_id: The player's database ID
            only_add: If True, only add roles (don't remove). If False, full sync.
        """
        self._operations.append(DeferredDiscordOperation(
            operation_type='assign_roles',
            player_id=player_id,
            kwargs={'only_add': only_add}
        ))
        logger.debug(f"Queued role sync for player {player_id} (only_add={only_add})")

    def add_role_removal(self, player_id: int):
        """
        Queue a Discord role removal operation for a player.

        Args:
            player_id: The player's database ID
        """
        self._operations.append(DeferredDiscordOperation(
            operation_type='remove_roles',
            player_id=player_id,
            kwargs={}
        ))
        logger.debug(f"Queued role removal for player {player_id}")

    def add_dm(self, player_id: int, message: str, **kwargs):
        """
        Queue a Discord DM operation for a player.

        Args:
            player_id: The player's database ID
            message: The message to send
            **kwargs: Additional arguments for the DM task
        """
        self._operations.append(DeferredDiscordOperation(
            operation_type='send_dm',
            player_id=player_id,
            kwargs={'message': message, **kwargs}
        ))
        logger.debug(f"Queued DM for player {player_id}")

    def execute_all(self):
        """
        Execute all queued Discord operations via Celery tasks.

        This should be called AFTER the database transaction has committed.
        Operations are executed asynchronously via Celery.

        Returns:
            int: Number of operations queued for execution
        """
        if self._executed:
            logger.warning("DeferredDiscordQueue.execute_all() called multiple times")
            return 0

        if not self._operations:
            logger.debug("No deferred Discord operations to execute")
            return 0

        # Import tasks lazily to avoid circular imports
        from app.tasks.tasks_discord import (
            assign_roles_to_player_task,
            remove_player_roles_task
        )

        executed_count = 0
        for op in self._operations:
            try:
                if op.operation_type == 'assign_roles':
                    assign_roles_to_player_task.delay(
                        player_id=op.player_id,
                        **op.kwargs
                    )
                    logger.info(f"Dispatched role sync task for player {op.player_id}")

                elif op.operation_type == 'remove_roles':
                    remove_player_roles_task.delay(
                        player_id=op.player_id,
                        **op.kwargs
                    )
                    logger.info(f"Dispatched role removal task for player {op.player_id}")

                elif op.operation_type == 'send_dm':
                    # DM tasks would be dispatched here if we had them
                    # For now, log a warning
                    logger.warning(f"DM task not implemented for player {op.player_id}")

                else:
                    logger.warning(f"Unknown operation type: {op.operation_type}")
                    continue

                executed_count += 1

            except Exception as e:
                logger.error(
                    f"Failed to dispatch Discord operation {op.operation_type} "
                    f"for player {op.player_id}: {e}"
                )

        self._operations.clear()
        self._executed = True

        logger.info(f"Executed {executed_count} deferred Discord operations")
        return executed_count

    def clear(self):
        """Clear all queued operations without executing them."""
        count = len(self._operations)
        self._operations.clear()
        if count > 0:
            logger.debug(f"Cleared {count} deferred Discord operations")

    def __len__(self):
        return len(self._operations)

    def __bool__(self):
        return len(self._operations) > 0


def get_discord_queue() -> DeferredDiscordQueue:
    """
    Get the deferred Discord queue for the current request.

    Returns a request-scoped queue when in a Flask request context,
    or a new queue instance when outside of a request context.

    Returns:
        DeferredDiscordQueue: The queue for the current context
    """
    if not has_request_context():
        # Outside of request context, return a new queue
        # This is useful for testing or background tasks
        return DeferredDiscordQueue()

    if not hasattr(g, '_discord_queue'):
        g._discord_queue = DeferredDiscordQueue()

    return g._discord_queue


def defer_discord_sync(player_id: int, only_add: bool = True):
    """
    Convenience function to queue a Discord role sync.

    This is the most common operation and provides a simple API.

    Args:
        player_id: The player's database ID
        only_add: If True, only add roles (don't remove existing ones)
    """
    get_discord_queue().add_role_sync(player_id, only_add)


def defer_discord_removal(player_id: int):
    """
    Convenience function to queue a Discord role removal.

    Args:
        player_id: The player's database ID
    """
    get_discord_queue().add_role_removal(player_id)


def execute_deferred_discord():
    """
    Execute all deferred Discord operations for the current request.

    Call this AFTER the database transaction has committed successfully.

    Returns:
        int: Number of operations executed
    """
    return get_discord_queue().execute_all()


def clear_deferred_discord():
    """
    Clear all deferred Discord operations without executing them.

    Useful for error handling when the transaction is rolled back.
    """
    get_discord_queue().clear()
