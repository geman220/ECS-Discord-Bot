"""
Discord Bot Onboarding Routes

API endpoints for handling user onboarding interactions, league selection processing,
and new player notifications.
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import aiohttp
import discord
from discord.ext import commands
from fastapi import APIRouter, HTTPException, Depends, Body, BackgroundTasks

from api.utils.discord_utils import get_bot
from api.utils.api_client import get_session

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/onboarding", tags=["onboarding"])

# Configuration
WEBUI_API_URL = "http://webui:5000/api"
NEW_PLAYERS_CHANNEL_NAME = "pl-new-players"  # Channel name to find dynamically
LEAGUE_RESPONSE_TIMEOUT = 300  # 5 minutes to respond to league selection

# =======================================================================
# League Selection Processing
# =======================================================================

LEAGUE_PATTERNS = {
    'pub_league_classic': [
        r'\b(classic|plc|pub\s*league\s*classic|standard|regular|basic|original)\b',
        r'\b(classic\s*pub|pub\s*classic)\b',
        r'\bclassic\b'
    ],
    'pub_league_premier': [
        r'\b(premier|plp|pub\s*league\s*premier|premium|advanced|competitive)\b',
        r'\b(premier\s*pub|pub\s*premier)\b', 
        r'\bpremier\b'
    ],
    'ecs_fc': [
        r'\b(ecs\s*fc|ecs|fc|emerald\s*city|supporters\s*fc|emerald|city)\b',
        r'\b(emerald\s*city\s*supporters)\b',
        r'\becs\b'
    ]
}

def parse_league_selection(message_content: str) -> Optional[str]:
    """
    Parse user message to determine league selection using fuzzy matching.
    
    Args:
        message_content: User's message content
        
    Returns:
        League name if matched, None otherwise
    """
    content_lower = message_content.lower().strip()
    
    # Direct matches first
    for league, patterns in LEAGUE_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, content_lower, re.IGNORECASE):
                logger.info(f"Matched league '{league}' with pattern '{pattern}' in message: '{content_lower}'")
                return league
    
    # Fallback for common variations
    if any(word in content_lower for word in ['classic', 'standard', 'regular', 'basic']):
        return 'pub_league_classic'
    elif any(word in content_lower for word in ['premier', 'premium', 'advanced', 'competitive']):
        return 'pub_league_premier'
    elif any(word in content_lower for word in ['ecs', 'fc', 'emerald', 'city', 'supporters']):
        return 'ecs_fc'
    
    return None


async def get_message_template(category: str, key: str) -> Optional[Dict]:
    """
    Fetch a message template from the Flask API.
    
    Args:
        category: Message category name
        key: Template key
        
    Returns:
        Template data or None if not found
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{WEBUI_API_URL}/discord/message-template/{category}/{key}") as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    logger.warning(f"Failed to fetch message template {category}/{key}: {resp.status}")
                    return None
    except Exception as e:
        logger.error(f"Error fetching message template: {e}")
        return None


