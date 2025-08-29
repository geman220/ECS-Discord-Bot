"""
Security middleware for Flask application.
Provides protection against common web application attacks.
Compatible with existing ECS Discord Bot infrastructure.
"""
import re
import time
import logging
import ipaddress
from collections import defaultdict, deque
from flask import request, abort, g, current_app
from werkzeug.exceptions import TooManyRequests
from functools import wraps

logger = logging.getLogger(__name__)

def is_private_ip(ip_str):
    """Check if an IP address is private/local/internal."""
    try:
        ip = ipaddress.ip_address(ip_str)
        
        # Standard private/loopback/link-local addresses
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            return True
            
        # Docker bridge networks (commonly 172.17.0.0/16, 172.18.0.0/16, etc.)
        if ipaddress.IPv4Address('172.16.0.0') <= ip <= ipaddress.IPv4Address('172.31.255.255'):
            return True
            
        # Additional Docker and container networks
        docker_networks = [
            ipaddress.IPv4Network('172.16.0.0/12'),  # Docker default bridge networks
            ipaddress.IPv4Network('192.168.0.0/16'), # Private networks
            ipaddress.IPv4Network('10.0.0.0/8'),     # Private networks
            ipaddress.IPv4Network('169.254.0.0/16'), # Link-local
            ipaddress.IPv4Network('127.0.0.0/8'),    # Loopback
        ]
        
        for network in docker_networks:
            if ip in network:
                return True
                
        return False
        
    except (ValueError, ipaddress.AddressValueError):
        # If we can't parse the IP, treat it as potentially external for security
        return False

