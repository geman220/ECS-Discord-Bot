# app/tasks/tasks_ecs_fc_rsvp_helpers.py

"""
ECS FC RSVP Helpers Module

This module provides helper functions for ECS FC-specific Discord notifications,
including DM reminders and embed formatting. 

Note: Async functions have been removed as part of V2 synchronous migration.
Only synchronous functions that are still in use are retained.
"""

import logging
import requests
from datetime import datetime
from typing import Dict, Any
from flask import current_app

logger = logging.getLogger(__name__)


def send_ecs_fc_dm_sync(discord_id: str, message: str) -> Dict[str, Any]:
    """
    Send a synchronous DM to a player for ECS FC RSVP reminders.
    Uses the existing DM system that coaches/admins use.
    
    Args:
        discord_id: Discord ID of the player
        message: Message content to send
    
    Returns:
        Dictionary with success status and details
    """
    payload = {
        "message": message,
        "discord_id": discord_id
    }
    
    bot_api_url = current_app.config.get('BOT_API_URL', 'http://discord-bot:5001') + '/send_discord_dm'
    
    try:
        response = requests.post(bot_api_url, json=payload, timeout=10)
        if response.status_code == 200:
            logger.info(f"ECS FC RSVP DM sent to {discord_id}")
            return {'success': True, 'message': 'ECS FC RSVP DM sent successfully'}
        else:
            logger.error(f"Failed to send ECS FC RSVP DM to {discord_id}: {response.text}")
            return {'success': False, 'message': 'Failed to send ECS FC RSVP DM', 'error': response.text}
    except Exception as e:
        logger.error(f"Error sending ECS FC RSVP DM: {str(e)}")
        return {'success': False, 'message': f'Error sending DM: {str(e)}'}


def format_ecs_fc_match_embed_data(match, response_counts: Dict[str, int] = None) -> Dict[str, Any]:
    """
    Format ECS FC match data for Discord embed.
    
    Args:
        match: EcsFcMatch object
        response_counts: Optional dictionary with RSVP counts
    
    Returns:
        Dictionary formatted for Discord embed
    """
    # Format date and time
    match_datetime = datetime.combine(match.match_date, match.match_time)
    formatted_date = match_datetime.strftime("%A, %B %d, %Y")
    formatted_time = match_datetime.strftime("%I:%M %p").lstrip('0')
    
    # Build embed data
    embed_data = {
        "title": f"⚽ {match.team.name} vs {match.opponent_name}",
        "description": f"React with ✅ for Yes, ❌ for No, or ❓ for Maybe",
        "color": 0x00ff00 if match.is_home_match else 0x0099ff,
        "fields": [
            {
                "name": "📅 Date & Time",
                "value": f"{formatted_date}\n🕐 {formatted_time}",
                "inline": True
            },
            {
                "name": "📍 Location",
                "value": f"{match.location}\n{'🏠 Home Match' if match.is_home_match else '✈️ Away Match'}",
                "inline": True
            }
        ]
    }
    
    # Add field name if specified
    if match.field_name:
        embed_data["fields"].append({
            "name": "🥅 Field",
            "value": match.field_name,
            "inline": True
        })
    
    # Add RSVP deadline if specified
    if match.rsvp_deadline:
        deadline_str = match.rsvp_deadline.strftime("%B %d at %I:%M %p").replace(' 0', ' ')
        embed_data["fields"].append({
            "name": "⏰ RSVP Deadline",
            "value": deadline_str,
            "inline": False
        })
    
    # Add response counts if provided
    if response_counts:
        yes_count = response_counts.get('yes', 0)
        no_count = response_counts.get('no', 0)
        maybe_count = response_counts.get('maybe', 0)
        total_responses = yes_count + no_count + maybe_count
        
        embed_data["fields"].append({
            "name": "📊 Current Responses",
            "value": f"✅ Yes: {yes_count}\n❌ No: {no_count}\n❓ Maybe: {maybe_count}\n\n**Total: {total_responses}**",
            "inline": False
        })
    
    # Add notes if specified
    if match.notes:
        embed_data["fields"].append({
            "name": "📝 Notes",
            "value": match.notes,
            "inline": False
        })
    
    embed_data["footer"] = {
        "text": f"Match ID: {match.id} | React to RSVP!"
    }
    
    return embed_data