# app/models/stats.py

"""
Statistics Models Module

This module contains models related to player and team statistics:
- PlayerSeasonStats: Player statistics per season
- PlayerCareerStats: Player career statistics
- PlayerAttendanceStats: Player attendance tracking
- Standings: Team standings
- StatChangeLog: Stat change logging
- PlayerStatAudit: Player stat audit trail
- PlayerEventType: Enum for player events
- PlayerEvent: Match events for players
- StatChangeType: Enum for stat change types
"""

import logging
import enum
from datetime import datetime
from flask import g
from sqlalchemy import event, func, Enum

from app.core import db
from app.models.players import player_teams

logger = logging.getLogger(__name__)


class PlayerSeasonStats(db.Model):
    """
    Model for storing a player's season statistics.

    Stats are separated by league to ensure proper attribution:
    - A player on both Premier and Classic has separate stat records
    - Golden Boot is calculated per-league, not combined
    - Career stats aggregate across all leagues
    """
    __tablename__ = 'player_season_stats'

    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id', ondelete='CASCADE'), nullable=False)
    season_id = db.Column(db.Integer, db.ForeignKey('season.id'), nullable=False)
    league_id = db.Column(db.Integer, db.ForeignKey('league.id'), nullable=True)  # For league-specific stats
    goals = db.Column(db.Integer, default=0, nullable=False)
    assists = db.Column(db.Integer, default=0, nullable=False)
    yellow_cards = db.Column(db.Integer, default=0, nullable=False)
    red_cards = db.Column(db.Integer, default=0, nullable=False)

    player = db.relationship('Player', back_populates='season_stats')
    season = db.relationship('Season', back_populates='player_stats')
    league = db.relationship('League', backref='player_season_stats')
    teams = db.relationship(
        'Team',
        secondary=player_teams,
        primaryjoin="PlayerSeasonStats.player_id==player_teams.c.player_id",
        secondaryjoin="Team.id==player_teams.c.team_id",
        viewonly=True
    )

    # Unique constraint: one stat record per player/season/league combo
    __table_args__ = (
        db.UniqueConstraint('player_id', 'season_id', 'league_id', name='uq_player_season_league_stats'),
    )

    @classmethod
    def get_or_create(cls, session, player_id, season_id, league_id=None):
        """Get existing stats record or create new one for player/season/league."""
        stats = session.query(cls).filter_by(
            player_id=player_id,
            season_id=season_id,
            league_id=league_id
        ).first()

        if not stats:
            stats = cls(
                player_id=player_id,
                season_id=season_id,
                league_id=league_id,
                goals=0,
                assists=0,
                yellow_cards=0,
                red_cards=0
            )
            session.add(stats)

        return stats

    def to_dict(self, session=None):
        return {
            'id': self.id,
            'player_id': self.player_id,
            'season_id': self.season_id,
            'league_id': self.league_id,
            'league_name': self.league.name if self.league else None,
            'goals': self.goals,
            'assists': self.assists,
            'yellow_cards': self.yellow_cards,
            'red_cards': self.red_cards,
        }


class PlayerCareerStats(db.Model):
    """Model for storing a player's career statistics."""
    __tablename__ = 'player_career_stats'

    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id', ondelete='CASCADE'), nullable=False)
    goals = db.Column(db.Integer, default=0, nullable=False)
    assists = db.Column(db.Integer, default=0, nullable=False)
    yellow_cards = db.Column(db.Integer, default=0, nullable=False)
    red_cards = db.Column(db.Integer, default=0, nullable=False)

    player = db.relationship('Player', back_populates='career_stats')

    @classmethod 
    def get_stats_by_team(cls, team_id):
        return g.db_session.query(cls).join(Player).join(player_teams).filter(
            player_teams.c.team_id == team_id
        ).all()

    def to_dict(self, session=None):
        return {
            'id': self.id,
            'player_id': self.player_id,
            'goals': self.goals,
            'assists': self.assists,
            'yellow_cards': self.yellow_cards,
            'red_cards': self.red_cards,
        }


