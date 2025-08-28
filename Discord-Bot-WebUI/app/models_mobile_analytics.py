# app/models_mobile_analytics.py

"""
Mobile Analytics Models

SQLAlchemy models for mobile error analytics, patterns, and logging.
Supports comprehensive error tracking, pattern analysis, and structured logging
from Flutter mobile application.
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Boolean, DECIMAL, DateTime, ForeignKey, CheckConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from app import db

class MobileErrorAnalytics(db.Model):
    """
    Mobile error analytics and crash reports from Flutter app.
    
    Tracks individual error occurrences with full context, recovery information,
    and user impact assessment for comprehensive error monitoring.
    """
    __tablename__ = 'mobile_error_analytics'
    
    id = Column(Integer, primary_key=True)
    error_id = Column(String(255), unique=True, nullable=False, index=True)
    error_type = Column(String(100), nullable=False, index=True)
    error_code = Column(String(100))
    error_message = Column(Text)
    technical_message = Column(Text)
    severity = Column(String(20), nullable=False, index=True)
    should_report = Column(Boolean, default=True)
    operation = Column(String(255))
    context = Column(JSONB)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    trace_id = Column(String(255), index=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), index=True)
    device_info = Column(String(255))
    app_version = Column(String(50))
    was_recovered = Column(Boolean, default=False)
    recovery_result = Column(Text)
    recovery_actions = Column(JSONB)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, index=True)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship('User', backref='mobile_errors')
    
    # Constraints
    __table_args__ = (
        CheckConstraint("severity IN ('low', 'medium', 'high', 'critical')", name='check_severity'),
    )
    
    def __repr__(self):
        return f'<MobileErrorAnalytics {self.error_id}: {self.error_type}>'
    
    def to_dict(self):
        """Convert to dictionary for API responses."""
        return {
            'id': self.id,
            'error_id': self.error_id,
            'error_type': self.error_type,
            'error_code': self.error_code,
            'error_message': self.error_message,
            'technical_message': self.technical_message,
            'severity': self.severity,
            'should_report': self.should_report,
            'operation': self.operation,
            'context': self.context,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'trace_id': self.trace_id,
            'user_id': self.user_id,
            'device_info': self.device_info,
            'app_version': self.app_version,
            'was_recovered': self.was_recovered,
            'recovery_result': self.recovery_result,
            'recovery_actions': self.recovery_actions,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class MobileErrorPatterns(db.Model):
    """
    Mobile error patterns and trend analysis.
    
    Aggregates error occurrences to identify patterns, track recovery rates,
    and provide insights for improving app reliability.
    """
    __tablename__ = 'mobile_error_patterns'
    
    id = Column(Integer, primary_key=True)
    pattern_id = Column(String(255), unique=True, nullable=False, index=True)
    error_type = Column(String(100), nullable=False, index=True)
    operation = Column(String(255), index=True)
    occurrences = Column(Integer, default=1)
    first_seen = Column(DateTime(timezone=True), nullable=False)
    last_seen = Column(DateTime(timezone=True), nullable=False, index=True)
    recovery_rate = Column(DECIMAL(3, 2), default=0.0)
    common_context_keys = Column(JSONB)
    error_metadata = Column('metadata', JSONB)  # Column name in DB is 'metadata'
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Constraints
    __table_args__ = (
        CheckConstraint("recovery_rate >= 0.0 AND recovery_rate <= 1.0", name='check_recovery_rate'),
    )
    
    def __repr__(self):
        return f'<MobileErrorPatterns {self.pattern_id}: {self.error_type} ({self.occurrences}x)>'
    
    def to_dict(self):
        """Convert to dictionary for API responses."""
        return {
            'id': self.id,
            'pattern_id': self.pattern_id,
            'error_type': self.error_type,
            'operation': self.operation,
            'occurrences': self.occurrences,
            'first_seen': self.first_seen.isoformat() if self.first_seen else None,
            'last_seen': self.last_seen.isoformat() if self.last_seen else None,
            'recovery_rate': float(self.recovery_rate) if self.recovery_rate else 0.0,
            'common_context_keys': self.common_context_keys,
            'metadata': self.error_metadata,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class MobileLogs(db.Model):
    """
    Structured logs from mobile application.
    
    Stores detailed application logs with structured context for debugging,
    monitoring, and operational insights.
    """
    __tablename__ = 'mobile_logs'
    
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    level = Column(String(20), nullable=False, index=True)
    message = Column(Text, nullable=False)
    logger = Column(String(100))
    trace_id = Column(String(255), index=True)
    session_id = Column(String(255))
    user_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), index=True)
    context = Column(JSONB)
    error_info = Column(Text)
    stack_trace = Column(Text)
    error_metadata = Column('metadata', JSONB)  # Column name in DB is 'metadata'
    platform = Column(String(50))
    app_version = Column(String(50))
    flutter_version = Column(String(50))
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, index=True)
    
    # Relationships
    user = relationship('User', backref='mobile_logs')
    
    # Constraints
    __table_args__ = (
        CheckConstraint("level IN ('DEBUG', 'INFO', 'WARN', 'ERROR', 'FATAL')", name='check_log_level'),
    )
    
    def __repr__(self):
        return f'<MobileLogs {self.level}: {self.message[:50]}...>'
    
    def to_dict(self):
        """Convert to dictionary for API responses."""
        return {
            'id': self.id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'level': self.level,
            'message': self.message,
            'logger': self.logger,
            'trace_id': self.trace_id,
            'session_id': self.session_id,
            'user_id': self.user_id,
            'context': self.context,
            'error_info': self.error_info,
            'stack_trace': self.stack_trace,
            'metadata': self.error_metadata,
            'platform': self.platform,
            'app_version': self.app_version,
            'flutter_version': self.flutter_version,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


# Utility functions for analytics
def get_error_summary(days=7):
    """
    Get error summary for the last N days.
    
    Returns:
        dict: Summary statistics including total errors, by severity, by type, etc.
    """
    from datetime import timedelta
    from sqlalchemy import func
    
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    
    # Total errors
    total_errors = db.session.query(MobileErrorAnalytics).filter(
        MobileErrorAnalytics.created_at >= cutoff_date
    ).count()
    
    # Errors by severity
    severity_stats = db.session.query(
        MobileErrorAnalytics.severity,
        func.count(MobileErrorAnalytics.id).label('count')
    ).filter(
        MobileErrorAnalytics.created_at >= cutoff_date
    ).group_by(MobileErrorAnalytics.severity).all()
    
    # Top error types
    error_type_stats = db.session.query(
        MobileErrorAnalytics.error_type,
        func.count(MobileErrorAnalytics.id).label('count')
    ).filter(
        MobileErrorAnalytics.created_at >= cutoff_date
    ).group_by(MobileErrorAnalytics.error_type).order_by(
        func.count(MobileErrorAnalytics.id).desc()
    ).limit(10).all()
    
    # Recovery rate
    total_with_recovery_info = db.session.query(MobileErrorAnalytics).filter(
        MobileErrorAnalytics.created_at >= cutoff_date,
        MobileErrorAnalytics.was_recovered.isnot(None)
    ).count()
    
    recovered_errors = db.session.query(MobileErrorAnalytics).filter(
        MobileErrorAnalytics.created_at >= cutoff_date,
        MobileErrorAnalytics.was_recovered == True
    ).count()
    
    recovery_rate = (recovered_errors / total_with_recovery_info) if total_with_recovery_info > 0 else 0
    
    return {
        'total_errors': total_errors,
        'severity_breakdown': {item.severity: item.count for item in severity_stats},
        'top_error_types': [{'type': item.error_type, 'count': item.count} for item in error_type_stats],
        'recovery_rate': round(recovery_rate, 2),
        'period_days': days
    }


def get_active_patterns(limit=20):
    """
    Get most active error patterns.
    
    Returns:
        list: Active error patterns sorted by recent activity
    """
    from datetime import timedelta
    
    cutoff_date = datetime.utcnow() - timedelta(days=7)
    
    patterns = db.session.query(MobileErrorPatterns).filter(
        MobileErrorPatterns.last_seen >= cutoff_date
    ).order_by(
        MobileErrorPatterns.occurrences.desc(),
        MobileErrorPatterns.last_seen.desc()
    ).limit(limit).all()
    
    return [pattern.to_dict() for pattern in patterns]