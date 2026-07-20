# app/services/public_cache.py

"""
Public-site render cache + invalidation — the ONE cache path (Redis, shared
between the portal and publicweb containers, which is exactly what makes a
portal-side publish/flag-flip reflect on ecspubleague.org within seconds).

Design (from the approved plan, post-critique):
- Versioned keys, no explicit deletes: `public:html:<host>:<path>:g<G>:p<P>`
  where G = global version (bumped by appearance/menu/theme/flag changes that
  affect every page) and P = per-entity version (bumped by a single page/news
  publish). Old versions age out via TTL.
- Cache is only ever READ/WRITTEN for anonymous GETs in PUBLIC_ONLY mode
  (enforced by the caller in public_site.py) — never for editors, never for
  draft/edit renders, and form-bearing pages are bypassed entirely (their HTML
  embeds per-session CSRF tokens).
- Single-flight: a short Redis NX lock keeps a stampede (cold key + crawler
  burst) from re-rendering the same page on every worker at once; losers serve
  a short-stale copy when one exists.

bump_public_cache(scope, slug=None) is called from EVERY public-affecting
write: page/news publish, FAQ/menu/appearance/redirect/media saves, slug
renames, scheduled-publish beat task, and registration/waitlist flag flips.
"""

import logging

logger = logging.getLogger(__name__)

TTL_HTML = 300          # hard backstop; invalidation is version-based
TTL_STALE = 3600        # how long a superseded copy may serve during refill
_LOCK_TTL = 15

_G_KEY = 'public:ver:global'
_P_KEY = 'public:ver:{scope}:{slug}'


def _redis():
    try:
        from flask import current_app
        r = getattr(current_app, 'redis', None)
        if r is not None:
            return r
        from app.utils.redis_manager import UnifiedRedisManager
        return UnifiedRedisManager().client
    except Exception:
        return None


def _get_ver(r, key):
    try:
        return int(r.get(key) or 0)
    except Exception:
        return 0


def bump_public_cache(scope='global', slug=None):
    """Invalidate public renders IMMEDIATELY. scope: 'global' (flags/appearance/
    menu/theme/redirects) or 'page'/'news' with a slug. Use this only when the
    writing transaction has ALREADY committed (e.g. the scheduled beat task) —
    otherwise a concurrent reader can refill the cache with pre-commit data
    under the new version. In-request write handlers should use
    bump_public_cache_after_commit()."""
    r = _redis()
    if r is None:
        return
    try:
        if scope == 'global' or slug is None:
            r.incr(_G_KEY)
        else:
            r.incr(_P_KEY.format(scope=scope, slug=slug))
    except Exception:
        logger.warning('public cache bump failed (%s %s)', scope, slug, exc_info=True)


def bump_public_cache_after_commit(scope='global', slug=None):
    """Queue a cache invalidation to fire AFTER the current request's
    transaction commits, so publicweb never caches pre-commit rows under the
    post-write version key. No-op (falls back to immediate) outside a request.
    Safe to call many times per request — bumps are de-duped and drained once
    on commit."""
    try:
        from flask import g, has_request_context
        if not has_request_context() or getattr(g, 'db_session', None) is None:
            return bump_public_cache(scope, slug)
        session = g.db_session
        pending = g.__dict__.setdefault('_public_cache_bumps', set())
        pending.add((scope, slug))
        if not g.__dict__.get('_public_cache_listener'):
            from sqlalchemy import event

            def _drain(sess):
                for sc, sl in list(pending):
                    bump_public_cache(sc, sl)
                pending.clear()
            event.listen(session, 'after_commit', _drain)
            g.__dict__['_public_cache_listener'] = True
    except Exception:
        logger.warning('after-commit cache bump registration failed', exc_info=True)
        bump_public_cache(scope, slug)


def cache_key(host, path, scope='page', slug=None):
    r = _redis()
    if r is None:
        return None
    g = _get_ver(r, _G_KEY)
    p = _get_ver(r, _P_KEY.format(scope=scope, slug=slug)) if slug else 0
    return f'public:html:{host}:{path}:g{g}:p{p}'


def get_cached_html(key):
    if not key:
        return None
    r = _redis()
    if r is None:
        return None
    try:
        val = r.get(key)
        return val.decode() if isinstance(val, bytes) else val
    except Exception:
        return None


def store_html(key, html):
    if not key or html is None:
        return
    r = _redis()
    if r is None:
        return
    try:
        r.setex(key, TTL_HTML, html)
        # Keep a stale fallback copy for single-flight losers during refill.
        r.setex(key + ':stale', TTL_STALE, html)
    except Exception:
        logger.debug('public cache store failed', exc_info=True)


def acquire_render_lock(key):
    """True if this worker should render (single-flight); False = serve stale
    or fall through to a live render if no stale copy exists."""
    r = _redis()
    if r is None or not key:
        return True
    try:
        return bool(r.set(key + ':lock', '1', nx=True, ex=_LOCK_TTL))
    except Exception:
        return True


def get_stale_html(key):
    if not key:
        return None
    r = _redis()
    if r is None:
        return None
    try:
        val = r.get(key + ':stale')
        return val.decode() if isinstance(val, bytes) else val
    except Exception:
        return None


# ---- edit lock (one volunteer at a time per page) ------------------------- #

_EDIT_LOCK_KEY = 'site_editor_lock:{page_id}'
EDIT_LOCK_TTL = 60


def acquire_edit_lock(page_id, user_id, user_name, force=False):
    """Try to hold the page's edit lock. Returns (ok, holder_name). Heartbeat
    by calling again (refreshes TTL when you already hold it)."""
    r = _redis()
    if r is None:
        return True, None
    key = _EDIT_LOCK_KEY.format(page_id=page_id)
    val = f'{user_id}:{user_name}'
    try:
        current = r.get(key)
        current = current.decode() if isinstance(current, bytes) else current
        if current is None or force or current.split(':', 1)[0] == str(user_id):
            r.setex(key, EDIT_LOCK_TTL, val)
            return True, None
        return False, current.split(':', 1)[1] if ':' in current else 'another editor'
    except Exception:
        return True, None


def release_edit_lock(page_id, user_id):
    r = _redis()
    if r is None:
        return
    key = _EDIT_LOCK_KEY.format(page_id=page_id)
    try:
        current = r.get(key)
        current = current.decode() if isinstance(current, bytes) else current
        if current and current.split(':', 1)[0] == str(user_id):
            r.delete(key)
    except Exception:
        pass
