#!/usr/bin/env python3
"""
Attendance Management Script

Commands for managing the player attendance statistics cache.
Run this after setting up the PlayerAttendanceStats table.
"""

import sys
import logging
from app import create_app
from app.core import db
from app.attendance_service import AttendanceService
from app.models import Player, Season

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def init_attendance_cache(safe_mode=False):
    """Initialize attendance statistics cache for all current players."""
    app = create_app()
    with app.app_context():
        try:
            # Get current season if available
            current_season = Season.query.filter_by(is_current=True).first()
            season_id = current_season.id if current_season else None
            
            if safe_mode:
                logger.info("Initializing attendance cache in SAFE MODE (slower but more reliable)...")
                # Get all current players
                current_players = Player.query.filter_by(is_current_player=True).all()
                player_ids = [p.id for p in current_players]
                logger.info(f"Found {len(player_ids)} current players")
                
                # Use safe bulk update
                AttendanceService.safe_bulk_update_attendance(player_ids, season_id)
            else:
                logger.info("Initializing attendance statistics cache...")
                AttendanceService.initialize_all_player_stats(season_id)
            
            logger.info("✅ Attendance cache initialization completed successfully!")
            
        except Exception as e:
            logger.error(f"❌ Error initializing attendance cache: {e}")
            if not safe_mode:
                logger.info("💡 Try running with 'safe' mode: python manage_attendance.py init-safe")
            sys.exit(1)


def refresh_stale_stats(hours=24):
    """Refresh attendance statistics that are older than specified hours."""
    app = create_app()
    with app.app_context():
        try:
            logger.info(f"Refreshing attendance stats older than {hours} hours...")
            AttendanceService.refresh_stale_stats(hours)
            logger.info("✅ Stale stats refresh completed successfully!")
            
        except Exception as e:
            logger.error(f"❌ Error refreshing stale stats: {e}")
            sys.exit(1)


def update_player_stats(player_id):
    """Update attendance statistics for a specific player."""
    app = create_app()
    with app.app_context():
        try:
            # Get current season if available
            current_season = Season.query.filter_by(is_current=True).first()
            season_id = current_season.id if current_season else None
            
            logger.info(f"Updating attendance stats for player {player_id}...")
            AttendanceService.update_player_attendance(player_id, season_id)
            logger.info("✅ Player stats update completed successfully!")
            
        except Exception as e:
            logger.error(f"❌ Error updating player stats: {e}")
            sys.exit(1)


def show_stats_summary():
    """Show a summary of the attendance statistics cache."""
    app = create_app()
    with app.app_context():
        try:
            from app.models import PlayerAttendanceStats
            
            total_stats = PlayerAttendanceStats.query.count()
            total_players = Player.query.filter_by(is_current_player=True).count()
            
            print(f"\n📊 Attendance Statistics Summary:")
            print(f"   • Total players with cached stats: {total_stats}")
            print(f"   • Total current players: {total_players}")
            print(f"   • Coverage: {(total_stats/max(total_players,1)*100):.1f}%")
            
            # Show some sample data
            if total_stats > 0:
                sample_stats = PlayerAttendanceStats.query.limit(5).all()
                print(f"\n📝 Sample Statistics:")
                for stats in sample_stats:
                    print(f"   • Player {stats.player_id}: {stats.response_rate}% response, "
                          f"{stats.adjusted_attendance_rate}% attendance, "
                          f"{stats.reliability_score}% reliability")
            
        except Exception as e:
            logger.error(f"❌ Error showing stats summary: {e}")
            sys.exit(1)


def main():
    """Main command dispatcher."""
    if len(sys.argv) < 2:
        print("""
🎯 Attendance Management Commands:

   python manage_attendance.py init
      Initialize attendance cache for all current players

   python manage_attendance.py init-safe
      Initialize cache in safe mode (slower but more reliable)

   python manage_attendance.py refresh [hours]
      Refresh stats older than specified hours (default: 24)

   python manage_attendance.py update <player_id>
      Update stats for a specific player

   python manage_attendance.py summary
      Show attendance statistics summary

Examples:
   python manage_attendance.py init
   python manage_attendance.py init-safe
   python manage_attendance.py refresh 12
   python manage_attendance.py update 123
   python manage_attendance.py summary
        """)
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    if command == 'init':
        init_attendance_cache(safe_mode=False)
    elif command == 'init-safe':
        init_attendance_cache(safe_mode=True)
    elif command == 'refresh':
        hours = int(sys.argv[2]) if len(sys.argv) > 2 else 24
        refresh_stale_stats(hours)
    elif command == 'update':
        if len(sys.argv) < 3:
            print("❌ Error: Player ID required")
            sys.exit(1)
        player_id = int(sys.argv[2])
        update_player_stats(player_id)
    elif command == 'summary':
        show_stats_summary()
    else:
        print(f"❌ Unknown command: {command}")
        sys.exit(1)


if __name__ == '__main__':
    main()