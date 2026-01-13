"""
Log Sanitization Utility.

Provides functions to mask sensitive data before logging to prevent
accidental exposure of PII, tokens, and other sensitive information.
"""

import re
from typing import Any, Dict, Optional, Set

# Keys that should always be redacted in session/dict logging
SENSITIVE_KEYS: Set[str] = {
    'oauth_state',
    'sms_confirmation_code',
    'confirmation_code',
    'pending_discord_email',
    'pending_discord_id',
    'csrf_token',
    '_csrf_token',
    'password',
    'secret',
    'token',
    'api_key',
    'access_token',
    'refresh_token',
    'authorization',
}


def mask_phone(phone: Optional[str]) -> str:
    """
    Mask a phone number, showing only the last 4 digits.

    Args:
        phone: Phone number to mask

    Returns:
        Masked phone number (e.g., '***-***-1234')

    Example:
        >>> mask_phone('+1-555-123-4567')
        '***-***-4567'
    """
    if not phone:
        return '****'

    # Remove non-digit characters for consistent masking
    digits_only = re.sub(r'\D', '', phone)

    if len(digits_only) >= 4:
        return f"***-***-{digits_only[-4:]}"
    else:
        return '****'


def mask_email(email: Optional[str]) -> str:
    """
    Mask an email address, showing only first char and domain.

    Args:
        email: Email address to mask

    Returns:
        Masked email (e.g., 'j***@example.com')

    Example:
        >>> mask_email('john.doe@example.com')
        'j***@example.com'
    """
    if not email or '@' not in email:
        return '***@***'

    local, domain = email.rsplit('@', 1)
    if local:
        return f"{local[0]}***@{domain}"
    return f"***@{domain}"


def mask_code(code: Optional[str]) -> str:
    """
    Mask a confirmation/verification code completely.

    Args:
        code: The code to mask

    Returns:
        Masked code (always '******')
    """
    if not code:
        return None
    return '******'


def mask_token(token: Optional[str], visible_chars: int = 8) -> str:
    """
    Mask a token, showing only the first few characters.

    Args:
        token: The token to mask
        visible_chars: Number of characters to show (default 8)

    Returns:
        Masked token (e.g., 'abc12345...')

    Example:
        >>> mask_token('abcdefghijklmnop')
        'abcdefgh...'
    """
    if not token:
        return None

    if len(token) <= visible_chars:
        return '***'

    return f"{token[:visible_chars]}..."


def mask_url(url: Optional[str]) -> str:
    """
    Mask sensitive parameters in a URL.

    Removes or masks common sensitive query parameters like
    state, token, code, key, etc.

    Args:
        url: The URL to mask

    Returns:
        URL with sensitive parameters masked
    """
    if not url:
        return None

    # Patterns to mask in URLs
    patterns = [
        (r'state=[^&]+', 'state=<redacted>'),
        (r'code=[^&]+', 'code=<redacted>'),
        (r'token=[^&]+', 'token=<redacted>'),
        (r'key=[^&]+', 'key=<redacted>'),
        (r'secret=[^&]+', 'secret=<redacted>'),
        (r'password=[^&]+', 'password=<redacted>'),
        (r'access_token=[^&]+', 'access_token=<redacted>'),
    ]

    result = url
    for pattern, replacement in patterns:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

    return result


def mask_session(session_dict: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Create a safe version of a session dictionary for logging.

    Redacts sensitive keys and truncates long values.

    Args:
        session_dict: The session dictionary to sanitize

    Returns:
        Sanitized dictionary safe for logging
    """
    if not session_dict:
        return {}

    safe_dict = {}
    for key, value in session_dict.items():
        key_lower = key.lower()

        # Check if key is sensitive
        is_sensitive = any(
            sensitive in key_lower
            for sensitive in SENSITIVE_KEYS
        )

        if is_sensitive:
            safe_dict[key] = '<redacted>'
        elif isinstance(value, str):
            # Truncate long strings
            if len(value) > 20:
                safe_dict[key] = f"{value[:20]}..."
            else:
                safe_dict[key] = value
        elif isinstance(value, dict):
            # Recursively sanitize nested dicts
            safe_dict[key] = mask_session(value)
        else:
            safe_dict[key] = value

    return safe_dict


def safe_log_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sanitize a dictionary for safe logging.

    Similar to mask_session but for general dictionaries.

    Args:
        data: Dictionary to sanitize

    Returns:
        Sanitized dictionary
    """
    return mask_session(data)


def get_safe_session_keys(session_dict: Optional[Dict[str, Any]]) -> str:
    """
    Get just the keys from a session for logging.

    This is the safest option - only log which keys exist,
    not their values.

    Args:
        session_dict: The session dictionary

    Returns:
        String representation of session keys
    """
    if not session_dict:
        return '[]'
    return str(list(session_dict.keys()))
