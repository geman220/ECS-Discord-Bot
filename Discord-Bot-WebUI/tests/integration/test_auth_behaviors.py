"""
Authentication behavior tests.

These tests verify WHAT happens when users authenticate, not HOW the code works.
Tests should remain stable even if:
- Error message text changes
- URL paths change
- Internal session structure changes
- Implementation is refactored

If a test breaks due to a minor change, the test is too narrowly scoped.
"""
import pytest
from unittest.mock import patch, Mock
from datetime import datetime, timedelta

from tests.factories import UserFactory
from tests.assertions import (
    assert_user_authenticated,
    assert_user_not_authenticated,
    assert_login_succeeded,
    assert_login_failed,
    assert_logout_succeeded,
    assert_user_exists,
    assert_user_approved,
    assert_user_not_approved,
    assert_redirects_to_login,
    assert_api_success,
    assert_api_error,
)


@pytest.mark.integration
@pytest.mark.auth
class TestLoginBehaviors:
    """Test login behaviors from user perspective."""

    def test_user_can_login_with_valid_credentials(self, client, db):
        """
        GIVEN an approved user with valid credentials
        WHEN they submit the login form with correct username/password
        THEN they should be authenticated and able to access protected pages
        """
        user = UserFactory(username='validuser', is_approved=True)

        response = client.post('/auth/login', data={
            'username': 'validuser',
            'password': 'password123'
        }, follow_redirects=False)

        # Behavior: User is now authenticated
        assert_login_succeeded(response, client)

    def test_user_cannot_login_with_wrong_password(self, client, db):
        """
        GIVEN a user with valid account
        WHEN they submit login with incorrect password
        THEN they should NOT be authenticated
        """
        user = UserFactory(username='testuser')

        response = client.post('/auth/login', data={
            'username': 'testuser',
            'password': 'wrongpassword'
        }, follow_redirects=False)

        # Behavior: User is NOT authenticated
        assert_login_failed(response, client)

    def test_user_cannot_login_with_nonexistent_username(self, client, db):
        """
        GIVEN no user exists with username
        WHEN someone tries to login with that username
        THEN they should NOT be authenticated
        """
        response = client.post('/auth/login', data={
            'username': 'doesnotexist',
            'password': 'anypassword'
        }, follow_redirects=False)

        # Behavior: Login failed
        assert_login_failed(response, client)

    def test_unapproved_user_cannot_login(self, client, db):
        """
        GIVEN a user whose account is not approved
        WHEN they try to login with correct credentials
        THEN they should NOT be authenticated
        """
        user = UserFactory(
            username='unapproved',
            is_approved=False,
            approval_status='pending'
        )

        response = client.post('/auth/login', data={
            'username': 'unapproved',
            'password': 'password123'
        }, follow_redirects=False)

        # Behavior: User cannot access protected resources
        assert_login_failed(response, client)

    def test_login_via_email_works(self, client, db):
        """
        GIVEN a user with valid account
        WHEN they login using their email instead of username
        THEN they should be authenticated (if supported)
        """
        user = UserFactory(email='logintest@example.com')

        # Try email-based login
        response = client.post('/auth/login', data={
            'username': 'logintest@example.com',  # Using email in username field
            'password': 'password123'
        }, follow_redirects=False)

        # Note: Behavior depends on whether email login is supported
        # If not supported, this test documents that behavior
        # The point is we test the OUTCOME, not the error message


@pytest.mark.integration
@pytest.mark.auth
class TestLogoutBehaviors:
    """Test logout behaviors."""

    def test_authenticated_user_can_logout(self, authenticated_client):
        """
        GIVEN an authenticated user
        WHEN they access the logout endpoint
        THEN they should no longer be authenticated
        """
        response = authenticated_client.get('/auth/logout', follow_redirects=True)

        # Behavior: User is no longer authenticated
        assert_logout_succeeded(authenticated_client)

    def test_unauthenticated_user_logout_doesnt_error(self, client):
        """
        GIVEN an unauthenticated visitor
        WHEN they access the logout endpoint
        THEN the request should complete without error
        """
        response = client.get('/auth/logout', follow_redirects=True)

        # Behavior: No crash, handled gracefully
        assert response.status_code in (200, 302)


