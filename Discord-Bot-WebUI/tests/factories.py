"""
Test factories for creating consistent test data.

These factories create model instances that match the actual database schema.
"""
import factory
from factory.alchemy import SQLAlchemyModelFactory
from faker import Faker
from datetime import datetime, timedelta, time, date

from app.core import db
from app.models import User, Team, Match, Player, Season, League, Schedule, Availability

fake = Faker()


class BaseFactory(SQLAlchemyModelFactory):
    class Meta:
        abstract = True
        sqlalchemy_session = None  # Will be set per-test
        sqlalchemy_session_persistence = 'flush'


# Helper to set session on factory meta
def set_factory_session(session):
    """Set the session for all factories."""
    BaseFactory._meta.sqlalchemy_session = session
    UserFactory._meta.sqlalchemy_session = session
    SeasonFactory._meta.sqlalchemy_session = session
    LeagueFactory._meta.sqlalchemy_session = session
    TeamFactory._meta.sqlalchemy_session = session
    PlayerFactory._meta.sqlalchemy_session = session
    ScheduleFactory._meta.sqlalchemy_session = session
    MatchFactory._meta.sqlalchemy_session = session
    AvailabilityFactory._meta.sqlalchemy_session = session


class UserFactory(BaseFactory):
    """Factory for creating User instances."""
    class Meta:
        model = User

    username = factory.Sequence(lambda n: f'user{n}')
    email = factory.LazyAttribute(lambda obj: f'{obj.username}@example.com')
    is_approved = True
    approval_status = 'approved'

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        """Override create to ensure password is set properly."""
        password = kwargs.pop('password', 'password123')
        instance = model_class(*args, **kwargs)
        instance.set_password(password)
        session = cls._meta.sqlalchemy_session
        if session:
            session.add(instance)
            session.flush()
        return instance


class SeasonFactory(BaseFactory):
    """
    Factory for creating Season instances.

    Season model fields:
    - name: String(100), required
    - league_type: String(50), required
    - is_current: Boolean, default False
    """
    class Meta:
        model = Season

    name = factory.Sequence(lambda n: f'Season {n}')
    league_type = 'CLASSIC'  # Required field
    is_current = False


class LeagueFactory(BaseFactory):
    """
    Factory for creating League instances.

    League model fields:
    - name: String(100), required
    - season_id: ForeignKey to season.id, required
    """
    class Meta:
        model = League

    name = factory.Faker('company')
    season = factory.SubFactory(SeasonFactory)

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        """Handle season relationship properly."""
        season = kwargs.pop('season', None)
        instance = model_class(*args, **kwargs)
        if season:
            instance.season_id = season.id
        session = cls._meta.sqlalchemy_session
        if session:
            session.add(instance)
            session.flush()
        return instance


class TeamFactory(BaseFactory):
    """
    Factory for creating Team instances.

    Team model fields:
    - name: String(100), required
    - league_id: ForeignKey to league.id, required
    """
    class Meta:
        model = Team

    name = factory.Faker('city')
    league = factory.SubFactory(LeagueFactory)

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        """Handle league relationship properly."""
        league = kwargs.pop('league', None)
        instance = model_class(*args, **kwargs)
        if league:
            instance.league_id = league.id
        session = cls._meta.sqlalchemy_session
        if session:
            session.add(instance)
            session.flush()
        return instance


class PlayerFactory(BaseFactory):
    """
    Factory for creating Player instances.

    Player model fields:
    - name: String(100), required
    - user_id: ForeignKey to users.id, required
    - discord_id: String(100), unique
    - is_phone_verified, is_coach, is_ref, etc.
    - encrypted_phone: Text (encrypted phone number)

    Note: Player-Team relationship is many-to-many via player_teams table.
    """
    class Meta:
        model = Player

    name = factory.Faker('name')
    discord_id = factory.Sequence(lambda n: f'discord_{n}')
    jersey_number = factory.Faker('random_int', min=1, max=99)
    jersey_size = factory.Faker('random_element', elements=['XS', 'S', 'M', 'L', 'XL', 'XXL'])
    is_phone_verified = False
    is_coach = False
    is_ref = False

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        """Create player with user and optionally add to team."""
        team = kwargs.pop('team', None)
        user = kwargs.pop('user', None)

        # If no user provided, create one
        if not user:
            user = UserFactory()

        instance = model_class(*args, **kwargs)
        instance.user_id = user.id

        session = cls._meta.sqlalchemy_session
        if session:
            session.add(instance)
            session.flush()
            # Add to team if provided
            if team:
                instance.teams.append(team)
                session.flush()
        return instance


