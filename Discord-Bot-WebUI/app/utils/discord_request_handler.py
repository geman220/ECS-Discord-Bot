import asyncio
import aiohttp
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

async def make_discord_request(
    method: str, url: str, session: aiohttp.ClientSession, retries: int = 3, delay: float = 0.5, **kwargs
) -> Any:
    """Make a Discord API request with retries, handling 404 and 429 responses.
    
    This version always attempts to parse the response as JSON. If it's not JSON,
    it logs an error and returns None.
    """
    logger.debug(f"Discord request: {method} {url}, kwargs={kwargs}")
    for attempt in range(retries):
        try:
            async with session.request(method, url, **kwargs) as response:
                if response.status == 404:
                    logger.warning(f"404 Not Found for URL: {url}")
                    return None
                elif response.status == 429:
                    # Rate limited by Discord
                    retry_after = float(response.headers.get('Retry-After', '1'))
                    logger.warning(f"Rate limited (429) by Discord. Retrying after {retry_after}s")
                    await asyncio.sleep(retry_after)
                    continue
                elif response.status >= 400:
                    response_text = await response.text()
                    logger.error(f"Error {response.status} for {url}: {response_text}")
                    response.raise_for_status()
                else:
                    # Successful response
                    try:
                        return await response.json()
                    except (aiohttp.ContentTypeError, ValueError) as e:
                        # The response isn't valid JSON
                        logger.error(f"Failed to decode JSON from {url}: {e}")
                        return None

        except Exception as e:
            logger.error(f"Attempt {attempt + 1} - Error on {method} request to {url}: {e}")
            await asyncio.sleep(delay)

    logger.error(f"Failed to complete {method} request to {url} after {retries} attempts.")
    return None

class DiscordRateLimiter:
    def __init__(self, max_requests: int = 50, time_window: int = 1):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = []
        self._lock = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            now = datetime.utcnow()
            # Remove old requests outside the time window
            self.requests = [t for t in self.requests if (now - t) < timedelta(seconds=self.time_window)]

            if len(self.requests) >= self.max_requests:
                sleep_time = self.time_window - (now - min(self.requests)).total_seconds()
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)

            self.requests.append(now)


class OptimizedDiscordRequests:
    def __init__(self):
        self.rate_limiter = DiscordRateLimiter()
        self.semaphore = asyncio.Semaphore(50)  # Limit concurrent requests
        self.not_found_cache = set()  # Cache for member not found responses

    async def make_request(self, method: str, url: str, session: aiohttp.ClientSession, **kwargs) -> Optional[Dict[Any, Any]]:
        member_id = self._extract_member_id(url)
        if member_id and member_id in self.not_found_cache:
            return {"detail": "Member not found (cached)"}

        async with self.semaphore:
            await self.rate_limiter.acquire()

            response = await make_discord_request(method, url, session, **kwargs)
            if response is None:
                # Could be a 404 or failed after retries
                # If we previously got None due to 404:
                if member_id:
                    self.not_found_cache.add(member_id)
                    return {"detail": "Member not found"}
                return None

            # If response has an error field, it's an error from make_discord_request
            if isinstance(response, dict) and 'error' in response:
                # Return it as is
                return response

            return response

    def _extract_member_id(self, url: str) -> Optional[str]:
        """Extract member ID from Discord API URL if present."""
        try:
            if "/members/" in url:
                parts = url.split("/members/")
                if len(parts) > 1:
                    return parts[1].split("/")[0]
        except:
            pass
        return None


# Global instance for convenience
discord_client = OptimizedDiscordRequests()

async def optimized_discord_request(tasks: List[tuple]) -> List[Optional[Dict[Any, Any]]]:
    """
    Execute multiple Discord requests concurrently.
    tasks: list of tuples (method, url, kwargs_dict)
    Returns a list of results in the same order.
    """
    async with aiohttp.ClientSession() as aiosession:
        coros = []
        for (method, url, kw) in tasks:
            coros.append(discord_client.make_request(method, url, aiosession, **kw))
        
        results = await asyncio.gather(*coros, return_exceptions=False)
        return results
