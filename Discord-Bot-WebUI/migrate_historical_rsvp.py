#!/usr/bin/env python3
"""
Historical RSVP Data Migration Script

Retroactively processes existing RSVP data from previous seasons to populate
the new PlayerAttendanceStats cache. This ensures accurate attendance 
statistics that include historical data.
"""

import sys
import logging
from datetime import datetime
from collections import defaultdict
from typing import Dict, List, Tuple

from app import create_app
from app.core import db
from app.models import (
    Player, Season, Availability, Match, Schedule, 
    PlayerAttendanceStats, League
)
from app.attendance_service import AttendanceService

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class HistoricalRSVPMigrator:
    """Migrates historical RSVP data to populate attendance statistics cache."""
    
    def __init__(self):
        self.stats = {
            'players_processed': 0,
            'players_updated': 0,
            'total_rsvp_records': 0,
            'errors': 0,
            'seasons_found': 0
        }
    
    def get_seasons_with_data(self) -> List[Season]:
        """Get all seasons that have RSVP data."""
        try:
            # Find seasons that have matches with availability responses
            seasons_with_data = db.session.query(Season).join(
                Schedule, Season.id == Schedule.season_id
            ).join(
                Match, Schedule.id == Match.schedule_id
            ).join(
                Availability, Match.id == Availability.match_id
            ).distinct().all()
            
            logger.info(f"Found {len(seasons_with_data)} seasons with RSVP data:")
            for season in seasons_with_data:
                rsvp_count = db.session.query(Availability).join(
                    Match, Availability.match_id == Match.id
                ).join(
                    Schedule, Match.schedule_id == Schedule.id
                ).filter(Schedule.season_id == season.id).count()
                
                logger.info(f"  • {season.name}: {rsvp_count} RSVP records")
            
            return seasons_with_data
            
        except Exception as e:
            logger.error(f"Error getting seasons with data: {e}")
            return []
    
    def get_historical_player_data(self, season_ids: List[int] = None) -> Dict[int, Dict]:
        """
        Get comprehensive historical RSVP data for all players.
        Returns player_id -> {season_stats, overall_stats}
        """
        try:
            logger.info("Extracting historical RSVP data...")
            
            # Build query for all availability records
            query = db.session.query(
                Availability.player_id,
                Availability.response,
                Match.date,
                Schedule.season_id
            ).join(
                Match, Availability.match_id == Match.id
            ).join(
                Schedule, Match.schedule_id == Schedule.id
            ).filter(
                Availability.player_id.isnot(None)
            )
            
            # Filter by seasons if specified
            if season_ids:
                query = query.filter(Schedule.season_id.in_(season_ids))
            
            # Order by date for chronological processing
            records = query.order_by(Match.date).all()
            
            logger.info(f"Processing {len(records)} historical RSVP records...")
            self.stats['total_rsvp_records'] = len(records)
            
            # Group data by player
            player_data = defaultdict(lambda: {
                'total_invites': 0,
                'responses': [],
                'seasons': defaultdict(lambda: {
                    'invites': 0,
                    'responses': []
                })
            })
            
            # Process each record
            for record in records:
                player_id = record.player_id
                if not player_id:
                    continue
                
                player_data[player_id]['total_invites'] += 1
                player_data[player_id]['responses'].append(record.response)
                
                # Season-specific tracking
                season_id = record.season_id
                player_data[player_id]['seasons'][season_id]['invites'] += 1
                player_data[player_id]['seasons'][season_id]['responses'].append(record.response)
            
            logger.info(f"Compiled data for {len(player_data)} players")
            return dict(player_data)
            
        except Exception as e:
            logger.error(f"Error extracting historical data: {e}")
            return {}
    
    def calculate_player_stats(self, responses: List[str]) -> Dict[str, float]:
        """Calculate attendance statistics from a list of responses."""
        if not responses:
            return {
                'response_rate': 0.0,
                'attendance_rate': 0.0,
                'adjusted_attendance_rate': 0.0,
                'reliability_score': 0.0
            }
        
        total = len(responses)
        yes_count = responses.count('yes')
        no_count = responses.count('no')
        maybe_count = responses.count('maybe')
        responded_count = yes_count + no_count + maybe_count
        
        # Calculate percentages
        response_rate = (responded_count / total) * 100 if total > 0 else 0
        attendance_rate = (yes_count / total) * 100 if total > 0 else 0
        adjusted_attendance_rate = ((yes_count + (maybe_count * 0.5)) / total) * 100 if total > 0 else 0
        
        # Calculate reliability score
        if total >= 5:  # Established players
            reliability_score = (response_rate * 0.3) + (adjusted_attendance_rate * 0.7)
        else:  # New players
            reliability_score = (response_rate * 0.5) + (adjusted_attendance_rate * 0.5)
        
        return {
            'response_rate': round(response_rate, 1),
            'attendance_rate': round(attendance_rate, 1),
            'adjusted_attendance_rate': round(adjusted_attendance_rate, 1),
            'reliability_score': round(min(100, reliability_score), 1),
            'yes_count': yes_count,
            'no_count': no_count,
            'maybe_count': maybe_count,
            'total_responses': responded_count,
            'total_invites': total
        }
    
    def migrate_player_stats(self, player_data: Dict[int, Dict], current_season_id: int = None):
        """Migrate historical stats to PlayerAttendanceStats table."""
        try:
            logger.info("Migrating historical stats to database...")
            
            for player_id, data in player_data.items():
                try:
                    # Calculate overall stats
                    overall_stats = self.calculate_player_stats(data['responses'])
                    
                    # Get or create attendance stats record
                    stats_record = PlayerAttendanceStats.query.filter_by(player_id=player_id).first()
                    if not stats_record:
                        stats_record = PlayerAttendanceStats(
                            player_id=player_id,
                            current_season_id=current_season_id
                        )
                        db.session.add(stats_record)
                    
                    # Update with historical data
                    stats_record.total_matches_invited = overall_stats['total_invites']
                    stats_record.total_responses = overall_stats['total_responses']
                    stats_record.yes_responses = overall_stats['yes_count']
                    stats_record.no_responses = overall_stats['no_count']
                    stats_record.maybe_responses = overall_stats['maybe_count']
                    stats_record.no_response_count = overall_stats['total_invites'] - overall_stats['total_responses']
                    
                    stats_record.response_rate = overall_stats['response_rate']
                    stats_record.attendance_rate = overall_stats['attendance_rate']
                    stats_record.adjusted_attendance_rate = overall_stats['adjusted_attendance_rate']
                    stats_record.reliability_score = overall_stats['reliability_score']
                    
                    # Update current season stats if available
                    if current_season_id and current_season_id in data['seasons']:
                        season_data = data['seasons'][current_season_id]
                        season_stats = self.calculate_player_stats(season_data['responses'])
                        
                        stats_record.season_matches_invited = season_stats['total_invites']
                        stats_record.season_yes_responses = season_stats['yes_count']
                        stats_record.season_attendance_rate = season_stats['adjusted_attendance_rate']
                    
                    stats_record.last_updated = datetime.utcnow()
                    
                    self.stats['players_updated'] += 1
                    
                    # Commit every 50 players to avoid memory issues
                    if self.stats['players_updated'] % 50 == 0:
                        db.session.commit()
                        logger.info(f"Processed {self.stats['players_updated']} players...")
                
                except Exception as e:
                    logger.error(f"Error processing player {player_id}: {e}")
                    self.stats['errors'] += 1
                    continue
                
                self.stats['players_processed'] += 1
            
            # Final commit
            db.session.commit()
            logger.info("Historical migration completed!")
            
        except Exception as e:
            logger.error(f"Error in migration: {e}")
            db.session.rollback()
            raise
    
    def run_migration(self, season_names: List[str] = None, all_seasons: bool = False):
        """
        Run the complete historical migration.
        
        Args:
            season_names: List of specific season names to migrate
            all_seasons: If True, migrate all available seasons
        """
        try:
            logger.info("🚀 Starting Historical RSVP Migration")
            
            # Get current season for context
            current_season = Season.query.filter_by(is_current=True).first()
            current_season_id = current_season.id if current_season else None
            
            # Determine which seasons to process
            if all_seasons:
                seasons = self.get_seasons_with_data()
                season_ids = [s.id for s in seasons]
                logger.info(f"Processing ALL {len(seasons)} seasons with data")
            elif season_names:
                seasons = Season.query.filter(Season.name.in_(season_names)).all()
                season_ids = [s.id for s in seasons]
                logger.info(f"Processing specific seasons: {[s.name for s in seasons]}")
            else:
                # Default: process last 2 seasons
                seasons = Season.query.order_by(Season.id.desc()).limit(2).all()
                season_ids = [s.id for s in seasons]
                logger.info(f"Processing last 2 seasons: {[s.name for s in seasons]}")
            
            self.stats['seasons_found'] = len(seasons)
            
            if not seasons:
                logger.warning("No seasons found with RSVP data!")
                return
            
            # Extract historical data
            player_data = self.get_historical_player_data(season_ids)
            
            if not player_data:
                logger.warning("No historical RSVP data found!")
                return
            
            # Migrate to cache table
            self.migrate_player_stats(player_data, current_season_id)
            
            # Print final statistics
            self.print_migration_summary()
            
        except Exception as e:
            logger.error(f"Migration failed: {e}")
            raise
    
    def print_migration_summary(self):
        """Print a summary of the migration results."""
        print("\n" + "="*60)
        print("📊 HISTORICAL RSVP MIGRATION SUMMARY")
        print("="*60)
        print(f"✅ Seasons processed: {self.stats['seasons_found']}")
        print(f"✅ Total RSVP records: {self.stats['total_rsvp_records']:,}")
        print(f"✅ Players processed: {self.stats['players_processed']}")
        print(f"✅ Players updated: {self.stats['players_updated']}")
        print(f"❌ Errors encountered: {self.stats['errors']}")
        print("="*60)
        
        if self.stats['players_updated'] > 0:
            print("🎉 Migration completed successfully!")
            print("   Your attendance statistics now include historical data.")
        else:
            print("⚠️  No players were updated. Check if data exists.")


