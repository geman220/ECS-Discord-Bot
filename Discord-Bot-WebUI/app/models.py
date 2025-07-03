# app/models.py

"""
Database Models Module

This module defines the SQLAlchemy ORM models used throughout the application.
It includes models for users, roles, permissions, leagues, seasons, teams, players,
matches, notifications, feedback, temporary substitutes, and various statistical and history tracking entities.
"""

import logging
import enum
from datetime import datetime, timedelta

import pyotp
from flask import request
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from sqlalchemy import event, func, Enum, JSON, DateTime, Boolean, Column, Integer, ForeignKey, or_, desc
from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_property

from app.core import db

# Set up the module logger
logger = logging.getLogger(__name__)

# Association table for the many-to-many relationship between User and Role
user_roles = db.Table(
    'user_roles',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id'), primary_key=True),
    db.Column('role_id', db.Integer, db.ForeignKey('roles.id'), primary_key=True)
)

# Association table for many-to-many relationship between Player and League (secondary leagues)
player_league = db.Table(
    'player_league',
    db.Column('player_id', db.Integer, db.ForeignKey('player.id'), primary_key=True),
    db.Column('league_id', db.Integer, db.ForeignKey('league.id'), primary_key=True)
)

# Association table for many-to-many relationship between Role and Permission
role_permissions = db.Table(
    'role_permissions',
    db.Column('role_id', db.Integer, db.ForeignKey('roles.id')),
    db.Column('permission_id', db.Integer, db.ForeignKey('permissions.id'))
)

# Association table for many-to-many relationship between Player and Team
player_teams = db.Table(
    'player_teams',
    db.Column('player_id', db.Integer, db.ForeignKey('player.id', ondelete='CASCADE'), primary_key=True),
    db.Column('team_id', db.Integer, db.ForeignKey('team.id', ondelete='CASCADE'), primary_key=True),
    db.Column('is_coach', db.Boolean, default=False)
)

# Association table for many-to-many relationship between HelpTopic and Role
help_topic_roles = db.Table(
    'help_topic_roles',
    db.Column('help_topic_id', db.Integer, db.ForeignKey('help_topics.id'), primary_key=True),
    db.Column('role_id', db.Integer, db.ForeignKey('roles.id'), primary_key=True)
)


class League(db.Model):
    """Model representing a league."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    season_id = db.Column(db.Integer, db.ForeignKey('season.id'), nullable=False)
    season = db.relationship('Season', back_populates='leagues')
    teams = db.relationship('Team', back_populates='league', lazy='joined')
    players = db.relationship(
        'Player',
        secondary=player_teams,
        primaryjoin='League.id==Team.league_id',
        secondaryjoin='and_(Team.id==player_teams.c.team_id, Player.id==player_teams.c.player_id)',
        overlaps="teams,players",
        viewonly=True,
        backref=db.backref('associated_leagues', viewonly=True)
    )
    primary_players = db.relationship('Player', back_populates='primary_league', foreign_keys='Player.primary_league_id')
    other_players = db.relationship('Player', secondary=player_league, back_populates='other_leagues')
    users = db.relationship('User', back_populates='league')

    def to_dict(self, session=None):
        return {
            'id': self.id,
            'name': self.name,
            'season_id': self.season_id,
        }

    def __repr__(self):
        return f'<League {self.name}>'


class User(UserMixin, db.Model):
    """Model representing a user in the system."""
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    _email = db.Column('email', db.String(120), unique=True, nullable=False)  # Private attribute for email
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp(), nullable=False)
    updated_at = db.Column(db.DateTime, default=db.func.current_timestamp(), onupdate=db.func.current_timestamp(), nullable=False)
    is_approved = db.Column(db.Boolean, default=False, nullable=False)
    email_notifications = db.Column(db.Boolean, default=True)
    sms_notifications = db.Column(db.Boolean, default=True)
    sms_confirmation_code = db.Column(db.String(6), nullable=True)
    discord_notifications = db.Column(db.Boolean, default=True)
    profile_visibility = db.Column(db.String(20), default='everyone')
    notifications = db.relationship('Notification', back_populates='user', lazy='select')
    has_completed_onboarding = db.Column(db.Boolean, default=False)
    has_completed_tour = db.Column(db.Boolean, default=False)
    has_skipped_profile_creation = db.Column(db.Boolean, default=False)
    league_id = db.Column(db.Integer, db.ForeignKey('league.id'), nullable=True)
    league = db.relationship('League', back_populates='users')
    is_2fa_enabled = db.Column(db.Boolean, default=False)
    totp_secret = db.Column(db.String(32), nullable=True)
    roles = db.relationship('Role', secondary=user_roles, back_populates='users')
    player = db.relationship('Player', back_populates='user', uselist=False)
    stat_change_logs = db.relationship('StatChangeLog', back_populates='user', cascade='all, delete-orphan')
    stat_audits = db.relationship('PlayerStatAudit', back_populates='user', cascade='all, delete-orphan')
    feedbacks = db.relationship('Feedback', back_populates='user', lazy='dynamic')
    notes = db.relationship('Note', back_populates='author', lazy=True)
    last_login = db.Column(db.DateTime, default=datetime.utcnow)
    feedback_replies = db.relationship('FeedbackReply', back_populates='user', lazy=True)

    @hybrid_property
    def email(self):
        return self._email

    @email.setter
    def email(self, value):
        self._email = value.lower() if value else None

    @email.expression
    def email(cls):
        return cls._email

    @email.comparator
    def email(cls):
        return cls._email

    def generate_totp_secret(self):
        """Generate a TOTP secret for 2FA."""
        self.totp_secret = pyotp.random_base32()

    def verify_totp(self, token):
        """Verify a provided 2FA token."""
        totp = pyotp.TOTP(self.totp_secret)
        return totp.verify(token)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def has_role(self, role_name):
        return any(role.name == role_name for role in self.roles or [])

    def has_permission(self, permission_name):
        return any(
            perm.name == permission_name
            for role in self.roles or []
            for perm in role.permissions or []
        )

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'is_approved': self.is_approved,
            'roles': [role.name for role in self.roles],
            'has_completed_onboarding': self.has_completed_onboarding,
            'league_id': self.league_id
        }


class Role(db.Model):
    """Model representing a user role."""
    __tablename__ = 'roles'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.String(255), nullable=True)

    users = db.relationship('User', secondary=user_roles, back_populates='roles')
    permissions = db.relationship('Permission', secondary=role_permissions, back_populates='roles')

    def __repr__(self):
        return f'<Role {self.name}>'


class Permission(db.Model):
    """Model representing a permission."""
    __tablename__ = 'permissions'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.String(255), nullable=True)
    roles = db.relationship('Role', secondary=role_permissions, back_populates='permissions')

    def __repr__(self):
        return f'<Permission {self.name}>'


class Season(db.Model):
    """Model representing a season."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    league_type = db.Column(db.String(50), nullable=False)
    is_current = db.Column(db.Boolean, default=False, nullable=False)
    leagues = db.relationship('League', back_populates='season', lazy=True)
    player_stats = db.relationship('PlayerSeasonStats', back_populates='season', lazy=True, cascade="all, delete-orphan")
    stat_change_logs = db.relationship('StatChangeLog', back_populates='season', cascade='all, delete-orphan')
    stat_audits = db.relationship('PlayerStatAudit', back_populates='season', cascade='all, delete-orphan')
    player_assignments = relationship(
        'PlayerTeamSeason',
        back_populates='season',
        cascade='all, delete-orphan'
    )

    def to_dict(self, session=None):
        return {
            'id': self.id,
            'name': self.name,
            'league_type': self.league_type,
            'is_current': self.is_current,
        }

    def __repr__(self):
        return f'<Season {self.name} ({self.league_type})>'


