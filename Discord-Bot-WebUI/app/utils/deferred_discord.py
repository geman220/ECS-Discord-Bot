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

    def add_role_revoke(self, player_id: int, candidate_roles=None, team_ids=None):
        """Queue a precise revoke pass (see revoke_unexpected_roles_task).

        MUST be deferred rather than dispatched inline: the task re-derives the
        player's expected roles from the database, so it has to run after the
        request's transaction commits or it would read the pre-change roster and
        conclude nothing needs revoking.
        """
        self._operations.append(DeferredDiscordOperation(
            operation_type='revoke_roles',
            player_id=player_id,
            kwargs={'candidate_roles': list(candidate_roles or []),
                    'team_ids': list(team_ids or [])}
        ))

    def add_dm(self, player_id: int, message: str, **kwargs):
        self._operations.append(DeferredDiscordOperation(
            operation_type='send_dm',
            player_id=player_id,
            kwargs={'message': message, **kwargs}
        ))

    def execute_all(self) -> int:
        """Dispatch all queued operations to Celery. Empties the queue.

        assign_roles ops are COALESCED into batched tasks
        (process_discord_role_updates) rather than one task per player. Bulk admin
        actions (approve / role-assign 100-300 users) queue one assign op each, and
        the old per-op .delay() fan-out spawned N concurrent role-sync tasks that
        tripped Discord's rate limiter.

        Coalescing is done PER only_add MODE. This used to collapse every assign op
        into a single reconcile dispatch and drop only_add entirely, so a caller that
        asked for an additive grant (member-hub team placement documented its sync as
        "additive, never strips") silently got a full add+remove reconcile instead.
        remove_roles / DM ops are left per-player (rare, usually single-user).
        """
        if not self._operations:
            return 0

        from app.tasks.tasks_discord import (
            process_discord_role_updates,
            remove_player_roles_task,
            revoke_unexpected_roles_task,
        )

        # Split assign ops (batched, grouped by mode) from the rest. When the same
        # player is queued in both modes in one request, the reconcile wins — it is
        # the stricter operation and subsumes the additive one.
        assign_by_mode = {True: [], False: []}
        seen_assign = {}
        other_ops = []
        for op in self._operations:
            if op.operation_type == 'assign_roles':
                mode = bool(op.kwargs.get('only_add', False))
                prev = seen_assign.get(op.player_id)
                if prev is None:
                    seen_assign[op.player_id] = mode
                    assign_by_mode[mode].append(op.player_id)
                elif prev is True and mode is False:
                    # Upgrade this player from additive to reconcile.
                    assign_by_mode[True].remove(op.player_id)
                    assign_by_mode[False].append(op.player_id)
                    seen_assign[op.player_id] = False
            else:
                other_ops.append(op)

        dispatched = 0

        # One batched task per mode.
        for mode, player_ids in assign_by_mode.items():
            if not player_ids:
                continue
            try:
                from app.core.session_manager import managed_session
                from app.models import Player
                with managed_session() as s:
                    discord_ids = [
                        str(did) for (did,) in s.query(Player.discord_id).filter(
                            Player.id.in_(player_ids),
                            Player.discord_id.isnot(None),
                        ).all()
                    ]
                if discord_ids:
                    process_discord_role_updates.delay(discord_ids, only_add=mode)
                    dispatched += 1
            except Exception as e:
                logger.error(
                    f"Failed to dispatch batched role sync (only_add={mode}) for "
                    f"{len(player_ids)} players: {e}"
                )

        # Remaining ops (removals, DMs) stay per-player.
        for op in other_ops:
            try:
                if op.operation_type == 'remove_roles':
                    remove_player_roles_task.delay(
                        player_id=op.player_id, **op.kwargs
                    )
                elif op.operation_type == 'revoke_roles':
                    revoke_unexpected_roles_task.delay(
                        player_id=op.player_id, **op.kwargs
                    )
                elif op.operation_type == 'send_dm':
                    logger.warning(f"DM task not implemented for player {op.player_id}")
                    continue
                else:
                    logger.warning(f"Unknown operation type: {op.operation_type}")
                    continue
                dispatched += 1
            except Exception as e:
                logger.error(
                    f"Failed to dispatch Discord op {op.operation_type} "
                    f"for player {op.player_id}: {e}"
                )

        self._operations.clear()
        if dispatched:
            logger.info(
                f"Dispatched {dispatched} deferred Discord task(s) "
                f"({len(assign_by_mode[False])} reconcile / "
                f"{len(assign_by_mode[True])} add-only players batched for role sync)"
            )
        return dispatched

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
            # Dispatch on success. 4xx/5xx means the route returned an error or
            # validation failure; rolled-back work shouldn't trigger Discord
            # side effects.
            #
            # 3xx COUNTS AS SUCCESS. This gate used to be `< 300`, which silently
            # discarded every operation queued by a form route that ends in the
            # normal POST-redirect-GET pattern. The confirmed victim was
            # admin_panel/routes/user_management/roles.py `assign_user_roles`:
            # it queues a reconcile AND a precise revoke, then returns
            # `redirect(...)` -> 302 -> clear(). That route is the ONLY path in
            # the app that can strip a protected division/coach Discord role
            # (the reconcile allowlist blocks those by design), so this one
            # comparison meant revoking `pl-premier` never actually removed
            # ECS-FC-PL-PREMIER. It logged "Queued Discord role sync", flashed
            # success, and committed the Flask-side change -- so the UI and DB
            # agreed while Discord silently diverged, with no error anywhere and
            # nothing for the beat drain to pick up (no flag is set on this path,
            # and the drain is add-only regardless).
            #
            # Safety of widening: an exception escaping to @transactional runs
            # _safe_rollback() -> clear_deferred_discord(), which empties the
            # queue BEFORE any response exists. So a failed request cannot reach
            # here with live operations, whatever status it ends up returning.
            # ARM ONLY -- the actual dispatch happens after the COMMIT.
            #
            # after_this_request runs during process_response, but the request
            # session is committed later, by cleanup_request registered as
            # teardown_appcontext (app/init/database.py). Dispatching here
            # published Celery tasks BEFORE the transaction was durable: the
            # worker opens its own connection and cannot see uncommitted rows,
            # so it either acted on pre-change state or found nothing at all —
            # and if the teardown commit then failed, the tasks had already
            # gone out for work that was rolled back.
            #
            # @transactional routes commit inside the view, so they were fine;
            # everything relying on the teardown commit was not. Arming here and
            # flushing from cleanup_request (see flush_deferred_discord_after_commit)
            # makes the ordering correct for both.
            if 200 <= response.status_code < 400:
                g._discord_dispatch_armed = True
            else:
                g._discord_queue.clear()
                g._discord_dispatch_armed = False
            return response

    return g._discord_queue


