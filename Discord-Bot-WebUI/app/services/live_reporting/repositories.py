# app/services/live_reporting/repositories.py

"""
Live Reporting Repositories

Industry standard repository pattern with async database operations,
connection pooling, and proper error handling.
"""

import logging
import json
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
import asyncio

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload
from sqlalchemy import select, update, and_, or_
from sqlalchemy.exc import SQLAlchemyError, IntegrityError

from app.models import MLSMatch, LiveReportingSession
from .config import LiveReportingConfig, MatchEventContext

logger = logging.getLogger(__name__)


class DatabaseError(Exception):
    """Custom exception for database operations."""
    pass


class AsyncDatabaseRepository:
    """
    Async database repository with connection pooling.
    
    Implements industry standard patterns:
    - Async/await throughout
    - Connection pooling
    - Proper error handling
    - Context managers for transactions
    - Type hints and logging
    """
    
    def __init__(self, config: LiveReportingConfig):
        self.config = config
        self._engine = None
        self._session_factory = None
        self._setup_engine()
    
    def _setup_engine(self):
        """Setup async database engine with connection pooling."""
        self._engine = create_async_engine(
            self.config.database_url,
            pool_size=self.config.database_pool_size,
            max_overflow=self.config.database_max_overflow,
            pool_timeout=self.config.database_pool_timeout,
            pool_pre_ping=True,
            pool_recycle=3600,  # Recycle connections after 1 hour
            echo=self.config.log_level == 'DEBUG'
        )
        
        self._session_factory = async_sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
    
    @asynccontextmanager
    async def session(self):
        """
        Async context manager for database sessions.
        
        Provides automatic transaction management with proper
        error handling and cleanup.
        """
        session = self._session_factory()
        try:
            yield session
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error(f"Database error: {e}", exc_info=True)
            raise DatabaseError(f"Database operation failed: {e}") from e
        finally:
            await session.close()
    
    async def close(self):
        """Close database connections."""
        if self._engine:
            await self._engine.dispose()
    
    async def health_check(self) -> bool:
        """
        Check database connectivity.
        
        Returns:
            bool: True if database is accessible, False otherwise
        """
        try:
            async with self.session() as session:
                await session.execute(select(1))
            return True
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False


class MatchRepository(AsyncDatabaseRepository):
    """Repository for match-related database operations."""
    
    async def get_match(self, match_id: str) -> Optional[MLSMatch]:
        """
        Get match by ID.
        
        Args:
            match_id: ESPN match ID
            
        Returns:
            MLSMatch or None if not found
        """
        try:
            async with self.session() as session:
                stmt = select(MLSMatch).where(MLSMatch.match_id == match_id)
                result = await session.execute(stmt)
                return result.scalar_one_or_none()
        except SQLAlchemyError as e:
            logger.error(f"Error getting match {match_id}: {e}")
            return None
    
    async def create_match(self, context: MatchEventContext, **kwargs) -> MLSMatch:
        """
        Create a new match record.
        
        Args:
            context: Match event context
            **kwargs: Additional match data
            
        Returns:
            Created MLSMatch instance
        """
        try:
            async with self.session() as session:
                match = MLSMatch(
                    match_id=context.match_id,
                    competition=context.competition,
                    opponent=f"{context.home_team or 'Unknown'} vs {context.away_team or 'Unknown'}",
                    date_time=datetime.utcnow(),
                    is_home_game=False,  # Will be determined from ESPN data
                    venue=context.venue or 'Unknown Venue',
                    discord_thread_id=context.thread_id,
                    thread_created=context.thread_id is not None,
                    live_reporting_scheduled=False,
                    **kwargs
                )
                
                session.add(match)
                await session.flush()
                await session.refresh(match)
                return match
        except IntegrityError:
            logger.warning(f"Match {context.match_id} already exists")
            return await self.get_match(context.match_id)
        except SQLAlchemyError as e:
            logger.error(f"Error creating match {context.match_id}: {e}")
            raise DatabaseError(f"Failed to create match: {e}")
    
    async def update_match_thread(self, match_id: str, thread_id: str) -> bool:
        """
        Update match Discord thread ID.
        
        Args:
            match_id: ESPN match ID
            thread_id: Discord thread ID
            
        Returns:
            bool: True if updated successfully
        """
        try:
            async with self.session() as session:
                stmt = (
                    update(MLSMatch)
                    .where(MLSMatch.match_id == match_id)
                    .values(
                        discord_thread_id=thread_id,
                        thread_created=True
                    )
                )
                result = await session.execute(stmt)
                return result.rowcount > 0
        except SQLAlchemyError as e:
            logger.error(f"Error updating match thread {match_id}: {e}")
            return False


