# app/public_redirects.py

"""
Legacy WordPress → new-site 301 redirects (SEO preservation).

Same domain (ecspubleague.org), so these are same-domain path→path 301s. The
map covers the paths that CHANGE in the rebuild; identical paths (/, /about/,
/faqs/, /news/, /register/, /contact/) need no redirect.

DORMANT until cutover: the hook only fires for the hosts in
``LEGACY_REDIRECT_HOSTS`` (default ecspubleague.org + www). On portal.ecsfc.com
it does a single host-string check and returns — zero behavior change on the
live portal, so this is safe to ship with the pre-cutover demo.

WP-legacy exploit-shaped paths (/wp-*, .php, /wp-content/) are intentionally NOT
handled here — the app's SecurityMiddleware bans those before this runs. If any
such legacy URL ever needs a 301, do it in Traefik redirectregex (before Flask),
per the infra notes.

Flask handles clean slugs and TEC event/venue paths fine (no WAF pattern match).
"""

import logging

from flask import request, redirect

logger = logging.getLogger(__name__)

# Hosts on which legacy redirects are active. Kept as a set for cheap lookup.
# Override via app.config['LEGACY_REDIRECT_HOSTS'] if needed.
DEFAULT_LEGACY_HOSTS = frozenset({'ecspubleague.org', 'www.ecspubleague.org'})

# News posts that WordPress served at the ROOT (e.g. /team-reveal-x/) now live
# under /news/<slug>. Keep this list in sync with the seeded post slugs.
_ROOT_POST_SLUGS = [
    'fall-2026-timeline', 'spring-2026-timeline', 'preseason-party',
    'fall-2025-information-for-new-players',
    'team-reveal-real-hellmouth', 'team-reveal-townsville-fc',
    'team-reveal-wasteland-wanderers', 'team-reveal-we-didnt-do-sht',
    'team-reveal-van-goal-fc', 'team-reveal-twin-pks', 'team-reveal-the-eh-team',
    'team-reveal-shire-united', 'team-reveal-pk-rangers', 'team-reveal-olymplinkos',
    'team-reveal-not-a-phase', 'team-reveal-nc-legends', 'team-reveal-miami-rice',
    'team-reveal-meepchester-united', 'team-reveal-if-you-aint-first-youre-last',
    'team-reveal-hex-appeal', 'team-reveal-futbol-heads', 'team-reveal-fellowship-fc',
    'team-reveal-fc-candy-kingdom', 'team-reveal-critical-goal',
    'team-reveal-cereal-killers', 'team-reveal-bob-loblaws-ball-lobbers',
    'team-reveal-banana-kicks-fc', 'team-reveal-average-goals',
]


def _build_static_map():
    """Exact-path (normalized, no trailing slash) → target endpoint/args."""
    m = {}
    # Blog posts: root slug -> /news/<slug>
    for slug in _ROOT_POST_SLUGS:
        m[f'/{slug}'] = ('public.news_detail', {'slug': slug})
    # Category archives -> news index
    for cat in ('announcements', 'events', 'news'):
        m[f'/category/{cat}'] = ('public.news_list', {})
    # The Events Calendar archive + tickets -> live public calendar.
    # Target the PUBLIC endpoint (public.calendar), not the portal-only
    # calendar.calendar_view — the latter isn't registered on publicweb and
    # would BuildError-500 the marketing host.
    m['/events'] = ('public.calendar', {})
    m['/tickets-checkout'] = ('public.home', {})
    m['/tickets-order'] = ('public.home', {})
    # Leftover WordPress RSS page in the sitemap -> news index (low value, real URL).
    m['/feed-2'] = ('public.news_list', {})
    # WordPress served the privacy policy at /privacy-policy/; the canonical route
    # is /privacy (legal_bp). 301 the old URL so the app-store/legal link survives.
    # (/terms/ needs no entry — /terms is a real route, handled by trailing-slash.)
    m['/privacy-policy'] = ('legal.privacy_policy', {})
    return m


_STATIC_MAP = _build_static_map()