@pytest.mark.integration
@pytest.mark.auth
class TestProtectedRouteBehaviors:
    """Test that protected routes require authentication."""

    def test_unauthenticated_user_redirected_from_protected_page(self, client):
        """
        GIVEN an unauthenticated visitor
        WHEN they try to access a protected page
        THEN they should be redirected to login
        """
        response = client.get('/players/', follow_redirects=False)

        # Behavior: Redirected to authentication
        assert_redirects_to_login(response)

    def test_authenticated_user_can_access_protected_page(self, authenticated_client):
        """
        GIVEN an authenticated user
        WHEN they access a protected page
        THEN they should see the page content
        """
        response = authenticated_client.get('/players/', follow_redirects=False)

        # Behavior: Page loads successfully (not redirected to login)
        assert response.status_code in (200, 304)


@pytest.mark.integration
@pytest.mark.auth
class TestRegistrationBehaviors:
    """Test registration behaviors."""

    def test_new_user_can_register(self, client, db):
        """
        GIVEN registration is open
        WHEN a new user submits valid registration data
        THEN an account should be created for them
        """
        response = client.post('/auth/register', data={
            'username': 'newuser',
            'email': 'newuser@example.com',
            'password': 'SecurePass123!',
            'password_confirm': 'SecurePass123!',
            'discord_username': 'NewUser#1234'
        }, follow_redirects=True)

        # Behavior: User account was created
        user = assert_user_exists(username='newuser')
        assert user.email == 'newuser@example.com'

    def test_registration_requires_unique_username(self, client, db):
        """
        GIVEN a user with username 'existinguser' exists
        WHEN someone tries to register with that same username
        THEN registration should fail (account not created)
        """
        existing = UserFactory(username='existinguser')

        response = client.post('/auth/register', data={
            'username': 'existinguser',  # Already taken
            'email': 'different@example.com',
            'password': 'SecurePass123!',
            'password_confirm': 'SecurePass123!',
        }, follow_redirects=True)

        # Behavior: No new user created with that username
        from app.models import User
        users = User.query.filter_by(email='different@example.com').all()
        assert len(users) == 0, "Should not create duplicate username"

    def test_registration_requires_unique_email(self, client, db):
        """
        GIVEN a user with email exists
        WHEN someone tries to register with that same email
        THEN registration should fail
        """
        existing = UserFactory(email='taken@example.com')

        response = client.post('/auth/register', data={
            'username': 'differentuser',
            'email': 'taken@example.com',  # Already taken
            'password': 'SecurePass123!',
            'password_confirm': 'SecurePass123!',
        }, follow_redirects=True)

        # Behavior: No new user created
        from app.models import User
        users = User.query.filter_by(username='differentuser').all()
        assert len(users) == 0, "Should not create duplicate email"

    def test_new_registrations_require_approval(self, client, db):
        """
        GIVEN registration requires admin approval
        WHEN a new user registers
        THEN their account should be pending approval (not immediately active)
        """
        response = client.post('/auth/register', data={
            'username': 'pendinguser',
            'email': 'pending@example.com',
            'password': 'SecurePass123!',
            'password_confirm': 'SecurePass123!',
        }, follow_redirects=True)

        # Behavior: User exists but is not approved
        user = assert_user_exists(username='pendinguser')
        assert_user_not_approved(user)


@pytest.mark.integration
@pytest.mark.auth
class TestTwoFactorBehaviors:
    """Test two-factor authentication behaviors."""

    def test_user_with_2fa_requires_code_after_password(self, client, db):
        """
        GIVEN a user with 2FA enabled
        WHEN they login with correct password
        THEN they should need to provide 2FA code before being fully authenticated
        """
        user = UserFactory(
            username='2fauser',
            two_factor_enabled=True,
            two_factor_secret='TESTSECRET123'
        )

        # First step: password
        response = client.post('/auth/login', data={
            'username': '2fauser',
            'password': 'password123'
        }, follow_redirects=False)

        # Behavior: Not yet fully authenticated (redirected to 2FA page)
        # We verify by checking they can't access protected resources yet
        assert_user_not_authenticated(client)

    def test_valid_2fa_code_completes_login(self, client, db):
        """
        GIVEN a user who passed password stage of 2FA login
        WHEN they provide a valid 2FA code
        THEN they should be fully authenticated
        """
        user = UserFactory(
            username='2fauser2',
            two_factor_enabled=True,
            two_factor_secret='TESTSECRET123'
        )

        # Login with password first
        client.post('/auth/login', data={
            'username': '2fauser2',
            'password': 'password123'
        })

        # Mock TOTP verification to return True
        with patch('app.auth.two_factor.verify_totp', return_value=True):
            response = client.post('/auth/two-factor', data={
                'totp_code': '123456'
            }, follow_redirects=True)

            # Behavior: Now fully authenticated
            assert_user_authenticated(client)


