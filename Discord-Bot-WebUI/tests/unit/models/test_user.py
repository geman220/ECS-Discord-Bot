"""
User model unit tests.

These tests verify the User model's core behaviors:
- Password hashing and verification
- Role and permission checking
- 2FA token generation and verification
- Approval status management
"""
import pytest
import pyotp
from unittest.mock import patch, MagicMock

from tests.factories import UserFactory


@pytest.mark.unit
class TestUserPasswordBehaviors:
    """Test User password-related behaviors."""

    def test_set_password_creates_hash(self, db):
        """
        GIVEN a new User
        WHEN set_password is called
        THEN password_hash should be set and not equal to plaintext
        """
        user = UserFactory.build(username='pwd_test')
        user.set_password('mysecretpassword')

        assert user.password_hash is not None
        assert user.password_hash != 'mysecretpassword'
        assert len(user.password_hash) > 0

    def test_check_password_returns_true_for_correct_password(self, db):
        """
        GIVEN a User with a set password
        WHEN check_password is called with correct password
        THEN it should return True
        """
        user = UserFactory.build(username='pwd_check_true')
        user.set_password('correctpassword')

        assert user.check_password('correctpassword') is True

    def test_check_password_returns_false_for_incorrect_password(self, db):
        """
        GIVEN a User with a set password
        WHEN check_password is called with incorrect password
        THEN it should return False
        """
        user = UserFactory.build(username='pwd_check_false')
        user.set_password('correctpassword')

        assert user.check_password('wrongpassword') is False

    def test_password_hash_differs_for_same_password(self, db):
        """
        GIVEN two Users setting the same password
        WHEN passwords are hashed
        THEN hashes should be different (salt is used)
        """
        user1 = UserFactory.build(username='salt_test_1')
        user2 = UserFactory.build(username='salt_test_2')

        user1.set_password('samepassword')
        user2.set_password('samepassword')

        assert user1.password_hash != user2.password_hash


@pytest.mark.unit
class TestUserRoleBehaviors:
    """Test User role-related behaviors."""

    def test_has_role_returns_true_when_user_has_role(self, db, user_role):
        """
        GIVEN a User with a specific role
        WHEN has_role is called with that role name
        THEN it should return True
        """
        user = UserFactory(username='role_test_true')
        user.roles.append(user_role)
        db.session.commit()

        assert user.has_role('User') is True

    def test_has_role_returns_false_when_user_lacks_role(self, db, user_role):
        """
        GIVEN a User without a specific role
        WHEN has_role is called with that role name
        THEN it should return False
        """
        user = UserFactory(username='role_test_false')
        user.roles.append(user_role)
        db.session.commit()

        assert user.has_role('Admin') is False

    def test_has_role_handles_empty_roles(self, db):
        """
        GIVEN a User with no roles
        WHEN has_role is called
        THEN it should return False without error
        """
        user = UserFactory(username='no_roles')
        db.session.commit()

        assert user.has_role('AnyRole') is False


@pytest.mark.unit
class TestUserPermissionBehaviors:
    """Test User permission-related behaviors."""

    def test_has_permission_returns_true_when_role_has_permission(self, db, user_role):
        """
        GIVEN a User with a role that has a specific permission
        WHEN has_permission is called with that permission name
        THEN it should return True
        """
        user = UserFactory(username='perm_test_true')
        user.roles.append(user_role)
        db.session.commit()

        # user_role fixture already has view_rsvps permission
        assert user.has_permission('view_rsvps') is True

    def test_has_permission_returns_false_when_lacking_permission(self, db, user_role):
        """
        GIVEN a User with a role that lacks a specific permission
        WHEN has_permission is called with that permission name
        THEN it should return False
        """
        user = UserFactory(username='perm_test_false')
        user.roles.append(user_role)
        db.session.commit()

        assert user.has_permission('admin_panel') is False

    def test_has_permission_handles_no_roles(self, db):
        """
        GIVEN a User with no roles
        WHEN has_permission is called
        THEN it should return False without error
        """
        user = UserFactory(username='no_roles_perm')
        db.session.commit()

        assert user.has_permission('any_permission') is False


