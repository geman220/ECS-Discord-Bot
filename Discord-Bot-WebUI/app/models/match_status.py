"""
Match Status Enum

Defines canonical status values for MLS match live reporting.
This enum ensures consistency across the entire codebase and prevents
bugs caused by status value mismatches (e.g., 'FINISHED' vs 'completed').
"""

from enum import Enum


class MatchStatus(str, Enum):
    """Canonical match status values for live reporting."""

    NOT_STARTED = 'not_started'
    SCHEDULED = 'scheduled'
    RUNNING = 'running'
    STOPPED = 'stopped'
    COMPLETED = 'completed'
    FAILED = 'failed'

    @classmethod
    def is_live(cls, status: str) -> bool:
        """
        Check if status represents a live match.

        Args:
            status: Status string to check

        Returns:
            True if the match is currently live
        """
        return status == cls.RUNNING

    @classmethod
    def is_finished(cls, status: str) -> bool:
        """
        Check if status represents a finished match.

        Args:
            status: Status string to check

        Returns:
            True if the match has finished (completed or stopped)
        """
        return status in [cls.COMPLETED, cls.STOPPED]

    @classmethod
    def is_active(cls, status: str) -> bool:
        """
        Check if status should have an active session.

        Args:
            status: Status string to check

        Returns:
            True if the match should have an active reporting session
        """
        return status in [cls.SCHEDULED, cls.RUNNING]

    @classmethod
    def get_display_name(cls, status: str) -> str:
        """
        Get human-readable display name for status.

        Args:
            status: Status string

        Returns:
            Human-readable status display name
        """
        display_names = {
            cls.NOT_STARTED: 'Not Started',
            cls.SCHEDULED: 'Scheduled',
            cls.RUNNING: 'Live',
            cls.STOPPED: 'Stopped',
            cls.COMPLETED: 'Completed',
            cls.FAILED: 'Failed'
        }
        return display_names.get(status, status.title())

    @classmethod
    def get_color_class(cls, status: str) -> str:
        """
        Get Bootstrap color class for status.

        Args:
            status: Status string

        Returns:
            Bootstrap color class (e.g., 'success', 'warning')
        """
        color_classes = {
            cls.NOT_STARTED: 'info',
            cls.SCHEDULED: 'info',
            cls.RUNNING: 'warning',
            cls.STOPPED: 'secondary',
            cls.COMPLETED: 'success',
            cls.FAILED: 'danger'
        }
        return color_classes.get(status, 'secondary')

    @classmethod
    def get_icon_class(cls, status: str) -> str:
        """
        Get icon class for status.

        Args:
            status: Status string

        Returns:
            Icon class (e.g., 'ti-clock', 'ti-player-play')
        """
        icon_classes = {
            cls.NOT_STARTED: 'ti-clock',
            cls.SCHEDULED: 'ti-clock',
            cls.RUNNING: 'ti-player-play',
            cls.STOPPED: 'ti-player-stop',
            cls.COMPLETED: 'ti-check',
            cls.FAILED: 'ti-x'
        }
        return icon_classes.get(status, 'ti-question-mark')
