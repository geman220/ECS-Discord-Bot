"""
Unit tests for SMS helper functions.
"""
import pytest
from unittest.mock import Mock, patch
from datetime import datetime, timedelta
from app.sms_helpers import (
    send_sms_notification, 
    process_incoming_sms, 
    validate_phone_number,
    check_sms_rate_limit,
    format_sms_message
)


@pytest.mark.unit
class TestSMSHelpers:
    """Test SMS helper functions."""
    
    def test_validate_phone_number(self):
        """Test phone number validation."""
        # Valid US numbers
        assert validate_phone_number('+15551234567') == '+15551234567'
        assert validate_phone_number('555-123-4567') == '+15551234567'
        assert validate_phone_number('(555) 123-4567') == '+15551234567'
        assert validate_phone_number('5551234567') == '+15551234567'
        
        # Invalid numbers
        assert validate_phone_number('123') is None
        assert validate_phone_number('abc-def-ghij') is None
        assert validate_phone_number('') is None
        assert validate_phone_number(None) is None
    
    @patch('app.sms_helpers.twilio_client')
    def test_send_sms_success(self, mock_twilio, user):
        """Test successful SMS sending."""
        mock_twilio.messages.create.return_value = Mock(sid='MSG123')
        
        user.phone_number = '555-123-4567'
        result = send_sms_notification(user, 'Test message')
        
        assert result is True
        mock_twilio.messages.create.assert_called_once()
        call_args = mock_twilio.messages.create.call_args
        assert call_args[1]['to'] == '+15551234567'
        assert call_args[1]['body'] == 'Test message'
    
    @patch('app.sms_helpers.twilio_client')
    def test_send_sms_no_phone(self, mock_twilio, user):
        """Test SMS sending with no phone number."""
        user.phone_number = None
        result = send_sms_notification(user, 'Test message')
        
        assert result is False
        mock_twilio.messages.create.assert_not_called()
    
    @patch('app.sms_helpers.twilio_client')
    def test_send_sms_twilio_error(self, mock_twilio, user):
        """Test SMS sending with Twilio error."""
        mock_twilio.messages.create.side_effect = Exception('Twilio error')
        
        user.phone_number = '555-123-4567'
        result = send_sms_notification(user, 'Test message')
        
        assert result is False
    
    @patch('app.sms_helpers.redis_client')
    def test_sms_rate_limiting(self, mock_redis, user):
        """Test SMS rate limiting."""
        # First message - should pass
        mock_redis.get.return_value = None
        assert check_sms_rate_limit(user.id) is True
        
        # Simulate hitting rate limit
        mock_redis.get.return_value = b'5'  # Max messages sent
        assert check_sms_rate_limit(user.id) is False
        
        # Test system-wide rate limit
        mock_redis.get.side_effect = [b'4', b'100']  # User: 4, System: 100
        assert check_sms_rate_limit(user.id) is False  # System limit hit
    
    def test_format_sms_message(self, match, team):
        """Test SMS message formatting."""
        # Match reminder
        message = format_sms_message('match_reminder', {
            'match': match,
            'team': team
        })
        assert 'Test Team' in message
        assert 'June 1' in message
        assert '19:00' in message
        
        # RSVP confirmation
        message = format_sms_message('rsvp_confirm', {
            'available': True,
            'match': match
        })
        assert 'confirmed' in message.lower()
        
        # Invalid template
        message = format_sms_message('invalid_template', {})
        assert message == ''
    
    @patch('app.sms_helpers.db')
    def test_process_incoming_sms_yes(self, mock_db, user, match):
        """Test processing incoming SMS with YES response."""
        from app.models import Availability
        
        # Mock query results
        mock_query = Mock()
        mock_query.filter_by.return_value.first.return_value = user
        mock_db.session.query.return_value = mock_query
        
        # Mock match lookup
        with patch('app.sms_helpers.get_next_match_for_user') as mock_match:
            mock_match.return_value = match
            
            response = process_incoming_sms('+15551234567', 'YES')
            
            assert 'confirmed available' in response
            # Verify availability was created/updated
            mock_db.session.add.assert_called()
            mock_db.session.commit.assert_called()
    
    @patch('app.sms_helpers.db')
    def test_process_incoming_sms_no(self, mock_db, user, match):
        """Test processing incoming SMS with NO response."""
        # Mock query results
        mock_query = Mock()
        mock_query.filter_by.return_value.first.return_value = user
        mock_db.session.query.return_value = mock_query
        
        with patch('app.sms_helpers.get_next_match_for_user') as mock_match:
            mock_match.return_value = match
            
            response = process_incoming_sms('+15551234567', 'NO')
            
            assert 'marked as unavailable' in response
    
    def test_process_incoming_sms_help(self):
        """Test processing incoming SMS with HELP command."""
        response = process_incoming_sms('+15551234567', 'HELP')
        
        assert 'YES - Confirm' in response
        assert 'NO - Decline' in response
        assert 'INFO' in response
    
    def test_process_incoming_sms_stop(self):
        """Test processing incoming SMS with STOP command."""
        response = process_incoming_sms('+15551234567', 'STOP')
        
        assert 'unsubscribed' in response.lower()
    
    @patch('app.sms_helpers.db')
    def test_process_incoming_sms_unknown_number(self, mock_db):
        """Test processing SMS from unknown number."""
        # Mock no user found
        mock_query = Mock()
        mock_query.filter_by.return_value.first.return_value = None
        mock_db.session.query.return_value = mock_query
        
        response = process_incoming_sms('+15559999999', 'YES')
        
        assert 'not recognized' in response
    
    @patch('app.sms_helpers.db')
    def test_process_incoming_sms_no_match(self, mock_db, user):
        """Test processing SMS when no upcoming match."""
        # Mock user found
        mock_query = Mock()
        mock_query.filter_by.return_value.first.return_value = user
        mock_db.session.query.return_value = mock_query
        
        # Mock no match found
        with patch('app.sms_helpers.get_next_match_for_user') as mock_match:
            mock_match.return_value = None
            
            response = process_incoming_sms('+15551234567', 'YES')
            
            assert 'no upcoming match' in response.lower()