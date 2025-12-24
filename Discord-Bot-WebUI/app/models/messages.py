# app/models/messages.py

"""
Direct Messaging Models

This module provides models for the lightweight messaging system:
- DirectMessage: Individual messages between users
- MessagingPermission: Role-based messaging permission configuration
- MessagingSettings: Global messaging system settings

The messaging system is designed to be minimal overhead and integrates
with the existing WebSocket presence system for real-time delivery.
"""

from datetime import datetime
from app.core import db


class DirectMessage(db.Model):
    """
    Individual direct message between two users.

    Messages are stored permanently but can be configured for auto-cleanup.
    Real-time delivery uses WebSocket when recipient is online.
    """
    __tablename__ = 'direct_messages'

    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    recipient_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    content = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    read_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    sender = db.relationship(
        'User',
        foreign_keys=[sender_id],
        backref=db.backref('sent_messages', lazy='dynamic')
    )
    recipient = db.relationship(
        'User',
        foreign_keys=[recipient_id],
        backref=db.backref('received_messages', lazy='dynamic')
    )

    # Indexes for common queries
    __table_args__ = (
        db.Index('ix_dm_conversation', 'sender_id', 'recipient_id'),
        db.Index('ix_dm_unread', 'recipient_id', 'is_read'),
    )

    def to_dict(self):
        """Serialize message for API/WebSocket responses."""
        return {
            'id': self.id,
            'sender_id': self.sender_id,
            'recipient_id': self.recipient_id,
            'content': self.content,
            'is_read': self.is_read,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'read_at': self.read_at.isoformat() if self.read_at else None,
            'sender_name': self.sender.player.name if self.sender and self.sender.player else (
                self.sender.username if self.sender else None
            ),
            'sender_avatar': self.sender.player.profile_picture_url if self.sender and self.sender.player else None
        }

    def mark_as_read(self):
        """Mark message as read with timestamp."""
        if not self.is_read:
            self.is_read = True
            self.read_at = datetime.utcnow()

    @classmethod
    def get_conversation(cls, user_id_1, user_id_2, limit=50, offset=0):
        """
        Get messages between two users.

        Returns messages ordered by created_at descending (newest first).
        """
        return cls.query.filter(
            db.or_(
                db.and_(cls.sender_id == user_id_1, cls.recipient_id == user_id_2),
                db.and_(cls.sender_id == user_id_2, cls.recipient_id == user_id_1)
            )
        ).order_by(cls.created_at.desc()).offset(offset).limit(limit).all()

    @classmethod
    def get_unread_count(cls, user_id):
        """Get count of unread messages for a user."""
        return cls.query.filter_by(
            recipient_id=user_id,
            is_read=False
        ).count()

    @classmethod
    def get_conversations_for_user(cls, user_id, limit=20):
        """
        Get list of conversations with most recent message.
        Returns a list of conversation summaries.
        """
        # Subquery to get max message ID per conversation partner
        from sqlalchemy import func, case

        # Get all users this user has messaged with
        subq = db.session.query(
            case(
                (cls.sender_id == user_id, cls.recipient_id),
                else_=cls.sender_id
            ).label('partner_id'),
            func.max(cls.id).label('max_id'),
            func.count(case((cls.is_read == False, cls.recipient_id == user_id))).label('unread_count')
        ).filter(
            db.or_(cls.sender_id == user_id, cls.recipient_id == user_id)
        ).group_by('partner_id').subquery()

        # Join to get full message details
        messages = db.session.query(cls).join(
            subq, cls.id == subq.c.max_id
        ).order_by(cls.created_at.desc()).limit(limit).all()

        return messages

    def __repr__(self):
        return f'<DirectMessage {self.id} from {self.sender_id} to {self.recipient_id}>'


