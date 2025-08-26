# app/tasks/mobile_analytics_cleanup.py

"""
Mobile Analytics Cleanup Tasks

Celery tasks for automated cleanup of mobile analytics data.
Since pg_cron requires superuser privileges, we use Celery for scheduling.
"""

from datetime import datetime, timedelta
from app.core import celery
from app import db
from app.models_mobile_analytics import MobileErrorAnalytics, MobileErrorPatterns, MobileLogs
import logging

logger = logging.getLogger(__name__)


def cleanup_mobile_analytics():
    """
    Clean up old mobile analytics data using the PostgreSQL function.
    
    Retention policies:
    - Error analytics: 30 days
    - Logs: 7 days  
    - Error patterns: 60 days (based on last_seen)
    
    Returns:
        dict: Cleanup statistics
    """
    try:
        from sqlalchemy import text
        
        # Call the PostgreSQL cleanup function
        result = db.session.execute(text("SELECT cleanup_mobile_analytics()"))
        cleanup_data = result.scalar()
        
        # The function returns JSONB, which SQLAlchemy converts to dict
        if isinstance(cleanup_data, dict):
            logger.info(f"✅ Mobile analytics cleanup completed: {cleanup_data}")
            return cleanup_data
        else:
            # If for some reason it's not a dict, try to parse it
            import json
            cleanup_dict = json.loads(cleanup_data) if isinstance(cleanup_data, str) else cleanup_data
            logger.info(f"✅ Mobile analytics cleanup completed: {cleanup_dict}")
            return cleanup_dict
        
    except Exception as e:
        logger.error(f"❌ Mobile analytics cleanup failed: {str(e)}", exc_info=True)
        
        return {
            'analytics_deleted': 0,
            'logs_deleted': 0,
            'patterns_deleted': 0,
            'total_deleted': 0,
            'execution_time_seconds': 0,
            'cleanup_date': datetime.utcnow().isoformat(),
            'status': 'failed',
            'error': str(e)
        }


def get_cleanup_preview():
    """
    Preview what would be deleted without actually deleting.
    
    Returns:
        dict: Preview of records that would be deleted
    """
    try:
        # Calculate cutoff dates
        analytics_cutoff = datetime.utcnow() - timedelta(days=30)
        logs_cutoff = datetime.utcnow() - timedelta(days=7)
        patterns_cutoff = datetime.utcnow() - timedelta(days=60)
        
        # Count records that would be deleted
        analytics_count = db.session.query(MobileErrorAnalytics).filter(
            MobileErrorAnalytics.created_at < analytics_cutoff
        ).count()
        
        logs_count = db.session.query(MobileLogs).filter(
            MobileLogs.created_at < logs_cutoff
        ).count()
        
        patterns_count = db.session.query(MobileErrorPatterns).filter(
            MobileErrorPatterns.last_seen < patterns_cutoff
        ).count()
        
        # Get oldest records in each table
        oldest_analytics = db.session.query(MobileErrorAnalytics.created_at).order_by(
            MobileErrorAnalytics.created_at.asc()
        ).first()
        
        oldest_logs = db.session.query(MobileLogs.created_at).order_by(
            MobileLogs.created_at.asc()
        ).first()
        
        oldest_patterns = db.session.query(MobileErrorPatterns.last_seen).order_by(
            MobileErrorPatterns.last_seen.asc()
        ).first()
        
        return {
            'preview_date': datetime.utcnow().isoformat(),
            'mobile_error_analytics': {
                'records_to_delete': analytics_count,
                'retention_cutoff': analytics_cutoff.isoformat(),
                'oldest_record': oldest_analytics[0].isoformat() if oldest_analytics else None
            },
            'mobile_logs': {
                'records_to_delete': logs_count,
                'retention_cutoff': logs_cutoff.isoformat(),
                'oldest_record': oldest_logs[0].isoformat() if oldest_logs else None
            },
            'mobile_error_patterns': {
                'records_to_delete': patterns_count,
                'retention_cutoff': patterns_cutoff.isoformat(),
                'oldest_record': oldest_patterns[0].isoformat() if oldest_patterns else None
            },
            'total_records_to_delete': analytics_count + logs_count + patterns_count
        }
        
    except Exception as e:
        logger.error(f"❌ Cleanup preview failed: {str(e)}", exc_info=True)
        return {
            'error': str(e),
            'preview_date': datetime.utcnow().isoformat()
        }


