# app/models/predictions.py

"""
Draft Predictions Models Module

This module contains models for draft predictions:
- DraftSeason: Draft season management
- DraftPrediction: Individual draft predictions
- DraftPredictionSummary: Summary of draft predictions
"""

from datetime import datetime
from sqlalchemy import JSON, DateTime, Boolean, Date, Time, String, Text, Integer, ForeignKey, Numeric
from sqlalchemy.orm import relationship

from app.core import db


class DraftSeason(db.Model):
    """Model for draft seasons."""
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
    predictions = db.relationship('DraftPrediction', back_populates='draft_season', cascade='all, delete-orphan')
    summaries = db.relationship('DraftPredictionSummary', back_populates='draft_season', cascade='all, delete-orphan')
    
    def get_eligible_players(self, session=None):
        """Get players eligible for this draft season based on league type and season."""
        from app.models import Player, League
        from sqlalchemy import func
        from app.core import db
        from flask import g
        
        # Use provided session or fall back to g.db_session or default
        if session:
            query_session = session
        elif hasattr(g, 'db_session'):
            query_session = g.db_session
        else:
            query_session = db.session
        
        # Get players who are current and in leagues of the specified type for this season
        players = query_session.query(Player).join(Player.league).filter(
            Player.is_current_player == True,
            League.season_id == self.season_id,
            func.lower(League.name) == func.lower(self.league_type)
        ).order_by(Player.name).all()
        
        return players
    
    def to_dict(self):
        return {
            'id': self.id,
            'season_id': self.season_id,
            'league_type': self.league_type,
            'name': self.name,
            'description': self.description,
            'is_active': self.is_active,
            'prediction_start_date': self.prediction_start_date.isoformat() if self.prediction_start_date else None,
            'prediction_end_date': self.prediction_end_date.isoformat() if self.prediction_end_date else None,
            'draft_completed': self.draft_completed,
            'draft_date': self.draft_date.isoformat() if self.draft_date else None,
            'predictions_open': self.predictions_open,
            'predictions_close_date': self.predictions_close_date.isoformat() if self.predictions_close_date else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'created_by': self.created_by,
        }


class DraftPrediction(db.Model):
    """Model for individual draft predictions."""
    __tablename__ = 'draft_predictions'
    
    id = db.Column(db.Integer, primary_key=True)
    draft_season_id = db.Column(db.Integer, db.ForeignKey('draft_seasons.id'), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False)
    coach_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    predicted_round = db.Column(db.Integer, nullable=False)
    predicted_pick_number = db.Column(db.Integer, nullable=True)
    confidence_level = db.Column(db.Integer, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    draft_season = db.relationship('DraftSeason', back_populates='predictions')
    coach_user = db.relationship('User', foreign_keys=[coach_user_id], backref='draft_predictions')
    player = db.relationship('Player', foreign_keys=[player_id], backref='draft_predictions')
    
    __table_args__ = (
        db.UniqueConstraint('draft_season_id', 'player_id', 'coach_user_id', name='uq_draft_prediction'),
    )
    
    def to_dict(self):
        return {
            'id': self.id,
            'draft_season_id': self.draft_season_id,
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
    def get_player_average_prediction(season_id, player_id, session=None):
        """Get the average predicted round for a player in a season."""
        from sqlalchemy import func
        from app.core import db
        from flask import g
        
        # Use provided session or fall back to g.db_session or default
        if session:
            query_session = session
        elif hasattr(g, 'db_session'):
            query_session = g.db_session
        else:
            query_session = db.session
        
        result = query_session.query(func.avg(DraftPrediction.predicted_round)).filter_by(
            draft_season_id=season_id,
            player_id=player_id
        ).scalar()
        
        return float(result) if result else None
    
    @staticmethod
    def get_player_prediction_range(season_id, player_id, session=None):
        """Get the min and max predicted rounds for a player in a season."""
        from sqlalchemy import func
        from app.core import db
        from flask import g
        
        # Use provided session or fall back to g.db_session or default
        if session:
            query_session = session
        elif hasattr(g, 'db_session'):
            query_session = g.db_session
        else:
            query_session = db.session
        
        result = query_session.query(
            func.min(DraftPrediction.predicted_round),
            func.max(DraftPrediction.predicted_round)
        ).filter_by(
            draft_season_id=season_id,
            player_id=player_id
        ).first()
        
        return {
            'min_round': result[0] if result and result[0] else None,
            'max_round': result[1] if result and result[1] else None
        }


class DraftPredictionSummary(db.Model):
    """Model for draft prediction summaries."""
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
    
    def to_dict(self):
        return {
            'id': self.id,
            'draft_season_id': self.draft_season_id,
            'user_id': self.user_id,
            'total_predictions': self.total_predictions,
            'correct_predictions': self.correct_predictions,
            'incorrect_predictions': self.incorrect_predictions,
            'pending_predictions': self.pending_predictions,
            'accuracy_percentage': float(self.accuracy_percentage) if self.accuracy_percentage else 0.0,
            'total_points': float(self.total_points) if self.total_points else 0.0,
            'rank': self.rank,
            'last_updated': self.last_updated.isoformat() if self.last_updated else None,
        }
    
    def update_summary(self):
        """Update the summary based on current predictions."""
        predictions = DraftPrediction.query.filter_by(
            draft_season_id=self.draft_season_id,
            user_id=self.user_id
        ).all()
        
        self.total_predictions = len(predictions)
        self.correct_predictions = sum(1 for p in predictions if p.is_correct is True)
        self.incorrect_predictions = sum(1 for p in predictions if p.is_correct is False)
        self.pending_predictions = sum(1 for p in predictions if p.is_correct is None)
        
        if self.total_predictions > 0:
            self.accuracy_percentage = (self.correct_predictions / self.total_predictions) * 100
        else:
            self.accuracy_percentage = 0.0
        
        self.total_points = sum(p.points_awarded or 0 for p in predictions)
        self.last_updated = datetime.utcnow()
        
        db.session.commit()
    
    @staticmethod
    def refresh_summary(draft_season_id, player_id, session=None):
        """Refresh prediction summary for a player in a season."""
        from app.core import db
        from flask import g
        
        # Use provided session or fall back to g.db_session or default
        if session:
            query_session = session
        elif hasattr(g, 'db_session'):
            query_session = g.db_session
        else:
            query_session = db.session
        
        # This method would typically update summary statistics
        # For now, we'll just pass since the individual predictions are what matter
        pass