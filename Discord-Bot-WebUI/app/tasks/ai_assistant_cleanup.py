# app/tasks/ai_assistant_cleanup.py

"""
AI Assistant Cleanup Task

Scheduled daily to:
- Delete AI assistant logs older than 90 days
- Log cleanup results to admin audit log
"""

import logging
from app.decorators import celery_task

logger = logging.getLogger(__name__)


@celery_task(
    name='app.tasks.ai_assistant_cleanup.cleanup_ai_logs',
    bind=True,
    queue='default',
    max_retries=1
)
def cleanup_ai_logs(self, session, retention_days=90):
    """Delete AI assistant interaction logs older than retention_days."""
    try:
        from app.models.ai_assistant import AIAssistantLog

        deleted_count = AIAssistantLog.cleanup_old_logs(days=retention_days)

        logger.info(f"AI assistant log cleanup: deleted {deleted_count} logs older than {retention_days} days")

        return {
            'success': True,
            'deleted_count': deleted_count,
            'retention_days': retention_days
        }
    except Exception as e:
        logger.error(f"AI assistant log cleanup failed: {e}")
        return {
            'success': False,
            'error': str(e)
        }
