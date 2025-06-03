# app/utils/task_session_manager.py

"""
Task Session Manager Module

This module provides comprehensive utilities for standardizing session handling in Celery tasks.
It includes decorators, context managers, and function wrappers that ensure database sessions are
properly created, committed/rolled back, and closed in all code paths for both synchronous and
asynchronous tasks.
"""

import logging
import asyncio
import functools
import inspect
from contextlib import contextmanager, asynccontextmanager
from typing import Callable, Any, Optional, TypeVar, Union, Dict

from flask import current_app
from sqlalchemy.exc import SQLAlchemyError
from app.core import celery

logger = logging.getLogger(__name__)

# Type variables for better type hinting
F = TypeVar('F', bound=Callable[..., Any])
AsyncF = TypeVar('AsyncF', bound=Callable[..., Any])


@contextmanager
def task_session():
    """
    Context manager that provides a database session for synchronous task execution.
    
    The context manager creates a new database session, yields it, and ensures proper
    commit/rollback and closure upon exit regardless of whether an exception occurred.
    
    Yields:
        SQLAlchemy session: A database session for use within the context.
        
    Example:
        with task_session() as session:
            # Use session for database operations
            results = session.query(MyModel).all()
    """
    app = current_app._get_current_object()
    session = app.SessionLocal()
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"Error in task_session: {str(e)}", exc_info=True)
        raise
    finally:
        session.close()


@asynccontextmanager
async def async_task_session():
    """
    Asynchronous context manager that provides a database session for async task execution.
    
    Creates a new database session, yields it, and ensures proper commit/rollback
    and closure upon exit regardless of whether an exception occurred.
    
    Yields:
        SQLAlchemy session: A database session for use within the async context.
        
    Example:
        async with async_task_session() as session:
            # Use session for database operations
            results = session.query(MyModel).all()
    """
    app = current_app._get_current_object()
    session = app.SessionLocal()
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"Error in async_task_session: {str(e)}", exc_info=True)
        raise
    finally:
        session.close()


