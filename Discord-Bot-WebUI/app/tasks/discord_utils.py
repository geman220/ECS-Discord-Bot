"""
Discord Utilities for Task Operations

This module provides utility functions for Discord bot operations
within Celery tasks and background operations.
"""

import logging
from typing import Optional
from discord.ext import commands

logger = logging.getLogger(__name__)

# Global Discord bot instance
_discord_bot = None


def set_discord_bot(bot: commands.Bot):
    """
    Set the Discord bot instance for task operations.
    
    Args:
        bot: Discord bot instance
    """
    global _discord_bot
    _discord_bot = bot
    logger.info("Discord bot instance set for task operations")


def get_discord_bot() -> Optional[commands.Bot]:
    """
    Get the Discord bot instance for task operations.
    
    Returns:
        Discord bot instance or None if not set
    """
    global _discord_bot
    
    if _discord_bot is None:
        # Try to get bot instance from shared_states if not set locally
        try:
            import sys
            import os
            
            # Add the parent directory to the path so we can import from the Discord bot
            parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            if parent_dir not in sys.path:
                sys.path.append(parent_dir)
            
            from shared_states import get_bot_instance
            _discord_bot = get_bot_instance()
            
            if _discord_bot:
                logger.info("Successfully retrieved Discord bot instance from shared_states")
            else:
                logger.warning("Discord bot instance not available in shared_states")
                
        except Exception as e:
            logger.error(f"Error importing bot instance from shared_states: {e}")
            return None
    
    return _discord_bot


def is_discord_bot_ready() -> bool:
    """
    Check if the Discord bot is ready for operations.
    
    Returns:
        bool: True if bot is ready, False otherwise
    """
    bot = get_discord_bot()
    if bot is None:
        return False
    
    return bot.is_ready()


async def safe_discord_operation(operation_func, *args, **kwargs):
    """
    Safely execute a Discord operation with error handling.
    
    Args:
        operation_func: Function to execute
        *args: Arguments for the function
        **kwargs: Keyword arguments for the function
        
    Returns:
        Tuple of (success: bool, result: any)
    """
    try:
        if not is_discord_bot_ready():
            logger.error("Discord bot not ready for operations")
            return False, None
        
        result = await operation_func(*args, **kwargs)
        return True, result
    except Exception as e:
        logger.error(f"Discord operation failed: {e}")
        return False, None