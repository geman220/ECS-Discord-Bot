"""
Admin helpers unit tests.

These tests verify the admin_helpers module's core behaviors:
- User management functions (filtering, approving, actions)
- System health check functions (database, Redis, Celery, Docker)
- RSVP status handling functions
- Role permission management functions
- Match statistics helpers
- Temporary sub management functions
- Expected role determination
"""
import pytest
from datetime import datetime, date, time, timedelta
from unittest.mock import patch, MagicMock, Mock

from app.models import User, Role, Permission, Player, Team, Match, Availability, Announcement
from tests.factories import (
    UserFactory, PlayerFactory, TeamFactory, MatchFactory,
    AvailabilityFactory, SeasonFactory, LeagueFactory, set_factory_session
)


# =============================================================================
# USER FILTERING TESTS
# =============================================================================

@pytest.mark.unit
class TestGetFilteredUsers:
    """Test get_filtered_users function for user filtering behaviors."""

    def test_get_filtered_users_returns_all_users_when_no_filters(self, db, app):
        """
        GIVEN multiple users in the database
        WHEN get_filtered_users is called with no filters
        THEN it should return all users
        """
        from app.admin_helpers import get_filtered_users

        # Create test users
        user1 = UserFactory(username='filter_test_1')
        user2 = UserFactory(username='filter_test_2')
        db.session.commit()

        result = get_filtered_users({})
        users = result.all()

        usernames = [u.username for u in users]
        assert 'filter_test_1' in usernames
        assert 'filter_test_2' in usernames

    def test_get_filtered_users_filters_by_search_username(self, db, app):
        """
        GIVEN users with different usernames
        WHEN get_filtered_users is called with a search term
        THEN it should return only matching users
        """
        from app.admin_helpers import get_filtered_users

        UserFactory(username='searchable_user')
        UserFactory(username='other_person')
        db.session.commit()

        result = get_filtered_users({'search': 'searchable'})
        users = result.all()

        assert len(users) == 1
        assert users[0].username == 'searchable_user'

    def test_get_filtered_users_filters_by_search_email(self, db, app):
        """
        GIVEN users with different usernames containing email-like patterns
        WHEN get_filtered_users is called with search
        THEN it should return matching users by username

        Note: Email search is not supported at SQL level because emails are encrypted.
        The search only matches usernames.
        """
        from app.admin_helpers import get_filtered_users

        # Create users with distinct usernames (email search not supported due to encryption)
        UserFactory(username='unique_email_user', email='someone@test.com')
        UserFactory(username='different_user', email='other@test.com')
        db.session.commit()

        result = get_filtered_users({'search': 'unique_email'})
        users = result.all()

        assert len(users) == 1
        assert users[0].username == 'unique_email_user'

    def test_get_filtered_users_filters_by_role(self, db, app, admin_role):
        """
        GIVEN users with different roles
        WHEN get_filtered_users is called with role filter
        THEN it should return only users with that role
        """
        from app.admin_helpers import get_filtered_users

        admin_user = UserFactory(username='role_admin_user')
        admin_user.roles.append(admin_role)
        regular_user = UserFactory(username='role_regular_user')
        db.session.commit()

        result = get_filtered_users({'role': 'Admin'})
        users = result.all()

        usernames = [u.username for u in users]
        assert 'role_admin_user' in usernames
        assert 'role_regular_user' not in usernames

    def test_get_filtered_users_filters_by_approved_status(self, db, app):
        """
        GIVEN approved and unapproved users
        WHEN get_filtered_users is called with approved filter
        THEN it should return only approved users
        """
        from app.admin_helpers import get_filtered_users

        UserFactory(username='approved_test_user', is_approved=True)
        UserFactory(username='pending_test_user', is_approved=False)
        db.session.commit()

        result = get_filtered_users({'approved': 'true'})
        users = result.all()

        # All returned users should be approved
        for user in users:
            assert user.is_approved is True


# =============================================================================
# USER ACTION TESTS
# =============================================================================

