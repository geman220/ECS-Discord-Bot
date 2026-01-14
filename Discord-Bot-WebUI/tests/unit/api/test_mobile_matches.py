"""
Mobile API matches endpoint tests.

These tests verify the mobile API matches endpoints:
- GET /matches - List matches
- GET /matches/schedule - Get match schedule
- GET /matches/<id> - Get match details
- GET /matches/<id>/events - Get match events
- GET /matches/<id>/availability - Get match availability
"""
import pytest
from unittest.mock import patch, MagicMock
from flask_jwt_extended import create_access_token

from tests.factories import UserFactory, PlayerFactory


@pytest.mark.unit
@pytest.mark.api
class TestGetAllMatches:
    """Test matches list endpoint."""

    def test_get_matches_requires_authentication(self, client, app):
        """
        GIVEN an unauthenticated request
        WHEN requesting matches list
        THEN a 401 or 422 error should be returned
        """
        with app.app_context():
            response = client.get('/api/v1/matches')

            assert response.status_code in (401, 422)

    def test_get_matches_with_valid_jwt(self, client, app, db, player):
        """
        GIVEN an authenticated user
        WHEN requesting matches list
        THEN a valid response should be returned
        """
        with app.app_context():
            access_token = create_access_token(identity=str(player.user_id))
            response = client.get(
                '/api/v1/matches',
                headers={'Authorization': f'Bearer {access_token}'}
            )

            # Should return 200 with list or ETag-related response
            assert response.status_code in (200, 304)
            if response.status_code == 200:
                data = response.get_json()
                assert isinstance(data, list)

    def test_get_matches_accepts_upcoming_parameter(self, client, app, db, player):
        """
        GIVEN an authenticated user
        WHEN requesting upcoming matches
        THEN a valid response should be returned
        """
        with app.app_context():
            access_token = create_access_token(identity=str(player.user_id))
            response = client.get(
                '/api/v1/matches?upcoming=true',
                headers={'Authorization': f'Bearer {access_token}'}
            )

            assert response.status_code in (200, 304)

    def test_get_matches_accepts_completed_parameter(self, client, app, db, player):
        """
        GIVEN an authenticated user
        WHEN requesting completed matches
        THEN a valid response should be returned
        """
        with app.app_context():
            access_token = create_access_token(identity=str(player.user_id))
            response = client.get(
                '/api/v1/matches?completed=true',
                headers={'Authorization': f'Bearer {access_token}'}
            )

            assert response.status_code in (200, 304)

    def test_get_matches_accepts_limit_parameter(self, client, app, db, player):
        """
        GIVEN an authenticated user
        WHEN requesting matches with limit
        THEN a valid response should be returned
        """
        with app.app_context():
            access_token = create_access_token(identity=str(player.user_id))
            response = client.get(
                '/api/v1/matches?limit=5',
                headers={'Authorization': f'Bearer {access_token}'}
            )

            assert response.status_code in (200, 304)

    def test_get_matches_accepts_team_id_parameter(self, client, app, db, player, team):
        """
        GIVEN an authenticated user
        WHEN requesting matches for a specific team
        THEN a valid response should be returned
        """
        with app.app_context():
            access_token = create_access_token(identity=str(player.user_id))
            response = client.get(
                f'/api/v1/matches?team_id={team.id}',
                headers={'Authorization': f'Bearer {access_token}'}
            )

            assert response.status_code in (200, 304)


@pytest.mark.unit
@pytest.mark.api
class TestGetMatchSchedule:
    """Test match schedule endpoint."""

    def test_get_schedule_requires_authentication(self, client, app):
        """
        GIVEN an unauthenticated request
        WHEN requesting match schedule
        THEN a 401 or 422 error should be returned
        """
        with app.app_context():
            response = client.get('/api/v1/matches/schedule')

            assert response.status_code in (401, 422)

    def test_get_schedule_with_valid_jwt(self, client, app, db, player):
        """
        GIVEN an authenticated user
        WHEN requesting match schedule
        THEN a valid response should be returned
        """
        with app.app_context():
            access_token = create_access_token(identity=str(player.user_id))
            response = client.get(
                '/api/v1/matches/schedule',
                headers={'Authorization': f'Bearer {access_token}'}
            )

            # Should return 200 or 304 (ETag)
            assert response.status_code in (200, 304)


@pytest.mark.unit
@pytest.mark.api
class TestGetMatchDetails:
    """Test match details endpoint."""

    def test_get_match_details_requires_authentication(self, client, app):
        """
        GIVEN an unauthenticated request
        WHEN requesting match details
        THEN a 401 or 422 error should be returned
        """
        with app.app_context():
            response = client.get('/api/v1/matches/1')

            assert response.status_code in (401, 422)

    def test_get_match_details_returns_404_for_nonexistent(self, client, app, db, player):
        """
        GIVEN an authenticated user
        WHEN requesting a non-existent match
        THEN a 404 error should be returned
        """
        with app.app_context():
            access_token = create_access_token(identity=str(player.user_id))
            response = client.get(
                '/api/v1/matches/99999',
                headers={'Authorization': f'Bearer {access_token}'}
            )

            assert response.status_code == 404

    def test_get_match_details_with_valid_match(self, client, app, db, player, match):
        """
        GIVEN an authenticated user
        WHEN requesting an existing match
        THEN match details should be returned
        """
        with app.app_context():
            access_token = create_access_token(identity=str(player.user_id))
            response = client.get(
                f'/api/v1/matches/{match.id}',
                headers={'Authorization': f'Bearer {access_token}'}
            )

            # Should return 200 with match data or 304 (ETag)
            assert response.status_code in (200, 304)
            if response.status_code == 200:
                data = response.get_json()
                assert 'id' in data
                assert data['id'] == match.id


