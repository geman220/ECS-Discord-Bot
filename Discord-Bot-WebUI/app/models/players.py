# app/models/players.py

"""
Player and Team Models Module

This module contains models related to players and teams:
- Team: Team entity
- Player: Player entity
- PlayerOrderHistory: Player order tracking
- PlayerTeamSeason: Player-team assignments per season
- PlayerTeamHistory: Historical team assignments
- PlayerImageCache: Cached player images
"""

import logging
from datetime import datetime
from flask import request, g
from sqlalchemy import JSON, DateTime, Boolean, or_
from sqlalchemy.orm import relationship

# Single source of truth for position display (slug -> label) on API output.
from app.constants.positions import label_for as _pos_label, to_label_array as _pos_label_array

from app.core import db

logger = logging.getLogger(__name__)

# Import Match model for team recent_form and player methods
from app.models.matches import Match

# Association table for many-to-many relationship between Player and League (secondary leagues)
player_league = db.Table(
    'player_league',
    db.Column('player_id', db.Integer, db.ForeignKey('player.id'), primary_key=True),
    db.Column('league_id', db.Integer, db.ForeignKey('league.id'), primary_key=True),
    db.Index('idx_player_league_league_id', 'league_id')
)

# Association table for many-to-many relationship between Player and Team
player_teams = db.Table(
    'player_teams',
    db.Column('player_id', db.Integer, db.ForeignKey('player.id', ondelete='CASCADE'), primary_key=True),
    db.Column('team_id', db.Integer, db.ForeignKey('team.id', ondelete='CASCADE'), primary_key=True),
    db.Column('is_coach', db.Boolean, default=False),
    db.Column('position', db.String(20), default='bench'),
    # Composite PK leads with player_id, so team_id needs its own index for
    # roster/standings joins that group or filter by team.
    db.Index('idx_player_teams_team_id', 'team_id'),
)


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
    background_position = db.Column(db.String(50), nullable=True, default='center')
    background_size = db.Column(db.String(50), nullable=True, default='cover')
    is_active = db.Column(db.Boolean, default=True, nullable=False)

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
            player for player, is_coach in g.db_session.query(Team, player_teams.c.is_coach)
            .join(player_teams)
            .filter(player_teams.c.team_id == self.id, player_teams.c.is_coach == True)
        ]

    @property
    def recent_form(self):
        """Return a small HTML snippet representing the team's recent match outcomes.

        Served from the bulk stats cache, like top_scorer / top_assist. This used to
        run its own `Match.query` on every access — and to_dict() reads it, so a list
        of 25 teams fired 25 extra queries. It also used Model.query, which binds to
        db.session rather than the request's session, so it checked out a SECOND
        pooled connection on top. Both problems disappear by reading the cache that
        the other three stat properties already use.
        """
        from app.team_performance_helpers import get_team_stats_cached
        stats = get_team_stats_cached(self.id)
        return stats.get('recent_form', '')

    @property
    def top_scorer(self):
        from app.team_performance_helpers import get_team_stats_cached
        stats = get_team_stats_cached(self.id)
        return stats['top_scorer']

    @property
    def top_assist(self):
        from app.team_performance_helpers import get_team_stats_cached
        stats = get_team_stats_cached(self.id)
        return stats['top_assist']

    @property
    def avg_goals_per_match(self):
        from app.team_performance_helpers import get_team_stats_cached
        stats = get_team_stats_cached(self.id)
        return stats['avg_goals_per_match']

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
    __table_args__ = (
        db.Index('idx_player_order_history_player_id', 'player_id'),
    )

    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id', ondelete='CASCADE'), nullable=False)
    order_id = db.Column(db.String, nullable=False)
    season_id = db.Column(db.Integer, db.ForeignKey('season.id'), nullable=False)
    league_id = db.Column(db.Integer, db.ForeignKey('league.id'), nullable=False)
    profile_count = db.Column(db.Integer, default=1, nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp(), nullable=False)

    # passive_deletes=True trusts DB's ON DELETE CASCADE
    player = db.relationship('Player', back_populates='order_history', passive_deletes=True)
    season = db.relationship('Season', backref='order_histories', lazy=True)
    league = db.relationship('League', backref='order_histories', lazy=True)

    def __repr__(self):
        return f'<PlayerOrderHistory {self.player_id} - Order {self.order_id} - Season {self.season_id} - League {self.league_id}>'


