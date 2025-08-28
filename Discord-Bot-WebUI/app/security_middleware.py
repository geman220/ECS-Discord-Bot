"""
Security middleware for Flask application.
Provides protection against common web application attacks.
Compatible with existing ECS Discord Bot infrastructure.
"""
import re
import time
import logging
from collections import defaultdict, deque
from flask import request, abort, g, current_app
from werkzeug.exceptions import TooManyRequests
from functools import wraps

logger = logging.getLogger(__name__)

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
            # Skip checks for static files, health checks, and API monitoring
            if (request.path.startswith('/static/') or 
                request.path.startswith('/test/status/') or
                request.path in ['/health', '/healthcheck']):
                return
            
            # Get client IP (handle proxy headers from Traefik)
            client_ip = self._get_client_ip()
            
            # Rate limiting check (more lenient for legitimate traffic)
            if not self.rate_limiter.allow_request(client_ip, limit=200, window=3600):
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
        """Handle detected security violation."""
        path = request.path
        user_agent = request.headers.get('User-Agent', 'Unknown')
        
        # Log security violation with more context
        logger.warning(
            f"SECURITY VIOLATION DETECTED: IP={client_ip}, Path={path}, "
            f"Method={request.method}, User-Agent={user_agent}, "
            f"Query={request.query_string.decode()}"
        )
        
        # Add IP to temporary blacklist (shorter duration for less disruption)
        self.rate_limiter.blacklist_ip(client_ip, duration=1800)  # 30 minutes
        
        # Return 404 to avoid revealing attack detection (matches your current behavior)
        abort(404)
    
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
    """Simple in-memory rate limiter."""
    
    def __init__(self):
        self.requests = defaultdict(deque)
        self.blacklist = {}
        self.cleanup_interval = 300  # 5 minutes
        self.last_cleanup = time.time()
    
    def allow_request(self, ip, limit=100, window=3600):
        """Check if request from IP should be allowed."""
        current_time = time.time()
        
        # Clean up old entries periodically
        if current_time - self.last_cleanup > self.cleanup_interval:
            self._cleanup_old_entries()
        
        # Check if IP is blacklisted
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
    
    def blacklist_ip(self, ip, duration=3600):
        """Temporarily blacklist an IP address."""
        self.blacklist[ip] = time.time() + duration
        logger.info(f"IP {ip} blacklisted for {duration} seconds")
    
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