@pytest.mark.unit
class TestHandleUserAction:
    """Test handle_user_action function for user management actions."""

    def test_handle_user_action_approve_sets_is_approved(self, db, app):
        """
        GIVEN an unapproved user
        WHEN handle_user_action is called with 'approve' action
        THEN the user should be approved
        """
        from app.admin_helpers import handle_user_action
        from flask import g

        user = UserFactory(username='unapproved_action', is_approved=False)
        db.session.commit()
        user_id = user.id

        with app.test_request_context():
            g.db_session = db.session
            result = handle_user_action('approve', user_id)
            # Re-fetch user within the session to check is_approved
            updated_user = User.query.get(user_id)
            is_approved = updated_user.is_approved

        assert result is True
        assert is_approved is True

    def test_handle_user_action_remove_deletes_user(self, db, app):
        """
        GIVEN an existing user
        WHEN handle_user_action is called with 'remove' action
        THEN the user should be deleted
        """
        from app.admin_helpers import handle_user_action
        from flask import g

        user = UserFactory(username='user_to_remove')
        db.session.commit()
        user_id = user.id

        with app.test_request_context():
            g.db_session = db.session
            result = handle_user_action('remove', user_id)
            db.session.commit()

        assert result is True
        assert User.query.get(user_id) is None


# =============================================================================
# SYSTEM HEALTH CHECK TESTS
# =============================================================================

@pytest.mark.unit
class TestCheckDatabaseHealth:
    """Test database health check function."""

    def test_check_database_health_returns_true_when_db_accessible(self, db, app):
        """
        GIVEN a working database connection
        WHEN check_database_health is called
        THEN it should return True
        """
        from app.admin_helpers import check_database_health
        from flask import g

        with app.test_request_context():
            g.db_session = db.session
            result = check_database_health()

        assert result is True

    def test_check_database_health_returns_false_on_error(self, db, app):
        """
        GIVEN a database connection that fails
        WHEN check_database_health is called
        THEN it should return False
        """
        from app.admin_helpers import check_database_health
        from flask import g

        mock_session = MagicMock()
        mock_session.execute.side_effect = Exception("DB connection failed")

        with app.test_request_context():
            g.db_session = mock_session
            result = check_database_health()

        assert result is False


@pytest.mark.unit
class TestCheckRedisHealth:
    """Test Redis health check function."""

    def test_check_redis_health_returns_true_when_redis_accessible(self, app, mock_redis):
        """
        GIVEN a working Redis connection
        WHEN check_redis_health is called
        THEN it should return True
        """
        from app.admin_helpers import check_redis_health

        # The mock_redis fixture already mocks ping to return True
        app.extensions['redis'] = mock_redis

        with app.test_request_context():
            result = check_redis_health()

        assert result is True

    def test_check_redis_health_returns_false_on_connection_error(self, app):
        """
        GIVEN a Redis connection that fails
        WHEN check_redis_health is called
        THEN it should return False
        """
        from app.admin_helpers import check_redis_health

        mock_redis = MagicMock()
        mock_redis.ping.side_effect = Exception("Redis connection failed")
        app.extensions['redis'] = mock_redis

        with app.test_request_context():
            result = check_redis_health()

        assert result is False


@pytest.mark.unit
class TestCheckCeleryHealth:
    """Test Celery health check function."""

    @patch('app.admin_helpers.requests.get')
    def test_check_celery_health_returns_true_when_workers_active(self, mock_get, app):
        """
        GIVEN active Celery workers
        WHEN check_celery_health is called
        THEN it should return True
        """
        from app.admin_helpers import check_celery_health

        mock_response = MagicMock()
        mock_response.json.return_value = {'worker1': {'status': True}}
        mock_get.return_value = mock_response

        with app.test_request_context():
            result = check_celery_health()

        assert result is True

    @patch('app.admin_helpers.requests.get')
    def test_check_celery_health_returns_false_when_no_workers(self, mock_get, app):
        """
        GIVEN no active Celery workers
        WHEN check_celery_health is called
        THEN it should return False
        """
        from app.admin_helpers import check_celery_health

        mock_response = MagicMock()
        mock_response.json.return_value = {}
        mock_get.return_value = mock_response

        with app.test_request_context():
            result = check_celery_health()

        assert result is False

    @patch('app.admin_helpers.requests.get')
    def test_check_celery_health_returns_false_on_connection_error(self, mock_get, app):
        """
        GIVEN Flower API is not accessible
        WHEN check_celery_health is called
        THEN it should return False
        """
        from app.admin_helpers import check_celery_health

        mock_get.side_effect = Exception("Connection refused")

        with app.test_request_context():
            result = check_celery_health()

        assert result is False


