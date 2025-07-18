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
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    opponent_name = db.Column(db.String(255), nullable=False)
    match_date = db.Column(db.Date, nullable=False)
    match_time = db.Column(db.Time, nullable=False)
    location = db.Column(db.String(100), nullable=False)
    field_name = db.Column(db.String(100), nullable=True)
    is_home_match = db.Column(db.Boolean, nullable=False)
    notes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(50), nullable=False)
    home_score = db.Column(db.Integer, nullable=True)
    away_score = db.Column(db.Integer, nullable=True)
    created_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False)
    updated_at = db.Column(db.DateTime, nullable=False)
    rsvp_deadline = db.Column(db.DateTime, nullable=True)
    rsvp_reminder_sent = db.Column(db.Boolean, nullable=False, default=False)
    
    # Relationships
    team = db.relationship('Team', foreign_keys=[team_id], backref='ecs_fc_matches')
    availability = db.relationship('EcsFcAvailability', back_populates='match', cascade='all, delete-orphan')
    
    def to_dict(self):
        return {
            'id': self.id,
            'team_id': self.team_id,
            'opponent_name': self.opponent_name,
            'match_date': self.match_date.isoformat() if self.match_date else None,
            'match_time': self.match_time.isoformat() if self.match_time else None,
            'location': self.location,
            'field_name': self.field_name,
            'is_home_match': self.is_home_match,
            'notes': self.notes,
            'status': self.status,
            'home_score': self.home_score,
            'away_score': self.away_score,
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'rsvp_deadline': self.rsvp_deadline.isoformat() if self.rsvp_deadline else None,
            'rsvp_reminder_sent': self.rsvp_reminder_sent,
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
    name = db.Column(db.String(255), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    description = db.Column(db.Text, nullable=True)
    template_data = db.Column(db.JSON, nullable=False)
    created_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False)
    updated_at = db.Column(db.DateTime, nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    
    # Relationships
    team = db.relationship('Team', foreign_keys=[team_id], backref='ecs_fc_schedule_templates')
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'team_id': self.team_id,
            'description': self.description,
            'template_data': self.template_data,
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'is_active': self.is_active,
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
    query = EcsFcMatch.query.filter(EcsFcMatch.team_id == team_id)
    
    if start_date:
        query = query.filter(EcsFcMatch.match_date >= start_date)
    if end_date:
        query = query.filter(EcsFcMatch.match_date <= end_date)
    
    return query.order_by(EcsFcMatch.match_date, EcsFcMatch.match_time).all()


def get_ecs_fc_matches_for_date_range(start_date, end_date):
    """Get all ECS FC matches within a date range."""
    return EcsFcMatch.query.filter(
        EcsFcMatch.match_date >= start_date,
        EcsFcMatch.match_date <= end_date
    ).order_by(EcsFcMatch.match_date, EcsFcMatch.match_time).all()