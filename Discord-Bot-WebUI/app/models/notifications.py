from datetime import datetime, timedelta
from app.core import db

class UserFCMToken(db.Model):
    """Model for storing Firebase Cloud Messaging tokens for push notifications - 2025 Enhanced"""
    __tablename__ = 'user_fcm_tokens'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    fcm_token = db.Column(db.String(500), nullable=False, unique=True)  # Increased length for modern tokens
    platform = db.Column(db.String(20), nullable=False)  # 'ios', 'android', 'web'
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_used = db.Column(db.DateTime, default=datetime.utcnow)  # Track last successful notification
    deactivated_reason = db.Column(db.String(100), nullable=True)  # Why token was deactivated
    app_version = db.Column(db.String(20), nullable=True)  # Track app version for debugging
    device_info = db.Column(db.String(200), nullable=True)  # Optional device information
    
    # Relationship
    user = db.relationship('User', backref='fcm_tokens')
    
    def __repr__(self):
        return f'<UserFCMToken {self.user_id}:{self.platform}>'
    
    @property
    def is_stale(self):
        """Check if token is stale (inactive for over 30 days per Firebase recommendations)"""
        if not self.last_used:
            return False
        return datetime.utcnow() - self.last_used > timedelta(days=30)
    
    @property
    def token_preview(self):
        """Return a preview of the token for logging (first 20 chars + ...)"""
        if not self.fcm_token:
            return "No token"
        return f"{self.fcm_token[:20]}..." if len(self.fcm_token) > 20 else self.fcm_token
    
    def mark_as_used(self):
        """Update last_used timestamp when notification is successfully sent"""
        self.last_used = datetime.utcnow()
        self.updated_at = datetime.utcnow()
    
    def deactivate(self, reason: str):
        """Deactivate token with reason"""
        self.is_active = False
        self.deactivated_reason = reason
        self.updated_at = datetime.utcnow()
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'fcm_token': self.fcm_token,
            'platform': self.platform,
            'is_active': self.is_active,
            'is_stale': self.is_stale,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'last_used': self.last_used.isoformat() if self.last_used else None,
            'deactivated_reason': self.deactivated_reason,
            'app_version': self.app_version,
            'device_info': self.device_info
        }
    
    @classmethod
    def cleanup_stale_tokens(cls):
        """Class method to identify and deactivate stale tokens"""
        try:
            stale_threshold = datetime.utcnow() - timedelta(days=30)
            stale_tokens = cls.query.filter(
                cls.is_active == True,
                cls.last_used < stale_threshold
            ).all()
            
            for token in stale_tokens:
                token.deactivate('stale_token_cleanup')
            
            return len(stale_tokens)
        except Exception as e:
            from flask import current_app
            current_app.logger.error(f"Error in stale token cleanup: {e}")
            return 0