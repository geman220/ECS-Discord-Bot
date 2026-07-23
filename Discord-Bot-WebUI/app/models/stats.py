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

    # passive_deletes=True trusts DB's ON DELETE CASCADE
    player = db.relationship('Player', back_populates='season_stats', passive_deletes=True)
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
        # season_id-only filters (season-wide stat aggregation) aren't served by
        # the player_id-leading unique index above.
        db.Index('idx_player_season_stats_season_id_league_id', 'season_id', 'league_id'),
    )

    @classmethod
    def get_or_create(cls, session, player_id, season_id, league_id=None):
        """Get existing stats record or create new one for player/season/league.

        If called with a non-NULL league_id and no row exists for that exact
        (player, season, league) combo, also check for a legacy NULL-league_id
        row for the same (player, season). When that legacy row exists and is
        empty (all stats zero), upgrade it in place by setting its league_id —
        this prevents creating duplicate rows like the ~85 cases where every
        affected player had both a NULL-league row and a Premier=24 row for
        season 20. Non-empty NULL rows are left alone (their stat values may
        be a legacy aggregate we don't want to silently re-attribute).
        """
        stats = session.query(cls).filter_by(
            player_id=player_id,
            season_id=season_id,
            league_id=league_id
        ).first()

        if not stats and league_id is not None:
            legacy = session.query(cls).filter_by(
                player_id=player_id,
                season_id=season_id,
                league_id=None
            ).first()
            if legacy and legacy.goals == 0 and legacy.assists == 0 \
                    and legacy.yellow_cards == 0 and legacy.red_cards == 0:
                legacy.league_id = league_id
                return legacy

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
    __table_args__ = (
        db.Index('idx_player_career_stats_player_id', 'player_id'),
    )

    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id', ondelete='CASCADE'), nullable=False)
    goals = db.Column(db.Integer, default=0, nullable=False)
    assists = db.Column(db.Integer, default=0, nullable=False)
    yellow_cards = db.Column(db.Integer, default=0, nullable=False)
    red_cards = db.Column(db.Integer, default=0, nullable=False)

    # passive_deletes=True trusts DB's ON DELETE CASCADE
    player = db.relationship('Player', back_populates='career_stats', passive_deletes=True)

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
    __table_args__ = (
        db.Index('idx_standings_team_id_season_id', 'team_id', 'season_id'),
        db.Index('idx_standings_season_id', 'season_id'),
    )

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

    # passive_deletes=True trusts DB's ON DELETE CASCADE
    player = db.relationship('Player', back_populates='stat_change_logs', passive_deletes=True)
    user = db.relationship('User', back_populates='stat_change_logs', passive_deletes=True)
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
    
    # Relationships - passive_deletes=True trusts DB's ON DELETE CASCADE
    player = db.relationship('Player', back_populates='attendance_stats', passive_deletes=True)
    season = db.relationship('Season')
    
    @classmethod
    def get_or_create(cls, player_id, season_id=None, session=None):
        """Get existing stats or create new record for player.

        `session` must be passed outside of a request context (e.g. Celery),
        where `g.db_session` does not exist.
        """
        if session is None:
            session = g.db_session
        stats = session.query(cls).filter_by(player_id=player_id).first()
        if not stats:
            stats = cls(player_id=player_id, current_season_id=season_id)
            session.add(stats)
        return stats
    
    def update_stats(self, session=None):
        """Recalculate all statistics from availability data.

        'Matches invited' is the set of REGULAR-week matches the player's team(s) have
        ALREADY PLAYED (Match.date <= today). Matches in that window with no yes/no/maybe
        response count as a no-response, so a player who answered only a couple of RSVPs
        does not show an artificial 100% (the denominator was once just the count of
        Availability rows, i.e. only games they responded to).

        Known remaining limitation: there is no roster join-date, so a player added to a
        team mid-season is still charged for that team's earlier played matches. The
        fallback branch approximates tenure with the player's first-ever RSVP, which
        flatters anyone who ignored their opening weeks. Both go away once per-season
        participation is tracked at (player, season, league) grain.
        """
        if session is None:
            session = g.db_session

        from sqlalchemy import or_
        from app.models.matches import Match, Availability

        # Only matches that have actually been PLAYED can count. Without this bound the
        # denominator included every unplayed fixture on the calendar as a no-response, so
        # in week 2 of a 10-week season a perfect attender read ~20% — and in preseason,
        # when nothing has been played, EVERY player read 0%.
        today = datetime.utcnow().date()

        # Player's current team(s).
        team_ids = [tid for (tid,) in session.query(player_teams.c.team_id)
                    .filter(player_teams.c.player_id == self.player_id).all()]

        # First recorded activity = proxy for when the player started being invited.
        first_activity = session.query(func.min(Availability.responded_at)).filter(
            Availability.player_id == self.player_id).scalar()

        # The player's actual responses, keyed by match.
        responses = {a.match_id: (a.response or '').lower()
                     for a in session.query(Availability).filter_by(player_id=self.player_id).all()}

        # CAREER invited universe = every REGULAR match the player's team(s) played in,
        # summed across ALL seasons (true lifetime) via player_team_season roster history.
        # We join by team_id ALONE: Pub League teams are recreated per season, so each
        # team_id already encodes exactly one (team, season) — no need to also match the
        # season. This is deliberate: historical schedules have a null/orphaned
        # season_id, so joining through Schedule.season_id silently dropped every season
        # before the current one. (Current player_teams alone would also cap "career" at
        # this season.) Only real games count — week_type='REGULAR' excludes
        # FUN/TST/BYE/PLAYOFF/PRACTICE/BONUS special weeks (self-match placeholder rows).
        # Falls back to current teams (then to response rows) when there's no roster history.
        from app.models.players import PlayerTeamSeason
        pts_team_ids = [tid for (tid,) in session.query(PlayerTeamSeason.team_id).filter(
            PlayerTeamSeason.player_id == self.player_id).distinct().all()]
        if pts_team_ids:
            invited_match_ids = [mid for (mid,) in session.query(Match.id).filter(
                Match.week_type == 'REGULAR',
                Match.date <= today,
                Match.home_team_id != Match.away_team_id,
                or_(Match.home_team_id.in_(pts_team_ids),
                    Match.away_team_id.in_(pts_team_ids))
            ).all()]
        elif team_ids and first_activity is not None:
            invited_match_ids = [mid for (mid,) in session.query(Match.id).filter(
                or_(Match.home_team_id.in_(team_ids), Match.away_team_id.in_(team_ids)),
                Match.date >= first_activity.date(),
                Match.date <= today,
                Match.home_team_id != Match.away_team_id,
                Match.week_type == 'REGULAR'
            ).all()]
        else:
            invited_match_ids = list(responses.keys())

        # Reset counters
        self.total_matches_invited = len(invited_match_ids)
        self.total_responses = 0
        self.yes_responses = 0
        self.no_responses = 0
        self.maybe_responses = 0
        self.no_response_count = 0

        # Count responses across the invited universe (missing row => no-response)
        for mid in invited_match_ids:
            response = responses.get(mid, '')
            if response in ('yes', 'no', 'maybe'):
                self.total_responses += 1
                if response == 'yes':
                    self.yes_responses += 1
                elif response == 'no':
                    self.no_responses += 1
                else:
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
        
        # Update CURRENT-season stats. Resolve the current season(s) here (is_current=True)
        # so a bulk recompute doesn't need to pre-set current_season_id — that guard was
        # why season attendance read 0% for everyone. Multiple leagues can each have a
        # current season, so we count matches in any of them.
        from app.models.core import Season
        # Season.is_current is per league_type, so Pub League AND ECS FC are both current at
        # the same time. This query had no ORDER BY, so `[0]` was whichever row Postgres
        # happened to return — and every coach-dashboard roster join keys on the stamped
        # current_season_id, silently rendering N/A for a whole league when the other one won.
        # Stamp the Pub League season deterministically (that is what the roster pages read);
        # season match counting below still spans every current season.
        current_rows = (session.query(Season.id, Season.league_type)
                        .filter(Season.is_current.is_(True))
                        .order_by(Season.id.desc()).all())
        current_season_ids = [sid for (sid, _lt) in current_rows]
        if current_season_ids:
            self.current_season_id = next(
                (sid for (sid, lt) in current_rows if lt == 'Pub League'),
                current_season_ids[0],
            )
            self._update_season_stats(session, current_season_ids)
        else:
            self.season_matches_invited = 0
            self.season_yes_responses = 0
            self.season_attendance_rate = 0.0

        self.last_updated = datetime.utcnow()

    def _update_season_stats(self, session, season_ids):
        """Update current-season statistics (same 'bounded by first activity'
        denominator as update_stats, scoped to the current season(s))."""
        from sqlalchemy import or_
        from app.models.matches import Match, Availability, Schedule

        team_ids = [tid for (tid,) in session.query(player_teams.c.team_id)
                    .filter(player_teams.c.player_id == self.player_id).all()]

        # First recorded activity (career-wide) — a lower date bound so current-season
        # team matches all qualify even if the player hasn't RSVP'd yet this season.
        first_activity = session.query(func.min(Availability.responded_at)).filter(
            Availability.player_id == self.player_id).scalar()

        # The player's responses within the current season(s), keyed by match.
        responses = dict(session.query(Availability.match_id, Availability.response).join(Match).join(Schedule).filter(
            Availability.player_id == self.player_id,
            Schedule.season_id.in_(season_ids)
        ).all())

        if team_ids and first_activity is not None:
            season_match_ids = [mid for (mid,) in session.query(Match.id).join(Schedule).filter(
                Schedule.season_id.in_(season_ids),
                or_(Match.home_team_id.in_(team_ids), Match.away_team_id.in_(team_ids)),
                Match.date >= first_activity.date(),
                # Played only — an unplayed fixture is not a missed one.
                Match.date <= datetime.utcnow().date(),
                # Real league games only (exclude special weeks / placeholders).
                Match.week_type == 'REGULAR',
                Match.home_team_id != Match.away_team_id
            ).all()]
        else:
            season_match_ids = list(responses.keys())

        self.season_matches_invited = len(season_match_ids)
        self.season_yes_responses = sum(1 for mid in season_match_ids
                                        if (responses.get(mid) or '').lower() == 'yes')

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

    # Offline resilience fields
    idempotency_key = db.Column(db.String(64), nullable=True, index=True)
    client_timestamp = db.Column(db.DateTime, nullable=True)

    # Reporter tracking for deduplication and attribution
    reported_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    # Substitute tracking — events by temp subs don't count toward season awards
    is_sub_event = db.Column(db.Boolean, default=False, nullable=False, server_default='false')

    # Added by 2026_04_29_add_card_reason_to_events.sql. Optional reason for
    # YELLOW_CARD/RED_CARD: FOUL | DISSENT | PERSISTENT_INFRINGEMENT | SERIOUS_FOUL_PLAY.
    card_reason = db.Column(db.String(30), nullable=True)

    player = db.relationship('Player', back_populates='events', passive_deletes=True)
    match = db.relationship('Match', back_populates='events')
    team = db.relationship('Team', backref='own_goal_events')
    reporter = db.relationship('User', backref='reported_player_events')

    def to_dict(self, include_player=False):
        data = {
            'id': self.id,
            'idempotency_key': self.idempotency_key,
            'player_id': self.player_id,
            'match_id': self.match_id,
            'team_id': self.team_id,
            'minute': self.minute,
            'event_type': self.event_type.name if self.event_type else None,
            'client_timestamp': self.client_timestamp.isoformat() if self.client_timestamp else None,
            'reported_by': self.reported_by,
            'reported_by_name': self.reporter.username if self.reporter else None,
            'is_sub_event': self.is_sub_event,
            'card_reason': self.card_reason,
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
    __table_args__ = (
        db.Index('idx_player_stat_audit_player_id_timestamp', 'player_id', db.text('timestamp DESC')),
    )

    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id', ondelete='CASCADE'), nullable=False)
    season_id = db.Column(db.Integer, db.ForeignKey('season.id', ondelete='CASCADE'), nullable=True)
    stat_type = db.Column(db.String(50), nullable=False)
    old_value = db.Column(db.Integer, nullable=False)
    new_value = db.Column(db.Integer, nullable=False)
    change_type = db.Column(db.Enum(StatChangeType), nullable=False)
    changed_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # passive_deletes=True trusts DB's ON DELETE CASCADE
    player = db.relationship('Player', back_populates='stat_audits', passive_deletes=True)
    season = db.relationship('Season', back_populates='stat_audits')
    user = db.relationship('User', back_populates='stat_audits', passive_deletes=True)


# Listen for goal difference updates
event.listen(Standings, 'before_insert', Standings.update_goal_difference)
event.listen(Standings, 'before_update', Standings.update_goal_difference)