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
        # Store poll message_id -> {poll_id, team_id, channel_id} mapping
        self.poll_messages = {}
        self.bot_instance = None
        # Track command usage by date
        self.command_stats = {}
        # Track start time for uptime calculation
        self.start_time = datetime.utcnow()
        # Track recent bot logs
        self.recent_logs = []
        # Track message activity
        self.message_stats = {}
        # Track member join activity
        self.member_activity = {}

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
        Also cleans up old poll messages based on their creation time.
        
        Args:
            days_threshold: Remove messages for matches older than this many days
        
        Returns:
            Number of messages removed
        """
        today = datetime.utcnow().date()
        to_remove = []
        poll_messages_removed = 0
        
        for message_id, metadata in self.managed_messages.items():
            match_date = metadata.get('match_date')
            added_at = metadata.get('added_at')
            
            # Handle match messages with dates
            if match_date:
                # Try to parse the match date
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
            
            # Handle poll messages and other messages without match dates
            elif added_at:
                try:
                    # Parse the added_at timestamp
                    if 'T' in added_at:
                        added_datetime = datetime.fromisoformat(added_at)
                    else:
                        added_datetime = datetime.strptime(added_at, '%Y-%m-%d %H:%M:%S')
                    
                    # Check if this message is older than threshold
                    days_old = (datetime.utcnow() - added_datetime).days
                    if days_old > days_threshold:
                        to_remove.append(message_id)
                        # Count poll messages separately for logging
                        if message_id in self.poll_messages:
                            poll_messages_removed += 1
                            
                except (ValueError, TypeError):
                    # If we can't parse added_at, skip this message
                    pass
        
        # Remove the old messages
        for message_id in to_remove:
            self.remove_managed_message_id(message_id)
            # Also remove from poll_messages if it's there
            if message_id in self.poll_messages:
                del self.poll_messages[message_id]
        
        regular_messages_removed = len(to_remove) - poll_messages_removed
        logger.info(f"Cleaned up {len(to_remove)} old messages older than {days_threshold} days "
                   f"({regular_messages_removed} match messages, {poll_messages_removed} poll messages)")
        return len(to_remove)

    def track_command_usage(self, command_name=None):
        """Track command usage by date."""
        try:
            today = datetime.utcnow().date()
            date_key = str(today)
            
            # Increment daily command count
            self.command_stats[date_key] = self.command_stats.get(date_key, 0) + 1
            
            # Log command usage
            if command_name:
                self.log_activity(f"Command executed: /{command_name}")
                logger.debug(f"Command '{command_name}' executed. Daily total: {self.command_stats[date_key]}")
        except Exception as e:
            logger.error(f"Error tracking command usage: {e}")

    def track_message_activity(self, guild_id=None):
        """Track message activity by hour."""
        try:
            now = datetime.utcnow()
            hour_key = now.strftime("%Y-%m-%d-%H")
            
            if hour_key not in self.message_stats:
                self.message_stats[hour_key] = 0
            self.message_stats[hour_key] += 1
            
            # Keep only last 24 hours of data
            cutoff = now - timedelta(hours=24)
            cutoff_key = cutoff.strftime("%Y-%m-%d-%H")
            
            # Remove old entries
            old_keys = [k for k in self.message_stats.keys() if k < cutoff_key]
            for key in old_keys:
                del self.message_stats[key]
                
        except Exception as e:
            logger.error(f"Error tracking message activity: {e}")

    def track_member_join(self, member_id, guild_id):
        """Track member join activity."""
        try:
            today = str(datetime.utcnow().date())
            
            if today not in self.member_activity:
                self.member_activity[today] = []
            
            self.member_activity[today].append({
                'member_id': member_id,
                'guild_id': guild_id,
                'joined_at': datetime.utcnow().isoformat()
            })
            
            self.log_activity(f"New member joined: {member_id}")
            
            # Keep only last 7 days
            cutoff = datetime.utcnow() - timedelta(days=7)
            cutoff_date = str(cutoff.date())
            
            old_dates = [d for d in self.member_activity.keys() if d < cutoff_date]
            for date in old_dates:
                del self.member_activity[date]
                
        except Exception as e:
            logger.error(f"Error tracking member join: {e}")

    def log_activity(self, message, level="INFO"):
        """Log bot activity."""
        try:
            log_entry = {
                "timestamp": datetime.utcnow().isoformat(),
                "level": level,
                "message": message
            }
            
            self.recent_logs.append(log_entry)
            
            # Keep only last 100 log entries
            if len(self.recent_logs) > 100:
                self.recent_logs = self.recent_logs[-100:]
                
        except Exception as e:
            logger.error(f"Error logging activity: {e}")

    def get_messages_last_hour(self):
        """Get message count for the last hour."""
        try:
            now = datetime.utcnow()
            current_hour = now.strftime("%Y-%m-%d-%H")
            return self.message_stats.get(current_hour, 0)
        except Exception as e:
            logger.error(f"Error getting messages last hour: {e}")
            return 0

    def get_new_members_today(self, guild_id=None):
        """Get count of new members today."""
        try:
            today = str(datetime.utcnow().date())
            members_today = self.member_activity.get(today, [])
            
            if guild_id:
                members_today = [m for m in members_today if m['guild_id'] == guild_id]
            
            return len(members_today)
        except Exception as e:
            logger.error(f"Error getting new members today: {e}")
            return 0

    def set_bot_instance(self, bot: commands.Bot):
        self.bot_instance = bot
        # Set start time when bot is ready
        if not hasattr(self, 'start_time') or self.start_time is None:
            self.start_time = datetime.utcnow()
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
                active_messages = len(bot_state.get_managed_message_ids(days_limit=14))
                this_month_messages = len(bot_state.get_managed_message_ids(days_limit=30))
                
                logger.info(f"Managing {all_messages} total messages: {active_messages} active (14 days), {this_month_messages} within month")
                
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