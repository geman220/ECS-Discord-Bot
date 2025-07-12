"""
ECS FC Substitute System Celery Tasks

This module contains all asynchronous tasks for the ECS FC substitute system,
including notifications via SMS, Discord, and email.
"""

import logging
from datetime import datetime
from typing import List, Dict, Any

from sqlalchemy.orm import joinedload

from app.decorators import celery_task
from app.models import User, Player
from app.models_ecs import EcsFcMatch
from app.models_ecs_subs import (
    EcsFcSubRequest, EcsFcSubResponse, EcsFcSubAssignment, EcsFcSubPool
)
from app.models import db as database
from app.sms_helpers import send_sms
from app.email import send_email
from app.tasks.tasks_ecs_fc_rsvp_helpers import send_ecs_fc_dm_sync

logger = logging.getLogger(__name__)


@celery_task(name='notify_sub_pool_of_request')
def notify_sub_pool_of_request(self, session, request_id: int) -> Dict[str, Any]:
    """
    Send notifications to all active substitutes in the pool about a new request.
    
    Args:
        request_id: ID of the EcsFcSubRequest
        
    Returns:
        Dictionary with notification results
    """
    try:
        # Get the request with related data
        sub_request = session.query(EcsFcSubRequest).options(
            joinedload(EcsFcSubRequest.match).joinedload(EcsFcMatch.team),
            joinedload(EcsFcSubRequest.team)
        ).get(request_id)
        
        if not sub_request:
            logger.error(f"Sub request {request_id} not found")
            return {'success': False, 'error': 'Request not found'}
        
        match = sub_request.match
        if not match:
            logger.error(f"Match not found for sub request {request_id}")
            return {'success': False, 'error': 'Match not found'}
        
        # Get all active subs from the pool
        active_subs = session.query(EcsFcSubPool).options(
            joinedload(EcsFcSubPool.player).joinedload(Player.user)
        ).filter_by(is_active=True).all()
        
        if not active_subs:
            logger.warning("No active substitutes in the pool")
            return {'success': True, 'notified': 0, 'message': 'No active substitutes to notify'}
        
        # Prepare notification content
        match_date = match.match_date.strftime('%A, %B %d')
        match_time = match.match_time.strftime('%I:%M %p').lstrip('0')
        location = match.location
        team_name = match.team.name if match.team else 'Unknown Team'
        
        positions_text = f" Positions needed: {sub_request.positions_needed}" if sub_request.positions_needed else ""
        notes_text = f" Notes: {sub_request.notes}" if sub_request.notes else ""
        
        # Track notification results
        results = {
            'total_subs': len(active_subs),
            'sms_sent': 0,
            'discord_sent': 0,
            'email_sent': 0,
            'errors': []
        }
        
        for pool_entry in active_subs:
            player = pool_entry.player
            if not player or not player.user:
                continue
            
            user = player.user
            notification_methods = []
            
            # Send SMS if enabled
            if pool_entry.sms_for_sub_requests and user.sms_notifications and player.phone_number:
                sms_message = (
                    f"ECS FC Sub Request: {team_name} needs a substitute on {match_date} "
                    f"at {match_time} at {location}.{positions_text} "
                    f"Reply YES if available."
                )
                
                try:
                    success, error = send_sms(player.phone_number, sms_message, user_id=user.id)
                    if success:
                        results['sms_sent'] += 1
                        notification_methods.append('SMS')
                    else:
                        results['errors'].append(f"SMS to {player.name}: {error}")
                except Exception as e:
                    logger.error(f"Error sending SMS to {player.name}: {e}")
                    results['errors'].append(f"SMS to {player.name}: {str(e)}")
            
            # Send Discord DM if enabled
            if pool_entry.discord_for_sub_requests and user.discord_notifications and player.discord_id:
                discord_message = (
                    f"**ECS FC Substitute Request**\n"
                    f"Team: {team_name}\n"
                    f"Date: {match_date}\n"
                    f"Time: {match_time}\n"
                    f"Location: {location}\n"
                    f"{positions_text}\n"
                    f"{notes_text}\n\n"
                    f"Reply with **YES** if you are available to substitute."
                )
                
                try:
                    # Store the request context for response handling
                    response = EcsFcSubResponse(
                        request_id=request_id,
                        player_id=player.id,
                        is_available=False,  # Will be updated when they respond
                        response_method='DISCORD',
                        notification_sent_at=datetime.utcnow(),
                        notification_methods='DISCORD'
                    )
                    session.add(response)
                    session.flush()  # Get the ID
                    
                    # Commit the session before making the external API call to avoid
                    # holding the database transaction open during the Discord API call
                    # Commit happens automatically in @celery_task decorator
                    
                    # Send DM using existing proven system
                    dm_result = send_ecs_fc_dm_sync(player.discord_id, discord_message)
                    if dm_result['success']:
                        results['discord_sent'] += 1
                        notification_methods.append('DISCORD')
                        logger.info(f"ECS FC sub request DM sent to player {player.discord_id}")
                    else:
                        results['errors'].append(f"Discord DM failed: {dm_result.get('message')}")
                        logger.warning(f"Failed to send ECS FC sub DM to player {player.discord_id}: {dm_result.get('message')}")
                        
                except Exception as e:
                    logger.error(f"Error sending Discord DM to {player.name}: {e}")
                    results['errors'].append(f"Discord to {player.name}: {str(e)}")
            
            # Send Email if enabled
            if pool_entry.email_for_sub_requests and user.email_notifications and user.email:
                email_subject = f"ECS FC Substitute Request - {team_name}"
                email_body = f"""
                <h3>ECS FC Substitute Request</h3>
                <p><strong>Team:</strong> {team_name}</p>
                <p><strong>Date:</strong> {match_date}</p>
                <p><strong>Time:</strong> {match_time}</p>
                <p><strong>Location:</strong> {location}</p>
                {f'<p><strong>Positions needed:</strong> {sub_request.positions_needed}</p>' if sub_request.positions_needed else ''}
                {f'<p><strong>Notes:</strong> {sub_request.notes}</p>' if sub_request.notes else ''}
                <br>
                <p>If you are available to substitute, please respond via SMS or Discord.</p>
                """
                
                try:
                    send_email(
                        user.email,
                        email_subject,
                        email_body,
                        is_html=True
                    )
                    results['email_sent'] += 1
                    notification_methods.append('EMAIL')
                except Exception as e:
                    logger.error(f"Error sending email to {player.name}: {e}")
                    results['errors'].append(f"Email to {player.name}: {str(e)}")
            
            # Update pool stats
            pool_entry.requests_received += 1
            pool_entry.last_active_at = datetime.utcnow()
            
            # Create or update response record
            if notification_methods and not (pool_entry.discord_for_sub_requests and 'DISCORD' in notification_methods):
                # For non-Discord notifications, create a response record
                response = session.query(EcsFcSubResponse).filter_by(
                    request_id=request_id,
                    player_id=player.id
                ).first()
                
                if not response:
                    response = EcsFcSubResponse(
                        request_id=request_id,
                        player_id=player.id,
                        is_available=False,
                        response_method='PENDING',
                        notification_sent_at=datetime.utcnow(),
                        notification_methods=','.join(notification_methods)
                    )
                    session.add(response)
        
        # Session will be committed by decorator
        
        results['success'] = True
        results['message'] = (
            f"Notified {results['sms_sent'] + results['discord_sent'] + results['email_sent']} "
            f"substitutes out of {results['total_subs']} in the pool"
        )
        
        logger.info(f"Sub request {request_id} notification results: {results}")
        return results
        
    except Exception as e:
        logger.error(f"Error in notify_sub_pool_of_request: {e}", exc_info=True)
        # Session rollback handled by decorator
        return {'success': False, 'error': str(e)}


