# app/tasks/tasks_api_logging.py

"""
Async API Request Logging Task

Celery task for asynchronous API request logging to prevent
database connection pool exhaustion from blocking commits on every request.
"""

import logging
from datetime import datetime
from typing import Dict, Any, Optional

from app.decorators import celery_task

logger = logging.getLogger(__name__)


@celery_task(
    name='app.tasks.tasks_api_logging.log_api_request_async',
    bind=True,
    ignore_result=True,  # We don't need to track results for logging
    max_retries=1,  # Only retry once - logging isn't critical
    soft_time_limit=10,  # 10 second soft limit
    time_limit=30  # 30 second hard limit
)
def log_api_request_async(
    self,
    session,
    endpoint_path: str,
    method: str,
    status_code: int,
    response_time_ms: float,
    user_id: Optional[int],
    ip_address: Optional[str],
    user_agent: Optional[str],
    timestamp_iso: str
) -> Dict[str, Any]:
    """
    Async API request logging via Celery.

    This task is called asynchronously to log API requests without blocking
    the main request/response cycle. This prevents connection pool exhaustion
    under high load.

    Args:
        session: Database session (provided by celery_task decorator)
        endpoint_path: The API endpoint path
        method: HTTP method (GET, POST, etc.)
        status_code: HTTP response status code
        response_time_ms: Response time in milliseconds
        user_id: Optional user ID if authenticated
        ip_address: Client IP address
        user_agent: Client user agent string
        timestamp_iso: ISO formatted timestamp string

    Returns:
        dict with status information
    """
    try:
        from app.models.api_logs import APIRequestLog

        # Parse timestamp from ISO format
        try:
            timestamp = datetime.fromisoformat(timestamp_iso)
        except (ValueError, TypeError):
            timestamp = datetime.utcnow()

        # Create log entry directly using the session
        log_entry = APIRequestLog(
            endpoint_path=endpoint_path[:500] if endpoint_path else '',
            method=method,
            status_code=status_code,
            response_time_ms=response_time_ms,
            user_id=user_id,
            ip_address=ip_address,
            user_agent=user_agent[:500] if user_agent else None,
            timestamp=timestamp
        )
        session.add(log_entry)
        # Commit is handled by the celery_task decorator's managed_session

        return {'status': 'logged', 'endpoint': endpoint_path}

    except Exception as e:
        logger.debug(f"Failed to log API request: {e}")
        # Don't raise - logging failures shouldn't cause task retries
        return {'status': 'failed', 'error': str(e)}
