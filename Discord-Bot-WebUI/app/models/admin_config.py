# app/models/admin_config.py

"""
Admin Configuration Models

This module contains models for managing application-wide admin settings
and feature toggles that can be controlled through the admin panel.
"""

import logging
from datetime import datetime
from sqlalchemy import Boolean, String, Text, DateTime, Integer
from app.core import db

# Set up the module logger
logger = logging.getLogger(__name__)


class AdminConfig(db.Model):
    """
    Model for storing global admin configuration settings.
    
    This allows global admins to toggle features on/off dynamically
    without requiring code deployments or server restarts.
    """
    __tablename__ = 'admin_config'

    id = db.Column(Integer, primary_key=True)
    key = db.Column(String(100), nullable=False, unique=True, index=True)
    value = db.Column(String(500), nullable=True)
    description = db.Column(Text, nullable=True)
    category = db.Column(String(50), nullable=False, default='general')
    data_type = db.Column(String(20), nullable=False, default='string')  # string, boolean, integer, json
    is_enabled = db.Column(Boolean, nullable=False, default=True)
    created_at = db.Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = db.Column(Integer, db.ForeignKey('users.id'), nullable=True)

    # Relationship to user who last updated this setting
    updated_by_user = db.relationship('User', backref='admin_config_updates', lazy='select')

    def __repr__(self):
        return f'<AdminConfig {self.key}={self.value}>'

    @property
    def parsed_value(self):
        """Parse the value based on data_type."""
        if not self.value:
            return None
            
        if self.data_type == 'boolean':
            return self.value.lower() in ('true', '1', 'yes', 'on')
        elif self.data_type == 'integer':
            try:
                return int(self.value)
            except (ValueError, TypeError):
                return None
        elif self.data_type == 'json':
            try:
                import json
                return json.loads(self.value)
            except (ValueError, TypeError):
                return None
        else:
            return self.value

    @classmethod
    def get_setting(cls, key, default=None):
        """
        Get a setting value by key.
        
        Args:
            key (str): The setting key
            default: Default value if setting doesn't exist or is disabled
            
        Returns:
            The parsed setting value or default
        """
        from flask import g, has_request_context
        
        try:
            # Use Flask request session when available to prevent session conflicts
            if has_request_context() and hasattr(g, 'db_session') and g.db_session:
                setting = g.db_session.query(cls).filter_by(key=key, is_enabled=True).first()
                if setting:
                    # Access parsed_value while session is still active
                    return setting.parsed_value
            else:
                # Fallback to managed session for non-request contexts
                from app.core.session_manager import managed_session
                with managed_session() as session:
                    setting = session.query(cls).filter_by(key=key, is_enabled=True).first()
                    if setting:
                        # Access parsed_value while session is still active
                        return setting.parsed_value
            
            return default
        except Exception as e:
            logger.error(f"Error getting admin setting {key}: {e}")
            return default

    @classmethod
    def set_setting(cls, key, value, description=None, category='general', 
                   data_type='string', user_id=None):
        """
        Set or update a setting.
        
        Args:
            key (str): The setting key
            value: The setting value
            description (str): Optional description
            category (str): Setting category
            data_type (str): Data type (string, boolean, integer, json)
            user_id (int): ID of user making the change
        """
        try:
            setting = cls.query.filter_by(key=key).first()
            
            if setting:
                setting.value = str(value) if value is not None else None
                setting.updated_at = datetime.utcnow()
                setting.updated_by = user_id
                if description:
                    setting.description = description
            else:
                setting = cls(
                    key=key,
                    value=str(value) if value is not None else None,
                    description=description,
                    category=category,
                    data_type=data_type,
                    updated_by=user_id
                )
                db.session.add(setting)
            
            db.session.commit()
            logger.info(f"Admin setting {key} updated to {value} by user {user_id}")
            return setting
        except Exception as e:
            logger.error(f"Error setting admin setting {key}: {e}")
            db.session.rollback()
            raise

    @classmethod
    def get_settings_by_category(cls, category):
        """Get all enabled settings in a category."""
        from flask import g, has_request_context
        
        try:
            # Use Flask request session when available to prevent session conflicts
            if has_request_context() and hasattr(g, 'db_session') and g.db_session:
                return g.db_session.query(cls).filter_by(category=category, is_enabled=True).all()
            else:
                # Fallback to managed session for non-request contexts
                from app.core.session_manager import managed_session
                with managed_session() as session:
                    return session.query(cls).filter_by(category=category, is_enabled=True).all()
        except Exception as e:
            logger.error(f"Error getting settings for category {category}: {e}")
            return []

    @classmethod
    def initialize_default_settings(cls):
        """Initialize default admin settings if they don't exist."""
        default_settings = [
            # Navigation Settings
            {
                'key': 'teams_navigation_enabled',
                'value': 'true',
                'description': 'Enable/disable Teams navigation for pl-premier and pl-classic roles',
                'category': 'navigation',
                'data_type': 'boolean'
            },
            {
                'key': 'store_navigation_enabled',
                'value': 'true',
                'description': 'Enable/disable Store navigation for coaches and admins',
                'category': 'navigation',
                'data_type': 'boolean'
            },
            {
                'key': 'matches_navigation_enabled',
                'value': 'true',
                'description': 'Enable/disable Matches navigation',
                'category': 'navigation',
                'data_type': 'boolean'
            },
            {
                'key': 'leagues_navigation_enabled',
                'value': 'true',
                'description': 'Enable/disable Leagues navigation',
                'category': 'navigation',
                'data_type': 'boolean'
            },
            {
                'key': 'drafts_navigation_enabled',
                'value': 'true',
                'description': 'Enable/disable Drafts navigation',
                'category': 'navigation',
                'data_type': 'boolean'
            },
            {
                'key': 'players_navigation_enabled',
                'value': 'true',
                'description': 'Enable/disable Players navigation',
                'category': 'navigation',
                'data_type': 'boolean'
            },
            {
                'key': 'messaging_navigation_enabled',
                'value': 'true',
                'description': 'Enable/disable Messaging navigation',
                'category': 'navigation',
                'data_type': 'boolean'
            },
            {
                'key': 'mobile_features_navigation_enabled',
                'value': 'true',
                'description': 'Enable/disable Mobile Features navigation',
                'category': 'navigation',
                'data_type': 'boolean'
            },
            # Registration Settings
            {
                'key': 'registration_enabled',
                'value': 'true',
                'description': 'Allow new user registrations',
                'category': 'registration',
                'data_type': 'boolean'
            },
            {
                'key': 'waitlist_registration_enabled',
                'value': 'true',
                'description': 'Enable/disable waitlist registration functionality',
                'category': 'registration',
                'data_type': 'boolean'
            },
            {
                'key': 'admin_approval_required',
                'value': 'true',
                'description': 'Require admin approval for all new registrations',
                'category': 'registration',
                'data_type': 'boolean'
            },
            {
                'key': 'discord_only_login',
                'value': 'true',
                'description': 'Only allow Discord OAuth login (no password auth)',
                'category': 'registration',
                'data_type': 'boolean'
            },
            {
                'key': 'default_user_role',
                'value': 'pl-unverified',
                'description': 'Default role assigned to new registered users',
                'category': 'registration',
                'data_type': 'string'
            },
            {
                'key': 'require_real_name',
                'value': 'true',
                'description': 'Require users to provide their real name during registration',
                'category': 'registration',
                'data_type': 'boolean'
            },
            {
                'key': 'require_email',
                'value': 'true',
                'description': 'Require email address during registration',  
                'category': 'registration',
                'data_type': 'boolean'
            },
            {
                'key': 'require_phone',
                'value': 'false',
                'description': 'Require phone number during registration',
                'category': 'registration',
                'data_type': 'boolean'
            },
            {
                'key': 'require_location',
                'value': 'false',
                'description': 'Require location/address during registration',
                'category': 'registration',
                'data_type': 'boolean'
            },
            {
                'key': 'require_jersey_size',
                'value': 'true',
                'description': 'Require jersey size selection during registration',
                'category': 'registration',
                'data_type': 'boolean'
            },
            {
                'key': 'require_position_preferences',
                'value': 'true',
                'description': 'Require soccer position preferences during registration',
                'category': 'registration',
                'data_type': 'boolean'
            },
            {
                'key': 'require_availability',
                'value': 'true',
                'description': 'Require availability information during registration',
                'category': 'registration',
                'data_type': 'boolean'
            },
            {
                'key': 'require_referee_willingness',
                'value': 'true',
                'description': 'Require referee willingness question during registration',
                'category': 'registration',
                'data_type': 'boolean'
            },
            # System Settings
            {
                'key': 'apple_wallet_enabled',
                'value': 'true',
                'description': 'Enable/disable Apple Wallet pass functionality',
                'category': 'features',
                'data_type': 'boolean'
            },
            {
                'key': 'push_notifications_enabled',
                'value': 'true',
                'description': 'Enable/disable push notification functionality',
                'category': 'features',
                'data_type': 'boolean'
            },
            {
                'key': 'maintenance_mode',
                'value': 'false',
                'description': 'Enable maintenance mode (blocks non-admin access)',
                'category': 'system',
                'data_type': 'boolean'
            }
        ]

        try:
            for setting_data in default_settings:
                existing = cls.query.filter_by(key=setting_data['key']).first()
                if not existing:
                    setting = cls(**setting_data)
                    db.session.add(setting)
            
            db.session.commit()
            logger.info("Default admin settings initialized")
        except Exception as e:
            logger.error(f"Error initializing default settings: {e}")
            db.session.rollback()
            raise


