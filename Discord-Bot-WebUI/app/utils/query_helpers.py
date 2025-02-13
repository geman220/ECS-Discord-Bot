# app/utils/query_helpers.py

"""
Query Helpers Module

This module provides helper methods for executing common database queries safely
within a Flask request context using the session stored in g.db_session.
It includes methods to count Player records and to fetch database connection statistics.
"""

import logging
from sqlalchemy import func, text, select
from flask import g
from app.models import Player

logger = logging.getLogger(__name__)


class QueryHelper:
    def __init__(self):
        # Initialization placeholder; db_manager is no longer used as we rely on g.db_session.
        pass

    def get_player_count(self, filters=None) -> int:
        """
        Safely get the count of Player records using g.db_session.

        Optionally applies filters to the query. Uses a subquery to optimize the count operation.

        Args:
            filters: Optional list of filter expressions to apply to the query.

        Returns:
            The total count of Player records matching the filters.

        Raises:
            RuntimeError: If no database session is available.
            Exception: Propagates any exceptions encountered during query execution.
        """
        # Retrieve the current session from the Flask request context.
        session = getattr(g, 'db_session', None)
        if session is None:
            raise RuntimeError("No database session available in request context.")

        try:
            query = session.query(Player)
            if filters:
                query = query.filter(*filters)
            
            # Create a subquery selecting only the Player IDs to optimize counting.
            subquery = query.statement.with_only_columns([Player.id]).order_by(None).subquery()
            count_stmt = select(func.count()).select_from(subquery)
        
            result = session.execute(count_stmt)
            return result.scalar()
        except Exception as e:
            logger.error(f"Error getting player count: {e}", exc_info=True)
            raise

    def get_connection_stats(self) -> list:
        """
        Safely get database connection statistics using g.db_session.

        Executes a raw SQL query on PostgreSQL's pg_stat_activity to fetch connection state,
        count, and duration metrics for the current database.

        Returns:
            A list of dictionaries, each representing a row of connection statistics.

        Raises:
            RuntimeError: If no database session is available.
            Exception: Propagates any exceptions encountered during query execution.
        """
        # Retrieve the current session from the Flask request context.
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
            # Return all rows as a list of dictionaries.
            return result.fetchall()
        except Exception as e:
            logger.error(f"Error getting connection stats: {e}", exc_info=True)
            raise