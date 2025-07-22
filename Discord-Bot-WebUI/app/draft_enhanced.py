# app/draft_enhanced.py

"""
Enhanced Draft System

A modern, scalable draft system with comprehensive player information,
real-time updates, and improved user experience. Consolidates all league
drafts into a single, maintainable system with advanced features.
"""

import logging
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta

from flask import Blueprint, render_template, redirect, url_for, g, jsonify, request
from flask_login import login_required, current_user
from flask_socketio import emit, join_room, leave_room, rooms
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.sql import exists, and_, or_, func
from sqlalchemy import text, desc

from app.core import socketio, db
from app.decorators import role_required
from app.alert_helpers import show_success, show_error, show_warning, show_info
from app.db_utils import mark_player_for_discord_update
from app.models import (
    League, Player, Team, Season, PlayerSeasonStats, PlayerCareerStats,
    Match, PlayerEvent, player_teams, player_league, Availability,
    PlayerTeamHistory, Schedule, PlayerAttendanceStats, PlayerImageCache,
    DraftOrderHistory
)
from app.attendance_service import AttendanceService
from app.image_cache_service import ImageCacheService
from app.draft_cache_service import DraftCacheService
from app.sockets.session import socket_session
from app.tasks.tasks_discord import assign_roles_to_player_task, remove_player_roles_task

logger = logging.getLogger(__name__)
draft_enhanced = Blueprint('draft_enhanced', __name__, url_prefix='/draft')


# Template filter for formatting position names
@draft_enhanced.app_template_filter('format_position')
def format_position(position):
    """Format position names for display."""
    if not position:
        return position
    return position.replace('_', ' ').title()