class SecurityMiddleware:
    """Enhanced security middleware for attack detection and prevention."""
    
    def __init__(self, app=None):
        self.app = app
        self.attack_patterns = self._load_attack_patterns()
        self.rate_limiter = RequestRateLimiter()
        
        if app:
            self.init_app(app)
    
    def init_app(self, app):
        """Initialize the security middleware with Flask app."""
        app.before_request(self.security_check)
        app.after_request(self.security_response)
        # Store reference to this middleware in the app for status checking
        app.security_middleware = self
    
    def _load_attack_patterns(self):
        """Load common attack patterns for detection."""
        return [
            # PHP file attempts (main attack vector from logs)
            re.compile(r'\.php[^a-zA-Z0-9]', re.IGNORECASE),
            # Common CMS exploitation attempts
            re.compile(r'/(wp-|plus/|utility/|vendor/phpunit)', re.IGNORECASE),
            # SQL injection patterns (more conservative to avoid false positives)
            re.compile(r'\b(union\s+select|drop\s+table|information_schema)\b', re.IGNORECASE),
            # XSS patterns (basic)
            re.compile(r'<script|javascript:|onload=|onerror=', re.IGNORECASE),
            # Path traversal
            re.compile(r'\.\./|\.\.\\'),
            # File inclusion attempts
            re.compile(r'(eval|base64_decode)\s*\(', re.IGNORECASE),
            # Shell upload attempts
            re.compile(r'file_put_contents|fopen.*w\+', re.IGNORECASE)
        ]
    
    def security_check(self):
        """Perform security checks before processing request."""
        try:
            # Skip checks for static files, health checks, API monitoring, and security endpoints
            if (request.path.startswith('/static/') or 
                request.path.startswith('/test/status/') or
                request.path.startswith('/security/') or
                request.path in ['/health', '/healthcheck']):
                return
            
            # Get client IP (handle proxy headers from Traefik)
            client_ip = self._get_client_ip()
            
            # Rate limiting check (more lenient for legitimate traffic and private IPs)
            if is_private_ip(client_ip):
                # Much higher limits for private/local IPs
                limit, window = 1000, 3600
            else:
                # Standard limits for external IPs
                limit, window = 200, 3600
                
            if not self.rate_limiter.allow_request(client_ip, limit=limit, window=window):
                # Don't rate limit private IPs as aggressively
                if not is_private_ip(client_ip):
                    logger.warning(f"Rate limit exceeded from {client_ip} for {request.path}")
                    abort(429)  # Too Many Requests
            
            # Detect attack patterns
            if self._detect_attack_patterns():
                self._handle_security_violation(client_ip)
                
        except Exception as e:
            logger.error(f"Security check error: {e}")
            # Don't block legitimate requests due to security check errors
            pass
    
    def _get_client_ip(self):
        """Get the real client IP address (handle proxy headers)."""
        # Check standard proxy headers (Traefik/Cloudflare compatible)
        if request.headers.get('X-Forwarded-For'):
            # Take the first IP in the chain (original client)
            return request.headers.get('X-Forwarded-For').split(',')[0].strip()
        elif request.headers.get('X-Real-IP'):
            return request.headers.get('X-Real-IP')
        elif request.headers.get('CF-Connecting-IP'):  # Cloudflare
            return request.headers.get('CF-Connecting-IP')
        else:
            return request.remote_addr or 'unknown'
    
    def _detect_attack_patterns(self):
        """Check request for malicious patterns."""
        # Check URL path
        if any(pattern.search(request.path) for pattern in self.attack_patterns):
            return True
        
        # Check query parameters
        for key, value in request.args.items():
            if any(pattern.search(str(value)) for pattern in self.attack_patterns):
                return True
        
        # Check POST data
        if request.method == 'POST':
            try:
                if request.is_json:
                    # Check JSON data
                    json_str = str(request.get_json())
                    if any(pattern.search(json_str) for pattern in self.attack_patterns):
                        return True
                elif request.form:
                    # Check form data
                    for key, value in request.form.items():
                        if any(pattern.search(str(value)) for pattern in self.attack_patterns):
                            return True
            except:
                pass  # Don't block if we can't parse request data
        
        return False
    
    def _handle_security_violation(self, client_ip):
        """Handle detected security violation with auto-ban logic."""
        path = request.path
        user_agent = request.headers.get('User-Agent', 'Unknown')
        
        # Log security violation with more context
        logger.warning(
            f"SECURITY VIOLATION DETECTED: IP={client_ip}, Path={path}, "
            f"Method={request.method}, User-Agent={user_agent}, "
            f"Query={request.query_string.decode()}"
        )
        
        # Track attack attempt for this IP
        self.rate_limiter.record_attack(client_ip)
        
        # Don't blacklist private/local IPs to avoid blocking legitimate internal traffic
        if not is_private_ip(client_ip):
            # Check if auto-ban should be triggered
            from flask import current_app
            auto_ban_enabled = current_app.config.get('SECURITY_AUTO_BAN_ENABLED', True)
            attack_threshold = current_app.config.get('SECURITY_AUTO_BAN_ATTACK_THRESHOLD', 3)
            
            attack_count = self.rate_limiter.attack_counts.get(client_ip, 0)
            
            if auto_ban_enabled and attack_count >= attack_threshold:
                # Trigger auto-ban
                ban_duration = current_app.config.get('SECURITY_AUTO_BAN_DURATION_HOURS', 1) * 3600
                self.rate_limiter.auto_ban_ip(client_ip, ban_duration)
                logger.warning(f"AUTO-BAN TRIGGERED: IP {client_ip} banned for {ban_duration/3600} hours after {attack_count} attacks")
                
                # Store in database for persistence
                self._store_security_ban(client_ip, ban_duration, f"Auto-ban after {attack_count} attack attempts")
            else:
                # Add to temporary blacklist (shorter duration)
                self.rate_limiter.blacklist_ip(client_ip, duration=1800)  # 30 minutes
                logger.info(f"IP {client_ip} temporarily blacklisted (attack #{attack_count})")
        else:
            logger.info(f"Skipping blacklist for private IP {client_ip}")
        
        # Store security event for dashboard
        self._store_security_event(client_ip, 'attack_detected', 'high', 
                                 f"Attack pattern detected in {path}")
        
        # Return 404 to avoid revealing attack detection (matches your current behavior)
        abort(404)
    
    def _store_security_ban(self, ip, duration_seconds, reason):
        """Store auto-ban in database for persistence."""
        try:
            from app.models.security import IPBan
            duration_hours = duration_seconds / 3600
            IPBan.ban_ip(ip, duration_hours=duration_hours, reason=reason, 
                        banned_by="SYSTEM_AUTO_BAN", is_permanent=False)
            logger.info(f"Stored auto-ban for {ip} in database")
        except Exception as e:
            logger.error(f"Failed to store security ban in database: {e}")
    
    def _store_security_event(self, ip, event_type, severity, description):
        """Store security event for dashboard display."""
        try:
            from app.models.security import SecurityEvent
            SecurityEvent.create(
                ip_address=ip,
                event_type=event_type,
                severity=severity,
                description=description,
                user_agent=request.headers.get('User-Agent', 'Unknown'),
                path=request.path,
                method=request.method
            )
            logger.info(f"Stored security event: {event_type} for {ip}")
        except Exception as e:
            logger.error(f"Failed to store security event: {e}")
    
    def get_stats(self):
        """Get current security statistics for dashboard (excludes private/internal IPs)."""
        # Only count external IPs in statistics
        external_ips_with_requests = [ip for ip in self.rate_limiter.requests.keys() if not is_private_ip(ip)]
        external_ips_blacklisted = [ip for ip in self.rate_limiter.blacklist.keys() if not is_private_ip(ip)]
        external_attack_attempts = sum(count for ip, count in self.rate_limiter.attack_counts.items() if not is_private_ip(ip))
        external_attackers = len([ip for ip, count in self.rate_limiter.attack_counts.items() if count > 0 and not is_private_ip(ip)])
        
        return {
            'total_monitored_ips': len(external_ips_with_requests),
            'total_blacklisted_ips': len(external_ips_blacklisted),
            'total_attack_attempts': external_attack_attempts,
            'unique_attackers': external_attackers
        }
    
    def get_monitored_ips(self):
        """Get list of currently monitored IPs with request counts (excludes private/internal IPs)."""
        current_time = time.time()
        monitored = []
        
        for ip, requests in self.rate_limiter.requests.items():
            # Skip private/internal IPs completely
            if is_private_ip(ip):
                continue
                
            # Count requests in last hour
            recent_requests = sum(1 for req_time in requests if current_time - req_time <= 3600)
            attack_count = self.rate_limiter.attack_counts.get(ip, 0)
            is_banned = ip in self.rate_limiter.blacklist
            
            # Only include if there's meaningful activity
            if recent_requests > 0 or attack_count > 0 or is_banned:
                monitored.append({
                    'ip': ip,
                    'requests_last_hour': recent_requests,
                    'attack_attempts': attack_count,
                    'is_blacklisted': is_banned,
                    'blacklist_expires': self.rate_limiter.blacklist.get(ip, 0) if is_banned else None
                })
        
        return sorted(monitored, key=lambda x: x['requests_last_hour'], reverse=True)
    
    def security_response(self, response):
        """Add security headers to response."""
        if not request.path.startswith('/static/'):
            # Add security headers
            response.headers.update({
                'X-Content-Type-Options': 'nosniff',
                'X-Frame-Options': 'DENY',
                'X-XSS-Protection': '1; mode=block',
                'Referrer-Policy': 'strict-origin-when-cross-origin',
                'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
            })
        
        return response


