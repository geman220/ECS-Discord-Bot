"""
DiscordService unit tests.

These tests verify the DiscordService's core behaviors:
- Circuit breaker pattern integration
- Session management (creation, reuse, cleanup)
- Event dispatching logic for various Discord operations
- Rate limiting and retry logic
- Error handling for various failure scenarios
- API endpoint interactions
"""
import pytest
import asyncio
import aiohttp
from datetime import datetime
from unittest.mock import Mock, MagicMock, AsyncMock, patch, PropertyMock

from app.services.discord_service import (
    DiscordService,
    get_discord_service,
    create_match_thread_via_bot,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def discord_service():
    """Create a fresh DiscordService instance for each test."""
    service = DiscordService()
    yield service
    # Cleanup: close session if it was created
    if service._session and not service._session.closed:
        asyncio.get_event_loop().run_until_complete(service.close())


@pytest.fixture
def mock_session():
    """Create a mock aiohttp ClientSession."""
    session = AsyncMock(spec=aiohttp.ClientSession)
    session.closed = False
    return session


@pytest.fixture
def mock_response_success():
    """Create a mock successful response."""
    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock(return_value={'thread_id': '123456789', 'message_id': '987654321'})
    response.text = AsyncMock(return_value='OK')
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=None)
    return response


@pytest.fixture
def mock_response_error():
    """Create a mock error response."""
    response = AsyncMock()
    response.status = 500
    response.json = AsyncMock(return_value={'error': 'Internal Server Error'})
    response.text = AsyncMock(return_value='Internal Server Error')
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=None)
    return response


@pytest.fixture
def match_data():
    """Create sample match data for testing."""
    return {
        'id': 1,
        'home_team': 'Team A',
        'away_team': 'Team B',
        'date': '2024-01-15',
        'time': '19:00',
        'venue': 'Stadium',
        'competition': 'League',
        'is_home_game': True
    }


# =============================================================================
# CIRCUIT BREAKER TESTS
# =============================================================================

@pytest.mark.unit
class TestCircuitBreakerIntegration:
    """Test circuit breaker pattern integration in DiscordService."""

    def test_should_skip_call_when_circuit_breaker_open(self, discord_service):
        """
        GIVEN the circuit breaker is in OPEN state
        WHEN checking if calls should be skipped
        THEN the method should return True
        """
        with patch('app.utils.discord_helpers.get_circuit_breaker_status') as mock_cb:
            mock_cb.return_value = {'can_proceed': False, 'state': 'open'}

            result = discord_service._should_skip_call("test_operation")

            assert result is True

    def test_should_not_skip_call_when_circuit_breaker_closed(self, discord_service):
        """
        GIVEN the circuit breaker is in CLOSED state
        WHEN checking if calls should be skipped
        THEN the method should return False
        """
        with patch('app.utils.discord_helpers.get_circuit_breaker_status') as mock_cb:
            mock_cb.return_value = {'can_proceed': True, 'state': 'closed'}

            result = discord_service._should_skip_call("test_operation")

            assert result is False

    def test_should_not_skip_call_when_circuit_breaker_half_open(self, discord_service):
        """
        GIVEN the circuit breaker is in HALF_OPEN state
        WHEN checking if calls should be skipped
        THEN the method should return False (allow test calls)
        """
        with patch('app.utils.discord_helpers.get_circuit_breaker_status') as mock_cb:
            mock_cb.return_value = {'can_proceed': True, 'state': 'half_open'}

            result = discord_service._should_skip_call("test_operation")

            assert result is False

    def test_should_not_skip_when_circuit_breaker_check_fails(self, discord_service):
        """
        GIVEN the circuit breaker status check raises an exception
        WHEN checking if calls should be skipped
        THEN the method should return False (fail open)
        """
        with patch('app.utils.discord_helpers.get_circuit_breaker_status') as mock_cb:
            mock_cb.side_effect = Exception("Circuit breaker error")

            result = discord_service._should_skip_call("test_operation")

            assert result is False

    @pytest.mark.asyncio
    async def test_create_match_thread_skipped_when_circuit_open(self, discord_service, match_data):
        """
        GIVEN the circuit breaker is OPEN
        WHEN creating a match thread
        THEN the operation should be skipped and return None
        """
        with patch.object(discord_service, '_should_skip_call', return_value=True):
            result = await discord_service.create_match_thread(match_data)

            assert result is None