class DraftService:
    """Service class for draft operations with enhanced functionality."""
    
    @staticmethod
    def get_league_data(league_name: str) -> Tuple[Optional[League], List[League]]:
        """Get current league and all leagues with the given name."""
        session = g.db_session
        
        all_leagues = session.query(League).filter(League.name == league_name).all()
        current_league = (
            session.query(League)
            .join(League.season)
            .filter(League.name == league_name)
            .filter_by(is_current=True)
            .one_or_none()
        )
        
        return current_league, all_leagues
    
    @staticmethod
    def record_draft_pick(session, player_id: int, team_id: int, league_id: int, season_id: int, drafted_by_user_id: int, notes: str = None) -> int:
        """Record a draft pick in the draft order history table."""
        try:
            # Get the next draft position for this season/league
            max_position = session.query(func.max(DraftOrderHistory.draft_position)).filter(
                DraftOrderHistory.season_id == season_id,
                DraftOrderHistory.league_id == league_id
            ).scalar() or 0
            
            next_position = max_position + 1
            
            # Create the draft order record
            draft_record = DraftOrderHistory(
                season_id=season_id,
                league_id=league_id,
                player_id=player_id,
                team_id=team_id,
                draft_position=next_position,
                drafted_by=drafted_by_user_id,
                notes=notes
            )
            
            session.add(draft_record)
            session.flush()  # Flush to get the ID but don't commit yet
            
            logger.info(f"Recorded draft pick #{next_position}: Player {player_id} to Team {team_id} in Season {season_id}/League {league_id}")
            
            return next_position
            
        except Exception as e:
            logger.error(f"Error recording draft pick: {str(e)}")
            raise
    
    @staticmethod
    def remove_draft_pick(session, player_id: int, season_id: int, league_id: int):
        """Remove a player from draft history and adjust subsequent picks."""
        try:
            # Find the draft record for this player
            draft_record = session.query(DraftOrderHistory).filter(
                DraftOrderHistory.player_id == player_id,
                DraftOrderHistory.season_id == season_id,
                DraftOrderHistory.league_id == league_id
            ).first()
            
            if not draft_record:
                logger.warning(f"No draft record found for player {player_id}")
                return
            
            removed_position = draft_record.draft_position
            
            # Get all subsequent picks before deleting the record
            subsequent_picks = session.query(DraftOrderHistory).filter(
                DraftOrderHistory.season_id == season_id,
                DraftOrderHistory.league_id == league_id,
                DraftOrderHistory.draft_position > removed_position
            ).order_by(DraftOrderHistory.draft_position).all()
            
            # Delete the record first
            session.delete(draft_record)
            session.flush()  # Ensure deletion is processed before updates
            
            # Adjust subsequent draft positions down by 1
            # Use bulk update with a single query to avoid constraint violations
            if subsequent_picks:
                # Update all positions at once using raw SQL to avoid constraint conflicts
                session.execute(
                    """
                    UPDATE draft_order_history 
                    SET draft_position = draft_position - 1, updated_at = NOW()
                    WHERE season_id = :season_id 
                    AND league_id = :league_id 
                    AND draft_position > :removed_position
                    """,
                    {
                        'season_id': season_id,
                        'league_id': league_id,
                        'removed_position': removed_position
                    }
                )
            
            logger.info(f"Removed draft pick #{removed_position} for player {player_id} and adjusted {len(subsequent_picks)} subsequent picks")
            
        except Exception as e:
            logger.error(f"Error removing draft pick: {str(e)}")
            raise
    
    @staticmethod
    def swap_draft_positions(session, pick_id: int, new_position: int) -> Dict[str, Any]:
        """
        Swap a draft pick to a new position and automatically adjust all affected picks.
        
        For example, if pick #105 is moved to #100:
        - Pick at #100 moves to #101
        - Pick at #101 moves to #102
        - ... and so on until #104 moves to #105
        
        Args:
            session: Database session
            pick_id: ID of the draft pick to move
            new_position: New position number to move to
            
        Returns:
            Dict containing success status and affected picks information
        """
        try:
            # Get the pick to be moved with eager loading
            pick_to_move = session.query(DraftOrderHistory).options(
                joinedload(DraftOrderHistory.player)
            ).filter_by(id=pick_id).first()
            
            if not pick_to_move:
                return {'success': False, 'message': 'Draft pick not found'}
            
            old_position = pick_to_move.draft_position
            season_id = pick_to_move.season_id
            league_id = pick_to_move.league_id
            player_name = pick_to_move.player.name
            
            # If positions are the same, no action needed
            if old_position == new_position:
                return {'success': True, 'message': 'No position change needed', 'affected_picks': 0}
            
            # Get max position to validate the new position
            max_position = session.query(func.max(DraftOrderHistory.draft_position)).filter(
                DraftOrderHistory.season_id == season_id,
                DraftOrderHistory.league_id == league_id
            ).scalar() or 0
            
            # Validate new position is within valid range
            if new_position < 1 or new_position > max_position:
                return {'success': False, 'message': f'Position must be between 1 and {max_position}'}
            
            # Use a temporary position to avoid unique constraint violations
            # Find a safe temporary position outside the current range
            temp_position = max_position + 1000
            
            # Move the pick to temporary position first
            pick_to_move.draft_position = temp_position
            pick_to_move.updated_at = datetime.utcnow()
            session.flush()  # Flush to avoid constraint issues
            
            # Determine the range of picks that need to be adjusted
            if old_position > new_position:
                # Moving up (e.g., from #105 to #100)
                # All picks from new_position to old_position-1 need to shift down by 1
                affected_picks = session.query(DraftOrderHistory).filter(
                    DraftOrderHistory.season_id == season_id,
                    DraftOrderHistory.league_id == league_id,
                    DraftOrderHistory.draft_position >= new_position,
                    DraftOrderHistory.draft_position < old_position
                ).order_by(desc(DraftOrderHistory.draft_position)).all()
                
                # Shift affected picks down (start from highest position to avoid conflicts)
                for pick in affected_picks:
                    pick.draft_position += 1
                    pick.updated_at = datetime.utcnow()
                    session.flush()  # Flush after each update to avoid constraint violations
                    
            else:
                # Moving down (e.g., from #100 to #105)
                # All picks from old_position+1 to new_position need to shift up by 1
                affected_picks = session.query(DraftOrderHistory).filter(
                    DraftOrderHistory.season_id == season_id,
                    DraftOrderHistory.league_id == league_id,
                    DraftOrderHistory.draft_position > old_position,
                    DraftOrderHistory.draft_position <= new_position
                ).order_by(DraftOrderHistory.draft_position).all()
                
                # Shift affected picks up (start from lowest position to avoid conflicts)
                for pick in affected_picks:
                    pick.draft_position -= 1
                    pick.updated_at = datetime.utcnow()
                    session.flush()  # Flush after each update to avoid constraint violations
            
            # Now move the pick to its final position
            pick_to_move.draft_position = new_position
            pick_to_move.updated_at = datetime.utcnow()
            
            # Log the swap
            logger.info(
                f"Swapped draft pick #{old_position} ({player_name}) "
                f"to position #{new_position}, affected {len(affected_picks)} other picks"
            )
            
            return {
                'success': True,
                'message': f'Successfully moved pick from #{old_position} to #{new_position}',
                'affected_picks': len(affected_picks),
                'old_position': old_position,
                'new_position': new_position,
                'player_name': player_name
            }
            
        except Exception as e:
            logger.error(f"Error swapping draft positions: {str(e)}")
            raise
    
    @staticmethod
    def set_absolute_draft_position(session, pick_id, new_position):
        """Set absolute draft position without cascading shifts to other picks."""
        try:
            pick_to_move = session.query(DraftOrderHistory).get(pick_id)
            if not pick_to_move:
                return {'success': False, 'message': 'Draft pick not found'}
            
            season_id = pick_to_move.season_id
            league_id = pick_to_move.league_id
            old_position = pick_to_move.draft_position
            player_name = pick_to_move.player.full_name if pick_to_move.player else 'Unknown Player'
            
            if old_position == new_position:
                return {'success': True, 'message': 'No position change needed'}
            
            # Get max position to validate the new position
            max_position = session.query(func.max(DraftOrderHistory.draft_position)).filter(
                DraftOrderHistory.season_id == season_id,
                DraftOrderHistory.league_id == league_id
            ).scalar() or 0
            
            # Validate new position is within valid range
            if new_position < 1 or new_position > max_position:
                return {'success': False, 'message': f'Position must be between 1 and {max_position}'}
            
            # Use a temporary position to avoid conflicts
            temp_position = max_position + 1000
            
            # Move the pick to temporary position first
            pick_to_move.draft_position = temp_position
            pick_to_move.updated_at = datetime.utcnow()
            session.flush()
            
            # Check if the desired position is occupied
            existing_pick = session.query(DraftOrderHistory).filter(
                DraftOrderHistory.season_id == season_id,
                DraftOrderHistory.league_id == league_id,
                DraftOrderHistory.draft_position == new_position
            ).first()
            
            if existing_pick:
                # Move the existing pick to the old position
                existing_pick.draft_position = old_position
                existing_pick.updated_at = datetime.utcnow()
                session.flush()
            
            # Now move the pick to its final position
            pick_to_move.draft_position = new_position
            pick_to_move.updated_at = datetime.utcnow()
            
            logger.info(f"Set absolute position: {player_name} moved from #{old_position} to #{new_position}")
            
            return {
                'success': True,
                'message': f'Successfully set {player_name} to position #{new_position}',
                'old_position': old_position,
                'new_position': new_position,
                'player_name': player_name,
                'swapped_with': existing_pick.player.full_name if existing_pick and existing_pick.player else None
            }
            
        except Exception as e:
            logger.error(f"Error setting absolute draft position: {str(e)}")
            raise

    @staticmethod
    def get_enhanced_player_data(players: List[Player], current_season_id: Optional[int] = None) -> List[Dict]:
        """Get enhanced player data with comprehensive stats and profile info - OPTIMIZED."""
        if not players:
            return []
        
        player_ids = [p.id for p in players]
        start_time = datetime.now()
        logger.debug(f"Processing {len(player_ids)} players for enhanced data")
        
        # Batch load all supporting data - removed parallel execution due to Flask context issues
        attendance_start = datetime.now()
        attendance_data = AttendanceService.get_attendance_stats(player_ids)
        logger.debug(f"Attendance data loaded in {(datetime.now() - attendance_start).total_seconds():.2f}s")
        
        history_start = datetime.now()
        team_history_data = DraftService._batch_load_team_history(player_ids)
        logger.debug(f"Team history loaded in {(datetime.now() - history_start).total_seconds():.2f}s")
        
        image_start = datetime.now()
        image_data = ImageCacheService.get_player_image_data(player_ids)
        logger.debug(f"Image data loaded in {(datetime.now() - image_start).total_seconds():.2f}s")
        
        # Log performance for debugging (reduced verbosity)
        if len(player_ids) <= 5:
            for pid, data in image_data.items():
                logger.debug(f"Player {pid} image optimized: {data.get('is_optimized', False)}")
        else:
            logger.debug(f"Image data loaded for {len(image_data)} players")
        
        # Build enhanced player data using optimized approach
        enhanced_players = []
        
        # Pre-calculate season stats lookup if needed
        season_stats_lookup = {}
        if current_season_id:
            for player in players:
                season_stats_lookup[player.id] = next(
                    (s for s in player.season_stats if s.season_id == current_season_id),
                    None
                )
        
        # Process players in optimized batch
        for player in players:
            # Get cached data
            player_stats = attendance_data.get(player.id, {})
            teams_played_on = team_history_data.get(player.id, 0)
            player_images = image_data.get(player.id, {})
            season_stats = season_stats_lookup.get(player.id) if current_season_id else None
            
            # Build image URLs efficiently
            original_url = player.profile_picture_url or '/static/img/default_player.png'
            thumbnail_url = player_images.get('thumbnail_url', original_url)
            
            enhanced_data = {
                'id': player.id,
                'name': player.name,
                'profile_picture_url': thumbnail_url,
                'profile_picture_medium': player_images.get('medium_url', original_url),
                'profile_picture_webp': player_images.get('webp_url', original_url),
                'image_optimized': player_images.get('is_optimized', False),
                'player_notes': player.player_notes or '',
                'favorite_position': player.favorite_position or 'Any',
                'other_positions': player.other_positions or '',
                'expected_weeks_available': player.expected_weeks_available,
                'unavailable_dates': player.unavailable_dates or '',
                'jersey_number': player.jersey_number,
                'is_sub': player.is_sub,
                'is_ref': player.is_ref,
                'willing_to_referee': player.willing_to_referee == 'Yes',
                
                # Career stats with safe access
                'career_goals': player.career_stats[0].goals if player.career_stats else 0,
                'career_assists': player.career_stats[0].assists if player.career_stats else 0,
                'career_yellow_cards': player.career_stats[0].yellow_cards if player.career_stats else 0,
                'career_red_cards': player.career_stats[0].red_cards if player.career_stats else 0,
                
                # Average stats per season
                'avg_goals_per_season': (
                    round(player.career_stats[0].goals / max(teams_played_on, 1), 1) 
                    if player.career_stats and teams_played_on > 0 else 0
                ),
                'avg_assists_per_season': (
                    round(player.career_stats[0].assists / max(teams_played_on, 1), 1) 
                    if player.career_stats and teams_played_on > 0 else 0
                ),
                
                # Season stats
                'season_goals': season_stats.goals if season_stats else 0,
                'season_assists': season_stats.assists if season_stats else 0,
                'season_yellow_cards': season_stats.yellow_cards if season_stats else 0,
                'season_red_cards': season_stats.red_cards if season_stats else 0,
                
                # League experience
                'league_experience_seasons': teams_played_on,
                'experience_level': 'Veteran' if teams_played_on >= 3 else 'Experienced' if teams_played_on >= 1 else 'New Player',
                
                # Team info - optimized list comprehension
                'current_teams': [{'id': t.id, 'name': t.name} for t in player.teams],
                'primary_team_id': player.primary_team_id,
                
                # Attendance metrics - preserve None for no historical data
                'rsvp_response_rate': player_stats.get('response_rate', None),
                'attendance_estimate': player_stats.get('adjusted_attendance_rate', None),  # None indicates no historical data
                'total_matches_invited': player_stats.get('total_matches_invited', 0),
                'reliability_score': player_stats.get('reliability_score', None),  # None indicates no historical data
                'has_attendance_data': bool(player_stats)  # Flag to indicate if player has any attendance history
            }
            
            enhanced_players.append(enhanced_data)
        
        total_time = (datetime.now() - start_time).total_seconds()
        logger.debug(f"Enhanced player data processing completed in {total_time:.2f}s for {len(enhanced_players)} players")
        
        return enhanced_players
    
    @staticmethod
    def _batch_load_attendance(player_ids: List[int], season_id: Optional[int] = None) -> Dict[int, Dict]:
        """Fast batch load of cached attendance data using AttendanceService."""
        try:
            # Use the cached attendance service for lightning-fast lookups
            attendance_data = AttendanceService.get_attendance_stats(player_ids)
            
            # Convert to the format expected by the rest of the draft system
            result = {}
            for player_id, stats in attendance_data.items():
                result[player_id] = {
                    'response_rate': stats['response_rate'],
                    'attendance_estimate': stats['adjusted_attendance_rate'],  # Use adjusted rate
                    'reliability_score': stats['reliability_score'],
                    'total_invited': stats['total_matches_invited'],
                    # These aren't available in cached stats but kept for compatibility
                    'yes_count': 0,  # Could be added to stats table if needed
                    'no_count': 0,
                    'maybe_count': 0,
                    'pending_count': 0
                }
            
            return result
            
        except Exception as e:
            logger.warning(f"Error loading cached attendance data, using defaults: {e}")
            # Fallback to default values if service fails
            return {player_id: {
                'response_rate': 0,
                'attendance_estimate': None,
                'reliability_score': 25,
                'total_invited': 0,
                'yes_count': 0,
                'no_count': 0,
                'maybe_count': 0,
                'pending_count': 0
            } for player_id in player_ids}
    
    @staticmethod
    def _batch_load_team_history(player_ids: List[int]) -> Dict[int, int]:
        """Batch load team history counts for league experience using PlayerTeamSeason records."""
        from app.models import PlayerTeamSeason, player_teams
        session = g.db_session
        
        try:
            # Count unique team-season combinations from PlayerTeamSeason
            # This gives us the actual seasons a player has played
            season_counts = (
                session.query(
                    PlayerTeamSeason.player_id,
                    func.count(func.distinct(PlayerTeamSeason.team_id)).label('teams_count')
                )
                .filter(PlayerTeamSeason.player_id.in_(player_ids))
                .group_by(PlayerTeamSeason.player_id)
                .all()
            )
            
            result = {record.player_id: record.teams_count for record in season_counts}
            
            # Also check current team assignments for players who might not have PlayerTeamSeason records yet
            try:
                current_team_counts = (
                    session.query(
                        player_teams.c.player_id,
                        func.count(func.distinct(player_teams.c.team_id)).label('teams_count')
                    )
                    .filter(player_teams.c.player_id.in_(player_ids))
                    .group_by(player_teams.c.player_id)
                    .all()
                )
                
                # For players without PlayerTeamSeason records, use current team count
                for record in current_team_counts:
                    player_id = record.player_id
                    if player_id not in result:
                        result[player_id] = record.teams_count
                    
            except Exception as e:
                logger.debug(f"Error querying current teams: {e}")
            
        except Exception as e:
            logger.warning(f"Error loading team history: {e}")
            result = {}
        
        # Add default 0 for players with no history
        for player_id in player_ids:
            if player_id not in result:
                result[player_id] = 0
        
        logger.debug(f"Team history counts for players {player_ids[:5]}{'...' if len(player_ids) > 5 else ''}: {[(pid, result.get(pid, 0)) for pid in player_ids[:5]]}")
        
        return result
    
    @staticmethod
    def _calculate_league_experience(player: Player, current_season_id: Optional[int] = None) -> Dict:
        """Calculate player's experience within this specific league/division."""
        from app.models import PlayerTeamHistory, Team, League
        
        session = g.db_session
        
        # Get the current league for context
        current_league = None
        if current_season_id:
            current_league = session.query(League).join(League.season).filter_by(id=current_season_id).first()
        
        league_name = current_league.name if current_league else None
        
        # Count seasons played in this league
        seasons_played = 0
        total_matches = 0
        
        if league_name:
            # Get all team histories for teams in this league
            # Each team history entry = one season, since teams are recreated each season
            team_histories = (
                session.query(PlayerTeamHistory)
                .join(Team)
                .join(League)
                .filter(PlayerTeamHistory.player_id == player.id)
                .filter(League.name == league_name)
                .all()
            )
            
            seasons_played = len(team_histories)  # Each team = one season
            
            # Count total matches by counting PlayerEvents in this league
            from app.models import PlayerEvent, Match, Schedule
            match_events = (
                session.query(PlayerEvent)
                .join(Match)
                .join(Schedule)
                .join(League, Schedule.season_id == League.season_id)
                .filter(PlayerEvent.player_id == player.id)
                .filter(League.name == league_name)
                .all()
            )
            
            total_matches = len(set(event.match_id for event in match_events))
        
        return {
            'seasons': seasons_played,
            'total_matches': total_matches,
            'league_name': league_name,
            'experience_level': 'Veteran' if seasons_played >= 3 else 'Experienced' if seasons_played >= 1 else 'First Season'
        }
    
    
    @staticmethod
    def get_draft_analytics(league_name: str) -> Dict:
        """Get draft analytics for the league with caching."""
        # Try cache first
        cached_analytics = DraftCacheService.get_draft_analytics_cache(league_name)
        if cached_analytics:
            logger.debug(f"Using cached analytics for {league_name}")
            return cached_analytics
        
        current_league, _ = DraftService.get_league_data(league_name)
        if not current_league:
            return {}
        
        session = g.db_session
        teams = current_league.teams
        current_league_name = current_league.name
        
        analytics = {
            'total_teams': len(teams),
            'total_players_drafted': 0,
            'avg_players_per_team': 0,
            'teams_summary': [],
            'position_distribution': {},
            'draft_progress': 0
        }
        
        total_drafted = 0
        position_counts = {}
        
        for team in teams:
            team_players = [p for p in team.players if p.is_current_player]
            team_count = len(team_players)
            total_drafted += team_count
            
            # Count positions
            for player in team_players:
                pos = getattr(player, 'favorite_position', 'Unknown')
                position_counts[pos] = position_counts.get(pos, 0) + 1
            
            # Calculate average experience level for team
            avg_experience = 0
            if team_players:
                total_experience = 0
                for player in team_players:
                    # Get player's team history count as experience indicator
                    team_history_count = len([th for th in player.team_history if th.team.league.name == current_league_name]) if hasattr(player, 'team_history') else 0
                    total_experience += team_history_count
                avg_experience = total_experience / team_count
            
            analytics['teams_summary'].append({
                'team_id': team.id,
                'team_name': team.name,
                'player_count': team_count,
                'avg_experience_level': avg_experience
            })
        
        analytics['total_players_drafted'] = total_drafted
        analytics['avg_players_per_team'] = total_drafted / max(len(teams), 1)
        analytics['position_distribution'] = position_counts
        analytics['draft_progress'] = min(100, (total_drafted / (len(teams) * 15)) * 100)  # Assuming 15 players per team target
        
        # Cache the analytics before returning
        DraftCacheService.set_draft_analytics_cache(league_name, analytics)
        
        return analytics


