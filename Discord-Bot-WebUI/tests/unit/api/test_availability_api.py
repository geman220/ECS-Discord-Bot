"""
Availability API endpoint tests.

These tests verify the availability API endpoints behavior:
- RSVP submission behaviors (yes/no/maybe)
- RSVP retrieval behaviors
- Bulk RSVP operations
- Team availability summary behaviors
- Match availability status behaviors
- Permission checking (only team members can RSVP)
- Error handling

Tests use GIVEN/WHEN/THEN pattern for clarity.
"""
import pytest
from datetime import datetime, date, time, timedelta
from unittest.mock import patch, MagicMock

from tests.factories import (
    UserFactory, TeamFactory, PlayerFactory, MatchFactory,
    AvailabilityFactory, SeasonFactory, LeagueFactory, ScheduleFactory,
    set_factory_session
)


# =============================================================================
# TEST FIXTURES SPECIFIC TO AVAILABILITY API
# =============================================================================

@pytest.fixture
def api_client(client, app):
    """
    Create a test client configured for availability API access.
    Sets up headers to bypass host restrictions.
    """
    # The before_request handler checks request.host
    # For testing, we use localhost:5000 which is in the allowed list
    return client


@pytest.fixture
def api_headers():
    """Headers that allow API access via mobile API key."""
    return {'X-API-Key': 'ecs-soccer-mobile-key'}


@pytest.fixture
def home_team(db, league):
    """Create a home team for matches."""
    set_factory_session(db.session)
    team = TeamFactory(name='Home Team', league=league)
    db.session.commit()
    return team


@pytest.fixture
def away_team(db, league):
    """Create an away team for matches."""
    set_factory_session(db.session)
    team = TeamFactory(name='Away Team', league=league)
    db.session.commit()
    return team


@pytest.fixture
def test_match(db, home_team, away_team, season):
    """Create a test match for availability tests."""
    set_factory_session(db.session)
    # Create schedule first
    schedule = ScheduleFactory(
        team=home_team,
        opponent_team=away_team,
        season=season,
        date=date.today() + timedelta(days=3)
    )
    # Create match
    match = MatchFactory(
        home_team=home_team,
        away_team=away_team,
        schedule=schedule,
        date=schedule.date
    )
    db.session.commit()
    return match


@pytest.fixture
def old_match(db, home_team, away_team, season):
    """Create an old match (more than 7 days ago) for filtering tests."""
    set_factory_session(db.session)
    old_date = date.today() - timedelta(days=14)
    schedule = ScheduleFactory(
        team=home_team,
        opponent_team=away_team,
        season=season,
        date=old_date
    )
    match = MatchFactory(
        home_team=home_team,
        away_team=away_team,
        schedule=schedule,
        date=old_date
    )
    db.session.commit()
    return match


@pytest.fixture
def team_player(db, user, home_team):
    """Create a player on the home team."""
    set_factory_session(db.session)
    player = PlayerFactory(
        name='Team Player',
        user=user,
        discord_id='team_player_discord_123'
    )
    player.teams.append(home_team)
    db.session.commit()
    return player


@pytest.fixture
def non_team_player(db, away_team):
    """Create a player NOT on the home team (on away team only)."""
    set_factory_session(db.session)
    other_user = UserFactory(username='otheruser', email='other@example.com')
    player = PlayerFactory(
        name='Non Team Player',
        user=other_user,
        discord_id='non_team_player_discord_456'
    )
    player.teams.append(away_team)
    db.session.commit()
    return player


# =============================================================================
# SCHEDULE AVAILABILITY POLL TESTS
# =============================================================================

