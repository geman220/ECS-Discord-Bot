# app/services/push_campaign_service.py

"""
Push Notification Campaign Service

Manages push notification campaign lifecycle:
- Campaign creation and validation
- Scheduling for future delivery
- Immediate sending
- Cancellation
- Analytics tracking
"""

import logging
from datetime import datetime
from typing import Dict, Any, Optional, List

from app.core import db
from app.models import (
    User, AdminAuditLog,
    PushNotificationCampaign, NotificationGroup,
    CampaignStatus, CampaignPriority, TargetType
)
from app.services.push_targeting_service import push_targeting_service
from app.services.notification_service import notification_service

logger = logging.getLogger(__name__)


class PushCampaignService:
    """Service for managing push notification campaigns."""

    def __init__(self, session=None):
        """Initialize with optional database session."""
        self._session = session

    @property
    def session(self):
        """Get database session."""
        return self._session or db.session

    def create_campaign(
        self,
        name: str,
        title: str,
        body: str,
        target_type: str,
        created_by: int,
        target_ids: Optional[List[Any]] = None,
        notification_group_id: Optional[int] = None,
        platform_filter: str = 'all',
        priority: str = 'normal',
        action_url: Optional[str] = None,
        data_payload: Optional[Dict] = None,
        send_immediately: bool = True,
        scheduled_send_time: Optional[datetime] = None,
    ) -> PushNotificationCampaign:
        """
        Create a new push notification campaign.

        Args:
            name: Campaign name for tracking
            title: Notification title (max 50 chars for iOS)
            body: Notification body
            target_type: Target type ('all', 'team', 'league', etc.)
            created_by: User ID of creator
            target_ids: List of target IDs (team IDs, role names, etc.)
            notification_group_id: ID of notification group (if using group targeting)
            platform_filter: Platform filter ('all', 'ios', 'android')
            priority: Priority level ('normal', 'high', 'urgent')
            action_url: Deep link URL for notification action
            data_payload: Additional custom data
            send_immediately: Whether to send now (True) or schedule
            scheduled_send_time: When to send (required if not immediate)

        Returns:
            Created PushNotificationCampaign instance
        """
        # Validate required fields
        if not name or not title or not body:
            raise ValueError("name, title, and body are required")

        if not send_immediately and not scheduled_send_time:
            raise ValueError("scheduled_send_time required when not sending immediately")

        if scheduled_send_time and scheduled_send_time <= datetime.utcnow():
            raise ValueError("scheduled_send_time must be in the future")

        # Validate target type
        valid_target_types = [t.value for t in TargetType]
        if target_type not in valid_target_types:
            raise ValueError(f"Invalid target_type. Must be one of: {valid_target_types}")

        # Calculate target count preview
        target_count = 0
        try:
            preview = push_targeting_service.preview_recipient_count(
                target_type, target_ids, platform_filter
            )
            target_count = preview.get('total_tokens', 0)
        except Exception as e:
            logger.warning(f"Could not preview target count: {e}")

        # Determine initial status
        status = CampaignStatus.DRAFT.value
        if send_immediately:
            status = CampaignStatus.DRAFT.value  # Will be updated when actually sent

        campaign = PushNotificationCampaign(
            name=name,
            title=title[:100],  # Truncate to field limit
            body=body,
            target_type=target_type,
            target_ids=target_ids,
            notification_group_id=notification_group_id,
            platform_filter=platform_filter,
            status=status,
            send_immediately=send_immediately,
            scheduled_send_time=scheduled_send_time,
            priority=priority,
            action_url=action_url,
            data_payload=data_payload,
            target_count=target_count,
            created_by=created_by,
        )

        self.session.add(campaign)
        self.session.commit()

        logger.info(f"Created campaign {campaign.id}: {name} (target_count={target_count})")
        return campaign

    def send_campaign_now(self, campaign_id: int) -> Dict[str, Any]:
        """
        Send a campaign immediately.

        Args:
            campaign_id: Campaign ID to send

        Returns:
            Dictionary with send results
        """
        campaign = self.session.query(PushNotificationCampaign).get(campaign_id)
        if not campaign:
            raise ValueError(f"Campaign {campaign_id} not found")

        if campaign.status not in [CampaignStatus.DRAFT.value, CampaignStatus.SCHEDULED.value]:
            raise ValueError(f"Campaign cannot be sent (status={campaign.status})")

        # Mark as sending
        campaign.mark_as_sending()
        self.session.commit()

        try:
            # Resolve targets to tokens
            tokens = push_targeting_service.resolve_targets(
                campaign.target_type,
                campaign.target_ids,
                campaign.platform_filter
            )

            if not tokens:
                campaign.mark_as_failed("No recipients found for targeting criteria")
                self.session.commit()
                return {
                    'success': False,
                    'error': 'No recipients found',
                    'campaign_id': campaign_id,
                }

            # Build data payload
            data = campaign.data_payload.copy() if campaign.data_payload else {}
            data['campaign_id'] = str(campaign_id)
            data['type'] = 'campaign'
            data['priority'] = campaign.priority

            if campaign.action_url:
                data['action_url'] = campaign.action_url
                data['deep_link'] = campaign.action_url

            # Send notification
            result = notification_service.send_push_notification(
                tokens=tokens,
                title=campaign.title,
                body=campaign.body,
                data=data
            )

            # Update campaign with results
            sent = result.get('success', 0) + result.get('failure', 0)
            delivered = result.get('success', 0)
            failed = result.get('failure', 0)

            campaign.mark_as_sent(sent, delivered, failed)
            self.session.commit()

            logger.info(
                f"Campaign {campaign_id} sent: {delivered} delivered, {failed} failed"
            )

            return {
                'success': True,
                'campaign_id': campaign_id,
                'sent_count': sent,
                'delivered_count': delivered,
                'failed_count': failed,
                'token_count': len(tokens),
            }

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error sending campaign {campaign_id}: {error_msg}")
            campaign.mark_as_failed(error_msg)
            self.session.commit()

            return {
                'success': False,
                'campaign_id': campaign_id,
                'error': error_msg,
            }

    def schedule_campaign(
        self,
        campaign_id: int,
        send_time: datetime
    ) -> Dict[str, Any]:
        """
        Schedule a campaign for future delivery.

        Args:
            campaign_id: Campaign ID to schedule
            send_time: When to send the campaign

        Returns:
            Dictionary with scheduling result
        """
        campaign = self.session.query(PushNotificationCampaign).get(campaign_id)
        if not campaign:
            raise ValueError(f"Campaign {campaign_id} not found")

        if not campaign.is_editable:
            raise ValueError(f"Campaign cannot be scheduled (status={campaign.status})")

        if send_time <= datetime.utcnow():
            raise ValueError("send_time must be in the future")

        # Update campaign
        campaign.send_immediately = False
        campaign.scheduled_send_time = send_time
        campaign.status = CampaignStatus.SCHEDULED.value

        # Schedule Celery task
        try:
            from app.tasks.tasks_push_notifications import send_scheduled_campaign
            task = send_scheduled_campaign.apply_async(
                args=[campaign_id],
                eta=send_time
            )
            campaign.celery_task_id = task.id
        except ImportError:
            logger.warning("Celery task not available - campaign will need manual processing")
        except Exception as e:
            logger.error(f"Error scheduling Celery task: {e}")

        self.session.commit()

        logger.info(f"Campaign {campaign_id} scheduled for {send_time}")

        return {
            'success': True,
            'campaign_id': campaign_id,
            'scheduled_send_time': send_time.isoformat(),
            'celery_task_id': campaign.celery_task_id,
        }

    def cancel_campaign(self, campaign_id: int, cancelled_by: int) -> Dict[str, Any]:
        """
        Cancel a scheduled campaign.

        Args:
            campaign_id: Campaign ID to cancel
            cancelled_by: User ID of person cancelling

        Returns:
            Dictionary with cancellation result
        """
        campaign = self.session.query(PushNotificationCampaign).get(campaign_id)
        if not campaign:
            raise ValueError(f"Campaign {campaign_id} not found")

        if not campaign.is_cancellable:
            raise ValueError(f"Campaign cannot be cancelled (status={campaign.status})")

        # Revoke Celery task if exists
        if campaign.celery_task_id:
            try:
                from celery.result import AsyncResult
                task = AsyncResult(campaign.celery_task_id)
                task.revoke()
            except Exception as e:
                logger.warning(f"Could not revoke Celery task: {e}")

        # Mark as cancelled
        campaign.cancel(cancelled_by)
        self.session.commit()

        logger.info(f"Campaign {campaign_id} cancelled by user {cancelled_by}")

        return {
            'success': True,
            'campaign_id': campaign_id,
            'cancelled_at': campaign.cancelled_at.isoformat(),
        }

    def update_campaign(
        self,
        campaign_id: int,
        **updates
    ) -> PushNotificationCampaign:
        """
        Update a draft campaign.

        Args:
            campaign_id: Campaign ID to update
            **updates: Fields to update

        Returns:
            Updated campaign instance
        """
        campaign = self.session.query(PushNotificationCampaign).get(campaign_id)
        if not campaign:
            raise ValueError(f"Campaign {campaign_id} not found")

        if not campaign.is_editable:
            raise ValueError(f"Campaign cannot be edited (status={campaign.status})")

        # Allowed update fields
        allowed_fields = [
            'name', 'title', 'body', 'target_type', 'target_ids',
            'notification_group_id', 'platform_filter', 'priority',
            'action_url', 'data_payload', 'scheduled_send_time'
        ]

        for field, value in updates.items():
            if field in allowed_fields:
                setattr(campaign, field, value)

        # Recalculate target count if targeting changed
        if any(f in updates for f in ['target_type', 'target_ids', 'platform_filter']):
            try:
                preview = push_targeting_service.preview_recipient_count(
                    campaign.target_type,
                    campaign.target_ids,
                    campaign.platform_filter
                )
                campaign.target_count = preview.get('total_tokens', 0)
            except Exception as e:
                logger.warning(f"Could not update target count: {e}")

        self.session.commit()
        return campaign

    def duplicate_campaign(
        self,
        campaign_id: int,
        new_name: Optional[str] = None,
        created_by: Optional[int] = None
    ) -> PushNotificationCampaign:
        """
        Duplicate an existing campaign.

        Args:
            campaign_id: Campaign ID to duplicate
            new_name: Optional new name for the copy
            created_by: User ID for the new campaign creator

        Returns:
            New campaign instance
        """
        original = self.session.query(PushNotificationCampaign).get(campaign_id)
        if not original:
            raise ValueError(f"Campaign {campaign_id} not found")

        new_campaign = original.duplicate(new_name, created_by)
        self.session.add(new_campaign)
        self.session.commit()

        logger.info(f"Duplicated campaign {campaign_id} as {new_campaign.id}")
        return new_campaign

    def get_campaign_status(self, campaign_id: int) -> Dict[str, Any]:
        """
        Get detailed campaign status and analytics.

        Args:
            campaign_id: Campaign ID

        Returns:
            Dictionary with status and analytics
        """
        campaign = self.session.query(PushNotificationCampaign).get(campaign_id)
        if not campaign:
            raise ValueError(f"Campaign {campaign_id} not found")

        return campaign.to_dict(include_group=True)

    def list_campaigns(
        self,
        status: Optional[str] = None,
        created_by: Optional[int] = None,
        page: int = 1,
        per_page: int = 20,
        order_by: str = 'created_at',
        order_dir: str = 'desc'
    ) -> Dict[str, Any]:
        """
        List campaigns with filtering and pagination.

        Args:
            status: Filter by status
            created_by: Filter by creator
            page: Page number
            per_page: Items per page
            order_by: Field to order by
            order_dir: Order direction ('asc' or 'desc')

        Returns:
            Dictionary with campaigns and pagination info
        """
        query = self.session.query(PushNotificationCampaign)

        if status:
            query = query.filter(PushNotificationCampaign.status == status)
        if created_by:
            query = query.filter(PushNotificationCampaign.created_by == created_by)

        # Ordering
        order_field = getattr(PushNotificationCampaign, order_by, PushNotificationCampaign.created_at)
        if order_dir == 'desc':
            query = query.order_by(order_field.desc())
        else:
            query = query.order_by(order_field.asc())

        # Pagination
        total = query.count()
        campaigns = query.offset((page - 1) * per_page).limit(per_page).all()

        return {
            'campaigns': [c.to_dict() for c in campaigns],
            'total': total,
            'page': page,
            'per_page': per_page,
            'pages': (total + per_page - 1) // per_page,
        }

    def get_scheduled_campaigns(self) -> List[PushNotificationCampaign]:
        """
        Get all campaigns that are scheduled and due to be sent.

        Returns:
            List of campaigns ready to send
        """
        now = datetime.utcnow()
        return self.session.query(PushNotificationCampaign).filter(
            PushNotificationCampaign.status == CampaignStatus.SCHEDULED.value,
            PushNotificationCampaign.scheduled_send_time <= now
        ).all()


# Singleton instance for easy import
push_campaign_service = PushCampaignService()
