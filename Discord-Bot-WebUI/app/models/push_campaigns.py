# app/models/push_campaigns.py

"""
Push Notification Campaign Models

Models for managing push notification targeting, groups, and campaigns:
- NotificationGroup: Reusable groups for targeted push notifications
- NotificationGroupMember: Members of static notification groups
- PushNotificationCampaign: Campaign tracking with scheduling and analytics
"""

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any

from app.core import db


class GroupType(str, Enum):
    """Types of notification groups"""
    DYNAMIC = 'dynamic'  # Criteria-based, recalculated each time
    STATIC = 'static'    # Fixed user list


class CampaignStatus(str, Enum):
    """Campaign status values"""
    DRAFT = 'draft'
    SCHEDULED = 'scheduled'
    SENDING = 'sending'
    SENT = 'sent'
    CANCELLED = 'cancelled'
    FAILED = 'failed'


class CampaignPriority(str, Enum):
    """Campaign priority levels"""
    NORMAL = 'normal'
    HIGH = 'high'
    URGENT = 'urgent'


class TargetType(str, Enum):
    """Target types for campaigns"""
    ALL = 'all'
    TEAM = 'team'
    LEAGUE = 'league'
    ROLE = 'role'
    POOL = 'pool'
    GROUP = 'group'
    PLATFORM = 'platform'
    CUSTOM = 'custom'


