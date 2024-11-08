# In app/utils/discord_helpers.py

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
    Send update to Discord bot with proper error handling and logging.
    """
    bot_api_url = "http://discord-bot:5001"
    endpoint = "/post_match_update"
    url = f"{bot_api_url}{endpoint}"

    payload = {
        "thread_id": thread_id,
        "update_type": update_type,
        "update_data": update_data
    }

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=payload, timeout=timeout) as response:
                if response.status == 200:
                    logger.info(f"Successfully sent {update_type} update to thread {thread_id}")
                    return

                error_text = await response.text()
                logger.error(
                    f"Failed to send {update_type} update to thread {thread_id}. "
                    f"Status: {response.status}, Error: {error_text}"
                )
                raise aiohttp.ClientError(f"Failed to send update: {error_text}")

        except asyncio.TimeoutError:
            logger.error(f"Timeout sending {update_type} update to thread {thread_id}")
            raise
        except Exception as e:
            logger.error(
                f"Error sending {update_type} update to thread {thread_id}: {str(e)}",
                exc_info=True
            )
            raise