@draft_enhanced.route('/<league_name>')
@login_required
@role_required(['Pub League Admin', 'Global Admin', 'Pub League Coach'])
def draft_league(league_name: str):
    """Enhanced draft page for any league."""
    print(f"🔴 DRAFT_ENHANCED ROUTE HIT: {league_name}")
    logger.info(f"🔴 Enhanced draft route accessed: {league_name}")
    
    # Validate league name
    valid_leagues = ['classic', 'premier', 'ecs_fc']
    if league_name.lower() not in valid_leagues:
        show_error(f'Invalid league name: {league_name}')
        return redirect(url_for('main.index'))
    
    # Normalize league name for database lookup
    db_league_name = {
        'classic': 'Classic',
        'premier': 'Premier', 
        'ecs_fc': 'ECS FC'
    }.get(league_name.lower())
    
    current_league, all_leagues = DraftService.get_league_data(db_league_name)
    
    if not current_league:
        show_error(f'No current {db_league_name} league found.')
        return redirect(url_for('main.index'))
    
    if not all_leagues:
        show_error(f'No {db_league_name} leagues found.')
        return redirect(url_for('main.index'))
    
    # Get teams (excluding Practice teams)
    teams = [team for team in current_league.teams if team.name != "Practice"]
    team_ids = [t.id for t in teams]
    
    # Get all players eligible for this league
    league_ids = [l.id for l in all_leagues]
    belongs_to_league = or_(
        Player.primary_league_id.in_(league_ids),
        exists().where(
            and_(
                player_league.c.player_id == Player.id,
                player_league.c.league_id.in_(league_ids)
            )
        )
    )
    
    # OPTIMIZED: Single query approach with conditional filtering
    # Get all eligible players in one query with optimized loading
    all_players_query = (
        g.db_session.query(Player)
        .filter(belongs_to_league)
        .filter(Player.is_current_player.is_(True))
        .options(
            joinedload(Player.career_stats),
            joinedload(Player.season_stats),
            selectinload(Player.teams),
            # Pre-load attendance and image relationships if they exist
            # joinedload(Player.attendance_stats),  # Uncomment if relationship exists
            # joinedload(Player.image_cache)        # Uncomment if relationship exists
        )
        .order_by(Player.name.asc())
    ).all()
    
    logger.debug(f"Loaded {len(all_players_query)} total players for processing")
    
    # Separate players into available/drafted using Python filtering (faster than DB queries)
    available_players_raw = []
    drafted_players_raw = []
    
    # Build team lookup for faster filtering
    team_ids_set = set(team_ids)
    
    for player in all_players_query:
        player_team_ids = {team.id for team in player.teams}
        if player_team_ids.intersection(team_ids_set):
            drafted_players_raw.append(player)
        else:
            available_players_raw.append(player)
    
    logger.debug(f"Separated into {len(available_players_raw)} available and {len(drafted_players_raw)} drafted players")
    
    # Try to get cached data first
    cache_key_available = f"{db_league_name}_available"
    cache_key_drafted = f"{db_league_name}_drafted"
    
    available_players = DraftCacheService.get_enhanced_players_cache(db_league_name, 'available')
    drafted_players = DraftCacheService.get_enhanced_players_cache(db_league_name, 'drafted')
    
    # If cache miss, process data and cache results
    if available_players is None or drafted_players is None:
        logger.debug(f"Cache miss for {db_league_name} - processing enhanced data")
        
        # Process enhanced data sequentially (parallel execution removed due to Flask context issues)
        if available_players is None:
            available_players = DraftService.get_enhanced_player_data(
                available_players_raw,
                current_league.season_id
            )
            DraftCacheService.set_enhanced_players_cache(db_league_name, 'available', available_players)
        
        if drafted_players is None:
            drafted_players = DraftService.get_enhanced_player_data(
                drafted_players_raw,
                current_league.season_id
            )
            DraftCacheService.set_enhanced_players_cache(db_league_name, 'drafted', drafted_players)
    else:
        logger.debug(f"Using cached player data for {db_league_name}")
    
    # Organize drafted players by team
    drafted_by_team = {team.id: [] for team in teams}
    logger.debug(f"Available teams for drafting: {[team.id for team in teams]}")
    
    for player in drafted_players:
        logger.debug(f"Player {player['name']} current teams: {player['current_teams']}")
        for team_info in player['current_teams']:
            team_id = team_info['id']
            if team_id in drafted_by_team:
                drafted_by_team[team_id].append(player)
                logger.debug(f"Added player {player['name']} to team {team_id}")
                break
    
    logger.debug(f"Final drafted_by_team counts: {[(team_id, len(players)) for team_id, players in drafted_by_team.items()]}")
    
    # Get draft analytics
    analytics = DraftService.get_draft_analytics(db_league_name)
    
    return render_template(
        'draft_enhanced.html',
        title=f'{db_league_name} League Draft',
        league_name=league_name,
        db_league_name=db_league_name,
        teams=teams,
        available_players=available_players,
        drafted_players_by_team=drafted_by_team,
        analytics=analytics,
        current_season_id=current_league.season_id
    )