@celery_task(name='notify_assigned_substitute')
def notify_assigned_substitute(self, session, assignment_id: int) -> Dict[str, Any]:
    """
    Send notification to the assigned substitute with match details.
    
    Args:
        assignment_id: ID of the EcsFcSubAssignment
        
    Returns:
        Dictionary with notification results
    """
    try:
        # Get assignment with related data
        assignment = session.query(EcsFcSubAssignment).options(
            joinedload(EcsFcSubAssignment.request).joinedload(EcsFcSubRequest.match).joinedload(EcsFcMatch.team),
            joinedload(EcsFcSubAssignment.player).joinedload(Player.user)
        ).get(assignment_id)
        
        if not assignment:
            logger.error(f"Assignment {assignment_id} not found")
            return {'success': False, 'error': 'Assignment not found'}
        
        player = assignment.player
        user = player.user if player else None
        
        if not user:
            logger.error(f"User not found for player {player.id if player else 'unknown'}")
            return {'success': False, 'error': 'User not found'}
        
        match = assignment.request.match
        if not match:
            logger.error(f"Match not found for assignment {assignment_id}")
            return {'success': False, 'error': 'Match not found'}
        
        # Prepare notification content
        match_date = match.match_date.strftime('%A, %B %d')
        match_time = match.match_time.strftime('%I:%M %p').lstrip('0')
        location = match.location
        team_name = match.team.name if match.team else 'Unknown Team'
        
        position_text = f" Position: {assignment.position_assigned}" if assignment.position_assigned else ""
        notes_text = f" Notes: {assignment.notes}" if assignment.notes else ""
        match_notes = f" Match notes: {match.notes}" if match.notes else ""
        
        results = {
            'player_name': player.name,
            'methods_attempted': [],
            'methods_successful': [],
            'errors': []
        }
        
        # Get sub pool preferences
        pool_entry = session.query(EcsFcSubPool).filter_by(
            player_id=player.id,
            is_active=True
        ).first()
        
        # Default to user preferences if no pool entry
        sms_enabled = pool_entry.sms_for_sub_requests if pool_entry else user.sms_notifications
        discord_enabled = pool_entry.discord_for_sub_requests if pool_entry else user.discord_notifications
        email_enabled = pool_entry.email_for_sub_requests if pool_entry else user.email_notifications
        
        # Send SMS
        if sms_enabled and player.phone_number:
            sms_message = (
                f"You've been assigned as a substitute for {team_name} on {match_date} "
                f"at {match_time} at {location}.{position_text}{match_notes}"
            )
            
            try:
                success, error = send_sms(player.phone_number, sms_message, user_id=user.id)
                results['methods_attempted'].append('SMS')
                if success:
                    results['methods_successful'].append('SMS')
                else:
                    results['errors'].append(f"SMS: {error}")
            except Exception as e:
                logger.error(f"Error sending assignment SMS: {e}")
                results['errors'].append(f"SMS: {str(e)}")
        
        # Send Discord DM
        if discord_enabled and player.discord_id:
            try:
                discord_message = (
                    f"**You've been assigned as a substitute!**\n\n"
                    f"**Team:** {team_name}\n"
                    f"**Date:** {match_date}\n"
                    f"**Time:** {match_time}\n"
                    f"**Location:** {location}\n"
                    f"{f'**Position:** {assignment.position_assigned}' if assignment.position_assigned else ''}\n"
                    f"{f'**Notes:** {assignment.notes}' if assignment.notes else ''}\n"
                    f"{f'**Match Notes:** {match.notes}' if match.notes else ''}\n\n"
                    f"Good luck!"
                )
                
                results['methods_attempted'].append('Discord')
                
                # Commit the session before making the external API call to avoid
                # holding the database transaction open during the Discord API call
                # Commit happens automatically in @celery_task decorator
                
                dm_result = send_ecs_fc_dm_sync(player.discord_id, discord_message)
                if dm_result['success']:
                    results['methods_successful'].append('Discord')
                    logger.info(f"ECS FC sub assignment DM sent to player {player.discord_id}")
                else:
                    results['errors'].append(f"Discord DM failed: {dm_result.get('message')}")
                    logger.warning(f"Failed to send ECS FC assignment DM to player {player.discord_id}: {dm_result.get('message')}")
                    
            except Exception as e:
                logger.error(f"Error sending assignment Discord DM: {e}")
                results['errors'].append(f"Discord: {str(e)}")
        
        # Send Email
        if email_enabled and user.email:
            email_subject = f"Substitute Assignment - {team_name} on {match_date}"
            email_body = f"""
            <h3>You've been assigned as a substitute!</h3>
            
            <p><strong>Team:</strong> {team_name}</p>
            <p><strong>Date:</strong> {match_date}</p>
            <p><strong>Time:</strong> {match_time}</p>
            <p><strong>Location:</strong> {location}</p>
            {f'<p><strong>Position:</strong> {assignment.position_assigned}</p>' if assignment.position_assigned else ''}
            {f'<p><strong>Assignment Notes:</strong> {assignment.notes}</p>' if assignment.notes else ''}
            {f'<p><strong>Match Notes:</strong> {match.notes}</p>' if match.notes else ''}
            
            <br>
            <p>Good luck at the match!</p>
            """
            
            try:
                send_email(
                    user.email,
                    email_subject,
                    email_body,
                    is_html=True
                )
                results['methods_attempted'].append('Email')
                results['methods_successful'].append('Email')
            except Exception as e:
                logger.error(f"Error sending assignment email: {e}")
                results['errors'].append(f"Email: {str(e)}")
        
        # Update assignment notification status
        assignment.notification_sent = True
        assignment.notification_sent_at = datetime.utcnow()
        assignment.notification_methods = ','.join(results['methods_successful'])
        
        # Update pool stats if exists
        if pool_entry:
            pool_entry.matches_played += 1
        
        # Session will be committed by decorator
        
        results['success'] = len(results['methods_successful']) > 0
        results['message'] = (
            f"Notified {player.name} via {', '.join(results['methods_successful'])}" 
            if results['methods_successful'] 
            else f"Failed to notify {player.name}"
        )
        
        logger.info(f"Assignment {assignment_id} notification results: {results}")
        return results
        
    except Exception as e:
        logger.error(f"Error in notify_assigned_substitute: {e}", exc_info=True)
        # Session rollback handled by decorator
        return {'success': False, 'error': str(e)}


