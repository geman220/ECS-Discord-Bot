# app/models/communication.py

"""
Communication Models Module

This module contains models related to communication and notifications:
- Notification: System notifications for users
- Announcement: Public announcements
- ScheduledMessage: Scheduled messages for matches
- Feedback: User feedback system
- FeedbackReply: Replies to feedback
- Note: Notes attached to feedback
"""

import logging
from datetime import datetime, timedelta
from sqlalchemy import JSON, DateTime

from app.core import db

logger = logging.getLogger(__name__)


class Notification(db.Model):
    """Model representing a system notification for a user."""
    __tablename__ = 'notifications'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    content = db.Column(db.String(255), nullable=False)
    notification_type = db.Column(db.String(50), nullable=False, default='system')
    icon = db.Column(db.String(50), nullable=True)
    read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship('User', back_populates='notifications')

    def icon_class(self):
        if self.icon:
            return self.icon
        icon_mapping = {
            'warning': 'ti ti-alert-triangle',
            'error': 'ti ti-alert-circle',
            'info': 'ti ti-info-circle',
            'success': 'ti ti-check-circle',
            'system': 'ti ti-bell'
        }
        return icon_mapping.get(self.notification_type, 'ti-bell')


class Announcement(db.Model):
    """Model representing an announcement."""
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    position = db.Column(db.Integer, default=0)


