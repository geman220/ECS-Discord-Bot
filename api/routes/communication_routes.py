"""
FastAPI Communication Routes for Discord Bot Operations.
Handles direct messaging, thread messaging, and match updates.

Extracted from bot_rest_api.py to create a modular router.
"""

from fastapi import APIRouter, HTTPException, Depends, Body
from discord.ext import commands
import discord
import logging
import random
from typing import Optional

from api.utils.discord_utils import get_bot
from api.utils.embeds import create_match_embed

# Set up logging
logger = logging.getLogger(__name__)

# Create router
router = APIRouter()

# FIX THIS AFTER TESTING - should be configurable
TEAM_ID = '9726'


# Dependencies imported from utils modules


@router.post("/send_discord_dm")
async def send_discord_dm(
    message: str = Body(..., embed=True, description="The message to send"),
    discord_id: str = Body(..., embed=True, description="The player's Discord ID"),
    bot: commands.Bot = Depends(get_bot)
):
    """Send a direct message to a Discord user."""
    # Fetch the Discord user by their discord_id
    try:
        user = await bot.fetch_user(int(discord_id))
    except Exception as e:
        raise HTTPException(status_code=404, detail="User not found or Discord ID invalid")
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Attempt to send a DM to the user
    try:
        dm_channel = await user.create_dm()
        dm_message = await dm_channel.send(message)
        return {"status": "sent", "message_id": dm_message.id}
    except discord.Forbidden:
        raise HTTPException(status_code=403, detail="Cannot send DM to this user. They may have DMs disabled.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send DM: {str(e)}")


@router.post("/channels/{thread_id}/messages")
async def send_message_to_thread(thread_id: int, content: str, bot: commands.Bot = Depends(get_bot)):
    """Send a message to a specific Discord thread."""
    thread = bot.get_channel(thread_id)
    if not thread or not isinstance(thread, discord.Thread):
        raise HTTPException(status_code=404, detail="Thread not found")

    try:
        message = await thread.send(content)
        logger.info(f"Sent message to thread {thread_id}")
        return {"message_id": message.id, "content": message.content}
    except discord.errors.Forbidden:
        raise HTTPException(status_code=403, detail="Bot doesn't have permission to send messages to this thread")
    except discord.errors.HTTPException as e:
        logger.error(f"Failed to send message to thread: {e}")
        raise HTTPException(status_code=500, detail="Failed to send message to thread")


