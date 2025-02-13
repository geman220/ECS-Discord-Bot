# app/utils/discord_helpers.py

"""
Discord Helpers Module

This module provides helper functions for interacting with the Discord bot API.
Specifically, it contains an asynchronous function to send updates (such as match
updates) to a Discord thread, with robust error handling and logging.
"""

import logging
import aiohttp
import asyncio

logger = logging.getLogger(__name__)


async def send_discord_update(
    thread_id: str,
    update_type: str,
    update_data: str,
    timeout: int = 30
) -> None:
    """
    Send an update to a Discord thread via the Discord bot API.

    Constructs a payload with the provided thread ID, update type, and update data,
    and sends a POST request to the Discord bot API endpoint. The function logs 
    successes and errors appropriately and raises exceptions when necessary.

    Args:
        thread_id: The ID of the Discord thread to update.
        update_type: A string indicating the type of update (e.g., "score_update").
        update_data: The content of the update message.
        timeout: Optional timeout for the API request in seconds (default is 30).

    Raises:
        aiohttp.ClientError: If the API call fails (non-200 status) or times out.
        asyncio.TimeoutError: If the request exceeds the specified timeout.
        Exception: For any other unexpected errors.
    """
    bot_api_url = "http://discord-bot:5001"
    endpoint = "/post_match_update"
    url = f"{bot_api_url}{endpoint}"

    # Construct the payload to be sent to the Discord API.
    payload = {
        "thread_id": thread_id,
        "update_type": update_type,
        "update_data": update_data
    }

    # Create an asynchronous HTTP session.
    async with aiohttp.ClientSession() as session:
        try:
            # Send a POST request with the payload and timeout.
            async with session.post(url, json=payload, timeout=timeout) as response:
                if response.status == 200:
                    logger.info(f"Successfully sent {update_type} update to thread {thread_id}")
                    return  # Successful update; exit the function.

                # If the response status is not 200, log and raise an error.
                error_text = await response.text()
                logger.error(
                    f"Failed to send {update_type} update to thread {thread_id}. "
                    f"Status: {response.status}, Error: {error_text}"
                )
                raise aiohttp.ClientError(f"Failed to send update: {error_text}")

        except asyncio.TimeoutError:
            # Handle timeout errors specifically.
            logger.error(f"Timeout sending {update_type} update to thread {thread_id}")
            raise
        except Exception as e:
            # Log any unexpected errors and re-raise them.
            logger.error(
                f"Error sending {update_type} update to thread {thread_id}: {str(e)}",
                exc_info=True
            )
            raise