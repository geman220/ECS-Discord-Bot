"""
Unit tests for SMS helper functions.
"""
import pytest
from unittest.mock import Mock, patch
from datetime import datetime, timedelta
from app.sms_helpers import (
    send_sms,
    handle_incoming_text_command,
    check_sms_rate_limit,
    handle_rsvp,
    get_upcoming_match_for_player
)


@pytest.mark.unit
class TestSMSHelpers:
    """Test SMS helper functions."""
    
    @patch('app.sms_helpers.twilio_client')
    def test_send_sms_success(self, mock_twilio):
        """Test successful SMS sending."""
        mock_twilio.messages.create.return_value = Mock(sid='MSG123')
        
        result = send_sms('+15551234567', 'Test message', user_id=1)
        
        assert result is True
        mock_twilio.messages.create.assert_called_once()
    
    @patch('app.sms_helpers.twilio_client')
    def test_send_sms_twilio_error(self, mock_twilio):
        """Test SMS sending with Twilio error."""
        mock_twilio.messages.create.side_effect = Exception('Twilio error')
        
        result = send_sms('+15551234567', 'Test message')
        
        assert result is False
    
    @patch('app.sms_helpers.redis_client')
    def test_sms_rate_limiting(self, mock_redis):
        """Test SMS rate limiting."""
        # First message - should pass
        mock_redis.get.return_value = None
        assert check_sms_rate_limit(1) is True
        
        # Simulate hitting rate limit
        mock_redis.get.return_value = b'5'  # Max messages sent
        assert check_sms_rate_limit(1) is False
    
    @patch('app.sms_helpers.db')
    @patch('app.sms_helpers.Player')
    def test_handle_incoming_text_yes(self, mock_player, mock_db):
        """Test processing incoming SMS with YES response."""
        # Mock player lookup
        mock_player_instance = Mock()
        mock_player.query.filter_by.return_value.first.return_value = mock_player_instance
        
        with patch('app.sms_helpers.handle_rsvp') as mock_handle_rsvp:
            mock_handle_rsvp.return_value = "You are confirmed available"
            
            response = handle_incoming_text_command('+15551234567', 'YES')
            
            assert 'confirmed available' in response
    
    def test_handle_incoming_text_help(self):
        """Test processing incoming SMS with HELP command."""
        with patch('app.sms_helpers.send_help_message') as mock_help:
            mock_help.return_value = True
            
            response = handle_incoming_text_command('+15551234567', 'HELP')
            
            mock_help.assert_called_once()
    
    def test_handle_incoming_text_stop(self):
        """Test processing incoming SMS with STOP command."""
        with patch('app.sms_helpers.Player') as mock_player:
            mock_player_instance = Mock()
            mock_player.query.filter_by.return_value.first.return_value = mock_player_instance
            
            with patch('app.sms_helpers.handle_opt_out') as mock_opt_out:
                response = handle_incoming_text_command('+15551234567', 'STOP')
                
                mock_opt_out.assert_called_once()
    
    @patch('app.sms_helpers.db')
    def test_get_upcoming_match_for_player(self, mock_db):
        """Test getting upcoming match for player."""
        from app.models import Player, Match, Team
        
        # Mock player with team
        player = Mock()
        player.team_id = 1
        player.team = Mock()
        player.team.matches = []
        
        # Mock match
        match = Mock()
        match.scheduled_date = datetime.now() + timedelta(days=3)
        match.is_future_match = True
        
        with patch('app.sms_helpers.Match') as mock_match:
            mock_query = Mock()
            mock_query.filter.return_value.order_by.return_value.first.return_value = match
            mock_match.query = mock_query
            
            result = get_upcoming_match_for_player(player)
            
            assert result == match
    
    @patch('app.sms_helpers.db')
    def test_handle_rsvp_yes(self, mock_db):
        """Test handling RSVP YES response."""
        from app.models import Player, Availability
        
        player = Mock()
        player.id = 1
        player.user_id = 1
        
        with patch('app.sms_helpers.get_upcoming_match_for_player') as mock_get_match:
            match = Mock()
            match.id = 1
            mock_get_match.return_value = match
            
            with patch('app.sms_helpers.Availability') as mock_availability:
                response = handle_rsvp(player, 'YES')
                
                assert 'confirmed' in response.lower()
                mock_db.session.add.assert_called()
                mock_db.session.commit.assert_called()
    
    @patch('app.sms_helpers.db')
    def test_handle_rsvp_no_match(self, mock_db):
        """Test handling RSVP when no upcoming match."""
        player = Mock()
        
        with patch('app.sms_helpers.get_upcoming_match_for_player') as mock_get_match:
            mock_get_match.return_value = None
            
            response = handle_rsvp(player, 'YES')
            
            assert 'no upcoming match' in response.lower()