# app/tasks/tasks_push_notifications.py

"""
Push Notification Campaign Tasks

Background tasks for processing push notification campaigns:
- Send scheduled campaigns
- Process due campaigns (periodic)
- Cleanup old campaign data
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any

from app.decorators import celery_task
from app.models import (
    PushNotificationCampaign, CampaignStatus, AdminAuditLog
)

logger = logging.getLogger(__name__)


@celery_task(
    name='app.tasks.tasks_push_notifications.send_scheduled_campaign',
    retry_backoff=True,
    bind=True,
    max_retries=3
)
def send_scheduled_campaign(self, session, campaign_id: int) -> Dict[str, Any]:
    """
    Send a scheduled push notification campaign.

    This task is triggered by Celery's apply_async with an ETA
    or called directly from the periodic task.

    Args:
        session: Database session from decorator
        campaign_id: ID of the campaign to send

    Returns:
        Dictionary with send results
    """
    logger.info(f"Processing scheduled campaign {campaign_id}")

    try:
        campaign = session.query(PushNotificationCampaign).get(campaign_id)

        if not campaign:
            logger.error(f"Campaign {campaign_id} not found")
            return {
                'success': False,
                'campaign_id': campaign_id,
                'error': 'Campaign not found'
            }

        # Verify campaign is in correct state
        if campaign.status not in [CampaignStatus.SCHEDULED.value, CampaignStatus.DRAFT.value]:
            logger.warning(
                f"Campaign {campaign_id} has status '{campaign.status}', skipping"
            )
            return {
                'success': False,
                'campaign_id': campaign_id,
                'error': f'Campaign status is {campaign.status}, cannot send'
            }

        # Import service here to avoid circular imports
        from app.services.push_campaign_service import PushCampaignService
        from app.services.push_targeting_service import PushTargetingService
        from app.services.notification_service import notification_service

        # Initialize services with session
        campaign_service = PushCampaignService(session)
        targeting_service = PushTargetingService(session)

        # Mark as sending
        campaign.status = CampaignStatus.SENDING.value
        campaign.actual_send_time = datetime.utcnow()
        session.commit()

        # Resolve targets
        tokens = targeting_service.resolve_targets(
            campaign.target_type,
            campaign.target_ids,
            campaign.platform_filter
        )

        if not tokens:
            campaign.status = CampaignStatus.FAILED.value
            campaign.error_message = "No recipients found for targeting criteria"
            session.commit()

            logger.warning(f"Campaign {campaign_id}: No recipients found")
            return {
                'success': False,
                'campaign_id': campaign_id,
                'error': 'No recipients found'
            }

        # Build data payload
        data = campaign.data_payload.copy() if campaign.data_payload else {}
        data['campaign_id'] = str(campaign_id)
        data['type'] = 'campaign'
        data['priority'] = campaign.priority

        if campaign.action_url:
            data['action_url'] = campaign.action_url
            data['deep_link'] = campaign.action_url

        # Send notifications
        result = notification_service.send_push_notification(
            tokens=tokens,
            title=campaign.title,
            body=campaign.body,
            data=data
        )

        # Update campaign with results
        sent_count = result.get('success', 0) + result.get('failure', 0)
        delivered_count = result.get('success', 0)
        failed_count = result.get('failure', 0)

        campaign.status = CampaignStatus.SENT.value
        campaign.sent_count = sent_count
        campaign.delivered_count = delivered_count
        campaign.failed_count = failed_count
        session.commit()

        logger.info(
            f"Campaign {campaign_id} sent successfully: "
            f"{delivered_count} delivered, {failed_count} failed"
        )

        # Log audit trail
        try:
            AdminAuditLog.log_action(
                user_id=campaign.created_by,
                action='push_campaign_sent',
                resource_type='push_notification_campaign',
                resource_id=str(campaign_id),
                new_value=f'Sent to {sent_count} devices ({delivered_count} delivered)',
            )
        except Exception as e:
            logger.warning(f"Could not log audit: {e}")

        return {
            'success': True,
            'campaign_id': campaign_id,
            'sent_count': sent_count,
            'delivered_count': delivered_count,
            'failed_count': failed_count,
            'token_count': len(tokens)
        }

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error sending campaign {campaign_id}: {error_msg}")

        # Try to update campaign status
        try:
            campaign = session.query(PushNotificationCampaign).get(campaign_id)
            if campaign:
                campaign.status = CampaignStatus.FAILED.value
                campaign.error_message = error_msg[:500]  # Truncate if needed
                session.commit()
        except Exception as inner_e:
            logger.error(f"Could not update campaign status: {inner_e}")

        # Re-raise for retry logic if configured
        raise


@celery_task(
    name='app.tasks.tasks_push_notifications.process_due_campaigns',
    retry_backoff=True,
    bind=True
)
def process_due_campaigns(self, session) -> Dict[str, Any]:
    """
    Process all campaigns that are scheduled and due to be sent.

    This task should be run periodically (e.g., every 5 minutes)
    to catch any campaigns that weren't triggered by their individual tasks.

    Args:
        session: Database session from decorator

    Returns:
        Dictionary with processing results
    """
    logger.info("Processing due campaigns")

    try:
        now = datetime.utcnow()

        # Find scheduled campaigns that are due
        due_campaigns = session.query(PushNotificationCampaign).filter(
            PushNotificationCampaign.status == CampaignStatus.SCHEDULED.value,
            PushNotificationCampaign.scheduled_send_time <= now
        ).all()

        processed = 0
        failed = 0
        results = []

        for campaign in due_campaigns:
            try:
                # Process each campaign
                result = send_scheduled_campaign(session, campaign.id)
                results.append(result)

                if result.get('success'):
                    processed += 1
                else:
                    failed += 1

            except Exception as e:
                logger.error(f"Error processing campaign {campaign.id}: {e}")
                failed += 1
                results.append({
                    'campaign_id': campaign.id,
                    'success': False,
                    'error': str(e)
                })

        logger.info(
            f"Due campaigns processed: {processed} successful, {failed} failed"
        )

        return {
            'success': True,
            'processed_count': processed,
            'failed_count': failed,
            'total_due': len(due_campaigns),
            'results': results
        }

    except Exception as e:
        logger.error(f"Error in process_due_campaigns: {e}")
        return {
            'success': False,
            'error': str(e)
        }


@celery_task(
    name='app.tasks.tasks_push_notifications.cleanup_old_campaigns',
    retry_backoff=True,
    bind=True
)
def cleanup_old_campaigns(self, session, days_old: int = 90) -> Dict[str, Any]:
    """
    Clean up old campaign data.

    Archives or deletes campaigns older than the specified number of days.
    Only processes campaigns in final states (sent, cancelled, failed).

    Args:
        session: Database session from decorator
        days_old: Age threshold in days (default 90)

    Returns:
        Dictionary with cleanup results
    """
    logger.info(f"Cleaning up campaigns older than {days_old} days")

    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days_old)

        # Find old campaigns in final states
        old_campaigns = session.query(PushNotificationCampaign).filter(
            PushNotificationCampaign.created_at < cutoff_date,
            PushNotificationCampaign.status.in_([
                CampaignStatus.SENT.value,
                CampaignStatus.CANCELLED.value,
                CampaignStatus.FAILED.value
            ])
        ).all()

        deleted_count = 0
        for campaign in old_campaigns:
            try:
                session.delete(campaign)
                deleted_count += 1
            except Exception as e:
                logger.warning(f"Could not delete campaign {campaign.id}: {e}")

        session.commit()

        logger.info(f"Cleaned up {deleted_count} old campaigns")

        return {
            'success': True,
            'deleted_count': deleted_count,
            'cutoff_date': cutoff_date.isoformat()
        }

    except Exception as e:
        logger.error(f"Error in cleanup_old_campaigns: {e}")
        return {
            'success': False,
            'error': str(e)
        }


@celery_task(
    name='app.tasks.tasks_push_notifications.check_stuck_campaigns',
    retry_backoff=True,
    bind=True
)
def check_stuck_campaigns(self, session, stuck_minutes: int = 30) -> Dict[str, Any]:
    """
    Check for campaigns stuck in 'sending' state.

    If a campaign has been in 'sending' state for too long,
    mark it as failed.

    Args:
        session: Database session from decorator
        stuck_minutes: Minutes threshold for stuck detection (default 30)

    Returns:
        Dictionary with check results
    """
    logger.info(f"Checking for campaigns stuck in sending state (>{stuck_minutes}m)")

    try:
        cutoff_time = datetime.utcnow() - timedelta(minutes=stuck_minutes)

        # Find stuck campaigns
        stuck_campaigns = session.query(PushNotificationCampaign).filter(
            PushNotificationCampaign.status == CampaignStatus.SENDING.value,
            PushNotificationCampaign.actual_send_time < cutoff_time
        ).all()

        fixed_count = 0
        for campaign in stuck_campaigns:
            try:
                campaign.status = CampaignStatus.FAILED.value
                campaign.error_message = f"Stuck in sending state for >{stuck_minutes} minutes"
                fixed_count += 1
                logger.warning(f"Marked stuck campaign {campaign.id} as failed")
            except Exception as e:
                logger.error(f"Could not fix stuck campaign {campaign.id}: {e}")

        session.commit()

        return {
            'success': True,
            'stuck_count': len(stuck_campaigns),
            'fixed_count': fixed_count
        }

    except Exception as e:
        logger.error(f"Error in check_stuck_campaigns: {e}")
        return {
            'success': False,
            'error': str(e)
        }
