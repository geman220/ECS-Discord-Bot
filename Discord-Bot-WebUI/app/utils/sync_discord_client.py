"""
Synchronous Discord API client.

Pure synchronous implementation to replace async Discord calls in Celery tasks.
Eliminates ThreadPoolExecutor usage that causes queue buildup.
"""

import logging
import requests
from typing import Dict, Any, Optional
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


class SyncDiscordClient:
    """
    Synchronous Discord API client for Celery tasks.
    
    Replaces async aiohttp calls with synchronous requests library
    to prevent ThreadPoolExecutor resource exhaustion.
    """
    
    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        self.session = self._create_session()
    
    def _create_session(self) -> requests.Session:
        """Create a requests session with retry logic."""
        session = requests.Session()
        
        # Configure retries for network errors
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[502, 503, 504],
            allowed_methods=["GET", "POST", "PUT", "DELETE", "PATCH"]
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        return session
    
    def force_rsvp_sync(self) -> Dict[str, Any]:
        """
        Trigger Discord RSVP sync using synchronous HTTP call.
        
        Returns:
            Dictionary with success status and response data.
        """
        discord_bot_url = "http://discord-bot:5001/api/force_rsvp_sync"
        
        try:
            logger.info("Starting Discord RSVP sync API call (synchronous)")
            
            response = self.session.post(
                discord_bot_url,
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"Discord RSVP sync triggered successfully: {result}")
                return {
                    'success': True,
                    'message': 'Discord RSVP sync triggered successfully',
                    'discord_response': result,
                    'api_call_success': True
                }
            else:
                error_msg = f"Failed to trigger Discord RSVP sync: {response.status_code} - {response.text}"
                logger.error(error_msg)
                return {
                    'success': False,
                    'message': error_msg,
                    'api_call_success': False
                }
                
        except requests.Timeout:
            error_msg = f"Discord API call timed out after {self.timeout} seconds"
            logger.error(error_msg)
            return {
                'success': False,
                'message': error_msg,
                'api_call_success': False,
                'timeout': True
            }
        except requests.RequestException as e:
            error_msg = f"Error connecting to Discord bot for RSVP sync: {str(e)}"
            logger.error(error_msg)
            return {
                'success': False,
                'message': error_msg,
                'api_call_success': False,
                'error': str(e)
            }
        except Exception as e:
            error_msg = f"Unexpected error during Discord RSVP sync: {str(e)}"
            logger.error(error_msg)
            return {
                'success': False,
                'message': error_msg,
                'api_call_success': False,
                'error': str(e)
            }
    
    def update_discord_reactions(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update Discord reactions using synchronous HTTP call.
        
        Args:
            data: Dictionary containing message_id and reaction updates.
            
        Returns:
            Dictionary with success status and response data.
        """
        discord_bot_url = "http://discord-bot:5001/api/update_reactions"
        
        try:
            logger.info(f"Updating Discord reactions for message {data.get('message_id')} (synchronous)")
            
            response = self.session.post(
                discord_bot_url,
                json=data,
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"Discord reactions updated successfully: {result}")
                return {
                    'success': True,
                    'message': 'Discord reactions updated successfully',
                    'discord_response': result,
                    'api_call_success': True
                }
            else:
                error_msg = f"Failed to update Discord reactions: {response.status_code} - {response.text}"
                logger.error(error_msg)
                return {
                    'success': False,
                    'message': error_msg,
                    'api_call_success': False,
                    'status_code': response.status_code
                }
                
        except requests.Timeout:
            error_msg = f"Discord API call timed out after {self.timeout} seconds"
            logger.error(error_msg)
            return {
                'success': False,
                'message': error_msg,
                'api_call_success': False,
                'timeout': True
            }
        except requests.RequestException as e:
            error_msg = f"Error updating Discord reactions: {str(e)}"
            logger.error(error_msg)
            return {
                'success': False,
                'message': error_msg,
                'api_call_success': False,
                'error': str(e)
            }
        except Exception as e:
            error_msg = f"Unexpected error updating Discord reactions: {str(e)}"
            logger.error(error_msg)
            return {
                'success': False,
                'message': error_msg,
                'api_call_success': False,
                'error': str(e)
            }
    
    def send_ecs_fc_rsvp_message(self, match_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send ECS FC RSVP message using synchronous HTTP call.
        
        Args:
            match_data: Dictionary containing match details.
            
        Returns:
            Dictionary with success status and message details.
        """
        discord_bot_url = "http://discord-bot:5001/api/send_ecs_fc_rsvp"
        
        try:
            logger.info(f"Sending ECS FC RSVP for match {match_data.get('match_id')} (synchronous)")
            
            response = self.session.post(
                discord_bot_url,
                json=match_data,
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"ECS FC RSVP sent successfully: {result}")
                return {
                    'success': True,
                    'message': 'ECS FC RSVP message sent successfully',
                    'message_id': result.get('message_id'),
                    'discord_response': result
                }
            else:
                error_msg = f"Failed to send ECS FC RSVP: {response.status_code} - {response.text}"
                logger.error(error_msg)
                return {
                    'success': False,
                    'message': error_msg,
                    'status_code': response.status_code
                }
                
        except requests.Timeout:
            error_msg = f"Discord API call timed out after {self.timeout} seconds"
            logger.error(error_msg)
            return {
                'success': False,
                'message': error_msg,
                'timeout': True
            }
        except Exception as e:
            error_msg = f"Error sending ECS FC RSVP: {str(e)}"
            logger.error(error_msg)
            return {
                'success': False,
                'message': error_msg,
                'error': str(e)
            }
    
    def send_availability_message(self, message_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send availability message using synchronous HTTP call.
        
        Args:
            message_data: Dictionary containing message details.
            
        Returns:
            Dictionary with success status and response.
        """
        discord_bot_url = "http://discord-bot:5001/api/send_availability"
        
        try:
            logger.info(f"Sending availability message for user {message_data.get('user_id')} (synchronous)")
            
            response = self.session.post(
                discord_bot_url,
                json=message_data,
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                result = response.json()
                logger.info("Availability message sent successfully")
                return {
                    'success': True,
                    'message': 'Availability message sent successfully',
                    'discord_response': result
                }
            else:
                error_msg = f"Failed to send availability message: {response.status_code} - {response.text}"
                logger.error(error_msg)
                return {
                    'success': False,
                    'message': error_msg,
                    'status_code': response.status_code
                }
                
        except requests.Timeout:
            error_msg = f"Discord API call timed out after {self.timeout} seconds"
            logger.error(error_msg)
            return {
                'success': False,
                'message': error_msg,
                'timeout': True
            }
        except Exception as e:
            error_msg = f"Error sending availability message: {str(e)}"
            logger.error(error_msg)
            return {
                'success': False,
                'message': error_msg,
                'error': str(e)
            }
    
    def create_match_thread(self, match_data: Dict[str, Any]) -> Optional[str]:
        """
        Create a Discord thread for a match using synchronous HTTP call.
        
        Args:
            match_data: Dictionary containing match details.
            
        Returns:
            Thread ID if successful, None otherwise.
        """
        discord_bot_url = "http://discord-bot:5001/api/create_match_thread"
        
        try:
            logger.info(f"Creating Discord thread for match {match_data.get('match_id')} (synchronous)")
            
            response = self.session.post(
                discord_bot_url,
                json=match_data,
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                result = response.json()
                thread_id = result.get('thread_id')
                logger.info(f"Discord thread created successfully: {thread_id}")
                return thread_id
            else:
                error_msg = f"Failed to create Discord thread: {response.status_code} - {response.text}"
                logger.error(error_msg)
                return None
                
        except requests.Timeout:
            logger.error(f"Discord API call timed out after {self.timeout} seconds")
            return None
        except Exception as e:
            logger.error(f"Error creating Discord thread: {str(e)}")
            return None
    
    def send_rsvp_availability_message(self, message_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send RSVP availability message using synchronous HTTP call.
        
        Args:
            message_data: Dictionary containing availability message details.
            
        Returns:
            Dictionary with success status and response data.
        """
        discord_bot_url = "http://discord-bot:5001/api/send_availability_message"
        
        try:
            logger.info(f"Sending RSVP availability message for match {message_data.get('match_id')} (synchronous)")
            
            response = self.session.post(
                discord_bot_url,
                json=message_data,
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                result = response.json()
                logger.info("RSVP availability message sent successfully")
                return {
                    'success': True,
                    'message': 'Availability message sent successfully',
                    'discord_response': result,
                    'home_message_id': result.get('home_message_id'),
                    'away_message_id': result.get('away_message_id'),
                    'timestamp': result.get('timestamp')
                }
            else:
                error_msg = f"Failed to send availability message: {response.status_code} - {response.text}"
                logger.error(error_msg)
                return {
                    'success': False,
                    'message': error_msg,
                    'status_code': response.status_code
                }
                
        except requests.Timeout:
            error_msg = f"Discord API call timed out after {self.timeout} seconds"
            logger.error(error_msg)
            return {
                'success': False,
                'message': error_msg,
                'timeout': True
            }
        except Exception as e:
            error_msg = f"Error sending availability message: {str(e)}"
            logger.error(error_msg)
            return {
                'success': False,
                'message': error_msg,
                'error': str(e)
            }
    
    def update_rsvp_response(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update RSVP response using synchronous HTTP call.
        
        Args:
            data: Dictionary containing RSVP update data.
            
        Returns:
            Dictionary with success status and response data.
        """
        discord_bot_url = "http://discord-bot:5001/api/update_rsvp"
        
        try:
            logger.info(f"Updating RSVP for match {data.get('match_id')}, user {data.get('discord_id')} (synchronous)")
            
            response = self.session.post(
                discord_bot_url,
                json=data,
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                result = response.json()
                logger.info("RSVP update completed successfully")
                return {
                    'success': True,
                    'message': 'RSVP updated successfully',
                    'discord_response': result,
                    'timestamp': result.get('timestamp')
                }
            else:
                error_msg = f"Failed to update RSVP: {response.status_code} - {response.text}"
                logger.error(error_msg)
                return {
                    'success': False,
                    'message': error_msg,
                    'status_code': response.status_code
                }
                
        except requests.Timeout:
            error_msg = f"Discord API call timed out after {self.timeout} seconds"
            logger.error(error_msg)
            return {
                'success': False,
                'message': error_msg,
                'timeout': True
            }
        except Exception as e:
            error_msg = f"Error updating RSVP: {str(e)}"
            logger.error(error_msg)
            return {
                'success': False,
                'message': error_msg,
                'error': str(e)
            }
    
    def notify_rsvp_changes(self, match_id: int) -> Dict[str, Any]:
        """
        Notify Discord of RSVP changes using synchronous HTTP call.
        
        Args:
            match_id: Match ID to notify about.
            
        Returns:
            Dictionary with success status and response data.
        """
        discord_bot_url = "http://discord-bot:5001/api/notify_rsvp_changes"
        
        try:
            logger.info(f"Notifying Discord of RSVP changes for match {match_id} (synchronous)")
            
            response = self.session.post(
                discord_bot_url,
                json={'match_id': match_id},
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                result = response.json()
                logger.info("Discord RSVP notification completed successfully")
                return {
                    'success': True,
                    'message': 'RSVP notification sent successfully',
                    'discord_response': result,
                    'timestamp': result.get('timestamp')
                }
            else:
                error_msg = f"Failed to notify RSVP changes: {response.status_code} - {response.text}"
                logger.error(error_msg)
                return {
                    'success': False,
                    'message': error_msg,
                    'status_code': response.status_code
                }
                
        except requests.Timeout:
            error_msg = f"Discord API call timed out after {self.timeout} seconds"
            logger.error(error_msg)
            return {
                'success': False,
                'message': error_msg,
                'timeout': True
            }
        except Exception as e:
            error_msg = f"Error notifying RSVP changes: {str(e)}"
            logger.error(error_msg)
            return {
                'success': False,
                'message': error_msg,
                'error': str(e)
            }
    
    def check_member_in_server(self, server_id: str, discord_id: str) -> Dict[str, Any]:
        """
        Check if a user is a member of the Discord server.
        
        Args:
            server_id: Discord server ID.
            discord_id: Discord user ID.
            
        Returns:
            Dictionary with success status and member info.
        """
        discord_bot_url = f"http://discord-bot:5001/api/server/guilds/{server_id}/members/{discord_id}"
        
        try:
            logger.info(f"Checking if user {discord_id} is in server {server_id} (synchronous)")
            
            response = self.session.get(
                discord_bot_url,
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"User {discord_id} found in server")
                return {
                    'success': True,
                    'in_server': True,
                    'member_data': result
                }
            elif response.status_code == 404:
                logger.info(f"User {discord_id} not found in server")
                return {
                    'success': True,
                    'in_server': False
                }
            else:
                error_msg = f"Failed to check member status: {response.status_code} - {response.text}"
                logger.error(error_msg)
                return {
                    'success': False,
                    'message': error_msg,
                    'status_code': response.status_code
                }
                
        except requests.Timeout:
            error_msg = f"Discord API call timed out after {self.timeout} seconds"
            logger.error(error_msg)
            return {
                'success': False,
                'message': error_msg,
                'timeout': True
            }
        except Exception as e:
            error_msg = f"Error checking member status: {str(e)}"
            logger.error(error_msg)
            return {
                'success': False,
                'message': error_msg,
                'error': str(e)
            }
    
    def invite_user_to_server(self, discord_id: str) -> Dict[str, Any]:
        """
        Invite a user to the Discord server.
        
        Args:
            discord_id: Discord user ID to invite.
            
        Returns:
            Dictionary with success status and invite details.
        """
        discord_bot_url = "http://discord-bot:5001/api/invite_user"
        
        try:
            logger.info(f"Inviting user {discord_id} to server (synchronous)")
            
            response = self.session.post(
                discord_bot_url,
                json={'discord_id': discord_id},
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"User {discord_id} invited successfully")
                return {
                    'success': True,
                    'invite_code': result.get('invite_code'),
                    'invite_link': result.get('invite_link'),
                    'message': result.get('message', 'User invited successfully')
                }
            else:
                error_msg = f"Failed to invite user: {response.status_code} - {response.text}"
                logger.error(error_msg)
                return {
                    'success': False,
                    'message': error_msg,
                    'status_code': response.status_code
                }
                
        except requests.Timeout:
            error_msg = f"Discord API call timed out after {self.timeout} seconds"
            logger.error(error_msg)
            return {
                'success': False,
                'message': error_msg,
                'timeout': True
            }
        except Exception as e:
            error_msg = f"Error inviting user: {str(e)}"
            logger.error(error_msg)
            return {
                'success': False,
                'message': error_msg,
                'error': str(e)
            }
    
    def assign_role_to_member(self, server_id: str, discord_id: str, role_id: str) -> Dict[str, Any]:
        """
        Assign a role to a Discord server member.
        
        Args:
            server_id: Discord server ID.
            discord_id: Discord user ID.
            role_id: Discord role ID to assign.
            
        Returns:
            Dictionary with success status.
        """
        discord_bot_url = "http://discord-bot:5001/api/assign_role"
        
        try:
            logger.info(f"Assigning role {role_id} to user {discord_id} in server {server_id} (synchronous)")
            
            response = self.session.post(
                discord_bot_url,
                json={
                    'server_id': server_id,
                    'discord_id': discord_id,
                    'role_id': role_id
                },
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"Role assigned successfully to user {discord_id}")
                return {
                    'success': True,
                    'message': result.get('message', 'Role assigned successfully')
                }
            else:
                error_msg = f"Failed to assign role: {response.status_code} - {response.text}"
                logger.error(error_msg)
                return {
                    'success': False,
                    'message': error_msg,
                    'status_code': response.status_code
                }
                
        except requests.Timeout:
            error_msg = f"Discord API call timed out after {self.timeout} seconds"
            logger.error(error_msg)
            return {
                'success': False,
                'message': error_msg,
                'timeout': True
            }
        except Exception as e:
            error_msg = f"Error assigning role: {str(e)}"
            logger.error(error_msg)
            return {
                'success': False,
                'message': error_msg,
                'error': str(e)
            }
    
    def close(self):
        """Close the session."""
        if self.session:
            self.session.close()


# Global client instance for reuse
_discord_client: Optional[SyncDiscordClient] = None


def get_sync_discord_client() -> SyncDiscordClient:
    """
    Get or create a global synchronous Discord client.
    
    Returns:
        SyncDiscordClient instance.
    """
    global _discord_client
    if _discord_client is None:
        _discord_client = SyncDiscordClient()
    return _discord_client