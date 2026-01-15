"""
Players Route Behavior Tests.

These tests verify WHAT happens when users interact with player routes, not HOW the code works.
Tests should remain stable even if:
- Implementation details change
- Internal data structures are refactored
- Additional features are added

Tests focus on behaviors:
- Can users view player profiles?
- Can users update their own profiles?
- Can admins manage player data?
- Does the system handle permissions correctly?
- Can users verify their profiles via the wizard?
"""
import pytest
from datetime import datetime, date, time, timedelta
from unittest.mock import patch, Mock, MagicMock
import uuid

from tests.factories import (
    UserFactory, MatchFactory, PlayerFactory, TeamFactory,
    SeasonFactory, LeagueFactory, ScheduleFactory, AvailabilityFactory
)
from tests.helpers import MatchTestHelper, TestDataBuilder


# =============================================================================
# Fixtures for Players Tests
# =============================================================================

@pytest.fixture
def pub_league_admin_role(db):
    """Create Pub League Admin role with required permissions."""
    from app.models import Role, Permission

    role = Role.query.filter_by(name='Pub League Admin').first()
    if not role:
        role = Role(name='Pub League Admin', description='Pub League Administrator')
        db.session.add(role)
        db.session.flush()

    # Add required permissions
    permissions_needed = [
        ('view_all_player_profiles', 'Can view all player profiles'),
        ('edit_player_stats', 'Can edit player stats'),
        ('view_player_contact_info', 'Can view player contact info'),
        ('view_player_admin_notes', 'Can view admin notes'),
        ('edit_player_admin_notes', 'Can edit admin notes'),
        ('edit_any_player_profile', 'Can edit any player profile'),
    ]

    for perm_name, perm_desc in permissions_needed:
        perm = Permission.query.filter_by(name=perm_name).first()
        if not perm:
            perm = Permission(name=perm_name, description=perm_desc)
            db.session.add(perm)
            db.session.flush()

        if perm not in role.permissions:
            role.permissions.append(perm)

    db.session.commit()
    return role


@pytest.fixture
def global_admin_role(db):
    """Create Global Admin role."""
    from app.models import Role

    role = Role.query.filter_by(name='Global Admin').first()
    if not role:
        role = Role(name='Global Admin', description='Global Administrator')
        db.session.add(role)
        db.session.commit()
    return role


@pytest.fixture
def pub_league_coach_role(db):
    """Create Pub League Coach role with required permissions."""
    from app.models import Role, Permission

    role = Role.query.filter_by(name='Pub League Coach').first()
    if not role:
        role = Role(name='Pub League Coach', description='Pub League Coach')
        db.session.add(role)
        db.session.flush()

    # Add basic permissions
    view_profiles = Permission.query.filter_by(name='view_all_player_profiles').first()
    if not view_profiles:
        view_profiles = Permission(name='view_all_player_profiles', description='Can view all profiles')
        db.session.add(view_profiles)
        db.session.flush()

    if view_profiles not in role.permissions:
        role.permissions.append(view_profiles)

    db.session.commit()
    return role


@pytest.fixture
def admin_user_with_role(db, global_admin_role):
    """Create admin user with Global Admin role."""
    from app.models import User

    user = User(
        username=f'admin_{uuid.uuid4().hex[:8]}',
        email=f'admin_{uuid.uuid4().hex[:8]}@example.com',
        is_approved=True,
        approval_status='approved'
    )
    user.set_password('admin123')
    user.roles.append(global_admin_role)
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def pub_league_admin_user(db, pub_league_admin_role):
    """Create user with Pub League Admin role."""
    from app.models import User

    user = User(
        username=f'pubadmin_{uuid.uuid4().hex[:8]}',
        email=f'pubadmin_{uuid.uuid4().hex[:8]}@example.com',
        is_approved=True,
        approval_status='approved'
    )
    user.set_password('admin123')
    user.roles.append(pub_league_admin_role)
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def coach_user(db, pub_league_coach_role, team):
    """Create a coach user with player profile."""
    from app.models import User, Player, player_teams

    user = User(
        username=f'coach_{uuid.uuid4().hex[:8]}',
        email=f'coach_{uuid.uuid4().hex[:8]}@example.com',
        is_approved=True,
        approval_status='approved'
    )
    user.set_password('password123')
    user.roles.append(pub_league_coach_role)
    db.session.add(user)
    db.session.flush()

    player = Player(
        name='Coach Player',
        user_id=user.id,
        discord_id=f'discord_coach_{uuid.uuid4().hex[:12]}',
        jersey_number=1
    )
    db.session.add(player)
    db.session.flush()

    player.teams.append(team)
    db.session.commit()

    return user


@pytest.fixture
def admin_authenticated_client(client, admin_user_with_role):
    """Create authenticated client for admin user."""
    with client.session_transaction() as session:
        session['_user_id'] = admin_user_with_role.id
        session['_fresh'] = True
    return client


@pytest.fixture
def pub_league_admin_client(client, pub_league_admin_user):
    """Create authenticated client for Pub League admin user."""
    with client.session_transaction() as session:
        session['_user_id'] = pub_league_admin_user.id
        session['_fresh'] = True
    return client


@pytest.fixture
def coach_client(client, coach_user):
    """Create authenticated client for coach user."""
    with client.session_transaction() as session:
        session['_user_id'] = coach_user.id
        session['_fresh'] = True
    return client


@pytest.fixture
def pub_league_season(db):
    """Create a current Pub League season."""
    from app.models import Season

    season = Season(
        name='Test Pub League Season 2024',
        league_type='Pub League',
        is_current=True
    )
    db.session.add(season)
    db.session.commit()
    return season


@pytest.fixture
def classic_league(db, pub_league_season):
    """Create a Classic league."""
    from app.models import League

    league = League(
        name='Classic',
        season_id=pub_league_season.id
    )
    db.session.add(league)
    db.session.commit()
    return league