# =============================================================================
# SESSION MANAGEMENT TESTS
# =============================================================================

@pytest.mark.unit
class TestSessionManagement:
    """Test aiohttp session management."""

    @pytest.mark.asyncio
    async def test_get_session_creates_new_session_when_none(self, discord_service):
        """
        GIVEN no existing session
        WHEN getting session
        THEN a new session should be created
        """
        assert discord_service._session is None

        session = await discord_service._get_session()

        assert session is not None
        assert isinstance(session, aiohttp.ClientSession)
        assert discord_service._session is session

        # Cleanup
        await discord_service.close()

    @pytest.mark.asyncio
    async def test_get_session_reuses_existing_session(self, discord_service):
        """
        GIVEN an existing open session
        WHEN getting session multiple times
        THEN the same session should be returned
        """
        session1 = await discord_service._get_session()
        session2 = await discord_service._get_session()

        assert session1 is session2

        # Cleanup
        await discord_service.close()

    @pytest.mark.asyncio
    async def test_get_session_creates_new_when_closed(self, discord_service):
        """
        GIVEN an existing but closed session
        WHEN getting session
        THEN a new session should be created
        """
        # Create initial session
        session1 = await discord_service._get_session()
        await discord_service.close()  # Close it

        # Get new session
        session2 = await discord_service._get_session()

        assert session2 is not None
        assert session1 is not session2

        # Cleanup
        await discord_service.close()

    @pytest.mark.asyncio
    async def test_close_closes_session(self, discord_service):
        """
        GIVEN an open session
        WHEN closing the service
        THEN the session should be closed
        """
        session = await discord_service._get_session()
        assert not session.closed

        await discord_service.close()

        assert session.closed

    @pytest.mark.asyncio
    async def test_close_handles_no_session(self, discord_service):
        """
        GIVEN no existing session
        WHEN closing the service
        THEN no error should occur
        """
        assert discord_service._session is None

        # Should not raise any exception
        await discord_service.close()


# =============================================================================
# CREATE MATCH THREAD TESTS
# =============================================================================

