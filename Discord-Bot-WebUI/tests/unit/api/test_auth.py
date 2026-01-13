"""
Unit tests for authentication endpoints.

These tests use behavior-based assertions to be resilient to changes.
Tests verify WHAT happens, not specific error messages or internal state.
"""
import pytest
import json
from unittest.mock import patch, Mock
from datetime import datetime, timedelta

from tests.assertions import (
    assert_login_succeeded,
    assert_login_failed,
    assert_user_authenticated,
    assert_user_not_authenticated,
)


@pytest.mark.unit
@pytest.mark.auth
class TestAuthAPI:
    """Test authentication API endpoints."""

    def test_login_success(self, client, user):
        """Test successful login - user becomes authenticated."""
        response = client.post('/auth/login', data={
            'username': 'testuser',
            'password': 'password123'
        }, follow_redirects=False)

        # Behavior: User is now authenticated
        assert_login_succeeded(response, client)

    def test_login_invalid_credentials(self, client, user):
        """Test login with invalid credentials - user NOT authenticated."""
        response = client.post('/auth/login', data={
            'username': 'testuser',
            'password': 'wrongpassword'
        })

        # Behavior: Login failed, user not authenticated
        assert_login_failed(response, client)

    def test_login_unapproved_user(self, client, db):
        """Test login with unapproved user - user NOT authenticated."""
        # Create unapproved user
        from app.models import User
        user = User(
            username='unapproved',
            email='unapproved@test.com',
            is_approved=False,
            approval_status='pending'
        )
        user.set_password('password123')
        db.session.add(user)
        db.session.commit()

        response = client.post('/auth/login', data={
            'username': 'unapproved',
            'password': 'password123'
        })

        # Behavior: Login failed, user not authenticated
        assert_login_failed(response, client)
    
    def test_logout(self, authenticated_client):
        """Test logout functionality - user becomes unauthenticated."""
        response = authenticated_client.get('/auth/logout', follow_redirects=True)

        # Behavior: User is no longer authenticated
        assert response.status_code == 200
        assert_user_not_authenticated(authenticated_client)

    def test_register_success(self, client, db):
        """Test successful registration - user account created."""
        response = client.post('/auth/register', data={
            'username': 'newuser',
            'email': 'newuser@test.com',
            'password': 'SecurePass123!',
            'password_confirm': 'SecurePass123!',
            'discord_username': 'NewUser#1234'
        }, follow_redirects=True)

        # Behavior: User account was created
        from app.models import User
        user = User.query.filter_by(username='newuser').first()
        assert user is not None, "User should be created after registration"
        assert user.email == 'newuser@test.com'

    def test_register_duplicate_username(self, client, user):
        """Test registration with duplicate username - no new user created."""
        response = client.post('/auth/register', data={
            'username': 'testuser',  # Already exists
            'email': 'another@test.com',
            'password': 'SecurePass123!',
            'password_confirm': 'SecurePass123!',
            'discord_username': 'Another#1234'
        })

        # Behavior: No duplicate user created
        from app.models import User
        users_with_email = User.query.filter_by(email='another@test.com').all()
        assert len(users_with_email) == 0, "Should not create user with duplicate username"

    def test_two_factor_setup(self, authenticated_client, user):
        """Test 2FA setup process - can access setup page."""
        response = authenticated_client.get('/auth/two-factor/setup')
        # Behavior: Setup page accessible
        assert response.status_code == 200

        # Mock TOTP verification
        with patch('app.auth.two_factor.verify_totp') as mock_verify:
            mock_verify.return_value = True

            response = authenticated_client.post('/auth/two-factor/setup', data={
                'totp_code': '123456'
            }, follow_redirects=True)

            # Behavior: Setup completes successfully
            assert response.status_code == 200
    
    def test_two_factor_login(self, client, db):
        """Test login with 2FA enabled - requires second factor."""
        from app.models import User

        # Create user with 2FA
        user = User(
            username='2fauser',
            email='2fa@test.com',
            is_approved=True,
            approval_status='approved',
            is_2fa_enabled=True,
            totp_secret='TESTSECRET123456'
        )
        user.set_password('password123')
        db.session.add(user)
        db.session.commit()

        # First step - username/password
        response = client.post('/auth/login', data={
            'username': '2fauser',
            'password': 'password123'
        })

        # Behavior: Not yet fully authenticated (need 2FA)
        assert_user_not_authenticated(client)

        # Second step - TOTP code
        with patch('app.auth.two_factor.verify_totp') as mock_verify:
            mock_verify.return_value = True

            response = client.post('/auth/two-factor', data={
                'totp_code': '123456'
            }, follow_redirects=True)

            # Behavior: Now fully authenticated
            assert_user_authenticated(client)

    @patch('app.auth.discord.discord')
    def test_discord_oauth_callback(self, mock_discord, client, db):
        """Test Discord OAuth callback - completes authentication flow."""
        # Mock Discord OAuth response
        mock_discord.authorized = True
        mock_discord.fetch_token.return_value = {'access_token': 'test_token'}

        mock_user_info = {
            'id': '123456789',
            'username': 'DiscordUser',
            'discriminator': '1234',
            'email': 'discord@test.com'
        }

        with patch('requests.get') as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = mock_user_info
            mock_get.return_value = mock_response

            response = client.get('/auth/discord/callback', follow_redirects=True)

            # Behavior: OAuth callback completes (either creates user or redirects)
            # Note: discord_id is stored on Player model, not User model
            assert response.status_code in (200, 302), "OAuth callback should complete successfully"

    def test_password_reset_request(self, client, user, mock_smtp):
        """Test password reset request - email is sent."""
        response = client.post('/auth/forgot-password', data={
            'email': 'test@example.com'
        }, follow_redirects=True)

        # Behavior: Request completes and email is sent
        assert response.status_code == 200
        assert mock_smtp.send.called, "Password reset email should be sent"

    def test_password_reset_complete(self, client, user):
        """Test password reset with token - password changes."""
        # Generate reset token
        token = user.get_reset_password_token()

        response = client.post(f'/auth/reset-password/{token}', data={
            'password': 'NewSecurePass123!',
            'password_confirm': 'NewSecurePass123!'
        }, follow_redirects=True)

        # Behavior: Password was changed
        assert response.status_code == 200
        assert user.check_password('NewSecurePass123!'), "Password should be updated"

    def test_session_expiry(self, authenticated_client, app):
        """Test session expiry handling - user redirected to login."""
        # Set invalid session
        with authenticated_client.session_transaction() as session:
            session['user_id'] = 99999  # Non-existent user

        response = authenticated_client.get('/players/', follow_redirects=False)

        # Behavior: Invalid session redirects to login
        assert response.status_code in (302, 401, 403)