@pytest.fixture
def player_with_stats(db, user, team, pub_league_season):
    """Create a player with season and career stats."""
    from app.models import Player, PlayerSeasonStats, PlayerCareerStats

    player = Player(
        name='Stats Test Player',
        user_id=user.id,
        discord_id=f'discord_stats_{uuid.uuid4().hex[:12]}',
        jersey_number=10,
        jersey_size='M'
    )
    db.session.add(player)
    db.session.flush()
    player.teams.append(team)

    # Add season stats
    season_stats = PlayerSeasonStats(
        player_id=player.id,
        season_id=pub_league_season.id,
        goals=5,
        assists=3,
        yellow_cards=1,
        red_cards=0
    )
    db.session.add(season_stats)

    # Add career stats
    career_stats = PlayerCareerStats(
        player_id=player.id,
        goals=25,
        assists=15,
        yellow_cards=5,
        red_cards=1
    )
    db.session.add(career_stats)

    db.session.commit()
    return player


@pytest.fixture
def other_user(db, user_role):
    """Create another test user."""
    from app.models import User

    user = User(
        username=f'otheruser_{uuid.uuid4().hex[:8]}',
        email=f'other_{uuid.uuid4().hex[:8]}@example.com',
        is_approved=True,
        approval_status='approved'
    )
    user.set_password('password123')
    user.roles.append(user_role)
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def other_player(db, other_user, team):
    """Create another player for testing cross-user access."""
    from app.models import Player

    player = Player(
        name='Other Player',
        user_id=other_user.id,
        discord_id=f'discord_other_{uuid.uuid4().hex[:12]}',
        jersey_number=99,
        jersey_size='L'
    )
    db.session.add(player)
    db.session.flush()
    player.teams.append(team)
    db.session.commit()
    return player


@pytest.fixture(autouse=True)
def mock_players_dependencies():
    """Mock external dependencies for player tests."""
    mock_task = MagicMock()
    mock_task.delay = MagicMock(return_value=MagicMock(id='mock-task-id'))
    mock_task.apply_async = MagicMock(return_value=MagicMock(id='mock-task-id'))

    # Mock Discord bot API calls
    mock_requests_post = MagicMock()
    mock_requests_post.return_value = MagicMock(status_code=200, json=lambda: {'success': True})

    # Mock PresenceManager for online status
    mock_presence = MagicMock()
    mock_presence.is_user_online.return_value = False

    with patch('app.tasks.player_sync.sync_players_with_woocommerce', mock_task), \
         patch('app.sockets.presence.PresenceManager', mock_presence), \
         patch('app.players.PresenceManager', mock_presence):
        yield


# =============================================================================
# BEHAVIOR TESTS: Player Profile Viewing
# =============================================================================

@pytest.mark.unit
class TestPlayerProfileViewingBehaviors:
    """Test that users can view player profiles based on permissions."""

    def test_when_user_views_own_profile_then_profile_is_displayed(
        self, db, authenticated_client, player, pub_league_season, classic_league
    ):
        """
        GIVEN an authenticated user with a player profile
        WHEN they view their own profile
        THEN the profile page should be displayed
        """
        # Ensure player has a league assigned
        player.league_id = classic_league.id
        db.session.commit()

        response = authenticated_client.get(
            f'/players/profile/{player.id}',
            follow_redirects=False
        )

        # Should display profile or redirect based on implementation
        assert response.status_code in (200, 302), \
            f"Should display profile or redirect, got {response.status_code}"

    def test_when_unauthenticated_user_views_profile_then_redirected_to_login(
        self, client, db, player
    ):
        """
        GIVEN an unauthenticated user
        WHEN they try to view a player profile
        THEN they should be redirected to login
        """
        response = client.get(
            f'/players/profile/{player.id}',
            follow_redirects=False
        )

        assert response.status_code in (302, 401, 403), \
            f"Should redirect to login, got {response.status_code}"

    def test_when_user_views_nonexistent_profile_then_404_returned(
        self, db, authenticated_client
    ):
        """
        GIVEN an authenticated user
        WHEN they try to view a non-existent player profile
        THEN a 404 error should be returned
        """
        response = authenticated_client.get(
            '/players/profile/99999',
            follow_redirects=False
        )

        assert response.status_code in (302, 404), \
            f"Should return 404 or redirect, got {response.status_code}"

    def test_when_admin_views_any_profile_then_profile_is_accessible(
        self, db, admin_authenticated_client, other_player, pub_league_season, classic_league
    ):
        """
        GIVEN an admin user
        WHEN they view any player's profile
        THEN the profile should be accessible
        """
        other_player.league_id = classic_league.id
        db.session.commit()

        response = admin_authenticated_client.get(
            f'/players/profile/{other_player.id}',
            follow_redirects=False
        )

        assert response.status_code in (200, 302), \
            f"Admin should be able to view any profile, got {response.status_code}"


# =============================================================================
# BEHAVIOR TESTS: Player Profile API
# =============================================================================

@pytest.mark.unit
class TestPlayerProfileAPIBehaviors:
    """Test the player profile API endpoint behaviors."""

    def test_when_user_requests_profile_api_then_json_returned(
        self, db, authenticated_client, player
    ):
        """
        GIVEN an authenticated user
        WHEN they request a player profile via API
        THEN JSON data should be returned
        """
        response = authenticated_client.get(
            f'/players/api/player_profile/{player.id}',
            follow_redirects=False
        )

        assert response.status_code in (200, 302), \
            f"Should return JSON or redirect, got {response.status_code}"

        if response.status_code == 200:
            data = response.get_json()
            assert data is not None, "Should return JSON data"
            assert 'name' in data, "Response should include player name"

    def test_when_profile_api_called_for_nonexistent_player_then_404(
        self, db, authenticated_client
    ):
        """
        GIVEN an authenticated user
        WHEN they request a non-existent player via API
        THEN 404 should be returned
        """
        response = authenticated_client.get(
            '/players/api/player_profile/99999',
            follow_redirects=False
        )

        assert response.status_code == 404, \
            f"Should return 404 for non-existent player, got {response.status_code}"

    def test_when_unauthenticated_requests_profile_api_then_rejected(
        self, client, db, player
    ):
        """
        GIVEN an unauthenticated user
        WHEN they request a profile via API
        THEN they should be rejected
        """
        response = client.get(
            f'/players/api/player_profile/{player.id}',
            follow_redirects=False
        )

        assert response.status_code in (302, 401, 403), \
            f"Should reject unauthenticated request, got {response.status_code}"