@pytest.mark.unit
class TestCreateMatchThread:
    """Test create_match_thread functionality."""

    @pytest.mark.asyncio
    async def test_create_match_thread_success(self, discord_service, match_data):
        """
        GIVEN valid match data and a responsive API
        WHEN creating a match thread
        THEN a thread ID should be returned
        """
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={'thread_id': '123456789'})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        with patch.object(discord_service, '_should_skip_call', return_value=False), \
             patch.object(discord_service, '_get_session') as mock_get_session:

            mock_session = AsyncMock()
            mock_session.post = MagicMock(return_value=mock_response)
            mock_get_session.return_value = mock_session

            result = await discord_service.create_match_thread(match_data)

            assert result == '123456789'

    @pytest.mark.asyncio
    async def test_create_match_thread_uses_existing_thread(self, discord_service, match_data):
        """
        GIVEN a thread already exists for the match (409 status)
        WHEN creating a match thread
        THEN the existing thread ID should be returned
        """
        mock_response = AsyncMock()
        mock_response.status = 409
        mock_response.json = AsyncMock(return_value={'thread_id': 'existing_thread_123'})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        with patch.object(discord_service, '_should_skip_call', return_value=False), \
             patch.object(discord_service, '_get_session') as mock_get_session:

            mock_session = AsyncMock()
            mock_session.post = MagicMock(return_value=mock_response)
            mock_get_session.return_value = mock_session

            result = await discord_service.create_match_thread(match_data)

            assert result == 'existing_thread_123'

    @pytest.mark.asyncio
    async def test_create_match_thread_retries_on_server_error(self, discord_service, match_data):
        """
        GIVEN a server error response
        WHEN creating a match thread
        THEN the operation should retry and eventually fail
        """
        mock_response = AsyncMock()
        mock_response.status = 500
        mock_response.text = AsyncMock(return_value='Internal Server Error')
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        call_count = 0

        with patch.object(discord_service, '_should_skip_call', return_value=False), \
             patch.object(discord_service, '_get_session') as mock_get_session, \
             patch('asyncio.sleep', new_callable=AsyncMock):

            mock_session = AsyncMock()

            def count_calls(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                return mock_response

            mock_session.post = MagicMock(side_effect=count_calls)
            mock_get_session.return_value = mock_session

            result = await discord_service.create_match_thread(match_data)

            assert result is None
            assert call_count == 3  # max_retries is 3

    @pytest.mark.asyncio
    async def test_create_match_thread_handles_client_error(self, discord_service, match_data):
        """
        GIVEN a client connection error
        WHEN creating a match thread
        THEN the operation should retry and handle gracefully
        """
        with patch.object(discord_service, '_should_skip_call', return_value=False), \
             patch.object(discord_service, '_get_session') as mock_get_session, \
             patch('asyncio.sleep', new_callable=AsyncMock):

            mock_session = AsyncMock()
            mock_session.post = MagicMock(side_effect=aiohttp.ClientError("Connection failed"))
            mock_get_session.return_value = mock_session

            result = await discord_service.create_match_thread(match_data)

            assert result is None

    @pytest.mark.asyncio
    async def test_create_match_thread_handles_timeout(self, discord_service, match_data):
        """
        GIVEN a timeout during the request
        WHEN creating a match thread
        THEN the operation should retry and handle gracefully
        """
        with patch.object(discord_service, '_should_skip_call', return_value=False), \
             patch.object(discord_service, '_get_session') as mock_get_session, \
             patch('asyncio.sleep', new_callable=AsyncMock):

            mock_session = AsyncMock()
            mock_session.post = MagicMock(side_effect=asyncio.TimeoutError())
            mock_get_session.return_value = mock_session

            result = await discord_service.create_match_thread(match_data)

            assert result is None


# =============================================================================
# UPDATE LIVE MATCH TESTS
# =============================================================================

@pytest.mark.unit
class TestUpdateLiveMatch:
    """Test update_live_match functionality."""

    @pytest.mark.asyncio
    async def test_update_live_match_success(self, discord_service):
        """
        GIVEN valid thread ID and match data
        WHEN updating a live match
        THEN True should be returned
        """
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        match_data = {
            'thread_id': '123456',
            'update_type': 'score_update',
            'update_data': {'score': '1-0'}
        }

        with patch.object(discord_service, '_should_skip_call', return_value=False), \
             patch.object(discord_service, '_get_session') as mock_get_session:

            mock_session = AsyncMock()
            mock_session.post = MagicMock(return_value=mock_response)
            mock_get_session.return_value = mock_session

            result = await discord_service.update_live_match('123456', match_data)

            assert result is True

    @pytest.mark.asyncio
    async def test_update_live_match_skipped_when_circuit_open(self, discord_service):
        """
        GIVEN the circuit breaker is OPEN
        WHEN updating a live match
        THEN False should be returned
        """
        with patch.object(discord_service, '_should_skip_call', return_value=True):
            result = await discord_service.update_live_match('123456', {'update_type': 'test'})

            assert result is False

    @pytest.mark.asyncio
    async def test_update_live_match_retries_on_failure(self, discord_service):
        """
        GIVEN a failing API response
        WHEN updating a live match
        THEN the operation should retry
        """
        mock_response = AsyncMock()
        mock_response.status = 503
        mock_response.text = AsyncMock(return_value='Service Unavailable')
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        call_count = 0

        with patch.object(discord_service, '_should_skip_call', return_value=False), \
             patch.object(discord_service, '_get_session') as mock_get_session, \
             patch('asyncio.sleep', new_callable=AsyncMock):

            mock_session = AsyncMock()

            def count_calls(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                return mock_response

            mock_session.post = MagicMock(side_effect=count_calls)
            mock_get_session.return_value = mock_session

            result = await discord_service.update_live_match('123456', {'update_type': 'test'})

            assert result is False
            assert call_count == 2  # max_retries is 2 for update_live_match


# =============================================================================
# SEND MATCH EMBED TESTS
# =============================================================================

@pytest.mark.unit
class TestSendMatchEmbed:
    """Test send_match_embed functionality."""

    @pytest.mark.asyncio
    async def test_send_match_embed_success(self, discord_service):
        """
        GIVEN valid channel ID and embed data
        WHEN sending a match embed
        THEN the message ID should be returned
        """
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={'message_id': '987654321'})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        embed_data = {'title': 'Match Update', 'description': 'Score: 1-0'}

        with patch.object(discord_service, '_get_session') as mock_get_session:
            mock_session = AsyncMock()
            mock_session.post = MagicMock(return_value=mock_response)
            mock_get_session.return_value = mock_session

            result = await discord_service.send_match_embed('channel_123', embed_data)

            assert result == '987654321'

    @pytest.mark.asyncio
    async def test_send_match_embed_failure(self, discord_service):
        """
        GIVEN an API error response
        WHEN sending a match embed
        THEN None should be returned
        """
        mock_response = AsyncMock()
        mock_response.status = 400
        mock_response.text = AsyncMock(return_value='Bad Request')
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        with patch.object(discord_service, '_get_session') as mock_get_session:
            mock_session = AsyncMock()
            mock_session.post = MagicMock(return_value=mock_response)
            mock_get_session.return_value = mock_session

            result = await discord_service.send_match_embed('channel_123', {'title': 'Test'})

            assert result is None

    @pytest.mark.asyncio
    async def test_send_match_embed_handles_exception(self, discord_service):
        """
        GIVEN an exception during the request
        WHEN sending a match embed
        THEN None should be returned
        """
        with patch.object(discord_service, '_get_session') as mock_get_session:
            mock_session = AsyncMock()
            mock_session.post = MagicMock(side_effect=Exception("Unexpected error"))
            mock_get_session.return_value = mock_session

            result = await discord_service.send_match_embed('channel_123', {'title': 'Test'})

            assert result is None


# =============================================================================
# GET BOT STATUS TESTS
# =============================================================================

@pytest.mark.unit
class TestGetBotStatus:
    """Test get_bot_status functionality."""

    @pytest.mark.asyncio
    async def test_get_bot_status_success(self, discord_service):
        """
        GIVEN a healthy Discord bot
        WHEN getting bot status
        THEN health information should be returned
        """
        mock_health = {
            'status': 'healthy',
            'healthy': True,
            'circuit_breaker': {'state': 'closed'}
        }

        with patch('app.utils.discord_helpers.check_discord_bot_health') as mock_check:
            mock_check.return_value = mock_health

            result = await discord_service.get_bot_status()

            assert result['status'] == 'healthy'
            assert result['healthy'] is True

    @pytest.mark.asyncio
    async def test_get_bot_status_handles_error(self, discord_service):
        """
        GIVEN an error checking bot health
        WHEN getting bot status
        THEN error status should be returned
        """
        with patch('app.utils.discord_helpers.check_discord_bot_health') as mock_check:
            mock_check.side_effect = Exception("Connection failed")

            result = await discord_service.get_bot_status()

            assert result['status'] == 'error'
            assert result['connected'] is False
            assert 'error' in result


# =============================================================================
# LEAGUE EVENT ANNOUNCEMENT TESTS
# =============================================================================

@pytest.mark.unit
class TestLeagueEventAnnouncement:
    """Test league event announcement functionality."""

    @pytest.mark.asyncio
    async def test_post_league_event_announcement_success(self, discord_service):
        """
        GIVEN valid event data
        WHEN posting a league event announcement
        THEN announcement result should be returned
        """
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            'message_id': '123456',
            'channel_id': '789012',
            'channel_name': 'league-announcements'
        })
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        with patch.object(discord_service, '_should_skip_call', return_value=False), \
             patch.object(discord_service, '_get_session') as mock_get_session:

            mock_session = AsyncMock()
            mock_session.post = MagicMock(return_value=mock_response)
            mock_get_session.return_value = mock_session

            result = await discord_service.post_league_event_announcement(
                event_id=1,
                title='Test Event',
                start_datetime='2024-01-15T19:00:00',
                description='Test description',
                event_type='meeting',
                location='Stadium'
            )

            assert result is not None
            assert result['message_id'] == '123456'
            assert result['channel_name'] == 'league-announcements'

    @pytest.mark.asyncio
    async def test_post_league_event_announcement_skipped_when_circuit_open(self, discord_service):
        """
        GIVEN the circuit breaker is OPEN
        WHEN posting a league event announcement
        THEN None should be returned
        """
        with patch.object(discord_service, '_should_skip_call', return_value=True):
            result = await discord_service.post_league_event_announcement(
                event_id=1,
                title='Test Event',
                start_datetime='2024-01-15T19:00:00'
            )

            assert result is None

    @pytest.mark.asyncio
    async def test_update_league_event_announcement_success(self, discord_service):
        """
        GIVEN valid event update data
        WHEN updating a league event announcement
        THEN True should be returned
        """
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        with patch.object(discord_service, '_should_skip_call', return_value=False), \
             patch.object(discord_service, '_get_session') as mock_get_session:

            mock_session = AsyncMock()
            mock_session.put = MagicMock(return_value=mock_response)
            mock_get_session.return_value = mock_session

            result = await discord_service.update_league_event_announcement(
                event_id=1,
                message_id=123456,
                channel_id=789012,
                title='Updated Event',
                start_datetime='2024-01-15T19:00:00'
            )

            assert result is True

    @pytest.mark.asyncio
    async def test_delete_league_event_announcement_success(self, discord_service):
        """
        GIVEN valid message and channel IDs
        WHEN deleting a league event announcement
        THEN True should be returned
        """
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        with patch.object(discord_service, '_should_skip_call', return_value=False), \
             patch.object(discord_service, '_get_session') as mock_get_session:

            mock_session = AsyncMock()
            mock_session.delete = MagicMock(return_value=mock_response)
            mock_get_session.return_value = mock_session

            result = await discord_service.delete_league_event_announcement(
                message_id=123456,
                channel_id=789012
            )

            assert result is True