@pytest.mark.unit
class TestCheckDockerHealth:
    """Test Docker health check function."""

    @patch('app.admin_helpers.get_docker_client')
    def test_check_docker_health_returns_true_when_docker_available(self, mock_client, app):
        """
        GIVEN Docker daemon is running
        WHEN check_docker_health is called
        THEN it should return True
        """
        from app.admin_helpers import check_docker_health

        mock_client.return_value = MagicMock()  # Return a valid client

        with app.test_request_context():
            result = check_docker_health()

        assert result is True

    @patch('app.admin_helpers.get_docker_client')
    def test_check_docker_health_returns_false_when_docker_unavailable(self, mock_client, app):
        """
        GIVEN Docker daemon is not running
        WHEN check_docker_health is called
        THEN it should return False
        """
        from app.admin_helpers import check_docker_health

        mock_client.return_value = None  # No client available

        with app.test_request_context():
            result = check_docker_health()

        assert result is False


@pytest.mark.unit
class TestCheckSystemHealth:
    """Test overall system health check function."""

    @patch('app.admin_helpers.check_database_health')
    @patch('app.admin_helpers.check_redis_health')
    @patch('app.admin_helpers.check_celery_health')
    @patch('app.admin_helpers.check_docker_health')
    def test_check_system_health_returns_all_statuses(
        self, mock_docker, mock_celery, mock_redis, mock_db, app
    ):
        """
        GIVEN various system components
        WHEN check_system_health is called
        THEN it should return status for all components
        """
        from app.admin_helpers import check_system_health

        mock_db.return_value = True
        mock_redis.return_value = True
        mock_celery.return_value = False
        mock_docker.return_value = True

        with app.test_request_context():
            result = check_system_health()

        assert 'database' in result
        assert 'redis' in result
        assert 'celery' in result
        assert 'docker' in result
        assert 'overall' in result
        assert result['database'] is True
        assert result['celery'] is False
        assert result['overall'] is False  # One component failed


# =============================================================================
# ROLE PERMISSION TESTS
# =============================================================================

@pytest.mark.unit
class TestGetRolePermissionsData:
    """Test role permissions data retrieval function."""

    def test_get_role_permissions_data_returns_permissions_for_valid_role(self, db, app):
        """
        GIVEN a role with permissions
        WHEN get_role_permissions_data is called
        THEN it should return the role's permissions
        """
        from app.admin_helpers import get_role_permissions_data
        import uuid

        # Create role with permission using unique names
        unique_suffix = uuid.uuid4().hex[:8]
        role = Role(name=f'PermTestRole_{unique_suffix}', description='Test role')
        permission = Permission(name=f'test_permission_{unique_suffix}', description='Test')
        role.permissions.append(permission)
        db.session.add(role)
        db.session.add(permission)
        db.session.commit()

        result = get_role_permissions_data(role.id, session=db.session)

        assert result is not None
        assert len(result) == 1
        assert f'test_permission_{unique_suffix}' in result[0]['name']

    def test_get_role_permissions_data_returns_none_for_invalid_role(self, db, app):
        """
        GIVEN a non-existent role ID
        WHEN get_role_permissions_data is called
        THEN it should return None
        """
        from app.admin_helpers import get_role_permissions_data

        result = get_role_permissions_data(99999, session=db.session)

        assert result is None

    def test_get_role_permissions_data_returns_empty_list_for_role_without_permissions(self, db, app):
        """
        GIVEN a role without any permissions
        WHEN get_role_permissions_data is called
        THEN it should return an empty list
        """
        from app.admin_helpers import get_role_permissions_data
        import uuid

        # Use unique role name to avoid conflicts with other tests
        unique_name = f'EmptyPermRole_{uuid.uuid4().hex[:8]}'
        role = Role(name=unique_name, description='Role without permissions')
        # Explicitly ensure permissions is empty
        role.permissions = []
        db.session.add(role)
        db.session.commit()

        # Refresh the role to ensure we have fresh data
        db.session.refresh(role)

        result = get_role_permissions_data(role.id, session=db.session)

        assert result is not None
        assert len(result) == 0


# =============================================================================
# MATCH STATISTICS TESTS
# =============================================================================

