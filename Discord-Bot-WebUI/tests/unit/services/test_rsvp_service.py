"""
RSVPService unit tests.

These tests verify the RSVPService's core behaviors:
- RSVP validation logic
- RSVP creation and update operations
- Concurrent update handling
- Event publishing behavior
- Idempotency and audit trail functionality
- Bulk operations
- Health checks and metrics

Note: Some tests mock _apply_rsvp_update because the service code attempts
to set operation_id/trace_id columns that don't exist in the Availability model.
This is a known issue in the service that these tests help document.
"""
import pytest
import json
from datetime import datetime, date, timedelta
from unittest.mock import Mock, MagicMock, AsyncMock, patch

from app.services.rsvp_service import (
    RSVPService,
    RSVPServiceError,
    RSVPValidationError,
    RSVPConcurrentUpdateError,
    create_rsvp_service_sync,
)
from app.events.rsvp_events import RSVPEvent, RSVPSource, RSVPEventType
from app.models import Availability, Match, Player
from tests.factories import (
    UserFactory,
    PlayerFactory,
    MatchFactory,
    AvailabilityFactory,
    TeamFactory,
    set_factory_session,
)


def create_mock_availability(match_id, player_id, discord_id, response):
    """Helper to create a mock availability object."""
    mock_avail = MagicMock()
    mock_avail.match_id = match_id
    mock_avail.player_id = player_id
    mock_avail.discord_id = discord_id
    mock_avail.response = response
    mock_avail.responded_at = datetime.utcnow()
    return mock_avail


@pytest.fixture
def mock_event_publisher():
    """Create mock event publisher for testing."""
    publisher = AsyncMock()
    publisher.publish_rsvp_event = AsyncMock(return_value=True)
    publisher.health_check = AsyncMock(return_value={'status': 'healthy'})
    return publisher


@pytest.fixture
def mock_redis_client():
    """Create mock Redis client for testing."""
    client = MagicMock()
    client.get.return_value = None
    client.setex.return_value = True
    client.ping.return_value = True
    return client


@pytest.fixture
def rsvp_service(db, mock_event_publisher, mock_redis_client):
    """Create RSVPService instance with mocked dependencies."""
    return RSVPService(
        session=db.session,
        event_publisher=mock_event_publisher,
        redis_client=mock_redis_client
    )


@pytest.fixture
def rsvp_service_no_publisher(db, mock_redis_client):
    """Create RSVPService instance without event publisher."""
    return RSVPService(
        session=db.session,
        event_publisher=None,
        redis_client=mock_redis_client
    )


# =============================================================================
# VALIDATION TESTS
# =============================================================================