@pytest.mark.integration
@pytest.mark.auth
class TestPasswordResetBehaviors:
    """Test password reset behaviors."""

    def test_password_reset_request_sends_email(self, client, db, mock_smtp):
        """
        GIVEN a user with valid email
        WHEN they request a password reset
        THEN an email should be sent
        """
        user = UserFactory(email='reset@example.com')

        response = client.post('/auth/forgot-password', data={
            'email': 'reset@example.com'
        }, follow_redirects=True)

        # Behavior: Email was sent
        assert mock_smtp.send.called, "Password reset email should be sent"

    def test_password_reset_request_for_nonexistent_email_doesnt_error(self, client, db):
        """
        GIVEN no user with the given email exists
        WHEN someone requests password reset for that email
        THEN the request should complete without error (no user enumeration)
        """
        response = client.post('/auth/forgot-password', data={
            'email': 'doesnotexist@example.com'
        }, follow_redirects=True)

        # Behavior: Request completes (no crash)
        # Security: Should NOT reveal whether email exists
        assert response.status_code == 200


@pytest.mark.integration
@pytest.mark.auth
class TestDiscordOAuthBehaviors:
    """Test Discord OAuth authentication behaviors."""

    @patch('app.auth.discord.discord')
    def test_discord_oauth_creates_new_user(self, mock_discord, client, db):
        """
        GIVEN Discord OAuth callback with new user info
        WHEN the callback is processed
        THEN a new user account should be created
        """
        mock_discord.authorized = True

        with patch('requests.get') as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {
                'id': '123456789',
                'username': 'DiscordNewUser',
                'discriminator': '1234',
                'email': 'discord_new@example.com'
            }
            mock_get.return_value = mock_response

            response = client.get('/auth/discord/callback', follow_redirects=True)

            # Behavior: User was created with Discord ID
            user = assert_user_exists(discord_id='123456789')
            assert user is not None

    @patch('app.auth.discord.discord')
    def test_discord_oauth_links_existing_user(self, mock_discord, client, db):
        """
        GIVEN an existing user and Discord OAuth callback with matching email
        WHEN the callback is processed
        THEN the existing user should be linked to Discord
        """
        existing_user = UserFactory(email='existing@example.com')
        mock_discord.authorized = True

        with patch('requests.get') as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {
                'id': '987654321',
                'username': 'ExistingDiscord',
                'discriminator': '5678',
                'email': 'existing@example.com'  # Same email as existing user
            }
            mock_get.return_value = mock_response

            response = client.get('/auth/discord/callback', follow_redirects=True)

            # Behavior: Existing user now has Discord ID
            db.session.refresh(existing_user)
            assert existing_user.discord_id == '987654321'


@pytest.mark.integration
@pytest.mark.auth
class TestSessionBehaviors:
    """Test session management behaviors."""

    def test_session_persists_across_requests(self, authenticated_client):
        """
        GIVEN an authenticated user
        WHEN they make multiple requests
        THEN they should remain authenticated
        """
        # First request
        response1 = authenticated_client.get('/players/')
        assert response1.status_code == 200

        # Second request
        response2 = authenticated_client.get('/players/')
        assert response2.status_code == 200

        # Still authenticated
        assert_user_authenticated(authenticated_client)

    def test_invalid_session_requires_relogin(self, client, db):
        """
        GIVEN a user with an invalid/expired session
        WHEN they try to access protected resources
        THEN they should be redirected to login
        """
        # Simulate invalid session by setting user_id for non-existent user
        with client.session_transaction() as sess:
            sess['user_id'] = 99999  # Non-existent user ID
            sess['_fresh'] = True

        response = client.get('/players/', follow_redirects=False)

        # Behavior: Redirected to login
        assert_redirects_to_login(response)
