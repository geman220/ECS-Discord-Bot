"""
Security models for IP bans and security events.
"""
from datetime import datetime, timedelta
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, Index
from sqlalchemy.sql import func
from app.core import db


class IPBan(db.Model):
    """Model for storing IP bans."""
    __tablename__ = 'ip_bans'
    
    id = Column(Integer, primary_key=True)
    ip_address = Column(String(45), nullable=False, index=True)  # IPv6 can be up to 45 chars
    reason = Column(String(255), nullable=True)
    banned_by = Column(String(100), nullable=True)  # Username who banned the IP
    banned_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=True)  # NULL means permanent ban
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Add indexes for performance
    __table_args__ = (
        Index('idx_ip_active', 'ip_address', 'is_active'),
        Index('idx_expires_at', 'expires_at'),
    )
    
    def __repr__(self):
        return f'<IPBan {self.ip_address}>'
    
    @property
    def is_expired(self):
        """Check if the ban has expired."""
        if not self.expires_at:
            return False  # Permanent ban
        return datetime.utcnow() > self.expires_at
    
    @property
    def time_remaining(self):
        """Get time remaining for the ban in seconds."""
        if not self.expires_at:
            return None  # Permanent ban
        remaining = self.expires_at - datetime.utcnow()
        return max(0, int(remaining.total_seconds()))
    
    @classmethod
    def is_ip_banned(cls, ip_address):
        """Check if an IP is currently banned."""
        now = datetime.utcnow()
        return db.session.query(cls).filter(
            cls.ip_address == ip_address,
            cls.is_active == True,
            db.or_(cls.expires_at.is_(None), cls.expires_at > now)
        ).first() is not None
    
    @classmethod
    def get_active_bans(cls):
        """Get all active bans."""
        now = datetime.utcnow()
        return db.session.query(cls).filter(
            cls.is_active == True,
            db.or_(cls.expires_at.is_(None), cls.expires_at > now)
        ).order_by(cls.banned_at.desc()).all()
    
    @classmethod
    def ban_ip(cls, ip_address, reason=None, banned_by=None, duration_hours=None):
        """Ban an IP address."""
        # Check if already banned
        existing_ban = db.session.query(cls).filter(
            cls.ip_address == ip_address,
            cls.is_active == True
        ).first()
        
        if existing_ban:
            # Update existing ban
            existing_ban.reason = reason or existing_ban.reason
            existing_ban.banned_by = banned_by or existing_ban.banned_by
            existing_ban.banned_at = datetime.utcnow()
            existing_ban.expires_at = datetime.utcnow() + timedelta(hours=duration_hours) if duration_hours else None
            existing_ban.updated_at = datetime.utcnow()
            ban = existing_ban
        else:
            # Create new ban
            expires_at = datetime.utcnow() + timedelta(hours=duration_hours) if duration_hours else None
            ban = cls(
                ip_address=ip_address,
                reason=reason,
                banned_by=banned_by,
                expires_at=expires_at
            )
            db.session.add(ban)
        
        db.session.commit()
        return ban
    
    @classmethod
    def unban_ip(cls, ip_address):
        """Unban an IP address."""
        bans = db.session.query(cls).filter(
            cls.ip_address == ip_address,
            cls.is_active == True
        ).all()
        
        count = 0
        for ban in bans:
            ban.is_active = False
            ban.updated_at = datetime.utcnow()
            count += 1
        
        db.session.commit()
        return count
    
    @classmethod
    def clear_expired_bans(cls):
        """Clear expired bans."""
        now = datetime.utcnow()
        expired_bans = db.session.query(cls).filter(
            cls.is_active == True,
            cls.expires_at.isnot(None),
            cls.expires_at <= now
        ).all()
        
        count = 0
        for ban in expired_bans:
            ban.is_active = False
            ban.updated_at = datetime.utcnow()
            count += 1
        
        db.session.commit()
        return count
    
    @classmethod
    def clear_all_bans(cls):
        """Clear all active bans."""
        active_bans = db.session.query(cls).filter(cls.is_active == True).all()
        
        count = 0
        for ban in active_bans:
            ban.is_active = False
            ban.updated_at = datetime.utcnow()
            count += 1
        
        db.session.commit()
        return count


class SecurityEvent(db.Model):
    """Model for storing security events."""
    __tablename__ = 'security_events'
    
    id = Column(Integer, primary_key=True)
    event_type = Column(String(50), nullable=False)  # 'attack_detected', 'ip_banned', 'rate_limit_exceeded'
    ip_address = Column(String(45), nullable=False, index=True)
    severity = Column(String(20), nullable=False, default='medium')  # 'low', 'medium', 'high', 'critical'
    description = Column(Text, nullable=True)
    details = Column(Text, nullable=True)  # JSON details about the event
    user_agent = Column(String(500), nullable=True)
    request_path = Column(String(500), nullable=True)
    request_method = Column(String(10), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    # Add indexes for performance
    __table_args__ = (
        Index('idx_event_type_created', 'event_type', 'created_at'),
        Index('idx_ip_created', 'ip_address', 'created_at'),
        Index('idx_severity_created', 'severity', 'created_at'),
    )
    
    def __repr__(self):
        return f'<SecurityEvent {self.event_type} from {self.ip_address}>'
    
    @classmethod
    def log_event(cls, event_type, ip_address, severity='medium', description=None, 
                  details=None, user_agent=None, request_path=None, request_method=None):
        """Log a security event."""
        event = cls(
            event_type=event_type,
            ip_address=ip_address,
            severity=severity,
            description=description,
            details=details,
            user_agent=user_agent,
            request_path=request_path,
            request_method=request_method
        )
        db.session.add(event)
        db.session.commit()
        return event
    
    @classmethod
    def get_recent_events(cls, limit=50, hours=24):
        """Get recent security events."""
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        return db.session.query(cls).filter(
            cls.created_at >= cutoff
        ).order_by(cls.created_at.desc()).limit(limit).all()
    
    @classmethod
    def cleanup_old_events(cls, days=30):
        """Clean up old security events."""
        cutoff = datetime.utcnow() - timedelta(days=days)
        count = db.session.query(cls).filter(cls.created_at < cutoff).count()
        db.session.query(cls).filter(cls.created_at < cutoff).delete()
        db.session.commit()
        return count