@pytest.mark.unit
@pytest.mark.api
class TestGetMatchEvents:
    """Test match events endpoint."""

    def test_get_match_events_requires_authentication(self, client, app):
        """
        GIVEN an unauthenticated request
        WHEN requesting match events
        THEN a 401 or 422 error should be returned
        """
        with app.app_context():
            response = client.get('/api/v1/matches/1/events')

            assert response.status_code in (401, 422)

    def test_get_match_events_returns_404_for_nonexistent(self, client, app, db, player):
        """
        GIVEN an authenticated user
        WHEN requesting events for non-existent match
        THEN a 404 error should be returned
        """
        with app.app_context():
            access_token = create_access_token(identity=str(player.user_id))
            response = client.get(
                '/api/v1/matches/99999/events',
                headers={'Authorization': f'Bearer {access_token}'}
            )

            assert response.status_code == 404

    def test_get_match_events_with_valid_match(self, client, app, db, player, match):
        """
        GIVEN an authenticated user
        WHEN requesting events for existing match
        THEN events should be returned
        """
        with app.app_context():
            access_token = create_access_token(identity=str(player.user_id))
            response = client.get(
                f'/api/v1/matches/{match.id}/events',
                headers={'Authorization': f'Bearer {access_token}'}
            )

            # Should return 200 with events data or 304 (ETag)
            assert response.status_code in (200, 304)
            if response.status_code == 200:
                data = response.get_json()
                # Response contains events list within a dict structure
                assert 'events' in data
                assert isinstance(data['events'], list)


@pytest.mark.unit
@pytest.mark.api
class TestGetMatchAvailability:
    """Test match availability endpoint."""

    def test_get_availability_requires_authentication(self, client, app):
        """
        GIVEN an unauthenticated request
        WHEN requesting match availability
        THEN a 401 or 422 error should be returned
        """
        with app.app_context():
            response = client.get('/api/v1/matches/1/availability')

            assert response.status_code in (401, 422)

    def test_get_availability_returns_404_for_nonexistent(self, client, app, db, player):
        """
        GIVEN an authenticated user
        WHEN requesting availability for non-existent match
        THEN a 404 error should be returned
        """
        with app.app_context():
            access_token = create_access_token(identity=str(player.user_id))
            response = client.get(
                '/api/v1/matches/99999/availability',
                headers={'Authorization': f'Bearer {access_token}'}
            )

            assert response.status_code == 404

    def test_get_availability_with_valid_match(self, client, app, db, player, match):
        """
        GIVEN an authenticated user
        WHEN requesting availability for existing match
        THEN availability data should be returned
        """
        with app.app_context():
            access_token = create_access_token(identity=str(player.user_id))
            response = client.get(
                f'/api/v1/matches/{match.id}/availability',
                headers={'Authorization': f'Bearer {access_token}'}
            )

            # Should return 200 with availability data or 304 (ETag)
            assert response.status_code in (200, 304)
            if response.status_code == 200:
                data = response.get_json()
                # Response should have some form of availability data
                assert data is not None


@pytest.mark.unit
@pytest.mark.api
class TestMatchLiveUpdates:
    """Test match live updates endpoint."""

    def test_live_updates_requires_authentication(self, client, app):
        """
        GIVEN an unauthenticated request
        WHEN requesting live updates
        THEN a 401 or 422 error should be returned
        """
        with app.app_context():
            response = client.get('/api/v1/matches/1/live_updates')

            assert response.status_code in (401, 422)

    def test_live_updates_returns_404_for_nonexistent(self, client, app, db, player):
        """
        GIVEN an authenticated user
        WHEN requesting live updates for non-existent match
        THEN a 404 error should be returned
        """
        with app.app_context():
            access_token = create_access_token(identity=str(player.user_id))
            response = client.get(
                '/api/v1/matches/99999/live_updates',
                headers={'Authorization': f'Bearer {access_token}'}
            )

            assert response.status_code == 404

    def test_live_updates_with_valid_match(self, client, app, db, player, match):
        """
        GIVEN an authenticated user
        WHEN requesting live updates for existing match
        THEN live update data should be returned
        """
        with app.app_context():
            access_token = create_access_token(identity=str(player.user_id))
            response = client.get(
                f'/api/v1/matches/{match.id}/live_updates',
                headers={'Authorization': f'Bearer {access_token}'}
            )

            # Should return 200 with data or 304 (ETag)
            assert response.status_code in (200, 304)
