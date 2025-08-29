"""
Security status monitoring endpoint.
Provides information about security features and current threats.
"""
import time
import logging
from datetime import datetime, timedelta
from flask import Blueprint, jsonify, request, current_app, render_template, redirect, url_for, flash
from flask_login import login_required
from functools import wraps
from sqlalchemy import text
from app.decorators import role_required
import ipaddress

logger = logging.getLogger(__name__)
security_status_bp = Blueprint('security_status', __name__)

def is_private_ip(ip_str):
    """Check if an IP address is private/local."""
    try:
        ip = ipaddress.ip_address(ip_str)
        return ip.is_private or ip.is_loopback or ip.is_link_local
    except (ValueError, ipaddress.AddressValueError):
        return False

def require_admin_or_internal(f):
    """Decorator to require admin access or internal network (for API endpoints only)."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Allow access from internal networks (Docker, localhost) for API monitoring
        client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
        if client_ip:
            client_ip = client_ip.split(',')[0].strip()
        
        internal_networks = ['127.0.0.1', 'localhost', '::1']
        docker_networks = ['172.', '192.168.', '10.']
        
        is_internal = (
            client_ip in internal_networks or 
            any(client_ip.startswith(net) for net in docker_networks)
        )
        
        if not is_internal:
            # Check if user has admin role
            from app.utils.user_helpers import safe_current_user
            if not (safe_current_user and safe_current_user.is_authenticated):
                return jsonify({'error': 'Authentication required'}), 401
            
            # Check for admin roles with fallback for production
            try:
                from app.role_impersonation import get_effective_roles
                user_roles = get_effective_roles()
                has_admin = 'Global Admin' in user_roles or 'Pub League Admin' in user_roles
                if not has_admin:
                    return jsonify({'error': 'Admin access required'}), 403
            except ImportError as ie:
                logger.error(f"Import error in role_impersonation (production issue): {ie}")
                # Fallback: Check user roles directly without impersonation
                try:
                    if hasattr(safe_current_user, 'roles'):
                        user_role_names = [role.name for role in safe_current_user.roles]
                        has_admin = 'Global Admin' in user_role_names or 'Pub League Admin' in user_role_names
                        if not has_admin:
                            return jsonify({'error': 'Admin access required'}), 403
                    else:
                        return jsonify({'error': 'Unable to verify admin access'}), 500
                except Exception as fallback_error:
                    logger.error(f"Fallback role check failed: {fallback_error}")
                    return jsonify({'error': 'Authorization check failed'}), 500
            except Exception as e:
                logger.error(f"Error checking admin roles: {e}")
                return jsonify({'error': 'Authorization check failed'}), 500
        
        return f(*args, **kwargs)
    return decorated_function

@security_status_bp.route('/security/status')
@require_admin_or_internal
def security_status():
    """Get current security status."""
    try:
        # Get security middleware instance if available
        security_middleware = None
        if hasattr(current_app, 'security_middleware'):
            security_middleware = current_app.security_middleware
        
        # Basic security status
        status = {
            'timestamp': datetime.now().isoformat(),
            'security_features': {
                'rate_limiting': hasattr(current_app, 'limiter'),
                'csrf_protection': current_app.config.get('WTF_CSRF_ENABLED', False),
                'session_security': current_app.config.get('SESSION_COOKIE_SECURE', False),
                'security_headers': True,  # We always add basic headers
                'attack_detection': security_middleware is not None
            },
            'configuration': {
                'max_content_length': current_app.config.get('MAX_CONTENT_LENGTH'),
                'session_timeout': str(current_app.config.get('PERMANENT_SESSION_LIFETIME')),
                'csrf_timeout': current_app.config.get('WTF_CSRF_TIME_LIMIT'),
            },
            'redis_status': 'unknown'
        }
        
        # Check Redis connectivity
        try:
            if hasattr(current_app, 'redis') and current_app.redis:
                current_app.redis.ping()
                status['redis_status'] = 'connected'
        except Exception as e:
            status['redis_status'] = f'error: {str(e)}'
        
        # Add rate limiting stats if available
        if hasattr(current_app, 'limiter'):
            try:
                # Get rate limit info for current client
                client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
                if client_ip:
                    client_ip = client_ip.split(',')[0].strip()
                
                limiter = current_app.limiter
                status['rate_limiting'] = {
                    'enabled': True,
                    'client_ip': client_ip,
                    'storage_type': 'redis',
                }
            except Exception as e:
                status['rate_limiting'] = {'enabled': True, 'error': str(e)}
        
        # Add security middleware stats if available
        if security_middleware and hasattr(security_middleware, 'rate_limiter'):
            try:
                # Get comprehensive stats from security middleware
                stats_data = security_middleware.get_stats()
                monitored_ips = security_middleware.get_monitored_ips()
                
                client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
                if client_ip:
                    client_ip = client_ip.split(',')[0].strip()
                
                # Get stats for this IP
                rate_limiter = security_middleware.rate_limiter
                request_count = len(rate_limiter.requests.get(client_ip, []))
                is_blacklisted = client_ip in rate_limiter.blacklist
                attack_count = rate_limiter.attack_counts.get(client_ip, 0)
                
                status['attack_protection'] = {
                    'enabled': True,
                    'client_ip': client_ip,
                    'recent_requests': request_count,
                    'blacklisted': is_blacklisted,
                    'attack_attempts': attack_count,
                    'total_monitored_ips': stats_data['total_monitored_ips'],
                    'total_blacklisted_ips': stats_data['total_blacklisted_ips'],
                    'total_attack_attempts': stats_data['total_attack_attempts'],
                    'unique_attackers': stats_data['unique_attackers'],
                    'monitored_ips': monitored_ips[:10],  # Show top 10 most active IPs
                    'auto_ban_enabled': current_app.config.get('SECURITY_AUTO_BAN_ENABLED', True)
                }
                
                # Add rate limiting info
                status['rate_limiting']['current_client'] = {
                    'ip': client_ip,
                    'requests': request_count,
                    'blacklisted': is_blacklisted,
                    'attack_count': attack_count
                }
                
            except Exception as e:
                status['attack_protection'] = {'error': str(e)}
        
        return jsonify(status)
        
    except Exception as e:
        return jsonify({
            'error': 'Failed to get security status',
            'details': str(e)
        }), 500

@security_status_bp.route('/security/health')
def security_health():
    """Simple health check for security monitoring."""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'uptime': time.time(),
        'security_active': True
    })

@security_status_bp.route('/security/threats')
@require_admin_or_internal
def recent_threats():
    """Get recent security threats (if any)."""
    try:
        # This would typically read from logs or a threat database
        # For now, return a simple response
        threats = []
        
        # Check if security middleware has recent violations
        if hasattr(current_app, 'security_middleware'):
            security_middleware = current_app.security_middleware
            if hasattr(security_middleware, 'rate_limiter'):
                rate_limiter = security_middleware.rate_limiter
                
                # Get blacklisted IPs as threats
                current_time = time.time()
                for ip, expiry in rate_limiter.blacklist.items():
                    if current_time < expiry:
                        threats.append({
                            'type': 'blacklisted_ip',
                            'source': ip,
                            'expires_at': datetime.fromtimestamp(expiry).isoformat(),
                            'severity': 'medium'
                        })
        
        return jsonify({
            'threats': threats,
            'count': len(threats),
            'last_updated': datetime.now().isoformat()
        })
        
    except Exception as e:
        return jsonify({
            'error': 'Failed to get threat information',
            'details': str(e)
        }), 500

@security_status_bp.route('/security')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def security_dashboard():
    """Security dashboard page."""
    try:
        # Get current security status
        security_middleware = None
        if hasattr(current_app, 'security_middleware'):
            security_middleware = current_app.security_middleware
        
        # Get comprehensive security stats
        stats = {
            'security_features': {
                'rate_limiting': True,  # Our security middleware handles rate limiting
                'csrf_protection': current_app.config.get('WTF_CSRF_ENABLED', False),
                'session_security': current_app.config.get('SESSION_COOKIE_SECURE', False),
                'security_headers': True,
                'attack_detection': security_middleware is not None,
                'auto_ban': current_app.config.get('SECURITY_AUTO_BAN_ENABLED', True)
            },
            'auto_ban_config': {
                'enabled': current_app.config.get('SECURITY_AUTO_BAN_ENABLED', True),
                'attack_threshold': current_app.config.get('SECURITY_AUTO_BAN_ATTACK_THRESHOLD', 3),
                'rate_threshold': current_app.config.get('SECURITY_AUTO_BAN_RATE_THRESHOLD', 500),
                'duration_hours': current_app.config.get('SECURITY_AUTO_BAN_DURATION_HOURS', 1),
                'escalation_enabled': current_app.config.get('SECURITY_AUTO_BAN_ESCALATION_ENABLED', True),
                'max_duration_hours': current_app.config.get('SECURITY_AUTO_BAN_MAX_DURATION_HOURS', 168)
            },
            'redis_status': 'unknown',
            'total_monitored_ips': 0,
            'total_blacklisted_ips': 0,
            'total_attack_attempts': 0,
            'unique_attackers': 0,
            'monitored_ips': []
        }
        
        # Check Redis connectivity
        try:
            if hasattr(current_app, 'redis') and current_app.redis:
                current_app.redis.ping()
                stats['redis_status'] = 'connected'
        except Exception as e:
            stats['redis_status'] = f'error: {str(e)}'
        
        # Get security middleware stats and database bans
        blacklisted_ips = []
        try:
            # Get database bans
            from app.models import IPBan
            db_bans = IPBan.get_active_bans()
            
            for ban in db_bans:
                if not is_private_ip(ban.ip_address):  # Don't show private IPs in dashboard
                    blacklisted_ips.append({
                        'ip': ban.ip_address,
                        'expires_at': ban.expires_at or datetime.utcnow() + timedelta(days=365),  # Show far future for permanent
                        'time_remaining': ban.time_remaining or 999999999,  # Large number for permanent
                        'reason': ban.reason,
                        'banned_by': ban.banned_by,
                        'banned_at': ban.banned_at,
                        'is_permanent': ban.expires_at is None
                    })
            
            stats['total_blacklisted_ips'] = len(blacklisted_ips)
            
            if security_middleware and hasattr(security_middleware, 'rate_limiter'):
                # Get comprehensive stats from security middleware
                try:
                    security_stats = security_middleware.get_stats()
                    monitored_details = security_middleware.get_monitored_ips()
                    
                    stats.update({
                        'total_monitored_ips': security_stats['total_monitored_ips'],
                        'total_attack_attempts': security_stats['total_attack_attempts'],
                        'unique_attackers': security_stats['unique_attackers'],
                        'monitored_ips': monitored_details[:10]  # Top 10 most active
                    })
                except Exception as e:
                    logger.error(f"Error getting security middleware stats: {e}", exc_info=True)
                    # Fallback to basic stats
                    try:
                        rate_limiter = security_middleware.rate_limiter
                        stats['total_monitored_ips'] = len(rate_limiter.requests)
                        stats['total_attack_attempts'] = sum(rate_limiter.attack_counts.values()) if hasattr(rate_limiter, 'attack_counts') else 0
                        stats['unique_attackers'] = len(rate_limiter.attack_counts) if hasattr(rate_limiter, 'attack_counts') else 0
                        stats['monitored_ips'] = []  # Can't get detailed list in fallback
                    except Exception as fallback_error:
                        logger.error(f"Fallback stats collection also failed: {fallback_error}")
                        # Use minimal stats
                        stats.update({
                            'total_monitored_ips': 0,
                            'total_attack_attempts': 0,
                            'unique_attackers': 0,
                            'monitored_ips': []
                        })
                
                # Also add in-memory bans that aren't in database
                current_time = time.time()
                for ip, expiry in rate_limiter.blacklist.items():
                    if current_time < expiry and not is_private_ip(ip):
                        # Check if this IP is already in database bans
                        if not any(ban['ip'] == ip for ban in blacklisted_ips):
                            blacklisted_ips.append({
                                'ip': ip,
                                'expires_at': datetime.fromtimestamp(expiry),
                                'time_remaining': int(expiry - current_time),
                                'reason': 'Automatic detection',
                                'banned_by': 'Security System',
                                'banned_at': datetime.fromtimestamp(expiry - 1800),  # Estimate
                                'is_permanent': False
                            })
        except Exception as e:
            logger.error(f"Error getting security stats: {e}")
        
        try:
            # Ensure auto_ban_config exists (failsafe)
            if 'auto_ban_config' not in stats:
                logger.warning("auto_ban_config missing from stats, adding default")
                stats['auto_ban_config'] = {
                    'enabled': current_app.config.get('SECURITY_AUTO_BAN_ENABLED', True),
                    'attack_threshold': current_app.config.get('SECURITY_AUTO_BAN_ATTACK_THRESHOLD', 3),
                    'rate_threshold': current_app.config.get('SECURITY_AUTO_BAN_RATE_THRESHOLD', 500),
                    'duration_hours': current_app.config.get('SECURITY_AUTO_BAN_DURATION_HOURS', 1),
                    'escalation_enabled': current_app.config.get('SECURITY_AUTO_BAN_ESCALATION_ENABLED', True),
                    'max_duration_hours': current_app.config.get('SECURITY_AUTO_BAN_MAX_DURATION_HOURS', 168)
                }
            
            # Add current timestamp for initial page load
            current_time = datetime.now().strftime('%H:%M:%S')
            return render_template('security/dashboard.html', 
                                 stats=stats, 
                                 blacklisted_ips=blacklisted_ips,
                                 current_time=current_time,
                                 title="Security Dashboard")
        except Exception as template_error:
            logger.error(f"Template rendering error: {template_error}")
            # Fallback to JSON response if template fails
            return jsonify({
                'message': 'Security Dashboard (Fallback Mode)',
                'stats': stats,
                'blacklisted_ips': blacklisted_ips
            })
        
    except Exception as e:
        logger.error(f"Error loading security dashboard: {e}")
        flash('Error loading security dashboard', 'error')
        return redirect(url_for('main.index'))

@security_status_bp.route('/security/unban_ip', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def unban_ip():
    """Unban an IP address."""
    try:
        data = request.get_json() or {}
        ip_address = data.get('ip_address') or request.form.get('ip_address')
        if not ip_address:
            return jsonify({'error': 'IP address required'}), 400
        
        # Get current user
        from app.utils.user_helpers import safe_current_user
        unbanned_by = safe_current_user.username if safe_current_user else 'System'
        
        # Unban from database
        from app.models import IPBan
        db_count = IPBan.unban_ip(ip_address)
        
        # Remove from in-memory blacklist
        memory_count = 0
        security_middleware = getattr(current_app, 'security_middleware', None)
        if security_middleware and hasattr(security_middleware, 'rate_limiter'):
            rate_limiter = security_middleware.rate_limiter
            if ip_address in rate_limiter.blacklist:
                del rate_limiter.blacklist[ip_address]
                memory_count = 1
        
        total_count = db_count + memory_count
        
        if total_count > 0:
            # Log security event
            from app.models import SecurityEvent
            SecurityEvent.log_event(
                event_type='ip_unbanned',
                ip_address=ip_address,
                severity='medium',
                description=f'IP unbanned by {unbanned_by}. Removed {db_count} database ban(s) and {memory_count} memory ban(s).',
                request_path='/security/unban_ip',
                request_method='POST'
            )
            
            logger.info(f"IP {ip_address} unbanned by {unbanned_by}")
            return jsonify({'success': True, 'message': f'IP {ip_address} has been unbanned'})
        else:
            return jsonify({'error': 'IP address not found in ban list'}), 404
        
    except Exception as e:
        logger.error(f"Error unbanning IP: {e}")
        return jsonify({'error': 'Failed to unban IP address'}), 500

@security_status_bp.route('/security/logs')
@require_admin_or_internal
def security_logs():
    """Get recent security logs."""
    try:
        # In a production environment, you would read from actual log files
        # For now, return a simple response
        logs = [
            {
                'timestamp': datetime.now() - timedelta(minutes=5),
                'level': 'WARNING',
                'message': 'Rate limit exceeded from IP 192.168.1.100',
                'source': 'security_middleware'
            },
            {
                'timestamp': datetime.now() - timedelta(minutes=15),
                'level': 'INFO',
                'message': 'Security headers applied to response',
                'source': 'security_middleware'
            },
            {
                'timestamp': datetime.now() - timedelta(hours=1),
                'level': 'WARNING',
                'message': 'Attack pattern detected in request path: /wp-admin.php',
                'source': 'security_middleware'
            }
        ]
        
        return jsonify({'logs': logs})
        
    except Exception as e:
        logger.error(f"Error getting security logs: {e}")
        return jsonify({'error': 'Failed to get security logs'}), 500

@security_status_bp.route('/security/events')
@require_admin_or_internal
def security_events():
    """Get recent security events."""
    try:
        # Get security events from the last 24 hours
        events = []
        
        security_middleware = getattr(current_app, 'security_middleware', None)
        if security_middleware and hasattr(security_middleware, 'rate_limiter'):
            rate_limiter = security_middleware.rate_limiter
            current_time = time.time()
            
            # Add blacklist events (exclude private/local IPs from reporting)
            for ip, expiry in rate_limiter.blacklist.items():
                if current_time < expiry and not is_private_ip(ip):
                    events.append({
                        'type': 'ip_blacklisted',
                        'ip': ip,
                        'timestamp': datetime.fromtimestamp(expiry - 1800),  # Assume 30 min blacklist
                        'severity': 'high',
                        'description': f'IP {ip} was blacklisted due to suspicious activity'
                    })
            
            # Add rate limiting events for heavily monitored IPs (exclude private/local IPs)
            for ip, requests in rate_limiter.requests.items():
                if len(requests) > 50 and not is_private_ip(ip):  # High request count from external IPs only
                    events.append({
                        'type': 'high_request_rate',
                        'ip': ip,
                        'timestamp': datetime.now() - timedelta(minutes=30),
                        'severity': 'medium',
                        'description': f'IP {ip} has made {len(requests)} requests recently'
                    })
        
        # Sort events by timestamp (most recent first)
        events.sort(key=lambda x: x['timestamp'], reverse=True)
        
        return jsonify({'events': events[:50]})  # Return last 50 events
        
    except Exception as e:
        logger.error(f"Error getting security events: {e}")
        return jsonify({'error': 'Failed to get security events'}), 500

@security_status_bp.route('/security/ban_ip', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def ban_ip():
    """Ban an IP address manually."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Invalid request data'}), 400
            
        ip_address = data.get('ip_address')
        duration_hours = data.get('duration_hours')
        reason = data.get('reason')
        
        if not ip_address:
            return jsonify({'error': 'IP address is required'}), 400
        
        # Validate IP address format
        try:
            ipaddress.ip_address(ip_address)
        except ValueError:
            return jsonify({'error': 'Invalid IP address format'}), 400
        
        # Get current user
        from app.utils.user_helpers import safe_current_user
        banned_by = safe_current_user.username if safe_current_user else 'System'
        
        # Import the IPBan model
        from app.models import IPBan
        
        # Create database ban
        ban = IPBan.ban_ip(
            ip_address=ip_address,
            reason=reason,
            banned_by=banned_by,
            duration_hours=duration_hours
        )
        
        # Also add to in-memory middleware ban list
        security_middleware = getattr(current_app, 'security_middleware', None)
        if security_middleware and hasattr(security_middleware, 'rate_limiter'):
            duration_seconds = duration_hours * 3600 if duration_hours else 86400 * 365  # 1 year for permanent
            security_middleware.rate_limiter.blacklist_ip(ip_address, duration=duration_seconds)
        
        # Log security event
        from app.models import SecurityEvent
        SecurityEvent.log_event(
            event_type='ip_banned_manual',
            ip_address=ip_address,
            severity='high',
            description=f'IP manually banned by {banned_by}. Duration: {"Permanent" if not duration_hours else f"{duration_hours} hours"}. Reason: {reason or "No reason provided"}',
            request_path='/security/ban_ip',
            request_method='POST'
        )
        
        duration_text = "permanently" if not duration_hours else f"for {duration_hours} hours"
        logger.info(f"IP {ip_address} banned {duration_text} by {banned_by}")
        
        return jsonify({
            'success': True,
            'message': f'IP {ip_address} has been banned {duration_text}'
        })
        
    except Exception as e:
        logger.error(f"Error banning IP: {e}")
        return jsonify({'error': 'Failed to ban IP address'}), 500

