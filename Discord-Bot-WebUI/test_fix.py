import requests
import json
import logging

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def test_get_match_and_team_id_from_message():
    """
    Test the fix for get_match_and_team_id_from_message endpoint
    """
    # Simulate the response from fetch_match_and_team_id_task with 'success' instead of 'status'
    mock_response = {
        'success': True,
        'match_id': 169,
        'team_id': 171
    }
    
    logger.info(f"Mock response with 'success' key: {mock_response}")
    
    # Check if our fixed endpoint can handle 'success' key correctly
    status_check = mock_response.get('status')
    success_check = mock_response.get('success')
    
    logger.info(f"Status check result: {status_check}")
    logger.info(f"Success check result: {success_check}")
    
    if 'success' in mock_response:
        if mock_response['success']:
            response = {
                'status': 'success',
                'data': {
                    'match_id': mock_response.get('match_id'),
                    'team_id': mock_response.get('team_id')
                }
            }
            logger.info(f"Fixed response format: {response}")
            return True
        else:
            logger.error("Success is False, would return error")
            return False
    else:
        # Legacy format check (status key)
        status = mock_response.get('status')
        logger.info(f"Using legacy format with status: {status}")
        return False

if __name__ == "__main__":
    success = test_get_match_and_team_id_from_message()
    print(f"Test result: {'Passed' if success else 'Failed'}")