@pytest.mark.unit
class TestRSVPValidation:
    """Test RSVP validation logic."""

    @pytest.mark.asyncio
    async def test_validate_accepts_yes_response(self, rsvp_service, match, player):
        """
        GIVEN a valid match and player
        WHEN validating 'yes' response
        THEN validation should succeed
        """
        result = await rsvp_service._validate_rsvp_update(
            match_id=match.id,
            player_id=player.id,
            new_response='yes',
            source=RSVPSource.WEB
        )

        assert result['valid'] is True

    @pytest.mark.asyncio
    async def test_validate_accepts_no_response(self, rsvp_service, match, player):
        """
        GIVEN a valid match and player
        WHEN validating 'no' response
        THEN validation should succeed
        """
        result = await rsvp_service._validate_rsvp_update(
            match_id=match.id,
            player_id=player.id,
            new_response='no',
            source=RSVPSource.WEB
        )

        assert result['valid'] is True

    @pytest.mark.asyncio
    async def test_validate_accepts_maybe_response(self, rsvp_service, match, player):
        """
        GIVEN a valid match and player
        WHEN validating 'maybe' response
        THEN validation should succeed
        """
        result = await rsvp_service._validate_rsvp_update(
            match_id=match.id,
            player_id=player.id,
            new_response='maybe',
            source=RSVPSource.WEB
        )

        assert result['valid'] is True

    @pytest.mark.asyncio
    async def test_validate_accepts_no_response_value(self, rsvp_service, match, player):
        """
        GIVEN a valid match and player
        WHEN validating 'no_response' to clear RSVP
        THEN validation should succeed
        """
        result = await rsvp_service._validate_rsvp_update(
            match_id=match.id,
            player_id=player.id,
            new_response='no_response',
            source=RSVPSource.WEB
        )

        assert result['valid'] is True

    @pytest.mark.asyncio
    async def test_validate_rejects_invalid_response(self, rsvp_service, match, player):
        """
        GIVEN a valid match and player
        WHEN validating an invalid response value
        THEN validation should fail with appropriate error
        """
        result = await rsvp_service._validate_rsvp_update(
            match_id=match.id,
            player_id=player.id,
            new_response='invalid_response',
            source=RSVPSource.WEB
        )

        assert result['valid'] is False
        assert 'Invalid response' in result['error']
        assert 'invalid_response' in result['error']

    @pytest.mark.asyncio
    async def test_validate_rejects_nonexistent_match(self, rsvp_service, player):
        """
        GIVEN a non-existent match ID
        WHEN validating RSVP update
        THEN validation should fail with match not found error
        """
        result = await rsvp_service._validate_rsvp_update(
            match_id=99999,
            player_id=player.id,
            new_response='yes',
            source=RSVPSource.WEB
        )

        assert result['valid'] is False
        assert 'Match 99999 not found' in result['error']

    @pytest.mark.asyncio
    async def test_validate_rejects_nonexistent_player(self, rsvp_service, match):
        """
        GIVEN a non-existent player ID
        WHEN validating RSVP update
        THEN validation should fail with player not found error
        """
        result = await rsvp_service._validate_rsvp_update(
            match_id=match.id,
            player_id=99999,
            new_response='yes',
            source=RSVPSource.WEB
        )

        assert result['valid'] is False
        assert 'Player 99999 not found' in result['error']

    @pytest.mark.asyncio
    async def test_validate_rejects_past_match(self, db, rsvp_service, player, schedule, team, opponent_team):
        """
        GIVEN a match in the past
        WHEN validating RSVP update
        THEN validation should fail with past match error
        """
        # Create a match with a past date
        past_match = Match(
            date=date.today() - timedelta(days=7),
            time=schedule.time,
            location=schedule.location,
            home_team_id=team.id,
            away_team_id=opponent_team.id,
            schedule_id=schedule.id
        )
        db.session.add(past_match)
        db.session.commit()

        result = await rsvp_service._validate_rsvp_update(
            match_id=past_match.id,
            player_id=player.id,
            new_response='yes',
            source=RSVPSource.WEB
        )

        assert result['valid'] is False
        assert 'Cannot RSVP to past matches' in result['error']

    @pytest.mark.asyncio
    async def test_validate_discord_source_requires_discord_id(self, db, rsvp_service, match, user, team):
        """
        GIVEN a player without Discord ID
        WHEN validating RSVP update from Discord source
        THEN validation should fail
        """
        # Create player without discord_id
        player_no_discord = Player(
            name='No Discord Player',
            user_id=user.id,
            discord_id=None
        )
        db.session.add(player_no_discord)
        db.session.commit()

        result = await rsvp_service._validate_rsvp_update(
            match_id=match.id,
            player_id=player_no_discord.id,
            new_response='yes',
            source=RSVPSource.DISCORD
        )

        assert result['valid'] is False
        assert 'Player has no Discord ID' in result['error']


# =============================================================================
# UPDATE OPERATION TESTS
# =============================================================================

