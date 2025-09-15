"""
Security cleanup tasks for maintaining the security database tables.
"""
import logging
from datetime import datetime, timedelta
from app.decorators import celery_task

logger = logging.getLogger(__name__)


@celery_task(bind=True)
def cleanup_security_logs(self, session, retention_days=90):
    """
    Clean up old security events from the database.
    
    Args:
        retention_days (int): Number of days to retain security logs (default: 90)
    """
    try:
        from app.models import SecurityEvent
        
        logger.info(f"Starting security logs cleanup - retaining {retention_days} days")
        
        # Clean up old security events
        deleted_count = SecurityEvent.cleanup_old_events(days=retention_days)
        
        logger.info(f"Security logs cleanup completed - deleted {deleted_count} old events")
        
        return {
            'success': True,
            'deleted_events': deleted_count,
            'retention_days': retention_days,
            'cleaned_at': datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error in security logs cleanup: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e),
            'cleaned_at': datetime.utcnow().isoformat()
        }


@celery_task(bind=True)
def cleanup_expired_bans(self, session):
    """
    Clean up expired IP bans by marking them as inactive.
    This is mainly for housekeeping - expired bans are already ignored in queries.
    """
    try:
        from app.models import IPBan
        
        logger.info("Starting expired bans cleanup")
        
        # Mark expired bans as inactive
        cleaned_count = IPBan.clear_expired_bans()
        
        logger.info(f"Expired bans cleanup completed - marked {cleaned_count} bans as inactive")
        
        return {
            'success': True,
            'cleaned_bans': cleaned_count,
            'cleaned_at': datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error in expired bans cleanup: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e),
            'cleaned_at': datetime.utcnow().isoformat()
        }


@celery_task(bind=True)
def security_maintenance(self, session):
    """
    Comprehensive security maintenance task.
    Runs both log cleanup and expired ban cleanup.
    """
    try:
        logger.info("Starting comprehensive security maintenance")
        
        results = {}
        
        # Clean up old security logs (keep 90 days by default)
        log_result = cleanup_security_logs.apply_async(kwargs={'retention_days': 90})
        results['logs'] = log_result.get(timeout=300)  # 5 minute timeout
        
        # Clean up expired bans
        ban_result = cleanup_expired_bans.apply_async()
        results['bans'] = ban_result.get(timeout=300)  # 5 minute timeout
        
        logger.info("Security maintenance completed successfully")
        
        return {
            'success': True,
            'results': results,
            'completed_at': datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error in security maintenance: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e),
            'completed_at': datetime.utcnow().isoformat()
        }


@celery_task(bind=True)
def generate_security_report(self, session, days=7):
    """
    Generate a security report for the specified number of days.
    
    Args:
        days (int): Number of days to include in the report (default: 7)
    """
    try:
        from app.models import SecurityEvent, IPBan
        from collections import Counter
        
        logger.info(f"Generating security report for the last {days} days")
        
        # Get recent security events
        events = SecurityEvent.get_recent_events(limit=1000, hours=days * 24)
        
        # Get active bans
        active_bans = IPBan.get_active_bans()
        
        # Generate statistics
        event_types = Counter([event.event_type for event in events])
        severity_levels = Counter([event.severity for event in events])
        top_ips = Counter([event.ip_address for event in events]).most_common(10)
        
        report = {
            'period_days': days,
            'generated_at': datetime.utcnow().isoformat(),
            'summary': {
                'total_events': len(events),
                'active_bans': len(active_bans),
                'unique_ips': len(set([event.ip_address for event in events]))
            },
            'event_types': dict(event_types),
            'severity_levels': dict(severity_levels),
            'top_ips': [{'ip': ip, 'count': count} for ip, count in top_ips],
            'recent_bans': [
                {
                    'ip': ban.ip_address,
                    'banned_by': ban.banned_by,
                    'banned_at': ban.banned_at.isoformat() if ban.banned_at else None,
                    'expires_at': ban.expires_at.isoformat() if ban.expires_at else 'Permanent',
                    'reason': ban.reason
                }
                for ban in active_bans[:10]  # Top 10 most recent
            ]
        }
        
        logger.info(f"Security report generated - {len(events)} events, {len(active_bans)} active bans")
        
        return {
            'success': True,
            'report': report
        }
        
    except Exception as e:
        logger.error(f"Error generating security report: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e),
            'generated_at': datetime.utcnow().isoformat()
        }


