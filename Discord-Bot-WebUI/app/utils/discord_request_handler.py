import asyncio
import aiohttp
from typing import Optional, Dict, Any
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class DiscordRateLimiter:
    def __init__(self, max_requests: int = 50, time_window: int = 1):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = []
        self._lock = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            now = datetime.utcnow()
            # Remove old requests
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
            
            try:
                async with session.request(method, url, timeout=10, **kwargs) as response:
                    if response.status in [200, 201, 204]:
                        return await response.json() if response.content_length else None

                    if response.status == 404:
                        response_text = await response.text()
                        if "Member not found" in response_text and member_id:
                            self.not_found_cache.add(member_id)
                            return {"detail": "Member not found"}

                    if response.status == 429:
                        retry_after = float(response.headers.get('Retry-After', '1'))
                        await asyncio.sleep(retry_after)
                        return await self.make_request(method, url, session, **kwargs)

                    error_text = await response.text()
                    return {"error": error_text, "status": response.status}

            except asyncio.TimeoutError:
                logger.warning(f"Request timeout for {url}")
                return {"error": "Request timeout"}
            except Exception as e:
                logger.error(f"Request error: {str(e)}")
                return {"error": str(e)}

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

# Global instance
discord_client = OptimizedDiscordRequests()

# Wrapper function to maintain existing interface
async def optimized_discord_request(method: str, url: str, session: aiohttp.ClientSession, **kwargs) -> Optional[Dict[Any, Any]]:
    return await discord_client.make_request(method, url, session, **kwargs)