class Standings(db.Model):
    """Model representing team standings for a season."""
    __tablename__ = 'standings'

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    season_id = db.Column(db.Integer, db.ForeignKey('season.id'), nullable=False)
    played = db.Column(db.Integer, default=0, nullable=False)
    wins = db.Column(db.Integer, default=0, nullable=False)
    draws = db.Column(db.Integer, default=0, nullable=False)
    losses = db.Column(db.Integer, default=0, nullable=False)
    goals_for = db.Column(db.Integer, default=0, nullable=False)
    goals_against = db.Column(db.Integer, default=0, nullable=False)
    goal_difference = db.Column(db.Integer, default=0, nullable=False)
    points = db.Column(db.Integer, default=0, nullable=False)

    team = db.relationship('Team', backref='standings')
    season = db.relationship('Season', backref='standings')

    @staticmethod
    def update_goal_difference(mapper, connection, target):
        target.goal_difference = (target.goals_for or 0) - (target.goals_against or 0)

    @property
    def team_goals(self):
        return g.db_session.query(
            func.sum(PlayerSeasonStats.goals)
        ).join(Player).join(player_teams).filter(
            player_teams.c.team_id == self.team_id
        ).scalar() or 0

    def to_dict(self, session=None):
        return {
            'id': self.id,
            'team_id': self.team_id,
            'team_name': self.team.name,
            'season_id': self.season_id,
            'played': self.played,
            'wins': self.wins,
            'draws': self.draws,
            'losses': self.losses,
            'goals_for': self.goals_for,
            'goals_against': self.goals_against,
            'goal_difference': self.goal_difference,
            'points': self.points,
        }