def main():
    """Main command dispatcher."""
    if len(sys.argv) < 2:
        print("""
📊 Historical RSVP Migration Commands:

   python migrate_historical_rsvp.py all
      Migrate ALL seasons with RSVP data

   python migrate_historical_rsvp.py recent
      Migrate last 2 seasons (default, safest option)

   python migrate_historical_rsvp.py seasons "Season 1" "Season 2"
      Migrate specific named seasons

   python migrate_historical_rsvp.py preview
      Show what seasons have data (no migration)

Examples:
   python migrate_historical_rsvp.py all
   python migrate_historical_rsvp.py recent
   python migrate_historical_rsvp.py seasons "Spring 2024" "Fall 2024"
   python migrate_historical_rsvp.py preview
        """)
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    app = create_app()
    with app.app_context():
        migrator = HistoricalRSVPMigrator()
        
        if command == 'all':
            migrator.run_migration(all_seasons=True)
        elif command == 'recent':
            migrator.run_migration()
        elif command == 'seasons':
            if len(sys.argv) < 3:
                print("❌ Error: Season names required")
                sys.exit(1)
            season_names = sys.argv[2:]
            migrator.run_migration(season_names=season_names)
        elif command == 'preview':
            seasons = migrator.get_seasons_with_data()
            print(f"\n📋 Found {len(seasons)} seasons with RSVP data")
        else:
            print(f"❌ Unknown command: {command}")
            sys.exit(1)


if __name__ == '__main__':
    main()