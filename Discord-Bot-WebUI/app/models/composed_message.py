# app/models/composed_message.py

"""
ComposedMessage — one record per admin "Compose" send.

The multi-channel composer writes a message once, picks channels
(in_app/push/email/sms/discord) and an audience, and delivery runs through the
NotificationOrchestrator (so every user's channel preferences are honored).
This table is the composer's history + scheduling state.

Requires sql_create_composed_messages.sql (run manually in pgAdmin).
"""

from datetime import datetime

from app.core import db


class ComposedMessage(db.Model):
    """A write-once, multi-channel admin message routed via the orchestrator."""
    __tablename__ = 'composed_messages'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    message = db.Column(db.Text, nullable=False)

    # Channel allow-list, e.g. ["in_app", "push", "email"].
    channels = db.Column(db.JSON, nullable=False)

    # Audience: type + ids resolved at SEND time (not at compose time), so a
    # scheduled message picks up roster changes.
    # audience_type: all_active | team | league | role | users
    audience_type = db.Column(db.String(20), nullable=False)
    audience_ids = db.Column(db.JSON, nullable=True)  # team/league ids, role names, or user ids
    audience_description = db.Column(db.String(300), nullable=True)

    action_url = db.Column(db.String(500), nullable=True)
    priority = db.Column(db.String(10), nullable=False, default='normal')  # normal | high

    # scheduled | sending | sent | partially_sent | failed | cancelled
    status = db.Column(db.String(20), nullable=False, default='scheduled', index=True)
    scheduled_send_time = db.Column(db.DateTime, nullable=True)  # UTC; NULL = immediate
    celery_task_id = db.Column(db.String(155), nullable=True)

    total_recipients = db.Column(db.Integer, nullable=False, default=0)
    # Orchestrator per-channel result dict, stored verbatim after the send.
    results = db.Column(db.JSON, nullable=True)
    error_message = db.Column(db.String(500), nullable=True)

    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_by = db.relationship('User', foreign_keys=[created_by_id])
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    sent_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'message': self.message,
            'channels': self.channels,
            'audience_type': self.audience_type,
            'audience_description': self.audience_description,
            'status': self.status,
            'scheduled_send_time': self.scheduled_send_time.isoformat() if self.scheduled_send_time else None,
            'total_recipients': self.total_recipients,
            'results': self.results,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'sent_at': self.sent_at.isoformat() if self.sent_at else None,
        }

    def __repr__(self):
        return f'<ComposedMessage {self.id}: {self.title} ({self.status})>'
