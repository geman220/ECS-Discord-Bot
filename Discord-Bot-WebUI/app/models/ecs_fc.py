# app/models/ecs_fc.py

"""
ECS FC Models Module

This module contains models specific to ECS FC functionality:
- ExternalOpponent: Reusable external opponent teams
- EcsFcMatch: ECS FC match scheduling
- EcsFcAvailability: ECS FC player availability
- EcsFcScheduleTemplate: ECS FC schedule templates
"""

from datetime import datetime
from sqlalchemy import JSON, DateTime, Boolean, Date, Time, String, Text, Integer, ForeignKey
from sqlalchemy.orm import relationship

from app.core import db


class ExternalOpponent(db.Model):
    """
    Model for reusable external opponent teams.

    ECS FC teams play against external teams not in our database.
    This model allows saving commonly-played opponents for reuse.
    """
    __tablename__ = 'external_opponents'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False, unique=True)
    short_name = db.Column(db.String(100), nullable=True)  # Abbreviated name
    home_venue = db.Column(db.String(255), nullable=True)
    city = db.Column(db.String(100), nullable=True)
    league_affiliation = db.Column(db.String(100), nullable=True)  # WSSL, GSSL, etc.
    contact_info = db.Column(db.Text, nullable=True)  # Contact name, email, phone
    notes = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    # Relationships
    creator = db.relationship('User', foreign_keys=[created_by], backref='created_opponents')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'short_name': self.short_name,
            'home_venue': self.home_venue,
            'city': self.city,
            'league_affiliation': self.league_affiliation,
            'contact_info': self.contact_info,
            'notes': self.notes,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<ExternalOpponent {self.name}>'


class EcsFcMatch(db.Model):
    """Model for ECS FC matches."""
    __tablename__ = 'ecs_fc_matches'

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    opponent_name = db.Column(db.String(255), nullable=False)  # Always stored (from library or free-text)
    external_opponent_id = db.Column(db.Integer, db.ForeignKey('external_opponents.id'), nullable=True)  # Optional link to library
    match_date = db.Column(db.Date, nullable=False)
    match_time = db.Column(db.Time, nullable=False)
    location = db.Column(db.String(100), nullable=False)
    field_name = db.Column(db.String(100), nullable=True)
    is_home_match = db.Column(db.Boolean, nullable=False)
    home_shirt_color = db.Column(db.String(50), nullable=True)
    away_shirt_color = db.Column(db.String(50), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(50), nullable=False)
    home_score = db.Column(db.Integer, nullable=True)
    away_score = db.Column(db.Integer, nullable=True)
    created_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False)
    updated_at = db.Column(db.DateTime, nullable=False)
    rsvp_deadline = db.Column(db.DateTime, nullable=True)
    rsvp_reminder_sent = db.Column(db.Boolean, nullable=False, default=False)

    # Discord integration
    discord_message_id = db.Column(db.String(30), nullable=True)
    discord_channel_id = db.Column(db.String(30), nullable=True)
    last_discord_notification = db.Column(db.DateTime, nullable=True)
    notification_status = db.Column(db.String(50), nullable=True)

    # Relationships
    team = db.relationship('Team', foreign_keys=[team_id], backref='ecs_fc_matches')
    external_opponent = db.relationship('ExternalOpponent', foreign_keys=[external_opponent_id], backref='matches')
    availabilities = db.relationship('EcsFcAvailability', back_populates='match', cascade='all, delete-orphan')
    events = db.relationship('EcsFcPlayerEvent', back_populates='match', cascade='all, delete-orphan')

    # Alias for backward compatibility with code using singular form
    @property
    def availability(self):
        return self.availabilities

    def get_rsvp_summary(self):
        """Get RSVP response counts for this match."""
        yes_count = sum(1 for a in self.availabilities if a.response == 'yes')
        no_count = sum(1 for a in self.availabilities if a.response == 'no')
        maybe_count = sum(1 for a in self.availabilities if a.response == 'maybe')
        no_response_count = sum(1 for a in self.availabilities if a.response == 'no_response' or not a.response)

        # Count players on team who haven't responded at all
        if self.team and hasattr(self.team, 'players'):
            responded_player_ids = {a.player_id for a in self.availabilities if a.player_id}
            all_player_ids = {p.id for p in self.team.players}
            not_responded = len(all_player_ids - responded_player_ids)
            no_response_count = no_response_count + not_responded

        return {
            'yes': yes_count,
            'no': no_count,
            'maybe': maybe_count,
            'no_response': no_response_count,
            'total': yes_count + no_count + maybe_count + no_response_count
        }

    def get_rsvp_details(self):
        """Get RSVP details with player names grouped by response."""
        rsvp_data = {'yes': [], 'no': [], 'maybe': []}
        for availability in self.availabilities:
            if availability.response in rsvp_data and availability.player:
                rsvp_data[availability.response].append({
                    'player_name': availability.player.name,
                    'player_id': availability.player_id
                })
        return rsvp_data

    def to_dict(self):
        return {
            'id': self.id,
            'team_id': self.team_id,
            'opponent_name': self.opponent_name,
            'external_opponent_id': self.external_opponent_id,
            'match_date': self.match_date.isoformat() if self.match_date else None,
            'match_time': self.match_time.isoformat() if self.match_time else None,
            'location': self.location,
            'field_name': self.field_name,
            'is_home_match': self.is_home_match,
            'home_shirt_color': self.home_shirt_color,
            'away_shirt_color': self.away_shirt_color,
            'notes': self.notes,
            'status': self.status,
            'home_score': self.home_score,
            'away_score': self.away_score,
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'rsvp_deadline': self.rsvp_deadline.isoformat() if self.rsvp_deadline else None,
            'rsvp_reminder_sent': self.rsvp_reminder_sent,
            'discord_message_id': self.discord_message_id,
            'discord_channel_id': self.discord_channel_id,
            'last_discord_notification': self.last_discord_notification.isoformat() if self.last_discord_notification else None,
            'notification_status': self.notification_status,
        }


