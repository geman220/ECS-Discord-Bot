# app/models/wallet_asset.py

"""
Wallet Asset Models Module

This module contains models for wallet pass assets and configuration:
- WalletAsset: Assets like icons and logos for wallet passes
- WalletTemplate: Templates for pass appearance
- WalletCertificate: Certificates for signing passes
"""

from datetime import datetime
import os
import json
from app.core import db

class WalletAsset(db.Model):
    """Stores uploaded assets for wallet passes"""
    __tablename__ = 'wallet_asset'
    
    id = db.Column(db.Integer, primary_key=True)
    pass_type_id = db.Column(db.Integer, db.ForeignKey('wallet_pass_type.id'), nullable=False)
    asset_type = db.Column(db.String(50), nullable=False)  # 'icon', 'logo', 'background'
    file_name = db.Column(db.String(100), nullable=False)
    file_path = db.Column(db.String(255), nullable=False)
    content_type = db.Column(db.String(100), nullable=False)
    file_size = db.Column(db.Integer, nullable=False)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    pass_type = db.relationship('WalletPassType', backref='assets')
    
    __table_args__ = (
        db.UniqueConstraint('pass_type_id', 'asset_type', name='uq_pass_type_asset'),
    )
    
    def to_dict(self):
        """Convert asset to dict"""
        return {
            'id': self.id,
            'pass_type_id': self.pass_type_id,
            'asset_type': self.asset_type,
            'file_name': self.file_name,
            'file_path': self.file_path,
            'content_type': self.content_type,
            'file_size': self.file_size,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
        
    @classmethod
    def get_by_type_and_pass_type(cls, asset_type, pass_type_id):
        """Get asset by type and pass type"""
        return cls.query.filter_by(
            asset_type=asset_type,
            pass_type_id=pass_type_id
        ).first()
    
    @classmethod
    def get_assets_by_pass_type(cls, pass_type_id):
        """Get all assets for a pass type"""
        return cls.query.filter_by(pass_type_id=pass_type_id).all()


class WalletTemplate(db.Model):
    """Stores customized templates for wallet passes"""
    __tablename__ = 'wallet_template'
    
    id = db.Column(db.Integer, primary_key=True)
    pass_type_id = db.Column(db.Integer, db.ForeignKey('wallet_pass_type.id'), nullable=False)
    platform = db.Column(db.String(20), nullable=False)  # 'apple', 'google'
    name = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text, nullable=False)  # JSON content
    is_default = db.Column(db.Boolean, default=False)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    pass_type = db.relationship('WalletPassType', backref='templates')
    
    __table_args__ = (
        db.UniqueConstraint('pass_type_id', 'platform', 'name', name='uq_pass_type_platform_template'),
    )
    
    def to_dict(self):
        """Convert template to dict"""
        return {
            'id': self.id,
            'pass_type_id': self.pass_type_id,
            'platform': self.platform,
            'name': self.name,
            'content': self.content,
            'is_default': self.is_default,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
    
    @classmethod
    def get_default(cls, pass_type_id, platform):
        """Get the default template for a pass type and platform"""
        return cls.query.filter_by(
            pass_type_id=pass_type_id,
            platform=platform,
            is_default=True
        ).first()
    
    @classmethod
    def set_default(cls, template_id):
        """Set a template as default and unset others"""
        template = cls.query.get_or_404(template_id)
        
        # Unset other defaults
        other_defaults = cls.query.filter(
            cls.pass_type_id == template.pass_type_id,
            cls.platform == template.platform,
            cls.id != template_id,
            cls.is_default == True
        ).all()
        
        for other in other_defaults:
            other.is_default = False
        
        template.is_default = True
        db.session.commit()
        
        return template


class WalletCertificate(db.Model):
    """Stores wallet pass signing certificates"""
    __tablename__ = 'wallet_certificate'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    type = db.Column(db.String(20), nullable=False)  # 'certificate', 'key', 'wwdr', 'credentials', 'apns_key'
    platform = db.Column(db.String(20), nullable=False)  # 'apple', 'google'
    file_name = db.Column(db.String(100), nullable=False)
    file_path = db.Column(db.String(255), nullable=False)

    # For Apple Wallet pass
    team_identifier = db.Column(db.String(20))
    pass_type_identifier = db.Column(db.String(100))

    # For APNs push key (token-based auth)
    apns_key_id = db.Column(db.String(20))  # 10-character key ID from Apple

    # For Google Wallet
    issuer_id = db.Column(db.String(50))
    
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        """Convert certificate to dict"""
        return {
            'id': self.id,
            'name': self.name,
            'type': self.type,
            'platform': self.platform,
            'file_name': self.file_name,
            'team_identifier': self.team_identifier,
            'pass_type_identifier': self.pass_type_identifier,
            'apns_key_id': self.apns_key_id,
            'issuer_id': self.issuer_id,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
    
    @classmethod
    def get_active_by_type(cls, cert_type, platform='apple'):
        """Get active certificate by type and platform"""
        return cls.query.filter_by(
            type=cert_type,
            platform=platform,
            is_active=True
        ).first()
    
    @classmethod
    def has_complete_apple_config(cls):
        """Check if all required Apple certificates are present"""
        certificate = cls.get_active_by_type('certificate')
        key = cls.get_active_by_type('key')
        wwdr = cls.get_active_by_type('wwdr')
        
        return certificate is not None and key is not None and wwdr is not None
    
    @classmethod
    def has_complete_google_config(cls):
        """Check if all required Google credentials are present"""
        credentials = cls.get_active_by_type('credentials', platform='google')
        
        return credentials is not None