class Team(db.Model):
    """Model representing a team."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    league_id = db.Column(db.Integer, db.ForeignKey('league.id'), nullable=False)
    league = db.relationship('League', back_populates='teams')
    players = db.relationship('Player', secondary=player_teams, back_populates='teams')
    matches = db.relationship('Schedule', foreign_keys='Schedule.team_id', lazy=True)

    discord_channel_id = db.Column(db.String(30), nullable=True)
    discord_coach_role_id = db.Column(db.String(30), nullable=True)
    discord_player_role_id = db.Column(db.String(30), nullable=True)

    schedules = db.relationship('Schedule', foreign_keys='Schedule.team_id', back_populates='team', overlaps='matches')
    opponent_schedules = db.relationship('Schedule', foreign_keys='Schedule.opponent', back_populates='opponent_team')

    season_assignments = db.relationship(
        'PlayerTeamSeason',
        back_populates='team',
        cascade='all, delete-orphan'
    )

    kit_url = db.Column(db.String(255), nullable=True)
    background_image_url = db.Column(db.String(255), nullable=True)

    def to_dict(self, include_players=False):
        data = {
            'id': self.id,
            'name': self.name,
            'league_id': self.league_id,
            'discord_channel_id': self.discord_channel_id,
            'discord_coach_role_id': self.discord_coach_role_id,
            'discord_player_role_id': self.discord_player_role_id,
            'recent_form': self.recent_form,
            'top_scorer': self.top_scorer,
            'top_assist': self.top_assist,
            'avg_goals_per_match': self.avg_goals_per_match,
        }
        if include_players:
            data['players'] = [player.to_dict(public=True) for player in self.players]
        return data

    @property
    def coaches(self):
        """Get all coaches for this team."""
        return [
            player for player, is_coach in db.session.query(Team, player_teams.c.is_coach)
            .join(player_teams)
            .filter(player_teams.c.team_id == self.id, player_teams.c.is_coach == True)
        ]

    @property
    def recent_form(self):
        """Return a small HTML snippet representing the team's recent match outcomes."""
        last_five_matches = Match.query.filter(
            (Match.home_team_id == self.id) | (Match.away_team_id == self.id)
        ).order_by(Match.date.desc()).limit(5).all()

        form = []
        for match in last_five_matches:
            if match.home_team_score is not None and match.away_team_score is not None:
                if ((match.home_team_id == self.id and match.home_team_score > match.away_team_score) or
                    (match.away_team_id == self.id and match.away_team_score > match.home_team_score)):
                    form.append('<span style="color:green;">W</span>')
                elif match.home_team_score == match.away_team_score:
                    form.append('<span style="color:yellow;">D</span>')
                else:
                    form.append('<span style="color:red;">L</span>')
            else:
                form.append('<span style="color:gray;">N/A</span>')
        return ''.join(form)

    @property
    def top_scorer(self):
        top_scorer = db.session.query(
            Player, func.sum(PlayerSeasonStats.goals).label('total_goals')
        ).join(
            player_teams, Player.id == player_teams.c.player_id
        ).join(
            PlayerSeasonStats, Player.id == PlayerSeasonStats.player_id
        ).filter(
            player_teams.c.team_id == self.id
        ).group_by(Player.id).order_by(
            desc('total_goals')
        ).first()
        return f"{top_scorer[0].name} ({top_scorer[1]} goals)" if top_scorer and top_scorer[1] > 0 else "No data"

    @property
    def top_assist(self):
        top_assist = db.session.query(
            Player, func.sum(PlayerSeasonStats.assists).label('total_assists')
        ).join(
            player_teams, Player.id == player_teams.c.player_id
        ).join(
            PlayerSeasonStats, Player.id == PlayerSeasonStats.player_id
        ).filter(
            player_teams.c.team_id == self.id
        ).group_by(Player.id).order_by(
            desc('total_assists')
        ).first()
        return f"{top_assist[0].name} ({top_assist[1]} assists)" if top_assist and top_assist[1] > 0 else "No data"

    @property
    def avg_goals_per_match(self):
        total_goals = db.session.query(
            func.sum(PlayerSeasonStats.goals)
        ).join(
            Player, Player.id == PlayerSeasonStats.player_id
        ).join(
            player_teams, Player.id == player_teams.c.player_id
        ).filter(
            player_teams.c.team_id == self.id
        ).scalar() or 0

        matches_played = db.session.query(func.count(Match.id)).filter(
            or_(Match.home_team_id == self.id, Match.away_team_id == self.id)
        ).scalar() or 1

        return round(total_goals / matches_played, 2)

    @property
    def popover_content(self):
        return (
            f"<strong>Recent Form:</strong> {self.recent_form}<br>"
            f"<strong>Top Scorer:</strong> {self.top_scorer}<br>"
            f"<strong>Top Assist:</strong> {self.top_assist}<br>"
            f"<strong>Avg Goals/Match:</strong> {self.avg_goals_per_match}"
        )