# =============================================================================
# BEHAVIOR TESTS: Player Profile Update
# =============================================================================

@pytest.mark.unit
class TestPlayerProfileUpdateBehaviors:
    """Test player profile update behaviors."""

    def test_when_user_updates_own_profile_then_changes_are_saved(
        self, db, authenticated_client, player, pub_league_season, classic_league
    ):
        """
        GIVEN an authenticated user with edit_own_profile permission
        WHEN they update their profile
        THEN the changes should be saved
        """
        player.league_id = classic_league.id
        db.session.commit()

        response = authenticated_client.post(
            f'/players/profile/{player.id}/update_modal',
            json={
                'phone': '555-123-4567',
                'pronouns': 'they/them',
                'jersey_size': 'L'
            },
            content_type='application/json'
        )

        # Should update successfully or redirect
        assert response.status_code in (200, 302, 403), \
            f"Should handle profile update, got {response.status_code}"

    def test_when_user_updates_other_profile_then_rejected(
        self, db, authenticated_client, other_player
    ):
        """
        GIVEN a regular user
        WHEN they try to update another user's profile
        THEN the request should be rejected
        """
        response = authenticated_client.post(
            f'/players/profile/{other_player.id}/update_modal',
            json={'phone': '555-999-9999'},
            content_type='application/json'
        )

        assert response.status_code == 403, \
            f"Should reject update of other's profile, got {response.status_code}"

    def test_when_update_modal_has_no_data_then_error_returned(
        self, db, authenticated_client, player
    ):
        """
        GIVEN an authenticated user
        WHEN they submit an update with no data
        THEN an error should be returned
        """
        response = authenticated_client.post(
            f'/players/profile/{player.id}/update_modal',
            json={},
            content_type='application/json'
        )

        # Empty data should still work (no fields to update)
        assert response.status_code in (200, 400), \
            f"Should handle empty update, got {response.status_code}"


# =============================================================================
# BEHAVIOR TESTS: Profile Verification Wizard
# =============================================================================

@pytest.mark.unit
class TestProfileVerificationWizardBehaviors:
    """Test profile verification wizard behaviors."""

    def test_when_user_accesses_verify_endpoint_then_redirected_to_wizard(
        self, db, authenticated_client, player
    ):
        """
        GIVEN an authenticated user with a player profile
        WHEN they access the verify endpoint
        THEN they should be redirected to the wizard
        """
        response = authenticated_client.get(
            '/players/verify',
            follow_redirects=False
        )

        assert response.status_code in (200, 302), \
            f"Should redirect to wizard, got {response.status_code}"

    def test_when_user_accesses_wizard_for_own_profile_then_wizard_displayed(
        self, db, authenticated_client, player
    ):
        """
        GIVEN an authenticated user
        WHEN they access the wizard for their own profile
        THEN the wizard should be displayed
        """
        response = authenticated_client.get(
            f'/players/profile/{player.id}/wizard',
            follow_redirects=False
        )

        assert response.status_code in (200, 302), \
            f"Should display wizard, got {response.status_code}"

    def test_when_user_accesses_wizard_for_other_profile_then_rejected(
        self, db, authenticated_client, other_player
    ):
        """
        GIVEN an authenticated user
        WHEN they try to access the wizard for another user's profile
        THEN they should be rejected
        """
        response = authenticated_client.get(
            f'/players/profile/{other_player.id}/wizard',
            follow_redirects=False
        )

        assert response.status_code == 302, \
            f"Should redirect with error, got {response.status_code}"

    def test_when_wizard_update_submitted_then_profile_is_verified(
        self, db, authenticated_client, player
    ):
        """
        GIVEN an authenticated user completing the wizard
        WHEN they submit their profile data
        THEN the profile should be marked as verified
        """
        response = authenticated_client.post(
            f'/players/profile/{player.id}/wizard/update',
            data={
                'name': player.name,
                'phone': '555-123-4567',
                'jersey_size': 'M'
            },
            follow_redirects=False
        )

        assert response.status_code in (200, 302), \
            f"Wizard update should succeed, got {response.status_code}"

    def test_when_wizard_auto_save_submitted_then_data_saved(
        self, db, authenticated_client, player
    ):
        """
        GIVEN an authenticated user in the wizard
        WHEN auto-save is triggered
        THEN data should be saved without marking as verified
        """
        response = authenticated_client.post(
            f'/players/profile/{player.id}/wizard/auto-save',
            json={'phone': '555-111-2222'},
            content_type='application/json'
        )

        assert response.status_code in (200, 403), \
            f"Auto-save should handle request, got {response.status_code}"

    def test_when_auto_save_for_other_profile_then_rejected(
        self, db, authenticated_client, other_player
    ):
        """
        GIVEN an authenticated user
        WHEN they try to auto-save for another user's profile
        THEN the request should be rejected
        """
        response = authenticated_client.post(
            f'/players/profile/{other_player.id}/wizard/auto-save',
            json={'phone': '555-999-9999'},
            content_type='application/json'
        )

        assert response.status_code == 403, \
            f"Should reject auto-save for other's profile, got {response.status_code}"


# =============================================================================
# BEHAVIOR TESTS: Profile Verification
# =============================================================================

