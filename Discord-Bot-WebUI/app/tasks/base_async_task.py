"""
Base Async Task Pattern

This module provides a standardized pattern for Celery tasks that need to perform
async operations (like HTTP requests) while properly managing database sessions.

The pattern separates database operations from async operations to prevent 
idle transaction timeouts and connection leaks.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
import asyncio

logger = logging.getLogger(__name__)


class BaseAsyncTask(ABC):
    """
    Base class for async Celery tasks that separates database operations from async operations.
    
    Usage:
        @celery_task(name='my_task')
        def my_task_wrapper(self, session, arg1, arg2):
            task = MyAsyncTask()
            return task.execute(session, arg1, arg2)
        
        class MyAsyncTask(BaseAsyncTask):
            def _extract_data(self, session, arg1, arg2):
                # Quick database queries here
                return {'data': 'from_db'}
            
            async def _execute_async(self, data):
                # HTTP requests and async operations here
                return {'success': True}
    """
    
    def execute(self, session, *args, **kwargs) -> Dict[str, Any]:
        """
        Execute the task using the two-phase pattern.
        
        Args:
            session: Database session for data extraction
            *args, **kwargs: Task arguments
            
        Returns:
            Task result dictionary
        """
        try:
            # Phase 1: Extract data with database session
            data = self._extract_data(session, *args, **kwargs)
            
            # Phase 2: Session is closed by decorator, run async operations
            result = asyncio.run(self._execute_async(data))
            
            return result
            
        except Exception as e:
            logger.error(f"Error in {self.__class__.__name__}: {e}", exc_info=True)
            return {'success': False, 'error': str(e)}
    
    @abstractmethod
    def _extract_data(self, session, *args, **kwargs) -> Dict[str, Any]:
        """
        Extract all required data from the database.
        
        This method should perform all database queries quickly and return
        all data needed for the async execution phase.
        
        Args:
            session: Database session
            *args, **kwargs: Task arguments
            
        Returns:
            Dictionary containing all data needed for async execution
        """
        pass
    
    @abstractmethod
    async def _execute_async(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute async operations without database session.
        
        This method performs HTTP requests, async operations, and sleeps
        without holding any database connections.
        
        Args:
            data: Data extracted from the database
            
        Returns:
            Task result dictionary with success status
        """
        pass


def async_celery_task(extract_data_func, execute_async_func):
    """
    Decorator factory for creating async Celery tasks using the two-phase pattern.
    
    Usage:
        @async_celery_task(extract_data_func=extract_player_data, 
                          execute_async_func=update_discord_roles_async)
        @celery_task(name='update_player_roles')
        def update_player_roles_task(self, session, player_id):
            pass  # Implementation handled by decorator
            
        def extract_player_data(session, player_id):
            # Quick DB queries
            return {'player_data': {...}}
            
        async def update_discord_roles_async(data):
            # HTTP operations
            return {'success': True}
    """
    def decorator(func):
        # Attach the functions to the task function
        func._extract_data = staticmethod(extract_data_func)
        func._execute_async = staticmethod(execute_async_func)
        return func
    return decorator


class AsyncTaskMixin:
    """
    Mixin to add async task functionality to existing Celery task functions.
    
    Usage:
        @celery_task(name='my_task')
        def my_task(self, session, *args, **kwargs):
            return AsyncTaskMixin.execute_two_phase(
                session, args, kwargs,
                extract_func=extract_my_data,
                async_func=execute_my_async_operations
            )
    """
    
    @staticmethod
    def execute_two_phase(session, args, kwargs, extract_func, async_func):
        """
        Execute a task using the two-phase pattern.
        
        Args:
            session: Database session
            args, kwargs: Task arguments
            extract_func: Function to extract data from database
            async_func: Async function to execute operations
            
        Returns:
            Task result
        """
        try:
            # Phase 1: Extract data
            data = extract_func(session, *args, **kwargs)
            
            # Phase 2: Run async operations (session closed by decorator)
            result = asyncio.run(async_func(data))
            
            return result
            
        except Exception as e:
            logger.error(f"Error in two-phase execution: {e}", exc_info=True)
            return {'success': False, 'error': str(e)}