@celery_task(name='process_ecs_fc_sub_response')
def process_sub_response(self, session, player_id: int, response_text: str, response_method: str) -> Dict[str, Any]:
    """
    Process a substitute's response to a request.
    
    Args:
        player_id: ID of the player responding
        response_text: The response text (e.g., "YES", "NO")
        response_method: How they responded (SMS, DISCORD)
        
    Returns:
        Dictionary with processing results
    """
    try:
        # Normalize response
        response_text = response_text.strip().upper()
        is_available = response_text in ['YES', 'Y', 'AVAILABLE', '1']
        
        # Find the most recent open request that this player was notified about
        response = session.query(EcsFcSubResponse).join(
            EcsFcSubRequest
        ).filter(
            EcsFcSubResponse.player_id == player_id,
            EcsFcSubRequest.status == 'OPEN'
        ).order_by(
            EcsFcSubResponse.notification_sent_at.desc()
        ).first()
        
        if not response:
            logger.warning(f"No open sub request found for player {player_id}")
            return {
                'success': False,
                'error': 'No active substitute request found'
            }
        
        # Update the response
        response.is_available = is_available
        response.response_method = response_method
        response.response_text = response_text
        response.responded_at = datetime.utcnow()
        
        # Update pool stats
        pool_entry = session.query(EcsFcSubPool).filter_by(
            player_id=player_id,
            is_active=True
        ).first()
        
        if pool_entry and is_available:
            pool_entry.requests_accepted += 1
        
        # Session will be committed by decorator
        
        return {
            'success': True,
            'is_available': is_available,
            'request_id': response.request_id,
            'message': f"Response recorded: {'Available' if is_available else 'Not available'}"
        }
        
    except Exception as e:
        logger.error(f"Error processing sub response: {e}", exc_info=True)
        # Session rollback handled by decorator
        return {'success': False, 'error': str(e)}


