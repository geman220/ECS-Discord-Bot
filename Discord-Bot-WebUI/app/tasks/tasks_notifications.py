# app/tasks/tasks_notifications.py

"""
Async Notification Delivery Task
================================

Wraps the synchronous NotificationOrchestrator.send() in a Celery task so
request handlers can fire-and-forget notifications instead of blocking on
SMTP / Discord / FCM / Twilio network I/O inside the HTTP response.

Request handlers dispatch via ``orchestrator.send_async(payload)``, which
serializes the payload and enqueues :func:`send_notification_async` here.
"""

import logging
from typing import Dict, Any

from app.decorators import celery_task
from app.services.notification_orchestrator import orchestrator, payload_from_dict

logger = logging.getLogger(__name__)


@celery_task(
    name='app.tasks.tasks_notifications.send_notification_async',
    max_retries=3,
    default_retry_delay=30,
)
def send_notification_async(self, session, payload_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Deliver a notification enqueued by ``orchestrator.send_async()``.

    Args:
        session: DB session injected by the celery_task decorator (unused
            directly here — the orchestrator opens its own sessions).
        payload_dict: Output of ``payload_to_dict(payload)``.

    Returns:
        The orchestrator's per-channel result dict.
    """
    try:
        payload = payload_from_dict(payload_dict)
    except Exception as e:
        # A malformed payload can't be fixed by retrying — log and drop.
        logger.error(f"Dropping notification with unparseable payload: {e}", exc_info=True)
        return {'error': 'invalid_payload'}

    result = orchestrator.send(payload)
    logger.info(
        f"Async notification delivered: type={payload.notification_type.value}, "
        f"users={len(payload.user_ids)}"
    )
    return result