class MessagingPermission(db.Model):
    """
    Configurable role-to-role messaging permissions.

    Allows admins to control which roles can message which other roles.
    If no permission record exists, messaging is denied by default.
    """
    __tablename__ = 'messaging_permissions'

    id = db.Column(db.Integer, primary_key=True)
    sender_role_id = db.Column(db.Integer, db.ForeignKey('roles.id'), nullable=False)
    recipient_role_id = db.Column(db.Integer, db.ForeignKey('roles.id'), nullable=False)
    is_allowed = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    # Relationships
    sender_role = db.relationship('Role', foreign_keys=[sender_role_id])
    recipient_role = db.relationship('Role', foreign_keys=[recipient_role_id])
    updated_by_user = db.relationship('User', foreign_keys=[updated_by])

    __table_args__ = (
        db.UniqueConstraint('sender_role_id', 'recipient_role_id', name='uq_messaging_permission'),
    )

    @classmethod
    def can_message(cls, sender_role_ids, recipient_role_ids):
        """
        Check if any sender role can message any recipient role.

        Args:
            sender_role_ids: List of sender's role IDs
            recipient_role_ids: List of recipient's role IDs

        Returns:
            bool: True if messaging is allowed

        Note:
            If no permissions are configured at all, messaging is ALLOWED by default.
            This provides a "default allow, restrict as needed" approach.
        """
        # Check if any permissions exist at all
        any_permissions_exist = cls.query.first() is not None

        # If no permissions configured, allow all messaging by default
        if not any_permissions_exist:
            return True

        # Check for an explicit allow permission
        permission = cls.query.filter(
            cls.sender_role_id.in_(sender_role_ids),
            cls.recipient_role_id.in_(recipient_role_ids),
            cls.is_allowed == True
        ).first()
        return permission is not None

    @classmethod
    def get_permission_matrix(cls):
        """
        Get all permissions as a matrix dictionary.

        Returns:
            dict: {sender_role_id: {recipient_role_id: is_allowed}}
        """
        permissions = cls.query.all()
        matrix = {}
        for perm in permissions:
            if perm.sender_role_id not in matrix:
                matrix[perm.sender_role_id] = {}
            matrix[perm.sender_role_id][perm.recipient_role_id] = perm.is_allowed
        return matrix

    @classmethod
    def set_permission(cls, sender_role_id, recipient_role_id, is_allowed, updated_by=None):
        """
        Set or update a messaging permission.

        Args:
            sender_role_id: Sender role ID
            recipient_role_id: Recipient role ID
            is_allowed: Whether messaging is allowed
            updated_by: User ID making the change
        """
        perm = cls.query.filter_by(
            sender_role_id=sender_role_id,
            recipient_role_id=recipient_role_id
        ).first()

        if perm:
            perm.is_allowed = is_allowed
            perm.updated_by = updated_by
        else:
            perm = cls(
                sender_role_id=sender_role_id,
                recipient_role_id=recipient_role_id,
                is_allowed=is_allowed,
                updated_by=updated_by
            )
            db.session.add(perm)

        return perm

    def __repr__(self):
        return f'<MessagingPermission {self.sender_role_id} -> {self.recipient_role_id}: {self.is_allowed}>'


class MessagingSettings(db.Model):
    """
    Global messaging system settings.

    Singleton table for system-wide messaging configuration.
    """
    __tablename__ = 'messaging_settings'

    id = db.Column(db.Integer, primary_key=True)
    enabled = db.Column(db.Boolean, default=True)
    max_message_length = db.Column(db.Integer, default=2000)
    message_retention_days = db.Column(db.Integer, default=90)  # 0 = keep forever
    allow_attachments = db.Column(db.Boolean, default=False)
    typing_indicators = db.Column(db.Boolean, default=True)
    read_receipts = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    @classmethod
    def get_settings(cls):
        """Get or create the singleton settings record."""
        settings = cls.query.first()
        if not settings:
            settings = cls()
            db.session.add(settings)
            db.session.commit()
        return settings

    def to_dict(self):
        """Serialize settings for API responses."""
        return {
            'enabled': self.enabled,
            'max_message_length': self.max_message_length,
            'message_retention_days': self.message_retention_days,
            'allow_attachments': self.allow_attachments,
            'typing_indicators': self.typing_indicators,
            'read_receipts': self.read_receipts
        }

    def __repr__(self):
        return f'<MessagingSettings enabled={self.enabled}>'