@celery_task(name='notify_sub_pool_with_slots')
def notify_sub_pool_with_slots(self, session, request_id: int) -> Dict[str, Any]:
    """
    Send consolidated gender-specific notifications to substitutes about a new request with slots.
    Groups notifications by gender and sends one message per gender with all positions needed.
    
    Args:
        request_id: ID of the EcsFcSubRequest
        
    Returns:
        Dictionary with notification results
    """
    try:
        from collections import defaultdict
        
        # Get the request with related data
        sub_request = session.query(EcsFcSubRequest).options(
            joinedload(EcsFcSubRequest.match).joinedload(EcsFcMatch.team),
            joinedload(EcsFcSubRequest.team)
        ).get(request_id)
        
        if not sub_request:
            logger.error(f"Sub request {request_id} not found")
            return {'success': False, 'error': 'Request not found'}
        
        match = sub_request.match
        if not match:
            logger.error(f"Match not found for sub request {request_id}")
            return {'success': False, 'error': 'Match not found'}
        
        # Get all slots for this request
        slots_query = session.execute(
            "SELECT slot_number, position_needed, gender_needed FROM ecs_fc_sub_slots WHERE request_id = :request_id ORDER BY slot_number",
            {"request_id": request_id}
        )
        slots = slots_query.fetchall()
        
        if not slots:
            # No slots defined, fall back to original notification method
            return notify_sub_pool_of_request(self, session, request_id)
        
        # Group slots by gender
        gender_slots = defaultdict(list)
        for slot in slots:
            gender = slot[2] or 'any'  # gender_needed
            position = slot[1] or 'Any position'  # position_needed
            gender_slots[gender].append(position)
        
        # Get all active subs from the pool
        active_subs = session.query(EcsFcSubPool).options(
            joinedload(EcsFcSubPool.player).joinedload(Player.user)
        ).filter_by(is_active=True).all()
        
        if not active_subs:
            logger.warning("No active substitutes in the pool")
            return {'success': True, 'notified': 0, 'message': 'No active substitutes to notify'}
        
        # Group substitutes by gender based on pronouns
        subs_by_gender = {
            'male': [],
            'female': [],
            'any': []
        }
        
        for pool_entry in active_subs:
            player = pool_entry.player
            if not player or not player.user:
                continue
            
            pronouns = player.pronouns or ''
            if pronouns.lower() == 'he/him':
                subs_by_gender['male'].append(pool_entry)
            elif pronouns.lower() == 'she/her':
                subs_by_gender['female'].append(pool_entry)
            else:  # they/them or no pronouns
                subs_by_gender['any'].append(pool_entry)
        
        # Prepare match details
        match_date = match.match_date.strftime('%A, %B %d')
        match_time = match.match_time.strftime('%I:%M %p').lstrip('0')
        location = match.location
        team_name = match.team.name if match.team else 'Unknown Team'
        
        # Track notification results
        results = {
            'total_notified': 0,
            'messages_sent': 0,
            'by_gender': {},
            'errors': []
        }
        
        # Send consolidated notifications for each gender group
        for gender, positions in gender_slots.items():
            # Determine who to notify
            recipients = []
            if gender == 'male':
                recipients = subs_by_gender['male'] + subs_by_gender['any']
            elif gender == 'female':
                recipients = subs_by_gender['female'] + subs_by_gender['any']
            else:  # any gender
                recipients = active_subs
            
            if not recipients:
                continue
            
            # Format the message
            num_needed = len(positions)
            gender_text = f"{num_needed} {gender}" if gender != 'any' else f"{num_needed}"
            positions_text = ", ".join(set(positions))  # Remove duplicates
            
            if gender == 'any':
                message_header = f"Need {num_needed} substitute{'s' if num_needed > 1 else ''}"
            else:
                message_header = f"Need {num_needed} {gender} substitute{'s' if num_needed > 1 else ''}"
            
            sms_message = (
                f"ECS FC: {message_header} ({positions_text}) for {team_name} "
                f"on {match_date} at {match_time} at {location}. Reply YES if available."
            )
            
            discord_message = (
                f"🚨 **ECS FC Substitute Request**\n"
                f"**{message_header}**\n"
                f"**Positions:** {positions_text}\n"
                f"**Team:** {team_name}\n"
                f"**Date:** {match_date}\n"
                f"**Time:** {match_time}\n"
                f"**Location:** {location}\n\n"
                f"Reply **YES** if you are available!"
            )
            
            email_subject = f"ECS FC: {message_header} - {team_name}"
            email_body = f"""
            <h3>ECS FC Substitute Request</h3>
            <p><strong>{message_header}</strong></p>
            <p><strong>Positions needed:</strong> {positions_text}</p>
            <p><strong>Team:</strong> {team_name}</p>
            <p><strong>Date:</strong> {match_date}</p>
            <p><strong>Time:</strong> {match_time}</p>
            <p><strong>Location:</strong> {location}</p>
            <br>
            <p>If you are available to substitute, please respond via SMS or Discord.</p>
            """
            
            gender_results = {
                'total': len(recipients),
                'sms': 0,
                'discord': 0,
                'email': 0
            }
            
            # Send to each recipient
            for pool_entry in recipients:
                player = pool_entry.player
                user = player.user
                notification_methods = []
                
                # Send SMS if enabled
                if pool_entry.sms_for_sub_requests and user.sms_notifications and player.phone_number:
                    try:
                        success, error = send_sms(player.phone_number, sms_message, user_id=user.id)
                        if success:
                            gender_results['sms'] += 1
                            notification_methods.append('SMS')
                    except Exception as e:
                        logger.error(f"Error sending SMS to {player.name}: {e}")
                        results['errors'].append(f"SMS to {player.name}: {str(e)}")
                
                # Send Discord DM if enabled
                if pool_entry.discord_for_sub_requests and user.discord_notifications and player.discord_id:
                    try:
                        # Commit the session before making the external API call to avoid
                        # holding the database transaction open during the Discord API call
                        # Commit happens automatically in @celery_task decorator
                        
                        success, error = send_ecs_fc_dm_sync(
                            int(player.discord_id),
                            discord_message
                        )
                        if success:
                            gender_results['discord'] += 1
                            notification_methods.append('DISCORD')
                    except Exception as e:
                        logger.error(f"Error sending Discord DM to {player.name}: {e}")
                        results['errors'].append(f"Discord to {player.name}: {str(e)}")
                
                # Send Email if enabled
                if pool_entry.email_for_sub_requests and user.email_notifications and user.email:
                    try:
                        send_email(
                            user.email,
                            email_subject,
                            email_body,
                            is_html=True
                        )
                        gender_results['email'] += 1
                        notification_methods.append('EMAIL')
                    except Exception as e:
                        logger.error(f"Error sending email to {player.name}: {e}")
                        results['errors'].append(f"Email to {player.name}: {str(e)}")
                
                # Update pool stats
                pool_entry.requests_received += 1
                pool_entry.last_active_at = datetime.utcnow()
                
                # Create response record
                if notification_methods:
                    response = session.query(EcsFcSubResponse).filter_by(
                        request_id=request_id,
                        player_id=player.id
                    ).first()
                    
                    if not response:
                        response = EcsFcSubResponse(
                            request_id=request_id,
                            player_id=player.id,
                            is_available=False,
                            response_method='PENDING',
                            notification_sent_at=datetime.utcnow(),
                            notification_methods=','.join(notification_methods)
                        )
                        session.add(response)
                    
                    results['total_notified'] += 1
            
            results['by_gender'][gender] = gender_results
            results['messages_sent'] += 1
        
        # Session will be committed by decorator
        
        return {
            'success': True,
            'results': results,
            'message': f"Sent {results['messages_sent']} consolidated messages to {results['total_notified']} substitutes"
        }
        
    except Exception as e:
        logger.error(f"Error in notify_sub_pool_with_slots: {e}", exc_info=True)
        # Session rollback handled by decorator
        return {'success': False, 'error': str(e)}