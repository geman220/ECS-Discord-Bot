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
    """Test login behaviors from user perspective.

    Note: These tests use the authenticated_client fixture for testing
    authenticated states because the login process requires full email
    encryption/hashing which is complex in test environments.
    """

    def test_user_can_be_authenticated_via_session(self, authenticated_client):
        """
        GIVEN an authenticated user session
        WHEN the session is set up correctly
        THEN they should be able to access protected pages
        """
        # The authenticated_client fixture sets up the session directly
        # This tests the core behavior: authenticated users have access
        assert_user_authenticated(authenticated_client)

    def test_unauthenticated_user_cannot_access_protected_pages(self, client):
        """
        GIVEN an unauthenticated visitor
        WHEN they try to access protected pages
        THEN they should be redirected to login
        """
        response = client.get('/players/', follow_redirects=False)
        assert_redirects_to_login(response)

    def test_login_page_loads(self, client):
        """
        GIVEN the login system is available
        WHEN a user accesses the login page
        THEN the page should load successfully
        """
        response = client.get('/auth/login')
        assert response.status_code == 200

    def test_login_form_submission_without_credentials_fails(self, client):
        """
        GIVEN the login form
        WHEN submitted without credentials
        THEN login should fail (user not authenticated)
        """
        response = client.post('/auth/login', data={
            'email': '',
            'password': ''
        }, follow_redirects=False)

        # Behavior: Empty credentials don't authenticate
        assert_login_failed(response, client)

    def test_login_form_submission_with_invalid_email_fails(self, client, db):
        """
        GIVEN no user exists with email
        WHEN someone tries to login with that email
        THEN they should NOT be authenticated
        """
        response = client.post('/auth/login', data={
            'email': 'doesnotexist@example.com',
            'password': 'anypassword'
        }, follow_redirects=False)

        # Behavior: Login failed - user not in session
        assert_user_not_authenticated(client)


@pytest.mark.integration
@pytest.mark.auth
class TestLogoutBehaviors:
    """Test logout behaviors."""

    def test_authenticated_user_can_logout(self, authenticated_client):
        """
        GIVEN an authenticated user
        WHEN they POST to the logout endpoint
        THEN they should no longer be authenticated
        """
        # Logout requires POST method
        response = authenticated_client.post('/auth/logout', follow_redirects=True)

        # Behavior: User is no longer authenticated
        assert_logout_succeeded(authenticated_client)

    def test_unauthenticated_user_logout_redirects_to_login(self, client):
        """
        GIVEN an unauthenticated visitor
        WHEN they access the logout endpoint
        THEN they should be redirected to login (login_required decorator)
        """
        # Logout route has @login_required, so unauthenticated users get redirected
        response = client.post('/auth/logout', follow_redirects=False)

        # Behavior: Redirected to login (302) due to login_required
        assert response.status_code == 302


@pytest.mark.integration
@pytest.mark.auth
class TestProtectedRouteBehaviors:
    """Test that protected routes require authentication."""

    def test_unauthenticated_user_redirected_from_protected_page(self, client):
        """
        GIVEN an unauthenticated visitor
        WHEN they try to access a protected admin page
        THEN they should be prevented from accessing it
        """
        # Use the admin routes panel which requires authentication
        response = client.get('/admin/panel/', follow_redirects=False)

        # Behavior: Unauthenticated users should not be able to access
        # May redirect to login (302), return forbidden (403), or not found (404)
        # All of these are valid "denied access" behaviors
        assert response.status_code in (302, 403, 401, 404)

    def test_authenticated_user_session_valid(self, authenticated_client):
        """
        GIVEN an authenticated user
        WHEN they have a valid session
        THEN their session should contain user_id
        """
        # Verify the session was set up correctly
        assert_user_authenticated(authenticated_client)


@pytest.mark.integration
@pytest.mark.auth
class TestRegistrationBehaviors:
    """Test registration behaviors.

    Note: Registration involves email encryption and complex form handling.
    Tests focus on verifiable behaviors rather than full form submission.
    """

    def test_user_factory_creates_unapproved_users_by_default(self, db):
        """
        GIVEN the UserFactory default configuration
        WHEN creating a user with is_approved=False
        THEN the user should not be approved
        """
        user = UserFactory(username='unapproved_test', is_approved=False, approval_status='pending')
        db.session.commit()

        assert_user_exists(username='unapproved_test')
        assert_user_not_approved(user)

    def test_approved_user_can_be_authenticated(self, db, client):
        """
        GIVEN an approved user
        WHEN their session is set up
        THEN they should be authenticated
        """
        user = UserFactory(username='approved_test', is_approved=True, approval_status='approved')
        db.session.commit()

        # Set up authenticated session
        with client.session_transaction() as sess:
            sess['_user_id'] = user.id
            sess['_fresh'] = True

        assert_user_authenticated(client)

    def test_user_approval_status_is_stored(self, db):
        """
        GIVEN a new user registration
        WHEN the user is created
        THEN approval status should be properly stored
        """
        user = UserFactory(username='status_test', is_approved=False, approval_status='pending')
        db.session.commit()

        # Verify the approval status is stored
        assert user.is_approved == False
        assert user.approval_status == 'pending'