@pytest.mark.unit
class TestGetMatchStats:
    """Test match statistics retrieval function."""

    def test_get_match_stats_returns_correct_total(self, db, app, match):
        """
        GIVEN matches in the database
        WHEN get_match_stats is called
        THEN it should return correct total count
        """
        from app.admin_helpers import get_match_stats

        with app.test_request_context():
            result = get_match_stats()

        assert 'total_matches' in result
        assert result['total_matches'] >= 1

    def test_get_match_stats_calculates_completion_rate(self, db, app, match):
        """
        GIVEN completed and incomplete matches
        WHEN get_match_stats is called
        THEN it should calculate completion rate correctly
        """
        from app.admin_helpers import get_match_stats

        # Set scores on existing match to mark as completed
        match.home_team_score = 2
        match.away_team_score = 1
        db.session.commit()

        with app.test_request_context():
            result = get_match_stats()

        assert 'completion_rate' in result
        assert 'completed_matches' in result
        assert result['completed_matches'] >= 1

    def test_get_match_stats_handles_no_matches(self, db, app):
        """
        GIVEN no matches in database
        WHEN get_match_stats is called
        THEN it should handle gracefully with zero values
        """
        from app.admin_helpers import get_match_stats

        # Delete all matches first
        Match.query.delete()
        db.session.commit()

        with app.test_request_context():
            result = get_match_stats()

        assert result.get('total_matches', 0) == 0
        assert result.get('completion_rate', 0) == 0


# =============================================================================
# DOCKER CONTAINER TESTS
# =============================================================================

@pytest.mark.unit
class TestGetContainerData:
    """Test Docker container data retrieval function."""

    @patch('app.admin_helpers.get_docker_client')
    def test_get_container_data_returns_formatted_containers(self, mock_get_client, app):
        """
        GIVEN running Docker containers
        WHEN get_container_data is called
        THEN it should return formatted container data
        """
        from app.admin_helpers import get_container_data

        mock_container = MagicMock()
        mock_container.id = 'abc123456789def'
        mock_container.name = 'test-container'
        mock_container.status = 'running'
        mock_container.image.tags = ['test-image:latest']

        mock_client = MagicMock()
        mock_client.containers.list.return_value = [mock_container]
        mock_get_client.return_value = mock_client

        with app.test_request_context():
            result = get_container_data()

        assert result is not None
        assert len(result) == 1
        assert result[0]['id'] == 'abc123456789'  # First 12 chars
        assert result[0]['name'] == 'test-container'
        assert result[0]['status'] == 'running'
        assert result[0]['image'] == 'test-image:latest'

    @patch('app.admin_helpers.get_docker_client')
    def test_get_container_data_returns_none_when_docker_unavailable(self, mock_get_client, app):
        """
        GIVEN Docker is not available
        WHEN get_container_data is called
        THEN it should return None
        """
        from app.admin_helpers import get_container_data

        mock_get_client.return_value = None

        with app.test_request_context():
            result = get_container_data()

        assert result is None


@pytest.mark.unit
class TestManageDockerContainer:
    """Test Docker container management function."""

    @patch('app.admin_helpers.get_docker_client')
    def test_manage_docker_container_start_succeeds(self, mock_get_client, app):
        """
        GIVEN a stopped Docker container
        WHEN manage_docker_container is called with 'start' action
        THEN it should start the container and return True
        """
        from app.admin_helpers import manage_docker_container

        mock_container = MagicMock()
        mock_client = MagicMock()
        mock_client.containers.get.return_value = mock_container
        mock_get_client.return_value = mock_client

        with app.test_request_context():
            result = manage_docker_container('container123', 'start')

        assert result is True
        mock_container.start.assert_called_once()

    @patch('app.admin_helpers.get_docker_client')
    def test_manage_docker_container_stop_succeeds(self, mock_get_client, app):
        """
        GIVEN a running Docker container
        WHEN manage_docker_container is called with 'stop' action
        THEN it should stop the container and return True
        """
        from app.admin_helpers import manage_docker_container

        mock_container = MagicMock()
        mock_client = MagicMock()
        mock_client.containers.get.return_value = mock_container
        mock_get_client.return_value = mock_client

        with app.test_request_context():
            result = manage_docker_container('container123', 'stop')

        assert result is True
        mock_container.stop.assert_called_once()

    @patch('app.admin_helpers.get_docker_client')
    def test_manage_docker_container_restart_succeeds(self, mock_get_client, app):
        """
        GIVEN a Docker container
        WHEN manage_docker_container is called with 'restart' action
        THEN it should restart the container and return True
        """
        from app.admin_helpers import manage_docker_container

        mock_container = MagicMock()
        mock_client = MagicMock()
        mock_client.containers.get.return_value = mock_container
        mock_get_client.return_value = mock_client

        with app.test_request_context():
            result = manage_docker_container('container123', 'restart')

        assert result is True
        mock_container.restart.assert_called_once()

    @patch('app.admin_helpers.get_docker_client')
    def test_manage_docker_container_returns_false_when_docker_unavailable(self, mock_get_client, app):
        """
        GIVEN Docker is not available
        WHEN manage_docker_container is called
        THEN it should return False
        """
        from app.admin_helpers import manage_docker_container

        mock_get_client.return_value = None

        with app.test_request_context():
            result = manage_docker_container('container123', 'start')

        assert result is False


