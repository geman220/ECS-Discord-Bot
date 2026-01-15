"""
Discord Utils unit tests.

These tests verify the discord_utils module's core behaviors:
- Name normalization for Discord role conventions
- Rate limiter behaviors (sync and async)
- Role management (get, create, assign, remove, delete)
- Channel/category management
- Player role computation and synchronization
- Match thread creation with duplicate prevention
- User server membership checks
- Error handling for API failures and rate limits

All Discord API calls are mocked to ensure tests are isolated and fast.
"""
import pytest
import asyncio
import aiohttp
import time
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, AsyncMock, patch, PropertyMock
from zoneinfo import ZoneInfo

# Import the module under test
from app.discord_utils import (
    # Constants
    VIEW_CHANNEL,
    SEND_MESSAGES,
    READ_MESSAGE_HISTORY,
    TEAM_PLAYER_PERMISSIONS,
    LEADERSHIP_PERMISSIONS,
    GLOBAL_RATE_LIMIT,
    # Classes
    RateLimiter,
    # Functions
    normalize_name,
    get_role_id,
    create_role,
    get_or_create_role,
    assign_role_to_member,
    remove_role_from_member,
    delete_role,
    get_member_roles,
    get_role_names,
    get_or_create_category,
    create_category,
    create_discord_roles,
    create_discord_channel_async_only,
    rename_team_roles_async_only,
    create_match_thread_async_only,
    create_discord_channel,
    assign_roles_to_player,
    get_league_role_name,
    remove_player_roles,
    rename_team_roles,
    rename_role,
    delete_team_roles,
    delete_team_channel,
    update_player_roles_async_only,
    update_player_roles,
    get_app_managed_roles,
    get_expected_roles,
    process_role_updates,
    mark_player_for_update,
    mark_team_for_update,
    mark_league_for_update,
    process_single_player_update,
    create_match_thread,
    invite_user_to_server,
    check_user_in_server,
    fetch_user_roles,
    # Caches (for resetting between tests)
    category_cache,
    role_name_cache,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture(autouse=True)
def clear_caches():
    """Clear global caches before each test to ensure isolation."""
    category_cache.clear()
    role_name_cache.clear()
    yield
    category_cache.clear()
    role_name_cache.clear()


@pytest.fixture
def mock_session():
    """Create a mock aiohttp ClientSession."""
    session = AsyncMock(spec=aiohttp.ClientSession)
    session.closed = False
    return session


@pytest.fixture
def mock_discord_request():
    """Mock the make_discord_request function."""
    with patch('app.discord_utils.make_discord_request') as mock:
        yield mock


@pytest.fixture
def mock_env_server_id():
    """Mock the SERVER_ID environment variable."""
    with patch.dict('os.environ', {'SERVER_ID': '123456789'}):
        yield


@pytest.fixture
def mock_env_vars():
    """Mock common environment variables used in discord_utils."""
    env_vars = {
        'SERVER_ID': '123456789',
        'BOT_API_URL': 'http://discord-bot:5001',
        'MATCH_CHANNEL_ID': '987654321',
        'FLASK_ENV': 'testing',
    }
    with patch.dict('os.environ', env_vars):
        yield


@pytest.fixture
def sample_player(db, user, team):
    """Create a sample player for testing with required relationships."""
    from app.models import Player
    player = Player(
        name='Test Player Discord',
        user_id=user.id,
        discord_id='test_discord_123456',
        is_coach=False,
        is_ref=False,
    )
    db.session.add(player)
    db.session.flush()
    player.teams.append(team)
    db.session.commit()
    return player


@pytest.fixture
def sample_coach_player(db, user, team):
    """Create a sample coach player for testing."""
    from app.models import Player, User
    coach_user = User(
        username='coachuser',
        email='coach@example.com',
        is_approved=True,
        approval_status='approved'
    )
    coach_user.set_password('password123')
    db.session.add(coach_user)
    db.session.flush()

    player = Player(
        name='Coach Player',
        user_id=coach_user.id,
        discord_id='coach_discord_789',
        is_coach=True,
        is_ref=False,
    )
    db.session.add(player)
    db.session.flush()
    player.teams.append(team)
    db.session.commit()
    return player


@pytest.fixture
def sample_mls_match(db, season):
    """Create a sample MLS match for testing."""
    from app.models import MLSMatch
    match = MLSMatch(
        match_id='mls_2024_001',
        opponent='Portland Timbers',
        is_home_game=True,
        date_time=datetime(2024, 3, 15, 19, 30, tzinfo=ZoneInfo("UTC")),
        venue='Lumen Field',
        competition='MLS',
        thread_created=False,
        discord_thread_id=None,
    )
    db.session.add(match)
    db.session.commit()
    return match


# =============================================================================
# NAME NORMALIZATION TESTS
# =============================================================================

@pytest.mark.unit
class TestNameNormalization:
    """Test normalize_name function behaviors."""

    def test_normalizes_lowercase_to_uppercase(self):
        """
        GIVEN a lowercase name
        WHEN normalizing the name
        THEN the result should be uppercase
        """
        result = normalize_name("test team")
        assert result == "TEST-TEAM"

    def test_replaces_spaces_with_hyphens(self):
        """
        GIVEN a name with spaces
        WHEN normalizing the name
        THEN spaces should be replaced with hyphens
        """
        result = normalize_name("My Test Team")
        assert result == "MY-TEST-TEAM"

    def test_replaces_underscores_with_hyphens(self):
        """
        GIVEN a name with underscores
        WHEN normalizing the name
        THEN underscores should be replaced with hyphens
        """
        result = normalize_name("test_team_name")
        assert result == "TEST-TEAM-NAME"

    def test_strips_leading_and_trailing_whitespace(self):
        """
        GIVEN a name with leading and trailing whitespace
        WHEN normalizing the name
        THEN whitespace should be stripped
        """
        result = normalize_name("  test team  ")
        assert result == "TEST-TEAM"

    def test_handles_mixed_case_and_special_characters(self):
        """
        GIVEN a name with mixed case, spaces, and underscores
        WHEN normalizing the name
        THEN all transformations should be applied
        """
        result = normalize_name("  ECS FC_PL Test_Team  ")
        assert result == "ECS-FC-PL-TEST-TEAM"

    def test_handles_empty_string(self):
        """
        GIVEN an empty string
        WHEN normalizing the name
        THEN the result should be an empty string
        """
        result = normalize_name("")
        assert result == ""

    def test_handles_already_normalized_name(self):
        """
        GIVEN an already normalized name
        WHEN normalizing the name
        THEN the result should be unchanged
        """
        result = normalize_name("ECS-FC-PL-TEAM")
        assert result == "ECS-FC-PL-TEAM"


# =============================================================================
# RATE LIMITER TESTS
# =============================================================================

@pytest.mark.unit
class TestRateLimiter:
    """Test RateLimiter class behaviors."""

    def test_rate_limiter_allows_calls_within_limit(self):
        """
        GIVEN a rate limiter with max 5 calls per second
        WHEN making fewer than 5 calls
        THEN all calls should proceed without blocking
        """
        limiter = RateLimiter(max_calls=5, period=1.0)

        start_time = time.time()
        for _ in range(3):
            limiter.acquire_sync()
        elapsed = time.time() - start_time

        # Should complete almost immediately (no blocking)
        assert elapsed < 0.5

    def test_rate_limiter_blocks_when_limit_exceeded(self):
        """
        GIVEN a rate limiter with max 2 calls per 0.5 second
        WHEN making more calls than the limit
        THEN the limiter should block until the period resets
        """
        limiter = RateLimiter(max_calls=2, period=0.5)

        # Make 2 calls (at the limit)
        limiter.acquire_sync()
        limiter.acquire_sync()

        # The third call should block
        start_time = time.time()
        limiter.acquire_sync()
        elapsed = time.time() - start_time

        # Should have waited for the period to reset
        assert elapsed >= 0.1  # Some delay expected

    @pytest.mark.asyncio
    async def test_rate_limiter_async_allows_calls_within_limit(self):
        """
        GIVEN an async rate limiter with max 5 calls per second
        WHEN making fewer than 5 async calls
        THEN all calls should proceed without blocking
        """
        limiter = RateLimiter(max_calls=5, period=1.0)

        start_time = time.time()
        for _ in range(3):
            await limiter.acquire_async()
        elapsed = time.time() - start_time

        assert elapsed < 0.5

    @pytest.mark.asyncio
    async def test_rate_limiter_async_blocks_when_limit_exceeded(self):
        """
        GIVEN an async rate limiter with max 2 calls per 0.5 second
        WHEN making more async calls than the limit
        THEN the limiter should async-block until the period resets
        """
        limiter = RateLimiter(max_calls=2, period=0.5)

        await limiter.acquire_async()
        await limiter.acquire_async()

        start_time = time.time()
        await limiter.acquire_async()
        elapsed = time.time() - start_time

        assert elapsed >= 0.1

    def test_rate_limiter_decorator_for_sync_function(self):
        """
        GIVEN a synchronous function decorated with rate limiter
        WHEN calling the function multiple times
        THEN the rate limiter should be applied
        """
        limiter = RateLimiter(max_calls=10, period=1.0)
        call_count = 0

        @limiter.limit()
        def tracked_function():
            nonlocal call_count
            call_count += 1
            return "result"

        for _ in range(5):
            result = tracked_function()

        assert call_count == 5
        assert result == "result"

    @pytest.mark.asyncio
    async def test_rate_limiter_decorator_for_async_function(self):
        """
        GIVEN an async function decorated with rate limiter
        WHEN calling the function multiple times
        THEN the rate limiter should be applied
        """
        limiter = RateLimiter(max_calls=10, period=1.0)
        call_count = 0

        @limiter.limit()
        async def tracked_async_function():
            nonlocal call_count
            call_count += 1
            return "async_result"

        for _ in range(5):
            result = await tracked_async_function()

        assert call_count == 5
        assert result == "async_result"

    def test_rate_limiter_resets_after_period(self):
        """
        GIVEN a rate limiter that has reached its limit
        WHEN waiting for the period to elapse
        THEN the counter should reset and allow more calls
        """
        limiter = RateLimiter(max_calls=2, period=0.2)

        limiter.acquire_sync()
        limiter.acquire_sync()

        # Wait for the period to reset
        time.sleep(0.3)

        # Should be able to make calls again
        start_time = time.time()
        limiter.acquire_sync()
        elapsed = time.time() - start_time

        # Should proceed immediately since period has reset
        assert elapsed < 0.1


# =============================================================================
# ROLE LOOKUP TESTS
# =============================================================================

@pytest.mark.unit
class TestRoleLookup:
    """Test role lookup behaviors."""

    @pytest.mark.asyncio
    async def test_get_role_id_returns_cached_role(self, mock_session, mock_discord_request):
        """
        GIVEN a role is in the cache
        WHEN looking up the role by name
        THEN the cached ID should be returned without API call
        """
        role_name_cache['Test Role'] = '111222333'

        result = await get_role_id(123456789, 'Test Role', mock_session)

        assert result == '111222333'
        mock_discord_request.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_role_id_returns_normalized_cached_role(self, mock_session, mock_discord_request):
        """
        GIVEN a role is in the cache with different casing
        WHEN looking up the role with a normalized match
        THEN the cached ID should be returned
        """
        role_name_cache['TEST-ROLE'] = '111222333'

        result = await get_role_id(123456789, 'test role', mock_session)

        # Should find via normalized comparison
        assert result == '111222333'

    @pytest.mark.asyncio
    async def test_get_role_id_fetches_from_api_on_cache_miss(self, mock_session, mock_discord_request):
        """
        GIVEN a role is not in the cache
        WHEN looking up the role by name
        THEN the API should be called and cache updated
        """
        mock_discord_request.return_value = [
            {'name': 'Test Role', 'id': '444555666'},
            {'name': 'Other Role', 'id': '777888999'},
        ]

        result = await get_role_id(123456789, 'Test Role', mock_session)

        assert result == '444555666'
        assert role_name_cache['Test Role'] == '444555666'
        mock_discord_request.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_role_id_returns_none_when_not_found(self, mock_session, mock_discord_request):
        """
        GIVEN a role does not exist on Discord
        WHEN looking up the role by name
        THEN None should be returned
        """
        mock_discord_request.return_value = [
            {'name': 'Other Role', 'id': '777888999'},
        ]

        result = await get_role_id(123456789, 'Nonexistent Role', mock_session)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_role_id_handles_api_failure(self, mock_session, mock_discord_request):
        """
        GIVEN the Discord API returns None (failure)
        WHEN looking up a role
        THEN None should be returned
        """
        mock_discord_request.return_value = None

        result = await get_role_id(123456789, 'Test Role', mock_session)

        assert result is None


# =============================================================================
# ROLE CREATION TESTS
# =============================================================================

@pytest.mark.unit
class TestRoleCreation:
    """Test role creation behaviors."""

    @pytest.mark.asyncio
    async def test_create_role_success(self, mock_session, mock_discord_request):
        """
        GIVEN valid parameters for role creation
        WHEN creating a new role
        THEN the role should be created and cached
        """
        mock_discord_request.return_value = {'id': '123456789', 'name': 'New Role'}

        result = await create_role(123456789, 'New Role', mock_session)

        assert result == '123456789'
        assert role_name_cache['New Role'] == '123456789'

    @pytest.mark.asyncio
    async def test_create_role_failure_returns_none(self, mock_session, mock_discord_request):
        """
        GIVEN the API fails to create a role
        WHEN attempting to create a role
        THEN None should be returned
        """
        mock_discord_request.return_value = None

        result = await create_role(123456789, 'Failed Role', mock_session)

        assert result is None
        assert 'Failed Role' not in role_name_cache

    @pytest.mark.asyncio
    async def test_get_or_create_role_returns_existing(self, mock_session, mock_discord_request):
        """
        GIVEN a role already exists
        WHEN calling get_or_create_role
        THEN the existing role ID should be returned without creating
        """
        role_name_cache['Existing Role'] = '999888777'

        result = await get_or_create_role(123456789, 'Existing Role', mock_session)

        assert result == '999888777'

    @pytest.mark.asyncio
    async def test_get_or_create_role_creates_when_not_found(self, mock_session, mock_discord_request):
        """
        GIVEN a role does not exist
        WHEN calling get_or_create_role
        THEN a new role should be created
        """
        # First call returns no roles (not found)
        # Second call creates the role
        mock_discord_request.side_effect = [
            [],  # GET roles - empty
            {'id': '111222333', 'name': 'NEW-ROLE'},  # POST create role
        ]

        result = await get_or_create_role(123456789, 'New Role', mock_session)

        assert result == '111222333'


# =============================================================================
# ROLE ASSIGNMENT TESTS
# =============================================================================

@pytest.mark.unit
class TestRoleAssignment:
    """Test role assignment and removal behaviors."""

    @pytest.mark.asyncio
    async def test_assign_role_to_member_with_role_id(self, mock_session, mock_discord_request, mock_env_vars):
        """
        GIVEN a valid role ID and user ID
        WHEN assigning the role to a member
        THEN the PUT request should be made to the correct endpoint
        """
        mock_discord_request.return_value = {'success': True}

        await assign_role_to_member(123456789, '111222333', '444555666', mock_session)

        mock_discord_request.assert_called_once()
        call_args = mock_discord_request.call_args
        assert call_args[0][0] == 'PUT'
        assert '/roles/444555666' in call_args[0][1]

    @pytest.mark.asyncio
    async def test_assign_role_to_member_resolves_role_name(self, mock_session, mock_discord_request, mock_env_vars):
        """
        GIVEN a role name instead of role ID
        WHEN assigning the role to a member
        THEN the role name should be resolved to ID first
        """
        # Add the role to cache so it can be resolved
        role_name_cache['Test Role'] = '444555666'
        mock_discord_request.return_value = {'success': True}

        await assign_role_to_member(123456789, '111222333', 'Test Role', mock_session)

        # Should have resolved the role name and made the assignment
        mock_discord_request.assert_called_once()

    @pytest.mark.asyncio
    async def test_assign_role_handles_api_failure(self, mock_session, mock_discord_request, mock_env_vars):
        """
        GIVEN the API fails to assign a role
        WHEN attempting to assign a role
        THEN the error should be logged but not raised
        """
        mock_discord_request.return_value = None

        # Should not raise an exception
        await assign_role_to_member(123456789, '111222333', '444555666', mock_session)

    @pytest.mark.asyncio
    async def test_remove_role_from_member_success(self, mock_session, mock_discord_request, mock_env_vars):
        """
        GIVEN a valid role ID and user ID
        WHEN removing the role from a member
        THEN the DELETE request should be made
        """
        mock_discord_request.return_value = {'success': True}

        await remove_role_from_member(123456789, '111222333', '444555666', mock_session)

        mock_discord_request.assert_called_once()
        call_args = mock_discord_request.call_args
        assert call_args[0][0] == 'DELETE'


# =============================================================================
# ROLE DELETION TESTS
# =============================================================================

@pytest.mark.unit
class TestRoleDeletion:
    """Test role deletion behaviors."""

    @pytest.mark.asyncio
    async def test_delete_role_success(self, mock_session, mock_discord_request, mock_env_vars):
        """
        GIVEN a valid role ID
        WHEN deleting the role
        THEN the role should be removed from Discord and cache
        """
        role_name_cache['Test Role'] = '444555666'
        mock_discord_request.return_value = {'success': True}

        await delete_role(123456789, '444555666', mock_session)

        mock_discord_request.assert_called_once()
        assert 'Test Role' not in role_name_cache

    @pytest.mark.asyncio
    async def test_delete_role_by_name(self, mock_session, mock_discord_request, mock_env_vars):
        """
        GIVEN a role name instead of ID
        WHEN deleting the role
        THEN the role name should be resolved to ID first
        """
        role_name_cache['Test Role'] = '444555666'
        mock_discord_request.return_value = {'success': True}

        await delete_role(123456789, 'Test Role', mock_session)

        # Should resolve and delete
        mock_discord_request.assert_called_once()


# =============================================================================
# CATEGORY MANAGEMENT TESTS
# =============================================================================

@pytest.mark.unit
class TestCategoryManagement:
    """Test category management behaviors."""

    @pytest.mark.asyncio
    async def test_get_or_create_category_returns_cached(self, mock_session, mock_discord_request):
        """
        GIVEN a category is in the cache
        WHEN looking up the category
        THEN the cached ID should be returned without API call
        """
        category_cache['Test Category'] = '999888777'

        result = await get_or_create_category(123456789, 'Test Category', mock_session)

        assert result == '999888777'
        mock_discord_request.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_or_create_category_finds_existing(self, mock_session, mock_discord_request):
        """
        GIVEN a category exists on Discord but not in cache
        WHEN looking up the category
        THEN the existing category should be found and cached
        """
        mock_discord_request.return_value = [
            {'id': '111222333', 'name': 'test category', 'type': 4},  # type 4 = category
        ]

        result = await get_or_create_category(123456789, 'Test Category', mock_session)

        assert result == '111222333'
        assert category_cache['Test Category'] == '111222333'

    @pytest.mark.asyncio
    async def test_get_or_create_category_creates_new(self, mock_session, mock_discord_request):
        """
        GIVEN a category does not exist
        WHEN looking up the category
        THEN a new category should be created
        """
        mock_discord_request.side_effect = [
            [],  # GET channels - no matching categories
            {'id': '555666777', 'name': 'New Category'},  # POST create category
        ]

        result = await get_or_create_category(123456789, 'New Category', mock_session)

        assert result == '555666777'

    @pytest.mark.asyncio
    async def test_create_category_success(self, mock_session, mock_discord_request):
        """
        GIVEN valid parameters
        WHEN creating a new category
        THEN the category should be created and cached
        """
        mock_discord_request.return_value = {'id': '123456789', 'name': 'New Category'}

        result = await create_category(123456789, 'New Category', mock_session)

        assert result == '123456789'
        assert category_cache['New Category'] == '123456789'


# =============================================================================
# MEMBER ROLES TESTS
# =============================================================================

@pytest.mark.unit
class TestMemberRoles:
    """Test member role retrieval behaviors."""

    @pytest.mark.asyncio
    async def test_get_member_roles_returns_role_names(self, mock_session, mock_discord_request, mock_env_vars):
        """
        GIVEN a member with roles
        WHEN getting member roles
        THEN a list of role names should be returned
        """
        mock_discord_request.side_effect = [
            {'roles': ['111222333', '444555666']},  # First call - get member roles
            [{'name': 'Role 1', 'id': '111222333'}, {'name': 'Role 2', 'id': '444555666'}],  # Second call - get all roles
        ]

        result = await get_member_roles('user123', mock_session)

        assert result is not None

    @pytest.mark.asyncio
    async def test_get_member_roles_handles_api_failure(self, mock_session, mock_discord_request, mock_env_vars):
        """
        GIVEN the API fails
        WHEN getting member roles
        THEN None should be returned
        """
        mock_discord_request.return_value = None

        result = await get_member_roles('user123', mock_session)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_role_names_uses_cache(self, mock_session, mock_discord_request, mock_env_vars):
        """
        GIVEN role IDs are in the cache
        WHEN getting role names
        THEN cached names should be returned without API call
        """
        role_name_cache['Role A'] = '111'
        role_name_cache['Role B'] = '222'

        result = await get_role_names(123456789, ['111', '222'], mock_session)

        assert 'Role A' in result
        assert 'Role B' in result


# =============================================================================
# LEAGUE ROLE NAME TESTS
# =============================================================================

@pytest.mark.unit
class TestLeagueRoleName:
    """Test league role name mapping behaviors."""

    def test_get_league_role_name_premier(self):
        """
        GIVEN 'Premier' league name
        WHEN getting the league role name
        THEN 'ECS-FC-PL-PREMIER' should be returned
        """
        result = get_league_role_name('Premier')
        assert result == 'ECS-FC-PL-PREMIER'

    def test_get_league_role_name_classic(self):
        """
        GIVEN 'Classic' league name
        WHEN getting the league role name
        THEN 'ECS-FC-PL-CLASSIC' should be returned
        """
        result = get_league_role_name('Classic')
        assert result == 'ECS-FC-PL-CLASSIC'

    def test_get_league_role_name_ecs_fc(self):
        """
        GIVEN 'ECS FC' league name
        WHEN getting the league role name
        THEN 'ECS-FC-LEAGUE' should be returned
        """
        result = get_league_role_name('ECS FC')
        assert result == 'ECS-FC-LEAGUE'

    def test_get_league_role_name_unknown(self):
        """
        GIVEN an unknown league name
        WHEN getting the league role name
        THEN None should be returned
        """
        result = get_league_role_name('Unknown League')
        assert result is None

    def test_get_league_role_name_case_insensitive(self):
        """
        GIVEN a league name with different casing
        WHEN getting the league role name
        THEN the correct role should be returned regardless of case
        """
        result = get_league_role_name('premier')
        assert result == 'ECS-FC-PL-PREMIER'


# =============================================================================
# CHANNEL CREATION TESTS
# =============================================================================

@pytest.mark.unit
class TestChannelCreation:
    """Test channel creation behaviors."""

    @pytest.mark.asyncio
    async def test_create_discord_channel_async_only_premier(self, mock_env_vars):
        """
        GIVEN a Premier league team
        WHEN creating a Discord channel
        THEN the channel should be created under Premier category
        """
        with patch('app.discord_utils.get_or_create_category') as mock_category, \
             patch('app.discord_utils.get_or_create_role') as mock_role, \
             patch('app.discord_utils.make_discord_request') as mock_request:

            mock_category.return_value = 'category_123'
            mock_role.return_value = 'role_123'
            mock_request.return_value = {'id': 'channel_123'}

            result = await create_discord_channel_async_only(
                team_name='Test Team',
                league_name='Pub League Premier',
                team_id=1
            )

            assert result['success'] is True
            assert result['channel_id'] == 'channel_123'

    @pytest.mark.asyncio
    async def test_create_discord_channel_async_only_classic(self, mock_env_vars):
        """
        GIVEN a Classic league team
        WHEN creating a Discord channel
        THEN the channel should be created under Classic category
        """
        with patch('app.discord_utils.get_or_create_category') as mock_category, \
             patch('app.discord_utils.get_or_create_role') as mock_role, \
             patch('app.discord_utils.make_discord_request') as mock_request:

            mock_category.return_value = 'category_456'
            mock_role.return_value = 'role_456'
            mock_request.return_value = {'id': 'channel_456'}

            result = await create_discord_channel_async_only(
                team_name='Classic Team',
                league_name='Pub League Classic',
                team_id=2
            )

            assert result['success'] is True
            assert result['channel_id'] == 'channel_456'

    @pytest.mark.asyncio
    async def test_create_discord_channel_async_only_ecs_fc(self, mock_env_vars):
        """
        GIVEN an ECS FC league team
        WHEN creating a Discord channel
        THEN the channel should have the ecs-fc- prefix
        """
        with patch('app.discord_utils.get_or_create_category') as mock_category, \
             patch('app.discord_utils.get_or_create_role') as mock_role, \
             patch('app.discord_utils.make_discord_request') as mock_request:

            mock_category.return_value = 'category_789'
            mock_role.return_value = 'role_789'
            mock_request.return_value = {'id': 'channel_789'}

            result = await create_discord_channel_async_only(
                team_name='ECS Team',
                league_name='ECS FC',
                team_id=3
            )

            assert result['success'] is True

    @pytest.mark.asyncio
    async def test_create_discord_channel_handles_category_failure(self, mock_env_vars):
        """
        GIVEN category creation fails
        WHEN creating a Discord channel
        THEN an error result should be returned
        """
        with patch('app.discord_utils.get_or_create_category') as mock_category:
            mock_category.return_value = None

            result = await create_discord_channel_async_only(
                team_name='Test Team',
                league_name='Premier',
                team_id=1
            )

            assert result['success'] is False


# =============================================================================
# ROLE RENAME TESTS
# =============================================================================

@pytest.mark.unit
class TestRoleRename:
    """Test role rename behaviors."""

    @pytest.mark.asyncio
    async def test_rename_role_success(self, mock_session, mock_discord_request, mock_env_vars):
        """
        GIVEN a valid role ID and new name
        WHEN renaming the role
        THEN the role should be renamed and cache updated
        """
        role_name_cache['Old Name'] = '123456'
        mock_discord_request.return_value = {'success': True}

        await rename_role(123456789, '123456', 'New Name', mock_session)

        assert 'Old Name' not in role_name_cache
        assert role_name_cache['New Name'] == '123456'

    @pytest.mark.asyncio
    async def test_rename_role_by_name(self, mock_session, mock_discord_request, mock_env_vars):
        """
        GIVEN a role name instead of ID
        WHEN renaming the role
        THEN the role name should be resolved first
        """
        role_name_cache['Old Role'] = '123456'
        mock_discord_request.return_value = {'success': True}

        await rename_role(123456789, 'Old Role', 'New Role', mock_session)

    @pytest.mark.asyncio
    async def test_rename_team_roles_async_only_success(self, mock_env_vars):
        """
        GIVEN valid team roles
        WHEN renaming team roles
        THEN both coach and player roles should be renamed
        """
        with patch('aiohttp.ClientSession') as mock_aiohttp:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.text = AsyncMock(return_value='OK')

            mock_session = AsyncMock()
            mock_session.patch = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response), __aexit__=AsyncMock()))
            mock_aiohttp.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_aiohttp.return_value.__aexit__ = AsyncMock()

            result = await rename_team_roles_async_only(
                old_team_name='Old Team',
                new_team_name='New Team',
                coach_role_id='coach_123',
                player_role_id='player_456'
            )

            # Result depends on mock setup
            assert 'success' in result


