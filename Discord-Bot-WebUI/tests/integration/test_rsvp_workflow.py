"""
Integration tests for complete RSVP workflow.
Tests the full user journey, not implementation details.
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch

from tests.factories import UserFactory, MatchFactory, PlayerFactory
from tests.helpers import SMSTestHelper, TestDataBuilder, assert_sms_sent


@pytest.mark.integration
class TestRSVPWorkflow:
    """Test complete RSVP workflow from notification to response."""
    
    def test_player_receives_and_responds_to_rsvp(self, db, client):
        """Test full RSVP flow: notification -> response -> confirmation."""
        # Setup: Create player with upcoming match
        user, matches = TestDataBuilder.create_user_with_upcoming_matches(num_matches=1)
        match = matches[0]
        sms_helper = SMSTestHelper()
        
        with patch('app.sms_helpers.send_sms', side_effect=sms_helper.mock_send_sms):
            # Step 1: System sends RSVP reminder
            from app.tasks.tasks_rsvp import send_rsvp_reminders
            send_rsvp_reminders()
            
            # Verify: Player received reminder
            assert_sms_sent(sms_helper, to=user.phone_number, contains='RSVP')
            assert_sms_sent(sms_helper, contains=match.home_team.name)
            
            # Step 2: Player responds YES via SMS
            from app.sms_helpers import handle_incoming_text_command
            response = handle_incoming_text_command(user.phone_number, 'YES')
            
            # Verify: Confirmation sent and availability recorded
            assert 'confirmed' in response.lower()
            
            from app.models import Availability
            availability = Availability.query.filter_by(
                user_id=user.id,
                match_id=match.id
            ).first()
            assert availability is not None
            assert availability.available is True
    
    def test_player_can_change_rsvp(self, db):
        """Test that players can change their RSVP."""
        # Setup: Player already RSVP'd YES
        user, matches = TestDataBuilder.create_user_with_upcoming_matches(num_matches=1)
        match = matches[0]
        
        from tests.helpers import MatchTestHelper
        MatchTestHelper.create_rsvp(user, match, available=True)
        
        # When: Player changes to NO
        from app.sms_helpers import handle_rsvp
        player = user.players[0]
        response = handle_rsvp(player, 'NO')
        
        # Then: RSVP should be updated
        from app.models import Availability
        availability = Availability.query.filter_by(
            user_id=user.id,
            match_id=match.id
        ).first()
        assert availability.available is False
        assert 'unavailable' in response.lower()
    
    def test_rsvp_reminder_only_sent_once_per_day(self, db):
        """Test that RSVP reminders respect daily limits."""
        user = UserFactory()
        player = PlayerFactory(user=user)
        
        # Create match in 3 days
        match = MatchFactory(
            home_team=player.team,
            scheduled_date=datetime.utcnow() + timedelta(days=3)
        )
        
        sms_helper = SMSTestHelper()
        
        with patch('app.sms_helpers.send_sms', side_effect=sms_helper.mock_send_sms):
            from app.tasks.tasks_rsvp import send_rsvp_reminders
            
            # First run: should send
            send_rsvp_reminders()
            assert len(sms_helper.sent_messages) == 1
            
            # Second run same day: should not send
            sms_helper.clear_messages()
            send_rsvp_reminders()
            assert len(sms_helper.sent_messages) == 0
    
    def test_web_rsvp_updates_correctly(self, db, authenticated_client, user):
        """Test RSVP via web interface."""
        player = PlayerFactory(user=user)
        match = MatchFactory(home_team=player.team)
        
        # Submit RSVP via web
        response = authenticated_client.post('/api/rsvp', json={
            'match_id': match.id,
            'available': True,
            'notes': 'Looking forward to it!'
        })
        
        assert response.status_code == 200
        
        # Verify database updated
        from app.models import Availability
        availability = Availability.query.filter_by(
            user_id=user.id,
            match_id=match.id
        ).first()
        assert availability is not None
        assert availability.available is True
        assert availability.notes == 'Looking forward to it!'