class Player(db.Model):
    """Model representing a player."""
    __tablename__ = 'player'
    __table_args__ = (
        db.Index('idx_player_user_id', 'user_id'),
        db.Index('idx_player_primary_league_id', 'primary_league_id'),
    )

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    is_phone_verified = db.Column(db.Boolean, default=False)
    
    # Encrypted PII fields
    encrypted_phone = db.Column(db.Text, nullable=True)
    phone_hash = db.Column(db.String(64), nullable=True, index=True)  # For searching encrypted phones
    sms_consent_given = db.Column(db.Boolean, default=False)
    sms_consent_timestamp = db.Column(db.DateTime)
    sms_opt_out_timestamp = db.Column(db.DateTime)
    # Liability waiver / terms-of-participation acceptance audit trail. Set once
    # at registration when the player checks the waiver box; null = never accepted.
    terms_accepted_at = db.Column(db.DateTime, nullable=True)
    jersey_size = db.Column(db.String(10), nullable=True)
    jersey_number = db.Column(db.Integer, nullable=True)
    is_coach = db.Column(db.Boolean, default=False)
    is_ref = db.Column(db.Boolean, default=False)
    is_available_for_ref = db.Column(db.Boolean, default=True)
    is_sub = db.Column(db.Boolean, default=False)
    interested_in_sub = db.Column(db.Boolean, default=False)
    discord_id = db.Column(db.String(100), unique=True)
    discord_username = db.Column(db.String(150), nullable=True)
    discord_in_server = db.Column(db.Boolean, nullable=True)
    discord_last_checked = db.Column(db.DateTime, nullable=True)
    needs_manual_review = db.Column(db.Boolean, default=False)
    linked_primary_player_id = db.Column(db.Integer, nullable=True)
    order_id = db.Column(db.String, nullable=True)
    events = db.relationship('PlayerEvent', back_populates='player', lazy=True, cascade='all, delete-orphan', passive_deletes=True)
    pronouns = db.Column(db.String(50), nullable=True)
    date_of_birth = db.Column(db.Date, nullable=True)
    # iSpy consent: opt-out hides this player from iSpy target search and blocks
    # tagging in submissions. Defaults False (opt-in by default).
    ispy_opt_out = db.Column(db.Boolean, default=False, nullable=False)
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
    admin_notes = db.relationship('PlayerAdminNote', back_populates='player', cascade='all, delete-orphan', passive_deletes=True, order_by='desc(PlayerAdminNote.created_at)')
    notes = db.Column(db.Text, nullable=True)  # DEPRECATED: Use admin_notes relationship instead
    is_current_player = db.Column(db.Boolean, default=False)
    profile_picture_url = db.Column(db.String(255), nullable=True)
    stat_change_logs = db.relationship('StatChangeLog', back_populates='player', cascade='all, delete-orphan', passive_deletes=True)
    stat_audits = db.relationship('PlayerStatAudit', back_populates='player', cascade='all, delete-orphan', passive_deletes=True)
    season_stats = db.relationship('PlayerSeasonStats', back_populates='player', passive_deletes=True)
    career_stats = db.relationship('PlayerCareerStats', back_populates='player', passive_deletes=True)
    order_history = db.relationship('PlayerOrderHistory', back_populates='player', cascade='all, delete')
    discord_roles = db.Column(JSON)
    # When this player record was first created (i.e. when they joined). Backfilled
    # from the associated user's created_at for pre-existing rows; new rows default
    # to insert time. Surfaced as the "Joined" date on the player profile.
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=True)
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
    # NOTE: intentionally NO onupdate= here. This timestamp must reflect only
    # explicit profile edits/verifications (set directly in the profile routes),
    # NOT incidental row writes. With onupdate, every login bumped this via the
    # Discord status sync (check_discord_status -> discord_last_checked), which
    # falsely showed "Last Updated: today" and defeated the 5-month review-due alert.
    profile_last_updated = db.Column(db.DateTime, default=datetime.utcnow)
    last_known_emails = db.Column(db.Text, nullable=True)
    merge_history = db.Column(db.Text, nullable=True)
    # DEPRECATED: Use is_phone_verified instead. This field is unused and will be
    # removed in a future migration. See is_phone_verified (line 172) for the
    # authoritative phone verification status field.
    verified_phone = db.Column(db.Boolean, default=False)

    @property
    def email(self):
        """Get email from associated user."""
        return self.user.email if self.user else None

    @email.setter
    def email(self, value):
        """Set email on associated user."""
        if self.user:
            self.user.email = value

    @property 
    def current_teams(self):
        """Return a list of tuples containing teams and associated coach status."""
        return [
            (team, is_coach) for team, is_coach in g.db_session.query(Team, player_teams.c.is_coach)
            .join(player_teams)
            .filter(player_teams.c.player_id == self.id)
        ]

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
            # Positions are stored as canonical slugs; present display labels so
            # API clients (incl. the Flutter app) keep receiving human-readable
            # values. See app/constants/positions.py.
            'favorite_position': _pos_label(self.favorite_position),
            'profile_picture_url': f"{base_url}{self.profile_picture_url}" if self.profile_picture_url else default_image,
        }
        if not public:
            data.update({
                'phone': self.phone,
                'is_phone_verified': self.is_phone_verified,
                'jersey_size': self.jersey_size,
                'discord_id': self.discord_id,
                'discord_username': self.discord_username,
                'discord_in_server': self.discord_in_server,
                'discord_last_checked': self.discord_last_checked,
                'pronouns': self.pronouns,
                'expected_weeks_available': self.expected_weeks_available,
                'unavailable_dates': self.unavailable_dates,
                'willing_to_referee': self.willing_to_referee,
                'other_positions': _pos_label_array(self.other_positions),
                'positions_not_to_play': _pos_label_array(self.positions_not_to_play),
                'frequency_play_goal': self.frequency_play_goal,
                'additional_info': self.additional_info,
                'league_id': self.league_id,
                'primary_league_id': self.primary_league_id,
                'user_id': self.user_id,
                'is_current_player': self.is_current_player,
            })
        return data

    @property
    def phone(self):
        """Get decrypted phone."""
        if self.encrypted_phone:
            from app.utils.pii_encryption import decrypt_value
            return decrypt_value(self.encrypted_phone)
        return None

    @phone.setter
    def phone(self, value):
        """Set encrypted phone."""
        if value:
            from app.utils.pii_encryption import encrypt_value, create_hash
            self.encrypted_phone = encrypt_value(value)
            self.phone_hash = create_hash(value)
        else:
            self.encrypted_phone = None
            self.phone_hash = None

    def __repr__(self):
        user_email = self.user.email if self.user else "No User"
        return f'<Player {self.name} ({user_email})>'

    def get_season_stat(self, season_id, stat, session=None):
        """Read a season stat from the ALREADY-LOADED season_stats relationship.

        This used to run `PlayerSeasonStats.query.filter_by(...).first()` on every
        single call, with no memoisation. The player profile renders the same four
        stats in up to four separate blocks — sixteen identical queries for ONE player
        — and the route already `selectinload`s player.season_stats, so the rows were
        sitting in memory the whole time. team_details paid two per player, ~30 on a
        roster.

        Reading the relationship costs zero queries when it's eager-loaded, and at
        worst ONE lazy load per player (not per stat). It also drops a second pooled
        connection: Model.query binds to db.session, not the request's session.

        `session` is accepted for backwards compatibility and no longer used.
        """
        for season_stat in (self.season_stats or []):
            if season_stat.season_id == season_id:
                return getattr(season_stat, stat, 0)
        return 0

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
            from app.models.stats import PlayerSeasonStats, StatChangeType
            season_stats = PlayerSeasonStats.query.filter_by(player_id=self.id, season_id=season_id).first()
            if not season_stats:
                season_stats = PlayerSeasonStats(player_id=self.id, season_id=season_id)
                g.db_session.add(season_stats)

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
            from app.models.stats import PlayerCareerStats, StatChangeType
            if not self.career_stats:
                new_career_stats = PlayerCareerStats(player_id=self.id)
                g.db_session.add(new_career_stats)
                self.career_stats = [new_career_stats]
                g.db_session.flush()

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
        from app.models.stats import StatChangeLog, StatChangeType
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
            g.db_session.add(log_entry)
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
                (team, is_coach) for team, is_coach in g.db_session.query(Team, player_teams.c.is_coach)
                .join(player_teams)
                .filter(player_teams.c.player_id == self.id)
            ]
        return self.teams

    def get_all_match_stats(self, session=None):
        from app.models.stats import PlayerEvent
        return PlayerEvent.query.filter_by(player_id=self.id).all()

    def check_discord_status(self, fast_fail: bool = False):
        """
        Check if player is in Discord server and update username via Discord bot API.

        Args:
            fast_fail: If True, use shorter timeout and skip if service is unavailable.
                       Use this for web request contexts to avoid blocking page loads.
        """
        if not self.discord_id:
            return False

        try:
            import os
            from web_config import Config
            from app.utils.sync_discord_client import get_sync_discord_client, is_discord_service_available

            # Check circuit breaker first in fast_fail mode
            if fast_fail and not is_discord_service_available():
                logger.debug(f"Skipping Discord check for player {self.id} - service unavailable")
                return False

            guild_id = os.getenv('SERVER_ID')
            bot_api_url = Config.BOT_API_URL

            if not guild_id or not bot_api_url:
                logger.warning("Server ID or Bot API URL not configured")
                return False

            # Check Discord member status via synchronous Discord client
            discord_client = get_sync_discord_client()

            # Check if user is in Discord server
            member_check = discord_client.check_member_in_server(guild_id, self.discord_id, fast_fail=fast_fail)

            if member_check.get('success'):
                # Update player information from Discord response
                self.discord_in_server = member_check.get('in_server', False)

                # If we got member data, update username
                member_data = member_check.get('member_data', {})
                if member_data:
                    if member_data.get('username'):
                        self.discord_username = member_data.get('username')
                    elif member_data.get('display_name'):
                        self.discord_username = member_data.get('display_name')

                self.discord_last_checked = datetime.utcnow()
                return True
            else:
                # API call failed - check if it was due to circuit breaker
                if member_check.get('circuit_breaker'):
                    logger.debug(f"Discord check skipped for user {self.discord_id} - circuit breaker open")
                else:
                    logger.warning(f"Discord bot API failed to check status for user {self.discord_id}")
                return False

        except Exception as e:
            logger.error(f"Error checking Discord status for player {self.id}: {str(e)}")
            return False