class NotificationGroup(db.Model):
    """
    Reusable groups for targeted push notifications.

    Supports both dynamic (rule-based) and static (user list) groups.
    Dynamic groups recalculate membership based on criteria each time.
    Static groups maintain a fixed list of members.
    """
    __tablename__ = 'notification_groups'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    group_type = db.Column(db.String(20), nullable=False, default=GroupType.DYNAMIC.value)

    # JSON criteria for dynamic groups
    # Example: {"target_type": "role", "role_names": ["Coach", "Admin"]}
    # Example: {"target_type": "team", "team_ids": [1, 2, 3]}
    criteria = db.Column(db.JSON, nullable=True)

    # Audit fields
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    # Relationships
    creator = db.relationship('User', foreign_keys=[created_by], backref='created_notification_groups')
    members = db.relationship('NotificationGroupMember', back_populates='group',
                             cascade='all, delete-orphan', lazy='dynamic')
    campaigns = db.relationship('PushNotificationCampaign', back_populates='notification_group')

    def __repr__(self):
        return f'<NotificationGroup {self.id}:{self.name}>'

    @property
    def is_dynamic(self) -> bool:
        """Check if this is a dynamic group"""
        return self.group_type == GroupType.DYNAMIC.value

    @property
    def is_static(self) -> bool:
        """Check if this is a static group"""
        return self.group_type == GroupType.STATIC.value

    @property
    def member_count(self) -> int:
        """Get the count of static members"""
        if self.is_static:
            return self.members.count()
        return 0

    def get_criteria_summary(self) -> str:
        """Get a human-readable summary of the criteria"""
        if not self.criteria:
            return "No criteria defined"

        target_type = self.criteria.get('target_type', 'unknown')

        if target_type == 'all':
            return "All users with push tokens"
        elif target_type == 'role':
            roles = self.criteria.get('role_names', [])
            return f"Roles: {', '.join(roles)}"
        elif target_type == 'team':
            team_ids = self.criteria.get('team_ids', [])
            return f"Teams: {len(team_ids)} selected"
        elif target_type == 'league':
            league_ids = self.criteria.get('league_ids', [])
            return f"Leagues: {len(league_ids)} selected"
        elif target_type == 'pool':
            pool_type = self.criteria.get('pool_type', 'all')
            return f"Substitute pool: {pool_type}"
        elif target_type == 'platform':
            platform = self.criteria.get('platform', 'all')
            return f"Platform: {platform}"

        return f"Type: {target_type}"

    def to_dict(self, include_members: bool = False) -> Dict[str, Any]:
        """Convert to dictionary representation"""
        data = {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'group_type': self.group_type,
            'criteria': self.criteria,
            'criteria_summary': self.get_criteria_summary(),
            'is_active': self.is_active,
            'member_count': self.member_count if self.is_static else None,
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

        if include_members and self.is_static:
            data['members'] = [m.to_dict() for m in self.members.all()]

        return data


class NotificationGroupMember(db.Model):
    """
    Members of static notification groups.

    Only used for group_type='static'. Links users directly to groups.
    """
    __tablename__ = 'notification_group_members'

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('notification_groups.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    added_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    added_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)

    # Relationships
    group = db.relationship('NotificationGroup', back_populates='members')
    user = db.relationship('User', foreign_keys=[user_id], backref='notification_group_memberships')
    added_by_user = db.relationship('User', foreign_keys=[added_by])

    # Unique constraint
    __table_args__ = (
        db.UniqueConstraint('group_id', 'user_id', name='uq_notification_group_member'),
    )

    def __repr__(self):
        return f'<NotificationGroupMember group={self.group_id} user={self.user_id}>'

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation"""
        return {
            'id': self.id,
            'group_id': self.group_id,
            'user_id': self.user_id,
            'user_name': self.user.username if self.user else None,
            'added_at': self.added_at.isoformat() if self.added_at else None,
            'added_by': self.added_by,
        }


class PushNotificationCampaign(db.Model):
    """
    Push notification campaigns with scheduling and tracking.

    Supports immediate sending, scheduled delivery, and analytics tracking.
    """
    __tablename__ = 'push_notification_campaigns'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    title = db.Column(db.String(100), nullable=False)
    body = db.Column(db.Text, nullable=False)

    # Targeting
    target_type = db.Column(db.String(50), nullable=False)
    target_ids = db.Column(db.JSON, nullable=True)  # List of IDs for the target type
    notification_group_id = db.Column(db.Integer, db.ForeignKey('notification_groups.id', ondelete='SET NULL'), nullable=True)
    platform_filter = db.Column(db.String(20), default='all')  # 'all', 'ios', 'android', 'web'

    # Scheduling
    status = db.Column(db.String(20), nullable=False, default=CampaignStatus.DRAFT.value)
    send_immediately = db.Column(db.Boolean, default=True, nullable=False)
    scheduled_send_time = db.Column(db.DateTime, nullable=True)
    actual_send_time = db.Column(db.DateTime, nullable=True)

    # Options
    priority = db.Column(db.String(20), default=CampaignPriority.NORMAL.value)
    action_url = db.Column(db.String(255), nullable=True)  # Deep link URL
    icon = db.Column(db.String(50), nullable=True)
    sound = db.Column(db.String(50), default='default')
    badge_count = db.Column(db.Integer, nullable=True)
    data_payload = db.Column(db.JSON, nullable=True)  # Additional custom data

    # Analytics
    target_count = db.Column(db.Integer, default=0)
    sent_count = db.Column(db.Integer, default=0)
    delivered_count = db.Column(db.Integer, default=0)
    failed_count = db.Column(db.Integer, default=0)
    click_count = db.Column(db.Integer, default=0)

    # Task tracking
    celery_task_id = db.Column(db.String(100), nullable=True)

    # Audit
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    cancelled_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    cancelled_at = db.Column(db.DateTime, nullable=True)
    error_message = db.Column(db.Text, nullable=True)  # Store error details if failed

    # Relationships
    creator = db.relationship('User', foreign_keys=[created_by], backref='created_campaigns')
    canceller = db.relationship('User', foreign_keys=[cancelled_by])
    notification_group = db.relationship('NotificationGroup', back_populates='campaigns')

    def __repr__(self):
        return f'<PushNotificationCampaign {self.id}:{self.name}>'

    @property
    def is_editable(self) -> bool:
        """Check if campaign can still be edited"""
        return self.status == CampaignStatus.DRAFT.value

    @property
    def is_cancellable(self) -> bool:
        """Check if campaign can be cancelled"""
        return self.status in [CampaignStatus.DRAFT.value, CampaignStatus.SCHEDULED.value]

    @property
    def delivery_rate(self) -> float:
        """Calculate delivery rate as percentage"""
        if self.sent_count == 0:
            return 0.0
        return round((self.delivered_count / self.sent_count) * 100, 2)

    @property
    def click_rate(self) -> float:
        """Calculate click rate as percentage"""
        if self.delivered_count == 0:
            return 0.0
        return round((self.click_count / self.delivered_count) * 100, 2)

    @property
    def failure_rate(self) -> float:
        """Calculate failure rate as percentage"""
        if self.sent_count == 0:
            return 0.0
        return round((self.failed_count / self.sent_count) * 100, 2)

    def get_target_summary(self) -> str:
        """Get a human-readable summary of the target"""
        if self.target_type == TargetType.ALL.value:
            return "All users"
        elif self.target_type == TargetType.GROUP.value and self.notification_group:
            return f"Group: {self.notification_group.name}"
        elif self.target_type == TargetType.TEAM.value:
            count = len(self.target_ids) if self.target_ids else 0
            return f"{count} team(s)"
        elif self.target_type == TargetType.LEAGUE.value:
            count = len(self.target_ids) if self.target_ids else 0
            return f"{count} league(s)"
        elif self.target_type == TargetType.ROLE.value:
            roles = self.target_ids if self.target_ids else []
            return f"Roles: {', '.join(roles)}"
        elif self.target_type == TargetType.POOL.value:
            return "Substitute pool"
        elif self.target_type == TargetType.PLATFORM.value:
            return f"Platform: {self.platform_filter}"

        return f"Type: {self.target_type}"

    def mark_as_scheduled(self, task_id: str):
        """Mark campaign as scheduled with Celery task ID"""
        self.status = CampaignStatus.SCHEDULED.value
        self.celery_task_id = task_id
        self.updated_at = datetime.utcnow()

    def mark_as_sending(self):
        """Mark campaign as currently sending"""
        self.status = CampaignStatus.SENDING.value
        self.actual_send_time = datetime.utcnow()
        self.updated_at = datetime.utcnow()

    def mark_as_sent(self, sent: int, delivered: int, failed: int):
        """Mark campaign as sent with analytics"""
        self.status = CampaignStatus.SENT.value
        self.sent_count = sent
        self.delivered_count = delivered
        self.failed_count = failed
        self.updated_at = datetime.utcnow()

    def mark_as_failed(self, error_message: str):
        """Mark campaign as failed with error"""
        self.status = CampaignStatus.FAILED.value
        self.error_message = error_message
        self.updated_at = datetime.utcnow()

    def cancel(self, cancelled_by_id: int):
        """Cancel the campaign"""
        self.status = CampaignStatus.CANCELLED.value
        self.cancelled_by = cancelled_by_id
        self.cancelled_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()

    def update_analytics(self, delivered: int = 0, clicked: int = 0):
        """Update delivery and click analytics"""
        self.delivered_count += delivered
        self.click_count += clicked
        self.updated_at = datetime.utcnow()

    def to_dict(self, include_group: bool = False) -> Dict[str, Any]:
        """Convert to dictionary representation"""
        data = {
            'id': self.id,
            'name': self.name,
            'title': self.title,
            'body': self.body,
            'target_type': self.target_type,
            'target_ids': self.target_ids,
            'target_summary': self.get_target_summary(),
            'notification_group_id': self.notification_group_id,
            'platform_filter': self.platform_filter,
            'status': self.status,
            'send_immediately': self.send_immediately,
            'scheduled_send_time': self.scheduled_send_time.isoformat() if self.scheduled_send_time else None,
            'actual_send_time': self.actual_send_time.isoformat() if self.actual_send_time else None,
            'priority': self.priority,
            'action_url': self.action_url,
            'icon': self.icon,
            'sound': self.sound,
            'badge_count': self.badge_count,
            'data_payload': self.data_payload,
            'analytics': {
                'target_count': self.target_count,
                'sent_count': self.sent_count,
                'delivered_count': self.delivered_count,
                'failed_count': self.failed_count,
                'click_count': self.click_count,
                'delivery_rate': self.delivery_rate,
                'click_rate': self.click_rate,
                'failure_rate': self.failure_rate,
            },
            'celery_task_id': self.celery_task_id,
            'error_message': self.error_message,
            'is_editable': self.is_editable,
            'is_cancellable': self.is_cancellable,
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'cancelled_by': self.cancelled_by,
            'cancelled_at': self.cancelled_at.isoformat() if self.cancelled_at else None,
        }

        if include_group and self.notification_group:
            data['notification_group'] = self.notification_group.to_dict()

        return data

    def duplicate(self, new_name: str = None, created_by_id: int = None) -> 'PushNotificationCampaign':
        """Create a duplicate of this campaign as a draft"""
        return PushNotificationCampaign(
            name=new_name or f"{self.name} (Copy)",
            title=self.title,
            body=self.body,
            target_type=self.target_type,
            target_ids=self.target_ids.copy() if self.target_ids else None,
            notification_group_id=self.notification_group_id,
            platform_filter=self.platform_filter,
            status=CampaignStatus.DRAFT.value,
            send_immediately=True,
            priority=self.priority,
            action_url=self.action_url,
            icon=self.icon,
            sound=self.sound,
            badge_count=self.badge_count,
            data_payload=self.data_payload.copy() if self.data_payload else None,
            created_by=created_by_id or self.created_by,
        )
