"""
Path Validation Utility for Path Traversal Prevention.

Ensures file paths stay within allowed directories to prevent
directory traversal attacks (e.g., ../../etc/passwd).
"""

import os
import logging
from pathlib import Path
from typing import Union

logger = logging.getLogger(__name__)


class PathTraversalError(Exception):
    """Raised when a path traversal attempt is detected."""
    pass


def validate_path_within_directory(
    file_path: Union[str, Path],
    base_directory: Union[str, Path]
) -> str:
    """
    Validate that a file path stays within the allowed base directory.

    Uses os.path.realpath() to resolve symlinks and normalize the path,
    then verifies the resolved path is within the base directory.

    Args:
        file_path: The file path to validate
        base_directory: The allowed base directory

    Returns:
        The resolved absolute path if valid

    Raises:
        PathTraversalError: If path escapes base directory
    """
    # Convert to strings if Path objects
    file_path_str = str(file_path)
    base_dir_str = str(base_directory)

    # Resolve both paths to absolute, following symlinks
    base_abs = os.path.realpath(base_dir_str)
    file_abs = os.path.realpath(file_path_str)

    # Ensure base directory ends with separator for proper prefix matching
    # This prevents /app/static matching /app/staticfiles
    base_with_sep = base_abs + os.sep

    # Check if file path is within base directory
    # Allow exact match or path starting with base + separator
    if file_abs != base_abs and not file_abs.startswith(base_with_sep):
        logger.warning(
            f"Path traversal attempt detected: '{file_path_str}' "
            f"resolves to '{file_abs}' which is outside '{base_abs}'"
        )
        raise PathTraversalError(
            f"Path is not within the allowed directory"
        )

    return file_abs


def safe_join_path(
    base_directory: Union[str, Path],
    *path_components: str
) -> str:
    """
    Safely join path components and validate the result.

    This is a drop-in replacement for os.path.join() that validates
    the resulting path stays within the base directory.

    Args:
        base_directory: The base directory (must be trusted)
        *path_components: Path components to join (may be untrusted)

    Returns:
        Safe absolute path within base directory

    Raises:
        PathTraversalError: If resulting path escapes base directory

    Example:
        # Safe usage:
        path = safe_join_path('/app/uploads', user_filename)

        # This will raise PathTraversalError:
        path = safe_join_path('/app/uploads', '../../../etc/passwd')
    """
    # Join the paths
    joined = os.path.join(str(base_directory), *path_components)

    # Validate the result
    return validate_path_within_directory(joined, base_directory)


def is_path_safe(
    file_path: Union[str, Path],
    base_directory: Union[str, Path]
) -> bool:
    """
    Check if a path is safe without raising an exception.

    Args:
        file_path: The file path to check
        base_directory: The allowed base directory

    Returns:
        True if path is safe, False otherwise
    """
    try:
        validate_path_within_directory(file_path, base_directory)
        return True
    except PathTraversalError:
        return False


def sanitize_filename(filename: str) -> str:
    """
    Sanitize a filename by removing path separators and dangerous characters.

    This is more aggressive than werkzeug's secure_filename() and ensures
    the filename cannot contain any path traversal sequences.

    Args:
        filename: The filename to sanitize

    Returns:
        Sanitized filename safe for use in file paths
    """
    if not filename:
        return ''

    # Get just the basename (removes any path components)
    filename = os.path.basename(filename)

    # Remove null bytes
    filename = filename.replace('\x00', '')

    # Remove any remaining path separators (shouldn't exist after basename)
    filename = filename.replace('/', '').replace('\\', '')

    # Remove leading dots to prevent hidden files
    filename = filename.lstrip('.')

    # If nothing left, return empty string
    if not filename:
        return ''

    return filename


def validate_url_path_component(url_path: str, allowed_prefix: str) -> str:
    """
    Validate a URL path component (e.g., from /static/...).

    Used for validating URL paths that will be converted to file paths.
    Prevents traversal via URL-encoded sequences or path manipulation.

    Args:
        url_path: The URL path to validate (e.g., '/static/img/photo.jpg')
        allowed_prefix: Required prefix (e.g., '/static/')

    Returns:
        The validated path component after the prefix

    Raises:
        PathTraversalError: If path doesn't start with prefix or contains traversal
    """
    # Normalize the URL path
    # Note: We don't use urllib.parse.unquote here because the web framework
    # should have already decoded the URL. Double-decoding could enable attacks.

    if not url_path.startswith(allowed_prefix):
        raise PathTraversalError(
            f"URL path must start with '{allowed_prefix}'"
        )

    # Get the path after the prefix
    relative_path = url_path[len(allowed_prefix):]

    # Check for traversal sequences
    # These checks are case-insensitive for Windows compatibility
    dangerous_patterns = ['..', './', '.\\']
    path_lower = relative_path.lower()

    for pattern in dangerous_patterns:
        if pattern in path_lower:
            logger.warning(f"Path traversal attempt in URL: {url_path}")
            raise PathTraversalError(
                f"URL path contains forbidden pattern"
            )

    return relative_path
