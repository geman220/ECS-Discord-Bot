# app/services/base_service.py

"""
Base Service for Business Logic.

Provides a foundational service class with common patterns including:
- Session management
- Operation tracing
- Error handling
- Metrics collection
"""

import logging
import uuid
from abc import ABC
from datetime import datetime
from typing import Optional, TypeVar, Generic, Dict, Any, Tuple
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.dto.base import APIResponse


logger = logging.getLogger(__name__)
T = TypeVar('T')


@dataclass
class ServiceResult(Generic[T]):
    """
    Generic result wrapper for service operations.

    Provides a consistent way to return operation results
    with success/failure status and optional data.
    """
    success: bool
    message: str
    data: Optional[T] = None
    error_code: Optional[str] = None

    @classmethod
    def ok(cls, data: T = None, message: str = "Success") -> 'ServiceResult[T]':
        """Create a successful result."""
        return cls(success=True, message=message, data=data)

    @classmethod
    def fail(cls, message: str, error_code: str = None) -> 'ServiceResult[T]':
        """Create a failure result."""
        return cls(success=False, message=message, error_code=error_code)

    def to_api_response(self) -> APIResponse:
        """Convert to APIResponse for HTTP responses."""
        return APIResponse(
            success=self.success,
            message=self.message,
            data=self.data,
            errors=[self.error_code] if self.error_code else None
        )


class ServiceError(Exception):
    """Base exception for service layer errors."""

    def __init__(self, message: str, error_code: str = None):
        super().__init__(message)
        self.message = message
        self.error_code = error_code


class ValidationError(ServiceError):
    """Raised when input validation fails."""
    pass


class NotFoundError(ServiceError):
    """Raised when a requested entity is not found."""
    pass


class AuthorizationError(ServiceError):
    """Raised when user is not authorized for an operation."""
    pass


class ConflictError(ServiceError):
    """Raised when operation conflicts with current state."""
    pass


class BaseService(ABC):
    """
    Abstract base service with common functionality.

    All domain services should inherit from this class to get:
    - Session management
    - Operation tracing
    - Consistent error handling
    - Metrics hooks

    Example:
        class UserService(BaseService):
            def __init__(self, session: Session, user_repo: UserRepository):
                super().__init__(session)
                self.user_repo = user_repo

            def get_user(self, user_id: int) -> ServiceResult[User]:
                user = self.user_repo.get_by_id(user_id)
                if not user:
                    return ServiceResult.fail("User not found", "USER_NOT_FOUND")
                return ServiceResult.ok(user)
    """

    def __init__(self, session: Session):
        """
        Initialize service with database session.

        Args:
            session: SQLAlchemy session for database operations
        """
        self.session = session
        self._operation_id: Optional[str] = None
        self._trace_id: Optional[str] = None
        self._started_at: Optional[datetime] = None

        # Metrics counters
        self._operations_count = 0
        self._errors_count = 0

    # ==================== Context Management ====================

    def set_operation_context(
        self,
        operation_id: Optional[str] = None,
        trace_id: Optional[str] = None
    ) -> 'BaseService':
        """
        Set operation context for tracing and idempotency.

        Args:
            operation_id: Unique ID for this operation (for idempotency)
            trace_id: Trace ID for distributed tracing

        Returns:
            Self for method chaining
        """
        self._operation_id = operation_id or str(uuid.uuid4())
        self._trace_id = trace_id or str(uuid.uuid4())
        self._started_at = datetime.utcnow()
        return self

    @property
    def operation_id(self) -> str:
        """Get current operation ID, generating one if not set."""
        if not self._operation_id:
            self._operation_id = str(uuid.uuid4())
        return self._operation_id

    @property
    def trace_id(self) -> str:
        """Get current trace ID, generating one if not set."""
        if not self._trace_id:
            self._trace_id = str(uuid.uuid4())
        return self._trace_id

    # ==================== Logging Helpers ====================

    def _log_operation_start(self, operation: str, **context):
        """Log the start of an operation with context."""
        self._operations_count += 1
        logger.info(
            f"[{self.__class__.__name__}] Starting {operation}",
            extra={
                'operation_id': self.operation_id,
                'trace_id': self.trace_id,
                **context
            }
        )

    def _log_operation_success(self, operation: str, **context):
        """Log successful operation completion."""
        duration = None
        if self._started_at:
            duration = (datetime.utcnow() - self._started_at).total_seconds()
        logger.info(
            f"[{self.__class__.__name__}] Completed {operation}",
            extra={
                'operation_id': self.operation_id,
                'trace_id': self.trace_id,
                'duration_seconds': duration,
                **context
            }
        )

    def _log_operation_error(self, operation: str, error: Exception, **context):
        """Log operation error."""
        self._errors_count += 1
        duration = None
        if self._started_at:
            duration = (datetime.utcnow() - self._started_at).total_seconds()
        logger.error(
            f"[{self.__class__.__name__}] Failed {operation}: {str(error)}",
            extra={
                'operation_id': self.operation_id,
                'trace_id': self.trace_id,
                'duration_seconds': duration,
                'error_type': type(error).__name__,
                **context
            },
            exc_info=True
        )

    # ==================== Validation Helpers ====================

    def _validate_required(self, value: Any, field_name: str) -> None:
        """Raise ValidationError if value is None or empty."""
        if value is None or (isinstance(value, str) and not value.strip()):
            raise ValidationError(f"{field_name} is required", f"MISSING_{field_name.upper()}")

    def _validate_positive_int(self, value: Any, field_name: str) -> int:
        """Validate and return a positive integer."""
        try:
            int_value = int(value)
            if int_value <= 0:
                raise ValidationError(
                    f"{field_name} must be a positive integer",
                    f"INVALID_{field_name.upper()}"
                )
            return int_value
        except (TypeError, ValueError):
            raise ValidationError(
                f"{field_name} must be a valid integer",
                f"INVALID_{field_name.upper()}"
            )

    # ==================== Transaction Helpers ====================

    def _commit(self) -> None:
        """Commit current transaction."""
        self.session.commit()

    def _rollback(self) -> None:
        """Rollback current transaction."""
        self.session.rollback()

    def _flush(self) -> None:
        """Flush pending changes without committing."""
        self.session.flush()
