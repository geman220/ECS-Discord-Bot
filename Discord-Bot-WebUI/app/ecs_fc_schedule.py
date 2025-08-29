"""
ECS FC Schedule Management Module

This module handles all ECS FC specific scheduling functionality including
match creation, editing, deletion, and integration with the RSVP system.
"""

import logging
from datetime import datetime, timedelta, date, time
from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy import and_, or_, desc, asc
from sqlalchemy.orm import joinedload
from flask import current_app, g

from app.core import db
from app.models import Team, League, Player, User
from app.models_ecs import EcsFcMatch, EcsFcAvailability, EcsFcScheduleTemplate, is_ecs_fc_team

logger = logging.getLogger(__name__)


class EcsFcScheduleManager:
    """Manager class for ECS FC schedule operations."""
    
    @staticmethod
    def create_match(
        team_id: int,
        opponent_name: str,
        match_date: date,
        match_time: time,
        location: str,
        field_name: str = None,
        is_home_match: bool = True,
        notes: str = None,
        created_by: int = None,
        rsvp_deadline: datetime = None
    ) -> Tuple[bool, str, Optional[EcsFcMatch]]:
        """
        Create a new ECS FC match.
        
        Args:
            team_id: ID of the team
            opponent_name: Name of the opposing team
            match_date: Date of the match
            match_time: Time of the match
            location: Location/venue of the match
            field_name: Specific field name (optional)
            is_home_match: Whether this is a home match
            notes: Additional notes
            created_by: User ID who created the match
            rsvp_deadline: Deadline for RSVP responses
            
        Returns:
            Tuple of (success, message, match_object)
        """
        try:
            # Validate that this is an ECS FC team
            if not is_ecs_fc_team(team_id):
                return False, "This team is not an ECS FC team", None
            
            # Validate required fields
            if not all([team_id, opponent_name, match_date, match_time, location]):
                return False, "Missing required fields", None
            
            # Check for date conflicts
            existing_match = g.db_session.query(EcsFcMatch).filter(
                EcsFcMatch.team_id == team_id,
                EcsFcMatch.match_date == match_date,
                EcsFcMatch.match_time == match_time
            ).first()
            
            if existing_match:
                return False, "A match already exists for this team at this date and time", None
            
            # Create the match
            match = EcsFcMatch(
                team_id=team_id,
                opponent_name=opponent_name.strip(),
                match_date=match_date,
                match_time=match_time,
                location=location.strip(),
                field_name=field_name.strip() if field_name else None,
                is_home_match=is_home_match,
                notes=notes.strip() if notes else None,
                created_by=created_by,
                rsvp_deadline=rsvp_deadline
            )
            
            g.db_session.add(match)
            g.db_session.commit()
            
            # Send Discord notification
            EcsFcScheduleManager._send_match_notification(match, "created")
            
            # Schedule automatic RSVP reminder
            EcsFcScheduleManager._schedule_rsvp_reminder(match)
            
            logger.info(f"Created ECS FC match: {match.id} for team {team_id}")
            return True, "Match created successfully", match
            
        except Exception as e:
            g.db_session.rollback()
            logger.error(f"Error creating ECS FC match: {str(e)}")
            return False, f"Error creating match: {str(e)}", None
    
    @staticmethod
    def update_match(
        match_id: int,
        **kwargs
    ) -> Tuple[bool, str, Optional[EcsFcMatch]]:
        """
        Update an existing ECS FC match.
        
        Args:
            match_id: ID of the match to update
            **kwargs: Fields to update
            
        Returns:
            Tuple of (success, message, match_object)
        """
        try:
            match = g.db_session.query(EcsFcMatch).filter(EcsFcMatch.id == match_id).first()
            if not match:
                return False, "Match not found", None
            
            # Update fields
            updatable_fields = [
                'opponent_name', 'match_date', 'match_time', 'location',
                'field_name', 'is_home_match', 'notes', 'status',
                'home_score', 'away_score', 'rsvp_deadline'
            ]
            
            changes_made = False
            for field, value in kwargs.items():
                if field in updatable_fields and hasattr(match, field):
                    if isinstance(value, str):
                        value = value.strip() if value else None
                    setattr(match, field, value)
                    changes_made = True
            
            if changes_made:
                g.db_session.commit()
                
                # Send notification for significant changes
                if any(field in kwargs for field in ['match_date', 'match_time', 'location']):
                    EcsFcScheduleManager._send_match_notification(match, "updated")
                
                logger.info(f"Updated ECS FC match: {match_id}")
                return True, "Match updated successfully", match
            else:
                return False, "No changes to update", match
                
        except Exception as e:
            g.db_session.rollback()
            logger.error(f"Error updating ECS FC match {match_id}: {str(e)}")
            return False, f"Error updating match: {str(e)}", None
    
    @staticmethod
    def delete_match(match_id: int) -> Tuple[bool, str]:
        """
        Delete an ECS FC match.
        
        Args:
            match_id: ID of the match to delete
            
        Returns:
            Tuple of (success, message)
        """
        try:
            match = g.db_session.query(EcsFcMatch).filter(EcsFcMatch.id == match_id).first()
            if not match:
                return False, "Match not found"
            
            # Store match info for notification
            team_name = match.team.name if match.team else "Unknown Team"
            opponent_name = match.opponent_name
            match_date = match.match_date
            
            # Delete the match (cascading will handle availability records)
            g.db_session.delete(match)
            g.db_session.commit()
            
            # Send cancellation notification
            EcsFcScheduleManager._send_match_notification(match, "cancelled")
            
            logger.info(f"Deleted ECS FC match: {match_id}")
            return True, "Match deleted successfully"
            
        except Exception as e:
            g.db_session.rollback()
            logger.error(f"Error deleting ECS FC match {match_id}: {str(e)}")
            return False, f"Error deleting match: {str(e)}"
    
    @staticmethod
    def get_team_matches(
        team_id: int,
        upcoming_only: bool = False,
        limit: int = None,
        offset: int = 0
    ) -> List[EcsFcMatch]:
        """
        Get matches for a specific team.
        
        Args:
            team_id: ID of the team
            upcoming_only: Only return future matches
            limit: Maximum number of matches to return
            offset: Number of matches to skip
            
        Returns:
            List of ECS FC matches
        """
        try:
            query = g.db_session.query(EcsFcMatch).filter(EcsFcMatch.team_id == team_id)
            
            if upcoming_only:
                query = query.filter(EcsFcMatch.match_date >= datetime.now().date())
            
            query = query.order_by(EcsFcMatch.match_date.asc(), EcsFcMatch.match_time.asc())
            
            if offset:
                query = query.offset(offset)
            
            if limit:
                query = query.limit(limit)
            
            return query.all()
            
        except Exception as e:
            logger.error(f"Error getting team matches for team {team_id}: {str(e)}")
            return []
    
    @staticmethod
    def get_match_by_id(match_id: int) -> Optional[EcsFcMatch]:
        """
        Get a specific match by ID.
        
        Args:
            match_id: ID of the match
            
        Returns:
            ECS FC match or None
        """
        try:
            return g.db_session.query(EcsFcMatch).options(
                joinedload(EcsFcMatch.team),
                joinedload(EcsFcMatch.availabilities)
            ).filter(EcsFcMatch.id == match_id).first()
            
        except Exception as e:
            logger.error(f"Error getting match {match_id}: {str(e)}")
            return None
    
    @staticmethod
    def get_matches_for_date_range(
        team_id: int,
        start_date: date,
        end_date: date
    ) -> List[EcsFcMatch]:
        """
        Get matches within a date range for a team.
        
        Args:
            team_id: ID of the team
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            
        Returns:
            List of ECS FC matches
        """
        try:
            return g.db_session.query(EcsFcMatch).filter(
                EcsFcMatch.team_id == team_id,
                EcsFcMatch.match_date >= start_date,
                EcsFcMatch.match_date <= end_date
            ).order_by(EcsFcMatch.match_date.asc(), EcsFcMatch.match_time.asc()).all()
            
        except Exception as e:
            logger.error(f"Error getting matches for date range: {str(e)}")
            return []
    
    @staticmethod
    def submit_rsvp(
        match_id: int,
        player_id: int,
        response: str,
        user_id: int = None,
        discord_id: str = None,
        notes: str = None
    ) -> Tuple[bool, str]:
        """
        Submit an RSVP response for a match.
        
        Args:
            match_id: ID of the match
            player_id: ID of the player
            response: RSVP response ('yes', 'no', 'maybe')
            user_id: User ID (optional)
            discord_id: Discord ID (optional)
            notes: Additional notes (optional)
            
        Returns:
            Tuple of (success, message)
        """
        try:
            # Validate response
            if response not in ['yes', 'no', 'maybe']:
                return False, "Invalid RSVP response"
            
            # Check if match exists
            match = g.db_session.query(EcsFcMatch).filter(EcsFcMatch.id == match_id).first()
            if not match:
                return False, "Match not found"
            
            # Check if player is on the team
            player = g.db_session.query(Player).filter(Player.id == player_id).first()
            if not player:
                return False, "Player not found"
            
            # Verify player is on the team
            if not any(team.id == match.team_id for team in player.teams):
                return False, "Player is not on this team"
            
            # Check for existing availability record
            availability = g.db_session.query(EcsFcAvailability).filter(
                EcsFcAvailability.ecs_fc_match_id == match_id,
                EcsFcAvailability.player_id == player_id
            ).first()
            
            if availability:
                # Update existing record
                availability.response = response
                availability.user_id = user_id
                availability.discord_id = discord_id
                availability.notes = notes.strip() if notes else None
                availability.response_time = datetime.utcnow()
            else:
                # Create new record
                availability = EcsFcAvailability(
                    ecs_fc_match_id=match_id,
                    player_id=player_id,
                    user_id=user_id,
                    discord_id=discord_id,
                    response=response,
                    notes=notes.strip() if notes else None,
                    response_time=datetime.utcnow()
                )
                g.db_session.add(availability)
            
            g.db_session.commit()
            
            logger.info(f"RSVP submitted for match {match_id}, player {player_id}: {response}")
            return True, "RSVP submitted successfully"
            
        except Exception as e:
            g.db_session.rollback()
            logger.error(f"Error submitting RSVP: {str(e)}")
            return False, f"Error submitting RSVP: {str(e)}"
    
    @staticmethod
    def get_rsvp_summary(match_id: int) -> Dict[str, Any]:
        """
        Get RSVP summary for a match.
        
        Args:
            match_id: ID of the match
            
        Returns:
            Dictionary with RSVP summary
        """
        try:
            match = g.db_session.query(EcsFcMatch).options(
                joinedload(EcsFcMatch.team),
                joinedload(EcsFcMatch.availabilities)
            ).filter(EcsFcMatch.id == match_id).first()
            
            if not match:
                return {'error': 'Match not found'}
            
            # Get all team players
            team_players = match.team.players if match.team else []
            
            # Initialize counts
            summary = {
                'yes': 0,
                'no': 0,
                'maybe': 0,
                'no_response': 0,
                'total_players': len(team_players),
                'responses': []
            }
            
            # Count responses
            responded_players = set()
            for availability in match.availabilities:
                if availability.response:
                    summary[availability.response] += 1
                    responded_players.add(availability.player_id)
                    
                    # Add detailed response info
                    player_info = {
                        'player_id': availability.player_id,
                        'player_name': availability.player.player_name if availability.player else 'Unknown',
                        'response': availability.response,
                        'response_time': availability.response_time.isoformat() if availability.response_time else None,
                        'notes': availability.notes
                    }
                    summary['responses'].append(player_info)
            
            # Count players who haven't responded
            all_player_ids = {p.id for p in team_players}
            summary['no_response'] = len(all_player_ids - responded_players)
            
            return summary
            
        except Exception as e:
            logger.error(f"Error getting RSVP summary for match {match_id}: {str(e)}")
            return {'error': str(e)}
    
    @staticmethod
    def send_rsvp_reminders(match_id: int, target_players: List[int] = None) -> Tuple[bool, str]:
        """
        Send RSVP reminders for a match.
        
        Args:
            match_id: ID of the match
            target_players: List of player IDs to remind (optional, defaults to all unresponded)
            
        Returns:
            Tuple of (success, message)
        """
        try:
            match = g.db_session.query(EcsFcMatch).filter(EcsFcMatch.id == match_id).first()
            if not match:
                return False, "Match not found"
            
            # Get players who haven't responded
            if target_players is None:
                responded_players = {
                    av.player_id for av in match.availabilities if av.response
                }
                team_players = {p.id for p in match.team.players} if match.team else set()
                target_players = list(team_players - responded_players)
            
            if not target_players:
                return False, "No players to remind"
            
            # Queue reminder task using the ECS FC specific task
            from app.tasks.tasks_rsvp_ecs import send_ecs_fc_rsvp_reminder
            send_ecs_fc_rsvp_reminder.delay(match_id, target_players)
            
            logger.info(f"Queued RSVP reminders for match {match_id}, {len(target_players)} players")
            return True, f"RSVP reminders queued for {len(target_players)} players"
            
        except Exception as e:
            logger.error(f"Error sending RSVP reminders for match {match_id}: {str(e)}")
            return False, f"Error sending reminders: {str(e)}"
    
    @staticmethod
    def _schedule_rsvp_reminder(match: EcsFcMatch):
        """
        Schedule automatic RSVP reminder for an ECS FC match.
        
        Args:
            match: The ECS FC match to schedule reminder for
        """
        try:
            from app.models import ScheduledMessage
            
            # Calculate when to send the reminder
            # Send on Monday at 9 AM before the match (same as pub league)
            match_datetime = datetime.combine(match.match_date, match.match_time)
            
            # Find the Monday before the match
            days_until_match = (match_datetime.date() - datetime.utcnow().date()).days
            if days_until_match > 7:
                # Find the Monday of the week before the match
                days_until_monday = (match_datetime.weekday() + 6) % 7
                if days_until_monday == 0:
                    days_until_monday = 7
                send_date = match_datetime.date() - timedelta(days=days_until_monday)
                send_time = datetime.combine(send_date, datetime.strptime("09:00", "%H:%M").time())
            else:
                # If match is within a week, send reminder tomorrow at 9 AM
                send_time = datetime.combine(
                    datetime.utcnow().date() + timedelta(days=1),
                    datetime.strptime("09:00", "%H:%M").time()
                )
            
            # Check if a scheduled message already exists for this match
            existing = g.db_session.query(ScheduledMessage).filter(
                ScheduledMessage.message_metadata.op('->>')('ecs_fc_match_id') == str(match.id)
            ).first()
            
            if existing:
                logger.info(f"Scheduled message already exists for ECS FC match {match.id}")
                return
            
            # Get team Discord channel info
            team = match.team
            if not team:
                logger.warning(f"No team found for ECS FC match {match.id}")
                return
            
            # Create scheduled message with ECS FC metadata
            scheduled_message = ScheduledMessage(
                scheduled_send_time=send_time,
                status='QUEUED',
                message_type='ecs_fc_rsvp',
                message_metadata={
                    'ecs_fc_match_id': match.id,
                    'team_id': team.id,
                    'team_name': team.name,
                    'opponent_name': match.opponent_name,
                    'match_date': match.match_date.isoformat(),
                    'match_time': match.match_time.strftime('%H:%M'),
                    'location': match.location
                },
                created_by=match.created_by
            )
            
            g.db_session.add(scheduled_message)
            g.db_session.commit()
            
            logger.info(f"Scheduled RSVP reminder for ECS FC match {match.id} at {send_time}")
            
        except Exception as e:
            logger.error(f"Error scheduling RSVP reminder for match {match.id}: {str(e)}")
            # Don't fail the match creation if scheduling fails
            g.db_session.rollback()
    
    @staticmethod
    def _send_match_notification(match: EcsFcMatch, action: str):
        """
        Send Discord notification for match events.
        
        Args:
            match: The ECS FC match
            action: Action type ('created', 'updated', 'cancelled')
        """
        try:
            if not match.team:
                return
            
            # Format match info
            match_info = f"{match.team.name} vs {match.opponent_name}"
            date_str = match.match_date.strftime("%B %d, %Y")
            time_str = match.match_time.strftime("%I:%M %p")
            location_str = match.location
            if match.field_name:
                location_str += f" ({match.field_name})"
            
            # Create message based on action
            if action == "created":
                title = "🆕 New Match Scheduled"
                description = f"A new match has been scheduled for {match_info}"
            elif action == "updated":
                title = "📝 Match Updated"
                description = f"Match details have been updated for {match_info}"
            elif action == "cancelled":
                title = "❌ Match Cancelled"
                description = f"The match for {match_info} has been cancelled"
            else:
                return
            
            # Create embed
            embed = {
                "title": title,
                "description": description,
                "color": 0x3498db if action != "cancelled" else 0xe74c3c,
                "fields": [
                    {"name": "Date", "value": date_str, "inline": True},
                    {"name": "Time", "value": time_str, "inline": True},
                    {"name": "Location", "value": location_str, "inline": False}
                ]
            }
            
            if action != "cancelled" and match.notes:
                embed["fields"].append({"name": "Notes", "value": match.notes, "inline": False})
            
            # For match creation notifications, we could use the DM system or team channel
            # For now, just log that a notification should be sent
            # This could be enhanced later to send a team channel notification
            logger.info(f"ECS FC match {action}: {description} for team {match.team_id}")
            
        except Exception as e:
            logger.error(f"Error sending match notification: {str(e)}")
    
    @staticmethod
    def bulk_import_matches(
        team_id: int,
        matches_data: List[Dict[str, Any]],
        created_by: int = None
    ) -> Tuple[bool, str, List[int]]:
        """
        Bulk import matches from a list of match data.
        
        Args:
            team_id: ID of the team
            matches_data: List of match dictionaries
            created_by: User ID who created the matches
            
        Returns:
            Tuple of (success, message, list_of_created_match_ids)
        """
        try:
            # Validate that this is an ECS FC team
            if not is_ecs_fc_team(team_id):
                return False, "This team is not an ECS FC team", []
            
            created_matches = []
            errors = []
            
            for i, match_data in enumerate(matches_data):
                try:
                    # Parse date and time
                    if isinstance(match_data.get('match_date'), str):
                        match_date = datetime.strptime(match_data['match_date'], '%Y-%m-%d').date()
                    else:
                        match_date = match_data['match_date']
                    
                    if isinstance(match_data.get('match_time'), str):
                        match_time = datetime.strptime(match_data['match_time'], '%H:%M').time()
                    else:
                        match_time = match_data['match_time']
                    
                    # Create match
                    success, message, match = EcsFcScheduleManager.create_match(
                        team_id=team_id,
                        opponent_name=match_data['opponent_name'],
                        match_date=match_date,
                        match_time=match_time,
                        location=match_data['location'],
                        field_name=match_data.get('field_name'),
                        is_home_match=match_data.get('is_home_match', True),
                        notes=match_data.get('notes'),
                        created_by=created_by
                    )
                    
                    if success and match:
                        created_matches.append(match.id)
                        # Note: _schedule_rsvp_reminder is already called in create_match
                    else:
                        errors.append(f"Row {i+1}: {message}")
                        
                except Exception as e:
                    errors.append(f"Row {i+1}: {str(e)}")
            
            success_count = len(created_matches)
            error_count = len(errors)
            
            if success_count > 0 and error_count == 0:
                return True, f"Successfully imported {success_count} matches", created_matches
            elif success_count > 0 and error_count > 0:
                return True, f"Imported {success_count} matches with {error_count} errors: {'; '.join(errors)}", created_matches
            else:
                return False, f"Failed to import matches: {'; '.join(errors)}", []
                
        except Exception as e:
            logger.error(f"Error bulk importing matches: {str(e)}")
            return False, f"Error importing matches: {str(e)}", []


