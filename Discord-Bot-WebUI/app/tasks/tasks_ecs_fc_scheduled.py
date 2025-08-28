"""
ECS FC Scheduled Tasks Module

This module handles processing of scheduled messages for ECS FC matches,
integrating with the existing scheduled message system.
"""

import logging
from datetime import datetime
from typing import Dict, Any, Optional

from app.core import db
from app.decorators import celery_task
from app.models import ScheduledMessage
from app.models_ecs import EcsFcMatch, EcsFcAvailability
from app.ecs_fc_schedule import EcsFcScheduleManager
from app.tasks.tasks_ecs_fc_rsvp_helpers import (
    format_ecs_fc_match_embed_data
)
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)


@celery_task(name='app.tasks.tasks_ecs_fc_scheduled.send_ecs_fc_availability_message', max_retries=3, queue='discord')
def send_ecs_fc_availability_message(self, session, scheduled_message_id: int) -> Dict[str, Any]:
    """
    Send an ECS FC availability message based on a scheduled message.
    
    This task is called by the existing process_scheduled_messages task
    when it encounters a message with type 'ecs_fc_rsvp'.
    
    Args:
        session: Database session
        scheduled_message_id: ID of the scheduled message
        
    Returns:
        Dictionary with send result
    """
    try:
        # Get the scheduled message
        message = session.query(ScheduledMessage).filter(
            ScheduledMessage.id == scheduled_message_id
        ).first()
        
        if not message:
            return {
                'success': False,
                'message': 'Scheduled message not found'
            }
        
        # Extract ECS FC match ID from metadata
        metadata = message.message_metadata or {}
        ecs_fc_match_id = metadata.get('ecs_fc_match_id')
        
        if not ecs_fc_match_id:
            return {
                'success': False,
                'message': 'No ECS FC match ID in scheduled message metadata'
            }
        
        # Get the ECS FC match
        match = session.query(EcsFcMatch).options(
            joinedload(EcsFcMatch.team),
            joinedload(EcsFcMatch.availabilities)
        ).filter(EcsFcMatch.id == ecs_fc_match_id).first()
        
        if not match:
            return {
                'success': False,
                'message': f'ECS FC match {ecs_fc_match_id} not found'
            }
        
        # Build the RSVP message
        match_date_str = match.match_date.strftime("%B %d, %Y")
        match_time_str = match.match_time.strftime("%I:%M %p")
        
        # Get current RSVP summary
        rsvp_summary = match.get_rsvp_summary()
        
        # Create embed for Discord
        embed = {
            "title": f"📋 RSVP Reminder: {match.team.name} vs {match.opponent_name}",
            "description": "Please respond to let us know if you can make the match!",
            "color": 0x3498db,
            "fields": [
                {"name": "📅 Date", "value": match_date_str, "inline": True},
                {"name": "⏰ Time", "value": match_time_str, "inline": True},
                {"name": "📍 Location", "value": match.location, "inline": False}
            ]
        }
        
        if match.field_name:
            embed["fields"].append({"name": "🏟️ Field", "value": match.field_name, "inline": True})
            
        embed["fields"].append({"name": "🏠 Home/Away", "value": "Home" if match.is_home_match else "Away", "inline": True})
        
        # Add current RSVP status
        embed["fields"].append({
            "name": "📊 Current Responses",
            "value": f"✅ Yes: {rsvp_summary['yes']}\n❌ No: {rsvp_summary['no']}\n❓ Maybe: {rsvp_summary['maybe']}\n⏳ No Response: {rsvp_summary['no_response']}",
            "inline": False
        })
        
        if match.notes:
            embed["fields"].append({"name": "📝 Notes", "value": match.notes, "inline": False})
            
        if match.rsvp_deadline:
            deadline_str = match.rsvp_deadline.strftime("%B %d at %I:%M %p")
            embed["fields"].append({"name": "⏰ RSVP Deadline", "value": deadline_str, "inline": False})
        
        # Add instructions
        embed["footer"] = {
            "text": "React with ✅ for Yes, ❌ for No, or ❓ for Maybe"
        }
        
        # Send to team Discord channel
        try:
            # Build match data for Discord API
            match_data = {
                'match_id': match.id,
                'team_id': match.team_id,
                'team_name': match.team.name,
                'opponent_name': match.opponent_name,
                'match_date': match.match_date.strftime('%Y-%m-%d'),
                'match_time': match.match_time.strftime('%H:%M'),
                'location': match.location,
                'is_home_match': match.is_home_match,
                'rsvp_deadline': match.rsvp_deadline.isoformat() if match.rsvp_deadline else None,
                'notes': match.notes,
                'field_name': match.field_name,
                'response_counts': rsvp_summary
            }
            
            # Use synchronous Discord client to send RSVP message
            from app.utils.sync_discord_client import get_sync_discord_client
            discord_client = get_sync_discord_client()
            result = discord_client.send_ecs_fc_rsvp_message(match_data)
            
            if result['success']:
                # Update scheduled message
                message.status = 'SENT'
                message.sent_at = datetime.utcnow()
                message.send_error = None
                # Store the Discord message ID in metadata if returned
                if result.get('message_id'):
                    if not message.message_metadata:
                        message.message_metadata = {}
                    message.message_metadata['discord_message_id'] = result['message_id']
                # Commit happens automatically in @celery_task decorator
                
                logger.info(f"ECS FC RSVP reminder sent successfully for match {match.id}")
                
                return {
                    'success': True,
                    'message': 'ECS FC RSVP reminder sent successfully',
                    'match_id': match.id,
                    'team_id': match.team_id,
                    'discord_message_id': result.get('message_id')
                }
            else:
                # Failed to send
                message.status = 'FAILED'
                message.send_error = result.get('message', 'Unknown Discord API error')
                message.last_send_attempt = datetime.utcnow()
                # Commit happens automatically in @celery_task decorator
                
                return {
                    'success': False,
                    'message': f'Failed to send ECS FC RSVP reminder: {result.get("message")}',
                    'match_id': match.id
                }
            
        except Exception as e:
            logger.error(f"Error sending Discord notification: {str(e)}")
            message.status = 'FAILED'
            message.send_error = str(e)
            message.last_send_attempt = datetime.utcnow()
            # Commit happens automatically in @celery_task decorator
            
            return {
                'success': False,
                'message': f'Failed to send Discord notification: {str(e)}'
            }
            
    except SQLAlchemyError as e:
        # Rollback happens automatically in @celery_task decorator
        logger.error(f"Database error processing ECS FC scheduled message: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        # Rollback happens automatically in @celery_task decorator
        logger.error(f"Error processing ECS FC scheduled message: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)


@celery_task(name='app.tasks.tasks_ecs_fc_scheduled.schedule_ecs_fc_reminders', max_retries=3, queue='discord')
def schedule_ecs_fc_reminders(self, session, days_ahead: int = 90) -> Dict[str, Any]:
    """
    Schedule RSVP reminders for upcoming ECS FC matches.
    
    This task can be run periodically (e.g., daily) to ensure all
    ECS FC matches have scheduled reminders.
    
    Args:
        session: Database session
        days_ahead: Number of days ahead to schedule reminders for
        
    Returns:
        Dictionary with scheduling result
    """
    try:
        from datetime import timedelta
        
        # Get upcoming ECS FC matches without scheduled reminders
        end_date = datetime.now().date() + timedelta(days=days_ahead)
        
        matches = session.query(EcsFcMatch).filter(
            EcsFcMatch.match_date >= datetime.now().date(),
            EcsFcMatch.match_date <= end_date,
            EcsFcMatch.status == 'SCHEDULED'
        ).all()
        
        scheduled_count = 0
        skipped_count = 0
        
        for match in matches:
            # Check if reminder already exists
            existing = session.query(ScheduledMessage).filter(
                ScheduledMessage.message_metadata.op('->>')('ecs_fc_match_id') == str(match.id)
            ).first()
            
            if existing:
                skipped_count += 1
                continue
            
            # Schedule reminder
            try:
                EcsFcScheduleManager._schedule_rsvp_reminder(match)
                scheduled_count += 1
            except Exception as e:
                logger.error(f"Error scheduling reminder for match {match.id}: {str(e)}")
        
        logger.info(f"Scheduled {scheduled_count} ECS FC reminders, skipped {skipped_count} existing")
        
        return {
            'success': True,
            'message': f'Scheduled {scheduled_count} reminders',
            'scheduled_count': scheduled_count,
            'skipped_count': skipped_count,
            'total_matches': len(matches)
        }
        
    except SQLAlchemyError as e:
        # Rollback happens automatically in @celery_task decorator
        logger.error(f"Database error scheduling ECS FC reminders: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        # Rollback happens automatically in @celery_task decorator
        logger.error(f"Error scheduling ECS FC reminders: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)