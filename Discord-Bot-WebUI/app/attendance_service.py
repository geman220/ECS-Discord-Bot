"""
Attendance Statistics Service

High-performance service for managing player attendance statistics.
Uses cached data in PlayerAttendanceStats table for fast draft system lookups.
Updates statistics automatically when RSVP responses change.
"""

import logging
from typing import List, Optional
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError
from app.core import db
from app.models import PlayerAttendanceStats, Availability, Player, Season

logger = logging.getLogger(__name__)


class AttendanceService:
    """Service for managing player attendance statistics efficiently."""
    
    @staticmethod
    def update_player_attendance(player_id: int, season_id: Optional[int] = None) -> None:
        """
        Update attendance statistics for a single player.
        Called whenever a player's RSVP response changes.
        """
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                # Use a fresh transaction for each attempt
                if attempt > 0:
                    # Close any existing session state
                    g.db_session.rollback()
                
                # Get or create attendance stats record
                stats = PlayerAttendanceStats.get_or_create(player_id, season_id)
                
                # Update the statistics
                stats.update_stats()
                
                g.db_session.commit()
                logger.debug(f"Updated attendance stats for player {player_id}")
                return  # Success
                
            except Exception as e:
                g.db_session.rollback()
                
                if attempt < max_retries - 1:
                    logger.warning(f"Attempt {attempt + 1} failed for player {player_id}, retrying: {e}")
                    import time
                    time.sleep(0.1 * (attempt + 1))  # Brief delay with backoff
                else:
                    logger.error(f"All {max_retries} attempts failed for player {player_id}: {e}")
                    # Don't re-raise to avoid breaking the main flow
                    return
    
    @staticmethod
    def bulk_update_attendance(player_ids: List[int], season_id: Optional[int] = None) -> None:
        """
        Bulk update attendance statistics for multiple players.
        Useful for initial data migration or batch processing.
        Uses individual transactions to prevent cascade failures.
        """
        updated_count = 0
        error_count = 0
        
        logger.info(f"Starting bulk update for {len(player_ids)} players...")
        
        for i, player_id in enumerate(player_ids):
            try:
                # Use individual transaction for each player to prevent cascade failures
                with g.db_session.begin():
                    stats = PlayerAttendanceStats.get_or_create(player_id, season_id)
                    stats.update_stats()
                    updated_count += 1
                    
                # Log progress every 50 players
                if (i + 1) % 50 == 0:
                    logger.info(f"Processed {i + 1}/{len(player_ids)} players...")
                    
            except Exception as e:
                error_count += 1
                logger.warning(f"Failed to update player {player_id}: {e}")
                # Rollback is handled automatically by the context manager
                continue
        
        logger.info(f"Bulk updated attendance stats for {updated_count}/{len(player_ids)} players ({error_count} errors)")
        
        if error_count > len(player_ids) * 0.5:  # More than 50% failed
            logger.error(f"High error rate: {error_count}/{len(player_ids)} players failed")
            raise Exception(f"Bulk update had too many failures: {error_count}/{len(player_ids)}")
    
    @staticmethod
    def safe_bulk_update_attendance(player_ids: List[int], season_id: Optional[int] = None, batch_size: int = 25) -> None:
        """
        Extra-safe bulk update that processes players in small batches.
        Use this if the regular bulk update is having issues.
        """
        total_updated = 0
        total_errors = 0
        
        # Process in small batches to minimize transaction conflicts
        for i in range(0, len(player_ids), batch_size):
            batch = player_ids[i:i + batch_size]
            logger.info(f"Processing batch {i//batch_size + 1}: players {i+1}-{min(i+batch_size, len(player_ids))}")
            
            batch_updated = 0
            batch_errors = 0
            
            for player_id in batch:
                try:
                    # Individual transaction per player
                    AttendanceService.update_player_attendance(player_id, season_id)
                    batch_updated += 1
                except Exception as e:
                    batch_errors += 1
                    logger.warning(f"Failed to update player {player_id} in batch: {e}")
                    continue
            
            total_updated += batch_updated
            total_errors += batch_errors
            
            logger.info(f"Batch complete: {batch_updated}/{len(batch)} players updated")
            
            # Small delay between batches to reduce database pressure
            import time
            time.sleep(0.1)
        
        logger.info(f"Safe bulk update complete: {total_updated}/{len(player_ids)} players updated ({total_errors} errors)")
    
    @staticmethod
    def get_attendance_stats(player_ids: List[int]) -> dict:
        """
        Fast lookup of attendance statistics for multiple players.
        Returns a dictionary mapping player_id to attendance data.
        """
        try:
            stats_records = PlayerAttendanceStats.query.filter(
                PlayerAttendanceStats.player_id.in_(player_ids)
            ).all()
            
            # Create lookup dictionary
            result = {}
            for stats in stats_records:
                result[stats.player_id] = {
                    'total_matches_invited': stats.total_matches_invited,
                    'response_rate': stats.response_rate,
                    'attendance_rate': stats.attendance_rate,
                    'adjusted_attendance_rate': stats.adjusted_attendance_rate,
                    'reliability_score': stats.reliability_score,
                    'season_attendance_rate': stats.season_attendance_rate,
                    'last_updated': stats.last_updated
                }
            
            # Add default values for players without stats
            for player_id in player_ids:
                if player_id not in result:
                    result[player_id] = {
                        'total_matches_invited': 0,
                        'response_rate': 0.0,
                        'attendance_rate': 0.0,
                        'adjusted_attendance_rate': 50.0,  # Default for new players
                        'reliability_score': 25.0,         # Conservative default
                        'season_attendance_rate': 0.0,
                        'last_updated': None
                    }
            
            return result
            
        except Exception as e:
            logger.error(f"Error getting attendance stats: {e}")
            return {player_id: {
                'total_matches_invited': 0,
                'response_rate': 0.0,
                'attendance_rate': 0.0,
                'adjusted_attendance_rate': 50.0,
                'reliability_score': 25.0,
                'season_attendance_rate': 0.0,
                'last_updated': None
            } for player_id in player_ids}
    
    @staticmethod
    def initialize_all_player_stats(season_id: Optional[int] = None) -> None:
        """
        Initialize attendance statistics for all current players.
        Run this once during deployment to populate the cache table.
        """
        try:
            # Get all current players
            current_players = Player.query.filter_by(is_current_player=True).all()
            player_ids = [p.id for p in current_players]
            
            logger.info(f"Initializing attendance stats for {len(player_ids)} players")
            
            # Use bulk update
            AttendanceService.bulk_update_attendance(player_ids, season_id)
            
            logger.info(f"Successfully initialized attendance stats for all players")
            
        except Exception as e:
            logger.error(f"Error initializing player attendance stats: {e}")
            raise
    
    @staticmethod
    def refresh_stale_stats(hours_threshold: int = 24) -> None:
        """
        Refresh attendance statistics that haven't been updated recently.
        Can be run as a periodic maintenance task.
        """
        try:
            cutoff_time = datetime.utcnow() - timedelta(hours=hours_threshold)
            
            # Find stale records
            stale_stats = PlayerAttendanceStats.query.filter(
                PlayerAttendanceStats.last_updated < cutoff_time
            ).all()
            
            logger.info(f"Found {len(stale_stats)} stale attendance records")
            
            # Update each stale record
            for stats in stale_stats:
                try:
                    stats.update_stats()
                except Exception as e:
                    logger.warning(f"Failed to refresh stats for player {stats.player_id}: {e}")
            
            g.db_session.commit()
            logger.info(f"Refreshed {len(stale_stats)} stale attendance records")
            
        except Exception as e:
            g.db_session.rollback()
            logger.error(f"Error refreshing stale stats: {e}")
            raise


def handle_availability_change(player_id: int, season_id: Optional[int] = None):
    """
    Event handler to be called whenever a player's availability response changes.
    This keeps the attendance statistics up-to-date in real-time.
    """
    try:
        AttendanceService.update_player_attendance(player_id, season_id)
    except Exception as e:
        logger.error(f"Failed to handle availability change for player {player_id}: {e}")
        # Don't re-raise to avoid breaking the main RSVP flow