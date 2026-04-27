# app/utils/deferred_cache.py

"""
Deferred Cache Invalidation Module

Queue cache-clear calls during a request and dispatch them via
after_this_request, so Redis I/O happens AFTER the @transactional
decorator commits. Keeps DB row locks short.

Mirrors the pattern in app/utils/deferred_audit.py and
app/utils/deferred_discord.py.
"""

import logging
from typing import List, Optional, Set

from flask import g, has_request_context, after_this_request

logger = logging.getLogger(__name__)


def _flush(leagues: Set[Optional[str]]) -> int:
    """Run the queued cache clears synchronously."""
    from app.draft_cache_service import DraftCacheService

    deleted = 0
    for league in leagues:
        try:
            deleted += DraftCacheService.clear_all_league_caches(league) or 0
        except Exception as e:
            logger.warning(f"Deferred cache clear failed for league={league!r}: {e}")
    return deleted


def defer_clear_league_cache(league_name: Optional[str] = None) -> None:
    """
    Queue a draft-cache clear for the given league name. Dispatched after
    the request commits.

    Pass `None` to clear all leagues. Multiple calls within a request are
    de-duplicated.

    Outside a request context (Celery tasks, scripts) the clear runs
    immediately.
    """
    if not has_request_context():
        _flush({league_name})
        return

    if not hasattr(g, '_deferred_cache_clears'):
        g._deferred_cache_clears = set()

        @after_this_request
        def _dispatch_deferred_cache(response):
            if 200 <= response.status_code < 300:
                pending: Set[Optional[str]] = g._deferred_cache_clears
                if pending:
                    _flush(pending)
            else:
                g._deferred_cache_clears.clear()
            return response

    g._deferred_cache_clears.add(league_name)


def clear_deferred_cache() -> None:
    """Drop any queued cache clears for the current request."""
    if has_request_context() and hasattr(g, '_deferred_cache_clears'):
        g._deferred_cache_clears.clear()
