from datetime import datetime
from app.core import db

class UserFCMToken(db.Model):
    """Model for storing Firebase Cloud Messaging tokens for push notifications"""
    __tablename__ = 'user_fcm_tokens'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    fcm_token = db.Column(db.String(255), nullable=False, unique=True)
    platform = db.Column(db.String(20), nullable=False)  # 'ios' or 'android'
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship
    user = db.relationship('User', backref='fcm_tokens')
    
    def __repr__(self):
        return f'<UserFCMToken {self.user_id}:{self.platform}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'fcm_token': self.fcm_token,
            'platform': self.platform,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }