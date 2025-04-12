# shared_states.py

import asyncio
import discord
from discord.ext import commands
import logging

# Initialize logger
logger = logging.getLogger(__name__)

# Initialize bot_ready event
bot_ready = asyncio.Event()

from datetime import datetime, timedelta

class BotState:
    def __init__(self):
        # Store message_id -> {match_date, team_id, added_at} mapping
        self.managed_messages = {}
        self.bot_instance = None

    def add_managed_message_id(self, message_id, match_date=None, team_id=None):
        """
        Add a message ID to the managed messages with metadata.
        
        Args:
            message_id: The Discord message ID
            match_date: The date of the match (datetime or string)
            team_id: The team ID associated with this message
        """
        # Convert match_date to string if it's a datetime
        date_str = None
        if match_date:
            if isinstance(match_date, datetime):
                date_str = match_date.isoformat()
            else:
                date_str = str(match_date)
                
        self.managed_messages[message_id] = {
            'match_date': date_str,
            'team_id': team_id,
            'added_at': datetime.utcnow().isoformat()
        }
        logger.debug(f"Added managed message ID: {message_id} (match date: {date_str}, team: {team_id})")

    def remove_managed_message_id(self, message_id):
        """Remove a message ID from managed messages."""
        if message_id in self.managed_messages:
            self.managed_messages.pop(message_id)
            logger.debug(f"Removed managed message ID: {message_id}")

    def get_managed_message_ids(self, days_limit=None):
        """
        Get all managed message IDs, optionally filtered by date.
        
        Args:
            days_limit: Only include messages for matches within this many days
                        (before or after today). If None, return all messages.
        """
        if days_limit is None:
            # Return all message IDs (for backward compatibility)
            return set(self.managed_messages.keys())
            
        today = datetime.utcnow().date()
        relevant_ids = set()
        
        for message_id, metadata in self.managed_messages.items():
            match_date = metadata.get('match_date')
            
            # Default to keeping messages with unknown dates
            if not match_date:
                relevant_ids.add(message_id)
                continue
                
            # Try to parse the date
            try:
                if 'T' in match_date:  # ISO format with time
                    match_datetime = datetime.fromisoformat(match_date)
                    match_date = match_datetime.date()
                else:
                    # Try different date formats
                    for fmt in ['%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y']:
                        try:
                            match_date = datetime.strptime(match_date, fmt).date()
                            break
                        except ValueError:
                            continue
                            
                # If successful, check if within range
                if isinstance(match_date, datetime.date):
                    days_diff = abs((match_date - today).days)
                    if days_diff <= days_limit:
                        relevant_ids.add(message_id)
                        
            except (ValueError, TypeError):
                # If we can't parse the date, keep the message by default
                relevant_ids.add(message_id)
                
        return relevant_ids
        
    def cleanup_old_messages(self, days_threshold=14):
        """
        Remove messages for matches that are older than the threshold.
        
        Args:
            days_threshold: Remove messages for matches older than this many days
        
        Returns:
            Number of messages removed
        """
        today = datetime.utcnow().date()
        to_remove = []
        
        for message_id, metadata in self.managed_messages.items():
            match_date = metadata.get('match_date')
            if not match_date:
                continue
                
            # Try to parse the date
            try:
                if 'T' in match_date:  # ISO format with time
                    match_datetime = datetime.fromisoformat(match_date)
                    match_date = match_datetime.date()
                else:
                    # Try different date formats
                    for fmt in ['%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y']:
                        try:
                            match_date = datetime.strptime(match_date, fmt).date()
                            break
                        except ValueError:
                            continue
                
                # If the match date is in the past beyond threshold, mark for removal
                if isinstance(match_date, datetime.date):
                    days_old = (today - match_date).days
                    if days_old > days_threshold:
                        to_remove.append(message_id)
            except (ValueError, TypeError):
                # Skip messages with unparseable dates
                pass
        
        # Remove the old messages
        for message_id in to_remove:
            self.remove_managed_message_id(message_id)
            
        logger.info(f"Cleaned up {len(to_remove)} old messages older than {days_threshold} days")
        return len(to_remove)

    def set_bot_instance(self, bot: commands.Bot):
        self.bot_instance = bot
        logger.info(f"Bot instance has been set in shared_states. Bot ID: {bot.user.id if bot.user else 'Unknown'}")

    def get_bot_instance(self) -> commands.Bot:
        if self.bot_instance is None:
            logger.error("Attempt to access bot instance, but it is not set.")
        else:
            logger.info(f"Returning bot instance. Bot ID: {self.bot_instance.user.id if self.bot_instance.user else 'Unknown'}")
        return self.bot_instance

# Instantiate the state as a singleton
bot_state = BotState()

def set_bot_instance(bot: commands.Bot):
    """
    Sets the Discord bot instance in the shared state.
    """
    bot_state.set_bot_instance(bot)

def get_bot_instance() -> commands.Bot:
    """
    Gets the Discord bot instance from the shared state.
    """
    return bot_state.get_bot_instance()

async def periodic_check():
    """
    Periodically performs tasks related to the Discord bot:
    - Logs guild membership
    - Cleans up old managed messages
    - Performs other maintenance tasks
    """
    # Run cleanup every 6 hours (in seconds)
    CLEANUP_INTERVAL = 6 * 60 * 60
    last_cleanup_time = datetime.utcnow()
    
    while True:
        try:
            # Check bot status
            bot = bot_state.get_bot_instance()
            if bot:
                guild_count = len(bot.guilds)
                logger.info(f"Bot is currently in {guild_count} guild(s).")
                
                # Log managed message count with different timeframes
                all_messages = len(bot_state.get_managed_message_ids())
                this_week_messages = len(bot_state.get_managed_message_ids(days_limit=7))
                this_month_messages = len(bot_state.get_managed_message_ids(days_limit=30))
                
                logger.info(f"Managing {all_messages} total messages: {this_week_messages} for this week, {this_month_messages} for this month")
                
                # Check if it's time to clean up old messages (every 6 hours)
                now = datetime.utcnow()
                if (now - last_cleanup_time).total_seconds() >= CLEANUP_INTERVAL:
                    # Clean up messages for matches more than 14 days old
                    removed_count = bot_state.cleanup_old_messages(days_threshold=14)
                    if removed_count > 0:
                        logger.info(f"Cleaned up {removed_count} messages for matches that are more than 14 days old")
                    
                    # Update the last cleanup time
                    last_cleanup_time = now
            else:
                logger.warning("Bot instance not set in shared_states.")
                
            # Wait for 5 minutes before the next check
            await asyncio.sleep(5 * 60)
        except Exception as e:
            logger.error(f"Error in periodic_check: {e}")
            await asyncio.sleep(60)  # Wait before retrying in case of an error