class PlayerOrderHistory(db.Model):
    """Model to track a player's order history (e.g., WooCommerce orders)."""
    __tablename__ = 'player_order_history'

    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id', ondelete='CASCADE'), nullable=False)
    order_id = db.Column(db.String, nullable=False)
    season_id = db.Column(db.Integer, db.ForeignKey('season.id'), nullable=False)
    league_id = db.Column(db.Integer, db.ForeignKey('league.id'), nullable=False)
    profile_count = db.Column(db.Integer, default=1, nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp(), nullable=False)

    player = db.relationship('Player', back_populates='order_history')
    season = db.relationship('Season', backref='order_histories', lazy=True)
    league = db.relationship('League', backref='order_histories', lazy=True)

    def __repr__(self):
        return f'<PlayerOrderHistory {self.player_id} - Order {self.order_id} - Season {self.season_id} - League {self.league_id}>'


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


class Player(db.Model):
    """Model representing a player."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=True)
    is_phone_verified = db.Column(db.Boolean, default=False)
    sms_consent_given = db.Column(db.Boolean, default=False)
    sms_consent_timestamp = db.Column(db.DateTime)
    sms_opt_out_timestamp = db.Column(db.DateTime)
    jersey_size = db.Column(db.String(10), nullable=True)
    jersey_number = db.Column(db.Integer, nullable=True)
    is_coach = db.Column(db.Boolean, default=False)
    is_ref = db.Column(db.Boolean, default=False)
    is_sub = db.Column(db.Boolean, default=False)
    discord_id = db.Column(db.String(100), unique=True)
    needs_manual_review = db.Column(db.Boolean, default=False)
    linked_primary_player_id = db.Column(db.Integer, nullable=True)
    order_id = db.Column(db.String, nullable=True)
    events = db.relationship('PlayerEvent', back_populates='player', lazy=True, cascade='all, delete-orphan', passive_deletes=True)
    pronouns = db.Column(db.String(50), nullable=True)
    expected_weeks_available = db.Column(db.String(20), nullable=True)
    unavailable_dates = db.Column(db.Text, nullable=True)
    willing_to_referee = db.Column(db.Text, nullable=True)
    favorite_position = db.Column(db.Text, nullable=True)
    other_positions = db.Column(db.Text, nullable=True)
    positions_not_to_play = db.Column(db.Text, nullable=True)
    frequency_play_goal = db.Column(db.Text, nullable=True)
    additional_info = db.Column(db.Text, nullable=True)
    player_notes = db.Column(db.Text, nullable=True)
    team_swap = db.Column(db.String(10), nullable=True)
    teams = db.relationship('Team', secondary=player_teams, back_populates='players')
    primary_team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=True)
    primary_team = db.relationship('Team', foreign_keys=[primary_team_id])
    league_id = db.Column(db.Integer, db.ForeignKey('league.id'), nullable=True)
    league = db.relationship('League', back_populates='players', foreign_keys=[league_id])
    primary_league_id = db.Column(db.Integer, db.ForeignKey('league.id'), nullable=True)
    primary_league = db.relationship('League', back_populates='primary_players', foreign_keys=[primary_league_id])
    other_leagues = db.relationship('League', secondary='player_league', back_populates='other_players')
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    user = db.relationship('User', back_populates='player')
    availability = db.relationship('Availability', back_populates='player', lazy=True, cascade="all, delete-orphan", passive_deletes=True)
    attendance_stats = db.relationship('PlayerAttendanceStats', back_populates='player', uselist=False, cascade="all, delete-orphan")
    image_cache = db.relationship('PlayerImageCache', back_populates='player', uselist=False, cascade="all, delete-orphan")
    notes = db.Column(db.Text, nullable=True)
    is_current_player = db.Column(db.Boolean, default=False)
    profile_picture_url = db.Column(db.String(255), nullable=True)
    stat_change_logs = db.relationship('StatChangeLog', back_populates='player', cascade='all, delete-orphan', passive_deletes=True)
    stat_audits = db.relationship('PlayerStatAudit', back_populates='player', cascade='all, delete-orphan', passive_deletes=True)
    season_stats = db.relationship('PlayerSeasonStats', back_populates='player', passive_deletes=True)
    career_stats = db.relationship('PlayerCareerStats', back_populates='player', passive_deletes=True)
    order_history = db.relationship('PlayerOrderHistory', back_populates='player', cascade='all, delete')
    discord_roles = db.Column(JSON)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    discord_last_verified = db.Column(DateTime)
    discord_needs_update = db.Column(Boolean, default=False)
    discord_roles_synced = db.Column(db.Boolean, default=False)
    last_sync_attempt = db.Column(db.DateTime, nullable=True)
    season_assignments = relationship(
        'PlayerTeamSeason',
        back_populates='player',
        cascade='all, delete-orphan'
    )

    @property 
    def current_teams(self):
        """Return a list of tuples containing teams and associated coach status."""
        return [
            (team, is_coach) for team, is_coach in db.session.query(Team, player_teams.c.is_coach)
            .join(player_teams)
            .filter(player_teams.c.player_id == self.id)
        ]

    def get_all_teams(self, session=None):
        teams = []
        if self.primary_team:
            teams.append(self.primary_team)
    
        if self.is_coach and session:
            coached_team = session.query(Team).filter(
                Team.coach_id == self.id,
                Team.id != self.primary_team_id if self.primary_team_id else True
            ).first()
            if coached_team:
                teams.append(coached_team)
    
        return teams

    def to_dict(self, public=False):
        base_url = request.host_url.rstrip('/')
        default_image = f"{base_url}/static/img/default_player.png"
        
        data = {
            'id': self.id,
            'name': self.name,
            'team_id': self.primary_team_id,
            'is_coach': self.is_coach,
            'is_ref': self.is_ref,
            'jersey_number': self.jersey_number,
            'favorite_position': self.favorite_position,
            'profile_picture_url': f"{base_url}{self.profile_picture_url}" if self.profile_picture_url else default_image,
        }
        if not public:
            data.update({
                'phone': self.phone,
                'is_phone_verified': self.is_phone_verified,
                'jersey_size': self.jersey_size,
                'discord_id': self.discord_id,
                'pronouns': self.pronouns,
                'expected_weeks_available': self.expected_weeks_available,
                'unavailable_dates': self.unavailable_dates,
                'willing_to_referee': self.willing_to_referee,
                'other_positions': self.other_positions,
                'positions_not_to_play': self.positions_not_to_play,
                'frequency_play_goal': self.frequency_play_goal,
                'additional_info': self.additional_info,
                'league_id': self.league_id,
                'primary_league_id': self.primary_league_id,
                'user_id': self.user_id,
                'is_current_player': self.is_current_player,
            })
        return data

    def __repr__(self):
        return f'<Player {self.name} ({self.user.email})>'

    def get_season_stat(self, season_id, stat, session=None):
        season_stat = PlayerSeasonStats.query.filter_by(player_id=self.id, season_id=season_id).first()
        return getattr(season_stat, stat, 0) if season_stat else 0

    def season_goals(self, season_id):
        return self.get_season_stat(season_id, 'goals')

    def season_assists(self, season_id):
        return self.get_season_stat(season_id, 'assists')

    def season_yellow_cards(self, season_id):
        return self.get_season_stat(season_id, 'yellow_cards')

    def season_red_cards(self, season_id):
        return self.get_season_stat(season_id, 'red_cards')

    def update_season_stats(self, season_id, stats_changes, user_id):
        if not stats_changes:
            logger.warning(f"No stats changes provided for Player ID {self.id} in Season ID {season_id}.")
            return

        try:
            season_stats = PlayerSeasonStats.query.filter_by(player_id=self.id, season_id=season_id).first()
            if not season_stats:
                season_stats = PlayerSeasonStats(player_id=self.id, season_id=season_id)
                db.session.add(season_stats)

            for stat, increment in stats_changes.items():
                if hasattr(season_stats, stat):
                    current_value = getattr(season_stats, stat)
                    setattr(season_stats, stat, current_value + increment)
                    logger.debug(
                        f"Updated {stat} for Player ID {self.id} in Season ID {season_id}: "
                        f"{current_value} + {increment} = {current_value + increment}"
                    )
                    self.log_stat_change(stat, current_value, current_value + increment, 
                                         StatChangeType.EDIT.value, user_id, season_id)

            self.update_career_stats(stats_changes, user_id)
            logger.info(f"Player ID {self.id} stats updated for Season ID {season_id} by User ID {user_id}.")
        except Exception as e:
            logger.error(f"Error updating season stats: {str(e)}")
            raise

    def update_career_stats(self, stats_changes, user_id):
        if not stats_changes:
            logger.warning(f"No stats changes provided for Player ID {self.id} in Career Stats.")
            return

        try:
            if not self.career_stats:
                new_career_stats = PlayerCareerStats(player_id=self.id)
                db.session.add(new_career_stats)
                self.career_stats = [new_career_stats]
                db.session.flush()

            for stat, increment in stats_changes.items():
                if hasattr(self.career_stats[0], stat):
                    current_value = getattr(self.career_stats[0], stat)
                    setattr(self.career_stats[0], stat, current_value + increment)
                    logger.debug(
                        f"Updated {stat} for Player ID {self.id} in Career Stats: "
                        f"{current_value} + {increment} = {current_value + increment}"
                    )
                    self.log_stat_change(stat, current_value, current_value + increment, 
                                         StatChangeType.EDIT.value, user_id)
            
            logger.info(f"Player ID {self.id} career stats updated by User ID {user_id}.")
        except Exception as e:
            logger.error(f"Error updating career stats: {str(e)}")
            raise

    def log_stat_change(self, stat, old_value, new_value, change_type, user_id, season_id=None):
        if change_type not in [ct.value for ct in StatChangeType]:
            logger.warning(f"Invalid change type '{change_type}' for stat change logging.")
            return

        try:
            log_entry = StatChangeLog(
                player_id=self.id,
                stat=stat,
                old_value=old_value,
                new_value=new_value,
                change_type=change_type,
                user_id=user_id,
                season_id=season_id
            )
            db.session.add(log_entry)
            logger.info(
                f"Logged stat change for Player ID {self.id}: {stat} {change_type} "
                f"from {old_value} to {new_value} by User ID {user_id}."
            )
        except Exception as e:
            logger.error(f"Error logging stat change for Player ID {self.id}: {str(e)}")
            raise

    def get_career_goals(self, session=None):
        if self.career_stats:
            return sum(stat.goals for stat in self.career_stats if stat.goals)
        return 0

    def get_career_assists(self, session=None):
        if self.career_stats:
            return sum(stat.assists for stat in self.career_stats if stat.assists)
        return 0

    def get_career_yellow_cards(self, session=None):
        if self.career_stats:
            return sum(stat.yellow_cards for stat in self.career_stats if stat.yellow_cards)
        return 0

    def get_career_red_cards(self, session=None):
        if self.career_stats:
            return sum(stat.red_cards for stat in self.career_stats if stat.red_cards)
        return 0

    def get_all_matches(self, session=None):
        team_ids = [team.id for team in self.teams]
        return Match.query.filter(
            or_(Match.home_team_id.in_(team_ids), Match.away_team_id.in_(team_ids))
        ).all()

    def get_current_teams(self, with_coach_status=False):
        if with_coach_status:
            return [
                (team, is_coach) for team, is_coach in db.session.query(Team, player_teams.c.is_coach)
                .join(player_teams)
                .filter(player_teams.c.player_id == self.id)
            ]
        return self.teams

    def get_all_match_stats(self, session=None):
        return PlayerEvent.query.filter_by(player_id=self.id).all()


class Schedule(db.Model):
    """Model representing a schedule for matches."""
    id = db.Column(db.Integer, primary_key=True)
    week = db.Column(db.String(10), nullable=False)
    date = db.Column(db.Date, nullable=False)
    time = db.Column(db.Time, nullable=False)
    opponent = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    location = db.Column(db.String(100), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    season_id = db.Column(db.Integer, db.ForeignKey('season.id'))

    team = db.relationship('Team', foreign_keys=[team_id], back_populates='schedules', overlaps='matches')
    opponent_team = db.relationship('Team', foreign_keys=[opponent], back_populates='opponent_schedules', post_update=True)
    matches = db.relationship('Match', back_populates='schedule', lazy=True)
    season = db.relationship('Season')


class Match(db.Model):
    """Model representing a match between two teams."""
    __tablename__ = 'matches'
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
    schedule_id = db.Column(db.Integer, db.ForeignKey('schedule.id'), nullable=False)
    events = db.relationship('PlayerEvent', back_populates='match', lazy=True, cascade="all, delete-orphan")
    # Relationship with temporary sub assignments defined in TemporarySubAssignment model

    # Team verification fields
    home_team_verified = db.Column(db.Boolean, default=False)
    home_team_verified_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    home_team_verified_at = db.Column(db.DateTime, nullable=True)
    away_team_verified = db.Column(db.Boolean, default=False)
    away_team_verified_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    away_team_verified_at = db.Column(db.DateTime, nullable=True)

    home_team = db.relationship('Team', foreign_keys=[home_team_id], backref='home_matches')
    away_team = db.relationship('Team', foreign_keys=[away_team_id], backref='away_matches')
    schedule = db.relationship('Schedule', back_populates='matches')
    availability = db.relationship('Availability', back_populates='match', lazy=True, cascade="all, delete-orphan")
    ref_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=True)
    ref = db.relationship('Player', backref='assigned_matches')
    scheduled_messages = db.relationship('ScheduledMessage', back_populates='match')
    home_verifier = db.relationship('User', foreign_keys=[home_team_verified_by], backref=db.backref('home_verified_matches', lazy='dynamic'))
    away_verifier = db.relationship('User', foreign_keys=[away_team_verified_by], backref=db.backref('away_verified_matches', lazy='dynamic'))
    
    # Discord notification tracking
    last_discord_notification = db.Column(db.DateTime, nullable=True)
    notification_status = db.Column(db.String(50), nullable=True)
    last_notification_state_hash = db.Column(db.String(64), nullable=True)

    def to_dict(self, include_teams=False, include_events=False):
        data = {
            'id': self.id,
            'date': self.date.isoformat() if self.date else None,
            'time': self.time.isoformat() if self.time else None,
            'location': self.location,
            'home_team_id': self.home_team_id,
            'away_team_id': self.away_team_id,
            'home_team_score': self.home_team_score,
            'away_team_score': self.away_team_score,
            'notes': self.notes,
            'schedule_id': self.schedule_id,
            'ref_id': self.ref_id,
            'reported': self.reported,
            'home_team_verified': self.home_team_verified,
            'away_team_verified': self.away_team_verified,
            'fully_verified': self.fully_verified,
        }
        if include_teams:
            data['home_team'] = self.home_team.to_dict()
            data['away_team'] = self.away_team.to_dict()
        if include_events:
            data['events'] = [event.to_dict() for event in self.events]
        return data

    @property
    def reported(self):
        """Determine if the match has been reported based on scores."""
        return (
            self.home_team_score is not None and
            self.away_team_score is not None
        )
        
    @property
    def fully_verified(self):
        """Determine if the match has been verified by both teams."""
        return self.home_team_verified and self.away_team_verified
        
    def get_verification_status(self):
        """Get a detailed verification status for the match."""
        return {
            'reported': self.reported,
            'home_team_verified': self.home_team_verified,
            'away_team_verified': self.away_team_verified,
            'fully_verified': self.fully_verified,
            'home_verifier': self.home_verifier.username if self.home_verifier else None,
            'away_verifier': self.away_verifier.username if self.away_verifier else None,
            'home_verified_at': self.home_team_verified_at.isoformat() if self.home_team_verified_at else None,
            'away_verified_at': self.away_team_verified_at.isoformat() if self.away_team_verified_at else None,
        }

    def get_opponent_name(self, player):
        player_team_ids = [team.id for team in player.teams]
        if self.home_team_id in player_team_ids:
            return self.away_team.name
        elif self.away_team_id in player_team_ids:
            return self.home_team.name
        return None


class PlayerSeasonStats(db.Model):
    """Model for storing a player's season statistics."""
    __tablename__ = 'player_season_stats'
    
    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id', ondelete='CASCADE'), nullable=False)
    season_id = db.Column(db.Integer, db.ForeignKey('season.id'), nullable=False)
    goals = db.Column(db.Integer, default=0, nullable=False)
    assists = db.Column(db.Integer, default=0, nullable=False)
    yellow_cards = db.Column(db.Integer, default=0, nullable=False)
    red_cards = db.Column(db.Integer, default=0, nullable=False)

    player = db.relationship('Player', back_populates='season_stats')
    season = db.relationship('Season', back_populates='player_stats')
    teams = db.relationship(
        'Team',
        secondary=player_teams,
        primaryjoin="PlayerSeasonStats.player_id==player_teams.c.player_id",
        secondaryjoin="Team.id==player_teams.c.team_id",
        viewonly=True
    )

    def to_dict(self, session=None):
        return {
            'id': self.id,
            'player_id': self.player_id,
            'season_id': self.season_id,
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
        return db.session.query(cls).join(Player).join(player_teams).filter(
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
        return db.session.query(
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

# Listen for goal difference updates
event.listen(Standings, 'before_insert', Standings.update_goal_difference)
event.listen(Standings, 'before_update', Standings.update_goal_difference)


class Availability(db.Model):
    """Model representing a player's availability for a match."""
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('matches.id'), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id', ondelete='CASCADE'), nullable=True)
    discord_id = db.Column(db.String(100), nullable=False)
    response = db.Column(db.String(20), nullable=False)
    responded_at = db.Column(db.DateTime, default=datetime.utcnow)
    match = db.relationship('Match', back_populates='availability')
    player = db.relationship('Player', back_populates='availability')

    def to_dict(self, session=None):
        return {
            'id': self.id,
            'match_id': self.match_id,
            'player_id': self.player_id,
            'discord_id': self.discord_id,
            'response': self.response,
            'responded_at': self.responded_at.isoformat() if self.responded_at else None,
        }


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
            db.session.add(stats)
        return stats
    
    def update_stats(self, session=None):
        """Recalculate all statistics from availability data."""
        if session is None:
            session = db.session
            
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


class PlayerImageCache(db.Model):
    """Cached and optimized player profile images for fast loading."""
    __tablename__ = 'player_image_cache'
    
    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id', ondelete='CASCADE'), nullable=False, unique=True)
    
    # Image URLs
    original_url = db.Column(db.String(500))
    cached_url = db.Column(db.String(500))
    thumbnail_url = db.Column(db.String(500))
    webp_url = db.Column(db.String(500))
    
    # Image properties
    file_size = db.Column(db.Integer, default=0)
    width = db.Column(db.Integer, default=0)
    height = db.Column(db.Integer, default=0)
    format = db.Column(db.String(10), default='jpg')
    
    # Cache management
    cache_status = db.Column(db.String(20), default='pending')  # pending, processing, ready, failed
    last_cached = db.Column(db.DateTime, default=datetime.utcnow)
    cache_expiry = db.Column(db.DateTime)
    
    # Performance optimization
    is_optimized = db.Column(db.Boolean, default=False)
    optimization_level = db.Column(db.Integer, default=1)  # 1=basic, 2=medium, 3=aggressive
    
    # Relationships
    player = db.relationship('Player', back_populates='image_cache')
    
    def to_dict(self):
        return {
            'player_id': self.player_id,
            'thumbnail_url': self.thumbnail_url,
            'cached_url': self.cached_url,
            'webp_url': self.webp_url,
            'is_optimized': self.is_optimized,
            'file_size': self.file_size,
            'cache_status': self.cache_status
        }


class Notification(db.Model):
    """Model representing a system notification for a user."""
    __tablename__ = 'notifications'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    content = db.Column(db.String(255), nullable=False)
    notification_type = db.Column(db.String(50), nullable=False, default='system')
    icon = db.Column(db.String(50), nullable=True)
    read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship('User', back_populates='notifications')

    def icon_class(self):
        if self.icon:
            return self.icon
        icon_mapping = {
            'warning': 'ti ti-alert-triangle',
            'error': 'ti ti-alert-circle',
            'info': 'ti ti-info-circle',
            'success': 'ti ti-check-circle',
            'system': 'ti ti-bell'
        }
        return icon_mapping.get(self.notification_type, 'ti-bell')


class Announcement(db.Model):
    """Model representing an announcement."""
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    position = db.Column(db.Integer, default=0)


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


class Feedback(db.Model):
    """Model representing user feedback."""
    __tablename__ = 'feedback'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    name = db.Column(db.String(150), nullable=True)
    category = db.Column(db.String(50), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=False)
    priority = db.Column(db.String(20), default='Low')
    status = db.Column(db.String(20), default='Open')
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    closed_at = db.Column(db.DateTime, nullable=True)
    
    user = db.relationship('User', back_populates='feedbacks')
    notes = db.relationship('Note', back_populates='feedback', cascade='all, delete-orphan', lazy=True)
    replies = db.relationship('FeedbackReply', back_populates='feedback', cascade='all, delete-orphan', lazy=True)

    def __repr__(self):
        return f'<Feedback {self.id} - {self.title}>'

    @classmethod
    def delete_old_closed_tickets(cls):
        try:
            thirty_days_ago = datetime.utcnow() - timedelta(days=30)
            old_closed_tickets = cls.query.filter(cls.closed_at <= thirty_days_ago).all()
            for ticket in old_closed_tickets:
                db.session.delete(ticket)
            logger.info(f"Successfully deleted old closed tickets older than {thirty_days_ago}")
        except Exception as e:
            logger.error(f"Error deleting old closed tickets: {str(e)}")
            raise


class FeedbackReply(db.Model):
    """Model representing a reply to a feedback ticket."""
    __tablename__ = 'feedback_replies'

    id = db.Column(db.Integer, primary_key=True)
    feedback_id = db.Column(db.Integer, db.ForeignKey('feedback.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    is_admin_reply = db.Column(db.Boolean, default=False)

    feedback = db.relationship('Feedback', back_populates='replies')
    user = db.relationship('User', back_populates='feedback_replies')

    def __repr__(self):
        return f'<FeedbackReply {self.id} for Feedback {self.feedback_id}>'


class Note(db.Model):
    """Model representing a note attached to a feedback ticket."""
    __tablename__ = 'notes'

    id = db.Column(db.Integer, primary_key=True)
    feedback_id = db.Column(db.Integer, db.ForeignKey('feedback.id'), nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp(), nullable=False)

    feedback = db.relationship('Feedback', back_populates='notes')
    author = db.relationship('User', back_populates='notes')

    def __repr__(self):
        return f'<Note {self.id} by {self.author.username}>'


class ScheduledMessage(db.Model):
    """Model representing a scheduled message for a match."""
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('matches.id'), nullable=False)
    scheduled_send_time = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), default='PENDING')
    home_channel_id = db.Column(db.String(20), nullable=True)
    home_message_id = db.Column(db.String(20), nullable=True)
    away_channel_id = db.Column(db.String(20), nullable=True)
    away_message_id = db.Column(db.String(20), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    match = db.relationship('Match', back_populates='scheduled_messages')


class Token(db.Model):
    """Model representing a token for player operations (e.g., password reset)."""
    __tablename__ = 'tokens'

    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id', ondelete='CASCADE'), nullable=False)
    token = db.Column(db.String(32), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False, nullable=False)

    player = db.relationship('Player', backref=db.backref('tokens', lazy=True))

    def __init__(self, player_id, token, expires_at=None):
        self.player_id = player_id
        self.token = token
        self.created_at = datetime.utcnow()
        self.expires_at = expires_at or (self.created_at + timedelta(hours=24))

    def __repr__(self):
        return f'<Token {self.token} for player {self.player_id}>'

    @property
    def is_expired(self):
        return datetime.utcnow() > self.expires_at

    @property
    def is_valid(self):
        return not self.is_expired and not self.used

    def invalidate(self):
        try:
            self.used = True
            logger.info(f"Token {self.token} for player {self.player_id} invalidated")
        except Exception as e:
            logger.error(f"Error invalidating token {self.token} for player {self.player_id}: {str(e)}")
            raise


class MLSMatch(db.Model):
    """Model representing an MLS match with additional details."""
    __tablename__ = 'mls_matches'

    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.String, unique=True, nullable=False)
    opponent = db.Column(db.String(100), nullable=False)
    date_time = db.Column(db.DateTime(timezone=True), nullable=False)
    is_home_game = db.Column(db.Boolean, nullable=False)
    summary_link = db.Column(db.String(200))
    stats_link = db.Column(db.String(200))
    commentary_link = db.Column(db.String(200))
    venue = db.Column(db.String(100))
    competition = db.Column(db.String(50))
    thread_creation_time = db.Column(db.DateTime(timezone=True))
    thread_created = db.Column(db.Boolean, default=False)
    discord_thread_id = db.Column(db.String)
    thread_creation_scheduled = db.Column(db.Boolean, default=False)
    thread_creation_task_id = db.Column(db.String(100))
    last_thread_scheduling_attempt = db.Column(db.DateTime)
    live_reporting_scheduled = db.Column(db.Boolean, default=False)
    live_reporting_started = db.Column(db.Boolean, default=False)
    live_reporting_status = db.Column(db.String(20), default='not_started')
    live_reporting_task_id = db.Column(db.String(50))
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.date_time and not self.thread_creation_time:
            self.thread_creation_time = self.date_time - timedelta(hours=24)

    def __repr__(self):
        return f'<MLSMatch {self.match_id}: {self.opponent} on {self.date_time}>'


class PlayerTeamSeason(db.Model):
    """Model linking a player, team, and season for assignments."""
    __tablename__ = 'player_team_season'

    id = Column(Integer, primary_key=True)
    player_id = Column(Integer, ForeignKey('player.id', ondelete='CASCADE'), nullable=False)
    team_id = Column(Integer, ForeignKey('team.id', ondelete='CASCADE'), nullable=False)
    season_id = Column(Integer, ForeignKey('season.id', ondelete='CASCADE'), nullable=False)

    player = relationship('Player', back_populates='season_assignments')
    team = relationship('Team', back_populates='season_assignments')
    season = relationship('Season', back_populates='player_assignments')

    def __repr__(self):
        return f'<PlayerTeamSeason player={self.player_id} team={self.team_id} season={self.season_id}>'


class PlayerTeamHistory(db.Model):
    """Model for tracking the history of player-team associations."""
    __tablename__ = 'player_team_history'
    
    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'))
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'))
    joined_date = db.Column(db.DateTime, default=datetime.utcnow)
    left_date = db.Column(db.DateTime, nullable=True)
    is_coach = db.Column(db.Boolean, default=False)
    
    player = db.relationship('Player', backref='team_history')
    team = db.relationship('Team', backref='player_history')


class Progress(db.Model):
    """Model representing the progress of a task."""
    __tablename__ = 'progress'
    
    task_id = db.Column(db.String(50), primary_key=True)
    stage = db.Column(db.String(50), nullable=False)
    message = db.Column(db.String(255))
    progress = db.Column(db.Integer)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class HelpTopic(db.Model):
    """Model representing a help topic."""
    __tablename__ = 'help_topics'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    markdown_content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    allowed_roles = db.relationship('Role', secondary=help_topic_roles, backref=db.backref('help_topics', lazy='dynamic'))

    def __repr__(self):
        return f'<HelpTopic {self.title}>'

class Prediction(db.Model):
    """Model representing a user's prediction for a match."""
    __tablename__ = 'predictions'
    
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.String, nullable=False)
    discord_user_id = db.Column(db.String, nullable=False)
    home_score = db.Column(db.Integer, nullable=False)
    opponent_score = db.Column(db.Integer, nullable=False)
    is_correct = db.Column(db.Boolean, default=None)
    season_correct_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Prediction {self.match_id} by {self.discord_user_id}>"


class TemporarySubAssignment(db.Model):
    """Model representing a temporary substitute assignment for a match."""
    __tablename__ = 'temporary_sub_assignments'
    
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('matches.id', ondelete='CASCADE'), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id', ondelete='CASCADE'), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id', ondelete='CASCADE'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    assigned_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Define relationships
    match = db.relationship('Match', backref=db.backref('temp_sub_assignments', lazy='dynamic'))
    player = db.relationship('Player', backref=db.backref('temp_sub_assignments', lazy='dynamic'))
    team = db.relationship('Team', backref=db.backref('temp_sub_assignments', lazy='dynamic'))
    assigner = db.relationship('User', backref=db.backref('assigned_subs', lazy='dynamic'))
    
    __table_args__ = (
        db.UniqueConstraint('match_id', 'player_id', name='uq_temp_sub_match_player'),
    )
    
    def __repr__(self):
        return f"<TemporarySubAssignment: {self.player_id} for {self.team_id} in match {self.match_id}>"


class SubRequest(db.Model):
    """Model representing a substitute request from a coach."""
    __tablename__ = 'sub_requests'
    
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('matches.id', ondelete='CASCADE'), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id', ondelete='CASCADE'), nullable=False)
    requested_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    status = db.Column(db.String(20), default='PENDING')  # PENDING, APPROVED, DECLINED, FULFILLED
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    fulfilled_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    
    # Define relationships
    match = db.relationship('Match', backref=db.backref('sub_requests', lazy='dynamic'))
    team = db.relationship('Team', backref=db.backref('sub_requests', lazy='dynamic'))
    requester = db.relationship('User', foreign_keys=[requested_by], backref=db.backref('requested_subs', lazy='dynamic'))
    fulfiller = db.relationship('User', foreign_keys=[fulfilled_by], backref=db.backref('fulfilled_sub_requests', lazy='dynamic'))
    
    __table_args__ = (
        db.UniqueConstraint('match_id', 'team_id', name='uq_sub_req_match_team'),
    )
    
    def __repr__(self):
        return f"<SubRequest: {self.team_id} in match {self.match_id}, status: {self.status}>"