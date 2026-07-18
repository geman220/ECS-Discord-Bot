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
    # The Events Calendar archive + tickets -> live calendar
    m['/events'] = ('calendar.calendar_view', {})
    m['/tickets-checkout'] = ('public.home', {})
    m['/tickets-order'] = ('public.home', {})
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

        # 1. Exact static map (posts, categories, events archive, tickets).
        target = _STATIC_MAP.get(norm)
        if target:
            from flask import url_for
            return redirect(url_for(target[0], **target[1]), code=301)

        # 2. Single TEC event pages: /event/<slug> -> /calendar
        if norm.startswith('/event/'):
            from flask import url_for
            return redirect(url_for('calendar.calendar_view'), code=301)

        # 3. TEC venue/organizer taxonomy pages -> /calendar (thin content).
        if norm.startswith('/venue/') or norm.startswith('/organizer'):
            from flask import url_for
            return redirect(url_for('calendar.calendar_view'), code=301)

        return None

    logger.info("Legacy WordPress redirects registered (hosts: %s)", ', '.join(sorted(hosts)))