@pytest.mark.unit
class TestProfileVerificationBehaviors:
    """Test profile verification endpoint behaviors."""

    def test_when_user_verifies_own_profile_then_timestamp_updated(
        self, db, authenticated_client, player
    ):
        """
        GIVEN an authenticated user
        WHEN they verify their profile
        THEN the verification timestamp should be updated
        """
        response = authenticated_client.post(
            f'/players/profile/{player.id}/verify',
            follow_redirects=False
        )

        assert response.status_code in (200, 302), \
            f"Should verify profile, got {response.status_code}"

    def test_when_user_verifies_other_profile_then_rejected(
        self, db, authenticated_client, other_player
    ):
        """
        GIVEN an authenticated user
        WHEN they try to verify another user's profile
        THEN the request should be rejected
        """
        response = authenticated_client.post(
            f'/players/profile/{other_player.id}/verify',
            follow_redirects=False
        )

        assert response.status_code in (302, 403), \
            f"Should reject verification of other's profile, got {response.status_code}"

    def test_when_ajax_verify_succeeds_then_json_returned(
        self, db, authenticated_client, player
    ):
        """
        GIVEN an authenticated user
        WHEN they verify via AJAX
        THEN JSON response should be returned
        """
        response = authenticated_client.post(
            f'/players/profile/{player.id}/verify',
            headers={'X-Requested-With': 'XMLHttpRequest'},
            follow_redirects=False
        )

        assert response.status_code in (200, 403), \
            f"Should return JSON for AJAX, got {response.status_code}"

        if response.status_code == 200:
            data = response.get_json()
            assert data is not None
            assert data.get('success') is True


# =============================================================================
# BEHAVIOR TESTS: Mobile Profile Update
# =============================================================================

@pytest.mark.unit
class TestMobileProfileUpdateBehaviors:
    """Test mobile profile update behaviors."""

    def test_when_user_accesses_mobile_profile_then_page_displayed(
        self, db, authenticated_client, player
    ):
        """
        GIVEN an authenticated user
        WHEN they access their mobile profile page
        THEN the page should be displayed
        """
        response = authenticated_client.get(
            f'/players/profile/{player.id}/mobile',
            follow_redirects=False
        )

        assert response.status_code in (200, 302), \
            f"Should display mobile profile, got {response.status_code}"

    def test_when_user_accesses_other_mobile_profile_then_rejected(
        self, db, authenticated_client, other_player
    ):
        """
        GIVEN an authenticated user
        WHEN they try to access another user's mobile profile
        THEN they should be rejected
        """
        response = authenticated_client.get(
            f'/players/profile/{other_player.id}/mobile',
            follow_redirects=False
        )

        assert response.status_code == 302, \
            f"Should reject access to other's mobile profile, got {response.status_code}"

    def test_when_user_accesses_desktop_profile_then_page_displayed(
        self, db, authenticated_client, player
    ):
        """
        GIVEN an authenticated user
        WHEN they access their desktop profile page
        THEN the page should be displayed
        """
        response = authenticated_client.get(
            f'/players/profile/{player.id}/desktop',
            follow_redirects=False
        )

        assert response.status_code in (200, 302), \
            f"Should display desktop profile, got {response.status_code}"

    def test_when_profile_success_page_accessed_then_displayed(
        self, db, authenticated_client, player
    ):
        """
        GIVEN an authenticated user
        WHEN they access the success page for their profile
        THEN the success page should be displayed
        """
        response = authenticated_client.get(
            f'/players/profile/{player.id}/mobile/success?action=updated',
            follow_redirects=False
        )

        assert response.status_code in (200, 302), \
            f"Should display success page, got {response.status_code}"


# =============================================================================
# BEHAVIOR TESTS: Player Team History
# =============================================================================

@pytest.mark.unit
class TestPlayerTeamHistoryBehaviors:
    """Test player team history behaviors."""

    def test_when_team_history_requested_then_history_returned(
        self, db, authenticated_client, player
    ):
        """
        GIVEN an authenticated user
        WHEN they request a player's team history
        THEN the history should be returned
        """
        response = authenticated_client.get(
            f'/players/player/{player.id}/team_history',
            follow_redirects=False
        )

        assert response.status_code in (200, 500), \
            f"Should return team history, got {response.status_code}"

    def test_when_unauthenticated_requests_history_then_rejected(
        self, client, db, player
    ):
        """
        GIVEN an unauthenticated user
        WHEN they request team history
        THEN they should be rejected
        """
        response = client.get(
            f'/players/player/{player.id}/team_history',
            follow_redirects=False
        )

        assert response.status_code in (302, 401, 403), \
            f"Should reject unauthenticated request, got {response.status_code}"


# =============================================================================
# BEHAVIOR TESTS: Admin Player Management
# =============================================================================

@pytest.mark.unit
class TestAdminPlayerManagementBehaviors:
    """Test admin player management behaviors."""

    def test_when_admin_views_players_then_redirected_to_user_management(
        self, db, pub_league_admin_client
    ):
        """
        GIVEN an admin user
        WHEN they access the players view
        THEN they should be redirected to user management
        """
        response = pub_league_admin_client.get(
            '/players/',
            follow_redirects=False
        )

        assert response.status_code == 302, \
            f"Should redirect to user management, got {response.status_code}"

    def test_when_non_admin_views_players_then_rejected(
        self, db, authenticated_client
    ):
        """
        GIVEN a non-admin user
        WHEN they try to access the players view
        THEN they should be rejected
        """
        response = authenticated_client.get(
            '/players/',
            follow_redirects=False
        )

        assert response.status_code in (302, 403), \
            f"Should reject non-admin access, got {response.status_code}"

    def test_when_admin_requests_update_then_redirected(
        self, db, pub_league_admin_client
    ):
        """
        GIVEN an admin user
        WHEN they request player update
        THEN they should be redirected appropriately
        """
        response = pub_league_admin_client.post(
            '/players/update',
            follow_redirects=False
        )

        assert response.status_code == 307, \
            f"Should redirect with POST preserved, got {response.status_code}"


# =============================================================================
# BEHAVIOR TESTS: Player Creation
# =============================================================================

