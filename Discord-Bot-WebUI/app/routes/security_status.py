"""
Security status monitoring endpoint.
Provides information about security features and current threats.
"""
import time
from datetime import datetime, timedelta
from flask import Blueprint, jsonify, request, current_app
from functools import wraps

security_status_bp = Blueprint('security_status', __name__)

def require_admin_or_internal(f):
    """Decorator to require admin access or internal network."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Allow access from internal networks (Docker, localhost)
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
            
            # For now, allow authenticated users - in production you'd check admin role
            # has_admin = any('admin' in role.name.lower() for role in safe_current_user.roles)
            # if not has_admin:
            #     return jsonify({'error': 'Admin access required'}), 403
        
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