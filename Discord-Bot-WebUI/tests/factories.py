"""
Test factories for creating consistent test data.
"""
import factory
from factory.alchemy import SQLAlchemyModelFactory
from faker import Faker
from datetime import datetime, timedelta

from app.core import db
from app.models import User, Team, Match, Player, Season, League

fake = Faker()


class BaseFactory(SQLAlchemyModelFactory):
    class Meta:
        abstract = True
        sqlalchemy_session = db.session
        sqlalchemy_session_persistence = 'commit'


class UserFactory(BaseFactory):
    class Meta:
        model = User
    
    username = factory.Sequence(lambda n: f'user{n}')
    email = factory.LazyAttribute(lambda obj: f'{obj.username}@example.com')
    is_approved = True
    email_notifications = True
    sms_notifications = True
    discord_notifications = True
    approval_status = 'approved'
    
    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        """Override create to ensure password is set properly."""
        password = kwargs.pop('password', 'password123')
        instance = model_class(*args, **kwargs)
        instance.set_password(password)
        if cls._meta.sqlalchemy_session:
            cls._meta.sqlalchemy_session.add(instance)
            cls._meta.sqlalchemy_session.flush()
        return instance


class LeagueFactory(BaseFactory):
    class Meta:
        model = League
    
    name = factory.Faker('company')
    description = factory.Faker('text', max_nb_chars=200)
    is_active = True


class SeasonFactory(BaseFactory):
    class Meta:
        model = Season
    
    name = factory.LazyAttribute(lambda obj: f'{obj.league.name} Season {datetime.now().year}')
    league = factory.SubFactory(LeagueFactory)
    start_date = factory.LazyFunction(datetime.utcnow)
    end_date = factory.LazyFunction(lambda: datetime.utcnow() + timedelta(days=90))
    is_active = True


class TeamFactory(BaseFactory):
    class Meta:
        model = Team
    
    name = factory.Faker('city')
    season = factory.SubFactory(SeasonFactory)
    captain = factory.SubFactory(UserFactory)


class PlayerFactory(BaseFactory):
    class Meta:
        model = Player
    
    user = factory.SubFactory(UserFactory)
    team = factory.SubFactory(TeamFactory)
    jersey_number = factory.Faker('random_int', min=1, max=99)
    jersey_size = factory.Faker('random_element', elements=['XS', 'S', 'M', 'L', 'XL', 'XXL'])
    positions = 'Forward,Midfielder'
    phone = factory.Faker('phone_number')
    is_phone_verified = True


class MatchFactory(BaseFactory):
    class Meta:
        model = Match
    
    season = factory.SubFactory(SeasonFactory)
    home_team = factory.SubFactory(TeamFactory)
    away_team = factory.SubFactory(TeamFactory)
    scheduled_date = factory.LazyFunction(lambda: datetime.utcnow() + timedelta(days=7))
    scheduled_time = '19:00'
    field_name = factory.Faker('random_element', elements=['North Field', 'South Field', 'Main Field'])