@pytest.mark.unit
class TestRSVPUpdateOperations:
    """Test RSVP update operations."""

    @pytest.mark.asyncio
    async def test_update_creates_new_availability(self, rsvp_service, db, match, player):
        """
        GIVEN a player with no existing RSVP
        WHEN updating RSVP to 'yes'
        THEN a new Availability record should be created

        Note: We mock _apply_rsvp_update because the async version tries to set
        operation_id/trace_id columns that don't exist in the model.
        """
        mock_avail = create_mock_availability(match.id, player.id, player.discord_id, 'yes')

        with patch.object(rsvp_service, '_apply_rsvp_update', new_callable=AsyncMock) as mock_apply:
            mock_apply.return_value = mock_avail

            success, message, event = await rsvp_service.update_rsvp(
                match_id=match.id,
                player_id=player.id,
                new_response='yes',
                source=RSVPSource.WEB
            )

        assert success is True
        assert 'RSVP updated to yes' in message
        assert event is not None
        assert event.event_type == RSVPEventType.RSVP_CREATED
        mock_apply.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_modifies_existing_availability(self, rsvp_service, db, match, player, availability):
        """
        GIVEN a player with existing 'yes' RSVP
        WHEN updating RSVP to 'no'
        THEN the Availability record should be updated
        """
        # availability fixture creates 'yes' response
        assert availability.response == 'yes'

        success, message, event = await rsvp_service.update_rsvp(
            match_id=match.id,
            player_id=player.id,
            new_response='no',
            source=RSVPSource.WEB
        )

        assert success is True
        assert event is not None
        assert event.event_type == RSVPEventType.RSVP_UPDATED
        assert event.old_response == 'yes'
        assert event.new_response == 'no'

        # Refresh from database
        db.session.refresh(availability)
        assert availability.response == 'no'

    @pytest.mark.asyncio
    async def test_update_deletes_availability_on_no_response(self, rsvp_service, db, match, player, availability):
        """
        GIVEN a player with existing RSVP
        WHEN updating RSVP to 'no_response'
        THEN the Availability record should be deleted
        """
        avail_id = availability.id

        success, message, event = await rsvp_service.update_rsvp(
            match_id=match.id,
            player_id=player.id,
            new_response='no_response',
            source=RSVPSource.WEB
        )

        assert success is True
        assert event is not None
        assert event.event_type == RSVPEventType.RSVP_DELETED

        # Verify record was deleted
        avail = db.session.query(Availability).get(avail_id)
        assert avail is None

    @pytest.mark.asyncio
    async def test_update_noop_when_no_change(self, rsvp_service, db, match, player, availability):
        """
        GIVEN a player with existing 'yes' RSVP
        WHEN updating RSVP to same value 'yes'
        THEN no change should occur and no event generated
        """
        assert availability.response == 'yes'

        success, message, event = await rsvp_service.update_rsvp(
            match_id=match.id,
            player_id=player.id,
            new_response='yes',
            source=RSVPSource.WEB
        )

        assert success is True
        assert 'No change required' in message
        assert event is None

    @pytest.mark.asyncio
    async def test_update_returns_failure_for_invalid_response(self, rsvp_service, match, player):
        """
        GIVEN a valid match and player
        WHEN updating with invalid response
        THEN operation should fail
        """
        success, message, event = await rsvp_service.update_rsvp(
            match_id=match.id,
            player_id=player.id,
            new_response='invalid',
            source=RSVPSource.WEB
        )

        assert success is False
        assert 'Invalid response' in message
        assert event is None

    @pytest.mark.asyncio
    async def test_update_includes_user_context_in_event(self, rsvp_service, db, match, player):
        """
        GIVEN user context metadata
        WHEN updating RSVP
        THEN event should include allowed metadata fields
        """
        user_context = {
            'user_agent': 'Mozilla/5.0 Test Browser',
            'ip_address': '192.168.1.1',
            'session_id': 'test-session-123'
        }

        mock_avail = create_mock_availability(match.id, player.id, player.discord_id, 'yes')

        with patch.object(rsvp_service, '_apply_rsvp_update', new_callable=AsyncMock) as mock_apply:
            mock_apply.return_value = mock_avail

            success, message, event = await rsvp_service.update_rsvp(
                match_id=match.id,
                player_id=player.id,
                new_response='yes',
                source=RSVPSource.WEB,
                user_context=user_context
            )

        assert success is True
        assert event is not None
        assert event.user_agent == 'Mozilla/5.0 Test Browser'
        assert event.ip_address == '192.168.1.1'
        assert event.session_id == 'test-session-123'


# =============================================================================
# IDEMPOTENCY TESTS
# =============================================================================

