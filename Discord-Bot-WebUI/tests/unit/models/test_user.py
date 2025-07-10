"""
Unit tests for User model and authentication.
"""
import pytest
from datetime import datetime, timedelta
from app.models import User, Role
from sqlalchemy.exc import IntegrityError


@pytest.mark.unit
class TestUserModel:
    """Test User model functionality."""
    
    def test_create_user(self, db):
        """Test user creation."""
        user = User(
            username='newuser',
            email='new@example.com',
            discord_id='111222333',
            discord_username='NewUser#5678'
        )
        user.set_password('secure_password')
        db.session.add(user)
        db.session.commit()
        
        assert user.id is not None
        assert user.username == 'newuser'
        assert user.email == 'new@example.com'
        assert user.check_password('secure_password')
        assert not user.check_password('wrong_password')
    
    def test_user_unique_constraints(self, db):
        """Test unique constraints on user fields."""
        user1 = User(
            username='unique_user',
            email='unique@example.com',
            discord_id='999888777'
        )
        db.session.add(user1)
        db.session.commit()
        
        # Test duplicate username
        user2 = User(
            username='unique_user',  # Duplicate
            email='different@example.com',
            discord_id='111222333'
        )
        db.session.add(user2)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()
        
        # Test duplicate email
        user3 = User(
            username='different_user',
            email='unique@example.com',  # Duplicate
            discord_id='444555666'
        )
        db.session.add(user3)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()
    
    def test_user_roles(self, db, user_role, admin_role):
        """Test user role assignment."""
        user = User(username='roletest', email='role@test.com')
        user.roles.append(user_role)
        user.roles.append(admin_role)
        db.session.add(user)
        db.session.commit()
        
        assert len(user.roles) == 2
        assert user.has_role('User')
        assert user.has_role('Admin')
        assert not user.has_role('NonExistent')
    
    def test_user_approval(self, db):
        """Test user approval workflow."""
        user = User(
            username='pending',
            email='pending@test.com',
            approved=False
        )
        db.session.add(user)
        db.session.commit()
        
        assert not user.approved
        assert user.approved_date is None
        
        # Approve user
        user.approved = True
        user.approved_date = datetime.utcnow()
        db.session.commit()
        
        assert user.approved
        assert user.approved_date is not None
    
    def test_password_hashing(self, db):
        """Test password hashing and verification."""
        user = User(username='hashtest', email='hash@test.com')
        
        # Test setting password
        user.set_password('MySecureP@ssw0rd')
        assert user.password_hash is not None
        assert user.password_hash != 'MySecureP@ssw0rd'  # Should be hashed
        
        # Test password verification
        assert user.check_password('MySecureP@ssw0rd')
        assert not user.check_password('WrongPassword')
        assert not user.check_password('')
        assert not user.check_password(None)
    
    def test_two_factor_auth(self, db):
        """Test two-factor authentication setup."""
        user = User(username='2fatest', email='2fa@test.com')
        db.session.add(user)
        db.session.commit()
        
        assert not user.two_factor_enabled
        assert user.two_factor_secret is None
        
        # Enable 2FA
        user.enable_two_factor('TEST_SECRET_KEY')
        assert user.two_factor_enabled
        assert user.two_factor_secret == 'TEST_SECRET_KEY'
        
        # Disable 2FA
        user.disable_two_factor()
        assert not user.two_factor_enabled
        assert user.two_factor_secret is None
    
    def test_user_statistics(self, db, user, team, match):
        """Test user statistics methods."""
        from app.models import Player, Availability
        
        # Create player
        player = Player(user_id=user.id, team_id=team.id)
        db.session.add(player)
        
        # Create availability
        avail = Availability(
            user_id=user.id,
            match_id=match.id,
            available=True,
            response_date=datetime.utcnow()
        )
        db.session.add(avail)
        db.session.commit()
        
        # Test statistics
        stats = user.get_season_stats(match.season_id)
        assert stats is not None
        assert 'matches_played' in stats
        assert 'goals' in stats
    
    def test_user_phone_number(self, db):
        """Test phone number formatting."""
        user = User(username='phonetest', email='phone@test.com')
        
        # Test various phone formats
        user.phone_number = '(555) 123-4567'
        assert user.formatted_phone_number == '+15551234567'
        
        user.phone_number = '555.123.4567'
        assert user.formatted_phone_number == '+15551234567'
        
        user.phone_number = '+1-555-123-4567'
        assert user.formatted_phone_number == '+15551234567'
        
        user.phone_number = '5551234567'
        assert user.formatted_phone_number == '+15551234567'
        
        user.phone_number = None
        assert user.formatted_phone_number is None
    
    def test_user_repr(self, db, user):
        """Test user string representation."""
        assert repr(user) == f'<User {user.username}>'
        assert str(user) == user.username