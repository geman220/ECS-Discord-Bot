"""
Integration tests for communication workflows.
Tests SMS, email, and Discord notification systems.
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, Mock

from tests.factories import UserFactory, TeamFactory, PlayerFactory
from tests.helpers import SMSTestHelper, AuthTestHelper, assert_sms_sent
from app.models import User
from app.sms_helpers import check_sms_rate_limit


@pytest.mark.integration 
class TestCommunicationWorkflow:
    """Test complete communication journeys."""
    
    def test_sms_opt_out_and_opt_in_workflow(self, db):
        """Test SMS subscription management."""
        # Setup: User receiving SMS
        user = UserFactory(phone_number='+15551234567', sms_notifications=True)
        player = PlayerFactory(user=user)
        
        sms_helper = SMSTestHelper()
        
        with patch('app.sms_helpers.send_sms', side_effect=sms_helper.mock_send_sms):
            # Step 1: User opts out via SMS
            from app.sms_helpers import handle_incoming_text_command
            response = handle_incoming_text_command('+15551234567', 'STOP')
            
            assert 'unsubscribed' in response.lower()
            
            # Verify: User marked as opted out
            user = User.query.get(user.id)
            assert user.sms_notifications is False
            assert user.sms_opt_out_date is not None
            
            # Step 2: System respects opt-out
            sms_helper.clear_messages()
            from app.tasks.tasks_rsvp import send_rsvp_reminder_to_user
            send_rsvp_reminder_to_user(user.id, match_id=1)
            
            # No SMS should be sent
            assert len(sms_helper.sent_messages) == 0
            
            # Step 3: User opts back in
            response = handle_incoming_text_command('+15551234567', 'START')
            
            assert 'resubscribed' in response.lower()
            
            # Verify: User can receive SMS again
            user = User.query.get(user.id)
            assert user.sms_notifications is True
            assert user.sms_opt_out_date is None
    
    def test_sms_rate_limiting_per_user(self, db):
        """Test SMS rate limits are enforced per user."""
        # Setup: User with phone number
        user = UserFactory(phone_number='+15551234567')
        
        with patch('app.sms_helpers.redis_client') as mock_redis:
            mock_redis.get.return_value = None
            mock_redis.incr.return_value = 1
            
            # First 5 messages should succeed
            for i in range(5):
                result = check_sms_rate_limit(user.id)
                assert result is True
                mock_redis.incr.return_value = i + 2
            
            # 6th message should fail
            mock_redis.get.return_value = b'5'
            result = check_sms_rate_limit(user.id)
            assert result is False
    
    def test_scheduled_message_workflow(self, db, client):
        """Test scheduling and sending messages."""
        # Setup: Admin scheduling team announcement
        admin = UserFactory()
        admin.roles.append('Admin')
        
        team = TeamFactory()
        players = [PlayerFactory(team=team) for _ in range(10)]
        
        with AuthTestHelper.authenticated_request(client, admin):
            # Schedule message for tomorrow
            tomorrow = datetime.utcnow() + timedelta(days=1)
            response = client.post('/admin/messages/schedule', json={
                'recipient_type': 'team',
                'recipient_id': team.id,
                'message_type': 'announcement',
                'subject': 'Team Practice Update',
                'content': 'Practice moved to 6 PM due to field maintenance.',
                'scheduled_for': tomorrow.isoformat(),
                'channels': ['sms', 'email']
            })
            
            assert response.status_code == 200
            data = response.get_json()
            message_id = data['message_id']
            
            # Verify: Message scheduled
            from app.models import ScheduledMessage
            scheduled = ScheduledMessage.query.get(message_id)
            assert scheduled is not None
            assert scheduled.status == 'pending'
        
        # Fast forward to scheduled time
        with patch('datetime.datetime') as mock_dt:
            mock_dt.utcnow.return_value = tomorrow + timedelta(minutes=5)
            
            sms_helper = SMSTestHelper()
            with patch('app.sms_helpers.send_sms', side_effect=sms_helper.mock_send_sms):
                with patch('app.email.send_email') as mock_email:
                    # Run scheduled message processor
                    from app.tasks.tasks_core import process_scheduled_messages
                    process_scheduled_messages()
                    
                    # Verify: Messages sent
                    for player in players:
                        if player.user.phone_number:
                            messages = sms_helper.get_messages_for_user(player.user)
                            assert len(messages) == 1
                            assert 'Practice moved to 6 PM' in messages[0]['message']
                    
                    # Email sent to all
                    assert mock_email.call_count == len(players)
            
            # Verify: Message marked as sent
            scheduled = ScheduledMessage.query.get(message_id)
            assert scheduled.status == 'sent'
            assert scheduled.sent_at is not None
    
    def test_communication_preferences_respected(self, db):
        """Test system respects user communication preferences."""
        # Setup: Users with different preferences
        sms_only = UserFactory(
            phone_number='+15551111111',
            sms_notifications=True,
            email_notifications=False
        )
        email_only = UserFactory(
            email='email@example.com',
            sms_notifications=False,
            email_notifications=True
        )
        both = UserFactory(
            phone_number='+15552222222',
            email='both@example.com',
            sms_notifications=True,
            email_notifications=True
        )
        neither = UserFactory(
            sms_notifications=False,
            email_notifications=False
        )
        
        # Create players
        for user in [sms_only, email_only, both, neither]:
            PlayerFactory(user=user)
        
        sms_helper = SMSTestHelper()
        
        with patch('app.sms_helpers.send_sms', side_effect=sms_helper.mock_send_sms):
            with patch('app.email.send_email') as mock_email:
                # Send notification to all
                from app.services.notification_service import notify_users
                notify_users(
                    user_ids=[sms_only.id, email_only.id, both.id, neither.id],
                    message='Test notification',
                    channels=['sms', 'email']
                )
                
                # Verify: Preferences respected
                assert len(sms_helper.get_messages_for_user(sms_only)) == 1
                assert len(sms_helper.get_messages_for_user(email_only)) == 0
                assert len(sms_helper.get_messages_for_user(both)) == 1
                assert len(sms_helper.get_messages_for_user(neither)) == 0
                
                # Check email calls
                email_recipients = [call[0][0].email for call in mock_email.call_args_list]
                assert 'email@example.com' in email_recipients
                assert 'both@example.com' in email_recipients
                assert sms_only.email not in email_recipients
                assert neither.email not in email_recipients
    
    def test_bulk_communication_with_placeholders(self, db, client):
        """Test sending personalized bulk messages."""
        # Setup: Admin sending to all players
        admin = UserFactory()
        admin.roles.append('Admin')
        
        # Create players with upcoming matches
        players = []
        for i in range(20):
            user = UserFactory(
                username=f'player{i}',
                phone_number=f'+1555000{i:04d}'
            )
            player = PlayerFactory(user=user)
            players.append(player)
        
        sms_helper = SMSTestHelper()
        
        with AuthTestHelper.authenticated_request(client, admin):
            with patch('app.sms_helpers.send_sms', side_effect=sms_helper.mock_send_sms):
                # Send bulk message with placeholders
                response = client.post('/admin/messages/bulk', json={
                    'recipient_type': 'all_players',
                    'template': 'season_start',
                    'placeholders': {
                        'season_name': 'Spring 2024',
                        'first_match_date': 'March 15'
                    },
                    'channels': ['sms']
                })
                
                assert response.status_code == 200
                data = response.get_json()
                assert data['sent_count'] == 20
                
                # Verify: Personalized messages sent
                for player in players:
                    messages = sms_helper.get_messages_for_user(player.user)
                    assert len(messages) == 1
                    message = messages[0]['message']
                    assert player.user.username in message  # Personalized
                    assert 'Spring 2024' in message
                    assert 'March 15' in message
    
    def test_emergency_broadcast_overrides_preferences(self, db, client):
        """Test emergency messages bypass user preferences."""
        # Setup: Users who opted out
        opted_out_users = []
        for i in range(5):
            user = UserFactory(
                phone_number=f'+1555999{i:04d}',
                sms_notifications=False,  # Opted out
                email_notifications=False
            )
            PlayerFactory(user=user)
            opted_out_users.append(user)
        
        admin = UserFactory()
        admin.roles.append('Admin')
        
        sms_helper = SMSTestHelper()
        
        with AuthTestHelper.authenticated_request(client, admin):
            with patch('app.sms_helpers.send_sms', side_effect=sms_helper.mock_send_sms):
                # Send emergency broadcast
                response = client.post('/admin/messages/emergency', json={
                    'message': 'All matches cancelled due to severe weather warning!',
                    'override_preferences': True
                })
                
                assert response.status_code == 200
                
                # Verify: Even opted-out users received it
                for user in opted_out_users:
                    messages = sms_helper.get_messages_for_user(user)
                    assert len(messages) == 1
                    assert 'severe weather warning' in messages[0]['message']