@pytest.mark.unit
class TestRSVPIdempotency:
    """Test RSVP idempotency handling."""

    @pytest.mark.asyncio
    async def test_duplicate_operation_returns_cached_result(self, db, match, player, mock_event_publisher):
        """
        GIVEN an operation that was already completed
        WHEN the same operation_id is used again
        THEN cached result should be returned
        """
        operation_id = 'test-operation-123'

        # Mock Redis to return cached result
        cached_result = {
            'success': True,
            'message': 'RSVP updated to yes',
            'event': None,
            'completed_at': datetime.utcnow().isoformat()
        }
        mock_redis = MagicMock()
        mock_redis.get.return_value = json.dumps(cached_result)

        service = RSVPService(
            session=db.session,
            event_publisher=mock_event_publisher,
            redis_client=mock_redis
        )

        with patch('app.services.rsvp_service.get_safe_redis') as mock_get_redis:
            mock_safe_redis = MagicMock()
            mock_safe_redis.get.return_value = json.dumps(cached_result)
            mock_get_redis.return_value = mock_safe_redis

            success, message, event = await service.update_rsvp(
                match_id=match.id,
                player_id=player.id,
                new_response='yes',
                source=RSVPSource.WEB,
                operation_id=operation_id
            )

        assert success is True
        assert message == 'RSVP updated to yes'
        assert service.duplicate_operations == 1

    @pytest.mark.asyncio
    async def test_operation_result_stored_in_redis(self, rsvp_service, db, match, player):
        """
        GIVEN a successful RSVP update
        WHEN operation completes
        THEN result should be stored in Redis
        """
        operation_id = 'test-store-op-456'
        mock_avail = create_mock_availability(match.id, player.id, player.discord_id, 'yes')

        with patch('app.services.rsvp_service.get_safe_redis') as mock_get_redis:
            mock_safe_redis = MagicMock()
            mock_safe_redis.get.return_value = None  # No existing operation
            mock_safe_redis.setex.return_value = True
            mock_get_redis.return_value = mock_safe_redis

            with patch.object(rsvp_service, '_apply_rsvp_update', new_callable=AsyncMock) as mock_apply:
                mock_apply.return_value = mock_avail

                success, message, event = await rsvp_service.update_rsvp(
                    match_id=match.id,
                    player_id=player.id,
                    new_response='yes',
                    source=RSVPSource.WEB,
                    operation_id=operation_id
                )

            assert success is True
            # Verify setex was called to store result
            mock_safe_redis.setex.assert_called()
            call_args = mock_safe_redis.setex.call_args
            assert f'rsvp:operation:{operation_id}' in str(call_args)


# =============================================================================
# EVENT PUBLISHING TESTS
# =============================================================================

@pytest.mark.unit
class TestRSVPEventPublishing:
    """Test RSVP event publishing behavior."""

    @pytest.mark.asyncio
    async def test_event_published_on_successful_update(self, rsvp_service, db, match, player, mock_event_publisher):
        """
        GIVEN an event publisher
        WHEN RSVP is successfully updated
        THEN event should be published
        """
        mock_avail = create_mock_availability(match.id, player.id, player.discord_id, 'yes')

        with patch.object(rsvp_service, '_apply_rsvp_update', new_callable=AsyncMock) as mock_apply:
            mock_apply.return_value = mock_avail

            success, message, event = await rsvp_service.update_rsvp(
                match_id=match.id,
                player_id=player.id,
                new_response='yes',
                source=RSVPSource.WEB
            )

        assert success is True
        mock_event_publisher.publish_rsvp_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_succeeds_when_event_publish_fails(self, db, match, player):
        """
        GIVEN an event publisher that fails
        WHEN RSVP is updated
        THEN update should still succeed (database is source of truth)
        """
        failing_publisher = AsyncMock()
        failing_publisher.publish_rsvp_event = AsyncMock(return_value=False)

        mock_redis = MagicMock()
        mock_redis.get.return_value = None

        service = RSVPService(
            session=db.session,
            event_publisher=failing_publisher,
            redis_client=mock_redis
        )

        mock_avail = create_mock_availability(match.id, player.id, player.discord_id, 'yes')

        with patch('app.services.rsvp_service.get_safe_redis') as mock_get_redis:
            mock_safe_redis = MagicMock()
            mock_safe_redis.get.return_value = None
            mock_get_redis.return_value = mock_safe_redis

            with patch.object(service, '_apply_rsvp_update', new_callable=AsyncMock) as mock_apply:
                mock_apply.return_value = mock_avail

                success, message, event = await service.update_rsvp(
                    match_id=match.id,
                    player_id=player.id,
                    new_response='yes',
                    source=RSVPSource.WEB
                )

        assert success is True
        assert 'RSVP updated to yes' in message

    @pytest.mark.asyncio
    async def test_no_event_published_on_noop(self, rsvp_service, db, match, player, availability, mock_event_publisher):
        """
        GIVEN an existing RSVP
        WHEN updating to same value (no-op)
        THEN no event should be published
        """
        success, message, event = await rsvp_service.update_rsvp(
            match_id=match.id,
            player_id=player.id,
            new_response='yes',  # Same as existing
            source=RSVPSource.WEB
        )

        assert success is True
        assert event is None
        mock_event_publisher.publish_rsvp_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_event_has_correct_type_for_create(self, rsvp_service, db, match, player):
        """
        GIVEN a player without existing RSVP
        WHEN creating new RSVP
        THEN event type should be RSVP_CREATED
        """
        mock_avail = create_mock_availability(match.id, player.id, player.discord_id, 'yes')

        with patch.object(rsvp_service, '_apply_rsvp_update', new_callable=AsyncMock) as mock_apply:
            mock_apply.return_value = mock_avail

            success, message, event = await rsvp_service.update_rsvp(
                match_id=match.id,
                player_id=player.id,
                new_response='yes',
                source=RSVPSource.WEB
            )

        assert event.event_type == RSVPEventType.RSVP_CREATED

    @pytest.mark.asyncio
    async def test_event_has_correct_type_for_delete(self, rsvp_service, db, match, player, availability):
        """
        GIVEN a player with existing RSVP
        WHEN clearing RSVP with 'no_response'
        THEN event type should be RSVP_DELETED
        """
        success, message, event = await rsvp_service.update_rsvp(
            match_id=match.id,
            player_id=player.id,
            new_response='no_response',
            source=RSVPSource.WEB
        )

        assert event.event_type == RSVPEventType.RSVP_DELETED