def get_analytics_storage_stats():
    """
    Get storage statistics for mobile analytics tables.
    
    Returns:
        dict: Storage statistics
    """
    try:
        from sqlalchemy import text
        
        # Get table sizes (PostgreSQL specific)
        size_query = text("""
            SELECT 
                schemaname,
                tablename,
                pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size,
                pg_total_relation_size(schemaname||'.'||tablename) as size_bytes
            FROM pg_tables 
            WHERE tablename LIKE 'mobile_%'
            ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC
        """)
        
        result = db.session.execute(size_query)
        table_sizes = [dict(row) for row in result]
        
        # Get record counts
        analytics_count = db.session.query(MobileErrorAnalytics).count()
        logs_count = db.session.query(MobileLogs).count()
        patterns_count = db.session.query(MobileErrorPatterns).count()
        
        return {
            'record_counts': {
                'mobile_error_analytics': analytics_count,
                'mobile_logs': logs_count,
                'mobile_error_patterns': patterns_count,
                'total_records': analytics_count + logs_count + patterns_count
            },
            'table_sizes': table_sizes,
            'stats_date': datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"❌ Storage stats failed: {str(e)}", exc_info=True)
        return {
            'error': str(e),
            'stats_date': datetime.utcnow().isoformat()
        }


# Celery task definitions
try:
    
    @celery.task(name='app.tasks.mobile_analytics_cleanup.cleanup_mobile_analytics_task')
    def cleanup_mobile_analytics_task():
        """Celery task for mobile analytics cleanup."""
        logger.info("🧹 Starting mobile analytics cleanup task")
        result = cleanup_mobile_analytics()
        logger.info(f"🧹 Mobile analytics cleanup task completed: {result.get('total_deleted', 0)} records deleted")
        return result
    
    @celery.task(name='app.tasks.mobile_analytics_cleanup.cleanup_preview_task')
    def cleanup_preview_task():
        """Celery task for cleanup preview."""
        return get_cleanup_preview()
    
    @celery.task(name='app.tasks.mobile_analytics_cleanup.storage_stats_task')
    def storage_stats_task():
        """Celery task for storage statistics."""
        return get_analytics_storage_stats()
        
except ImportError:
    logger.info("Celery not available, tasks will run synchronously")


# Manual execution functions
if __name__ == '__main__':
    print("Mobile Analytics Cleanup Utility")
    print("1. Preview cleanup")
    print("2. Execute cleanup")
    print("3. Show storage stats")
    
    choice = input("Enter choice (1-3): ")
    
    if choice == '1':
        preview = get_cleanup_preview()
        print("\n=== Cleanup Preview ===")
        for table, info in preview.items():
            if isinstance(info, dict) and 'records_to_delete' in info:
                print(f"{table}: {info['records_to_delete']} records to delete")
        print(f"Total: {preview.get('total_records_to_delete', 0)} records")
        
    elif choice == '2':
        confirm = input("Are you sure you want to delete old records? (yes/no): ")
        if confirm.lower() == 'yes':
            result = cleanup_mobile_analytics()
            print(f"\n=== Cleanup Results ===")
            print(f"Status: {result['status']}")
            print(f"Total deleted: {result['total_deleted']}")
            print(f"Execution time: {result['execution_time_seconds']:.2f}s")
        else:
            print("Cleanup cancelled")
            
    elif choice == '3':
        stats = get_analytics_storage_stats()
        print("\n=== Storage Statistics ===")
        if 'record_counts' in stats:
            for table, count in stats['record_counts'].items():
                print(f"{table}: {count:,} records")
        else:
            print("Error getting stats:", stats.get('error', 'Unknown error'))