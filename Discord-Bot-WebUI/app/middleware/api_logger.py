# app/middleware/api_logger.py

"""
API Request Logger Middleware

Logs API requests for analytics and monitoring.
Only logs requests to /api/ endpoints to reduce noise.
"""

import logging
import time
from functools import wraps

from flask import request, g
from flask_login import current_user

logger = logging.getLogger(__name__)

# Endpoints to exclude from logging (health checks, etc.)
EXCLUDED_ENDPOINTS = [
    '/api/health',
    '/api/ping',
    '/api/status',
]

# Maximum requests to log per minute to avoid overwhelming the database
MAX_LOGS_PER_MINUTE = 1000
_log_count_this_minute = 0
_last_minute = 0


def init_api_logger(app):
    """
    Initialize the API logger middleware.

    Args:
        app: Flask application instance
    """

    @app.before_request
    def start_timer():
        """Record the start time for response time calculation."""
        if request.path.startswith('/api/'):
            g.api_request_start_time = time.time()

    @app.after_request
    def log_api_request(response):
        """Log API requests after they complete."""
        global _log_count_this_minute, _last_minute

        # Only log API requests
        if not request.path.startswith('/api/'):
            return response

        # Skip excluded endpoints
        if any(request.path.startswith(excluded) for excluded in EXCLUDED_ENDPOINTS):
            return response

        # Rate limiting for logging
        current_minute = int(time.time() / 60)
        if current_minute != _last_minute:
            _log_count_this_minute = 0
            _last_minute = current_minute

        if _log_count_this_minute >= MAX_LOGS_PER_MINUTE:
            return response

        try:
            # Calculate response time
            start_time = getattr(g, 'api_request_start_time', None)
            if start_time:
                response_time_ms = (time.time() - start_time) * 1000
            else:
                response_time_ms = 0

            # Get user ID if authenticated
            user_id = None
            try:
                if current_user and current_user.is_authenticated:
                    user_id = current_user.id
            except Exception:
                pass

            # Get client info
            ip_address = request.remote_addr
            user_agent = request.headers.get('User-Agent', '')

            # Log the request
            from app.models.api_logs import APIRequestLog
            from app.core import db

            APIRequestLog.log_request(
                endpoint_path=request.path,
                method=request.method,
                status_code=response.status_code,
                response_time_ms=response_time_ms,
                user_id=user_id,
                ip_address=ip_address,
                user_agent=user_agent
            )

            # Commit the log entry
            try:
                db.session.commit()
                _log_count_this_minute += 1
            except Exception as commit_error:
                db.session.rollback()
                logger.debug(f"Failed to commit API log: {commit_error}")

        except Exception as e:
            # Don't let logging errors affect the response
            logger.debug(f"Error logging API request: {e}")

        return response

    logger.info("API request logger middleware initialized")
