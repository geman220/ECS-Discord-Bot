"""
Account approval / role assignment FCM push.

Fires a high-priority push to a user the moment their account becomes usable —
either through first-time approval (`is_approved: false → true`) or a new
role assignment (mid-season promotion, sub pool addition, etc.). Mobile's
pending-approval screen subscribes to these so users auto-redirect to /home
without waiting on the 30s poll cycle.

The push goes through the existing notification orchestrator so all the
delivery rules (FCM token lookup, in-app notification mirror, opt-out
honoring) work the same as everything else.

Wiring: a SQLAlchemy `set` event on `User.is_approved` flags the instance,
and an `after_commit` event on the Session fires the push only if the
transaction actually persisted. Every code path that flips `is_approved`
benefits — and there are 13+ of them. Doing it via event hooks instead of
instrumenting each handler is the only sane option.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import event, inspect as sa_inspect
from sqlalchemy.orm import Session

from app.models import User

logger = logging.getLogger(__name__)


# session.info key under which we stash User instances pending an approval
# push. Using session.info instead of scanning identity_map keeps after_commit
# O(1) for sessions that don't have any pending pushes.
_SESSION_INFO_KEY = 'pending_account_approval_users'


def push_account_approved(user_id: int, *, role_label: Optional[str] = None) -> None:
    """
    Fire-and-forget FCM push for a newly-approved user.

    Routes through the standard NotificationOrchestrator so:
      - the user's in-app bell list also gets an entry
      - email/SMS/Discord channels are explicitly suppressed (push only)
      - Firebase Admin SDK send + token cleanup behave identically to other notifications

    Failures are logged but never bubble up — a missing FCM token (permission
    denied, app uninstalled, etc.) is a normal no-op.
    """
    try:
        # Lazy import to avoid pulling the orchestrator into app boot before
        # blueprints are wired (event listener fires from anywhere).
        from app.services.notification_orchestrator import (
            orchestrator, NotificationPayload, NotificationType,
        )
    except Exception as exc:
        logger.warning(f"orchestrator unavailable for account_approved push: {exc}")
        return

    body = (
        f"You've been added as a {role_label}. Tap to enter."
        if role_label
        else "Your ECS FC profile has been approved. Tap to enter."
    )

    try:
        orchestrator.send(NotificationPayload(
            notification_type=NotificationType.ACCOUNT_APPROVED,
            title="You're in!",
            message=body,
            user_ids=[int(user_id)],
            data={
                'type': 'account_approved',
                'user_id': str(user_id),
                'role_label': role_label or '',
            },
            priority='high',
            force_push=True,
            force_email=False,
            force_sms=False,
            force_discord=False,
        ))
        logger.info(f"account_approved push dispatched for user {user_id} (role_label={role_label!r})")
    except Exception:
        logger.exception(f"account_approved push failed for user {user_id}")


def push_role_assigned(user_id: int, *, role_label: str) -> None:
    """
    Fire-and-forget FCM push for an already-approved user gaining a new role.

    Same pipeline as account_approved; mobile handles both types identically
    (refresh user payload + auto-route). The split exists for in-app history
    copy. If a flow doesn't care about the distinction, prefer
    push_account_approved.
    """
    try:
        from app.services.notification_orchestrator import (
            orchestrator, NotificationPayload, NotificationType,
        )
    except Exception as exc:
        logger.warning(f"orchestrator unavailable for role_assigned push: {exc}")
        return

    try:
        orchestrator.send(NotificationPayload(
            notification_type=NotificationType.ROLE_ASSIGNED,
            title="New role assigned",
            message=f"You've been added as a {role_label}. Tap to enter.",
            user_ids=[int(user_id)],
            data={
                'type': 'role_assigned',
                'user_id': str(user_id),
                'role_label': role_label,
            },
            priority='high',
            force_push=True,
            force_email=False,
            force_sms=False,
            force_discord=False,
        ))
        logger.info(f"role_assigned push dispatched for user {user_id} (role_label={role_label!r})")
    except Exception:
        logger.exception(f"role_assigned push failed for user {user_id}")


# -----------------------------------------------------------------------------
# SQLAlchemy event hooks: fire on User.is_approved False → True
# -----------------------------------------------------------------------------

@event.listens_for(User.is_approved, 'set', propagate=True)
def _track_approval_change(target, value, oldvalue, initiator):
    """
    Mark an instance for a deferred push when is_approved transitions to True.

    We don't push from here directly because:
      1. The transaction may roll back, and we'd ship a phantom approval.
      2. user.id may not exist yet for a freshly-inserted row before flush.

    Instead we record the instance against its session's info dict and fire
    from the after_commit hook below.

    `oldvalue` semantics:
      - `NEVER_SET` for first-time attribute assignment (new User instances)
      - `False` / `None` for genuine pending-state users
      - `True` for already-approved users (no-op)
    """
    if value is not True or oldvalue is True:
        return

    state = sa_inspect(target)
    session = state.session
    if session is None:
        # Instance not yet attached to a session — set a fallback instance flag
        # so a later session.add → commit still fires the push. Rare path.
        target.__dict__['_pending_account_approved_push'] = True
        return
    bucket = session.info.setdefault(_SESSION_INFO_KEY, [])
    bucket.append(target)


@event.listens_for(Session, 'after_commit')
def _fire_pending_approval_pushes(session):
    """
    After a successful commit, fire one push per flagged User instance.

    O(1) when there's nothing pending — `session.info.pop` is a dict lookup.
    Sweep the rare instance-flag fallback path too, to catch instances that
    were detached when the 'set' event fired and only attached later.
    """
    pending = session.info.pop(_SESSION_INFO_KEY, None) or []

    # Fallback sweep: instances flagged before they were attached to a session.
    for instance in list(session.identity_map.values()):
        if not isinstance(instance, User):
            continue
        if instance.__dict__.pop('_pending_account_approved_push', False):
            pending.append(instance)

    if not pending:
        return

    seen_ids = set()
    for inst in pending:
        try:
            uid = inst.id
        except Exception:
            continue
        if uid is None or uid in seen_ids:
            continue
        seen_ids.add(uid)
        try:
            push_account_approved(uid)
        except Exception:
            # Already wrapped inside push_account_approved; belt-and-braces.
            logger.exception(f"approval push fan-out failed for user {uid}")


@event.listens_for(Session, 'after_rollback')
def _drop_pending_on_rollback(session):
    """A rollback means no approval actually persisted — drop the queue."""
    session.info.pop(_SESSION_INFO_KEY, None)


def register():
    """
    Idempotent registration hook.

    The decorators above already attach the listeners at module-import time
    (Python evaluates the @event.listens_for decorator on first import of
    this module). This function exists so the app boot can simply call
    `register()` and be sure the module has been imported at least once,
    even if no other code path imports it yet.
    """
    return True