async def get_contextual_welcome_message(user_data: Dict) -> str:
    """
    Generate contextual welcome message based on user's onboarding status.
    
    Args:
        user_data: User information from Flask API
        
    Returns:
        Appropriate welcome message
    """
    username = user_data.get('username', 'there')
    has_onboarding = user_data.get('has_completed_onboarding', False)
    preferred_league = user_data.get('preferred_league')
    recommended_action = user_data.get('recommended_action', 'ask_league_and_onboarding')
    
    # Try to get template from database
    template = await get_message_template('welcome_messages', recommended_action)
    
    if template and template.get('message_content'):
        # Get league info for variables
        league_info = get_league_welcome_info(preferred_league) if preferred_league else {}
        
        # Format the message with variables
        try:
            return template['message_content'].format(
                username=username,
                league_display_name=league_info.get('display_name', ''),
                league_welcome_message=league_info.get('welcome_message', ''),
                league_contact_info=league_info.get('contact_info', '')
            )
        except KeyError as e:
            logger.warning(f"Missing variable in template {recommended_action}: {e}")
    
    # Fallback to hardcoded messages if template not found
    base_greeting = f"Welcome to the ECS Discord server, {username}! 👋"
    
    if recommended_action == 'send_welcome':
        # User has completed everything
        league_info = get_league_welcome_info(preferred_league)
        return f"{base_greeting}\n\nI see you've completed your registration for **{league_info['display_name']}**! {league_info['welcome_message']}"
    
    elif recommended_action == 'ask_league_only':
        # Has onboarding but no league
        return f"""{base_greeting}

I noticed you completed your registration but didn't specify which league you're interested in joining. Could you let me know which one you'd like to participate in?

🏆 **Pub League Classic** - Our standard recreational league
🌟 **Pub League Premier** - More competitive play  
⚽ **ECS FC** - Our club team

Just reply with your preference (e.g., "Premier" or "ECS FC")!"""
    
    elif recommended_action == 'encourage_onboarding':
        # Has league but no onboarding
        league_info = get_league_welcome_info(preferred_league)
        return f"""{base_greeting}

I see you selected **{league_info['display_name']}** - great choice! {league_info['welcome_message']}

I noticed you haven't completed the onboarding questions yet. When you have a chance, it would be really helpful to finish those so we know how to best support you: https://portal.ecsfc.com/onboarding

{league_info['contact_info']}"""
    
    else:
        # ask_league_and_onboarding - needs both
        return f"""{base_greeting}

I noticed you started your registration but haven't completed the onboarding questions yet. If you have time, it would be really helpful to finish those so we know how to best help you: https://portal.ecsfc.com/onboarding

Until then, could you let me know which league you were looking to participate in?

🏆 **Pub League Classic** - Our standard recreational league
🌟 **Pub League Premier** - More competitive play  
⚽ **ECS FC** - Our club team

Just reply with your preference!"""


def get_league_welcome_info(league: str) -> Dict[str, str]:
    """Get league-specific welcome information."""
    league_info = {
        'pub_league_classic': {
            'display_name': 'Pub League Classic',
            'welcome_message': "You'll love our classic recreational league - it's all about having fun and improving your game! ⚽",
            'contact_info': "For Pub League Classic questions, reach out to our Pub League coordinators in the #pub-league channels."
        },
        'pub_league_premier': {
            'display_name': 'Pub League Premier', 
            'welcome_message': "Welcome to Premier! Get ready for more competitive matches and skilled gameplay. 🌟",
            'contact_info': "For Pub League Premier questions, check out #pub-league-premier or contact our Premier coordinators."
        },
        'ecs_fc': {
            'display_name': 'ECS FC',
            'welcome_message': "Welcome to ECS FC! You're joining our club team - exciting times ahead! ⚽🔥",
            'contact_info': "For ECS FC questions, check out the #ecs-fc channels or reach out to our ECS FC coordinators."
        }
    }
    return league_info.get(league, {
        'display_name': 'Unknown League',
        'welcome_message': 'Welcome to our community!',
        'contact_info': 'Reach out to our coordinators for more information.'
    })


async def get_league_selection_confirmation(league: str) -> str:
    """Get confirmation message for league selection."""
    # Try to get template from database
    template = await get_message_template('league_responses', 'league_selection_confirmation')
    
    if template and template.get('message_content'):
        league_info = get_league_welcome_info(league)
        try:
            return template['message_content'].format(
                league_display_name=league_info.get('display_name', ''),
                league_welcome_message=league_info.get('welcome_message', ''),
                league_contact_info=league_info.get('contact_info', '')
            )
        except KeyError as e:
            logger.warning(f"Missing variable in league confirmation template: {e}")
    
    # Fallback to hardcoded message
    league_info = get_league_welcome_info(league)
    return f"""Perfect! I've updated your profile to show you're interested in **{league_info['display_name']}**. 

{league_info['welcome_message']}

{league_info['contact_info']}

Your information has been passed along to our leadership team, and they'll be able to help get you connected with the right people. Welcome to the community! 🎉"""