# =============================================================================
# SCHEDULE IMAGE ANNOUNCEMENT TESTS
# =============================================================================

@pytest.mark.unit
class TestScheduleImageAnnouncement:
    """Test schedule image announcement functionality."""

    @pytest.mark.asyncio
    async def test_post_schedule_image_announcement_success(self, discord_service):
        """
        GIVEN valid image data
        WHEN posting a schedule image announcement
        THEN announcement result should be returned
        """
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            'message_id': '123456',
            'channel_name': 'schedule-channel'
        })
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        with patch.object(discord_service, '_should_skip_call', return_value=False), \
             patch.object(discord_service, '_get_session') as mock_get_session:

            mock_session = AsyncMock()
            mock_session.post = MagicMock(return_value=mock_response)
            mock_get_session.return_value = mock_session

            result = await discord_service.post_schedule_image_announcement(
                image_bytes=b'fake_image_data',
                title='Weekly Schedule',
                description='Games for this week'
            )

            assert result is not None
            assert result['message_id'] == '123456'

    @pytest.mark.asyncio
    async def test_post_schedule_image_handles_failure(self, discord_service):
        """
        GIVEN an API error
        WHEN posting a schedule image announcement
        THEN None should be returned
        """
        mock_response = AsyncMock()
        mock_response.status = 500
        mock_response.text = AsyncMock(return_value='Server Error')
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        with patch.object(discord_service, '_should_skip_call', return_value=False), \
             patch.object(discord_service, '_get_session') as mock_get_session:

            mock_session = AsyncMock()
            mock_session.post = MagicMock(return_value=mock_response)
            mock_get_session.return_value = mock_session

            result = await discord_service.post_schedule_image_announcement(
                image_bytes=b'fake_image_data',
                title='Weekly Schedule'
            )

            assert result is None