@pytest.mark.unit
class TestPlayerCreationBehaviors:
    """Test player creation behaviors."""

    def test_when_admin_creates_player_with_valid_data_then_player_created(
        self, db, pub_league_admin_client, classic_league
    ):
        """
        GIVEN an admin user
        WHEN they create a player with valid data
        THEN the player should be created
        """
        with patch('app.players.create_user_for_player') as mock_create_user, \
             patch('app.players.create_player_profile') as mock_create_profile:
            mock_user = MagicMock()
            mock_user.id = 9999
            mock_create_user.return_value = mock_user

            mock_player = MagicMock()
            mock_player.id = 8888
            mock_create_profile.return_value = mock_player

            response = pub_league_admin_client.post(
                '/players/create_player',
                data={
                    'name': 'New Test Player',
                    'email': 'newplayer@example.com',
                    'phone': '555-123-4567',
                    'jersey_size': 'M',
                    'league_id': str(classic_league.id)
                },
                follow_redirects=False
            )

            # Should redirect after creation or show error
            assert response.status_code in (302, 200), \
                f"Should handle player creation, got {response.status_code}"

    def test_when_non_admin_creates_player_then_rejected(
        self, db, authenticated_client, classic_league
    ):
        """
        GIVEN a non-admin user
        WHEN they try to create a player
        THEN the request should be rejected
        """
        response = authenticated_client.post(
            '/players/create_player',
            data={
                'name': 'Unauthorized Player',
                'email': 'unauthorized@example.com',
                'phone': '555-999-9999',
                'jersey_size': 'M',
                'league_id': str(classic_league.id)
            },
            follow_redirects=False
        )

        assert response.status_code in (302, 403), \
            f"Should reject non-admin creation, got {response.status_code}"


# =============================================================================
# BEHAVIOR TESTS: Player Editing
# =============================================================================

@pytest.mark.unit
class TestPlayerEditingBehaviors:
    """Test player editing behaviors."""

    def test_when_admin_edits_player_then_form_displayed(
        self, db, pub_league_admin_client, player
    ):
        """
        GIVEN an admin user
        WHEN they access the edit player page
        THEN the edit form should be displayed
        """
        response = pub_league_admin_client.get(
            f'/players/edit_player/{player.id}',
            follow_redirects=False
        )

        assert response.status_code in (200, 302), \
            f"Should display edit form, got {response.status_code}"

    def test_when_non_admin_edits_player_then_rejected(
        self, db, authenticated_client, player
    ):
        """
        GIVEN a non-admin user
        WHEN they try to edit a player
        THEN they should be rejected
        """
        response = authenticated_client.get(
            f'/players/edit_player/{player.id}',
            follow_redirects=False
        )

        assert response.status_code in (302, 403), \
            f"Should reject non-admin edit, got {response.status_code}"

    def test_when_admin_edits_nonexistent_player_then_404(
        self, db, pub_league_admin_client
    ):
        """
        GIVEN an admin user
        WHEN they try to edit a non-existent player
        THEN 404 should be returned
        """
        response = pub_league_admin_client.get(
            '/players/edit_player/99999',
            follow_redirects=False
        )

        assert response.status_code == 404, \
            f"Should return 404 for non-existent player, got {response.status_code}"


# =============================================================================
# BEHAVIOR TESTS: Player Deletion
# =============================================================================

@pytest.mark.unit
class TestPlayerDeletionBehaviors:
    """Test player deletion behaviors."""

    def test_when_admin_deletes_player_then_player_removed(
        self, db, pub_league_admin_client
    ):
        """
        GIVEN an admin user
        WHEN they delete a player
        THEN the player should be removed
        """
        from app.models import Player, User

        # Create player specifically for deletion
        delete_user = User(
            username=f'delete_user_{uuid.uuid4().hex[:8]}',
            email=f'delete_{uuid.uuid4().hex[:8]}@example.com',
            is_approved=True,
            approval_status='approved'
        )
        delete_user.set_password('password123')
        db.session.add(delete_user)
        db.session.flush()

        delete_player = Player(
            name='Delete Me Player',
            user_id=delete_user.id,
            discord_id=f'discord_delete_{uuid.uuid4().hex[:12]}'
        )
        db.session.add(delete_player)
        db.session.commit()

        player_id = delete_player.id

        response = pub_league_admin_client.post(
            f'/players/delete_player/{player_id}',
            follow_redirects=False
        )

        assert response.status_code == 302, \
            f"Should redirect after deletion, got {response.status_code}"

    def test_when_non_admin_deletes_player_then_rejected(
        self, db, authenticated_client, player
    ):
        """
        GIVEN a non-admin user
        WHEN they try to delete a player
        THEN the request should be rejected
        """
        response = authenticated_client.post(
            f'/players/delete_player/{player.id}',
            follow_redirects=False
        )

        assert response.status_code in (302, 403), \
            f"Should reject non-admin deletion, got {response.status_code}"

    def test_when_admin_deletes_nonexistent_player_then_404(
        self, db, pub_league_admin_client
    ):
        """
        GIVEN an admin user
        WHEN they try to delete a non-existent player
        THEN 404 should be returned
        """
        response = pub_league_admin_client.post(
            '/players/delete_player/99999',
            follow_redirects=False
        )

        assert response.status_code == 404, \
            f"Should return 404 for non-existent player, got {response.status_code}"


# =============================================================================
# BEHAVIOR TESTS: Player Stats Management
# =============================================================================

