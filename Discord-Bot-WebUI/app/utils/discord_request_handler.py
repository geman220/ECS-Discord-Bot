# app/utils/discord_request_handler.py

"""
Discord Request Handler Module

This module provides helper functions and classes for making requests to the Discord
bot API with rate limiting, retry logic, and concurrency control. It defines:
  - make_discord_request: an async function to perform a single Discord API request with retries.
  - DiscordRateLimiter: a class to limit the rate of outgoing requests.
  - OptimizedDiscordRequests: a class that uses both a rate limiter and a semaphore to manage
    concurrent requests and cache 404 responses.
  - optimized_discord_request: an async helper to execute multiple Discord requests concurrently.
"""

import asyncio
import aiohttp
import requests
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
import os

logger = logging.getLogger(__name__)


async def make_discord_request(
    method: str,
    url: str,
    session: aiohttp.ClientSession,
    retries: int = 3,
    delay: float = 0.5,
    **kwargs
) -> Any:
    """
    Make a Discord API request with retries, handling 404 and 429 responses.

    This function attempts to parse the response as JSON. If the response is not JSON,
    it logs an error and returns None.

    Args:
        method: HTTP method (e.g., 'GET', 'POST').
        url: The API endpoint URL.
        session: An aiohttp.ClientSession for making the request.
        retries: Number of retry attempts if a request fails.
        delay: Delay between retry attempts in seconds.
        **kwargs: Additional keyword arguments passed to session.request.

    Returns:
        The JSON-decoded response if successful, or None if an error occurs.
    """
    logger.debug(f"Discord request: {method} {url}, kwargs={kwargs}")
    for attempt in range(retries):
        try:
            async with session.request(method, url, **kwargs) as response:
                if response.status == 404:
                    logger.warning(f"404 Not Found for URL: {url}")
                    return None
                elif response.status == 429:
                    # Rate limited by Discord; wait for Retry-After header value.
                    retry_after = float(response.headers.get('Retry-After', '1'))
                    logger.warning(f"Rate limited (429) by Discord. Retrying after {retry_after}s")
                    await asyncio.sleep(retry_after)
                    continue
                elif response.status >= 400:
                    # For other errors, log and raise an exception.
                    response_text = await response.text()
                    logger.error(f"Error {response.status} for {url}: {response_text}")
                    response.raise_for_status()
                else:
                    # Successful response; attempt to decode JSON.
                    try:
                        return await response.json()
                    except (aiohttp.ContentTypeError, ValueError) as e:
                        logger.error(f"Failed to decode JSON from {url}: {e}")
                        return None

        except Exception as e:
            logger.error(f"Attempt {attempt + 1} - Error on {method} request to {url}: {e}")
            await asyncio.sleep(delay)

    logger.error(f"Failed to complete {method} request to {url} after {retries} attempts.")
    return None


