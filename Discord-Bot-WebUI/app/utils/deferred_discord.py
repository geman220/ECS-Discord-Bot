# app/utils/deferred_discord.py

"""
Deferred Discord Operations Module

Discord work queued during a request is dispatched via Celery in an
after_this_request callback so it runs AFTER the @transactional decorator
commits. This keeps DB row locks short and prevents external I/O from
extending the transaction past idle_in_transaction_session_timeout.

Mirrors the pattern in app/utils/deferred_audit.py.
"""

import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any

from flask import g, has_request_context, after_this_request

logger = logging.getLogger(__name__)


@dataclass
class DeferredDiscordOperation:
    operation_type: str
    player_id: int
    kwargs: Dict[str, Any] = field(default_factory=dict)


class DeferredDiscordQueue:
    """Request-scoped queue of Discord operations to dispatch via Celery."""

    def __init__(self):
        self._operations: List[DeferredDiscordOperation] = []

    def add_role_sync(self, player_id: int, only_add: bool = True):
        self._operations.append(DeferredDiscordOperation(
            operation_type='assign_roles',
            player_id=player_id,
            kwargs={'only_add': only_add}
        ))

    def add_role_removal(self, player_id: int):
        self._operations.append(DeferredDiscordOperation(
            operation_type='remove_roles',
            player_id=player_id,
            kwargs={}
        ))

    def add_dm(self, player_id: int, message: str, **kwargs):
        self._operations.append(DeferredDiscordOperation(
            operation_type='send_dm',
            player_id=player_id,
            kwargs={'message': message, **kwargs}
        ))

    def execute_all(self) -> int:
        """Dispatch all queued operations to Celery. Empties the queue."""
        if not self._operations:
            return 0

        from app.tasks.tasks_discord import (
            assign_roles_to_player_task,
            remove_player_roles_task,
        )

        executed = 0
        for op in self._operations:
            try:
                if op.operation_type == 'assign_roles':
                    assign_roles_to_player_task.delay(
                        player_id=op.player_id, **op.kwargs
                    )
                elif op.operation_type == 'remove_roles':
                    remove_player_roles_task.delay(
                        player_id=op.player_id, **op.kwargs
                    )
                elif op.operation_type == 'send_dm':
                    logger.warning(f"DM task not implemented for player {op.player_id}")
                    continue
                else:
                    logger.warning(f"Unknown operation type: {op.operation_type}")
                    continue
                executed += 1
            except Exception as e:
                logger.error(
                    f"Failed to dispatch Discord op {op.operation_type} "
                    f"for player {op.player_id}: {e}"
                )

        self._operations.clear()
        if executed:
            logger.info(f"Dispatched {executed} deferred Discord operations")
        return executed

    def clear(self):
        self._operations.clear()

    def __len__(self):
        return len(self._operations)

    def __bool__(self):
        return bool(self._operations)


def get_discord_queue() -> DeferredDiscordQueue:
    """
    Return the request-scoped Discord queue, registering the after-commit
    dispatch the first time it's accessed in a request.

    Outside a request context, returns an ephemeral queue; callers should
    invoke execute_all() themselves (or, more typically, just call the
    underlying Celery task directly).
    """
    if not has_request_context():
        return DeferredDiscordQueue()

    if not hasattr(g, '_discord_queue'):
        g._discord_queue = DeferredDiscordQueue()

        @after_this_request
        def _dispatch_deferred_discord(response):
            # Only dispatch on success. Non-2xx means the route returned
            # an error or validation failure; rolled-back work shouldn't
            # trigger Discord side effects.
            if 200 <= response.status_code < 300:
                try:
                    g._discord_queue.execute_all()
                except Exception as e:
                    logger.error(f"Error dispatching deferred Discord ops: {e}")
            else:
                g._discord_queue.clear()
            return response

    return g._discord_queue


def defer_discord_sync(player_id: int, only_add: bool = True):
    """Queue a Discord role sync. Dispatched after the request commits."""
    get_discord_queue().add_role_sync(player_id, only_add)


def defer_discord_removal(player_id: int):
    """Queue a Discord role removal. Dispatched after the request commits."""
    get_discord_queue().add_role_removal(player_id)


def clear_deferred_discord():
    """
    Drop any queued Discord operations for the current request.

    Mostly redundant now that dispatch is gated on a 2xx response, but kept
    so existing callers don't break and so @transactional retries can scrub
    state between attempts.
    """
    if has_request_context() and hasattr(g, '_discord_queue'):
        g._discord_queue.clear()


def execute_deferred_discord() -> int:
    """
    Deprecated. Dispatch happens automatically via after_this_request.

    Retained as a no-op that returns the pending count for backward
    compatibility with existing routes; remove once all callers are gone.
    """
    if has_request_context() and hasattr(g, '_discord_queue'):
        return len(g._discord_queue)
    return 0
