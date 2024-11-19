# app/database/db_models.py

from app.core import db
from sqlalchemy.dialects.postgresql import JSONB

class DBMonitoringSnapshot(db.Model):
    __tablename__ = 'db_monitoring_snapshots'

    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, nullable=False, index=True)
    pool_stats = db.Column(JSONB)
    active_connections = db.Column(JSONB)
    long_running_transactions = db.Column(JSONB)
    recent_events = db.Column(JSONB)
    session_monitor = db.Column(JSONB)