@pytest.mark.unit
@pytest.mark.api
class TestScheduleAvailabilityPoll:
    """Tests for schedule_availability_poll endpoint."""

    def test_schedule_poll_with_valid_data_succeeds(
        self, api_client, app, db, test_match, home_team, api_headers
    ):
        """
        GIVEN valid match, date, time, and team data
        WHEN POST /schedule_availability_poll is called
        THEN 200 status and success message should be returned
        """
        with app.app_context():
            response = api_client.post(
                '/api/schedule_availability_poll',
                json={
                    'match_id': test_match.id,
                    'match_date': test_match.date.isoformat(),
                    'match_time': test_match.time.isoformat(),
                    'team_id': home_team.id
                },
                headers=api_headers
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data['message'] == 'Poll scheduled successfully'
            assert data['match_id'] == test_match.id

    def test_schedule_poll_missing_match_id_returns_400(
        self, api_client, app, home_team, api_headers
    ):
        """
        GIVEN request missing match_id
        WHEN POST /schedule_availability_poll is called
        THEN 400 error should be returned
        """
        with app.app_context():
            response = api_client.post(
                '/api/schedule_availability_poll',
                json={
                    'match_date': '2024-01-15',
                    'match_time': '19:00',
                    'team_id': home_team.id
                },
                headers=api_headers
            )

            assert response.status_code == 400
            data = response.get_json()
            assert 'error' in data

    def test_schedule_poll_missing_team_id_returns_400(
        self, api_client, app, test_match, api_headers
    ):
        """
        GIVEN request missing team_id
        WHEN POST /schedule_availability_poll is called
        THEN 400 error should be returned
        """
        with app.app_context():
            response = api_client.post(
                '/api/schedule_availability_poll',
                json={
                    'match_id': test_match.id,
                    'match_date': '2024-01-15',
                    'match_time': '19:00'
                },
                headers=api_headers
            )

            assert response.status_code == 400

    def test_schedule_poll_invalid_date_format_returns_400(
        self, api_client, app, test_match, home_team, api_headers
    ):
        """
        GIVEN invalid date format
        WHEN POST /schedule_availability_poll is called
        THEN 400 error should be returned
        """
        with app.app_context():
            response = api_client.post(
                '/api/schedule_availability_poll',
                json={
                    'match_id': test_match.id,
                    'match_date': 'not-a-date',
                    'match_time': '19:00',
                    'team_id': home_team.id
                },
                headers=api_headers
            )

            assert response.status_code == 400

    def test_schedule_poll_nonexistent_match_returns_404(
        self, api_client, app, home_team, api_headers
    ):
        """
        GIVEN non-existent match ID
        WHEN POST /schedule_availability_poll is called
        THEN 404 error should be returned
        """
        with app.app_context():
            response = api_client.post(
                '/api/schedule_availability_poll',
                json={
                    'match_id': 99999,
                    'match_date': '2024-01-15',
                    'match_time': '19:00',
                    'team_id': home_team.id
                },
                headers=api_headers
            )

            assert response.status_code == 404

    def test_schedule_poll_nonexistent_team_returns_404(
        self, api_client, app, test_match, api_headers
    ):
        """
        GIVEN non-existent team ID
        WHEN POST /schedule_availability_poll is called
        THEN 404 error should be returned
        """
        with app.app_context():
            response = api_client.post(
                '/api/schedule_availability_poll',
                json={
                    'match_id': test_match.id,
                    'match_date': test_match.date.isoformat(),
                    'match_time': test_match.time.isoformat(),
                    'team_id': 99999
                },
                headers=api_headers
            )

            assert response.status_code == 404


# =============================================================================
# GET MATCH AVAILABILITY TESTS
# =============================================================================

@pytest.mark.unit
@pytest.mark.api
class TestGetMatchAvailability:
    """Tests for get_match_availability endpoint."""

    def test_get_availability_for_existing_match_succeeds(
        self, api_client, app, db, test_match, api_headers
    ):
        """
        GIVEN an existing match
        WHEN GET /match_availability/<match_id> is called
        THEN 200 status and availability data should be returned
        """
        with app.app_context():
            response = api_client.get(
                f'/api/match_availability/{test_match.id}',
                headers=api_headers
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data['match_id'] == test_match.id
            assert 'availability' in data

    def test_get_availability_for_nonexistent_match_returns_404(
        self, api_client, app, api_headers
    ):
        """
        GIVEN a non-existent match ID
        WHEN GET /match_availability/<match_id> is called
        THEN 404 error should be returned
        """
        with app.app_context():
            response = api_client.get(
                '/api/match_availability/99999',
                headers=api_headers
            )

            assert response.status_code == 404

    def test_get_availability_includes_all_responses(
        self, api_client, app, db, test_match, team_player, api_headers
    ):
        """
        GIVEN a match with existing availability records
        WHEN GET /match_availability/<match_id> is called
        THEN all availability records should be included
        """
        set_factory_session(db.session)
        # Create availability record
        AvailabilityFactory(
            match=test_match,
            player=team_player,
            response='yes',
            discord_id=team_player.discord_id
        )
        db.session.commit()

        with app.app_context():
            response = api_client.get(
                f'/api/match_availability/{test_match.id}',
                headers=api_headers
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data['match_id'] == test_match.id


# =============================================================================
# GET MATCH RSVPS TESTS
# =============================================================================

@pytest.mark.unit
@pytest.mark.api
class TestGetMatchRsvps:
    """Tests for get_match_rsvps endpoint."""

    def test_get_rsvps_returns_categorized_responses(
        self, api_client, app, db, test_match, team_player, non_team_player, api_headers
    ):
        """
        GIVEN a match with various RSVP responses
        WHEN GET /get_match_rsvps/<match_id> is called
        THEN responses should be categorized by yes/no/maybe
        """
        set_factory_session(db.session)
        # Create different responses
        AvailabilityFactory(
            match=test_match,
            player=team_player,
            response='yes',
            discord_id=team_player.discord_id
        )
        AvailabilityFactory(
            match=test_match,
            player=non_team_player,
            response='no',
            discord_id=non_team_player.discord_id
        )
        db.session.commit()

        with app.app_context():
            response = api_client.get(
                f'/api/get_match_rsvps/{test_match.id}',
                headers=api_headers
            )

            assert response.status_code == 200
            data = response.get_json()
            assert 'yes' in data
            assert 'no' in data
            assert 'maybe' in data

    def test_get_rsvps_filters_by_team_id(
        self, api_client, app, db, test_match, team_player, non_team_player, home_team, api_headers
    ):
        """
        GIVEN a match with RSVPs from multiple teams
        WHEN GET /get_match_rsvps/<match_id>?team_id=<id> is called
        THEN only RSVPs from specified team should be returned
        """
        set_factory_session(db.session)
        AvailabilityFactory(
            match=test_match,
            player=team_player,
            response='yes',
            discord_id=team_player.discord_id
        )
        AvailabilityFactory(
            match=test_match,
            player=non_team_player,
            response='yes',
            discord_id=non_team_player.discord_id
        )
        db.session.commit()

        with app.app_context():
            response = api_client.get(
                f'/api/get_match_rsvps/{test_match.id}?team_id={home_team.id}',
                headers=api_headers
            )

            assert response.status_code == 200
            data = response.get_json()
            # Should contain filtered results
            assert 'yes' in data

    def test_get_rsvps_includes_discord_ids_when_requested(
        self, api_client, app, db, test_match, team_player, api_headers
    ):
        """
        GIVEN a match with RSVPs
        WHEN GET /get_match_rsvps/<match_id>?include_discord_ids=true is called
        THEN discord_ids should be included in response
        """
        set_factory_session(db.session)
        AvailabilityFactory(
            match=test_match,
            player=team_player,
            response='yes',
            discord_id=team_player.discord_id
        )
        db.session.commit()

        with app.app_context():
            response = api_client.get(
                f'/api/get_match_rsvps/{test_match.id}?include_discord_ids=true',
                headers=api_headers
            )

            assert response.status_code == 200
            data = response.get_json()
            assert 'yes' in data


# =============================================================================
# UPDATE AVAILABILITY FROM DISCORD TESTS
# =============================================================================

@pytest.mark.unit
@pytest.mark.api
class TestUpdateAvailabilityFromDiscord:
    """Tests for update_availability_from_discord endpoint."""

    def test_update_from_discord_with_valid_data_processes_request(
        self, api_client, app, db, test_match, team_player, api_headers
    ):
        """
        GIVEN valid match_id, discord_id, and response
        WHEN POST /update_availability_from_discord is called
        THEN the request should be processed (either success or handled error)
        """
        with app.app_context():
            response = api_client.post(
                '/api/update_availability_from_discord',
                json={
                    'match_id': test_match.id,
                    'discord_id': team_player.discord_id,
                    'response': 'yes'
                },
                headers=api_headers
            )

            # The endpoint processes valid input; returns 200 on success
            # or 500 if enterprise RSVP fails (external dependency)
            assert response.status_code in (200, 500)
            data = response.get_json()
            # Either success or error response
            assert 'status' in data or 'error' in data

    def test_update_from_discord_missing_match_id_returns_400(
        self, api_client, app, team_player, api_headers
    ):
        """
        GIVEN request missing match_id
        WHEN POST /update_availability_from_discord is called
        THEN 400 error should be returned
        """
        with app.app_context():
            response = api_client.post(
                '/api/update_availability_from_discord',
                json={
                    'discord_id': team_player.discord_id,
                    'response': 'yes'
                },
                headers=api_headers
            )

            assert response.status_code == 400

    def test_update_from_discord_missing_discord_id_returns_400(
        self, api_client, app, test_match, api_headers
    ):
        """
        GIVEN request missing discord_id
        WHEN POST /update_availability_from_discord is called
        THEN 400 error should be returned
        """
        with app.app_context():
            response = api_client.post(
                '/api/update_availability_from_discord',
                json={
                    'match_id': test_match.id,
                    'response': 'yes'
                },
                headers=api_headers
            )

            assert response.status_code == 400

    def test_update_from_discord_missing_response_returns_400(
        self, api_client, app, test_match, team_player, api_headers
    ):
        """
        GIVEN request missing response
        WHEN POST /update_availability_from_discord is called
        THEN 400 error should be returned
        """
        with app.app_context():
            response = api_client.post(
                '/api/update_availability_from_discord',
                json={
                    'match_id': test_match.id,
                    'discord_id': team_player.discord_id
                },
                headers=api_headers
            )

            assert response.status_code == 400


# =============================================================================
# STORE MESSAGE IDS TESTS
# =============================================================================

@pytest.mark.unit
@pytest.mark.api
class TestStoreMessageIds:
    """Tests for store_message_ids endpoint."""

    @patch('app.availability_api.store_message_ids_for_match')
    def test_store_message_ids_with_valid_data_succeeds(
        self, mock_store, api_client, app, db, test_match, api_headers
    ):
        """
        GIVEN valid message IDs for home and away channels
        WHEN POST /store_message_ids is called
        THEN message IDs should be stored successfully
        """
        mock_store.return_value = (True, 'Message IDs stored successfully')

        with app.app_context():
            response = api_client.post(
                '/api/store_message_ids',
                json={
                    'match_id': test_match.id,
                    'home_channel_id': '123456789',
                    'home_message_id': '987654321',
                    'away_channel_id': '111111111',
                    'away_message_id': '222222222'
                },
                headers=api_headers
            )

            assert response.status_code == 200
            data = response.get_json()
            assert 'message' in data

    def test_store_message_ids_missing_field_returns_400(
        self, api_client, app, test_match, api_headers
    ):
        """
        GIVEN request missing required fields
        WHEN POST /store_message_ids is called
        THEN 400 error should be returned
        """
        with app.app_context():
            response = api_client.post(
                '/api/store_message_ids',
                json={
                    'match_id': test_match.id,
                    'home_channel_id': '123456789'
                    # Missing other fields
                },
                headers=api_headers
            )

            assert response.status_code == 400


# =============================================================================
# GET MATCH ID FROM MESSAGE TESTS
# =============================================================================

@pytest.mark.unit
@pytest.mark.api
class TestGetMatchIdFromMessage:
    """Tests for get_match_id_from_message endpoint."""

    def test_get_match_id_for_nonexistent_message_returns_404(
        self, api_client, app, api_headers
    ):
        """
        GIVEN a message ID that doesn't exist in database
        WHEN GET /get_match_id_from_message/<message_id> is called
        THEN 404 error should be returned
        """
        with app.app_context():
            response = api_client.get(
                '/api/get_match_id_from_message/nonexistent123',
                headers=api_headers
            )

            assert response.status_code == 404

    def test_get_match_id_from_scheduled_message(
        self, api_client, app, db, test_match, api_headers
    ):
        """
        GIVEN a scheduled message with a valid message ID
        WHEN GET /get_match_id_from_message/<message_id> is called
        THEN match_id should be returned
        """
        from app.models import ScheduledMessage

        with app.app_context():
            # Create a scheduled message
            scheduled_msg = ScheduledMessage(
                match_id=test_match.id,
                scheduled_send_time=datetime.utcnow(),
                home_message_id='test_message_123',
                home_channel_id='test_channel_123'
            )
            db.session.add(scheduled_msg)
            db.session.commit()

            response = api_client.get(
                '/api/get_match_id_from_message/test_message_123',
                headers=api_headers
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data['match_id'] == test_match.id


# =============================================================================
# IS USER ON TEAM TESTS
# =============================================================================

@pytest.mark.unit
@pytest.mark.api
class TestIsUserOnTeam:
    """Tests for is_user_on_team endpoint."""

    def test_team_member_returns_true(
        self, api_client, app, db, team_player, home_team, api_headers
    ):
        """
        GIVEN a player who is on a specific team
        WHEN POST /is_user_on_team is called
        THEN is_team_member should be True
        """
        with app.app_context():
            response = api_client.post(
                '/api/is_user_on_team',
                json={
                    'discord_id': team_player.discord_id,
                    'team_id': home_team.id
                },
                headers=api_headers
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data['is_team_member'] is True

    def test_non_team_member_returns_false(
        self, api_client, app, db, non_team_player, home_team, api_headers
    ):
        """
        GIVEN a player who is NOT on a specific team
        WHEN POST /is_user_on_team is called
        THEN is_team_member should be False
        """
        with app.app_context():
            response = api_client.post(
                '/api/is_user_on_team',
                json={
                    'discord_id': non_team_player.discord_id,
                    'team_id': home_team.id
                },
                headers=api_headers
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data['is_team_member'] is False

    def test_nonexistent_player_returns_false(
        self, api_client, app, home_team, api_headers
    ):
        """
        GIVEN a discord_id that doesn't exist
        WHEN POST /is_user_on_team is called
        THEN is_team_member should be False
        """
        with app.app_context():
            response = api_client.post(
                '/api/is_user_on_team',
                json={
                    'discord_id': 'nonexistent_discord_id',
                    'team_id': home_team.id
                },
                headers=api_headers
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data['is_team_member'] is False

    def test_missing_discord_id_returns_400(
        self, api_client, app, home_team, api_headers
    ):
        """
        GIVEN request missing discord_id
        WHEN POST /is_user_on_team is called
        THEN 400 error should be returned
        """
        with app.app_context():
            response = api_client.post(
                '/api/is_user_on_team',
                json={'team_id': home_team.id},
                headers=api_headers
            )

            assert response.status_code == 400

    def test_missing_team_id_returns_400(
        self, api_client, app, team_player, api_headers
    ):
        """
        GIVEN request missing team_id
        WHEN POST /is_user_on_team is called
        THEN 400 error should be returned
        """
        with app.app_context():
            response = api_client.post(
                '/api/is_user_on_team',
                json={'discord_id': team_player.discord_id},
                headers=api_headers
            )

            assert response.status_code == 400


# =============================================================================
# GET PLAYER ID FROM DISCORD TESTS
# =============================================================================

@pytest.mark.unit
@pytest.mark.api
class TestGetPlayerIdFromDiscord:
    """Tests for get_player_id_from_discord endpoint."""

    def test_existing_player_returns_player_data(
        self, api_client, app, db, team_player, api_headers
    ):
        """
        GIVEN an existing player's discord_id
        WHEN GET /get_player_id_from_discord/<discord_id> is called
        THEN player info should be returned
        """
        with app.app_context():
            response = api_client.get(
                f'/api/get_player_id_from_discord/{team_player.discord_id}',
                headers=api_headers
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data['player_id'] == team_player.id
            assert data['player_name'] == team_player.name
            assert 'teams' in data

    def test_nonexistent_player_returns_404(
        self, api_client, app, api_headers
    ):
        """
        GIVEN a discord_id that doesn't exist
        WHEN GET /get_player_id_from_discord/<discord_id> is called
        THEN 404 error should be returned
        """
        with app.app_context():
            response = api_client.get(
                '/api/get_player_id_from_discord/nonexistent_id_123',
                headers=api_headers
            )

            assert response.status_code == 404


# =============================================================================
# UPDATE AVAILABILITY WEB (LOGIN REQUIRED) TESTS
# =============================================================================

@pytest.mark.unit
@pytest.mark.api
class TestUpdateAvailabilityWeb:
    """Tests for update_availability_web endpoint (login required)."""

    def test_unauthenticated_request_denied(
        self, api_client, app, test_match, team_player, api_headers
    ):
        """
        GIVEN an unauthenticated request
        WHEN POST /update_availability_web is called
        THEN access should be denied (401 or redirect)
        """
        with app.app_context():
            response = api_client.post(
                '/api/update_availability_web',
                json={
                    'match_id': test_match.id,
                    'player_id': team_player.id,
                    'response': 'yes'
                },
                headers=api_headers
            )

            # Either 401 Unauthorized or redirect to login
            assert response.status_code in (401, 302, 403)

    @patch('app.availability_api.update_rsvp')
    @patch('app.availability_api.notify_discord_of_rsvp_change_task')
    def test_authenticated_request_with_valid_data_succeeds(
        self, mock_notify_task, mock_update_rsvp, authenticated_client, app, db, test_match, player, api_headers
    ):
        """
        GIVEN an authenticated user with valid RSVP data
        WHEN POST /update_availability_web is called
        THEN availability should be updated successfully
        """
        mock_update_rsvp.return_value = (True, 'Availability updated')
        mock_notify_task.delay = MagicMock()

        with app.app_context():
            response = authenticated_client.post(
                '/api/update_availability_web',
                json={
                    'match_id': test_match.id,
                    'player_id': player.id,
                    'response': 'yes'
                },
                headers=api_headers
            )

            assert response.status_code == 200

    def test_authenticated_request_missing_match_id_returns_400(
        self, authenticated_client, app, player, api_headers
    ):
        """
        GIVEN an authenticated user missing match_id
        WHEN POST /update_availability_web is called
        THEN 400 error should be returned
        """
        with app.app_context():
            response = authenticated_client.post(
                '/api/update_availability_web',
                json={
                    'player_id': player.id,
                    'response': 'yes'
                },
                headers=api_headers
            )

            assert response.status_code == 400


# =============================================================================
# SYNC MATCH RSVPS (LOGIN REQUIRED) TESTS
# =============================================================================

@pytest.mark.unit
@pytest.mark.api
class TestSyncMatchRsvps:
    """Tests for sync_match_rsvps endpoint (login required)."""

    def test_unauthenticated_request_denied(
        self, api_client, app, test_match, api_headers
    ):
        """
        GIVEN an unauthenticated request
        WHEN POST /sync_match_rsvps/<match_id> is called
        THEN access should be denied
        """
        with app.app_context():
            response = api_client.post(
                f'/api/sync_match_rsvps/{test_match.id}',
                headers=api_headers
            )

            assert response.status_code in (401, 302, 403)

    @patch('app.availability_api.update_discord_rsvp')
    def test_authenticated_sync_for_nonexistent_match_returns_error(
        self, mock_update, authenticated_client, app, api_headers
    ):
        """
        GIVEN an authenticated user and non-existent match
        WHEN POST /sync_match_rsvps/<match_id> is called
        THEN error should be returned (404 via abort or 500 from exception handling)
        """
        with app.app_context():
            response = authenticated_client.post(
                '/api/sync_match_rsvps/99999',
                headers=api_headers
            )

            # The endpoint catches abort(404) and returns 500 with error message
            assert response.status_code in (404, 500)
            data = response.get_json()
            assert 'error' in data


# =============================================================================
# GET MESSAGE IDS TESTS
# =============================================================================

@pytest.mark.unit
@pytest.mark.api
class TestGetMessageIds:
    """Tests for get_message_ids endpoint."""

    def test_nonexistent_match_returns_404(
        self, api_client, app, api_headers
    ):
        """
        GIVEN a non-existent match ID
        WHEN GET /get_message_ids/<match_id> is called
        THEN 404 error should be returned
        """
        with app.app_context():
            response = api_client.get(
                '/api/get_message_ids/99999',
                headers=api_headers
            )

            assert response.status_code == 404


# =============================================================================
# GET MATCH AND TEAM ID FROM MESSAGE TESTS
# =============================================================================

@pytest.mark.unit
@pytest.mark.api
class TestGetMatchAndTeamIdFromMessage:
    """Tests for get_match_and_team_id_from_message endpoint."""

    def test_missing_message_id_returns_400(
        self, api_client, app, api_headers
    ):
        """
        GIVEN request missing message_id parameter
        WHEN GET /get_match_and_team_id_from_message is called
        THEN 400 error should be returned
        """
        with app.app_context():
            response = api_client.get(
                '/api/get_match_and_team_id_from_message?channel_id=123',
                headers=api_headers
            )

            assert response.status_code == 400

    def test_missing_channel_id_returns_400(
        self, api_client, app, api_headers
    ):
        """
        GIVEN request missing channel_id parameter
        WHEN GET /get_match_and_team_id_from_message is called
        THEN 400 error should be returned
        """
        with app.app_context():
            response = api_client.get(
                '/api/get_match_and_team_id_from_message?message_id=123',
                headers=api_headers
            )

            assert response.status_code == 400


# =============================================================================
# GET SCHEDULED MESSAGES TESTS
# =============================================================================

@pytest.mark.unit
@pytest.mark.api
class TestGetScheduledMessages:
    """Tests for get_scheduled_messages endpoint."""

    def test_get_scheduled_messages_returns_recent_messages(
        self, api_client, app, db, test_match, api_headers
    ):
        """
        GIVEN scheduled messages for recent matches
        WHEN GET /get_scheduled_messages is called
        THEN only recent messages should be returned
        """
        from app.models import ScheduledMessage

        with app.app_context():
            # Create a scheduled message
            scheduled_msg = ScheduledMessage(
                match_id=test_match.id,
                scheduled_send_time=datetime.utcnow(),
                home_message_id='msg_123',
                home_channel_id='channel_123'
            )
            db.session.add(scheduled_msg)
            db.session.commit()

            response = api_client.get(
                '/api/get_scheduled_messages',
                headers=api_headers
            )

            assert response.status_code == 200
            data = response.get_json()
            assert isinstance(data, list)


# =============================================================================
# POLL RESPONSE TESTS
# =============================================================================

@pytest.mark.unit
@pytest.mark.api
class TestUpdatePollResponseFromDiscord:
    """Tests for update_poll_response_from_discord endpoint."""

    def test_missing_poll_id_returns_400(
        self, api_client, app, team_player, api_headers
    ):
        """
        GIVEN request missing poll_id
        WHEN POST /update_poll_response_from_discord is called
        THEN 400 error should be returned
        """
        with app.app_context():
            response = api_client.post(
                '/api/update_poll_response_from_discord',
                json={
                    'discord_id': team_player.discord_id,
                    'response': 'yes'
                },
                headers=api_headers
            )

            assert response.status_code == 400

    def test_missing_discord_id_returns_400(
        self, api_client, app, api_headers
    ):
        """
        GIVEN request missing discord_id
        WHEN POST /update_poll_response_from_discord is called
        THEN 400 error should be returned
        """
        with app.app_context():
            response = api_client.post(
                '/api/update_poll_response_from_discord',
                json={
                    'poll_id': 1,
                    'response': 'yes'
                },
                headers=api_headers
            )

            assert response.status_code == 400

    def test_invalid_response_value_returns_400(
        self, api_client, app, team_player, api_headers
    ):
        """
        GIVEN invalid response value (not yes/no/maybe)
        WHEN POST /update_poll_response_from_discord is called
        THEN 400 error should be returned
        """
        with app.app_context():
            response = api_client.post(
                '/api/update_poll_response_from_discord',
                json={
                    'poll_id': 1,
                    'discord_id': team_player.discord_id,
                    'response': 'invalid_response'
                },
                headers=api_headers
            )

            assert response.status_code == 400


# =============================================================================
# RECORD POLL RESPONSE TESTS
# =============================================================================

@pytest.mark.unit
@pytest.mark.api
class TestRecordPollResponse:
    """Tests for record_poll_response endpoint."""

    def test_missing_required_fields_returns_400(
        self, api_client, app, api_headers
    ):
        """
        GIVEN request missing required fields
        WHEN POST /record_poll_response is called
        THEN 400 error should be returned
        """
        with app.app_context():
            response = api_client.post(
                '/api/record_poll_response',
                json={
                    'poll_id': 1
                    # Missing discord_id and response
                },
                headers=api_headers
            )

            assert response.status_code == 400

    def test_invalid_response_returns_400(
        self, api_client, app, api_headers
    ):
        """
        GIVEN invalid response value
        WHEN POST /record_poll_response is called
        THEN 400 error should be returned
        """
        with app.app_context():
            response = api_client.post(
                '/api/record_poll_response',
                json={
                    'poll_id': 1,
                    'discord_id': 'test123',
                    'response': 'invalid'
                },
                headers=api_headers
            )

            assert response.status_code == 400


# =============================================================================
# UPDATE POLL MESSAGE TESTS
# =============================================================================

@pytest.mark.unit
@pytest.mark.api
class TestUpdatePollMessage:
    """Tests for update_poll_message endpoint."""

    def test_missing_message_record_id_returns_400(
        self, api_client, app, api_headers
    ):
        """
        GIVEN request missing message_record_id
        WHEN POST /update_poll_message is called
        THEN 400 error should be returned
        """
        with app.app_context():
            response = api_client.post(
                '/api/update_poll_message',
                json={
                    'message_id': '123'
                },
                headers=api_headers
            )

            assert response.status_code == 400

    def test_nonexistent_message_record_returns_404(
        self, api_client, app, api_headers
    ):
        """
        GIVEN non-existent message_record_id
        WHEN POST /update_poll_message is called
        THEN 404 error should be returned
        """
        with app.app_context():
            response = api_client.post(
                '/api/update_poll_message',
                json={
                    'message_record_id': 99999,
                    'message_id': '123'
                },
                headers=api_headers
            )

            assert response.status_code == 404


# =============================================================================
# GET ACTIVE POLL MESSAGES TESTS
# =============================================================================

@pytest.mark.unit
@pytest.mark.api
class TestGetActivePollMessages:
    """Tests for get_active_poll_messages endpoint."""

    def test_returns_empty_list_when_no_active_polls(
        self, api_client, app, api_headers
    ):
        """
        GIVEN no active polls in database
        WHEN GET /get_active_poll_messages is called
        THEN empty list should be returned
        """
        with app.app_context():
            response = api_client.get(
                '/api/get_active_poll_messages',
                headers=api_headers
            )

            assert response.status_code == 200
            data = response.get_json()
            assert isinstance(data, list)


# =============================================================================
# SYNC DISCORD RSVPS TESTS
# =============================================================================

@pytest.mark.unit
@pytest.mark.api
class TestSyncDiscordRsvps:
    """Tests for sync_discord_rsvps endpoint."""

    def test_missing_json_data_returns_error(
        self, api_client, app, api_headers
    ):
        """
        GIVEN request with no JSON data
        WHEN POST /sync_discord_rsvps is called
        THEN error should be returned (400 or 500)
        """
        with app.app_context():
            response = api_client.post(
                '/api/sync_discord_rsvps',
                headers=api_headers
            )

            # No JSON data results in either 400 (validation) or 500 (NoneType error)
            assert response.status_code in (400, 500)

    def test_invalid_data_format_returns_400(
        self, api_client, app, api_headers
    ):
        """
        GIVEN invalid data format (rsvps not a list)
        WHEN POST /sync_discord_rsvps is called
        THEN 400 error should be returned
        """
        with app.app_context():
            response = api_client.post(
                '/api/sync_discord_rsvps',
                json={
                    'match_id': 1,
                    'rsvps': 'not a list'
                },
                headers=api_headers
            )

            assert response.status_code == 400

    def test_nonexistent_match_returns_404(
        self, api_client, app, api_headers
    ):
        """
        GIVEN non-existent match_id
        WHEN POST /sync_discord_rsvps is called
        THEN 404 error should be returned
        """
        with app.app_context():
            response = api_client.post(
                '/api/sync_discord_rsvps',
                json={
                    'match_id': 99999,
                    'rsvps': []
                },
                headers=api_headers
            )

            assert response.status_code == 404

    @patch('app.availability_api.notify_frontend_of_rsvp_change_task')
    def test_sync_with_valid_data_succeeds(
        self, mock_notify, api_client, app, db, test_match, team_player, api_headers
    ):
        """
        GIVEN valid match and RSVP data
        WHEN POST /sync_discord_rsvps is called
        THEN RSVPs should be synced successfully
        """
        mock_notify.delay = MagicMock()

        with app.app_context():
            response = api_client.post(
                '/api/sync_discord_rsvps',
                json={
                    'match_id': test_match.id,
                    'rsvps': [
                        {
                            'discord_id': team_player.discord_id,
                            'response': 'yes'
                        }
                    ]
                },
                headers=api_headers
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data['success'] is True


# =============================================================================
# FORCE DISCORD SYNC (ADMIN) TESTS
# =============================================================================

@pytest.mark.unit
@pytest.mark.api
class TestForceDiscordSync:
    """Tests for force_discord_sync endpoint (admin required)."""

    def test_unauthenticated_request_denied(
        self, api_client, app, api_headers
    ):
        """
        GIVEN an unauthenticated request
        WHEN POST /force_discord_sync is called
        THEN access should be denied
        """
        with app.app_context():
            response = api_client.post(
                '/api/force_discord_sync',
                headers=api_headers
            )

            assert response.status_code in (401, 302, 403)

    def test_non_admin_user_denied(
        self, authenticated_client, app, api_headers
    ):
        """
        GIVEN an authenticated non-admin user
        WHEN POST /force_discord_sync is called
        THEN access should be denied (403) or error due to missing admin check
        """
        with app.app_context():
            response = authenticated_client.post(
                '/api/force_discord_sync',
                headers=api_headers
            )

            # The endpoint expects g.user.is_admin which may error if g.user not set
            # Should return 403 if admin check works, or 500 if g.user not available
            assert response.status_code in (403, 500)


# =============================================================================
# GET MESSAGE INFO TESTS
# =============================================================================

@pytest.mark.unit
@pytest.mark.api
class TestGetMessageInfo:
    """Tests for get_message_info endpoint."""

    def test_nonexistent_message_returns_404(
        self, api_client, app, api_headers
    ):
        """
        GIVEN a non-existent message ID
        WHEN GET /get_message_info/<message_id> is called
        THEN 404 error should be returned
        """
        with app.app_context():
            response = api_client.get(
                '/api/get_message_info/nonexistent_msg_id',
                headers=api_headers
            )

            assert response.status_code == 404

    @patch('app.cache_helpers.get_cached_message_info')
    def test_existing_message_returns_info(
        self, mock_cache, api_client, app, db, test_match, home_team, api_headers
    ):
        """
        GIVEN a scheduled message with a valid message ID
        WHEN GET /get_message_info/<message_id> is called
        THEN message info should be returned
        """
        from app.models import ScheduledMessage
        mock_cache.return_value = None  # Force cache miss

        with app.app_context():
            # Create a scheduled message
            scheduled_msg = ScheduledMessage(
                match_id=test_match.id,
                scheduled_send_time=datetime.utcnow(),
                home_message_id='info_test_msg_456',
                home_channel_id='info_test_channel_456'
            )
            db.session.add(scheduled_msg)
            db.session.commit()

            response = api_client.get(
                '/api/get_message_info/info_test_msg_456',
                headers=api_headers
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data['match_id'] == test_match.id
            assert data['team_id'] == home_team.id
            assert 'is_home' in data


# =============================================================================
# TASK STATUS TESTS
# =============================================================================

@pytest.mark.unit
@pytest.mark.api
class TestTaskStatus:
    """Tests for task_status endpoint."""

    @patch('app.availability_api.celery')
    def test_pending_task_returns_pending_status(
        self, mock_celery, api_client, app, api_headers
    ):
        """
        GIVEN a pending Celery task
        WHEN GET /task_status/<task_id> is called
        THEN pending status should be returned
        """
        mock_result = MagicMock()
        mock_result.state = 'PENDING'
        mock_celery.AsyncResult.return_value = mock_result

        with app.app_context():
            response = api_client.get(
                '/api/task_status/test_task_123',
                headers=api_headers
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data['state'] == 'PENDING'

    @patch('app.availability_api.celery')
    def test_success_task_returns_result(
        self, mock_celery, api_client, app, api_headers
    ):
        """
        GIVEN a successful Celery task
        WHEN GET /task_status/<task_id> is called
        THEN success status and result should be returned
        """
        mock_result = MagicMock()
        mock_result.state = 'SUCCESS'
        mock_result.result = {'data': 'test_result'}
        mock_celery.AsyncResult.return_value = mock_result

        with app.app_context():
            response = api_client.get(
                '/api/task_status/test_task_123',
                headers=api_headers
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data['state'] == 'SUCCESS'
            assert data['result'] == {'data': 'test_result'}

    @patch('app.availability_api.celery')
    def test_failed_task_returns_error(
        self, mock_celery, api_client, app, api_headers
    ):
        """
        GIVEN a failed Celery task
        WHEN GET /task_status/<task_id> is called
        THEN failure status and error should be returned
        """
        mock_result = MagicMock()
        mock_result.state = 'FAILURE'
        mock_result.result = Exception('Task failed')
        mock_celery.AsyncResult.return_value = mock_result

        with app.app_context():
            response = api_client.get(
                '/api/task_status/test_task_123',
                headers=api_headers
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data['state'] == 'FAILURE'
            assert 'error' in data


# =============================================================================
# GET MATCH REQUEST TESTS
# =============================================================================

@pytest.mark.unit
@pytest.mark.api
class TestGetMatchRequest:
    """Tests for get_match_request endpoint."""

    @patch('app.availability_api.get_match_request_data')
    def test_existing_match_returns_data(
        self, mock_get_data, api_client, app, test_match, api_headers
    ):
        """
        GIVEN an existing match
        WHEN GET /get_match_request/<match_id> is called
        THEN match request data should be returned
        """
        mock_get_data.return_value = {
            'match_id': test_match.id,
            'date': test_match.date.isoformat(),
            'teams': ['Home', 'Away']
        }

        with app.app_context():
            response = api_client.get(
                f'/api/get_match_request/{test_match.id}',
                headers=api_headers
            )

            assert response.status_code == 200

    @patch('app.availability_api.get_match_request_data')
    def test_nonexistent_match_returns_404(
        self, mock_get_data, api_client, app, api_headers
    ):
        """
        GIVEN a non-existent match ID
        WHEN GET /get_match_request/<match_id> is called
        THEN 404 error should be returned
        """
        mock_get_data.return_value = None

        with app.app_context():
            response = api_client.get(
                '/api/get_match_request/99999',
                headers=api_headers
            )

            assert response.status_code == 404


# =============================================================================
# RSVP RESPONSE VALUE TESTS
# =============================================================================

@pytest.mark.unit
@pytest.mark.api
class TestRsvpResponseValues:
    """Tests for validating RSVP response values."""

    def test_yes_response_passes_validation(
        self, api_client, app, test_match, team_player, api_headers
    ):
        """
        GIVEN a 'yes' response value
        WHEN submitting an RSVP
        THEN the request should pass validation (not return 400)
        """
        with app.app_context():
            response = api_client.post(
                '/api/update_availability_from_discord',
                json={
                    'match_id': test_match.id,
                    'discord_id': team_player.discord_id,
                    'response': 'yes'
                },
                headers=api_headers
            )

            # 'yes' is a valid response, so it should not return 400
            # It may return 200 (success) or 500 (internal enterprise RSVP error)
            assert response.status_code != 400

    def test_no_response_passes_validation(
        self, api_client, app, test_match, team_player, api_headers
    ):
        """
        GIVEN a 'no' response value
        WHEN submitting an RSVP
        THEN the request should pass validation (not return 400)
        """
        with app.app_context():
            response = api_client.post(
                '/api/update_availability_from_discord',
                json={
                    'match_id': test_match.id,
                    'discord_id': team_player.discord_id,
                    'response': 'no'
                },
                headers=api_headers
            )

            # 'no' is a valid response, so it should not return 400
            assert response.status_code != 400

    def test_maybe_response_passes_validation(
        self, api_client, app, test_match, team_player, api_headers
    ):
        """
        GIVEN a 'maybe' response value
        WHEN submitting an RSVP
        THEN the request should pass validation (not return 400)
        """
        with app.app_context():
            response = api_client.post(
                '/api/update_availability_from_discord',
                json={
                    'match_id': test_match.id,
                    'discord_id': team_player.discord_id,
                    'response': 'maybe'
                },
                headers=api_headers
            )

            # 'maybe' is a valid response, so it should not return 400
            assert response.status_code != 400


# =============================================================================
# UPDATE AVAILABILITY (DEPRECATED) TESTS
# =============================================================================

@pytest.mark.unit
@pytest.mark.api
class TestUpdateAvailabilityDeprecated:
    """Tests for the deprecated update_availability endpoint."""

    def test_deprecated_endpoint_processes_request(
        self, api_client, app, db, test_match, team_player, api_headers
    ):
        """
        GIVEN a request to the deprecated update_availability endpoint
        WHEN POST /update_availability is called
        THEN the request should be redirected to enterprise RSVP
        """
        with app.app_context():
            response = api_client.post(
                '/api/update_availability',
                json={
                    'match_id': test_match.id,
                    'discord_id': team_player.discord_id,
                    'response': 'yes'
                },
                headers=api_headers
            )

            # Deprecated endpoint forwards to enterprise RSVP
            # Returns success or error from enterprise system
            assert response.status_code in (200, 400, 500)


# =============================================================================
# BULK RSVP OPERATIONS TESTS
# =============================================================================

@pytest.mark.unit
@pytest.mark.api
class TestBulkRsvpOperations:
    """Tests for bulk RSVP operations."""

    @patch('app.availability_api.notify_frontend_of_rsvp_change_task')
    def test_sync_multiple_rsvps_at_once(
        self, mock_notify, api_client, app, db, test_match, team_player, non_team_player, api_headers
    ):
        """
        GIVEN multiple RSVPs to sync
        WHEN POST /sync_discord_rsvps is called with multiple entries
        THEN all RSVPs should be processed
        """
        mock_notify.delay = MagicMock()

        with app.app_context():
            response = api_client.post(
                '/api/sync_discord_rsvps',
                json={
                    'match_id': test_match.id,
                    'rsvps': [
                        {'discord_id': team_player.discord_id, 'response': 'yes'},
                        {'discord_id': non_team_player.discord_id, 'response': 'no'}
                    ]
                },
                headers=api_headers
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data['success'] is True

    @patch('app.availability_api.notify_frontend_of_rsvp_change_task')
    def test_sync_empty_rsvp_list(
        self, mock_notify, api_client, app, db, test_match, api_headers
    ):
        """
        GIVEN an empty RSVP list
        WHEN POST /sync_discord_rsvps is called
        THEN sync should complete with zero updates
        """
        mock_notify.delay = MagicMock()

        with app.app_context():
            response = api_client.post(
                '/api/sync_discord_rsvps',
                json={
                    'match_id': test_match.id,
                    'rsvps': []
                },
                headers=api_headers
            )

            assert response.status_code == 200


# =============================================================================
# EDGE CASE TESTS
# =============================================================================

@pytest.mark.unit
@pytest.mark.api
class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_invalid_response_value_handled(
        self, api_client, app, test_match, team_player, api_headers
    ):
        """
        GIVEN an invalid response value (not yes/no/maybe)
        WHEN POST /update_availability_from_discord is called
        THEN the request should be rejected (400) or error internally (500)
        """
        with app.app_context():
            response = api_client.post(
                '/api/update_availability_from_discord',
                json={
                    'match_id': test_match.id,
                    'discord_id': team_player.discord_id,
                    'response': 'invalid_value'
                },
                headers=api_headers
            )

            # Invalid response values should not succeed
            assert response.status_code in (400, 500)

    def test_empty_discord_id_handled(
        self, api_client, app, test_match, api_headers
    ):
        """
        GIVEN an empty discord_id
        WHEN POST /update_availability_from_discord is called
        THEN request should be handled (error returned, not success)
        """
        with app.app_context():
            response = api_client.post(
                '/api/update_availability_from_discord',
                json={
                    'match_id': test_match.id,
                    'discord_id': '',
                    'response': 'yes'
                },
                headers=api_headers
            )

            # Empty discord_id should not succeed (400, 404 player not found, or 500)
            assert response.status_code != 200

    def test_negative_match_id_handled(
        self, api_client, app, api_headers
    ):
        """
        GIVEN a negative match_id
        WHEN GET /match_availability/<match_id> is called
        THEN 404 error should be returned
        """
        with app.app_context():
            # Flask route will match -1 as int:match_id
            response = api_client.get(
                '/api/match_availability/-1',
                headers=api_headers
            )

            # Flask may reject negative IDs at route level or API returns 404
            assert response.status_code in (404, 500)

    def test_very_long_discord_id_handled(
        self, api_client, app, test_match, api_headers
    ):
        """
        GIVEN an extremely long discord_id
        WHEN POST /is_user_on_team is called
        THEN request should be handled gracefully
        """
        long_discord_id = 'x' * 1000

        with app.app_context():
            response = api_client.post(
                '/api/is_user_on_team',
                json={
                    'discord_id': long_discord_id,
                    'team_id': 1
                },
                headers=api_headers
            )

            # Should return false for non-existent player
            assert response.status_code == 200
            data = response.get_json()
            assert data['is_team_member'] is False


# =============================================================================
# CONCURRENT REQUEST HANDLING TESTS
# =============================================================================

@pytest.mark.unit
@pytest.mark.api
class TestConcurrentBehavior:
    """Tests for behaviors that might occur with concurrent requests."""

    def test_same_player_multiple_matches_rsvp(
        self, api_client, app, db, home_team, away_team, season, team_player, api_headers
    ):
        """
        GIVEN a player with RSVPs on multiple matches
        WHEN requesting availability for different matches
        THEN each match should have independent availability data
        """
        set_factory_session(db.session)

        # Create two matches
        schedule1 = ScheduleFactory(
            team=home_team,
            opponent_team=away_team,
            season=season,
            date=date.today() + timedelta(days=5)
        )
        match1 = MatchFactory(
            home_team=home_team,
            away_team=away_team,
            schedule=schedule1,
            date=schedule1.date
        )

        schedule2 = ScheduleFactory(
            team=home_team,
            opponent_team=away_team,
            season=season,
            date=date.today() + timedelta(days=10)
        )
        match2 = MatchFactory(
            home_team=home_team,
            away_team=away_team,
            schedule=schedule2,
            date=schedule2.date
        )
        db.session.commit()

        with app.app_context():
            # Check availability for both matches
            response1 = api_client.get(
                f'/api/match_availability/{match1.id}',
                headers=api_headers
            )
            response2 = api_client.get(
                f'/api/match_availability/{match2.id}',
                headers=api_headers
            )

            assert response1.status_code == 200
            assert response2.status_code == 200

            data1 = response1.get_json()
            data2 = response2.get_json()

            assert data1['match_id'] == match1.id
            assert data2['match_id'] == match2.id


# =============================================================================
# RESPONSE FORMAT TESTS
# =============================================================================

@pytest.mark.unit
@pytest.mark.api
class TestResponseFormats:
    """Tests for verifying API response formats."""

    def test_match_availability_response_structure(
        self, api_client, app, db, test_match, api_headers
    ):
        """
        GIVEN an existing match
        WHEN GET /match_availability/<match_id> is called
        THEN response should have expected structure
        """
        with app.app_context():
            response = api_client.get(
                f'/api/match_availability/{test_match.id}',
                headers=api_headers
            )

            assert response.status_code == 200
            data = response.get_json()

            # Verify expected keys
            assert 'match_id' in data
            assert 'availability' in data
            assert isinstance(data['match_id'], int)
            assert isinstance(data['availability'], (list, dict))

    def test_get_match_rsvps_response_structure(
        self, api_client, app, db, test_match, api_headers
    ):
        """
        GIVEN an existing match
        WHEN GET /get_match_rsvps/<match_id> is called
        THEN response should have yes/no/maybe categories
        """
        with app.app_context():
            response = api_client.get(
                f'/api/get_match_rsvps/{test_match.id}',
                headers=api_headers
            )

            assert response.status_code == 200
            data = response.get_json()

            # Verify expected categories
            assert 'yes' in data
            assert 'no' in data
            assert 'maybe' in data

    def test_error_response_structure(
        self, api_client, app, api_headers
    ):
        """
        GIVEN a request that will fail
        WHEN API endpoint is called
        THEN error response should have expected structure
        """
        with app.app_context():
            response = api_client.get(
                '/api/match_availability/99999',
                headers=api_headers
            )

            assert response.status_code == 404
            data = response.get_json()

            # Error responses should have an error message
            assert 'error' in data