class ScheduledMessage(db.Model):
    """Model representing a scheduled message for a match."""
    __tablename__ = 'scheduled_message'
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('matches.id'), nullable=True)  # Made nullable for ECS FC
    scheduled_send_time = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), default='PENDING')
    home_channel_id = db.Column(db.String(20), nullable=True)
    home_message_id = db.Column(db.String(20), nullable=True)
    away_channel_id = db.Column(db.String(20), nullable=True)
    away_message_id = db.Column(db.String(20), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # New fields for enhanced functionality and ECS FC support
    message_type = db.Column(db.String(50), default='standard')
    message_metadata = db.Column(JSON, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    last_send_attempt = db.Column(db.DateTime, nullable=True)
    sent_at = db.Column(db.DateTime, nullable=True)
    send_error = db.Column(db.String(255), nullable=True)
    task_name = db.Column(db.String(255), nullable=True)

    match = db.relationship('Match', back_populates='scheduled_messages')
    creator = db.relationship('User', backref='created_scheduled_messages')


class Feedback(db.Model):
    """Model representing user feedback."""
    __tablename__ = 'feedback'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    name = db.Column(db.String(150), nullable=True)
    category = db.Column(db.String(50), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=False)
    priority = db.Column(db.String(20), default='Low')
    status = db.Column(db.String(20), default='Open')
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    closed_at = db.Column(db.DateTime, nullable=True)
    
    user = db.relationship('User', back_populates='feedbacks')
    notes = db.relationship('Note', back_populates='feedback', cascade='all, delete-orphan', lazy=True)
    replies = db.relationship('FeedbackReply', back_populates='feedback', cascade='all, delete-orphan', lazy=True)

    def __repr__(self):
        return f'<Feedback {self.id} - {self.title}>'

    @classmethod
    def delete_old_closed_tickets(cls):
        try:
            thirty_days_ago = datetime.utcnow() - timedelta(days=30)
            old_closed_tickets = cls.query.filter(cls.closed_at <= thirty_days_ago).all()
            for ticket in old_closed_tickets:
                g.db_session.delete(ticket)
            logger.info(f"Successfully deleted old closed tickets older than {thirty_days_ago}")
        except Exception as e:
            logger.error(f"Error deleting old closed tickets: {str(e)}")
            raise


class FeedbackReply(db.Model):
    """Model representing a reply to a feedback ticket."""
    __tablename__ = 'feedback_replies'

    id = db.Column(db.Integer, primary_key=True)
    feedback_id = db.Column(db.Integer, db.ForeignKey('feedback.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    is_admin_reply = db.Column(db.Boolean, default=False)

    feedback = db.relationship('Feedback', back_populates='replies')
    user = db.relationship('User', back_populates='feedback_replies')

    def __repr__(self):
        return f'<FeedbackReply {self.id} for Feedback {self.feedback_id}>'


class Note(db.Model):
    """Model representing a note attached to a feedback ticket."""
    __tablename__ = 'notes'

    id = db.Column(db.Integer, primary_key=True)
    feedback_id = db.Column(db.Integer, db.ForeignKey('feedback.id'), nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp(), nullable=False)

    feedback = db.relationship('Feedback', back_populates='notes')
    author = db.relationship('User', back_populates='notes')

    def __repr__(self):
        return f'<Note {self.id} by {self.author.username}>'


class DeviceToken(db.Model):
    """Model representing a device token for push notifications."""
    __tablename__ = 'device_tokens'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    device_token = db.Column(db.String(255), nullable=False, unique=True)
    device_type = db.Column(db.String(20), nullable=False)  # 'ios' or 'android'
    app_version = db.Column(db.String(20), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user = db.relationship('User', back_populates='device_tokens')

    def __repr__(self):
        return f'<DeviceToken {self.id} - {self.device_type} for User {self.user_id}>'


class SMSLog(db.Model):
    """
    Model for SMS audit logging.

    Tracks all SMS messages sent through the system for:
    - Cost tracking and billing reconciliation
    - Delivery status monitoring
    - Compliance auditing (TCPA)
    - Debugging delivery issues
    """
    __tablename__ = 'sms_logs'

    id = db.Column(db.Integer, primary_key=True)

    # Recipient information
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    phone_number_hash = db.Column(db.String(64), nullable=True, index=True)  # Hashed for privacy

    # Message details
    message_type = db.Column(db.String(50), nullable=False, default='general')
    # Types: verification, reminder, rsvp_confirmation, announcement, system, admin_direct
    message_length = db.Column(db.Integer, nullable=True)
    segment_count = db.Column(db.Integer, nullable=True)  # SMS segments (affects cost)

    # Twilio response
    twilio_sid = db.Column(db.String(40), nullable=True, unique=True, index=True)
    twilio_status = db.Column(db.String(20), nullable=True)
    # Status: queued, sending, sent, delivered, failed, undelivered

    # Cost tracking
    cost_estimate = db.Column(db.Numeric(8, 4), nullable=True)  # USD per segment
    actual_cost = db.Column(db.Numeric(8, 4), nullable=True)  # From Twilio webhook

    # Delivery tracking
    sent_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    delivered_at = db.Column(db.DateTime, nullable=True)
    failed_at = db.Column(db.DateTime, nullable=True)
    error_code = db.Column(db.String(10), nullable=True)
    error_message = db.Column(db.String(255), nullable=True)

    # Admin/sender context
    sent_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    source = db.Column(db.String(50), nullable=True)  # orchestrator, admin_panel, webhook, task

    # Relationships
    user = db.relationship('User', foreign_keys=[user_id], backref='sms_logs_received')
    sent_by = db.relationship('User', foreign_keys=[sent_by_user_id], backref='sms_logs_sent')

    def __repr__(self):
        return f'<SMSLog {self.id} - {self.message_type} to user {self.user_id} status={self.twilio_status}>'

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'message_type': self.message_type,
            'twilio_sid': self.twilio_sid,
            'twilio_status': self.twilio_status,
            'cost_estimate': float(self.cost_estimate) if self.cost_estimate else None,
            'actual_cost': float(self.actual_cost) if self.actual_cost else None,
            'sent_at': self.sent_at.isoformat() if self.sent_at else None,
            'delivered_at': self.delivered_at.isoformat() if self.delivered_at else None,
            'error_code': self.error_code,
            'error_message': self.error_message,
            'source': self.source
        }

    @classmethod
    def log_sms(cls, user_id=None, phone_number=None, message_type='general',
                message_length=None, twilio_sid=None, sent_by_user_id=None, source=None):
        """
        Create an SMS log entry.

        Args:
            user_id: ID of the recipient user (if known)
            phone_number: Phone number (will be hashed for privacy)
            message_type: Type of message (verification, reminder, etc.)
            message_length: Length of the message in characters
            twilio_sid: Twilio message SID
            sent_by_user_id: ID of the admin who sent (for direct messages)
            source: Where the SMS originated (orchestrator, admin_panel, etc.)

        Returns:
            SMSLog: The created log entry
        """
        try:
            # Hash phone number for privacy
            phone_hash = None
            if phone_number:
                import hashlib
                phone_hash = hashlib.sha256(phone_number.encode()).hexdigest()

            # Calculate segment count (SMS is 160 chars, or 70 for unicode)
            segment_count = None
            if message_length:
                segment_count = (message_length // 160) + (1 if message_length % 160 else 0)

            # Estimate cost (Twilio standard rate ~$0.0079 per segment)
            cost_estimate = None
            if segment_count:
                cost_estimate = segment_count * 0.0079

            log_entry = cls(
                user_id=user_id,
                phone_number_hash=phone_hash,
                message_type=message_type,
                message_length=message_length,
                segment_count=segment_count,
                twilio_sid=twilio_sid,
                twilio_status='queued',
                cost_estimate=cost_estimate,
                sent_by_user_id=sent_by_user_id,
                source=source
            )

            db.session.add(log_entry)
            db.session.commit()

            return log_entry

        except Exception as e:
            logger.error(f"Failed to create SMS log entry: {e}")
            db.session.rollback()
            return None

    @classmethod
    def update_delivery_status(cls, twilio_sid, status, error_code=None, error_message=None, actual_cost=None):
        """
        Update SMS delivery status from Twilio webhook.

        Args:
            twilio_sid: The Twilio message SID
            status: New status (delivered, failed, undelivered)
            error_code: Twilio error code if failed
            error_message: Error description if failed
            actual_cost: Actual cost from Twilio
        """
        try:
            log_entry = cls.query.filter_by(twilio_sid=twilio_sid).first()
            if not log_entry:
                logger.warning(f"SMS log not found for Twilio SID: {twilio_sid}")
                return None

            log_entry.twilio_status = status

            if status == 'delivered':
                log_entry.delivered_at = datetime.utcnow()
            elif status in ('failed', 'undelivered'):
                log_entry.failed_at = datetime.utcnow()
                log_entry.error_code = error_code
                log_entry.error_message = error_message

            if actual_cost is not None:
                log_entry.actual_cost = actual_cost

            db.session.commit()
            return log_entry

        except Exception as e:
            logger.error(f"Failed to update SMS log status: {e}")
            db.session.rollback()
            return None