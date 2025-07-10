"""
Unit tests for authentication endpoints.
"""
import pytest
import json
from unittest.mock import patch, Mock
from datetime import datetime, timedelta


@pytest.mark.unit
@pytest.mark.auth
class TestAuthAPI:
    """Test authentication API endpoints."""
    
    def test_login_success(self, client, user):
        """Test successful login."""
        response = client.post('/auth/login', data={
            'username': 'testuser',
            'password': 'password123'
        }, follow_redirects=False)
        
        assert response.status_code == 302  # Redirect after successful login
        
        # Test session
        with client.session_transaction() as session:
            assert 'user_id' in session
    
    def test_login_invalid_credentials(self, client, user):
        """Test login with invalid credentials."""
        response = client.post('/auth/login', data={
            'username': 'testuser',
            'password': 'wrongpassword'
        })
        
        assert response.status_code == 200
        assert b'Invalid username or password' in response.data
    
    def test_login_unapproved_user(self, client, db):
        """Test login with unapproved user."""
        # Create unapproved user
        from app.models import User
        user = User(
            username='unapproved',
            email='unapproved@test.com',
            approved=False
        )
        user.set_password('password123')
        db.session.add(user)
        db.session.commit()
        
        response = client.post('/auth/login', data={
            'username': 'unapproved',
            'password': 'password123'
        })
        
        assert response.status_code == 200
        assert b'Account pending approval' in response.data
    
    def test_logout(self, authenticated_client):
        """Test logout functionality."""
        response = authenticated_client.get('/auth/logout', follow_redirects=True)
        
        assert response.status_code == 200
        
        # Verify session cleared
        with authenticated_client.session_transaction() as session:
            assert 'user_id' not in session
    
    def test_register_success(self, client, db):
        """Test successful registration."""
        response = client.post('/auth/register', data={
            'username': 'newuser',
            'email': 'newuser@test.com',
            'password': 'SecurePass123!',
            'password_confirm': 'SecurePass123!',
            'discord_username': 'NewUser#1234'
        }, follow_redirects=True)
        
        assert response.status_code == 200
        assert b'Registration successful' in response.data
        
        # Verify user created
        from app.models import User
        user = User.query.filter_by(username='newuser').first()
        assert user is not None
        assert user.email == 'newuser@test.com'
        assert not user.approved  # Should require approval
    
    def test_register_duplicate_username(self, client, user):
        """Test registration with duplicate username."""
        response = client.post('/auth/register', data={
            'username': 'testuser',  # Already exists
            'email': 'another@test.com',
            'password': 'SecurePass123!',
            'password_confirm': 'SecurePass123!',
            'discord_username': 'Another#1234'
        })
        
        assert response.status_code == 200
        assert b'Username already exists' in response.data
    
    def test_two_factor_setup(self, authenticated_client, user):
        """Test 2FA setup process."""
        response = authenticated_client.get('/auth/two-factor/setup')
        assert response.status_code == 200
        assert b'Two-Factor Authentication Setup' in response.data
        
        # Mock TOTP verification
        with patch('app.auth.verify_totp') as mock_verify:
            mock_verify.return_value = True
            
            response = authenticated_client.post('/auth/two-factor/setup', data={
                'totp_code': '123456'
            }, follow_redirects=True)
            
            assert response.status_code == 200
            assert b'Two-factor authentication enabled' in response.data
    
    def test_two_factor_login(self, client, db):
        """Test login with 2FA enabled."""
        from app.models import User
        
        # Create user with 2FA
        user = User(
            username='2fauser',
            email='2fa@test.com',
            approved=True,
            two_factor_enabled=True,
            two_factor_secret='SECRET123'
        )
        user.set_password('password123')
        db.session.add(user)
        db.session.commit()
        
        # First step - username/password
        response = client.post('/auth/login', data={
            'username': '2fauser',
            'password': 'password123'
        })
        
        assert response.status_code == 302
        assert response.location.endswith('/auth/two-factor')
        
        # Second step - TOTP code
        with patch('app.auth.verify_totp') as mock_verify:
            mock_verify.return_value = True
            
            response = client.post('/auth/two-factor', data={
                'totp_code': '123456'
            }, follow_redirects=True)
            
            assert response.status_code == 200
            with client.session_transaction() as session:
                assert 'user_id' in session
    
    @patch('app.auth.discord')
    def test_discord_oauth_callback(self, mock_discord, client, db):
        """Test Discord OAuth callback."""
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
            
            # Should create/update user
            from app.models import User
            user = User.query.filter_by(discord_id='123456789').first()
            assert user is not None
            assert user.discord_username == 'DiscordUser#1234'
    
    def test_password_reset_request(self, client, user, mock_smtp):
        """Test password reset request."""
        response = client.post('/auth/forgot-password', data={
            'email': 'test@example.com'
        }, follow_redirects=True)
        
        assert response.status_code == 200
        assert b'Password reset email sent' in response.data
        
        # Verify email was sent
        assert mock_smtp.send.called
    
    def test_password_reset_complete(self, client, user):
        """Test password reset with token."""
        # Generate reset token
        token = user.get_reset_password_token()
        
        response = client.post(f'/auth/reset-password/{token}', data={
            'password': 'NewSecurePass123!',
            'password_confirm': 'NewSecurePass123!'
        }, follow_redirects=True)
        
        assert response.status_code == 200
        assert b'Password has been reset' in response.data
        
        # Verify password changed
        assert user.check_password('NewSecurePass123!')
    
    def test_session_expiry(self, authenticated_client, app):
        """Test session expiry handling."""
        with patch('datetime.datetime') as mock_datetime:
            # Set time to future (beyond session lifetime)
            future_time = datetime.utcnow() + timedelta(hours=25)
            mock_datetime.utcnow.return_value = future_time
            
            response = authenticated_client.get('/players/')
            assert response.status_code == 302  # Should redirect to login
            assert '/auth/login' in response.location