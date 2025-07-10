"""
Unit tests for authentication workflows.
Tests behavior and user outcomes, not implementation details.
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch

from tests.factories import UserFactory
from tests.helpers import AuthTestHelper


@pytest.mark.unit
class TestAuthenticationWorkflow:
    """Test authentication behaviors from user perspective."""
    
    def test_user_can_login_with_valid_credentials(self, client, db):
        """User should be able to login with correct username and password."""
        # Given: A registered user
        user = UserFactory(username='testuser')
        
        # When: They login with correct credentials
        response = AuthTestHelper.login_user(client, user)
        
        # Then: They should be logged in successfully
        assert response.status_code == 200
        assert b'Dashboard' in response.data  # User sees dashboard
        
        # And: Session should be established
        with client.session_transaction() as session:
            assert session.get('user_id') == user.id
    
    def test_user_cannot_login_with_wrong_password(self, client, db):
        """User should see error message with incorrect password."""
        # Given: A registered user
        user = UserFactory(username='testuser')
        
        # When: They login with wrong password
        response = client.post('/auth/login', data={
            'username': 'testuser',
            'password': 'wrongpassword'
        })
        
        # Then: They should see an error
        assert response.status_code == 200  # Stays on login page
        assert b'Invalid username or password' in response.data
        
        # And: No session should be created
        with client.session_transaction() as session:
            assert 'user_id' not in session
    
    def test_unapproved_user_sees_pending_message(self, client, db):
        """Unapproved users should see a pending approval message."""
        # Given: An unapproved user
        user = UserFactory(username='pending', approved=False)
        
        # When: They try to login
        response = client.post('/auth/login', data={
            'username': 'pending',
            'password': 'password123'
        })
        
        # Then: They should see pending message
        assert b'Account pending approval' in response.data
        assert b'administrator will review' in response.data
    
    def test_user_can_logout(self, client, db):
        """Logged in user should be able to logout."""
        # Given: A logged in user
        user = UserFactory()
        client = AuthTestHelper.create_authenticated_session(client, user)
        
        # When: They logout
        response = client.get('/auth/logout', follow_redirects=True)
        
        # Then: They should be logged out
        assert response.status_code == 200
        assert b'logged out' in response.data.lower()
        
        # And: Session should be cleared
        with client.session_transaction() as session:
            assert 'user_id' not in session
    
    def test_user_can_register_new_account(self, client, db):
        """New user should be able to create an account."""
        # When: User submits registration form
        response = client.post('/auth/register', data={
            'username': 'newuser',
            'email': 'new@example.com',
            'password': 'SecurePass123!',
            'password_confirm': 'SecurePass123!',
            'phone_number': '555-123-4567',
            'discord_username': 'NewUser#1234'
        }, follow_redirects=True)
        
        # Then: Account should be created
        assert b'Registration successful' in response.data
        assert b'administrator will review' in response.data
        
        # And: User should exist in database
        from app.models import User
        user = User.query.filter_by(username='newuser').first()
        assert user is not None
        assert user.email == 'new@example.com'
        assert not user.approved  # Requires approval
    
    def test_duplicate_username_shows_error(self, client, db):
        """Registration with existing username should show error."""
        # Given: An existing user
        existing = UserFactory(username='taken')
        
        # When: Someone tries to register with same username
        response = client.post('/auth/register', data={
            'username': 'taken',
            'email': 'different@example.com',
            'password': 'Password123!',
            'password_confirm': 'Password123!',
            'discord_username': 'Different#1234'
        })
        
        # Then: They should see an error
        assert b'Username already exists' in response.data
    
    @patch('app.auth.send_password_reset_email')
    def test_user_can_request_password_reset(self, mock_email, client, db):
        """User should be able to request password reset."""
        # Given: A user who forgot their password
        user = UserFactory(email='forgetful@example.com')
        
        # When: They request a reset
        response = client.post('/auth/forgot-password', data={
            'email': 'forgetful@example.com'
        }, follow_redirects=True)
        
        # Then: They should see confirmation
        assert b'reset link has been sent' in response.data
        
        # And: Email should be sent
        mock_email.assert_called_once()
        assert mock_email.call_args[0][0].id == user.id
    
    def test_session_expires_after_inactivity(self, client, db, app):
        """User session should expire after configured timeout."""
        # Given: A logged in user
        user = UserFactory()
        
        with patch('datetime.datetime') as mock_datetime:
            # Login at current time
            now = datetime.utcnow()
            mock_datetime.utcnow.return_value = now
            
            client = AuthTestHelper.create_authenticated_session(client, user)
            
            # When: Time passes beyond session timeout
            mock_datetime.utcnow.return_value = now + timedelta(hours=25)
            
            # Then: Protected routes should redirect to login
            response = client.get('/players/')
            assert response.status_code == 302
            assert '/auth/login' in response.location