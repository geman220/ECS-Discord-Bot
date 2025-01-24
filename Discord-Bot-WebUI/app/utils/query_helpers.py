# app/utils/query_helpers.py

from sqlalchemy import func, text, select
from contextlib import contextmanager
from flask import g
from app.models import Player
import logging

logger = logging.getLogger(__name__)

class QueryHelper:
    def __init__(self):
        # Removed db_manager as we now rely on g.db_session
        pass

    def get_player_count(self, filters=None):
        """Safe method to get player count using g.db_session."""
        session = getattr(g, 'db_session', None)
        if session is None:
            raise RuntimeError("No database session available in request context.")

        try:
            query = session.query(Player)
            if filters:
                query = query.filter(*filters)
            
            # Use a subquery to optimize the count
            subquery = query.statement.with_only_columns([Player.id]).order_by(None).subquery()
            count_stmt = select(func.count()).select_from(subquery)
        
            result = session.execute(count_stmt)
            return result.scalar()
        except Exception as e:
            logger.error(f"Error getting player count: {e}", exc_info=True)
            raise

    def get_connection_stats(self):
        """Safe method to get connection statistics using g.db_session."""
        session = getattr(g, 'db_session', None)
        if session is None:
            raise RuntimeError("No database session available in request context.")

        try:
            stats_query = text("""
                SELECT 
                    COALESCE(state, 'unknown') as state,
                    count(*) as count,
                    COALESCE(
                        EXTRACT(epoch FROM (now() - state_change)),
                        0
                    ) as duration
                FROM pg_stat_activity 
                WHERE datname = current_database()
                GROUP BY state
            """)
            result = session.execute(stats_query)
            return result.fetchall()
        except Exception as e:
            logger.error(f"Error getting connection stats: {e}", exc_info=True)
            raise