class PlayerTeamSeason(db.Model):
    """Model linking a player, team, and season for assignments."""
    __tablename__ = 'player_team_season'
    __table_args__ = (
        # (player_id, team_id) is already covered by player_team_season_unique's
        # leading columns; only season_id needs its own index.
        db.Index('idx_player_team_season_season_id', 'season_id'),
    )

    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id', ondelete='CASCADE'), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id', ondelete='CASCADE'), nullable=False)
    season_id = db.Column(db.Integer, db.ForeignKey('season.id', ondelete='CASCADE'), nullable=False)
    # Durable per-season snapshot of whether this player COACHED this team that
    # season. player_teams.is_coach is wiped at rollover, so this is the only
    # historical record of season-specific coaching. Finalized at rollover from
    # the season's final player_teams.is_coach; set best-effort at draft time.
    is_coach = db.Column(db.Boolean, nullable=False, default=False, server_default='false')

    # passive_deletes=True trusts DB's ON DELETE CASCADE
    player = db.relationship('Player', back_populates='season_assignments', passive_deletes=True)
    team = db.relationship('Team', back_populates='season_assignments', passive_deletes=True)
    season = db.relationship('Season', back_populates='player_assignments', passive_deletes=True)

    def __repr__(self):
        return f'<PlayerTeamSeason player={self.player_id} team={self.team_id} season={self.season_id}>'


