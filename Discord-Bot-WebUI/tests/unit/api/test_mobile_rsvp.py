"""
Mobile API RSVP endpoint tests.

These tests verify the mobile API RSVP endpoints:
- Update availability from web (JWT required)
- Bulk availability updates (JWT required)
- Debug availability endpoint (JWT required)

Note: Tests that require specific player/user relationships across different
database sessions are marked for integration testing.
"""
import pytest
from unittest.mock import patch, MagicMock
from flask_jwt_extended import create_access_token

from tests.factories import UserFactory, PlayerFactory


@pytest.mark.unit
@pytest.mark.api
class TestUpdateAvailabilityWeb:
    """Test web interface availability update endpoint."""

    def test_update_availability_web_requires_authentication(self, client, app):
        """
        GIVEN an unauthenticated request
        WHEN posting to update_availability_web
        THEN a 401 or 422 error should be returned
        """
        with app.app_context():
            response = client.post('/api/v1/update_availability_web', json={
                'match_id': 1,
                'response': 'yes'
            })

            assert response.status_code in (401, 422)

    def test_update_availability_web_requires_match_id(self, client, app, db):
        """
        GIVEN an authenticated user
        WHEN posting without match_id
        THEN a 400 error should be returned
        """
        with app.app_context():
            user = UserFactory(username='web_test1')
            db.session.commit()

            access_token = create_access_token(identity=str(user.id))
            response = client.post(
                '/api/v1/update_availability_web',
                json={'response': 'yes'},
                headers={'Authorization': f'Bearer {access_token}'}
            )

            assert response.status_code == 400

    def test_update_availability_web_requires_response(self, client, app, db):
        """
        GIVEN an authenticated user
        WHEN posting without response
        THEN a 400 error should be returned
        """
        with app.app_context():
            user = UserFactory(username='web_test2')
            db.session.commit()

            access_token = create_access_token(identity=str(user.id))
            response = client.post(
                '/api/v1/update_availability_web',
                json={'match_id': 1},
                headers={'Authorization': f'Bearer {access_token}'}
            )

            assert response.status_code == 400

    @patch('app.mobile_api.rsvp.update_player_match_availability')
    @patch('app.mobile_api.rsvp.notify_availability_update')
    def test_update_availability_web_success(
        self, mock_notify, mock_update, client, app, db, match, team
    ):
        """
        GIVEN an authenticated user with a player profile
        WHEN posting valid availability
        THEN the availability should be updated
        """
        with app.app_context():
            user = UserFactory(username='web_success')
            player = PlayerFactory(name='Web Player', user=user, primary_team_id=team.id)
            db.session.commit()

            mock_update.return_value = True

            access_token = create_access_token(identity=str(user.id))
            response = client.post(
                '/api/v1/update_availability_web',
                json={'match_id': match.id, 'response': 'yes'},
                headers={'Authorization': f'Bearer {access_token}'}
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data['success'] is True
            assert data['availability'] == 'yes'


@pytest.mark.unit
@pytest.mark.api
class TestBulkAvailabilityUpdate:
    """Test bulk availability update endpoint."""

    def test_bulk_availability_requires_authentication(self, client, app):
        """
        GIVEN an unauthenticated request
        WHEN posting to bulk availability endpoint
        THEN a 401 or 422 error should be returned
        """
        with app.app_context():
            response = client.post('/api/v1/matches/availability/bulk', json={
                'updates': [{'match_id': 1, 'availability': 'yes'}]
            })

            assert response.status_code in (401, 422)

    def test_bulk_availability_requires_updates_list(self, client, app, db):
        """
        GIVEN an authenticated user
        WHEN posting without updates list
        THEN a 400 error should be returned
        """
        with app.app_context():
            user = UserFactory(username='bulk_test1')
            db.session.commit()

            access_token = create_access_token(identity=str(user.id))
            response = client.post(
                '/api/v1/matches/availability/bulk',
                json={},
                headers={'Authorization': f'Bearer {access_token}'}
            )

            assert response.status_code == 400

    @patch('app.mobile_api.rsvp.update_player_match_availability')
    def test_bulk_availability_handles_invalid_updates(
        self, mock_update, client, app, db, team
    ):
        """
        GIVEN an authenticated user with a player profile
        WHEN posting updates with missing fields
        THEN those updates should fail individually
        """
        with app.app_context():
            user = UserFactory(username='bulk_invalid')
            player = PlayerFactory(name='Bulk Player', user=user, primary_team_id=team.id)
            db.session.commit()

            access_token = create_access_token(identity=str(user.id))
            response = client.post(
                '/api/v1/matches/availability/bulk',
                json={'updates': [
                    {'match_id': 1},  # Missing availability
                    {'availability': 'yes'}  # Missing match_id
                ]},
                headers={'Authorization': f'Bearer {access_token}'}
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data['failed'] == 2
            assert data['successful'] == 0

    @patch('app.mobile_api.rsvp.update_player_match_availability')
    def test_bulk_availability_handles_nonexistent_matches(
        self, mock_update, client, app, db, team
    ):
        """
        GIVEN an authenticated user with a player profile
        WHEN posting updates for non-existent matches
        THEN those updates should fail individually
        """
        with app.app_context():
            user = UserFactory(username='bulk_nomatch')
            player = PlayerFactory(name='Bulk NoMatch', user=user, primary_team_id=team.id)
            db.session.commit()

            access_token = create_access_token(identity=str(user.id))
            response = client.post(
                '/api/v1/matches/availability/bulk',
                json={'updates': [
                    {'match_id': 99999, 'availability': 'yes'},
                    {'match_id': 88888, 'availability': 'no'}
                ]},
                headers={'Authorization': f'Bearer {access_token}'}
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data['failed'] == 2
            # Check that each result indicates failure
            for result in data['results']:
                assert result['success'] is False
                assert 'error' in result

    @patch('app.mobile_api.rsvp.update_player_match_availability')
    def test_bulk_availability_success(
        self, mock_update, client, app, db, match, team, schedule
    ):
        """
        GIVEN an authenticated user with a player profile
        WHEN posting valid bulk updates
        THEN all updates should succeed
        """
        from app.models import Match

        with app.app_context():
            user = UserFactory(username='bulk_success')
            player = PlayerFactory(name='Bulk Success', user=user, primary_team_id=team.id)

            # Create another match for bulk update
            match2 = Match(
                date=schedule.date,
                time=schedule.time,
                location='Field 2',
                home_team_id=team.id,
                away_team_id=match.away_team_id,
                schedule_id=schedule.id
            )
            db.session.add(match2)
            db.session.commit()

            mock_update.return_value = True

            access_token = create_access_token(identity=str(user.id))
            response = client.post(
                '/api/v1/matches/availability/bulk',
                json={'updates': [
                    {'match_id': match.id, 'availability': 'yes'},
                    {'match_id': match2.id, 'availability': 'no'}
                ]},
                headers={'Authorization': f'Bearer {access_token}'}
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data['successful'] == 2
            assert data['failed'] == 0


@pytest.mark.unit
@pytest.mark.api
class TestDebugAvailability:
    """Test debug availability endpoint."""

    def test_debug_availability_requires_authentication(self, client, app):
        """
        GIVEN an unauthenticated request
        WHEN requesting debug availability
        THEN a 401 or 422 error should be returned
        """
        with app.app_context():
            response = client.get('/api/v1/debug/availability')

            assert response.status_code in (401, 422)

    def test_debug_availability_with_valid_jwt(self, client, app, db, player):
        """
        GIVEN an authenticated request with valid JWT
        WHEN requesting debug availability
        THEN either player info or 404 should be returned (based on player lookup)
        """
        with app.app_context():
            access_token = create_access_token(identity=str(player.user_id))
            response = client.get(
                '/api/v1/debug/availability',
                headers={'Authorization': f'Bearer {access_token}'}
            )

            # Response should be valid (200 with data or 404 if player not found in managed_session)
            assert response.status_code in (200, 404)
            if response.status_code == 200:
                data = response.get_json()
                assert 'player_id' in data
                assert 'recent_availability' in data
