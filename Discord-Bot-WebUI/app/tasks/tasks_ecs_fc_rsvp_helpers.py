# app/tasks/tasks_ecs_fc_rsvp_helpers.py

"""
ECS FC RSVP Helpers Module

This module provides helper functions for ECS FC-specific Discord notifications,
including RSVP messages, DM reminders, and team channel updates.
Based on the existing pub league RSVP helpers but adapted for ECS FC structure.
"""

import logging
import aiohttp
import asyncio
import requests
from datetime import datetime
from typing import Optional, Dict, Any, Tuple, List
from flask import current_app

logger = logging.getLogger(__name__)


async def send_ecs_fc_rsvp_message_async(match_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Send an ECS FC RSVP message to the team's Discord channel.
    
    Args:
        match_data: Dictionary containing ECS FC match details:
        {
            'match_id': int,
            'team_id': int,
            'team_name': str,
            'opponent_name': str,
            'match_date': str,
            'match_time': str,
            'location': str,
            'field_name': str (optional),
            'rsvp_deadline': str (optional),
            'notes': str (optional)
        }
    
    Returns:
        Dictionary with success status and message details
    """
    bot_api_url = "http://discord-bot:5001/api/ecs_fc/post_rsvp_message"
    max_retries = 3
    initial_backoff = 5

    for attempt in range(max_retries):
        try:
            async with aiohttp.ClientSession() as session:
                logger.info(
                    f"Sending ECS FC RSVP message (attempt {attempt+1}/{max_retries})",
                    extra={'match_id': match_data.get('match_id'), 'team_id': match_data.get('team_id')}
                )
                
                timeout = 30 * (attempt + 1)
                async with session.post(bot_api_url, json=match_data, timeout=timeout) as response:
                    if response.status == 429:  # Rate limited
                        retry_after = response.headers.get('Retry-After', initial_backoff * (2 ** attempt))
                        try:
                            retry_after = int(retry_after)
                        except (ValueError, TypeError):
                            retry_after = initial_backoff * (2 ** attempt)
                        
                        logger.warning(
                            f"Discord rate limit hit, retrying after {retry_after}s",
                            extra={'status': response.status, 'retry_after': retry_after, 'attempt': attempt + 1}
                        )
                        await asyncio.sleep(retry_after)
                        continue
                        
                    elif response.status != 200:
                        error_text = await response.text()
                        if attempt < max_retries - 1:
                            backoff = initial_backoff * (2 ** attempt)
                            logger.warning(
                                f"ECS FC RSVP message failed (attempt {attempt+1}/{max_retries}), retrying in {backoff}s",
                                extra={'status': response.status, 'error': error_text}
                            )
                            await asyncio.sleep(backoff)
                            continue
                        
                        logger.error(
                            f"Failed to send ECS FC RSVP message after {max_retries} attempts",
                            extra={'status': response.status, 'error': error_text}
                        )
                        return {
                            'success': False,
                            'message': f"Discord API error: {response.status}",
                            'error': error_text
                        }
                    
                    # Success
                    response_data = await response.json()
                    logger.info(
                        "ECS FC RSVP message sent successfully",
                        extra={
                            'match_id': match_data.get('match_id'),
                            'team_id': match_data.get('team_id'),
                            'message_id': response_data.get('message_id')
                        }
                    )
                    
                    return {
                        'success': True,
                        'message': 'ECS FC RSVP message sent successfully',
                        'message_id': response_data.get('message_id'),
                        'timestamp': datetime.utcnow().isoformat()
                    }
                    
        except asyncio.TimeoutError:
            if attempt < max_retries - 1:
                backoff = initial_backoff * (2 ** attempt)
                logger.warning(
                    f"Timeout sending ECS FC RSVP message (attempt {attempt+1}/{max_retries}), retrying in {backoff}s"
                )
                await asyncio.sleep(backoff)
                continue
            logger.error(f"Timeout sending ECS FC RSVP message after {max_retries} attempts")
            return {'success': False, 'message': 'Timeout contacting Discord bot'}
            
        except Exception as e:
            if attempt < max_retries - 1:
                backoff = initial_backoff * (2 ** attempt)
                logger.warning(
                    f"Error sending ECS FC RSVP message (attempt {attempt+1}/{max_retries}): {str(e)}, retrying in {backoff}s"
                )
                await asyncio.sleep(backoff)
                continue
            logger.error(f"Error sending ECS FC RSVP message after {max_retries} attempts: {str(e)}")
            return {'success': False, 'message': f'Error: {str(e)}'}

    return {'success': False, 'message': 'Max retries exceeded'}


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


async def send_ecs_fc_dm_batch_async(dm_list: List[Dict[str, str]]) -> Dict[str, Any]:
    """
    Send DMs to multiple players asynchronously for ECS FC RSVP reminders.
    
    Args:
        dm_list: List of dictionaries with 'discord_id' and 'message' keys
    
    Returns:
        Dictionary with success counts and details
    """
    bot_api_url = "http://discord-bot:5001/api/ecs_fc/send_dm_batch"
    
    payload = {
        "dm_list": dm_list
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(bot_api_url, json=payload, timeout=60) as response:
                if response.status == 200:
                    response_data = await response.json()
                    logger.info(
                        f"ECS FC batch DMs sent: {response_data.get('sent_count', 0)} successful, "
                        f"{response_data.get('failed_count', 0)} failed"
                    )
                    return {
                        'success': True,
                        'sent_count': response_data.get('sent_count', 0),
                        'failed_count': response_data.get('failed_count', 0),
                        'details': response_data.get('details', [])
                    }
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to send ECS FC batch DMs: {response.status} - {error_text}")
                    return {'success': False, 'message': f'Discord API error: {response.status}', 'error': error_text}
                    
    except Exception as e:
        logger.error(f"Error sending ECS FC batch DMs: {str(e)}")
        return {'success': False, 'message': f'Error: {str(e)}'}


async def update_ecs_fc_rsvp_embed_async(match_id: int) -> Dict[str, Any]:
    """
    Update the ECS FC RSVP embed in Discord with current response counts.
    
    Args:
        match_id: ID of the ECS FC match
    
    Returns:
        Dictionary with success status and details
    """
    bot_api_url = f"http://discord-bot:5001/api/ecs_fc/update_rsvp_embed/{match_id}"
    max_retries = 3
    retry_delay = 2
    
    for attempt in range(max_retries):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(bot_api_url, timeout=10 * (attempt + 1)) as response:
                    if response.status == 200:
                        logger.info(f"ECS FC RSVP embed updated successfully for match {match_id}")
                        return {'success': True, 'message': 'ECS FC RSVP embed updated successfully'}
                    else:
                        error_text = await response.text()
                        if attempt < max_retries - 1:
                            logger.warning(
                                f"Failed to update ECS FC RSVP embed (attempt {attempt+1}/{max_retries})",
                                extra={'match_id': match_id, 'status': response.status, 'error': error_text}
                            )
                            await asyncio.sleep(retry_delay * (attempt + 1))
                            continue
                        
                        logger.error(
                            f"Failed to update ECS FC RSVP embed after {max_retries} attempts",
                            extra={'match_id': match_id, 'status': response.status, 'error': error_text}
                        )
                        return {
                            'success': False, 
                            'message': f'Discord API error: {response.status}',
                            'error': error_text
                        }
                        
        except Exception as e:
            if attempt < max_retries - 1:
                logger.warning(f"Error updating ECS FC RSVP embed (attempt {attempt+1}/{max_retries}): {str(e)}")
                await asyncio.sleep(retry_delay * (attempt + 1))
                continue
            logger.error(f"Error updating ECS FC RSVP embed after {max_retries} attempts: {str(e)}")
            return {'success': False, 'message': f'Error: {str(e)}'}

    return {'success': False, 'message': 'Max retries exceeded'}


def format_ecs_fc_match_embed_data(match, response_counts: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
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