@draft_enhanced.route('/<league_name>/pitch')
@login_required
@role_required(['Pub League Admin', 'Global Admin', 'Pub League Coach'])
def draft_league_pitch_view(league_name: str):
    """Soccer pitch view for visual team drafting."""
    logger.info(f"🏟️ Pitch view route accessed: {league_name}")
    
    # Validate league name
    valid_leagues = ['classic', 'premier', 'ecs_fc']
    if league_name.lower() not in valid_leagues:
        show_error(f'Invalid league name: {league_name}')
        return redirect(url_for('main.index'))
    
    # Normalize league name for database lookup
    db_league_name = {
        'classic': 'Classic',
        'premier': 'Premier', 
        'ecs_fc': 'ECS FC'
    }.get(league_name.lower())
    
    current_league, all_leagues = DraftService.get_league_data(db_league_name)
    
    if not current_league:
        show_error(f'No current {db_league_name} league found.')
        return redirect(url_for('main.index'))
    
    if not all_leagues:
        show_error(f'No {db_league_name} leagues found.')
        return redirect(url_for('main.index'))
    
    # Get teams (excluding Practice teams)
    teams = [team for team in current_league.teams if team.name != "Practice"]
    team_ids = [t.id for t in teams]
    
    # Get all players eligible for this league
    league_ids = [l.id for l in all_leagues]
    belongs_to_league = or_(
        Player.primary_league_id.in_(league_ids),
        exists().where(
            and_(
                player_league.c.player_id == Player.id,
                player_league.c.league_id.in_(league_ids)
            )
        )
    )
    
    # Get all eligible players
    all_players_query = (
        g.db_session.query(Player)
        .filter(belongs_to_league)
        .filter(Player.is_current_player.is_(True))
        .options(
            joinedload(Player.career_stats),
            joinedload(Player.season_stats),
            selectinload(Player.teams)
        )
        .order_by(Player.name.asc())
    ).all()
    
    # Separate players into available/drafted
    available_players_raw = []
    drafted_players_raw = []
    
    team_ids_set = set(team_ids)
    
    for player in all_players_query:
        player_team_ids = {team.id for team in player.teams}
        if player_team_ids.intersection(team_ids_set):
            drafted_players_raw.append(player)
        else:
            available_players_raw.append(player)
    
    # Process enhanced player data
    available_players = DraftService.get_enhanced_player_data(
        available_players_raw,
        current_league.season_id
    )
    
    drafted_players = DraftService.get_enhanced_player_data(
        drafted_players_raw,
        current_league.season_id
    )
    
    # Organize drafted players by team with positions
    drafted_by_team = {team.id: [] for team in teams}
    
    for player in drafted_players:
        for team_info in player['current_teams']:
            team_id = team_info['id']
            if team_id in drafted_by_team:
                # Get the player's position from player_teams table
                try:
                    position_result = g.db_session.execute(text("""
                        SELECT position FROM player_teams 
                        WHERE player_id = :player_id AND team_id = :team_id
                    """), {'player_id': player['id'], 'team_id': team_id}).fetchone()
                    
                    position = position_result[0] if position_result else 'bench'
                except:
                    position = 'bench'  # Default if query fails
                
                # Add position to player data
                player['current_position'] = position
                drafted_by_team[team_id].append(player)
                break
    
    # Convert teams to JSON-serializable format
    teams_json = [{'id': team.id, 'name': team.name} for team in teams]
    
    return render_template(
        'draft_pitch_view.html',
        title=f'{db_league_name} League Draft',
        league_name=league_name,
        db_league_name=db_league_name,
        teams=teams,
        teams_json=teams_json,
        available_players=available_players,
        drafted_players_by_team=drafted_by_team,
        current_season_id=current_league.season_id
    )


