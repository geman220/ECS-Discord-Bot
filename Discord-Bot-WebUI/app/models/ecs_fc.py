# app/models/ecs_fc.py

"""
ECS FC Models Module

This module contains models specific to ECS FC functionality:
- EcsFcMatch: ECS FC match scheduling
- EcsFcAvailability: ECS FC player availability
- EcsFcScheduleTemplate: ECS FC schedule templates
"""

from datetime import datetime
from sqlalchemy import JSON, DateTime, Boolean, Date, Time, String, Text, Integer, ForeignKey
from sqlalchemy.orm import relationship

from app.core import db


class EcsFcMatch(db.Model):
    """Model for ECS FC matches."""
    __tablename__ = 'ecs_fc_matches'
    
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    time = db.Column(db.Time, nullable=False)
    location = db.Column(db.String(100), nullable=False)
    home_team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    away_team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    home_team_message_id = db.Column(db.String(100), nullable=True)
    away_team_message_id = db.Column(db.String(100), nullable=True)
    home_team_score = db.Column(db.Integer, nullable=True)
    away_team_score = db.Column(db.Integer, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    home_team = db.relationship('Team', foreign_keys=[home_team_id], backref='ecs_fc_home_matches')
    away_team = db.relationship('Team', foreign_keys=[away_team_id], backref='ecs_fc_away_matches')
    availability = db.relationship('EcsFcAvailability', back_populates='match', cascade='all, delete-orphan')
    
    def to_dict(self):
        return {
            'id': self.id,
            'date': self.date.isoformat() if self.date else None,
            'time': self.time.isoformat() if self.time else None,
            'location': self.location,
            'home_team_id': self.home_team_id,
            'away_team_id': self.away_team_id,
            'home_team_score': self.home_team_score,
            'away_team_score': self.away_team_score,
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class EcsFcAvailability(db.Model):
    """Model for ECS FC player availability responses."""
    __tablename__ = 'ecs_fc_availability'
    
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('ecs_fc_matches.id'), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=True)
    discord_id = db.Column(db.String(100), nullable=False)
    response = db.Column(db.String(20), nullable=False)
    responded_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    match = db.relationship('EcsFcMatch', back_populates='availability')
    player = db.relationship('Player', backref='ecs_fc_availability')
    
    def to_dict(self):
        return {
            'id': self.id,
            'match_id': self.match_id,
            'player_id': self.player_id,
            'discord_id': self.discord_id,
            'response': self.response,
            'responded_at': self.responded_at.isoformat() if self.responded_at else None,
        }


class EcsFcScheduleTemplate(db.Model):
    """Model for ECS FC schedule templates."""
    __tablename__ = 'ecs_fc_schedule_templates'
    
    id = db.Column(db.Integer, primary_key=True)
    league_id = db.Column(db.Integer, db.ForeignKey('league.id'), nullable=False)
    week_number = db.Column(db.Integer, nullable=False)
    home_team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    away_team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    scheduled_date = db.Column(db.Date, nullable=False)
    scheduled_time = db.Column(db.Time, nullable=False)
    field_name = db.Column(db.String(50), nullable=False)
    match_order = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    league = db.relationship('League', backref='ecs_fc_schedule_templates')
    home_team = db.relationship('Team', foreign_keys=[home_team_id], backref='ecs_fc_home_schedule_templates')
    away_team = db.relationship('Team', foreign_keys=[away_team_id], backref='ecs_fc_away_schedule_templates')
    
    def to_dict(self):
        return {
            'id': self.id,
            'league_id': self.league_id,
            'week_number': self.week_number,
            'home_team_id': self.home_team_id,
            'away_team_id': self.away_team_id,
            'scheduled_date': self.scheduled_date.isoformat() if self.scheduled_date else None,
            'scheduled_time': self.scheduled_time.isoformat() if self.scheduled_time else None,
            'field_name': self.field_name,
            'match_order': self.match_order,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


def get_ecs_fc_teams():
    """Get all ECS FC teams."""
    from app.models.core import League
    from app.models.players import Team
    
    # Get ECS FC leagues
    ecs_fc_leagues = League.query.filter(League.name.ilike('%ECS FC%')).all()
    teams = []
    for league in ecs_fc_leagues:
        teams.extend(league.teams)
    return teams


def is_ecs_fc_team(team_id):
    """Check if a team is an ECS FC team."""
    from app.models.players import Team
    from app.models.core import League
    
    team = Team.query.get(team_id)
    if not team:
        return False
    
    league = League.query.get(team.league_id)
    if not league:
        return False
    
    return 'ECS FC' in league.name


def get_ecs_fc_matches_for_team(team_id, start_date=None, end_date=None):
    """Get ECS FC matches for a specific team."""
    query = EcsFcMatch.query.filter(
        (EcsFcMatch.home_team_id == team_id) | (EcsFcMatch.away_team_id == team_id)
    )
    
    if start_date:
        query = query.filter(EcsFcMatch.date >= start_date)
    if end_date:
        query = query.filter(EcsFcMatch.date <= end_date)
    
    return query.order_by(EcsFcMatch.date, EcsFcMatch.time).all()


def get_ecs_fc_matches_for_date_range(start_date, end_date):
    """Get all ECS FC matches within a date range."""
    return EcsFcMatch.query.filter(
        EcsFcMatch.date >= start_date,
        EcsFcMatch.date <= end_date
    ).order_by(EcsFcMatch.date, EcsFcMatch.time).all()