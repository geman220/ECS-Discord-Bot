# app/models/ratings.py

"""
Classic League Rating Models

Blind per-season coach ratings for Classic players plus admin final-score
overrides. Ratings key on season_id + league_type (DraftPrediction pattern) so
they survive league-row churn across seasons and trend queries need no league
joins. Final scores are always computed on the fly (override -> else coach
average) — see app/services/classic_rating_service.py, the single source of
truth for aggregation math.
"""

from datetime import datetime

from app.core import db


class PlayerSeasonRating(db.Model):
    """One coach's rating of one player for one season. Blind: coaches only
    ever read their own rows; admins see all. Metric columns are nullable so
    per-slider autosave can persist partial rows — a player counts as "rated"
    only when all four metrics are non-null."""
    __tablename__ = 'player_season_ratings'

    id = db.Column(db.Integer, primary_key=True)
    season_id = db.Column(db.Integer, db.ForeignKey('season.id'), nullable=False)
    league_type = db.Column(db.String(50), nullable=False, default='Classic')
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False)
    rater_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    intensity = db.Column(db.Numeric(3, 2), nullable=True)
    on_ball_skill = db.Column(db.Numeric(3, 2), nullable=True)
    spirit = db.Column(db.Numeric(3, 2), nullable=True)
    knowledge_movement = db.Column(db.Numeric(3, 2), nullable=True)

    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    season = db.relationship('Season', foreign_keys=[season_id], backref='player_ratings')
    player = db.relationship('Player', foreign_keys=[player_id], backref='season_ratings')
    rater = db.relationship('User', foreign_keys=[rater_user_id], backref='ratings_given')

    __table_args__ = (
        db.UniqueConstraint('season_id', 'league_type', 'player_id', 'rater_user_id',
                            name='uq_player_season_rating'),
        db.Index('idx_psr_season_league', 'season_id', 'league_type'),
        db.Index('idx_psr_player', 'player_id'),
        db.Index('idx_psr_rater', 'season_id', 'rater_user_id'),
    )

    @property
    def is_complete(self):
        return all(v is not None for v in (
            self.intensity, self.on_ball_skill, self.spirit, self.knowledge_movement))

    def to_dict(self):
        return {
            'id': self.id,
            'season_id': self.season_id,
            'league_type': self.league_type,
            'player_id': self.player_id,
            'rater_user_id': self.rater_user_id,
            'intensity': float(self.intensity) if self.intensity is not None else None,
            'on_ball_skill': float(self.on_ball_skill) if self.on_ball_skill is not None else None,
            'spirit': float(self.spirit) if self.spirit is not None else None,
            'knowledge_movement': float(self.knowledge_movement) if self.knowledge_movement is not None else None,
            'notes': self.notes,
            'is_complete': self.is_complete,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class PlayerRatingOverride(db.Model):
    """Admin override of a player's FINAL score for one metric in one season.
    Overrides beat the coach average; clearing one restores the average. Every
    set/clear is also written to AdminAuditLog."""
    __tablename__ = 'player_rating_overrides'

    id = db.Column(db.Integer, primary_key=True)
    season_id = db.Column(db.Integer, db.ForeignKey('season.id'), nullable=False)
    league_type = db.Column(db.String(50), nullable=False, default='Classic')
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False)
    metric = db.Column(db.String(30), nullable=False)
    override_value = db.Column(db.Numeric(3, 2), nullable=False)
    reason = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    player = db.relationship('Player', foreign_keys=[player_id], backref='rating_overrides')
    author = db.relationship('User', foreign_keys=[created_by])

    __table_args__ = (
        db.UniqueConstraint('season_id', 'league_type', 'player_id', 'metric',
                            name='uq_player_rating_override'),
        db.Index('idx_pro_season_player', 'season_id', 'league_type', 'player_id'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'season_id': self.season_id,
            'player_id': self.player_id,
            'metric': self.metric,
            'override_value': float(self.override_value),
            'reason': self.reason,
            'created_by': self.created_by,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class ClassicRatingMetric(db.Model):
    """Admin-editable guide text for each rating metric (label, description,
    1/3/5 scale anchors). Weights intentionally live in AdminConfig
    (classic_rating_weights), not here — one source for each datum;
    classic_rating_service.get_metrics() joins the two."""
    __tablename__ = 'classic_rating_metric'

    key = db.Column(db.String(30), primary_key=True)
    label = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text, nullable=False)
    anchor_1 = db.Column(db.Text, nullable=False)
    anchor_3 = db.Column(db.Text, nullable=False)
    anchor_5 = db.Column(db.Text, nullable=False)
    display_order = db.Column(db.Integer, nullable=False)

    def to_dict(self):
        return {
            'key': self.key,
            'label': self.label,
            'description': self.description,
            'anchor_1': self.anchor_1,
            'anchor_3': self.anchor_3,
            'anchor_5': self.anchor_5,
            'display_order': self.display_order,
        }