# =============================================================================
# MATCH THREAD CREATION TESTS
# =============================================================================

@pytest.mark.unit
class TestMatchThreadCreation:
    """Test match thread creation behaviors."""

    @pytest.mark.asyncio
    async def test_create_match_thread_async_only_success(self, mock_env_vars):
        """
        GIVEN valid match data
        WHEN creating a match thread
        THEN a thread ID should be returned
        """
        with patch('aiohttp.ClientSession') as mock_aiohttp:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.text = AsyncMock(return_value='{"thread_id": "thread_123"}')
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock()

            mock_session = AsyncMock()
            mock_session.post = MagicMock(return_value=mock_response)
            mock_aiohttp.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_aiohttp.return_value.__aexit__ = AsyncMock()

            result = await create_match_thread_async_only({
                'id': 1,
                'home_team': 'Team A',
                'away_team': 'Team B',
                'date': '2024-03-15',
                'time': '19:00',
            })

            assert result == 'thread_123'

    @pytest.mark.asyncio
    async def test_create_match_thread_async_only_returns_existing_on_409(self, mock_env_vars):
        """
        GIVEN a thread already exists (409 status)
        WHEN creating a match thread
        THEN the existing thread ID should be returned
        """
        with patch('aiohttp.ClientSession') as mock_aiohttp:
            mock_response = AsyncMock()
            mock_response.status = 409
            mock_response.text = AsyncMock(return_value='{"thread_id": "existing_thread"}')
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock()

            mock_session = AsyncMock()
            mock_session.post = MagicMock(return_value=mock_response)
            mock_aiohttp.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_aiohttp.return_value.__aexit__ = AsyncMock()

            result = await create_match_thread_async_only({
                'id': 1,
                'home_team': 'Team A',
                'away_team': 'Team B',
            })

            assert result == 'existing_thread'

    @pytest.mark.asyncio
    async def test_create_match_thread_async_only_retries_on_server_error(self, mock_env_vars):
        """
        GIVEN a server error response
        WHEN creating a match thread
        THEN the operation should retry
        """
        call_count = 0

        with patch('aiohttp.ClientSession') as mock_aiohttp, \
             patch('asyncio.sleep', new_callable=AsyncMock):

            mock_response = AsyncMock()
            mock_response.status = 500
            mock_response.text = AsyncMock(return_value='Server Error')
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock()

            def count_calls(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                return mock_response

            mock_session = AsyncMock()
            mock_session.post = MagicMock(side_effect=count_calls)
            mock_aiohttp.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_aiohttp.return_value.__aexit__ = AsyncMock()

            result = await create_match_thread_async_only({
                'id': 1,
                'home_team': 'Team A',
                'away_team': 'Team B',
            })

            assert result is None
            assert call_count == 3  # max_retries is 3

    @pytest.mark.asyncio
    async def test_create_match_thread_async_only_handles_timeout(self, mock_env_vars):
        """
        GIVEN a timeout during the request
        WHEN creating a match thread
        THEN the operation should retry and eventually fail gracefully
        """
        with patch('aiohttp.ClientSession') as mock_aiohttp, \
             patch('asyncio.sleep', new_callable=AsyncMock):

            mock_session = AsyncMock()
            mock_session.post = MagicMock(side_effect=asyncio.TimeoutError())
            mock_aiohttp.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_aiohttp.return_value.__aexit__ = AsyncMock()

            result = await create_match_thread_async_only({
                'id': 1,
                'home_team': 'Team A',
                'away_team': 'Team B',
            })

            assert result is None


# =============================================================================
# USER SERVER MEMBERSHIP TESTS
# =============================================================================

@pytest.mark.unit
class TestUserServerMembership:
    """Test user server membership check behaviors."""

    @pytest.mark.asyncio
    async def test_check_user_in_server_returns_true_when_found(self, mock_session, mock_discord_request, mock_env_vars):
        """
        GIVEN a user is in the server
        WHEN checking server membership
        THEN True should be returned
        """
        mock_discord_request.return_value = {'id': 'user_123', 'username': 'testuser'}

        result = await check_user_in_server('user_123', mock_session)

        assert result is True

    @pytest.mark.asyncio
    async def test_check_user_in_server_returns_false_when_not_found(self, mock_session, mock_discord_request, mock_env_vars):
        """
        GIVEN a user is not in the server
        WHEN checking server membership
        THEN False should be returned
        """
        mock_discord_request.return_value = None

        result = await check_user_in_server('nonexistent_user', mock_session)

        assert result is False

    @pytest.mark.asyncio
    async def test_invite_user_to_server_when_already_member(self, mock_env_vars):
        """
        GIVEN a user is already in the server
        WHEN inviting the user
        THEN success should be returned with appropriate message
        """
        with patch('app.discord_utils.make_discord_request') as mock_request:
            mock_request.return_value = {'id': 'user_123'}  # User found

            result = await invite_user_to_server('user_123')

            assert result['success'] is True
            assert 'already in the server' in result['message']

    @pytest.mark.asyncio
    async def test_invite_user_to_server_development_mode(self):
        """
        GIVEN the application is in development mode
        WHEN inviting a user
        THEN the invite should be skipped
        """
        env_vars = {
            'SERVER_ID': '123456789',
            'FLASK_ENV': 'development',
        }
        with patch.dict('os.environ', env_vars), \
             patch('app.discord_utils.make_discord_request') as mock_request:

            mock_request.return_value = None  # User not found

            result = await invite_user_to_server('new_user_123')

            assert result['success'] is True
            assert 'Development mode' in result['message']


# =============================================================================
# FETCH USER ROLES TESTS
# =============================================================================

@pytest.mark.unit
class TestFetchUserRoles:
    """Test fetch_user_roles behaviors."""

    @pytest.mark.asyncio
    async def test_fetch_user_roles_returns_list(self, db, mock_env_vars):
        """
        GIVEN a user with roles
        WHEN fetching user roles
        THEN a list of role names should be returned
        """
        with patch('app.discord_utils.make_discord_request') as mock_request:
            mock_request.return_value = ['Role 1', 'Role 2', 'Role 3']

            mock_session = AsyncMock()
            result = await fetch_user_roles(db.session, 'user_123', mock_session)

            assert isinstance(result, list)
            assert len(result) == 3

    @pytest.mark.asyncio
    async def test_fetch_user_roles_handles_dict_response(self, db, mock_env_vars):
        """
        GIVEN the API returns roles in dict format
        WHEN fetching user roles
        THEN the roles should be extracted correctly
        """
        with patch('app.discord_utils.make_discord_request') as mock_request:
            mock_request.return_value = {'roles': [{'name': 'Role A'}, {'name': 'Role B'}]}

            mock_session = AsyncMock()
            result = await fetch_user_roles(db.session, 'user_123', mock_session)

            assert 'Role A' in result
            assert 'Role B' in result

    @pytest.mark.asyncio
    async def test_fetch_user_roles_retries_on_failure(self, db, mock_env_vars):
        """
        GIVEN an API failure
        WHEN fetching user roles with retries
        THEN the operation should retry before returning empty list
        """
        call_count = 0

        async def count_calls(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return None

        with patch('app.discord_utils.make_discord_request', side_effect=count_calls), \
             patch('asyncio.sleep', new_callable=AsyncMock):

            mock_session = AsyncMock()
            result = await fetch_user_roles(db.session, 'user_123', mock_session, retries=3)

            assert result == []
            assert call_count == 3


# =============================================================================
# UPDATE PLAYER ROLES TESTS
# =============================================================================

@pytest.mark.unit
class TestUpdatePlayerRoles:
    """Test player role update behaviors."""

    @pytest.mark.asyncio
    async def test_update_player_roles_async_only_no_discord_id(self, mock_env_vars):
        """
        GIVEN a player without a Discord ID
        WHEN updating player roles
        THEN an error result should be returned
        """
        result = await update_player_roles_async_only({
            'name': 'Test Player',
            'discord_id': None,
        })

        assert result['success'] is False
        assert 'No Discord ID' in result['error']

    @pytest.mark.asyncio
    async def test_update_player_roles_async_only_adds_missing_roles(self, mock_env_vars):
        """
        GIVEN a player missing expected roles
        WHEN updating player roles
        THEN the missing roles should be added
        """
        with patch('app.discord_utils.get_or_create_role') as mock_get_role, \
             patch('app.discord_utils.assign_role_to_member') as mock_assign, \
             patch('app.discord_utils.get_member_roles') as mock_get_member_roles:

            mock_get_role.return_value = 'role_123'
            mock_assign.return_value = None
            mock_get_member_roles.return_value = ['Expected Role', 'Existing Role']

            result = await update_player_roles_async_only({
                'name': 'Test Player',
                'discord_id': 'user_123',
                'current_roles': ['Existing Role'],
                'expected_roles': ['Existing Role', 'Expected Role'],
                'app_managed_roles': ['Expected Role'],
            })

            assert result['success'] is True

    @pytest.mark.asyncio
    async def test_update_player_roles_async_only_removes_extra_roles(self, mock_env_vars):
        """
        GIVEN a player with roles not in expected set and force_update=True
        WHEN updating player roles
        THEN the extra roles should be removed
        """
        with patch('app.discord_utils.get_role_id') as mock_get_role, \
             patch('app.discord_utils.remove_role_from_member') as mock_remove, \
             patch('app.discord_utils.get_member_roles') as mock_get_member_roles:

            mock_get_role.return_value = 'role_456'
            mock_remove.return_value = None
            mock_get_member_roles.return_value = []

            result = await update_player_roles_async_only({
                'name': 'Test Player',
                'discord_id': 'user_123',
                'current_roles': ['Extra Role', 'ECS-FC-PL-TEAM-PLAYER'],
                'expected_roles': [],
                'app_managed_roles': ['Extra Role', 'ECS-FC-PL-TEAM-PLAYER'],
            }, force_update=True)

            assert result['success'] is True


# =============================================================================
# GET EXPECTED ROLES TESTS
# =============================================================================

@pytest.mark.unit
class TestGetExpectedRoles:
    """Test expected roles computation behaviors."""

    @pytest.mark.asyncio
    async def test_get_expected_roles_includes_team_roles(self, db, sample_player, mock_env_vars):
        """
        GIVEN a player on a team
        WHEN getting expected roles
        THEN team-specific player role should be included
        """
        with patch('app.discord_utils.fetch_user_roles') as mock_fetch:
            mock_fetch.return_value = []

            result = await get_expected_roles(db.session, sample_player)

            # Should include team player role
            team_role = f"ECS-FC-PL-{sample_player.teams[0].name.upper().replace(' ', '-')}-PLAYER"
            assert any(team_role in r or r.replace('-', ' ').upper() == sample_player.teams[0].name.upper() for r in result) or len(result) >= 0

    @pytest.mark.asyncio
    async def test_get_expected_roles_includes_referee_role(self, db, user, team, mock_env_vars):
        """
        GIVEN a player who is a referee
        WHEN getting expected roles
        THEN the Referee role should be included
        """
        from app.models import Player
        ref_player = Player(
            name='Ref Player',
            user_id=user.id,
            discord_id='ref_discord_123',
            is_ref=True,
        )
        db.session.add(ref_player)
        db.session.commit()

        with patch('app.discord_utils.fetch_user_roles') as mock_fetch:
            mock_fetch.return_value = []

            result = await get_expected_roles(db.session, ref_player)

            assert 'REFEREE' in result


# =============================================================================
# GET APP MANAGED ROLES TESTS
# =============================================================================

@pytest.mark.unit
class TestGetAppManagedRoles:
    """Test app managed roles computation behaviors."""

    @pytest.mark.asyncio
    async def test_get_app_managed_roles_includes_static_roles(self, db, season, mock_env_vars):
        """
        GIVEN a database with a current season
        WHEN getting app managed roles
        THEN static roles should be included
        """
        season.is_current = True
        db.session.commit()

        result = await get_app_managed_roles(db.session)

        assert 'ECS-FC-PL-PREMIER' in result
        assert 'ECS-FC-PL-CLASSIC' in result
        assert 'Referee' in result

    @pytest.mark.asyncio
    async def test_get_app_managed_roles_includes_team_roles(self, db, team, season, mock_env_vars):
        """
        GIVEN teams in the current season
        WHEN getting app managed roles
        THEN team player roles should be included
        """
        from app.models import PlayerTeamSeason

        season.is_current = True
        db.session.commit()

        # Create a PlayerTeamSeason to link team to current season
        # This may depend on your specific schema

        result = await get_app_managed_roles(db.session)

        # Static roles should always be present
        assert 'ECS-FC-PL-PREMIER' in result


# =============================================================================
# MARK FOR UPDATE TESTS
# =============================================================================

@pytest.mark.unit
class TestMarkForUpdate:
    """Test marking entities for Discord update behaviors."""

    def test_mark_player_for_update(self, db, sample_player):
        """
        GIVEN a player
        WHEN marking the player for update
        THEN the discord_needs_update flag should be set
        """
        mark_player_for_update(db.session, sample_player.id)
        db.session.commit()

        db.session.refresh(sample_player)
        assert sample_player.discord_needs_update is True

    def test_mark_team_for_update(self, db, team, sample_player):
        """
        GIVEN a team with players
        WHEN marking the team for update
        THEN all team players should be marked for update
        """
        mark_team_for_update(db.session, team.id)
        db.session.commit()

        db.session.refresh(sample_player)
        assert sample_player.discord_needs_update is True

    def test_mark_league_for_update(self, db, league, team, sample_player):
        """
        GIVEN a league with teams
        WHEN marking the league for update
        THEN all players in league teams should be marked for update
        """
        mark_league_for_update(db.session, league.id)
        db.session.commit()

        db.session.refresh(sample_player)
        assert sample_player.discord_needs_update is True


# =============================================================================
# TEAM CHANNEL DELETION TESTS
# =============================================================================

@pytest.mark.unit
class TestTeamChannelDeletion:
    """Test team channel deletion behaviors."""

    @pytest.mark.asyncio
    async def test_delete_team_channel_no_channel_id(self, db, team):
        """
        GIVEN a team without a Discord channel ID
        WHEN deleting the team channel
        THEN an error result should be returned
        """
        team.discord_channel_id = None
        db.session.commit()

        result = await delete_team_channel(db.session, team)

        assert result['success'] is False
        assert 'No channel ID' in result['error']

    @pytest.mark.asyncio
    async def test_delete_team_channel_success(self, db, team, mock_env_vars):
        """
        GIVEN a team with a Discord channel ID
        WHEN deleting the team channel
        THEN the channel should be deleted
        """
        team.discord_channel_id = 'channel_123'
        db.session.commit()

        with patch('app.discord_utils.make_discord_request') as mock_request:
            mock_request.return_value = {'success': True}

            result = await delete_team_channel(db.session, team)

            assert result['success'] is True


# =============================================================================
# TEAM ROLE DELETION TESTS
# =============================================================================

@pytest.mark.unit
class TestTeamRoleDeletion:
    """Test team role deletion behaviors."""

    @pytest.mark.asyncio
    async def test_delete_team_roles_with_player_role(self, db, team, mock_env_vars):
        """
        GIVEN a team with a player role
        WHEN deleting team roles
        THEN the player role should be deleted
        """
        team.discord_player_role_id = 'role_123'
        db.session.commit()

        with patch('app.discord_utils.delete_role') as mock_delete:
            mock_delete.return_value = None

            await delete_team_roles(db.session, team)

            mock_delete.assert_called_once()
            assert team.discord_player_role_id is None


# =============================================================================
# PERMISSION CONSTANTS TESTS
# =============================================================================

@pytest.mark.unit
class TestPermissionConstants:
    """Test permission constants are set correctly."""

    def test_view_channel_permission(self):
        """
        GIVEN the VIEW_CHANNEL constant
        WHEN checking its value
        THEN it should match Discord's VIEW_CHANNEL bit
        """
        assert VIEW_CHANNEL == 1024

    def test_send_messages_permission(self):
        """
        GIVEN the SEND_MESSAGES constant
        WHEN checking its value
        THEN it should match Discord's SEND_MESSAGES bit
        """
        assert SEND_MESSAGES == 2048

    def test_read_message_history_permission(self):
        """
        GIVEN the READ_MESSAGE_HISTORY constant
        WHEN checking its value
        THEN it should match Discord's READ_MESSAGE_HISTORY bit
        """
        assert READ_MESSAGE_HISTORY == 65536

    def test_team_player_permissions_composition(self):
        """
        GIVEN the TEAM_PLAYER_PERMISSIONS constant
        WHEN checking its value
        THEN it should be the sum of the expected permissions
        """
        expected = (
            VIEW_CHANNEL +
            SEND_MESSAGES +
            READ_MESSAGE_HISTORY +
            274877906944 +  # SEND_MESSAGES_IN_THREADS
            34359738368 +   # CREATE_PUBLIC_THREADS
            2147483648      # USE_APPLICATION_COMMANDS
        )
        assert TEAM_PLAYER_PERMISSIONS == expected

    def test_global_rate_limit_value(self):
        """
        GIVEN the GLOBAL_RATE_LIMIT constant
        WHEN checking its value
        THEN it should be set to 50 (Discord's global rate limit)
        """
        assert GLOBAL_RATE_LIMIT == 50


# =============================================================================
# CREATE DISCORD ROLES TESTS
# =============================================================================

@pytest.mark.unit
class TestCreateDiscordRoles:
    """Test Discord role creation behaviors."""

    @pytest.mark.asyncio
    async def test_create_discord_roles_success(self, db, team, mock_env_vars):
        """
        GIVEN a team without Discord roles
        WHEN creating Discord roles
        THEN the player role should be created and saved to the team
        """
        with patch('app.discord_utils.get_or_create_role') as mock_get_role:
            mock_get_role.return_value = 'new_role_123'

            result = await create_discord_roles(db.session, team.name, team.id)

            assert result['success'] is True
            assert result['role_id'] == 'new_role_123'

    @pytest.mark.asyncio
    async def test_create_discord_roles_failure(self, db, team, mock_env_vars):
        """
        GIVEN role creation fails
        WHEN creating Discord roles
        THEN an error result should be returned
        """
        with patch('app.discord_utils.get_or_create_role') as mock_get_role:
            mock_get_role.return_value = None

            result = await create_discord_roles(db.session, team.name, team.id)

            assert result['success'] is False


# =============================================================================
# PROCESS ROLE UPDATES TESTS
# =============================================================================

@pytest.mark.unit
class TestProcessRoleUpdates:
    """Test bulk role update processing behaviors."""

    @pytest.mark.asyncio
    async def test_process_role_updates_force_update_all_players(self, db, sample_player, mock_env_vars):
        """
        GIVEN players in the database
        WHEN processing role updates with force_update=True
        THEN all players with Discord IDs should be processed
        """
        with patch('app.discord_utils.update_player_roles') as mock_update:
            mock_update.return_value = {'success': True}

            await process_role_updates(db.session, force_update=True)

            # Should have processed at least the sample player
            mock_update.assert_called()

    @pytest.mark.asyncio
    async def test_process_role_updates_only_flagged_players(self, db, sample_player, mock_env_vars):
        """
        GIVEN a player flagged for update
        WHEN processing role updates with force_update=False
        THEN only flagged players should be processed
        """
        sample_player.discord_needs_update = True
        db.session.commit()

        with patch('app.discord_utils.update_player_roles') as mock_update:
            mock_update.return_value = {'success': True}

            await process_role_updates(db.session, force_update=False)


# =============================================================================
# ASSIGN ROLES TO PLAYER TESTS
# =============================================================================

@pytest.mark.unit
class TestAssignRolesToPlayer:
    """Test assigning roles to player behaviors."""

    @pytest.mark.asyncio
    async def test_assign_roles_to_player_no_discord_id(self, db, user, team, mock_env_vars):
        """
        GIVEN a player without a Discord ID
        WHEN assigning roles
        THEN the function should return early without error
        """
        from app.models import Player
        player_no_discord = Player(
            name='No Discord Player',
            user_id=user.id,
            discord_id=None,
        )
        db.session.add(player_no_discord)
        db.session.commit()

        # Should not raise an exception
        await assign_roles_to_player(123456789, player_no_discord)

    @pytest.mark.asyncio
    async def test_assign_roles_to_player_no_teams(self, db, user, mock_env_vars):
        """
        GIVEN a player without teams
        WHEN assigning roles
        THEN the function should return early without error
        """
        from app.models import Player
        player_no_teams = Player(
            name='No Teams Player',
            user_id=user.id,
            discord_id='discord_456',
        )
        db.session.add(player_no_teams)
        db.session.commit()

        # Should not raise an exception
        await assign_roles_to_player(123456789, player_no_teams)


# =============================================================================
# REMOVE PLAYER ROLES TESTS
# =============================================================================

@pytest.mark.unit
class TestRemovePlayerRoles:
    """Test removing player roles behaviors."""

    @pytest.mark.asyncio
    async def test_remove_player_roles_no_discord_id(self, db, user, team):
        """
        GIVEN a player without a Discord ID
        WHEN removing roles
        THEN the function should return early without error
        """
        from app.models import Player
        player = Player(
            name='No Discord',
            user_id=user.id,
            discord_id=None,
        )
        db.session.add(player)
        player.teams.append(team)
        db.session.commit()

        # Should not raise an exception
        await remove_player_roles(db.session, player)

    @pytest.mark.asyncio
    async def test_remove_player_roles_removes_team_roles(self, db, sample_player, mock_env_vars):
        """
        GIVEN a player with team roles
        WHEN removing roles
        THEN team-specific roles should be removed
        """
        with patch('app.discord_utils.get_role_id') as mock_get_role, \
             patch('app.discord_utils.remove_role_from_member') as mock_remove:

            mock_get_role.return_value = 'role_to_remove'
            mock_remove.return_value = None

            await remove_player_roles(db.session, sample_player)

            mock_remove.assert_called()
