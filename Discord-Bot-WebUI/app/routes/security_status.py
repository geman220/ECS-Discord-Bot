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

logger = logging.getLogger(__name__)
security_status_bp = Blueprint('security_status', __name__)

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
            
            # Check for admin roles
            try:
                from app.role_impersonation import get_effective_roles
                user_roles = get_effective_roles()
                has_admin = 'Global Admin' in user_roles or 'Pub League Admin' in user_roles
                if not has_admin:
                    return jsonify({'error': 'Admin access required'}), 403
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
                rate_limiter = security_middleware.rate_limiter
                client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
                if client_ip:
                    client_ip = client_ip.split(',')[0].strip()
                
                # Get stats for this IP
                request_count = len(rate_limiter.requests.get(client_ip, []))
                is_blacklisted = client_ip in rate_limiter.blacklist
                
                status['attack_protection'] = {
                    'client_ip': client_ip,
                    'recent_requests': request_count,
                    'blacklisted': is_blacklisted,
                    'total_monitored_ips': len(rate_limiter.requests),
                    'total_blacklisted_ips': len(rate_limiter.blacklist)
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
        
        # Get basic stats
        stats = {
            'security_features': {
                'rate_limiting': hasattr(current_app, 'limiter'),
                'csrf_protection': current_app.config.get('WTF_CSRF_ENABLED', False),
                'session_security': current_app.config.get('SESSION_COOKIE_SECURE', False),
                'security_headers': True,
                'attack_detection': security_middleware is not None
            },
            'redis_status': 'unknown',
            'total_monitored_ips': 0,
            'total_blacklisted_ips': 0
        }
        
        # Check Redis connectivity
        try:
            if hasattr(current_app, 'redis') and current_app.redis:
                current_app.redis.ping()
                stats['redis_status'] = 'connected'
        except Exception as e:
            stats['redis_status'] = f'error: {str(e)}'
        
        # Get security middleware stats
        blacklisted_ips = []
        if security_middleware and hasattr(security_middleware, 'rate_limiter'):
            try:
                rate_limiter = security_middleware.rate_limiter
                stats['total_monitored_ips'] = len(rate_limiter.requests)
                stats['total_blacklisted_ips'] = len(rate_limiter.blacklist)
                
                # Get blacklisted IPs with expiry times
                current_time = time.time()
                for ip, expiry in rate_limiter.blacklist.items():
                    if current_time < expiry:
                        blacklisted_ips.append({
                            'ip': ip,
                            'expires_at': datetime.fromtimestamp(expiry),
                            'time_remaining': int(expiry - current_time)
                        })
            except Exception as e:
                logger.error(f"Error getting security stats: {e}")
        
        return render_template('security/dashboard.html', 
                             stats=stats, 
                             blacklisted_ips=blacklisted_ips,
                             title="Security Dashboard")
        
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
        ip_address = request.form.get('ip_address') or request.json.get('ip_address')
        if not ip_address:
            return jsonify({'error': 'IP address required'}), 400
        
        security_middleware = getattr(current_app, 'security_middleware', None)
        if not security_middleware or not hasattr(security_middleware, 'rate_limiter'):
            return jsonify({'error': 'Security middleware not available'}), 500
        
        rate_limiter = security_middleware.rate_limiter
        
        # Remove from blacklist
        if ip_address in rate_limiter.blacklist:
            del rate_limiter.blacklist[ip_address]
            logger.info(f"IP {ip_address} unbanned by admin")
            return jsonify({'success': True, 'message': f'IP {ip_address} has been unbanned'})
        else:
            return jsonify({'error': 'IP address not found in blacklist'}), 404
        
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
            
            # Add blacklist events
            for ip, expiry in rate_limiter.blacklist.items():
                if current_time < expiry:
                    events.append({
                        'type': 'ip_blacklisted',
                        'ip': ip,
                        'timestamp': datetime.fromtimestamp(expiry - 1800),  # Assume 30 min blacklist
                        'severity': 'high',
                        'description': f'IP {ip} was blacklisted due to suspicious activity'
                    })
            
            # Add rate limiting events for heavily monitored IPs
            for ip, requests in rate_limiter.requests.items():
                if len(requests) > 50:  # High request count
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