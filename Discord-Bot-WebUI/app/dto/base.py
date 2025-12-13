# app/dto/base.py

"""
Base Data Transfer Object classes.

Provides foundational DTO classes with serialization support
for consistent API responses and data transfer between layers.
"""

from dataclasses import dataclass, asdict, field
from datetime import datetime, date
from typing import Any, Dict, List, Optional, TypeVar, Generic
from enum import Enum
import json


T = TypeVar('T')


def serialize_value(value: Any) -> Any:
    """Serialize a value to JSON-compatible format."""
    if isinstance(value, datetime):
        return value.isoformat()
    elif isinstance(value, date):
        return value.isoformat()
    elif isinstance(value, Enum):
        return value.value
    elif hasattr(value, 'to_dict'):
        return value.to_dict()
    elif isinstance(value, list):
        return [serialize_value(item) for item in value]
    elif isinstance(value, dict):
        return {k: serialize_value(v) for k, v in value.items()}
    return value


@dataclass
class BaseDTO:
    """
    Base Data Transfer Object with serialization support.

    All DTOs should inherit from this class to get consistent
    serialization behavior and utility methods.
    """

    def to_dict(self) -> Dict[str, Any]:
        """Convert DTO to dictionary with proper serialization."""
        data = asdict(self)
        return {k: serialize_value(v) for k, v in data.items()}

    def to_json(self) -> str:
        """Convert DTO to JSON string."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'BaseDTO':
        """Create DTO instance from dictionary."""
        return cls(**data)


@dataclass
class APIResponse(BaseDTO):
    """
    Standard API response format.

    Provides consistent structure for all API responses:
    - success: Whether the operation succeeded
    - message: Human-readable message
    - data: Optional payload data
    - errors: Optional list of error details
    """
    success: bool
    message: str
    data: Optional[Any] = None
    errors: Optional[List[str]] = None

    @classmethod
    def ok(cls, message: str = "Success", data: Any = None) -> 'APIResponse':
        """Create a successful response."""
        return cls(success=True, message=message, data=data)

    @classmethod
    def error(cls, message: str, errors: Optional[List[str]] = None) -> 'APIResponse':
        """Create an error response."""
        return cls(success=False, message=message, errors=errors)


@dataclass
class PaginatedResponse(BaseDTO, Generic[T]):
    """
    Paginated response for list endpoints.

    Provides standard pagination metadata alongside data.
    """
    items: List[Any]
    total: int
    page: int
    per_page: int
    pages: int
    has_next: bool
    has_prev: bool

    @classmethod
    def create(
        cls,
        items: List[Any],
        total: int,
        page: int,
        per_page: int
    ) -> 'PaginatedResponse':
        """Create a paginated response with calculated metadata."""
        pages = (total + per_page - 1) // per_page if per_page > 0 else 0
        return cls(
            items=items,
            total=total,
            page=page,
            per_page=per_page,
            pages=pages,
            has_next=page < pages,
            has_prev=page > 1
        )


@dataclass
class ErrorResponse(BaseDTO):
    """
    Detailed error response for API errors.

    Provides structured error information including:
    - error_code: Machine-readable error code
    - message: Human-readable message
    - details: Optional additional error details
    - trace_id: Optional trace ID for debugging
    """
    error_code: str
    message: str
    details: Optional[Dict[str, Any]] = None
    trace_id: Optional[str] = None

    def to_response(self, status_code: int = 400):
        """Convert to Flask jsonify response tuple."""
        from flask import jsonify
        return jsonify(self.to_dict()), status_code