@draft_enhanced.route('/api/status')
@login_required
def draft_status():
    """Check draft system status."""
    return jsonify({
        'status': 'ok',
        'user': current_user.username if current_user.is_authenticated else None,
        'timestamp': datetime.now().isoformat()
    })


@draft_enhanced.route('/api/<league_name>/players')
@login_required
@role_required(['Pub League Admin', 'Global Admin', 'Pub League Coach'])
def get_players_api(league_name: str):
    """API endpoint for getting player data with filtering and sorting."""
    # Validate league name
    db_league_name = {
        'classic': 'Classic',
        'premier': 'Premier',
        'ecs_fc': 'ECS FC'
    }.get(league_name.lower())
    
    if not db_league_name:
        return jsonify({'error': 'Invalid league name'}), 400
    
    # Get query parameters
    search = request.args.get('search', '').strip()
    position = request.args.get('position', '').strip()
    sort_by = request.args.get('sort_by', 'name')
    sort_order = request.args.get('sort_order', 'asc')
    status = request.args.get('status', 'available')  # available, drafted, all
    
    current_league, all_leagues = DraftService.get_league_data(db_league_name)
    if not current_league:
        return jsonify({'error': 'League not found'}), 404
    
    # Build query based on status
    if status == 'available':
        # Available players
        team_ids = [t.id for t in current_league.teams if t.name != "Practice"]
        not_in_teams = ~exists().where(
            and_(
                player_teams.c.player_id == Player.id,
                player_teams.c.team_id.in_(team_ids)
            )
        )
        query = (
            g.db_session.query(Player)
            .filter(Player.is_current_player.is_(True))
            .filter(not_in_teams)
        )
    elif status == 'drafted':
        # Drafted players
        team_ids = [t.id for t in current_league.teams if t.name != "Practice"]
        query = (
            g.db_session.query(Player)
            .join(player_teams, player_teams.c.player_id == Player.id)
            .filter(player_teams.c.team_id.in_(team_ids))
            .filter(Player.is_current_player.is_(True))
        )
    else:
        # All players
        query = (
            g.db_session.query(Player)
            .filter(Player.is_current_player.is_(True))
        )
    
    # Apply filters
    if search:
        query = query.filter(Player.name.ilike(f'%{search}%'))
    
    if position:
        # This would need a position field in Player model
        # query = query.filter(Player.favorite_position.ilike(f'%{position}%'))
        pass
    
    # Apply sorting
    if sort_by == 'name':
        query = query.order_by(Player.name.asc() if sort_order == 'asc' else Player.name.desc())
    elif sort_by == 'goals':
        # This would need custom sorting logic
        pass
    
    query = query.options(
        joinedload(Player.career_stats),
        joinedload(Player.season_stats),
        selectinload(Player.teams)
    )
    
    players = DraftService.get_enhanced_player_data(
        query.all(),
        current_league.season_id
    )
    
    return jsonify({
        'players': players,
        'total': len(players),
        'status': status,
        'filters': {
            'search': search,
            'position': position,
            'sort_by': sort_by,
            'sort_order': sort_order
        }
    })