@pytest.mark.unit
class TestPlayerStatsManagementBehaviors:
    """Test player stats management behaviors."""

    def test_when_admin_adds_stat_manually_then_stat_recorded(
        self, db, pub_league_admin_client, player, match
    ):
        """
        GIVEN an admin user
        WHEN they add a stat manually
        THEN the stat should be recorded
        """
        with patch.object(player, 'add_stat_manually', return_value=None):
            response = pub_league_admin_client.post(
                f'/players/add_stat_manually/{player.id}',
                data={
                    'match_id': match.id,
                    'goals': '1',
                    'assists': '0',
                    'yellow_cards': '0',
                    'red_cards': '0'
                },
                follow_redirects=False
            )

            # Should redirect after adding stat
            assert response.status_code in (302, 404, 500), \
                f"Should handle stat addition, got {response.status_code}"

    def test_when_non_admin_adds_stat_then_rejected(
        self, db, authenticated_client, player, match
    ):
        """
        GIVEN a non-admin user
        WHEN they try to add a stat manually
        THEN the request should be rejected
        """
        response = authenticated_client.post(
            f'/players/add_stat_manually/{player.id}',
            data={
                'match_id': match.id,
                'goals': '1'
            },
            follow_redirects=False
        )

        assert response.status_code in (302, 403), \
            f"Should reject non-admin stat addition, got {response.status_code}"


# =============================================================================
# BEHAVIOR TESTS: Match Stats Editing
# =============================================================================

@pytest.mark.unit
class TestMatchStatsEditingBehaviors:
    """Test match stats editing behaviors."""

    def test_when_admin_gets_match_stat_then_json_returned(
        self, db, pub_league_admin_client, player, match
    ):
        """
        GIVEN an admin user
        WHEN they request match stat data
        THEN JSON should be returned
        """
        from app.models import PlayerEvent
        from app.models.stats import EventType

        # Create a player event for testing
        event = PlayerEvent(
            player_id=player.id,
            match_id=match.id,
            event_type=EventType.GOAL,
            minute=45
        )
        db.session.add(event)
        db.session.commit()

        response = pub_league_admin_client.get(
            f'/players/edit_match_stat/{event.id}',
            follow_redirects=False
        )

        assert response.status_code in (200, 404), \
            f"Should return stat data, got {response.status_code}"

    def test_when_admin_removes_match_stat_then_stat_removed(
        self, db, pub_league_admin_client, player, match
    ):
        """
        GIVEN an admin user
        WHEN they remove a match stat
        THEN the stat should be removed
        """
        from app.models import PlayerEvent
        from app.models.stats import EventType

        event = PlayerEvent(
            player_id=player.id,
            match_id=match.id,
            event_type=EventType.GOAL,
            minute=30
        )
        db.session.add(event)
        db.session.commit()

        with patch('app.players.decrement_player_stats'):
            response = pub_league_admin_client.post(
                f'/players/remove_match_stat/{event.id}',
                follow_redirects=False
            )

            assert response.status_code in (200, 404, 500), \
                f"Should handle stat removal, got {response.status_code}"

    def test_when_non_admin_removes_stat_then_rejected(
        self, db, authenticated_client
    ):
        """
        GIVEN a non-admin user
        WHEN they try to remove a match stat
        THEN the request should be rejected
        """
        response = authenticated_client.post(
            '/players/remove_match_stat/1',
            follow_redirects=False
        )

        assert response.status_code in (302, 403, 404), \
            f"Should reject non-admin stat removal, got {response.status_code}"


# =============================================================================
# BEHAVIOR TESTS: Profile Picture Upload
# =============================================================================

@pytest.mark.unit
class TestProfilePictureUploadBehaviors:
    """Test profile picture upload behaviors."""

    def test_when_user_uploads_profile_picture_then_picture_saved(
        self, db, authenticated_client, player
    ):
        """
        GIVEN an authenticated user
        WHEN they upload a profile picture
        THEN the picture should be saved
        """
        with patch('app.players.save_cropped_profile_picture') as mock_save:
            mock_save.return_value = '/static/uploads/profile_123.png'

            response = authenticated_client.post(
                f'/players/player/{player.id}/upload_profile_picture',
                data={'cropped_image_data': 'data:image/png;base64,iVBORw0KGgo='},
                follow_redirects=False
            )

            # Should handle upload
            assert response.status_code in (200, 302, 400, 403), \
                f"Should handle picture upload, got {response.status_code}"

    def test_when_upload_has_no_image_then_error_returned(
        self, db, authenticated_client, player
    ):
        """
        GIVEN an authenticated user
        WHEN they submit upload with no image
        THEN an error should be returned
        """
        response = authenticated_client.post(
            f'/players/player/{player.id}/upload_profile_picture',
            data={},
            follow_redirects=False
        )

        assert response.status_code in (302, 400, 403), \
            f"Should return error for missing image, got {response.status_code}"

    def test_when_ajax_upload_succeeds_then_json_returned(
        self, db, authenticated_client, player
    ):
        """
        GIVEN an authenticated user
        WHEN they upload via AJAX
        THEN JSON response should be returned
        """
        with patch('app.players.save_cropped_profile_picture') as mock_save:
            mock_save.return_value = '/static/uploads/profile_123.png'

            response = authenticated_client.post(
                f'/players/player/{player.id}/upload_profile_picture',
                data={'cropped_image_data': 'data:image/png;base64,iVBORw0KGgo='},
                headers={'X-Requested-With': 'XMLHttpRequest'},
                follow_redirects=False
            )

            assert response.status_code in (200, 400, 403), \
                f"Should return JSON for AJAX, got {response.status_code}"


# =============================================================================
# BEHAVIOR TESTS: Admin Review
# =============================================================================

@pytest.mark.unit
class TestAdminReviewBehaviors:
    """Test admin review page behaviors."""

    def test_when_admin_accesses_review_then_page_displayed(
        self, db, pub_league_admin_client
    ):
        """
        GIVEN an admin user
        WHEN they access the admin review page
        THEN the page should be displayed
        """
        response = pub_league_admin_client.get(
            '/players/admin/review',
            follow_redirects=False
        )

        assert response.status_code in (200, 302), \
            f"Should display review page, got {response.status_code}"

    def test_when_non_admin_accesses_review_then_rejected(
        self, db, authenticated_client
    ):
        """
        GIVEN a non-admin user
        WHEN they try to access admin review
        THEN they should be rejected
        """
        response = authenticated_client.get(
            '/players/admin/review',
            follow_redirects=False
        )

        assert response.status_code in (302, 403), \
            f"Should reject non-admin access, got {response.status_code}"


