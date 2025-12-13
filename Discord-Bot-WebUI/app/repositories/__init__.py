# app/repositories/__init__.py

"""
Repository Layer for Data Access.

Repositories provide a clean abstraction over database operations,
separating data access logic from business logic in services.
"""

from app.repositories.base import BaseRepository

__all__ = [
    'BaseRepository',
]