class LiveReportingRepository(AsyncDatabaseRepository):
    """Repository for live reporting session operations."""
    
    async def get_active_sessions(self) -> List[LiveReportingSession]:
        """
        Get all active live reporting sessions.
        
        Returns:
            List of active LiveReportingSession instances
        """
        try:
            async with self.session() as session:
                stmt = (
                    select(LiveReportingSession)
                    .where(LiveReportingSession.is_active == True)
                    .order_by(LiveReportingSession.started_at)
                )
                result = await session.execute(stmt)
                return list(result.scalars().all())
        except SQLAlchemyError as e:
            logger.error(f"Error getting active sessions: {e}")
            return []
    
    async def get_session(self, match_id: str) -> Optional[LiveReportingSession]:
        """
        Get live reporting session by match ID.
        
        Args:
            match_id: ESPN match ID
            
        Returns:
            LiveReportingSession or None if not found
        """
        try:
            async with self.session() as session:
                stmt = select(LiveReportingSession).where(
                    LiveReportingSession.match_id == match_id
                )
                result = await session.execute(stmt)
                return result.scalar_one_or_none()
        except SQLAlchemyError as e:
            logger.error(f"Error getting session {match_id}: {e}")
            return None
    
    async def create_session(self, context: MatchEventContext) -> LiveReportingSession:
        """
        Create a new live reporting session.
        
        Args:
            context: Match event context
            
        Returns:
            Created LiveReportingSession instance
        """
        try:
            async with self.session() as session:
                live_session = LiveReportingSession(
                    match_id=context.match_id,
                    competition=context.competition,
                    thread_id=context.thread_id,
                    is_active=True,
                    started_at=datetime.utcnow(),
                    last_status=context.current_status,
                    last_score=context.current_score or "0-0",
                    last_event_keys=json.dumps(context.last_event_keys or []),
                    update_count=0,
                    error_count=0
                )
                
                session.add(live_session)
                await session.flush()
                await session.refresh(live_session)
                return live_session
        except IntegrityError:
            logger.warning(f"Session for match {context.match_id} already exists")
            return await self.get_session(context.match_id)
        except SQLAlchemyError as e:
            logger.error(f"Error creating session {context.match_id}: {e}")
            raise DatabaseError(f"Failed to create session: {e}")
    
    async def update_session(
        self,
        match_id: str,
        status: Optional[str] = None,
        score: Optional[str] = None,
        event_keys: Optional[List[str]] = None,
        increment_updates: bool = True,
        error_message: Optional[str] = None,
        is_active: Optional[bool] = None
    ) -> bool:
        """
        Update live reporting session.
        
        Args:
            match_id: ESPN match ID
            status: New match status
            score: New match score
            event_keys: New event keys
            increment_updates: Whether to increment update count
            error_message: Error message if any
            is_active: Whether session is active
            
        Returns:
            bool: True if updated successfully
        """
        try:
            async with self.session() as session:
                update_values = {
                    'last_update': datetime.utcnow()
                }
                
                if status is not None:
                    update_values['last_status'] = status
                if score is not None:
                    update_values['last_score'] = score
                if event_keys is not None:
                    update_values['last_event_keys'] = json.dumps(event_keys) if isinstance(event_keys, list) else event_keys
                if increment_updates:
                    update_values['update_count'] = LiveReportingSession.update_count + 1
                if error_message:
                    update_values['last_error'] = error_message
                    update_values['error_count'] = LiveReportingSession.error_count + 1
                if is_active is not None:
                    update_values['is_active'] = is_active
                
                stmt = (
                    update(LiveReportingSession)
                    .where(LiveReportingSession.match_id == match_id)
                    .values(**update_values)
                )
                result = await session.execute(stmt)
                return result.rowcount > 0
        except SQLAlchemyError as e:
            logger.error(f"Error updating session {match_id}: {e}")
            return False
    
    async def deactivate_session(self, match_id: str, reason: str = "") -> bool:
        """
        Deactivate live reporting session.
        
        Args:
            match_id: ESPN match ID
            reason: Reason for deactivation
            
        Returns:
            bool: True if deactivated successfully
        """
        try:
            async with self.session() as session:
                stmt = (
                    update(LiveReportingSession)
                    .where(LiveReportingSession.match_id == match_id)
                    .values(
                        is_active=False,
                        ended_at=datetime.utcnow(),
                        last_error=reason
                    )
                )
                result = await session.execute(stmt)
                return result.rowcount > 0
        except SQLAlchemyError as e:
            logger.error(f"Error deactivating session {match_id}: {e}")
            return False
    
    async def cleanup_old_sessions(self, older_than_hours: int = 24) -> int:
        """
        Cleanup old inactive sessions.
        
        Args:
            older_than_hours: Sessions older than this will be deleted
            
        Returns:
            int: Number of sessions cleaned up
        """
        try:
            cutoff_time = datetime.utcnow() - timedelta(hours=older_than_hours)
            
            async with self.session() as session:
                stmt = select(LiveReportingSession).where(
                    and_(
                        LiveReportingSession.is_active == False,
                        LiveReportingSession.ended_at < cutoff_time
                    )
                )
                result = await session.execute(stmt)
                sessions_to_delete = list(result.scalars().all())
                
                for session_obj in sessions_to_delete:
                    await session.delete(session_obj)
                
                return len(sessions_to_delete)
        except SQLAlchemyError as e:
            logger.error(f"Error cleaning up old sessions: {e}")
            return 0