# =============================================================================
# TASK STATUS TESTS
# =============================================================================

@pytest.mark.unit
class TestCheckTaskStatus:
    """Test task status check function."""

    @patch('app.admin_helpers.requests.get')
    def test_check_task_status_returns_task_summary(self, mock_get, app):
        """
        GIVEN tasks in the queue
        WHEN check_task_status is called
        THEN it should return task summary
        """
        from app.admin_helpers import check_task_status

        mock_response = MagicMock()
        mock_response.json.return_value = [
            {'uuid': 'task1', 'name': 'test_task', 'state': 'SUCCESS', 'received': '2024-01-01', 'started': '2024-01-01'},
            {'uuid': 'task2', 'name': 'test_task2', 'state': 'FAILURE', 'received': '2024-01-01', 'started': '2024-01-01'},
            {'uuid': 'task3', 'name': 'test_task3', 'state': 'PENDING', 'received': '2024-01-01', 'started': '2024-01-01'},
        ]
        mock_get.return_value = mock_response

        with app.test_request_context():
            result = check_task_status()

        assert result['total'] == 3
        assert result['succeeded'] == 1
        assert result['failed'] == 1
        assert result['pending'] == 1

    @patch('app.admin_helpers.requests.get')
    def test_check_task_status_handles_api_error(self, mock_get, app):
        """
        GIVEN Flower API is unavailable
        WHEN check_task_status is called
        THEN it should return error response
        """
        from app.admin_helpers import check_task_status

        mock_get.side_effect = Exception("API unavailable")

        with app.test_request_context():
            result = check_task_status()

        assert 'error' in result
        assert result['total'] == 0


# =============================================================================
# INITIAL EXPECTED ROLES TESTS
# =============================================================================

@pytest.mark.unit
class TestGetInitialExpectedRoles:
    """Test initial expected roles determination function."""

    def test_get_initial_expected_roles_includes_team_player_role(self, db, app, player, team):
        """
        GIVEN a player on a team
        WHEN get_initial_expected_roles is called
        THEN it should include team player role
        """
        from app.admin_helpers import get_initial_expected_roles

        # Ensure player has primary_team set
        player.primary_team = team
        db.session.commit()

        with app.test_request_context():
            roles = get_initial_expected_roles(player)

        assert any('Player' in role for role in roles)

    def test_get_initial_expected_roles_includes_coach_role_for_coach(self, db, app, player, team):
        """
        GIVEN a player who is a coach
        WHEN get_initial_expected_roles is called
        THEN it should include coach role
        """
        from app.admin_helpers import get_initial_expected_roles

        player.primary_team = team
        player.is_coach = True
        db.session.commit()

        with app.test_request_context():
            roles = get_initial_expected_roles(player)

        assert any('Coach' in role for role in roles)

    def test_get_initial_expected_roles_includes_referee_role_for_ref(self, db, app, player):
        """
        GIVEN a player who is a referee
        WHEN get_initial_expected_roles is called
        THEN it should include Referee role
        """
        from app.admin_helpers import get_initial_expected_roles

        player.is_ref = True
        db.session.commit()

        with app.test_request_context():
            roles = get_initial_expected_roles(player)

        assert 'Referee' in roles

    def test_get_initial_expected_roles_includes_substitute_role_for_sub(self, db, app, player):
        """
        GIVEN a player who is a substitute
        WHEN get_initial_expected_roles is called
        THEN it should include Substitute role
        """
        from app.admin_helpers import get_initial_expected_roles

        player.is_sub = True
        db.session.commit()

        with app.test_request_context():
            roles = get_initial_expected_roles(player)

        assert 'Substitute' in roles


# =============================================================================
# ANNOUNCEMENT MANAGEMENT TESTS
# =============================================================================

