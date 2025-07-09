"""
Unified Substitute Pool System Tasks

This module contains Celery tasks for the unified substitute pool system
that supports ECS FC, Classic, and Premier leagues.
"""

import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

from celery import shared_task
from sqlalchemy.orm import joinedload

from app.core import db
from app.models import User, Player, Team
from app.models_substitute_pools import (
    SubstitutePool, SubstituteRequest, SubstituteResponse, SubstituteAssignment,
    get_active_substitutes, log_pool_action
)
from app.sms_helpers import send_sms
from app.email import send_email
from app.tasks.tasks_ecs_fc_rsvp_helpers import send_ecs_fc_dm_sync

logger = logging.getLogger(__name__)


@shared_task(name='notify_substitute_pool_of_request')
def notify_substitute_pool_of_request(request_id: int, league_type: str) -> Dict[str, Any]:
    """
    Send notifications to all active substitutes in the pool about a new request.
    
    Args:
        request_id: ID of the SubstituteRequest
        league_type: Type of league ('ECS FC', 'Classic', 'Premier')
        
    Returns:
        Dictionary with notification results
    """
    try:
        # Get the request with related data
        sub_request = db.session.query(SubstituteRequest).options(
            joinedload(SubstituteRequest.team)
        ).get(request_id)
        
        if not sub_request:
            logger.error(f"Substitute request {request_id} not found")
            return {'success': False, 'error': 'Request not found'}
        
        # Get match information based on league type
        match_info = get_match_info_for_league(sub_request, league_type)
        if not match_info:
            logger.error(f"Could not get match info for request {request_id}")
            return {'success': False, 'error': 'Match information not available'}
        
        # Get all active subs from the pool for this league, filtered by gender preference
        gender_filter = sub_request.gender_preference if hasattr(sub_request, 'gender_preference') else None
        
        # Get gender-specific subs if filter is applied
        if gender_filter:
            gender_specific_subs = get_active_substitutes(league_type, db.session, gender_filter)
        else:
            gender_specific_subs = []
            
        # Get all subs with they/them or null pronouns (they get all notifications)
        all_subs = get_active_substitutes(league_type, db.session, None)
        from app.models import Player
        inclusive_subs = []
        for sub in all_subs:
            if sub.player and sub.player.pronouns:
                if 'they/them' in sub.player.pronouns.lower():
                    inclusive_subs.append(sub)
            elif not sub.player.pronouns:  # null pronouns
                inclusive_subs.append(sub)
        
        # Combine lists and remove duplicates
        if gender_filter:
            active_subs = gender_specific_subs + inclusive_subs
            # Remove duplicates by player_id
            seen_player_ids = set()
            unique_subs = []
            for sub in active_subs:
                if sub.player_id not in seen_player_ids:
                    unique_subs.append(sub)
                    seen_player_ids.add(sub.player_id)
            active_subs = unique_subs
        else:
            # No filter, send to everyone
            active_subs = all_subs
        
        if not active_subs:
            gender_note = f" (filtered for {gender_filter} players)" if gender_filter else ""
            logger.warning(f"No active substitutes in the {league_type} pool{gender_note}")
            return {'success': True, 'notified': 0, 'message': f'No active substitutes in {league_type} pool{gender_note}'}
        
        # Prepare notification content
        match_date = match_info['date'].strftime('%A, %B %d') if match_info['date'] else 'TBD'
        match_time = match_info['time'].strftime('%I:%M %p').lstrip('0') if match_info['time'] else 'TBD'
        location = match_info['location'] or 'TBD'
        team_name = sub_request.team.name if sub_request.team else 'Unknown Team'
        
        positions_text = f" Positions needed: {sub_request.positions_needed}" if sub_request.positions_needed else ""
        gender_text = f" (seeking {gender_filter} player)" if gender_filter else ""
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
            if pool_entry.sms_for_sub_requests and user.sms_notifications and player.phone:
                sms_message = (
                    f"{league_type} Sub Request: {team_name} needs a substitute{gender_text} on {match_date} "
                    f"at {match_time} at {location}.{positions_text} "
                    f"Reply YES if available."
                )
                
                try:
                    success, error = send_sms(player.phone, sms_message, user_id=user.id)
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
                    f"**{league_type} Substitute Request{gender_text}**\n"
                    f"Team: {team_name}\n"
                    f"Date: {match_date}\n"
                    f"Time: {match_time}\n"
                    f"Location: {location}\n"
                    f"{positions_text}\n"
                    f"{notes_text}\n\n"
                    f"Reply with **YES** if you are available to substitute."
                )
                
                try:
                    # Create response record for tracking
                    response = SubstituteResponse(
                        request_id=request_id,
                        player_id=player.id,
                        is_available=False,  # Will be updated when they respond
                        response_method='DISCORD',
                        notification_sent_at=datetime.utcnow(),
                        notification_methods='DISCORD'
                    )
                    db.session.add(response)
                    db.session.flush()  # Get the ID
                    
                    # Send DM using existing system
                    dm_result = send_ecs_fc_dm_sync(player.discord_id, discord_message)
                    if dm_result['success']:
                        results['discord_sent'] += 1
                        notification_methods.append('DISCORD')
                        logger.info(f"{league_type} sub request DM sent to player {player.discord_id}")
                    else:
                        results['errors'].append(f"Discord DM failed: {dm_result.get('message')}")
                        logger.warning(f"Failed to send {league_type} sub DM to player {player.discord_id}: {dm_result.get('message')}")
                        
                except Exception as e:
                    logger.error(f"Error sending Discord DM to {player.name}: {e}")
                    results['errors'].append(f"Discord to {player.name}: {str(e)}")
            
            # Send Email if enabled
            if pool_entry.email_for_sub_requests and user.email_notifications and user.email:
                email_subject = f"{league_type} Substitute Request - {team_name}"
                
                positions_html = f'<p><strong>Positions needed:</strong> {sub_request.positions_needed}</p>' if sub_request.positions_needed else ''
                notes_html = f'<p><strong>Notes:</strong> {sub_request.notes}</p>' if sub_request.notes else ''
                
                email_body = f"""
                <h3>{league_type} Substitute Request</h3>
                <p><strong>Team:</strong> {team_name}</p>
                <p><strong>Date:</strong> {match_date}</p>
                <p><strong>Time:</strong> {match_time}</p>
                <p><strong>Location:</strong> {location}</p>
                {positions_html}
                {notes_html}
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
            
            # Create or update response record for non-Discord notifications
            if notification_methods and 'DISCORD' not in notification_methods:
                response = db.session.query(SubstituteResponse).filter_by(
                    request_id=request_id,
                    player_id=player.id
                ).first()
                
                if not response:
                    response = SubstituteResponse(
                        request_id=request_id,
                        player_id=player.id,
                        is_available=False,
                        response_method='PENDING',
                        notification_sent_at=datetime.utcnow(),
                        notification_methods=','.join(notification_methods)
                    )
                    db.session.add(response)
        
        db.session.commit()
        
        results['success'] = True
        results['message'] = (
            f"Notified {results['sms_sent'] + results['discord_sent'] + results['email_sent']} "
            f"substitutes out of {results['total_subs']} in the {league_type} pool"
        )
        
        logger.info(f"Substitute request {request_id} notification results: {results}")
        return results
        
    except Exception as e:
        logger.error(f"Error in notify_substitute_pool_of_request: {e}", exc_info=True)
        db.session.rollback()
        return {'success': False, 'error': str(e)}


@shared_task(name='notify_assigned_substitute')
def notify_assigned_substitute(assignment_id: int) -> Dict[str, Any]:
    """
    Send notification to the assigned substitute with match details.
    
    Args:
        assignment_id: ID of the SubstituteAssignment
        
    Returns:
        Dictionary with notification results
    """
    try:
        # Get assignment with related data
        assignment = db.session.query(SubstituteAssignment).options(
            joinedload(SubstituteAssignment.request).joinedload(SubstituteRequest.team),
            joinedload(SubstituteAssignment.player).joinedload(Player.user)
        ).get(assignment_id)
        
        if not assignment:
            logger.error(f"Assignment {assignment_id} not found")
            return {'success': False, 'error': 'Assignment not found'}
        
        player = assignment.player
        user = player.user if player else None
        
        if not user:
            logger.error(f"User not found for player {player.id if player else 'unknown'}")
            return {'success': False, 'error': 'User not found'}
        
        # Get match information based on league type
        match_info = get_match_info_for_league(assignment.request, assignment.request.league_type)
        if not match_info:
            logger.error(f"Could not get match info for assignment {assignment_id}")
            return {'success': False, 'error': 'Match information not available'}
        
        # Prepare notification content
        match_date = match_info['date'].strftime('%A, %B %d') if match_info['date'] else 'TBD'
        match_time = match_info['time'].strftime('%I:%M %p').lstrip('0') if match_info['time'] else 'TBD'
        location = match_info['location'] or 'TBD'
        team_name = assignment.request.team.name if assignment.request.team else 'Unknown Team'
        
        position_text = f" Position: {assignment.position_assigned}" if assignment.position_assigned else ""
        notes_text = f" Notes: {assignment.notes}" if assignment.notes else ""
        match_notes = f" Match notes: {match_info.get('notes', '')}" if match_info.get('notes') else ""
        
        results = {
            'player_name': player.name,
            'methods_attempted': [],
            'methods_successful': [],
            'errors': []
        }
        
        # Get sub pool preferences
        pool_entry = db.session.query(SubstitutePool).filter_by(
            player_id=player.id,
            league_type=assignment.request.league_type,
            is_active=True
        ).first()
        
        # Default to user preferences if no pool entry
        sms_enabled = pool_entry.sms_for_sub_requests if pool_entry else user.sms_notifications
        discord_enabled = pool_entry.discord_for_sub_requests if pool_entry else user.discord_notifications
        email_enabled = pool_entry.email_for_sub_requests if pool_entry else user.email_notifications
        
        # Send SMS
        if sms_enabled and player.phone:
            sms_message = (
                f"You've been assigned as a substitute for {team_name} on {match_date} "
                f"at {match_time} at {location}.{position_text}{match_notes}"
            )
            
            try:
                success, error = send_sms(player.phone, sms_message, user_id=user.id)
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
                position_line = f"**Position:** {assignment.position_assigned}\n" if assignment.position_assigned else ""
                notes_line = f"**Notes:** {assignment.notes}\n" if assignment.notes else ""
                match_notes_line = f"**Match Notes:** {match_info.get('notes', '')}\n" if match_info.get('notes') else ""
                
                discord_message = (
                    f"**You've been assigned as a substitute!**\n\n"
                    f"**Team:** {team_name}\n"
                    f"**Date:** {match_date}\n"
                    f"**Time:** {match_time}\n"
                    f"**Location:** {location}\n"
                    f"{position_line}"
                    f"{notes_line}"
                    f"{match_notes_line}\n"
                    f"Good luck!"
                )
                
                results['methods_attempted'].append('Discord')
                dm_result = send_ecs_fc_dm_sync(player.discord_id, discord_message)
                if dm_result['success']:
                    results['methods_successful'].append('Discord')
                    logger.info(f"Sub assignment DM sent to player {player.discord_id}")
                else:
                    results['errors'].append(f"Discord DM failed: {dm_result.get('message')}")
                    logger.warning(f"Failed to send assignment DM to player {player.discord_id}: {dm_result.get('message')}")
                    
            except Exception as e:
                logger.error(f"Error sending assignment Discord DM: {e}")
                results['errors'].append(f"Discord: {str(e)}")
        
        # Send Email
        if email_enabled and user.email:
            email_subject = f"Substitute Assignment - {team_name} on {match_date}"
            
            position_html = f'<p><strong>Position:</strong> {assignment.position_assigned}</p>' if assignment.position_assigned else ''
            notes_html = f'<p><strong>Assignment Notes:</strong> {assignment.notes}</p>' if assignment.notes else ''
            match_notes_html = f'<p><strong>Match Notes:</strong> {match_info.get("notes", "")}</p>' if match_info.get('notes') else ''
            
            email_body = f"""
            <h3>You've been assigned as a substitute!</h3>
            
            <p><strong>Team:</strong> {team_name}</p>
            <p><strong>Date:</strong> {match_date}</p>
            <p><strong>Time:</strong> {match_time}</p>
            <p><strong>Location:</strong> {location}</p>
            {position_html}
            {notes_html}
            {match_notes_html}
            
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
        
        db.session.commit()
        
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
        db.session.rollback()
        return {'success': False, 'error': str(e)}


