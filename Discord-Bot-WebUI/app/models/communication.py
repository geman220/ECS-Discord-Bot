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