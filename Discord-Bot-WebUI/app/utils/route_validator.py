# app/utils/route_validator.py

"""
AI Response URL Validator

Scans AI assistant responses for markdown links and bare URLs,
validates them against Flask's actual route map, and fixes or
strips invalid URLs to prevent hallucinated links.
"""

import difflib
import logging
import re
import time

logger = logging.getLogger(__name__)

# Cache for valid routes (rebuilt every 5 minutes)
_route_cache = {
    'routes': set(),
    'prefixes': set(),
    'timestamp': 0,
}
_CACHE_TTL = 300  # 5 minutes


def _normalize_url(url):
    """Normalize a URL for comparison: strip trailing slash (except root)."""
    if url and url != '/':
        return url.rstrip('/')
    return url


def _build_route_set():
    """Build a set of all valid routes from Flask's URL map + admin search index."""
    from flask import current_app

    routes = set()
    prefixes = set()

    for rule in current_app.url_map.iter_rules():
        if 'GET' not in rule.methods:
            continue

        url = rule.rule

        # Skip static files
        if url.startswith('/static'):
            continue

        if '<' in url:
            # Parameterized route: extract prefix up to first parameter
            prefix = url[:url.index('<')].rstrip('/')
            if prefix and len(prefix) > 1:
                prefixes.add(prefix)
        else:
            # Store both normalized and original to handle trailing slash variants
            routes.add(_normalize_url(url))

    # Merge admin search index URLs (most reliable, uses url_for())
    try:
        from app.admin_panel import _build_admin_search_index
        for item in _build_admin_search_index():
            if item.get('url'):
                routes.add(_normalize_url(item['url']))
    except Exception:
        pass

    return routes, prefixes


def _get_valid_routes():
    """Get cached set of valid routes, rebuilding if stale."""
    now = time.time()
    if now - _route_cache['timestamp'] > _CACHE_TTL:
        try:
            routes, prefixes = _build_route_set()
            _route_cache['routes'] = routes
            _route_cache['prefixes'] = prefixes
            _route_cache['timestamp'] = now
        except Exception as e:
            logger.warning(f"Failed to rebuild route cache: {e}")
    return _route_cache['routes'], _route_cache['prefixes']


def _is_valid_url(url, valid_routes, valid_prefixes):
    """Check if a URL matches a known route (exact or prefix for parameterized routes)."""
    normalized = _normalize_url(url)

    if normalized in valid_routes:
        return True

    # Check prefix match (for parameterized routes like /players/123)
    for prefix in valid_prefixes:
        if normalized.startswith(prefix):
            return True

    return False


def _find_closest_route(url, valid_routes):
    """Find the closest matching valid route using fuzzy matching.

    Uses suffix validation to prevent false corrections caused by long shared
    prefixes inflating the similarity ratio. For example, /admin-panel/discord/settings
    has a 0.80 full-path ratio with /admin-panel/discord/roles (because they share
    /admin-panel/discord/), but the suffix ratio is only 0.15 — a clear mismatch.
    """
    normalized = _normalize_url(url)

    # High cutoff (0.90) ensures we only correct near-typos, not conceptual mismatches.
    # Admin-panel URLs share long prefixes that inflate similarity scores:
    #   /admin-panel/discord/settings vs /admin-panel/mls/settings = 0.85 (WRONG match)
    #   /admin-panel/user-management vs /admin-panel/users-management = 0.98 (correct typo fix)
    # The 0.90 cutoff cleanly separates these cases.
    matches = difflib.get_close_matches(normalized, valid_routes, n=1, cutoff=0.90)
    if not matches:
        return None

    candidate = matches[0]

    # Second layer: validate the differing suffix after shared path segments.
    # Catches edge cases the high cutoff alone might miss.
    url_parts = normalized.strip('/').split('/')
    candidate_parts = candidate.strip('/').split('/')

    common_depth = 0
    for u, c in zip(url_parts, candidate_parts):
        if u == c:
            common_depth += 1
        else:
            break

    url_suffix = '/'.join(url_parts[common_depth:])
    candidate_suffix = '/'.join(candidate_parts[common_depth:])

    if url_suffix and candidate_suffix:
        suffix_ratio = difflib.SequenceMatcher(None, url_suffix, candidate_suffix).ratio()
        if suffix_ratio < 0.5:
            return None

    return candidate


# Regex patterns for extracting URLs from AI responses
_MARKDOWN_LINK_RE = re.compile(r'\[([^\]]+)\]\((/[^)]+)\)')

# General bare URL pattern: matches any /path that looks like a portal route
# Uses negative lookbehinds to skip URLs already inside markdown links
# Note: all lookbehinds are fixed-width (1 char) for Python re compatibility
_BARE_URL_RE = re.compile(
    r'(?<!\()'       # not preceded by ( (markdown link URL)
    r'(?<!\[)'       # not preceded by [
    r'(?<![/\w])'    # not preceded by another path char (avoids partial matches)
    r'(/[a-z][a-z0-9_-]*(?:/[a-z0-9_-]+)+)'  # /path/with/at-least-two-segments
    r'(?=[\s.,;:!?)"\']|$)',  # followed by whitespace, punctuation, or end
    re.MULTILINE
)


def validate_response_urls(response_text):
    """Scan an AI response for URLs and validate them against Flask's route map.

    Returns:
        tuple: (cleaned_response, urls_fixed, urls_stripped)
    """
    valid_routes, valid_prefixes = _get_valid_routes()

    if not valid_routes:
        # Cache not populated (e.g., outside app context) - pass through
        return response_text, 0, 0

    urls_fixed = 0
    urls_stripped = 0

    # Pass 1: Validate markdown links [text](url)
    def fix_markdown_link(match):
        nonlocal urls_fixed, urls_stripped
        link_text = match.group(1)
        url = match.group(2)

        if _is_valid_url(url, valid_routes, valid_prefixes):
            return match.group(0)  # Valid, keep as-is

        # Try fuzzy match
        closest = _find_closest_route(url, valid_routes)
        if closest:
            urls_fixed += 1
            logger.info(f"AI URL corrected: {url} -> {closest}")
            return f'[{link_text}]({closest})'

        # No match found - strip the link, keep the text
        urls_stripped += 1
        logger.info(f"AI URL stripped (no match): {url}")
        return f'**{link_text}** (try searching for this in the top navbar search bar)'

    result = _MARKDOWN_LINK_RE.sub(fix_markdown_link, response_text)

    # Pass 2: Validate bare URLs not already inside markdown links
    # Re-scan the result (which now has fixed/stripped markdown links)
    def fix_bare_url(match):
        nonlocal urls_fixed, urls_stripped
        url = match.group(1)

        # Skip very short paths that are likely false positives
        if len(url) < 3 or url.count('/') < 1:
            return match.group(0)

        if _is_valid_url(url, valid_routes, valid_prefixes):
            return match.group(0)

        closest = _find_closest_route(url, valid_routes)
        if closest:
            urls_fixed += 1
            logger.info(f"AI bare URL corrected: {url} -> {closest}")
            return match.group(0).replace(url, closest)

        urls_stripped += 1
        logger.info(f"AI bare URL stripped (no match): {url}")
        return match.group(0).replace(url, f'{url} (this page may not exist)')

    result = _BARE_URL_RE.sub(fix_bare_url, result)

    if urls_fixed or urls_stripped:
        logger.info(f"AI response URL validation: {urls_fixed} fixed, {urls_stripped} stripped")

    return result, urls_fixed, urls_stripped