def _queue_or_dispatch(add_op):
    """Queue an op on the request-scoped queue, or dispatch it NOW if there is no request.

    Outside a request context `get_discord_queue()` hands back an EPHEMERAL queue
    that nothing ever calls `execute_all()` on, so the operation was silently
    DISCARDED -- no log line, no exception, no trace. Callers of the module-level
    `defer_*` helpers get no handle on the queue, so they could not flush it even
    if they knew to.

    That made the helpers a landmine: correct from a route, a silent no-op from a
    Celery task, CLI command, socketio handler or background thread. Only
    `app/pub_league/services.py` had noticed and hand-rolled a
    `has_request_context()` branch. Centralising it here means no caller has to
    know, and a service-layer function stays correct when someone later wires it
    to a beat schedule.

    Args:
        add_op: callable taking the queue and enqueuing exactly one operation.
    """
    q = get_discord_queue()
    add_op(q)
    if not has_request_context():
        # No after_this_request hook will ever fire for this queue -- flush it
        # ourselves rather than dropping it on the floor.
        try:
            q.execute_all()
        except Exception as e:
            logger.error(
                f"Direct dispatch of Discord op outside request context failed: {e}"
            )


def flush_deferred_discord_after_commit():
    """Dispatch queued Discord ops. Call ONLY after the request session commits.

    Invoked by app/core/session_manager.cleanup_request immediately after a
    successful commit, which is the earliest point at which a Celery worker —
    reading through its own connection — can actually see the request's writes.

    Safe to call when nothing is queued, when no queue was ever created, or when
    the response was an error (the after_this_request hook disarms and clears in
    that case). Never raises: a dispatch problem must not turn into a failed
    teardown.
    """
    if not has_request_context():
        return
    queue = getattr(g, '_discord_queue', None)
    if queue is None or not getattr(g, '_discord_dispatch_armed', False):
        return
    try:
        queue.execute_all()
    except Exception as e:
        logger.error(f"Error dispatching deferred Discord ops after commit: {e}")
    finally:
        g._discord_dispatch_armed = False


def defer_discord_sync(player_id: int, only_add: bool = True):
    """Queue a Discord role sync. Dispatched after the request commits.

    Outside a request context, dispatches immediately instead of being dropped.
    """
    _queue_or_dispatch(lambda q: q.add_role_sync(player_id, only_add))


def defer_discord_removal(player_id: int):
    """Queue a Discord role removal. Dispatched after the request commits.

    Outside a request context, dispatches immediately instead of being dropped.
    """
    _queue_or_dispatch(lambda q: q.add_role_removal(player_id))


def defer_discord_revoke(player_id: int, candidate_roles=None, team_ids=None):
    """Queue a precise revoke pass. Dispatched after the request commits.

    Only roles the shared expected-role calculator no longer grants are removed, so
    this is safe to call after any roster or Flask-role change.

    Outside a request context, dispatches immediately instead of being dropped.
    """
    if not has_request_context():
        # Do NOT dispatch inline. add_role_revoke's own contract (above) says a
        # revoke MUST run after the caller's transaction commits, because the
        # task re-derives expected roles from the DB -- dispatched inline it
        # reads the PRE-change roster and either revokes nothing (a silent
        # no-op that looks like success) or revokes against stale state.
        #
        # Unlike a sync, getting this wrong REMOVES access. So outside a request
        # we refuse and say so, rather than guessing that the caller committed.
        # Callers in Celery/CLI should commit first and then call
        # revoke_unexpected_roles_task.delay(...) directly.
        logger.error(
            f"defer_discord_revoke called for player {player_id} outside a "
            f"request context; REFUSING to dispatch inline because the revoke "
            f"would re-derive expected roles from an uncommitted transaction. "
            f"Commit first, then call revoke_unexpected_roles_task.delay().")
        return
    _queue_or_dispatch(
        lambda q: q.add_role_revoke(player_id, candidate_roles, team_ids))


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
