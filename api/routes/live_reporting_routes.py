# api/routes/live_reporting_routes.py

"""
Live Reporting API Routes

FastAPI routes for handling real-time match updates from the Flask WebUI.
Provides endpoints for creating threads, sending events, and testing.
"""

import logging
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from datetime import datetime
import discord
from discord.ext import commands

from shared_states import get_bot_instance

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/live-reporting", tags=["live-reporting"])


# Pydantic models for request/response
class ThreadCreateRequest(BaseModel):
    channel_id: int
    match_title: str
    home_team: str
    away_team: str
    match_date: str
    competition: str
    match_id: Optional[str] = None


class LiveEventRequest(BaseModel):
    thread_id: int
    event_type: str
    content: str
    embed: Optional[Dict[str, Any]] = None
    match_data: Optional[Dict[str, Any]] = None


class StatusUpdateRequest(BaseModel):
    thread_id: int
    content: str
    event_type: str = "status_change"


class FinalUpdateRequest(BaseModel):
    thread_id: int
    content: str
    close_thread: bool = False


def get_bot():
    """Dependency to get bot instance."""
    bot = get_bot_instance()
    if not bot or not bot.is_ready():
        raise HTTPException(status_code=503, detail="Discord bot is not ready")
    return bot


def get_event_embed_config(event_type: str, content: str, match_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Generate embed configuration for different live event types."""

    # Default configuration
    config = {
        'use_embed': True,
        'title': '⚽ Live Match Event',
        'description': content,
        'color': 0x005F4F,  # Sounders green
        'fields': []
    }

    # Parse content to extract event details
    if '⚽ GOAL!' in content:
        config.update({
            'title': '⚽ GOAL!',
            'color': 0x00FF00,  # Bright green for goals
            'fields': [
                {'name': '🎯 Event', 'value': 'Goal Scored', 'inline': True},
                {'name': '⏱️ Time', 'value': 'Live', 'inline': True}
            ]
        })

        # Extract team context for goal color (Sounders is always our team regardless of home/away)
        if 'Sounders' in content or 'Seattle' in content or 'SOUNDERS' in content:
            config['color'] = 0x005F4F  # Sounders green for OUR goals - always celebrate!
            config['title'] = '⚽ SOUNDERS GOAL!'
        else:
            config['color'] = 0xFF4444  # Red for opponent goals - tone it down
            config['title'] = '⚽ Opponent Goal'

    elif '📋 Yellow-Card' in content or '🟨' in content:
        config.update({
            'title': '🟨 Yellow Card',
            'color': 0xFFD700,  # Gold for yellow cards
            'fields': [
                {'name': '⚠️ Caution', 'value': 'Player Booked', 'inline': True},
                {'name': '📋 Discipline', 'value': 'Yellow Card', 'inline': True}
            ]
        })

    elif '🟥' in content or 'Red Card' in content:
        config.update({
            'title': '🟥 Red Card',
            'color': 0xFF0000,  # Red for red cards
            'fields': [
                {'name': '🚫 Dismissal', 'value': 'Player Sent Off', 'inline': True},
                {'name': '📋 Discipline', 'value': 'Red Card', 'inline': True}
            ]
        })

    elif '📋 Substitution' in content or '🔄' in content:
        config.update({
            'title': '🔄 Substitution',
            'color': 0x0099FF,  # Blue for substitutions
            'fields': [
                {'name': '⚡ Change', 'value': 'Player Substitution', 'inline': True},
                {'name': '🔄 Tactical', 'value': 'Fresh Legs', 'inline': True}
            ]
        })

    elif 'LET\'S GO' in content or '🔥' in content and 'Time to' in content:
        config.update({
            'title': '🔥 PRE-MATCH HYPE',
            'color': 0x005F4F,  # Sounders green
            'fields': [
                {'name': '🏟️ Venue', 'value': 'Lumen Field', 'inline': True},
                {'name': '💚💙 Support', 'value': 'ECS Ready!', 'inline': True}
            ]
        })

    elif '🧪' in content and 'test' in content.lower():
        config.update({
            'title': '🧪 System Test',
            'color': 0x9932CC,  # Purple for test messages
            'fields': [
                {'name': '🔧 Status', 'value': 'Testing Live Reporting', 'inline': True},
                {'name': '✅ Connection', 'value': 'Operational', 'inline': True}
            ]
        })

    # Add match data if available
    if match_data and isinstance(match_data, dict):
        try:
            # Extract score from match data
            competition = match_data.get('header', {}).get('competitions', [{}])[0]
            status_info = competition.get('status', {})
            clock = status_info.get('displayClock', 'Live')

            if clock and clock != '0:00':
                config['fields'].append({
                    'name': '⏱️ Match Time',
                    'value': f"{clock}",
                    'inline': True
                })
        except:
            pass  # Skip if match_data parsing fails

    return config


@router.post("/thread/create")
async def create_match_thread(request: ThreadCreateRequest, bot: commands.Bot = Depends(get_bot)):
    """
    Create a Discord thread for live match reporting.

    Called by Flask WebUI 48 hours before match start.
    """
    try:
        logger.info(f"Creating match thread for {request.home_team} vs {request.away_team}")

        # Get the channel
        channel = bot.get_channel(request.channel_id)
        if not channel:
            raise HTTPException(status_code=404, detail=f"Channel {request.channel_id} not found")

        # Format thread name and content
        thread_name = f"🔴 LIVE: {request.home_team} vs {request.away_team}"

        # Create initial thread content
        embed = discord.Embed(
            title=f"⚽ {request.home_team} vs {request.away_team}",
            description=f"**Competition:** {request.competition}\n**Date:** {request.match_date}",
            color=0x00ff00,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="📺", value="Live updates will start 5 minutes before kickoff!", inline=False)
        embed.set_footer(text="ECS Live Reporting System")

        # Create thread based on channel type
        if isinstance(channel, discord.ForumChannel):
            # Forum channel - create thread with initial post
            thread = await channel.create_thread(
                name=thread_name,
                content="🔴 **Live Match Thread**",
                embed=embed
            )
            if hasattr(thread, 'thread'):
                thread = thread.thread
        else:
            # Text channel - create thread
            thread = await channel.create_thread(
                name=thread_name,
                type=discord.ChannelType.public_thread
            )
            # Send initial message
            await thread.send(embed=embed)

        logger.info(f"Created match thread {thread.id} for {request.home_team} vs {request.away_team}")

        return {
            "success": True,
            "thread_id": thread.id,
            "thread_name": thread.name,
            "channel_id": request.channel_id,
            "message": "Match thread created successfully"
        }

    except discord.HTTPException as e:
        logger.error(f"Discord API error creating thread: {e}")
        raise HTTPException(status_code=500, detail=f"Discord API error: {e}")
    except Exception as e:
        logger.error(f"Error creating match thread: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create thread: {e}")


@router.post("/event")
async def send_live_event(request: LiveEventRequest, bot: commands.Bot = Depends(get_bot)):
    """
    Send a live match event to Discord thread.

    Called by real-time service for goals, cards, etc.
    Enhanced with professional embed formatting and ESPN integration.
    """
    try:
        # Get the thread
        thread = bot.get_channel(request.thread_id)
        if not thread:
            raise HTTPException(status_code=404, detail=f"Thread {request.thread_id} not found")

        # Use enhanced embed if provided by WebUI, otherwise fallback to old system
        if request.embed:
            # Use the enhanced embed format from WebUI with ESPN data
            embed_data = request.embed

            embed = discord.Embed(
                title=embed_data.get('title', '⚽ Live Match Event'),
                description=embed_data.get('description', request.content),
                color=embed_data.get('color', 0x005F4F),
                timestamp=datetime.fromisoformat(embed_data.get('timestamp', datetime.utcnow().isoformat()))
            )

            # Add enhanced fields with match context
            for field in embed_data.get('fields', []):
                embed.add_field(
                    name=field['name'],
                    value=field['value'],
                    inline=field.get('inline', False)
                )

            # Add author if provided (team vs team)
            if 'author' in embed_data:
                embed.set_author(
                    name=embed_data['author']['name'],
                    icon_url=embed_data['author'].get('icon_url')
                )

            # Add thumbnail if provided (player image)
            if 'thumbnail' in embed_data:
                embed.set_thumbnail(url=embed_data['thumbnail']['url'])

            # Add footer with ECS branding
            footer_data = embed_data.get('footer', {})
            embed.set_footer(
                text=footer_data.get('text', 'ECS Live Reporting'),
                icon_url=footer_data.get('icon_url', 'https://www.soundersfc.com/sites/seattle/files/imagecache/620x350/image_nodes/2013/03/Sounders_shield_full_color.png')
            )

            message = await thread.send(embed=embed)

        else:
            # Fallback to legacy embed system
            embed_config = get_event_embed_config(request.event_type, request.content, request.match_data)

            if embed_config['use_embed']:
                embed = discord.Embed(
                    title=embed_config['title'],
                    description=request.content,
                    color=embed_config['color'],
                    timestamp=datetime.utcnow()
                )

                # Add legacy fields
                for field in embed_config.get('fields', []):
                    embed.add_field(
                        name=field['name'],
                        value=field['value'],
                        inline=field.get('inline', False)
                    )

                embed.set_footer(text="ECS Live Reporting")
                message = await thread.send(embed=embed)
            else:
                message = await thread.send(request.content)

        logger.info(f"Sent {request.event_type} event to thread {request.thread_id}")

        return {
            "success": True,
            "message_id": message.id,
            "thread_id": request.thread_id,
            "event_type": request.event_type
        }

    except discord.HTTPException as e:
        logger.error(f"Discord API error sending event: {e}")
        raise HTTPException(status_code=500, detail=f"Discord API error: {e}")
    except Exception as e:
        logger.error(f"Error sending live event: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to send event: {e}")


@router.post("/status")
async def send_status_update(request: StatusUpdateRequest, bot: commands.Bot = Depends(get_bot)):
    """
    Send match status update (kickoff, halftime, fulltime).
    """
    try:
        thread = bot.get_channel(request.thread_id)
        if not thread:
            raise HTTPException(status_code=404, detail=f"Thread {request.thread_id} not found")

        # Create status embed
        color_map = {
            "kickoff": 0x00ff00,  # Green
            "halftime": 0xffa500,  # Orange
            "fulltime": 0xff0000,  # Red
            "status_change": 0x0099ff  # Blue
        }

        embed = discord.Embed(
            description=request.content,
            color=color_map.get(request.event_type, 0x0099ff),
            timestamp=datetime.utcnow()
        )

        message = await thread.send(embed=embed)

        logger.info(f"Sent status update to thread {request.thread_id}: {request.event_type}")

        return {
            "success": True,
            "message_id": message.id,
            "thread_id": request.thread_id
        }

    except Exception as e:
        logger.error(f"Error sending status update: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to send status: {e}")


@router.post("/final")
async def send_final_update(request: FinalUpdateRequest, bot: commands.Bot = Depends(get_bot)):
    """
    Send final match summary and optionally close thread.
    """
    try:
        thread = bot.get_channel(request.thread_id)
        if not thread:
            raise HTTPException(status_code=404, detail=f"Thread {request.thread_id} not found")

        # Send final message
        embed = discord.Embed(
            title="🏁 Match Completed",
            description=request.content,
            color=0xff0000,
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text="Thanks for following the live updates!")

        message = await thread.send(embed=embed)

        # Optionally close/archive thread
        if request.close_thread and hasattr(thread, 'edit'):
            try:
                await thread.edit(archived=True)
                logger.info(f"Archived thread {request.thread_id}")
            except:
                logger.warning(f"Could not archive thread {request.thread_id}")

        logger.info(f"Sent final update to thread {request.thread_id}")

        return {
            "success": True,
            "message_id": message.id,
            "thread_id": request.thread_id,
            "archived": request.close_thread
        }

    except Exception as e:
        logger.error(f"Error sending final update: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to send final update: {e}")


@router.get("/thread/{thread_id}/status")
async def get_thread_status(thread_id: int, bot: commands.Bot = Depends(get_bot)):
    """
    Get thread status and basic info.
    """
    try:
        thread = bot.get_channel(thread_id)
        if not thread:
            raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

        return {
            "thread_id": thread.id,
            "name": thread.name,
            "archived": getattr(thread, 'archived', False),
            "locked": getattr(thread, 'locked', False),
            "message_count": getattr(thread, 'message_count', 0),
            "member_count": getattr(thread, 'member_count', 0)
        }

    except Exception as e:
        logger.error(f"Error getting thread status: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get thread status: {e}")


# Health check for live reporting system
@router.get("/health")
async def live_reporting_health():
    """Health check for live reporting system."""
    try:
        bot = get_bot_instance()
        bot_ready = bot and bot.is_ready()

        return {
            "status": "healthy" if bot_ready else "degraded",
            "bot_ready": bot_ready,
            "timestamp": datetime.utcnow().isoformat(),
            "system": "live_reporting_api"
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }