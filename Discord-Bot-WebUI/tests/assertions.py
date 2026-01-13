"""
Behavior-based test assertions.

These assertions test WHAT happens (behavior), not HOW it happens (implementation).
This makes tests resilient to refactoring - they only fail when actual functionality breaks.

Usage:
    from tests.assertions import assert_user_authenticated, assert_api_success

    def test_login_works(client, user):
        response = client.post('/auth/login', data={...})
        assert_login_succeeded(response, client)
"""
import pytest
from typing import Optional, List, Any, Dict


# =============================================================================
# AUTHENTICATION ASSERTIONS
# =============================================================================

def assert_user_authenticated(client):
    """
    Assert that a user session is currently authenticated.

    Tests behavior: User can access a protected resource.
    Does NOT check session internals or specific user IDs.
    """
    # Try to access a protected endpoint
    response = client.get('/players/')
    # Should not be redirected to login (302) or get unauthorized (401)
    assert response.status_code not in (401, 403), \
        f"User should be authenticated but got status {response.status_code}"
    # If we got a redirect, it shouldn't be to login
    if response.status_code in (301, 302, 303, 307, 308):
        location = response.headers.get('Location', '').lower()
        assert 'login' not in location and 'auth' not in location, \
            f"User should be authenticated but was redirected to {location}"


def assert_user_not_authenticated(client):
    """
    Assert that no user session is currently authenticated.

    Tests behavior: User cannot access protected resources.
    """
    response = client.get('/players/')
    # Should be redirected to login or get unauthorized
    is_redirect_to_auth = response.status_code in (301, 302, 303, 307, 308)
    is_unauthorized = response.status_code in (401, 403)

    if is_redirect_to_auth:
        location = response.headers.get('Location', '').lower()
        has_auth_redirect = 'login' in location or 'auth' in location
        assert has_auth_redirect, \
            f"Unauthenticated user should redirect to login, not {location}"
    else:
        assert is_unauthorized, \
            f"Unauthenticated user should get 401/403 or redirect, got {response.status_code}"


def assert_login_succeeded(response, client):
    """
    Assert that a login attempt succeeded.

    Tests behavior: After login, user is authenticated.
    Does NOT check specific redirect URLs or session values.
    """
    # Login typically redirects on success
    assert response.status_code in (200, 301, 302, 303, 307, 308), \
        f"Login should succeed with redirect or 200, got {response.status_code}"

    # The proof is that the user is now authenticated
    assert_user_authenticated(client)


def assert_login_failed(response, client):
    """
    Assert that a login attempt failed.

    Tests behavior: After failed login, user is NOT authenticated.
    Does NOT check specific error messages or response text.
    """
    # User should not be authenticated
    assert_user_not_authenticated(client)


def assert_logout_succeeded(client):
    """
    Assert that logout was successful.

    Tests behavior: After logout, user cannot access protected resources.
    """
    assert_user_not_authenticated(client)


# =============================================================================
# API RESPONSE ASSERTIONS
# =============================================================================

def assert_api_success(response, expected_keys: Optional[List[str]] = None):
    """
    Assert that an API call succeeded.

    Args:
        response: Flask test response
        expected_keys: Optional list of keys that should be in the response data

    Tests behavior: API returned success status and expected data structure.
    Does NOT check exact values or error messages.
    """
    assert response.status_code == 200, \
        f"API should return 200, got {response.status_code}. Response: {response.data[:500]}"

    if expected_keys:
        data = response.get_json()
        assert data is not None, "API should return JSON response"

        # Check in both top level and nested 'data' key
        actual_data = data.get('data', data)

        for key in expected_keys:
            assert key in actual_data, \
                f"Response should contain '{key}'. Got keys: {list(actual_data.keys())}"


def assert_api_error(response, expected_status: Optional[int] = None):
    """
    Assert that an API call returned an error.

    Args:
        response: Flask test response
        expected_status: Optional specific status code to expect

    Tests behavior: API returned error status.
    Does NOT check exact error messages.
    """
    if expected_status:
        assert response.status_code == expected_status, \
            f"API should return {expected_status}, got {response.status_code}"
    else:
        assert response.status_code >= 400, \
            f"API should return error (>=400), got {response.status_code}"