@router.post("/post_match_update")
async def post_match_update(update: dict, bot: commands.Bot = Depends(get_bot)):
    """Post a match update to a Discord thread."""
    thread_id = update.get("thread_id")
    update_type = update.get("update_type")
    update_data = update.get("update_data", {})

    try:
        embed = create_match_embed(update_type, update_data)
        
        channel = bot.get_channel(int(thread_id))
        if channel:
            await channel.send(embed=embed)
            logger.info(f"Successfully sent {update_type} update to thread {thread_id}")
        else:
            logger.error(f"Channel {thread_id} not found")
            raise HTTPException(status_code=404, detail=f"Channel {thread_id} not found")

    except Exception as e:
        logger.error(f"Error in post_match_update: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

    return {"success": True}


# Helper functions for creating match embeds
def create_match_embed(update_type, update_data):
    """Create a Discord embed for different types of match updates."""
    focus_team_id = str(TEAM_ID)  # Our team ID

    if update_type == "score_update":
        return create_score_update_embed(update_data, focus_team_id)
    elif update_type in ["match_event", "hype_event"]:
        return create_match_event_embed(update_data, focus_team_id, is_hype=(update_type == "hype_event"))
    elif update_type == "halftime":
        return create_halftime_embed(update_data, focus_team_id)
    elif update_type == "fulltime":
        # Extract match_id from update_data (ensure update_data contains it)
        match_id = update_data.get("match_id")
        return create_fulltime_embed(match_id, update_data, focus_team_id)
    elif update_type == "match_started":
        # Create a special kickoff embed to avoid duplicate messages
        return create_match_started_embed(update_data, focus_team_id)
    elif update_type in ["status_scheduled", "pre_match_info"]:
        return create_pre_match_embed(update_data, focus_team_id)
    else:
        logger.warning(f"Unknown update type: {update_type}")
        embed = discord.Embed(
            title="Match Update",
            description="An update has occurred."
        )
        return embed


def create_match_started_embed(update_data, focus_team_id):
    """Create an embed for match kickoff."""
    home_team = update_data.get('home_team', {})
    away_team = update_data.get('away_team', {})
    home_team_name = home_team.get('displayName', "Home Team")
    away_team_name = away_team.get('displayName', "Away Team")
    home_team_id = str(home_team.get('id', ""))
    away_team_id = str(away_team.get('id', ""))

    embed = discord.Embed()
    embed.title = f"🏟️ Kickoff! {home_team_name} vs {away_team_name}"
    embed.color = discord.Color.green()
    
    # Check if our team is playing
    if home_team_id == focus_team_id:
        embed.description = f"**{home_team_name}** 0 - 0 {away_team_name}"
        embed.set_thumbnail(url=home_team.get('logo'))
        embed.add_field(name="Let's Go!", value="The match has started! Let's go Sounders! 💚", inline=False)
    elif away_team_id == focus_team_id:
        embed.description = f"{home_team_name} 0 - 0 **{away_team_name}**"
        embed.set_thumbnail(url=away_team.get('logo'))
        embed.add_field(name="Let's Go!", value="The match has started! Let's go Sounders! 💚", inline=False)
    else:
        embed.description = f"{home_team_name} 0 - 0 {away_team_name}"
        embed.color = discord.Color.blue()
        embed.add_field(name="Kickoff", value="The match has started!", inline=False)

    embed.add_field(name="Time", value="Kickoff", inline=True)
    
    return embed


def create_score_update_embed(update_data, focus_team_id):
    """Create an embed for score updates."""
    # Extract current and previous scores
    home_team = update_data.get('home_team', {})
    away_team = update_data.get('away_team', {})
    home_score = int(update_data.get('home_score', "0"))
    away_score = int(update_data.get('away_score', "0"))
    previous_home_score = int(update_data.get('previous_home_score', home_score))
    previous_away_score = int(update_data.get('previous_away_score', away_score))
    time = update_data.get('time', "N/A")

    # Determine if a goal has been scored
    goal_scored = False
    if home_score > previous_home_score or away_score > previous_away_score:
        goal_scored = True
        # Prepare event data for the goal
        if home_score > previous_home_score:
            scoring_team = home_team
            scoring_team_id = str(home_team.get('id', ""))
            scoring_team_name = home_team.get('displayName', "Home Team")
        else:
            scoring_team = away_team
            scoring_team_id = str(away_team.get('id', ""))
            scoring_team_name = away_team.get('displayName', "Away Team")

        # Include player information if available
        goal_scorer = update_data.get('goal_scorer', {})
        event_data = {
            'type': 'Goal',
            'team': scoring_team,
            'player': goal_scorer,
            'time': time,
            'home_team': home_team,
            'away_team': away_team,
            'home_score': str(home_score),
            'away_score': str(away_score)
        }
        return create_match_event_embed(event_data, focus_team_id)

    # If no goal, create a generic score update embed
    home_team_name = home_team.get('displayName', "Home Team")
    away_team_name = away_team.get('displayName', "Away Team")
    home_team_id = str(home_team.get('id', ""))
    away_team_id = str(away_team.get('id', ""))

    embed = discord.Embed()
    embed.add_field(name="Time", value=time, inline=True)

    if home_team_id == focus_team_id:
        embed.title = f"⚽ Score Update: {home_team_name} vs {away_team_name}"
        embed.description = f"**{home_team_name}** {home_score} - {away_score} {away_team_name}"
        embed.set_thumbnail(url=home_team.get('logo'))
        # Randomized messages for our team scoring conditions
        if home_score > away_score:
            messages = [
                "We're in the lead! Keep pushing! 🔥",
                "On top of the game—let's maintain our momentum! 🚀",
                "Great job! We're ahead. Stay focused! 💪"
            ]
            embed.color = discord.Color.green()
            embed.add_field(name="Status", value=random.choice(messages), inline=False)
        elif home_score < away_score:
            messages = [
                "We're behind, but it's not over! Let's rally! 💪",
                "Time to step it up—fight back! ⚡",
                "Challenging start, but we can turn it around! 🔥"
            ]
            embed.color = discord.Color.red()
            embed.add_field(name="Status", value=random.choice(messages), inline=False)
        else:
            messages = [
                "It's all square! Time to take control! ⚖️",
                "Evenly matched—now's our chance to break through! 🌟",
                "The score is level. Let's create an opportunity! ⚽"
            ]
            embed.color = discord.Color.gold()
            embed.add_field(name="Status", value=random.choice(messages), inline=False)
    elif away_team_id == focus_team_id:
        embed.title = f"⚽ Score Update: {home_team_name} vs {away_team_name}"
        embed.description = f"{home_team_name} {home_score} - {away_score} **{away_team_name}**"
        embed.set_thumbnail(url=away_team.get('logo'))
        if away_score > home_score:
            messages = [
                "We're ahead! Keep the pressure on! 💪",
                "Fantastic! We're leading on the road! 🚀",
                "In the lead—stay sharp and maintain the edge! 🔥"
            ]
            embed.color = discord.Color.green()
            embed.add_field(name="Status", value=random.choice(messages), inline=False)
        elif away_score < home_score:
            messages = [
                "We're behind, but there's still time! Let's fight back! 💪",
                "Away challenge—time to show our strength! ⚡",
                "Trailing on the road, but we can turn it around! 🔥"
            ]
            embed.color = discord.Color.red()
            embed.add_field(name="Status", value=random.choice(messages), inline=False)
        else:
            messages = [
                "Level away from home! Let's push for the win! ⚽",
                "All square on the road—time to take control! 🌟",
                "Even match—now's our chance to break through! 💪"
            ]
            embed.color = discord.Color.gold()
            embed.add_field(name="Status", value=random.choice(messages), inline=False)
    else:
        # Neither team is our focus team
        embed.title = f"⚽ Score Update: {home_team_name} vs {away_team_name}"
        embed.description = f"{home_team_name} {home_score} - {away_score} {away_team_name}"
        embed.color = discord.Color.blue()

    return embed


def create_match_event_embed(event_data, focus_team_id, is_hype=False):
    """Create an embed for match events (goals, cards, substitutions)."""
    event_type = event_data.get('type', '')
    event_team = event_data.get('team', {})
    event_time = event_data.get('time', "N/A")
    athlete = event_data.get('player', {})
    home_team = event_data.get('home_team', {})
    away_team = event_data.get('away_team', {})
    home_score = event_data.get('home_score', "0")
    away_score = event_data.get('away_score', "0")

    event_team_id = str(event_team.get('id', ""))
    event_team_name = event_team.get('displayName', "Unknown Team")
    is_focus_team_event = event_team_id == focus_team_id

    # Prepare embed based on event type and favorability
    if event_type == "Goal":
        embed = create_goal_embed(event_team_name, athlete, is_focus_team_event, event_time, is_hype)
    elif event_type in ["Yellow Card", "Red Card"]:
        embed = create_card_embed(event_type, event_team_name, athlete, is_focus_team_event, event_time, is_hype)
    elif event_type == "Substitution":
        embed = create_substitution_embed(event_team_name, athlete, is_focus_team_event, event_time)
    else:
        embed = discord.Embed(
            title=f"{event_type} - {event_team_name}",
            description=f"An event occurred for {event_team_name}."
        )
        embed.color = discord.Color.green() if is_hype else discord.Color.blue()
        embed.add_field(name="Time", value=event_time, inline=True)

    # Add current score to the embed
    home_team_name = home_team.get('displayName', "Home Team")
    away_team_name = away_team.get('displayName', "Away Team")
    embed.add_field(name="Score", value=f"{home_team_name} {home_score} - {away_score} {away_team_name}", inline=False)

    # Add player image
    add_player_image(embed, athlete)

    return embed


def create_goal_embed(team_name, athlete, is_focus_team_event, event_time, is_hype):
    """Create an embed for goal events."""
    scorer_name = athlete.get('displayName', "Unknown Player")
    if is_focus_team_event:
        messages = [
            f"🎉 GOOOOOAAAALLLL! {scorer_name} scores for {team_name} at {event_time}! Keep it coming! ⚽🔥",
            f"Goal! {scorer_name} puts {team_name} in the lead at {event_time}! Amazing strike! 🚀",
            f"Fantastic! {scorer_name} nets one for {team_name} at {event_time}! Let's keep the momentum! 💪"
        ]
        embed = discord.Embed(
            title=random.choice(messages),
            color=discord.Color.green()
        )
    else:
        messages = [
            f"😡 Goal for {team_name} by {scorer_name} at {event_time}. We must fight back! 💪",
            f"{scorer_name} scores for the opposition at {event_time}. Time to regroup! ⚡",
            f"They take the lead... {scorer_name} scores for {team_name} at {event_time}. Let's counterattack! 🔥"
        ]
        embed = discord.Embed(
            title=random.choice(messages),
            color=discord.Color.red()
        )
    return embed


def create_card_embed(card_type, team_name, athlete, is_focus_team_event, event_time, is_hype):
    """Create an embed for card events."""
    player_name = athlete.get('displayName', "Unknown Player")
    emoji = "🟨" if card_type == "Yellow Card" else "🟥"
    if is_hype:
        messages = [
            f"{emoji} {card_type} for {team_name}! {player_name} gets booked at {event_time}. Advantage us! 😈",
            f"{emoji} A booking for {team_name} at {event_time}! {player_name} should be more careful! 🔥"
        ]
        embed = discord.Embed(
            title=random.choice(messages),
            color=discord.Color.green()
        )
    else:
        messages = [
            f"{emoji} {card_type} for {team_name}: {player_name} received it at {event_time}. Stay focused!",
            f"{emoji} {player_name} got a {card_type.lower()} at {event_time} for {team_name}. Let's tighten up our play!"
        ]
        embed = discord.Embed(
            title=random.choice(messages),
            color=discord.Color.red() if card_type == "Red Card" else discord.Color.gold()
        )
    return embed


def create_substitution_embed(team_name, athlete, is_focus_team_event, event_time):
    """Create an embed for substitution events."""
    player_in = athlete.get('in', {}).get('displayName', "Unknown Player")
    player_out = athlete.get('out', {}).get('displayName', "Unknown Player")

    if is_focus_team_event:
        embed = discord.Embed(
            title=f"🔄 Substitution for {team_name}",
            description=f"{player_in} comes on for {player_out} at {event_time}. Fresh legs! 🏃‍♂️",
            color=discord.Color.blue()
        )
    else:
        embed = discord.Embed(
            title=f"🔄 Substitution for {team_name}",
            description=f"{team_name} brings on {player_in} for {player_out} at {event_time}. Stay focused!",
            color=discord.Color.light_grey()
        )

    return embed


def add_player_image(embed, athlete):
    """Add player image to embed if available."""
    if isinstance(athlete, dict) and 'id' in athlete:
        player_id = athlete['id']
        player_image_url = f"https://a.espncdn.com/combiner/i?img=/i/headshots/soccer/players/full/{player_id}.png"
        embed.set_thumbnail(url=player_image_url)


def create_halftime_embed(update_data, focus_team_id):
    """Create an embed for halftime."""
    home_team = update_data.get('home_team', {})
    away_team = update_data.get('away_team', {})
    home_score = update_data.get('home_score', "0")
    away_score = update_data.get('away_score', "0")
    
    home_team_name = home_team.get('displayName', "Home Team")
    away_team_name = away_team.get('displayName', "Away Team")
    home_team_id = str(home_team.get('id', ""))
    away_team_id = str(away_team.get('id', ""))

    embed = discord.Embed()
    embed.title = f"⏰ Halftime: {home_team_name} vs {away_team_name}"
    embed.color = discord.Color.orange()
    
    if home_team_id == focus_team_id:
        embed.description = f"**{home_team_name}** {home_score} - {away_score} {away_team_name}"
        embed.set_thumbnail(url=home_team.get('logo'))
    elif away_team_id == focus_team_id:
        embed.description = f"{home_team_name} {home_score} - {away_score} **{away_team_name}**"
        embed.set_thumbnail(url=away_team.get('logo'))
    else:
        embed.description = f"{home_team_name} {home_score} - {away_score} {away_team_name}"

    embed.add_field(name="Status", value="Halftime break - 15 minutes", inline=False)
    embed.add_field(name="Time", value="45'+", inline=True)
    
    return embed


def create_fulltime_embed(match_id, update_data, focus_team_id):
    """Create an embed for fulltime result."""
    home_team = update_data.get('home_team', {})
    away_team = update_data.get('away_team', {})
    home_score = update_data.get('home_score', "0")
    away_score = update_data.get('away_score', "0")
    
    home_team_name = home_team.get('displayName', "Home Team")
    away_team_name = away_team.get('displayName', "Away Team")
    home_team_id = str(home_team.get('id', ""))
    away_team_id = str(away_team.get('id', ""))

    embed = discord.Embed()
    embed.title = f"🏁 Full Time: {home_team_name} vs {away_team_name}"
    
    if home_team_id == focus_team_id:
        embed.description = f"**{home_team_name}** {home_score} - {away_score} {away_team_name}"
        embed.set_thumbnail(url=home_team.get('logo'))
        
        if int(home_score) > int(away_score):
            embed.color = discord.Color.green()
            embed.add_field(name="Result", value="Victory! Great performance! 🎉", inline=False)
        elif int(home_score) < int(away_score):
            embed.color = discord.Color.red()
            embed.add_field(name="Result", value="Defeat. We'll bounce back stronger! 💪", inline=False)
        else:
            embed.color = discord.Color.gold()
            embed.add_field(name="Result", value="Draw. Hard-fought point! 🤝", inline=False)
            
    elif away_team_id == focus_team_id:
        embed.description = f"{home_team_name} {home_score} - {away_score} **{away_team_name}**"
        embed.set_thumbnail(url=away_team.get('logo'))
        
        if int(away_score) > int(home_score):
            embed.color = discord.Color.green()
            embed.add_field(name="Result", value="Away victory! Brilliant performance! 🎉", inline=False)
        elif int(away_score) < int(home_score):
            embed.color = discord.Color.red()
            embed.add_field(name="Result", value="Away defeat. We'll come back stronger! 💪", inline=False)
        else:
            embed.color = discord.Color.gold()
            embed.add_field(name="Result", value="Away draw. Good point on the road! 🤝", inline=False)
    else:
        embed.description = f"{home_team_name} {home_score} - {away_score} {away_team_name}"
        embed.color = discord.Color.blue()
        embed.add_field(name="Result", value="Match concluded", inline=False)

    embed.add_field(name="Time", value="90'+", inline=True)
    
    return embed


def create_pre_match_embed(update_data, focus_team_id):
    """Create an embed for pre-match information."""
    home_team = update_data.get('home_team', {})
    away_team = update_data.get('away_team', {})
    match_time = update_data.get('match_time', "TBD")
    
    home_team_name = home_team.get('displayName', "Home Team")
    away_team_name = away_team.get('displayName', "Away Team")
    home_team_id = str(home_team.get('id', ""))
    away_team_id = str(away_team.get('id', ""))

    embed = discord.Embed()
    embed.title = f"🏟️ Upcoming Match: {home_team_name} vs {away_team_name}"
    embed.color = discord.Color.blue()
    
    if home_team_id == focus_team_id:
        embed.description = f"**{home_team_name}** vs {away_team_name}"
        embed.set_thumbnail(url=home_team.get('logo'))
        embed.add_field(name="Home Advantage", value="Playing at home! Let's show our support! 🏠", inline=False)
    elif away_team_id == focus_team_id:
        embed.description = f"{home_team_name} vs **{away_team_name}**"
        embed.set_thumbnail(url=away_team.get('logo'))
        embed.add_field(name="Away Challenge", value="On the road! Let's travel well! 🚌", inline=False)
    else:
        embed.description = f"{home_team_name} vs {away_team_name}"

    embed.add_field(name="Kickoff", value=match_time, inline=True)
    embed.add_field(name="Status", value="Match scheduled", inline=True)
    
    return embed