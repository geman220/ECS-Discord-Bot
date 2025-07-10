"""
Contract tests for API endpoints.
Ensures API responses maintain expected structure.
"""
import pytest
from datetime import datetime, timedelta

from tests.factories import UserFactory, MatchFactory, PlayerFactory
from tests.helpers import AuthTestHelper
from tests.contracts import UserContracts, MatchContracts, RSVPContracts


@pytest.mark.contract
class TestAPIContracts:
    """Test API contracts remain stable."""
    
    def test_user_profile_contract(self, client, db):
        """Test user profile API returns expected structure."""
        # Setup: User with stats
        user = UserFactory()
        player = PlayerFactory(user=user)
        
        with AuthTestHelper.authenticated_request(client, user):
            response = client.get('/api/users/profile')
            
            # Verify: Contract matches
            contract = UserContracts.profile_response()
            assert contract.matches_response(response)
            
            # Verify: Data makes sense
            data = response.get_json()['data']
            assert data['id'] == user.id
            assert data['username'] == user.username
            assert isinstance(data['stats']['matches_played'], int)
            assert data['stats']['matches_played'] >= 0
    
    def test_login_success_contract(self, client, db):
        """Test login API returns expected structure on success."""
        user = UserFactory(username='testuser')
        
        response = client.post('/api/auth/login', json={
            'username': 'testuser',
            'password': 'password123'
        })
        
        # Verify: Success contract
        contract = UserContracts.login_success()
        assert contract.matches_response(response)
        
        # Verify: Token provided
        data = response.get_json()['data']
        assert len(data['token']) > 20  # JWT token
    
    def test_login_failure_contract(self, client, db):
        """Test login API returns expected structure on failure."""
        response = client.post('/api/auth/login', json={
            'username': 'nonexistent',
            'password': 'wrongpass'
        })
        
        # Verify: Failure contract
        contract = UserContracts.login_failure()
        assert contract.matches_response(response)
    
    def test_match_list_contract(self, client, db):
        """Test match list API returns paginated results."""
        # Setup: Multiple matches
        user = UserFactory()
        player = PlayerFactory(user=user)
        
        for i in range(15):
            MatchFactory(
                home_team=player.team,
                scheduled_date=datetime.utcnow().date() + timedelta(days=i)
            )
        
        with AuthTestHelper.authenticated_request(client, user):
            response = client.get('/api/matches?page=1&per_page=10')
            
            # Verify: Contract matches
            contract = MatchContracts.match_list()
            assert contract.matches_response(response)
            
            # Verify: Pagination works
            data = response.get_json()['data']
            assert len(data['matches']) == 10
            assert data['total'] == 15
            assert data['page'] == 1
            assert data['per_page'] == 10
    
    def test_match_detail_contract(self, client, db):
        """Test match detail API returns expected structure."""
        user = UserFactory()
        player = PlayerFactory(user=user)
        match = MatchFactory(home_team=player.team)
        
        with AuthTestHelper.authenticated_request(client, user):
            response = client.get(f'/api/matches/{match.id}')
            
            # Verify: Contract matches
            contract = MatchContracts.match_detail()
            assert contract.matches_response(response)
            
            # Verify: Data accuracy
            data = response.get_json()['data']
            assert data['id'] == match.id
            assert data['home_team']['id'] == match.home_team_id
            assert data['away_team']['id'] == match.away_team_id
    
    def test_rsvp_submission_contract(self, client, db):
        """Test RSVP API returns expected structure."""
        user = UserFactory()
        player = PlayerFactory(user=user)
        match = MatchFactory(home_team=player.team)
        
        with AuthTestHelper.authenticated_request(client, user):
            response = client.post('/api/rsvp', json={
                'match_id': match.id,
                'available': True
            })
            
            # Verify: Contract matches
            contract = RSVPContracts.rsvp_success()
            assert contract.matches_response(response)
            
            # Verify: Timestamp format
            data = response.get_json()['data']
            # Should be ISO format
            datetime.fromisoformat(data['updated_at'].replace('Z', '+00:00'))
    
    def test_team_rsvp_list_contract(self, client, db):
        """Test team RSVP list API returns expected structure."""
        # Setup: Captain viewing team RSVPs
        captain = UserFactory()
        team = TeamFactory(captain=captain)
        match = MatchFactory(home_team=team)
        
        # Create team with mixed responses
        for i in range(11):
            player = PlayerFactory(team=team)
            if i < 7:  # 7 available
                from tests.helpers import MatchTestHelper
                MatchTestHelper.create_rsvp(player.user, match, available=True)
            elif i < 9:  # 2 unavailable
                MatchTestHelper.create_rsvp(player.user, match, available=False)
            # 2 no response
        
        with AuthTestHelper.authenticated_request(client, captain):
            response = client.get(f'/api/matches/{match.id}/rsvps')
            
            # Verify: Contract matches
            contract = RSVPContracts.rsvp_list()
            assert contract.matches_response(response)
            
            # Verify: Counts correct
            data = response.get_json()['data']
            assert data['available_count'] == 7
            assert data['unavailable_count'] == 2
            assert data['no_response_count'] == 2
    
    def test_api_versioning_header(self, client, db):
        """Test API includes version header."""
        user = UserFactory()
        
        with AuthTestHelper.authenticated_request(client, user):
            response = client.get('/api/users/profile')
            
            # Verify: Version header present
            assert 'X-API-Version' in response.headers
            assert response.headers['X-API-Version'] == 'v1'
    
    def test_api_error_format_consistency(self, client, db):
        """Test API errors follow consistent format."""
        user = UserFactory()
        
        # Test various error scenarios
        error_scenarios = [
            # Unauthorized
            (client.get('/api/users/profile'), 401),
            # Not found
            (client.get('/api/matches/99999'), 404),
            # Bad request
            (client.post('/api/rsvp', json={}), 400),
        ]
        
        for request, expected_status in error_scenarios:
            if expected_status != 401:  # Add auth for non-401 tests
                with AuthTestHelper.authenticated_request(client, user):
                    response = request
            else:
                response = request
            
            assert response.status_code == expected_status
            
            # Verify: Consistent error format
            data = response.get_json()
            assert 'error' in data
            assert 'message' in data
            assert isinstance(data['error'], str)
            assert isinstance(data['message'], str)