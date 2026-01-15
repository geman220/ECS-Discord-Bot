"""
URL Validation Utility for SSRF Prevention.

Validates URLs to prevent Server-Side Request Forgery attacks while allowing
access to specific internal Docker services needed for admin testing.
"""

import ipaddress
import socket
import logging
from urllib.parse import urlparse
from typing import Optional, Set, Dict, List

logger = logging.getLogger(__name__)

# Allowlisted internal Docker services (from docker-compose.yml)
# Format: hostname -> list of allowed ports
ALLOWED_INTERNAL_HOSTS: Dict[str, List[int]] = {
    'flower': [5555],           # Celery monitoring dashboard
    'discord-bot': [5001],      # Bot health endpoint
    'webui': [5000],            # Self-testing
    'redis': [6379],            # Redis cache (if HTTP needed)
}

# Private/internal IP ranges to block for external URLs
BLOCKED_IP_RANGES = [
    ipaddress.ip_network('10.0.0.0/8'),       # Private Class A
    ipaddress.ip_network('172.16.0.0/12'),    # Private Class B (Docker default)
    ipaddress.ip_network('192.168.0.0/16'),   # Private Class C
    ipaddress.ip_network('127.0.0.0/8'),      # Localhost
    ipaddress.ip_network('169.254.0.0/16'),   # Link-local / Cloud metadata
    ipaddress.ip_network('::1/128'),          # IPv6 localhost
    ipaddress.ip_network('fc00::/7'),         # IPv6 private
    ipaddress.ip_network('fe80::/10'),        # IPv6 link-local
]

# Always block these hostnames (cloud metadata endpoints)
BLOCKED_HOSTNAMES: Set[str] = {
    'metadata.google.internal',
    '169.254.169.254',              # AWS/GCP/Azure metadata
    'metadata.azure.com',
    'kubernetes.default.svc',
    'kubernetes.default',
}

# Allowed URL schemes
ALLOWED_SCHEMES: Set[str] = {'http', 'https'}


class SSRFValidationError(Exception):
    """Raised when URL validation fails due to SSRF risk."""
    pass


def _is_ip_in_blocked_range(ip_str: str) -> bool:
    """Check if an IP address is in any blocked range."""
    try:
        ip = ipaddress.ip_address(ip_str)
        for blocked_range in BLOCKED_IP_RANGES:
            if ip in blocked_range:
                return True
        return False
    except ValueError:
        return False


def _resolve_hostname_ips(hostname: str) -> List[str]:
    """Resolve a hostname to its IP addresses."""
    try:
        results = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        return list(set(sockaddr[0] for _, _, _, _, sockaddr in results))
    except socket.gaierror:
        return []


def validate_url_for_ssrf(url: str) -> bool:
    """
    Validate a URL to prevent SSRF attacks.

    Allows:
    - External URLs that don't resolve to private IP ranges
    - Specific internal Docker services defined in ALLOWED_INTERNAL_HOSTS

    Blocks:
    - Cloud metadata endpoints
    - Private IP ranges (unless explicitly allowlisted)
    - Non-http/https schemes

    Args:
        url: The URL to validate

    Returns:
        True if URL is safe to request

    Raises:
        SSRFValidationError: If URL poses SSRF risk
    """
    if not url:
        raise SSRFValidationError("URL is required")

    # Parse URL
    try:
        parsed = urlparse(url)
    except Exception as e:
        raise SSRFValidationError(f"Invalid URL format: {e}")

    # Check scheme
    scheme = (parsed.scheme or '').lower()
    if scheme not in ALLOWED_SCHEMES:
        raise SSRFValidationError(
            f"Scheme '{scheme}' not allowed. Use http or https."
        )

    # Get hostname
    hostname = parsed.hostname
    if not hostname:
        raise SSRFValidationError("URL must contain a hostname")

    hostname_lower = hostname.lower()

    # Get port (default based on scheme)
    port = parsed.port
    if port is None:
        port = 443 if scheme == 'https' else 80

    # Check for blocked hostnames (cloud metadata)
    if hostname_lower in BLOCKED_HOSTNAMES:
        logger.warning(f"SSRF blocked: metadata endpoint {hostname}")
        raise SSRFValidationError(f"Hostname '{hostname}' is blocked (metadata endpoint)")

    # Check for blocked hostname patterns
    for blocked in BLOCKED_HOSTNAMES:
        if hostname_lower.endswith('.' + blocked):
            logger.warning(f"SSRF blocked: metadata subdomain {hostname}")
            raise SSRFValidationError(f"Hostname '{hostname}' is blocked")

    # Check if it's an allowed internal Docker service
    if hostname_lower in ALLOWED_INTERNAL_HOSTS:
        allowed_ports = ALLOWED_INTERNAL_HOSTS[hostname_lower]
        if port in allowed_ports:
            logger.debug(f"SSRF allowed: internal service {hostname}:{port}")
            return True
        else:
            raise SSRFValidationError(
                f"Port {port} not allowed for internal service '{hostname}'. "
                f"Allowed ports: {allowed_ports}"
            )

    # For external URLs, resolve hostname and check IP ranges
    ip_addresses = _resolve_hostname_ips(hostname)

    if not ip_addresses:
        raise SSRFValidationError(f"Could not resolve hostname: {hostname}")

    for ip_str in ip_addresses:
        if _is_ip_in_blocked_range(ip_str):
            logger.warning(f"SSRF blocked: {hostname} resolves to private IP {ip_str}")
            raise SSRFValidationError(
                f"URL resolves to blocked IP range. "
                f"Only external URLs or allowlisted internal services are permitted."
            )

    logger.debug(f"SSRF validated: external URL {url}")
    return True


def is_url_safe(url: str) -> bool:
    """
    Check if a URL is safe without raising an exception.

    Args:
        url: The URL to check

    Returns:
        True if URL is safe, False otherwise
    """
    try:
        return validate_url_for_ssrf(url)
    except SSRFValidationError:
        return False
