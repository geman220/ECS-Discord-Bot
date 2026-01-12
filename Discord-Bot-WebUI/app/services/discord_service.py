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
        import asyncio

        # Check if we need to create a new session
        need_new_session = False

        if self._session is None or self._session.closed:
            need_new_session = True
        else:
            # Check if the session's loop matches the current running loop
            # This handles cases where a new event loop was created (e.g., CSV import)
            try:
                current_loop = asyncio.get_running_loop()
                # aiohttp sessions are bound to their creating loop
                # If the connector's loop is different, we need a new session
                if hasattr(self._session, '_connector') and self._session._connector:
                    connector_loop = getattr(self._session._connector, '_loop', None)
                    if connector_loop is not None and connector_loop != current_loop:
                        # Session is bound to a different (likely closed) loop
                        try:
                            await self._session.close()
                        except Exception:
                            pass  # Ignore errors closing old session
                        need_new_session = True
            except RuntimeError:
                # No running loop - shouldn't happen in async context
                pass

        if need_new_session:
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

    async def post_schedule_image_announcement(
        self,
        image_bytes: bytes,
        title: str,
        description: Optional[str] = None,
        footer_text: Optional[str] = None,
        channel_id: Optional[int] = None,
        channel_name: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Post a schedule image announcement to Discord.

        Args:
            image_bytes: PNG image data as bytes
            title: Embed title
            description: Optional embed description
            footer_text: Optional footer text
            channel_id: Optional specific channel ID
            channel_name: Optional channel name (resolved by bot)

        Returns:
            Dict with message_id, channel_id, channel_name if successful
        """
        if self._should_skip_call("post_schedule_image_announcement"):
            return None

        try:
            session = await self._get_session()
            url = f"{self.bot_api_url}/api/schedule-image/announce"

            # Create multipart form data
            data = aiohttp.FormData()
            data.add_field('image', image_bytes, filename='schedule.png', content_type='image/png')
            data.add_field('title', title)
            if description:
                data.add_field('description', description)
            if footer_text:
                data.add_field('footer_text', footer_text)
            if channel_id:
                data.add_field('channel_id', str(channel_id))
            if channel_name:
                data.add_field('channel_name', channel_name)

            logger.info(f"Posting schedule image announcement: {title}")

            async with session.post(url, data=data) as response:
                if response.status == 200:
                    result = await response.json()
                    logger.info(f"Posted schedule image: message_id={result.get('message_id')}, channel={result.get('channel_name')}")
                    return result
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to post schedule image (status {response.status}): {error_text}")
                    return None

        except Exception as e:
            logger.error(f"Error posting schedule image announcement: {e}")
            return None

    async def post_event_reminder(
        self,
        title: str,
        event_type: str,
        date_str: str,
        time_str: str,
        location: Optional[str] = None,
        description: Optional[str] = None,
        channel_name: str = 'league-announcements'
    ) -> Optional[Dict[str, Any]]:
        """
        Post an event reminder to the announcements channel.

        Args:
            title: Event title
            event_type: Type of event (plop, party, meeting, etc.)
            date_str: Formatted date string
            time_str: Formatted time string
            location: Optional location
            description: Optional description
            channel_name: Target channel name (default: league-announcements)

        Returns:
            Dict with message_id, channel_id if successful
        """
        if self._should_skip_call("post_event_reminder"):
            return None

        try:
            session = await self._get_session()
            url = f"{self.bot_api_url}/api/event-reminder"

            payload = {
                'title': title,
                'event_type': event_type,
                'date_str': date_str,
                'time_str': time_str,
                'location': location,
                'description': description,
                'channel_name': channel_name
            }

            logger.info(f"Posting event reminder for {title}")

            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    logger.info(f"Posted event reminder: {result.get('message_id')}")
                    return result
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to post event reminder (status {response.status}): {error_text}")
                    return None

        except Exception as e:
            logger.error(f"Error posting event reminder for {title}: {e}")
            return None

    async def post_plop_reminder(
        self,
        date_str: str,
        time_str: str,
        location: str,
        end_time_str: Optional[str] = None,
        channel_name: str = 'league-announcements'
    ) -> Optional[Dict[str, Any]]:
        """
        Post a PLOP reminder to the announcements channel.

        Specifically formatted for PLOP events with location emphasis.

        Args:
            date_str: Formatted date string (e.g., "Sunday, January 11")
            time_str: Start time string
            location: PLOP location (important - this is the key info)
            end_time_str: Optional end time
            channel_name: Target channel name

        Returns:
            Dict with message_id, channel_id if successful
        """
        if self._should_skip_call("post_plop_reminder"):
            return None

        try:
            session = await self._get_session()
            url = f"{self.bot_api_url}/api/plop-reminder"

            payload = {
                'date_str': date_str,
                'time_str': time_str,
                'end_time_str': end_time_str,
                'location': location,
                'channel_name': channel_name
            }

            logger.info(f"Posting PLOP reminder for {date_str} at {location}")

            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    logger.info(f"Posted PLOP reminder: {result.get('message_id')}")
                    return result
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to post PLOP reminder (status {response.status}): {error_text}")
                    return None

        except Exception as e:
            logger.error(f"Error posting PLOP reminder: {e}")
            return None

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