class EcsFcAvailability(db.Model):
    """Model for ECS FC player availability responses."""
    __tablename__ = 'ecs_fc_availability'

    id = db.Column(db.Integer, primary_key=True)
    # Note: Database column is 'ecs_fc_match_id' but we use 'match_id' as the Python attribute
    ecs_fc_match_id = db.Column('ecs_fc_match_id', db.Integer, db.ForeignKey('ecs_fc_matches.id'), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=True)
    discord_id = db.Column(db.String(100), nullable=False)
    response = db.Column(db.String(20), nullable=False)
    responded_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    match = db.relationship('EcsFcMatch', back_populates='availabilities')
    player = db.relationship('Player', backref='ecs_fc_availability')

    # Alias for backward compatibility with code using match_id
    @property
    def match_id(self):
        return self.ecs_fc_match_id

    @match_id.setter
    def match_id(self, value):
        self.ecs_fc_match_id = value
    
    def to_dict(self):
        return {
            'id': self.id,
            'match_id': self.match_id,
            'player_id': self.player_id,
            'discord_id': self.discord_id,
            'response': self.response,
            'responded_at': self.responded_at.isoformat() if self.responded_at else None,
        }


class EcsFcPlayerEvent(db.Model):
    """
    Model representing a match event (goal, assist, card) for ECS FC matches.

    This mirrors the PlayerEvent model for Pub League matches.
    """
    __tablename__ = 'ecs_fc_player_events'

    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id', ondelete='CASCADE'), nullable=True)
    ecs_fc_match_id = db.Column(db.Integer, db.ForeignKey('ecs_fc_matches.id'), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=True)  # For own goals
    minute = db.Column(db.String(10), nullable=True)  # e.g., "45", "90+2"
    event_type = db.Column(db.String(20), nullable=False)  # goal, assist, yellow_card, red_card, own_goal
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    player = db.relationship('Player', backref='ecs_fc_events')
    match = db.relationship('EcsFcMatch', back_populates='events')
    team = db.relationship('Team', backref='ecs_fc_own_goal_events')
    creator = db.relationship('User', foreign_keys=[created_by], backref='created_ecs_fc_events')

    def to_dict(self, include_player=False):
        data = {
            'id': self.id,
            'player_id': self.player_id,
            'match_id': self.ecs_fc_match_id,
            'team_id': self.team_id,
            'minute': self.minute,
            'event_type': self.event_type,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
        if include_player and self.player:
            data['player'] = {
                'id': self.player.id,
                'name': self.player.name,
                'jersey_number': self.player.jersey_number,
            }
        return data


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


def is_ecs_fc_league(league_id):
    """
    Check if a league is an ECS FC league.

    ECS FC leagues allow players to be on multiple teams within the same league,
    unlike Pub League (Classic/Premier) which restricts players to one team per league.

    Args:
        league_id: The ID of the league to check

    Returns:
        bool: True if the league is an ECS FC league, False otherwise
    """
    from app.models.core import League

    if not league_id:
        return False

    league = League.query.get(league_id)
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