class PlayerTeamHistory(db.Model):
    """Model for tracking the history of player-team associations."""
    __tablename__ = 'player_team_history'
    __table_args__ = (
        db.Index('idx_player_team_history_player_id_joined_date', 'player_id', db.text('joined_date DESC')),
    )

    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'))
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'))
    joined_date = db.Column(db.DateTime, default=datetime.utcnow)
    left_date = db.Column(db.DateTime, nullable=True)
    is_coach = db.Column(db.Boolean, default=False)
    
    player = db.relationship('Player', backref='team_history')
    team = db.relationship('Team', backref='player_history')


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
    
    # Relationships - passive_deletes=True trusts DB's ON DELETE CASCADE
    player = db.relationship('Player', back_populates='image_cache', passive_deletes=True)
    
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


def add_player_to_team(player, team, session, position='bench'):
    """
    Add player to team, preserving coach status from Player.is_coach.

    This function ensures that when a player is added to a team, their coach
    status is properly reflected in the player_teams association table. This
    prevents the bug where player_teams.is_coach defaults to FALSE even when
    Player.is_coach is TRUE.

    Args:
        player: Player object to add to the team
        team: Team object to add the player to
        session: Database session for executing the insert
        position: Player position on the team (default: 'bench')

    Returns:
        True if the player was added, False if already on the team
    """
    from sqlalchemy import insert
    from sqlalchemy.exc import IntegrityError

    # Check if player is already on the team
    existing = session.execute(
        player_teams.select().where(
            player_teams.c.player_id == player.id,
            player_teams.c.team_id == team.id
        )
    ).fetchone()

    if existing:
        # Player already on team - update coach status if needed
        if existing.is_coach != player.is_coach:
            session.execute(
                player_teams.update().where(
                    player_teams.c.player_id == player.id,
                    player_teams.c.team_id == team.id
                ).values(is_coach=player.is_coach)
            )
        return False

    try:
        session.execute(
            insert(player_teams).values(
                player_id=player.id,
                team_id=team.id,
                is_coach=player.is_coach,  # Preserve coach status from Player model
                position=position
            )
        )
        return True
    except IntegrityError:
        # Race condition - player was added by another transaction
        return False


