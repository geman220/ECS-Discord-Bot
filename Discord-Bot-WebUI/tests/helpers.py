"""
Test helpers for common testing operations.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from app.models import User, Match, Availability, Player
from app.core import db


class TestDataBuilder:
    """Builder pattern for creating complex test scenarios."""
    
    @staticmethod
    def create_match_with_teams(home_team_size=11, away_team_size=11, **match_kwargs):
        """Create a match with fully populated teams."""
        from tests.factories import MatchFactory, PlayerFactory
        
        match = MatchFactory(**match_kwargs)
        
        # Create players for home team
        for i in range(home_team_size):
            PlayerFactory(team=match.home_team)
        
        # Create players for away team
        for i in range(away_team_size):
            PlayerFactory(team=match.away_team)
        
        db.session.commit()
        return match
    
    @staticmethod
    def create_user_with_upcoming_matches(num_matches=3):
        """Create a user with multiple upcoming matches."""
        from tests.factories import UserFactory, PlayerFactory, MatchFactory
        
        user = UserFactory()
        player = PlayerFactory(user=user)
        
        matches = []
        for i in range(num_matches):
            match = MatchFactory(
                home_team=player.team,
                scheduled_date=datetime.utcnow() + timedelta(days=i+1)
            )
            matches.append(match)
        
        db.session.commit()
        return user, matches
    
    @staticmethod
    def create_team_with_full_roster(captain=None, season=None):
        """Create a team with a full roster of players."""
        from tests.factories import TeamFactory, PlayerFactory, UserFactory
        
        if not captain:
            captain = UserFactory()
        if not season:
            from tests.factories import SeasonFactory
            season = SeasonFactory()
        
        team = TeamFactory(captain=captain, season=season)
        
        # Create 15 players
        players = []
        for i in range(15):
            user = UserFactory()
            player = PlayerFactory(user=user, team=team, jersey_number=i+1)
            players.append(player)
        
        team.players = players
        db.session.commit()
        return team
    
    @staticmethod
    def create_team_with_players(captain=None, season=None, player_count=11):
        """Create a team with specified number of players."""
        from tests.factories import TeamFactory, PlayerFactory, UserFactory
        
        if not captain:
            captain = UserFactory()
        if not season:
            from tests.factories import SeasonFactory
            season = SeasonFactory()
        
        team = TeamFactory(captain=captain, season=season)
        
        players = []
        for i in range(player_count):
            user = UserFactory()
            player = PlayerFactory(user=user, team=team, jersey_number=i+1)
            players.append(player)
        
        team.players = players
        db.session.commit()
        return team
    
    @staticmethod
    def create_team_with_match_history(num_matches=10):
        """Create a team with completed match history."""
        from tests.factories import TeamFactory, MatchFactory
        
        team = TeamFactory()
        
        # Create matches with results
        for i in range(num_matches):
            match = MatchFactory(
                home_team=team,
                scheduled_date=datetime.utcnow().date() - timedelta(days=i*7),
                status='completed',
                home_score=2 if i % 2 == 0 else 1,
                away_score=1 if i % 2 == 0 else 2
            )
        
        db.session.commit()
        return team


class SMSTestHelper:
    """Helper for testing SMS functionality."""
    
    def __init__(self):
        self.sent_messages = []
    
    def mock_send_sms(self, phone, message, user_id=None):
        """Mock SMS sending that tracks messages."""
        self.sent_messages.append({
            'phone': phone,
            'message': message,
            'user_id': user_id,
            'timestamp': datetime.utcnow()
        })
        return True
    
    def get_messages_for_user(self, user):
        """Get all messages sent to a user."""
        return [m for m in self.sent_messages if m['phone'] == user.phone_number]
    
    def clear_messages(self):
        """Clear all tracked messages."""
        self.sent_messages = []


class AuthTestHelper:
    """Helper for authentication testing."""
    
    @staticmethod
    def login_user(client, user, password='password123'):
        """Log in a user and return the response."""
        return client.post('/auth/login', data={
            'email': user.email,
            'password': password
        }, follow_redirects=True)
    
    @staticmethod
    def create_authenticated_session(client, user):
        """Create an authenticated session for a user."""
        with client.session_transaction() as sess:
            sess['user_id'] = user.id
            sess['_fresh'] = True
        return client
    
    @staticmethod
    @contextmanager
    def authenticated_request(client, user):
        """Context manager for authenticated requests."""
        with client.session_transaction() as sess:
            sess['user_id'] = user.id
            sess['_fresh'] = True
        yield client
        with client.session_transaction() as sess:
            sess.clear()


class MatchTestHelper:
    """Helper for match-related testing."""
    
    @staticmethod
    def create_rsvp(user, match, available=True, notes=None):
        """Create an RSVP for a user."""
        availability = Availability(
            user_id=user.id,
            match_id=match.id,
            available=available,
            response_date=datetime.utcnow(),
            notes=notes
        )
        db.session.add(availability)
        db.session.commit()
        return availability
    
    @staticmethod
    def simulate_match_day(match):
        """Simulate it being match day."""
        match.scheduled_date = datetime.utcnow().date()
        db.session.commit()
        return match
    
    @staticmethod
    def complete_match(match, home_score=2, away_score=1):
        """Mark a match as completed with scores."""
        match.status = 'completed'
        match.home_score = home_score
        match.away_score = away_score
        match.completed_date = datetime.utcnow()
        db.session.commit()
        return match


def assert_email_sent(mock_mail, to=None, subject=None, body_contains=None):
    """Assert that an email was sent with specific criteria."""
    assert mock_mail.send.called, "No email was sent"
    
    if to or subject or body_contains:
        # Get the last sent message
        call_args = mock_mail.send.call_args
        msg = call_args[0][0] if call_args else None
        
        if to:
            assert to in msg.recipients, f"Email not sent to {to}"
        
        if subject:
            assert subject in msg.subject, f"Email subject doesn't contain {subject}"
        
        if body_contains:
            assert body_contains in msg.body or body_contains in msg.html, \
                f"Email body doesn't contain {body_contains}"


def assert_sms_sent(sms_helper, to=None, contains=None):
    """Assert that an SMS was sent with specific criteria."""
    messages = sms_helper.sent_messages
    assert len(messages) > 0, "No SMS messages were sent"
    
    if to:
        matching = [m for m in messages if m['phone'] == to]
        assert len(matching) > 0, f"No SMS sent to {to}"
        messages = matching
    
    if contains:
        matching = [m for m in messages if contains in m['message']]
        assert len(matching) > 0, f"No SMS contains '{contains}'"