@security_status_bp.route('/security/clear_all_bans', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def clear_all_bans():
    """Clear all IP bans."""
    try:
        # Get current user
        from app.utils.user_helpers import safe_current_user
        cleared_by = safe_current_user.username if safe_current_user else 'System'
        
        # Clear database bans
        from app.models import IPBan
        count = IPBan.clear_all_bans()
        
        # Clear in-memory middleware bans
        security_middleware = getattr(current_app, 'security_middleware', None)
        if security_middleware and hasattr(security_middleware, 'rate_limiter'):
            security_middleware.rate_limiter.blacklist.clear()
        
        # Log security event
        from app.models import SecurityEvent
        SecurityEvent.log_event(
            event_type='all_bans_cleared',
            ip_address='system',
            severity='medium',
            description=f'All IP bans cleared by {cleared_by}. {count} bans were removed.',
            request_path='/security/clear_all_bans',
            request_method='POST'
        )
        
        logger.info(f"All IP bans cleared by {cleared_by}. {count} bans removed.")
        
        return jsonify({
            'success': True,
            'message': f'Successfully cleared {count} IP ban(s)'
        })
        
    except Exception as e:
        logger.error(f"Error clearing all bans: {e}")
        return jsonify({'error': 'Failed to clear IP bans'}), 500