class DiscordRateLimiter:
    """
    A simple rate limiter for Discord API requests.

    This class limits the number of requests sent within a given time window.
    """
    def __init__(self, max_requests: int = 50, time_window: int = 1):
        """
        Initialize the rate limiter.

        Args:
            max_requests: Maximum number of requests allowed in the time window.
            time_window: Time window in seconds.
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = []  # List to track the timestamps of requests.
        self._lock = asyncio.Lock()

    async def acquire(self):
        """
        Acquire permission to make a new request.

        This method waits if the number of requests in the current time window
        has reached the maximum allowed.
        """
        async with self._lock:
            now = datetime.utcnow()
            # Remove timestamps older than the time window.
            self.requests = [t for t in self.requests if (now - t) < timedelta(seconds=self.time_window)]

            if len(self.requests) >= self.max_requests:
                # Calculate sleep time based on the oldest request in the window.
                sleep_time = self.time_window - (now - min(self.requests)).total_seconds()
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)

            self.requests.append(now)


class OptimizedDiscordRequests:
    """
    Optimized interface for making Discord API requests.

    This class uses a DiscordRateLimiter and an asyncio semaphore to limit the rate
    and concurrency of API requests. It also caches member-not-found responses.
    """
    def __init__(self):
        self.rate_limiter = DiscordRateLimiter()
        self.semaphore = asyncio.Semaphore(50)  # Limit concurrent requests.
        self.not_found_cache = set()  # Cache for member not found responses.

    async def make_request(self, method: str, url: str, session: aiohttp.ClientSession, **kwargs) -> Optional[Dict[Any, Any]]:
        """
        Make an optimized Discord API request.

        If the member ID extracted from the URL is cached as not found, returns a cached response.
        Otherwise, it waits for rate limiter and semaphore before making the request.

        Args:
            method: HTTP method to use.
            url: The target API URL.
            session: An aiohttp.ClientSession instance.
            **kwargs: Additional parameters for the request.

        Returns:
            A dictionary with the response data if successful, or None.
        """
        member_id = self._extract_member_id(url)
        if member_id and member_id in self.not_found_cache:
            return {"detail": "Member not found (cached)"}

        async with self.semaphore:
            await self.rate_limiter.acquire()

            response = await make_discord_request(method, url, session, **kwargs)
            if response is None:
                # If a 404 occurred, cache the member as not found.
                if member_id:
                    self.not_found_cache.add(member_id)
                    return {"detail": "Member not found"}
                return None

            # If the response indicates an error, return it directly.
            if isinstance(response, dict) and 'error' in response:
                return response

            return response

    def _extract_member_id(self, url: str) -> Optional[str]:
        """
        Extract a member ID from a Discord API URL if present.

        Args:
            url: The API URL string.

        Returns:
            The extracted member ID, or None if not found.
        """
        try:
            if "/members/" in url:
                parts = url.split("/members/")
                if len(parts) > 1:
                    return parts[1].split("/")[0]
        except Exception:
            pass
        return None


# Global instance for convenience.
discord_client = OptimizedDiscordRequests()


async def optimized_discord_request(tasks: List[tuple]) -> List[Optional[Dict[Any, Any]]]:
    """
    Execute multiple Discord requests concurrently.

    Args:
        tasks: A list of tuples, each containing (method, url, kwargs_dict).

    Returns:
        A list of results corresponding to the tasks in the same order.
    """
    async with aiohttp.ClientSession() as aiosession:
        coros = []
        for (method, url, kw) in tasks:
            coros.append(discord_client.make_request(method, url, aiosession, **kw))
        
        results = await asyncio.gather(*coros, return_exceptions=False)
        return results


def send_to_discord_bot(endpoint: str, data: Dict[str, Any], method: str = 'POST') -> Optional[Dict[str, Any]]:
    """
    Send a request to the Discord bot API.

    This is a synchronous function for use within Celery tasks and other synchronous contexts.

    Args:
        endpoint: The API endpoint path (e.g., '/api/live-reporting/thread/create')
        data: Request payload data
        method: HTTP method to use

    Returns:
        Response data if successful, None if failed
    """
    try:
        # Get Discord bot URL from environment, default to localhost
        bot_url = os.getenv('DISCORD_BOT_URL', 'http://discord-bot:5001')

        # Construct full URL
        url = f"{bot_url.rstrip('/')}{endpoint}"

        logger.info(f"Sending {method} request to Discord bot: {url}")

        # Make the request
        response = requests.request(
            method=method,
            url=url,
            json=data,
            timeout=30,
            headers={'Content-Type': 'application/json'}
        )

        # Check if request was successful
        if response.status_code in [200, 201]:
            try:
                return response.json()
            except ValueError:
                logger.warning(f"Discord bot response not JSON: {response.text}")
                return {"success": True, "raw_response": response.text}
        else:
            logger.error(f"Discord bot request failed: {response.status_code} - {response.text}")
            return None

    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to connect to Discord bot at {url}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error sending request to Discord bot: {e}")
        return None