class ScheduleFactory(BaseFactory):
    """
    Factory for creating Schedule instances.

    Schedule model fields:
    - week: String(10), required
    - date: Date, required
    - time: Time, required
    - opponent: ForeignKey to team.id, required
    - location: String(100), required
    - team_id: ForeignKey to team.id, required
    - season_id: ForeignKey to season.id (optional)
    """
    class Meta:
        model = Schedule

    week = factory.Sequence(lambda n: f'Week {n}')
    date = factory.LazyFunction(lambda: date.today() + timedelta(days=7))
    time = factory.LazyFunction(lambda: time(19, 0))  # 7 PM
    location = factory.Faker('random_element', elements=['North Field', 'South Field', 'Main Field'])

    # These will be set in _create
    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        """Handle team relationships properly."""
        team = kwargs.pop('team', None)
        opponent_team = kwargs.pop('opponent_team', None)
        season = kwargs.pop('season', None)

        instance = model_class(*args, **kwargs)

        if team:
            instance.team_id = team.id
        if opponent_team:
            instance.opponent = opponent_team.id
        if season:
            instance.season_id = season.id

        session = cls._meta.sqlalchemy_session
        if session:
            session.add(instance)
            session.flush()
        return instance


class MatchFactory(BaseFactory):
    """
    Factory for creating Match instances.

    Match model fields:
    - date: Date, required
    - time: Time, required
    - location: String(100), required
    - home_team_id: ForeignKey to team.id, required
    - away_team_id: ForeignKey to team.id, required
    - schedule_id: ForeignKey to schedule.id, required

    Note: A Match requires a Schedule to exist first.
    If home_team/away_team provided without schedule, one will be auto-created.
    """
    class Meta:
        model = Match

    date = factory.LazyFunction(lambda: date.today() + timedelta(days=7))
    time = factory.LazyFunction(lambda: time(19, 0))  # 7 PM
    location = factory.Faker('random_element', elements=['North Field', 'South Field', 'Main Field'])

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        """Handle team and schedule relationships properly."""
        home_team = kwargs.pop('home_team', None)
        away_team = kwargs.pop('away_team', None)
        schedule = kwargs.pop('schedule', None)
        season = kwargs.pop('season', None)

        session = cls._meta.sqlalchemy_session

        # Auto-create teams if not provided
        if not home_team:
            home_team = TeamFactory()
        if not away_team:
            away_team = TeamFactory(league=home_team.league)

        # Auto-create schedule if not provided
        if not schedule:
            schedule = ScheduleFactory(
                team=home_team,
                opponent_team=away_team,
                season=season
            )

        instance = model_class(*args, **kwargs)
        instance.home_team_id = home_team.id
        instance.away_team_id = away_team.id
        instance.schedule_id = schedule.id

        # Copy date/time/location from schedule if not explicitly set
        if 'date' not in kwargs:
            instance.date = schedule.date
        if 'time' not in kwargs:
            instance.time = schedule.time
        if 'location' not in kwargs:
            instance.location = schedule.location

        if session:
            session.add(instance)
            session.flush()
        return instance


class AvailabilityFactory(BaseFactory):
    """
    Factory for creating Availability instances (RSVP).

    Availability model fields:
    - match_id: ForeignKey to matches.id, required
    - player_id: ForeignKey to player.id (optional)
    - discord_id: String(100), required
    - response: String(20), required ('yes', 'no', 'maybe')
    - responded_at: DateTime
    """
    class Meta:
        model = Availability

    discord_id = factory.Sequence(lambda n: f'discord_{n}')
    response = 'yes'
    responded_at = factory.LazyFunction(datetime.utcnow)

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        """Handle match and player relationships."""
        match = kwargs.pop('match', None)
        player = kwargs.pop('player', None)

        instance = model_class(*args, **kwargs)

        if match:
            instance.match_id = match.id
        if player:
            instance.player_id = player.id
            instance.discord_id = player.discord_id or instance.discord_id

        session = cls._meta.sqlalchemy_session
        if session:
            session.add(instance)
            session.flush()
        return instance


# =============================================================================
# CONVENIENCE BUILDERS
# =============================================================================

def create_full_match(session, home_team=None, away_team=None, season=None):
    """
    Create a complete match with all required dependencies.

    Returns: (match, home_team, away_team, schedule, season)
    """
    set_factory_session(session)

    if not season:
        season = SeasonFactory()

    league = LeagueFactory(season=season)

    if not home_team:
        home_team = TeamFactory(league=league)
    if not away_team:
        away_team = TeamFactory(league=league)

    schedule = ScheduleFactory(
        team=home_team,
        opponent_team=away_team,
        season=season
    )

    match = MatchFactory(
        home_team=home_team,
        away_team=away_team,
        schedule=schedule
    )

    return match, home_team, away_team, schedule, season


def create_player_with_team(session, user=None):
    """
    Create a player with team assignment.

    Returns: (player, team, league, season)
    """
    set_factory_session(session)

    season = SeasonFactory()
    league = LeagueFactory(season=season)
    team = TeamFactory(league=league)

    player = PlayerFactory(team=team)

    if user:
        # Link player to user if needed
        # This depends on your User-Player relationship
        pass

    return player, team, league, season
