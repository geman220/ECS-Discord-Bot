# app/utils/query_helpers.py

from sqlalchemy import func
from contextlib import contextmanager
import logging

logger = logging.getLogger(__name__)

class QueryHelper:
    def __init__(self, db_manager):
        self.db_manager = db_manager

    def get_player_count(self, filters=None):
        """Safe method to get player count"""
        with self.db_manager.session_scope() as session:
            try:
                query = session.query(Player)
                if filters:
                    query = query.filter(*filters)
                    
                # Use a subquery to optimize the count
                subquery = query.statement.with_only_columns([Player.id]).order_by(None).subquery()
                count_stmt = select([func.count()]).select_from(subquery)
                
                result = self.db_manager.execute_with_retry(session, count_stmt)
                return result.scalar()
                
            except Exception as e:
                logger.error(f"Error getting player count: {e}")
                raise

    def get_connection_stats(self):
        """Safe method to get connection statistics"""
        with self.db_manager.session_scope() as session:
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
                
                result = self.db_manager.execute_with_retry(session, stats_query)
                return result.fetchall()
                
            except Exception as e:
                logger.error(f"Error getting connection stats: {e}")
                raise

    @contextmanager
    def transaction_scope(self):
        """Scope for ensuring transactions are properly handled"""
        with self.db_manager.session_scope() as session:
            try:
                yield session
                if session.in_transaction():
                    session.commit()
            except Exception:
                if session.in_transaction():
                    session.rollback()
                raise