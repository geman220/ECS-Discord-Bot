# app/utils/deferred_audit.py

"""
Deferred Audit Log Module

Provides a mechanism to write audit log entries via Celery, outside the
caller's database transaction. This prevents slow admin_audit_log INSERTs
from blocking or rolling back critical data changes.
"""

import logging
from flask import g, has_request_context, after_this_request

logger = logging.getLogger(__name__)


def _is_testing():
    """Check if the app is in testing mode (Celery is mocked in tests)."""
    try:
        from flask import current_app
        return current_app.testing
    except RuntimeError:
        return False


def _write_synchronously(entries):
    """Write audit log entries directly to the database (no Celery)."""
    from app.models.admin_config import AdminAuditLog
    for entry in entries:
        try:
            AdminAuditLog.log_action(**entry, auto_commit=True, deferred=False)
        except Exception as e:
            logger.error(f"Failed to write audit log entry: {e}")


def defer_audit_log(**kwargs):
    """
    Queue an audit log entry to be written via Celery after the current
    request's transaction commits.

    Accepts the same keyword arguments as AdminAuditLog.log_action()
    (minus auto_commit/deferred, which are handled internally).

    Inside a request context the entries are batched and dispatched in
    an after_this_request callback (i.e. after @transactional commits).
    Outside a request context (e.g. Celery tasks) it dispatches immediately.
    In test mode, writes synchronously since Celery is mocked.
    """
    # Remove parameters that are handled internally
    kwargs.pop('auto_commit', None)
    kwargs.pop('deferred', None)

    # Tests mock Celery, so deferred writes would be silently lost.
    # Write synchronously to keep test assertions on audit log counts working.
    if _is_testing():
        _write_synchronously([kwargs])
        return

    if not has_request_context():
        _dispatch_to_celery([kwargs])
        return

    if not hasattr(g, '_deferred_audit_logs'):
        g._deferred_audit_logs = []

        @after_this_request
        def _dispatch_deferred_audit_logs(response):
            """Dispatch queued audit log writes to Celery after commit."""
            entries = g._deferred_audit_logs
            if entries:
                _dispatch_to_celery(entries)
            return response

    g._deferred_audit_logs.append(kwargs)


def _dispatch_to_celery(entries):
    """Send audit log entries to the Celery task."""
    try:
        from app.tasks.tasks_audit import write_audit_logs_task
        write_audit_logs_task.delay(entries)
    except Exception as e:
        # If Celery is down, fall back to synchronous write so we don't
        # silently lose audit entries.
        logger.warning(f"Celery dispatch failed for audit logs, writing synchronously: {e}")
        _write_synchronously(entries)
