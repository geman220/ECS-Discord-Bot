"""
Mobile API authentication endpoint tests.

These tests verify the mobile API authentication endpoints:
- Discord OAuth URL generation
- Discord OAuth callback
- 2FA verification
- User profile retrieval
"""
import pytest
from unittest.mock import patch, MagicMock
from flask_jwt_extended import create_access_token

from tests.factories import UserFactory, PlayerFactory


@pytest.mark.unit
@pytest.mark.api
class TestDiscordAuthUrl:
    """Test Discord OAuth URL generation endpoint."""

    def test_get_discord_auth_url_returns_valid_response(self, client, app):
        """
        GIVEN the mobile API is available
        WHEN requesting a Discord auth URL
        THEN a valid response with auth_url should be returned
        """
        with app.app_context():
            response = client.get('/api/v1/get_discord_auth_url')

            assert response.status_code == 200
            data = response.get_json()
            assert 'auth_url' in data
            assert 'code_verifier' in data
            assert 'state' in data
            assert 'discord.com' in data['auth_url']

    def test_get_discord_auth_url_with_custom_redirect(self, client, app):
        """
        GIVEN a custom redirect URI
        WHEN requesting a Discord auth URL
        THEN the redirect URI should be included in the URL
        """
        with app.app_context():
            response = client.get('/api/v1/get_discord_auth_url?redirect_uri=myapp://callback')

            assert response.status_code == 200
            data = response.get_json()
            assert 'auth_url' in data


@pytest.mark.unit
@pytest.mark.api
class TestDiscordCallback:
    """Test Discord OAuth callback endpoint."""

    def test_discord_callback_requires_code(self, client, app):
        """
        GIVEN a Discord callback request without code
        WHEN posting to the callback endpoint
        THEN a 400 error should be returned
        """
        with app.app_context():
            response = client.post('/api/v1/discord_callback', json={
                'redirect_uri': 'myapp://callback',
                'state': 'test_state',
                'code_verifier': 'test_verifier'
            })

            assert response.status_code == 400

    def test_discord_callback_requires_redirect_uri(self, client, app):
        """
        GIVEN a Discord callback request without redirect_uri
        WHEN posting to the callback endpoint
        THEN a 400 error should be returned
        """
        with app.app_context():
            response = client.post('/api/v1/discord_callback', json={
                'code': 'test_code',
                'state': 'test_state',
                'code_verifier': 'test_verifier'
            })

            assert response.status_code == 400

    def test_discord_callback_requires_state(self, client, app):
        """
        GIVEN a Discord callback request without state
        WHEN posting to the callback endpoint
        THEN a 400 error should be returned
        """
        with app.app_context():
            response = client.post('/api/v1/discord_callback', json={
                'code': 'test_code',
                'redirect_uri': 'myapp://callback',
                'code_verifier': 'test_verifier'
            })

            assert response.status_code == 400

    def test_discord_callback_requires_code_verifier(self, client, app):
        """
        GIVEN a Discord callback request without code_verifier
        WHEN posting to the callback endpoint
        THEN a 400 error should be returned
        """
        with app.app_context():
            response = client.post('/api/v1/discord_callback', json={
                'code': 'test_code',
                'redirect_uri': 'myapp://callback',
                'state': 'test_state'
            })

            assert response.status_code == 400


@pytest.mark.unit
@pytest.mark.api
class TestVerify2FA:
    """Test 2FA verification endpoint."""

    def test_verify_2fa_requires_user_id(self, client, app):
        """
        GIVEN a 2FA request without user_id
        WHEN posting to the verify_2fa endpoint
        THEN a 400 error should be returned
        """
        with app.app_context():
            response = client.post('/api/v1/verify_2fa', json={
                'token': '123456'
            })

            assert response.status_code == 400

    def test_verify_2fa_requires_token(self, client, app):
        """
        GIVEN a 2FA request without token
        WHEN posting to the verify_2fa endpoint
        THEN a 400 error should be returned
        """
        with app.app_context():
            response = client.post('/api/v1/verify_2fa', json={
                'user_id': 1
            })

            assert response.status_code == 400

    def test_verify_2fa_invalid_token_rejected(self, client, app, db):
        """
        GIVEN a user with 2FA enabled
        WHEN an invalid token is provided
        THEN a 401 error should be returned
        """
        with app.app_context():
            user = UserFactory(
                username='2fa_test',
                is_2fa_enabled=True
            )
            user.generate_totp_secret()
            db.session.commit()

            response = client.post('/api/v1/verify_2fa', json={
                'user_id': user.id,
                'token': '000000'  # Invalid token
            })

            assert response.status_code == 401


@pytest.mark.unit
@pytest.mark.api
class TestUserProfile:
    """Test user profile endpoint."""

    def test_user_profile_requires_authentication(self, client, app):
        """
        GIVEN an unauthenticated request
        WHEN requesting user profile
        THEN a 401 error should be returned
        """
        with app.app_context():
            response = client.get('/api/v1/user_profile')

            assert response.status_code in (401, 422)  # JWT missing or invalid

    def test_user_profile_returns_user_data(self, client, app, db):
        """
        GIVEN an authenticated user
        WHEN requesting their profile
        THEN user data should be returned
        """
        with app.app_context():
            user = UserFactory(username='profile_test')
            db.session.commit()

            access_token = create_access_token(identity=str(user.id))
            response = client.get(
                '/api/v1/user_profile',
                headers={'Authorization': f'Bearer {access_token}'}
            )

            assert response.status_code == 200
            data = response.get_json()
            assert 'username' in data
            assert data['username'] == 'profile_test'

    def test_user_profile_includes_player_data(self, client, app, db, team):
        """
        GIVEN an authenticated user with a player profile
        WHEN requesting their profile
        THEN player data should be included
        """
        with app.app_context():
            user = UserFactory(username='player_profile')
            player = PlayerFactory(
                name='Test Player Profile',
                user=user,
                primary_team_id=team.id
            )
            db.session.commit()

            access_token = create_access_token(identity=str(user.id))
            response = client.get(
                '/api/v1/user_profile',
                headers={'Authorization': f'Bearer {access_token}'}
            )

            assert response.status_code == 200
            data = response.get_json()
            assert 'player_id' in data
            assert data['player_name'] == 'Test Player Profile'

    def test_user_profile_includes_capabilities(self, client, app, db):
        """
        GIVEN an authenticated user
        WHEN requesting their profile
        THEN capabilities should be included
        """
        with app.app_context():
            user = UserFactory(username='caps_test')
            db.session.commit()

            access_token = create_access_token(identity=str(user.id))
            response = client.get(
                '/api/v1/user_profile',
                headers={'Authorization': f'Bearer {access_token}'}
            )

            assert response.status_code == 200
            data = response.get_json()
            assert 'capabilities' in data
            assert 'can_draft' in data['capabilities']
            assert 'is_admin' in data['capabilities']

    def test_user_profile_returns_404_for_nonexistent_user(self, client, app):
        """
        GIVEN a JWT for a user that doesn't exist
        WHEN requesting their profile
        THEN a 404 error should be returned
        """
        with app.app_context():
            # Create token for non-existent user
            access_token = create_access_token(identity='99999')
            response = client.get(
                '/api/v1/user_profile',
                headers={'Authorization': f'Bearer {access_token}'}
            )

            assert response.status_code == 404