class AdminAuditLog(db.Model):
    """
    Model for tracking admin actions and changes.
    
    This provides an audit trail of all admin panel activities
    for security and compliance purposes.
    """
    __tablename__ = 'admin_audit_log'

    id = db.Column(Integer, primary_key=True)
    user_id = db.Column(Integer, db.ForeignKey('users.id'), nullable=False)
    action = db.Column(String(100), nullable=False)
    resource_type = db.Column(String(50), nullable=False)  # 'admin_config', 'user', 'role', etc.
    resource_id = db.Column(String(100), nullable=True)  # ID of affected resource
    old_value = db.Column(Text, nullable=True)
    new_value = db.Column(Text, nullable=True)
    ip_address = db.Column(String(45), nullable=True)
    user_agent = db.Column(Text, nullable=True)
    timestamp = db.Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationship to user who performed the action
    user = db.relationship('User', backref='admin_audit_logs', lazy='select')

    def __repr__(self):
        return f'<AdminAuditLog {self.user_id}:{self.action} on {self.resource_type}>'

    @classmethod
    def log_action(cls, user_id, action, resource_type, resource_id=None, 
                   old_value=None, new_value=None, ip_address=None, user_agent=None):
        """
        Log an admin action.
        
        Args:
            user_id (int): ID of user performing action
            action (str): Action performed (create, update, delete, toggle, etc.)
            resource_type (str): Type of resource affected
            resource_id (str): ID of affected resource
            old_value (str): Previous value (for updates)
            new_value (str): New value (for updates)
            ip_address (str): IP address of user
            user_agent (str): User agent string
        """
        try:
            log_entry = cls(
                user_id=user_id,
                action=action,
                resource_type=resource_type,
                resource_id=str(resource_id) if resource_id else None,
                old_value=str(old_value) if old_value else None,
                new_value=str(new_value) if new_value else None,
                ip_address=ip_address,
                user_agent=user_agent
            )
            db.session.add(log_entry)
            db.session.commit()
            logger.info(f"Admin action logged: {user_id}:{action} on {resource_type}")
        except Exception as e:
            logger.error(f"Error logging admin action: {e}")
            db.session.rollback()

    @classmethod
    def get_recent_logs(cls, limit=100, user_id=None, resource_type=None):
        """Get recent audit logs with optional filtering."""
        from flask import g, has_request_context
        
        try:
            # Use Flask request session when available to prevent session conflicts
            if has_request_context() and hasattr(g, 'db_session') and g.db_session:
                query = g.db_session.query(cls)
            else:
                # Fallback to managed session for non-request contexts
                from app.core.session_manager import managed_session
                with managed_session() as session:
                    query = session.query(cls)
                    
                    if user_id:
                        query = query.filter_by(user_id=user_id)
                    if resource_type:
                        query = query.filter_by(resource_type=resource_type)
                        
                    return query.order_by(cls.timestamp.desc()).limit(limit).all()
            
            # This path executes when using request session
            if user_id:
                query = query.filter_by(user_id=user_id)
            if resource_type:
                query = query.filter_by(resource_type=resource_type)
                
            return query.order_by(cls.timestamp.desc()).limit(limit).all()
        except Exception as e:
            logger.error(f"Error getting audit logs: {e}")
            return []