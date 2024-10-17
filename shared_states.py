# shared_states.py

import asyncio
import discord
from discord.ext import commands
import logging

# Initialize logger
logger = logging.getLogger(__name__)

# Initialize bot_ready event
bot_ready = asyncio.Event()

class BotState:
    def __init__(self):
        self.managed_message_ids = set()
        self.bot_instance = None

    def add_managed_message_id(self, message_id):
        self.managed_message_ids.add(message_id)
        logger.debug(f"Added managed message ID: {message_id}")

    def remove_managed_message_id(self, message_id):
        self.managed_message_ids.discard(message_id)
        logger.debug(f"Removed managed message ID: {message_id}")

    def get_managed_message_ids(self):
        return self.managed_message_ids

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
    Periodically performs tasks related to the Discord bot.
    """
    while True:
        try:
            bot = bot_state.get_bot_instance()
            if bot:
                guild_count = len(bot.guilds)
                logger.info(f"Bot is currently in {guild_count} guild(s).")
            else:
                logger.warning("Bot instance not set in shared_states.")
            await asyncio.sleep(60)  # Wait for 1 minute before the next check
        except Exception as e:
            logger.error(f"Error in periodic_check: {e}")
            await asyncio.sleep(60)  # Wait before retrying in case of an error