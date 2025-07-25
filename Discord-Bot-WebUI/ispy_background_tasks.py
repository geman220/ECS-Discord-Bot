"""
I-Spy Background Tasks

This module provides background task functions for maintaining the I-Spy system,
including cooldown cleanup and season management.
"""

import logging
from datetime import datetime, timedelta
from app.ispy_helpers import cleanup_expired_cooldowns
from app.core.session_manager import managed_session
from app.models.ispy import ISpyUserJail

logger = logging.getLogger(__name__)


def cleanup_ispy_expired_data():
    """
    Clean up expired I-Spy data including cooldowns and jails.
    This should be run as a weekly background task.
    """
    try:
        # Clean up expired cooldowns
        deleted_cooldowns = cleanup_expired_cooldowns()
        logger.info(f"Cleaned up {deleted_cooldowns} expired I-Spy cooldown records")
        
        # Clean up expired jails
        with managed_session() as session:
            # Mark expired jails as inactive
            expired_jails = session.query(ISpyUserJail).filter(
                ISpyUserJail.is_active == True,
                ISpyUserJail.expires_at < datetime.utcnow()
            ).all()
            
            for jail in expired_jails:
                jail.is_active = False
            
            session.commit()
            logger.info(f"Marked {len(expired_jails)} expired I-Spy jails as inactive")
        
        return {
            'success': True,
            'cooldowns_cleaned': deleted_cooldowns,
            'jails_expired': len(expired_jails)
        }
        
    except Exception as e:
        logger.error(f"Error in I-Spy cleanup task: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }


def reset_ispy_season(new_season_name: str, start_date: str, end_date: str):
    """
    Reset I-Spy for a new season.
    This should be called during standard league rollovers.
    
    Args:
        new_season_name: Name for the new season
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
    """
    try:
        from app.models.ispy import ISpySeason
        from datetime import datetime
        
        with managed_session() as session:
            # Deactivate current season
            current_season = session.query(ISpySeason).filter(
                ISpySeason.is_active == True
            ).first()
            
            if current_season:
                current_season.is_active = False
                logger.info(f"Deactivated season: {current_season.name}")
            
            # Create new season
            new_season = ISpySeason(
                name=new_season_name,
                start_date=datetime.strptime(start_date, '%Y-%m-%d').date(),
                end_date=datetime.strptime(end_date, '%Y-%m-%d').date(),
                is_active=True
            )
            
            session.add(new_season)
            session.commit()
            
            logger.info(f"Created new I-Spy season: {new_season_name}")
            
            return {
                'success': True,
                'old_season': current_season.name if current_season else None,
                'new_season': new_season_name,
                'season_id': new_season.id
            }
            
    except Exception as e:
        logger.error(f"Error resetting I-Spy season: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }


# Integration with existing task system
def add_ispy_tasks_to_scheduler():
    """
    Add I-Spy background tasks to the existing Celery scheduler.
    Call this from your main task configuration.
    """
    try:
        from celery import Celery
        from celery.schedules import crontab
        
        # This would integrate with your existing Celery app
        # Add to your celery beat schedule:
        
        schedule_config = {
            'ispy-weekly-cleanup': {
                'task': 'app.tasks.cleanup_ispy_expired_data',
                'schedule': crontab(hour=2, minute=0, day_of_week=1),  # Monday 2 AM
            },
        }
        
        logger.info("I-Spy background tasks added to scheduler")
        return schedule_config
        
    except ImportError:
        logger.warning("Celery not available - I-Spy tasks need manual scheduling")
        return None


if __name__ == "__main__":
    # Manual testing
    result = cleanup_ispy_expired_data()
    print(f"Cleanup result: {result}")