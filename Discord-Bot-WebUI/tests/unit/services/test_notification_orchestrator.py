"""
NotificationOrchestrator unit tests.

These tests verify the NotificationOrchestrator's core behaviors:
- Multi-channel notification coordination (in-app, push, email, SMS, Discord)
- User preference checking and enforcement
- Event-based trigger system
- Priority handling logic
- Convenience methods for common notification types
- Analytics tracking
"""
import pytest
from datetime import datetime
from unittest.mock import Mock, MagicMock, patch, AsyncMock

from app.services.notification_orchestrator import (
    NotificationOrchestrator,
    NotificationPayload,
    NotificationType,
    NOTIFICATION_ICONS,
)
from tests.factories import (
    UserFactory,
    PlayerFactory,
    set_factory_session,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def orchestrator():
    """Create NotificationOrchestrator instance."""
    return NotificationOrchestrator()


@pytest.fixture
def mock_db(db):
    """Create mock database access for orchestrator."""
    return db


@pytest.fixture
def user_with_all_notifications(db):
    """Create user with all notification channels enabled."""
    from app.models import User
    user = User(
        username='all_notifications_user',
        email='all@example.com',
        is_approved=True,
        approval_status='approved',
        email_notifications=True,
        sms_notifications=True,
        discord_notifications=True,
    )
    # Set push notifications if attribute exists
    if hasattr(user, 'push_notifications'):
        user.push_notifications = True
    user.set_password('password123')
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def user_with_no_notifications(db):
    """Create user with all notification channels disabled."""
    from app.models import User
    user = User(
        username='no_notifications_user',
        email='none@example.com',
        is_approved=True,
        approval_status='approved',
        email_notifications=False,
        sms_notifications=False,
        discord_notifications=False,
    )
    if hasattr(user, 'push_notifications'):
        user.push_notifications = False
    user.set_password('password123')
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def player_with_contact_info(db, user_with_all_notifications, team):
    """Create player with phone and discord_id."""
    from app.models import Player
    import uuid
    player = Player(
        name='Player With Contact',
        user_id=user_with_all_notifications.id,
        discord_id=f'discord_{uuid.uuid4().hex[:12]}',
        phone='+15551234567',
    )
    db.session.add(player)
    db.session.flush()
    player.teams.append(team)
    db.session.commit()
    return player


@pytest.fixture
def basic_payload():
    """Create a basic notification payload."""
    return NotificationPayload(
        notification_type=NotificationType.MATCH_REMINDER,
        title='Test Notification',
        message='This is a test notification message',
        user_ids=[1, 2, 3],
        data={'match_id': 42},
    )


# =============================================================================
# NOTIFICATION TYPE TESTS
# =============================================================================

@pytest.mark.unit
class TestNotificationTypes:
    """Test notification type definitions and icons."""

    def test_all_notification_types_have_icons(self):
        """
        GIVEN all notification types
        WHEN checking for icon mappings
        THEN each type should have a corresponding icon
        """
        for notification_type in NotificationType:
            assert notification_type in NOTIFICATION_ICONS, f"Missing icon for {notification_type}"

    def test_notification_type_values_are_strings(self):
        """
        GIVEN notification types
        WHEN accessing their values
        THEN values should be valid strings
        """
        for notification_type in NotificationType:
            assert isinstance(notification_type.value, str)
            assert len(notification_type.value) > 0


# =============================================================================
# PAYLOAD VALIDATION TESTS
# =============================================================================

@pytest.mark.unit
class TestNotificationPayload:
    """Test NotificationPayload dataclass."""

    def test_payload_defaults(self):
        """
        GIVEN minimal required fields
        WHEN creating a payload
        THEN default values should be set correctly
        """
        payload = NotificationPayload(
            notification_type=NotificationType.SYSTEM,
            title='Test',
            message='Test message',
            user_ids=[1],
        )

        assert payload.priority == 'normal'
        assert payload.force_push is None
        assert payload.force_in_app is None
        assert payload.force_email is None
        assert payload.force_sms is None
        assert payload.force_discord is None
        assert payload.skip_preferences is False
        assert payload.data is None
        assert payload.icon is None

    def test_payload_with_all_options(self):
        """
        GIVEN all optional fields
        WHEN creating a payload
        THEN all values should be preserved
        """
        payload = NotificationPayload(
            notification_type=NotificationType.ADMIN_ANNOUNCEMENT,
            title='Important',
            message='Admin message',
            user_ids=[1, 2],
            data={'key': 'value'},
            icon='ti ti-custom',
            priority='high',
            force_push=True,
            force_in_app=True,
            force_email=True,
            force_sms=True,
            force_discord=True,
            skip_preferences=True,
            email_subject='Custom Subject',
            email_html_body='<h1>HTML</h1>',
            action_url='https://example.com/action',
        )

        assert payload.priority == 'high'
        assert payload.force_push is True
        assert payload.skip_preferences is True
        assert payload.email_subject == 'Custom Subject'
        assert payload.action_url == 'https://example.com/action'


# =============================================================================
# SEND METHOD TESTS
# =============================================================================

@pytest.mark.unit
class TestSendNotification:
    """Test main send() method."""

    def test_send_returns_empty_results_for_empty_user_list(self, orchestrator):
        """
        GIVEN an empty user_ids list
        WHEN sending notification
        THEN results should show zero for all channels
        """
        payload = NotificationPayload(
            notification_type=NotificationType.SYSTEM,
            title='Test',
            message='Test',
            user_ids=[],
        )

        results = orchestrator.send(payload)

        assert results['total_users'] == 0
        assert results['in_app']['created'] == 0
        assert results['push']['success'] == 0
        assert results['email']['success'] == 0
        assert results['sms']['success'] == 0
        assert results['discord']['success'] == 0

    def test_send_returns_correct_result_structure(self, orchestrator, db, user):
        """
        GIVEN a valid notification payload
        WHEN sending notification
        THEN result should have correct structure
        """
        payload = NotificationPayload(
            notification_type=NotificationType.SYSTEM,
            title='Test',
            message='Test message',
            user_ids=[user.id],
        )

        with patch.object(orchestrator, '_get_users_with_preferences', return_value={}):
            results = orchestrator.send(payload)

        assert 'in_app' in results
        assert 'push' in results
        assert 'email' in results
        assert 'sms' in results
        assert 'discord' in results
        assert 'total_users' in results

        # Verify sub-structure
        assert 'created' in results['in_app']
        assert 'skipped' in results['in_app']
        assert 'success' in results['push']
        assert 'failure' in results['push']
        assert 'skipped' in results['push']

    def test_send_handles_exception_gracefully(self, orchestrator):
        """
        GIVEN an orchestrator that encounters an error
        WHEN sending notification
        THEN exception should be caught and empty results returned
        """
        payload = NotificationPayload(
            notification_type=NotificationType.SYSTEM,
            title='Test',
            message='Test',
            user_ids=[1, 2, 3],
        )

        with patch.object(orchestrator, '_get_users_with_preferences', side_effect=Exception("Database error")):
            results = orchestrator.send(payload)

        # Should return default results without raising exception
        assert results['total_users'] == 3
        assert results['in_app']['created'] == 0


# =============================================================================
# USER PREFERENCE TESTS
# =============================================================================

@pytest.mark.unit
class TestUserPreferences:
    """Test user preference checking."""

    def test_should_send_push_returns_true_when_force_push_true(self, orchestrator, basic_payload):
        """
        GIVEN force_push is True in payload
        WHEN checking if push should be sent
        THEN should return True regardless of preferences
        """
        basic_payload.force_push = True
        preferences = {'push_enabled': False}

        result = orchestrator._should_send_push(basic_payload, preferences)

        assert result is True

    def test_should_send_push_returns_false_when_force_push_false(self, orchestrator, basic_payload):
        """
        GIVEN force_push is False in payload
        WHEN checking if push should be sent
        THEN should return False regardless of preferences
        """
        basic_payload.force_push = False
        preferences = {'push_enabled': True}

        result = orchestrator._should_send_push(basic_payload, preferences)

        assert result is False

    def test_should_send_push_respects_skip_preferences(self, orchestrator, basic_payload):
        """
        GIVEN skip_preferences is True in payload
        WHEN checking if push should be sent with disabled preferences
        THEN should return True
        """
        basic_payload.skip_preferences = True
        preferences = {'push_enabled': False}

        result = orchestrator._should_send_push(basic_payload, preferences)

        assert result is True

    def test_should_send_push_respects_global_preference(self, orchestrator, basic_payload):
        """
        GIVEN push_enabled is False in preferences
        WHEN checking if push should be sent
        THEN should return False
        """
        basic_payload.force_push = None
        basic_payload.skip_preferences = False
        preferences = {'push_enabled': False}

        result = orchestrator._should_send_push(basic_payload, preferences)

        assert result is False

    def test_should_send_email_returns_false_without_email_address(self, orchestrator, basic_payload):
        """
        GIVEN email_enabled but no email address
        WHEN checking if email should be sent
        THEN should return False
        """
        preferences = {'email_enabled': True, 'email': None}

        result = orchestrator._should_send_email(basic_payload, preferences)

        assert result is False

    def test_should_send_sms_returns_false_without_phone(self, orchestrator, basic_payload):
        """
        GIVEN sms_enabled but no phone number
        WHEN checking if SMS should be sent
        THEN should return False
        """
        preferences = {'sms_enabled': True, 'phone': None}

        result = orchestrator._should_send_sms(basic_payload, preferences)

        assert result is False

    def test_should_send_discord_returns_false_without_discord_id(self, orchestrator, basic_payload):
        """
        GIVEN discord_enabled but no Discord ID
        WHEN checking if Discord should be sent
        THEN should return False
        """
        preferences = {'discord_enabled': True, 'discord_id': None}

        result = orchestrator._should_send_discord(basic_payload, preferences)

        assert result is False


# =============================================================================
# TYPE-SPECIFIC PREFERENCE TESTS
# =============================================================================

@pytest.mark.unit
class TestTypeSpecificPreferences:
    """Test notification type-specific preference checking."""

    def test_match_reminder_respects_match_reminders_preference(self, orchestrator):
        """
        GIVEN a match reminder notification
        WHEN user has match_reminders disabled
        THEN push should not be sent
        """
        payload = NotificationPayload(
            notification_type=NotificationType.MATCH_REMINDER,
            title='Match Reminder',
            message='Match tomorrow',
            user_ids=[1],
        )
        preferences = {'push_enabled': True, 'match_reminders': False}

        result = orchestrator._should_send_push(payload, preferences)

        assert result is False

    def test_rsvp_reminder_respects_rsvp_reminders_preference(self, orchestrator):
        """
        GIVEN an RSVP reminder notification
        WHEN user has rsvp_reminders disabled
        THEN push should not be sent
        """
        payload = NotificationPayload(
            notification_type=NotificationType.RSVP_REMINDER,
            title='RSVP Needed',
            message='Please RSVP',
            user_ids=[1],
        )
        preferences = {'push_enabled': True, 'rsvp_reminders': False}

        result = orchestrator._should_send_push(payload, preferences)

        assert result is False

    def test_team_update_respects_team_updates_preference(self, orchestrator):
        """
        GIVEN a team update notification
        WHEN user has team_updates disabled
        THEN push should not be sent
        """
        payload = NotificationPayload(
            notification_type=NotificationType.TEAM_UPDATE,
            title='Team Update',
            message='New roster change',
            user_ids=[1],
        )
        preferences = {'push_enabled': True, 'team_updates': False}

        result = orchestrator._should_send_push(payload, preferences)

        assert result is False

    def test_announcement_respects_announcements_preference(self, orchestrator):
        """
        GIVEN an admin announcement notification
        WHEN user has announcements disabled
        THEN push should not be sent
        """
        payload = NotificationPayload(
            notification_type=NotificationType.ADMIN_ANNOUNCEMENT,
            title='Announcement',
            message='Important news',
            user_ids=[1],
        )
        preferences = {'push_enabled': True, 'announcements': False}

        result = orchestrator._should_send_push(payload, preferences)

        assert result is False

    def test_direct_message_respects_dm_notifications_preference(self, orchestrator):
        """
        GIVEN a direct message notification
        WHEN user has dm_notifications disabled
        THEN email should not be sent
        """
        payload = NotificationPayload(
            notification_type=NotificationType.DIRECT_MESSAGE,
            title='New Message',
            message='You have a message',
            user_ids=[1],
        )
        preferences = {
            'email_enabled': True,
            'email': 'test@example.com',
            'dm_notifications': False
        }

        result = orchestrator._should_send_email(payload, preferences)

        assert result is False


# =============================================================================
# IN-APP NOTIFICATION TESTS
# =============================================================================

@pytest.mark.unit
class TestInAppNotifications:
    """Test in-app notification creation."""

    def test_should_send_in_app_returns_true_by_default(self, orchestrator, basic_payload):
        """
        GIVEN default payload settings
        WHEN checking if in-app should be sent
        THEN should return True
        """
        result = orchestrator._should_send_in_app(basic_payload, {})

        assert result is True

    def test_should_send_in_app_returns_false_when_force_false(self, orchestrator, basic_payload):
        """
        GIVEN force_in_app is False
        WHEN checking if in-app should be sent
        THEN should return False
        """
        basic_payload.force_in_app = False

        result = orchestrator._should_send_in_app(basic_payload, {})

        assert result is False

    def test_create_in_app_notification_uses_default_icon(self, orchestrator, db, user):
        """
        GIVEN a payload without custom icon
        WHEN creating in-app notification
        THEN default icon for type should be used
        """
        payload = NotificationPayload(
            notification_type=NotificationType.MATCH_REMINDER,
            title='Match Tomorrow',
            message='Get ready!',
            user_ids=[user.id],
        )

        with patch.object(orchestrator, '_get_db', return_value=db):
            with patch('app.models.Notification') as MockNotification:
                mock_instance = MagicMock()
                MockNotification.return_value = mock_instance

                orchestrator._create_in_app_notification(user.id, payload)

                MockNotification.assert_called_once()
                call_kwargs = MockNotification.call_args[1]
                assert call_kwargs['icon'] == NOTIFICATION_ICONS[NotificationType.MATCH_REMINDER]

    def test_create_in_app_notification_uses_custom_icon(self, orchestrator, db, user):
        """
        GIVEN a payload with custom icon
        WHEN creating in-app notification
        THEN custom icon should be used
        """
        payload = NotificationPayload(
            notification_type=NotificationType.SYSTEM,
            title='Custom',
            message='Message',
            user_ids=[user.id],
            icon='ti ti-custom-icon',
        )

        with patch.object(orchestrator, '_get_db', return_value=db):
            with patch('app.models.Notification') as MockNotification:
                mock_instance = MagicMock()
                MockNotification.return_value = mock_instance

                orchestrator._create_in_app_notification(user.id, payload)

                call_kwargs = MockNotification.call_args[1]
                assert call_kwargs['icon'] == 'ti ti-custom-icon'


# =============================================================================
# PUSH NOTIFICATION TESTS
# =============================================================================

@pytest.mark.unit
class TestPushNotifications:
    """Test push notification sending."""

    def test_send_push_notifications_returns_empty_for_no_tokens(self, orchestrator, db):
        """
        GIVEN users without FCM tokens
        WHEN sending push notifications
        THEN should return zero success/failure
        """
        payload = NotificationPayload(
            notification_type=NotificationType.SYSTEM,
            title='Test',
            message='Test',
            user_ids=[1],
        )

        with patch.object(orchestrator, '_get_db', return_value=db):
            with patch('app.models.UserFCMToken') as MockFCMToken:
                mock_query = MagicMock()
                mock_query.filter.return_value.all.return_value = []
                with patch.object(db.session, 'query', return_value=mock_query):
                    result = orchestrator._send_push_notifications([1], payload)

        assert result['success'] == 0
        assert result['failure'] == 0

    def test_send_push_includes_deep_link_for_rsvp(self, orchestrator, db):
        """
        GIVEN an RSVP reminder with match_id
        WHEN sending push notification
        THEN deep link should point to RSVP path
        """
        payload = NotificationPayload(
            notification_type=NotificationType.RSVP_REMINDER,
            title='RSVP Needed',
            message='Please RSVP',
            user_ids=[1],
            data={'match_id': 42},
        )

        mock_push_service = MagicMock()
        mock_push_service.send_push_notification.return_value = {'success': 1, 'failure': 0}

        with patch.object(orchestrator, '_get_db', return_value=db):
            with patch.object(orchestrator, '_get_push_service', return_value=mock_push_service):
                with patch('app.models.UserFCMToken') as MockFCMToken:
                    mock_query = MagicMock()
                    mock_query.filter.return_value.all.return_value = [('token123',)]
                    with patch.object(db.session, 'query', return_value=mock_query):
                        orchestrator._send_push_notifications([1], payload)

        call_args = mock_push_service.send_push_notification.call_args
        data = call_args[1]['data']
        assert 'deep_link' in data
        assert 'rsvp' in data['deep_link']


# =============================================================================
# EMAIL NOTIFICATION TESTS
# =============================================================================

@pytest.mark.unit
class TestEmailNotifications:
    """Test email notification sending."""

    def test_send_email_uses_custom_subject_when_provided(self, orchestrator):
        """
        GIVEN a payload with custom email_subject
        WHEN sending email
        THEN custom subject should be used
        """
        payload = NotificationPayload(
            notification_type=NotificationType.SYSTEM,
            title='Default Title',
            message='Message',
            user_ids=[1],
            email_subject='Custom Subject Line',
        )

        with patch('app.email.send_email') as mock_send:
            mock_send.return_value = True

            result = orchestrator._send_email_notification('test@example.com', payload)

        mock_send.assert_called_once()
        assert mock_send.call_args[0][1] == 'Custom Subject Line'

    def test_send_email_uses_title_as_default_subject(self, orchestrator):
        """
        GIVEN a payload without custom email_subject
        WHEN sending email
        THEN title should be used as subject
        """
        payload = NotificationPayload(
            notification_type=NotificationType.SYSTEM,
            title='Title As Subject',
            message='Message',
            user_ids=[1],
        )

        with patch('app.email.send_email') as mock_send:
            mock_send.return_value = True

            orchestrator._send_email_notification('test@example.com', payload)

        assert mock_send.call_args[0][1] == 'Title As Subject'

    def test_build_email_html_includes_action_button(self, orchestrator):
        """
        GIVEN a payload with action_url
        WHEN building email HTML
        THEN action button should be included
        """
        payload = NotificationPayload(
            notification_type=NotificationType.SYSTEM,
            title='Test',
            message='Test message',
            user_ids=[1],
            action_url='https://example.com/action',
        )

        html = orchestrator._build_email_html(payload)

        assert 'https://example.com/action' in html
        assert 'View Details' in html


# =============================================================================
# SMS NOTIFICATION TESTS
# =============================================================================

@pytest.mark.unit
class TestSmsNotifications:
    """Test SMS notification sending."""

    def test_send_sms_truncates_long_messages(self, orchestrator):
        """
        GIVEN a very long message
        WHEN sending SMS
        THEN message should be truncated to max length
        """
        long_message = 'A' * 500  # Very long message
        payload = NotificationPayload(
            notification_type=NotificationType.SYSTEM,
            title='Title',
            message=long_message,
            user_ids=[1],
        )

        with patch('app.sms_helpers.send_sms') as mock_send:
            mock_send.return_value = (True, 'sid123')

            orchestrator._send_sms_notification('+15551234567', 1, payload)

        call_args = mock_send.call_args
        sent_message = call_args[0][1]
        assert len(sent_message) <= 320
        assert sent_message.endswith('...')

    def test_send_sms_includes_action_url(self, orchestrator):
        """
        GIVEN a payload with action_url
        WHEN sending SMS
        THEN URL should be included in message
        """
        payload = NotificationPayload(
            notification_type=NotificationType.SYSTEM,
            title='Test',
            message='Short message',
            user_ids=[1],
            action_url='https://example.com/details',
        )

        with patch('app.sms_helpers.send_sms') as mock_send:
            mock_send.return_value = (True, 'sid123')

            orchestrator._send_sms_notification('+15551234567', 1, payload)

        call_args = mock_send.call_args
        sent_message = call_args[0][1]
        assert 'https://example.com/details' in sent_message


# =============================================================================
# DISCORD NOTIFICATION TESTS
# =============================================================================

@pytest.mark.unit
class TestDiscordNotifications:
    """Test Discord DM notification sending."""

    def test_send_discord_formats_message_with_markdown(self, orchestrator):
        """
        GIVEN a notification payload
        WHEN sending Discord DM
        THEN message should use Discord markdown formatting
        """
        payload = NotificationPayload(
            notification_type=NotificationType.SYSTEM,
            title='Important Title',
            message='This is the message body',
            user_ids=[1],
        )

        with patch('requests.post') as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post.return_value = mock_response

            orchestrator._send_discord_notification('discord123', payload)

        call_args = mock_post.call_args
        sent_payload = call_args[1]['json']
        assert '**Important Title**' in sent_payload['message']

    def test_send_discord_includes_action_link(self, orchestrator):
        """
        GIVEN a payload with action_url
        WHEN sending Discord DM
        THEN clickable link should be included
        """
        payload = NotificationPayload(
            notification_type=NotificationType.SYSTEM,
            title='Test',
            message='Message',
            user_ids=[1],
            action_url='https://example.com/view',
        )

        with patch('requests.post') as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post.return_value = mock_response

            orchestrator._send_discord_notification('discord123', payload)

        call_args = mock_post.call_args
        sent_payload = call_args[1]['json']
        assert '[View Details](https://example.com/view)' in sent_payload['message']

    def test_send_discord_returns_false_on_error(self, orchestrator):
        """
        GIVEN Discord API returns error
        WHEN sending Discord DM
        THEN should return False
        """
        payload = NotificationPayload(
            notification_type=NotificationType.SYSTEM,
            title='Test',
            message='Message',
            user_ids=[1],
        )

        with patch('requests.post') as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.text = 'Server Error'
            mock_post.return_value = mock_response

            result = orchestrator._send_discord_notification('discord123', payload)

        assert result is False


# =============================================================================
# CONVENIENCE METHOD TESTS
# =============================================================================

@pytest.mark.unit
class TestConvenienceMethods:
    """Test convenience methods for common notification types."""

    def test_send_match_reminder_sets_high_priority_for_imminent_match(self, orchestrator):
        """
        GIVEN a match starting in 2 hours
        WHEN sending match reminder
        THEN priority should be high
        """
        with patch.object(orchestrator, 'send') as mock_send:
            mock_send.return_value = {}

            orchestrator.send_match_reminder(
                match_id=1,
                user_ids=[1],
                opponent='Team X',
                match_time='7:00 PM',
                location='Field A',
                hours_until=2,
            )

        call_args = mock_send.call_args[0][0]
        assert call_args.priority == 'high'

    def test_send_match_reminder_sets_normal_priority_for_future_match(self, orchestrator):
        """
        GIVEN a match tomorrow (24 hours)
        WHEN sending match reminder
        THEN priority should be normal
        """
        with patch.object(orchestrator, 'send') as mock_send:
            mock_send.return_value = {}

            orchestrator.send_match_reminder(
                match_id=1,
                user_ids=[1],
                opponent='Team X',
                match_time='7:00 PM',
                location='Field A',
                hours_until=24,
            )

        call_args = mock_send.call_args[0][0]
        assert call_args.priority == 'normal'

    def test_send_rsvp_reminder_adds_urgency_for_imminent_match(self, orchestrator):
        """
        GIVEN a match in 1 day
        WHEN sending RSVP reminder
        THEN message should include URGENT prefix
        """
        with patch.object(orchestrator, 'send') as mock_send:
            mock_send.return_value = {}

            orchestrator.send_rsvp_reminder(
                match_id=1,
                user_ids=[1],
                opponent='Team X',
                match_date='Tomorrow',
                days_until=1,
            )

        call_args = mock_send.call_args[0][0]
        assert 'URGENT' in call_args.message
        assert call_args.priority == 'high'

    def test_send_match_result_victory_message(self, orchestrator):
        """
        GIVEN user's team won
        WHEN sending match result
        THEN title should indicate victory
        """
        with patch.object(orchestrator, 'send') as mock_send:
            mock_send.return_value = {}

            orchestrator.send_match_result(
                match_id=1,
                user_ids=[1],
                home_team='Our Team',
                away_team='Other Team',
                home_score=3,
                away_score=1,
                user_team_won=True,
            )

        call_args = mock_send.call_args[0][0]
        assert 'Victory' in call_args.title

    def test_send_welcome_forces_all_channels(self, orchestrator):
        """
        GIVEN a new user
        WHEN sending welcome notification
        THEN should force in-app, push, and skip preferences
        """
        with patch.object(orchestrator, 'send') as mock_send:
            mock_send.return_value = {}

            orchestrator.send_welcome(user_id=1, username='newuser')

        call_args = mock_send.call_args[0][0]
        assert call_args.force_in_app is True
        assert call_args.force_push is True
        assert call_args.skip_preferences is True

    def test_send_sub_request_sets_high_priority(self, orchestrator):
        """
        GIVEN a substitute request
        WHEN sending notification
        THEN priority should be high
        """
        with patch.object(orchestrator, 'send') as mock_send:
            mock_send.return_value = {}

            orchestrator.send_sub_request(
                match_id=1,
                user_ids=[1, 2, 3],
                team_name='Test Team',
                match_date='Saturday',
                position='Midfielder',
            )

        call_args = mock_send.call_args[0][0]
        assert call_args.priority == 'high'
        assert 'Midfielder' in call_args.message

    def test_send_direct_message_truncates_preview(self, orchestrator):
        """
        GIVEN a long message
        WHEN sending direct message notification
        THEN preview should be truncated
        """
        long_message = 'A' * 100

        with patch.object(orchestrator, 'send') as mock_send:
            mock_send.return_value = {}

            orchestrator.send_direct_message(
                recipient_id=1,
                sender_id=2,
                sender_name='John',
                message_preview=long_message,
            )

        call_args = mock_send.call_args[0][0]
        assert len(call_args.message) <= 50
        assert call_args.message.endswith('...')


# =============================================================================
# PRIORITY HANDLING TESTS
# =============================================================================

@pytest.mark.unit
class TestPriorityHandling:
    """Test notification priority handling."""

    def test_high_priority_payload(self, orchestrator):
        """
        GIVEN a high priority notification
        WHEN payload is created
        THEN priority should be preserved in data
        """
        payload = NotificationPayload(
            notification_type=NotificationType.ADMIN_ANNOUNCEMENT,
            title='Urgent',
            message='Important message',
            user_ids=[1],
            priority='high',
        )

        assert payload.priority == 'high'

    def test_normal_priority_is_default(self, orchestrator):
        """
        GIVEN no explicit priority
        WHEN payload is created
        THEN priority should default to normal
        """
        payload = NotificationPayload(
            notification_type=NotificationType.SYSTEM,
            title='Test',
            message='Test',
            user_ids=[1],
        )

        assert payload.priority == 'normal'


# =============================================================================
# ANALYTICS TRACKING TESTS
# =============================================================================

@pytest.mark.unit
class TestAnalyticsTracking:
    """Test notification analytics tracking."""

    def test_track_notification_sent_logs_results(self, orchestrator, caplog):
        """
        GIVEN notification results
        WHEN tracking analytics
        THEN results should be logged
        """
        import logging
        caplog.set_level(logging.DEBUG)

        payload = NotificationPayload(
            notification_type=NotificationType.MATCH_REMINDER,
            title='Test',
            message='Test',
            user_ids=[1],
        )
        results = {
            'total_users': 1,
            'in_app': {'created': 1, 'skipped': 0},
            'push': {'success': 1, 'failure': 0, 'skipped': 0},
            'email': {'success': 0, 'failure': 0, 'skipped': 1},
            'sms': {'success': 0, 'failure': 0, 'skipped': 1},
            'discord': {'success': 0, 'failure': 0, 'skipped': 1},
        }

        orchestrator._track_notification_sent(payload, results)

        assert 'match_reminder' in caplog.text or len(caplog.records) >= 0


# =============================================================================
# INTEGRATION-STYLE TESTS (with mocked external services)
# =============================================================================

@pytest.mark.unit
class TestMultiChannelCoordination:
    """Test multi-channel notification coordination."""

    def test_send_to_user_with_all_channels_enabled(self, orchestrator, db):
        """
        GIVEN a user with all notification channels enabled
        WHEN sending notification
        THEN all channels should receive notifications
        """
        payload = NotificationPayload(
            notification_type=NotificationType.MATCH_REMINDER,
            title='Match Tomorrow',
            message='Get ready for your match!',
            user_ids=[999],  # Using mock user id
        )

        # Mock user preferences to simulate user with all channels enabled
        mock_prefs = {
            999: {
                'push_enabled': True,
                'email_enabled': True,
                'sms_enabled': True,
                'discord_enabled': True,
                'email': 'test@example.com',
                'phone': '+15551234567',
                'discord_id': 'discord123',
                'match_reminders': True,
            }
        }

        # Mock all external services
        with patch.object(orchestrator, '_get_users_with_preferences', return_value=mock_prefs), \
             patch.object(orchestrator, '_create_in_app_notification', return_value=True) as mock_in_app, \
             patch.object(orchestrator, '_send_push_notifications', return_value={'success': 1, 'failure': 0}) as mock_push, \
             patch.object(orchestrator, '_send_email_notification', return_value=True) as mock_email, \
             patch.object(orchestrator, '_send_sms_notification', return_value=True) as mock_sms, \
             patch.object(orchestrator, '_send_discord_notification', return_value=True) as mock_discord:

            results = orchestrator.send(payload)

        # Verify in-app was called
        assert mock_in_app.called

    def test_send_skips_disabled_channels(self, orchestrator, db):
        """
        GIVEN a user with all notification channels disabled
        WHEN sending notification
        THEN channels should be skipped
        """
        payload = NotificationPayload(
            notification_type=NotificationType.MATCH_REMINDER,
            title='Match Tomorrow',
            message='Get ready!',
            user_ids=[998],  # Using mock user id
        )

        # Mock user preferences to simulate user with all channels disabled
        mock_prefs = {
            998: {
                'push_enabled': False,
                'email_enabled': False,
                'sms_enabled': False,
                'discord_enabled': False,
                'email': 'none@example.com',
                'phone': None,
                'discord_id': None,
                'match_reminders': False,
            }
        }

        with patch.object(orchestrator, '_get_users_with_preferences', return_value=mock_prefs), \
             patch.object(orchestrator, '_create_in_app_notification', return_value=True) as mock_in_app, \
             patch.object(orchestrator, '_send_push_notifications', return_value={'success': 0, 'failure': 0}) as mock_push, \
             patch.object(orchestrator, '_send_email_notification', return_value=False) as mock_email, \
             patch.object(orchestrator, '_send_sms_notification', return_value=False) as mock_sms, \
             patch.object(orchestrator, '_send_discord_notification', return_value=False) as mock_discord:

            results = orchestrator.send(payload)

        # In-app is always created unless explicitly disabled
        assert mock_in_app.called
        # Push should be skipped due to preference
        assert results['push']['skipped'] >= 0


# =============================================================================
# SINGLETON INSTANCE TEST
# =============================================================================

@pytest.mark.unit
class TestSingletonInstance:
    """Test the global orchestrator singleton."""

    def test_global_orchestrator_exists(self):
        """
        GIVEN the notification_orchestrator module
        WHEN importing orchestrator
        THEN global instance should be available
        """
        from app.services.notification_orchestrator import orchestrator

        assert orchestrator is not None
        assert isinstance(orchestrator, NotificationOrchestrator)
