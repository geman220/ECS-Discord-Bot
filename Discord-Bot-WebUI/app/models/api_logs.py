# app/models/api_logs.py

"""
API Request Logging Model

This module provides a model for tracking API request metrics:
- Request endpoint and method
- Response status and timing
- User attribution
- Timestamps for analytics
"""

from datetime import datetime
from app.core import db


class APIRequestLog(db.Model):
    """Model for logging API requests for analytics."""
    __tablename__ = 'api_request_logs'

    id = db.Column(db.Integer, primary_key=True)
    endpoint_path = db.Column(db.String(500), nullable=False, index=True)
    method = db.Column(db.String(10), nullable=False)
    status_code = db.Column(db.Integer, nullable=False)
    response_time_ms = db.Column(db.Float, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    ip_address = db.Column(db.String(45), nullable=True)  # IPv6 max length
    user_agent = db.Column(db.String(500), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True, nullable=False)

    # Optional: Link to user for attribution
    user = db.relationship('User', backref=db.backref('api_requests', lazy='dynamic'))

    def __repr__(self):
        return f'<APIRequestLog {self.method} {self.endpoint_path} {self.status_code}>'

    @classmethod
    def log_request(cls, endpoint_path, method, status_code, response_time_ms,
                   user_id=None, ip_address=None, user_agent=None):
        """
        Log an API request.

        Args:
            endpoint_path: The API endpoint path
            method: HTTP method (GET, POST, etc.)
            status_code: HTTP response status code
            response_time_ms: Response time in milliseconds
            user_id: Optional user ID if authenticated
            ip_address: Client IP address
            user_agent: Client user agent string
        """
        log_entry = cls(
            endpoint_path=endpoint_path[:500],  # Truncate if too long
            method=method,
            status_code=status_code,
            response_time_ms=response_time_ms,
            user_id=user_id,
            ip_address=ip_address,
            user_agent=user_agent[:500] if user_agent else None
        )
        db.session.add(log_entry)
        # Don't commit here - let the caller handle transaction

    @classmethod
    def get_stats(cls, hours=24):
        """
        Get API statistics for the specified time window.

        Args:
            hours: Number of hours to look back

        Returns:
            dict with total_requests, avg_response_time, error_rate, etc.
        """
        from datetime import timedelta
        from sqlalchemy import func

        cutoff = datetime.utcnow() - timedelta(hours=hours)

        # Total requests
        total = cls.query.filter(cls.timestamp >= cutoff).count()

        if total == 0:
            return {
                'total_requests': 0,
                'avg_response_time': 0,
                'error_rate': 0,
                'requests_per_hour': 0,
                'success_count': 0,
                'error_count': 0
            }

        # Average response time
        avg_time = db.session.query(func.avg(cls.response_time_ms)).filter(
            cls.timestamp >= cutoff
        ).scalar() or 0

        # Error count (4xx and 5xx)
        error_count = cls.query.filter(
            cls.timestamp >= cutoff,
            cls.status_code >= 400
        ).count()

        success_count = total - error_count
        error_rate = (error_count / total * 100) if total > 0 else 0

        return {
            'total_requests': total,
            'avg_response_time': round(avg_time, 2),
            'error_rate': round(error_rate, 2),
            'requests_per_hour': round(total / hours, 2),
            'success_count': success_count,
            'error_count': error_count
        }

    @classmethod
    def get_endpoint_breakdown(cls, hours=24, limit=10):
        """
        Get request counts by endpoint.

        Args:
            hours: Number of hours to look back
            limit: Maximum number of endpoints to return

        Returns:
            list of dicts with endpoint, count, avg_time
        """
        from datetime import timedelta
        from sqlalchemy import func

        cutoff = datetime.utcnow() - timedelta(hours=hours)

        results = db.session.query(
            cls.endpoint_path,
            func.count(cls.id).label('count'),
            func.avg(cls.response_time_ms).label('avg_time'),
            func.sum(db.case((cls.status_code >= 400, 1), else_=0)).label('errors')
        ).filter(
            cls.timestamp >= cutoff
        ).group_by(
            cls.endpoint_path
        ).order_by(
            func.count(cls.id).desc()
        ).limit(limit).all()

        return [
            {
                'endpoint': r.endpoint_path,
                'count': r.count,
                'avg_time': round(r.avg_time, 2) if r.avg_time else 0,
                'errors': r.errors or 0
            }
            for r in results
        ]

    @classmethod
    def get_hourly_breakdown(cls, hours=24):
        """
        Get request counts by hour.

        Args:
            hours: Number of hours to look back

        Returns:
            list of dicts with hour and count
        """
        from datetime import timedelta
        from sqlalchemy import func, extract

        cutoff = datetime.utcnow() - timedelta(hours=hours)

        results = db.session.query(
            extract('hour', cls.timestamp).label('hour'),
            func.count(cls.id).label('count')
        ).filter(
            cls.timestamp >= cutoff
        ).group_by(
            extract('hour', cls.timestamp)
        ).order_by(
            extract('hour', cls.timestamp)
        ).all()

        return [
            {'hour': int(r.hour), 'count': r.count}
            for r in results
        ]

    @classmethod
    def cleanup_old_logs(cls, days=30):
        """
        Remove logs older than the specified number of days.

        Args:
            days: Number of days to keep

        Returns:
            Number of deleted records
        """
        from datetime import timedelta

        cutoff = datetime.utcnow() - timedelta(days=days)
        deleted = cls.query.filter(cls.timestamp < cutoff).delete()
        db.session.commit()
        return deleted
