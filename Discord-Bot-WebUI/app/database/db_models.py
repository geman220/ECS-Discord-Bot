# app/database/db_models.py

"""
Database Models for Monitoring

This module defines models for storing database monitoring snapshots.
Each snapshot captures various metrics and events in JSONB format for easy querying.
"""

from app.core import db
from sqlalchemy.dialects.postgresql import JSONB

class DBMonitoringSnapshot(db.Model):
    """
    Represents a snapshot of database monitoring metrics.

    This model captures various details such as connection pool statistics,
    active connections, long-running transactions, recent events, and session
    monitoring data, all stored in JSONB format for flexibility.
    """
    __tablename__ = 'db_monitoring_snapshots'

    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, nullable=False, index=True)  # Snapshot creation time
    pool_stats = db.Column(JSONB)             # Database connection pool statistics
    active_connections = db.Column(JSONB)     # Data on current active connections
    long_running_transactions = db.Column(JSONB)  # Information about long-running transactions
    recent_events = db.Column(JSONB)          # Recent events or errors recorded
    session_monitor = db.Column(JSONB)        # Additional session monitoring metrics