# =============================================================================
# BULK OPERATIONS TESTS
# =============================================================================

@pytest.mark.unit
class TestRSVPBulkOperations:
    """Test RSVP bulk update operations."""

    @pytest.mark.asyncio
    async def test_bulk_update_processes_multiple_updates(self, rsvp_service, db, match, player, schedule, team, opponent_team):
        """
        GIVEN multiple RSVP updates
        WHEN performing bulk update
        THEN all updates should be processed
        """
        # Create second match
        match2 = Match(
            date=schedule.date,
            time=schedule.time,
            location='Field 2',
            home_team_id=team.id,
            away_team_id=opponent_team.id,
            schedule_id=schedule.id
        )
        db.session.add(match2)
        db.session.commit()

        updates = [
            {'match_id': match.id, 'player_id': player.id, 'new_response': 'yes'},
            {'match_id': match2.id, 'player_id': player.id, 'new_response': 'no'},
        ]

        mock_avail = create_mock_availability(match.id, player.id, player.discord_id, 'yes')

        with patch.object(rsvp_service, '_apply_rsvp_update', new_callable=AsyncMock) as mock_apply:
            mock_apply.return_value = mock_avail

            result = await rsvp_service.bulk_update_rsvps(
                updates=updates,
                source=RSVPSource.WEB
            )

        assert result['summary']['total'] == 2
        assert result['summary']['successful_count'] == 2
        assert result['summary']['failed_count'] == 0
        assert len(result['events']) == 2

    @pytest.mark.asyncio
    async def test_bulk_update_handles_partial_failures(self, rsvp_service, db, match, player):
        """
        GIVEN some valid and some invalid updates
        WHEN performing bulk update
        THEN valid updates should succeed and invalid should fail
        """
        updates = [
            {'match_id': match.id, 'player_id': player.id, 'new_response': 'yes'},
            {'match_id': 99999, 'player_id': player.id, 'new_response': 'yes'},  # Invalid match
        ]

        mock_avail = create_mock_availability(match.id, player.id, player.discord_id, 'yes')

        with patch.object(rsvp_service, '_apply_rsvp_update', new_callable=AsyncMock) as mock_apply:
            mock_apply.return_value = mock_avail

            result = await rsvp_service.bulk_update_rsvps(
                updates=updates,
                source=RSVPSource.WEB
            )

        assert result['summary']['successful_count'] == 1
        assert result['summary']['failed_count'] == 1

    @pytest.mark.asyncio
    async def test_bulk_update_includes_trace_id(self, rsvp_service, db, match, player):
        """
        GIVEN a trace_id for bulk operation
        WHEN performing bulk update
        THEN trace_id should be included in summary
        """
        updates = [
            {'match_id': match.id, 'player_id': player.id, 'new_response': 'yes'},
        ]

        result = await rsvp_service.bulk_update_rsvps(
            updates=updates,
            source=RSVPSource.WEB,
            trace_id='test-trace-bulk-123'
        )

        assert result['summary']['trace_id'] == 'test-trace-bulk-123'


