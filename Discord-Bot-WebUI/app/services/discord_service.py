# app/services/discord_service.py

"""
Discord Service

Centralized service for all Discord-related operations from the Flask app.
This service communicates with the Discord bot via API calls, maintaining
proper separation of concerns.
"""

import asyncio
import logging
from typing import Optional, Dict, Any, List
import aiohttp
import json
import os
from datetime import datetime

logger = logging.getLogger(__name__)


class DiscordService:
    """
    Service for Discord operations via bot API.
    All Discord interactions from Flask should go through this service.
    """
    
    def __init__(self):
        self.bot_api_url = os.getenv('BOT_API_URL', 'http://discord-bot:5001')
        self._session = None
    
    def _should_skip_call(self, operation_name: str) -> bool:
        """Check if Discord bot calls should be skipped due to circuit breaker."""
        try:
            from app.utils.discord_helpers import get_circuit_breaker_status
            cb_status = get_circuit_breaker_status()
            if not cb_status['can_proceed']:
                logger.warning(f"Skipping Discord {operation_name} - circuit breaker is {cb_status['state']}")
                return True
            return False
        except Exception as e:
            logger.warning(f"Error checking circuit breaker status: {e}")
            return False
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session with proper timeout."""
        if self._session is None or self._session.closed:
            # Create session with proper timeout configuration
            timeout = aiohttp.ClientTimeout(total=30, connect=10, sock_read=20)
            connector = aiohttp.TCPConnector(limit=100, limit_per_host=30)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector
            )
        return self._session
    
    async def create_match_thread(self, match_data: Dict[str, Any]) -> Optional[str]:
        """
        Create a Discord thread for a match via bot API.
        
        Args:
            match_data: Dictionary containing match information
            
        Returns:
            Thread ID if successful, None otherwise
        """
        if self._should_skip_call("create_match_thread"):
            return None
            
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                session = await self._get_session()
                url = f"{self.bot_api_url}/api/create_match_thread"
                
                # Standardize the payload
                payload = {
                    'match_id': match_data.get('id') or match_data.get('match_id'),
                    'home_team': match_data.get('home_team'),
                    'away_team': match_data.get('away_team'),
                    'date': match_data.get('date'),
                    'time': match_data.get('time'),
                    'venue': match_data.get('venue', 'TBD'),
                    'competition': match_data.get('competition', 'MLS'),
                    'is_home_game': match_data.get('is_home_game', False)
                }
                
                logger.info(f"Attempt {attempt + 1}/{max_retries}: Creating Discord thread for match {payload['match_id']}")
                
                async with session.post(url, json=payload) as response:
                    if response.status == 200:
                        result = await response.json()
                        thread_id = result.get('thread_id')
                        if result.get('existing'):
                            logger.info(f"Using existing thread {thread_id} for match {payload['match_id']}")
                        else:
                            logger.info(f"Created new thread {thread_id} for match {payload['match_id']}")
                        return thread_id
                    
                    elif response.status == 409:
                        # Thread already exists
                        result = await response.json()
                        thread_id = result.get('thread_id')
                        if thread_id:
                            logger.info(f"Thread already exists for match {payload['match_id']}: {thread_id}")
                            return thread_id
                    
                    elif response.status in [500, 502, 503, 504]:
                        # Server errors - retry
                        error_text = await response.text()
                        logger.warning(f"Server error {response.status} on attempt {attempt + 1}: {error_text}")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_delay * (attempt + 1))
                            continue
                    
                    else:
                        error_text = await response.text()
                        logger.error(f"Failed to create Discord thread (status {response.status}): {error_text}")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_delay)
                            continue
                        return None
                        
            except aiohttp.ClientError as e:
                logger.error(f"Client error creating thread (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    continue
            except asyncio.TimeoutError:
                logger.error(f"Timeout creating thread (attempt {attempt + 1})")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    continue
            except Exception as e:
                logger.error(f"Unexpected error creating thread (attempt {attempt + 1}): {e}", exc_info=True)
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    continue
        
        logger.error(f"Failed to create Discord thread after {max_retries} attempts for match {match_data.get('id', 'unknown')}")
        return None
    
    async def update_live_match(self, thread_id: str, match_data: Dict[str, Any]) -> bool:
        """
        Send live match update to Discord thread via bot API.
        
        Args:
            thread_id: Discord thread ID
            match_data: Match update data containing thread_id, update_type, and update_data
            
        Returns:
            True if successful, False otherwise
        """
        if self._should_skip_call("update_live_match"):
            return False
            
        max_retries = 2
        retry_delay = 1
        
        for attempt in range(max_retries):
            try:
                session = await self._get_session()
                # Use the same endpoint as the fallback for compatibility
                url = f"{self.bot_api_url}/post_match_update"
                
                # Extract the proper payload format
                payload = {
                    'thread_id': match_data.get('thread_id', thread_id),
                    'update_type': match_data.get('update_type', 'match_update'),
                    'update_data': match_data.get('update_data', {})
                }
                
                logger.debug(f"Attempt {attempt + 1}/{max_retries}: Sending live update to thread {thread_id}")
                
                async with session.post(url, json=payload) as response:
                    if response.status == 200:
                        logger.debug(f"Sent live update to thread {thread_id} via centralized service")
                        return True
                    elif response.status in [500, 502, 503, 504]:
                        # Server errors - retry
                        error_text = await response.text()
                        logger.warning(f"Server error {response.status} sending live update (attempt {attempt + 1}): {error_text}")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_delay * (attempt + 1))
                            continue
                    else:
                        error_text = await response.text()
                        logger.error(f"Failed to send live update (status {response.status}): {error_text}")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_delay)
                            continue
                        return False
                        
            except aiohttp.ClientError as e:
                logger.error(f"Client error sending live update (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    continue
            except asyncio.TimeoutError:
                logger.error(f"Timeout sending live update (attempt {attempt + 1})")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    continue
            except Exception as e:
                logger.error(f"Unexpected error sending live update (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    continue
        
        logger.error(f"Failed to send live update after {max_retries} attempts to thread {thread_id}")
        return False
    
    async def send_match_embed(self, channel_id: str, embed_data: Dict[str, Any]) -> Optional[str]:
        """
        Send an embed to a Discord channel via bot API.
        
        Args:
            channel_id: Discord channel ID
            embed_data: Embed data
            
        Returns:
            Message ID if successful, None otherwise
        """
        try:
            session = await self._get_session()
            url = f"{self.bot_api_url}/api/send_embed"
            
            payload = {
                'channel_id': channel_id,
                'embed': embed_data
            }
            
            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    message_id = result.get('message_id')
                    logger.info(f"Sent embed to channel {channel_id}: {message_id}")
                    return message_id
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to send embed (status {response.status}): {error_text}")
                    return None
                    
        except Exception as e:
            logger.error(f"Error sending embed to channel {channel_id}: {e}")
            return None
    
    async def get_bot_status(self) -> Dict[str, Any]:
        """
        Get Discord bot status and health information.
        
        Returns:
            Status dictionary with bot information
        """
        try:
            from app.utils.discord_helpers import check_discord_bot_health
            return await check_discord_bot_health()
        except Exception as e:
            logger.error(f"Error getting bot status: {e}")
            return {'status': 'error', 'connected': False, 'error': str(e)}
    
    async def post_league_event_announcement(
        self,
        event_id: int,
        title: str,
        start_datetime: str,
        description: Optional[str] = None,
        event_type: str = 'other',
        location: Optional[str] = None,
        end_datetime: Optional[str] = None,
        is_all_day: bool = False,
        channel_id: Optional[int] = None,
        channel_name: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Post a league event announcement to Discord.

        Args:
            event_id: The league event ID
            title: Event title
            start_datetime: ISO format datetime string
            description: Optional event description
            event_type: Type of event (party, meeting, etc.)
            location: Optional location
            end_datetime: Optional end datetime ISO string
            is_all_day: Whether it's an all-day event
            channel_id: Optional specific channel ID
            channel_name: Optional channel name (resolved by bot)

        Returns:
            Dict with message_id, channel_id, channel_name if successful
        """
        if self._should_skip_call("post_league_event_announcement"):
            return None

        try:
            session = await self._get_session()
            url = f"{self.bot_api_url}/api/league-event/announce"

            payload = {
                'event_id': event_id,
                'title': title,
                'description': description,
                'event_type': event_type,
                'location': location,
                'start_datetime': start_datetime,
                'end_datetime': end_datetime,
                'is_all_day': is_all_day
            }

            # Add channel if specified
            if channel_id:
                payload['channel_id'] = channel_id
            if channel_name:
                payload['channel_name'] = channel_name

            logger.info(f"Posting league event announcement for event {event_id}")

            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    logger.info(f"Posted league event announcement: message_id={result.get('message_id')}, channel={result.get('channel_name')}")
                    return result
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to post league event announcement (status {response.status}): {error_text}")
                    return None

        except Exception as e:
            logger.error(f"Error posting league event announcement for event {event_id}: {e}")
            return None

    async def update_league_event_announcement(
        self,
        event_id: int,
        message_id: int,
        channel_id: int,
        title: str,
        start_datetime: str,
        description: Optional[str] = None,
        event_type: str = 'other',
        location: Optional[str] = None,
        end_datetime: Optional[str] = None,
        is_all_day: bool = False
    ) -> bool:
        """
        Update an existing league event announcement in Discord.

        Returns:
            True if successful, False otherwise
        """
        if self._should_skip_call("update_league_event_announcement"):
            return False

        try:
            session = await self._get_session()
            url = f"{self.bot_api_url}/api/league-event/announce/{event_id}"

            payload = {
                'event_id': event_id,
                'message_id': message_id,
                'channel_id': channel_id,
                'title': title,
                'description': description,
                'event_type': event_type,
                'location': location,
                'start_datetime': start_datetime,
                'end_datetime': end_datetime,
                'is_all_day': is_all_day
            }

            async with session.put(url, json=payload) as response:
                if response.status == 200:
                    logger.info(f"Updated league event announcement for event {event_id}")
                    return True
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to update league event announcement (status {response.status}): {error_text}")
                    return False

        except Exception as e:
            logger.error(f"Error updating league event announcement for event {event_id}: {e}")
            return False

    async def delete_league_event_announcement(
        self,
        message_id: int,
        channel_id: int
    ) -> bool:
        """
        Delete a league event announcement from Discord.

        Returns:
            True if successful, False otherwise
        """
        if self._should_skip_call("delete_league_event_announcement"):
            return False

        try:
            session = await self._get_session()
            url = f"{self.bot_api_url}/api/league-event/announce"

            payload = {
                'message_id': message_id,
                'channel_id': channel_id
            }

            async with session.delete(url, json=payload) as response:
                if response.status == 200:
                    logger.info(f"Deleted league event announcement (message {message_id})")
                    return True
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to delete league event announcement (status {response.status}): {error_text}")
                    return False

        except Exception as e:
            logger.error(f"Error deleting league event announcement (message {message_id}): {e}")
            return False

    async def close(self):
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()


# Global service instance
_discord_service = None

def get_discord_service() -> DiscordService:
    """Get the global Discord service instance."""
    global _discord_service
    if _discord_service is None:
        _discord_service = DiscordService()
    return _discord_service


# Convenience functions for backward compatibility
async def create_match_thread_via_bot(match_data: Dict[str, Any]) -> Optional[str]:
    """
    Convenience function to create match thread via bot API.
    Replaces direct Discord API calls from Flask app.
    """
    service = get_discord_service()
    return await service.create_match_thread(match_data)