def assert_api_created(response, expected_keys: Optional[List[str]] = None):
    """Assert that an API create operation succeeded (201 Created)."""
    assert response.status_code == 201, \
        f"API create should return 201, got {response.status_code}"

    if expected_keys:
        data = response.get_json()
        actual_data = data.get('data', data) if data else {}
        for key in expected_keys:
            assert key in actual_data


def assert_api_no_content(response):
    """Assert that an API delete/update operation succeeded with no content (204)."""
    assert response.status_code == 204, \
        f"API should return 204 No Content, got {response.status_code}"


def assert_api_unauthorized(response):
    """Assert that an API call was rejected as unauthorized."""
    assert response.status_code == 401, \
        f"API should return 401 Unauthorized, got {response.status_code}"


def assert_api_forbidden(response):
    """Assert that an API call was rejected as forbidden."""
    assert response.status_code == 403, \
        f"API should return 403 Forbidden, got {response.status_code}"


def assert_api_not_found(response):
    """Assert that an API resource was not found."""
    assert response.status_code == 404, \
        f"API should return 404 Not Found, got {response.status_code}"


def assert_api_validation_error(response):
    """Assert that an API call failed validation (400 or 422)."""
    assert response.status_code in (400, 422), \
        f"API should return 400/422 for validation error, got {response.status_code}"


# =============================================================================
# DATABASE STATE ASSERTIONS
# =============================================================================

def assert_rsvp_recorded(user_id: int, match_id: int, expected_available: bool):
    """
    Assert that an RSVP was recorded in the database with expected value.

    Tests behavior: RSVP exists and has correct availability.
    """
    from app.models import Availability

    avail = Availability.query.filter_by(
        user_id=user_id,
        match_id=match_id
    ).first()

    assert avail is not None, \
        f"RSVP should exist for user {user_id}, match {match_id}"
    assert avail.available == expected_available, \
        f"RSVP should be {expected_available}, got {avail.available}"


def assert_rsvp_not_recorded(user_id: int, match_id: int):
    """Assert that no RSVP exists for the given user and match."""
    from app.models import Availability

    avail = Availability.query.filter_by(
        user_id=user_id,
        match_id=match_id
    ).first()

    assert avail is None, \
        f"RSVP should not exist for user {user_id}, match {match_id}"


def assert_user_exists(username: str = None, email: str = None, discord_id: str = None):
    """
    Assert that a user exists with the given identifier.

    At least one identifier must be provided.
    """
    from app.models import User

    query = User.query
    if username:
        query = query.filter_by(username=username)
    if email:
        query = query.filter_by(email=email)
    if discord_id:
        query = query.filter_by(discord_id=discord_id)

    user = query.first()
    assert user is not None, \
        f"User should exist with username={username}, email={email}, discord_id={discord_id}"
    return user


def assert_user_not_exists(username: str = None, email: str = None):
    """Assert that no user exists with the given identifier."""
    from app.models import User

    query = User.query
    if username:
        query = query.filter_by(username=username)
    if email:
        query = query.filter_by(email=email)

    user = query.first()
    assert user is None, \
        f"User should not exist with username={username}, email={email}"


def assert_user_has_role(user, role_name: str):
    """Assert that a user has a specific role."""
    role_names = [r.name for r in user.roles]
    assert role_name in role_names, \
        f"User should have role '{role_name}', has roles: {role_names}"


def assert_user_approved(user):
    """Assert that a user account is approved."""
    # Check common approval patterns
    is_approved = getattr(user, 'is_approved', None) or \
                  getattr(user, 'approved', None) or \
                  getattr(user, 'approval_status', '') == 'approved'
    assert is_approved, f"User {user.username} should be approved"


def assert_user_not_approved(user):
    """Assert that a user account is NOT approved."""
    is_approved = getattr(user, 'is_approved', None) or \
                  getattr(user, 'approved', None) or \
                  getattr(user, 'approval_status', '') == 'approved'
    assert not is_approved, f"User {user.username} should not be approved"


def assert_player_on_team(user_id: int, team_id: int):
    """Assert that a player is assigned to a team."""
    from app.models import Player

    player = Player.query.filter_by(
        user_id=user_id,
        team_id=team_id
    ).first()

    assert player is not None, \
        f"Player should be on team {team_id}"


