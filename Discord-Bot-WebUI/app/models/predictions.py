# app/models/predictions.py

"""
Draft Predictions Models Module

Simplified architecture - predictions link directly to Season + league_type.
No manual setup required - coaches just make predictions for their league.

Models:
- DraftPrediction: Individual draft predictions by coaches
- DraftSeason: DEPRECATED - kept for backward compatibility only
"""

from datetime import datetime
from sqlalchemy import JSON, DateTime, Boolean, Date, Time, String, Text, Integer, ForeignKey, Numeric
from sqlalchemy.orm import relationship

from app.core import db


class DraftPrediction(db.Model):
    """
    Model for individual draft predictions.

    Each coach can predict what round they think each player will be drafted.
    Predictions are tied directly to a Season + league_type (Premier/Classic).
    """
    __tablename__ = 'draft_predictions'

    id = db.Column(db.Integer, primary_key=True)

    # Direct link to season (simplified - no DraftSeason needed)
    season_id = db.Column(db.Integer, db.ForeignKey('season.id'), nullable=True)  # nullable for migration
    league_type = db.Column(db.String(50), nullable=True)  # 'Premier' or 'Classic', nullable for migration

    # Legacy field - kept for backward compatibility with existing data
    draft_season_id = db.Column(db.Integer, db.ForeignKey('draft_seasons.id'), nullable=True)

    # Core prediction data
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False)
    coach_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    predicted_round = db.Column(db.Integer, nullable=False)
    predicted_pick_number = db.Column(db.Integer, nullable=True)  # Optional: specific pick within round
    confidence_level = db.Column(db.Integer, nullable=True)  # 1-5 scale
    notes = db.Column(db.Text, nullable=True)

    # Timestamps for history tracking
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    season = db.relationship('Season', foreign_keys=[season_id], backref='draft_predictions')
    draft_season = db.relationship('DraftSeason', back_populates='predictions')  # Legacy
    coach_user = db.relationship('User', foreign_keys=[coach_user_id], backref='draft_predictions')
    player = db.relationship('Player', foreign_keys=[player_id], backref='draft_predictions')

    __table_args__ = (
        # New constraint for simplified model
        db.UniqueConstraint('season_id', 'league_type', 'player_id', 'coach_user_id',
                           name='uq_draft_prediction_simple'),
        # Legacy constraint - kept for existing data
        db.UniqueConstraint('draft_season_id', 'player_id', 'coach_user_id',
                           name='uq_draft_prediction'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'season_id': self.season_id,
            'league_type': self.league_type,
            'player_id': self.player_id,
            'coach_user_id': self.coach_user_id,
            'predicted_round': self.predicted_round,
            'predicted_pick_number': self.predicted_pick_number,
            'confidence_level': self.confidence_level,
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    @staticmethod
    def get_player_average_prediction(season_id, league_type, player_id, session=None):
        """Get the average predicted round for a player in a season/league."""
        from sqlalchemy import func
        from app.core import db
        from flask import g

        if session:
            query_session = session
        elif hasattr(g, 'db_session'):
            query_session = g.db_session
        else:
            query_session = db.session

        result = query_session.query(func.avg(DraftPrediction.predicted_round)).filter_by(
            season_id=season_id,
            league_type=league_type,
            player_id=player_id
        ).scalar()

        return float(result) if result else None

    @staticmethod
    def get_player_prediction_stats(season_id, league_type, player_id, session=None):
        """Get prediction statistics for a player (avg, min, max, count)."""
        from sqlalchemy import func
        from app.core import db
        from flask import g

        if session:
            query_session = session
        elif hasattr(g, 'db_session'):
            query_session = g.db_session
        else:
            query_session = db.session

        result = query_session.query(
            func.avg(DraftPrediction.predicted_round).label('avg_round'),
            func.min(DraftPrediction.predicted_round).label('min_round'),
            func.max(DraftPrediction.predicted_round).label('max_round'),
            func.count(DraftPrediction.id).label('prediction_count')
        ).filter_by(
            season_id=season_id,
            league_type=league_type,
            player_id=player_id
        ).first()

        return {
            'avg_round': float(result.avg_round) if result and result.avg_round else None,
            'min_round': result.min_round if result else None,
            'max_round': result.max_round if result else None,
            'prediction_count': result.prediction_count if result else 0
        }


# =============================================================================
# DEPRECATED - Kept for backward compatibility only
# =============================================================================

class DraftSeason(db.Model):
    """
    DEPRECATED: This model is no longer needed for new predictions.
    Kept only for backward compatibility with existing data.

    New predictions use season_id + league_type directly on DraftPrediction.
    """
    __tablename__ = 'draft_seasons'

    id = db.Column(db.Integer, primary_key=True)
    season_id = db.Column(db.Integer, db.ForeignKey('season.id'), nullable=False)
    league_type = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    prediction_start_date = db.Column(db.DateTime, nullable=False)
    prediction_end_date = db.Column(db.DateTime, nullable=False)
    draft_completed = db.Column(db.Boolean, nullable=False, default=False)
    draft_date = db.Column(db.DateTime, nullable=True)
    predictions_open = db.Column(db.Boolean, nullable=False, default=True)
    predictions_close_date = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # Relationships
    season = db.relationship('Season', backref='draft_seasons')
    creator = db.relationship('User', foreign_keys=[created_by], backref='created_draft_seasons')
    predictions = db.relationship('DraftPrediction', back_populates='draft_season')
    summaries = db.relationship('DraftPredictionSummary', back_populates='draft_season')


class DraftPredictionSummary(db.Model):
    """
    DEPRECATED: Summary statistics for coach predictions.
    This can be calculated on-the-fly from DraftPrediction data.
    """
    __tablename__ = 'draft_prediction_summaries'

    id = db.Column(db.Integer, primary_key=True)
    draft_season_id = db.Column(db.Integer, db.ForeignKey('draft_seasons.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    total_predictions = db.Column(db.Integer, nullable=False, default=0)
    correct_predictions = db.Column(db.Integer, nullable=False, default=0)
    incorrect_predictions = db.Column(db.Integer, nullable=False, default=0)
    pending_predictions = db.Column(db.Integer, nullable=False, default=0)
    accuracy_percentage = db.Column(db.Numeric(5, 2), nullable=False, default=0.0)
    total_points = db.Column(db.Numeric(8, 2), nullable=False, default=0.0)
    rank = db.Column(db.Integer, nullable=True)
    last_updated = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    draft_season = db.relationship('DraftSeason', back_populates='summaries')
    user = db.relationship('User', backref='draft_prediction_summaries')

    __table_args__ = (
        db.UniqueConstraint('draft_season_id', 'user_id', name='uq_draft_prediction_summary_season_user'),
    )
