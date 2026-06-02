# app/tasks/tasks_waitlist.py

"""
Waitlist Celery Tasks

Sends the confirmation email after a successful waitlist registration. Kept as
a background task so a slow/failed Gmail API call never blocks the registration
request or the redirect to the confirmation page.
"""

import logging

from app.decorators import celery_task
from app.models.core import User
from app.email import send_email

logger = logging.getLogger(__name__)


def _confirmation_id(user):
    """Mirror of app.auth.waitlist.waitlist_confirmation_id (kept local so the
    task has no import cycle with the auth blueprint)."""
    joined = getattr(user, 'waitlist_joined_at', None) or getattr(user, 'created_at', None)
    from datetime import datetime
    year = joined.year if joined else datetime.utcnow().year
    return f"WL-{year}-{user.id:05d}"


@celery_task(
    name='app.tasks.tasks_waitlist.send_waitlist_confirmation_email',
    retry_backoff=True,
    bind=True,
    max_retries=2,
)
def send_waitlist_confirmation_email(self, session, user_id):
    """
    Email a waitlist signup their confirmation, including their reference ID.

    Args:
        self: Celery task instance.
        session: Database session from the decorator.
        user_id (int): ID of the user who just joined the waitlist.

    Returns:
        dict: {'success': bool, ...}
    """
    user = session.query(User).get(user_id)
    if not user:
        logger.warning(f"Waitlist confirmation email skipped: user {user_id} not found")
        return {'success': False, 'reason': 'user_not_found'}

    # User.email decrypts the stored address; guard against missing/blank.
    try:
        to_email = user.email
    except Exception as e:  # decryption / attribute issues should not crash the task
        logger.error(f"Could not read email for user {user_id}: {e}")
        return {'success': False, 'reason': 'email_unreadable'}

    if not to_email:
        logger.info(f"Waitlist confirmation email skipped: user {user_id} has no email")
        return {'success': False, 'reason': 'no_email'}

    confirmation_id = _confirmation_id(user)
    display_name = (user.username or '').strip() or 'there'

    subject = "You're on the ECS Pub League waitlist"
    body = f"""\
<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
            max-width:560px;margin:0 auto;color:#111827;line-height:1.55;">
  <p>Hey {display_name},</p>
  <p>You're on the waitlist — nice. We'll email you the moment a spot opens up,
     so there's nothing else you need to do right now.</p>
  <p style="margin:24px 0;padding:14px 18px;background:#f3f4f6;border-radius:10px;
            font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:15px;">
    Your reference: <strong>{confirmation_id}</strong>
  </p>
  <p>Hang onto that reference in case you need to get in touch with us about your spot.</p>
  <p>See you on the pitch,<br>ECS Pub League</p>
</div>
"""

    try:
        result = send_email(to=to_email, subject=subject, body=body)
    except Exception as e:
        logger.error(f"Waitlist confirmation email send failed for user {user_id}: {e}")
        raise self.retry(exc=e)

    if result is None:
        logger.warning(f"Waitlist confirmation email returned None for user {user_id}")
        return {'success': False, 'reason': 'send_returned_none', 'confirmation_id': confirmation_id}

    logger.info(f"Sent waitlist confirmation email to user {user_id} ({confirmation_id})")
    return {'success': True, 'confirmation_id': confirmation_id}