@pytest.mark.unit
class TestUser2FABehaviors:
    """Test User two-factor authentication behaviors."""

    def test_generate_totp_secret_creates_valid_secret(self, db):
        """
        GIVEN a User without 2FA
        WHEN generate_totp_secret is called
        THEN a valid TOTP secret should be stored
        """
        user = UserFactory.build(username='2fa_generate')
        user.generate_totp_secret()

        assert user.totp_secret is not None
        assert len(user.totp_secret) == 32  # Base32 encoded secret length

    def test_verify_totp_accepts_valid_token(self, db):
        """
        GIVEN a User with 2FA enabled
        WHEN verify_totp is called with a valid token
        THEN it should return True
        """
        user = UserFactory.build(username='2fa_verify_true')
        user.generate_totp_secret()

        # Generate current valid token
        totp = pyotp.TOTP(user.totp_secret)
        valid_token = totp.now()

        assert user.verify_totp(valid_token) is True

    def test_verify_totp_rejects_invalid_token(self, db):
        """
        GIVEN a User with 2FA enabled
        WHEN verify_totp is called with an invalid token
        THEN it should return False
        """
        user = UserFactory.build(username='2fa_verify_false')
        user.generate_totp_secret()

        assert user.verify_totp('000000') is False
        assert user.verify_totp('invalid') is False


@pytest.mark.unit
class TestUserApprovalBehaviors:
    """Test User approval status behaviors."""

    def test_new_user_default_approval_status(self, db):
        """
        GIVEN a new User model (not factory)
        WHEN created and persisted with defaults
        THEN approval_status should be 'pending' and is_approved should be False
        """
        from app.models import User

        user = User(username='approval_default')
        user.set_password('test123')
        db.session.add(user)
        db.session.flush()

        # Model defaults applied after persistence
        assert user.is_approved is False
        assert user.approval_status == 'pending'

    def test_approved_user_has_correct_status(self, db):
        """
        GIVEN an approved User
        WHEN is_approved is True
        THEN approval_status should reflect approved state
        """
        user = UserFactory(
            username='approved_user',
            is_approved=True,
            approval_status='approved'
        )
        db.session.commit()

        assert user.is_approved is True
        assert user.approval_status == 'approved'


@pytest.mark.unit
class TestUserSerializationBehaviors:
    """Test User serialization behaviors."""

    def test_to_dict_includes_required_fields(self, db, user_role):
        """
        GIVEN a User with roles
        WHEN to_dict is called
        THEN it should include all required fields
        """
        user = UserFactory(username='serialize_test')
        user.roles.append(user_role)
        db.session.commit()

        result = user.to_dict()

        assert 'id' in result
        assert 'username' in result
        assert 'is_approved' in result
        assert 'roles' in result
        assert 'has_completed_onboarding' in result
        assert result['username'] == 'serialize_test'

    def test_to_dict_includes_role_names(self, db, user_role, admin_role):
        """
        GIVEN a User with multiple roles
        WHEN to_dict is called
        THEN roles should be a list of role names
        """
        user = UserFactory(username='multi_role')
        user.roles.append(user_role)
        user.roles.append(admin_role)
        db.session.commit()

        result = user.to_dict()

        assert 'User' in result['roles']
        assert 'Admin' in result['roles']


@pytest.mark.unit
class TestUserNotificationPreferences:
    """Test User notification preference behaviors."""

    def test_default_notification_preferences(self, db):
        """
        GIVEN a new User model (not factory)
        WHEN created and persisted with defaults
        THEN all notification preferences should be True
        """
        from app.models import User

        user = User(username='notif_default')
        user.set_password('test123')
        db.session.add(user)
        db.session.flush()

        # Model defaults applied after persistence
        assert user.push_notifications is True
        assert user.email_notifications is True
        assert user.sms_notifications is True
        assert user.discord_notifications is True

    def test_can_disable_push_notifications(self, db):
        """
        GIVEN a User
        WHEN push_notifications is set to False
        THEN the preference should be stored
        """
        user = UserFactory(username='notif_disable', push_notifications=False)
        db.session.commit()

        assert user.push_notifications is False