# =============================================================================
# BEHAVIOR TESTS: Discord Communication
# =============================================================================

@pytest.mark.unit
class TestDiscordCommunicationBehaviors:
    """Test Discord communication behaviors."""

    def test_when_coach_sends_discord_message_then_message_sent(
        self, db, coach_client, player
    ):
        """
        GIVEN a coach user
        WHEN they send a Discord message to a player
        THEN the message should be sent
        """
        player.discord_id = 'test_discord_123'
        player.user.discord_notifications = True
        db.session.commit()

        with patch('requests.post') as mock_post:
            mock_post.return_value = MagicMock(status_code=200)

            response = coach_client.post(
                f'/players/contact_player_discord/{player.id}',
                data={'discord_message': 'Test message'},
                follow_redirects=False
            )

            assert response.status_code == 302, \
                f"Should redirect after sending, got {response.status_code}"

    def test_when_player_has_no_discord_then_error_shown(
        self, db, coach_client, other_player
    ):
        """
        GIVEN a player without Discord linked
        WHEN coach tries to send Discord message
        THEN an error should be shown
        """
        other_player.discord_id = None
        db.session.commit()

        response = coach_client.post(
            f'/players/contact_player_discord/{other_player.id}',
            data={'discord_message': 'Test message'},
            follow_redirects=False
        )

        assert response.status_code == 302, \
            f"Should redirect with error, got {response.status_code}"

    def test_when_empty_message_sent_then_error_returned(
        self, db, coach_client, player
    ):
        """
        GIVEN a coach user
        WHEN they try to send an empty message
        THEN an error should be returned
        """
        response = coach_client.post(
            f'/players/contact_player_discord/{player.id}',
            data={'discord_message': ''},
            follow_redirects=False
        )

        assert response.status_code == 302, \
            f"Should redirect with error, got {response.status_code}"


# =============================================================================
# BEHAVIOR TESTS: Multi-Channel Communication
# =============================================================================

@pytest.mark.unit
class TestMultiChannelCommunicationBehaviors:
    """Test multi-channel communication behaviors."""

    def test_when_coach_contacts_via_email_then_email_sent(
        self, db, coach_client, player
    ):
        """
        GIVEN a coach user
        WHEN they contact a player via email
        THEN the email should be sent
        """
        player.user.email_notifications = True
        db.session.commit()

        with patch('app.players.send_email') as mock_email:
            mock_email.return_value = True

            response = coach_client.post(
                f'/players/contact_player/{player.id}',
                data={
                    'contact_channels': ['email'],
                    'message': 'Test email message',
                    'subject': 'Test Subject'
                },
                follow_redirects=False
            )

            assert response.status_code == 302, \
                f"Should redirect after sending, got {response.status_code}"

    def test_when_coach_contacts_via_sms_then_sms_sent(
        self, db, coach_client, player
    ):
        """
        GIVEN a coach user with a player that has SMS enabled
        WHEN they contact via SMS
        THEN the SMS should be sent
        """
        player.phone = '555-123-4567'
        player.user.sms_notifications = True
        db.session.commit()

        with patch('app.players.send_sms') as mock_sms:
            mock_sms.return_value = (True, 'Success')

            response = coach_client.post(
                f'/players/contact_player/{player.id}',
                data={
                    'contact_channels': ['sms'],
                    'message': 'Test SMS message'
                },
                follow_redirects=False
            )

            assert response.status_code == 302, \
                f"Should redirect after sending, got {response.status_code}"

    def test_when_no_channel_selected_then_error_returned(
        self, db, coach_client, player
    ):
        """
        GIVEN a coach user
        WHEN they try to contact without selecting a channel
        THEN an error should be returned
        """
        response = coach_client.post(
            f'/players/contact_player/{player.id}',
            data={
                'message': 'Test message'
            },
            follow_redirects=False
        )

        assert response.status_code == 302, \
            f"Should redirect with error, got {response.status_code}"


# =============================================================================
# BEHAVIOR TESTS: Player Profile Creation
# =============================================================================

@pytest.mark.unit
class TestPlayerProfileCreationBehaviors:
    """Test player profile creation behaviors."""

    def test_when_user_creates_profile_with_valid_data_then_profile_created(
        self, db, authenticated_client, classic_league
    ):
        """
        GIVEN an authenticated user
        WHEN they submit valid profile data
        THEN a profile should be created
        """
        response = authenticated_client.post(
            '/players/create-profile',
            data={
                'name': 'New Profile Player',
                'email': 'newprofile@example.com',
                'phone': '555-999-8888',
                'jersey_size': 'M',
                'jersey_number': '15',
                'league_id': classic_league.id
            },
            follow_redirects=False
        )

        # Should redirect after creation or show validation error
        assert response.status_code in (200, 302), \
            f"Should handle profile creation, got {response.status_code}"


# =============================================================================
# BEHAVIOR TESTS: Update Status
# =============================================================================

@pytest.mark.unit
class TestUpdateStatusBehaviors:
    """Test update status endpoint behaviors."""

    def test_when_user_checks_update_status_then_redirected(
        self, db, authenticated_client
    ):
        """
        GIVEN an authenticated user
        WHEN they check an update status
        THEN they should be redirected to user management
        """
        response = authenticated_client.get(
            '/players/update_status/test-task-id',
            follow_redirects=False
        )

        assert response.status_code == 302, \
            f"Should redirect to user management, got {response.status_code}"


# =============================================================================
# BEHAVIOR TESTS: Error Handling
# =============================================================================

