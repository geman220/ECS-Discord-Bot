# automations.py

import asyncio
import pytz
from datetime import datetime, timedelta
from discord.ext import commands
from database import (
    get_db_connection, 
    PREDICTIONS_DB_PATH,
)
from match_utils import (
    prepare_match_environment, 
    create_and_manage_thread, 
    generate_thread_name, 
    get_next_match,
)
from common import (
    server_id, 
    team_id, 
    match_channel_id,
)


async def automated_match_thread_creation(bot: commands.Bot, server_id):
    guild = await bot.fetch_guild(server_id)
    if guild is None:
        print(f"Failed to find guild with ID {server_id}.")
        return

    channel_id = match_channel_id
    channel = bot.get_channel(channel_id)
    if channel is None:
        print("Channel 'match-thread' not found in guild.")
        return

    match_info = await get_next_match(team_id, for_automation=True)
    if isinstance(match_info, str):
        print(f"get_next_match returned a string: {match_info}")
        return

    if match_info:
        weather_forecast = ""
        if match_info.get("is_home_game"):
            _, weather_forecast = await prepare_match_environment(guild, match_info)
            print(f"Weather forecast for automated thread: {weather_forecast}")

        thread_name = generate_thread_name(match_info)

        match_commands_cog = bot.get_cog("Match Commands")
        if not match_commands_cog:
            return

        try:
            thread_response = await create_and_manage_thread(guild, match_info, match_commands_cog, channel, weather_forecast)
            print(f"Thread creation response: {thread_response}")
        except Exception as e:
            print(f"Error in creating thread: {e}")
            return 
        

async def check_and_create_match_threads(bot: commands.Bot):
    await bot.wait_until_ready()
    now = datetime.now(pytz.timezone("America/Los_Angeles"))
    end_time = now + timedelta(hours=24)

    with get_db_connection(PREDICTIONS_DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "SELECT match_id FROM match_schedule WHERE date_time > ? AND date_time <= ? AND thread_created = 0",
            (now, end_time)
        )
        upcoming_match_ids = [row[0] for row in c.fetchall()]

    for match_id in upcoming_match_ids:
        await automated_match_thread_creation(bot, server_id)

        with get_db_connection(PREDICTIONS_DB_PATH) as conn:
            c = conn.cursor()
            c.execute(
                "UPDATE match_schedule SET thread_created = 1 WHERE match_id = ?",
                (match_id,)
            )
            conn.commit()
            

async def periodic_check(bot: commands.Bot):
    await bot.wait_until_ready()
    while True:
        guild = await bot.fetch_guild(server_id)
        if guild:
            await check_and_create_match_threads(bot)
        await asyncio.sleep(3600)