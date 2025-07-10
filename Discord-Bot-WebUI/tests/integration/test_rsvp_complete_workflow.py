"""
Integration tests for complete RSVP workflows.
Tests the full journey from notification to response.
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, Mock

from tests.factories import UserFactory, MatchFactory, PlayerFactory, TeamFactory
from tests.helpers import (
    TestDataBuilder, SMSTestHelper, MatchTestHelper,
    assert_sms_sent, AuthTestHelper
)


@pytest.mark.integration
class TestRSVPCompleteWorkflow:
    """Test complete RSVP user journeys."""
    
    def test_player_rsvp_journey_via_sms(self, db):
        """Test complete SMS RSVP flow from reminder to confirmation."""
        # Setup: Player with upcoming match in 3 days
        user = UserFactory(phone_number='+15551234567')
        player = PlayerFactory(user=user)
        match = MatchFactory(
            home_team=player.team,
            scheduled_date=datetime.utcnow().date() + timedelta(days=3),
            scheduled_time='19:00'
        )
        
        sms_helper = SMSTestHelper()
        
        with patch('app.sms_helpers.send_sms', side_effect=sms_helper.mock_send_sms):
            # Step 1: System sends RSVP reminder
            from app.tasks.tasks_rsvp import send_rsvp_reminders_for_match
            send_rsvp_reminders_for_match(match.id)
            
            # Verify: Player received personalized reminder
            messages = sms_helper.get_messages_for_user(user)
            assert len(messages) == 1
            reminder = messages[0]['message']
            assert 'RSVP' in reminder
            assert player.team.name in reminder
            assert 'Reply YES or NO' in reminder
            
            # Step 2: Player responds YES
            from app.sms_helpers import handle_incoming_text_command
            response = handle_incoming_text_command('+15551234567', 'yes')
            
            # Verify: Confirmation sent
            assert 'confirmed available' in response.lower()
            
            # Verify: Database updated
            from app.models import Availability
            availability = Availability.query.filter_by(
                user_id=user.id,
                match_id=match.id
            ).first()
            assert availability is not None
            assert availability.available is True
            assert availability.response_method == 'sms'
    
    def test_player_rsvp_journey_via_web(self, db, client):
        """Test complete web RSVP flow."""
        # Setup: Authenticated player with upcoming match
        user = UserFactory()
        player = PlayerFactory(user=user)
        match = MatchFactory(
            home_team=player.team,
            scheduled_date=datetime.utcnow().date() + timedelta(days=5)
        )
        
        with AuthTestHelper.authenticated_request(client, user):
            # Step 1: Player views their schedule
            response = client.get('/players/schedule')
            assert response.status_code == 200
            assert match.home_team.name.encode() in response.data
            
            # Step 2: Player submits RSVP
            response = client.post('/api/availability', json={
                'match_id': match.id,
                'available': True,
                'notes': 'Looking forward to it!'
            })
            
            assert response.status_code == 200
            data = response.get_json()
            assert data['success'] is True
            
            # Verify: Database updated correctly
            from app.models import Availability
            availability = Availability.query.filter_by(
                user_id=user.id,
                match_id=match.id
            ).first()
            assert availability is not None
            assert availability.available is True
            assert availability.notes == 'Looking forward to it!'
            assert availability.response_method == 'web'
    
    def test_captain_sees_team_availability(self, db, client):
        """Test captain can view team RSVP status."""
        # Setup: Team with mix of responses
        captain = UserFactory()
        team = TeamFactory(captain=captain)
        match = MatchFactory(home_team=team)
        
        # Create players with different responses
        available_players = [
            PlayerFactory(team=team) for _ in range(7)
        ]
        unavailable_players = [
            PlayerFactory(team=team) for _ in range(3)
        ]
        no_response_players = [
            PlayerFactory(team=team) for _ in range(5)
        ]
        
        # Set RSVPs
        for player in available_players:
            MatchTestHelper.create_rsvp(player.user, match, available=True)
        
        for player in unavailable_players:
            MatchTestHelper.create_rsvp(player.user, match, available=False)
        
        # Captain views team availability
        with AuthTestHelper.authenticated_request(client, captain):
            response = client.get(f'/matches/{match.id}/availability')
            assert response.status_code == 200
            
            # Verify counts shown correctly
            assert b'7 Available' in response.data
            assert b'3 Unavailable' in response.data
            assert b'5 No Response' in response.data
    
    def test_rsvp_reminder_escalation(self, db):
        """Test RSVP reminder escalation for non-responders."""
        # Setup: Player who hasn't responded
        user = UserFactory(phone_number='+15551234567')
        player = PlayerFactory(user=user)
        match = MatchFactory(
            home_team=player.team,
            scheduled_date=datetime.utcnow().date() + timedelta(days=2)
        )
        
        sms_helper = SMSTestHelper()
        
        with patch('app.sms_helpers.send_sms', side_effect=sms_helper.mock_send_sms):
            # Day 1: First reminder (3 days before)
            with patch('datetime.datetime') as mock_dt:
                mock_dt.utcnow.return_value = match.scheduled_date - timedelta(days=3)
                mock_dt.now.return_value = mock_dt.utcnow.return_value
                
                from app.tasks.tasks_rsvp import send_rsvp_reminders
                send_rsvp_reminders()
                
                assert len(sms_helper.sent_messages) == 1
                assert 'RSVP' in sms_helper.sent_messages[0]['message']
            
            # Day 2: Follow-up reminder (1 day before)
            sms_helper.clear_messages()
            with patch('datetime.datetime') as mock_dt:
                mock_dt.utcnow.return_value = match.scheduled_date - timedelta(days=1)
                mock_dt.now.return_value = mock_dt.utcnow.return_value
                
                send_rsvp_reminders()
                
                assert len(sms_helper.sent_messages) == 1
                assert 'still need your RSVP' in sms_helper.sent_messages[0]['message']
    
    def test_player_can_change_rsvp(self, db):
        """Test player changing their mind about availability."""
        # Setup: Player initially said YES
        user = UserFactory(phone_number='+15551234567')
        player = PlayerFactory(user=user)
        match = MatchFactory(home_team=player.team)
        
        # Initial RSVP: YES
        MatchTestHelper.create_rsvp(user, match, available=True)
        
        # Player changes to NO via SMS
        from app.sms_helpers import handle_incoming_text_command
        response = handle_incoming_text_command('+15551234567', 'NO')
        
        # Verify: Response updated
        assert 'updated' in response.lower()
        assert 'unavailable' in response.lower()
        
        from app.models import Availability
        availability = Availability.query.filter_by(
            user_id=user.id,
            match_id=match.id
        ).first()
        assert availability.available is False
        
        # Verify: History tracked
        assert availability.history is not None
        assert len(availability.history) == 2  # Initial + Update
    
    def test_rsvp_closes_at_match_time(self, db):
        """Test RSVP system closes when match starts."""
        # Setup: Match starting now
        user = UserFactory(phone_number='+15551234567')
        player = PlayerFactory(user=user)
        match = MatchFactory(
            home_team=player.team,
            scheduled_date=datetime.utcnow().date(),
            scheduled_time=datetime.utcnow().strftime('%H:%M')
        )
        
        # Try to RSVP after match started
        from app.sms_helpers import handle_incoming_text_command
        response = handle_incoming_text_command('+15551234567', 'YES')
        
        # Should be rejected
        assert 'already started' in response.lower() or 'too late' in response.lower()
        
        # Verify: No RSVP recorded
        from app.models import Availability
        availability = Availability.query.filter_by(
            user_id=user.id,
            match_id=match.id
        ).first()
        assert availability is None