# Utility functions
def get_ecs_fc_team_ids() -> List[int]:
    """Get all ECS FC team IDs."""
    try:
        teams = g.db_session.query(Team).join(League).filter(
            League.name == 'ECS FC'
        ).all()
        return [team.id for team in teams]
    except Exception as e:
        logger.error(f"Error getting ECS FC team IDs: {str(e)}")
        return []


def is_user_ecs_fc_coach(user_id: int) -> List[int]:
    """
    Check if user is a coach of any ECS FC teams.
    
    Args:
        user_id: User ID to check
        
    Returns:
        List of team IDs the user coaches (empty if none)
    """
    try:
        user = g.db_session.query(User).filter(User.id == user_id).first()
        if not user:
            return []
        
        # Get user's player record
        if not user.player:
            return []
        
        ecs_fc_team_ids = get_ecs_fc_team_ids()
        coached_teams = []
        
        # Query player_teams table to find teams where user's player is a coach
        from app.models import player_teams
        coached_ecs_fc_teams = g.db_session.query(player_teams.c.team_id).filter(
            player_teams.c.player_id == user.player.id,
            player_teams.c.is_coach == True,
            player_teams.c.team_id.in_(ecs_fc_team_ids)
        ).all()
        
        coached_teams = [team_id for (team_id,) in coached_ecs_fc_teams]
        
        return coached_teams
        
    except Exception as e:
        logger.error(f"Error checking if user {user_id} is ECS FC coach: {str(e)}")
        return []


def get_upcoming_ecs_fc_matches(team_id: int = None, days_ahead: int = 7) -> List[EcsFcMatch]:
    """
    Get upcoming ECS FC matches.
    
    Args:
        team_id: Specific team ID (optional)
        days_ahead: Number of days ahead to look
        
    Returns:
        List of upcoming matches
    """
    try:
        end_date = datetime.now().date() + timedelta(days=days_ahead)
        
        query = g.db_session.query(EcsFcMatch).filter(
            EcsFcMatch.match_date >= datetime.now().date(),
            EcsFcMatch.match_date <= end_date
        )
        
        if team_id:
            query = query.filter(EcsFcMatch.team_id == team_id)
        
        return query.order_by(EcsFcMatch.match_date.asc(), EcsFcMatch.match_time.asc()).all()
        
    except Exception as e:
        logger.error(f"Error getting upcoming ECS FC matches: {str(e)}")
        return []