def with_task_session(func: F) -> F:
    """
    Decorator for synchronous functions that provides a database session as the first argument.
    
    This decorator creates a session, passes it to the decorated function, and handles
    commit/rollback and closure automatically.
    
    Args:
        func: The function to decorate.
        
    Returns:
        The decorated function.
        
    Example:
        @with_task_session
        def process_data(session, data_id):
            # Use session for database operations
            item = session.query(Item).get(data_id)
            return item
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with task_session() as session:
            return func(session, *args, **kwargs)
    return wrapper


def with_async_task_session(func: AsyncF) -> AsyncF:
    """
    Decorator for asynchronous functions that provides a database session as the first argument.
    
    This decorator creates a session, passes it to the decorated async function, and handles
    commit/rollback and closure automatically.
    
    Args:
        func: The async function to decorate.
        
    Returns:
        The decorated async function.
        
    Example:
        @with_async_task_session
        async def fetch_data(session, data_id):
            # Use session for async database operations
            item = session.query(Item).get(data_id)
            return item
    """
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        async with async_task_session() as session:
            return await func(session, *args, **kwargs)
    return wrapper


def task_with_session(**task_kwargs):
    """
    Decorator that registers a function as a Celery task with standardized session handling.
    
    This decorator wraps a function in a Celery task, automatically managing a database session
    for the task's execution. It handles both synchronous and asynchronous functions.
    
    Args:
        **task_kwargs: Keyword arguments to pass to celery.task.
        
    Returns:
        A decorator function that creates a Celery task with session handling.
        
    Example:
        @task_with_session(name='app.tasks.process_data', bind=True)
        def process_data(self, session, data_id):
            # Task implementation using the session
            item = session.query(Item).get(data_id)
            return item
    """
    def decorator(func):
        # Determine if the function is async
        is_async = asyncio.iscoroutinefunction(func)
        
        # Get the task name from kwargs or generate a default one
        task_name = task_kwargs.pop('name', None) or f'app.tasks.{func.__module__}.{func.__name__}'
        
        # Ensure bind=True is included in task_kwargs
        task_kwargs['bind'] = True
        
        @celery.task(name=task_name, **task_kwargs)
        @functools.wraps(func)
        def wrapped_task(self, *args, **kwargs):
            app = celery.flask_app
            with app.app_context():
                session = app.SessionLocal()
                task_id = self.request.id
                
                try:
                    logger.debug(f"Starting task {task_name} (ID: {task_id})")
                    
                    # Handle async functions
                    if is_async:
                        from app.api_utils import async_to_sync
                        result = async_to_sync(func(self, session, *args, **kwargs))
                    else:
                        result = func(self, session, *args, **kwargs)
                    
                    # Commit changes if successful
                    session.commit()
                    logger.debug(f"Task {task_name} (ID: {task_id}) completed successfully")
                    return result
                    
                except SQLAlchemyError as e:
                    # Log detailed information for database errors
                    session.rollback()
                    logger.error(
                        f"Database error in task {task_name} (ID: {task_id}): {str(e)}",
                        exc_info=True
                    )
                    raise self.retry(exc=e, countdown=60, max_retries=3)
                    
                except Exception as e:
                    # Handle other exceptions
                    session.rollback()
                    logger.error(
                        f"Error in task {task_name} (ID: {task_id}): {str(e)}",
                        exc_info=True
                    )
                    raise
                    
                finally:
                    # Always close the session
                    session.close()
                    
        return wrapped_task
    return decorator


def async_task_with_session(**task_kwargs):
    """
    Decorator that registers an async function as a Celery task with standardized session handling.
    
    This decorator is a specialized version of task_with_session for async functions, providing
    cleaner syntax for defining async Celery tasks.
    
    Args:
        **task_kwargs: Keyword arguments to pass to celery.task.
        
    Returns:
        A decorator function that creates a Celery task from an async function.
        
    Example:
        @async_task_with_session(name='app.tasks.fetch_data')
        async def fetch_data(self, session, user_id):
            # Async task implementation using the session
            user = session.query(User).get(user_id)
            return user
    """
    def decorator(func):
        # Validate that the function is async
        if not asyncio.iscoroutinefunction(func):
            raise ValueError(f"Function {func.__name__} must be async to use async_task_with_session")
        
        # Use the regular task decorator for implementation
        return task_with_session(**task_kwargs)(func)
    
    return decorator


def retry_task_with_session(max_retries=3, retry_backoff=True, **task_kwargs):
    """
    Decorator for Celery tasks with retry capability and session handling.
    
    This decorator creates a Celery task with built-in retry logic, automatically handling
    database sessions for each task attempt.
    
    Args:
        max_retries: Maximum number of retry attempts (default: 3)
        retry_backoff: Whether to use exponential backoff for retries (default: True)
        **task_kwargs: Additional keyword arguments to pass to celery.task
        
    Returns:
        A decorator function that creates a retryable Celery task.
        
    Example:
        @retry_task_with_session(max_retries=5, queue='high_priority')
        def process_payment(self, session, payment_id):
            # Task implementation with automatic retry capability
            payment = session.query(Payment).get(payment_id)
            payment.process()
            return {"status": "completed"}
    """
    # Update task_kwargs with retry settings
    task_kwargs.update({
        'max_retries': max_retries,
        'retry_backoff': retry_backoff
    })
    
    # Use the regular task decorator with the updated settings
    return task_with_session(**task_kwargs)


def batch_task_with_session(chunk_size=100, **task_kwargs):
    """
    Decorator for Celery tasks that process data in batches with session handling.
    
    This decorator creates a Celery task that automatically processes a large dataset
    in smaller batches, with proper session management for each batch.
    
    Args:
        chunk_size: Number of items to process in each batch (default: 100)
        **task_kwargs: Additional keyword arguments to pass to celery.task
        
    Returns:
        A decorator function that creates a batched Celery task.
        
    Example:
        @batch_task_with_session(chunk_size=50, name='app.tasks.process_users')
        def process_users(self, session, user_ids):
            # This function will be called with smaller batches of user_ids
            for user_id in user_ids:
                user = session.query(User).get(user_id)
                # Process user
            return len(user_ids)
    """
    def decorator(func):
        @task_with_session(**task_kwargs)
        def wrapped_task(self, session, items, *args, **kwargs):
            if not items:
                return {"processed": 0, "message": "No items to process"}
            
            total = len(items)
            processed = 0
            results = []
            
            # Process in chunks
            for i in range(0, total, chunk_size):
                chunk = items[i:i+chunk_size]
                try:
                    # Process this chunk
                    result = func(self, session, chunk, *args, **kwargs)
                    results.append(result)
                    processed += len(chunk)
                    
                    # Update task state for progress reporting
                    self.update_state(
                        state='PROGRESS',
                        meta={'current': processed, 'total': total, 'percent': int(processed / total * 100)}
                    )
                    
                    # Commit after each chunk
                    session.commit()
                    
                except Exception as e:
                    # Roll back this chunk but continue with the next
                    session.rollback()
                    logger.error(f"Error processing batch {i//chunk_size + 1}: {str(e)}", exc_info=True)
                    
            return {
                "processed": processed,
                "total": total,
                "results": results
            }
            
        return wrapped_task
    return decorator


# Optional utility functions for direct use

def run_in_session(func: Callable, *args, **kwargs) -> Any:
    """
    Run a function with a database session and handle transaction management.
    
    This utility function is useful for running arbitrary code that needs a database
    session with proper transaction handling, without defining a dedicated task.
    
    Args:
        func: The function to run with a session.
        *args: Positional arguments to pass to the function.
        **kwargs: Keyword arguments to pass to the function.
        
    Returns:
        The result of the function.
        
    Example:
        def update_user(session, user_id, new_name):
            user = session.query(User).get(user_id)
            user.name = new_name
            return user
            
        result = run_in_session(update_user, user_id=123, new_name="New Name")
    """
    with task_session() as session:
        return func(session, *args, **kwargs)


async def run_in_async_session(func: Callable, *args, **kwargs) -> Any:
    """
    Run an async function with a database session and handle transaction management.
    
    This utility function is useful for running arbitrary async code that needs a database
    session with proper transaction handling, without defining a dedicated task.
    
    Args:
        func: The async function to run with a session.
        *args: Positional arguments to pass to the function.
        **kwargs: Keyword arguments to pass to the function.
        
    Returns:
        The result of the async function.
        
    Example:
        async def fetch_user_data(session, user_id):
            user = session.query(User).get(user_id)
            data = await external_api.get_user_details(user.external_id)
            return data
            
        result = await run_in_async_session(fetch_user_data, user_id=123)
    """
    async with async_task_session() as session:
        return await func(session, *args, **kwargs)