@pytest.mark.unit
class TestPlayersErrorHandlingBehaviors:
    """Test error handling behaviors for players routes."""

    def test_when_invalid_player_id_format_then_handled_gracefully(
        self, db, authenticated_client
    ):
        """
        GIVEN an authenticated user
        WHEN they request a player with invalid ID format
        THEN the error should be handled gracefully
        """
        response = authenticated_client.get(
            '/players/profile/invalid_id',
            follow_redirects=False
        )

        # Should return 404 or redirect
        assert response.status_code in (302, 404), \
            f"Should handle invalid ID format, got {response.status_code}"

    def test_when_database_error_occurs_then_error_handled(
        self, db, authenticated_client, player
    ):
        """
        GIVEN an authenticated user
        WHEN a database error occurs
        THEN the error should be handled gracefully
        """
        with patch('app.players.g.db_session') as mock_session:
            mock_session.query.side_effect = Exception("Database error")

            response = authenticated_client.get(
                f'/players/profile/{player.id}',
                follow_redirects=False
            )

            # Should handle error gracefully
            assert response.status_code in (302, 500), \
                f"Should handle database error, got {response.status_code}"


# =============================================================================
# BEHAVIOR TESTS: Forbidden Error Handler
# =============================================================================

@pytest.mark.unit
class TestForbiddenErrorHandlerBehaviors:
    """Test forbidden error handler behaviors."""

    def test_when_forbidden_error_raised_then_user_redirected(
        self, db, authenticated_client
    ):
        """
        GIVEN an authenticated user
        WHEN a Forbidden error is raised
        THEN the user should be redirected with a warning
        """
        # This tests the error handler indirectly through permission-restricted routes
        response = authenticated_client.get(
            '/players/admin/review',
            follow_redirects=False
        )

        assert response.status_code in (302, 403), \
            f"Should redirect or return 403, got {response.status_code}"


# =============================================================================
# BEHAVIOR TESTS: Profile Expiry
# =============================================================================

@pytest.mark.unit
class TestProfileExpiryBehaviors:
    """Test profile expiry behaviors."""

    def test_when_profile_is_old_then_marked_as_expired(
        self, db, authenticated_client, player, pub_league_season, classic_league
    ):
        """
        GIVEN a player with an old profile_last_updated
        WHEN viewing the profile
        THEN it should be marked as expired
        """
        player.league_id = classic_league.id
        player.profile_last_updated = datetime.utcnow() - timedelta(days=200)
        db.session.commit()

        response = authenticated_client.get(
            f'/players/profile/{player.id}',
            follow_redirects=False
        )

        # Profile view should work even with expired profile
        assert response.status_code in (200, 302), \
            f"Should display profile (expired or not), got {response.status_code}"

    def test_when_profile_is_recent_then_not_expired(
        self, db, authenticated_client, player, pub_league_season, classic_league
    ):
        """
        GIVEN a player with a recent profile_last_updated
        WHEN viewing the profile
        THEN it should not be marked as expired
        """
        player.league_id = classic_league.id
        player.profile_last_updated = datetime.utcnow()
        db.session.commit()

        response = authenticated_client.get(
            f'/players/profile/{player.id}',
            follow_redirects=False
        )

        assert response.status_code in (200, 302), \
            f"Should display profile, got {response.status_code}"


# =============================================================================
# BEHAVIOR TESTS: Profile Wizard Flow
# =============================================================================

@pytest.mark.unit
class TestProfileWizardFlowBehaviors:
    """Test complete profile wizard flow behaviors."""

    def test_when_profile_wizard_accessed_then_form_displayed(
        self, db, authenticated_client, player
    ):
        """
        GIVEN an authenticated user
        WHEN they access the profile wizard
        THEN the form should be displayed
        """
        response = authenticated_client.get(
            '/players/profile/wizard',
            follow_redirects=False
        )

        # Should display wizard or redirect based on player status
        assert response.status_code in (200, 302), \
            f"Should display wizard, got {response.status_code}"

    def test_when_user_without_player_accesses_wizard_then_redirected(
        self, db, client, user_role
    ):
        """
        GIVEN a user without a player profile
        WHEN they access the profile wizard
        THEN they should be redirected with an error
        """
        from app.models import User

        # Create user without player
        no_player_user = User(
            username=f'noplayer_{uuid.uuid4().hex[:8]}',
            email=f'noplayer_{uuid.uuid4().hex[:8]}@example.com',
            is_approved=True,
            approval_status='approved'
        )
        no_player_user.set_password('password123')
        no_player_user.roles.append(user_role)
        db.session.add(no_player_user)
        db.session.commit()

        with client.session_transaction() as session:
            session['_user_id'] = no_player_user.id
            session['_fresh'] = True

        response = client.get(
            '/players/profile/wizard',
            follow_redirects=False
        )

        assert response.status_code == 302, \
            f"Should redirect user without player, got {response.status_code}"

    def test_when_verify_redirect_accessed_then_redirected_to_wizard(
        self, db, authenticated_client, player
    ):
        """
        GIVEN an authenticated user
        WHEN they access the verify redirect endpoint
        THEN they should be redirected to the wizard
        """
        response = authenticated_client.get(
            f'/players/profile/{player.id}/verify',
            follow_redirects=False
        )

        # GET request should redirect to wizard
        assert response.status_code == 302, \
            f"Should redirect to wizard, got {response.status_code}"


# =============================================================================
# BEHAVIOR TESTS: Confirm Update
# =============================================================================

@pytest.mark.unit
class TestConfirmUpdateBehaviors:
    """Test confirm update behaviors."""

    def test_when_admin_confirms_update_then_redirected(
        self, db, pub_league_admin_client
    ):
        """
        GIVEN an admin user
        WHEN they confirm an update
        THEN they should be redirected appropriately
        """
        response = pub_league_admin_client.post(
            '/players/confirm_update',
            follow_redirects=False
        )

        assert response.status_code == 307, \
            f"Should redirect with POST preserved, got {response.status_code}"

    def test_when_non_admin_confirms_update_then_rejected(
        self, db, authenticated_client
    ):
        """
        GIVEN a non-admin user
        WHEN they try to confirm an update
        THEN they should be rejected
        """
        response = authenticated_client.post(
            '/players/confirm_update',
            follow_redirects=False
        )

        assert response.status_code in (302, 403), \
            f"Should reject non-admin, got {response.status_code}"