class RequestRateLimiter:
    """Simple in-memory rate limiter with auto-ban capabilities."""
    
    def __init__(self):
        self.requests = defaultdict(deque)
        self.blacklist = {}
        self.attack_counts = defaultdict(int)  # Track attack attempts per IP
        self.cleanup_interval = 300  # 5 minutes
        self.last_cleanup = time.time()
        logger.info("RequestRateLimiter initialized with auto-ban capabilities")
    
    def allow_request(self, ip, limit=100, window=3600):
        """Check if request from IP should be allowed."""
        current_time = time.time()
        
        # Clean up old entries periodically
        if current_time - self.last_cleanup > self.cleanup_interval:
            self._cleanup_old_entries()
        
        # Check database for persistent bans first
        try:
            from app.models import IPBan
            if IPBan.is_ip_banned(ip):
                return False
        except:
            pass  # Don't fail if database is unavailable
        
        # Check if IP is blacklisted in memory
        if ip in self.blacklist:
            if current_time < self.blacklist[ip]:
                return False
            else:
                del self.blacklist[ip]
        
        # Check rate limit
        ip_requests = self.requests[ip]
        
        # Remove old requests outside the window
        while ip_requests and ip_requests[0] < current_time - window:
            ip_requests.popleft()
        
        # Check if limit exceeded
        if len(ip_requests) >= limit:
            logger.warning(f"Rate limit exceeded for IP {ip}: {len(ip_requests)} requests")
            return False
        
        # Add current request
        ip_requests.append(current_time)
        return True
    
    def record_attack(self, ip):
        """Record an attack attempt from an IP address."""
        self.attack_counts[ip] += 1
        logger.warning(f"Attack #{self.attack_counts[ip]} recorded for IP {ip}")
    
    def blacklist_ip(self, ip, duration=3600):
        """Temporarily blacklist an IP address."""
        self.blacklist[ip] = time.time() + duration
        logger.info(f"IP {ip} blacklisted for {duration} seconds")
    
    def auto_ban_ip(self, ip, duration=3600):
        """Auto-ban an IP address with escalation logic."""
        from flask import current_app
        
        # Check if escalation is enabled
        escalation_enabled = current_app.config.get('SECURITY_AUTO_BAN_ESCALATION_ENABLED', True)
        max_duration = current_app.config.get('SECURITY_AUTO_BAN_MAX_DURATION_HOURS', 168) * 3600
        
        if escalation_enabled:
            # Escalate ban duration for repeat offenders
            current_ban_time = self.blacklist.get(ip, 0)
            if current_ban_time > time.time():
                # IP is already banned, escalate the duration
                remaining_time = current_ban_time - time.time()
                new_duration = min(duration * 2, max_duration)  # Double the ban time, up to max
                logger.info(f"Escalating ban for repeat offender {ip}: {new_duration/3600} hours")
            else:
                new_duration = duration
        else:
            new_duration = duration
        
        # Apply the ban
        self.blacklist[ip] = time.time() + new_duration
        logger.warning(f"IP {ip} AUTO-BANNED for {new_duration/3600} hours")
    
    def _cleanup_old_entries(self):
        """Remove old rate limiting entries."""
        current_time = time.time()
        window = 3600  # 1 hour
        
        # Clean up request history
        for ip in list(self.requests.keys()):
            ip_requests = self.requests[ip]
            while ip_requests and ip_requests[0] < current_time - window:
                ip_requests.popleft()
            
            # Remove empty entries
            if not ip_requests:
                del self.requests[ip]
        
        # Clean up expired blacklist entries
        expired_ips = [
            ip for ip, expiry in self.blacklist.items()
            if current_time >= expiry
        ]
        for ip in expired_ips:
            del self.blacklist[ip]
        
        self.last_cleanup = current_time


def require_api_key(f):
    """Decorator to require API key for sensitive endpoints."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        expected_key = current_app.config.get('API_KEY')
        
        if not api_key or not expected_key or api_key != expected_key:
            logger.warning(f"Invalid API key attempt from {request.remote_addr}")
            abort(401)
        
        return f(*args, **kwargs)
    return decorated_function


def log_suspicious_activity(message, **kwargs):
    """Log suspicious activity with context."""
    context = {
        'ip': request.remote_addr if request else 'unknown',
        'user_agent': request.headers.get('User-Agent') if request else 'unknown',
        'path': request.path if request else 'unknown',
        **kwargs
    }
    
    logger.warning(f"SUSPICIOUS ACTIVITY: {message} - {context}")