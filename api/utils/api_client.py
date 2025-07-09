# api_client.py - HTTP client utilities extracted from bot_rest_api.py

import aiohttp
import asyncio
import logging
from typing import Optional
from fastapi import HTTPException
from aiohttp import ClientError

# Set up logging
logger = logging.getLogger(__name__)

# Global session variable
session: Optional[aiohttp.ClientSession] = None

async def get_session() -> aiohttp.ClientSession:
    """Get or create the global aiohttp session."""
    global session
    if session is None:
        session = aiohttp.ClientSession()
    return session

async def startup_event():
    """App startup event handler to initialize the aiohttp session."""
    global session
    if session is None:
        session = aiohttp.ClientSession()

async def shutdown_event():
    """App shutdown event handler to close the aiohttp session."""
    global session
    if session:
        await session.close()

async def direct_api_permission_update(channel_id, role_id, allow, deny, bot_token):
    """Direct API call to Discord to update channel permissions."""
    url = f"https://discord.com/api/v10/channels/{channel_id}/permissions/{role_id}"
    headers = {
        "Authorization": f"Bot {bot_token}",
        "Content-Type": "application/json"
    }
    payload = {
        "allow": str(allow),
        "deny": str(deny),
        "type": 0  # For role overwrite
    }

    async with session.put(url, headers=headers, json=payload) as response:
        if response.status in [200, 204]:
            logger.info(f"Permissions set successfully for role ID {role_id} on channel ID {channel_id}")
            return {"status": "Permissions updated"}
        else:
            logger.error(f"Failed to set permissions: {response.status} - {await response.text()}")
            raise HTTPException(status_code=response.status, detail=f"Failed to set permissions: {await response.text()}")

async def retry_api_call(url, method='GET', json=None, max_retries=3, delay=1):
    """Retry API calls with exponential backoff."""
    for attempt in range(max_retries):
        try:
            async with session.request(method, url, json=json) as response:
                response.raise_for_status()
                return await response.json()
        except ClientError as e:
            if attempt == max_retries - 1:
                raise
            logger.warning(f"API call failed (attempt {attempt + 1}/{max_retries}): {e}")
            await asyncio.sleep(delay * (2 ** attempt))  # Exponential backoff