@shared_task(name='process_substitute_response')
def process_substitute_response(player_id: int, response_text: str, response_method: str) -> Dict[str, Any]:
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
        response = db.session.query(SubstituteResponse).join(
            SubstituteRequest
        ).filter(
            SubstituteResponse.player_id == player_id,
            SubstituteRequest.status == 'OPEN'
        ).order_by(
            SubstituteResponse.notification_sent_at.desc()
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
        pool_entry = db.session.query(SubstitutePool).filter_by(
            player_id=player_id,
            league_type=response.request.league_type,
            is_active=True
        ).first()
        
        if pool_entry and is_available:
            pool_entry.requests_accepted += 1
        
        db.session.commit()
        
        return {
            'success': True,
            'is_available': is_available,
            'request_id': response.request_id,
            'message': f"Response recorded: {'Available' if is_available else 'Not available'}"
        }
        
    except Exception as e:
        logger.error(f"Error processing substitute response: {e}", exc_info=True)
        db.session.rollback()
        return {'success': False, 'error': str(e)}


def get_match_info_for_league(sub_request: SubstituteRequest, league_type: str) -> Optional[Dict[str, Any]]:
    """
    Get match information for a substitute request based on league type.
    
    Args:
        sub_request: The substitute request
        league_type: The league type ('ECS FC', 'Classic', 'Premier')
        
    Returns:
        Dictionary with match information or None if not found
    """
    try:
        if league_type == 'ECS FC':
            # For ECS FC, get match from ECS FC tables
            from app.models_ecs import EcsFcMatch
            match = db.session.query(EcsFcMatch).get(sub_request.match_id)
            if match:
                return {
                    'date': match.match_date,
                    'time': match.match_time,
                    'location': match.location,
                    'notes': match.notes
                }
        else:
            # For Pub League (Classic/Premier), get match from regular Match table
            from app.models import Match
            match = db.session.query(Match).get(sub_request.match_id)
            if match:
                return {
                    'date': match.date,
                    'time': match.time,
                    'location': match.location,
                    'notes': match.notes
                }
        
        return None
        
    except Exception as e:
        logger.error(f"Error getting match info for league {league_type}: {e}")
        return None