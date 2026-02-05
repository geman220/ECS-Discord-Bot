# app/tasks/tasks_email_broadcast.py

"""
Email Broadcast Celery Tasks

Background task for processing email campaign sends (BCC batch and individual).
"""

import time
import logging
from datetime import datetime

from app.decorators import celery_task
from app.models.email_campaigns import EmailCampaign, EmailCampaignRecipient
from app.models.core import User
from app.email import send_email, send_email_bcc
from app.services.email_broadcast_service import email_broadcast_service

logger = logging.getLogger(__name__)


@celery_task(
    name='app.tasks.tasks_email_broadcast.send_email_broadcast',
    retry_backoff=True,
    bind=True,
    max_retries=1,
)
def send_email_broadcast(self, session, campaign_id):
    """
    Send an email broadcast campaign.

    For BCC mode: batches recipients and sends via BCC with delays.
    For individual mode: sends personalized emails one at a time.

    Args:
        self: Celery task instance.
        session: Database session from decorator.
        campaign_id (int): ID of the campaign to send.

    Returns:
        dict: Result with success status and counts.
    """
    logger.info(f"Starting email broadcast for campaign {campaign_id}")

    campaign = session.query(EmailCampaign).get(campaign_id)
    if not campaign:
        logger.error(f"Campaign {campaign_id} not found")
        return {'success': False, 'error': 'Campaign not found'}

    if campaign.status not in ('draft', 'sending'):
        logger.warning(f"Campaign {campaign_id} has status '{campaign.status}', skipping")
        return {'success': False, 'error': f'Campaign status is {campaign.status}'}

    # Mark as sending
    campaign.status = 'sending'
    campaign.sent_at = datetime.utcnow()
    campaign.celery_task_id = self.request.id
    session.commit()

    # Render using template if one is assigned, otherwise use raw body
    if campaign.template_id and campaign.template:
        try:
            wrapper_html = campaign.template.render(campaign.body_html, campaign.subject)
        except Exception as e:
            logger.error(f"Failed to render email template: {e}")
            wrapper_html = campaign.body_html
    else:
        wrapper_html = campaign.body_html

    try:
        if campaign.send_mode == 'bcc_batch':
            _send_bcc_batch(session, campaign, wrapper_html)
        else:
            _send_individual(session, campaign, wrapper_html)
    except Exception as e:
        logger.error(f"Campaign {campaign_id} failed: {e}", exc_info=True)
        campaign.status = 'failed'
        session.commit()
        return {'success': False, 'error': str(e)}

    # Determine final status
    campaign = session.query(EmailCampaign).get(campaign_id)
    if campaign.status == 'cancelled':
        pass  # Keep cancelled
    elif campaign.failed_count == 0:
        campaign.status = 'sent'
    elif campaign.sent_count > 0:
        campaign.status = 'partially_sent'
    else:
        campaign.status = 'failed'

    campaign.completed_at = datetime.utcnow()
    session.commit()

    logger.info(
        f"Campaign {campaign_id} completed: "
        f"sent={campaign.sent_count}, failed={campaign.failed_count}, status={campaign.status}"
    )

    return {
        'success': True,
        'campaign_id': campaign_id,
        'status': campaign.status,
        'sent': campaign.sent_count,
        'failed': campaign.failed_count,
    }


def _send_bcc_batch(session, campaign, wrapper_html):
    """Send campaign using BCC batches."""
    batch_size = campaign.bcc_batch_size or 50
    recipients = session.query(EmailCampaignRecipient).filter_by(
        campaign_id=campaign.id, status='pending'
    ).all()

    # Collect emails for all pending recipients
    batches = []
    current_batch = []
    current_recipients = []
    all_recipient_batches = []

    for recipient in recipients:
        user = session.query(User).get(recipient.user_id)
        if not user or not user.email:
            recipient.status = 'skipped'
            recipient.error_message = 'No email address'
            campaign.failed_count += 1
            continue

        current_batch.append(user.email)
        current_recipients.append(recipient)

        if len(current_batch) >= batch_size:
            batches.append(list(current_batch))
            all_recipient_batches.append(list(current_recipients))
            current_batch = []
            current_recipients = []

    # Add remaining
    if current_batch:
        batches.append(current_batch)
        all_recipient_batches.append(current_recipients)

    session.commit()

    send_count = 0
    for i, (batch_emails, batch_recipients) in enumerate(zip(batches, all_recipient_batches)):
        # Check for cancellation
        if send_count > 0 and send_count % 10 == 0:
            session.refresh(campaign)
            if campaign.status == 'cancelled':
                logger.info(f"Campaign {campaign.id} cancelled during send")
                return

        result = send_email_bcc(batch_emails, campaign.subject, wrapper_html)
        now = datetime.utcnow()

        if result:
            for r in batch_recipients:
                r.status = 'sent'
                r.sent_at = now
            campaign.sent_count += len(batch_recipients)
        else:
            for r in batch_recipients:
                r.status = 'failed'
                r.error_message = 'BCC batch send failed'
            campaign.failed_count += len(batch_recipients)

        send_count += len(batch_recipients)
        session.commit()

        # Rate limit delay between batches
        if i < len(batches) - 1:
            time.sleep(2)


def _send_individual(session, campaign, wrapper_html):
    """Send campaign with per-recipient personalization."""
    recipients = session.query(EmailCampaignRecipient).filter_by(
        campaign_id=campaign.id, status='pending'
    ).all()

    send_count = 0
    for recipient in recipients:
        # Check for cancellation every 10 sends
        if send_count > 0 and send_count % 10 == 0:
            session.refresh(campaign)
            if campaign.status == 'cancelled':
                logger.info(f"Campaign {campaign.id} cancelled during send")
                return

        user = session.query(User).get(recipient.user_id)
        if not user or not user.email:
            recipient.status = 'skipped'
            recipient.error_message = 'No email address'
            campaign.failed_count += 1
            session.commit()
            send_count += 1
            continue

        # Personalize content
        p_subject, p_body = email_broadcast_service.personalize_content(
            session, campaign.subject, campaign.body_html, recipient.user_id
        )

        # Re-wrap personalized body with template if assigned
        if campaign.template_id and campaign.template:
            try:
                personalized_html = campaign.template.render(p_body, p_subject)
            except Exception:
                personalized_html = p_body
        else:
            personalized_html = p_body

        result = send_email(user.email, p_subject, personalized_html)
        now = datetime.utcnow()

        if result:
            recipient.status = 'sent'
            recipient.sent_at = now
            campaign.sent_count += 1
        else:
            recipient.status = 'failed'
            recipient.error_message = 'Send failed'
            campaign.failed_count += 1

        send_count += 1
        session.commit()

        # Rate limit delay
        time.sleep(1.5)
