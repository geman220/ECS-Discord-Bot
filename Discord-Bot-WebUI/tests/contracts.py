"""
API Contract definitions for testing.
These define the expected shape of API responses.
"""
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime


@dataclass
class APIContract:
    """Base contract for API responses."""
    status: int
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    
    def matches_response(self, response):
        """Check if response matches contract."""
        if response.status_code != self.status:
            return False
        
        json_data = response.get_json()
        
        if self.error and json_data.get('error') != self.error:
            return False
        
        if self.data:
            return self._matches_data(json_data.get('data', {}), self.data)
        
        return True
    
    def _matches_data(self, actual, expected):
        """Recursively check data structure matches."""
        for key, value in expected.items():
            if key not in actual:
                return False
            
            if isinstance(value, dict):
                if not self._matches_data(actual[key], value):
                    return False
            elif isinstance(value, type):
                if not isinstance(actual[key], value):
                    return False
        
        return True


# Define contracts for your APIs
class UserContracts:
    """Contract definitions for user-related APIs."""
    
    @staticmethod
    def profile_response():
        return APIContract(
            status=200,
            data={
                'id': int,
                'username': str,
                'email': str,
                'teams': list,
                'stats': {
                    'matches_played': int,
                    'goals': int,
                    'assists': int
                }
            }
        )
    
    @staticmethod
    def login_success():
        return APIContract(
            status=200,
            data={
                'user_id': int,
                'username': str,
                'roles': list,
                'token': str
            }
        )
    
    @staticmethod
    def login_failure():
        return APIContract(
            status=401,
            error="Invalid credentials"
        )


class MatchContracts:
    """Contract definitions for match-related APIs."""
    
    @staticmethod
    def match_list():
        return APIContract(
            status=200,
            data={
                'matches': list,
                'total': int,
                'page': int,
                'per_page': int
            }
        )
    
    @staticmethod
    def match_detail():
        return APIContract(
            status=200,
            data={
                'id': int,
                'home_team': {
                    'id': int,
                    'name': str
                },
                'away_team': {
                    'id': int,
                    'name': str
                },
                'scheduled_date': str,
                'scheduled_time': str,
                'field_name': str,
                'status': str
            }
        )


class RSVPContracts:
    """Contract definitions for RSVP-related APIs."""
    
    @staticmethod
    def rsvp_success():
        return APIContract(
            status=200,
            data={
                'match_id': int,
                'available': bool,
                'updated_at': str
            }
        )
    
    @staticmethod
    def rsvp_list():
        return APIContract(
            status=200,
            data={
                'match_id': int,
                'responses': list,
                'available_count': int,
                'unavailable_count': int,
                'no_response_count': int
            }
        )