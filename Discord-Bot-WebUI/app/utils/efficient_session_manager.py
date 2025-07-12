# app/utils/efficient_session_manager.py

from contextlib import contextmanager
from flask import current_app, g, has_request_context
import logging
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)

@contextmanager
def query_session():
    """
    Create a short-lived session specifically for single queries.
    
    This bypasses the request-scoped session for operations that:
    1. Don't need to be part of the main request transaction
    2. Are heavy/slow and would hold connections too long
    3. Are read-only operations
    
    Usage:
        with query_session() as session:
            user = session.query(User).get(user_id)
            # Session automatically closed after this block
    """
    session = current_app.SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

@contextmanager  
def bulk_operation_session():
    """
    Session for bulk operations that need longer connection time.
    
    Use for:
    - Data imports/exports
    - Batch updates
    - Complex reporting queries
    
    Has longer timeout (30s) but ensures proper cleanup.
    """
    session = current_app.SessionLocal()
    try:
        # Set longer timeout for bulk operations
        session.execute("SET statement_timeout = '30s'")
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

def get_efficient_session():
    """
    Get the most appropriate session for the current context.
    
    Returns:
    - Request session if in request context and operation is part of main transaction
    - New query session if operation should be isolated
    """
    if has_request_context() and hasattr(g, 'db_session'):
        return g.db_session
    else:
        # Return a context manager for auto-cleanup
        return query_session()

class EfficientQuery:
    """
    Helper class for common query patterns with optimal session usage.
    """
    
    @staticmethod
    def get_user_for_auth(user_id):
        """
        Optimized user loading for authentication.
        Uses dedicated session to avoid holding request session.
        """
        with query_session() as session:
            from app.models import User
            from sqlalchemy.orm import selectinload
            
            user = session.query(User).options(
                selectinload(User.roles),
                selectinload(User.player)
            ).get(int(user_id))
            
            if user:
                # Detach from session so it can be used across request
                session.expunge(user)
            return user
    
    @staticmethod
    def get_player_profile(player_id):
        """
        Optimized player profile loading.
        Uses query session for heavy read operation.
        """
        with query_session() as session:
            from app.models import Player
            from sqlalchemy.orm import selectinload
            
            player = session.query(Player).options(
                selectinload(Player.teams),
                selectinload(Player.user),
                selectinload(Player.career_stats),
                selectinload(Player.season_stats),
                selectinload(Player.events)
            ).get(player_id)
            
            if player:
                session.expunge(player)
            return player
    
    @staticmethod 
    def get_match_details(match_id):
        """
        Optimized match loading for reporting.
        """
        with query_session() as session:
            from app.models import Match
            from sqlalchemy.orm import selectinload
            
            match = session.query(Match).options(
                selectinload(Match.home_team),
                selectinload(Match.away_team),
                selectinload(Match.home_verifier),
                selectinload(Match.away_verifier)
            ).get(match_id)
            
            if match:
                session.expunge(match)
            return match