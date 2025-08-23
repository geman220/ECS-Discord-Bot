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
import time
from typing import Dict, Optional
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerStats:
    failure_count: int = 0
    last_failure_time: float = 0
    last_success_time: float = 0
    state: CircuitState = CircuitState.CLOSED


class DiscordBotCircuitBreaker:
    """Circuit breaker for Discord bot API calls to prevent cascading failures."""
    
    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.stats = CircuitBreakerStats()
    
    def record_success(self):
        """Record a successful call."""
        self.stats.failure_count = 0
        self.stats.last_success_time = time.time()
        self.stats.state = CircuitState.CLOSED
        logger.debug("Discord bot circuit breaker: SUCCESS recorded")
    
    def record_failure(self):
        """Record a failed call."""
        self.stats.failure_count += 1
        self.stats.last_failure_time = time.time()
        
        if self.stats.failure_count >= self.failure_threshold:
            self.stats.state = CircuitState.OPEN
            logger.warning(f"Discord bot circuit breaker: OPENED after {self.stats.failure_count} failures")
    
    def can_proceed(self) -> bool:
        """Check if calls should be allowed."""
        if self.stats.state == CircuitState.CLOSED:
            return True
        
        if self.stats.state == CircuitState.OPEN:
            if time.time() - self.stats.last_failure_time > self.recovery_timeout:
                self.stats.state = CircuitState.HALF_OPEN
                logger.info("Discord bot circuit breaker: Moving to HALF_OPEN state")
                return True
            return False
        
        # HALF_OPEN state - allow one call to test
        return True
    
    def get_status(self) -> Dict:
        """Get current circuit breaker status."""
        return {
            'state': self.stats.state.value,
            'failure_count': self.stats.failure_count,
            'last_failure_time': self.stats.last_failure_time,
            'last_success_time': self.stats.last_success_time,
            'can_proceed': self.can_proceed()
        }


# Global circuit breaker instance
_circuit_breaker = DiscordBotCircuitBreaker()


async def send_discord_update(
    thread_id: str,
    update_type: str,
    update_data: str,
    timeout: int = 30,
    max_retries: int = 3
) -> bool:
    """
    Send an update to a Discord thread via the Discord bot API with circuit breaker and retry logic.

    Args:
        thread_id: The ID of the Discord thread to update.
        update_type: A string indicating the type of update (e.g., "score_update").
        update_data: The content of the update message.
        timeout: Optional timeout for the API request in seconds (default is 30).
        max_retries: Maximum number of retry attempts (default is 3).

    Returns:
        bool: True if successful, False if failed (circuit breaker open or max retries exceeded).
    """
    # Check circuit breaker before attempting
    if not _circuit_breaker.can_proceed():
        logger.warning(f"Discord bot circuit breaker is OPEN - skipping {update_type} update to thread {thread_id}")
        return False

    bot_api_url = "http://discord-bot:5001"
    endpoint = "/post_match_update"
    url = f"{bot_api_url}{endpoint}"

    payload = {
        "thread_id": thread_id,
        "update_type": update_type,
        "update_data": update_data
    }

    for attempt in range(max_retries):
        try:
            # Exponential backoff delay
            if attempt > 0:
                delay = min(2 ** (attempt - 1), 30)  # Max 30 second delay
                logger.info(f"Retrying Discord update after {delay}s delay (attempt {attempt + 1}/{max_retries})")
                await asyncio.sleep(delay)

            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=timeout) as response:
                    if response.status == 200:
                        _circuit_breaker.record_success()
                        logger.info(f"Successfully sent {update_type} update to thread {thread_id}")
                        return True

                    # Non-200 status - log and continue to retry
                    error_text = await response.text()
                    logger.warning(
                        f"Discord API returned {response.status} for {update_type} update "
                        f"(attempt {attempt + 1}/{max_retries}): {error_text}"
                    )
                    
                    # Don't retry on client errors (4xx)
                    if 400 <= response.status < 500:
                        logger.error(f"Client error {response.status} - not retrying")
                        _circuit_breaker.record_failure()
                        return False

        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.warning(
                f"Connection error sending {update_type} update "
                f"(attempt {attempt + 1}/{max_retries}): {str(e)}"
            )
        except Exception as e:
            logger.error(
                f"Unexpected error sending {update_type} update "
                f"(attempt {attempt + 1}/{max_retries}): {str(e)}",
                exc_info=True
            )

    # All retries failed
    _circuit_breaker.record_failure()
    logger.error(
        f"Failed to send {update_type} update to thread {thread_id} "
        f"after {max_retries} attempts"
    )
    return False


async def check_discord_bot_health() -> Dict:
    """
    Check Discord bot health and return status information.
    
    Returns:
        Dict containing health status and circuit breaker information.
    """
    if not _circuit_breaker.can_proceed():
        return {
            'status': 'circuit_breaker_open',
            'healthy': False,
            'circuit_breaker': _circuit_breaker.get_status(),
            'message': 'Circuit breaker is open - Discord bot calls are being blocked'
        }

    bot_api_url = "http://discord-bot:5001"
    url = f"{bot_api_url}/api/health"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    _circuit_breaker.record_success()
                    return {
                        'status': 'healthy',
                        'healthy': True,
                        'circuit_breaker': _circuit_breaker.get_status(),
                        'response_status': response.status
                    }
                else:
                    _circuit_breaker.record_failure()
                    return {
                        'status': 'unhealthy',
                        'healthy': False,
                        'circuit_breaker': _circuit_breaker.get_status(),
                        'response_status': response.status,
                        'message': f'Discord bot returned status {response.status}'
                    }
    except Exception as e:
        _circuit_breaker.record_failure()
        return {
            'status': 'unreachable',
            'healthy': False,
            'circuit_breaker': _circuit_breaker.get_status(),
            'error': str(e),
            'message': 'Discord bot is unreachable'
        }


def get_circuit_breaker_status() -> Dict:
    """Get the current circuit breaker status."""
    return _circuit_breaker.get_status()


def reset_circuit_breaker():
    """Reset the circuit breaker to closed state (admin function)."""
    global _circuit_breaker
    _circuit_breaker = DiscordBotCircuitBreaker()
    logger.info("Discord bot circuit breaker has been reset")