@celery_task(bind=True)
def smart_ban_cleanup(self, session):
    """
    Smart cleanup for IP bans - unban well-behaved IPs and maintain security.
    This balances security with usability by giving legitimate users a second chance.
    """
    try:
        from app.models import SecurityEvent, IPBan
        from flask import current_app
        
        logger.info("Starting smart ban cleanup")
        
        # Check if smart cleanup is enabled
        cleanup_enabled = current_app.config.get('SECURITY_CLEANUP_ENABLED', True)
        unban_good_ips = current_app.config.get('SECURITY_CLEANUP_UNBAN_GOOD_IPS', True)
        
        if not cleanup_enabled:
            logger.info("Smart ban cleanup is disabled in configuration")
            return {'success': True, 'message': 'Smart cleanup disabled'}
        
        results = {
            'unbanned_ips': [],
            'escalated_bans': [],
            'maintained_bans': []
        }
        
        # Get all active bans that are temporary (not permanent)
        active_bans = IPBan.get_active_bans()
        temporary_bans = [ban for ban in active_bans if ban.expires_at is not None]
        
        current_time = datetime.utcnow()
        
        for ban in temporary_bans:
            # Check how long this IP has been banned
            ban_duration = current_time - ban.banned_at
            time_remaining = ban.expires_at - current_time
            
            # Check recent security events for this IP since the ban
            recent_events = SecurityEvent.get_events_for_ip(
                ban.ip_address, 
                since=ban.banned_at
            )
            
            # Count violations since ban
            violations_since_ban = len([
                event for event in recent_events 
                if event.event_type in ['attack_detected', 'suspicious_activity'] 
                and event.created_at > ban.banned_at
            ])
            
            # Smart cleanup logic
            if unban_good_ips and violations_since_ban == 0 and ban_duration > timedelta(hours=6):
                # IP has been clean for 6+ hours, consider unbanning for first-time offenders
                if ban.reason and 'Auto-ban after 1 attack' in ban.reason:
                    IPBan.unban_ip(ban.ip_address)
                    results['unbanned_ips'].append({
                        'ip': ban.ip_address,
                        'reason': 'Clean behavior after first offense',
                        'ban_duration': str(ban_duration)
                    })
                    logger.info(f"Smart cleanup: Unbanned first-time offender {ban.ip_address} after clean behavior")
                    
                    # Log security event
                    SecurityEvent.create(
                        ip_address=ban.ip_address,
                        event_type='smart_unban',
                        severity='low',
                        description=f'IP unbanned by smart cleanup after {ban_duration} of clean behavior',
                        user_agent='SYSTEM_SMART_CLEANUP',
                        path='/security/smart_cleanup',
                        method='SYSTEM'
                    )
            
            elif violations_since_ban > 0:
                # IP continues to violate, escalate if needed
                if ban_duration < timedelta(days=1) and violations_since_ban >= 2:
                    # Escalate to longer ban for repeat offenders
                    new_duration = min(168, ban_duration.total_seconds() / 3600 * 2)  # Double duration, max 7 days
                    
                    IPBan.ban_ip(
                        ip_address=ban.ip_address,
                        reason=f'Escalated ban due to {violations_since_ban} violations during ban period',
                        banned_by='SYSTEM_SMART_CLEANUP',
                        duration_hours=new_duration
                    )
                    
                    results['escalated_bans'].append({
                        'ip': ban.ip_address,
                        'violations': violations_since_ban,
                        'new_duration_hours': new_duration
                    })
                    logger.warning(f"Smart cleanup: Escalated ban for {ban.ip_address} ({violations_since_ban} violations)")
            else:
                # Maintain current ban
                results['maintained_bans'].append({
                    'ip': ban.ip_address,
                    'time_remaining': str(time_remaining)
                })
        
        logger.info(f"Smart ban cleanup completed - {len(results['unbanned_ips'])} unbanned, "
                   f"{len(results['escalated_bans'])} escalated, {len(results['maintained_bans'])} maintained")
        
        return {
            'success': True,
            'results': results,
            'completed_at': datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error in smart ban cleanup: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e),
            'completed_at': datetime.utcnow().isoformat()
        }