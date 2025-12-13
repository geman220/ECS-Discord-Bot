# app/repositories/base.py

"""
Base Repository for Data Access.

Provides a generic repository pattern implementation with common
CRUD operations and query building utilities.
"""

from abc import ABC
from typing import Generic, TypeVar, List, Optional, Type, Dict, Any, Tuple
from sqlalchemy.orm import Session, Query
from sqlalchemy import and_, or_, desc, asc


T = TypeVar('T')


class BaseRepository(ABC, Generic[T]):
    """
    Generic base repository with common CRUD operations.

    Subclasses should specify the model class and can add
    domain-specific query methods.

    Example:
        class UserRepository(BaseRepository[User]):
            def __init__(self, session: Session):
                super().__init__(session, User)

            def find_by_email(self, email: str) -> Optional[User]:
                return self.find_one_by(email=email)
    """

    def __init__(self, session: Session, model_class: Type[T]):
        """
        Initialize repository with session and model class.

        Args:
            session: SQLAlchemy session for database operations
            model_class: The SQLAlchemy model class this repository manages
        """
        self.session = session
        self.model_class = model_class

    # ==================== Basic CRUD Operations ====================

    def get_by_id(self, id: int) -> Optional[T]:
        """Get entity by primary key ID."""
        return self.session.query(self.model_class).get(id)

    def get_all(self, limit: int = 100, offset: int = 0) -> List[T]:
        """Get all entities with pagination."""
        return (
            self.session.query(self.model_class)
            .offset(offset)
            .limit(limit)
            .all()
        )

    def add(self, entity: T) -> T:
        """Add a new entity to the session."""
        self.session.add(entity)
        return entity

    def add_all(self, entities: List[T]) -> List[T]:
        """Add multiple entities to the session."""
        self.session.add_all(entities)
        return entities

    def delete(self, entity: T) -> None:
        """Delete an entity from the session."""
        self.session.delete(entity)

    def delete_by_id(self, id: int) -> bool:
        """Delete an entity by ID. Returns True if entity was found and deleted."""
        entity = self.get_by_id(id)
        if entity:
            self.delete(entity)
            return True
        return False

    def count(self) -> int:
        """Count total entities."""
        return self.session.query(self.model_class).count()

    def exists(self, id: int) -> bool:
        """Check if entity exists by ID."""
        return self.get_by_id(id) is not None

    # ==================== Query Building ====================

    def find_one_by(self, **kwargs) -> Optional[T]:
        """Find single entity by attribute filters."""
        return self.session.query(self.model_class).filter_by(**kwargs).first()

    def find_all_by(self, **kwargs) -> List[T]:
        """Find all entities matching attribute filters."""
        return self.session.query(self.model_class).filter_by(**kwargs).all()

    def find_by_ids(self, ids: List[int]) -> List[T]:
        """Find all entities matching a list of IDs."""
        if not ids:
            return []
        pk = getattr(self.model_class, 'id', None)
        if pk is None:
            raise ValueError(f"Model {self.model_class.__name__} has no 'id' attribute")
        return self.session.query(self.model_class).filter(pk.in_(ids)).all()

    def query(self) -> Query:
        """Get a base query for the model. Use for complex queries."""
        return self.session.query(self.model_class)

    # ==================== Pagination ====================

    def paginate(
        self,
        page: int = 1,
        per_page: int = 20,
        order_by: Optional[str] = None,
        descending: bool = False,
        filters: Optional[Dict[str, Any]] = None
    ) -> Tuple[List[T], int]:
        """
        Get paginated results with total count.

        Args:
            page: Page number (1-indexed)
            per_page: Items per page
            order_by: Optional column name to order by
            descending: If True, order descending
            filters: Optional dict of filter conditions

        Returns:
            Tuple of (items list, total count)
        """
        query = self.session.query(self.model_class)

        # Apply filters
        if filters:
            query = query.filter_by(**filters)

        # Get total count
        total = query.count()

        # Apply ordering
        if order_by:
            column = getattr(self.model_class, order_by, None)
            if column is not None:
                query = query.order_by(desc(column) if descending else asc(column))

        # Apply pagination
        offset = (page - 1) * per_page
        items = query.offset(offset).limit(per_page).all()

        return items, total

    # ==================== Flush and Refresh ====================

    def flush(self) -> None:
        """Flush pending changes to database without committing."""
        self.session.flush()

    def refresh(self, entity: T) -> T:
        """Refresh entity from database."""
        self.session.refresh(entity)
        return entity

    def expunge(self, entity: T) -> T:
        """Remove entity from session (detach)."""
        self.session.expunge(entity)
        return entity