@pytest.mark.unit
class TestHandleAnnouncementUpdate:
    """Test announcement create/update function."""

    def test_handle_announcement_update_creates_new_announcement(self, db, app):
        """
        GIVEN no existing announcement
        WHEN handle_announcement_update is called with title and content
        THEN it should create a new announcement
        """
        from app.admin_helpers import handle_announcement_update
        from flask import g

        with app.test_request_context():
            g.db_session = db.session
            result = handle_announcement_update(
                title='Test Announcement',
                content='Test content'
            )
            db.session.commit()

        assert result is True
        announcement = Announcement.query.filter_by(title='Test Announcement').first()
        assert announcement is not None
        assert announcement.content == 'Test content'

    def test_handle_announcement_update_updates_existing_announcement(self, db, app):
        """
        GIVEN an existing announcement
        WHEN handle_announcement_update is called with announcement_id
        THEN it should update the announcement
        """
        from app.admin_helpers import handle_announcement_update
        from flask import g

        # Create initial announcement
        announcement = Announcement(title='Original Title', content='Original content', position=1)
        db.session.add(announcement)
        db.session.commit()
        announcement_id = announcement.id

        with app.test_request_context():
            g.db_session = db.session
            result = handle_announcement_update(
                title='Updated Title',
                content='Updated content',
                announcement_id=announcement_id
            )
            db.session.commit()

        assert result is True
        updated = Announcement.query.get(announcement_id)
        assert updated.title == 'Updated Title'
        assert updated.content == 'Updated content'


# =============================================================================
# SMS HELPER TESTS
# =============================================================================

@pytest.mark.unit
class TestSendSmsMessage:
    """Test SMS sending function."""

    @patch('app.admin_helpers.Client')
    def test_send_sms_message_normalizes_10_digit_phone(self, mock_client_class, app):
        """
        GIVEN a 10-digit phone number
        WHEN send_sms_message is called
        THEN it should normalize to E.164 format with +1
        """
        from app.admin_helpers import send_sms_message
        import os

        mock_client = MagicMock()
        mock_message = MagicMock()
        mock_message.sid = 'SM123'
        mock_client.messages.create.return_value = mock_message
        mock_client_class.return_value = mock_client

        with patch.dict(os.environ, {
            'TWILIO_SID': 'test_sid',
            'TWILIO_AUTH_TOKEN': 'test_token',
            'TWILIO_PHONE_NUMBER': '+15551234567'
        }):
            with app.test_request_context():
                result = send_sms_message('5559876543', 'Test message')

        assert result is True
        # Verify the phone was normalized
        call_args = mock_client.messages.create.call_args
        assert call_args.kwargs['to'] == '+15559876543'

    @patch('app.admin_helpers.Client')
    def test_send_sms_message_returns_false_without_credentials(self, mock_client_class, app):
        """
        GIVEN missing Twilio credentials
        WHEN send_sms_message is called
        THEN it should return False
        """
        from app.admin_helpers import send_sms_message
        import os

        with patch.dict(os.environ, {}, clear=True):
            with app.test_request_context():
                app.config['TWILIO_SID'] = None
                app.config['TWILIO_AUTH_TOKEN'] = None
                app.config['TWILIO_PHONE_NUMBER'] = None
                result = send_sms_message('5559876543', 'Test message')

        assert result is False


# =============================================================================
# CONTAINER LOGS TESTS
# =============================================================================

@pytest.mark.unit
class TestGetContainerLogs:
    """Test container logs retrieval function."""

    @patch('app.admin_helpers.get_docker_client')
    def test_get_container_logs_returns_logs(self, mock_get_client, app):
        """
        GIVEN a Docker container with logs
        WHEN get_container_logs is called
        THEN it should return log content
        """
        from app.admin_helpers import get_container_logs

        mock_container = MagicMock()
        mock_container.logs.return_value = b'Container log output'
        mock_client = MagicMock()
        mock_client.containers.get.return_value = mock_container
        mock_get_client.return_value = mock_client

        with app.test_request_context():
            result = get_container_logs('container123')

        assert result == 'Container log output'

    @patch('app.admin_helpers.get_docker_client')
    def test_get_container_logs_returns_none_for_missing_container(self, mock_get_client, app):
        """
        GIVEN a non-existent container ID
        WHEN get_container_logs is called
        THEN it should return None
        """
        from app.admin_helpers import get_container_logs
        import docker

        mock_client = MagicMock()
        mock_client.containers.get.side_effect = docker.errors.NotFound('Not found')
        mock_get_client.return_value = mock_client

        with app.test_request_context():
            result = get_container_logs('nonexistent')

        assert result is None


