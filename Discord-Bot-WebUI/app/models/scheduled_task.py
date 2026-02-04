"""
Scheduled Task Model

Database-backed task tracking that persists beyond Redis TTL expiration.
Solves the issue where matches scheduled >2 days in advance lose task tracking.
"""

from datetime import datetime
from sqlalchemy import Index
from app.core import db
from enum import Enum


class TaskType(str, Enum):
    """Types of scheduled tasks for match operations."""
    THREAD_CREATION = 'thread_creation'
    LIVE_REPORTING_START = 'live_reporting_start'


class TaskState(str, Enum):
    """Lifecycle states for scheduled tasks."""
    SCHEDULED = 'scheduled'
    RUNNING = 'running'
    COMPLETED = 'completed'
    FAILED = 'failed'
    EXPIRED = 'expired'
    PAUSED = 'paused'


class ScheduledTask(db.Model):
    """
    Database-backed task tracking that persists beyond Redis TTL.

    This model solves the critical issue where matches scheduled weeks in advance
    lose task tracking when Redis metadata expires after 2 days. The database
    becomes the source of truth for what tasks should execute.
    """
    __tablename__ = 'scheduled_tasks'

    id = db.Column(db.Integer, primary_key=True)
    task_type = db.Column(db.String(50), nullable=False)
    match_id = db.Column(db.Integer, nullable=False, index=True)
    celery_task_id = db.Column(db.String(100), index=True)

    # Scheduling information
    scheduled_time = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    execution_time = db.Column(db.DateTime(timezone=True))
    completion_time = db.Column(db.DateTime(timezone=True))

    # State tracking
    state = db.Column(db.String(20), nullable=False, default=TaskState.SCHEDULED, index=True)
    retry_count = db.Column(db.Integer, default=0)
    last_error = db.Column(db.Text)
    paused_celery_task_id = db.Column(db.String(100))  # Store original task ID when paused

    # Metadata
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), onupdate=datetime.utcnow)

    # Composite indexes for common queries
    __table_args__ = (
        Index('idx_match_type', 'match_id', 'task_type'),
        Index('idx_state_scheduled', 'state', 'scheduled_time'),
    )

    @classmethod
    def get_pending_tasks(cls, session, task_type=None, now=None):
        """
        Get tasks that should be running but aren't (overdue scheduled tasks).

        Args:
            session: Database session
            task_type: Optional filter by task type
            now: Optional current time (defaults to utcnow)

        Returns:
            List of ScheduledTask objects that are overdue
        """
        if now is None:
            now = datetime.utcnow()

        query = session.query(cls).filter(
            cls.state == TaskState.SCHEDULED,
            cls.scheduled_time <= now
        )

        if task_type:
            query = query.filter(cls.task_type == task_type)

        return query.all()

    @classmethod
    def find_existing_task(cls, session, match_id, task_type):
        """
        Find existing active task for a match.

        Args:
            session: Database session
            match_id: Match ID
            task_type: Type of task

        Returns:
            ScheduledTask or None
        """
        return session.query(cls).filter(
            cls.match_id == match_id,
            cls.task_type == task_type,
            cls.state.in_([TaskState.SCHEDULED, TaskState.RUNNING])
        ).first()

    def mark_running(self, celery_id=None):
        """Mark task as running."""
        self.state = TaskState.RUNNING
        self.execution_time = datetime.utcnow()
        if celery_id:
            self.celery_task_id = celery_id

    def mark_completed(self):
        """Mark task as completed."""
        self.state = TaskState.COMPLETED
        self.completion_time = datetime.utcnow()

    def mark_failed(self, error):
        """Mark task as failed with error message."""
        self.state = TaskState.FAILED
        self.last_error = str(error)[:500]  # Truncate long errors
        self.retry_count += 1

    def mark_expired(self):
        """Mark task as expired (scheduled time passed without execution)."""
        self.state = TaskState.EXPIRED

    def mark_paused(self):
        """
        Mark task as paused.
        Stores the current celery task ID so it can be revoked,
        and preserves the scheduled time for potential resume.
        """
        self.paused_celery_task_id = self.celery_task_id
        self.celery_task_id = None
        self.state = TaskState.PAUSED

    def mark_resumed(self, new_celery_task_id):
        """
        Mark task as resumed (back to scheduled).
        Sets a new celery task ID for the rescheduled task.
        """
        self.celery_task_id = new_celery_task_id
        self.paused_celery_task_id = None
        self.state = TaskState.SCHEDULED

    def to_dict(self):
        """Convert to dictionary for JSON serialization."""
        return {
            'id': self.id,
            'task_type': self.task_type,
            'match_id': self.match_id,
            'celery_task_id': self.celery_task_id,
            'scheduled_time': self.scheduled_time.isoformat() if self.scheduled_time else None,
            'execution_time': self.execution_time.isoformat() if self.execution_time else None,
            'completion_time': self.completion_time.isoformat() if self.completion_time else None,
            'state': self.state,
            'retry_count': self.retry_count,
            'last_error': self.last_error,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

    def __repr__(self):
        return f'<ScheduledTask {self.id}: {self.task_type} for match {self.match_id} - {self.state}>'