class StatChangeLog(db.Model):
    """Model for logging changes to player statistics."""
    __tablename__ = 'stat_change_logs'

    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id', ondelete='CASCADE'), nullable=False)
    stat = db.Column(db.String(50), nullable=False)
    old_value = db.Column(db.Integer, nullable=False)
    new_value = db.Column(db.Integer, nullable=False)
    change_type = db.Column(db.String(10), nullable=False)  # ADD, DELETE, EDIT
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    season_id = db.Column(db.Integer, db.ForeignKey('season.id', ondelete='CASCADE'), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    player = db.relationship('Player', back_populates='stat_change_logs')
    user = db.relationship('User', back_populates='stat_change_logs')
    season = db.relationship('Season', back_populates='stat_change_logs')


class PlayerAttendanceStats(db.Model):
    """Cached attendance statistics for fast lookups during drafts and player evaluations."""
    __tablename__ = 'player_attendance_stats'
    
    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id', ondelete='CASCADE'), nullable=False, unique=True)
    
    # Raw counts
    total_matches_invited = db.Column(db.Integer, default=0, nullable=False)
    total_responses = db.Column(db.Integer, default=0, nullable=False)
    yes_responses = db.Column(db.Integer, default=0, nullable=False)
    no_responses = db.Column(db.Integer, default=0, nullable=False)
    maybe_responses = db.Column(db.Integer, default=0, nullable=False)
    no_response_count = db.Column(db.Integer, default=0, nullable=False)
    
    # Calculated percentages (stored for fast access)
    response_rate = db.Column(db.Float, default=0.0, nullable=False)  # % of times they respond
    attendance_rate = db.Column(db.Float, default=0.0, nullable=False)  # % of times they say yes
    adjusted_attendance_rate = db.Column(db.Float, default=0.0, nullable=False)  # yes + (maybe * 0.5)
    reliability_score = db.Column(db.Float, default=0.0, nullable=False)  # composite score
    
    # Season-specific tracking
    current_season_id = db.Column(db.Integer, db.ForeignKey('season.id'), nullable=True)
    season_matches_invited = db.Column(db.Integer, default=0, nullable=False)
    season_yes_responses = db.Column(db.Integer, default=0, nullable=False)
    season_attendance_rate = db.Column(db.Float, default=0.0, nullable=False)
    
    # Metadata
    last_updated = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_match_date = db.Column(db.DateTime, nullable=True)
    
    # Relationships
    player = db.relationship('Player', back_populates='attendance_stats')
    season = db.relationship('Season')
    
    @classmethod
    def get_or_create(cls, player_id, season_id=None):
        """Get existing stats or create new record for player."""
        stats = cls.query.filter_by(player_id=player_id).first()
        if not stats:
            stats = cls(player_id=player_id, current_season_id=season_id)
            g.db_session.add(stats)
        return stats
    
    def update_stats(self, session=None):
        """Recalculate all statistics from availability data."""
        if session is None:
            session = g.db_session
            
        # Get all availability records for this player
        availability_records = session.query(Availability).filter_by(player_id=self.player_id).all()
        
        # Reset counters
        self.total_matches_invited = len(availability_records)
        self.total_responses = 0
        self.yes_responses = 0
        self.no_responses = 0
        self.maybe_responses = 0
        self.no_response_count = 0
        
        # Count responses
        for record in availability_records:
            response = (record.response or '').lower()
            if response in ['yes', 'no', 'maybe']:
                self.total_responses += 1
                if response == 'yes':
                    self.yes_responses += 1
                elif response == 'no':
                    self.no_responses += 1
                elif response == 'maybe':
                    self.maybe_responses += 1
            else:
                self.no_response_count += 1
        
        # Calculate percentages
        if self.total_matches_invited > 0:
            self.response_rate = (self.total_responses / self.total_matches_invited) * 100
            self.attendance_rate = (self.yes_responses / self.total_matches_invited) * 100
            self.adjusted_attendance_rate = ((self.yes_responses + (self.maybe_responses * 0.5)) / self.total_matches_invited) * 100
            
            # Reliability score weights response rate and attendance
            if self.total_matches_invited >= 5:  # Established players
                self.reliability_score = (self.response_rate * 0.3) + (self.adjusted_attendance_rate * 0.7)
            else:  # New players
                self.reliability_score = (self.response_rate * 0.5) + (self.adjusted_attendance_rate * 0.5)
        else:
            self.response_rate = 0.0
            self.attendance_rate = 0.0
            self.adjusted_attendance_rate = 0.0
            self.reliability_score = 0.0
        
        # Update season-specific stats if season is set
        if self.current_season_id:
            self._update_season_stats(session)
        
        self.last_updated = datetime.utcnow()
        
    def _update_season_stats(self, session):
        """Update current season statistics."""
        # Get availability records for current season
        season_records = session.query(Availability).join(Match).join(Schedule).filter(
            Availability.player_id == self.player_id,
            Schedule.season_id == self.current_season_id
        ).all()
        
        self.season_matches_invited = len(season_records)
        self.season_yes_responses = sum(1 for r in season_records if (r.response or '').lower() == 'yes')
        
        if self.season_matches_invited > 0:
            self.season_attendance_rate = (self.season_yes_responses / self.season_matches_invited) * 100
        else:
            self.season_attendance_rate = 0.0
    
    def to_dict(self):
        return {
            'player_id': self.player_id,
            'total_matches_invited': self.total_matches_invited,
            'response_rate': round(self.response_rate, 1),
            'attendance_rate': round(self.attendance_rate, 1),
            'adjusted_attendance_rate': round(self.adjusted_attendance_rate, 1),
            'reliability_score': round(self.reliability_score, 1),
            'season_attendance_rate': round(self.season_attendance_rate, 1),
            'last_updated': self.last_updated.isoformat() if self.last_updated else None
        }


class PlayerEventType(enum.Enum):
    GOAL = 'goal'
    ASSIST = 'assist'
    YELLOW_CARD = 'yellow_card'
    RED_CARD = 'red_card'
    OWN_GOAL = 'own_goal'


class PlayerEvent(db.Model):
    """Model representing a match event (goal, assist, etc.) for a player or team (own goals)."""
    __tablename__ = 'player_event'

    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id', ondelete='CASCADE'), nullable=True)
    match_id = db.Column(db.Integer, db.ForeignKey('matches.id'), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=True)  # For own goals
    minute = db.Column(db.String, nullable=True)
    event_type = db.Column(Enum(PlayerEventType), nullable=False)

    player = db.relationship('Player', back_populates='events', passive_deletes=True)
    match = db.relationship('Match', back_populates='events')
    team = db.relationship('Team', backref='own_goal_events')

    def to_dict(self, include_player=False):
        data = {
            'id': self.id,
            'player_id': self.player_id,
            'match_id': self.match_id,
            'minute': self.minute,
            'event_type': self.event_type.name if self.event_type else None,
        }
        if include_player:
            data['player'] = self.player.to_dict(public=True)
        return data


class StatChangeType(enum.Enum):
    ADD = 'add'
    EDIT = 'edit'
    DELETE = 'delete'


class PlayerStatAudit(db.Model):
    """Model for auditing changes to player statistics."""
    __tablename__ = 'player_stat_audit'

    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id', ondelete='CASCADE'), nullable=False)
    season_id = db.Column(db.Integer, db.ForeignKey('season.id', ondelete='CASCADE'), nullable=True)
    stat_type = db.Column(db.String(50), nullable=False)
    old_value = db.Column(db.Integer, nullable=False)
    new_value = db.Column(db.Integer, nullable=False)
    change_type = db.Column(db.Enum(StatChangeType), nullable=False)
    changed_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    player = db.relationship('Player', back_populates='stat_audits')
    season = db.relationship('Season', back_populates='stat_audits')
    user = db.relationship('User', back_populates='stat_audits')


# Listen for goal difference updates
event.listen(Standings, 'before_insert', Standings.update_goal_difference)
event.listen(Standings, 'before_update', Standings.update_goal_difference)