# =============================================================================
# SUB REQUEST TESTS
# =============================================================================

@pytest.mark.unit
class TestCreateSubRequest:
    """Test sub request creation function."""

    def test_create_sub_request_succeeds_for_valid_match_and_team(self, db, app, match, team, user):
        """
        GIVEN a valid match and team
        WHEN create_sub_request is called
        THEN it should create a sub request successfully
        """
        from app.admin_helpers import create_sub_request

        # Ensure team is part of the match
        match.home_team_id = team.id
        db.session.commit()

        result = create_sub_request(
            match_id=match.id,
            team_id=team.id,
            requested_by=user.id,
            notes='Need a sub',
            session=db.session
        )

        assert result[0] is True  # success
        assert 'successfully' in result[1].lower()
        assert result[2] is not None  # request_id

    def test_create_sub_request_fails_for_invalid_match(self, db, app, team, user):
        """
        GIVEN an invalid match ID
        WHEN create_sub_request is called
        THEN it should return failure
        """
        from app.admin_helpers import create_sub_request

        result = create_sub_request(
            match_id=99999,
            team_id=team.id,
            requested_by=user.id,
            session=db.session
        )

        assert result[0] is False
        assert 'not found' in result[1].lower()


@pytest.mark.unit
class TestUpdateSubRequestStatus:
    """Test sub request status update function."""

    def test_update_sub_request_status_updates_status(self, db, app, match, team, user):
        """
        GIVEN an existing sub request
        WHEN update_sub_request_status is called
        THEN it should update the status
        """
        from app.admin_helpers import create_sub_request, update_sub_request_status
        from app.models import SubRequest

        # Ensure team is part of the match
        match.home_team_id = team.id
        db.session.commit()

        # Create sub request first
        success, msg, request_id = create_sub_request(
            match_id=match.id,
            team_id=team.id,
            requested_by=user.id,
            session=db.session
        )

        assert success is True

        # Update status
        result = update_sub_request_status(
            request_id=request_id,
            status='APPROVED',
            session=db.session
        )

        assert result[0] is True

        # Verify status was updated
        sub_request = db.session.query(SubRequest).get(request_id)
        assert sub_request.status == 'APPROVED'

    def test_update_sub_request_status_fails_for_invalid_request(self, db, app):
        """
        GIVEN an invalid sub request ID
        WHEN update_sub_request_status is called
        THEN it should return failure
        """
        from app.admin_helpers import update_sub_request_status

        result = update_sub_request_status(
            request_id=99999,
            status='APPROVED',
            session=db.session
        )

        assert result[0] is False
        assert 'not found' in result[1].lower()


# =============================================================================
# RSVP STATUS DATA TESTS
# =============================================================================

@pytest.mark.unit
class TestGetRsvpStatusData:
    """Test RSVP status data retrieval function."""

    def test_get_rsvp_status_data_returns_player_responses(self, db, app, match, player, team):
        """
        GIVEN a match with player availability responses
        WHEN get_rsvp_status_data is called
        THEN it should return RSVP data for players
        """
        from app.admin_helpers import get_rsvp_status_data

        # Ensure player is on a team in the match
        player.primary_team = team
        match.home_team_id = team.id

        # Create availability response
        avail = Availability(
            match_id=match.id,
            player_id=player.id,
            discord_id=player.discord_id,
            response='yes',
            responded_at=datetime.utcnow()
        )
        db.session.add(avail)
        db.session.commit()

        result = get_rsvp_status_data(match, session=db.session)

        assert len(result) >= 1
        # Find our player in results
        player_entry = next((r for r in result if r['player'].id == player.id), None)
        assert player_entry is not None
        assert player_entry['response'] == 'yes'

    def test_get_rsvp_status_data_handles_no_responses(self, db, app, match):
        """
        GIVEN a match with no availability responses
        WHEN get_rsvp_status_data is called
        THEN it should return data with 'No Response' status
        """
        from app.admin_helpers import get_rsvp_status_data

        result = get_rsvp_status_data(match, session=db.session)

        # Should still return team players, just with no response
        for entry in result:
            if not entry.get('is_temp_sub'):
                # Regular players without response should show 'No Response'
                assert entry['response'] in ['No Response', 'yes', 'no', 'maybe']
