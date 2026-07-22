# app/tasks/tasks_composed_messages.py

"""
Multi-channel composer delivery task.

Resolves the audience at send time and delivers via the
NotificationOrchestrator with an explicit channel allow-list, so every user's
channel preferences are honored. Chunked with a small inter-chunk sleep to
stay friendly to the Gmail API / Twilio when email or SMS is selected.
"""

import logging
import time
from datetime import datetime

from app.decorators import celery_task
from app.models.composed_message import ComposedMessage

logger = logging.getLogger(__name__)

CHUNK_SIZE = 50
# Sleep between chunks only when a rate-limited external channel is selected.
THROTTLED_CHANNELS = {'email', 'sms'}
CHUNK_SLEEP_SECONDS = 2


def _merge_results(total, part):
    for channel, counts in part.items():
        if channel == 'total_users':
            total['total_users'] = total.get('total_users', 0) + part['total_users']
            continue
        bucket = total.setdefault(channel, {})
        for key, value in counts.items():
            bucket[key] = bucket.get(key, 0) + value
    return total


@celery_task(
    name='app.tasks.tasks_composed_messages.send_composed_message',
    bind=True,
    max_retries=0,
)
def send_composed_message(self, session, message_id):
    """Deliver one ComposedMessage through the orchestrator."""
    msg = session.query(ComposedMessage).get(message_id)
    if not msg:
        logger.error(f"ComposedMessage {message_id} not found")
        return {'success': False, 'error': 'Message not found'}

    if msg.status not in ('scheduled', 'sending'):
        logger.warning(f"ComposedMessage {message_id} has status '{msg.status}', skipping")
        return {'success': False, 'error': f'Status is {msg.status}'}

    # Task-identity guard (same pattern as email blasts): only the task the
    # record currently points at may send it, so an orphaned eta task from a
    # cancelled schedule can never fire a re-scheduled or reset message.
    if msg.celery_task_id and self.request.id and msg.celery_task_id != self.request.id:
        logger.warning(
            f"ComposedMessage {message_id}: task {self.request.id} is stale "
            f"(record owned by {msg.celery_task_id}), skipping")
        return {'success': False, 'error': 'Stale task for this message'}

    msg.status = 'sending'
    msg.sent_at = datetime.utcnow()
    session.commit()

    try:
        from app.services import audience_service
        from app.services.notification_orchestrator import (
            orchestrator, NotificationPayload, NotificationType,
        )

        user_ids = audience_service.resolve_user_ids(session, msg.audience_type, msg.audience_ids)
        msg.total_recipients = len(user_ids)
        session.commit()

        if not user_ids:
            msg.status = 'failed'
            msg.error_message = 'No recipients matched the audience at send time.'
            session.commit()
            return {'success': False, 'error': msg.error_message}

        channels = list(msg.channels or [])
        throttle = bool(THROTTLED_CHANNELS.intersection(channels))

        # Force delivery: for the selected forceable channels, push past each
        # member's per-channel opt-out. SMS is never forced (the orchestrator
        # still enforces the verified-phone/consent gate under force_sms), and
        # a channel that wasn't selected stays None so it's simply not attempted.
        force_kwargs = {}
        if getattr(msg, 'force_delivery', False):
            force_kwargs = {
                'force_push': True if 'push' in channels else None,
                'force_email': True if 'email' in channels else None,
                'force_discord': True if 'discord' in channels else None,
            }

        totals = {}
        for start in range(0, len(user_ids), CHUNK_SIZE):
            chunk = user_ids[start:start + CHUNK_SIZE]
            payload = NotificationPayload(
                notification_type=NotificationType.ADMIN_ANNOUNCEMENT,
                title=msg.title,
                message=msg.message,
                user_ids=chunk,
                channels=channels,
                tiered=False,
                priority=msg.priority or 'normal',
                action_url=msg.action_url or None,
                **force_kwargs,
            )
            part = orchestrator.send(payload)
            totals = _merge_results(totals, part)
            if throttle and start + CHUNK_SIZE < len(user_ids):
                time.sleep(CHUNK_SLEEP_SECONDS)

        # Outcome: sent if at least one selected channel delivered something and
        # nothing hard-failed; partially_sent when there were failures alongside
        # successes; failed when nothing went out at all.
        delivered = sum(
            totals.get(ch, {}).get('success', 0) for ch in ('push', 'email', 'sms', 'discord')
        ) + totals.get('in_app', {}).get('created', 0)
        failures = sum(
            totals.get(ch, {}).get('failure', 0) for ch in ('push', 'email', 'sms', 'discord')
        )

        msg.results = totals
        if delivered and not failures:
            msg.status = 'sent'
        elif delivered:
            msg.status = 'partially_sent'
        else:
            msg.status = 'failed'
            msg.error_message = 'No channel delivered — recipients may all be opted out or unreachable.'
        session.commit()

        logger.info(
            f"ComposedMessage {message_id} finished: status={msg.status}, "
            f"recipients={msg.total_recipients}, delivered={delivered}, failures={failures}")
        return {'success': msg.status in ('sent', 'partially_sent'), 'results': totals}

    except Exception as e:
        logger.exception(f"ComposedMessage {message_id} delivery failed: {e}")
        session.rollback()
        msg = session.query(ComposedMessage).get(message_id)
        if msg:
            msg.status = 'failed'
            msg.error_message = str(e)[:500]
            session.commit()
        return {'success': False, 'error': str(e)}
