# app/models/email_campaigns.py

"""
Email Campaign Models

Tables for tracking bulk email campaigns and per-recipient delivery status.
"""

import logging
from datetime import datetime

from app.core import db

logger = logging.getLogger(__name__)


class EmailCampaign(db.Model):
    """Campaign metadata for bulk email sends."""
    __tablename__ = 'email_campaigns'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    subject = db.Column(db.String(500), nullable=False)
    body_html = db.Column(db.Text, nullable=False)

    # Send configuration
    send_mode = db.Column(db.String(20), nullable=False, default='bcc_batch')  # bcc_batch | individual
    force_send = db.Column(db.Boolean, default=False, nullable=False)
    bcc_batch_size = db.Column(db.Integer, default=50, nullable=False)

    # Recipient filter
    filter_criteria = db.Column(db.JSON, nullable=False)  # e.g. {"type": "by_team", "team_id": 5}
    filter_description = db.Column(db.String(500), nullable=True)

    # Status tracking
    status = db.Column(db.String(20), nullable=False, default='draft', index=True)
    # draft | sending | sent | partially_sent | failed | cancelled
    total_recipients = db.Column(db.Integer, default=0, nullable=False)
    sent_count = db.Column(db.Integer, default=0, nullable=False)
    failed_count = db.Column(db.Integer, default=0, nullable=False)

    # Celery task tracking
    celery_task_id = db.Column(db.String(155), nullable=True)

    # Audit
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_by = db.relationship('User', foreign_keys=[created_by_id])
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp(), nullable=False)
    updated_at = db.Column(db.DateTime, default=db.func.current_timestamp(),
                           onupdate=db.func.current_timestamp(), nullable=False)
    sent_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    recipients = db.relationship('EmailCampaignRecipient', back_populates='campaign',
                                 cascade='all, delete-orphan', lazy='dynamic')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'subject': self.subject,
            'send_mode': self.send_mode,
            'force_send': self.force_send,
            'bcc_batch_size': self.bcc_batch_size,
            'filter_criteria': self.filter_criteria,
            'filter_description': self.filter_description,
            'status': self.status,
            'total_recipients': self.total_recipients,
            'sent_count': self.sent_count,
            'failed_count': self.failed_count,
            'created_by_id': self.created_by_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'sent_at': self.sent_at.isoformat() if self.sent_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
        }

    def __repr__(self):
        return f'<EmailCampaign {self.id}: {self.name} ({self.status})>'


class EmailCampaignRecipient(db.Model):
    """Per-recipient delivery tracking for email campaigns."""
    __tablename__ = 'email_campaign_recipients'

    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('email_campaigns.id', ondelete='CASCADE'),
                            nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # Snapshot of recipient name at send time
    recipient_name = db.Column(db.String(200), nullable=True)

    # Delivery status
    status = db.Column(db.String(20), nullable=False, default='pending')
    # pending | sent | failed | skipped
    error_message = db.Column(db.Text, nullable=True)
    sent_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    campaign = db.relationship('EmailCampaign', back_populates='recipients')
    user = db.relationship('User', foreign_keys=[user_id])

    __table_args__ = (
        db.Index('ix_email_campaign_recipients_campaign_status', 'campaign_id', 'status'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'campaign_id': self.campaign_id,
            'user_id': self.user_id,
            'recipient_name': self.recipient_name,
            'status': self.status,
            'error_message': self.error_message,
            'sent_at': self.sent_at.isoformat() if self.sent_at else None,
        }

    def __repr__(self):
        return f'<EmailCampaignRecipient campaign={self.campaign_id} user={self.user_id} ({self.status})>'