class PlayerAdminNote(db.Model):
    """
    Admin/coach notes about a prospect, with author attribution.

    A note targets EITHER a player (self-signup, has an account) OR a quick profile
    (admin-made walk-in, no account yet) — the two intakes into the same "waiting
    room" of not-yet-approved prospects. Exactly one of player_id / quick_profile_id
    is set (enforced by a DB CHECK). When a quick profile is claimed, its notes are
    re-pointed to the new player so the history follows the prospect.

    Visible only to coaches/admins. Each note tracks who created it and when.
    """
    __tablename__ = 'player_admin_note'
    __table_args__ = (
        db.CheckConstraint(
            '(player_id IS NOT NULL AND quick_profile_id IS NULL)'
            ' OR (player_id IS NULL AND quick_profile_id IS NOT NULL)',
            name='ck_player_admin_note_one_target'
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    # Exactly one target is set. Both nullable at the column level; the CHECK above
    # guarantees exactly-one so a note is never orphaned or double-targeted.
    player_id = db.Column(db.Integer, db.ForeignKey('player.id', ondelete='CASCADE'), nullable=True, index=True)
    quick_profile_id = db.Column(db.Integer, db.ForeignKey('quick_profile.id', ondelete='CASCADE'), nullable=True, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships - passive_deletes=True trusts DB's ON DELETE CASCADE
    player = db.relationship('Player', back_populates='admin_notes', passive_deletes=True)
    quick_profile = db.relationship('QuickProfile', foreign_keys=[quick_profile_id], passive_deletes=True)
    author = db.relationship('User', foreign_keys=[author_id])

    def to_dict(self, include_author=True):
        """
        Convert to dictionary for API responses.

        Args:
            include_author: Include author details (default True)
        """
        data = {
            'id': self.id,
            'player_id': self.player_id,
            'quick_profile_id': self.quick_profile_id,
            'content': self.content,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

        if include_author:
            data['author'] = {
                'id': self.author.id if self.author else None,
                'username': self.author.username if self.author else 'Unknown',
                'name': self.author.player.name if self.author and self.author.player else (self.author.username if self.author else 'Unknown')
            }

        return data

    def __repr__(self):
        return f'<PlayerAdminNote {self.id} for player {self.player_id}>'