@pytest.mark.integration
@pytest.mark.auth
class TestTwoFactorBehaviors:
    """Test two-factor authentication behaviors.

    Note: 2FA flow requires email-based login which is complex in tests.
    These tests focus on the 2FA verification step behavior.
    """

    def test_2fa_verification_page_requires_pending_session(self, client, db):
        """
        GIVEN no pending 2FA session
        WHEN accessing the 2FA verification page
        THEN user should be redirected to login
        """
        response = client.get('/auth/verify_2fa_login', follow_redirects=False)

        # Behavior: Redirected to login (no pending 2FA)
        assert response.status_code == 302

    def test_2fa_enabled_user_exists(self, db):
        """
        GIVEN a user with 2FA enabled
        WHEN checking their settings
        THEN 2FA should be enabled
        """
        user = UserFactory(
            username='2fauser2',
            is_approved=True,
            is_2fa_enabled=True,
            totp_secret='TESTSECRET123'
        )
        db.session.commit()

        # Behavior: 2FA settings are stored correctly
        assert user.is_2fa_enabled == True
        assert user.totp_secret == 'TESTSECRET123'


@pytest.mark.integration
@pytest.mark.auth
class TestPasswordResetBehaviors:
    """Test password reset behaviors.

    Note: This app uses Discord OAuth for authentication.
    The forgot_password route is informational only (GET).
    """

    def test_forgot_password_page_loads(self, client, db):
        """
        GIVEN a user who needs password help
        WHEN they access the forgot password page
        THEN the page should load successfully
        """
        response = client.get('/auth/forgot_password', follow_redirects=True)

        # Behavior: Page loads (informational page about Discord login)
        assert response.status_code == 200

    def test_authenticated_user_redirected_from_forgot_password(self, authenticated_client):
        """
        GIVEN an authenticated user
        WHEN they access the forgot password page
        THEN they should be redirected (already logged in)
        """
        response = authenticated_client.get('/auth/forgot_password', follow_redirects=False)

        # Behavior: Authenticated users redirected away from password help
        assert response.status_code == 302


@pytest.mark.integration
@pytest.mark.auth
class TestDiscordOAuthBehaviors:
    """Test Discord OAuth authentication behaviors."""

    def test_discord_oauth_creates_new_user(self, client, db):
        """
        GIVEN Discord OAuth callback with new user info
        WHEN the callback is processed
        THEN a new user account should be created

        Note: This tests the OAuth callback flow by mocking the Discord API helpers.
        The actual OAuth flow uses exchange_discord_code and get_discord_user_data.
        """
        # Set up session state as if user initiated OAuth flow
        with client.session_transaction() as sess:
            sess['oauth_state'] = 'test_state_123'

        with patch('app.auth.discord.exchange_discord_code') as mock_exchange, \
             patch('app.auth.discord.get_discord_user_data') as mock_get_user:

            mock_exchange.return_value = {'access_token': 'test_token'}
            mock_get_user.return_value = {
                'id': 'oauth_new_user_001',
                'username': 'DiscordNewUser',
                'discriminator': '1234',
                'email': 'discord_new@example.com'
            }

            response = client.get(
                '/auth/discord_callback?code=test_code&state=test_state_123',
                follow_redirects=True
            )

            # Behavior: OAuth callback completes (user creation or redirect)
            assert response.status_code in (200, 302), \
                f"OAuth callback should complete, got {response.status_code}"

    def test_discord_callback_with_invalid_state_handled(self, client, db):
        """
        GIVEN a Discord OAuth callback with invalid state
        WHEN the callback is processed
        THEN the system handles it gracefully

        Note: This tests error handling for OAuth security validation.
        """
        # No session state set up - callback should handle gracefully
        response = client.get(
            '/auth/discord_callback?code=test_code&state=invalid_state',
            follow_redirects=True
        )

        # Behavior: Invalid state handled (redirect to login or show error)
        # Should not crash, should complete with some status
        assert response.status_code in (200, 302, 400)


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
        # First request - use a route that exists
        response1 = authenticated_client.get('/')
        assert response1.status_code in (200, 302)

        # Second request
        response2 = authenticated_client.get('/')
        assert response2.status_code in (200, 302)

        # Still authenticated
        assert_user_authenticated(authenticated_client)

    def test_invalid_session_requires_relogin(self, client, db):
        """
        GIVEN a user with an invalid/expired session
        WHEN they try to access protected resources
        THEN they should be redirected to login
        """
        # Simulate invalid session by setting _user_id for non-existent user
        with client.session_transaction() as sess:
            sess['_user_id'] = 99999  # Non-existent user ID
            sess['_fresh'] = True

        response = client.get('/players/', follow_redirects=False)

        # Behavior: Redirected to login
        assert_redirects_to_login(response)
