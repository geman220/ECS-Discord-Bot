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
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=60, connect=10)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session
    
    async def create_match_thread(self, match_data: Dict[str, Any]) -> Optional[str]:
        """
        Create a Discord thread for a match via bot API.
        
        Args:
            match_data: Dictionary containing match information
            
        Returns:
            Thread ID if successful, None otherwise
        """
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
                
                # Enhanced timeout settings
                timeout = aiohttp.ClientTimeout(total=30, connect=10, sock_read=20)
                session._timeout = timeout
                
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
            session = await self._get_session()
            url = f"{self.bot_api_url}/api/status"
            
            async with session.get(url) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    logger.error(f"Failed to get bot status (status {response.status})")
                    return {'status': 'error', 'connected': False}
                    
        except Exception as e:
            logger.error(f"Error getting bot status: {e}")
            return {'status': 'error', 'connected': False}
    
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