# =======================================================================
# API Endpoints
# =======================================================================

@router.post("/process-user-message")
async def process_user_message(
    discord_id: str = Body(..., embed=True),
    message_content: str = Body(..., embed=True),
    bot: commands.Bot = Depends(get_bot)
):
    """
    Process a user's message to check for league selection.
    Called when users respond to onboarding DMs.
    """
    try:
        # Parse the message for league selection
        league_selection = parse_league_selection(message_content)
        
        if not league_selection:
            # No league detected, send helpful response - try to get from template
            template = await get_message_template('league_responses', 'league_clarification')
            if template and template.get('message_content'):
                response_message = template['message_content']
            else:
                # Fallback message
                response_message = """I didn't quite catch which league you're interested in. Could you clarify? Here are the options:

🏆 **Classic** - Pub League Classic (recreational)
🌟 **Premier** - Pub League Premier (competitive)  
⚽ **ECS FC** - Our club team

Just reply with one of those options!"""
            
            user = await bot.fetch_user(int(discord_id))
            dm_channel = await user.create_dm()
            await dm_channel.send(response_message)
            
            return {"processed": False, "response_sent": True, "message": "Clarification requested"}
        
        # Valid league selection detected
        async with aiohttp.ClientSession() as session:
            # Send league selection to Flask API
            async with session.post(
                f"{WEBUI_API_URL}/discord/league-selection",
                json={
                    "discord_id": discord_id,
                    "league_selection": league_selection,
                    "raw_message": message_content
                }
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    # Send confirmation to user
                    confirmation = await get_league_selection_confirmation(league_selection)
                    user = await bot.fetch_user(int(discord_id))
                    dm_channel = await user.create_dm()
                    message = await dm_channel.send(confirmation)
                    
                    # Update interaction status
                    await session.post(
                        f"{WEBUI_API_URL}/discord/update-interaction-status",
                        json={
                            "discord_id": discord_id,
                            "status": "completed",
                            "bot_message_id": str(message.id)
                        }
                    )
                    
                    # Trigger new player notification if needed
                    if data.get('should_trigger_notification'):
                        await trigger_new_player_notification(discord_id, bot)
                    
                    logger.info(f"Successfully processed league selection for {discord_id}: {league_selection}")
                    return {
                        "processed": True,
                        "league_selected": league_selection,
                        "response_sent": True
                    }
                else:
                    logger.error(f"Flask API error: {resp.status}")
                    return {"processed": False, "error": "API error"}
                    
    except Exception as e:
        logger.error(f"Error processing user message for {discord_id}: {e}")
        return {"processed": False, "error": str(e)}


@router.post("/send-contextual-welcome")
async def send_contextual_welcome(
    background_tasks: BackgroundTasks,
    discord_id: str = Body(..., embed=True),
    bot: commands.Bot = Depends(get_bot)
):
    """
    Send contextual welcome message based on user's onboarding status.
    """
    try:
        # Get user onboarding status from Flask API
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{WEBUI_API_URL}/discord/onboarding-status/{discord_id}") as resp:
                if resp.status != 200:
                    raise HTTPException(status_code=404, detail="User not found")
                
                user_data = await resp.json()
                
                if not user_data.get('exists'):
                    raise HTTPException(status_code=404, detail="User not found")
        
        # Generate contextual message
        welcome_message = await get_contextual_welcome_message(user_data)
        
        # Send DM to user
        try:
            user = await bot.fetch_user(int(discord_id))
            dm_channel = await user.create_dm()
            message = await dm_channel.send(welcome_message)
            
            # Update interaction status in background
            background_tasks.add_task(
                update_interaction_status,
                discord_id, "contacted", str(message.id)
            )
            
            logger.info(f"Sent contextual welcome to {discord_id}")
            return {
                "success": True,
                "message_sent": True,
                "message_id": str(message.id),
                "action": user_data.get('recommended_action')
            }
            
        except discord.Forbidden:
            # User has DMs disabled
            background_tasks.add_task(
                update_interaction_status,
                discord_id, "failed", None, "User has DMs disabled"
            )
            
            return {
                "success": False,
                "message_sent": False,
                "error": "User has DMs disabled"
            }
            
    except Exception as e:
        logger.error(f"Error sending contextual welcome to {discord_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/notify-new-player")
async def notify_new_player(
    discord_id: str = Body(..., embed=True),
    discord_username: str = Body(None, embed=True),
    discord_display_name: str = Body(None, embed=True),
    bot: commands.Bot = Depends(get_bot)
):
    """
    Post notification to #pl-new-players channel.
    """
    try:
        return await trigger_new_player_notification(discord_id, bot, discord_username, discord_display_name)
        
    except Exception as e:
        logger.error(f"Error posting new player notification: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def trigger_new_player_notification(
    discord_id: str, 
    bot: commands.Bot,
    discord_username: str = None,
    discord_display_name: str = None
) -> Dict:
    """
    Internal function to trigger new player notification.
    """
    try:
        # Get user info if not provided
        if not discord_username or not discord_display_name:
            try:
                user = await bot.fetch_user(int(discord_id))
                discord_username = user.name
                discord_display_name = user.display_name
            except:
                discord_username = "Unknown User"
                discord_display_name = "Unknown User"
        
        # Get user data from Flask API
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{WEBUI_API_URL}/discord/onboarding-status/{discord_id}") as resp:
                if resp.status != 200:
                    return {"success": False, "error": "User not found in database"}
                
                user_data = await resp.json()
                
                if not user_data.get('exists'):
                    return {"success": False, "error": "User not found"}
        
        # Create notification embed
        embed = discord.Embed(
            title="🎉 New Player Alert!",
            color=discord.Color.green()
        )
        
        # Add clickable Discord user mention for easy admin access
        discord_mention = f"<@{discord_id}>"
        embed.add_field(name="Discord User", value=f"{discord_mention} ({discord_display_name})", inline=True)
        embed.add_field(name="Registration Name", value=user_data.get('username', 'Unknown'), inline=True)
        embed.add_field(name="Email", value=user_data.get('email', 'Unknown'), inline=True)
        
        preferred_league = user_data.get('preferred_league')
        if preferred_league:
            league_info = get_league_welcome_info(preferred_league)
            embed.add_field(name="Interested League", value=league_info['display_name'], inline=True)
        else:
            embed.add_field(name="League Status", value="Not yet selected", inline=True)
        
        onboarding_status = "✅ Complete" if user_data.get('has_completed_onboarding') else "⏳ Incomplete"
        embed.add_field(name="Onboarding", value=onboarding_status, inline=True)
        
        # Add profile link
        player_id = user_data.get('player_id')
        if player_id:
            profile_url = f"https://portal.ecsfc.com/players/profile/{player_id}"
            embed.add_field(name="Profile", value=f"[View Profile]({profile_url})", inline=True)
        else:
            embed.add_field(name="Profile", value="Profile not available", inline=True)
        
        embed.set_footer(text="A new member has linked their Discord account!")
        embed.timestamp = datetime.utcnow()
        
        # Find #pl-new-players channel by name
        channel = None
        for guild in bot.guilds:
            for guild_channel in guild.channels:
                if guild_channel.name == NEW_PLAYERS_CHANNEL_NAME:
                    channel = guild_channel
                    break
            if channel:
                break
        
        if not channel:
            logger.error(f"Could not find channel with name '{NEW_PLAYERS_CHANNEL_NAME}'")
            return {"success": False, "error": f"Channel '{NEW_PLAYERS_CHANNEL_NAME}' not found"}
        
        # Handle different channel types
        if hasattr(channel, 'send'):
            # Regular text channel
            message = await channel.send(embed=embed)
        elif hasattr(channel, 'create_thread'):
            # Forum channel - create a new thread for the new player
            thread_name = f"New Player: {discord_display_name}"
            thread = await channel.create_thread(
                name=thread_name,
                embed=embed,
                reason="New player notification"
            )
            message = thread.message  # The initial message of the thread
        else:
            logger.error(f"Channel {NEW_PLAYERS_CHANNEL_ID} is not a supported channel type: {type(channel)}")
            return {"success": False, "error": f"Unsupported channel type: {type(channel).__name__}"}
        
        # Record notification in Flask API
        async with aiohttp.ClientSession() as session:
            await session.post(
                f"{WEBUI_API_URL}/discord/new-player-notification",
                json={
                    "discord_id": discord_id,
                    "discord_username": discord_username,
                    "discord_display_name": discord_display_name,
                    "notification_sent": True,
                    "discord_message_id": str(message.id)
                }
            )
        
        logger.info(f"Posted new player notification for {discord_username} ({discord_id})")
        return {
            "success": True,
            "message_id": str(message.id),
            "channel_id": str(channel.id),
            "channel_name": channel.name
        }
        
    except Exception as e:
        # Record failed notification
        async with aiohttp.ClientSession() as session:
            try:
                await session.post(
                    f"{WEBUI_API_URL}/discord/new-player-notification",
                    json={
                        "discord_id": discord_id,
                        "discord_username": discord_username,
                        "discord_display_name": discord_display_name,
                        "notification_sent": False,
                        "error_message": str(e)
                    }
                )
            except:
                pass  # Don't fail the main operation if logging fails
        
        logger.error(f"Failed to send new player notification: {e}")
        return {"success": False, "error": str(e)}


async def update_interaction_status(discord_id: str, status: str, bot_message_id: str = None, error_message: str = None):
    """Background task to update interaction status."""
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(
                f"{WEBUI_API_URL}/discord/update-interaction-status",
                json={
                    "discord_id": discord_id,
                    "status": status,
                    "bot_message_id": bot_message_id,
                    "error_message": error_message
                }
            )
    except Exception as e:
        logger.error(f"Failed to update interaction status: {e}")


# =======================================================================
# Batch Processing Endpoints
# =======================================================================

@router.post("/process-pending-contacts")
async def process_pending_contacts(bot: commands.Bot = Depends(get_bot)):
    """
    Process all users who need to be contacted by the bot.
    This can be called periodically or manually by admins.
    """
    try:
        # Get pending contacts from Flask API
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{WEBUI_API_URL}/discord/pending-contacts") as resp:
                if resp.status != 200:
                    raise HTTPException(status_code=500, detail="Failed to get pending contacts")
                
                data = await resp.json()
                users_to_contact = data.get('users_to_contact', [])
        
        results = {
            "processed": 0,
            "successful": 0,
            "failed": 0,
            "errors": []
        }
        
        # Process each user
        for user_info in users_to_contact:
            discord_id = user_info['discord_id']
            try:
                # Send contextual welcome
                result = await send_contextual_welcome(discord_id, bot)
                if result.get('success'):
                    results["successful"] += 1
                else:
                    results["failed"] += 1
                    results["errors"].append(f"{discord_id}: {result.get('error', 'Unknown error')}")
                
                results["processed"] += 1
                
                # Add small delay to avoid rate limits
                await asyncio.sleep(1)
                
            except Exception as e:
                results["failed"] += 1
                results["errors"].append(f"{discord_id}: {str(e)}")
                logger.error(f"Error processing contact for {discord_id}: {e}")
        
        logger.info(f"Processed {results['processed']} pending contacts: {results['successful']} successful, {results['failed']} failed")
        return results
        
    except Exception as e:
        logger.error(f"Error processing pending contacts: {e}")
        raise HTTPException(status_code=500, detail=str(e))