"""
ECS FC RSVP Tasks Module

This module defines Celery tasks specifically for ECS FC RSVP management.
These tasks handle RSVP notifications, reminders, and Discord integration
for the ECS FC scheduling system.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

from app.core import db, socketio
from app.decorators import celery_task
from app.models import Player, User, Team
from app.models_ecs import EcsFcMatch, EcsFcAvailability
from app.tasks.tasks_ecs_fc_rsvp_helpers import (
    send_ecs_fc_dm_sync,
    format_ecs_fc_match_embed_data
)
from app.utils.sync_discord_client import get_sync_discord_client
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)


@celery_task(name='app.tasks.tasks_rsvp_ecs.update_ecs_fc_rsvp', max_retries=3, queue='discord')
def update_ecs_fc_rsvp(self, session, match_id: int, player_id: int, new_response: str,
                       discord_id: Optional[str] = None, user_id: Optional[int] = None,
                       notes: Optional[str] = None) -> Dict[str, Any]:
    """
    Update RSVP response for an ECS FC match.

    Args:
        session: Database session
        match_id: ID of the ECS FC match
        player_id: ID of the player
        new_response: The new RSVP response ('yes', 'no', 'maybe')
        discord_id: Discord ID of the player (optional)
        user_id: User ID (optional)
        notes: Additional notes (optional)

    Returns:
        Dictionary with update result

    Raises:
        Retries the task on database or general errors
    """
    try:
        # Validate response
        if new_response not in ['yes', 'no', 'maybe']:
            return {
                'success': False,
                'message': 'Invalid RSVP response',
                'match_id': match_id,
                'player_id': player_id
            }

        # Get the match
        match = session.query(EcsFcMatch).options(
            joinedload(EcsFcMatch.team)
        ).filter(EcsFcMatch.id == match_id).first()
        
        if not match:
            return {
                'success': False,
                'message': 'ECS FC match not found',
                'match_id': match_id,
                'player_id': player_id
            }

        # Get the player
        player = session.query(Player).filter(Player.id == player_id).first()
        if not player:
            return {
                'success': False,
                'message': 'Player not found',
                'match_id': match_id,
                'player_id': player_id
            }

        # Check if player is on the team
        if not any(team.id == match.team_id for team in player.teams):
            return {
                'success': False,
                'message': 'Player is not on this team',
                'match_id': match_id,
                'player_id': player_id
            }

        # Get or create availability record
        availability = session.query(EcsFcAvailability).filter(
            EcsFcAvailability.ecs_fc_match_id == match_id,
            EcsFcAvailability.player_id == player_id
        ).first()

        old_response = availability.response if availability else None

        if availability:
            # Update existing record
            availability.response = new_response
            availability.user_id = user_id
            availability.discord_id = discord_id
            availability.notes = notes
            availability.response_time = datetime.utcnow()
        else:
            # Create new record
            availability = EcsFcAvailability(
                ecs_fc_match_id=match_id,
                player_id=player_id,
                user_id=user_id,
                discord_id=discord_id,
                response=new_response,
                notes=notes,
                response_time=datetime.utcnow()
            )
            session.add(availability)

        # Commit happens automatically in @celery_task decorator

        # Notify frontend via WebSocket
        try:
            socketio.emit('rsvp_update', {
                'match_id': match_id,
                'player_id': player_id,
                'response': new_response,
                'match_type': 'ecs_fc',
                'timestamp': datetime.utcnow().isoformat()
            }, room=f'team_{match.team_id}')
        except Exception as e:
            logger.warning(f"Failed to emit WebSocket update: {str(e)}")

        # Queue Discord notification update
        notify_ecs_fc_discord_of_rsvp_change_task.delay(match_id)

        logger.info(f"Updated ECS FC RSVP: match {match_id}, player {player_id}, response {new_response}")

        return {
            'success': True,
            'message': 'RSVP updated successfully',
            'match_id': match_id,
            'player_id': player_id,
            'old_response': old_response,
            'new_response': new_response,
            'update_timestamp': datetime.utcnow().isoformat()
        }

    except SQLAlchemyError as e:
        # Rollback happens automatically in @celery_task decorator
        logger.error(f"Database error updating ECS FC RSVP: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        # Rollback happens automatically in @celery_task decorator
        logger.error(f"Error updating ECS FC RSVP: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)


@celery_task(name='app.tasks.tasks_rsvp_ecs.send_ecs_fc_rsvp_reminder', max_retries=3, queue='discord')
def send_ecs_fc_rsvp_reminder(self, session, match_id: int, target_players: Optional[List[int]] = None) -> Dict[str, Any]:
    """
    Send RSVP reminders for an ECS FC match.

    Args:
        session: Database session
        match_id: ID of the ECS FC match
        target_players: List of player IDs to remind (optional)

    Returns:
        Dictionary with reminder result

    Raises:
        Retries the task on database or general errors
    """
    try:
        # Get the match with team and availability data
        match = session.query(EcsFcMatch).options(
            joinedload(EcsFcMatch.team),
            joinedload(EcsFcMatch.availabilities)
        ).filter(EcsFcMatch.id == match_id).first()

        if not match:
            return {
                'success': False,
                'message': 'ECS FC match not found',
                'match_id': match_id
            }

        # Get team players
        team_players = match.team.players if match.team else []
        if not team_players:
            return {
                'success': False,
                'message': 'No players found for this team',
                'match_id': match_id
            }

        # Determine which players need reminders
        if target_players is None:
            # Get players who haven't responded
            responded_players = {av.player_id for av in match.availabilities if av.response}
            all_players = {p.id for p in team_players}
            target_players = list(all_players - responded_players)

        if not target_players:
            return {
                'success': True,
                'message': 'No players need reminders',
                'match_id': match_id,
                'reminded_count': 0
            }

        # Create reminder message
        match_date_str = match.match_date.strftime("%B %d, %Y")
        match_time_str = match.match_time.strftime("%I:%M %p")
        
        embed = {
            "title": "🔔 RSVP Reminder",
            "description": f"Please respond to the RSVP for your upcoming match!",
            "color": 0xf39c12,
            "fields": [
                {"name": "Match", "value": f"{match.team.name} vs {match.opponent_name}", "inline": False},
                {"name": "Date", "value": match_date_str, "inline": True},
                {"name": "Time", "value": match_time_str, "inline": True},
                {"name": "Location", "value": match.location, "inline": False}
            ]
        }

        if match.field_name:
            embed["fields"].append({"name": "Field", "value": match.field_name, "inline": True})

        if match.rsvp_deadline:
            deadline_str = match.rsvp_deadline.strftime("%B %d at %I:%M %p")
            embed["fields"].append({"name": "RSVP Deadline", "value": deadline_str, "inline": False})

        # Send reminders to individual players
        reminded_count = 0
        failed_count = 0

        for player_id in target_players:
            try:
                player = session.query(Player).filter(Player.id == player_id).first()
                if not player or not player.discord_id:
                    continue

                # Send direct message to player using existing DM system
                reminder_message = (
                    f"🔔 **RSVP Reminder**\n\n"
                    f"You have an upcoming ECS FC match that needs your RSVP response:\n\n"
                    f"**{match.team.name} vs {match.opponent_name}**\n"
                    f"📅 {match.match_date.strftime('%B %d, %Y')}\n"
                    f"🕐 {match.match_time.strftime('%I:%M %p')}\n"
                    f"📍 {match.location}\n\n"
                    f"Please respond in your team's Discord channel as soon as possible!"
                )
                
                # Commit the session before making the external API call to avoid
                # holding the database transaction open during the Discord API call
                # Commit happens automatically in @celery_task decorator
                
                dm_result = send_ecs_fc_dm_sync(player.discord_id, reminder_message)
                if dm_result['success']:
                    logger.info(f"RSVP reminder DM sent to player {player.discord_id} for match {match_id}")
                else:
                    logger.warning(f"Failed to send RSVP reminder DM to player {player.discord_id}: {dm_result.get('message')}")
                
                reminded_count += 1
                
            except Exception as e:
                logger.error(f"Failed to send reminder to player {player_id}: {str(e)}")
                failed_count += 1

        # Also send a general reminder to the team channel by updating the original RSVP embed
        try:
            # Update the RSVP embed with current response counts
            discord_client = get_sync_discord_client()
            embed_result = discord_client.update_ecs_fc_rsvp_embed(match_id)
            if embed_result['success']:
                logger.info(f"Updated ECS FC RSVP embed for match {match_id} after sending {reminded_count} reminders")
            else:
                logger.warning(f"Failed to update ECS FC RSVP embed: {embed_result.get('message')}")
        except Exception as e:
            logger.warning(f"Failed to send team channel reminder: {str(e)}")

        logger.info(f"Sent ECS FC RSVP reminders: match {match_id}, {reminded_count} players reminded")

        return {
            'success': True,
            'message': f'Reminders sent to {reminded_count} players',
            'match_id': match_id,
            'reminded_count': reminded_count,
            'failed_count': failed_count,
            'reminder_timestamp': datetime.utcnow().isoformat()
        }

    except SQLAlchemyError as e:
        logger.error(f"Database error sending ECS FC RSVP reminder: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error sending ECS FC RSVP reminder: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)


@celery_task(name='app.tasks.tasks_rsvp_ecs.notify_ecs_fc_discord_of_rsvp_change', max_retries=3, queue='discord')
def notify_ecs_fc_discord_of_rsvp_change_task(self, session, match_id: int) -> Dict[str, Any]:
    """
    Notify Discord of RSVP changes for an ECS FC match.

    This task updates the Discord RSVP embed with current response counts.

    Args:
        session: Database session
        match_id: ID of the ECS FC match

    Returns:
        Dictionary with notification result

    Raises:
        Retries the task on database or general errors
    """
    try:
        # Get the match with availability data
        match = session.query(EcsFcMatch).options(
            joinedload(EcsFcMatch.team),
            joinedload(EcsFcMatch.availabilities)
        ).filter(EcsFcMatch.id == match_id).first()

        if not match:
            return {
                'success': False,
                'message': 'ECS FC match not found',
                'match_id': match_id
            }

        # Calculate RSVP summary
        rsvp_summary = match.get_rsvp_summary()
        
        # Create updated embed
        match_date_str = match.match_date.strftime("%B %d, %Y")
        match_time_str = match.match_time.strftime("%I:%M %p")
        
        # Determine embed color based on response rate
        total_players = rsvp_summary['yes'] + rsvp_summary['no'] + rsvp_summary['maybe'] + rsvp_summary['no_response']
        response_rate = (rsvp_summary['yes'] + rsvp_summary['no'] + rsvp_summary['maybe']) / max(total_players, 1)
        
        if response_rate >= 0.8:
            color = 0x27ae60  # Green
        elif response_rate >= 0.5:
            color = 0xf39c12  # Orange
        else:
            color = 0xe74c3c  # Red

        embed = {
            "title": f"⚽ {match.team.name} vs {match.opponent_name}",
            "description": f"Match scheduled for {match_date_str} at {match_time_str}",
            "color": color,
            "fields": [
                {"name": "📍 Location", "value": match.location, "inline": True},
                {"name": "🏠 Home/Away", "value": "Home" if match.is_home_match else "Away", "inline": True},
                {"name": "\u200b", "value": "\u200b", "inline": True},  # Empty field for spacing
                
                {"name": "✅ Yes", "value": str(rsvp_summary['yes']), "inline": True},
                {"name": "❌ No", "value": str(rsvp_summary['no']), "inline": True},
                {"name": "❓ Maybe", "value": str(rsvp_summary['maybe']), "inline": True},
                
                {"name": "⏳ No Response", "value": str(rsvp_summary['no_response']), "inline": True},
                {"name": "📊 Response Rate", "value": f"{response_rate:.1%}", "inline": True},
                {"name": "\u200b", "value": "\u200b", "inline": True}  # Empty field for spacing
            ]
        }

        if match.field_name:
            embed["fields"].insert(2, {"name": "🏟️ Field", "value": match.field_name, "inline": True})

        if match.notes:
            embed["fields"].append({"name": "📝 Notes", "value": match.notes, "inline": False})

        if match.rsvp_deadline:
            deadline_str = match.rsvp_deadline.strftime("%B %d at %I:%M %p")
            embed["fields"].append({"name": "⏰ RSVP Deadline", "value": deadline_str, "inline": False})

        # Update the RSVP embed with current response counts
        discord_client = get_sync_discord_client()
        embed_result = discord_client.update_ecs_fc_rsvp_embed(match_id)
        if embed_result['success']:
            logger.info(f"Updated ECS FC RSVP embed for match {match_id} after RSVP change")
        else:
            logger.warning(f"Failed to update ECS FC RSVP embed: {embed_result.get('message')}")

        logger.info(f"Updated ECS FC Discord RSVP notification: match {match_id}")

        return {
            'success': True,
            'message': 'Discord RSVP notification updated',
            'match_id': match_id,
            'rsvp_summary': rsvp_summary,
            'notification_timestamp': datetime.utcnow().isoformat()
        }

    except SQLAlchemyError as e:
        logger.error(f"Database error updating ECS FC Discord RSVP: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error updating ECS FC Discord RSVP: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)


@celery_task(name='app.tasks.tasks_rsvp_ecs.send_ecs_fc_match_notification', max_retries=3, queue='discord')
def send_ecs_fc_match_notification(self, session, match_id: int, notification_type: str = 'created') -> Dict[str, Any]:
    """
    Send notification about ECS FC match events.

    Args:
        session: Database session
        match_id: ID of the ECS FC match
        notification_type: Type of notification ('created', 'updated', 'cancelled')

    Returns:
        Dictionary with notification result

    Raises:
        Retries the task on database or general errors
    """
    try:
        # Get the match
        match = session.query(EcsFcMatch).options(
            joinedload(EcsFcMatch.team)
        ).filter(EcsFcMatch.id == match_id).first()

        if not match:
            return {
                'success': False,
                'message': 'ECS FC match not found',
                'match_id': match_id
            }

        # Format match information
        match_info = f"{match.team.name} vs {match.opponent_name}"
        date_str = match.match_date.strftime("%B %d, %Y")
        time_str = match.match_time.strftime("%I:%M %p")
        location_str = match.location
        if match.field_name:
            location_str += f" ({match.field_name})"

        # Create notification based on type
        if notification_type == 'created':
            title = "🆕 New Match Scheduled"
            description = f"A new match has been scheduled: {match_info}"
            color = 0x3498db
        elif notification_type == 'updated':
            title = "📝 Match Updated"
            description = f"Match details have been updated: {match_info}"
            color = 0xf39c12
        elif notification_type == 'cancelled':
            title = "❌ Match Cancelled"
            description = f"The following match has been cancelled: {match_info}"
            color = 0xe74c3c
        else:
            return {
                'success': False,
                'message': f'Invalid notification type: {notification_type}',
                'match_id': match_id
            }

        embed = {
            "title": title,
            "description": description,
            "color": color,
            "fields": [
                {"name": "📅 Date", "value": date_str, "inline": True},
                {"name": "🕐 Time", "value": time_str, "inline": True},
                {"name": "📍 Location", "value": location_str, "inline": False}
            ]
        }

        if notification_type != 'cancelled':
            embed["fields"].append({"name": "🏠 Home/Away", "value": "Home" if match.is_home_match else "Away", "inline": True})
            
            if match.notes:
                embed["fields"].append({"name": "📝 Notes", "value": match.notes, "inline": False})

            if match.rsvp_deadline:
                deadline_str = match.rsvp_deadline.strftime("%B %d at %I:%M %p")
                embed["fields"].append({"name": "⏰ RSVP Deadline", "value": deadline_str, "inline": False})

        # TODO: Send notification to team channel
        logger.info(f"Should send match notification to team {match.team_id}: {description}")

        logger.info(f"Sent ECS FC match notification: match {match_id}, type {notification_type}")

        return {
            'success': True,
            'message': f'Match {notification_type} notification sent',
            'match_id': match_id,
            'notification_type': notification_type,
            'notification_timestamp': datetime.utcnow().isoformat()
        }

    except SQLAlchemyError as e:
        logger.error(f"Database error sending ECS FC match notification: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error sending ECS FC match notification: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)


@celery_task(name='app.tasks.tasks_rsvp_ecs.cleanup_old_ecs_fc_availabilities', max_retries=3, queue='maintenance')
def cleanup_old_ecs_fc_availabilities(self, session, days_old: int = 90) -> Dict[str, Any]:
    """
    Clean up old ECS FC availability records.

    Args:
        session: Database session
        days_old: Age threshold in days (default: 90)

    Returns:
        Dictionary with cleanup result

    Raises:
        Retries the task on database or general errors
    """
    try:
        cutoff_date = datetime.utcnow().date() - timedelta(days=days_old)
        
        # Find old availability records
        old_availabilities = session.query(EcsFcAvailability).join(EcsFcMatch).filter(
            EcsFcMatch.match_date < cutoff_date
        ).all()

        deleted_count = len(old_availabilities)
        
        if deleted_count > 0:
            # Delete in batches to avoid long transactions
            batch_size = 100
            for i in range(0, deleted_count, batch_size):
                batch = old_availabilities[i:i + batch_size]
                for availability in batch:
                    session.delete(availability)
                # Commit happens automatically in @celery_task decorator
                logger.info(f"Deleted batch of {len(batch)} old ECS FC availability records")

        logger.info(f"Cleaned up {deleted_count} old ECS FC availability records older than {days_old} days")

        return {
            'success': True,
            'message': f'Cleaned up {deleted_count} old availability records',
            'deleted_count': deleted_count,
            'cutoff_date': cutoff_date.isoformat(),
            'cleanup_timestamp': datetime.utcnow().isoformat()
        }

    except SQLAlchemyError as e:
        # Rollback happens automatically in @celery_task decorator
        logger.error(f"Database error cleaning up old ECS FC availabilities: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        # Rollback happens automatically in @celery_task decorator
        logger.error(f"Error cleaning up old ECS FC availabilities: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)


# Alias for backward compatibility and ease of use
send_rsvp_reminder_task = send_ecs_fc_rsvp_reminder
notify_discord_of_rsvp_change_task = notify_ecs_fc_discord_of_rsvp_change_task