def assert_player_not_on_team(user_id: int, team_id: int):
    """Assert that a player is NOT assigned to a team."""
    from app.models import Player

    player = Player.query.filter_by(
        user_id=user_id,
        team_id=team_id
    ).first()

    assert player is None, \
        f"Player should not be on team {team_id}"


# =============================================================================
# REDIRECT ASSERTIONS
# =============================================================================

def assert_redirects_to_login(response):
    """Assert that response redirects to a login page."""
    assert response.status_code in (301, 302, 303, 307, 308), \
        f"Should redirect, got status {response.status_code}"

    location = response.headers.get('Location', '').lower()
    assert 'login' in location or 'auth' in location, \
        f"Should redirect to login, redirected to {location}"


def assert_redirects(response):
    """Assert that response is a redirect (any location)."""
    assert response.status_code in (301, 302, 303, 307, 308), \
        f"Should redirect, got status {response.status_code}"


def assert_no_redirect(response):
    """Assert that response is NOT a redirect."""
    assert response.status_code not in (301, 302, 303, 307, 308), \
        f"Should not redirect, got status {response.status_code}"


# =============================================================================
# CONTRACT ASSERTIONS (API Structure)
# =============================================================================

def assert_response_has_structure(response, structure: Dict[str, type]):
    """
    Assert that a JSON response has the expected structure.

    Args:
        response: Flask test response
        structure: Dict mapping key names to expected types
                   e.g., {'id': int, 'name': str, 'items': list}

    This is contract testing - verify shape, not exact values.
    """
    data = response.get_json()
    assert data is not None, "Response should be JSON"

    # Check in both top level and nested 'data' key
    actual_data = data.get('data', data)

    for key, expected_type in structure.items():
        assert key in actual_data, \
            f"Response should have key '{key}'"
        assert isinstance(actual_data[key], expected_type), \
            f"Response['{key}'] should be {expected_type.__name__}, got {type(actual_data[key]).__name__}"


def assert_paginated_response(response, expected_items_key: str = 'items'):
    """
    Assert that a response is a valid paginated response.

    Expects: items list, total count, page number, per_page value
    """
    data = response.get_json()
    actual_data = data.get('data', data) if data else {}

    assert expected_items_key in actual_data, \
        f"Paginated response should have '{expected_items_key}'"
    assert isinstance(actual_data[expected_items_key], list), \
        f"'{expected_items_key}' should be a list"

    # Common pagination fields
    for field in ['total', 'page', 'per_page']:
        if field in actual_data:
            assert isinstance(actual_data[field], int), \
                f"Pagination field '{field}' should be int"


# =============================================================================
# MOCK ASSERTIONS (for external services)
# =============================================================================

def assert_external_service_called(mock_obj, min_times: int = 1):
    """
    Assert that an external service mock was called.

    Tests behavior: Service was invoked (we don't care about exact params).
    """
    assert mock_obj.called, "External service should have been called"
    assert mock_obj.call_count >= min_times, \
        f"External service should be called at least {min_times} time(s), was called {mock_obj.call_count}"


def assert_external_service_not_called(mock_obj):
    """Assert that an external service mock was NOT called."""
    assert not mock_obj.called, \
        f"External service should not have been called, but was called {mock_obj.call_count} time(s)"


# =============================================================================
# SMS/NOTIFICATION ASSERTIONS
# =============================================================================

def assert_sms_sent(sms_helper, to: str = None, contains: str = None):
    """
    Assert that an SMS was sent.

    Args:
        sms_helper: SMSTestHelper instance tracking sent messages
        to: Optional phone number to filter by
        contains: Optional text that should be in the message body
    """
    messages = sms_helper.sent_messages

    if to:
        messages = [m for m in messages if m.get('to') == to]

    if contains:
        messages = [m for m in messages if contains.lower() in m.get('body', '').lower()]

    assert len(messages) > 0, \
        f"SMS should have been sent (to={to}, contains={contains})"


def assert_sms_not_sent(sms_helper, to: str = None):
    """Assert that no SMS was sent (optionally to a specific number)."""
    messages = sms_helper.sent_messages

    if to:
        messages = [m for m in messages if m.get('to') == to]

    assert len(messages) == 0, \
        f"SMS should not have been sent (found {len(messages)} messages)"
