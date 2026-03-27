# app/tasks/tasks_audit.py

"""
Audit log Celery tasks.

- write_audit_logs_task: Async INSERT so slow writes don't block/rollback
  request transactions.
- maintain_audit_log_table: Periodic cleanup that prunes old rows and runs
  VACUUM to prevent table bloat (the root cause of slow INSERTs).
"""

import logging
from datetime import datetime, timedelta
from app.decorators import celery_task

logger = logging.getLogger(__name__)


@celery_task(bind=True)
def write_audit_logs_task(self, session, entries):
    """
    Write one or more audit log entries to admin_audit_log.

    Args:
        session: Database session provided by @celery_task decorator.
        entries: List of dicts, each with keys matching AdminAuditLog columns
                 (user_id, action, resource_type, resource_id, old_value,
                  new_value, ip_address, user_agent).
    """
    from app.models.admin_config import AdminAuditLog

    written = 0
    for entry in entries:
        try:
            log_entry = AdminAuditLog(
                user_id=entry['user_id'],
                action=entry['action'],
                resource_type=entry['resource_type'],
                resource_id=str(entry['resource_id']) if entry.get('resource_id') else None,
                old_value=str(entry['old_value']) if entry.get('old_value') else None,
                new_value=str(entry['new_value']) if entry.get('new_value') else None,
                ip_address=entry.get('ip_address'),
                user_agent=entry.get('user_agent'),
            )
            session.add(log_entry)
            written += 1
        except Exception as e:
            logger.error(f"Failed to create audit log entry: {e}")

    try:
        session.commit()
        logger.debug(f"Wrote {written} audit log entries")
    except Exception as e:
        logger.error(f"Failed to commit audit log entries: {e}")
        session.rollback()

    return {'written': written, 'total': len(entries)}


@celery_task(bind=True)
def maintain_audit_log_table(self, session, retention_days=90):
    """
    Periodic maintenance for admin_audit_log:
      1. Delete rows older than retention_days.
      2. VACUUM the table to reclaim space and prevent bloat.

    VACUUM cannot run inside a transaction, so we use a raw autocommit
    connection from the engine.

    Args:
        session: Database session provided by @celery_task decorator.
        retention_days: How many days of audit history to keep (default 90).
    """
    from app.models.admin_config import AdminAuditLog
    from app.core import db
    from sqlalchemy import text

    cutoff = datetime.utcnow() - timedelta(days=retention_days)

    # --- Step 1: Prune old rows (normal transactional DELETE) ---
    try:
        deleted = session.query(AdminAuditLog).filter(
            AdminAuditLog.timestamp < cutoff
        ).delete(synchronize_session=False)
        session.commit()
        logger.info(
            f"Audit log maintenance: deleted {deleted} rows older than "
            f"{retention_days} days (before {cutoff.date()})"
        )
    except Exception as e:
        logger.error(f"Audit log maintenance: failed to prune rows: {e}")
        session.rollback()
        return {'status': 'error', 'step': 'prune', 'error': str(e)}

    # --- Step 2: VACUUM (requires autocommit / no transaction) ---
    try:
        raw_conn = db.engine.raw_connection()
        try:
            raw_conn.set_session(autocommit=True)
            cursor = raw_conn.cursor()
            cursor.execute('VACUUM ANALYZE admin_audit_log')
            cursor.close()
            logger.info("Audit log maintenance: VACUUM ANALYZE completed")
        finally:
            raw_conn.close()
    except Exception as e:
        # VACUUM failure is non-fatal — the prune already succeeded.
        logger.warning(f"Audit log maintenance: VACUUM failed (non-fatal): {e}")

    return {
        'status': 'success',
        'deleted': deleted,
        'retention_days': retention_days,
    }