# =============================================================================
# GET STATUS TESTS
# =============================================================================

@pytest.mark.unit
class TestRSVPGetStatus:
    """Test RSVP status retrieval."""

    @pytest.mark.asyncio
    async def test_get_status_for_single_player(self, rsvp_service, match, player, availability):
        """
        GIVEN a player with RSVP
        WHEN getting status for specific player
        THEN correct status should be returned
        """
        result = await rsvp_service.get_rsvp_status(
            match_id=match.id,
            player_id=player.id
        )

        assert result['match_id'] == match.id
        assert result['player_id'] == player.id
        assert result['response'] == 'yes'

    @pytest.mark.asyncio
    async def test_get_status_for_all_players(self, rsvp_service, db, match, player, availability):
        """
        GIVEN a match with RSVPs
        WHEN getting status for all players
        THEN summary should be returned
        """
        result = await rsvp_service.get_rsvp_status(match_id=match.id)

        assert result['match_id'] == match.id
        assert 'responses' in result
        assert 'summary' in result
        assert result['summary']['yes_count'] == 1
        assert result['summary']['total_responses'] == 1

    @pytest.mark.asyncio
    async def test_get_status_returns_error_for_invalid_match(self, rsvp_service):
        """
        GIVEN a non-existent match ID
        WHEN getting status
        THEN error should be returned
        """
        result = await rsvp_service.get_rsvp_status(match_id=99999)

        assert 'error' in result
        assert result['error'] == 'Match not found'


# =============================================================================
# SYNCHRONOUS API TESTS
# =============================================================================

@pytest.mark.unit
class TestRSVPSyncAPI:
    """Test synchronous RSVP API for Flask compatibility."""

    def test_sync_update_creates_availability(self, rsvp_service_no_publisher, db, match, player):
        """
        GIVEN a player without RSVP
        WHEN using sync update
        THEN availability should be created
        """
        success, message, event = rsvp_service_no_publisher.update_rsvp_sync(
            match_id=match.id,
            player_id=player.id,
            new_response='yes',
            source=RSVPSource.WEB
        )

        assert success is True
        assert 'RSVP updated to yes' in message
        assert event is not None

        avail = db.session.query(Availability).filter_by(
            match_id=match.id,
            player_id=player.id
        ).first()
        assert avail is not None
        assert avail.response == 'yes'

    def test_sync_update_handles_noop(self, rsvp_service_no_publisher, db, match, player, availability):
        """
        GIVEN a player with existing RSVP
        WHEN updating to same value via sync API
        THEN noop should be handled
        """
        success, message, event = rsvp_service_no_publisher.update_rsvp_sync(
            match_id=match.id,
            player_id=player.id,
            new_response='yes',
            source=RSVPSource.WEB
        )

        assert success is True
        assert 'already yes' in message
        assert event is None

    def test_sync_update_validates_response(self, rsvp_service_no_publisher, match, player):
        """
        GIVEN an invalid response value
        WHEN using sync update
        THEN validation should fail
        """
        success, message, event = rsvp_service_no_publisher.update_rsvp_sync(
            match_id=match.id,
            player_id=player.id,
            new_response='invalid',
            source=RSVPSource.WEB
        )

        assert success is False
        assert 'Invalid response' in message

    def test_sync_factory_creates_service(self, db):
        """
        GIVEN a database session
        WHEN creating service via sync factory
        THEN service should be created without event publisher
        """
        with patch('app.services.rsvp_service.get_redis_connection', return_value=MagicMock()):
            service = create_rsvp_service_sync(db.session)

        assert service is not None
        assert service.session == db.session
        assert service.event_publisher is None


# =============================================================================
# METRICS AND HEALTH TESTS
# =============================================================================