def register_public_redirects(app):
    """Install the host-gated legacy redirect before_request hook."""
    hosts = frozenset(app.config.get('LEGACY_REDIRECT_HOSTS', DEFAULT_LEGACY_HOSTS))

    @app.before_request
    def _legacy_wp_redirects():
        # Only active on the migrated marketing domain(s). No-op everywhere else
        # (i.e. on portal.ecsfc.com the demo is unaffected).
        host = (request.host or '').split(':')[0].lower()
        if host not in hosts:
            return None
        if request.method not in ('GET', 'HEAD'):
            return None

        path = request.path or '/'
        norm = path.rstrip('/') or '/'

        # A legacy 301 must never 500 the marketing host: if the target endpoint
        # isn't registered (e.g. a portal-only endpoint under PUBLIC_ONLY), build
        # fails -> fall through to a normal 404 instead of a BuildError crash.
        def _safe_301(endpoint, **kwargs):
            from flask import url_for
            try:
                return redirect(url_for(endpoint, **kwargs), code=301)
            except Exception:
                return None

        # 1. Exact static map (posts, categories, events archive, tickets).
        target = _STATIC_MAP.get(norm)
        if target:
            r = _safe_301(target[0], **target[1])
            if r:
                return r

        # 2. Single TEC event pages: /event/<slug> -> /calendar
        elif norm.startswith('/event/'):
            r = _safe_301('public.calendar')
            if r:
                return r

        # 3. TEC venue/organizer taxonomy pages -> /calendar (thin content).
        #    Match the bare archive (/venue, /organizer) AND per-item pages: the
        #    sitemap emits a bare /venue/ archive root whose normalized form is
        #    '/venue', so a plain startswith('/venue/') would miss it and 404.
        elif norm == '/venue' or norm.startswith('/venue/') \
                or norm == '/organizer' or norm.startswith('/organizer'):
            r = _safe_301('public.calendar')
            if r:
                return r

        # 4. Trailing-slash canonicalization (SEO). WordPress served every page
        #    with a trailing slash (/about/, /guide/, /guests/, /faqs/, /news/…);
        #    the new routes are canonical no-slash and strict, so those legacy
        #    URLs would 404. 301 any remaining trailing-slash path to its no-slash
        #    form so no inbound link/crawler is lost. Runs AFTER the maps above so
        #    /events/ etc. already went straight to their real target. Root exempt.
        if len(path) > 1 and path.endswith('/'):
            canonical = path.rstrip('/')
            if request.query_string:
                canonical += '?' + request.query_string.decode('latin-1')
            return redirect(canonical, code=301)

        return None

    @app.before_request
    def _admin_managed_redirects():
        """Admin-editable 301s (RedirectRule table). Source/target are stored as
        ROOT-relative public paths; we strip/re-add the /preview prefix so a rule
        works both on the demo and after the ecspubleague.org cutover. Gated to
        public-site requests so it never touches portal traffic."""
        if request.method not in ('GET', 'HEAD'):
            return None
        path = request.path or '/'
        # This runs on every request — cheap-exit for asset/api/admin traffic
        # BEFORE any DB query (matters on the marketing host, where the host
        # gate below would otherwise let /static/... hit the DB per asset).
        if (request.endpoint == 'static' or path.startswith('/static')
                or path.startswith('/api') or path.startswith('/admin-panel')):
            return None
        host = (request.host or '').split(':')[0].lower()
        # Match the prefix precisely so /previewer, /preview-mode, etc. aren't
        # treated as the demo.
        on_preview = (path == '/preview' or path.startswith('/preview/'))
        if host not in hosts and not on_preview:
            return None
        pub = path[len('/preview'):] if on_preview else path
        pub = pub.rstrip('/') or '/'
        try:
            from app.models import RedirectRule
            rule = (RedirectRule.query
                    .filter_by(source_path=pub, is_active=True).first())
        except Exception:
            return None  # table not migrated yet — never break the request
        if not rule:
            return None
        target = rule.target_path
        # Guard against a redirect loop (source == target, or a rule pointing at
        # its own path). Never 301 to the path we're already on.
        if target.rstrip('/') == pub or target.rstrip('/') == path.rstrip('/'):
            return None
        if on_preview and target.startswith('/'):
            target = '/preview' + target
        return redirect(target, code=301)

    logger.info("Legacy WordPress redirects registered (hosts: %s)", ', '.join(sorted(hosts)))
