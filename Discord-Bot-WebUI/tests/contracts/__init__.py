# Contract tests package

class ResponseContract:
    """Base class for API response contracts."""
    
    def __init__(self, expected_fields, expected_status=200):
        self.expected_fields = expected_fields
        self.expected_status = expected_status
    
    def matches_response(self, response):
        """Check if response matches this contract."""
        if response.status_code != self.expected_status:
            return False
        
        try:
            data = response.get_json()
            return self._check_fields(data, self.expected_fields)
        except:
            return False
    
    def _check_fields(self, data, fields):
        """Recursively check if data contains expected fields."""
        for field, field_type in fields.items():
            if field not in data:
                return False
            
            if isinstance(field_type, dict):
                if not isinstance(data[field], dict):
                    return False
                if not self._check_fields(data[field], field_type):
                    return False
            elif isinstance(field_type, type):
                if not isinstance(data[field], field_type):
                    return False
        
        return True


class UserContracts:
    """Contracts for user-related API endpoints."""
    
    @staticmethod
    def profile_response():
        return ResponseContract({
            'data': {
                'id': int,
                'username': str,
                'email': str,
                'stats': {
                    'matches_played': int,
                    'matches_available': int,
                    'matches_unavailable': int
                }
            },
            'status': str
        })
    
    @staticmethod
    def login_success():
        return ResponseContract({
            'data': {
                'token': str,
                'user': {
                    'id': int,
                    'username': str,
                    'email': str
                }
            },
            'status': str
        })
    
    @staticmethod
    def login_failure():
        return ResponseContract({
            'error': str,
            'message': str
        }, expected_status=401)


class MatchContracts:
    """Contracts for match-related API endpoints."""
    
    @staticmethod
    def match_list():
        return ResponseContract({
            'data': {
                'matches': list,
                'total': int,
                'page': int,
                'per_page': int
            },
            'status': str
        })
    
    @staticmethod
    def match_detail():
        return ResponseContract({
            'data': {
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
                'field_name': str
            },
            'status': str
        })


class RSVPContracts:
    """Contracts for RSVP-related API endpoints."""
    
    @staticmethod
    def rsvp_success():
        return ResponseContract({
            'data': {
                'match_id': int,
                'available': bool,
                'updated_at': str
            },
            'status': str
        })
    
    @staticmethod
    def rsvp_list():
        return ResponseContract({
            'data': {
                'match_id': int,
                'available_count': int,
                'unavailable_count': int,
                'no_response_count': int,
                'rsvps': list
            },
            'status': str
        })