@draft_enhanced.route('/api/draft-player', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin', 'Pub League Coach'])
def api_draft_player():
    """HTTP API endpoint for drafting players (fallback when sockets fail)."""
    try:
        data = request.get_json()
        player_id = data.get('player_id')
        team_id = data.get('team_id')
        league_name = data.get('league_name')
        
        if not all([player_id, team_id, league_name]):
            return jsonify({'error': 'Missing required data'}), 400
        
        session = g.db_session
        
        # Get the league and validate
        league = session.query(League).filter(
            League.name == league_name,
            League.is_active == True
        ).first()
        
        if not league:
            return jsonify({'error': 'League not found'}), 404
        
        # Get player and team
        player = session.query(Player).filter(Player.id == player_id).first()
        team = session.query(Team).filter(
            Team.id == team_id,
            Team.league_id == league.id
        ).first()
        
        if not player:
            return jsonify({'error': 'Player not found'}), 404
        if not team:
            return jsonify({'error': 'Team not found'}), 404
        
        # Check if player is already on a team in this league
        existing_assignment = session.query(player_teams).filter(
            player_teams.c.player_id == player_id,
            player_teams.c.team_id.in_(
                session.query(Team.id).filter(Team.league_id == league.id)
            )
        ).first()
        
        if existing_assignment:
            return jsonify({'error': 'Player already assigned to a team'}), 400
        
        # Add player to team
        team.players.append(player)
        
        # Record the draft pick in history
        try:
            draft_position = DraftService.record_draft_pick(
                session=session,
                player_id=player_id,
                team_id=team_id,
                league_id=league.id,
                season_id=league.season_id,
                drafted_by_user_id=current_user.id,
                notes=f"Drafted via HTTP API by {current_user.username}"
            )
            logger.info(f"Draft pick #{draft_position} recorded for {player.name} to {team.name}")
        except Exception as e:
            logger.error(f"Failed to record draft pick: {str(e)}")
            # Don't fail the entire operation if draft history fails
        
        session.commit()
        
        # Mark player for Discord update
        mark_player_for_discord_update(session, player_id)
        
        # Queue Discord role assignment task AFTER commit to add new team role (keep existing roles)
        assign_roles_to_player_task.delay(player_id=player_id, only_add=True)
        logger.info(f"Queued Discord role update for {player.name} (only_add = True to keep existing roles)")
        
        # Return response in the same format as socket handler
        return jsonify({
            'player': {
                'id': player.id,
                'name': player.name,
                'profile_picture_url': player.profile_picture_url,
                'experience_level': player.experience_level,
                'position': player.favorite_position
            },
            'team_id': team.id,
            'team_name': team.name,
            'league_name': league_name
        })
        
    except Exception as e:
        logger.error(f"Error in API draft player: {str(e)}", exc_info=True)
        session.rollback()
        return jsonify({'error': 'Internal server error'}), 500


#
# Enhanced Socket.IO Event Handlers
#

# Connect handler is handled by socket_handlers.py
# @socketio.on('connect')
# def handle_draft_connect():
#     """Handle client connection to default namespace."""
#     logger.info(f"Client connected to draft system: {current_user.username if current_user.is_authenticated else 'Anonymous'}")
#     emit('connected', {'message': 'Connected to draft system'})


# Socket handlers temporarily moved to socket_handlers.py due to blueprint registration issues
# This ensures they get registered properly with Flask-SocketIO