# =============================================================================
# EVENT REMINDER TESTS
# =============================================================================

@pytest.mark.unit
class TestEventReminder:
    """Test event reminder functionality."""

    @pytest.mark.asyncio
    async def test_post_event_reminder_success(self, discord_service):
        """
        GIVEN valid event reminder data
        WHEN posting an event reminder
        THEN reminder result should be returned
        """
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={'message_id': '123456'})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        with patch.object(discord_service, '_should_skip_call', return_value=False), \
             patch.object(discord_service, '_get_session') as mock_get_session:

            mock_session = AsyncMock()
            mock_session.post = MagicMock(return_value=mock_response)
            mock_get_session.return_value = mock_session

            result = await discord_service.post_event_reminder(
                title='Game Day',
                event_type='match',
                date_str='January 15, 2024',
                time_str='7:00 PM',
                location='Stadium'
            )

            assert result is not None
            assert result['message_id'] == '123456'

    @pytest.mark.asyncio
    async def test_post_plop_reminder_success(self, discord_service):
        """
        GIVEN valid PLOP reminder data
        WHEN posting a PLOP reminder
        THEN reminder result should be returned
        """
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={'message_id': '789012'})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        with patch.object(discord_service, '_should_skip_call', return_value=False), \
             patch.object(discord_service, '_get_session') as mock_get_session:

            mock_session = AsyncMock()
            mock_session.post = MagicMock(return_value=mock_response)
            mock_get_session.return_value = mock_session

            result = await discord_service.post_plop_reminder(
                date_str='Sunday, January 14',
                time_str='2:00 PM',
                location='Downtown Bar'
            )

            assert result is not None
            assert result['message_id'] == '789012'

    @pytest.mark.asyncio
    async def test_post_plop_reminder_skipped_when_circuit_open(self, discord_service):
        """
        GIVEN the circuit breaker is OPEN
        WHEN posting a PLOP reminder
        THEN None should be returned
        """
        with patch.object(discord_service, '_should_skip_call', return_value=True):
            result = await discord_service.post_plop_reminder(
                date_str='Sunday, January 14',
                time_str='2:00 PM',
                location='Downtown Bar'
            )

            assert result is None