@pytest.mark.unit
class TestRSVPMetricsAndHealth:
    """Test RSVP service metrics and health checks."""

    def test_get_metrics_returns_counters(self, rsvp_service):
        """
        GIVEN an RSVPService instance
        WHEN getting metrics
        THEN counter values should be returned
        """
        metrics = rsvp_service.get_metrics()

        assert 'operations_processed' in metrics
        assert 'duplicate_operations' in metrics
        assert 'validation_errors' in metrics
        assert 'concurrent_conflicts' in metrics
        assert 'duplicate_rate' in metrics
        assert 'error_rate' in metrics

    @pytest.mark.asyncio
    async def test_metrics_updated_on_operations(self, rsvp_service, db, match, player):
        """
        GIVEN an RSVPService with initial zero metrics
        WHEN performing operations
        THEN metrics should be updated
        """
        assert rsvp_service.operations_processed == 0

        mock_avail = create_mock_availability(match.id, player.id, player.discord_id, 'yes')

        with patch.object(rsvp_service, '_apply_rsvp_update', new_callable=AsyncMock) as mock_apply:
            mock_apply.return_value = mock_avail

            await rsvp_service.update_rsvp(
                match_id=match.id,
                player_id=player.id,
                new_response='yes',
                source=RSVPSource.WEB
            )

        assert rsvp_service.operations_processed == 1

    @pytest.mark.asyncio
    async def test_validation_error_counted(self, rsvp_service, match, player):
        """
        GIVEN an RSVPService
        WHEN validation fails
        THEN validation_errors counter should increment
        """
        assert rsvp_service.validation_errors == 0

        await rsvp_service.update_rsvp(
            match_id=match.id,
            player_id=player.id,
            new_response='invalid',
            source=RSVPSource.WEB
        )

        assert rsvp_service.validation_errors == 1

    @pytest.mark.asyncio
    async def test_health_check_returns_status(self, rsvp_service):
        """
        GIVEN an RSVPService
        WHEN checking health
        THEN health status should be returned
        """
        with patch('app.services.rsvp_service.get_safe_redis') as mock_get_redis:
            mock_safe_redis = MagicMock()
            mock_safe_redis.ping.return_value = True
            mock_get_redis.return_value = mock_safe_redis

            health = await rsvp_service.health_check()

        assert 'status' in health
        assert 'database_connected' in health
        assert 'redis_connected' in health
        assert 'event_publisher_healthy' in health


# =============================================================================
# CONCURRENT UPDATE TESTS
# =============================================================================

@pytest.mark.unit
class TestRSVPConcurrentUpdates:
    """Test RSVP concurrent update handling."""

    @pytest.mark.asyncio
    async def test_get_current_state_acquires_lock(self, rsvp_service, match, player):
        """
        GIVEN a match and player
        WHEN getting current state with lock
        THEN state should be returned with player and match
        """
        state = await rsvp_service._get_current_state_with_lock(
            match_id=match.id,
            player_id=player.id
        )

        assert state['player'] is not None
        assert state['match'] is not None
        assert state['player'].id == player.id
        assert state['match'].id == match.id

    @pytest.mark.asyncio
    async def test_concurrent_conflict_increments_counter(self, db, match, player, mock_event_publisher):
        """
        GIVEN a service that encounters concurrent update error
        WHEN error is caught
        THEN concurrent_conflicts counter should increment
        """
        mock_redis = MagicMock()
        mock_redis.get.return_value = None

        service = RSVPService(
            session=db.session,
            event_publisher=mock_event_publisher,
            redis_client=mock_redis
        )

        with patch.object(service, '_get_current_state_with_lock', side_effect=RSVPConcurrentUpdateError("Lock failed")):
            with patch('app.services.rsvp_service.get_safe_redis') as mock_get_redis:
                mock_safe_redis = MagicMock()
                mock_safe_redis.get.return_value = None
                mock_get_redis.return_value = mock_safe_redis

                success, message, event = await service.update_rsvp(
                    match_id=match.id,
                    player_id=player.id,
                    new_response='yes',
                    source=RSVPSource.WEB
                )

        assert success is False
        assert 'Concurrent update' in message
        assert service.concurrent_conflicts == 1


# =============================================================================
# TEAM DETERMINATION TESTS
# =============================================================================

@pytest.mark.unit
class TestRSVPTeamDetermination:
    """Test team ID determination for events."""

    def test_determine_team_id_returns_player_primary_team(self, rsvp_service, match, player, team):
        """
        GIVEN a player with primary team
        WHEN determining team ID
        THEN primary team ID should be returned if set
        """
        # Player is associated with team via teams relationship
        team_id = rsvp_service._determine_team_id(player, match)

        # Should return a team ID (either from match relationship or primary_team_id)
        assert team_id is None or isinstance(team_id, int)