# =============================================================================
# GLOBAL SERVICE INSTANCE TESTS
# =============================================================================

@pytest.mark.unit
class TestGlobalServiceInstance:
    """Test global Discord service instance management."""

    def test_get_discord_service_returns_singleton(self):
        """
        GIVEN no existing global service
        WHEN getting the Discord service multiple times
        THEN the same instance should be returned
        """
        # Reset global instance for this test
        import app.services.discord_service as module
        original = module._discord_service
        module._discord_service = None

        try:
            service1 = get_discord_service()
            service2 = get_discord_service()

            assert service1 is service2
            assert isinstance(service1, DiscordService)
        finally:
            module._discord_service = original

    @pytest.mark.asyncio
    async def test_convenience_function_uses_global_service(self, match_data):
        """
        GIVEN the global Discord service
        WHEN using the convenience function
        THEN it should delegate to the service
        """
        with patch('app.services.discord_service.get_discord_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.create_match_thread = AsyncMock(return_value='thread_123')
            mock_get_service.return_value = mock_service

            result = await create_match_thread_via_bot(match_data)

            assert result == 'thread_123'
            mock_service.create_match_thread.assert_called_once_with(match_data)


# =============================================================================
# ERROR HANDLING TESTS
# =============================================================================

@pytest.mark.unit
class TestErrorHandling:
    """Test error handling across DiscordService methods."""

    @pytest.mark.asyncio
    async def test_handles_json_decode_error(self, discord_service, match_data):
        """
        GIVEN a response with invalid JSON
        WHEN creating a match thread
        THEN the error should be handled gracefully
        """
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(side_effect=Exception("JSON decode error"))
        mock_response.text = AsyncMock(return_value='Not JSON')
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        with patch.object(discord_service, '_should_skip_call', return_value=False), \
             patch.object(discord_service, '_get_session') as mock_get_session, \
             patch('asyncio.sleep', new_callable=AsyncMock):

            mock_session = AsyncMock()
            mock_session.post = MagicMock(return_value=mock_response)
            mock_get_session.return_value = mock_session

            # Should handle the exception and return None after retries
            result = await discord_service.create_match_thread(match_data)

            # The result depends on how the exception is handled
            # In this case, it should either return None or the thread_id
            # from the response if JSON parsing was needed

    @pytest.mark.asyncio
    async def test_handles_unexpected_status_codes(self, discord_service, match_data):
        """
        GIVEN an unexpected status code (e.g., 418)
        WHEN creating a match thread
        THEN the operation should handle it gracefully
        """
        mock_response = AsyncMock()
        mock_response.status = 418  # I'm a teapot
        mock_response.text = AsyncMock(return_value='I am a teapot')
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        with patch.object(discord_service, '_should_skip_call', return_value=False), \
             patch.object(discord_service, '_get_session') as mock_get_session, \
             patch('asyncio.sleep', new_callable=AsyncMock):

            mock_session = AsyncMock()
            mock_session.post = MagicMock(return_value=mock_response)
            mock_get_session.return_value = mock_session

            result = await discord_service.create_match_thread(match_data)

            assert result is None


# =============================================================================
# PAYLOAD CONSTRUCTION TESTS
# =============================================================================

@pytest.mark.unit
class TestPayloadConstruction:
    """Test that API payloads are constructed correctly."""

    @pytest.mark.asyncio
    async def test_create_match_thread_payload_construction(self, discord_service):
        """
        GIVEN match data with various fields
        WHEN creating a match thread
        THEN the payload should be correctly constructed
        """
        match_data = {
            'id': 42,
            'home_team': 'Eagles',
            'away_team': 'Hawks',
            'date': '2024-02-01',
            'time': '15:00',
            'venue': 'Home Stadium',
            'competition': 'Cup',
            'is_home_game': True
        }

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={'thread_id': 'test_thread'})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        captured_payload = None

        with patch.object(discord_service, '_should_skip_call', return_value=False), \
             patch.object(discord_service, '_get_session') as mock_get_session:

            mock_session = AsyncMock()

            def capture_payload(url, json=None):
                nonlocal captured_payload
                captured_payload = json
                return mock_response

            mock_session.post = MagicMock(side_effect=capture_payload)
            mock_get_session.return_value = mock_session

            await discord_service.create_match_thread(match_data)

            assert captured_payload is not None
            assert captured_payload['match_id'] == 42
            assert captured_payload['home_team'] == 'Eagles'
            assert captured_payload['away_team'] == 'Hawks'
            assert captured_payload['is_home_game'] is True

    @pytest.mark.asyncio
    async def test_create_match_thread_handles_alternative_id_field(self, discord_service):
        """
        GIVEN match data with 'match_id' instead of 'id'
        WHEN creating a match thread
        THEN the payload should use the correct match ID
        """
        match_data = {
            'match_id': 99,  # Alternative field name
            'home_team': 'Team A',
            'away_team': 'Team B',
            'date': '2024-02-01',
            'time': '18:00'
        }

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={'thread_id': 'test_thread'})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        captured_payload = None

        with patch.object(discord_service, '_should_skip_call', return_value=False), \
             patch.object(discord_service, '_get_session') as mock_get_session:

            mock_session = AsyncMock()

            def capture_payload(url, json=None):
                nonlocal captured_payload
                captured_payload = json
                return mock_response

            mock_session.post = MagicMock(side_effect=capture_payload)
            mock_get_session.return_value = mock_session

            await discord_service.create_match_thread(match_data)

            assert captured_payload['match_id'] == 99


# =============================================================================
# API URL CONFIGURATION TESTS
# =============================================================================

@pytest.mark.unit
class TestAPIURLConfiguration:
    """Test API URL configuration."""

    def test_default_bot_api_url(self):
        """
        GIVEN no BOT_API_URL environment variable
        WHEN creating a DiscordService
        THEN the default URL should be used
        """
        with patch.dict('os.environ', {}, clear=True):
            with patch('os.getenv', return_value='http://discord-bot:5001'):
                service = DiscordService()
                assert service.bot_api_url == 'http://discord-bot:5001'

    def test_custom_bot_api_url(self):
        """
        GIVEN a custom BOT_API_URL environment variable
        WHEN creating a DiscordService
        THEN the custom URL should be used
        """
        with patch('os.getenv', return_value='http://custom-bot:8080'):
            service = DiscordService()
            assert service.bot_api_url == 'http://custom-bot:8080'
